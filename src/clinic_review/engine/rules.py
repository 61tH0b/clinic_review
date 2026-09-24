"""Rule files: one YAML per rule in rules/, loaded and validated strictly.

rules/README.md is the field reference. Unknown keys are errors, so a typo in a rule
file fails CI instead of silently changing who gets flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

CONCEPT = re.compile(r"^[a-z]+(\.[a-z0-9_]+)+$")
RULE_ID = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")

CATEGORIES = {"A", "B"}
SUBTYPES = {"loop", "unrecognized", "cancer", "screening", "immunization", "chronic", "life_stage"}
KINDS = {"interval", "loop"}
MODES = {"gap", "discuss"}
STATUSES = {"shadow", "live"}
ACTION_KINDS = {"order", "book", "self_refer", "review", "record"}
SEX = {"F", "M"}

# Where evidence can come from. The walker maps each one to CHR screens in the local
# profile, and plans each patient's walk from the rules' evidence_sources (PLAN 5.2).
SOURCES = frozenset(
    {
        "demographics",
        "encounters",
        "history.medical",
        "history.surgical",
        "history.family",
        "risk_factors",
        "medications",
        "immunizations",
        "labs",
        "vitals",
        "documents.diagnostic_imaging",
        "documents.consults",
        "documents.lab",
        "documents.hospital",
        "documents.historical",
    }
)


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    checked: date


@dataclass(frozen=True)
class Population:
    age_min: int | None = None
    age_max: int | None = None
    sex_at_birth: str | None = None
    # Facts that count in place of sex_at_birth (e.g. gender-affirming estrogen for 5+ years)
    sex_or_any_of: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    none_of: tuple[str, ...] = ()


@dataclass(frozen=True)
class Requirement:
    label: str  # what the task says when it's missing, e.g. "smoking history"
    any_of: tuple[str, ...]


@dataclass(frozen=True)
class Exclusion:
    concept: str
    within_months: int | None = None  # None: any time. Set for temporary exclusions.


@dataclass(frozen=True)
class Alternative:
    concept: str
    within_months: int
    value_in: tuple[str, ...] = ()
    use_reported_next_due: bool = False


@dataclass(frozen=True)
class Declined:
    concept: str
    valid_months: int


@dataclass(frozen=True)
class Trigger:
    concept: str
    lookback_months: int
    value_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class FollowUp:
    any_of: tuple[str, ...]
    within_days: int


@dataclass(frozen=True)
class Rule:
    id: str
    version: int
    title: str
    category: str
    subtype: str
    source: Source
    evidence_sources: tuple[str, ...]
    review_by: date
    owner: str
    kind: str = "interval"
    mode: str = "gap"
    status: str = "shadow"
    decision: str | None = None
    population: Population = Population()
    requires: tuple[Requirement, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    satisfied_by: tuple[Alternative, ...] = ()
    due_soon_days: int = 90
    grace_months: int = 0
    declined: Declined | None = None
    trigger: Trigger | None = None
    followed_by: FollowUp | None = None
    action: dict | None = None


# --- parsing helpers ---------------------------------------------------------------


def _mapping(value: Any, where: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise RuleError(f"{where}: expected a mapping")
    unknown = set(value) - allowed
    if unknown:
        raise RuleError(f"{where}: unknown key(s) {sorted(unknown)}")
    missing = set(required) - set(value)
    if missing:
        raise RuleError(f"{where}: missing key(s) {sorted(missing)}")
    return value


def _concepts(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise RuleError(f"{where}: expected a non-empty list of concepts")
    for c in value:
        if not isinstance(c, str) or not CONCEPT.match(c):
            raise RuleError(f"{where}: {c!r} isn't a concept name like 'obs.fit'")
    return tuple(value)


def _values(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise RuleError(f"{where}: expected a non-empty list")
    return tuple(str(v).lower() for v in value)


def _int(value: Any, where: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RuleError(f"{where}: expected a whole number >= {minimum}")
    return value


def _date(value: Any, where: str) -> date:
    if not isinstance(value, date):
        raise RuleError(f"{where}: expected a date like 2027-03-01")
    return value


def _choice(value: Any, where: str, options: set[str]) -> str:
    if value not in options:
        raise RuleError(f"{where}: {value!r} isn't one of {sorted(options)}")
    return value


def _population(value: Any) -> Population:
    if value is None:
        return Population()
    p = _mapping(value, "population", {"age", "sex_at_birth", "any_of", "none_of"})
    age_min = age_max = None
    if "age" in p:
        a = _mapping(p["age"], "population.age", {"min", "max"})
        age_min = _int(a["min"], "population.age.min") if "min" in a else None
        age_max = _int(a["max"], "population.age.max") if "max" in a else None
        if age_min is not None and age_max is not None and age_min > age_max:
            raise RuleError("population.age: min is above max")
    sex, sex_or = None, ()
    if "sex_at_birth" in p:
        s = p["sex_at_birth"]
        if isinstance(s, dict):
            s = _mapping(s, "population.sex_at_birth", {"is", "or_any_of"}, {"is"})
            sex_or = _concepts(s.get("or_any_of"), "population.sex_at_birth.or_any_of")
            s = s["is"]
        sex = _choice(s, "population.sex_at_birth", SEX)
    return Population(
        age_min=age_min,
        age_max=age_max,
        sex_at_birth=sex,
        sex_or_any_of=sex_or,
        any_of=_concepts(p.get("any_of"), "population.any_of"),
        none_of=_concepts(p.get("none_of"), "population.none_of"),
    )


def _requires(value: Any) -> tuple[Requirement, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuleError("requires: expected a list")
    out = []
    for i, r in enumerate(value):
        r = _mapping(r, f"requires[{i}]", {"label", "any_of"}, {"label", "any_of"})
        out.append(Requirement(label=str(r["label"]), any_of=_concepts(r["any_of"], f"requires[{i}].any_of")))
    return tuple(out)


def _exclusions(value: Any) -> tuple[Exclusion, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuleError("exclusions: expected a list")
    out = []
    for i, e in enumerate(value):
        where = f"exclusions[{i}]"
        if isinstance(e, str):
            out.append(Exclusion(_concepts([e], where)[0]))
        else:
            e = _mapping(e, where, {"concept", "within_months"}, {"concept"})
            months = _int(e["within_months"], f"{where}.within_months", 1) if "within_months" in e else None
            out.append(Exclusion(_concepts([e["concept"]], where)[0], months))
    return tuple(out)


def _alternatives(value: Any) -> tuple[Alternative, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise RuleError("satisfied_by: expected a non-empty list")
    out = []
    for i, a in enumerate(value):
        where = f"satisfied_by[{i}]"
        a = _mapping(
            a, where, {"concept", "within_months", "value_in", "use_reported_next_due"}, {"concept", "within_months"}
        )
        out.append(
            Alternative(
                concept=_concepts([a["concept"]], where)[0],
                within_months=_int(a["within_months"], f"{where}.within_months", 1),
                value_in=_values(a.get("value_in"), f"{where}.value_in"),
                use_reported_next_due=bool(a.get("use_reported_next_due", False)),
            )
        )
    return tuple(out)


def _declined(value: Any) -> Declined | None:
    if value is None:
        return None
    d = _mapping(value, "declined", {"concept", "valid_months"}, {"concept", "valid_months"})
    return Declined(_concepts([d["concept"]], "declined.concept")[0], _int(d["valid_months"], "declined.valid_months", 1))


def _trigger(value: Any) -> Trigger | None:
    if value is None:
        return None
    t = _mapping(value, "trigger", {"concept", "lookback_months", "value_in"}, {"concept", "lookback_months"})
    return Trigger(
        concept=_concepts([t["concept"]], "trigger.concept")[0],
        lookback_months=_int(t["lookback_months"], "trigger.lookback_months", 1),
        value_in=_values(t.get("value_in"), "trigger.value_in"),
    )


def _followed_by(value: Any) -> FollowUp | None:
    if value is None:
        return None
    f = _mapping(value, "followed_by", {"any_of", "within_days"}, {"any_of", "within_days"})
    return FollowUp(_concepts(f["any_of"], "followed_by.any_of"), _int(f["within_days"], "followed_by.within_days", 1))


TOP_LEVEL = {
    "id", "version", "title", "category", "subtype", "kind", "mode", "status", "source", "decision",
    "population", "requires", "exclusions", "satisfied_by", "due_soon_days", "grace_months", "declined",
    "trigger", "followed_by", "evidence_sources", "action", "review_by", "owner",
}  # fmt: skip
REQUIRED = {"id", "version", "title", "category", "subtype", "source", "evidence_sources", "review_by", "owner"}


def parse_rule(data: Any) -> Rule:
    d = _mapping(data, "rule", TOP_LEVEL, REQUIRED)
    rule_id = d["id"]
    if not isinstance(rule_id, str) or not RULE_ID.match(rule_id):
        raise RuleError(f"id: {rule_id!r} isn't a rule id like 'colon.fit'")
    s = _mapping(d["source"], "source", {"name", "url", "checked"}, {"name", "url", "checked"})
    source = Source(str(s["name"]), str(s["url"]), _date(s["checked"], "source.checked"))
    sources = d["evidence_sources"]
    if not isinstance(sources, list) or not sources:
        raise RuleError("evidence_sources: expected a non-empty list")
    for src in sources:
        _choice(src, "evidence_sources", SOURCES)
    action = d.get("action")
    if action is not None:
        action = _mapping(action, "action", {"kind", "note"}, {"kind"})
        _choice(action["kind"], "action.kind", ACTION_KINDS)
    rule = Rule(
        id=rule_id,
        version=_int(d["version"], "version", 1),
        title=str(d["title"]),
        category=_choice(d["category"], "category", CATEGORIES),
        subtype=_choice(d["subtype"], "subtype", SUBTYPES),
        kind=_choice(d.get("kind", "interval"), "kind", KINDS),
        mode=_choice(d.get("mode", "gap"), "mode", MODES),
        status=_choice(d.get("status", "shadow"), "status", STATUSES),
        source=source,
        decision=str(d["decision"]) if d.get("decision") is not None else None,
        population=_population(d.get("population")),
        requires=_requires(d.get("requires")),
        exclusions=_exclusions(d.get("exclusions")),
        satisfied_by=_alternatives(d.get("satisfied_by")),
        due_soon_days=_int(d.get("due_soon_days", 90), "due_soon_days"),
        grace_months=_int(d.get("grace_months", 0), "grace_months"),
        declined=_declined(d.get("declined")),
        trigger=_trigger(d.get("trigger")),
        followed_by=_followed_by(d.get("followed_by")),
        evidence_sources=tuple(sources),
        action=dict(action) if action else None,
        review_by=_date(d["review_by"], "review_by"),
        owner=str(d["owner"]),
    )
    if rule.kind == "interval":
        if not rule.satisfied_by:
            raise RuleError("an interval rule needs satisfied_by")
        if rule.trigger or rule.followed_by:
            raise RuleError("trigger and followed_by only go on loop rules")
    else:
        if not (rule.trigger and rule.followed_by):
            raise RuleError("a loop rule needs trigger and followed_by")
        if rule.satisfied_by or rule.grace_months:
            raise RuleError("satisfied_by and grace_months only go on interval rules")
    return rule


def load_rule(path: str | Path) -> Rule:
    path = Path(path)
    try:
        rule = parse_rule(yaml.safe_load(path.read_text()))
    except RuleError as e:
        raise RuleError(f"{path.name}: {e}") from None
    if path.name != f"{rule.id}.yaml":
        raise RuleError(f"{path.name}: file name must be {rule.id}.yaml")
    return rule


def load_rules(directory: str | Path) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        rule = load_rule(path)
        rules[rule.id] = rule
    return rules


def check_rules(rules: dict[str, Rule], today: date) -> list[str]:
    """Problems that should fail CI: stale rules and dates that can't be right."""
    problems = []
    for rule in rules.values():
        if rule.review_by < today:
            problems.append(f"{rule.id}: past its review_by date ({rule.review_by}), re-check the source")
        if rule.source.checked > today:
            problems.append(f"{rule.id}: source.checked ({rule.source.checked}) is in the future")
    return problems
