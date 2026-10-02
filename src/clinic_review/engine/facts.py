"""What the evaluator reads: one patient's normalized facts.

Facts come from the concept layer (valuesets/) applied to walker captures and model
extractions. The evaluator never sees raw EMR data, only concept names, dates, and values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fact:
    concept: str  # e.g. "obs.fit", "proc.colonoscopy", "dx.diabetes"
    date: date | None = None
    value: str | None = None  # normalized result, e.g. "positive", "negative", "4"
    # A due date printed on the report itself. The cervix screening lab prints one, and
    # rules that set use_reported_next_due trust it over a computed interval.
    next_due: date | None = None
    id: str = ""  # evidence id pointing back to the capture or extraction
    source: str = ""  # evidence source it came from, e.g. "labs"


@dataclass(frozen=True)
class Patient:
    id: str
    dob: date | None
    sex_at_birth: str | None  # "F", "M", or None when not recorded
    facts: tuple[Fact, ...]
    # Evidence sources the walker actually read for this patient. A rule that depends on a
    # source outside this set can't call anything a gap (see evaluate.py).
    searched: frozenset[str]
