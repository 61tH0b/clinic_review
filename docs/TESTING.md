# Interactive test registry

Current state: 0.2.0 local CLI/library source, awaiting draft review; no deployment or
real-patient validation. `python -m clinic_review.report --version` identifies the
source SHA and commit time. HTML also shows UTC generation time. Rules remain shadow
and value sets draft; attestation evaluation is disabled pending Ali's policy.

Updated 2026-10-02 03:06 PDT.

| Title | Where to run | Description | Version/build | Status + date |
|---|---|---|---|---|
| Worklists, diffs, and feedback | [reporting commands](reporting.md) | Export a synthetic ledger to a fresh private folder outside Git; inspect audiences, evidence, phone numbers, diff states, and capture-only feedback | 0.2.0; source SHA/time from `--version`; generation time in HTML | Synthetic automated verification; Ali review pending, 2026-10-02 |
| Report acceptance suite | `python -m pytest tests/test_report.py` | Exercise synthetic routing, pipeline diffs, edge cases, escaping, feedback, and redaction | 0.2.0 | 49 tests pass, 2026-10-02 |
| Fake-EMR browser pipeline | `python -m pytest tests/test_pipeline.py::test_walk_then_evaluate` | Walk headless fake EMR, evaluate, and export the resulting ledger | 0.2.0 | Passes in the 241-test full suite, 2026-10-02 |

The repo's four required checks are `python -m pytest`,
`python -m clinic_review.engine check rules`, `python -m clinic_review.concepts check`,
and `python scripts/check_no_phi.py --all`. None of these authorizes real-data runs,
clinical enablement, PR merging, or a default-branch change.

All four checks passed locally on 2026-10-02: 241 tests (192 baseline plus 49 report
tests), 7 rules, 8 value sets/70 concepts with all 45 rule concepts defined, and the
PHI scan. This confirms synthetic behavior, not clinical sign-off or deployment.
