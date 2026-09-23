from datetime import datetime, time

import pytest

from clinic_review.walker.guard import Verdict, ids_under_keys, verdict
from clinic_review.walker.pacing import in_window
from clinic_review.walker.profile import load_profile

from conftest import PROFILE


def test_profile_loads_and_builds_urls():
    p = load_profile(PROFILE)
    labs = p.screens["labs"]
    assert labs.url("http://emr.test", "1001") == "http://emr.test/#/patients/1001/labs"
    [pat] = labs.patterns("1001")
    assert pat.search("http://emr.test/api/patients/1001/labs")
    assert not pat.search("http://emr.test/api/patients/10011/labs")
    assert labs.binds_patient(0)
    files = p.screens["files"]
    assert not files.binds_patient(1)
    assert len(files.required_patterns("1001")) == 1
    assert p.roster.url("http://emr.test", 3) == "http://emr.test/#/patients/page/3"
    assert p.pacing.window_start is None and p.pacing.window_end is None


def test_patient_id_is_escaped_in_patterns():
    p = load_profile(PROFILE)
    [pat] = p.screens["labs"].patterns("1.1")
    assert pat.search("/api/patients/1.1/labs")
    assert not pat.search("/api/patients/1x1/labs")


def test_unknown_screen_rejected(tmp_path):
    text = PROFILE.read_text().replace("chart_screens: [labs, files]", "chart_screens: [labs, nope]")
    bad = tmp_path / "bad.yaml"
    bad.write_text(text)
    with pytest.raises(ValueError, match="nope"):
        load_profile(bad)


def test_ids_under_keys_nested():
    doc = {"patient_id": "1", "results": [{"patient_id": "1", "id": "L9"}], "meta": {"x": {"patient_id": 1}}}
    assert ids_under_keys(doc, ["patient_id"]) == {"1"}


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(url_binds_patient=True, doc={"patient_id": "1"}, page_on_patient=True, allow_unbound=False), Verdict.OK),
        (dict(url_binds_patient=True, doc={"patient_id": "2"}, page_on_patient=True, allow_unbound=False), Verdict.MISMATCH),
        (dict(url_binds_patient=True, doc={"results": [{"patient_id": "1"}, {"patient_id": "2"}]}, page_on_patient=True, allow_unbound=False), Verdict.MISMATCH),
        (dict(url_binds_patient=False, doc={"patient_id": "1"}, page_on_patient=True, allow_unbound=False), Verdict.OK),
        (dict(url_binds_patient=False, doc=None, page_on_patient=True, allow_unbound=False), Verdict.UNBOUND),
        (dict(url_binds_patient=False, doc=None, page_on_patient=True, allow_unbound=True), Verdict.OK),
        (dict(url_binds_patient=True, doc={"patient_id": "1"}, page_on_patient=False, allow_unbound=True), Verdict.UNBOUND),
        (dict(url_binds_patient=True, doc={"patient_id": "2"}, page_on_patient=False, allow_unbound=True), Verdict.MISMATCH),
    ],
)
def test_verdict(kwargs, expected):
    assert verdict(expected_id="1", patient_id_keys=["patient_id"], **kwargs) is expected


@pytest.mark.parametrize(
    "now, start, end, inside",
    [
        (time(20, 0), time(19, 0), time(6, 0), True),
        (time(2, 0), time(19, 0), time(6, 0), True),
        (time(6, 0), time(19, 0), time(6, 0), False),
        (time(12, 0), time(19, 0), time(6, 0), False),
        (time(10, 0), time(9, 0), time(17, 0), True),
        (time(18, 0), time(9, 0), time(17, 0), False),
        (time(3, 0), None, None, True),
    ],
)
def test_in_window(now, start, end, inside):
    assert in_window(datetime.combine(datetime(2026, 9, 23), now), start, end) is inside
