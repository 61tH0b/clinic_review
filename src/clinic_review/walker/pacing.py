"""Human-paced timing and the off-hours window."""
from __future__ import annotations

import random
from datetime import datetime, time

from .profile import Pacing


def in_window(now: datetime, start: time | None, end: time | None) -> bool:
    """True when `now` falls inside [start, end). The window may cross midnight."""
    if start is None or end is None:
        return True
    t = now.time()
    if start == end:
        return True
    if start < end:
        return start <= t < end
    return t >= start or t < end


def pause_seconds(pacing: Pacing, rng: random.Random) -> float:
    return rng.uniform(pacing.min_seconds, pacing.max_seconds)
