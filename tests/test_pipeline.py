"""Fact store, cohort, and evaluation runs. Synthetic patients only."""
from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from clinic_review.concepts import ConceptLayer
from clinic_review.engine import load_rules
from clinic_review.facts import MappingError, load_mapping, parse_mapping, read_chart
from clinic_review.facts.chart import get_path, parse_date
from clinic_review.pipeline import cohort, evaluate_panel, ruleset_digest
from clinic_review.pipeline.__main__ import main as pipeline_main
from clinic_review.store import raw_store
from clinic_review.store.ledger import Ledger

from conftest import TEST_KEY
from fake_emr import PATIENT_IDS

ROOT = Path(__file__).resolve().parent.parent
MAPPING_PATH = ROOT / "tests" / "fixtures" / "fake_emr" / "facts.yaml"
MAPPING = load_mapping(MAPPING_PATH)
LAYER = ConceptLayer.load(ROOT / "valuesets")
RULES = load_rules(ROOT / "rules")
AS_OF = date(2026, 10, 2)
WALK_TIME = "2026-10-02T03:00:00+00:00"


@pytest.fixture
def frozen_walk(monkeypatch):
    """Captures dated on the as-of day, so 'seen' medication dates never drift into the future."""
    monkeypatch.setattr(raw_store, "_now", lambda: WALK_TIME)


def put(store, run_id, chr_id, screen, path, doc, outcome="ok", sweep="current"):
    if not store._db.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone():
        store.start_run(run_id, "charts", sweep, "fake-emr")
    if outcome == "ok":
        store.add_capture(
            run_id=run_id, chr_id=chr_id, screen=screen, url=f"http://emr{path}", status=200,
            content_type="application/json", body=json.dumps(doc).encode(),
        )
    store.audit(run_id=run_id, chr_id=chr_id, screen=screen, started_at=WALK_TIME, kept=1, dropped=0, outcome=outcome)


SUMMARY = {"patient_id": "9", "status": "active", "sex": "F", "dob": "1968-04-02", "last_visit": "2026-08-01"}


# --- mapping -------------------------------------------------------------------------


def _mapping() -> dict:
    return yaml.safe_load(MAPPING_PATH.read_text())


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda m: m["screens"]["labs"]["rows"][0].pop("lab_name"), "needs at least one of text, code, lab_name"),
        (lambda m: m["screens"]["problems"]["rows"][0].pop("source"), "name a source"),
        (lambda m: m["screens"]["labs"]["rows"][0].update(source="vitals"), "isn't in the screen's sources"),
        (lambda m: m["screens"]["labs"].update(sources=["chart"]), "isn't an evidence source"),
        (lambda m: m["patient"].update(screen="nope"), "isn't one of the screens"),
        (lambda m: m["patient"].update(sex_values={"F": "female"}), "map each EMR value to F or M"),
        (lambda m: m["patient"].pop("include_statuses"), "status and include_statuses go together"),
        (lambda m: m["screens"]["labs"]["rows"][0].update(date=["a", "b"]), "only text can join"),
    ],
)
def test_bad_mappings_are_rejected(change, message):
    m = _mapping()
    change(m)
    with pytest.raises(MappingError, match=message):
        parse_mapping(m)


def test_helpers():
    assert get_path({"a": {"b": [{"c": 1}]}}, "a.b.0.c") == 1
    assert get_path({"a": 1}, "a.b") is None
    assert parse_date("2026-03-01T10:00:00Z", None) == date(2026, 3, 1)
    assert parse_date("01/03/2026", "%d/%m/%Y") == date(2026, 3, 1)
    assert parse_date("March 1", None) is None


# --- reading charts ------------------------------------------------------------------


def test_read_chart(store):
    put(store, "r1", "9", "summary", "/api/patients/9", SUMMARY)
    put(store, "r1", "9", "files", "/api/patients/9/files", {"files": [
        {"file_id": "D1", "tag": "Consults", "title": "Retinal exam", "date": "2026-01-02"},
        {"file_id": "D2", "tag": "Mystery tag", "title": "Mammogram", "date": "2026-01-02"},
        {"file_id": "D3", "tag": "Diagnostic Imaging", "title": "Mammogram", "date": "Jan 2 2026"},
    ]})
    chart = read_chart(store, MAPPING, "9", "current")
    assert (chart.dob, chart.sex_at_birth, chart.status, chart.last_visit) == (date(1968, 4, 2), "F", "active", date(2026, 8, 1))
    assert chart.searched == frozenset(MAPPING.screens["summary"].sources + MAPPING.screens["files"].sources)
    [retinal, mammo] = chart.observations
    assert (retinal.id, retinal.source, retinal.text, retinal.date) == ("files:D1", "documents.consults", "Retinal exam", date(2026, 1, 2))
    assert (mammo.id, mammo.date) == ("files:D3", None)
    assert [s.reason for s in chart.issues] == [
        "files: tag value isn't in source_values",
        "files: date didn't parse",
    ]


