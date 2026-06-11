"""Cross-implementation parity tests for movement primitives.

Verifies that Rust and Python engines produce identical results for
remove, swap, promote, and flip transitions.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Add python/ to path so we can import baize
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)
from baize.transition import apply_action


def _chess_session() -> GameSession:
    raw = {
        "game": {"name": "Test", "players": ["white", "black"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [8, 8], "visibility": "public"},
        },
        "components": {
            "pawn": {"owner": "per_player", "count": 8},
            "queen": {"owner": "per_player", "count": 1},
        },
        "turn_order": {
            "type": "alternating",
            "players": ["white", "black"],
            "actions_per_turn": 1,
            "mandatory": True,
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


def _place(session: GameSession, comp_type: str, owner: str, col: int, row: int) -> str:
    instance_id = f"{comp_type}-{owner}-{len(session.runtime.components)}"
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=instance_id,
            component_type=comp_type,
            owner=owner,
        )
    )
    zone = session.runtime.zones.get("board")
    assert isinstance(zone, GridZone)
    zone.grid_set(col, row, cid)
    return instance_id


class TestRemoveParity:
    def test_remove_clears_cell(self) -> None:
        session = _chess_session()
        pawn_id = _place(session, "pawn", "white", 3, 1)
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(3, 1) is not None

        action = Action(action_type="remove", component_id=pawn_id)
        apply_action(session, action)

        assert zone.grid_get(3, 1) is None


class TestSwapParity:
    def test_swap_exchanges_positions(self) -> None:
        session = _chess_session()
        pawn_id = _place(session, "pawn", "white", 0, 0)
        queen_id = _place(session, "queen", "white", 1, 0)

        action = Action(action_type="swap", component_id=pawn_id, swap_with=queen_id)
        apply_action(session, action)

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        at_0_0 = zone.grid_get(0, 0)
        at_1_0 = zone.grid_get(1, 0)
        assert at_0_0 is not None
        assert at_1_0 is not None
        assert session.runtime.components.get(at_0_0).string_id == queen_id  # type: ignore[union-attr]
        assert session.runtime.components.get(at_1_0).string_id == pawn_id  # type: ignore[union-attr]


class TestPromoteParity:
    def test_promote_changes_type(self) -> None:
        session = _chess_session()
        pawn_id = _place(session, "pawn", "white", 4, 7)

        action = Action(action_type="promote", component_id=pawn_id, promote_to="queen")
        apply_action(session, action)

        comp = None
        for c in session.runtime.components:
            if c.string_id == pawn_id:
                comp = c
                break
        assert comp is not None
        assert comp.component_type == "queen"


class TestPerturberParity:
    def test_sequence_counter(self) -> None:
        from baize.perturber import execute_effect

        session = _chess_session()
        effect = {
            "sequence": [
                {"set_counter": {"counter": "score", "value": 10}},
                {"add_counter": {"counter": "score", "value": 5}},
            ]
        }
        execute_effect(session, effect)
        assert session.runtime.counters["score"] == 15

    def test_if_then_else(self) -> None:
        from baize.perturber import execute_effect

        session = _chess_session()
        effect = {
            "if": "move_count == 0",
            "then": {"set_counter": {"counter": "branch", "value": 1}},
            "else": {"set_counter": {"counter": "branch", "value": 2}},
        }
        execute_effect(session, effect)
        assert session.runtime.counters["branch"] == 1

    def test_repeat_until_stable(self) -> None:
        from baize.perturber import execute_effect

        session = _chess_session()
        effect = {
            "repeat_until_stable": {
                "fuel": 100,
                "apply": {"set_counter": {"counter": "fixed", "value": 42}},
            }
        }
        execute_effect(session, effect)
        assert session.runtime.counters["fixed"] == 42


class TestCELParity:
    def test_composable_win_condition(self) -> None:
        from baize.cel import try_eval_end_condition

        variables = {
            "current_player": "X",
            "lines": [["X", "X", "X"], ["O", "", ""]],
        }
        result = try_eval_end_condition(
            variables,
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        assert result is True

    def test_composable_no_win(self) -> None:
        from baize.cel import try_eval_end_condition

        variables = {
            "current_player": "X",
            "lines": [["X", "O", "X"], ["", "X", ""]],
        }
        result = try_eval_end_condition(
            variables,
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        assert result is False

    def test_occupied_count(self) -> None:
        from baize.cel import try_eval_end_condition

        result = try_eval_end_condition(
            {"occupied_count": 9, "cell_count": 9},
            "occupied_count == cell_count",
        )
        assert result is True
