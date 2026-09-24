# Rules

One YAML file per rule, named `<id>.yaml`. The evaluator is `src/clinic_review/engine/`. Unknown keys fail validation, so a typo can't quietly change who gets flagged.

```sh
python -m clinic_review.engine check rules   # CI runs this; it fails on any rule past review_by
```

Every rule starts as `status: shadow`. It moves to `live` only after the chart audit shows PPV ≥ 90% and sensitivity ≥ 85% (PLAN section 9), and that move is a change to this file.

## Fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Catalog id, e.g. `colon.fit`. Must match the file name. |
| `version` | yes | Bump on any change that can change a result. |
| `title` | yes | Plain-language name for the queue. |
| `category` | yes | `A` (preventive and chronic-care gaps) or `B` (screening-result loops), per the CHR Panel Review Spec. |
| `subtype` | yes | `loop`, `unrecognized`, `cancer`, `screening`, `immunization`, `chronic`, `life_stage` |
| `kind` | no | `interval` (default) or `loop` |
| `mode` | no | `gap` (default) or `discuss`. A `discuss` rule never raises a recall; its gaps show as `DISCUSS` on the pre-visit card. |
| `status` | no | `shadow` (default) or `live` |
| `source` | yes | `name`, `url`, `checked` (date the source was last read) |
| `decision` | no | The catalog §9 decision this rule carries, if any |
| `population` | no | `age: {min, max}` in completed years, both ends inclusive. `sex_at_birth: F` or `{is: F, or_any_of: [...]}` for facts that count in its place. `any_of`: needs at least one of these facts. `none_of`: any of these makes the patient not eligible (usually because another rule covers them). |
| `exclusions` | no | Concepts that make an eligible patient `EXCLUDED`. Plain concept, or `{concept, within_months}` for a temporary exclusion like recent pregnancy. |
| `requires` | no | `[{label, any_of}]`. If none of the concepts is charted the state is `UNKNOWN`, and the label becomes the task ("record smoking history"). |
| `satisfied_by` | interval rules | `[{concept, within_months, value_in?, use_reported_next_due?}]`. Any one, recent enough, keeps the patient up to date. The alternative that covers the patient longest wins. `use_reported_next_due` trusts a due date printed on the report over the computed one. |
| `due_soon_days` | no | `DUE_SOON` starts this many days before the due date. Default 90. |
| `grace_months` | no | `DUE_SOON` continues this long past the due date before `OVERDUE`. Default 0. |
| `declined` | no | `{concept, valid_months}`. A documented refusal inside the window makes the state `DECLINED` until the re-offer date. |
| `trigger` | loop rules | `{concept, value_in?, lookback_months}`: the result that opens the loop |
| `followed_by` | loop rules | `{any_of, within_days}`: what closes it, and how long before it's `OVERDUE` |
| `evidence_sources` | yes | Every source the rule reads: `demographics`, `encounters`, `history.medical`, `history.surgical`, `history.family`, `risk_factors`, `medications`, `immunizations`, `labs`, `vitals`, `documents.diagnostic_imaging`, `documents.consults`, `documents.lab`, `documents.hospital`, `documents.historical`. The walker plans each patient's screens from these. If one wasn't walked, a gap becomes `UNKNOWN`, never `NOT_FOUND`. |
| `action` | no | `{kind, note}`. `kind`: `order`, `book`, `self_refer`, `review`, `record`. |
| `review_by` | yes | CI fails after this date until the source is re-checked |
| `owner` | yes | Who signs off changes |

## Concept names

`<family>.<name>`: `dx.` conditions, `obs.` lab results, `proc.` procedures, `imaging.` imaging, `exam.` exams, `risk.` risk factors and flags, `hx.` history, `rx.` medications, `state.` time-limited states (pregnancy), `screen.` program assessments, `decline.` documented refusals. The concept layer in `valuesets/` maps CHR codes, lab names, drug names, and document keywords to these.
