# Calorie & recipe tracker — Telegram + PydanticAI + Supabase

A multi-user food diary. People describe a meal or send a photo of their plate;
Gemini 1.5 Flash estimates the nutrition and writes it to Postgres, scoped to
the sender's Telegram user ID.

## Layout

```
src/calorie_bot/
├── config.py                 Settings (the only module that reads the environment)
├── domain/models.py          Pure Pydantic data structures — no IO, no framework
├── services/
│   ├── nutrition.py          Aggregation, scaling, macro sanity checks (pure)
│   └── timeframes.py         UTC <-> local-day conversion (pure)
├── db/
│   ├── schema.sql            initialize_nutrition_schema() + reporting functions
│   ├── schema.py             Ships and runs the SQL, under an advisory lock
│   ├── pool.py               asyncpg pool, tuned for Supabase poolers
│   └── repositories.py       All SQL. Every query scoped by user_id
├── agent/
│   ├── dependencies.py       AgentDeps: the resolved user + repositories
│   ├── prompts.py            All prompt text
│   ├── tools.py              create_recipe, log_meal, get_daily_summary, find_recipe
│   ├── nutrition_agent.py    Model + Agent wiring
│   ├── history.py            Per-user short-term conversation memory
│   └── runner.py             Deps assembly, locking, timeouts, photo prompts
└── bot/
    ├── handlers.py           Telegram handlers (auth, download, dispatch)
    ├── formatting.py         HTML rendering
    └── app.py                Composition root
```

Dependencies point one way only: `bot → agent → services → domain`, with `db`
depending on `domain` and `services`. `domain/` imports nothing from the project;
`services/` does no IO. You can swap Telegram for a web API by writing a new
`bot/`, or swap Gemini for another provider by editing `build_model` alone.

## Setup

Recommended: use `uv` for fast, reproducible environments and installs.

```bash
# Install uv (one-time)
pipx install uv

# Create a virtual environment and install pinned requirements
uv venv                # creates .venv and prints activation instructions
uv pip sync requirements.txt

# Install the editable package so `calorie_bot` is importable (optional)
uv pip install -e .

# Copy the example env and fill the secrets
cp .env.example .env

# Initialize the DB (optional; startup will do this if enabled)
uv run scripts/init_db.py

# Run the bot locally
uv run python main.py
```



You need a bot token from [@BotFather](https://t.me/botfather), a Gemini API key
from [aistudio.google.com](https://aistudio.google.com), and the Supabase
connection URI from *Project Settings → Database*.

**Which Supabase port:** the session pooler (5432) suits a long-lived `asyncpg`
pool. If you use the transaction pooler (6543), leave
`DB_STATEMENT_CACHE_SIZE=0` — it cannot hold server-side prepared statements.

## The schema

`schema.sql` puts the whole DDL inside `public.initialize_nutrition_schema()`,
guarded with `if not exists`, so it is safe to run on every boot. Run it from
the Supabase SQL editor with:

```sql
select public.initialize_nutrition_schema();
```

Three tables: `users` (keyed on `telegram_user_id`), `recipes` (nutrition stored
**per serving**, ingredients as `jsonb`), and `log_entries` (nutrition stored as
the **total** for the entry, so daily rollups are a plain `sum` with no joins,
served by the `(user_id, logged_at desc)` index).

Two helper functions, `daily_totals` and `daily_totals_by_meal`, give you the
same numbers ad hoc in the SQL editor.

## How tenant isolation works

Three independent layers, in order of importance:

1. **The agent has no user parameter.** Tool signatures expose `name`,
   `calories_per_serving`, `servings` — never `user_id`. The identity comes from
   `update.effective_user.id`, is resolved to a row before the model runs, and
   travels in `ctx.deps`. There is no argument the model could be persuaded to
   fill in with someone else's id.
2. **Every repository method is scoped.** `recipes.get(user_id, recipe_id)`
   returns `None` for a recipe belonging to someone else, which is why
   `log_meal` raises `ModelRetry` rather than logging a foreign recipe. There is
   no unscoped query in `repositories.py` to call by mistake.
3. **RLS is on with no permissive policy.** The bot connects with credentials
   that bypass RLS, but if these tables are ever exposed through PostgREST, the
   `anon` and `authenticated` keys read nothing. Add policies deliberately when
   you build a web client.

Prompt injection is treated as a given: instructions inside a photo caption or a
pasted recipe can at most make the agent log nonsense **into the sender's own
diary**, because the blast radius is bounded by the deps, not by the prompt.

## Notes on the agent

- **Per-serving everywhere.** Both `create_recipe` and `log_meal` take
  per-serving numbers plus a `servings` multiplier. Models are markedly better at
  "one serving is 420 kcal, they ate two" than at multiplying in their head.
- **Macro arithmetic is checked, not trusted.** `macros_are_consistent` compares
  stated calories against 4/4/9 kcal per gram and raises `ModelRetry` on a
  mismatch, so the model corrects itself instead of persisting an entry claiming
  100 kcal and 90 g of fat.
- **Flat scalar tool arguments.** Gemini's function-calling schema support is
  happiest with shallow signatures, so the macros are separate floats rather than
  a nested `Nutrition` object. `ingredients` is the one nested structure.
- **Photos never enter the history.** `_strip_binary` swaps image parts for a
  placeholder before storing the turn; otherwise every later message re-uploads
  the picture.
- **One run per user at a time.** `AgentRunner` holds a per-user `asyncio.Lock`,
  so two quick messages queue instead of racing on the same day's totals, while
  `concurrent_updates(True)` keeps different users fully parallel.

Conversation history lives in process. Running more than one replica means
either sticky routing or moving `ConversationStore` behind Redis — the class is
small and its interface is three methods.

## Testing

```bash
pip install pytest pytest-asyncio
pytest -q
```

`tests/test_tools.py` exercises the tools with a stub `ctx` and in-memory fakes —
no model call and no database — including the case where the agent is handed
another user's recipe id.

## Caveats worth knowing before you ship

- Calorie estimates from a photo are rough. Portion size, oil and sauces are the
  usual sources of error; the prompt tells the model to say so and to set a low
  `confidence`.
- The bot talks about food intake, which is sensitive territory. The system
  prompt steers away from prescriptive numeric plans and toward a professional
  when a conversation heads that way — worth reviewing against your own duty of
  care before launch.
- There is no rate limiting per user beyond the lock. Add
  `python-telegram-bot`'s `AIORateLimiter` and a per-user quota before opening it
  up publicly, since every message costs a Gemini call.
