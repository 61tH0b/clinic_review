# WP1 checklist, v1

Updated 2026-10-02 03:10 PDT. Owner: this WP1 chat, branch gpt/wp1-worklists-run-diff.

- [x] Verify repository path/origin and applicable instructions.
- [x] Check shared QUEUE.md for conflicts (none); don't edit sibling repositories.
- [x] Refresh Claude base; PR #1 open, baseline 192 tests and all four checks pass.
- [x] Tag pre-wp1 and create isolated WP1 branch; write design before code.
- [x] Ask Ali about attestation validity; capture-only until a decision arrives.
- [x] Write acceptance and edge tests before implementation (initial missing-module failure).
- [x] Build immutable rule snapshots, worklists, run diff, and feedback validation.
- [x] Mutation-check new logic and restore it (six detected mutations; 49 report tests green).
- [x] Update affected docs, changelog, version, and test registry.
- [x] Recheck queue/branch ownership (no conflict); all four checks pass, 241 tests.
- [x] Commit implementation as Aya Health Technologies Inc. <admin@autochart.ai> (4e4d3f7).
- [x] Push WP1 branch; open and attach draft PR #2 against the Claude base.
- [x] Record completion state and the blocked criterion; stop before WP2 for Ali's review.

Blocked: attestation-to-facts/next-run closure requires Ali's clinical policy. The
shared queue can't be claimed here because the explicit scope forbids sibling edits.

Draft PR: https://github.com/61tH0b/clinic_review/pull/2. PR #1 is still open; main and
the repository default branch weren't changed. `pre-wp1` remains a local rollback
tag. The final chat report is the coordination chat's handoff; this chat hasn't
messaged Claude or opened another work package. At 03:10 PDT, GitHub no-phi and rules
jobs pass; test jobs are still running. Local results are confirmed, not inferred CI.
