"""python -m clinic_review.pipeline evaluate --mapping local/chr-facts.yaml --store PATH
                                           [--sweep current] [--as-of YYYY-MM-DD] [--cohort-only]

Reads the sweep's captures, splits the cohort, runs every rule on the active cohort, and
writes the ledger into the store. It prints aggregates only: counts by cohort group, by
rule and state, and the most common skip reasons. No CHR id or chart text is printed.
Run it with --cohort-only first and sanity-check the denominator (PLAN section 4).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from ..concepts.layer import ConceptLayer
from ..concepts.valuesets import ValueSetError
from ..engine.rules import RuleError, load_rules
from ..engine.states import State
from ..facts.mapping import MappingError, load_mapping
from ..store import EnvKeyProvider, KeychainKeyProvider, RawStore
from ..store.ledger import GROUPS, Ledger
from .run import evaluate_panel, ruleset_digest


def print_summary(ledger: Ledger, run_id: str, out=None) -> None:
    out = out or sys.stdout  # looked up at call time, so redirection works
    cohort = ledger.cohort_counts(run_id)
    print("cohort: " + ", ".join(f"{g} {cohort[g]}" for g in GROUPS), file=out)
    for rule_id, counts in ledger.state_counts(run_id).items():
        shown = ", ".join(f"{s.value} {counts[s.value]}" for s in State if counts.get(s.value))
        print(f"  {rule_id}: {shown}", file=out)
    skips = ledger.skip_counts(run_id)
    if skips:
        print("most common skips (the value set curation list):", file=out)
        for reason, n in skips:
            print(f"  {n:5d}  {reason}", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m clinic_review.pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="run every rule on the sweep and write the ledger")
    ev.add_argument("--mapping", required=True, help="facts mapping, e.g. local/chr-facts.yaml")
    ev.add_argument("--store", required=True)
    ev.add_argument("--sweep", default="current")
    ev.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ev.add_argument("--rules", default="rules")
    ev.add_argument("--valuesets", default="valuesets")
    ev.add_argument("--cohort-only", action="store_true", help="split the cohort without running rules")
    args = parser.parse_args(argv)

    try:
        mapping = load_mapping(args.mapping)
        layer = ConceptLayer.load(args.valuesets)
        rules = load_rules(args.rules)
    except (MappingError, ValueSetError, RuleError) as e:
        print(f"invalid: {e}", file=sys.stderr)
        return 1
    keys = EnvKeyProvider() if os.environ.get("CLINIC_REVIEW_STORE_KEY") else KeychainKeyProvider()
    store = RawStore(args.store, keys)
    ledger = Ledger(args.store)
    try:
        summary = evaluate_panel(
            store,
            ledger,
            mapping,
            layer,
            rules,
            sweep=args.sweep,
            as_of=args.as_of,
            ruleset=ruleset_digest(args.rules, args.valuesets),
            cohort_only=args.cohort_only,
        )
        print(f"run {summary.run_id}: sweep {summary.sweep}, as of {summary.as_of}, ruleset {summary.ruleset}")
        print_summary(ledger, summary.run_id)
    finally:
        ledger.close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
