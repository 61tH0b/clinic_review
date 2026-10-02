# Local reporting, v1

2026-10-02 03:06 PDT. CLI/library version 0.2.0; local synthetic validation only.

Run reports under the separate clinic data account after its storage/privacy setup.
Patient-level files stay there. The examples use placeholders, not a real store.
Each `--out` must name a new local folder outside Git checkouts. Existing folders
aren't overwritten; `local/`, ignored export folders, and symlink aliases inside a
checkout are also rejected. New export folders are mode 700; their files are mode
600. An interrupted write may leave partial files; use a fresh folder on retry.

```sh
python -m clinic_review.report --version
python -m clinic_review.report worklists --store STORE_PATH --run RUN_ID --out NEW_OUTPUT_FOLDER
python -m clinic_review.report diff --store STORE_PATH --before BEFORE_RUN_ID --after AFTER_RUN_ID --out NEW_DIFF_FOLDER
python -m clinic_review.report feedback-check --store STORE_PATH --run RUN_ID --feedback FEEDBACK_CSV --as-of YYYY-MM-DD
```

The report reader opens SQLite read-only, requires a finished full evaluation, and
checks that every active patient's results have matching rule snapshots. Cohort-only,
incomplete, mismatched, and legacy runs are rejected. Re-evaluate a legacy run with the
current pipeline first; old results aren't relabelled with today's rule actions.
Snapshots add two ledger tables; existing raw captures and their sealing aren't changed.

## Worklists

`worklists.html` is one self-contained file. It needs no network, JavaScript, fonts,
or external assets. Each list also has its own CSV. Data cells are escaped in HTML,
and formula-like CSV cells get an apostrophe prefix for spreadsheet safety.

| List | Contains |
|---|---|
| physician_review | Category B open loops first, then review actions and gaps with no action |
| moa_book | Open results whose action is book |
| patient_self_refer | Open self-refer results, with the exact program instructions/phone numbers from the snapshotted action note |
| physician_order | Open results whose action is order |
| physician_record | Open results whose action is record |
| unknown_tasks | Missing inputs or unwalked sources; overrides the rule's normal action |
| previsit_discuss | DISCUSS only; never a recall |
| outreach | Cohort outreach patients; no rule evaluation is invented |

Open means DUE_SOON, OVERDUE, or NOT_FOUND. UP_TO_DATE, EXCLUDED, DECLINED, and
NOT_ELIGIBLE aren't recall rows. Each rule row includes its title, version, category,
shadow/live status, due date, evidence ids, searched sources, missing inputs, reason,
and action kind/note. Within lists, loops sort first, then due date and stable ids.
Exports are review materials, not authorization to book, send, or place orders.
All existing rules remain shadow; sign-off and chart-audit gates still apply.

## Run diff

`diff.html` and `diff.csv` carry both states, versions, titles, evidence ids, due dates,
cohort groups, and actions. The CLI prints counts by rule and a digest-change flag.
Different ruleset digests are also flagged in HTML. The before run's as-of date
mustn't be later than the after run's date.

| Flag | Meaning |
|---|---|
| newly_open | Both evaluations exist, and the result entered the open set |
| closed | Both evaluations exist, and the result left the open set |
| still_open | Both evaluations exist, and both states are open |
| changed_state | Both evaluations exist, with different states |
| added / removed | Evaluation exists on only one side; never inferred closure |

Flags overlap: NOT_FOUND to OVERDUE is still_open and changed_state. Closed isn't
proof of completed care: OVERDUE to UNKNOWN, EXCLUDED, NOT_ELIGIBLE, or DECLINED
also leaves the open set. Read the destination state. A patient leaving the active
cohort produces removed evaluations, with the destination cohort group visible.
UNKNOWN tasks and DISCUSS aren't included in the open-gap counts.

## Feedback capture: clinical policy pending

`feedback.csv` is an editable table of listed rule results, with blank outcome/date/
note columns. It excludes outreach rows because they have no evaluated rule result.
Its exact v1 header is:

```text
patient_id,rule_id,rule_version,outcome,date,evidence_note
```

Keep identity and version columns unchanged. Fill outcome with done_elsewhere,
declined, or not_applicable, date with YYYY-MM-DD, and optionally evidence_note.
Untouched template rows are ignored. Partly completed rows, duplicates, changed
identities/versions, extra/missing columns, and future dates fail validation. Dates
are checked against the explicit `--as-of` date (today by default). Error output
doesn't echo file paths, ids, notes, or invalid argument values. Notes stay in the
local CSV; no notes are persisted to the unsealed ledger.

Validated records have `source: attestation` in memory. They aren't engine facts,
and no CLI imports them into evaluation. Ali hasn't chosen how long they count or
which rule concepts each outcome can satisfy. Existing rule decline intervals
mustn't be silently reused as a general attestation policy. The acceptance criterion
"an attestation closes a gap on the next run" is blocked on that clinical decision.
After approval, implement explicit evidence mapping and validity tests, then wire
facts into the normal deterministic path; don't add a result-state override.

## Verification

The report suite uses the six synthetic fake-EMR charts already used by the pipeline
suite. It covers routing, two pipeline runs, cohort departures, historical snapshots,
empty/legacy/incomplete runs, unwalked-source UNKNOWN, escaping, redacted output,
feedback identity/version/date validation, and the lack of feedback evaluation effect.
The existing browser pipeline test also exports its genuinely walked fake-EMR ledger.

Six temporary mutations were detected and restored: wrong booking audience, wrong
closure condition, disabled CSV formula escaping, disabled HTML escaping, disabled
future-feedback date check, and removed result/snapshot version matching. The original
store sealing and patient-binding tests still apply; report reads don't change captures.
