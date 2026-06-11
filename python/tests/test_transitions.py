"""Tests for baize.transition — ported from engine/tests/transitions.rs."""

from __future__ import annotations

import json

from baize.action import Action
from baize.definition import GameDefinition
from baize.error import IllegalActionError
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)
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
        { "result": "win", "player": "current", "condition": "three_in_line" },
        { "result": "draw", "condition": "board_is_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def tic_tac_toe_session() -> GameSession:
    definition = GameDefinition.from_json(TIC_TAC_TOE_JSON)
    return GameSession(definition)


def place_action(col: int, row: int) -> Action:
    return Action(
        action_type="place",
        component_type="mark",
        to_pos={
            "zone": "board",
            "cell": f"{col},{row}",
        },
    )


def move_action(from_col: int, from_row: int, to_col: int, to_row: int) -> Action:
    return Action(
        action_type="move_piece",
        from_pos={
            "zone": "board",
            "cell": f"{from_col},{from_row}",
        },
        to_pos={
            "zone": "board",
            "cell": f"{to_col},{to_row}",
        },
    )


def test_place_marks_alternating() -> None:
    session = tic_tac_toe_session()
    assert session.current_player() == "X"

    events = apply_action(session, place_action(1, 1))
    assert any(e.event_type == "place" for e in events)
    assert any(e.event_type == "turn_advance" for e in events)
    assert session.current_player() == "O"

    # Board should have a mark at (1,1)
    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    assert board.grid_get(1, 1) is not None

    # O places
    _events = apply_action(session, place_action(0, 0))
    assert session.current_player() == "X"
    assert board.grid_get(0, 0) is not None

    # Sequence should advance
    assert session.runtime.sequence == 2
    assert session.runtime.move_count == 2


def test_move_piece_on_grid() -> None:
    chess_json = """{
        "game": { "name": "Test", "players": ["white", "black"], "information": "perfect" },
        "zones": { "board": { "zone_type": "grid", "dimensions": [8, 8], "visibility": "public" } },
        "components": { "rook": { "owner": "per_player", "count": 2 } },
        "turn_order": { "type": "alternating", "players": ["white", "black"] },
        "end_conditions": [{ "result": "win", "condition": "checkmate" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"""
    definition = GameDefinition.from_json(chess_json)
    session = GameSession(definition)

    # Manually place a rook
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="wr1",
            component_type="rook",
            owner="white",
        )
    )
    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    board.grid_set(0, 0, cid)

    # Move rook from (0,0) to (0,5)
    events = apply_action(session, move_action(0, 0, 0, 5))
    assert any(e.event_type == "move_piece" for e in events)

    assert board.grid_get(0, 0) is None
    assert board.grid_get(0, 5) == cid


def test_capture_enemy_piece() -> None:
    chess_json = """{
        "game": { "name": "Test", "players": ["white", "black"], "information": "perfect" },
        "zones": { "board": { "zone_type": "grid", "dimensions": [8, 8], "visibility": "public" } },
        "components": { "rook": { "owner": "per_player", "count": 2 } },
        "turn_order": { "type": "alternating", "players": ["white", "black"] },
        "end_conditions": [{ "result": "win", "condition": "checkmate" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"""
    definition = GameDefinition.from_json(chess_json)
    session = GameSession(definition)

    wr = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="wr1",
            component_type="rook",
            owner="white",
        )
    )
    br = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="br1",
            component_type="rook",
            owner="black",
        )
    )

    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    board.grid_set(0, 0, wr)
    board.grid_set(0, 5, br)

    # White rook captures black rook
    events = apply_action(session, move_action(0, 0, 0, 5))
    assert any(e.event_type == "capture" for e in events)
    assert any(e.event_type == "move_piece" for e in events)

    assert board.grid_get(0, 0) is None
    assert board.grid_get(0, 5) == wr  # white rook is now there


def test_hash_chain_integrity() -> None:
    session = tic_tac_toe_session()

    apply_action(session, place_action(1, 1))
    assert len(session.runtime.history_hashes) == 1

    apply_action(session, place_action(0, 0))
    assert len(session.runtime.history_hashes) == 2

    # Hashes should be different
    assert session.runtime.history_hashes[0] != session.runtime.history_hashes[1]


def test_resign_ends_game() -> None:
    session = tic_tac_toe_session()

    resign = Action(action_type="resign")

    events = apply_action(session, resign)
    assert any(e.event_type == "resign" for e in events)
    assert session.runtime.status == "finished"


def test_cannot_act_after_game_over() -> None:
    session = tic_tac_toe_session()
    session.runtime.status = "finished"

    try:
        apply_action(session, place_action(0, 0))
        assert False, "should have raised IllegalActionError"
    except IllegalActionError:
        pass


def test_events_are_jsonl_serializable() -> None:
    session = tic_tac_toe_session()
    events = apply_action(session, place_action(1, 1))

    for event in events:
        json_line = event.to_json_line()
        assert json_line
        # Each event serializes to a single JSON line
        assert "\n" not in json_line
        # Should be valid JSON
        parsed = json.loads(json_line)
        assert isinstance(parsed, dict)


