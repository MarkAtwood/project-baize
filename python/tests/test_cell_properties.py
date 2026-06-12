"""Tests for cell properties: arbitrary key-value attributes on grid cells.

Cell properties are declared in the zone definition and stored at runtime.
They can be queried via CEL (as prop_{key} 2D arrays) and mutated via the
set_cell_property perturber effect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.cel import try_eval_end_condition
from baize.definition import GameDefinition
from baize.end_conditions import _build_end_condition_variables
from baize.perturber import execute_effect
from baize.runtime import GameSession, GridZone


# ---------------------------------------------------------------------------
# Minimal game definition with cell properties
# ---------------------------------------------------------------------------

_TERRAIN_GAME = {
    "$schema": "../schema/game-definition.schema.json",
    "game": {
        "name": "Terrain Test",
        "players": ["White", "Black"],
        "information": "perfect",
    },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [3, 3],
            "visibility": "public",
            "cell_properties": {
                "0,0": {"terrain": "forest", "elevation": 2},
                "1,0": {"terrain": "mountain", "elevation": 5},
                "2,2": {"terrain": "forest", "elevation": 1},
            },
        }
    },
    "components": {
        "soldier": {"owner": "per_player", "count": 9},
    },
    "turn_order": {
        "type": "alternating",
        "players": ["White", "Black"],
        "actions_per_turn": 1,
        "mandatory": True,
    },
    "library": {
        "any_forest": "prop_terrain.exists(row, row.exists(cell, cell == \"forest\"))",
        "never": "false",
    },
    "end_conditions": [
        {"result": "draw", "condition": "never", "name": "never"},
    ],
    "authority": {"server_only": [], "client_verifiable": []},
}


def _load_terrain_game() -> GameDefinition:
    return GameDefinition.from_json(json.dumps(_TERRAIN_GAME))


# ---------------------------------------------------------------------------
# Tests: initialization from definition
# ---------------------------------------------------------------------------


class TestCellPropertyInit:
    """Cell properties declared in the zone definition are loaded at runtime."""

    def test_properties_loaded(self) -> None:
        session = GameSession(_load_terrain_game())
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(0, 0, "terrain") == "forest"
        assert zone.get_cell_property(0, 0, "elevation") == 2
        assert zone.get_cell_property(1, 0, "terrain") == "mountain"
        assert zone.get_cell_property(1, 0, "elevation") == 5
        assert zone.get_cell_property(2, 2, "terrain") == "forest"

    def test_unset_property_returns_none(self) -> None:
        session = GameSession(_load_terrain_game())
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(1, 1, "terrain") is None
        assert zone.get_cell_property(0, 0, "nonexistent") is None

    def test_out_of_bounds_returns_none(self) -> None:
        session = GameSession(_load_terrain_game())
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(99, 99, "terrain") is None

    def test_zone_without_cell_properties(self) -> None:
        defn_data = dict(_TERRAIN_GAME)
        defn_data["zones"] = {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
            }
        }
        defn = GameDefinition.from_json(json.dumps(defn_data))
        session = GameSession(defn)
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert len(zone.cell_properties) == 0


# ---------------------------------------------------------------------------
# Tests: set_cell_property perturber effect
# ---------------------------------------------------------------------------


class TestSetCellProperty:
    """The set_cell_property effect mutates cell properties at runtime."""

    def test_set_new_property(self) -> None:
        session = GameSession(_load_terrain_game())
        execute_effect(session, {
            "set_cell_property": {
                "zone": "board",
                "col": 1,
                "row": 1,
                "key": "terrain",
                "value": "road",
            }
        })
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(1, 1, "terrain") == "road"

    def test_overwrite_existing_property(self) -> None:
        session = GameSession(_load_terrain_game())
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(0, 0, "terrain") == "forest"
        execute_effect(session, {
            "set_cell_property": {
                "zone": "board",
                "col": 0,
                "row": 0,
                "key": "terrain",
                "value": "plain",
            }
        })
        assert zone.get_cell_property(0, 0, "terrain") == "plain"

    def test_set_integer_property(self) -> None:
        session = GameSession(_load_terrain_game())
        execute_effect(session, {
            "set_cell_property": {
                "zone": "board",
                "col": 2,
                "row": 0,
                "key": "elevation",
                "value": 10,
            }
        })
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(2, 0, "elevation") == 10

    def test_set_boolean_property(self) -> None:
        session = GameSession(_load_terrain_game())
        execute_effect(session, {
            "set_cell_property": {
                "zone": "board",
                "col": 0,
                "row": 0,
                "key": "fortified",
                "value": True,
            }
        })
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.get_cell_property(0, 0, "fortified") is True

    def test_unknown_zone_raises(self) -> None:
        session = GameSession(_load_terrain_game())
        with pytest.raises(ValueError, match="unknown zone"):
            execute_effect(session, {
                "set_cell_property": {
                    "zone": "nonexistent",
                    "col": 0,
                    "row": 0,
                    "key": "terrain",
                    "value": "road",
                }
            })


# ---------------------------------------------------------------------------
# Tests: wire format round-trip
# ---------------------------------------------------------------------------


class TestCellPropertyWire:
    """Cell properties are serialized in the wire format."""

    def test_wire_includes_cell_properties(self) -> None:
        session = GameSession(_load_terrain_game())
        wire = session.to_wire_state()
        grid_state = wire.zones["board"]
        assert grid_state.cell_properties is not None
        assert "0,0" in grid_state.cell_properties
        assert grid_state.cell_properties["0,0"]["terrain"] == "forest"
        assert grid_state.cell_properties["0,0"]["elevation"] == 2

    def test_wire_omits_empty_cell_properties(self) -> None:
        defn_data = dict(_TERRAIN_GAME)
        defn_data["zones"] = {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
            }
        }
        defn = GameDefinition.from_json(json.dumps(defn_data))
        session = GameSession(defn)
        wire = session.to_wire_state()
        grid_dict = wire.zones["board"].to_dict()
        assert "cell_properties" not in grid_dict

    def test_wire_round_trip_preserves_properties(self) -> None:
        session = GameSession(_load_terrain_game())
        wire = session.to_wire_state()
        wire_dict = wire.zones["board"].to_dict()
        assert wire_dict["cell_properties"]["1,0"]["terrain"] == "mountain"
        assert wire_dict["cell_properties"]["1,0"]["elevation"] == 5


# ---------------------------------------------------------------------------
# Tests: state hash changes with cell properties
# ---------------------------------------------------------------------------


class TestCellPropertyHash:
    """Cell property mutations change the state hash."""

    def test_mutation_changes_hash(self) -> None:
        session = GameSession(_load_terrain_game())
        hash_before = session.compute_state_hash()
        execute_effect(session, {
            "set_cell_property": {
                "zone": "board",
                "col": 0,
                "row": 0,
                "key": "terrain",
                "value": "plain",
            }
        })
        hash_after = session.compute_state_hash()
        assert hash_before != hash_after


# ---------------------------------------------------------------------------
# Tests: CEL context exposure
# ---------------------------------------------------------------------------


class TestCellPropertyCEL:
    """Cell properties are exposed as prop_{key} variables in CEL context."""

    def test_prop_terrain_in_variables(self) -> None:
        session = GameSession(_load_terrain_game())
        variables = _build_end_condition_variables(session, "White")
        assert "prop_terrain" in variables
        assert "prop_elevation" in variables

    def test_prop_terrain_rows_structure(self) -> None:
        session = GameSession(_load_terrain_game())
        variables = _build_end_condition_variables(session, "White")
        terrain = variables["prop_terrain"]
        assert isinstance(terrain, list)
        assert len(terrain) == 3  # 3 rows
        assert len(terrain[0]) == 3  # 3 cols
        # row 0: forest, mountain, ""
        assert terrain[0][0] == "forest"
        assert terrain[0][1] == "mountain"
        assert terrain[0][2] == ""
        # row 2: "", "", forest
        assert terrain[2][2] == "forest"

    def test_prop_elevation_values(self) -> None:
        session = GameSession(_load_terrain_game())
        variables = _build_end_condition_variables(session, "White")
        elevation = variables["prop_elevation"]
        assert elevation[0][0] == "2"  # int converted to string
        assert elevation[0][1] == "5"
        assert elevation[0][2] == ""  # unset

    def test_cel_exists_on_prop(self) -> None:
        """CEL can query whether any cell has a specific property value."""
        session = GameSession(_load_terrain_game())
        variables = _build_end_condition_variables(session, "White")
        result = try_eval_end_condition(
            variables,
            'prop_terrain.exists(row, row.exists(cell, cell == "forest"))',
        )
        assert result is True

    def test_cel_exists_nonexistent_value(self) -> None:
        session = GameSession(_load_terrain_game())
        variables = _build_end_condition_variables(session, "White")
        result = try_eval_end_condition(
            variables,
            'prop_terrain.exists(row, row.exists(cell, cell == "swamp"))',
        )
        assert result is False

    def test_no_prop_variables_when_no_cell_properties(self) -> None:
        defn_data = dict(_TERRAIN_GAME)
        defn_data["zones"] = {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
            }
        }
        defn = GameDefinition.from_json(json.dumps(defn_data))
        session = GameSession(defn)
        variables = _build_end_condition_variables(session, "White")
        prop_keys = [k for k in variables if k.startswith("prop_")]
        assert prop_keys == []
