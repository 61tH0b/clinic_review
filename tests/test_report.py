"""Worklists and diffs from the same synthetic charts as the pipeline suite."""
from __future__ import annotations

import csv
import dataclasses
import html
import json
from datetime import date

import pytest

from clinic_review.engine.evaluate import Result
from clinic_review.engine.states import State
from clinic_review.pipeline import evaluate_panel
from clinic_review.report import (
    ReportError, compare_runs, read_run, validate_feedback, worklists,
    write_diff, write_worklists,
)
from clinic_review.report.__main__ import main
from clinic_review.store.ledger import Ledger
from clinic_review.store import raw_store
from fake_emr import CHARTS, PATIENT_IDS
from test_pipeline import AS_OF, EXPECTED, LAYER, MAPPING, RULES, WALK_TIME, put


@pytest.fixture
def panel(store, monkeypatch):
    monkeypatch.setattr(raw_store, "_now", lambda: WALK_TIME)
    store.upsert_roster(PATIENT_IDS)
    for pid in PATIENT_IDS:
        chart = CHARTS[pid]
        for screen, field in (("summary", None), ("problems", "problems"),
                              ("medications", "medications"), ("labs", "results"), ("files", "files")):
            body = {"patient_id": pid, **chart[screen]} if field is None else {
                "patient_id": pid, field: chart[screen],
            }
            path = f"/api/patients/{pid}" if screen == "summary" else f"/api/patients/{pid}/{screen}"
            put(store, "capture", pid, screen, path, body)
    ledger = Ledger(store.path)
    summary = evaluate_panel(store, ledger, MAPPING, LAYER, RULES,
                             sweep="current", as_of=AS_OF, ruleset="synthetic-digest")
    yield store, ledger, summary
    ledger.close()


def test_synthetic_pipeline_worklists(panel, tmp_path, capsys):
    store, ledger, summary = panel
    assert {key: ledger.state_of(summary.run_id, *key) for key in EXPECTED} == EXPECTED
    run = read_run(store.path, summary.run_id)
    lists = worklists(run)
    assert list(lists)[0] == "physician_review"
    assert {(r["patient_id"], r["rule_id"]) for r in lists["physician_review"]} == {
        ("1002", "colon.loop.fit_positive"),
    }
    assert [(r["patient_id"], r["rule_id"]) for r in lists["moa_book"]] == [("1006", "dm.eye")]
    cervix = next(r for r in lists["patient_self_refer"] if r["patient_id"] == "1001")
    assert "1-877-702-6566" in cervix["action_note"]
    smoking = next(r for r in lists["unknown_tasks"] if r["rule_id"] == "lung.eligibility")
    assert smoking["patient_id"] == "1001" and smoking["task"] == "record smoking history"
    assert [r["patient_id"] for r in lists["outreach"]] == ["1004"]
    assert not any(r["patient_id"] == "1005" for rows in lists.values() for r in rows)
    output = tmp_path / "report"
    counts = write_worklists(run, output)
    assert counts == {name: len(rows) for name, rows in lists.items()}
    assert capsys.readouterr().out == ""
    html = (output / "worklists.html").read_text()
    assert html.index("physician_review") < html.index("moa_book")
    assert "shadow" in html and "not authorization" in html
    assert "http://" not in html and "https://" not in html and "<script" not in html
    with (output / "moa_book.csv").open() as fh:
        row = next(csv.DictReader(fh))
    assert row["due_date"] == "2025-06-01" and row["evidence_ids"] == "files:F1006A"
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / "feedback.csv").stat().st_mode & 0o777 == 0o600


def _manual(ledger, run_id, states, *, digest="one", rules=None, finish=True):
    ledger.start(run_id, "synthetic", AS_OF.isoformat(), digest, rules={"dm.eye": (rules or RULES)["dm.eye"]})
    for pid, state in states.items():
        result = Result(pid, "dm.eye", 1, AS_OF, State(state), reason="synthetic")
        ledger.add_patient(run_id, pid, "active", "synthetic", results=[result])
    if finish:
        ledger.finish(run_id)


