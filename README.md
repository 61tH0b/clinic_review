# clinic_review

Panel-wide screening and care-gap review for Bonne Vie Medical Clinic (Coquitlam, BC) on TELUS Collaborative Health Record. It covers ages 0 to 100, using BC rules. Browser automation reads charts on the clinic Mac, a local model extracts facts from reports and notes, and deterministic rules decide what's a gap.

- [`docs/PLAN.md`](docs/PLAN.md): how it works, including guardrails, the chart walker, the rules engine, validation, phasing, and open decisions
- [`docs/screening-catalog.md`](docs/screening-catalog.md): every rule by life stage, with a BC source for each
- [`docs/sources.md`](docs/sources.md): primary sources, checked 2026-09-22
- [`docs/HANDOFF.md`](docs/HANDOFF.md): what's built, ground rules, and the next work packages for whoever picks this up
- [`docs/TESTING.md`](docs/TESTING.md): local commands and the current review/version state
- [`docs/reporting.md`](docs/reporting.md): worklists, run diffs, and capture-only feedback

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

## Local worklists and run diffs (0.2.0)

WP1 adds `python -m clinic_review.report` (also `clinic-review-report` after installation).
It reads a finished ledger run without opening the raw-store key, and writes HTML/CSV
to a new caller-named local folder outside Git checkouts. Stdout contains counts only.
Rule titles and actions come from that run's snapshots; legacy runs need re-evaluation.
`--version` shows the source commit and its time; HTML shows that stamp and generation
time. A dirty checkout is labelled. This is local review software, with no deployment.

The feedback CSV captures done elsewhere, declined, or not applicable, plus a date
and optional note. `feedback-check` validates it against the selected run. It doesn't
change evaluation: attestation validity and rule-specific evidence mapping still need
Ali's decision. See [`docs/reporting.md`](docs/reporting.md) for the commands and gates.

## Rules

One YAML file per rule in [`rules/`](rules/), evaluated by `src/clinic_review/engine/`. [`rules/README.md`](rules/README.md) has the fields. The concept layer in [`valuesets/`](valuesets/) maps chart codes and text to the concepts rules read ([`valuesets/README.md`](valuesets/README.md)). After editing a rule or a value set:

```sh
python -m clinic_review.engine check rules   # validates every rule, fails on any past review_by
python -m clinic_review.concepts check       # validates value sets, fails if a rule reads an undefined concept
python -m pytest tests/test_engine.py tests/test_concepts.py
```

## Running the walker on the clinic Mac

Run this under the separate data account (PLAN.md section 2), never the dev account.

```sh
pip install -e ".[mac]"      # adds keyring, so the store key lives in the macOS Keychain

# 1. Start the walker's own Chrome profile with debugging on loopback, then log in to CHR by hand
open -na "Google Chrome" --args --user-data-dir="$HOME/ClinicReview/chrome-walker" --remote-debugging-port=9222

# 2. Phase 0: click through a few test charts while this records routes and response shapes (no values)
python -m clinic_review.walker record --out local/phase0-map.jsonl

# 3. Write local/chr-profile.yaml and local/chr-facts.yaml from that map, using the
#    tests/fixtures/fake_emr/ profile.yaml and facts.yaml as templates

# 4. Pilot: roster pass on 50 patients, then their charts
python -m clinic_review.walker roster --profile local/chr-profile.yaml --store "$HOME/ClinicReview/store.db" --limit 50
python -m clinic_review.walker charts --profile local/chr-profile.yaml --store "$HOME/ClinicReview/store.db" --limit 50
python -m clinic_review.walker status --store "$HOME/ClinicReview/store.db"

# 5. Check the denominator first, then run every rule. Both print aggregates only.
python -m clinic_review.pipeline evaluate --mapping local/chr-facts.yaml --store "$HOME/ClinicReview/store.db" --cohort-only
python -m clinic_review.pipeline evaluate --mapping local/chr-facts.yaml --store "$HOME/ClinicReview/store.db"
```

Runs only happen inside the profile's off-hours window unless you pass `--ignore-window`. A stopped run (logged out, wrong patient, a screen that won't load, a failed canary check) resumes where it left off when you run the same command again. Use `--sweep NAME` to start a fresh baseline.
