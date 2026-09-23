# Clinic Review: panel-wide screening and care-gap review

Plan v0.5, 2026-09-23. Bonne Vie Medical Clinic, Coquitlam BC. EMR: TELUS Collaborative Health Record (CHR, formerly Input Health).

**Goal:** for every active longitudinal patient aged 0 to 100, produce a verifiable list of what's due, overdue, or left open, using BC rules, and turn it into work the clinic actually closes.

**How:** browser automation reads each chart in CHR on the clinic Mac, a model on the same Mac turns reports and free text into facts, and deterministic BC rules decide what's a gap. Everything patient-level stays on the Mac.

**This repo is public and holds rules, the concept layer, code, and synthetic test patients. Nothing patient-level or clinic-operational, ever.**

---

## 1. How this fits with the CHR Panel Review Spec

The CHR Panel Review Spec (private Claude Doc, 2026-09-22) sets up the overall system. A navigator walks each chart in CHR at a human pace overnight and keeps what CHR loads for each screen. It stores that in an encrypted SQLite on the clinic Mac and puts findings in a clinician review queue. It gives Ali the concept layer, the rules, and the precision reviews.

This repo is that part: which patients are in scope, what's due for each of them at every age, how to tell "done" from "not found", and how to prove the rules are right before anyone sees a worklist. It can be built and fully tested now with synthetic patients. It also holds the chart walker (section 5.3).

It uses the spec's finding categories:

| Spec category | What it covers | Owned here? |
|---|---|---|
| **A. Preventive and chronic-care gaps** | Screening, immunizations, chronic disease monitoring, well-child, unrecognized conditions | **Yes, all of it.** This is the 0 to 100 screening ask. |
| **B. Dropped follow-ups** | Plans that never closed | **Partly.** The structured screening-result loops (FIT positive, BI-RADS 0/4/5, HPV 16/18, Lung-RADS) are deterministic and live here. Free-text plan extraction stays in the spec. |
| C. Questionnaire patterns | PHQ-9, GAD-7, AUDIT-C, EPDS scores nobody acted on | No (spec, reuses ACA scoring) |
| D. Unexplained symptom patterns | LLM timeline review, behind a flag | No |
| E. Operational open loops | Stale inbox items, overdue tasks, missed appointments | No |

---

## 2. Guardrails

1. **Public repo, so nothing patient-level or clinic-operational goes in it.** It holds rules, the concept layer, code, and synthetic patients. Everything else stays on the clinic Mac: patient data, panel counts and sizes, MRP status, patient lists, recall and deadline lists, screening interventions, run outputs, model configuration, and the CHR-specific walker profile (routes, selectors, endpoint names). That's enforced three ways: `.gitignore`, a pre-commit hook (`scripts/check_no_phi.py` rejects anything passing the BC PHN check, and data-type files), and the same check in CI on every push.
2. **PHI stays on the Mac.** The extraction model runs on the Mac. Azure OpenAI Canada East, as a regional deployment, is the fallback. Claude never sees charts. It has no in-Canada inference on any platform, so I build and test against synthetic patients only.
3. **Keep dev tools away from the data.** The walker and its encrypted store run under a separate macOS user account, with the data directory at `700`. Claude Code, including the Mac mini `--dangerously-skip-permissions` runs, works in the dev account against synthetic fixtures and can't read the store. Logs carry CHR IDs only.
4. **Consent and privacy:** covered by Bonne Vie's signed-off clinic policies.
5. **Pilot on your own panel** before anyone else's.
6. **Read-only, decision support only.** The walker has no handlers for Save, Sign, Send, or Book. The engine never orders, books, or messages. Any write goes through the spec's stage-don't-submit queue.

---

## 3. What counts as a category A gap

Seven sub-types, worked in this order. Screening-result loops go first even though screening is the headline, because a missed abnormal result is where delayed-diagnosis harm actually happens.

