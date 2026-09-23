"""The chart walker.

It opens chart screens in the clinician's own logged-in Chrome, one patient at a time, and
keeps the responses the EMR's own pages fetch to draw each screen. It never sends a request
of its own: navigation is a page view (the same URL a person would click to), and response
bodies are read over CDP as they pass through to the page, not fetched again.

It's read-only by construction. Nothing here clicks, types, saves, signs, sends or books.
"""
from __future__ import annotations

import base64
import logging
import random
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import CDPSession, Page

from ..store import ROSTER_ID, RawStore
from .guard import Verdict, parse_json, verdict
from .pacing import in_window, pause_seconds
from .profile import Profile, Screen

log = logging.getLogger(__name__)


class WalkerStop(Exception):
    reason = "stopped"


class LoggedOut(WalkerStop):
    reason = "logged_out"


class WrongPatient(WalkerStop):
    reason = "wrong_patient"


class ScreenFailed(WalkerStop):
    reason = "screen_failed"


class OutsideWindow(WalkerStop):
    reason = "outside_window"


class SelfCheckFailed(WalkerStop):
    reason = "self_check_failed"


class _LoadTimeout(Exception):
    pass


@dataclass(frozen=True)
class _Hit:
    index: int
    url: str
    status: int
    content_type: str | None
    body: bytes | None


@dataclass
class PassResult:
    run_id: str
    patients_done: int = 0
    screens: int = 0
    kept: int = 0
    dropped: int = 0
    stopped: str | None = None
    detail: str | None = None

    @property
    def complete(self) -> bool:
        return self.stopped is None


def _read_paused(cdp: CDPSession, index: int, url: str, event: dict) -> _Hit:
    status = int(event.get("responseStatusCode") or 0)
    headers = {h["name"].lower(): h["value"] for h in event.get("responseHeaders") or []}
    body: bytes | None
    try:
        res = cdp.send("Fetch.getResponseBody", {"requestId": event["requestId"]})
        raw = res.get("body", "")
        body = base64.b64decode(raw) if res.get("base64Encoded") else raw.encode()
    except PlaywrightError:
        body = None
    declared = headers.get("content-length")
    if body is not None and declared and declared.isdigit() and len(body) != int(declared):
        body = None  # truncated or unreadable: never keep a partial body
    return _Hit(index, url, status, headers.get("content-type"), body)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dig(doc, dotted: str):
    node = doc
    for part in dotted.split(".") if dotted else []:
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


