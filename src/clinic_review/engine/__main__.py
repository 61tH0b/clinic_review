"""python -m clinic_review.engine check [RULES_DIR] [--today YYYY-MM-DD]

Loads and validates every rule, then fails on any rule past its review_by date. CI runs
this on every push, so a stale rule blocks merges until someone re-checks its source.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .rules import RuleError, check_rules, load_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clinic_review.engine")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate rules and fail on stale ones")
    check.add_argument("rules_dir", nargs="?", default="rules")
    check.add_argument("--today", type=date.fromisoformat, default=date.today(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        rules = load_rules(args.rules_dir)
    except RuleError as e:
        print(f"invalid rule: {e}", file=sys.stderr)
        return 1
    if not rules:
        print(f"no rules found in {args.rules_dir}", file=sys.stderr)
        return 1
    problems = check_rules(rules, args.today)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    print(f"{len(rules)} rules OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
