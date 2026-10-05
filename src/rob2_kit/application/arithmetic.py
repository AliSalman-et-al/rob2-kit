"""Bounded decimal scratch arithmetic; no scientific interpretation or workspace access."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Any

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
_DISTINCTION = (
    "Arithmetic does not validate source selection, units, assumptions or scientific inference."
)


def calculate_arithmetic(
    expression: str,
    inputs: Mapping[str, str],
    units: str | None = None,
    assumptions: Sequence[str] = (),
) -> dict[str, Any]:
    if not isinstance(expression, str) or not 1 <= len(expression) <= 512:
        raise ValueError("expression must contain 1–512 characters")
    if re.search(r"[^A-Za-z0-9_+*/().\s-]", expression):
        raise ValueError("use decimal numbers, input names, + - * / and parentheses only")
    if len(inputs) > 16 or any(
        not isinstance(name, str) or not _NAME.fullmatch(name) for name in inputs
    ):
        raise ValueError(
            "use at most 16 named inputs, each a letter-led name of at most 32 characters"
        )
    if units is not None and (not isinstance(units, str) or len(units) > 200):
        raise ValueError("units annotation must be at most 200 characters")
    if len(assumptions) > 8 or any(
        not isinstance(item, str) or not 1 <= len(item) <= 200 for item in assumptions
    ):
        raise ValueError("use at most 8 assumption annotations of 1–200 characters")

    def number(value: str) -> Decimal:
        if not isinstance(value, str) or len(value) > 64 or not _NUMBER.fullmatch(value):
            raise ValueError("numbers must be finite decimal strings of at most 64 characters")
        return Decimal(value)

    values = {name: number(value) for name, value in inputs.items()}
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValueError(
            "use decimal numbers, input names, + - * / and parentheses only"
        ) from error
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("expression exceeds the 64-node limit")
    source = expression.strip()

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant):
            # Recover decimal spelling, never Python's binary float approximation.
            return number(ast.get_source_segment(source, node) or "")
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else value.copy_negate()
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("use decimal numbers, known input names, + - * / and parentheses only")

    try:
        with localcontext(
            Context(
                prec=28,
                rounding=ROUND_HALF_EVEN,
                Emax=256,
                Emin=-256,
                clamp=0,
                traps=[DivisionByZero, InvalidOperation, Overflow, Underflow, Subnormal],
                flags=[],
            )
        ) as context:
            result = +evaluate(tree.body)
            if not result.is_finite() or (result and not -256 <= result.adjusted() <= 256):
                raise ValueError("result exceeds the supported decimal exponent range [-256, 256]")
            return {
                "outcome": "success",
                "expression": expression,
                "inputs": dict(inputs),
                "units": units,
                "assumptions": list(assumptions),
                "result": format(result, "f"),
                "precision": 28,
                "rounding": "ROUND_HALF_EVEN",
                "precision_semantics": (
                    "Unary signs are exact; 28 significant digits at each binary operation "
                    "and final result."
                ),
                "inexact": context.flags[Inexact],
                "rounded": context.flags[Rounded],
                "distinction": _DISTINCTION,
            }
    except DecimalException as error:
        raise ValueError(
            "undefined decimal operation, zero divisor or numeric range exceeded"
        ) from error
