# clinic_review

Panel-wide screening and care-gap review for Bonne Vie Medical Clinic (Coquitlam, BC) on TELUS Collaborative Health Record. It covers ages 0 to 100, using BC rules.

- [`docs/PLAN.md`](docs/PLAN.md): how it works, including guardrails, data access, rules engine, validation, phasing, and open decisions
- [`docs/screening-catalog.md`](docs/screening-catalog.md): every rule by life stage, with a BC source for each
- [`docs/sources.md`](docs/sources.md): primary sources, checked 2026-09-22

**No patient data goes in this repo.** It holds rules, value sets, code, and synthetic test patients only. Exports and outputs stay on the encrypted clinic Mac.
