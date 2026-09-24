"""Rule engine: YAML rules in rules/, evaluated by a small deterministic evaluator.

See docs/PLAN.md section 6 and rules/README.md.
"""
from .evaluate import Result, evaluate
from .facts import Fact, Patient
from .rules import SOURCES, Rule, RuleError, check_rules, load_rule, load_rules, parse_rule
from .states import State

__all__ = [
    "Fact",
    "Patient",
    "Result",
    "Rule",
    "RuleError",
    "SOURCES",
    "State",
    "check_rules",
    "evaluate",
    "load_rule",
    "load_rules",
    "parse_rule",
]
