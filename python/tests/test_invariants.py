"""Tests for engine invariant assertions: invalid ComponentIds, out-of-bounds
grid access, invalid zone dimensions, and other impossible states that should
fail loudly rather than silently corrupt.
"""

import json

import pytest

from baize.error import (
    IllegalActionError,
    ValidationError,
)
from baize.runtime import (
    ComponentData,
    ComponentId,
    ComponentTable,
    CounterZone,
    GameSession,
    GraphZone,
    GridZone,
    SetZone,
    SlotZone,
    StackZone,
    TrackZone,
    runtime_zone_from_definition,
)
from baize.definition import GameDefinition, Zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_JSON = json.dumps(
    {
        "game": {
            "name": "Test",
            "players": ["X", "O"],
            "information": "perfect",
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
            }
        },
        "components": {
            "mark": {"owner": "per_player", "count": "unlimited"}
        },
        "turn_order": {
            "type": "alternating",
            "players": ["X", "O"],
            "actions_per_turn": 1,
            "mandatory": True,
        },
        "end_conditions": [
            {
                "result": "win",
                "player": "current",
                "condition": "three_in_line",
            },
            {"result": "draw", "condition": "board_is_full"},
        ],
        "authority": {
            "server_only": [],
            "client_verifiable": ["all"],
        },
    }
)


def _minimal_def() -> GameDefinition:
    return GameDefinition.from_json(_MINIMAL_JSON)


def _make_component(table: ComponentTable, name: str) -> ComponentId:
    return table.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=name,
            component_type="mark",
            owner="X",
        )
    )


# ---------------------------------------------------------------------------
# ComponentId validity
# ---------------------------------------------------------------------------


class TestComponentIdInvariants:
    def test_negative_component_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ComponentId(-1)

    def test_non_integer_component_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ComponentId("abc")  # type: ignore[arg-type]

    def test_component_table_get_out_of_range_returns_none(self) -> None:
        table = ComponentTable()
        assert table.get(ComponentId(0)) is None
        assert table.get(ComponentId(999)) is None

    def test_component_table_get_with_wrong_type_raises(self) -> None:
        table = ComponentTable()
        with pytest.raises(ValidationError):
            table.get("not_a_cid")  # type: ignore[arg-type]

    def test_component_table_insert_returns_sequential_ids(self) -> None:
        table = ComponentTable()
        c0 = _make_component(table, "a")
        c1 = _make_component(table, "b")
        c2 = _make_component(table, "c")
        assert c0.value == 0
        assert c1.value == 1
        assert c2.value == 2
        assert len(table) == 3

    def test_component_table_get_valid_id(self) -> None:
        table = ComponentTable()
        cid = _make_component(table, "test-0")
        data = table.get(cid)
        assert data is not None
        assert data.string_id == "test-0"


# ---------------------------------------------------------------------------
# GridZone invariants
# ---------------------------------------------------------------------------


class TestGridZoneInvariants:
    def test_negative_dimensions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GridZone(width=-1, height=3, cells=[None] * 3)

    def test_mismatched_cells_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GridZone(width=3, height=3, cells=[None] * 5)

    def test_zero_dimensions_accepted(self) -> None:
        zone = GridZone(width=0, height=0, cells=[])
        assert zone.count() == 0

    def test_get_out_of_bounds_returns_none(self) -> None:
        zone = GridZone(width=3, height=3, cells=[None] * 9)
        assert zone.grid_get(3, 0) is None
        assert zone.grid_get(0, 3) is None
        assert zone.grid_get(100, 100) is None
        assert zone.grid_get(-1, 0) is None

    def test_set_out_of_bounds_is_noop(self) -> None:
        zone = GridZone(width=3, height=3, cells=[None] * 9)
        cid = ComponentId(0)
        result = zone.grid_set(3, 0, cid)
        assert result is None
        assert zone.count() == 0

    def test_push_out_of_bounds_is_noop(self) -> None:
        zone = GridZone(width=2, height=2, cells=[None] * 4)
        zone.grid_push(5, 5, ComponentId(0))
        assert zone.count() == 0

    def test_pop_out_of_bounds_returns_none(self) -> None:
        zone = GridZone(width=2, height=2, cells=[None] * 4)
        assert zone.grid_pop(5, 5) is None

    def test_stack_out_of_bounds_returns_empty(self) -> None:
        zone = GridZone(width=2, height=2, cells=[None] * 4)
        assert zone.grid_stack(5, 5) == []

    def test_place_span_exceeds_boundary(self) -> None:
        zone = GridZone(width=3, height=3, cells=[None] * 9)
        with pytest.raises(IllegalActionError):
            zone.grid_place_span(0, 0, True, 4, ComponentId(0))

    def test_place_span_zero_span_succeeds(self) -> None:
        zone = GridZone(width=5, height=5, cells=[None] * 25)
        result = zone.grid_place_span(0, 0, True, 0, ComponentId(0))
        assert result == []

    def test_empty_valid_cells_mask(self) -> None:
        zone = GridZone(
            width=3,
            height=3,
            cells=[None] * 9,
            valid_cells=set(),
        )
        for row in range(3):
            for col in range(3):
                assert not zone._cell_valid(col, row)
                assert zone.grid_get(col, row) is None


