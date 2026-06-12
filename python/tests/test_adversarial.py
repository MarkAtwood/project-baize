"""Adversarial and defensive tests.

We don't trust callers, callees, filesystem data, or network input.
Every test verifies the engine raises an appropriate exception or returns
a safe default -- no panics, no silent corruption, no infinite loops.
"""

from __future__ import annotations

import json

import pytest

from baize.action import Action
from baize.definition import GameDefinition, Zone
from baize.error import ParseError, ValidationError
from baize.notation import format_move, parse_move
from baize.runtime import (
    ComponentData,
    ComponentId,
    ComponentTable,
    CounterZone,
    GameSession,
    GraphZone,
    GridZone,
    TrackZone,
    runtime_zone_from_definition,
)

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


def _minimal_def() -> GameDefinition:
    return GameDefinition.from_json(MINIMAL_GAME_JSON)


def _make_grid_zone_def(dims: list[int] | int, **kw: object) -> Zone:
    """Build a Zone definition for a grid with given dimensions."""
    d: dict = {"zone_type": "grid", "visibility": "public", "dimensions": dims}
    d.update(kw)
    return Zone.from_dict(d)


def _make_graph_zone_def(nodes: list[str], edges: list[list[str]] | None = None) -> Zone:
    d: dict = {"zone_type": "graph", "visibility": "public", "nodes": nodes}
    if edges is not None:
        d["edges"] = edges
    return Zone.from_dict(d)


def _make_track_zone_def(length: int) -> Zone:
    return Zone.from_dict({
        "zone_type": "track",
        "visibility": "public",
        "length": length,
    })


# ===================================================================
# TestMalformedJSON
# ===================================================================

class TestMalformedJSON:
    """Feed broken, weird, or wrong-type JSON to GameDefinition.from_json."""

    def test_empty_string(self) -> None:
        with pytest.raises(ParseError):
            GameDefinition.from_json("")

    def test_random_bytes(self) -> None:
        with pytest.raises(ParseError):
            GameDefinition.from_json("\x00\xff\xfe garbage !@#$%^")

    def test_valid_json_array(self) -> None:
        """Valid JSON but wrong top-level type (array)."""
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("[1, 2, 3]")

    def test_valid_json_number(self) -> None:
        """Valid JSON but wrong top-level type (number)."""
        with pytest.raises((ParseError, TypeError, AttributeError)):
            GameDefinition.from_json("42")

    def test_missing_required_fields(self) -> None:
        """JSON object missing all required keys."""
        with pytest.raises(ParseError):
            GameDefinition.from_json('{"foo": "bar"}')

    def test_extra_unknown_fields_still_parse(self) -> None:
        """Extra fields should not prevent parsing -- additionalProperties handling."""
        data = json.loads(MINIMAL_GAME_JSON)
        data["completely_unknown_field"] = "surprise"
        data["another_alien"] = [1, 2, 3]
        # Should not raise -- unknown fields are ignored
        defn = GameDefinition.from_json(
            json.dumps(data), validate_schema=False
        )
        assert defn.game.name == "Minimal"


# ===================================================================
# TestHostileZoneDefinitions
# ===================================================================

class TestHostileZoneDefinitions:
    """Feed weird dimensions, empty graphs, and self-loops."""

    def test_grid_zero_dimensions(self) -> None:
        """[0, 0] grid: empty but no crash."""
        zone = runtime_zone_from_definition(_make_grid_zone_def([0, 0]))
        assert isinstance(zone, GridZone)
        assert zone.width == 0
        assert zone.height == 0
        assert zone.cells == []
        # Operations on empty grid return None
        assert zone.grid_get(0, 0) is None

    def test_grid_negative_dimensions(self) -> None:
        with pytest.raises(ValidationError):
            runtime_zone_from_definition(_make_grid_zone_def([-1, -1]))

    def test_grid_huge_dimensions(self) -> None:
        """[999999, 999999] would allocate ~1 trillion cells. Must reject."""
        with pytest.raises((ValidationError, MemoryError, OverflowError)):
            runtime_zone_from_definition(_make_grid_zone_def([999999, 999999]))

    def test_grid_minimal_1x1(self) -> None:
        """[1, 1] is the smallest valid grid."""
        zone = runtime_zone_from_definition(_make_grid_zone_def([1, 1]))
        assert isinstance(zone, GridZone)
        assert zone.width == 1 and zone.height == 1
        assert len(zone.cells) == 1
        # Place and retrieve
        cid = ComponentId(0)
        zone.grid_set(0, 0, cid)
        assert zone.grid_get(0, 0) == cid

    def test_graph_empty_nodes(self) -> None:
        """Graph with zero nodes -- legal, just empty."""
        zone = runtime_zone_from_definition(_make_graph_zone_def([]))
        assert isinstance(zone, GraphZone)
        assert len(zone.node_names) == 0
        assert zone.graph_get("anything") is None

    def test_graph_duplicate_node_names(self) -> None:
        """Duplicate node names: last one wins in name_to_index dict."""
        zone = runtime_zone_from_definition(_make_graph_zone_def(["A", "A", "A"]))
        assert isinstance(zone, GraphZone)
        # Should not crash; the mapping silently overwrites
        assert len(zone.node_names) == 3

    def test_graph_self_loop_edge(self) -> None:
        """Self-loop edge ["A", "A"] should not crash."""
        zone = runtime_zone_from_definition(
            _make_graph_zone_def(["A", "B"], edges=[["A", "A"]])
        )
        assert isinstance(zone, GraphZone)
        # A is its own neighbor (self-loop added twice: a->a and a->a)
        neighbors = zone.graph_neighbors("A")
        assert "A" in neighbors