def test_latest_run_per_screen_wins(store):
    put(store, "r1", "9", "labs", "/api/patients/9/labs", {"results": [{"id": "OLD", "name": "FIT", "value": "Negative", "collected": "2020-01-01"}]})
    put(store, "r2", "9", "labs", "/api/patients/9/labs", {"results": [{"id": "NEW", "name": "FIT", "value": "Negative", "collected": "2026-01-01"}]})
    put(store, "r0", "9", "labs", "/api/patients/9/labs", {"results": [{"id": "OTHER", "name": "FIT"}]}, sweep="last-year")
    assert [o.id for o in read_chart(store, MAPPING, "9", "current").observations] == ["labs:NEW"]
    assert [o.id for o in read_chart(store, MAPPING, "9", "last-year").observations] == ["labs:OTHER"]


def test_a_failed_screen_isnt_searched(store):
    put(store, "r1", "9", "summary", "/api/patients/9", SUMMARY)
    put(store, "r1", "9", "files", "/api/patients/9/files", {}, outcome="failed")
    chart = read_chart(store, MAPPING, "9", "current")
    assert "documents.consults" not in chart.searched


# --- cohort --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "summary, group",
    [
        (SUMMARY, "active"),
        ({**SUMMARY, "last_visit": "2023-10-01"}, "outreach"),  # one day past 36 months
        ({**SUMMARY, "last_visit": "2023-10-02"}, "active"),
        ({**SUMMARY, "last_visit": None}, "outreach"),
        ({**SUMMARY, "status": "Deceased"}, "excluded"),
    ],
)
def test_cohort(store, summary, group):
    put(store, "r1", "9", "summary", "/api/patients/9", summary)
    assert cohort(read_chart(store, MAPPING, "9", "current"), MAPPING, AS_OF)[0] == group


def test_unwalked_patient(store):
    store.upsert_roster(["9"])
    assert cohort(read_chart(store, MAPPING, "9", "current"), MAPPING, AS_OF) == ("not_walked", "no screen loaded in this sweep")


def test_ruleset_digest_changes_with_any_rule(tmp_path):
    (tmp_path / "a.yaml").write_text("x: 1")
    before = ruleset_digest(tmp_path)
    (tmp_path / "a.yaml").write_text("x: 2")
    assert ruleset_digest(tmp_path) != before


# --- the whole path ------------------------------------------------------------------

EXPECTED = {
    ("1001", "dm.eye"): "UP_TO_DATE",
    ("1001", "colon.fit"): "UP_TO_DATE",
    ("1001", "breast.avg.50_74"): "UP_TO_DATE",
    ("1001", "cervix.hpv"): "NOT_FOUND",
    ("1001", "lung.eligibility"): "UNKNOWN",  # no smoking status charted
    ("1002", "colon.loop.fit_positive"): "OVERDUE",
    ("1002", "colon.fit"): "NOT_FOUND",
    ("1002", "lung.eligibility"): "NOT_FOUND",  # ex-smoker, 67, no assessment
    ("1002", "breast.avg.50_74"): "NOT_ELIGIBLE",
    ("1003", "cervix.hpv"): "NOT_ELIGIBLE",  # on adalimumab: the immunocompromised rule's patient
    ("1006", "dm.eye"): "OVERDUE",
    ("1006", "cervix.hpv"): "NOT_ELIGIBLE",
}


@pytest.mark.browser
def test_walk_then_evaluate(cdp_url, profile, store, fake_emr, tmp_path, frozen_walk, monkeypatch, capsys):
    from clinic_review.walker import Walker
    from clinic_review.walker.session import attach

    with attach(cdp_url) as page:
        walker = Walker(page, profile, store)
        assert walker.roster_pass().complete
        assert walker.chart_pass().complete

    ledger = Ledger(store.path)
    run = evaluate_panel(store, ledger, MAPPING, LAYER, RULES, sweep="current", as_of=AS_OF, ruleset="test")
    assert run.patients == len(PATIENT_IDS)
    assert ledger.cohort_counts(run.run_id) == {"active": 4, "outreach": 1, "excluded": 1, "not_walked": 0}
    assert (ledger.group_of(run.run_id, "1004"), ledger.group_of(run.run_id, "1005")) == ("outreach", "excluded")
    got = {key: ledger.state_of(run.run_id, *key) for key in EXPECTED}
    assert got == EXPECTED
    assert ledger.state_of(run.run_id, "1004", "dm.eye") is None  # outreach patients get no rule run
    # 1003's "Seasonal allergies" and "Pelvic ultrasound": on the curation list, not facts
    assert ("no concept matched", 2) in ledger.skip_counts(run.run_id)
    ledger.close()

    # The command line prints aggregates only: never a CHR id
    monkeypatch.setenv("CLINIC_REVIEW_STORE_KEY", base64.b64encode(TEST_KEY).decode())
    capsys.readouterr()
    code = pipeline_main([
        "evaluate", "--mapping", str(MAPPING_PATH), "--store", str(store.path), "--as-of", "2026-10-02",
        "--rules", str(ROOT / "rules"), "--valuesets", str(ROOT / "valuesets"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "cohort: active 4, outreach 1, excluded 1, not_walked 0" in out
    assert "colon.loop.fit_positive: OVERDUE 1, NOT_ELIGIBLE 3" in out
    body = out.split("\n", 1)[1]  # past the header, whose run id and digest are arbitrary hex
    assert not any(pid in body for pid in PATIENT_IDS)
