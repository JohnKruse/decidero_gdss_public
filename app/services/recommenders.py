"""Layer-B recommender: a bounded declarative rule over a scalar namespace.

Canary: Plainspoken Marmot

The recommendation seam (HICSS outline, section L.3) is split in two:

- **Layer A — metrics.** Cited statistical primitives (the report summarizers and
  convergence predicates) compute a *flat namespace of named scalar facts* over a
  round bundle. That layer is code, vetted and registered by name.
- **Layer B — selection.** Given that scalar namespace, an orchestration document
  declares which option to recommend with an ordered guard rule. This is *data*,
  not code — it never touches the round bundle, only the named scalars Layer A
  produced.

This module is Layer B: a pure evaluator with no database, no bundle access, and
no I/O. The guardrail is enforced structurally — conditions are parsed to a
Python AST and accepted only if every node is a comparison, boolean op, `not`,
name, or literal. Arithmetic, function calls, attribute/subscript access, loops,
and comprehensions are rejected, so the expressiveness ceiling stays fixed: when
a rule needs more, the answer is to add a registered Layer-A metric, never to
grow this language.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional

# The only AST node types a condition may contain. Anything else (BinOp for
# arithmetic, Call, Attribute, Subscript, comprehensions, ...) is rejected — as
# are comparison operators outside this set (`in`, `is`), since those operator
# nodes are walked as children and must themselves be whitelisted.
_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    # comparison operators
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


class RecommenderRuleError(ValueError):
    """Raised when a recommender rule or condition is malformed or unsafe."""


def _validate_node(node: ast.AST) -> None:
    """Recursively reject any condition AST node outside the whitelist."""
    if not isinstance(node, _ALLOWED_NODES):
        raise RecommenderRuleError(
            f"node {type(node).__name__} is not allowed in a recommender condition "
            "(only comparisons and booleans over scalar metrics are permitted)"
        )
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


def validate_condition_syntax(expr: str) -> None:
    """Author-time check: the condition parses and uses only whitelisted nodes.

    Unlike `evaluate_condition`, this does not resolve metric names (the scalar
    namespace is unknown at authoring/load time) — it only enforces that the
    condition is a safe comparison/boolean expression. Raises
    `RecommenderRuleError` otherwise. Used by the orchestration loader so an
    unsafe rule is rejected when the document is saved, not at runtime.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise RecommenderRuleError("condition must be a non-empty string")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise RecommenderRuleError(f"could not parse condition {expr!r}: {exc}") from exc
    _validate_node(tree)


def evaluate_condition(expr: str, namespace: Dict[str, Any]) -> bool:
    """Evaluate a single boolean condition against the scalar namespace.

    Names resolve to entries in `namespace`; an unknown name is an error rather
    than a silent falsy default, so a typo or stale metric reference surfaces at
    runtime instead of quietly skipping a guard.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise RecommenderRuleError("condition must be a non-empty string")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise RecommenderRuleError(f"could not parse condition {expr!r}: {exc}") from exc

    _validate_node(tree)

    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    missing = referenced - namespace.keys()
    if missing:
        raise RecommenderRuleError(
            f"condition {expr!r} references unknown metric(s): {sorted(missing)}"
        )

    # Names are bound to the scalar namespace; __builtins__ is stripped so no
    # globals are reachable even though the AST whitelist already forbids calls.
    return bool(eval(compile(tree, "<recommender>", "eval"), {"__builtins__": {}}, dict(namespace)))


def evaluate_rule(rule: List[Dict[str, Any]], namespace: Dict[str, Any]) -> Optional[str]:
    """Resolve an ordered guard rule to a recommended option.

    Each guard is either `{"when": <condition>, "recommend": <option>}` or a
    terminal `{"default": <option>}`. Guards are evaluated in order; the first
    `when` that holds (or a `default`) wins. Returns ``None`` if nothing matches
    and there is no default.
    """
    if not isinstance(rule, list):
        raise RecommenderRuleError("recommender rule must be a list of guards")

    for idx, guard in enumerate(rule):
        if not isinstance(guard, dict):
            raise RecommenderRuleError(f"guard at index {idx} must be an object")

        if "default" in guard:
            if set(guard) != {"default"}:
                raise RecommenderRuleError(
                    f"default guard at index {idx} must contain only 'default'"
                )
            return guard["default"]

        if "when" not in guard or "recommend" not in guard:
            raise RecommenderRuleError(
                f"guard at index {idx} must have 'when' + 'recommend', or be a 'default' guard"
            )
        if evaluate_condition(guard["when"], namespace):
            return guard["recommend"]

    return None
