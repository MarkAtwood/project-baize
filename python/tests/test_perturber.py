"""Tests for the structured perturber language."""

import json
from typing import Any

from baize.definition import GameDefinition
from baize.perturber import execute_effect
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)


def _test_session() -> GameSession:
    raw = {
        "game": {"name": "Test", "players": ["A", "B"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"},
        },
        "components": {"piece": {"owner": "per_player"}},
        "turn_order": {
            "type": "alternating", "players": ["A", "B"],
            "actions_per_turn": 1, "mandatory": True,
        },
        "end_conditions": [
            {"result": "draw", "condition": "all_cells_occupied"},
        ],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    defn = GameDefinition.from_json(json.dumps(raw))
    session = GameSession(defn)
    session.runtime.status = "in_progress"
    return session


def _place_piece(
    session: GameSession, name: str, owner: str, col: int, row: int
) -> None:
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=name,
            component_type="piece",
            owner=owner,
        )
    )
    zone = session.runtime.zones.get("board")
    assert isinstance(zone, GridZone)
    zone.grid_set(col, row, cid)


class TestSequence:
    def test_sequence_of_counters(self) -> None:
        session = _test_session()
        effect = {
            "sequence": [
                {"set_counter": {"counter": "score", "value": 10}},
                {"add_counter": {"counter": "score", "value": 5}},
            ]
        }
        execute_effect(session, effect)
        assert session.runtime.counters["score"] == 15


class TestIfThenElse:
    def test_condition_true(self) -> None:
        session = _test_session()
        effect = {
            "if": "move_count == 0",
            "then": {"set_counter": {"counter": "branch", "value": 1}},
            "else": {"set_counter": {"counter": "branch", "value": 2}},
        }
        execute_effect(session, effect)
        assert session.runtime.counters["branch"] == 1

    def test_condition_false(self) -> None:
        session = _test_session()
        session.runtime.move_count = 5
        effect = {
            "if": "move_count == 0",
            "then": {"set_counter": {"counter": "branch", "value": 1}},
            "else": {"set_counter": {"counter": "branch", "value": 2}},
        }
        execute_effect(session, effect)
        assert session.runtime.counters["branch"] == 2


class TestRepeat:
    def test_repeat_n(self) -> None:
        session = _test_session()
        effect = {
            "repeat": 3,
            "body": {"add_counter": {"counter": "ticks", "value": 1}},
        }
        execute_effect(session, effect)
        assert session.runtime.counters["ticks"] == 3


class TestRepeatUntilStable:
    def test_stops_when_stable(self) -> None:
        session = _test_session()
        effect = {
            "repeat_until_stable": {
                "fuel": 100,
                "apply": {"set_counter": {"counter": "fixed", "value": 42}},
            }
        }
        execute_effect(session, effect)
        assert session.runtime.counters["fixed"] == 42


class TestRemove:
    def test_remove_piece(self) -> None:
        session = _test_session()
        _place_piece(session, "target", "A", 1, 1)
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(1, 1) is not None

        execute_effect(session, {"remove": {"target": "target"}})
        assert zone.grid_get(1, 1) is None


def _multi_zone_session() -> GameSession:
    raw = {
        "game": {"name": "Test", "players": ["A", "B"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"},
            "front": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"},
            "right": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"},
        },
        "components": {"piece": {"owner": "per_player"}},
        "turn_order": {
            "type": "alternating", "players": ["A", "B"],
            "actions_per_turn": 1, "mandatory": True,
        },
        "end_conditions": [
            {"result": "draw", "condition": "all_cells_occupied"},
        ],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    defn = GameDefinition.from_json(json.dumps(raw))
    session = GameSession(defn)
    session.runtime.status = "in_progress"
    return session


def _place_piece_in(
    session: GameSession, name: str, owner: str, zone_name: str, col: int, row: int
) -> ComponentId:
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=name,
            component_type="piece",
            owner=owner,
        )
    )
    zone = session.runtime.zones[zone_name]
    assert isinstance(zone, GridZone)
    zone.grid_set(col, row, cid)
    return cid


class TestCycle:
    def test_same_zone_3_elements(self) -> None:
        session = _test_session()
        a = _place_piece_in(session, "a", "A", "board", 0, 0)
        b = _place_piece_in(session, "b", "A", "board", 1, 0)
        c = _place_piece_in(session, "c", "A", "board", 2, 0)

        execute_effect(session, {"cycle": [
            {"zone": "board", "pos": "0,0"},
            {"zone": "board", "pos": "1,0"},
            {"zone": "board", "pos": "2,0"},
        ]})

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(0, 0) == c
        assert zone.grid_get(1, 0) == a
        assert zone.grid_get(2, 0) == b

    def test_cross_zone(self) -> None:
        session = _multi_zone_session()
        a = _place_piece_in(session, "a", "A", "board", 0, 0)
        b = _place_piece_in(session, "b", "A", "front", 0, 0)
        c = _place_piece_in(session, "c", "A", "right", 0, 0)

        execute_effect(session, {"cycle": [
            {"zone": "board", "pos": "0,0"},
            {"zone": "front", "pos": "0,0"},
            {"zone": "right", "pos": "0,0"},
        ]})

        assert session.runtime.zones["board"].grid_get(0, 0) == c
        assert session.runtime.zones["front"].grid_get(0, 0) == a
        assert session.runtime.zones["right"].grid_get(0, 0) == b

    def test_empty_cell_acts_as_transfer(self) -> None:
        session = _test_session()
        a = _place_piece_in(session, "a", "A", "board", 0, 0)

        execute_effect(session, {"cycle": [
            {"zone": "board", "pos": "0,0"},
            {"zone": "board", "pos": "1,0"},
        ]})

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(0, 0) is None
        assert zone.grid_get(1, 0) == a

    def test_4x_returns_to_start(self) -> None:
        session = _test_session()
        a = _place_piece_in(session, "a", "A", "board", 0, 0)
        b = _place_piece_in(session, "b", "A", "board", 1, 0)
        c = _place_piece_in(session, "c", "A", "board", 2, 0)
        d = _place_piece_in(session, "d", "A", "board", 0, 1)

        effect = {"cycle": [
            {"zone": "board", "pos": "0,0"},
            {"zone": "board", "pos": "1,0"},
            {"zone": "board", "pos": "2,0"},
            {"zone": "board", "pos": "0,1"},
        ]}
        for _ in range(4):
            execute_effect(session, effect)

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(0, 0) == a
        assert zone.grid_get(1, 0) == b
        assert zone.grid_get(2, 0) == c
        assert zone.grid_get(0, 1) == d

    def test_single_element_is_noop(self) -> None:
        session = _test_session()
        a = _place_piece_in(session, "a", "A", "board", 0, 0)

        execute_effect(session, {"cycle": [{"zone": "board", "pos": "0,0"}]})

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(0, 0) == a

    def test_unknown_zone_errors(self) -> None:
        import pytest
        session = _test_session()
        with pytest.raises(ValueError, match="unknown zone"):
            execute_effect(session, {"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "nonexistent", "pos": "0,0"},
            ]})
