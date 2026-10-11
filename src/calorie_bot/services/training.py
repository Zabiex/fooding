"""Training business logic. Pure functions over domain models — no IO here,
which makes every rule in this file trivially unit-testable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..domain.models import (
    Exercise,
    ExerciseDraft,
    ExerciseEntryDraft,
    ExerciseEntry,
    UserProfile,
)

