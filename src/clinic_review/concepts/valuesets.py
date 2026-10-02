"""Value set files: one YAML per concept family in valuesets/, loaded and validated strictly.

valuesets/README.md is the field reference. Phrases are written naturally in the files
("TAH-BSO") and normalized on load, so authors never have to think about tokenization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..engine.rules import CONCEPT, SOURCES
from .text import normalize

MATCH_MODES = {"text", "lab", "extraction", "derived"}
STATUSES = {"draft", "signed"}
ICD9_SHAPE = "3 or 4 characters, digits or MSP letter codes, no decimal (e.g. 250, 2500, V451, 30B)"


class ValueSetError(ValueError):
    pass


@dataclass(frozen=True)
class DeriveInput:
    concept: str
    within_months: int | None = None


@dataclass(frozen=True)
class ConceptDef:
    id: str
    label: str
    valueset: str
    # text mode
    icd9: tuple[str, ...] = ()
    icd9_exclude: tuple[str, ...] = ()
    text: tuple[tuple[str, ...], ...] = ()
    not_if: tuple[tuple[str, ...], ...] = ()
    # lab mode
    lab_names: tuple[str, ...] = ()
    results: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (value, normalized phrases)
    numeric: bool = False
    # extraction mode
    extracted_from: tuple[str, ...] = ()
    note: str | None = None
    # derived mode
    derive_any_of: tuple[DeriveInput, ...] = ()


@dataclass(frozen=True)
class ValueSet:
    name: str
    match: str
    status: str
    review_by: date
    sources: tuple[str, ...]
    concepts: dict[str, ConceptDef]
    applies_to: tuple[str, ...] = ()
    signed_off_by: str | None = None
    signed_off_on: date | None = None
    cue_window: int = 3
    cues_before: tuple[tuple[str, ...], ...] = ()
    blocked_by: tuple[tuple[str, ...], ...] = ()
    exclusive: tuple[frozenset[str], ...] = field(default=())


# --- parsing helpers ---------------------------------------------------------------


def _mapping(value: Any, where: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ValueSetError(f"{where}: expected a mapping")
    unknown = set(value) - allowed
    if unknown:
        raise ValueSetError(f"{where}: unknown key(s) {sorted(unknown)}")
    missing = set(required) - set(value)
    if missing:
        raise ValueSetError(f"{where}: missing key(s) {sorted(missing)}")
    return value


def _list(value: Any, where: str, required: bool = False) -> list:
    if value is None:
        if required:
            raise ValueSetError(f"{where}: required")
        return []
    if not isinstance(value, list) or not value:
        raise ValueSetError(f"{where}: expected a non-empty list")
    return value


def _phrases(value: Any, where: str, required: bool = False) -> tuple[tuple[str, ...], ...]:
    out = []
    for p in _list(value, where, required):
        # Unquoted no, yes, on, off load as booleans in YAML; catch them here
        if not isinstance(p, str):
            raise ValueSetError(f"{where}: {p!r} must be a quoted string")
        toks = tuple(normalize(p).split())
        if not toks:
            raise ValueSetError(f"{where}: {p!r} is empty once normalized")
        if toks in out:
            raise ValueSetError(f"{where}: {p!r} is listed twice")
        out.append(toks)
    return tuple(out)


def _concept(value: Any, where: str) -> str:
    if not isinstance(value, str) or not CONCEPT.match(value):
        raise ValueSetError(f"{where}: {value!r} isn't a concept name like 'dx.diabetes'")
    return value


def _sources(value: Any, where: str, required: bool = True) -> tuple[str, ...]:
    out = []
    for s in _list(value, where, required):
        if s not in SOURCES:
            raise ValueSetError(f"{where}: {s!r} isn't an evidence source ({', '.join(sorted(SOURCES))})")
        out.append(s)
    return tuple(out)


def _icd9(value: Any, where: str) -> tuple[str, ...]:
    out = []
    for c in _list(value, where):
        # Unquoted 042 loads as a number (and loses its leading zero); catch it here
        if not isinstance(c, str):
            raise ValueSetError(f"{where}: {c!r} must be a quoted string like \"042\"")
        code = normalize_code(c)
        if not (3 <= len(code) <= 4 and code.isalnum()):
            raise ValueSetError(f"{where}: {c!r} should be {ICD9_SHAPE}")
        out.append(code)
    return tuple(out)


def normalize_code(code: str) -> str:
    """MSP claim format: no decimal point, leading zeros kept ("250.0" -> "2500")."""
    return code.upper().replace(".", "").replace(" ", "")


def _concept_def(cid: str, d: Any, vs_name: str, match: str) -> ConceptDef:
    where = f"concepts.{cid}"
    _concept(cid, where)
    if match == "text":
        d = _mapping(d, where, {"label", "icd9", "icd9_exclude", "text", "not_if"}, {"label"})
        cdef = ConceptDef(
            id=cid,
            label=str(d["label"]),
            valueset=vs_name,
            icd9=_icd9(d.get("icd9"), f"{where}.icd9"),
            icd9_exclude=_icd9(d.get("icd9_exclude"), f"{where}.icd9_exclude"),
            text=_phrases(d.get("text"), f"{where}.text"),
            not_if=_phrases(d.get("not_if"), f"{where}.not_if"),
        )
        if not (cdef.icd9 or cdef.text):
            raise ValueSetError(f"{where}: needs icd9 codes, text phrases, or both")
        if cdef.icd9_exclude and not cdef.icd9:
            raise ValueSetError(f"{where}: icd9_exclude without icd9")
        return cdef
    if match == "lab":
        d = _mapping(d, where, {"label", "names", "results", "numeric"}, {"label", "names"})
        names = tuple(" ".join(t) for t in _phrases(d["names"], f"{where}.names", required=True))
        results: list[tuple[str, tuple[str, ...]]] = []
        if "results" in d:
            r = d["results"]
            if not isinstance(r, dict) or not r:
                raise ValueSetError(f"{where}.results: expected a mapping of value -> phrases")
            seen: set[str] = set()
            for value, phrases in r.items():
                if not isinstance(value, str):
                    raise ValueSetError(f"{where}.results: {value!r} must be a quoted string")
                normed = tuple(" ".join(t) for t in _phrases(phrases, f"{where}.results.{value}", required=True))
                clash = seen & set(normed)
                if clash:
                    raise ValueSetError(f"{where}.results: {sorted(clash)} maps to more than one value")
                seen |= set(normed)
                results.append((str(value).lower(), normed))
        numeric = bool(d.get("numeric", False))
        if numeric == bool(results):
            raise ValueSetError(f"{where}: needs exactly one of results or numeric: true")
        return ConceptDef(id=cid, label=str(d["label"]), valueset=vs_name, lab_names=names, results=tuple(results), numeric=numeric)
    if match == "extraction":
        d = _mapping(d, where, {"label", "from", "note"}, {"label", "from"})
        return ConceptDef(
            id=cid,
            label=str(d["label"]),
            valueset=vs_name,
            extracted_from=_sources(d["from"], f"{where}.from"),
            note=str(d["note"]) if d.get("note") else None,
        )
    d = _mapping(d, where, {"label", "any_of"}, {"label", "any_of"})
    inputs = []
    for i, item in enumerate(_list(d["any_of"], f"{where}.any_of", required=True)):
        iw = f"{where}.any_of[{i}]"
        if isinstance(item, str):
            inputs.append(DeriveInput(_concept(item, iw)))
        else:
            item = _mapping(item, iw, {"concept", "within_months"}, {"concept"})
            months = item.get("within_months")
            if months is not None and (isinstance(months, bool) or not isinstance(months, int) or months < 1):
                raise ValueSetError(f"{iw}.within_months: expected a whole number >= 1")
            inputs.append(DeriveInput(_concept(item["concept"], iw), months))
    return ConceptDef(id=cid, label=str(d["label"]), valueset=vs_name, derive_any_of=tuple(inputs))


TOP_LEVEL = {
    "name", "match", "applies_to", "status", "signed_off", "review_by", "sources",
    "cue_window", "cues_before", "blocked_by", "exclusive", "concepts",
}  # fmt: skip


def parse_valueset(data: Any) -> ValueSet:
    d = _mapping(data, "valueset", TOP_LEVEL, {"name", "status", "review_by", "sources", "concepts"})
    name = str(d["name"])
    match = d.get("match", "text")
    if match not in MATCH_MODES:
        raise ValueSetError(f"match: {match!r} isn't one of {sorted(MATCH_MODES)}")
    status = d["status"]
    if status not in STATUSES:
        raise ValueSetError(f"status: {status!r} isn't one of {sorted(STATUSES)}")
    signed_by = signed_on = None
    if status == "signed":
        s = _mapping(d.get("signed_off"), "signed_off", {"by", "on"}, {"by", "on"})
        signed_by = str(s["by"])
        if not isinstance(s["on"], date):
            raise ValueSetError("signed_off.on: expected a date")
        signed_on = s["on"]
    elif d.get("signed_off") is not None:
        raise ValueSetError("signed_off: only set it when status is signed")
    if not isinstance(d["review_by"], date):
        raise ValueSetError("review_by: expected a date like 2027-10-01")
    sources = tuple(str(s) for s in _list(d["sources"], "sources", required=True))

    if match in ("text", "lab"):
        applies_to = _sources(d.get("applies_to"), "applies_to")
    elif "applies_to" in d:
        raise ValueSetError(f"applies_to: not used by {match} value sets")
    else:
        applies_to = ()
    text_only = {"cue_window", "cues_before", "blocked_by", "exclusive"} & set(d)
    if match != "text" and text_only:
        raise ValueSetError(f"{sorted(text_only)}: only text value sets use these")

    raw = d["concepts"]
    if not isinstance(raw, dict) or not raw:
        raise ValueSetError("concepts: expected a non-empty mapping")
    concepts = {cid: _concept_def(cid, c, name, match) for cid, c in raw.items()}

    exclusive = []
    for i, group in enumerate(_list(d.get("exclusive"), "exclusive")):
        members = frozenset(_concept(c, f"exclusive[{i}]") for c in _list(group, f"exclusive[{i}]", required=True))
        missing = members - set(concepts)
        if missing:
            raise ValueSetError(f"exclusive[{i}]: {sorted(missing)} aren't defined in this file")
        if len(members) < 2:
            raise ValueSetError(f"exclusive[{i}]: needs at least two concepts")
        exclusive.append(members)

    window = d.get("cue_window", 3)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueSetError("cue_window: expected a whole number >= 1")
    return ValueSet(
        name=name,
        match=match,
        status=status,
        review_by=d["review_by"],
        sources=sources,
        concepts=concepts,
        applies_to=applies_to,
        signed_off_by=signed_by,
        signed_off_on=signed_on,
        cue_window=window,
        cues_before=_phrases(d.get("cues_before"), "cues_before"),
        blocked_by=_phrases(d.get("blocked_by"), "blocked_by"),
        exclusive=tuple(exclusive),
    )


def load_valueset(path: str | Path) -> ValueSet:
    path = Path(path)
    try:
        vs = parse_valueset(yaml.safe_load(path.read_text()))
    except ValueSetError as e:
        raise ValueSetError(f"{path.name}: {e}") from None
    if path.stem != vs.name:
        raise ValueSetError(f"{path.name}: name must be {path.stem!r} to match the file")
    return vs
