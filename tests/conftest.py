from __future__ import annotations

import dataclasses
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from clinic_review.store import RawStore, StaticKeyProvider  # noqa: E402
from clinic_review.walker import load_profile  # noqa: E402
from fake_emr import FakeEMR  # noqa: E402

PROFILE = Path(__file__).parent / "fixtures" / "fake_emr" / "profile.yaml"
TEST_KEY = bytes(range(32))  # test-only key


@pytest.fixture
def store(tmp_path):
    s = RawStore(tmp_path / "store.db", StaticKeyProvider(TEST_KEY))
    yield s
    s.close()


@pytest.fixture
def fake_emr():
    with FakeEMR() as emr:
        yield emr


@pytest.fixture
def profile(fake_emr):
    return dataclasses.replace(load_profile(PROFILE), base_url=fake_emr.url)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def cdp_url(tmp_path_factory):
    """A headless Chromium with remote debugging, standing in for the clinician's Chrome."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        executable = pw.chromium.executable_path
    port = _free_port()
    proc = subprocess.Popen(
        [
            executable,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp_path_factory.mktemp('chrome-profile')}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            urllib.request.urlopen(url + "/json/version", timeout=1).read()
            break
        except OSError:
            if time.monotonic() > deadline or proc.poll() is not None:
                proc.kill()
                pytest.skip("Chromium with remote debugging didn't start")
            time.sleep(0.2)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
