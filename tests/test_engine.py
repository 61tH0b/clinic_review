"""Rule engine: synthetic patients at every edge (PLAN section 9.1). No real data."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from clinic_review.engine import (
    SOURCES,
    Fact,
    Patient,
    RuleError,
    State,
    check_rules,
    evaluate,
    load_rule,
    load_rules,
    parse_rule,
)
from clinic_review.engine.__main__ import main as engine_main
from clinic_review.engine.dates import add_months, age_on

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
RULES = load_rules(RULES_DIR)
AS_OF = date(2026, 9, 24)


def patient(*facts: Fact, dob=date(1960, 6, 1), sex="F", searched=SOURCES) -> Patient:
    return Patient(id="p1", dob=dob, sex_at_birth=sex, facts=tuple(facts), searched=frozenset(searched))


def fact(concept, on=None, value=None, next_due=None, fid=None) -> Fact:
    return Fact(concept=concept, date=on, value=value, next_due=next_due, id=fid or f"{concept}@{on}")


def run(rule_id, p, as_of=AS_OF):
    return evaluate(RULES[rule_id], p, as_of)


def turning(age: int, on: date = AS_OF) -> date:
    """Date of birth for someone whose birthday number `age` is exactly `on`."""
    return on.replace(year=on.year - age)


# --- rule files ----------------------------------------------------------------------


def test_every_rule_file_loads_and_is_current():
    assert set(RULES) == {
        "breast.avg.40_49",
        "breast.avg.50_74",
        "cervix.hpv",
        "colon.fit",
        "colon.loop.fit_positive",
        "dm.eye",
        "lung.eligibility",
    }
    assert check_rules(RULES, AS_OF) == []
    assert all(r.status == "shadow" for r in RULES.values())


def test_stale_rule_fails_the_check():
    problems = check_rules(RULES, date(2027, 9, 2))
    assert any(p.startswith("colon.fit: past its review_by") for p in problems)


def test_cli_check(capsys):
    assert engine_main(["check", str(RULES_DIR), "--today", "2026-09-24"]) == 0
    assert "7 rules OK" in capsys.readouterr().out
    assert engine_main(["check", str(RULES_DIR), "--today", "2027-09-02"]) == 1
    assert "past its review_by" in capsys.readouterr().err


def _base_rule() -> dict:
    return yaml.safe_load((RULES_DIR / "dm.eye.yaml").read_text())


@pytest.mark.parametrize(
    "change, message",
    [
        ({"satisfied_by": [{"concept": "exam.retinal", "within_months": 12, "within_days": 5}]}, "unknown key"),
        ({"population": {"any_of": ["Diabetes"]}}, "isn't a concept name"),
        ({"evidence_sources": ["chart"]}, "isn't one of"),
        ({"kind": "loop"}, "needs trigger and followed_by"),
        ({"satisfied_by": None}, "needs satisfied_by"),
        ({"population": {"age": {"min": 75, "max": 50}}}, "min is above max"),
        ({"action": {"kind": "fax"}}, "isn't one of"),
        ({"surprise": 1}, "unknown key"),
    ],
)
def test_bad_rules_are_rejected(change, message):
    data = {**_base_rule(), **change}
    with pytest.raises(RuleError, match=message):
        parse_rule(data)


def test_file_name_must_match_id(tmp_path):
    bad = tmp_path / "dm.eyes.yaml"
    bad.write_text((RULES_DIR / "dm.eye.yaml").read_text())
    with pytest.raises(RuleError, match="file name must be dm.eye.yaml"):
        load_rule(bad)


# --- dates ---------------------------------------------------------------------------


def test_date_helpers():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 15), -24) == date(2024, 3, 15)
    assert age_on(date(2000, 2, 29), date(2026, 2, 28)) == 25
    assert age_on(date(2000, 2, 29), date(2026, 3, 1)) == 26


# --- population ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "dob, state",
    [
        (turning(50) + timedelta(days=1), State.NOT_ELIGIBLE),  # 49.99
        (turning(50), State.NOT_FOUND),  # 50.00
        (turning(75) + timedelta(days=1), State.NOT_FOUND),  # 74.99
        (turning(75), State.NOT_ELIGIBLE),  # 75.00
    ],
)
def test_age_edges(dob, state):
    assert run("colon.fit", patient(dob=dob)).state is state


def test_missing_date_of_birth_is_unknown():
    r = run("colon.fit", patient(dob=None))
    assert r.state is State.UNKNOWN and r.missing_inputs == ("date of birth",)


def test_sex_at_birth():
    assert run("breast.avg.50_74", patient(sex="M")).state is State.NOT_ELIGIBLE
    r = run("breast.avg.50_74", patient(sex=None))
    assert r.state is State.UNKNOWN and r.missing_inputs == ("sex at birth",)
    # Gender-affirming estrogen for 5+ years counts in place of sex at birth
    r = run("breast.avg.50_74", patient(fact("rx.estrogen_gender_affirming_5y", date(2018, 1, 1)), sex="M"))
    assert r.state is State.NOT_FOUND


def test_none_of_sends_patient_to_another_rule():
    r = run("colon.fit", patient(fact("risk.colon_family_history_high")))
    assert r.state is State.NOT_ELIGIBLE and r.evidence_ids


def test_any_of_population():
    assert run("dm.eye", patient()).state is State.NOT_ELIGIBLE
    assert run("dm.eye", patient(fact("dx.diabetes", date(2015, 1, 1)))).state is State.NOT_FOUND


# --- exclusions and declines ---------------------------------------------------------


def test_exclusion():
    r = run("colon.fit", patient(fact("proc.colectomy_total", date(2010, 5, 1), fid="surg-1")))
    assert r.state is State.EXCLUDED and r.evidence_ids == ("surg-1",)


def test_temporary_exclusion_expires():
    recent = patient(fact("state.pregnancy", AS_OF - timedelta(days=60)))
    older = patient(fact("state.pregnancy", add_months(AS_OF, -4)))
    assert run("breast.avg.50_74", recent).state is State.EXCLUDED
    assert run("breast.avg.50_74", older).state is State.NOT_FOUND


def test_decline_holds_until_reoffer_date():
    declined_on = add_months(AS_OF, -6)
    r = run("colon.fit", patient(fact("decline.colon_screening", declined_on, fid="note-9")))
    assert r.state is State.DECLINED
    assert r.due_date == add_months(declined_on, 24) and r.evidence_ids == ("note-9",)
    stale = patient(fact("decline.colon_screening", add_months(AS_OF, -25)))
    assert run("colon.fit", stale).state is State.NOT_FOUND


def test_up_to_date_beats_a_decline():
    p = patient(
        fact("decline.colon_screening", add_months(AS_OF, -3)),
        fact("obs.fit", add_months(AS_OF, -2), "negative"),
    )
    assert run("colon.fit", p).state is State.UP_TO_DATE


# --- intervals -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "days_before_due, state",
    [
        (91, State.UP_TO_DATE),
        (90, State.DUE_SOON),
        (0, State.DUE_SOON),  # due today
        (-1, State.OVERDUE),
    ],
)
def test_interval_edges(days_before_due, state):
    fit_on = date(2024, 10, 1)
    due = add_months(fit_on, 24)
    r = run("colon.fit", patient(fact("obs.fit", fit_on, "negative", fid="lab-1")), as_of=due - timedelta(days=days_before_due))
    assert r.state is state
    assert r.due_date == due and r.evidence_ids == ("lab-1",)


def test_longest_cover_wins():
    p = patient(
        fact("obs.fit", add_months(AS_OF, -30), "negative"),
        fact("proc.colonoscopy", add_months(AS_OF, -108), fid="scope-1"),
    )
    r = run("colon.fit", p)
    assert r.state is State.UP_TO_DATE and r.evidence_ids == ("scope-1",)


def test_positive_fit_doesnt_count_as_screened():
    p = patient(fact("obs.fit", add_months(AS_OF, -3), "positive"))
    assert run("colon.fit", p).state is State.NOT_FOUND


def test_future_dated_facts_are_ignored():
    p = patient(fact("obs.fit", AS_OF + timedelta(days=5), "negative"))
    assert run("colon.fit", p).state is State.NOT_FOUND


def test_reported_next_due_overrides_the_interval():
    # HPV "other" with NILM: the lab prints a 12-month repeat, not the 5-year interval
    tested = add_months(AS_OF, -11)
    p = patient(fact("obs.hpv_test", tested, "negative", next_due=add_months(tested, 12)), dob=date(1985, 1, 1))
    r = run("cervix.hpv", p)
    assert r.state is State.DUE_SOON and r.due_date == add_months(tested, 12)
    no_date = patient(fact("obs.hpv_test", tested, "negative"), dob=date(1985, 1, 1))
    assert run("cervix.hpv", no_date).state is State.UP_TO_DATE


def test_hiv_follows_the_immunocompromised_cervix_rule():
    p = patient(fact("dx.hiv", date(2019, 1, 1)), dob=date(1985, 1, 1))
    assert run("cervix.hpv", p).state is State.NOT_ELIGIBLE


@pytest.mark.parametrize(
    "months_since_exam, extra_days, state",
    [
        (8, 0, State.UP_TO_DATE),
        (11, 0, State.DUE_SOON),
        (18, 0, State.DUE_SOON),  # past 1 year, inside the grace year
        (24, 0, State.DUE_SOON),
        (24, 1, State.OVERDUE),
    ],
)
def test_diabetic_eye_grace_year(months_since_exam, extra_days, state):
    exam_on = date(2024, 3, 10)
    as_of = add_months(exam_on, months_since_exam) + timedelta(days=extra_days)
    p = patient(fact("dx.diabetes", date(2015, 1, 1)), fact("exam.retinal", exam_on))
    assert run("dm.eye", p, as_of=as_of).state is state


# --- requires and discuss ------------------------------------------------------------


def test_missing_smoking_history_is_the_task():
    r = run("lung.eligibility", patient())
    assert r.state is State.UNKNOWN and r.missing_inputs == ("smoking history",)
    assert run("lung.eligibility", patient(fact("risk.never_smoker"))).state is State.NOT_ELIGIBLE
    assert run("lung.eligibility", patient(fact("risk.former_smoker"))).state is State.NOT_FOUND


def test_discuss_rules_never_raise_a_gap():
    dob = date(1981, 1, 1)
    assert run("breast.avg.40_49", patient(dob=dob)).state is State.DISCUSS
    recent = patient(fact("imaging.mammogram", add_months(AS_OF, -6)), dob=dob)
    assert run("breast.avg.40_49", recent).state is State.UP_TO_DATE


# --- screens that weren't walked -----------------------------------------------------


def test_unwalked_source_turns_a_gap_into_unknown():
    r = run("colon.fit", patient(searched=SOURCES - {"documents.consults"}))
    assert r.state is State.UNKNOWN
    assert r.missing_inputs == ("not walked: documents.consults",)
    assert "documents.consults" not in r.searched_sources


def test_unwalked_source_doesnt_hide_an_up_to_date_result():
    p = patient(fact("obs.fit", add_months(AS_OF, -3), "negative"), searched={"labs"})
    assert run("colon.fit", p).state is State.UP_TO_DATE


# --- loops ---------------------------------------------------------------------------


def test_positive_fit_loop():
    fit_on = AS_OF - timedelta(days=100)
    pos = fact("obs.fit", fit_on, "positive", fid="lab-7")
    r = run("colon.loop.fit_positive", patient(pos))
    assert r.state is State.DUE_SOON and r.due_date == fit_on + timedelta(days=180)

    late = run("colon.loop.fit_positive", patient(pos), as_of=fit_on + timedelta(days=181))
    assert late.state is State.OVERDUE and late.evidence_ids == ("lab-7",)

    closed = patient(pos, fact("proc.colonoscopy", fit_on + timedelta(days=40), fid="scope-2"))
    r = run("colon.loop.fit_positive", closed)
    assert r.state is State.UP_TO_DATE and r.evidence_ids == ("lab-7", "scope-2")


def test_colonoscopy_before_the_fit_doesnt_close_the_loop():
    fit_on = AS_OF - timedelta(days=200)
    p = patient(fact("obs.fit", fit_on, "positive"), fact("proc.colonoscopy", fit_on - timedelta(days=30)))
    assert run("colon.loop.fit_positive", p).state is State.OVERDUE


def test_loop_needs_a_recent_positive_trigger():
    assert run("colon.loop.fit_positive", patient(fact("obs.fit", AS_OF, "negative"))).state is State.NOT_ELIGIBLE
    old = patient(fact("obs.fit", add_months(AS_OF, -30), "positive"))
    assert run("colon.loop.fit_positive", old).state is State.NOT_ELIGIBLE


def test_same_inputs_same_result():
    p = patient(fact("obs.fit", date(2025, 1, 5), "negative"), fact("proc.colonoscopy", date(2018, 2, 1)))
    assert all(run(rule_id, p) == run(rule_id, p) for rule_id in RULES)
