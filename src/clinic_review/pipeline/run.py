"""One evaluation run: every roster patient through cohort, concept layer, and rules.

    captures (sweep) -> read_chart -> cohort -> concept layer + derived -> every rule -> ledger

Deterministic for a given store, sweep, as-of date, and ruleset. Only the active cohort
(PLAN section 4) gets rule results; the rest are counted by group.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from ..concepts.layer import ConceptLayer
from ..engine.dates import add_months
from ..engine.evaluate import evaluate
from ..engine.facts import Patient
from ..engine.rules import Rule
from ..facts.chart import Chart, read_chart
from ..facts.mapping import FactsMapping
from ..store.ledger import Ledger
from ..store.raw_store import RawStore

ACTIVITY_MONTHS = 36


def ruleset_digest(*directories: str | Path) -> str:
    """Hash of every rule and value set file, so runs can say whether the logic changed."""
    h = hashlib.sha256()
    for directory in directories:
        for path in sorted(Path(directory).glob("*.yaml")):
            h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def cohort(chart: Chart, mapping: FactsMapping, as_of: date) -> tuple[str, str]:
    """(group, reason). Groups: active, outreach, excluded, not_walked."""
    if not chart.searched:
        return "not_walked", "no screen loaded in this sweep"
    if mapping.patient.status is not None and chart.status not in mapping.patient.include_statuses:
        return "excluded", f"status {chart.status or 'not recorded'}"
    if chart.last_visit is None:
        return "outreach", "no visit recorded"
    if chart.last_visit < add_months(as_of, -ACTIVITY_MONTHS):
        return "outreach", f"not seen in {ACTIVITY_MONTHS} months"
    return "active", f"seen in the last {ACTIVITY_MONTHS} months"


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    sweep: str
    as_of: date
    ruleset: str
    patients: int


def evaluate_panel(
    store: RawStore,
    ledger: Ledger,
    mapping: FactsMapping,
    layer: ConceptLayer,
    rules: dict[str, Rule],
    *,
    sweep: str,
    as_of: date,
    ruleset: str,
    cohort_only: bool = False,
) -> RunSummary:
    run_id = f"eval-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    ledger.start(run_id, sweep, as_of.isoformat(), ruleset)
    patients = 0
    for chr_id in store.roster_ids():
        patients += 1
        chart = read_chart(store, mapping, chr_id, sweep)
        group, reason = cohort(chart, mapping, as_of)
        if group != "active" or cohort_only:
            ledger.add_patient(run_id, chr_id, group, reason, skips=chart.issues)
            continue
        resolved = layer.facts_for(chart.observations, as_of)
        patient = Patient(chr_id, chart.dob, chart.sex_at_birth, resolved.facts, chart.searched)
        results = [evaluate(rule, patient, as_of) for rule in rules.values()]
        ledger.add_patient(run_id, chr_id, group, reason, results=results, skips=chart.issues + resolved.skipped)
    ledger.finish(run_id)
    return RunSummary(run_id, sweep, as_of, ruleset, patients)
