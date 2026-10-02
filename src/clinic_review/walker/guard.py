"""Wrong-patient guard.

Every captured response has to be provably about the chart the walker opened, or it's
dropped. Evidence, strongest first:

1. The response URL matched a capture pattern that contains the patient id.
2. The JSON body carries the patient id under one of the profile's patient_id_keys,
   and every such value equals the expected id.
3. The screen allows unbound captures (a PDF fetched by file id) and the page URL is
   still on this patient's chart.

Any patient-id value in the body that differs from the expected one is a mismatch,
even if the URL looked right. Mismatches are never stored.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any, Iterable


class Verdict(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    UNBOUND = "unbound"


def ids_under_keys(doc: Any, keys: Iterable[str], max_depth: int = 4) -> set[str]:
    """Collect every value stored under any of `keys`, searching nested objects and lists."""
    keyset = set(keys)
    found: set[str] = set()

    def walk(node: Any, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keyset and isinstance(v, (str, int)) and not isinstance(v, bool):
                    found.add(str(v))
                walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1)

    walk(doc, 0)
    return found


def parse_json(body: bytes, content_type: str | None) -> Any | None:
    if content_type and "json" not in content_type.lower():
        return None
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def verdict(
    *,
    expected_id: str,
    url_binds_patient: bool,
    doc: Any | None,
    patient_id_keys: Iterable[str],
    page_on_patient: bool,
    allow_unbound: bool,
) -> Verdict:
    ids = ids_under_keys(doc, patient_id_keys) if doc is not None else set()
    if ids and ids != {expected_id}:
        return Verdict.MISMATCH
    if not page_on_patient:
        # The page wandered off this chart (redirect, login screen). Drop it; the
        # logged-out check decides whether the run stops.
        return Verdict.UNBOUND
    if url_binds_patient or ids:
        return Verdict.OK
    return Verdict.OK if allow_unbound else Verdict.UNBOUND