| Order | Sub-type | Examples | Where the rules live |
|---|---|---|---|
| 1 | **Screening-result loops** (spec B, structured) | Positive FIT, no colonoscopy report in 180 days. HPV 16/18, no colposcopy. BI-RADS 0/4/5, no work-up. LDCT "follow-up required", no thoracic referral. | catalog §2 |
| 2 | **Unrecognized conditions** | A1c ≥ 6.5% twice with no diabetes code. eGFR < 60 for 3+ months with no CKD code. Fragility fracture with no osteoporosis assessment. | catalog §8 |
| 3 | **Cancer screening** | Breast, cervix, colon, lung | catalog §2 |
| 4 | **Other screening** | BP, diabetes, lipids and CV risk, osteoporosis, AAA, HIV, HCV, STI | catalog §3 |
| 5 | **Immunizations** | Childhood schedule, school catch-up, Td, PCV20 at 65, RSV at 75, HPV9 catch-up | catalog §4 |
| 6 | **Chronic disease monitoring** | Diabetes (A1c, ACR, eGFR, eye, foot, statin), CKD, HTN, CHF, COPD, high-risk drug monitoring | catalog §8 |
| 7 | **Life stage** | Well-child visits (Rourke 0 to 5, Greig 6 to 17), prenatal labs, advance care planning and MOST, hereditary cancer referral | catalog §5 to §7 |

The full rule list, with a BC source for every row, is in [`screening-catalog.md`](screening-catalog.md).

---

## 4. Denominator: who's in the cohort

Running rules on walk-ins, transfers, and the deceased inflates every count and sends recalls to people who aren't yours.

- **Include:** active in CHR, not deceased, primary provider ("PP") is the physician under review, at least one visit in the last 36 months.
- **Exclude:** walk-in or episodic only, transferred out, moved, deceased.
- **Not seen in 36 months:** out of the rule run, but not dropped. They go on their own outreach list, since a long gap is itself a reason to reach out.
- **v1 is your panel only.** The roster pass pages through CHR's patient search filtered to your panel (the analytics patient search), so the walker never opens anyone else's chart.
- **Reconcile** against CHR's LFP dashboards ("active but not seen", "seen but not active", PAS empanelment). The results stay on the Mac.
- **Age** is computed at run date. Every age-triggered rule also reports "eligible within 90 days" so recalls batch well.

If the patient list doesn't show status and primary provider, the fallback is "seen in the last 36 months, primary provider from the chart header".

Run the denominator alone first and sanity-check the count before any rule runs.

---

## 5. Getting the data: browser automation of CHR

### 5.1 How the walk works

- **Where:** the clinic Mac, in real Chrome. The clinician starts Chrome, logs in to CHR, and does 2FA by hand. The walker attaches to that session and never touches credentials.
- **Chrome setup:** a dedicated Chrome profile for the walker, started with remote debugging on the loopback interface:
  ```sh
  open -na "Google Chrome" --args --user-data-dir="$HOME/ClinicReview/chrome-walker" --remote-debugging-port=9222
  ```
  Chrome 136 and later refuse remote debugging on the default profile, so a separate `--user-data-dir` is required anyway. It also keeps the walker's CHR session apart from everyday browsing. While that port is open, any process on the Mac can drive that Chrome, so only start it for a walk, under the separate data account, and quit it after. The walker refuses to attach to anything but `127.0.0.1` or `localhost`.
- **How it moves:** for each patient it opens chart sections by CHR's own page routes (what the address bar shows when you click through), waits for the screen to settle, and moves on. Clicks and keyboard are only a fallback for screens with no route, like a pop-over.
- **What it keeps:**
  - **Primary:** the JSON responses CHR's own page fetches to draw each screen, captured passively. The walker never sends a request CHR's page didn't make itself. That's the posture the CHR Companion work calls the most defensible.
  - **Cross-check:** DOM reading with a versioned selector profile, for anything computed on screen.
  - **Documents:** the PDF CHR loads in its viewer, OCR'd on-device with Apple Vision.
