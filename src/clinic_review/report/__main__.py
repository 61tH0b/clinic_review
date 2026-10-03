"""Local worklists, run diffs, and capture-only feedback. Counts only on stdout."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date

from .data import ReportError, read_run
from .feedback import OUTCOMES, validate_feedback
from .provenance import version_stamp
from .render import write_diff, write_worklists


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default message can echo an id or note in an invalid argument.
        self.exit(2, "Invalid report arguments; use --help for the command format.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="python -m clinic_review.report")
    parser.add_argument("--version", action="version", version=version_stamp())
    sub = parser.add_subparsers(dest="command", required=True)
    work = sub.add_parser("worklists", help="write local HTML/CSV worklists")
    diff = sub.add_parser("diff", help="write patient-level diff files; print counts")
    feedback = sub.add_parser("feedback-check", help="validate local feedback; doesn't change evaluation")
    for command in (work, diff, feedback):
        command.add_argument("--store", required=True)
    for command in (work, feedback):
        command.add_argument("--run", required=True)
    for command in (work, diff):
        command.add_argument("--out", required=True, help="new local directory outside Git checkouts")
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    feedback.add_argument("--feedback", required=True)
    # Parse after argparse: its type error would echo the caller's input.
    feedback.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args(argv)
    try:
        if args.command == "worklists":
            counts = write_worklists(read_run(args.store, args.run), args.out)
            for name, count in counts.items():
                print(f"{name}: {count}")
        elif args.command == "diff":
            before, after = read_run(args.store, args.before), read_run(args.store, args.after)
            counts = write_diff(before, after, args.out)
            print("ruleset digests: " + ("DIFFERENT" if before.ruleset != after.ruleset else "same"))
            for rule_id, changes in counts.items():
                print(f"{rule_id}: " + ", ".join(f"{name} {n}" for name, n in changes.items()))
        else:
            try:
                as_of = date.fromisoformat(args.as_of)
            except ValueError:
                raise ReportError("Validation date must be YYYY-MM-DD.") from None
            entries = validate_feedback(args.feedback, read_run(args.store, args.run), as_of=as_of)
            counts = Counter(entry.outcome for entry in entries)
            for outcome in OUTCOMES:
                print(f"{outcome}: {counts[outcome]}")
            print("capture only: attestation policy isn't approved; evaluation is unchanged")
    except ReportError as error:
        print(f"report unavailable: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
