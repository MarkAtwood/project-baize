"""Tests for baize.runtime — ported from engine/tests/runtime_state.rs."""

from __future__ import annotations

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    ComponentTable,
    GameSession,
    GridZone,
    SetZone,
    StackZone,
)


TIC_TAC_TOE_JSON = """{
    "game": { "name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [
        { "result": "win", "player": "current", "condition": "three_in_line" },
        { "result": "draw", "condition": "board_is_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def tic_tac_toe_def() -> GameDefinition:
    return GameDefinition.from_json(TIC_TAC_TOE_JSON)


def test_session_init() -> None:
    definition = tic_tac_toe_def()
    session = GameSession(definition)

    assert session.runtime.status == "setup"
    assert len(session.runtime.players) == 2
    assert "X" in session.runtime.players
    assert "O" in session.runtime.players
    assert len(session.runtime.zones) == 1
    assert "board" in session.runtime.zones
    assert session.is_perfect_information()


def test_current_player() -> None:
    definition = tic_tac_toe_def()
    session = GameSession(definition)

    assert session.current_player() == "X"
    session.advance_turn()
    assert session.current_player() == "O"
    session.advance_turn()
    assert session.current_player() == "X"


def test_grid_operations() -> None:
    definition = tic_tac_toe_def()
    session = GameSession(definition)

    # Place a component at (1, 1) -- center
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="mark-x-0",
            component_type="mark",
            owner="X",
        )
    )

    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    assert board.grid_get(1, 1) is None
    board.grid_set(1, 1, cid)
    assert board.grid_get(1, 1) == cid
    assert board.count() == 1

    # Out of bounds returns None
    assert board.grid_get(5, 5) is None


def test_stack_operations() -> None:
    zone = StackZone()

    c1 = ComponentId(0)
    c2 = ComponentId(1)
    c3 = ComponentId(2)

    zone.stack_push(c1)
    zone.stack_push(c2)
    zone.stack_push(c3)
    assert zone.count() == 3

    assert zone.stack_pop() == c3
    assert zone.stack_pop() == c2
    assert zone.count() == 1


def test_set_operations() -> None:
    zone = SetZone()

    c1 = ComponentId(0)
    c2 = ComponentId(1)

    zone.set_add(c1)
    zone.set_add(c2)
    assert zone.count() == 2

    assert zone.set_remove(c1) is True
    assert zone.count() == 1
    assert zone.set_remove(c1) is False  # already removed


def test_wire_round_trip() -> None:
    definition = tic_tac_toe_def()
    session = GameSession(definition)
    session.runtime.status = "in_progress"

    # Place a mark
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="mark-x-0",
            component_type="mark",
            owner="X",
        )
    )
    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    board.grid_set(1, 1, cid)

    # Convert to wire format and verify
    wire = session.to_wire_state()
    assert wire.turn == "X"
    assert wire.status == "in_progress"

    # Serialize and re-parse
    json_str = wire.to_json()
    from baize.state import GameState

    parsed = GameState.from_json(json_str)
    assert parsed.turn == "X"


def test_state_hashing() -> None:
    definition = tic_tac_toe_def()
    session = GameSession(definition)

    h1 = session.compute_state_hash()
    h2 = session.compute_state_hash()
    assert h1 == h2  # deterministic

    # Different state should produce different hash
    definition2 = tic_tac_toe_def()
    session2 = GameSession(definition2)
    session2.advance_turn()
    h3 = session2.compute_state_hash()
    assert h1 != h3


def test_per_player_zones() -> None:
    card_game_json = """{
        "game": { "name": "Card Game", "players": { "min": 2, "max": 4 }, "information": "imperfect" },
        "zones": {
            "deck": { "zone_type": "ordered_stack", "capacity": 52, "visibility": "hidden" },
            "hand": { "zone_type": "set", "per_player": true, "capacity": 5, "visibility": { "private": "owner" } }
        },
        "components": {
            "card": { "count": 52 }
        },
        "turn_order": { "type": "round_robin" },
        "end_conditions": [{ "result": "win", "condition": "hand_empty" }],
        "authority": { "server_only": ["deal"], "client_verifiable": ["play_card"] }
    }"""
    definition = GameDefinition.from_json(card_game_json)
    session = GameSession(definition)

    # Shared zone
    assert "deck" in session.runtime.zones
    # Per-player zones are on the player, not on the top-level zones
    assert "hand" not in session.runtime.zones

    # Each player has their own hand
    for _name, player in session.runtime.players.items():
        assert "hand" in player.zones