def test_diff_transitions_and_absent_evaluations(panel, tmp_path):
    store, ledger, _ = panel
    before = {"new": "UP_TO_DATE", "closed": "OVERDUE", "still": "NOT_FOUND",
              "unknown": "UNKNOWN", "removed": "NOT_FOUND", "stable": "UP_TO_DATE"}
    after = {"new": "NOT_FOUND", "closed": "UP_TO_DATE", "still": "OVERDUE",
             "unknown": "UP_TO_DATE", "added": "NOT_FOUND", "stable": "UP_TO_DATE"}
    _manual(ledger, "before", before)
    _manual(ledger, "after", after, digest="two")
    old, new = read_run(store.path, "before"), read_run(store.path, "after")
    diff = compare_runs(old, new)
    assert diff.ruleset_changed
    assert diff.counts["dm.eye"] == dict(newly_open=1, closed=1, still_open=1,
                                       changed_state=4, added=1, removed=1)
    rows = {r["patient_id"]: r for r in diff.rows}
    assert rows["still"]["changes"] == "still_open changed_state"
    assert rows["removed"]["changes"] == "removed"
    assert rows["removed"]["after_state"] == "NOT_EVALUATED"
    assert rows["added"]["changes"] == "added"
    write_diff(old, new, tmp_path / "diff")
    document = (tmp_path / "diff" / "diff.html").read_text()
    assert "different ruleset digests" in document
    assert "doesn't prove completed care" in html.unescape(document)


@pytest.mark.parametrize("before,after", [
    ("OVERDUE", "UNKNOWN"), ("NOT_FOUND", "NOT_ELIGIBLE"),
    ("DUE_SOON", "DECLINED"), ("NOT_FOUND", "DISCUSS"),
])
def test_left_open_set_isnt_proof_of_care(panel, before, after):
    store, ledger, _ = panel
    _manual(ledger, "before", {"p": before})
    _manual(ledger, "after", {"p": after})
    diff = compare_runs(read_run(store.path, "before"), read_run(store.path, "after"))
    assert diff.counts["dm.eye"]["closed"] == 1
    assert diff.rows[0]["after_state"] == after


def test_snapshots_dont_follow_later_rule_edits(panel):
    store, ledger, summary = panel
    changed = {**RULES, "dm.eye": dataclasses.replace(RULES["dm.eye"], title="Changed",
                                                    action={"kind": "order", "note": "new"})}
    _manual(ledger, "later", {"p": "NOT_FOUND"}, rules=changed)
    first = read_run(store.path, summary.run_id)
    row = next(r for r in first.rows if r["rule_id"] == "dm.eye")
    assert row["rule_title"] == "Diabetic retinal exam" and row["action_kind"] == "book"
    assert read_run(store.path, "later").rows[0]["rule_title"] == "Changed"


@pytest.mark.parametrize("kind", ["order", "review", "record", "self_refer", "book"])
def test_action_audiences_and_discuss_separation(panel, kind):
    store, ledger, _ = panel
    rules = {**RULES, "dm.eye": dataclasses.replace(RULES["dm.eye"], action={"kind": kind})}
    _manual(ledger, "routing", {"gap": "NOT_FOUND", "discuss": "DISCUSS", "unknown": "UNKNOWN"}, rules=rules)
    lists = worklists(read_run(store.path, "routing"))
    expected = {"order": "physician_order", "review": "physician_review", "record": "physician_record",
                "self_refer": "patient_self_refer", "book": "moa_book"}[kind]
    assert [r["patient_id"] for r in lists[expected]] == ["gap"]
    assert [r["patient_id"] for r in lists["previsit_discuss"]] == ["discuss"]
    assert [r["patient_id"] for r in lists["unknown_tasks"]] == ["unknown"]