- **Raw first:** every response body is stored as received, next to the normalized facts. Bodies and URLs are sealed with AES-256-GCM (key in the data account's macOS Keychain) and bound to their patient and screen, so a body can't be moved to another patient's row. Parsers can be fixed without walking the chart again.
- **Pacing:** 3 to 6 s jittered pause per screen, off-hours only (e.g. 7 pm to 6 am). It stops and alerts on logout, a login or 2FA prompt, or a screen failing to load twice, and resumes from the last completed patient.
- **Wrong-patient guard:** every captured response has to be provably about the chart the walker opened: the patient id is in the response URL, or every patient id in the body matches. A single conflicting id discards everything from that screen and stops the run. A canary test chart is checked before every run.
- **Audit log:** CHR ID, time, screens visited, run ID. Nothing else.

### 5.2 Walk only what the rules need

The spec budgets about 12 screens and 2 to 3 minutes per patient, which is 70 to 100 hours for a 2,000-patient panel. For category A, most patients don't need most screens. Every rule declares its `evidence_sources` (section 6.2), so the walker can plan each patient's screens from their age, sex, and conditions:

1. **Roster pass, everyone:** patient list and chart header only (age, sex, status, primary provider). At two screens each this is roughly one night for the whole panel, and it produces the denominator.
2. **Eligibility pass:** only the screens some rule needs for that patient. A healthy 30-year-old man needs history, vitals, immunizations, and labs. A 62-year-old woman adds documents (mammogram, colonoscopy, DXA). Encounter notes are only opened when a free-text fact (family history, smoking) isn't answered by the structured history screens.
3. **Incremental:** after the first pass, only patients with new activity since the last run (daysheet, inbox, new results). That's minutes a night.

I'd expect the eligibility pass to cut the first walk substantially, but that's a guess. The first 50 charts will give a real number.

The walker already takes the screen list per run. Planning it per patient from the rules' `evidence_sources` plugs in once the rules exist.

### 5.3 Where the walker lives

**Decided 2026-09-23: Playwright in this repo** (`src/clinic_review/walker/`), attached over the Chrome DevTools Protocol to the Chrome the clinician started and logged into. It's one Python pipeline one person can run and change, with no wait on the Mac app's release cycle.

What's built and tested against a fake CHR-like app with synthetic patients (`tests/fake_emr.py`):

| Piece | What it does |
|---|---|
| `walker/session.py` | Attaches to the clinician's Chrome in a tab of its own. Loopback only. |
| `walker/walker.py` | Roster pass (patient list, then chart header per patient) and chart pass (chosen screens per patient). Passive capture, settle detection, two tries per screen, off-hours window, jittered pacing, resume by sweep. |
| `walker/guard.py` | Wrong-patient verdict per response |
| `walker/record.py` | Phase 0 recorder: routes and response shapes, no values |
| `walker/profile.py` | Loads the EMR profile. The real CHR profile lives in `local/` (gitignored). `tests/fixtures/fake_emr/profile.yaml` is the format reference. |
| `store/` | Sealed raw capture store, audit log, roster, progress |

Tests cover the stop conditions end to end: wrong patient, logged out and resume, a screen that never loads, a broken canary, and outside the window. Not built yet: the DOM cross-check, per-patient screen planning from the rules, and OCR of captured PDFs. The Mac app's Clinic Workspace stays the path if this becomes an Autochart.ai feature. The raw store and concept-level facts don't change either way.

### 5.4 Phase 0: map screens to data

A clinician clicks through 5 test charts once while `python -m clinic_review.walker record --out local/phase0-map.jsonl` listens. It writes each page route and response path with ids replaced by `{id}`, plus the JSON shape (keys and types, no values). From that we write down screen → route → JSON fields → concept. The CHR-specific half of that mapping (routes, selectors, field names) goes in the local profile, not this repo. Only the concept names are committed here. The spec's code review already has a candidate list of chart sections, so this confirms rather than discovers.

### 5.5 What the rules need, and where it probably comes from

| Concept family | CHR screen | Coded? | Notes for the rules |
|---|---|---|---|
| Demographics, sex at birth, status, primary provider | Patient list, chart header and profile | Partly | Gender identity and sex at birth both matter (breast, cervix). Indigenous identity only if self-identified. It gates Hep A, RSV at 60, and COVID eligibility, and never appears in aggregates. |
| Conditions | Medical history, past diagnoses, encounter diagnoses | MSP ICD-9 where coded, free text otherwise | Encounter and billing diagnoses catch conditions nobody put in Medical History |
| Surgical history (exclusions) | Surgical history | Free text | Hysterectomy type, mastectomy, colectomy. Extraction target. |
| Family history | Family history | Free text | Drives breast annual, colon 5-yearly, hereditary referral. Extraction target. |
| Smoking, alcohol | Risk factors, social history | Probably free text | Lung eligibility hinges on it. Missing = its own gap. |
| Medications | Medications, prescriptions | Name strings, no DIN seen | Name-to-ATC table (statins, immunosuppressants, DOACs, lithium, glucocorticoids) |
| Immunizations | Injections | Unknown | Incomplete by design: pharmacy and school doses mostly aren't in CHR |
| Labs | Lab results | Names and values, no LOINC seen | Lab name table for A1c, ACR, eGFR, lipids, Lp(a), FIT, HPV, HIV, HCV, TSH, drug levels. Cervix screening reports print the next due date. |
| Vitals | Vitals | Probably structured | BP, weight, height |
| Screening reports | Files (Diagnostic Imaging, Consults, Lab, Hospital, Historical Chart, imported) | PDF | On-device OCR, then extraction of BI-RADS, HPV result and next due date, colonoscopy findings and recommended interval, LDCT category, DXA T-score |
| Visits | Encounter list | Dates, diagnoses | Denominator activity window, well-child visit timing |
| Pregnancy | Encounters, labs, history | Mixed | Triggers the prenatal rule set |

### 5.6 CHR's own preventive care module

CHR has a per-patient Preventive Care section and a "Preventative Care Report" dashboard. It's worth switching on as a baseline, but its BC defaults are out of date. Cervix is still Pap + HPV every 3 years, diabetes screening is every 5 years, and it only counts its own structured entries, not results sitting in PDFs. Catalog §10 has the comparison. Our output should beat it, and the gap between the two is a useful sanity check.

### 5.7 What CHR won't have

A lot of screening happens outside the clinic, and it only reaches CHR if the patient named you:

- Self-referred mammograms (and **BC Cancer sends providers no overdue reminders for breast**)
- HPV self-screening kits
- FITs ordered by walk-ins or other providers
- Pharmacy and public-health immunizations, which live in the provincial registry (CareConnect, Health Gateway)
- School-program vaccines (grade 6 and 9)
- Colonoscopies and imaging in other health authorities
- History from before CHR, which sits in imported documents, not coded fields

So **"not found in chart" never counts as "overdue".** Section 6.3 makes that a first-class state, and section 8 puts a CareConnect check between the rules and any outreach.

---

## 6. Rules

### 6.1 Concept layer

A curated table maps ICD-9 codes, free-text synonyms, lab test names, drug names, and document keywords to about 150 internal concepts (`dx.diabetes`, `obs.a1c`, `screen.mammogram`, `proc.hysterectomy_total`, `imm.pcv20`). It's built and clinician-signed before the rules, as the spec says. It lives in `valuesets/`.

### 6.2 Rule format

One YAML file per rule, readable by a clinician and reviewed like code:

```yaml
id: colon.fit.average_risk
version: 1
category: A
subtype: cancer_screening
title: Colorectal cancer screening, average risk (FIT)
source:
  name: BC Cancer Colon Screening Program, Screening Guidelines May 2026
  url: https://www.bccancer.bc.ca/screening/health-professionals/colon
  checked: 2026-09-22
population:
  age: {min: 50, max: 74}
  not: [colon.high_risk_family_history, dx.ibd, dx.colorectal_cancer]
exclusions: [proc.colectomy_total]
satisfied_by:
  - {concept: obs.fit, within_months: 24}
  - {concept: proc.colonoscopy, within_months: 120}
  - {concept: proc.flex_sig, within_months: 120}
  - {concept: imaging.ct_colonography, within_months: 60}
evidence_sources: [labs, documents.consults, documents.hospital, history.surgical]
declined_valid_months: 24
action:
  kind: order            # physician orders FIT; patients can't self-order
  mode: book_or_order    # MOA books, or physician orders at next visit
review_by: 2027-03-01    # BC Cancer is "investigating" starting at 45
owner: ali
```

Every rule carries its source, the date it was checked, a review-by date, and an owner. BC changed its cervix, breast, colon follow-up, and pneumococcal rules between 2024 and 2026, and the federal Task Force was wound down in March 2026. CI fails when any rule is past its review-by date. `evidence_sources` also tells the walker which screens to open (section 5.2).

**⚠ decide:** YAML here plus a small Python evaluator, or ACA-style Python modules (the spec's suggestion, reusing ACA's registry and `missing_inputs`)? I'd keep the *content* in YAML either way, so you can edit rules without touching code, and have a thin ACA module load it.

### 6.3 Evidence states

Every eligible patient gets exactly one state per rule. The review queue shows the state and the evidence, and for "not found" it also shows where the engine looked.

| State | Meaning | Queue action |
|---|---|---|
| `UP_TO_DATE` | Qualifying evidence inside the interval | Hidden |
| `DUE_SOON` | Due within 90 days | Batch into recall |
| `OVERDUE` | Evidence found, but older than the interval | Queue |
| `NOT_FOUND` | Eligible, nothing found in any source listed | "Not found in chart, check CareConnect" |
| `EXCLUDED` | Documented exclusion | Hidden, evidence kept |
| `DECLINED` | Informed refusal documented in the last N years | Re-offer after N years |
| `DISCUSS` | Shared decision, not a gap (breast 40 to 49, PSA, zoster, colon 75 to 84) | Pre-visit card only, never a recall |
| `UNKNOWN` | Can't decide, an input's missing | The missing input becomes the task ("record smoking history") |
| `NOT_ELIGIBLE` | Outside population | Hidden |

### 6.4 Engine

Deterministic Python, no LLM. In: the normalized store, the concept layer, and the rules. Out: `(patient_id, rule_id, rule_version, state, due_date, evidence_ids[], searched_sources[], run_id)`. The same inputs always give the same output, so every run can be diffed against the last.

---

## 7. The model on the Mac

The model does one job: **turn unstructured chart content into facts**. Each fact carries a quoted span that has to match the source exactly (the spec's traceability rule). The model never decides whether something's a gap.

For category A the extraction targets are narrow:

- **Screening reports:** BI-RADS category and density, HPV result and the lab's printed next-due date, colonoscopy findings and the recommended interval, LDCT result category, DXA T-scores
- **Free text:** smoking status and pack-years, family history of breast, colorectal, ovarian, and pancreatic cancer, hysterectomy type, informed refusals ("declines FIT"), goals of care

Keyword and concept matching runs first. Only documents that could satisfy a rule go to the model.

**Decided: on-device first, Azure Canada East as fallback.**

| | On the Mac (primary) | Azure OpenAI Canada East (fallback) |
|---|---|---|
| Setup | Apple Vision for OCR. An open-weight model via MLX or Ollama, sized for the 24 GB Mac mini: roughly 14B dense or a ~20B mixture-of-experts model at 4-bit, since macOS gives the GPU only part of the RAM. The candidate is picked by the extraction check (section 9). | **Regional** deployment only. Global and Data Zone deployments process outside Canada. |
| Hardware / cost | The 24 GB Mac mini you have. The ~30B models I'd first hoped for don't fit comfortably, so if the smaller model misses the extraction bar on scanned reports, those go to Azure. | gpt-4.1-mini at about US$0.48 in / $1.94 out per million tokens. A 2,000-patient first pass is well under US$100. |
| Speed | Roughly 5 to 10 s per 3k-token document. It runs alongside the overnight walk, so the walk stays the bottleneck. | Fast |
| Catch | Needs its own accuracy check | gpt-4.1-mini and gpt-4o are the only regional models in Canada, and **both retire April 14, 2027**. Prompts and schemas stay model-agnostic, so swapping means rerunning the extraction check, not rewriting. |

Which model and endpoint are actually in use lives in the Mac's local config, not in this repo.

---

## 8. From gap to closed gap

Everything in this section is generated and kept on the Mac. It follows the spec's queue and adds what category A needs:

1. **Panel dashboard, aggregates only:** per rule, eligible / up to date / due / overdue / not found, by age band. This is the baseline, and it shows progress over time.
2. **Queue order:** screening-result loops first (physician review within a week of each run), then unrecognized conditions, then cancer screening, immunizations, chronic monitoring, life stage.
3. **CareConnect check** on every `NOT_FOUND` before outreach. "Found externally" back-fills the store and teaches the rule where to look ("already done" in the spec).
4. **Outreach matched to how Bonne Vie runs:**
   - Needs a visit (loops, chronic monitoring, well-child, anything needing a conversation): **MOA books**. The script carries no clinical detail ("Dr. X would like to see you for a check-up"). CHR auto-sends SMS and email on booking, so the MOA confirms before saving.
   - Patient can self-arrange: breast (1-800-663-9203), cervix self-screening kit (1-877-702-6566 or online), lung (1-877-717-5864), and flu, COVID, and PCV20 at a pharmacy. The patient gets a physician-approved message with the number. FIT isn't in this group, since BC requires a physician or NP order.
   - Later: Autochart.ai Voice for recall calls.
5. **Pre-visit card:** open category A items for each booked patient on the day sheet. Most gaps close opportunistically. It's also the natural hook into Autochart.ai Scribe pre-charting.
6. **Weekly incremental walk** on patients with new activity. The ledger keeps open, closed, and declined history, so closure rate per rule is a real number.

---

## 9. Validation

1. **Synthetic suite (this repo, CI):** every rule gets hand-built patients at its edges. That means age 49.99 vs 50.00 and 74.99 vs 75.00, one day inside and outside the interval, exclusion present, decline present, and contradictory data. Synthea covers bulk and performance. The walker runs end to end in CI against a fake CHR-like app with synthetic patients.
2. **Walker check (on the Mac):** the first 50 real charts are captured with zero wrong-patient mismatches, checked by hand against CHR (the spec's Phase 1 gate).
3. **Chart audit (on the Mac):** a stratified random sample of 100 patients across age bands, reviewed by hand against the engine. Compute per-rule positive predictive value and sensitivity. A rule reaches the queue only at **PPV ≥ 90% and sensitivity ≥ 85%**. Below that it runs in shadow mode. That's stricter than the spec's 70% acceptance gate on purpose: category A is deterministic, so it should be precise.
4. **Extraction check (on the Mac):** about 200 hand-labelled documents across report types. Per-field accuracy (BI-RADS, next-due date, T-score, colonoscopy interval) decides the on-device model and has to clear the bar before the screening-result loops go live.
5. **"Already done" rate** from the queue, per rule, as the spec proposes. A high rate means a data source is missing, not that the rule's wrong.
6. **Regression:** any change to a rule, value set, or model reruns the synthetic suite and diffs the ledger against the last live run.

Audit and extraction results stay on the Mac. Only the per-rule pass/fail decision (a rule moving out of shadow mode) is recorded here, as a change to the rule file.

---

## 10. Phasing

| When | Work | Spec phase | Exit criteria |
|---|---|---|---|
| **Week 1** | Walker built and tested against the fake EMR (done). Phase 0: `walker record` on 5 test charts, then write the local CHR profile. Catalog sign-off. | 0 (map) | Every chart section the rules need has a known route and field list |
| **Weeks 1 to 2** | Concept layer v1, rule format, evaluator, cancer screening and loop rules, synthetic suite in CI. Roster pass on your panel with `--limit 50`. | 0 and 1 | CI is green on every edge case |
| **Weeks 3 to 4** | Walker on your first 50 charts. Remaining adult screening, immunizations, unrecognized conditions, chronic monitoring for DM, HTN, CKD. Rules in shadow mode. | 1 (walk and store) | Zero wrong-patient mismatches on 50 charts |
| **Weeks 5 to 6** | On-device OCR and extraction, model chosen. First full-panel walk (roster pass, then eligibility pass). 100-chart audit. | 3 (category A) | Extraction check and audit thresholds met |
| **Weeks 7 to 8** | Pediatrics (Rourke, Greig, childhood and school immunizations), prenatal, life-stage rules. Queue live for rules that passed. Weekly incremental walks. | 3 continued | First month of closure-rate data |
| **Later** | Colleagues' panels. Decide what becomes an Autochart.ai care-gap feature. | beyond 5 | Productizing moves this from internal QI to a Health Canada SaMD question, which is its own decision. |

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| "Gap" that's really data sitting outside CHR | `NOT_FOUND` state, CareConnect check, "already done" feedback |
| Bad extraction giving false reassurance (wrong BI-RADS, wrong interval) | Exact-quote rule, extraction check, physician review of every screening-result loop |
| CHR UI changes break the walker | Navigate by routes, not clicks. Versioned local profile. Self-check against a known test chart at the start of every run, and stop on mismatch. |
| TELUS sees nights of chart views from one account | Human pacing, off-hours, eligibility-driven walk to cut volume. Decide up front whether to tell TELUS (the spec's open question). |
| Session timeout or 2FA mid-run | Stop, alert, resume from the last completed patient |
| Wrong-patient capture | Patient-ID match on every response. Mismatches are discarded and logged. |
| Patient data reaching GitHub | `.gitignore`, pre-commit PHN guard, the same guard in CI, separate macOS account for the data |
| Alert fatigue | `DISCUSS` state keeps optional items off recall lists, rules ship in phases, shadow mode below threshold |
| Guideline drift | Source, checked date, review-by date, and owner on every rule. CI fails on stale rules. |
| Recall volume swamping the MOAs | Batch by due date, cap weekly recalls, loops first |
| Azure fallback model retiring April 2027 | Model-agnostic prompts and schemas, extraction check rerun on any swap |

---

## 12. Decisions I need from you

Decided 2026-09-23: Mac mini with 24 GB, your panel only for v1, 36-month activity window (with the not-seen list used for outreach).

1. **Tell TELUS** before the first overnight walk?
2. **Contested rules:** 13 of them, each with my recommendation, in catalog §9. The big ones are the hypertension threshold (BC 135/85 vs Hypertension Canada 130/80), osteoporosis (FRAX-first vs BMD at 70), and whether breast 40 to 49 is a gap or a discussion.

---

## Proposed repo layout

```
clinic_review/
  docs/                 plan, catalog, sources
  rules/                one YAML per rule
  valuesets/            concept layer: ICD-9, lab names, drug→ATC, document keywords, vaccine→antigen
  scripts/
    check_no_phi.py     pre-commit and CI guard
  src/clinic_review/
    walker/             browser walker: session, capture, guard, pacing, Phase 0 recorder
    store/              sealed raw capture store (SQLite, AES-256-GCM, key in macOS Keychain)
    engine/             evaluator, evidence states, ledger
    extract/            OCR + extraction schemas and prompts. Model adapters: local (MLX/Ollama), Azure Canada East.
    report/             dashboard aggregates, queue export, pre-visit card
  tests/
    fake_emr.py         fake CHR-like server with synthetic patients
    fixtures/           fake EMR app and its walker profile
  local/                gitignored: CHR profile (routes, selectors, fields), model config
```

The encrypted data store lives outside the repo, under the separate macOS account.