# ---------------------------------------------------------------------------
# TrackZone invariants
# ---------------------------------------------------------------------------


class TestTrackZoneInvariants:
    def test_zero_positions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TrackZone(positions=[])

    def test_single_position_accepted(self) -> None:
        zone = TrackZone(positions=[[]])
        assert zone.count() == 0


# ---------------------------------------------------------------------------
# GraphZone invariants
# ---------------------------------------------------------------------------


class TestGraphZoneInvariants:
    def test_occupants_length_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GraphZone(
                node_names=["A", "B"],
                name_to_index={"A": 0, "B": 1},
                adjacency={0: [], 1: []},
                occupants=[None],  # wrong length
            )

    def test_empty_graph_accepted(self) -> None:
        zone = GraphZone(
            node_names=[],
            name_to_index={},
            adjacency={},
            occupants=[],
        )
        assert zone.count() == 0
        assert zone.graph_get("anything") is None

    def test_graph_unknown_node_returns_none(self) -> None:
        zone = GraphZone(
            node_names=["A"],
            name_to_index={"A": 0},
            adjacency={0: []},
            occupants=[None],
        )
        assert zone.graph_get("Z") is None
        assert zone.graph_set("Z", ComponentId(0)) is None
        assert zone.graph_neighbors("Z") == []


# ---------------------------------------------------------------------------
# Zone creation from definition
# ---------------------------------------------------------------------------


class TestZoneCreationInvariants:
    def test_grid_zone_missing_dimensions(self) -> None:
        zone_def = Zone(zone_type="grid", visibility="public")
        with pytest.raises(ValidationError, match="dimensions"):
            runtime_zone_from_definition(zone_def)

    def test_track_zone_negative_length(self) -> None:
        zone_def = Zone(zone_type="track", visibility="public", length=-1)
        with pytest.raises(ValidationError, match="positive integer"):
            runtime_zone_from_definition(zone_def)

    def test_graph_zone_missing_nodes(self) -> None:
        zone_def = Zone(zone_type="graph", visibility="public")
        with pytest.raises(ValidationError, match="nodes"):
            runtime_zone_from_definition(zone_def)

    def test_graph_zone_unknown_edge_node(self) -> None:
        zone_def = Zone(
            zone_type="graph",
            visibility="public",
            nodes=["A", "B"],
            edges=[["A", "Z"]],
        )
        with pytest.raises(ValidationError, match="unknown node"):
            runtime_zone_from_definition(zone_def)


# ---------------------------------------------------------------------------
# Turn index integrity
# ---------------------------------------------------------------------------


class TestTurnIndexInvariants:
    def test_advance_turn_wraps_correctly(self) -> None:
        session = GameSession(_minimal_def())
        assert session.runtime.turn_index == 0
        session.advance_turn()
        assert session.runtime.turn_index == 1
        session.advance_turn()
        assert session.runtime.turn_index == 0

    def test_current_player_valid_for_all_indices(self) -> None:
        session = GameSession(_minimal_def())
        for _ in range(10):
            player = session.current_player()
            assert player is not None
            assert player in session.runtime.players
            session.advance_turn()


# ---------------------------------------------------------------------------
# Non-grid zone operations
# ---------------------------------------------------------------------------


class TestNonGridZoneOperations:
    def test_stack_pop_on_empty_returns_none(self) -> None:
        zone = StackZone()
        assert zone.stack_pop() is None

    def test_set_remove_nonexistent_returns_false(self) -> None:
        zone = SetZone()
        assert not zone.set_remove(ComponentId(42))

    def test_counter_zone_count_is_zero(self) -> None:
        zone = CounterZone(value=42)
        assert zone.count() == 0

    def test_slot_zone_count_empty_is_zero(self) -> None:
        zone = SlotZone()
        assert zone.count() == 0
        assert zone.component is None


# ---------------------------------------------------------------------------
# apply_action type assertions
# ---------------------------------------------------------------------------


class TestApplyActionAssertions:
    def test_apply_action_rejects_non_session(self) -> None:
        from baize.action import Action
        from baize.transition import apply_action

        action = Action(action_type="pass")
        with pytest.raises(AssertionError, match="GameSession"):
            apply_action("not_a_session", action)  # type: ignore[arg-type]

    def test_apply_action_rejects_non_action(self) -> None:
        from baize.transition import apply_action

        session = GameSession(_minimal_def())
        with pytest.raises(AssertionError, match="Action"):
            apply_action(session, "not_an_action")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# legal_moves type assertion
# ---------------------------------------------------------------------------


class TestLegalMovesAssertions:
    def test_legal_moves_rejects_non_session(self) -> None:
        from baize.moves import legal_moves

        with pytest.raises(AssertionError, match="GameSession"):
            legal_moves("not_a_session")  # type: ignore[arg-type]