def test_missing_action_routes_to_physician_review(panel):
    store, ledger, _ = panel
    rules = {**RULES, "dm.eye": dataclasses.replace(RULES["dm.eye"], action=None)}
    _manual(ledger, "missing-action", {"p": "NOT_FOUND"}, rules=rules)
    assert worklists(read_run(store.path, "missing-action"))["physician_review"][0]["patient_id"] == "p"


@pytest.mark.parametrize("run_id", ["does-not-exist", "incomplete", "legacy", "cohort-only"])
def test_unusable_runs_are_rejected(panel, run_id):
    store, ledger, _ = panel
    _manual(ledger, "incomplete", {"p": "NOT_FOUND"}, finish=False)
    ledger.start("legacy", "synthetic", AS_OF.isoformat(), "old")
    ledger.finish("legacy")
    summary = evaluate_panel(store, ledger, MAPPING, LAYER, RULES, sweep="current", as_of=AS_OF,
                             ruleset="one", cohort_only=True)
    with pytest.raises(ReportError):
        read_run(store.path, summary.run_id if run_id == "cohort-only" else run_id)


def test_store_reads_preserve_sealed_captures_and_dont_create_files(panel, tmp_path):
    store, ledger, summary = panel
    before = store._db.execute("SELECT body_sealed FROM captures").fetchall()
    read_run(store.path, summary.run_id)
    assert store._db.execute("SELECT body_sealed FROM captures").fetchall() == before
    with pytest.raises(ReportError):
        read_run(tmp_path / "missing.db", "missing")
    assert not (tmp_path / "missing.db").exists()


def test_bad_snapshot_and_reverse_dates_fail(panel):
    store, ledger, summary = panel
    run = read_run(store.path, summary.run_id)
    with pytest.raises(ReportError):
        compare_runs(dataclasses.replace(run, as_of=date(2027, 1, 1)), run)
    ledger._db.execute("DELETE FROM eval_rule_metadata WHERE run_id=? AND rule_id='dm.eye'", (summary.run_id,))
    ledger._db.commit()
    with pytest.raises(ReportError):
        read_run(store.path, summary.run_id)


def test_result_version_must_match_snapshot(panel):
    store, ledger, summary = panel
    ledger._db.execute("UPDATE results SET rule_version=2 WHERE run_id=? AND rule_id='dm.eye'", (summary.run_id,))
    ledger._db.commit()
    with pytest.raises(ReportError):
        read_run(store.path, summary.run_id)


def test_html_csv_injection_and_existing_output(panel, tmp_path):
    store, ledger, _ = panel
    rules = {**RULES, "dm.eye": dataclasses.replace(RULES["dm.eye"], title='<script>alert(1)</script>',
               action={"kind": "book", "note": '=HYPERLINK("https://invalid")'})}
    _manual(ledger, "escape", {"=1+1": "NOT_FOUND"}, rules=rules)
    run = read_run(store.path, "escape")
    output = tmp_path / "safe"
    write_worklists(run, output)
    html = (output / "worklists.html").read_text()
    assert '<script>' not in html and '&lt;script&gt;' in html
    with (output / "moa_book.csv").open() as fh:
        row = next(csv.DictReader(fh))
    assert row["patient_id"] == "'=1+1" and row["action_note"].startswith("'=HYPERLINK")
    with pytest.raises(ReportError):
        write_worklists(run, output)
    from pathlib import Path
    with pytest.raises(ReportError):
        write_worklists(run, Path(__file__).resolve().parents[1] / "out" / "unsafe-report")


FEEDBACK_FIELDS = ("patient_id", "rule_id", "rule_version", "outcome", "date", "evidence_note")


def feedback_file(path, **changes):
    row = dict(patient_id="1001", rule_id="cervix.hpv", rule_version="1",
               outcome="done_elsewhere", date="2026-10-02", evidence_note="Synthetic review")
    row.update(changes)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)
    return path


