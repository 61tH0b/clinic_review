"""The concept layer: chart entries in, engine facts out.

An Observation is one row the fact store pulled out of a walker capture: a problem list
entry, a surgical history line, a medication, a lab result, a document title. The layer
turns it into zero or more Facts, and records a Skip for anything it couldn't map or
deliberately didn't (negated, uncertain, a relative's history, a requisition rather than
a report). Skips are the curation list: they're how the value sets grow, and they stay on
the Mac. A Skip's reason only ever quotes value set phrases, never the chart text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..engine.dates import add_months
from ..engine.facts import Fact
from ..engine.rules import SOURCES
from .text import Span, contains, find, normalize, tokens
from .valuesets import ConceptDef, ValueSet, ValueSetError, load_valueset, normalize_code

_NUMBER = re.compile(r"^(<|>|<=|>=)?\s*\d+(\.\d+)?$")


@dataclass(frozen=True)
class Observation:
    source: str  # evidence source, e.g. "history.medical"
    id: str = ""  # row or capture id; becomes the fact's evidence id
    date: date | None = None  # when it happened, or when a current list showed it
    code: str | None = None  # ICD-9 as MSP stores it
    text: str | None = None  # problem, surgical history, medication, risk factor, document title
    lab_name: str | None = None
    result: str | None = None
    next_due: date | None = None  # a due date printed on the report


@dataclass(frozen=True)
class Skip:
    observation_id: str
    source: str
    reason: str


@dataclass(frozen=True)
class Resolved:
    facts: tuple[Fact, ...]
    skipped: tuple[Skip, ...]


def _say(phrase: tuple[str, ...]) -> str:
    return "'" + " ".join(phrase) + "'"


class ConceptLayer:
    def __init__(self, valuesets: list[ValueSet]):
        self.valuesets = tuple(valuesets)
        self.concepts: dict[str, ConceptDef] = {}
        for vs in self.valuesets:
            for cid, cdef in vs.concepts.items():
                if cid in self.concepts:
                    raise ValueSetError(f"{cid} is defined in both {self.concepts[cid].valueset} and {vs.name}")
                self.concepts[cid] = cdef
        self._labs: dict[str, ConceptDef] = {}
        for vs in self.valuesets:
            if vs.match != "lab":
                continue
            for cdef in vs.concepts.values():
                for name in cdef.lab_names:
                    if name in self._labs:
                        raise ValueSetError(f"lab name {name!r} maps to both {self._labs[name].id} and {cdef.id}")
                    self._labs[name] = cdef
        # Derived concepts may build on earlier derived concepts, never later ones
        self._derived: list[ConceptDef] = []
        seen: set[str] = set()
        for vs in self.valuesets:
            if vs.match != "derived":
                continue
            for cdef in vs.concepts.values():
                for inp in cdef.derive_any_of:
                    if inp.concept not in self.concepts:
                        raise ValueSetError(f"{cdef.id}: input {inp.concept} isn't defined in any value set")
                    if self.concepts[inp.concept].derive_any_of and inp.concept not in seen:
                        raise ValueSetError(f"{cdef.id}: derived input {inp.concept} must be defined above it")
                seen.add(cdef.id)
                self._derived.append(cdef)

    @classmethod
    def load(cls, directory: str | Path) -> "ConceptLayer":
        return cls([load_valueset(p) for p in sorted(Path(directory).glob("*.yaml"))])

    # --- resolving observations ------------------------------------------------------

    def resolve(self, obs: Observation) -> Resolved:
        if obs.source not in SOURCES:
            raise ValueError(f"unknown evidence source {obs.source!r}")
        facts: dict[str, Fact] = {}
        skipped: list[Skip] = []

        def fact(cid: str, value: str | None = None) -> None:
            facts.setdefault(
                cid, Fact(concept=cid, date=obs.date, value=value, next_due=obs.next_due, id=obs.id, source=obs.source)
            )

        def skip(reason: str) -> None:
            skipped.append(Skip(obs.id, obs.source, reason))

        applicable = [vs for vs in self.valuesets if obs.source in vs.applies_to]
        if obs.lab_name is not None:
            self._resolve_lab(obs, applicable, fact, skip)
        if obs.code:
            code = normalize_code(obs.code)
            for vs in applicable:
                if vs.match != "text":
                    continue
                for cdef in vs.concepts.values():
                    if any(code.startswith(p) for p in cdef.icd9) and not any(code.startswith(x) for x in cdef.icd9_exclude):
                        fact(cdef.id)
        if obs.text:
            toks = tokens(obs.text)
            for vs in applicable:
                if vs.match == "text":
                    for cid in self._match_text(vs, toks, skip):
                        fact(cid)
        if not facts and not skipped:
            skip("no concept matched")
        return Resolved(tuple(facts.values()), tuple(skipped))

    def _resolve_lab(self, obs: Observation, applicable, fact, skip) -> None:
        if not any(vs.match == "lab" for vs in applicable):
            skip(f"no lab value set reads {obs.source}")
            return
        cdef = self._labs.get(normalize(obs.lab_name))
        if cdef is None:
            skip("lab name not in any value set")
            return
        raw = (obs.result or "").strip()
        if cdef.numeric:
            if _NUMBER.match(raw):
                fact(cdef.id, raw.replace(" ", ""))
            else:
                fact(cdef.id)
                skip(f"{cdef.id}: result isn't a number")
            return
        result = normalize(raw)
        for value, phrases in cdef.results:
            if result in phrases:
                fact(cdef.id, value)
                return
        # Keep that the test happened, but with no value, so it can't satisfy a rule that
        # needs a specific result
        fact(cdef.id)
        skip(f"{cdef.id}: result not in the value set")

    def _match_text(self, vs: ValueSet, toks: tuple[str, ...], skip) -> list[str]:
        found: dict[str, list[Span]] = {}
        for cdef in vs.concepts.values():
            hits = [Span(cdef.id, i, i + len(p), p) for p in cdef.text for i in find(toks, p)]
            if hits:
                found[cdef.id] = hits
        if not found:
            return []  # nothing here for this value set, so nothing to log either
        blocker = next((b for b in vs.blocked_by if contains(toks, b)), None)
        if blocker:
            skip(f"{vs.name}: blocked by {_say(blocker)}")
            return []
        spans: list[Span] = []
        for cid, hits in found.items():
            blocker = next((n for n in self.concepts[cid].not_if if contains(toks, n)), None)
            if blocker:
                skip(f"{cid}: not counted because of {_say(blocker)}")
            else:
                spans.extend(hits)
        # Where phrases overlap, the longest wins among alternatives ("ex smoker" beats
        # "smoker"), but a refinement never hides its parent ("ckd stage 4" keeps "ckd")
        def rivals(a: str, b: str) -> bool:
            return a == b or any(a in g and b in g for g in vs.exclusive)

        spans = [s for s in spans if not any(s.inside(o) and rivals(s.concept, o.concept) for o in spans)]
        kept: list[Span] = []
        for s in spans:
            window = toks[max(0, s.start - vs.cue_window) : s.start]
            cue = next((c for c in vs.cues_before if contains(window, c)), None)
            if cue:
                skip(f"{s.concept}: {_say(cue)} before {_say(s.phrase)}")
            else:
                kept.append(s)
        concepts = {s.concept for s in kept}
        for group in vs.exclusive:
            clash = concepts & group
            if len(clash) > 1:
                skip(f"conflicting: {', '.join(sorted(clash))}")
                concepts -= clash
        return sorted(concepts)

    def resolve_all(self, observations) -> Resolved:
        facts: list[Fact] = []
        skipped: list[Skip] = []
        for obs in observations:
            r = self.resolve(obs)
            facts.extend(r.facts)
            skipped.extend(r.skipped)
        return Resolved(tuple(facts), tuple(skipped))

    # --- derived concepts ------------------------------------------------------------

    def derive(self, facts, as_of: date) -> tuple[Fact, ...]:
        """Derived facts only. Each one is dated by its latest contributing fact and keeps
        the contributing evidence ids, so the queue can show why it fired."""
        pool = [f for f in facts if f.date is None or f.date <= as_of]
        derived: list[Fact] = []
        for cdef in self._derived:
            hits = []
            for inp in cdef.derive_any_of:
                for f in pool:
                    if f.concept != inp.concept:
                        continue
                    if inp.within_months is not None and (f.date is None or f.date <= add_months(as_of, -inp.within_months)):
                        continue
                    hits.append(f)
            if hits:
                dated = [f.date for f in hits if f.date is not None]
                new = Fact(
                    concept=cdef.id,
                    date=max(dated) if dated else None,
                    id="+".join(sorted({f.id for f in hits if f.id})),
                    source="derived",
                )
                derived.append(new)
                pool.append(new)
        return tuple(derived)

    def facts_for(self, observations, as_of: date) -> Resolved:
        """Resolve every observation, then add derived facts. What the evaluator reads."""
        r = self.resolve_all(observations)
        return Resolved(r.facts + self.derive(r.facts, as_of), r.skipped)
