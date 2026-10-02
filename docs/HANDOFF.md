# Handoff: clinic_review

Updated 2026-10-02 03:10 PDT for WP1 (0.2.0). Base `eccbccca258c1552667bc7c7719a5d84fdac963f`
on `claude/clinic-screening-gaps-plan-9hubbe` (PR #1, still open). The base had 192 passing
synthetic tests. WP1 status below is local verification; CI isn't inferred from local tests.

## WP1 status, 2026-10-02 03:10 PDT

- Built on `gpt/wp1-worklists-run-diff`, with rollback tag `pre-wp1` at the base.
- Local worklists: self-contained HTML plus CSV per audience/action, category B first,
  UNKNOWN tasks, pre-visit-only DISCUSS, outreach, rule status, dates, and evidence.
- New runs snapshot titles/actions/status/version; report reads are read-only. Legacy,
  unfinished, incomplete, and cohort-only runs are rejected. Run diffs keep missing
  evaluations separate from closure and flag digest changes.
- Feedback CSV capture/validation has strict columns, outcomes, dates, and result/version
  binding. It doesn't feed facts or change evaluation. **Acceptance blocked:** an
  attestation closing a gap on the next run needs Ali's validity and evidence policy.
- All four checks pass locally: 241 tests (192 baseline plus 49 report tests), 7 rules,
  8 value sets/70 concepts with all 45 rule concepts defined, and the PHI scan. Six
  logic mutations were detected and restored. Push/draft-PR status is recorded below.
- All data used here is synthetic. No walker or clinical rule changes; all clinical
  sign-off/audit gates remain. WP2 hasn't started. [reporting.md](reporting.md) and
  [wp1-design.md](wp1-design.md) describe the implementation and limitation.
- Deviation: shared queue checked read-only because this package's explicit repository
  boundary forbids sibling edits. Ownership is recorded in `TASKS.md`. No conflict found.
- Implementation `4e4d3f7` is pushed, authored by Aya Health Technologies Inc.
  <admin@autochart.ai>. [Draft PR #2](https://github.com/61tH0b/clinic_review/pull/2)
  targets the Claude base; it's attached to the review chat. No merge, default-branch
  change, clinical enablement, or WP2 work. As of this timestamp, CI rules/no-phi jobs
  pass and test jobs are running. Confirm the final head's CI before review/merge.

## Read these first, in this order

1. `README.md`: setup, the no-patient-data rule, how to run things.
2. `docs/PLAN.md`: section 2 (guardrails), section 4 (cohort), section 6 (rules, concept layer, engine), section 9 (validation), and section 10 (roadmap).
3. `docs/screening-catalog.md`: every rule to build, with a BC source. Section 9 holds decisions that are already locked; don't reopen them.
4. `rules/README.md` and `valuesets/README.md`: the two file formats, field by field.
5. The tests. They're the spec. `tests/test_engine.py`, `tests/test_concepts.py`, and `tests/test_pipeline.py` show every edge case the code is held to.

## Ground rules (non-negotiable)

1. **No patient data, ever.** Not in the repo, not in your context, not in test fixtures. Synthetic patients only. Never open the clinic data account, `~/ClinicReview/` (the encrypted `store.db` and the walker's Chrome profile), or any file holding real chart content.
2. **Never point the walker at a real EMR.** Don't attach to a real Chrome on port 9222, and don't run `walker roster`, `walker charts`, or `pipeline evaluate` against a real store. The fake EMR in `tests/fake_emr.py` is the only target.
3. **`local/` is gitignored and stays that way.** It holds the CHR walker profile, the CHR facts mapping, and model config. They aren't patient data, but they're CHR-specific and never get committed.
4. **Canadian residency for any model.** Patient content only ever goes to a local model on the Mac (MLX or Ollama) or Azure OpenAI Canada East with a regional deployment. Global and Data Zone deployments process outside Canada, so they're out. No other endpoint, ever.
5. **Don't weaken a guard.** These are deliberate and tested:
   - the PHN check (`scripts/check_no_phi.py`, in the pre-commit hook and in CI)
   - the read-only walker, the wrong-patient guard, and the canary self-check
   - sealed bodies in the store
   - a gap on an unwalked screen comes back `UNKNOWN`, never `NOT_FOUND`
   - exact-match lab results
   - requisitions never counting as reports
   - aggregates-only command line output

   A change that touches `walker/`, `guard.py`, or `store/` needs a test proving the guard still holds.
6. **The rule engine stays deterministic.** No LLM in rule evaluation. A model only appears in extraction, and only produces facts backed by an exact quote from the source.
7. **Strict formats.** Any new YAML format rejects unknown keys, the way rules and value sets do. Quote phrases and codes in YAML: a bare `no` loads as false, and a bare `042` loads as 34.
8. **Clinical choices go to Ali.** If a build needs a clinical judgment the catalog doesn't settle, stop and ask. Don't pick one quietly.

## Workflow

- **Branches:** one per work package, off `main` once PR #1 is merged (off `claude/clinic-screening-gaps-plan-9hubbe` until then). Open one draft PR per package.
- **Git safety:** never push to `main` and never force-push. Before a risky change, tag the current head (`git tag pre-<package>`).
- **Before every commit, all of these must pass:**
  ```sh
  python -m pytest
  python -m clinic_review.engine check rules
  python -m clinic_review.concepts check
  python scripts/check_no_phi.py --all
  ```
- **Hooks:** turn them on once with `git config core.hooksPath .githooks`.
- **Mutation check:** for new logic, break it on purpose and confirm a test fails. The existing suites were checked this way.
- **Commit messages:** no model names or identifiers.
- **Style:** match the surrounding code. Docstrings and comments explain why, not what. Docs are plain, direct prose with contractions.

## What exists

```
walker captures -> raw store -> fact store -> cohort -> concept layer + derived -> rules -> ledger
```

| Module | What it does | Entry point |
|---|---|---|
| `walker/` | Playwright over CDP into the clinician's own Chrome. Read-only, with response-stage capture, the wrong-patient guard, the canary check, off-hours pacing, and resume by sweep. Phase 0 recorder (route and JSON shape only). | `python -m clinic_review.walker record\|roster\|charts\|status` |
| `store/raw_store.py` | SQLite. URLs and bodies sealed with AES-256-GCM, bound to patient and screen. Key in the macOS Keychain. | `RawStore` |
| `store/ledger.py` | Per evaluation run: cohort group, rule results with evidence ids, skips, and a ruleset digest | `Ledger` |
| `facts/` | Captures to demographics and `Observation` rows, through an EMR-specific facts mapping (`tests/fixtures/fake_emr/facts.yaml` is the reference) | `read_chart` |
| `concepts/` | Value sets: MSP WHO ICD-9, text, labs, documents, plus extracted and derived concepts. Rows become facts; skips record why a row didn't map. | `ConceptLayer`, `python -m clinic_review.concepts check` |
| `engine/` | Strict YAML rules and the deterministic evaluator. Interval and loop rules, population, exclusions, requires, grace, the reported next-due date, declines, discuss mode. | `evaluate`, `python -m clinic_review.engine check rules` |
| `pipeline/` | Cohort split (PLAN 4), then every rule on the active cohort, then the ledger. Prints aggregates only. | `python -m clinic_review.pipeline evaluate` |
| `report/` | Read-only completed-run reports: local HTML/CSV worklists and run diffs, aggregate stdout, and capture-only feedback validation | `python -m clinic_review.report worklists\|diff\|feedback-check` |
| `rules/` | 7 rules, all `status: shadow` | |
| `valuesets/` | 8 files, 70 concepts, all `status: draft` | |

The base had 192 tests; WP1 adds 49, for 241. The 8 walker tests and the end-to-end
pipeline test drive a real headless Chromium against the fake EMR. The pipeline
browser test also exports its resulting worklists.

## Work packages, in recommended order

Each package gets its own branch and draft PR. Stop after each one with a summary, the test output, and anything that needs Ali's decision.

### WP1. Worklists and run diff (`src/clinic_review/report/`), moderate

Results are only useful once someone can act on them. This is needed the moment the pilot runs on the Mac.

- **Patient-level worklists from a ledger run.** Written to a local output folder the caller names, never to stdout. Each row shows the rule title, state, due date, the evidence ids, and the `action` from the rule file. One list per action kind and audience:
  - MOA "book a visit"
  - patient "self-refer" message list, with the program phone numbers from the rule `action.note`
  - physician review for loops (category B), sorted first
  - `UNKNOWN` tasks ("record smoking history")
  - the outreach list (not seen in 36 months)
- **Format:** static HTML (one self-contained file, no external assets) plus CSV. Nothing leaves the Mac.
- **Run diff:** between two ledger runs, per rule: newly open, closed, still open, and changed state. It's aggregate on the command line and patient-level only in the written files. Flag when the two runs used different ruleset digests.
- **"Already done" feedback:** a small table where a reviewer marks a result as done elsewhere, declined, or not applicable, with a date and an optional evidence note. Feed it back as facts with `source: attestation`, so it's evidence like any other. The rule decides what it satisfies, with no special case in the engine.
  - **Decided 2026-10-02:** an attestation has no lifetime of its own. It's a dated fact for the event it attests, and the rule's interval decides when it's next due. "Declined" lapses after 12 months. Attestations satisfy events only (FIT, mammogram, HPV test, eye exam), never eligibility inputs such as pack-years or hysterectomy type, which still need chart evidence. One click must never drop a patient out of a program.
- **Acceptance:** tests against the synthetic pipeline run in `tests/test_pipeline.py`. The worklists contain the expected patients, nothing is printed to stdout but counts, the diff is correct across two runs, and an attestation closes a gap on the next run.

### WP2. Measurement rules (engine extension), hard

Catalog section 8.1 (unrecognized conditions) and most of 8.2 (chronic monitoring) need things the evaluator can't express yet.

- **Thresholds on numeric values:** A1c ≥ 6.5, eGFR < 60, ACR ≥ 3, LDL ≥ 5.0, office BP ≥ 135/85. BP needs systolic and diastolic, so decide how vitals arrive as facts. `Observation.result` today is one string.
- **Repeated measures:** "twice", "on 2 results ≥ 90 days apart", "≥ 2 visits within 6 months".
- **Combinations:** "A1c ≥ 6.5 plus FPG ≥ 7.0".
- **Absence conditions:** "not flagged if" a code or a medication is present (largely `none_of` today).
- **Stage-dependent intervals:** CKD monitoring frequency by eGFR and ACR category (KDIGO 2024, catalog `ckd.monitoring`).
- **Design:** a new `kind` (e.g. `measurement`) with its own strict schema, rather than overloading `interval`. Keep it declarative and readable by a clinician.
- **Then write:** `unrec.diabetes`, `unrec.prediabetes` (it changes `dm.screen`'s interval, see the catalog), `unrec.ckd`, `unrec.htn` (catalog §9 #1: BC 135/85), `statin.indicated`, `dm.a1c`, `dm.kidney`, `dm.foot`, `dm.bp`, `ckd.monitoring`, `htn.review`, `htn.labs`.
- **Concepts:** add any missing ones to the value sets. A BP vitals value set likely needs a new `match` mode.
- **Acceptance:** edge tests per rule, the way `tests/test_engine.py` does it. Exactly at threshold vs just under, 89 vs 90 days apart, one result vs two, and a code present vs absent. Mutation-check the new evaluator logic.

### WP3. Immunizations (catalog section 4), hard

- **Value sets:** vaccine product to antigens. A combo product satisfies each antigen it contains: DTaP-HB-IPV-Hib, MMRV, Tdap-IPV, PCV20, Men-C-C, Men-C-ACYW, HPV9, HepB, HepA, rotavirus, varicella, Td/Tdap, influenza (including Fluad), RSV (mRESVIA), and Shingrix.
- **Engine:** a `series` kind that counts doses per antigen by chronological age, with:
  - minimum ages and minimum intervals
  - grace periods (2 months for infant doses, 12 months for the 4 to 6 year dose)
  - closing windows (rotavirus never after 8 months)
  - "any prior dose of X counts" (PPV23 satisfies `imm.pcv20.65`)
  - "anyone who's had any RSV vaccine isn't eligible again"
- **Missing doses:** school-program doses default to `NOT_FOUND`, not `OVERDUE` (catalog 4.2).
- **Sensitive flags:** Indigenous identity, LTC, pregnancy, immunocompromise, health care worker, and GBMSM/2STNB drive eligibility. They must never appear in aggregates.
- **Sources:** BCCDC CD Manual Ch. 2 (Sept 2026 schedules) is the source, and `docs/sources.md` has the links. Don't use another province's schedule.
- **Acceptance:** edge tests for each childhood visit, each combo product, minimum interval violations, the rotavirus window, and adult one-time vaccines.

### WP4. Extraction on the Mac (`src/clinic_review/extract/`), hardest

Report-based loops (BI-RADS, colonoscopy findings and recommended interval, the HPV report's next due date, LDCT category, DXA T-score), plus everything in `valuesets/extracted.yaml`, depend on this.

- **OCR:** Apple Vision behind an interface. CI runs on Linux, so tests use a fake OCR that returns fixed text.
- **Model adapters:**
  - local first (MLX or Ollama, sized for the 24 GB Mac mini: roughly 14B dense or a ~20B MoE at 4-bit)
  - Azure OpenAI Canada East regional as the fallback
  - the same prompts and schemas for both; config lives in `local/`
- **Per-document-type schemas:** each field carries a `quote`. A fact is accepted only if its quote appears verbatim in the OCR text, after the same normalization on both sides. Otherwise it's dropped and logged as a skip. This is the traceability rule.
- **Output:** facts with the right concept, date, value, `next_due`, evidence id (document id), and source (`documents.*`). They go through the same ledger path.
- **Evaluation harness:** for the 200-document extraction check (PLAN 9.4). Ali labels documents on the Mac. The harness computes per-field accuracy and never prints document text. Synthetic documents only in this repo.
- **Acceptance:** fully tested with fake OCR and a fake model adapter. The exact-quote check gets its own adversarial tests: a paraphrased quote, a quote from a different document, and a quote that's present but with a negated meaning. A real-model smoke test is opt-in and Mac-only.

### WP5. Remaining cancer rules and loops (catalog section 2), moderate

`breast.fdr`, `breast.high_risk`, `breast.chest_rt` (from 25, §9 #4), `breast.75plus`, the breast BI-RADS loops, `cervix.immunocompromised` (3-yearly to 74, HIV included, §9 #5 and #6), `cervix.post_treatment`, `cervix.exit_70plus`, the cervix loops, `colon.family_history`, `colon.surveillance` (it uses the report's recommended interval), `colon.75_84`, `lung.loop.followup_required`, `prostate.loop.psa_rising` (PSA screening stays off, §9 #9).

- Most are YAML plus concepts plus edge tests. The loops that read report values only become useful after WP4, but the rules can land first.

### WP6. Per-patient screen planning, moderate and safety-sensitive

- After the roster pass, use each patient's age and sex to work out which rules could apply. Take the union of those rules' `evidence_sources` and map them to walker screens through the facts mapping's `screens[*].sources`. Then walk only those screens (PLAN 5.2).
- The walker's `chart_pass` takes one screen list for everyone today, so this needs per-patient screens.
- **Unwalked screens still turn gaps `UNKNOWN`:** a planner bug must never turn into a false `NOT_FOUND`. Test that explicitly.
- Every existing walker safety test must still pass.

### WP7. Small items, folded into whichever package touches the area

- **`unclear_if` for rules:** a concept that makes a rule `UNKNOWN` with a task. First use: `proc.hysterectomy_unspecified` on `cervix.hpv`, with the task "confirm hysterectomy type". Decided 2026-10-02: do it.
- **Breast implants:** stay an exclusion on `breast.avg.*` (BC Cancer doesn't do screening mammograms with implants, see docs/sources.md), but the worklist should show them as a task, "arrange diagnostic mammogram", not as a silent `EXCLUDED`.
- **Denominator:** a primary provider check if CHR exposes it, and "eligible within 90 days" counts (PLAN 4).
- **Synthea bulk run:** for performance on a 1,500-patient synthetic panel.

## Blocked on the Mac (not for a remote agent)

- Phase 0 recording, and writing `local/chr-profile.yaml` and `local/chr-facts.yaml` from it. The map has routes and JSON keys only, no values.
- The 50-chart pilot, the denominator check against CHR's LFP dashboards, value set sign-off, the 100-chart audit, and extraction labels.

## Open questions for Ali (don't decide these alone)

Decided 2026-10-02 (see PLAN section 12): attestation handling, hysterectomy-unspecified as `UNKNOWN`, breast implants kept as an exclusion with a task, and worklists as HTML plus CSV in a folder under the data account.

- Which CHR screen lists upcoming appointments, for the pre-visit card. It needs Phase 0.
