# clinic_review

Panel-wide screening and care-gap review for Bonne Vie Medical Clinic (Coquitlam, BC) on TELUS Collaborative Health Record. It covers ages 0 to 100, using BC rules. Browser automation reads charts on the clinic Mac, a local model extracts facts from reports and notes, and deterministic rules decide what's a gap.

- [`docs/PLAN.md`](docs/PLAN.md): how it works, including guardrails, the chart walker, the rules engine, validation, phasing, and open decisions
- [`docs/screening-catalog.md`](docs/screening-catalog.md): every rule by life stage, with a BC source for each
- [`docs/sources.md`](docs/sources.md): primary sources, checked 2026-09-22

## Nothing patient-level goes in this repo

This repo is public. It holds rules, value sets, code, and synthetic test patients only. Patient data, panel numbers, MRP status, patient lists, run outputs, model config, and the CHR-specific walker profile stay on the clinic Mac.

Turn on the guard after cloning:

```sh
git config core.hooksPath .githooks
```

The pre-commit hook runs `scripts/check_no_phi.py`, which blocks anything that passes the BC PHN check and any data-type file (CSV, PDF, HL7, SQLite and similar). CI runs the same check on every push.

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest
```

The walker tests drive a real headless Chromium against a fake CHR-like app with synthetic patients (`tests/fake_emr.py`).

## Running the walker on the clinic Mac

Run this under the separate data account (PLAN.md section 2), never the dev account.

```sh
pip install -e ".[mac]"      # adds keyring, so the store key lives in the macOS Keychain

# 1. Start the walker's own Chrome profile with debugging on loopback, then log in to CHR by hand
open -na "Google Chrome" --args --user-data-dir="$HOME/ClinicReview/chrome-walker" --remote-debugging-port=9222

# 2. Phase 0: click through a few test charts while this records routes and response shapes (no values)
python -m clinic_review.walker record --out local/phase0-map.jsonl

# 3. Write local/chr-profile.yaml from that map, using tests/fixtures/fake_emr/profile.yaml as the template

# 4. Pilot: roster pass on 50 patients, then their charts
python -m clinic_review.walker roster --profile local/chr-profile.yaml --store "$HOME/ClinicReview/store.db" --limit 50
python -m clinic_review.walker charts --profile local/chr-profile.yaml --store "$HOME/ClinicReview/store.db" --limit 50
python -m clinic_review.walker status --store "$HOME/ClinicReview/store.db"
```

Runs only happen inside the profile's off-hours window unless you pass `--ignore-window`. A stopped run (logged out, wrong patient, a screen that won't load, a failed canary check) resumes where it left off when you run the same command again. Use `--sweep NAME` to start a fresh baseline.
