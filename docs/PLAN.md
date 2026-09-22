# Clinic Review: panel-wide screening and care-gap review

Plan v0.3, 2026-09-22. Bonne Vie Medical Clinic, Coquitlam BC. EMR: TELUS Collaborative Health Record (CHR, formerly Input Health).

**Goal:** for every active longitudinal patient aged 0 to 100, produce a verifiable list of what's due, overdue, or left open, using BC rules, and turn it into work the clinic actually closes.

**This repo holds the rules, the concept layer, the export loader, and synthetic test data. No patient data, ever.**

---

## 1. How this fits with the CHR Panel Review Spec

The CHR Panel Review Spec (private Claude Doc, 2026-09-22) already covers the *hands*. The Autochart.ai Mac app's Clinic Workspace walks each chart at a human pace overnight. It keeps the JSON CHR loads for each screen, stores it in an encrypted SQLite on the clinic Mac, and puts findings in a review queue. That spec gives Adrian the navigator and storage, Adans the queue and staged writes, and Ali the concept layer, rules, and precision reviews.

This repo is the **brain for Ali's part**: which patients are in scope, what's due for each of them at every age, how to tell "done" from "not found", and how to prove the rules are right before anyone sees a worklist. It's written so it can be built and fully tested now, with synthetic patients, while the navigator's being built.

**One change to the spec's data plan, which I'd push hard on:** CHR has a self-serve bulk export (Settings > Exports, section 5). The spec assumed there was no bulk route and planned 70 to 100 hours of overnight chart walking for the first pass. The export is sanctioned, runs in minutes to hours, and covers most of what the rules need. It also avoids a week of unusual-looking activity in TELUS's audit logs. So: **export for the baseline, and the navigator only for what the export doesn't carry** (probably PDF contents and anything "Patient Data" flattens). That shrinks the navigator's job a lot, and lets this repo ingest the export directly on the clinic Mac.

It uses the spec's finding categories:

| Spec category | What it covers | Owned here? |
|---|---|---|
| **A. Preventive and chronic-care gaps** | Screening, immunizations, chronic disease monitoring, well-child, unrecognized conditions | **Yes, all of it.** This is the 0 to 100 screening ask. |
| **B. Dropped follow-ups** | Plans that never closed | **Partly.** The structured screening-result loops (FIT positive, BI-RADS 0/4/5, HPV 16/18, Lung-RADS) are deterministic and live here. Free-text plan extraction stays in the spec. |
| C. Questionnaire patterns | PHQ-9, GAD-7, AUDIT-C, EPDS scores nobody acted on | No (spec, reuses ACA scoring) |
| D. Unexplained symptom patterns | LLM timeline review, behind a flag | No |
| E. Operational open loops | Stale inbox items, overdue tasks, missed appointments | No |

---

## 2. Guardrails (before any code touches CHR)

1. **This repo is public right now.** Make it private. Rules and the catalog are fine to share one day. Anything clinic-specific or integration-specific isn't. `.gitignore` blocks data, exports, PDFs, and spreadsheets. Add a pre-commit hook that rejects anything passing the BC PHN check (10 digits, leading 9, mod-11 check digit).
2. **PHI stays in Canada, which rules me out.** Claude can't run with in-Canada inference on any platform right now (Anthropic API, Bedrock ca-central-1, Vertex, and Foundry all route to the US or globally). So I build and test against synthetic patients, and the real run happens on the clinic Mac.
3. **The CPSBC AI guideline has a consent clause worth taking seriously.** "Personal patient data must not be transferred from the clinical environment at which care is provided without patient consent or where required or permitted by law" (Ethical Principles for AI in Medicine, v1.2, April 2026). An on-device model avoids that question entirely. A Canada East Azure endpoint is arguably fine under PIPA as a service provider, but it's arguable. Section 7 recommends on-device first for that reason.
4. **PIA before the first harvest.** OIPC BC says a PIA isn't required under PIPA but recommends one, and will review it. Whether panel-wide gap review counts as direct care (implied consent) or secondary use (express consent) isn't settled in any BC guidance. The PIA should take a position and get a quick read from Fasken.
5. **Custodianship:** start with your own panel. Colleagues' panels need their written OK.
6. **Decision support only.** The engine never orders, books, or messages anything. The spec's "stage, don't submit" rule holds.

