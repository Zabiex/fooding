"""Dependencies handed to the agent at run time.

The critical property: `user` is resolved from the Telegram update *before* the
model is invoked, and tools read it from `ctx.deps`. No tool signature exposes
`user_id`, so the model has no parameter through which it could reach another
tenant's rows — prompt injection in a photo caption cannot widen the scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..db.repositories import Repositories
from ..domain.models import EntrySource, UserProfile
from ..services.timeframes import local_now


@dataclass
class AgentDeps:
    user: UserProfile
    repos: Repositories
    #: Where this turn came from, so logged entries are tagged text vs photo.
    input_source: EntrySource = EntrySource.TEXT

    @property
    def user_id(self):  # noqa: ANN201 - UUID, kept implicit for brevity
        return self.user.id

    @property
    def timezone(self) -> str:
        return self.user.timezone

    def now_local(self) -> datetime:
        return local_now(self.user.timezone)
