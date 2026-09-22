# Screening and care-gap rule catalog (ages 0 to 100, BC)

Catalog v0.1, sources checked 2026-09-22. Every row becomes one YAML rule in `rules/`. Everything here is category A (preventive and chronic-care gaps) in the CHR Panel Review Spec, except the screening-result loops, which are the structured part of category B. Sub-types match [PLAN.md](PLAN.md) section 3: **loop**, **unrecognized**, **cancer**, **screening**, **immunization**, **chronic**, **life stage**.

"Evidence" is where the engine looks for proof, in the order it checks: `lab` structured result, `doc` scanned or faxed report, `bill` MSP claim, `imm` immunization record, `prob` problem list, `note` free text (LLM), `vital`.

Items marked **⚠ decide** are places where sources conflict or there's a real clinical choice. They're collected in section 9.

---

## 1. Source hierarchy

When sources disagree, the higher one wins unless you override it:

1. BC organized programs: BC Cancer Screening Guidelines (May 2026) and program pages, BCCDC Communicable Disease Control Manual Chapter 2 (Immunization, Sept 2026 schedules), BCCDC STI testing table (May 2026), Perinatal Services BC
2. BC Guidelines (GPAC)
3. National specialty guidelines: Hypertension Canada, Diabetes Canada, CCS lipids, Osteoporosis Canada, CPS, Rourke Baby Record 2024, Greig Health Record 2025
4. Canadian Task Force on Preventive Health Care (archived; its mandate ended March 31, 2026 and the new National Advisory Committee on Preventive Health Services hasn't issued anything yet). Existing recommendations still inform rules where nothing BC-specific exists, but they won't be updated.

---

## 2. Cancer screening and screening-result loops

### 2.1 Breast (BC Cancer Breast Screening)

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `breast.avg.50_74` | Female sex at birth (or trans on estrogen ≥ 5 y), 50 to 74, average risk | Screening or diagnostic mammogram `doc` | 2 y | Self-referral: 1-800-663-9203. Patient message, not an order. |
| `breast.avg.40_49` | Same, 40 to 49 | Same | 2 y | "Available", not "recommended". State `DISCUSS`, not a gap. |
| `breast.fdr` | 40 to 74 with a first-degree relative with breast cancer | Same | **1 y** | Family history comes from `note`/`prob`. Missing family history on a 40+ patient makes this `UNKNOWN`. |
| `breast.high_risk` | Known BRCA1/2, PALB2, CDH1, PTEN, STK11, NF1 carrier, untested FDR of a carrier, or very strong family history | Mammogram (± MRI via program) | 1 y from 30 | Also check Hereditary Cancer Program referral exists (`doc`). |
| `breast.chest_rt` | Chest radiation age 10 to 30 | Same | 1 y | **⚠ decide** (§9 #4): start at 25 (Guidelines PDF, Fact Sheet) or 30 (web page). |
| `breast.75plus` | 75+ in good health | Same | 2 y | `DISCUSS`. Suppressed if frailty or life-limiting illness is coded. |

Exclusions: personal breast cancer (surveillance, not screening), implants, bilateral mastectomy, chest construction (not addressed by BC Cancer, so this is a manual exclusion), pregnancy or breastfeeding in the last 3 months.

**BC Cancer sends no overdue reminder to providers for breast**, only to patients. So this is the rule where the clinic list adds the most.

Screening-result loops:
- `breast.loop.birads_0_4_5`: BI-RADS 0, 4 or 5 with no diagnostic imaging or biopsy report within 60 days
- `breast.loop.birads_3`: BI-RADS 3 with no 6-month follow-up imaging within 8 months

### 2.2 Cervix (BC Cancer Cervix Screening)

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `cervix.hpv` | Has a cervix, 25 to 69, ever sexually active | HPV test (self or provider collected) `lab`/`doc` | 5 y | **Easiest rule to get right: the Cervical Cancer Screening Lab report prints the next due date.** Parse that date and use it in place of computing one. |
| `cervix.cytology` | Same, last screen was cytology (LBC under 40 as of May 2026) | NILM cytology | 3 y | Lab moves to HPV on LBC for 25+ in Jan 2027. |
| `cervix.immunocompromised` | Transplant, blood cancer, primary immunodeficiency, dialysis/severe CKD, on immunosuppressants (anti-TNF, MTX, AZA, MMF, JAK, anti-CD20) now or in the last 2 y | HPV test | **3 y**, to 74 | Immunosuppressant exposure comes from the med list via ATC. **⚠ decide:** HIV isn't clearly in BC Cancer's list (BC Guideline lists it as a risk factor). Stop rule at 74 also conflicts between sources. |
| `cervix.exit_70plus` | 69+ never screened or no screen in 5 y | One HPV test | Once | Stop if negative. |

Exclusions: total hysterectomy with no CIN2/3 or AIS history (subtotal still screens), neovagina, under 25 regardless of history. Post-treatment CIN2/3 or AIS follows a cotest schedule (12 months, then every 3 years), so these patients get their own rule `cervix.post_treatment`.

Screening-result loops:
- `cervix.loop.hpv1618`: HPV 16/18 or high-grade cytology with no colposcopy report within 4 months (BC Cancer arranges colposcopy, so this checks it happened)
- `cervix.loop.hpv_other_self`: HPV "other" on a self-collected swab with no LBC within 6 weeks (this one lands on the provider)
- `cervix.loop.hpv_other_repeat`: HPV "other" with NILM/ASCUS/LSIL and no repeat HPV at 12 months (+2 months grace)

### 2.3 Colon (BC Cancer Colon Screening)

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `colon.fit` | 50 to 74, average risk | FIT `lab` | 2 y | Or colonoscopy/flex sig 10 y, CT colonography 5 y. **Physician or NP must order**; patients can't self-order. Requisition box: "FIT (Age 50-74 asymptomatic q2y) Copy to Colon Screening Program". |
| `colon.family_history` | One FDR diagnosed under 60, or 2+ FDRs at any age | Colonoscopy `doc` | **5 y** | Start at 40 or 10 years before the youngest relative's diagnosis. Family history is almost always free text, so it's an LLM extraction target. |
| `colon.surveillance` | Prior colonoscopy with polyps | Colonoscopy | Per report: 6 mo (piecemeal), 1 y (10+ lesions), 3 y (5 to 9 low risk or any high risk), 5 y (FDR), 10 y | Read the endoscopist's recommended interval from the report, then check it against the BC Cancer July 2025 algorithm. Flag disagreements. |
| `colon.75_84` | 75 to 84 | FIT (no-copy requisition) | Individual | `DISCUSS`. 85+: not recommended. |

Not included: 45 to 49 (BC Cancer says not recommended; it's "investigating" dropping to 45, and the rule's review date is set to catch that). **⚠ decide** whether to show 40 to 49 as a discussion item, since the Dec 2025 Decision Table allows individual FIT.

Exclusions: colorectal cancer or IBD (specialist follow-up), total colectomy (manual exclusion, not covered by BC Cancer), symptoms (go to diagnostic work-up).

Screening-result loops:
- `colon.loop.fit_positive`: positive FIT with no colonoscopy report within 180 days (BC Cancer and Fraser Health book it, so this catches the ones that fell through)
- `colon.loop.surveillance_overdue`: surveillance colonoscopy past the report's recommended date + 3 months

### 2.4 Lung (BC Cancer Lung Screening)

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `lung.eligibility` | 55 to 74, current or former regular commercial tobacco smoker | Program risk assessment or LDCT `doc` | 2 y (1 y or 3 mo per result) | **Patient self-refers by phone**: 1-877-717-5864. The program calculates PLCOm2012 (≥ 1.5%), so the engine flags "possibly eligible", not "eligible". |
| `lung.smoking_unknown` | 55 to 74 with no smoking status recorded | Smoking status in `vital`/`note` | Once | **This is the real gap for most patients.** State `UNKNOWN`; action is "record smoking history". |

Exclusions: prior lung cancer, active nodule surveillance, home O2 or severe COPD, heart failure, dialysis, other active cancer.

Screening-result loop: `lung.loop.followup_required`: LDCT "additional screening" or "follow-up required" with no repeat CT or thoracic referral within 4 months.

### 2.5 Prostate

`prostate.psa_sdm`: off by default. BC Guideline (2020): men 55 to 69 with > 10 years' life expectancy may choose PSA after informed discussion. Screening PSA isn't MSP-insured (~$35 patient pay). If turned on, it's `DISCUSS` only, and the open loop `prostate.loop.psa_rising` (PSA above age threshold or velocity with no repeat or urology referral) runs regardless of the screening setting.

### 2.6 Hereditary cancer referral (life stage)

`hereditary.referral_criteria`: flag patients whose documented family history meets BC Cancer Hereditary Cancer Program criteria (rewritten March 9, 2026) and who have no referral or genetics consult on file. Examples: a relative with a known pathogenic variant, FDR with ovarian or pancreatic cancer, FDR with metastatic prostate cancer, 10+ adenomas by 60. Entirely free-text driven, so this ships in phase 2.

---

## 3. Other adult screening

### 3.1 Cardiometabolic

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `bp.adult` | 18+ | BP in `vital` | 12 mo | BC says "every appropriate visit". 12 months matches CHR's own default. |
| `lipids.cv_risk` | 40+ (any sex), or any age with HTN, diabetes, CKD, or premature family CVD (FDR male < 55, female < 65) | Lipid profile `lab` | 5 y (sooner if FRS 10%+) | BC CVD Primary Prevention 2021/2023 and CCS 2021. Non-fasting is fine. CCS risk tools stop at 75, so 76+ becomes `DISCUSS`. |
| `lipids.lpa_once` | Anyone with a lipid profile | Lp(a) `lab` ever | Once | BC and CCS. ≥ 50 mg/dL (≥ 100 nmol/L) is a risk enhancer. |
| `dm.screen` | 40+, or younger with risk factors (prior GDM, PCOS, BMI ≥ 30, antipsychotics, HIV, high-risk ethnicity) | A1c or fasting glucose `lab` | 3 y. **6 to 12 mo if prediabetes** (A1c 6.0 to 6.4% or FPG 6.1 to 6.9) | Diabetes Canada 2018, adopted in the BC Diabetes Care guideline. CHR's built-in default is every 5 years, which is out of date. |

### 3.2 Bone

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `bone.frax_65f` | Female 65+ | FRAX documented (`note`) or BMD `doc` | FRAX once, then per result | CTFPHC 2023 FRAX-first. BMD only if treatment's on the table. MSP pays for BMD at 10-year risk ≥ 10%, and **not within 3 years of the last BMD** (exceptions: prednisone ≥ 7.5 mg for ≥ 3 months, primary hyperparathyroidism). |
| `bone.bmd_repeat` | Untreated, prior BMD | BMD | By 10-y risk: < 10% 5 to 10 y, 10 to 15% 5 y, ≥ 15% 3 y. On treatment: 3 y after start. | Osteoporosis Canada 2023 intervals, floored at MSP's 3-year minimum |
| `bone.glucocorticoid` | Prednisone ≥ 7.5 mg/day (or equivalent) for ≥ 3 months | BMD | Once, then per MSP | From the med list via ATC |
| `bone.men_70` | Male 70+ | BMD or FRAX | Once | Osteoporosis Canada only (CTFPHC says don't screen men). **`DISCUSS`**, not a gap. **⚠ decide.** |

### 3.3 Vascular

`aaa.men_65_80`: male 65 to 80, one abdominal aortic ultrasound ever (or CT/US report mentioning the aorta). CTFPHC 2017 weak recommendation, and there's no BC program. Low priority. Also feeds `statin.indicated` (AAA > 3.0 cm).

### 3.4 Infectious disease

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `hiv.routine` | 18 to 70 | HIV Ag/Ab `lab` | 5 y | BCCDC HIV testing guideline (May 2026). **Annual** for GBMSM, people who inject drugs, sex workers, people from endemic countries (flags). 70+ with status never tested: once. |
| `hcv.cohort` | Born 1945 to 1965 | Anti-HCV `lab` ever | Once | BC Viral Hepatitis Testing 2021: "can be considered". Cheap, curable, low priority. Annual if risk is ongoing. |
| `hbv.newcomer` | Born in an endemic country | HBsAg + anti-HBc ever | Once | Needs country of birth, which is rarely structured. Shadow mode until it's captured. |
| `sti.under30` | 15 to 29 | CT/GC NAAT, HIV, syphilis | 12 mo | BCCDC (May 2026) uses **under 30** if sexually active. Sexual activity is rarely charted, so this is **pre-visit card only, never a recall**. |
| `tb.newcomer` | Arrived from a country with TB incidence ≥ 50/100k, within 2 to 5 years (see Canadian TB Standards 2022, ch. 13) | IGRA or TST | Once | Needs arrival date and country. Parked for v1. |

### 3.5 Behaviours

| Rule | Population | Satisfied by | Interval | Notes |
|---|---|---|---|---|
| `tobacco.status` | 12+ | Smoking and vaping status recorded | 12 mo | BC Tobacco Use Disorder 2024 (ask everyone, including youth, about vaping). If current smoker: cessation offer documented. Also unlocks `lung.eligibility`. |
| `alcohol.status` | 12+ | Alcohol use recorded against Canada's Guidance on Alcohol and Health | 12 mo | BC 2024 and the CRISM 2026 update (screen adults and youth 12 to 25). Pre-visit card only. |

### 3.6 Deliberately not rules

These come up a lot. Leaving them out is a decision, not an oversight:

- **Depression screening questionnaires:** CTFPHC 2025 strongly recommends against screening all adults. PHQ-9 results that *were* done and not acted on belong to the spec's category C.
- **Cognitive screening** in asymptomatic older adults: CTFPHC against (reaffirmed 2024), BC 2014 agrees. Exception: BC suggests screening people with cerebrovascular disease, but gives no interval.
- **Hearing:** no CTFPHC or BC recommendation found.
- **Vision 65+:** CTFPHC against screening in primary care. MSP covers an annual optometry exam at 65+, so it goes on the pre-visit card as a reminder, not a gap.
- **Frailty population screening:** BC 2017 says no.
- **Routine TSH, vitamin D, CA-125, screening ECG:** BC guidelines advise against routine testing.
- **PSA:** off by default (§2.5).

---

## 4. Immunizations

Source: BCCDC CD Manual Ch. 2, Part 1 Schedules (Sept 2026) and Part 4 product pages. Doses count from **chronological age**.

### 4.1 Routine childhood

| Age due | Antigens | Rule |
|---|---|---|
| 2 mo | DTaP-HB-IPV-Hib, PCV20, Men-C-C, rotavirus | `imm.child.2m` |
| 4 mo | DTaP-HB-IPV-Hib, PCV20, rotavirus | `imm.child.4m` |
| 6 mo | DTaP-HB-IPV-Hib (+ influenza seasonally, Hep A if Indigenous, PCV20 if high risk) | `imm.child.6m` |
| 12 mo | MMR, varicella, PCV20, Men-C-C | `imm.child.12m` |
| 18 mo | DTaP-IPV-Hib (+ Hep A dose 2 if Indigenous) | `imm.child.18m` |
| 4 to 6 y | Tdap-IPV, MMRV (MMR if lab-confirmed varicella ≥ 12 mo) | `imm.child.4_6y` |

Rules evaluate per antigen, not per visit, so a combo product satisfies each antigen it contains. Grace period before `OVERDUE`: 2 months for infant doses, 12 months for the 4 to 6 year dose. Rotavirus closes at 8 months (never flag after that).

### 4.2 School program (catch-up check)

| Grade | Antigens | Rule |
|---|---|---|
| Grade 6 | HPV9 (1 dose, 3 if immunocompromised), HepB and varicella catch-up | `imm.school.gr6` |
| Grade 9 | Men-C-ACYW, Tdap | `imm.school.gr9` |

Use age as a proxy for grade (grade 6 ≈ 11 to 12, grade 9 ≈ 14 to 15). Public health gives these at school, so they're usually **not in CHR**. Missing school doses default to `NEVER_FOUND`, not `OVERDUE`, until checked in the provincial registry.

### 4.3 Adults

| Rule | Population | Satisfied by | Interval / dose | Notes |
|---|---|---|---|---|
| `imm.td` | 18+ | Td or Tdap `imm` | 10 y | Adults born 1989+ who missed adolescent Tdap get one funded Tdap. |
| `imm.mmr` | Born on or after 1970-01-01 | 2 documented measles/mumps doses or immunity | 2 doses | Rubella: 1 dose if born 1957+. |
| `imm.varicella` | Susceptible adults | 2 doses or lab-confirmed immunity or disease before 2004 | 2 doses | "Susceptible" definition is detailed; mostly `UNKNOWN` in charts. Low priority. |
| `imm.hpv` | 9 to 26 (to 45 for GBMSM, Two-Spirit, trans, non-binary; HIV 9 to 45) | HPV9 doses | 1 dose (9 to 20), 2 doses ≥ 24 wks apart (21 to 26), 3 doses if HIV/immunocompromised/post-colposcopy treatment | **Deadline:** people born 1998/1999 (and 1979/1980 in the expanded group) must finish by **Dec 31, 2026**. High-urgency recall this quarter. |
| `imm.hepb` | Born 1980+ or risk group | 3 doses or immunity | Series | |
| `imm.menacwy` | Born 2002+, to age 24 | 1 dose Men-C-ACYW | Once | |
| `imm.flu` | 6 mo+ | Seasonal dose `imm` | Each season (Oct to Mar) | 65+: Fluad is the funded product. Children < 9 in first season: 2 doses. Much of this happens at pharmacies. |
| `imm.covid` | 65+, Indigenous, LTC, pregnancy, medical conditions (2025-26 criteria) | Seasonal dose | Per season | **⚠ Fall 2026-27 criteria aren't published yet.** Rule stays in shadow mode until they are. |
| `imm.pcv20.65` | 65+ | Any PCV20, PCV21, or PPV23 ever | Once | **Anyone with prior Pneumovax (PPV23) counts as done.** PCV21 isn't funded. |
| `imm.pcv20.risk` | 5+ with a high-risk condition (diabetes, chronic heart/lung/liver/kidney disease, asplenia, HIV, immunosuppression, cancer, CSF leak, cochlear implant, homelessness, SUD, LTC resident) | PCV20 | Once | Conditions come from the fact store, so this is a good example of B feeding D. |
| `imm.rsv.older` | 75+, or Indigenous 60+ | Any RSV vaccine ever | Once (mRESVIA) | New Sept 14, 2026. Anyone who's had any RSV vaccine isn't eligible again. |
| `imm.zoster` | 50+ | Shingrix × 2 | Once | **Not publicly funded in BC** (except FNHB Plan W clients 60+). `DISCUSS`, not a gap. |

Flags the engine needs for immunizations: Indigenous identity (self-identified only), LTC residence, pregnancy, immunocompromise, health care worker, GBMSM/2STNB. These are sensitive. They're only used for eligibility and never appear in aggregate reports.

---

## 5. Pregnancy (only when a pregnancy is active)

Trigger: pregnancy coded, or an EDD or positive β-hCG in the last 40 weeks with no delivery documented. Source: Perinatal Services BC lab tests by trimester (Aug 2026).

| Window | Expected | Rule |
|---|---|---|
| 8 to 14 wks | Group and screen, CBC, ferritin, HIV, syphilis, HBsAg, anti-HCV, rubella (if first pregnancy or no record), CT/GC, urine culture | `preg.initial_labs` |
| 9 to 20+6 wks | Prenatal genetic screening offered (SIPS/IPS/quad) | `preg.genetic_offer` |
| 24 to 28 wks | GDM screen (50 g GCT → 75 g OGTT), CBC, antibody screen if Rh-negative | `preg.24_28` |
| 27 to 32 wks | Tdap | `imm.tdap.pregnancy` |
| 36+ wks | GBS swab | `preg.gbs` |
| Delivery | Syphilis test | `preg.delivery_syphilis` |

Most prenatal care may be shared with a maternity clinic, so these are `NEVER_FOUND` by default and routed to the physician, not the MOA.

---

## 6. Well-child care

### 6.1 Ages 0 to 5: Rourke Baby Record 2024

| Rule | What | Evidence |
|---|---|---|
| `wellchild.visits` | Visits at ~1 wk, 1, 2, 4, 6, 12, 18 mo, 2 to 3 y, 4 to 5 y (2 wk, 9 mo, 15 mo optional) | `bill` (visit claims), `note` |
| `wellchild.growth` | Weight, length/height, head circumference (to 2 y) at each visit | `vital` |
| `wellchild.vision` | Visual acuity documented at 3 to 5 y | `note` |
| `wellchild.hearing_newborn` | BC Early Hearing Program result on file | `doc` |
| `wellchild.nbs` | Newborn blood spot result on file | `doc` |
| `wellchild.iron_risk` | Hb/ferritin at 6 to 18 mo **if at risk** (prematurity, LBW, cow's milk < 9 mo or > 500 mL/d, recent newcomer, food insecurity) | `lab` + risk from `note` |
| `wellchild.mchat` | M-CHAT at 18 to 24 mo **if risk factors** (sibling with ASD, concerns) | `note` |
| `wellchild.bp` | BP from age 3 | `vital` |
| `wellchild.lipids` | Non-HDL or LDL once between 2 and 10 (CPS, April 2026, universal) | `lab` |

Rourke is mostly documented in narrative, so well-child rules lean on `note` extraction and on MSP visit claims as a proxy. Accept that v1 checks "was there a well visit at roughly the right age", not every Rourke item.

### 6.2 Ages 6 to 17: Greig Health Record 2025

| Rule | What |
|---|---|
| `youth.annual_or_biennial_visit` | Periodic health visit at 6 to 9, 10 to 13, 14 to 17 |
| `youth.bmi` | BMI/height/weight in the last 2 years |
| `youth.bp` | BP in the last 2 years |
| `youth.headss` | HEADSS/psychosocial assessment from 12 |
| `youth.sti` | Annual CT/GC, HIV, syphilis if sexually active (§3.4; BC uses under 30) |

---

## 7. Older adults

| Rule | Population | What | Notes |
|---|---|---|---|
| `older.falls` | 65+ | Falls screen (3 questions or Staying Independent Checklist) in the last 12 months | BC Fall Prevention 2021. A "yes" means a multifactorial assessment. Pre-visit card. |
| `older.acp_most` | 80+, or Clinical Frailty Scale ≥ 5, or advanced HF, COPD, CKD stage 4 to 5, or dementia | ACP conversation or MOST (Fraser Health M1 to M3 / C0 to C2) on file | No guideline gives an interval, so this trigger is a design choice. MOST completed by a physician or NP. |
| `older.dmer_heads_up` | Turning 80, 85, then every 2 years | Informational only | RoadSafetyBC mails the DMER about 2 months before the birthday. Not MSP-insured. Not a gap, just a heads-up on the pre-visit card. |
| `older.deescalate` | CFS ≥ 7, palliative code, or hospice | Suppresses screening rules (states become `DISCUSS`) | Design choice. Stops the engine asking a 92-year-old in hospice for a FIT. |

Also age-triggered at 65+ and 75+: `imm.pcv20.65`, `imm.flu` (Fluad), `imm.rsv.older`, `imm.covid`. Screening stop ages are built into each cancer rule (breast and colon 74, cervix 69, lung 74).

---

## 8. Unrecognized conditions and chronic disease monitoring

### 8.1 Unrecognized conditions

These find patients whose data already meets a diagnosis that isn't on their chart. They're cheap, high yield, and they feed the chronic monitoring rules. **They also matter for LFP.** From the Jul to Sep 2026 period, LFP panel complexity comes from the CIHI grouper using ICD-9 codes on MSP claims, so an uncoded diabetic or CKD patient is under-counted.

| Rule | Criteria | Not flagged if |
|---|---|---|
| `unrec.diabetes` | A1c ≥ 6.5% twice, or A1c ≥ 6.5% plus FPG ≥ 7.0, or FPG ≥ 7.0 twice (Diabetes Canada) | ICD-9 250 on problem list or claims, or a diabetes medication (metformin alone isn't enough: PCOS, prediabetes) |
| `unrec.prediabetes` | A1c 6.0 to 6.4% or FPG 6.1 to 6.9 | Moves `dm.screen` to a 6 to 12 month interval rather than raising a new gap |
| `unrec.ckd` | eGFR < 60 on 2 results ≥ 90 days apart, or ACR ≥ 3 mg/mmol twice ≥ 90 days apart | ICD-9 585 or a CKD problem-list entry |
| `unrec.htn` | Office BP at or above threshold on ≥ 2 visits within 6 months | HTN code or an antihypertensive. **⚠ decide threshold** (§9). |
| `unrec.osteoporosis` | Fragility fracture (hip, vertebra, wrist, humerus) at 50+ in imaging or claims | BMD in the last 3 years, or osteoporosis treatment |
| `statin.indicated` | ASCVD, AAA > 3.0 cm or repaired, diabetes at 40+ (or 30+ with > 15 years' duration or microvascular disease), CKD at 50+, LDL ≥ 5.0 | On any statin, or documented statin intolerance or refusal |

### 8.2 Chronic disease monitoring

Only runs for patients with the condition coded, or flagged by 8.1 and confirmed. CHR ships dashboards for asthma, CAD, COPD, diabetes, heart failure, and hypertension, but **not CKD**, and they only see diagnoses entered in Medical History.

| Condition | Rule | Monitoring | Interval | Source |
|---|---|---|---|---|
| **Diabetes** | `dm.a1c` | A1c | 3 mo (6 mo if stable at target). Flag at > 6 mo. | BC Diabetes Care (rev. May 2026) |
| | `dm.kidney` | ACR + eGFR | 12 mo | same |
| | `dm.eye` | Retinal exam report | **⚠ decide:** 1 or 2 years (the guideline's own summary table and text disagree) | same |
| | `dm.foot` | Foot / monofilament exam | 12 mo | same |
| | `dm.bp` | BP | 6 mo | same (target < 130/80) |
| | `dm.statin` | On statin if 40+, CVD, or complications | n/a | same |
| | `dm.cardiorenal_drug` | SGLT2i or GLP-1RA if ASCVD, CKD, HF, or 60+ with CV risk factors | n/a | same. `DISCUSS`, not a gap. |
| | `dm.imm` | Flu yearly, PCV20 once (diabetes is a PCV20 high-risk condition) | | BCCDC |
| **CKD** | `ckd.monitoring` | eGFR + ACR at the KDIGO 2024 frequency | G1 to G2: 1/yr (3 if A3). G3a: 1 to 3. G3b: 2 to 3. G4: 3 to 4+. G5: 4+. | BC CKD (Jul 2025) |
| | `ckd.acei_arb` | ACEi or ARB | n/a | same. `DISCUSS`. |
| | `ckd.sglt2i` | SGLT2i if ACR ≥ 20 mg/mmol or HF | n/a | same. `DISCUSS`. |
| | `ckd.kfre` | Kidney Failure Risk Equation if eGFR < 60 | 12 mo | same |
| **Hypertension** | `htn.review` | Visit with BP | 12 mo | BC Hypertension (2020 content) |
| | `htn.labs` | Creatinine/eGFR + K+ if on ACEi, ARB, or diuretic | 12 mo | same |
| **Heart failure** | `hf.labs` | Creatinine + K+ | 6 mo (design choice; guideline says "periodically and after dose changes") | BC HF 2023 |
| | `hf.gdmt` | HFrEF on all four classes (ARNI/ACEi/ARB, beta-blocker, MRA, SGLT2i) | n/a | same. `DISCUSS`. |
| **COPD** | `copd.spirometry` | Confirming post-BD spirometry ever | Once | BC COPD 2024 |
| | `copd.imm` | Flu, COVID, PCV20, RSV (if eligible) | per vaccine | same |
| **Asthma** | `asthma.review` | Visit reviewing control | 6 mo | BC Asthma 2023 |
| | `asthma.spirometry` | Spirometry ever (age 6+) | Once | same |

### 8.3 High-risk drug monitoring (design choice, sources to confirm)

Standard monitoring intervals from product monographs and common practice. Each needs a source picked before it ships.

| Rule | Drug | Labs | Interval |
|---|---|---|---|
| `drug.lithium` | Lithium | Level, creatinine, TSH, calcium | Level 3 to 6 mo. Others 6 to 12 mo. |
| `drug.methotrexate` | Methotrexate | CBC, ALT, creatinine | 3 mo |
| `drug.amiodarone` | Amiodarone | TSH, ALT | 6 mo |
| `drug.doac` | Apixaban, rivaroxaban, dabigatran, edoxaban | Creatinine, CBC | 12 mo (6 mo if 75+ or CrCl < 60) |
| `drug.warfarin` | Warfarin | INR | 12 weeks (usually managed by clinic or pharmacy, so `NOT_FOUND` is common) |
| `drug.antipsychotic` | Second-generation antipsychotics | A1c or FPG, lipids, weight | 12 mo |

---

## 9. Decisions and conflicts to resolve

My recommendation is listed first in each row. None of these block the build, since the rule files carry the choice as a parameter.

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Hypertension diagnostic threshold for `unrec.htn` | BC (automated office ≥ 135/85) vs Hypertension Canada 2025 (≥ 130/80, confirmed out of office) | **BC 135/85.** Fewer false positives on a panel sweep. Show the HC 2025 target (SBP < 130) on the card. |
| 2 | Osteoporosis screening | CTFPHC FRAX-first for women 65+ vs Osteoporosis Canada BMD for all 70+ | **FRAX-first for women 65+** (it fits MSP's funding rules). Men 70+ as `DISCUSS`. |
| 3 | Diabetic eye exam interval | 1 y vs 2 y | **`DUE_SOON` at 1 year, `OVERDUE` at 2 years** |
| 4 | Breast screening after chest radiation | Start at 25 (May 2026 PDFs) vs 30 (web page) | **25**, since the PDFs are newer |
| 5 | Cervix stop age when immunocompromised | Negative HPV at 71 to 74 (Guidelines PDF) vs 65 to 69 (web page) | **71 to 74** (Guidelines PDF) |
| 6 | HIV as immunocompromised for cervix intervals | Not clearly in BC Cancer's list, but the BC Guideline lists it as a risk factor and HPV9 uses 3 doses for HIV | **Yes, treat as immunocompromised** (3-year interval) |
| 7 | Breast 40 to 49 | Gap vs `DISCUSS` | **`DISCUSS`**. BC Cancer calls it "available", not "recommended". |
| 8 | Colon 40 to 49 (average risk) | Not shown vs `DISCUSS` | **Not shown.** Review when BC Cancer decides on 45. |
| 9 | PSA | Off vs `DISCUSS` for 55 to 69 | **Off.** The PSA-rising open loop runs regardless. |
| 10 | HCV 1945 to 1965 birth cohort | Gap vs `DISCUSS` | **Low-priority gap.** One test, curable disease. |
| 11 | Old CTFPHC recommendations (AAA, parts of HCV, osteoporosis) | Keep vs drop | **Keep where BC is silent.** Set `review_by` 2027-06 to catch the new national committee. |
| 12 | Fall 2026-27 COVID eligibility | n/a | **Shadow mode** until BCCDC publishes it |
| 13 | Shingrix (not publicly funded) | Gap vs `DISCUSS` | **`DISCUSS`** (cost matters, except FNHB clients 60+) |

---

## 10. CHR's built-in preventive care vs this catalog

CHR has a Preventive Care section per patient and a "Preventative Care Report" dashboard (you may need to ask TELUS support to install it). It's worth switching on as a free baseline, but its BC defaults are out of date:

| Item | CHR default | This catalog |
|---|---|---|
| Cervix | Pap + HPV every 3 years, 25 to 69 | HPV every 5 years (3 if immunocompromised), lab's printed due date |
| Diabetes screen | 40+, every 5 years | 40+, every 3 years. 6 to 12 months if prediabetic. |
| Lipids | 40 to 74, every 5 years | Same, plus any age with risk conditions, plus Lp(a) once |
| Breast | Women 50 to 74, every 2 years | Same, plus annual for FDR or high risk, `DISCUSS` 40 to 49 |
| Colon | 50 to 74, FIT 2 y / flex sig 5 y / colonoscopy 10 y | Same, plus family-history colonoscopy every 5 years and surveillance intervals |
| Lung, HIV, HCV, osteoporosis, AAA, immunizations, pediatrics, open loops | Not covered | Covered |

CHR only reads its own structured preventive care entries. Results sitting in PDFs don't count, which is most of breast, colon, and lung.
