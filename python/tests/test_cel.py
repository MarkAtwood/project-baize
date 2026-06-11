"""Tests for the CEL expression evaluator."""

from baize.cel import try_eval_end_condition, try_eval_move_condition


class TestEndConditionEval:
    def test_simple_variable_true(self) -> None:
        result = try_eval_end_condition({"three_in_line": True}, "three_in_line")
        assert result is True

    def test_simple_variable_false(self) -> None:
        result = try_eval_end_condition({"three_in_line": False}, "three_in_line")
        assert result is False

    def test_boolean_and(self) -> None:
        variables = {"in_check": True, "has_legal_moves": False}
        result = try_eval_end_condition(variables, "in_check && !has_legal_moves")
        assert result is True

    def test_boolean_or(self) -> None:
        variables = {"a": False, "b": True}
        result = try_eval_end_condition(variables, "a || b")
        assert result is True

    def test_comparison_ge(self) -> None:
        result = try_eval_end_condition({"halfmove_clock": 101}, "halfmove_clock >= 100")
        assert result is True

    def test_comparison_lt(self) -> None:
        result = try_eval_end_condition({"halfmove_clock": 50}, "halfmove_clock >= 100")
        assert result is False

    def test_negation(self) -> None:
        result = try_eval_end_condition({"in_check": False}, "!in_check")
        assert result is True

    def test_complex_chess_checkmate(self) -> None:
        variables = {"in_check": True, "has_legal_moves": False}
        result = try_eval_end_condition(variables, "in_check && !has_legal_moves")
        assert result is True

    def test_complex_chess_stalemate(self) -> None:
        variables = {"in_check": False, "has_legal_moves": False}
        result = try_eval_end_condition(variables, "!in_check && !has_legal_moves")
        assert result is True

    def test_legacy_string_returns_none(self) -> None:
        result = try_eval_end_condition({}, "three_in_line(current.marks, row OR column)")
        assert result is None

    def test_boolean_literal_true(self) -> None:
        result = try_eval_end_condition({}, "true")
        assert result is True

    def test_boolean_literal_false(self) -> None:
        result = try_eval_end_condition({}, "false")
        assert result is False

    def test_parenthesized_expression(self) -> None:
        variables = {"a": True, "b": False, "c": True}
        result = try_eval_end_condition(variables, "a && (b || c)")
        assert result is True

    def test_empty_expression_returns_none(self) -> None:
        result = try_eval_end_condition({}, "")
        assert result is None

    def test_undefined_variable_returns_none(self) -> None:
        result = try_eval_end_condition({}, "undefined_var")
        assert result is None


class TestMoveConditionEval:
    def test_empty(self) -> None:
        assert try_eval_move_condition(True, False, "empty") is True
        assert try_eval_move_condition(False, True, "empty") is False

    def test_enemy(self) -> None:
        assert try_eval_move_condition(False, True, "enemy") is True
        assert try_eval_move_condition(True, False, "enemy") is False

    def test_empty_or_enemy(self) -> None:
        assert try_eval_move_condition(True, False, "empty || enemy") is True
        assert try_eval_move_condition(False, True, "empty || enemy") is True
        assert try_eval_move_condition(False, False, "empty || enemy") is False

    def test_empty_and_first_move(self) -> None:
        # first_move is always False until per-component tracking is added
        assert try_eval_move_condition(True, False, "empty && first_move") is False

    def test_legacy_and_returns_none(self) -> None:
        assert try_eval_move_condition(True, False, "empty AND first_move") is None
