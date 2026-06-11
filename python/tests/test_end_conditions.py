"""Tests for end condition evaluation."""

from __future__ import annotations

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession
from baize.transition import apply_action


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
        { "result": "win", "player": "current", "condition": "three_in_line", "name": "three_in_a_row" },
        { "result": "draw", "condition": "board_is_full", "name": "board_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def _session() -> GameSession:
    return GameSession(GameDefinition.from_json(TIC_TAC_TOE_JSON))


def _place(col: int, row: int) -> Action:
    return Action(
        action_type="place",
        component_type="mark",
        to_pos={"zone": "board", "cell": f"{col},{row}"},
    )


def test_x_wins_top_row() -> None:
    session = _session()
    # X(0,0) O(0,1) X(1,0) O(1,1) X(2,0)
    apply_action(session, _place(0, 0))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(1, 0))
    apply_action(session, _place(1, 1))
    events = apply_action(session, _place(2, 0))

    assert session.runtime.status == "finished"
    assert any(e.event_type == "game_end" for e in events)
    assert not any(e.event_type == "turn_advance" for e in events)

    result = session.runtime.result
    assert result is not None
    assert result.outcome == "win"
    assert result.winner == "X"
    assert result.condition == "three_in_a_row"


def test_o_wins_diagonal() -> None:
    session = _session()
    # X(0,0) O(1,1) X(0,1) O(2,0) X(2,2) O(0,2) — O wins anti-diagonal
    apply_action(session, _place(0, 0))
    apply_action(session, _place(1, 1))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(2, 0))
    apply_action(session, _place(2, 2))
    events = apply_action(session, _place(0, 2))

    assert session.runtime.status == "finished"
    result = session.runtime.result
    assert result is not None
    assert result.outcome == "win"
    assert result.winner == "O"
    assert any(e.event_type == "game_end" for e in events)


def test_draw_when_board_full() -> None:
    session = _session()
    # X O X
    # X X O
    # O X O
    apply_action(session, _place(0, 0))  # X
    apply_action(session, _place(1, 0))  # O
    apply_action(session, _place(2, 0))  # X
    apply_action(session, _place(2, 1))  # O
    apply_action(session, _place(0, 1))  # X
    apply_action(session, _place(0, 2))  # O
    apply_action(session, _place(1, 1))  # X
    apply_action(session, _place(2, 2))  # O
    events = apply_action(session, _place(1, 2))  # X

    assert session.runtime.status == "finished"
    result = session.runtime.result
    assert result is not None
    assert result.outcome == "draw"
    assert result.winner is None
    assert result.condition == "board_full"
    assert any(e.event_type == "game_end" for e in events)


def test_no_moves_after_win() -> None:
    session = _session()
    apply_action(session, _place(0, 0))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(1, 0))
    apply_action(session, _place(1, 1))
    apply_action(session, _place(2, 0))

    try:
        apply_action(session, _place(2, 2))
        assert False, "should have raised"
    except Exception:
        pass


def test_win_checked_before_turn_advance() -> None:
    session = _session()
    apply_action(session, _place(0, 0))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(1, 0))
    apply_action(session, _place(1, 1))
    apply_action(session, _place(2, 0))

    # Turn should NOT have advanced past X
    assert session.runtime.turn_index == 0
    assert session.current_player() == "X"


def test_game_end_event_has_state_hash() -> None:
    session = _session()
    apply_action(session, _place(0, 0))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(1, 0))
    apply_action(session, _place(1, 1))
    events = apply_action(session, _place(2, 0))

    game_end = next(e for e in events if e.event_type == "game_end")
    assert game_end.state_hash


def test_wire_state_includes_result() -> None:
    session = _session()
    apply_action(session, _place(0, 0))
    apply_action(session, _place(0, 1))
    apply_action(session, _place(1, 0))
    apply_action(session, _place(1, 1))
    apply_action(session, _place(2, 0))

    wire = session.to_wire_state()
    assert wire.result is not None
    assert wire.result.outcome == "win"
    assert wire.result.winner == "X"
