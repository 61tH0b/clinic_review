"""The evaluator: one rule, one patient, one as-of date, one state. Deterministic, no LLM.

Order of checks, first match wins:
  1. Population: age and sex_at_birth (missing either is UNKNOWN), none_of (NOT_ELIGIBLE)
  2. exclusions (EXCLUDED)
  3. requires (UNKNOWN, and the missing input becomes the task)
  4. population.any_of (NOT_ELIGIBLE)
  5. The interval or loop itself
  6. A documented decline turns any not-up-to-date state into DECLINED
  7. A gap state on a patient whose relevant screens weren't all walked becomes UNKNOWN
  8. mode: discuss turns any remaining gap state into DISCUSS
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .dates import add_months, age_on
from .facts import Fact, Patient
from .rules import Rule
from .states import GAP_STATES, State


@dataclass(frozen=True)
class Result:
    patient_id: str
    rule_id: str
    rule_version: int
    as_of: date
    state: State
    due_date: date | None = None
    evidence_ids: tuple[str, ...] = ()
    searched_sources: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    reason: str = ""


def _ids(facts) -> tuple[str, ...]:
    return tuple(f.id for f in facts if f.id)


def _value_ok(fact: Fact, value_in: tuple[str, ...]) -> bool:
    return not value_in or (fact.value is not None and fact.value.lower() in value_in)


def evaluate(rule: Rule, patient: Patient, as_of: date) -> Result:
    # Facts dated after the as-of date don't exist yet from the rule's point of view
    facts = tuple(f for f in patient.facts if f.date is None or f.date <= as_of)
    searched = tuple(s for s in rule.evidence_sources if s in patient.searched)

    def having(concepts) -> list[Fact]:
        return [f for f in facts if f.concept in concepts]

    def result(state: State, **kw) -> Result:
        return Result(patient.id, rule.id, rule.version, as_of, state, searched_sources=searched, **kw)

    pop = rule.population
    if pop.age_min is not None or pop.age_max is not None:
        if patient.dob is None:
            return result(State.UNKNOWN, missing_inputs=("date of birth",))
        age = age_on(patient.dob, as_of)
        if (pop.age_min is not None and age < pop.age_min) or (pop.age_max is not None and age > pop.age_max):
            return result(State.NOT_ELIGIBLE, reason=f"age {age}")
    if pop.sex_at_birth is not None:
        alternate = having(pop.sex_or_any_of)
        if patient.sex_at_birth != pop.sex_at_birth and not alternate:
            if patient.sex_at_birth is None:
                return result(State.UNKNOWN, missing_inputs=("sex at birth",))
            return result(State.NOT_ELIGIBLE, reason=f"sex at birth {patient.sex_at_birth}")
    if hits := having(pop.none_of):
        return result(State.NOT_ELIGIBLE, evidence_ids=_ids(hits), reason=f"has {hits[0].concept}")

    for ex in rule.exclusions:
        hits = [
            f
            for f in having({ex.concept})
            if ex.within_months is None or (f.date is not None and f.date > add_months(as_of, -ex.within_months))
        ]
        if hits:
            return result(State.EXCLUDED, evidence_ids=_ids(hits), reason=f"has {ex.concept}")

    missing = tuple(r.label for r in rule.requires if not having(r.any_of))
    if missing:
        return result(State.UNKNOWN, missing_inputs=missing)
    if pop.any_of and not having(pop.any_of):
        return result(State.NOT_ELIGIBLE, reason="not in population")

    state, due, evidence, reason = _loop(rule, facts, as_of) if rule.kind == "loop" else _interval(rule, facts, as_of)
    if state is State.NOT_ELIGIBLE:
        return result(state, reason=reason)

    if state is not State.UP_TO_DATE and rule.declined is not None:
        declines = [
            f
            for f in having({rule.declined.concept})
            if f.date is not None and f.date > add_months(as_of, -rule.declined.valid_months)
        ]
        if declines:
            last = max(declines, key=lambda f: f.date)
            return result(
                State.DECLINED,
                due_date=add_months(last.date, rule.declined.valid_months),  # re-offer date
                evidence_ids=_ids([last]),
                reason="informed refusal documented",
            )

    if state in GAP_STATES:
        unwalked = tuple(s for s in rule.evidence_sources if s not in patient.searched)
        if unwalked:
            return result(
                State.UNKNOWN,
                due_date=due,
                evidence_ids=evidence,
                missing_inputs=tuple(f"not walked: {s}" for s in unwalked),
                reason=f"would be {state.value}",
            )
        if rule.mode == "discuss":
            return result(State.DISCUSS, due_date=due, evidence_ids=evidence, reason=f"would be {state.value}")

    return result(state, due_date=due, evidence_ids=evidence, reason=reason)


def _interval(rule: Rule, facts: tuple[Fact, ...], as_of: date):
    best: tuple[date, Fact] | None = None
    for alt in rule.satisfied_by:
        for f in facts:
            if f.concept != alt.concept or f.date is None or not _value_ok(f, alt.value_in):
                continue
            if alt.use_reported_next_due and f.next_due is not None:
                due = f.next_due
            else:
                due = add_months(f.date, alt.within_months)
            # The alternative that keeps the patient covered longest wins (a colonoscopy
            # 9 years ago beats a FIT 3 years ago)
            if best is None or due > best[0]:
                best = (due, f)
    if best is None:
        return State.NOT_FOUND, None, (), "no qualifying evidence"
    due, fact = best
    evidence = _ids([fact])
    if as_of < due - timedelta(days=rule.due_soon_days):
        return State.UP_TO_DATE, due, evidence, fact.concept
    if as_of <= add_months(due, rule.grace_months):
        return State.DUE_SOON, due, evidence, fact.concept
    return State.OVERDUE, due, evidence, fact.concept


def _loop(rule: Rule, facts: tuple[Fact, ...], as_of: date):
    t, fu = rule.trigger, rule.followed_by
    since = add_months(as_of, -t.lookback_months)
    triggers = [
        f for f in facts if f.concept == t.concept and f.date is not None and f.date >= since and _value_ok(f, t.value_in)
    ]
    if not triggers:
        return State.NOT_ELIGIBLE, None, (), "no trigger result"
    trig = max(triggers, key=lambda f: f.date)
    closing = [f for f in facts if f.concept in fu.any_of and f.date is not None and f.date >= trig.date]
    due = trig.date + timedelta(days=fu.within_days)
    if closing:
        first = min(closing, key=lambda f: f.date)
        return State.UP_TO_DATE, due, _ids([trig, first]), f"closed by {first.concept}"
    state = State.DUE_SOON if as_of <= due else State.OVERDUE
    return state, due, _ids([trig]), f"{trig.concept} with no follow-up"
