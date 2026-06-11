"""Tests for movement primitive transitions: remove, swap, promote."""

import json

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import ComponentData, ComponentId, GameSession, GridZone


def _chess_like_session() -> GameSession:
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
    definition = GameDefinition.from_json(json.dumps(raw))
    session = GameSession(definition)
    session.runtime.status = "in_progress"
    return session


def _place_component(
    session: GameSession, comp_type: str, owner: str, col: int, row: int
) -> str:
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


class TestRemove:
    def test_remove_piece_from_grid(self) -> None:
        from baize.transition import apply_action

        session = _chess_like_session()
        pawn_id = _place_component(session, "pawn", "white", 3, 1)

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.grid_get(3, 1) is not None

        action = Action(action_type="remove", component_id=pawn_id)
        events = apply_action(session, action)

        assert zone.grid_get(3, 1) is None
        assert any(e.event_type == "remove" for e in events)

    def test_remove_nonexistent_fails(self) -> None:
        from baize.transition import apply_action

        session = _chess_like_session()
        action = Action(action_type="remove", component_id="nonexistent")

        with pytest.raises(Exception):
            apply_action(session, action)


class TestSwap:
    def test_swap_two_pieces(self) -> None:
        from baize.transition import apply_action

        session = _chess_like_session()
        pawn_id = _place_component(session, "pawn", "white", 0, 0)
        queen_id = _place_component(session, "queen", "white", 1, 0)

        action = Action(
            action_type="swap",
            component_id=pawn_id,
            swap_with=queen_id,
        )
        events = apply_action(session, action)

        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        at_0_0 = zone.grid_get(0, 0)
        at_1_0 = zone.grid_get(1, 0)
        assert at_0_0 is not None
        assert at_1_0 is not None
        assert session.runtime.components.get(at_0_0).string_id == queen_id  # type: ignore[union-attr]
        assert session.runtime.components.get(at_1_0).string_id == pawn_id  # type: ignore[union-attr]
        assert any(e.event_type == "swap" for e in events)


class TestPromote:
    def test_promote_changes_type(self) -> None:
        from baize.transition import apply_action

        session = _chess_like_session()
        pawn_id = _place_component(session, "pawn", "white", 4, 7)

        action = Action(
            action_type="promote",
            component_id=pawn_id,
            promote_to="queen",
        )
        events = apply_action(session, action)

        comp = None
        for c in session.runtime.components:
            if c.string_id == pawn_id:
                comp = c
                break
        assert comp is not None
        assert comp.component_type == "queen"
        assert any(e.event_type == "promote" for e in events)