BATTLESHIP_JSON = """{
    "game": { "name": "Battleship", "players": ["A", "B"], "information": "imperfect" },
    "zones": {
        "ocean": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
        "target": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
        "ships_remaining": { "zone_type": "counter", "per_player": true, "visibility": "public" }
    },
    "components": {
        "ship": {
            "owner": "per_player",
            "types": {
                "carrier": { "span": 5 },
                "destroyer": { "span": 2 }
            }
        },
        "peg": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["A", "B"] },
    "end_conditions": [{ "result": "win", "condition": "false" }],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def battleship_session() -> GameSession:
    definition = GameDefinition.from_json(BATTLESHIP_JSON)
    session = GameSession(definition)
    for player in session.runtime.players.values():
        player.counters["ships_remaining"] = 2
    return session


def place_ship_action(
    comp_type: str, col: int, row: int, orientation: str
) -> Action:
    return Action(
        action_type="place_ship",
        component_type=comp_type,
        to_pos={"zone": "ocean", "cell": f"{col},{row}"},
        orientation=orientation,
    )


def fire_action(col: int, row: int) -> Action:
    return Action(
        action_type="fire",
        to_pos={"zone": "ocean", "cell": f"{col},{row}"},
        zone="target",
    )


def test_place_ship_horizontal() -> None:
    session = battleship_session()

    events = apply_action(
        session, place_ship_action("carrier", 0, 0, "horizontal")
    )
    assert any(e.event_type == "place" for e in events)

    ocean = session.runtime.players["A"].zones["ocean"]
    assert isinstance(ocean, GridZone)
    cid = ocean.grid_get(0, 0)
    assert cid is not None
    for col in range(5):
        assert ocean.grid_get(col, 0) == cid
    assert ocean.grid_get(5, 0) is None

    comp = session.runtime.components.get(cid)
    assert comp is not None
    assert len(comp.span_cells) == 5
    assert comp.component_type == "carrier"


def test_place_ship_vertical() -> None:
    session = battleship_session()

    events = apply_action(
        session, place_ship_action("destroyer", 9, 8, "vertical")
    )
    assert any(e.event_type == "place" for e in events)

    ocean = session.runtime.players["A"].zones["ocean"]
    assert isinstance(ocean, GridZone)
    cid = ocean.grid_get(9, 8)
    assert cid is not None
    assert ocean.grid_get(9, 9) == cid
    assert ocean.grid_get(9, 7) is None


def test_place_ship_overlap_rejected() -> None:
    import pytest

    session = battleship_session()

    apply_action(
        session, place_ship_action("carrier", 0, 0, "horizontal")
    )
    session.runtime.turn_index = 0

    with pytest.raises(IllegalActionError):
        apply_action(
            session, place_ship_action("destroyer", 3, 0, "horizontal")
        )


def test_place_ship_out_of_bounds_rejected() -> None:
    import pytest

    session = battleship_session()

    with pytest.raises(IllegalActionError):
        apply_action(
            session, place_ship_action("carrier", 8, 0, "horizontal")
        )


def test_fire_miss() -> None:
    session = battleship_session()
    session.runtime.status = "in_progress"

    # B places destroyer at (5,5)
    session.runtime.turn_index = 1
    apply_action(session, place_ship_action("destroyer", 5, 5, "horizontal"))

    # A fires at (0,0) — miss
    session.runtime.turn_index = 0
    events = apply_action(session, fire_action(0, 0))
    assert any(e.event_type == "fire" for e in events)
    assert any(e.event_type == "miss" for e in events)
    assert not any(e.event_type == "hit" for e in events)

    target = session.runtime.players["A"].zones["target"]
    assert isinstance(target, GridZone)
    peg_cid = target.grid_get(0, 0)
    assert peg_cid is not None
    peg = session.runtime.components.get(peg_cid)
    assert peg is not None
    assert peg.component_type == "miss"


def test_fire_hit() -> None:
    session = battleship_session()
    session.runtime.status = "in_progress"

    # B places destroyer at (5,5)
    session.runtime.turn_index = 1
    apply_action(session, place_ship_action("destroyer", 5, 5, "horizontal"))

    # A fires at (5,5) — hit!
    session.runtime.turn_index = 0
    events = apply_action(session, fire_action(5, 5))
    assert any(e.event_type == "hit" for e in events)
    assert not any(e.event_type == "miss" for e in events)

    target = session.runtime.players["A"].zones["target"]
    assert isinstance(target, GridZone)
    peg_cid = target.grid_get(5, 5)
    assert peg_cid is not None
    peg = session.runtime.components.get(peg_cid)
    assert peg is not None
    assert peg.component_type == "hit"


def test_fire_sunk() -> None:
    session = battleship_session()
    session.runtime.status = "in_progress"

    # B places destroyer (span 2) at (5,5) horizontal
    session.runtime.turn_index = 1
    apply_action(session, place_ship_action("destroyer", 5, 5, "horizontal"))

    # A fires at (5,5) — first hit, not sunk
    session.runtime.turn_index = 0
    events1 = apply_action(session, fire_action(5, 5))
    assert any(e.event_type == "hit" for e in events1)
    assert not any(e.event_type == "sunk" for e in events1)

    # A fires at (6,5) — second hit, sunk!
    session.runtime.turn_index = 0
    events2 = apply_action(session, fire_action(6, 5))
    assert any(e.event_type == "hit" for e in events2)
    assert any(e.event_type == "sunk" for e in events2)

    # B's ships_remaining decremented
    assert session.runtime.players["B"].counters["ships_remaining"] == 1


def test_fire_duplicate_rejected() -> None:
    import pytest

    session = battleship_session()
    session.runtime.status = "in_progress"

    session.runtime.turn_index = 0
    apply_action(session, fire_action(0, 0))

    session.runtime.turn_index = 0
    with pytest.raises(IllegalActionError):
        apply_action(session, fire_action(0, 0))