---

## 3. What counts as a category A gap

Seven sub-types, worked in this order. Screening-result loops go first even though screening is the headline, because a missed abnormal result is where delayed-diagnosis harm actually happens.

| Order | Sub-type | Examples | Where the rules live |
|---|---|---|---|
| 1 | **Screening-result loops** (spec B, structured) | Positive FIT, no colonoscopy report in 180 days. HPV 16/18, no colposcopy. BI-RADS 0/4/5, no work-up. LDCT "follow-up required", no thoracic referral. | catalog §2 |
| 2 | **Unrecognized conditions** | A1c ≥ 6.5% twice with no diabetes code. eGFR < 60 for 3+ months with no CKD code. Fragility fracture with no osteoporosis assessment. | catalog §8 |
| 3 | **Cancer screening** | Breast, cervix, colon, lung | catalog §2 |
| 4 | **Other screening** | BP, diabetes, lipids and CV risk, osteoporosis, AAA, HIV, HCV, STI | catalog §3 |
| 5 | **Immunizations** | Childhood schedule, school catch-up, Td, PCV20 at 65, RSV at 75, HPV deadline Dec 31, 2026 | catalog §4 |
| 6 | **Chronic disease monitoring** | Diabetes (A1c, ACR, eGFR, eye, foot, statin), CKD, HTN, CHF, COPD, high-risk drug monitoring | catalog §8 |
| 7 | **Life stage** | Well-child visits (Rourke 0 to 5, Greig 6 to 17), prenatal labs, advance care planning and MOST, hereditary cancer referral | catalog §5 to §7 |

The full rule list, with a BC source for every row, is in [`screening-catalog.md`](screening-catalog.md).

---

## 4. Denominator: who's in the cohort

Running rules on walk-ins, transfers, and the deceased inflates every count and sends recalls to people who aren't yours.

- **Include:** active in CHR, not deceased, primary provider ("PP") is the physician under review, at least one visit in the last 36 months.
- **Exclude:** walk-in or episodic only, transferred out, moved, deceased.
- **Reconcile** against your LFP panel in the Provincial Attachment System (PAS). CHR already has LFP dashboards for this: "active but not seen" and "seen but not active" lists, plus a PAS empanelment dashboard. Start there. Anyone in only one list goes on a panel-hygiene list.
- **Age** is computed at run date. Every age-triggered rule also reports "eligible within 90 days" so recalls batch well.

**Time-sensitive, and it isn't about screening:** from the Jul to Sep 2026 LFP period (paid Nov 30), panel size comes from PAS and counts only patients whose MRP status is "Confirmed". Complexity comes from ICD-9 codes on your claims. The research suggests the PAS cutoff for that period is **before Oct 1, 2026**. Worth checking the PAS dashboard for unconfirmed patients this week. That's straight revenue, and it's the same denominator work this plan needs anyway.

If the Patients export doesn't carry status and primary provider, the fallback is "seen in the last 36 months, primary provider from the chart header".

Run the denominator alone first and sanity-check the count before any rule runs.

---

## 5. Getting the data: export first, navigator for the rest

### 5.1 CHR's self-serve export

**Settings > Exports.** It needs the "Data export" permission and 2FA on your CHR account. It filters by date range, by provider, and by an uploaded CSV of patient IDs. Output is a password-protected ZIP of CSVs, and you get an email when it's ready. It's documented in CHR's help centre ("Exporting data from the CHR" and "Data export categories and content").

The code review found the exports screen empty. That most likely means no export had been run, or the account lacked the permission. It doesn't mean the feature's missing. Phase 0 settles it.