@pytest.mark.parametrize("outcome", ["done_elsewhere", "declined", "not_applicable"])
def test_feedback_capture_doesnt_close_gaps(panel, tmp_path, outcome):
    store, ledger, summary = panel
    run = read_run(store.path, summary.run_id)
    entries = validate_feedback(feedback_file(tmp_path / "feedback.csv", outcome=outcome), run, as_of=AS_OF)
    assert entries[0].source == "attestation" and entries[0].outcome == outcome
    again = evaluate_panel(store, ledger, MAPPING, LAYER, RULES, sweep="current", as_of=AS_OF, ruleset="same")
    assert ledger.state_of(again.run_id, "1001", "cervix.hpv") == "NOT_FOUND"


@pytest.mark.parametrize("change", [
    {"surprise": "bad"}, {"rule_version": "2"}, {"patient_id": "wrong"},
    {"rule_id": "dm.eye.nope"}, {"outcome": "completed"}, {"date": "2026-10-03"},
    {"date": "yesterday"}, {"date": ""}, {"outcome": ""}, {"rule_version": "true"},
])
def test_feedback_invalid_rows_fail(panel, tmp_path, change):
    store, _, summary = panel
    with pytest.raises(ReportError):
        validate_feedback(feedback_file(tmp_path / "bad.csv", **change),
                          read_run(store.path, summary.run_id), as_of=AS_OF)


def test_feedback_template_duplicate_and_formula_roundtrip(panel, tmp_path):
    store, ledger, summary = panel
    run = read_run(store.path, summary.run_id)
    write_worklists(run, tmp_path / "template")
    assert validate_feedback(tmp_path / "template" / "feedback.csv", run, as_of=AS_OF) == ()
    path = feedback_file(tmp_path / "duplicates.csv")
    with path.open("a") as fh:
        fh.write('1001,cervix.hpv,1,declined,2026-10-02,another\n')
    with pytest.raises(ReportError):
        validate_feedback(path, run, as_of=AS_OF)
    _manual(ledger, "formula-id", {"=1+1": "NOT_FOUND"})
    formula_run = read_run(store.path, "formula-id")
    write_worklists(formula_run, tmp_path / "formula-template")
    path = tmp_path / "formula-template" / "feedback.csv"
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    rows[0].update(outcome="done_elsewhere", date="2026-10-02")
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FEEDBACK_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    assert validate_feedback(path, formula_run, as_of=AS_OF)[0].patient_id == "=1+1"


def test_cli_aggregates_and_redacted_errors(panel, tmp_path, capsys):
    store, _, summary = panel
    assert main(["worklists", "--store", str(store.path), "--run", summary.run_id,
                 "--out", str(tmp_path / "cli")]) == 0
    out = capsys.readouterr()
    assert "physician_review: 1" in out.out
    assert not any(pid in out.out for pid in PATIENT_IDS)
    assert main(["diff", "--store", str(store.path), "--before", summary.run_id,
                 "--after", summary.run_id, "--out", str(tmp_path / "cli-diff")]) == 0
    out = capsys.readouterr()
    assert "still_open" in out.out and not any(pid in out.out for pid in PATIENT_IDS)
    secret = tmp_path / "sensitive-patient-name.db"
    assert main(["worklists", "--store", str(secret), "--run", "sensitive-run-id",
                 "--out", str(tmp_path / "error")]) == 1
    out = capsys.readouterr()
    assert "sensitive" not in out.out + out.err
    feedback = feedback_file(tmp_path / "feedback.csv", evidence_note="private synthetic evidence")
    assert main(["feedback-check", "--store", str(store.path), "--run", summary.run_id,
                 "--feedback", str(feedback), "--as-of", "2026-10-02"]) == 0
    out = capsys.readouterr()
    assert "done_elsewhere: 1" in out.out and "capture only" in out.out
    assert "private" not in out.out + out.err and "1001" not in out.out + out.err


