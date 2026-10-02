"""Phase 0 recorder: map screens to the responses they load, without keeping any values.

A clinician clicks through a few test charts while this listens. For every JSON or PDF
response it writes one line: the page route and response path with ids replaced by {id},
the method, status, content type, and for JSON the shape of the body (keys and value
types only). No values, no query strings. The output is what the local walker profile
gets written from, and it stays on the clinic Mac.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, Response

ID_SEGMENT = re.compile(r"(?<![A-Za-z])(?:\d{2,}|[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-fA-F]{16,})(?![A-Za-z])")
MAX_KEYS = 80


def template(url: str) -> str:
    """Path and fragment only, with id-like segments replaced by {id}."""
    parts = urlsplit(url)
    out = parts.path or "/"
    if parts.fragment:
        out += "#" + parts.fragment.split("?", 1)[0]
    return ID_SEGMENT.sub("{id}", out)


def shape_of(value: Any, depth: int = 0, max_depth: int = 4) -> Any:
    if isinstance(value, dict):
        if depth >= max_depth:
            return "object"
        keys = sorted(value)[:MAX_KEYS]
        return {ID_SEGMENT.sub("{id}", str(k)): shape_of(value[k], depth + 1, max_depth) for k in keys}
    if isinstance(value, list):
        return [shape_of(value[0], depth + 1, max_depth)] if value else []
    if value is None:
        return "null"
    return type(value).__name__


class Recorder:
    def __init__(self, out: TextIO) -> None:
        self.out = out
        self._seen: set[str] = set()
        self.lines = 0

    def _on_response(self, page: Page, resp: Response) -> None:
        ctype = (resp.headers.get("content-type") or "").lower()
        if "json" not in ctype and "pdf" not in ctype:
            return
        entry: dict[str, Any] = {
            "page": template(page.url),
            "response": template(resp.url),
            "method": resp.request.method,
            "status": resp.status,
            "content_type": ctype.split(";")[0],
        }
        if "json" in ctype:
            try:
                entry["shape"] = shape_of(json.loads(resp.body()))
            except Exception:  # unreadable or not JSON after all
                entry["shape"] = "unreadable"
        line = json.dumps(entry, sort_keys=True)
        if line in self._seen:
            return
        self._seen.add(line)
        self.out.write(line + "\n")
        self.out.flush()
        self.lines += 1

    def watch_page(self, page: Page) -> None:
        page.on("response", lambda resp: self._on_response(page, resp))

    def watch(self, context: BrowserContext) -> None:
        for page in context.pages:
            self.watch_page(page)
        context.on("page", self.watch_page)


def record(context: BrowserContext, out_path: str | Path, poll_page: Page | None = None) -> int:
    """Record until interrupted (Ctrl-C). Returns the number of distinct lines written."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as out:
        recorder = Recorder(out)
        recorder.watch(context)
        pump = poll_page or (context.pages[0] if context.pages else context.new_page())
        try:
            while True:
                pump.wait_for_timeout(500)
        except KeyboardInterrupt:
            pass
        return recorder.lines
