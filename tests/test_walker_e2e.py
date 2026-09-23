"""End-to-end: the walker attached over CDP to a real Chromium, walking the fake EMR."""
from __future__ import annotations

import dataclasses
import io
import json

import pytest

from clinic_review.store import ROSTER_ID
from clinic_review.walker import Walker
from clinic_review.walker.record import Recorder
from clinic_review.walker.session import attach, attach_context

from fake_emr import FAKE_PDF, PATIENT_IDS

pytestmark = pytest.mark.browser


def test_roster_then_charts(cdp_url, profile, store, fake_emr):
    with attach(cdp_url) as page:
        walker = Walker(page, profile, store)
        roster = walker.roster_pass()
        assert roster.complete, roster.detail
        assert store.roster_ids() == PATIENT_IDS
        assert roster.patients_done == len(PATIENT_IDS)

        charts = walker.chart_pass()
        assert charts.complete, charts.detail
        assert charts.patients_done == len(PATIENT_IDS)

    [summary] = list(store.captures("1003", "summary"))
    assert json.loads(summary.body)["patient_id"] == "1003"
    [labs] = list(store.captures("1003", "labs"))
    assert json.loads(labs.body)["results"][0]["name"] == "HbA1c"
    files = list(store.captures("1003", "files"))
    assert {c.content_type.split(";")[0] for c in files} == {"application/json", "application/pdf"}
    assert any(c.body == FAKE_PDF for c in files)
    # Unrelated traffic on the same pages is never kept
    assert not any("notifications" in c.url for pid in PATIENT_IDS for c in store.captures(pid))
    assert list(store.captures(ROSTER_ID))
    # The canary chart is checked but never stored
    assert not list(store.captures("5000"))


def test_walker_never_sends_its_own_requests(cdp_url, profile, store, fake_emr):
    """Every API call the server sees is one the fake EMR's own page would make."""
    with attach(cdp_url) as page:
        Walker(page, profile, store).chart_pass(patient_ids=["1001"])
    api_calls = [r for r in fake_emr.requests if r.startswith("/api/")]
    allowed = ("/api/notifications", "/api/patients/5000", "/api/patients/1001", "/api/files/")
    assert api_calls and all(r.startswith(allowed) for r in api_calls)


def test_wrong_patient_stops_the_run_and_keeps_nothing(cdp_url, profile, store, fake_emr):
    fake_emr.state["wrong_patient"] = "1002"
    with attach(cdp_url) as page:
        result = Walker(page, profile, store).chart_pass(patient_ids=["1001", "1002", "1003"])
    assert result.stopped == "wrong_patient"
    assert list(store.captures("1001", "labs"))
    assert not list(store.captures("1002"))
    assert not list(store.captures("1003"))
    assert store.done_ids("current", "charts") == {"1001"}


def test_logged_out_stops_and_resume_picks_up(cdp_url, profile, store, fake_emr):
    with attach(cdp_url) as page:
        walker = Walker(page, profile, store)
        assert walker.chart_pass(patient_ids=["1001", "1002"]).complete
        fake_emr.state["logged_out"] = True
        stopped = walker.chart_pass(patient_ids=["1001", "1002", "1003", "1004"])
        assert stopped.stopped == "logged_out"
        assert stopped.patients_done == 0

        fake_emr.state["logged_out"] = False
        resumed = walker.chart_pass(patient_ids=["1001", "1002", "1003", "1004"])
    assert resumed.complete
    assert resumed.patients_done == 2  # 1001 and 1002 were already done in this sweep
    assert store.done_ids("current", "charts") == {"1001", "1002", "1003", "1004"}


def test_screen_that_never_loads_stops_the_run(cdp_url, profile, store, fake_emr):
    fake_emr.state["hang_labs"] = "1002"
    fake_emr.state["hang_seconds"] = 4
    fast = dataclasses.replace(profile, pacing=dataclasses.replace(profile.pacing, screen_timeout_ms=1200))
    with attach(cdp_url) as page:
        result = Walker(page, fast, store).chart_pass(patient_ids=["1001", "1002"], screens=["labs"])
    assert result.stopped == "screen_failed"
    assert store.done_ids("current", "charts") == {"1001"}


def test_self_check_fails_when_canary_breaks(cdp_url, profile, store, fake_emr):
    fake_emr.state["wrong_patient"] = "5000"
    canary_on_labs = dataclasses.replace(profile, roster_screens=("labs",))
    with attach(cdp_url) as page:
        result = Walker(page, canary_on_labs, store).chart_pass(patient_ids=["1001"])
    assert result.stopped == "self_check_failed"
    assert result.patients_done == 0


def test_outside_window_stops_before_any_chart(cdp_url, profile, store, fake_emr):
    from datetime import datetime, time

    daytime = dataclasses.replace(
        profile, pacing=dataclasses.replace(profile.pacing, window_start=time(19, 0), window_end=time(6, 0))
    )
    with attach(cdp_url) as page:
        walker = Walker(page, daytime, store, clock=lambda: datetime(2026, 9, 23, 12, 0))
        result = walker.chart_pass(patient_ids=["1001"])
    assert result.stopped == "outside_window"
    assert not list(store.captures("1001"))


def test_recorder_keeps_shapes_not_values(cdp_url, fake_emr):
    out = io.StringIO()
    with attach_context(cdp_url) as context:
        recorder = Recorder(out)
        recorder.watch(context)
        page = context.new_page()
        try:
            page.goto(fake_emr.url + "/#/patients/1004/labs")
            page.wait_for_timeout(800)
            page.goto(fake_emr.url + "/#/patients/1004/files")
            page.wait_for_timeout(800)
        finally:
            page.close()
    text = out.getvalue()
    lines = [json.loads(line) for line in text.splitlines()]
    labs = next(line for line in lines if line["response"] == "/api/patients/{id}/labs")
    assert labs["page"] == "/#/patients/{id}/labs"
    assert labs["shape"]["results"] == [{"id": "str", "name": "str", "patient_id": "str", "value": "str"}]
    assert any(line["content_type"] == "application/pdf" for line in lines)
    assert "1004" not in text and "HbA1c" not in text
