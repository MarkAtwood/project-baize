"""Tests for baize.moves — ported from engine/tests/move_generation.rs."""

from __future__ import annotations

from baize.definition import GameDefinition
from baize.moves import legal_moves
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)


SIMPLE_CHESS_JSON = """{
    "game": { "name": "Simple Chess", "players": ["white", "black"], "information": "perfect" },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [8, 8],
            "visibility": "public"
        }
    },
    "components": {
        "king": {
            "owner": "per_player",
            "count": 1,
            "movement": [
                { "primitive": "step", "direction": "adjacent" }
            ]
        },
        "rook": {
            "owner": "per_player",
            "count": 2,
            "movement": [
                { "primitive": "slide", "direction": "orthogonal" }
            ]
        },
        "knight": {
            "owner": "per_player",
            "count": 2,
            "movement": [
                { "primitive": "leap", "dx": 1, "dy": 2 }
            ]
        },
        "bishop": {
            "owner": "per_player",
            "count": 2,
            "movement": [
                { "primitive": "slide", "direction": "diagonal" }
            ]
        }
    },
    "turn_order": { "type": "alternating", "players": ["white", "black"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [{ "result": "win", "condition": "checkmate" }],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def simple_chess_def() -> GameDefinition:
    return GameDefinition.from_json(SIMPLE_CHESS_JSON)


def place_piece(
    session: GameSession,
    name: str,
    comp_type: str,
    owner: str,
    col: int,
    row: int,
) -> ComponentId:
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=name,
            component_type=comp_type,
            owner=owner,
        )
    )
    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    board.grid_set(col, row, cid)
    return cid


def test_king_center_of_empty_board() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wk", "king", "white", 4, 4)

    moves = legal_moves(session)
    # King at (4,4) on an empty board: 8 adjacent squares
    assert len(moves) == 8


def test_king_corner() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wk", "king", "white", 0, 0)

    moves = legal_moves(session)
    # King at (0,0): 3 adjacent squares
    assert len(moves) == 3


def test_rook_empty_board() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wr", "rook", "white", 4, 4)

    moves = legal_moves(session)
    # Rook at (4,4) on 8x8: 4+3+4+3 = 14
    assert len(moves) == 14


def test_rook_blocked_by_friendly() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wr", "rook", "white", 0, 0)
    place_piece(session, "wk", "king", "white", 0, 2)  # blocks vertical

    moves_all = legal_moves(session)
    # Filter to rook moves only
    rook_moves = [
        m
        for m in moves_all
        if (
            session.runtime.components.get(m.component_id) is not None
            and session.runtime.components.get(m.component_id).component_type == "rook"  # type: ignore[union-attr]
        )
    ]
    # Rook at (0,0): right 7, up 1 (blocked at row 2 by friendly king)
    # left 0, down 0 => 7 + 1 = 8
    assert len(rook_moves) == 8


def test_rook_can_capture_enemy() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wr", "rook", "white", 0, 0)
    place_piece(session, "bk", "king", "black", 0, 3)  # enemy on same file

    moves_all = legal_moves(session)
    rook_moves = [
        m
        for m in moves_all
        if (
            session.runtime.components.get(m.component_id) is not None
            and session.runtime.components.get(m.component_id).component_type == "rook"  # type: ignore[union-attr]
        )
    ]
    # Rook at (0,0): right 7, up to row 3 (capture enemy) = 3
    # Total: 7 + 3 = 10
    assert len(rook_moves) == 10


def test_knight_moves() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wn", "knight", "white", 4, 4)

    moves = legal_moves(session)
    # Knight at (4,4) on 8x8: all 8 L-shapes are in bounds
    assert len(moves) == 8


def test_knight_corner() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wn", "knight", "white", 0, 0)

    moves = legal_moves(session)
    # Knight at (0,0): only (1,2) and (2,1) are in bounds
    assert len(moves) == 2


def test_bishop_empty_board() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wb", "bishop", "white", 4, 4)

    moves = legal_moves(session)
    # Bishop at (4,4) on 8x8:
    # NE(+1,+1): (5,5),(6,6),(7,7) = 3
    # NW(-1,+1): (3,5),(2,6),(1,7) = 3
    # SE(+1,-1): (5,3),(6,2),(7,1) = 3
    # SW(-1,-1): (3,3),(2,2),(1,1),(0,0) = 4
    # Total: 13
    assert len(moves) == 13


def test_only_current_player_moves() -> None:
    definition = simple_chess_def()
    session = GameSession(definition)
    place_piece(session, "wk", "king", "white", 4, 4)
    place_piece(session, "bk", "king", "black", 0, 0)

    # White's turn
    moves = legal_moves(session)
    # Only white king should move (8 moves)
    assert len(moves) == 8

    # Advance to black's turn
    session.advance_turn()
    moves = legal_moves(session)
    # Only black king should move (3 moves from corner)
    assert len(moves) == 3
