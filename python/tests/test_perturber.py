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
