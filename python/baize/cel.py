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
        (&&|\|\|)                # multi-char boolean operators (before single-char)
        | (>=|<=|!=|==|>|<)      # comparisons (before single-char ! and =)
        | ([!(){},\.])           # single-char operators/punctuation
        | (-?\d+)                # integer literal
        | (true|false)           # boolean literal
        | "([^"]*)"             # double-quoted string literal
        | '([^']*)'             # single-quoted string literal
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
            tokens.append(("OP", m.group(3)))
        elif m.group(4):
            tokens.append(("INT", m.group(4)))
        elif m.group(5):
            tokens.append(("BOOL", m.group(5)))
        elif m.group(6) is not None:
            tokens.append(("STR", m.group(6)))
        elif m.group(7) is not None:
            tokens.append(("STR", m.group(7)))
        elif m.group(8):
            tokens.append(("IDENT", m.group(8)))
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
        result: Any = value == "true"
        return _parse_postfix(tokens, pos + 1, result, variables)
    if kind == "STR":
        result = value
        return _parse_postfix(tokens, pos + 1, result, variables)
    if kind == "INT":
        result = int(value)
        return _parse_postfix(tokens, pos + 1, result, variables)
    if kind == "IDENT":
        if value not in variables:
            raise KeyError(value)
        result = variables[value]
        return _parse_postfix(tokens, pos + 1, result, variables)
    if kind == "OP" and value == "(":
        result, pos = _parse_or(tokens, pos + 1, variables)
        if pos < len(tokens) and tokens[pos] == ("OP", ")"):
            return _parse_postfix(tokens, pos + 1, result, variables)
        raise ValueError("missing closing parenthesis")

    raise ValueError(f"unexpected token: {kind}={value}")


def _parse_postfix(
    tokens: list[tuple[str, str]],
    pos: int,
    value: Any,
    variables: dict[str, Any],
) -> tuple[Any, int]:
    """Handle .method(var, predicate) calls on a value (exists, all)."""
    while (
        pos + 1 < len(tokens)
        and tokens[pos] == ("OP", ".")
        and tokens[pos + 1][0] == "IDENT"
    ):
        method = tokens[pos + 1][1]
        pos += 2  # skip dot and method name

        if method in ("exists", "all", "filter") and isinstance(value, list):
            # Expect: (var_name, predicate_expr...)
            if pos >= len(tokens) or tokens[pos] != ("OP", "("):
                raise ValueError(f"expected ( after .{method}")
            pos += 1  # skip (

            # Read the binding variable name
            if pos >= len(tokens) or tokens[pos][0] != "IDENT":
                raise ValueError(f".{method} requires a variable name")
            bind_var = tokens[pos][1]
            pos += 1

            # Expect comma
            if pos >= len(tokens) or tokens[pos] != ("OP", ","):
                raise ValueError(f".{method} requires (var, predicate)")
            pos += 1  # skip comma

            # Find the matching closing paren to extract the predicate tokens
            depth = 1
            pred_start = pos
            while pos < len(tokens) and depth > 0:
                if tokens[pos] == ("OP", "("):
                    depth += 1
                elif tokens[pos] == ("OP", ")"):
                    depth -= 1
                if depth > 0:
                    pos += 1
            pred_tokens = tokens[pred_start:pos]
            pos += 1  # skip closing )

            if method == "filter":
                filtered = []
                for item in value:
                    inner_vars = dict(variables)
                    inner_vars[bind_var] = item
                    pred_result, _ = _parse_or(pred_tokens, 0, inner_vars)
                    if bool(pred_result):
                        filtered.append(item)
                value = filtered
            else:
                results = []
                for item in value:
                    inner_vars = dict(variables)
                    inner_vars[bind_var] = item
                    pred_result, _ = _parse_or(pred_tokens, 0, inner_vars)
                    results.append(bool(pred_result))
                value = any(results) if method == "exists" else all(results)

        elif method == "size" and isinstance(value, (list, str)):
            # .size() — no args needed
            if pos < len(tokens) and tokens[pos] == ("OP", "("):
                pos += 1  # skip (
                if pos < len(tokens) and tokens[pos] == ("OP", ")"):
                    pos += 1  # skip )
            value = len(value)
        else:
            raise ValueError(f"unsupported method: .{method}")

    return value, pos


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