# ===================================================================
# TestHostileGridOperations
# ===================================================================

class TestHostileGridOperations:
    """Out-of-bounds and masked-cell access on GridZone."""

    def test_grid_get_negative_coords(self) -> None:
        zone = runtime_zone_from_definition(_make_grid_zone_def([3, 3]))
        assert isinstance(zone, GridZone)
        assert zone.grid_get(-1, -1) is None

    def test_grid_get_way_beyond_bounds(self) -> None:
        zone = runtime_zone_from_definition(_make_grid_zone_def([3, 3]))
        assert isinstance(zone, GridZone)
        assert zone.grid_get(999999, 999999) is None

    def test_grid_set_negative_coords(self) -> None:
        zone = runtime_zone_from_definition(_make_grid_zone_def([3, 3]))
        assert isinstance(zone, GridZone)
        result = zone.grid_set(-1, -1, ComponentId(0))
        assert result is None  # no-op

    def test_grid_set_masked_cell(self) -> None:
        """With valid_cells mask, accessing a masked-out cell returns None."""
        zone_def = _make_grid_zone_def([3, 3], valid_cells=[[1, 1]])
        zone = runtime_zone_from_definition(zone_def)
        assert isinstance(zone, GridZone)
        # (0, 0) is NOT in valid_cells, so it should be masked
        assert zone.grid_get(0, 0) is None
        result = zone.grid_set(0, 0, ComponentId(0))
        assert result is None

    def test_component_table_out_of_range(self) -> None:
        table = ComponentTable()
        cid = table.insert(ComponentData(
            id=ComponentId(0), string_id="p1", component_type="piece",
        ))
        # Access with a valid-but-beyond-range ID
        assert table.get(ComponentId(999999)) is None


# ===================================================================
# TestHostileGraphOperations
# ===================================================================

class TestHostileGraphOperations:
    """Access patterns that should return safe defaults on GraphZone."""

    def _make_graph(self) -> GraphZone:
        zone = runtime_zone_from_definition(
            _make_graph_zone_def(["A", "B", "C"], edges=[["A", "B"], ["B", "C"]])
        )
        assert isinstance(zone, GraphZone)
        return zone

    def test_graph_get_empty_string_node(self) -> None:
        g = self._make_graph()
        assert g.graph_get("") is None

    def test_graph_get_nonexistent_node(self) -> None:
        g = self._make_graph()
        assert g.graph_get("DOES_NOT_EXIST") is None

    def test_graph_set_nonexistent_node(self) -> None:
        g = self._make_graph()
        result = g.graph_set("DOES_NOT_EXIST", ComponentId(0))
        assert result is None

    def test_graph_neighbors_nonexistent_node(self) -> None:
        g = self._make_graph()
        assert g.graph_neighbors("DOES_NOT_EXIST") == []


# ===================================================================
# TestHostileNotation
# ===================================================================

class TestHostileNotation:
    """Feed garbage to parse_move and format_move."""

    def test_parse_empty_string(self) -> None:
        defn = _minimal_def()
        assert parse_move("", defn) is None

    def test_parse_very_long_string(self) -> None:
        """10,000 char string must not cause infinite loop."""
        defn = _minimal_def()
        result = parse_move("A" * 10000, defn)
        assert result is None

    def test_parse_unicode_garbage(self) -> None:
        defn = _minimal_def()
        for garbage in [
            "\U0001f600\U0001f4a9\U0001f525",   # emoji
            "\u200f\u200e\u202b",                 # RTL/LTR marks
            "hello\x00world",                     # null bytes
            "\N{SNOWMAN}\N{PILE OF POO}",         # named unicode
        ]:
            result = parse_move(garbage, defn)
            assert result is None, f"Expected None for {garbage!r}"

    def test_parse_move_with_no_notation(self) -> None:
        """Definition has no notation spec -- parse_move should still work."""
        defn = _minimal_def()
        assert defn.notation is None
        # Coordinate-style input should work if labels exist
        # With no labels, "0,0" should parse as coordinate
        result = parse_move("0,0", defn)
        assert result is not None
        assert result.to_pos == {"col": 0, "row": 0}

    def test_format_move_missing_position(self) -> None:
        """Action with no to_pos should produce a safe fallback string."""
        defn = _minimal_def()
        action = Action(action_type="pass")
        result = format_move(action, defn)
        # Should return str(action) or some safe fallback, not crash
        assert isinstance(result, str)
        assert len(result) > 0


