"""Evidence states. PLAN.md section 6.3 has what each one means for the queue."""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    UP_TO_DATE = "UP_TO_DATE"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    NOT_FOUND = "NOT_FOUND"
    EXCLUDED = "EXCLUDED"
    DECLINED = "DECLINED"
    DISCUSS = "DISCUSS"
    UNKNOWN = "UNKNOWN"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


# States that ask someone to act. Only these get downgraded to UNKNOWN when a screen the
# rule depends on wasn't walked, since a newer result could be sitting on that screen.
GAP_STATES = frozenset({State.DUE_SOON, State.OVERDUE, State.NOT_FOUND})
