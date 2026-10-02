"""Local review records. Turning them into clinical evidence requires an approved policy."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .data import ReportError, Run

FEEDBACK_FIELDS = ("patient_id", "rule_id", "rule_version", "outcome", "date", "evidence_note")
OUTCOMES = ("done_elsewhere", "declined", "not_applicable")


@dataclass(frozen=True)
class Attestation:
    patient_id: str
    rule_id: str
    rule_version: int
    outcome: str
    date: date
    evidence_note: str = ""
    source: str = "attestation"


def _identity(value: str, known: set[str]) -> str:
    # Spreadsheet-safe templates prefix a formula-like id with an apostrophe.
    if value not in known and value.startswith("'") and value[1:] in known:
        return value[1:]
    return value


def validate_feedback(path: str | Path, run: Run, *, as_of: date) -> tuple[Attestation, ...]:
    results = {(r["patient_id"], r["rule_id"]): r for r in run.rows}
    known = {key[0] for key in results}
    entries = []
    seen = set()
    try:
        with Path(path).open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != list(FEEDBACK_FIELDS):
                raise ReportError("Feedback columns don't match schema v1.")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ReportError("Feedback row has missing or extra fields.")
                pid = _identity(row["patient_id"], known)
                key = (pid, row["rule_id"])
                result = results.get(key)
                if result is None or row["rule_version"] != result["rule_version"]:
                    raise ReportError("Feedback doesn't match a result and version in this run.")
                if not any(row[f] for f in ("outcome", "date", "evidence_note")):
                    continue
                if key in seen:
                    raise ReportError("Feedback has duplicate patient/rule entries.")
                if row["outcome"] not in OUTCOMES:
                    raise ReportError("Feedback needs a supported outcome.")
                on = date.fromisoformat(row["date"])
                if on > as_of:
                    raise ReportError("Feedback date is after the validation date.")
                entries.append(Attestation(pid, key[1], int(row["rule_version"]), row["outcome"], on, row["evidence_note"]))
                seen.add(key)
        return tuple(entries)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        if isinstance(error, ReportError):
            raise
        raise ReportError("Couldn't read valid feedback; check its local file and dates.") from None
