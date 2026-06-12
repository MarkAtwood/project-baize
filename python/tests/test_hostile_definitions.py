"""Tests for hostile/malformed game definitions in Python.

Verifies the engine rejects or handles gracefully:
- Empty dict, None, wrong types
- Absurd dimensions, player counts, component counts
- Missing required fields
- Very long strings
All should raise exceptions, not crash.
"""

from __future__ import annotations

import json

import pytest

from baize.definition import GameDefinition
from baize.error import ParseError, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_data() -> dict:
    return {
        "game": {"name": "Test", "players": ["A", "B"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"}
        },
        "components": {
            "piece": {"owner": "per_player", "count": "unlimited"}
        },
        "turn_order": {"type": "alternating", "players": ["A", "B"]},
        "end_conditions": [{"result": "draw", "condition": "board_is_full"}],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }


def _parse(data: dict) -> GameDefinition:
    return GameDefinition.from_json(json.dumps(data), validate_schema=False)


# ===================================================================
# Empty and structurally wrong JSON
# ===================================================================

class TestStructurallyWrong:

    def test_empty_string(self) -> None:
        with pytest.raises(ParseError):
            GameDefinition.from_json("")

    def test_empty_object(self) -> None:
        with pytest.raises((ParseError, KeyError)):
            GameDefinition.from_json("{}")

    def test_json_array(self) -> None:
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("[1, 2, 3]")

    def test_json_number(self) -> None:
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("42")

    def test_json_string(self) -> None:
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json('"hello"')

    def test_json_null(self) -> None:
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("null")

    def test_json_true(self) -> None:
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("true")

    def test_binary_garbage(self) -> None:
        with pytest.raises(ParseError):
            GameDefinition.from_json("\x00\x01\x02 garbage !@#$%^")


# ===================================================================
# Wrong types for known fields
# ===================================================================

class TestWrongTypes:

    def test_players_as_number(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = 42
        with pytest.raises((ParseError, TypeError, ValueError)):
            _parse(data)

    def test_players_as_string(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = "two"
        with pytest.raises((ParseError, TypeError, ValueError)):
            _parse(data)

    def test_zones_as_array(self) -> None:
        data = _minimal_data()
        data["zones"] = [1, 2, 3]
        with pytest.raises((ParseError, TypeError, AttributeError)):
            _parse(data)

    def test_end_conditions_as_string(self) -> None:
        data = _minimal_data()
        data["end_conditions"] = "none"
        with pytest.raises((ParseError, TypeError)):
            _parse(data)

    def test_dimensions_as_string(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = "big"
        # Should raise during zone creation or validation
        with pytest.raises((ParseError, TypeError, ValueError, ValidationError)):
            _parse(data)

    def test_game_name_as_number(self) -> None:
        data = _minimal_data()
        data["game"]["name"] = 999
        # Might parse (Python is lenient with str) but should not crash
        try:
            _parse(data)
        except (ParseError, TypeError, ValueError, ValidationError):
            pass  # Any of these are acceptable rejections


# ===================================================================
# Missing required fields
# ===================================================================

class TestMissingFields:

    def test_missing_game(self) -> None:
        data = _minimal_data()
        del data["game"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_zones(self) -> None:
        data = _minimal_data()
        del data["zones"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_end_conditions(self) -> None:
        data = _minimal_data()
        del data["end_conditions"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_authority(self) -> None:
        data = _minimal_data()
        del data["authority"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_turn_order(self) -> None:
        data = _minimal_data()
        del data["turn_order"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_components(self) -> None:
        data = _minimal_data()
        del data["components"]
        with pytest.raises((ParseError, KeyError)):
            _parse(data)

    def test_missing_game_name(self) -> None:
        data = _minimal_data()
        del data["game"]["name"]
        with pytest.raises((ParseError, KeyError, ValueError)):
            _parse(data)

    def test_missing_game_players(self) -> None:
        data = _minimal_data()
        del data["game"]["players"]
        with pytest.raises((ParseError, KeyError, ValueError)):
            _parse(data)


# ===================================================================
# Null/None in required positions
# ===================================================================

class TestNullValues:

    def test_null_game(self) -> None:
        data = _minimal_data()
        data["game"] = None
        with pytest.raises((ParseError, TypeError, AttributeError)):
            _parse(data)

    def test_null_zones(self) -> None:
        data = _minimal_data()
        data["zones"] = None
        with pytest.raises((ParseError, TypeError, AttributeError)):
            _parse(data)

    def test_null_game_name(self) -> None:
        data = _minimal_data()
        data["game"]["name"] = None
        with pytest.raises((ParseError, TypeError, ValueError, ValidationError)):
            _parse(data)

    def test_null_players(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = None
        with pytest.raises((ParseError, TypeError, ValueError)):
            _parse(data)


# ===================================================================
# Absurd grid dimensions
# ===================================================================

class TestAbsurdDimensions:

    def test_dimension_zero(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [0, 3]
        # May parse but should not allocate huge memory or crash
        try:
            defn = _parse(data)
            # If parsed, dimensions are stored as-is
            assert defn.zones["board"].dimensions is not None
        except (ParseError, ValidationError, ValueError):
            pass  # Acceptable rejection

    def test_dimension_negative(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [-1, -1]
        # Should be rejected or at least not crash
        try:
            _parse(data)
        except (ParseError, ValidationError, ValueError):
            pass  # Acceptable

    def test_dimension_million(self) -> None:
        """[999999, 999999] would allocate ~1 trillion cells. Must reject."""
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [999999, 999999]
        with pytest.raises((ValidationError, MemoryError, OverflowError)):
            _parse(data)

    def test_dimension_1001(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [1001, 1]
        with pytest.raises(ValidationError):
            _parse(data)

    def test_dimension_at_limit(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [1000, 1000]
        defn = _parse(data)
        assert defn.zones["board"].dimensions == [1000, 1000]

    def test_dimension_1x1(self) -> None:
        data = _minimal_data()
        data["zones"]["board"]["dimensions"] = [1, 1]
        defn = _parse(data)
        assert defn.zones["board"].dimensions == [1, 1]


# ===================================================================
# Player count limits
# ===================================================================

class TestPlayerLimits:

    def test_too_many_players(self) -> None:
        data = _minimal_data()
        names = [f"p{i}" for i in range(101)]
        data["game"]["players"] = names
        data["turn_order"]["players"] = names
        with pytest.raises(ValidationError):
            _parse(data)

    def test_100_players_ok(self) -> None:
        data = _minimal_data()
        names = [f"p{i}" for i in range(100)]
        data["game"]["players"] = names
        data["turn_order"]["players"] = names
        defn = _parse(data)
        assert len(defn.game.players) == 100

    def test_player_range_too_high(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = {"min": 2, "max": 101}
        with pytest.raises(ValidationError):
            _parse(data)

    def test_player_range_zero_min(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = {"min": 0, "max": 4}
        with pytest.raises((ParseError, ValueError)):
            _parse(data)

    def test_player_range_inverted(self) -> None:
        data = _minimal_data()
        data["game"]["players"] = {"min": 10, "max": 2}
        with pytest.raises((ParseError, ValueError)):
            _parse(data)


# ===================================================================
# Component count limits
# ===================================================================

class TestComponentLimits:

    def test_single_component_exceeds_10000(self) -> None:
        data = _minimal_data()
        data["components"] = {"stone": {"count": 10001}}
        with pytest.raises(ValidationError):
            _parse(data)

    def test_per_player_overflow(self) -> None:
        """100 players x 101 each = 10100 > 10000"""
        data = _minimal_data()
        names = [f"p{i}" for i in range(100)]
        data["game"]["players"] = names
        data["turn_order"]["players"] = names
        data["components"] = {"piece": {"owner": "per_player", "count": 101}}
        with pytest.raises(ValidationError):
            _parse(data)

    def test_within_limit(self) -> None:
        data = _minimal_data()
        data["components"] = {"stone": {"count": 10000}}
        defn = _parse(data)
        assert defn.components["stone"].count == 10000


# ===================================================================
# Long strings
# ===================================================================

class TestLongStrings:

    def test_very_long_game_name(self) -> None:
        """A 1MB name is unusual but should not crash."""
        data = _minimal_data()
        data["game"]["name"] = "A" * 1_000_000
        defn = _parse(data)
        assert len(defn.game.name) == 1_000_000

    def test_very_long_player_name(self) -> None:
        data = _minimal_data()
        long_name = "X" * 100_000
        data["game"]["players"] = [long_name, "B"]
        data["turn_order"]["players"] = [long_name, "B"]
        defn = _parse(data)
        assert len(defn.game.players[0]) == 100_000

    def test_very_long_zone_name(self) -> None:
        data = _minimal_data()
        long_zone = "z" * 100_000
        data["zones"] = {
            long_zone: {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"}
        }
        defn = _parse(data)
        assert long_zone in defn.zones


# ===================================================================
# Extra/unknown fields do not crash
# ===================================================================

class TestExtraFields:

    def test_extra_top_level_field(self) -> None:
        data = _minimal_data()
        data["completely_unknown"] = "surprise"
        data["another_alien"] = [1, 2, 3]
        defn = _parse(data)
        assert defn.game.name == "Test"

    def test_extra_nested_field(self) -> None:
        data = _minimal_data()
        data["game"]["extra_field"] = {"nested": True}
        defn = _parse(data)
        assert defn.game.name == "Test"
