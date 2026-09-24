from __future__ import annotations

from calendar import monthrange
from datetime import date


def add_months(d: date, months: int) -> date:
    """Calendar months, clamped to the last day of the target month (Jan 31 + 1 = Feb 28)."""
    year, month0 = divmod(d.month - 1 + months, 12)
    year += d.year
    return date(year, month0 + 1, min(d.day, monthrange(year, month0 + 1)[1]))


def age_on(dob: date, on: date) -> int:
    """Completed years. A Feb 29 birthday ticks over on Mar 1 in non-leap years."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))
