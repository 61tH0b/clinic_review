"""Attach to the Chrome the clinician started and logged into.

The walker never handles credentials or 2FA. The clinician starts a dedicated Chrome
profile with remote debugging on the loopback interface, logs in to the EMR by hand, and
the walker attaches over CDP and works in a tab of its own.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, sync_playwright

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _require_loopback(cdp_url: str) -> None:
    host = urlsplit(cdp_url).hostname
    if host not in LOOPBACK:
        raise ValueError(f"refusing to attach to {host!r}: the debugging endpoint must be on this machine")


@contextmanager
def attach_context(cdp_url: str) -> Iterator[BrowserContext]:
    _require_loopback(cdp_url)
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("Chrome has no open profile to attach to")
        yield browser.contexts[0]
    finally:
        pw.stop()  # disconnects; the clinician's Chrome keeps running


@contextmanager
def attach(cdp_url: str) -> Iterator[Page]:
    """A new tab in the clinician's logged-in Chrome, closed on exit."""
    with attach_context(cdp_url) as context:
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()