# ===================================================================
# TestHostileComponentTable
# ===================================================================

class TestHostileComponentTable:
    """Edge cases for ComponentId and ComponentTable."""

    def test_component_id_negative(self) -> None:
        with pytest.raises(ValidationError):
            ComponentId(-1)

    def test_component_table_get_out_of_range(self) -> None:
        table = ComponentTable()
        assert table.get(ComponentId(999999)) is None

    def test_insert_empty_string_id(self) -> None:
        """Empty string is a valid string_id."""
        table = ComponentTable()
        cid = table.insert(ComponentData(
            id=ComponentId(0), string_id="", component_type="piece",
        ))
        assert table.get(cid) is not None
        assert table.get(cid).string_id == ""  # type: ignore[union-attr]

    def test_insert_very_long_string_id(self) -> None:
        """10,000 char string_id should work."""
        table = ComponentTable()
        long_id = "x" * 10000
        cid = table.insert(ComponentData(
            id=ComponentId(0), string_id=long_id, component_type="piece",
        ))
        assert table.get(cid) is not None
        assert table.get(cid).string_id == long_id  # type: ignore[union-attr]


# ===================================================================
# TestHostileGameSession
# ===================================================================

class TestHostileGameSession:
    """GameSession with weird player counts and turn state."""

    def test_zero_players(self) -> None:
        """Session with empty player list -- should not crash."""
        data = json.loads(MINIMAL_GAME_JSON)
        data["game"]["players"] = []
        data["turn_order"]["players"] = []
        defn = GameDefinition.from_json(json.dumps(data), validate_schema=False)
        session = GameSession(defn)
        assert len(session.runtime.players) == 0
        assert session.current_player() is None

    def test_many_players(self) -> None:
        """100 players -- should work fine."""
        names = [f"p{i}" for i in range(100)]
        data = json.loads(MINIMAL_GAME_JSON)
        data["game"]["players"] = names
        data["turn_order"]["players"] = names
        defn = GameDefinition.from_json(json.dumps(data), validate_schema=False)
        session = GameSession(defn)
        assert len(session.runtime.players) == 100
        assert session.current_player() == "p0"

    def test_advance_turn_no_players(self) -> None:
        """advance_turn on session with 0 players -- no crash."""
        data = json.loads(MINIMAL_GAME_JSON)
        data["game"]["players"] = []
        data["turn_order"]["players"] = []
        defn = GameDefinition.from_json(json.dumps(data), validate_schema=False)
        session = GameSession(defn)
        # Should not crash or infinite loop
        session.advance_turn()
        assert session.runtime.sequence == 1

    def test_current_player_turn_index_beyond_count(self) -> None:
        """turn_index beyond player count returns None."""
        defn = _minimal_def()
        session = GameSession(defn)
        session.runtime.turn_index = 9999
        assert session.current_player() is None


# ===================================================================
# TestBoundaryValues
# ===================================================================

class TestBoundaryValues:
    """Edge-of-range values that should work or fail gracefully."""

    def test_grid_1x1_all_ops(self) -> None:
        """Single-cell grid: set, get, count all work."""
        zone = runtime_zone_from_definition(_make_grid_zone_def([1, 1]))
        assert isinstance(zone, GridZone)
        assert zone.grid_get(0, 0) is None
        cid = ComponentId(0)
        zone.grid_set(0, 0, cid)
        assert zone.grid_get(0, 0) == cid
        assert zone.count() == 1

    def test_track_length_zero_defaults_to_one(self) -> None:
        """Track with length 0 is falsy, so it defaults to 1 via `or` chain."""
        zone = runtime_zone_from_definition(_make_track_zone_def(0))
        assert isinstance(zone, TrackZone)
        assert len(zone.positions) == 1

    def test_counter_max_value_no_overflow(self) -> None:
        """Counter at a huge value -- Python ints don't overflow."""
        counter = CounterZone(value=2**63)
        counter.value += 1
        assert counter.value == 2**63 + 1

    def test_component_id_zero_works(self) -> None:
        """ComponentId(0) is the first valid ID."""
        cid = ComponentId(0)
        assert cid.value == 0
        table = ComponentTable()
        inserted = table.insert(ComponentData(
            id=cid, string_id="first", component_type="piece",
        ))
        assert table.get(inserted) is not None

    def test_empty_game_definition_minimal(self) -> None:
        """Minimal valid JSON with empty zones/components creates a session."""
        data = {
            "game": {"name": "Empty", "players": ["A", "B"], "information": "perfect"},
            "zones": {},
            "components": {},
            "turn_order": {"type": "alternating", "players": ["A", "B"]},
            "end_conditions": [{"result": "draw", "condition": "always"}],
            "authority": {"server_only": [], "client_verifiable": ["all"]},
        }
        defn = GameDefinition.from_json(json.dumps(data), validate_schema=False)
        session = GameSession(defn)
        assert len(session.runtime.zones) == 0
        assert session.runtime.components.is_empty()
        assert session.current_player() == "A"