def test_two_pipeline_runs_with_new_report_and_outreach(panel, tmp_path, capsys):
    store, ledger, first = panel
    # The positive FIT's missing follow-up arrives in the next synthetic sweep.
    put(store, "new-capture", "1002", "files", "/api/patients/1002/files", {"files": [
        {"file_id": "FOLLOWUP", "tag": "Consults", "title": "Colonoscopy report", "date": "2026-09-01"},
    ]})
    # An active patient who leaves the cohort isn't a demonstrated care closure.
    put(store, "new-capture", "1006", "summary", "/api/patients/1006", {
        "patient_id": "1006", **CHARTS["1006"]["summary"], "last_visit": "2020-01-01",
    })
    second = evaluate_panel(store, ledger, MAPPING, LAYER, RULES, sweep="current", as_of=AS_OF,
                            ruleset="synthetic-digest")
    old, new = read_run(store.path, first.run_id), read_run(store.path, second.run_id)
    diff = compare_runs(old, new)
    assert not diff.ruleset_changed
    assert diff.counts["colon.loop.fit_positive"]["closed"] == 1
    assert diff.counts["dm.eye"]["removed"] == 1 and diff.counts["dm.eye"]["closed"] == 0
    row = next(r for r in diff.rows if r["patient_id"] == "1006" and r["rule_id"] == "dm.eye")
    assert row["after_cohort"] == "outreach" and row["after_state"] == "NOT_EVALUATED"
    write_diff(old, new, tmp_path / "two-pipeline-runs")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n", "  ="])
def test_spreadsheet_formula_prefixes_are_escaped(prefix):
    from clinic_review.report.render import _safe_csv
    assert _safe_csv(prefix + "payload").startswith("'")


def test_feedback_short_and_long_rows_fail(panel, tmp_path):
    store, _, summary = panel
    run = read_run(store.path, summary.run_id)
    path = tmp_path / "malformed.csv"
    header = ",".join(FEEDBACK_FIELDS) + "\n"
    for body in ("1001,cervix.hpv,1\n", "1001,cervix.hpv,1,declined,2026-10-02,note,extra\n"):
        path.write_text(header + body)
        with pytest.raises(ReportError):
            validate_feedback(path, run, as_of=AS_OF)


def test_unwalked_screen_stays_unknown_in_report(panel):
    store, ledger, _ = panel
    for screen, captures in store.sweep_captures("1002", "current").items():
        if screen != "files":
            path = "/api/patients/1002" if screen == "summary" else f"/api/patients/1002/{screen}"
            put(store, "partial", "1002", screen, path, json.loads(captures[0].body), sweep="partial")
    put(store, "partial", "1002", "files", "/api/patients/1002/files", {}, outcome="failed", sweep="partial")
    summary = evaluate_panel(store, ledger, MAPPING, LAYER, RULES, sweep="partial", as_of=AS_OF, ruleset="one")
    run = read_run(store.path, summary.run_id)
    row = next(r for r in worklists(run)["unknown_tasks"] if
               r["patient_id"] == "1002" and r["rule_id"] == "colon.loop.fit_positive")
    assert row["state"] == "UNKNOWN" and "not walked: documents.consults" in row["task"]
    assert not any(r["patient_id"] == "1002" for r in worklists(run)["physician_review"])


def test_empty_full_run_is_valid_but_corrupt_state_isnt(panel):
    store, ledger, _ = panel
    _manual(ledger, "empty", {})
    empty = read_run(store.path, "empty")
    assert sum(map(len, worklists(empty).values())) == 0
    _manual(ledger, "bad-state", {"p": "NOT_FOUND"})
    ledger._db.execute("UPDATE results SET state='oops' WHERE run_id='bad-state'")
    ledger._db.commit()
    with pytest.raises(ReportError):
        read_run(store.path, "bad-state")


def test_cli_argument_and_date_errors_dont_echo_input(panel, tmp_path, capsys):
    store, _, summary = panel
    with pytest.raises(SystemExit):
        main(["worklists", "--sensitive-patient-argument", "private-name"])
    assert "private-name" not in capsys.readouterr().err
    path = feedback_file(tmp_path / "feedback.csv")
    assert main(["feedback-check", "--store", str(store.path), "--run", summary.run_id,
                 "--feedback", str(path), "--as-of", "private-name"]) == 1
    assert "private-name" not in capsys.readouterr().err