| Export | What the rules get from it | Verified? |
|---|---|---|
| **Patients** | Demographics, hopefully status and primary provider (the denominator) | Columns not documented. Check in Phase 0. |
| **Patient Data** | "All patient data values other than the Latest Lab Results and Patient Name". Probably medical, surgical, family, and social history, risk factors, vitals, and preventive care entries. CHR warns it's slow. | Columns not documented. This is the big one to inspect. |
| **Encounters** | Visit dates, diagnoses, and maybe note text | Not documented |
| **Prescriptions** | Two files: medications and prescriptions | Named, columns not documented |
| **Patient Injections** | Immunizations | Not documented |
| **Original Lab Messages** | **Raw HL7** from Excelleris and others (ID, created date, distributor, HL7 message, provider, file ID) | Documented. Structured OBX segments beat scraped lab tables. |
| **Patient Files** | Active files only (archived ones aren't exported). Unclear whether it's the PDFs or just a listing. | **Key unknown.** If it's only a listing, PDF contents come from the navigator or a per-patient chart PDF. |
| **Incoming Faxes** | Title, date, sender, patient. Good for classifying screening letters by sender. | Documented |
| **Imported Data** | Jane-era imported records | Documented |
| **Qnaire Responses** | Spec's category C | Not documented |
| **Schedule** | Upcoming bookings, for the pre-visit card | Not documented |

**Phase 0 test:** run each export for your own provider, filtered to 5 test patients, on the clinic Mac. Write down the column headers (no values) and map them to the concepts below. That's an hour's work, and it decides how much the navigator has to do.

### 5.2 What the rules need, and where it probably comes from

| Concept family | Export source (fallback: navigator screen) | Coded? | Notes for the rules |
|---|---|---|---|
| Demographics, sex at birth, status, primary provider | Patients (`property-items`) | Partly | Gender identity and sex at birth both matter (breast, cervix). Indigenous identity only if self-identified. It gates Hep A, RSV at 60, and COVID eligibility, and never appears in aggregates. |
| Conditions | Patient Data, Encounters (diagnoses) | MSP ICD-9 where coded, free text otherwise | Encounter and billing diagnoses catch conditions nobody put in Medical History |
| Surgical history (exclusions) | Patient Data (`surgical-history-records`) | Free text | Hysterectomy type, mastectomy, colectomy. LLM extraction target. |
| Family history | Patient Data (`family-history-records`) | Free text | Drives breast annual, colon 5-yearly, hereditary referral. LLM target. |
| Smoking, alcohol | Patient Data (`risk-factors`, `social-history-records`) | Probably free text | Lung eligibility hinges on it. Missing = its own gap. |
| Medications | Prescriptions | Name strings, no DIN seen | Name-to-ATC table (statins, immunosuppressants, DOACs, lithium, glucocorticoids) |
| Immunizations | Patient Injections | Unknown | Incomplete by design: pharmacy and school doses mostly aren't in CHR |
| Labs | Original Lab Messages (HL7) | OBX codes (local, maybe LOINC) | Lab code/name table for A1c, ACR, eGFR, lipids, Lp(a), FIT, HPV, HIV, HCV, TSH, drug levels. Cervix screening reports carry the next due date. |
| Vitals | Patient Data (`vitals`) | Probably structured | BP, weight, height |
| Screening reports | Patient Files + Incoming Faxes (fallback: navigator) | PDF | On-device OCR, then extraction of BI-RADS, HPV result and next due date, colonoscopy findings and recommended interval, LDCT category, DXA T-score |
| Visits | Encounters | Dates, diagnoses | Denominator activity window, well-child visit timing |
| Pregnancy | Encounters, labs, Patient Data | Mixed | Triggers the prenatal rule set |

### 5.3 CHR's own preventive care module

CHR has a per-patient Preventive Care section and a "Preventative Care Report" dashboard with compliance by provider (ask support to install it if it isn't there). **Switch it on in week 1 as a free baseline**, but don't trust its BC defaults. Cervix is still Pap + HPV every 3 years, diabetes screening is every 5 years, and it only counts its own structured entries, not PDF results. Catalog §10 has the comparison. Our rule output should beat it, and the gap between the two is a useful sanity check.

### 5.4 What CHR won't have

A lot of this happens outside the clinic, and it only reaches CHR if the patient named you:

- Self-referred mammograms (and **BC Cancer sends providers no overdue reminders for breast**)
- HPV self-screening kits
- FITs ordered by walk-ins or other providers
- Pharmacy and public-health immunizations, which live in the provincial registry (CareConnect, Health Gateway)
- School-program vaccines (grade 6 and 9)
- Colonoscopies and imaging in other health authorities
- Jane-era and "Historical Chart" history, which sits in documents, not coded fields

So **"not found in chart" never counts as "overdue".** Section 6.3 makes that a first-class state, and section 8 puts a CareConnect check between the rules and any outreach.

---

## 6. Rules

### 6.1 Concept layer

A curated table maps ICD-9 codes, free-text synonyms, lab test names, drug names, and document keywords to about 150 internal concepts (`dx.diabetes`, `obs.a1c`, `screen.mammogram`, `proc.hysterectomy_total`, `imm.pcv20`). It's built and clinician-signed before the rules, as the spec says. Lives in `valuesets/`.

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
evidence_sources: [lab-results, files:Consults, files:Hospital]
declined_valid_months: 24
action:
  kind: order            # physician orders FIT; patients can't self-order
  mode: book_or_order    # MOA books, or physician orders at next visit
review_by: 2027-03-01    # BC Cancer is "investigating" starting at 45
owner: ali
```

Every rule carries its source, the date it was checked, a review-by date, and an owner. BC changed cervix, breast, colon follow-up, and pneumococcal rules in 2024 to 2026, and the federal Task Force was wound down in March 2026. CI fails when any rule is past its review-by date.

**⚠ decide:** YAML here plus a small Python evaluator, or ACA-style Python modules (the spec's suggestion, reusing ACA's registry and `missing_inputs`)? I'd keep the *content* in YAML either way, so you can edit rules without touching code, and have a thin ACA module that loads it. You get ACA's machinery and a clinician-editable source of truth.

### 6.3 Evidence states

Every eligible patient gets exactly one state per rule. The review queue shows the state, the evidence, and (for "not found") where it looked.

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

`NOT_FOUND` vs `OVERDUE` matters most for immunizations and self-referred cancer screening. `DISCUSS` keeps "available" or "optional" items off the recall list.

### 6.4 Engine

Deterministic Python, no LLM. In: the normalized store, the concept layer, and the rules. Out: `(patient_id, rule_id, rule_version, state, due_date, evidence_ids[], searched_sources[], run_id)`. The same inputs always give the same output, so every run can be diffed against the last.

---

## 7. Where the LLM and OCR fit

LLMs do one job: **turn unstructured chart content into facts**, each with a quoted span that has to match the source exactly (the spec's traceability rule). They never decide whether something's a gap.

For category A the extraction targets are narrow:

- **Screening reports:** BI-RADS category and density, HPV result and the lab's printed next-due date, colonoscopy findings and the recommended interval, LDCT result category, DXA T-scores
- **Free text:** smoking status and pack-years, family history of breast, colorectal, ovarian, and pancreatic cancer, hysterectomy type, informed refusals ("declines FIT"), goals of care

Keyword and concept matching runs first. Only documents that could satisfy a rule go to the model, which cuts volume a lot.

**Hosting options:**

| Option | Residency | Cost | Catch |
|---|---|---|---|
| **On-device on the clinic Mac (recommended first).** Apple Vision OCR plus an open-weight ~30B mixture-of-experts model via MLX or Ollama on a 64 GB Mac mini | PHI never leaves the clinic, so the CPSBC consent clause doesn't come up | Hardware you may already have | Slower. Extraction is prompt-heavy, so budget roughly 5 to 10 s per 3k-token document for an MoE model. It runs overnight. Needs its own accuracy check. |
| **Azure OpenAI Canada East, regional deployment** | In Canada (regional only; Global and Data Zone route out of Canada) | gpt-4.1-mini at US$0.48 in / $1.94 out per M tokens | Only gpt-4.1-mini and gpt-4o are regional in Canada, and **both retire April 14, 2027**. GPT-5 in Canada needs provisioned throughput, about US$8.5k a month minimum. Batch discounts are Global-only. |
| Azure Document Intelligence, Canada Central (OCR only) | In Canada, 24-hour retention | Read US$1.50 per 1,000 pages | Only if on-device OCR isn't good enough on faxes |

Money isn't the deciding factor. A 2,000-patient panel at 60k tokens a patient is about 120M input tokens, roughly US$60 on Canada East. The first pass of scanned pages is in the low hundreds of dollars on Document Intelligence, or free on-device. Residency, consent, and model retirement are what matter.

Time does matter with the on-device route. At 5 to 10 s per document and maybe 20 relevant documents per patient, a 2,000-patient first pass is 55 to 110 hours of model time. That's one to two weeks of nights on one Mac, the same order as the spec's chart walk. Keyword pre-filtering is what keeps it there, and refreshes after that take minutes.

---

## 8. From gap to closed gap

This follows the spec's queue and adds what category A needs:

1. **Panel dashboard, aggregates only:** per rule, eligible / up to date / due / overdue / not found, by age band. This is the baseline, and it shows progress over time.
2. **Queue order:** screening-result loops first (physician review within a week of each run), then unrecognized conditions, then cancer screening, immunizations, chronic monitoring, life stage.
3. **CareConnect check** on every `NOT_FOUND` before outreach. "Found externally" back-fills the store and teaches the rule where to look ("already done" in the spec).
4. **Outreach matched to how Bonne Vie runs:**
   - Needs a visit (loops, chronic monitoring, well-child, anything needing a conversation): **MOA books**. The script carries no clinical detail ("Dr. X would like to see you for a check-up"). CHR auto-sends SMS and email on booking, so the MOA confirms before saving.
   - Patient can self-arrange: breast (1-800-663-9203), cervix self-screening kit (1-877-702-6566 or online), lung (1-877-717-5864), and flu, COVID, and PCV20 at a pharmacy. A physician-approved patient message with the number. FIT isn't in this group, since BC requires a physician or NP order.
   - Later: Autochart.ai Voice for recall calls.
5. **Pre-visit card:** open category A items for each booked patient on the day sheet. Most gaps close opportunistically. It's also the natural hook into Autochart.ai Scribe pre-charting.
6. **Weekly re-run** on patients with new activity, per the spec. The ledger keeps open, closed, and declined history, so closure rate per rule is a real number.

**Time-sensitive this quarter:** HPV9 catch-up for people born 1998 and 1999 (and 1979 and 1980 in the expanded group) has to be finished by **Dec 31, 2026**. If the harvest isn't ready by November, pull that list by hand from date of birth.

---

## 9. Validation

1. **Synthetic suite (this repo, CI):** every rule gets hand-built patients at its edges. That means age 49.99 vs 50.00 and 74.99 vs 75.00, one day inside and outside the interval, exclusion present, decline present, and contradictory data. Synthea covers bulk and performance.
2. **Chart audit (outside this repo):** a stratified random sample of 100 patients across age bands, reviewed by hand against the engine. Compute per-rule positive predictive value and sensitivity. A rule reaches the queue only at **PPV ≥ 90% and sensitivity ≥ 85%**. Below that it runs in shadow mode. That's stricter than the spec's 70% acceptance gate on purpose: category A is deterministic, so it should be precise.
3. **Extraction check:** about 200 hand-labelled documents across report types. Per-field accuracy (BI-RADS, next-due date, T-score, colonoscopy interval) has to clear the bar before the screening-result loops go live.
4. **"Already done" rate** from the queue, per rule, as the spec proposes. A high rate means a data source is missing, not that the rule's wrong.
5. **Regression:** any change to a rule, value set, or model reruns the synthetic suite and diffs the ledger against the last live run.

---

## 10. Phasing

This repo's work can start today and runs alongside the spec's phases.

| When | This repo | Spec phase it lines up with | Exit criteria |
|---|---|---|---|
| **Week 1** | Repo private, PHN hook. Grant yourself Data export + 2FA. Run the 5-patient export test (§5.1) and record column headers only. Turn on CHR's Preventative Care Report and check the LFP/PAS dashboards. | 0 (map screens) | Headers mapped to concepts. We know whether Patient Files carries PDFs. |
| **Weeks 1 to 2** | Catalog signed off, concept layer v1, export loader (CSV + HL7), rules for cancer screening + loops, evaluator, synthetic suite in CI | 0 and 1 (walk and store), with the navigator scoped down to what the export lacks | You've signed the catalog. CI is green on every edge case. |
| **Weeks 3 to 4** | Remaining adult screening, immunizations, unrecognized conditions, chronic monitoring for DM, HTN, CKD | 1 and 2 | Full-panel export loaded on the clinic Mac. Rules run in shadow mode on your panel. |
| **Weeks 5 to 6** | Extraction schemas and prompts for screening reports and free-text facts. On-device model chosen and checked. | 3 (category A) | Extraction check passes. 100-chart audit hits PPV and sensitivity thresholds. |
| **Weeks 7 to 8** | Pediatrics (Rourke, Greig, childhood and school immunizations), prenatal, life-stage rules | 3 continued | First month of closure-rate data |
| **Later** | Colleagues' panels with sign-off. Decide what becomes an Autochart.ai care-gap feature. | beyond 5 | Productizing moves this from internal QI to a Health Canada SaMD question, which is its own decision. |

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| "Gap" that's really data sitting outside CHR | `NOT_FOUND` state, CareConnect check, "already done" feedback |
| Bad extraction giving false reassurance (wrong BI-RADS, wrong interval) | Exact-quote rule, extraction check, physician review of every screening-result loop |
| Alert fatigue | `DISCUSS` state keeps optional items off recall lists, rules ship in phases, shadow mode below threshold |
| Guideline drift | Source, checked date, review-by date, and owner on every rule. CI fails on stale rules. |
| PHI in git, logs, or prompts | Private repo, PHN pre-commit hook, no PHI in logs, on-device first |
| Recall volume swamping the MOAs | Batch by due date, cap weekly recalls, loops first |
| CHR terms of use and audit visibility of overnight walks | Export-first shrinks the walk to what the export lacks. Still worth one call to TELUS before any overnight run. |
| Export columns turn out thinner than hoped | The navigator is the fallback for any concept the export lacks. Phase 0 tells us which ones, before any code depends on them. |
| Export ZIPs sitting around with the whole panel's PHI | Download only to the encrypted clinic Mac, never email or cloud-sync them, delete after ingest, and log each export in the PIA's records |
| gpt-4.1-mini retiring April 2027 if Azure's chosen | Prompt and schema written to be model-agnostic, with an extraction check rerun on any model swap |

---

## 12. Decisions I need from you

1. **Export-first:** OK to change the spec so the baseline comes from CHR's export and the navigator only fills gaps? If yes, who on the CHR account gets the Data export permission? It's a lot of PHI in one ZIP, so I'd keep it to you.
2. **Repo role:** is clinic_review the home for the rules, the concept layer, and the export loader (what this plan assumes), with the Mac app consuming the output? Or should rules live in ACA from day one?
3. **LLM hosting:** on-device first (recommended), or Azure Canada East?
4. **Consent position for the PIA:** direct care (implied consent) or secondary use (notice or express consent)? Worth a quick question to Jon at Fasken.
5. **Panel scope for v1:** your panel only (recommended)?
6. **Denominator:** is 36 months since the last visit the right activity window? And have you checked PAS for unconfirmed patients before the Oct 1 cutoff?
7. **Contested rules:** 13 of them, each with my recommendation, in catalog §9. The big ones are the hypertension threshold (BC 135/85 vs Hypertension Canada 130/80), osteoporosis (FRAX-first vs BMD at 70), and whether breast 40 to 49 is a gap or a discussion.

---

## Proposed repo layout

```
clinic_review/
  docs/                 plan, catalog, PIA outline (no PHI)
  rules/                one YAML per rule
  valuesets/            concept layer: ICD-9, lab names, drug→ATC, document keywords, vaccine→antigen
  src/clinic_review/
    ingest/             CHR export loader (CSV + HL7), normalizer into the fact store
    engine/             evaluator, evidence states, ledger
    extract_schemas/    JSON schemas + prompts for report and free-text extraction
    report/             dashboard aggregates, queue export, pre-visit card
  tests/
    fixtures/           synthetic patients only
```

The navigator, the encrypted store, and the queue UI live in the Mac app, per the spec. The export loader lives here, so the whole pipeline can run on the clinic Mac from an export before the navigator exists.
