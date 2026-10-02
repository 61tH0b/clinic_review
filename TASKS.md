# WP1 checklist, v1

2026-10-02 02:52 PDT. Owner: this WP1 chat, branch gpt/wp1-worklists-run-diff.

- [x] Verify repository path/origin and applicable instructions.
- [x] Check shared QUEUE.md for conflicts (none); don't edit sibling repositories.
- [x] Refresh Claude base; PR #1 open, baseline 192 tests and all four checks pass.
- [x] Tag pre-wp1 and create isolated WP1 branch; write design before code.
- [x] Ask Ali about attestation validity; capture-only until a decision arrives.
- [x] Write acceptance and edge tests before implementation (initial missing-module failure).
- [x] Build immutable rule snapshots, worklists, run diff, and feedback validation.
- [x] Mutation-check new logic and restore it (six detected mutations; 49 report tests green).
- [x] Update affected docs, changelog, version, and test registry.
- [ ] Recheck queue/branch ownership; run all four checks; commit with required author.
- [ ] Push WP1 branch, open and attach draft PR against the Claude base.
- [ ] Report Changed, Found, Blocked on me, and Deviations; stop before WP2.

Blocked: attestation-to-facts/next-run closure requires Ali's clinical policy. The
shared queue can't be claimed here because the explicit scope forbids sibling edits.
