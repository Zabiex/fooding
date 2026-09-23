-- =============================================================================
-- Calorie & recipe tracker — Supabase / PostgreSQL schema
--
-- The whole DDL lives inside public.initialize_nutrition_schema() so it can be
-- called idempotently from application startup, from a migration runner, or
-- straight from the Supabase SQL editor:
--
--     select public.initialize_nutrition_schema();
--
-- Everything is "if not exists" guarded, so running it twice is a no-op.
-- =============================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists pg_trgm;    -- fuzzy recipe name search


-- -----------------------------------------------------------------------------
-- Trigger helper: keep updated_at honest
-- -----------------------------------------------------------------------------
create or replace function public.tg_set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;


-- -----------------------------------------------------------------------------
-- Main initializer
-- -----------------------------------------------------------------------------
create or replace function public.initialize_nutrition_schema()
returns void
language plpgsql
as $init$
begin
    ---------------------------------------------------------------------------
    -- Enum types
    ---------------------------------------------------------------------------
    if not exists (select 1 from pg_type where typname = 'meal_type') then
        create type public.meal_type as enum (
            'breakfast', 'lunch', 'dinner', 'snack', 'drink', 'other'
        );
    end if;

    if not exists (select 1 from pg_type where typname = 'entry_source') then
        create type public.entry_source as enum (
            'text', 'photo', 'recipe', 'manual'
        );
    end if;

    ---------------------------------------------------------------------------
    -- users
    --
    -- telegram_user_id is the natural key coming from the bot. It is the only
    -- identity the bot ever trusts; the LLM never sees it and never supplies it.
    ---------------------------------------------------------------------------
    create table if not exists public.users (
        id                    uuid primary key default gen_random_uuid(),
        telegram_user_id      bigint      not null unique,
        telegram_chat_id      bigint,
        username              text,
        first_name            text,
        locale                text        not null default 'en',
        timezone              text        not null default 'UTC',
        daily_calorie_target  integer     check (daily_calorie_target is null or daily_calorie_target > 0),
        protein_target_g      real        check (protein_target_g   is null or protein_target_g   >= 0),
        carbs_target_g        real        check (carbs_target_g     is null or carbs_target_g     >= 0),
        fat_target_g          real        check (fat_target_g       is null or fat_target_g       >= 0),
        whitelist             boolean     not null default false,
        is_active             boolean     not null default true,
        created_at            timestamptz not null default now(),
        updated_at            timestamptz not null default now()
    );

    alter table public.users
        add column if not exists whitelist boolean not null default false;

    create index if not exists users_telegram_user_id_idx
        on public.users (telegram_user_id);

    ---------------------------------------------------------------------------
    -- recipes
    --
    -- Nutrition is stored per serving; ingredients are a jsonb array so the
    -- agent can round-trip structured ingredient data without a join table.
    ---------------------------------------------------------------------------
    create table if not exists public.recipes (
        id                  uuid primary key default gen_random_uuid(),
        user_id             uuid        not null references public.users (id) on delete cascade,
        name                text        not null check (length(btrim(name)) > 0),
        description         text,
        servings            double precision not null default 1 check (servings > 0),
        ingredients         jsonb       not null default '[]'::jsonb,
        calories            double precision not null check (calories >= 0),   -- per serving
        protein_g           double precision not null default 0 check (protein_g >= 0),
        carbs_g             double precision not null default 0 check (carbs_g   >= 0),
        fat_g               double precision not null default 0 check (fat_g     >= 0),
        fiber_g             double precision not null default 0 check (fiber_g   >= 0),
        tags                text[]      not null default '{}',
        is_archived         boolean     not null default false,
        created_at          timestamptz not null default now(),
        updated_at          timestamptz not null default now()
    );

    -- One recipe name per user (case-insensitive). Different users may reuse names.
    create unique index if not exists recipes_user_name_uniq
        on public.recipes (user_id, lower(btrim(name)));

    create index if not exists recipes_user_id_idx
        on public.recipes (user_id) where is_archived = false;

    create index if not exists recipes_name_trgm_idx
        on public.recipes using gin (name gin_trgm_ops);

    ---------------------------------------------------------------------------
    -- log_entries
    --
    -- Nutrition here is the TOTAL for the entry (already multiplied by
    -- servings), so daily aggregation is a plain sum with no joins.
    ---------------------------------------------------------------------------
    create table if not exists public.log_entries (
        id            uuid primary key default gen_random_uuid(),
        user_id       uuid        not null references public.users (id)   on delete cascade,
        recipe_id     uuid                 references public.recipes (id) on delete set null,
        description   text        not null check (length(btrim(description)) > 0),
        meal_type     public.meal_type    not null default 'other',
        source        public.entry_source not null default 'text',
        servings      double precision not null default 1 check (servings > 0),
        calories      double precision not null check (calories >= 0),
        protein_g     double precision not null default 0 check (protein_g >= 0),
        carbs_g       double precision not null default 0 check (carbs_g   >= 0),
        fat_g         double precision not null default 0 check (fat_g     >= 0),
        fiber_g       double precision not null default 0 check (fiber_g   >= 0),
        confidence    real        check (confidence is null or (confidence >= 0 and confidence <= 1)),
        raw_input     text,
        logged_at     timestamptz not null default now(),
        created_at    timestamptz not null default now()
    );

    -- The access pattern is always "this user, this time window".
    create index if not exists log_entries_user_logged_at_idx
        on public.log_entries (user_id, logged_at desc);

    create index if not exists log_entries_recipe_id_idx
        on public.log_entries (recipe_id) where recipe_id is not null;

    ---------------------------------------------------------------------------
    -- updated_at triggers
    ---------------------------------------------------------------------------
    if not exists (select 1 from pg_trigger where tgname = 'users_set_updated_at') then
        create trigger users_set_updated_at
            before update on public.users
            for each row execute function public.tg_set_updated_at();
    end if;

    if not exists (select 1 from pg_trigger where tgname = 'recipes_set_updated_at') then
        create trigger recipes_set_updated_at
            before update on public.recipes
            for each row execute function public.tg_set_updated_at();
    end if;

    ---------------------------------------------------------------------------
    -- Row level security
    --
    -- The bot connects with the service role / direct Postgres credentials,
    -- which BYPASSES RLS. Enabling it with no permissive policy means the
    -- anon and authenticated Supabase API keys can read nothing at all --
    -- a safe default if you ever expose these tables through PostgREST.
    -- Tenant isolation for the bot itself is enforced in the repository layer
    -- (every statement is scoped by user_id) and by the fact that the agent
    -- never receives a user_id parameter it could tamper with.
    ---------------------------------------------------------------------------
    alter table public.users       enable row level security;
    alter table public.recipes     enable row level security;
    alter table public.log_entries enable row level security;
