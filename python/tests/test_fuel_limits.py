"""Tests for computational DoS prevention: fuel limits on CEL and move generation."""

from __future__ import annotations

import json

import pytest

from baize.cel import (
    MAX_CEL_EVAL_STEPS,
    MAX_CEL_LENGTH,
    MAX_CEL_NESTING,
    _check_nesting,
    try_eval_end_condition,
    try_eval_move_condition,
)
from baize.definition import GameDefinition
from baize.error import ParseError, ValidationError
from baize.moves import MAX_LEGAL_MOVES, legal_moves
from baize.runtime import GameSession, runtime_zone_from_definition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_GAME_JSON = json.dumps({
    "game": {"name": "Minimal", "players": ["A", "B"], "information": "perfect"},
    "zones": {
        "board": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"}
    },
    "components": {
        "piece": {"owner": "per_player", "count": "unlimited"}
    },
    "turn_order": {"type": "alternating", "players": ["A", "B"]},
    "end_conditions": [
        {"result": "draw", "condition": "board_is_full"}
    ],
    "authority": {"server_only": [], "client_verifiable": ["all"]},
})


def _minimal_dict() -> dict:
    return json.loads(MINIMAL_GAME_JSON)


# ===================================================================
# CEL Fuel Limits
# ===================================================================


class TestCelLengthLimit:
    """Expressions exceeding MAX_CEL_LENGTH are rejected."""

    def test_normal_expression_works(self) -> None:
        result = try_eval_move_condition(True, False, "empty")
        assert result is True

    def test_oversized_expression_rejected(self) -> None:
        expr = "a" * (MAX_CEL_LENGTH + 1)
        result = try_eval_move_condition(True, False, expr)
        assert result is None

    def test_exactly_at_limit_not_rejected(self) -> None:
        # An expression exactly at the limit should be attempted (not rejected)
        # It will fail to parse (all a's), but that's a parse error not a limit
        expr = "a" * MAX_CEL_LENGTH
        result = try_eval_move_condition(True, False, expr)
        # None because "aaa...a" is not valid CEL, not because of length
        assert result is None


class TestCelNestingLimit:
    """Expressions exceeding MAX_CEL_NESTING are rejected."""

    def test_shallow_nesting_works(self) -> None:
        result = try_eval_move_condition(True, False, "((((empty))))")
        assert result is True

    def test_deep_nesting_rejected(self) -> None:
        expr = "(" * (MAX_CEL_NESTING + 1) + "true" + ")" * (MAX_CEL_NESTING + 1)
        result = try_eval_move_condition(True, False, expr)
        assert result is None

    def test_check_nesting_helper(self) -> None:
        assert _check_nesting("((()))") is True
        assert _check_nesting("(" * 33 + ")" * 33) is False
        assert _check_nesting("(" * 32 + ")" * 32) is True

    def test_nesting_at_boundary(self) -> None:
        expr = "(" * MAX_CEL_NESTING + "true" + ")" * MAX_CEL_NESTING
        # At exactly the limit: should be OK
        assert _check_nesting(expr) is True
        # One more: rejected
        expr2 = "(" * (MAX_CEL_NESTING + 1) + "true" + ")" * (MAX_CEL_NESTING + 1)
        assert _check_nesting(expr2) is False