class Walker:
    def __init__(
        self,
        page: Page,
        profile: Profile,
        store: RawStore,
        *,
        sweep: str = "current",
        ignore_window: bool = False,
        clock: Callable[[], datetime] = datetime.now,
        rng: random.Random | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.page = page
        self.profile = profile
        self.store = store
        self.sweep = sweep
        self.ignore_window = ignore_window
        self.clock = clock
        self.rng = rng or random.Random()
        self._sleep = sleep or (lambda seconds: page.wait_for_timeout(seconds * 1000))

    # passes

    def roster_pass(self, limit: int | None = None) -> PassResult:
        """Page through the patient list, then open each patient's roster screens (chart header)."""
        result = self._begin("roster")
        try:
            self._self_check()
            ids = self._walk_roster_pages(result)
            self._visit_patients(result, "roster", ids, self.profile.roster_screens, limit)
        except WalkerStop as stop:
            self._stopped(result, stop)
        finally:
            self.store.finish_run(result.run_id, result.stopped or "complete")
        return result

    def chart_pass(
        self,
        patient_ids: Iterable[str] | None = None,
        screens: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> PassResult:
        """Open the chart screens for each patient. Defaults to everyone on the stored roster."""
        result = self._begin("charts")
        names = tuple(screens) if screens is not None else self.profile.chart_screens
        for name in names:
            if name not in self.profile.screens:
                raise ValueError(f"unknown screen {name!r}")
        ids = list(patient_ids) if patient_ids is not None else self.store.roster_ids()
        try:
            self._self_check()
            self._visit_patients(result, "charts", ids, names, limit)
        except WalkerStop as stop:
            self._stopped(result, stop)
        finally:
            self.store.finish_run(result.run_id, result.stopped or "complete")
        return result

    # internals

    def _begin(self, kind: str) -> PassResult:
        run_id = f"{kind}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
        self.store.start_run(run_id, kind, self.sweep, self.profile.name)
        log.info("run %s started (sweep %s)", run_id, self.sweep)
        return PassResult(run_id=run_id)

    def _stopped(self, result: PassResult, stop: WalkerStop) -> None:
        result.stopped = stop.reason
        result.detail = str(stop)
        log.warning("run %s stopped: %s (%s)", result.run_id, stop.reason, stop)

    def _check_window(self) -> None:
        pacing = self.profile.pacing
        if not self.ignore_window and not in_window(self.clock(), pacing.window_start, pacing.window_end):
            raise OutsideWindow("outside the off-hours window; resume later from the same sweep")

    def _pause(self) -> None:
        seconds = pause_seconds(self.profile.pacing, self.rng)
        if seconds > 0:
            self._sleep(seconds)

    def _check_logged_in(self) -> None:
        url = self.page.url
        for pattern in self.profile.logged_out_url_patterns:
            if re.search(pattern, url):
                raise LoggedOut("the EMR session ended; log in again in the walker's Chrome and resume")
        selector = self.profile.logged_out_selector
        if selector:
            try:
                present = self.page.locator(selector).count() > 0
            except PlaywrightError:
                present = False  # mid-navigation; the next poll checks again
            if present:
                raise LoggedOut("login screen showing; log in again in the walker's Chrome and resume")

    def _page_on_patient(self, patient_id: str) -> bool:
        token = re.escape(quote(patient_id, safe=""))
        return re.search(rf"(?<![0-9A-Za-z]){token}(?![0-9A-Za-z])", self.page.url) is not None

    def _load(self, url: str, patterns: list[re.Pattern[str]], required: set[int]) -> list[_Hit]:
        """Open `url` and collect matching responses until the screen settles.

        Bodies are read at the response stage over CDP (Fetch domain), before the page
        consumes them. The request is still the page's own; the walker only reads the
        response on its way through and passes it on unchanged. Reading afterwards
        (Network.getResponseBody) returns empty bodies for some types on current Chrome.
        """
        pacing = self.profile.pacing
        hits: list[_Hit] = []
        last_hit = [time.monotonic()]
        cdp = self.page.context.new_cdp_session(self.page)

        def on_paused(event: dict) -> None:
            request_id = event["requestId"]
            try:
                req_url = event["request"]["url"]
                for i, pattern in enumerate(patterns):
                    if pattern.search(req_url):
                        hits.append(_read_paused(cdp, i, req_url, event))
                        last_hit[0] = time.monotonic()
                        break
            finally:
                try:
                    cdp.send("Fetch.continueResponse", {"requestId": request_id})
                except PlaywrightError:
                    pass  # page navigated away; the request is gone

        cdp.on("Fetch.requestPaused", on_paused)
        cdp.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "resourceType": t, "requestStage": "Response"} for t in ("XHR", "Fetch")]},
        )
        try:
            try:
                if self.page.url == url:
                    self.page.reload(wait_until="domcontentloaded")
                else:
                    self.page.goto(url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                raise _LoadTimeout(f"navigation failed: {exc.message.splitlines()[0]}") from None
            started = time.monotonic()
            last_hit[0] = max(last_hit[0], started)
            while True:
                self._check_logged_in()
                seen = {h.index for h in hits}
                now = time.monotonic()
                if required <= seen and (now - last_hit[0]) * 1000 >= pacing.settle_ms:
                    break
                if (now - started) * 1000 >= pacing.screen_timeout_ms:
                    raise _LoadTimeout(f"{len(required - seen)} expected response(s) never arrived")
                self.page.wait_for_timeout(100)
        finally:
            try:
                cdp.send("Fetch.disable")
                cdp.detach()
            except PlaywrightError:
                pass
        return list(hits)

    def _load_with_retries(self, url: str, patterns: list[re.Pattern[str]], required: set[int]) -> list[_Hit]:
        last: _LoadTimeout | None = None
        for _ in range(max(1, self.profile.screen_attempts)):
            try:
                return self._load(url, patterns, required)
            except _LoadTimeout as exc:
                last = exc
        raise last  # type: ignore[misc]

    def _judge(self, screen: Screen, patient_id: str, hits: list[_Hit]) -> tuple[list[_Hit], int, int]:
        """Split hits into (keep, dropped, mismatched)."""
        on_patient = self._page_on_patient(patient_id)
        keep: list[_Hit] = []
        dropped = mismatched = 0
        for hit in hits:
            if hit.body is None or not 200 <= hit.status < 300:
                dropped += 1
                continue
            v = verdict(
                expected_id=patient_id,
                url_binds_patient=screen.binds_patient(hit.index),
                doc=parse_json(hit.body, hit.content_type),
                patient_id_keys=self.profile.patient_id_keys,
                page_on_patient=on_patient,
                allow_unbound=screen.allow_unbound,
            )
            if v is Verdict.OK:
                keep.append(hit)
            else:
                dropped += 1
                mismatched += v is Verdict.MISMATCH
        return keep, dropped, mismatched

    def _visit(self, result: PassResult, patient_id: str, screen: Screen) -> None:
        started = _utc_now()
        patterns = screen.patterns(patient_id)
        required = {i for i, p in enumerate(screen.capture) if p not in screen.optional}
        try:
            hits = self._load_with_retries(screen.url(self.profile.base_url, patient_id), patterns, required)
        except _LoadTimeout as exc:
            self.store.audit(
                run_id=result.run_id, chr_id=patient_id, screen=screen.name,
                started_at=started, kept=0, dropped=0, outcome="failed",
            )
            raise ScreenFailed(f"{screen.name} for {patient_id} didn't load: {exc}") from None

        keep, dropped, mismatched = self._judge(screen, patient_id, hits)
        if mismatched:
            # One conflicting id makes the whole visit suspect. Keep nothing from it.
            self.store.audit(
                run_id=result.run_id, chr_id=patient_id, screen=screen.name,
                started_at=started, kept=0, dropped=len(hits), outcome="wrong_patient",
            )
            raise WrongPatient(
                f"{screen.name} for {patient_id} returned another patient's data; nothing from this screen was kept"
            )
        for hit in keep:
            self.store.add_capture(
                run_id=result.run_id, chr_id=patient_id, screen=screen.name, url=hit.url,
                status=hit.status, content_type=hit.content_type, body=hit.body or b"",
            )
        self.store.audit(
            run_id=result.run_id, chr_id=patient_id, screen=screen.name,
            started_at=started, kept=len(keep), dropped=dropped, outcome="ok",
        )
        result.screens += 1
        result.kept += len(keep)
        result.dropped += dropped
        log.info("%s %s: kept %d, dropped %d", patient_id, screen.name, len(keep), dropped)

    def _visit_patients(
        self, result: PassResult, pass_name: str, ids: list[str], screens: Iterable[str], limit: int | None
    ) -> None:
        done = self.store.done_ids(self.sweep, pass_name)
        todo = [pid for pid in ids if pid not in done]
        if limit is not None:
            todo = todo[:limit]
        for pid in todo:
            self._check_window()
            for name in screens:
                self._visit(result, pid, self.profile.screens[name])
                self._pause()
            self.store.mark_done(self.sweep, pass_name, pid, result.run_id)
            result.patients_done += 1

    def _walk_roster_pages(self, result: PassResult) -> list[str]:
        roster = self.profile.roster
        pattern = roster.pattern()
        ids: list[str] = []
        seen: set[str] = set()
        for page_no in range(roster.first_page, roster.first_page + roster.max_pages):
            self._check_window()
            try:
                hits = self._load_with_retries(roster.url(self.profile.base_url, page_no), [pattern], {0})
            except _LoadTimeout as exc:
                raise ScreenFailed(f"patient list page {page_no} didn't load: {exc}") from None
            page_ids: list[str] = []
            for hit in hits:
                if hit.body is None or not 200 <= hit.status < 300:
                    continue
                items = _dig(parse_json(hit.body, hit.content_type), roster.items_path) or []
                page_ids += [str(item[roster.id_field]) for item in items if isinstance(item, dict) and roster.id_field in item]
                self.store.add_capture(
                    run_id=result.run_id, chr_id=ROSTER_ID, screen=f"list:{page_no}", url=hit.url,
                    status=hit.status, content_type=hit.content_type, body=hit.body,
                )
            new = [pid for pid in page_ids if pid not in seen]
            if not new:
                break
            ids += new
            seen.update(new)
            log.info("patient list page %d: %d patients", page_no, len(new))
            self._pause()
        self.store.upsert_roster(ids)
        return ids

    def _self_check(self) -> None:
        """Open the canary chart and make sure capture and the patient guard both work."""
        pid = self.profile.canary_patient_id
        if pid is None:
            return
        names = self.profile.roster_screens or self.profile.chart_screens
        screen = self.profile.screens[names[0]]
        patterns = screen.patterns(pid)
        required = {i for i, p in enumerate(screen.capture) if p not in screen.optional}
        try:
            hits = self._load_with_retries(screen.url(self.profile.base_url, pid), patterns, required)
        except _LoadTimeout as exc:
            raise SelfCheckFailed(f"canary chart didn't load: {exc}") from None
        keep, _, mismatched = self._judge(screen, pid, hits)
        if mismatched or not keep:
            raise SelfCheckFailed(
                "canary chart didn't produce clean captures; the EMR may have changed. Recheck the profile."
            )
        log.info("self-check passed on the canary chart")
