"""python -m clinic_review.concepts check [--valuesets DIR] [--rules DIR] [--today YYYY-MM-DD]

Validates every value set, fails if any rule reads a concept no value set defines, and
fails on any value set past its review_by date. CI runs it next to the rules check.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from ..engine.rules import RuleError, load_rules, referenced_concepts
from .layer import ConceptLayer
from .valuesets import ValueSetError


def check(layer: ConceptLayer, rules, today: date) -> list[str]:
    problems = []
    for rule in rules.values():
        for cid in sorted(referenced_concepts(rule) - set(layer.concepts)):
            problems.append(f"{rule.id}: reads {cid}, which no value set defines")
    for vs in layer.valuesets:
        if vs.review_by < today:
            problems.append(f"valuesets/{vs.name}.yaml: past its review_by date ({vs.review_by})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clinic_review.concepts")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="validate value sets and check every rule concept is defined")
    c.add_argument("--valuesets", default="valuesets")
    c.add_argument("--rules", default="rules")
    c.add_argument("--today", type=date.fromisoformat, default=date.today(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        layer = ConceptLayer.load(args.valuesets)
        rules = load_rules(args.rules)
    except (ValueSetError, RuleError) as e:
        print(f"invalid: {e}", file=sys.stderr)
        return 1
    problems = check(layer, rules, args.today)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        return 1
    drafts = [vs.name for vs in layer.valuesets if vs.status == "draft"]
    used = set().union(*(referenced_concepts(r) for r in rules.values())) if rules else set()
    print(f"{len(layer.valuesets)} value sets, {len(layer.concepts)} concepts, all {len(used)} rule concepts defined")
    if drafts:
        print(f"awaiting clinician sign-off: {', '.join(drafts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