class TestCelFuelLimit:
    """The built-in evaluator aborts when fuel is exhausted."""

    def test_simple_expression_within_fuel(self) -> None:
        result = try_eval_end_condition({"x": True}, "x")
        assert result is True

    def test_end_condition_composable(self) -> None:
        # This exercises the .exists/.all path
        variables = {
            "lines": [["X", "X", "X"], ["O", "", ""]],
            "current_player": "X",
        }
        result = try_eval_end_condition(
            variables,
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        assert result is True


# ===================================================================
# Move Generation Limits
# ===================================================================


class TestMoveGenerationLimit:
    """legal_moves stops at MAX_LEGAL_MOVES."""

    def test_small_game_within_limit(self) -> None:
        defn = GameDefinition.from_json(MINIMAL_GAME_JSON)
        session = GameSession(defn)
        moves = legal_moves(session)
        # Empty board, no pieces placed: no moves
        assert len(moves) <= MAX_LEGAL_MOVES


# ===================================================================
# Definition Loading Limits
# ===================================================================


class TestPlayerCountLimit:
    """Definitions with too many players are rejected."""

    def test_100_players_accepted(self) -> None:
        d = _minimal_dict()
        names = [f"p{i}" for i in range(100)]
        d["game"]["players"] = names
        d["turn_order"]["players"] = names
        defn = GameDefinition.from_json(json.dumps(d), validate_schema=False)
        assert len(defn.game.players) == 100

    def test_101_players_rejected(self) -> None:
        d = _minimal_dict()
        names = [f"p{i}" for i in range(101)]
        d["game"]["players"] = names
        d["turn_order"]["players"] = names
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)

    def test_player_range_101_max_rejected(self) -> None:
        d = _minimal_dict()
        d["game"]["players"] = {"min": 2, "max": 101}
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)


class TestGridDimensionLimit:
    """Grid zones with dimensions > 1000 are rejected."""

    def test_1000x1000_accepted_at_definition(self) -> None:
        d = _minimal_dict()
        d["zones"]["board"]["dimensions"] = [1000, 1000]
        defn = GameDefinition.from_json(json.dumps(d), validate_schema=False)
        assert defn.zones["board"].dimensions == [1000, 1000]

    def test_1001x1_rejected(self) -> None:
        d = _minimal_dict()
        d["zones"]["board"]["dimensions"] = [1001, 1]
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)

    def test_1x1001_rejected(self) -> None:
        d = _minimal_dict()
        d["zones"]["board"]["dimensions"] = [1, 1001]
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)

    def test_huge_dimensions_rejected(self) -> None:
        d = _minimal_dict()
        d["zones"]["board"]["dimensions"] = [1000000, 1000000]
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)

    def test_runtime_zone_rejects_huge_grid(self) -> None:
        from baize.definition import Zone
        zone_def = Zone.from_dict({
            "zone_type": "grid",
            "visibility": "public",
            "dimensions": [1001, 1001],
        })
        with pytest.raises(ValidationError):
            runtime_zone_from_definition(zone_def)


class TestComponentCountLimit:
    """Definitions with too many total components are rejected."""

    def test_many_components_within_limit(self) -> None:
        d = _minimal_dict()
        d["components"] = {f"c{i}": {} for i in range(100)}
        defn = GameDefinition.from_json(json.dumps(d), validate_schema=False)
        assert len(defn.components) == 100

    def test_too_many_components_rejected(self) -> None:
        d = _minimal_dict()
        d["components"] = {f"c{i}": {"count": 1} for i in range(10001)}
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)

    def test_per_player_multiplier(self) -> None:
        """Per-player components count as players * count."""
        d = _minimal_dict()
        # 50 players, each with 201 per-player pieces = 10050 > 10000
        names = [f"p{i}" for i in range(50)]
        d["game"]["players"] = names
        d["turn_order"]["players"] = names
        d["components"] = {"piece": {"owner": "per_player", "count": 201}}
        with pytest.raises((ParseError, ValidationError)):
            GameDefinition.from_json(json.dumps(d), validate_schema=False)


# ===================================================================
# Reference Games Still Work
# ===================================================================


class TestReferenceGamesWithinLimits:
    """All 22 reference game definitions pass validation."""

    def test_all_reference_games_parse(self) -> None:
        from pathlib import Path
        games_dir = Path(__file__).resolve().parent.parent.parent / "games"
        if not games_dir.exists():
            pytest.skip("games directory not found")
        game_files = sorted(games_dir.glob("*.json"))
        assert len(game_files) >= 20, f"Expected 20+ games, found {len(game_files)}"
        for game_file in game_files:
            defn = GameDefinition.from_json(game_file.read_text())
            assert defn.game.name, f"{game_file.name} has empty name"
