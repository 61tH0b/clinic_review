"""Read one patient's captures from a sweep into demographics and Observation rows.

Only JSON responses are read here. PDFs wait for OCR and extraction (PLAN section 7).
Problems reading a row (a date that won't parse, a missing field) become skips, like the
concept layer's, so they land on the same curation list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from ..concepts.layer import Observation, Skip
from ..store.raw_store import Capture, RawStore
from .mapping import SEEN, FactsMapping, RowSpec


@dataclass(frozen=True)
class Chart:
    chr_id: str
    dob: date | None
    sex_at_birth: str | None
    status: str | None
    last_visit: date | None
    observations: tuple[Observation, ...]
    searched: frozenset[str]
    issues: tuple[Skip, ...]


def get_path(doc: Any, path: str) -> Any:
    """Dotted path into JSON; numeric parts index lists. "" is the document itself."""
    if path == "":
        return doc
    for part in path.split("."):
        if isinstance(doc, dict):
            doc = doc.get(part)
        elif isinstance(doc, list) and part.isdigit() and int(part) < len(doc):
            doc = doc[int(part)]
        else:
            return None
        if doc is None:
            return None
    return doc


def parse_date(value: Any, fmt: str | None) -> date | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        if fmt:
            return datetime.strptime(text, fmt).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _json(capture: Capture) -> Any:
    if not (capture.content_type or "").split(";")[0].strip().endswith("json"):
        return None
    try:
        return json.loads(capture.body)
    except ValueError:
        return None


def _rows(spec: RowSpec, screen: str, doc: Any, seen_on: date, fmt: str | None, issues: list[Skip]) -> list[Observation]:
    items = get_path(doc, spec.items)
    if not isinstance(items, list):
        issues.append(Skip(screen, spec.source or "", f"{screen}: no list at {spec.items or 'top level'}"))
        return []
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        f = spec.fields
        row_id = get_path(item, f["id"][0]) if "id" in f else None
        oid = f"{screen}:{row_id if row_id not in (None, '') else i}"
        if spec.source_by is not None:
            source = spec.source_values.get(str(get_path(item, spec.source_by)))
            if source is None:
                issues.append(Skip(oid, "", f"{screen}: {spec.source_by} value isn't in source_values"))
                continue
        else:
            source = spec.source
        when = None
        if "date" in f:
            if f["date"][0] == SEEN:
                when = seen_on
            else:
                raw = get_path(item, f["date"][0])
                when = parse_date(raw, fmt)
                if raw not in (None, "") and when is None:
                    issues.append(Skip(oid, source, f"{screen}: date didn't parse"))

        def text_of(key: str) -> str | None:
            if key not in f:
                return None
            parts = [get_path(item, p) for p in f[key]]
            joined = " ".join(str(p) for p in parts if p not in (None, ""))
            return joined or None

        out.append(
            Observation(
                source=source,
                id=oid,
                date=when,
                code=text_of("code"),
                text=text_of("text"),
                lab_name=text_of("lab_name"),
                result=text_of("result"),
                next_due=parse_date(get_path(item, f["next_due"][0]), fmt) if "next_due" in f else None,
            )
        )
    return out


def read_chart(store: RawStore, mapping: FactsMapping, chr_id: str, sweep: str) -> Chart:
    screens = store.sweep_captures(chr_id, sweep)
    ok = store.screens_ok(chr_id, sweep)
    searched = frozenset(s for name in ok if name in mapping.screens for s in mapping.screens[name].sources)
    issues: list[Skip] = []
    observations: list[Observation] = []

    dob = sex = status = last_visit = None
    p = mapping.patient
    for cap in screens.get(p.screen, []):
        if not p.response.search(urlsplit(cap.url).path):
            continue
        doc = _json(cap)
        if not isinstance(doc, dict):
            continue
        dob = parse_date(get_path(doc, p.dob), mapping.date_format)
        sex = p.sex_values.get(str(get_path(doc, p.sex_at_birth)))
        if p.status:
            raw = get_path(doc, p.status)
            status = str(raw).lower() if raw is not None else None
        if p.last_visit:
            last_visit = parse_date(get_path(doc, p.last_visit), mapping.date_format)
        break

    for name, caps in screens.items():
        spec = mapping.screens.get(name)
        if spec is None or name not in ok:
            continue
        for cap in caps:
            path = urlsplit(cap.url).path
            for row in spec.rows:
                if row.response.search(path):
                    doc = _json(cap)
                    if doc is not None:
                        # The Mac's local date: an evening walk in BC is already tomorrow in UTC
                        seen_on = datetime.fromisoformat(cap.captured_at).astimezone().date()
                        observations.extend(_rows(row, name, doc, seen_on, mapping.date_format, issues))
    return Chart(chr_id, dob, sex, status, last_visit, tuple(observations), searched, tuple(issues))
