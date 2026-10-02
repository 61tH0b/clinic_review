"""Missing evaluations aren't evidence that a gap closed."""
from __future__ import annotations

from dataclasses import dataclass

from .data import ReportError, Run
from .worklists import OPEN

CHANGES = ("newly_open", "closed", "still_open", "changed_state", "added", "removed")
DIFF_FIELDS = (
    "patient_id", "rule_id", "before_title", "after_title", "before_version", "after_version",
    "before_rule_status", "after_rule_status", "before_state", "after_state",
    "before_cohort", "after_cohort", "before_due_date", "after_due_date",
    "before_evidence_ids", "after_evidence_ids", "before_action_kind", "after_action_kind",
    "before_action_note", "after_action_note", "changes",
)


@dataclass(frozen=True)
class RunDiff:
    rows: tuple[dict[str, str], ...]
    counts: dict[str, dict[str, int]]
    ruleset_changed: bool


def compare_runs(before: Run, after: Run) -> RunDiff:
    if before.as_of > after.as_of:
        raise ReportError("Before run is dated after the after run.")
    old = {(r["patient_id"], r["rule_id"]): r for r in before.rows}
    new = {(r["patient_id"], r["rule_id"]): r for r in after.rows}
    old_groups = {r["patient_id"]: r["cohort_group"] for r in before.cohort}
    new_groups = {r["patient_id"]: r["cohort_group"] for r in after.cohort}
    rows = []
    counts: dict[str, dict[str, int]] = {}
    for key in sorted(old.keys() | new.keys(), key=lambda k: (k[1], k[0])):
        left, right = old.get(key), new.get(key)
        changes = []
        if left is None:
            changes.append("added")
        elif right is None:
            changes.append("removed")
        else:
            was_open, is_open = left["state"] in OPEN, right["state"] in OPEN
            if is_open and not was_open:
                changes.append("newly_open")
            if was_open and not is_open:
                changes.append("closed")
            if was_open and is_open:
                changes.append("still_open")
            if left["state"] != right["state"]:
                changes.append("changed_state")
        totals = counts.setdefault(key[1], dict.fromkeys(CHANGES, 0))
        for change in changes:
            totals[change] += 1
        row = dict.fromkeys(DIFF_FIELDS, "")
        row.update(patient_id=key[0], rule_id=key[1], changes=" ".join(changes) or "unchanged")
        for prefix, source, groups in (("before", left, old_groups), ("after", right, new_groups)):
            row[f"{prefix}_state"] = source["state"] if source else "NOT_EVALUATED"
            row[f"{prefix}_cohort"] = groups.get(key[0], "NOT_IN_RUN")
            for target, field in (("title", "rule_title"), ("version", "rule_version"),
                                  ("rule_status", "rule_status"), ("due_date", "due_date"),
                                  ("evidence_ids", "evidence_ids"), ("action_kind", "action_kind"),
                                  ("action_note", "action_note")):
                row[f"{prefix}_{target}"] = source[field] if source else ""
        rows.append(row)
    return RunDiff(tuple(rows), counts, before.ruleset != after.ruleset)
