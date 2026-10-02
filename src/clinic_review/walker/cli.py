"""Command line for the chart walker.

    python -m clinic_review.walker record  --out local/phase0-map.jsonl
    python -m clinic_review.walker roster  --profile local/chr-profile.yaml --store PATH [--limit N]
    python -m clinic_review.walker charts  --profile local/chr-profile.yaml --store PATH [--limit N]
    python -m clinic_review.walker status  --store PATH

The store key comes from the macOS Keychain, or from CLINIC_REVIEW_STORE_KEY (base64)
when that's set.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from ..store import EnvKeyProvider, KeychainKeyProvider, RawStore
from .profile import load_profile
from .record import record
from .session import attach, attach_context
from .walker import Walker

DEFAULT_CDP = "http://127.0.0.1:9222"


def _store(path: str) -> RawStore:
    keys = EnvKeyProvider() if os.environ.get("CLINIC_REVIEW_STORE_KEY") else KeychainKeyProvider()
    return RawStore(path, keys)


def _run_pass(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    store = _store(args.store)
    try:
        with attach(args.cdp) as page:
            walker = Walker(page, profile, store, sweep=args.sweep, ignore_window=args.ignore_window)
            if args.command == "roster":
                result = walker.roster_pass(limit=args.limit)
            else:
                screens = args.screens.split(",") if args.screens else None
                result = walker.chart_pass(screens=screens, limit=args.limit)
    finally:
        store.close()
    print(
        f"{result.run_id}: {result.patients_done} patients, {result.screens} screens, "
        f"{result.kept} kept, {result.dropped} dropped"
    )
    if result.stopped:
        print(f"stopped: {result.stopped}. {result.detail}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clinic-review-walker")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="Phase 0: map screens to responses while a clinician clicks through")
    rec.add_argument("--cdp", default=DEFAULT_CDP)
    rec.add_argument("--out", required=True)

    for name, help_text in (
        ("roster", "page through the patient list and open each chart header"),
        ("charts", "open the chart screens for every patient on the stored roster"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--profile", required=True)
        p.add_argument("--store", required=True)
        p.add_argument("--cdp", default=DEFAULT_CDP)
        p.add_argument("--sweep", default="current", help="resume key; start a new name for a fresh baseline")
        p.add_argument("--limit", type=int, help="stop after this many patients (pilot runs)")
        p.add_argument("--ignore-window", action="store_true", help="run outside the off-hours window")
        if name == "charts":
            p.add_argument("--screens", help="comma-separated screen names; defaults to the profile's chart_screens")

    st = sub.add_parser("status", help="counts from the store, no patient data")
    st.add_argument("--store", required=True)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")

    if args.command == "record":
        with attach_context(args.cdp) as context:
            print("recording; click through the test charts, then press Ctrl-C", file=sys.stderr)
            lines = record(context, args.out)
        print(f"{lines} distinct responses written to {args.out}")
        return 0
    if args.command == "status":
        store = _store(args.store)
        try:
            for key, value in store.summary().items():
                print(f"{key}: {value}")
        finally:
            store.close()
        return 0
    return _run_pass(args)


if __name__ == "__main__":
    sys.exit(main())
