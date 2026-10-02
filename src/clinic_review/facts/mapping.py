"""Facts mapping: where the rows are in each screen's JSON, and which field is which.

This is EMR-specific, like the walker profile. The real CHR mapping is written from the
Phase 0 map and lives in local/ (gitignored). tests/fixtures/fake_emr/facts.yaml is the
format reference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..engine.rules import SOURCES

ROW_FIELDS = ("id", "date", "code", "text", "lab_name", "result", "next_due")
SEEN = "seen"  # date: seen means "the day the walker saw this row", for current lists


class MappingError(ValueError):
    pass


@dataclass(frozen=True)
class RowSpec:
    response: re.Pattern[str]  # searched against the capture URL's path
    items: str  # dotted path to the list of rows; "" for a top-level list
    source: str | None  # fixed evidence source, or
    source_by: str | None  # a field whose value picks the source through source_values
    source_values: dict[str, str]
    fields: dict[str, tuple[str, ...]]  # Observation field -> JSON path(s); text may join several


@dataclass(frozen=True)
class ScreenSpec:
    name: str
    sources: tuple[str, ...]  # evidence sources that count as searched once this screen loads
    rows: tuple[RowSpec, ...]


@dataclass(frozen=True)
class PatientSpec:
    screen: str
    response: re.Pattern[str]
    dob: str
    sex_at_birth: str
    sex_values: dict[str, str]
    status: str | None = None
    include_statuses: tuple[str, ...] = ()
    last_visit: str | None = None


@dataclass(frozen=True)
class FactsMapping:
    name: str
    patient: PatientSpec
    screens: dict[str, ScreenSpec]
    date_format: str | None = None  # strptime format; ISO dates when unset


def _mapping(value: Any, where: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise MappingError(f"{where}: expected a mapping")
    unknown = set(value) - allowed
    if unknown:
        raise MappingError(f"{where}: unknown key(s) {sorted(unknown)}")
    missing = set(required) - set(value)
    if missing:
        raise MappingError(f"{where}: missing key(s) {sorted(missing)}")
    return value


def _source(value: Any, where: str) -> str:
    if value not in SOURCES:
        raise MappingError(f"{where}: {value!r} isn't an evidence source")
    return value


def _regex(value: Any, where: str) -> re.Pattern[str]:
    try:
        return re.compile(str(value))
    except re.error as e:
        raise MappingError(f"{where}: bad regex: {e}") from None


def _row(d: Any, where: str, screen_sources: tuple[str, ...]) -> RowSpec:
    d = _mapping(d, where, {"response", "items", "source", "source_by", "source_values", *ROW_FIELDS}, {"response", "items"})
    fields = {}
    for f in ROW_FIELDS:
        if f in d:
            v = d[f]
            paths = tuple(str(p) for p in v) if isinstance(v, list) else (str(v),)
            if len(paths) > 1 and f != "text":
                raise MappingError(f"{where}.{f}: only text can join several fields")
            fields[f] = paths
    if not ({"text", "code", "lab_name"} & set(fields)):
        raise MappingError(f"{where}: needs at least one of text, code, lab_name")
    source = source_by = None
    values: dict[str, str] = {}
    if "source_by" in d:
        if "source" in d:
            raise MappingError(f"{where}: use source or source_by, not both")
        source_by = str(d["source_by"])
        raw = d.get("source_values")
        if not isinstance(raw, dict) or not raw:
            raise MappingError(f"{where}.source_values: expected a mapping of field value -> evidence source")
        values = {str(k): _source(v, f"{where}.source_values") for k, v in raw.items()}
        stray = set(values.values()) - set(screen_sources)
    else:
        if "source_values" in d:
            raise MappingError(f"{where}: source_values needs source_by")
        if "source" in d:
            source = _source(d["source"], f"{where}.source")
        elif len(screen_sources) == 1:
            source = screen_sources[0]
        else:
            raise MappingError(f"{where}: name a source; the screen reads several")
        stray = {source} - set(screen_sources)
    if stray:
        raise MappingError(f"{where}: {sorted(stray)} isn't in the screen's sources")
    return RowSpec(_regex(d["response"], f"{where}.response"), str(d["items"]), source, source_by, values, fields)


def parse_mapping(data: Any) -> FactsMapping:
    d = _mapping(data, "mapping", {"name", "patient", "screens", "date_format"}, {"name", "patient", "screens"})
    screens: dict[str, ScreenSpec] = {}
    raw_screens = d["screens"]
    if not isinstance(raw_screens, dict) or not raw_screens:
        raise MappingError("screens: expected a non-empty mapping")
    for name, s in raw_screens.items():
        where = f"screens.{name}"
        s = _mapping(s, where, {"sources", "rows"}, {"sources"})
        if not isinstance(s["sources"], list) or not s["sources"]:
            raise MappingError(f"{where}.sources: expected a non-empty list")
        sources = tuple(_source(x, f"{where}.sources") for x in s["sources"])
        rows = s.get("rows") or []
        if not isinstance(rows, list):
            raise MappingError(f"{where}.rows: expected a list")
        screens[name] = ScreenSpec(name, sources, tuple(_row(r, f"{where}.rows[{i}]", sources) for i, r in enumerate(rows)))
    p = _mapping(
        d["patient"],
        "patient",
        {"screen", "response", "dob", "sex_at_birth", "sex_values", "status", "include_statuses", "last_visit"},
        {"screen", "response", "dob", "sex_at_birth", "sex_values"},
    )
    if p["screen"] not in screens:
        raise MappingError(f"patient.screen: {p['screen']!r} isn't one of the screens")
    sex_values = p["sex_values"]
    if not isinstance(sex_values, dict) or not set(sex_values.values()) <= {"F", "M"}:
        raise MappingError("patient.sex_values: map each EMR value to F or M")
    include = p.get("include_statuses")
    if ("status" in p) != (include is not None):
        raise MappingError("patient: status and include_statuses go together")
    patient = PatientSpec(
        screen=p["screen"],
        response=_regex(p["response"], "patient.response"),
        dob=str(p["dob"]),
        sex_at_birth=str(p["sex_at_birth"]),
        sex_values={str(k): v for k, v in sex_values.items()},
        status=str(p["status"]) if "status" in p else None,
        include_statuses=tuple(str(x).lower() for x in include or ()),
        last_visit=str(p["last_visit"]) if p.get("last_visit") else None,
    )
    return FactsMapping(str(d["name"]), patient, screens, d.get("date_format"))


def load_mapping(path: str | Path) -> FactsMapping:
    path = Path(path)
    try:
        return parse_mapping(yaml.safe_load(path.read_text()))
    except MappingError as e:
        raise MappingError(f"{path.name}: {e}") from None
