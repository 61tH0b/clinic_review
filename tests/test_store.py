import sqlite3

import pytest
from cryptography.exceptions import InvalidTag

from clinic_review.store import RawStore, StaticKeyProvider


def test_roundtrip_and_sealed_on_disk(store, tmp_path):
    store.start_run("r1", "charts", "s", "fake")
    store.add_capture(
        run_id="r1", chr_id="1001", screen="labs", url="http://emr/api/patients/1001/labs",
        status=200, content_type="application/json", body=b'{"marker":"SYNTHETIC-VALUE"}',
    )
    [cap] = store.captures("1001")
    assert cap.body == b'{"marker":"SYNTHETIC-VALUE"}'
    assert cap.url.endswith("/labs")
    raw = (tmp_path / "store.db").read_bytes()
    assert b"SYNTHETIC-VALUE" not in raw
    assert b"/api/patients" not in raw


def test_body_bound_to_its_row(store, tmp_path):
    store.start_run("r1", "charts", "s", "fake")
    store.add_capture(
        run_id="r1", chr_id="1001", screen="labs", url="u", status=200, content_type=None, body=b"x",
    )
    db = sqlite3.connect(tmp_path / "store.db")
    db.execute("UPDATE captures SET chr_id = '1002'")
    db.commit()
    with pytest.raises(InvalidTag):
        list(store.captures("1002"))


def test_wrong_key_cannot_read(tmp_path):
    a = RawStore(tmp_path / "s.db", StaticKeyProvider(bytes(32)))
    a.start_run("r1", "charts", "s", "fake")
    a.add_capture(run_id="r1", chr_id="1", screen="x", url="u", status=200, content_type=None, body=b"b")
    a.close()
    b = RawStore(tmp_path / "s.db", StaticKeyProvider(bytes([1]) * 32))
    with pytest.raises(InvalidTag):
        list(b.captures("1"))
    b.close()


def test_progress_is_per_sweep(store):
    store.mark_done("sweep-a", "charts", "1001", "r1")
    assert store.done_ids("sweep-a", "charts") == {"1001"}
    assert store.done_ids("sweep-b", "charts") == set()
    assert store.done_ids("sweep-a", "roster") == set()
