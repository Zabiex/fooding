"""Short-term conversation memory, keyed by Telegram user id.

Kept in process and intentionally small: it exists so "make that two servings"
resolves against the previous turn, not so the bot remembers you for a week.
Long-term memory is the database. Swap this class for a Redis-backed one if you
run more than a single bot process.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage


@dataclass
class _Entry:
    messages: list[ModelMessage] = field(default_factory=list)
    touched_at: float = field(default_factory=time.monotonic)


class ConversationStore:
    def __init__(
        self,
        *,
        max_turns: int = 12,
        ttl_seconds: int = 1800,
        max_users: int = 5000,
    ) -> None:
        self._max_turns = max_turns
        self._ttl = ttl_seconds
        self._max_users = max_users
        self._store: "OrderedDict[int, _Entry]" = OrderedDict()

    def get(self, telegram_user_id: int) -> list[ModelMessage]:
        entry = self._store.get(telegram_user_id)
        if entry is None:
            return []
        if time.monotonic() - entry.touched_at > self._ttl:
            self._store.pop(telegram_user_id, None)
            return []
        self._store.move_to_end(telegram_user_id)
        return list(entry.messages)

    def extend(self, telegram_user_id: int, new_messages: list[ModelMessage]) -> None:
        entry = self._store.get(telegram_user_id) or _Entry()
        entry.messages = (entry.messages + list(new_messages))[-self._max_turns * 2 :]
        entry.touched_at = time.monotonic()
        self._store[telegram_user_id] = entry
        self._store.move_to_end(telegram_user_id)
        self._evict()

    def clear(self, telegram_user_id: int) -> None:
        self._store.pop(telegram_user_id, None)

    def _evict(self) -> None:
        now = time.monotonic()
        stale = [key for key, entry in self._store.items() if now - entry.touched_at > self._ttl]
        for key in stale:
            self._store.pop(key, None)
        while len(self._store) > self._max_users:
            self._store.popitem(last=False)
