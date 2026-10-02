"""Queue routing is operational; it doesn't change a clinical result."""
from __future__ import annotations

from .data import Run
from ..engine.states import GAP_STATES

OPEN = frozenset(s.value for s in GAP_STATES)
LISTS = (
    "physician_review", "moa_book", "patient_self_refer", "physician_order",
    "physician_record", "unknown_tasks", "previsit_discuss", "outreach",
)
ROUTES = {
    "book": "moa_book", "self_refer": "patient_self_refer", "order": "physician_order",
    "review": "physician_review", "record": "physician_record",
}
FIELDS = (
    "patient_id", "rule_id", "rule_version", "rule_title", "category", "rule_status",
    "state", "due_date", "evidence_ids", "searched_sources", "missing_inputs", "reason",
    "action_kind", "action_note", "cohort_group", "task",
)


def worklists(run: Run) -> dict[str, list[dict[str, str]]]:
    lists: dict[str, list[dict[str, str]]] = {name: [] for name in LISTS}
    for original in run.rows:
        row = {**original, "task": ""}
        if row["state"] == "UNKNOWN":
            name = "unknown_tasks"
            missing = row["missing_inputs"]
            row["task"] = "record " + missing if missing and "not walked:" not in missing else (
                missing or "review missing inputs"
            )
        elif row["state"] == "DISCUSS":
            name = "previsit_discuss"
            row["task"] = "discuss at a visit; never recall"
        elif row["state"] in OPEN:
            name = "physician_review" if row["category"] == "B" else ROUTES.get(row["action_kind"], "physician_review")
            row["task"] = row["action_note"] or "review rule action"
        else:
            continue
        lists[name].append(row)
    for patient in run.cohort:
        if patient["cohort_group"] == "outreach":
            row = dict.fromkeys(FIELDS, "")
            row.update(patient, state="OUTREACH", action_kind="review", task="review outreach eligibility")
            lists["outreach"].append(row)
    for rows in lists.values():
        rows.sort(key=lambda r: (r["category"] != "B", r["due_date"] or "9999-12-31", r["rule_id"], r["patient_id"]))
    return lists
