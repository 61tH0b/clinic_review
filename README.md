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
