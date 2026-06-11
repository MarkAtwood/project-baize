"""CEL (Common Expression Language) evaluation for game conditions.

Evaluates condition strings as CEL expressions against a context of game
state variables. Falls back to None for unparseable expressions, letting
callers use legacy string dispatch.

Uses cel-python if installed; otherwise uses a built-in evaluator that
covers the CEL subset needed by game definitions (variable lookup, boolean
operators, comparisons).
"""

from __future__ import annotations

import operator
import re
from typing import Any

# Try importing cel-python for full CEL support
try:
    import celpy  # type: ignore[import-not-found]

    _HAS_CELPY = True
except ImportError:
    _HAS_CELPY = False


def try_eval_end_condition(
    variables: dict[str, Any],
    condition: str,
) -> bool | None:
    """Evaluate a condition string as CEL against the given variables.

    Returns the boolean result, or None if the expression cannot be parsed.
    """
    return _eval_expression(condition, variables)


def try_eval_move_condition(
    is_empty: bool,
    is_enemy: bool,
    condition: str,
) -> bool | None:
    """Evaluate a movement condition as CEL with cell state variables."""
    variables: dict[str, Any] = {
        "empty": is_empty,
        "enemy": is_enemy,
        "empty_or_enemy": is_empty or is_enemy,
        "first_move": False,
    }
    return _eval_expression(condition, variables)


def _eval_expression(expr: str, variables: dict[str, Any]) -> bool | None:
    """Evaluate a CEL expression. Returns None if unparseable."""
    expr = expr.strip()
    if not expr:
        return None

    result = _builtin_eval(expr, variables)
    if result is not None:
        return result

    if _HAS_CELPY:
        return _celpy_eval(expr, variables)

    return None


# ---------------------------------------------------------------------------
# Built-in evaluator: covers the CEL subset used by game definitions
# ---------------------------------------------------------------------------

# Tokenizer for the simple expression evaluator
_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (&&|\|\||[!(){},])       # operators/punctuation
        | (>=|<=|!=|==|>|<)      # comparisons
        | (-?\d+)                # integer literal
        | (true|false)           # boolean literal
        | ([a-zA-Z_]\w*)         # identifier
    )\s*
    """,
    re.VERBOSE,
)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """Tokenize a CEL expression into (type, value) pairs."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            return []  # Unparseable
        if m.group(1):
            tokens.append(("OP", m.group(1)))
        elif m.group(2):
            tokens.append(("CMP", m.group(2)))
        elif m.group(3):
            tokens.append(("INT", m.group(3)))
        elif m.group(4):
            tokens.append(("BOOL", m.group(4)))
        elif m.group(5):
            tokens.append(("IDENT", m.group(5)))
        pos = m.end()
    return tokens


_CMP_OPS: dict[str, Any] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def _builtin_eval(expr: str, variables: dict[str, Any]) -> bool | None:
    """Evaluate simple CEL expressions without external dependencies.

    Supports: variable lookup, !, &&, ||, comparisons (>=, <=, etc.),
    integer and boolean literals. Returns None for anything it can't handle.
    """
    tokens = _tokenize(expr)
    if not tokens:
        return None

    try:
        result, pos = _parse_or(tokens, 0, variables)
        if pos != len(tokens):
            return None
        return bool(result)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _parse_or(
    tokens: list[tuple[str, str]], pos: int, variables: dict[str, Any]
) -> tuple[Any, int]:
    left, pos = _parse_and(tokens, pos, variables)
    while pos < len(tokens) and tokens[pos] == ("OP", "||"):
        right, pos = _parse_and(tokens, pos + 1, variables)
        left = left or right
    return left, pos


def _parse_and(
    tokens: list[tuple[str, str]], pos: int, variables: dict[str, Any]
) -> tuple[Any, int]:
    left, pos = _parse_comparison(tokens, pos, variables)
    while pos < len(tokens) and tokens[pos] == ("OP", "&&"):
        right, pos = _parse_comparison(tokens, pos + 1, variables)
        left = left and right
    return left, pos


def _parse_comparison(
    tokens: list[tuple[str, str]], pos: int, variables: dict[str, Any]
) -> tuple[Any, int]:
    left, pos = _parse_unary(tokens, pos, variables)
    if pos < len(tokens) and tokens[pos][0] == "CMP":
        op_fn = _CMP_OPS[tokens[pos][1]]
        right, pos = _parse_unary(tokens, pos + 1, variables)
        return op_fn(left, right), pos
    return left, pos


def _parse_unary(
    tokens: list[tuple[str, str]], pos: int, variables: dict[str, Any]
) -> tuple[Any, int]:
    if pos < len(tokens) and tokens[pos] == ("OP", "!"):
        val, pos = _parse_unary(tokens, pos + 1, variables)
        return not val, pos
    return _parse_primary(tokens, pos, variables)


def _parse_primary(
    tokens: list[tuple[str, str]], pos: int, variables: dict[str, Any]
) -> tuple[Any, int]:
    if pos >= len(tokens):
        raise ValueError("unexpected end of expression")

    kind, value = tokens[pos]

    if kind == "BOOL":
        return value == "true", pos + 1
    if kind == "INT":
        return int(value), pos + 1
    if kind == "IDENT":
        if value not in variables:
            raise KeyError(value)
        return variables[value], pos + 1
    if kind == "OP" and value == "(":
        result, pos = _parse_or(tokens, pos + 1, variables)
        if pos < len(tokens) and tokens[pos] == ("OP", ")"):
            return result, pos + 1
        raise ValueError("missing closing parenthesis")

    raise ValueError(f"unexpected token: {kind}={value}")


# ---------------------------------------------------------------------------
# cel-python backend (optional)
# ---------------------------------------------------------------------------


def _celpy_eval(expr: str, variables: dict[str, Any]) -> bool | None:
    """Evaluate using cel-python if available."""
    try:
        env = celpy.Environment()
        program = env.program(env.compile(expr))
        cel_vars = {
            k: celpy.celtypes.BoolType(v) if isinstance(v, bool)
            else celpy.celtypes.IntType(v) if isinstance(v, int)
            else celpy.celtypes.StringType(v) if isinstance(v, str)
            else v
            for k, v in variables.items()
        }
        result = program.evaluate(cel_vars)
        return bool(result)
    except Exception:
        return None
