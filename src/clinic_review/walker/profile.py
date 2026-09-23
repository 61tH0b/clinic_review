"""Walker profile: everything EMR-specific the walker needs, loaded from YAML.

The real CHR profile (routes, response URL patterns, selectors) lives in local/ on the
clinic Mac and is gitignored. The only profile committed here is the fake EMR one under
tests/fixtures/, which doubles as the format reference.

Templates use literal placeholders, not str.format, so regexes like \\d{3} stay intact:
  {patient_id}  replaced with the patient's EMR id (regex-escaped inside capture patterns)
  {page}        replaced with the roster page number
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from urllib.parse import quote

import yaml

PATIENT = "{patient_id}"
PAGE = "{page}"


def _fill_route(template: str, patient_id: str | None = None, page: int | None = None) -> str:
    out = template
    if patient_id is not None:
        out = out.replace(PATIENT, quote(patient_id, safe=""))
    if page is not None:
        out = out.replace(PAGE, str(page))
    return out


def _fill_pattern(template: str, patient_id: str | None = None) -> re.Pattern[str]:
    if patient_id is not None:
        template = template.replace(PATIENT, re.escape(quote(patient_id, safe="")))
    return re.compile(template)


@dataclass(frozen=True)
class Screen:
    """One chart screen the walker opens, and which responses to keep while it loads."""

    name: str
    route: str
    capture: tuple[str, ...]
    optional: tuple[str, ...] = ()
    # Keep responses that carry no patient id of their own (e.g. a PDF fetched by file id),
    # as long as the page itself is still on this patient's chart.
    allow_unbound: bool = False

    def url(self, base_url: str, patient_id: str) -> str:
        return base_url.rstrip("/") + _fill_route(self.route, patient_id=patient_id)

    def patterns(self, patient_id: str) -> list[re.Pattern[str]]:
        return [_fill_pattern(p, patient_id) for p in self.capture]

    def required_patterns(self, patient_id: str) -> list[re.Pattern[str]]:
        return [_fill_pattern(p, patient_id) for p in self.capture if p not in self.optional]

    def binds_patient(self, pattern_index: int) -> bool:
        """True when the capture pattern itself contains the patient id."""
        return PATIENT in self.capture[pattern_index]


@dataclass(frozen=True)
class Roster:
    """How to page through the patient list."""

    route: str
    capture: str
    items_path: str
    id_field: str
    first_page: int = 1
    max_pages: int = 1000

    def url(self, base_url: str, page: int) -> str:
        return base_url.rstrip("/") + _fill_route(self.route, page=page)

    def pattern(self) -> re.Pattern[str]:
        return re.compile(self.capture)


@dataclass(frozen=True)
class Pacing:
    min_seconds: float = 3.0
    max_seconds: float = 6.0
    # Off-hours window in local time. May cross midnight. None on both ends means any time.
    window_start: time | None = time(19, 0)
    window_end: time | None = time(6, 0)
    # A screen counts as loaded once every required response has arrived and nothing
    # matching has arrived for settle_ms.
    settle_ms: int = 800
    screen_timeout_ms: int = 20_000


@dataclass(frozen=True)
class Profile:
    name: str
    base_url: str
    roster: Roster
    screens: dict[str, Screen]
    roster_screens: tuple[str, ...]
    chart_screens: tuple[str, ...]
    patient_id_keys: tuple[str, ...]
    logged_out_url_patterns: tuple[str, ...] = ()
    logged_out_selector: str | None = None
    canary_patient_id: str | None = None
    pacing: Pacing = field(default_factory=Pacing)
    screen_attempts: int = 2

    def __post_init__(self) -> None:
        for name in (*self.roster_screens, *self.chart_screens):
            if name not in self.screens:
                raise ValueError(f"profile {self.name!r} lists unknown screen {name!r}")
        if not self.patient_id_keys:
            raise ValueError("patient_id_keys can't be empty: the wrong-patient guard needs it")


def _time(value: str | None) -> time | None:
    if value is None:
        return None
    hh, mm = str(value).split(":")
    return time(int(hh), int(mm))


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def load_profile(path: str | Path) -> Profile:
    data = yaml.safe_load(Path(path).read_text())
    screens = {
        name: Screen(
            name=name,
            route=s["route"],
            capture=_tuple(s["capture"]),
            optional=_tuple(s.get("optional")),
            allow_unbound=bool(s.get("allow_unbound", False)),
        )
        for name, s in data["screens"].items()
    }
    r = data["roster"]
    roster = Roster(
        route=r["route"],
        capture=r["capture"],
        items_path=r["items_path"],
        id_field=r["id_field"],
        first_page=int(r.get("first_page", 1)),
        max_pages=int(r.get("max_pages", 1000)),
    )
    p = data.get("pacing", {})
    window = p.get("window") or {}
    pacing = Pacing(
        min_seconds=float(p.get("min_seconds", 3.0)),
        max_seconds=float(p.get("max_seconds", 6.0)),
        window_start=_time(window.get("start", "19:00")) if window != "any" else None,
        window_end=_time(window.get("end", "06:00")) if window != "any" else None,
        settle_ms=int(p.get("settle_ms", 800)),
        screen_timeout_ms=int(p.get("screen_timeout_ms", 20_000)),
    )
    logged_out = data.get("logged_out", {})
    return Profile(
        name=data["name"],
        base_url=data["base_url"],
        roster=roster,
        screens=screens,
        roster_screens=_tuple(data.get("roster_screens")),
        chart_screens=_tuple(data.get("chart_screens")),
        patient_id_keys=_tuple(data["patient_id_keys"]),
        logged_out_url_patterns=_tuple(logged_out.get("url_patterns")),
        logged_out_selector=logged_out.get("selector"),
        canary_patient_id=(str(data["canary_patient_id"]) if data.get("canary_patient_id") else None),
        pacing=pacing,
        screen_attempts=int(data.get("screen_attempts", 2)),
    )