end;
$init$;


-- Run the initializer first so the tables exist, then create reporting helpers
-- that reference those tables. Creating the SQL-language functions requires
-- the referenced relations to be present at creation time.
select public.initialize_nutrition_schema();


-- -----------------------------------------------------------------------------
-- Reporting helpers (handy in the Supabase SQL editor / dashboards).
-- The bot computes day boundaries in Python using the user's timezone, but
-- these give you the same numbers ad hoc.
-- -----------------------------------------------------------------------------
create or replace function public.daily_totals(
    p_user_id  uuid,
    p_day      date,
    p_timezone text default 'UTC'
)
returns table (
    calories    double precision,
    protein_g   double precision,
    carbs_g     double precision,
    fat_g       double precision,
    fiber_g     double precision,
    entry_count bigint
)
language sql
stable
as $$
    select
        coalesce(sum(l.calories),  0)::double precision,
        coalesce(sum(l.protein_g), 0)::double precision,
        coalesce(sum(l.carbs_g),   0)::double precision,
        coalesce(sum(l.fat_g),     0)::double precision,
        coalesce(sum(l.fiber_g),   0)::double precision,
        count(*)
    from public.log_entries l
    where l.user_id = p_user_id
      and (l.logged_at at time zone p_timezone)::date = p_day;
$$;


create or replace function public.daily_totals_by_meal(
    p_user_id  uuid,
    p_day      date,
    p_timezone text default 'UTC'
)
returns table (
    meal_type   public.meal_type,
    calories    double precision,
    protein_g   double precision,
    carbs_g     double precision,
    fat_g       double precision,
    fiber_g     double precision,
    entry_count bigint
)
language sql
stable
as $$
    select
        l.meal_type,
        sum(l.calories)::double precision,
        sum(l.protein_g)::double precision,
        sum(l.carbs_g)::double precision,
        sum(l.fat_g)::double precision,
        sum(l.fiber_g)::double precision,
        count(*)
    from public.log_entries l
    where l.user_id = p_user_id
      and (l.logged_at at time zone p_timezone)::date = p_day
    group by l.meal_type
    order by l.meal_type;
$$;
