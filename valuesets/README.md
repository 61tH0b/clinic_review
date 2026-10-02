# Value sets (the concept layer)

These files map what's in a CHR chart to the concepts the rules read: MSP ICD-9 codes, problem list and history text, medication names, lab names and results, and document titles. The code is `src/clinic_review/concepts/`. PLAN section 6.1 has the why.

```sh
python -m clinic_review.concepts check   # validates every file, and fails if any rule reads an undefined concept
```

Every file starts as `status: draft`. A clinician reads it, then sets `status: signed` and `signed_off: {by, on}`. Rules can run in shadow mode on draft value sets, but a rule shouldn't go `live` on one.

WP1 doesn't change value sets or their schema. Local feedback records are labelled
`source: attestation` in memory, but they don't create concepts or enter evaluation.
Ali must approve their validity and rule-specific evidence mapping first; see
[`docs/reporting.md`](../docs/reporting.md). No completion, decline, or exclusion
concept is inferred from an unapproved feedback outcome.

## How matching works

- **Codes:** MSP stores WHO ICD-9 at 3 or 4 characters with no decimal and with leading zeros (`250`, `2500`, `V451`, `30B`). It isn't the US ICD-9-CM, so there are no 5-digit codes and 585 has no stages. A listed code matches itself and everything under it (`250` matches `2504`), minus `icd9_exclude`.
- **Text:** lowercased, `?` becomes "query", and punctuation becomes spaces. Phrases match whole words only, so "total hysterectomy" never matches inside "subtotal hysterectomy". Then, in order:
  1. A `blocked_by` phrase anywhere in the row blocks the whole row for that file, for example a relative ("mother: breast cancer"), a screening mention, or a requisition.
  2. A concept's `not_if` phrase anywhere in the row stops that concept ("pre-diabetes", "HIV negative", "eye drops").
  3. Where phrases overlap, the longest wins among alternatives: within one concept, or between concepts in the same `exclusive` group. So "ex-smoker" beats "smoker". A refinement doesn't hide its parent: "CKD stage 4" gives both CKD and severe CKD.
  4. A `cues_before` phrase in the few words before a match drops it ("no DM", "r/o diabetes", "?DM").
  5. Two concepts from one `exclusive` group in the same row conflict, and both are dropped.
- **Labs:** the name and result must match exactly after normalization, never as a substring. "HPV 16/18 not detected; other HR HPV detected" must never read as negative. An unknown result keeps the fact with no value, so it can't satisfy a rule that needs a specific result.
- **Skips:** anything dropped or unmatched becomes a skip with a reason. The skip list is how these files grow. It stays on the Mac, and a reason only quotes value set phrases, never chart text.

## Files

| File | `match` | Reads |
|---|---|---|
| `conditions.yaml` | text | MSP codes and problem list / history text |
| `procedures.yaml` | text | Surgical and medical history text |
| `risk_factors.yaml` | text | Smoking status |
| `medications.yaml` | text | Medication list entries |
| `labs.yaml` | lab | Structured lab names and results |
| `documents.yaml` | text | Document titles |
| `extracted.yaml` | extraction | Concepts only the model on the Mac produces (declines, family history, chest radiation). The model's target list. |
| `derived.yaml` | derived | Concepts computed from other facts (`risk.immunocompromised`) |

## Fields

Top level: `name` (must match the file name), `match` (`text`, `lab`, `extraction`, `derived`), `applies_to` (the evidence sources a text or lab file reads), `status`, `signed_off`, `review_by`, and `sources`. Text files can also set `blocked_by`, `cues_before`, `cue_window` (default 3 words), and `exclusive`.

Per concept:

- text: `label`, `icd9`, `icd9_exclude`, `text`, `not_if`
- lab: `label`, `names`, plus either `results: {value: [phrases]}` or `numeric: true`
- extraction: `label`, `from` (the sources the model reads), `note`
- derived: `label`, `any_of` (each entry is a concept, or `{concept, within_months}`)

Quote every phrase and code. YAML reads a bare `no` as false and a bare `042` as the number 34, so the loader rejects anything that isn't a string.
