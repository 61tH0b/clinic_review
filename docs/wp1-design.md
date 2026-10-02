# WP1 design, v1

2026-10-02 02:52 PDT. Synthetic implementation; clinical deployment gates still apply.

Each new evaluation run snapshots rule id/version, title, category, shadow/live status,
and action kind/note in the ledger. A separate run-mode row distinguishes cohort-only
runs. Report reads use a read-only SQLite connection and require a finished full run
with complete rule snapshots. Old runs without snapshots need re-evaluation; today's
rule files aren't a reliable description of historical actions.

Worklist rows carry patient id, rule id/version/title, category, rule status, state,
due date, evidence ids, searched sources, missing inputs, reason, and action kind/note.
Category B gaps go to physician review first. Other gaps route by action: book to MOA,
self-refer to patient, order/review to physician, and record to physician input tasks.
UNKNOWN gets its own input-task list regardless of action. DISCUSS gets a separate
pre-visit list and never a recall. Outreach comes directly from the cohort table.
Shadow results are explicitly labelled for review; export doesn't authorize outreach.

Each export creates a new private output directory outside Git checkouts. It writes
one self-contained HTML file, one CSV per audience/action list, and a feedback CSV
template. HTML escapes every data cell and loads no external assets. CSV escapes
spreadsheet formula prefixes. Existing output directories aren't overwritten.

Run diffs compare patient/rule keys. Open means DUE_SOON, OVERDUE, or NOT_FOUND.
Newly open, closed, still open, and changed state are independent flags; a changing
open state counts as both still open and changed state. Added/removed evaluations
are separate, never proof of closure. Different ruleset digests are flagged. UNKNOWN
or NOT_ELIGIBLE replacing a gap means it left the open set, not proof of completed
care; both states and cohort groups stay visible in the file. No patient id is printed.

Feedback CSV v1 has exactly these columns: patient_id, rule_id, rule_version,
outcome, date, evidence_note. Outcomes are done_elsewhere, declined, not_applicable.
Blank template rows are ignored; partially completed rows fail. Completed entries
must reference a result in the selected run, match its rule version, and have a date
no later than the explicit validation date. Duplicate patient/rule entries fail.
Notes stay only in the local CSV; the CLI prints counts, never input values or paths.
Entries carry source=attestation in memory, but don't become clinical facts yet.

Clinical gate: Ali hasn't chosen attestation validity or its rule-specific evidence
mapping. Feedback is capture/validation only. No engine override, invented interval,
or automatic exclusion/decline. Acceptance criterion 'attestation closes a gap on
the next run' remains blocked until the policy is approved and implemented.

Tests first: fake-EMR pipeline cohort/routing, snapshot stability, stdout/error
redaction, diff transitions and digest changes, missing/incomplete/legacy runs,
read-only/sealed-store preservation, HTML and CSV injection, feedback schema/date/
identity/version checks, and explicit lack of evaluation effect. Mutation checks
break routing, diff classification, escaping, and feedback validation in turn.

Deviations: feedback-to-facts/closure is gated; shared queue is read-only under this
chat's explicit repository boundary. No WP7 clinical or walker changes are needed.
