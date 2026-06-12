"""Tests for Shogi (Japanese Chess): setup, piece movement, captures, drops, promotion.

Foundation layer covering:
  - Standard position setup (40 pieces on 9x9 board)
  - Pseudo-legal move generation for all 8 piece types
  - Promoted piece movement (dragon king, dragon horse, gold-move promotions)
  - Capture mechanics: captured pieces go to hand, switch sides
  - Drop mechanics with restrictions (nifu, last-rank, no drop checkmate)
  - Promotion zone logic (last 3 ranks, mandatory vs optional)
  - Check and checkmate detection
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
    SetZone,
)
from baize.state import GameResult


# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "shogi.json"


def _load_shogi() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Direction vectors (from sente's perspective: sente moves "up" = +row)
# ---------------------------------------------------------------------------

ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ADJACENT = ORTHO + DIAG


def _opponent_of(player: str) -> str:
    return "gote" if player == "sente" else "sente"


def _forward_dir(player: str) -> int:
    """Sente moves upward (+row), gote moves downward (-row)."""
    return 1 if player == "sente" else -1


# Gold general movement: forward, orthogonal, forward-diagonal (6 of 8 directions).
# Excludes backward-diagonal. Per-player because "forward" is relative.
def _gold_directions(player: str) -> list[tuple[int, int]]:
    fwd = _forward_dir(player)
    return [
        (0, fwd),        # forward
        (1, 0), (-1, 0), # left/right
        (0, -fwd),       # backward
        (1, fwd), (-1, fwd),  # forward-diagonal
    ]


def _silver_directions(player: str) -> list[tuple[int, int]]:
    """Silver general: forward + all 4 diagonals (5 directions)."""
    fwd = _forward_dir(player)
    return [
        (0, fwd),                  # forward
        (1, 1), (1, -1),          # diagonals
        (-1, 1), (-1, -1),
    ]


def _knight_destinations(player: str) -> list[tuple[int, int]]:
    """Shogi knight: 2 forward + 1 to the side (forward only, 2 destinations)."""
    fwd = _forward_dir(player)
    return [(1, 2 * fwd), (-1, 2 * fwd)]


# ---------------------------------------------------------------------------
# ShogiGame helper
# ---------------------------------------------------------------------------

class ShogiGame:
    """Shogi game driver for testing."""

    BOARD_SIZE = 9

    # Promoted types that move as gold
    GOLD_MOVERS = {"gold", "promoted_silver", "promoted_knight", "promoted_lance", "tokin"}

    # Map of piece type -> promoted type
    PROMOTION_MAP = {
        "rook": "dragon_king",
        "bishop": "dragon_horse",
        "silver": "promoted_silver",
        "knight": "promoted_knight",
        "lance": "promoted_lance",
        "pawn": "tokin",
    }

    # Reverse: promoted -> unpromoted
    DEMOTION_MAP = {v: k for k, v in PROMOTION_MAP.items()}

    def __init__(self) -> None:
        defn = _load_shogi()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self._setup_standard_position()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def hand(self, player: str) -> SetZone:
        zone = self.session.runtime.players[player].zones["hand"]
        assert isinstance(zone, SetZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _place(self, col: int, row: int, piece_type: str, owner: str) -> ComponentId:
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{piece_type}-{owner}-{col}-{row}",
                component_type=piece_type,
                owner=owner,
            )
        )
        self.board.grid_set(col, row, cid)
        return cid

    def _add_to_hand(self, piece_type: str, owner: str) -> ComponentId:
        """Add a piece to a player's hand."""
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{piece_type}-{owner}-hand",
                component_type=piece_type,
                owner=owner,
            )
        )
        self.hand(owner).set_add(cid)
        return cid

    def _setup_standard_position(self) -> None:
        """Place all 40 pieces in standard Shogi opening position.

        Sente (first player) pieces on rows 0-2, gote pieces on rows 6-8.
        Board orientation: sente at bottom (row 0), gote at top (row 8).

        Row 0 (sente back rank): L N S G K G S N L
        Row 1:                   . R . . . . . B .
        Row 2 (sente pawns):     P P P P P P P P P
        ...
        Row 6 (gote pawns):      P P P P P P P P P
        Row 7:                   . B . . . . . R .
        Row 8 (gote back rank):  L N S G K G S N L
        """
        # Sente back rank (row 0)
        back_rank = ["lance", "knight", "silver", "gold", "king", "gold", "silver", "knight", "lance"]
        for col, piece_type in enumerate(back_rank):
            self._place(col, 0, piece_type, "sente")

        # Sente rook at (1, 1), bishop at (7, 1)
        self._place(1, 1, "rook", "sente")
        self._place(7, 1, "bishop", "sente")

        # Sente pawns on row 2
        for col in range(9):
            self._place(col, 2, "pawn", "sente")

        # Gote pawns on row 6
        for col in range(9):
            self._place(col, 6, "pawn", "gote")

        # Gote bishop at (1, 7), rook at (7, 7)
        self._place(1, 7, "bishop", "gote")
        self._place(7, 7, "rook", "gote")

        # Gote back rank (row 8)
        for col, piece_type in enumerate(back_rank):
            self._place(col, 8, piece_type, "gote")

    def piece_at(self, col: int, row: int) -> tuple[str, str] | None:
        """Return (piece_type, owner) or None."""
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        if comp is None:
            return None
        return (comp.component_type, comp.owner)

    def _clear_board(self) -> None:
        """Remove all pieces from the board and clear both hands."""
        for r in range(self.BOARD_SIZE):
            for c in range(self.BOARD_SIZE):
                self.board.grid_set(c, r, None)
        self.hand("sente").components.clear()
        self.hand("gote").components.clear()

    def _clear_and_place(self, pieces: list[tuple[int, int, str, str]]) -> None:
        """Clear the board and place specific pieces."""
        self._clear_board()
        for col, row, piece_type, owner in pieces:
            self._place(col, row, piece_type, owner)

    # ------------------------------------------------------------------
    # Move generation
    # ------------------------------------------------------------------

    def _in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.BOARD_SIZE and 0 <= row < self.BOARD_SIZE

    def _pseudo_legal_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Generate moves for the piece at (col, row) WITHOUT check validation."""
        info = self.piece_at(col, row)
        if info is None:
            return []
        piece_type, owner = info

        if piece_type == "king":
            return self._king_moves(col, row, owner)
        elif piece_type in self.GOLD_MOVERS:
            return self._gold_moves(col, row, owner)
        elif piece_type == "silver":
            return self._silver_moves(col, row, owner)
        elif piece_type == "rook":
            return self._slide_moves(col, row, owner, ORTHO)
        elif piece_type == "bishop":
            return self._slide_moves(col, row, owner, DIAG)
        elif piece_type == "dragon_king":
            return self._slide_moves(col, row, owner, ORTHO) + self._step_moves(col, row, owner, DIAG)
        elif piece_type == "dragon_horse":
            return self._slide_moves(col, row, owner, DIAG) + self._step_moves(col, row, owner, ORTHO)
        elif piece_type == "knight":
            return self._knight_moves(col, row, owner)
        elif piece_type == "lance":
            return self._lance_moves(col, row, owner)
        elif piece_type == "pawn":
            return self._pawn_moves(col, row, owner)
        else:
            return []

    def _king_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        return self._step_moves(col, row, owner, ADJACENT)

    def _step_moves(
        self, col: int, row: int, owner: str, directions: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """One step in each direction, blocked by friendly pieces."""
        moves = []
        for dc, dr in directions:
            nc, nr = col + dc, row + dr
            if self._in_bounds(nc, nr):
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _gold_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Gold general movement: 6 directions (forward, orthogonal, forward-diagonal)."""
        return self._step_moves(col, row, owner, _gold_directions(owner))

    def _silver_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Silver general movement: forward + all 4 diagonals (5 directions)."""
        return self._step_moves(col, row, owner, _silver_directions(owner))

    def _slide_moves(
        self, col: int, row: int, owner: str, directions: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Slide along directions until blocked or capturing."""
        moves = []
        for dc, dr in directions:
            nc, nr = col + dc, row + dr
            while self._in_bounds(nc, nr):
                target = self.piece_at(nc, nr)
                if target is None:
                    moves.append((nc, nr))
                elif target[1] != owner:
                    moves.append((nc, nr))
                    break
                else:
                    break
                nc += dc
                nr += dr
        return moves

    def _knight_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Shogi knight: 2 forward + 1 sideways (forward only, 2 destinations)."""
        moves = []
        for dc, dr in _knight_destinations(owner):
            nc, nr = col + dc, row + dr
            if self._in_bounds(nc, nr):
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _lance_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Lance: slides forward only."""
        fwd = _forward_dir(owner)
        return self._slide_moves(col, row, owner, [(0, fwd)])

    def _pawn_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Pawn: one step forward only."""
        fwd = _forward_dir(owner)
        moves = []
        nr = row + fwd
        if self._in_bounds(col, nr):
            target = self.piece_at(col, nr)
            if target is None or target[1] != owner:
                moves.append((col, nr))
        return moves

    # ------------------------------------------------------------------
    # Drop logic
    # ------------------------------------------------------------------

    def _legal_drop_squares(self, piece_type: str, owner: str) -> list[tuple[int, int]]:
        """Return all squares where piece_type can be legally dropped."""
        fwd = _forward_dir(owner)
        last_rank = 8 if owner == "sente" else 0
        second_last_rank = 7 if owner == "sente" else 1

        squares = []
        for c in range(self.BOARD_SIZE):
            for r in range(self.BOARD_SIZE):
                if self.piece_at(c, r) is not None:
                    continue

                # Pawns and lances cannot drop on last rank
                if piece_type in ("pawn", "lance") and r == last_rank:
                    continue

                # Knights cannot drop on last two ranks
                if piece_type == "knight" and r in (last_rank, second_last_rank):
                    continue

                # Nifu: no two unpromoted pawns in same column
                if piece_type == "pawn":
                    has_pawn_in_col = False
                    for check_r in range(self.BOARD_SIZE):
                        info = self.piece_at(c, check_r)
                        if info is not None and info[0] == "pawn" and info[1] == owner:
                            has_pawn_in_col = True
                            break
                    if has_pawn_in_col:
                        continue

                squares.append((c, r))
        return squares

    def _is_drop_checkmate(self, col: int, row: int, owner: str) -> bool:
        """Check if dropping a pawn at (col, row) would cause immediate checkmate.

        This is the uchifuzume (drop pawn mate) rule: you cannot drop a pawn
        that delivers checkmate.
        """
        # Temporarily place pawn
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"pawn-{owner}-temp",
                component_type="pawn",
                owner=owner,
            )
        )
        self.board.grid_set(col, row, cid)

        opponent = _opponent_of(owner)
        result = self.in_check(opponent) and self._has_no_legal_moves(opponent)

        # Undo
        self.board.grid_set(col, row, None)
        # Remove temp component from table
        self.session.runtime.components._entries.pop()

        return result

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def move(self, from_col: int, from_row: int, to_col: int, to_row: int,
             promote: bool = False) -> None:
        """Execute a board move. Validate owner, capture, optional promotion."""
        player = self.current_player()
        info = self.piece_at(from_col, from_row)
        if info is None:
            raise ValueError(f"no piece at ({from_col},{from_row})")
        if info[1] != player:
            raise ValueError(
                f"piece at ({from_col},{from_row}) belongs to {info[1]}, not {player}"
            )

        cid = self.board.grid_get(from_col, from_row)
        assert cid is not None
        comp = self.session.runtime.components.get(cid)
        assert comp is not None

        # Pick up piece
        self.board.grid_set(from_col, from_row, None)

        # Capture: captured piece goes to opponent's hand in unpromoted form
        target_cid = self.board.grid_get(to_col, to_row)
        if target_cid is not None:
            target_comp = self.session.runtime.components.get(target_cid)
            assert target_comp is not None
            self.board.grid_set(to_col, to_row, None)
            # Demote if promoted
            base_type = self.DEMOTION_MAP.get(target_comp.component_type, target_comp.component_type)
            target_comp.component_type = base_type
            target_comp.owner = player
            self.hand(player).set_add(target_cid)

        # Place at destination
        self.board.grid_set(to_col, to_row, cid)

        # Promotion
        if promote:
            promoted_type = self.PROMOTION_MAP.get(comp.component_type)
            if promoted_type is not None:
                comp.component_type = promoted_type

        # Advance turn
        self.session.advance_turn()

        # Detect checkmate / stalemate
        next_player = self.current_player()
        if self.is_checkmate(next_player):
            self.session.runtime.status = "finished"
            self.session.runtime.result = GameResult(
                outcome="win",
                winner=_opponent_of(next_player),
                condition="checkmate",
            )
        elif self.is_stalemate(next_player):
            self.session.runtime.status = "finished"
            self.session.runtime.result = GameResult(
                outcome="draw",
                condition="stalemate",
            )

    def drop(self, piece_type: str, col: int, row: int) -> None:
        """Drop a piece from hand onto the board."""
        player = self.current_player()
        hand = self.hand(player)

        # Find the piece in hand
        drop_cid: ComponentId | None = None
        for cid in hand.components:
            comp = self.session.runtime.components.get(cid)
            if comp is not None and comp.component_type == piece_type and comp.owner == player:
                drop_cid = cid
                break
        if drop_cid is None:
            raise ValueError(f"{player} has no {piece_type} in hand")

        # Validate square is empty
        if self.piece_at(col, row) is not None:
            raise ValueError(f"square ({col},{row}) is occupied")

        # Validate drop restrictions
        legal = self._legal_drop_squares(piece_type, player)
        if (col, row) not in legal:
            raise ValueError(f"cannot drop {piece_type} at ({col},{row})")

        # Check uchifuzume for pawn drops
        if piece_type == "pawn" and self._is_drop_checkmate(col, row, player):
            raise ValueError("pawn drop would cause checkmate (uchifuzume)")

        # Execute drop
        hand.set_remove(drop_cid)
        self.board.grid_set(col, row, drop_cid)

        # Advance turn
        self.session.advance_turn()

        # Detect checkmate / stalemate
        next_player = self.current_player()
        if self.is_checkmate(next_player):
            self.session.runtime.status = "finished"
            self.session.runtime.result = GameResult(
                outcome="win",
                winner=_opponent_of(next_player),
                condition="checkmate",
            )

    # ------------------------------------------------------------------
    # Promotion zone
    # ------------------------------------------------------------------

    def in_promotion_zone(self, row: int, player: str) -> bool:
        """Check if a row is in the promotion zone for a player."""
        if player == "sente":
            return row >= 6  # rows 6, 7, 8
        else:
            return row <= 2  # rows 0, 1, 2

    def must_promote(self, piece_type: str, row: int, player: str) -> bool:
        """Check if a piece MUST promote at this row."""
        last_rank = 8 if player == "sente" else 0
        second_last = 7 if player == "sente" else 1

        if piece_type in ("pawn", "lance") and row == last_rank:
            return True
        if piece_type == "knight" and row in (last_rank, second_last):
            return True
        return False

    # ------------------------------------------------------------------
    # Check / checkmate detection
    # ------------------------------------------------------------------

    def _find_king(self, player: str) -> tuple[int, int] | None:
        for r in range(self.BOARD_SIZE):
            for c in range(self.BOARD_SIZE):
                info = self.piece_at(c, r)
                if info is not None and info[0] == "king" and info[1] == player:
                    return (c, r)
        return None

    def is_attacked(self, col: int, row: int, by_player: str) -> bool:
        """Check if (col, row) is attacked by any piece belonging to by_player."""
        # Check all pieces of by_player for attacks on this square
        for r in range(self.BOARD_SIZE):
            for c in range(self.BOARD_SIZE):
                info = self.piece_at(c, r)
                if info is None or info[1] != by_player:
                    continue
                moves = self._pseudo_legal_moves(c, r)
                if (col, row) in moves:
                    return True
        return False

    def in_check(self, player: str) -> bool:
        pos = self._find_king(player)
        if pos is None:
            return False
        return self.is_attacked(pos[0], pos[1], _opponent_of(player))

    def _try_move(self, fc: int, fr: int, tc: int, tr: int) -> tuple[int, int, int, int, ComponentId | None, ComponentId | None]:
        piece_cid = self.board.grid_get(fc, fr)
        captured_cid = self.board.grid_get(tc, tr)
        self.board.grid_set(fc, fr, None)
        self.board.grid_set(tc, tr, piece_cid)
        return (fc, fr, tc, tr, piece_cid, captured_cid)

    def _undo_move(self, undo: tuple[int, int, int, int, ComponentId | None, ComponentId | None]) -> None:
        fc, fr, tc, tr, piece_cid, captured_cid = undo
        self.board.grid_set(tc, tr, captured_cid)
        self.board.grid_set(fc, fr, piece_cid)

    def legal_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Filter pseudo-legal moves: only those that don't leave own king in check."""
        info = self.piece_at(col, row)
        if info is None:
            return []
        owner = info[1]
        result = []
        for tc, tr in self._pseudo_legal_moves(col, row):
            undo = self._try_move(col, row, tc, tr)
            if not self.in_check(owner):
                result.append((tc, tr))
            self._undo_move(undo)
        return result

    def is_checkmate(self, player: str) -> bool:
        if not self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    def is_stalemate(self, player: str) -> bool:
        if self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    def _has_no_legal_moves(self, player: str) -> bool:
        """Return True if player has no legal board moves AND no legal drops."""
        # Check board moves
        for r in range(self.BOARD_SIZE):
            for c in range(self.BOARD_SIZE):
                info = self.piece_at(c, r)
                if info is not None and info[1] == player:
                    if len(self.legal_moves(c, r)) > 0:
                        return False
        # Check drops from hand
        hand = self.hand(player)
        seen_types: set[str] = set()
        for cid in hand.components:
            comp = self.session.runtime.components.get(cid)
            if comp is not None and comp.component_type not in seen_types:
                seen_types.add(comp.component_type)
                squares = self._legal_drop_squares(comp.component_type, player)
                # For each drop square, check if the drop resolves check
                for sc, sr in squares:
                    if comp.component_type == "pawn" and self._is_drop_checkmate(sc, sr, player):
                        continue
                    # Temporarily drop to see if it resolves check
                    self.board.grid_set(sc, sr, cid)
                    hand_removed = hand.set_remove(cid)
                    if not self.in_check(player):
                        # Undo
                        self.board.grid_set(sc, sr, None)
                        if hand_removed:
                            hand.set_add(cid)
                        return False
                    # Undo
                    self.board.grid_set(sc, sr, None)
                    if hand_removed:
                        hand.set_add(cid)
        return True


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_shogi()
        assert defn.game.name == "Shogi"

    def test_two_players(self) -> None:
        defn = _load_shogi()
        assert defn.game.players == ["sente", "gote"]

    def test_perfect_information(self) -> None:
        defn = _load_shogi()
        assert defn.game.information == "perfect"

    def test_9x9_board(self) -> None:
        defn = _load_shogi()
        assert defn.zones["board"].dimensions == [9, 9]

    def test_hand_zone_per_player(self) -> None:
        defn = _load_shogi()
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].zone_type == "set"

    def test_all_piece_types_present(self) -> None:
        defn = _load_shogi()
        expected = {
            "king", "rook", "bishop", "gold", "silver", "knight", "lance", "pawn",
            "dragon_king", "dragon_horse", "promoted_silver", "promoted_knight",
            "promoted_lance", "tokin",
        }
        assert set(defn.components.keys()) == expected

    def test_alternating_turns(self) -> None:
        defn = _load_shogi()
        assert defn.turn_order.type == "alternating"
        assert defn.turn_order.players == ["sente", "gote"]

    def test_client_verifiable(self) -> None:
        defn = _load_shogi()
        assert "all" in defn.authority.client_verifiable


# ---------------------------------------------------------------------------
# Tests: setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_40_pieces_total(self) -> None:
        game = ShogiGame()
        count = 0
        for r in range(9):
            for c in range(9):
                if game.piece_at(c, r) is not None:
                    count += 1
        assert count == 40

    def test_20_pieces_per_player(self) -> None:
        game = ShogiGame()
        sente_count = 0
        gote_count = 0
        for r in range(9):
            for c in range(9):
                info = game.piece_at(c, r)
                if info is not None:
                    if info[1] == "sente":
                        sente_count += 1
                    else:
                        gote_count += 1
        assert sente_count == 20
        assert gote_count == 20

    def test_sente_king_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(4, 0) == ("king", "sente")

    def test_gote_king_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(4, 8) == ("king", "gote")

    def test_sente_pawns_on_row_2(self) -> None:
        game = ShogiGame()
        for col in range(9):
            assert game.piece_at(col, 2) == ("pawn", "sente")

    def test_gote_pawns_on_row_6(self) -> None:
        game = ShogiGame()
        for col in range(9):
            assert game.piece_at(col, 6) == ("pawn", "gote")

    def test_sente_rook_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(1, 1) == ("rook", "sente")

    def test_sente_bishop_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(7, 1) == ("bishop", "sente")

    def test_gote_rook_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(7, 7) == ("rook", "gote")

    def test_gote_bishop_position(self) -> None:
        game = ShogiGame()
        assert game.piece_at(1, 7) == ("bishop", "gote")

    def test_sente_back_rank(self) -> None:
        game = ShogiGame()
        expected = ["lance", "knight", "silver", "gold", "king", "gold", "silver", "knight", "lance"]
        for col, pt in enumerate(expected):
            assert game.piece_at(col, 0) == (pt, "sente"), f"col {col}: expected {pt}"

    def test_gote_back_rank(self) -> None:
        game = ShogiGame()
        expected = ["lance", "knight", "silver", "gold", "king", "gold", "silver", "knight", "lance"]
        for col, pt in enumerate(expected):
            assert game.piece_at(col, 8) == (pt, "gote"), f"col {col}: expected {pt}"

    def test_empty_hands_at_start(self) -> None:
        game = ShogiGame()
        assert game.hand("sente").count() == 0
        assert game.hand("gote").count() == 0


# ---------------------------------------------------------------------------
# Tests: king movement
# ---------------------------------------------------------------------------


class TestKingMovement:
    def test_king_center_empty_board(self) -> None:
        """King in center of empty board has 8 moves."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "king", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 8

    def test_king_corner(self) -> None:
        """King in corner has 3 moves."""
        game = ShogiGame()
        game._clear_and_place([(0, 0, "king", "sente")])
        moves = game._pseudo_legal_moves(0, 0)
        assert len(moves) == 3

    def test_king_blocked_by_friendly(self) -> None:
        """King surrounded by friendly pieces has no moves."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 4, "king", "sente"),
            (3, 3, "pawn", "sente"),
            (4, 3, "pawn", "sente"),
            (5, 3, "pawn", "sente"),
            (3, 4, "pawn", "sente"),
            (5, 4, "pawn", "sente"),
            (3, 5, "pawn", "sente"),
            (4, 5, "pawn", "sente"),
            (5, 5, "pawn", "sente"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0

    def test_king_can_capture_enemy(self) -> None:
        """King can capture adjacent enemy piece."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 4, "king", "sente"),
            (5, 5, "pawn", "gote"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (5, 5) in moves


# ---------------------------------------------------------------------------
# Tests: gold general movement
# ---------------------------------------------------------------------------


class TestGoldMovement:
    def test_gold_center_6_directions(self) -> None:
        """Gold general: 6 directions — forward, left, right, backward, forward-diag L/R."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "gold", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # Sente forward = +row, so directions are:
        # forward (4,5), left (3,4), right (5,4), backward (4,3),
        # forward-diag-left (3,5), forward-diag-right (5,5)
        assert len(moves) == 6
        assert (4, 5) in moves   # forward
        assert (3, 4) in moves   # left
        assert (5, 4) in moves   # right
        assert (4, 3) in moves   # backward
        assert (3, 5) in moves   # forward-diag left
        assert (5, 5) in moves   # forward-diag right
        # backward-diag should NOT be available
        assert (3, 3) not in moves
        assert (5, 3) not in moves

    def test_gote_gold_directions(self) -> None:
        """Gote gold general moves in opposite forward direction."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "gold", "gote")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 6
        # Gote forward = -row
        assert (4, 3) in moves   # forward for gote
        assert (3, 3) in moves   # forward-diag left for gote
        assert (5, 3) in moves   # forward-diag right for gote
        assert (4, 5) in moves   # backward for gote
        # backward-diag for gote (which is sente's forward-diag) should NOT be available
        assert (3, 5) not in moves
        assert (5, 5) not in moves


# ---------------------------------------------------------------------------
# Tests: silver general movement
# ---------------------------------------------------------------------------


class TestSilverMovement:
    def test_silver_center_5_directions(self) -> None:
        """Silver general: 5 directions — forward + all 4 diagonals."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "silver", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 5
        # Forward
        assert (4, 5) in moves
        # All 4 diagonals
        assert (3, 5) in moves
        assert (5, 5) in moves
        assert (3, 3) in moves
        assert (5, 3) in moves
        # Sideways and backward should NOT be available
        assert (3, 4) not in moves
        assert (5, 4) not in moves
        assert (4, 3) not in moves


# ---------------------------------------------------------------------------
# Tests: rook movement
# ---------------------------------------------------------------------------


class TestRookMovement:
    def test_rook_center_empty_board(self) -> None:
        """Rook in center has orthogonal slides in 4 directions."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "rook", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # 4 up + 4 down + 4 left + 4 right = 16
        assert len(moves) == 16

    def test_rook_blocked_by_friendly(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 4, "rook", "sente"),
            (4, 5, "pawn", "sente"),
            (4, 3, "pawn", "sente"),
            (5, 4, "pawn", "sente"),
            (3, 4, "pawn", "sente"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0

    def test_rook_captures_enemy(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 4, "rook", "sente"),
            (4, 6, "pawn", "gote"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (4, 6) in moves
        assert (4, 7) not in moves  # blocked after capture


# ---------------------------------------------------------------------------
# Tests: bishop movement
# ---------------------------------------------------------------------------


class TestBishopMovement:
    def test_bishop_center_empty_board(self) -> None:
        """Bishop in center has diagonal slides."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "bishop", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # From (4,4) on 9x9: diag NE(4) + NW(4) + SE(4) + SW(4) = 16
        assert len(moves) == 16


# ---------------------------------------------------------------------------
# Tests: knight movement (shogi-style, forward only)
# ---------------------------------------------------------------------------


class TestKnightMovement:
    def test_sente_knight_two_forward_destinations(self) -> None:
        """Sente knight at center: 2 forward L-shaped jumps."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "knight", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # Sente forward = +row: destinations are (3,6) and (5,6)
        assert len(moves) == 2
        assert (3, 6) in moves
        assert (5, 6) in moves

    def test_gote_knight_two_forward_destinations(self) -> None:
        """Gote knight at center: 2 forward L-shaped jumps in opposite direction."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "knight", "gote")])
        moves = game._pseudo_legal_moves(4, 4)
        # Gote forward = -row: destinations are (3,2) and (5,2)
        assert len(moves) == 2
        assert (3, 2) in moves
        assert (5, 2) in moves

    def test_knight_edge_limited(self) -> None:
        """Knight near edge may have fewer destinations."""
        game = ShogiGame()
        game._clear_and_place([(0, 4, "knight", "sente")])
        moves = game._pseudo_legal_moves(0, 4)
        # Only (1,6) is in bounds; (-1,6) is out
        assert len(moves) == 1
        assert (1, 6) in moves

    def test_knight_at_top_no_moves(self) -> None:
        """Sente knight on row 8 has no forward destinations."""
        game = ShogiGame()
        game._clear_and_place([(4, 8, "knight", "sente")])
        moves = game._pseudo_legal_moves(4, 8)
        assert len(moves) == 0

    def test_knight_jumps_over_pieces(self) -> None:
        """Knight leaps over intervening pieces."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 4, "knight", "sente"),
            (4, 5, "pawn", "sente"),  # blocking square
            (3, 5, "pawn", "sente"),  # blocking square
            (5, 5, "pawn", "sente"),  # blocking square
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 2  # jumps over blockers


# ---------------------------------------------------------------------------
# Tests: lance movement
# ---------------------------------------------------------------------------


class TestLanceMovement:
    def test_sente_lance_slides_forward(self) -> None:
        """Sente lance slides forward (increasing row)."""
        game = ShogiGame()
        game._clear_and_place([(4, 0, "lance", "sente")])
        moves = game._pseudo_legal_moves(4, 0)
        # Can slide from row 1 to row 8 = 8 squares
        assert len(moves) == 8
        for r in range(1, 9):
            assert (4, r) in moves

    def test_gote_lance_slides_forward(self) -> None:
        """Gote lance slides forward (decreasing row)."""
        game = ShogiGame()
        game._clear_and_place([(4, 8, "lance", "gote")])
        moves = game._pseudo_legal_moves(4, 8)
        assert len(moves) == 8
        for r in range(0, 8):
            assert (4, r) in moves

    def test_lance_blocked(self) -> None:
        """Lance blocked by friendly piece."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "lance", "sente"),
            (4, 3, "pawn", "sente"),
        ])
        moves = game._pseudo_legal_moves(4, 0)
        assert len(moves) == 2  # rows 1, 2
        assert (4, 3) not in moves

    def test_lance_captures_then_stops(self) -> None:
        """Lance captures enemy piece and stops."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "lance", "sente"),
            (4, 3, "pawn", "gote"),
        ])
        moves = game._pseudo_legal_moves(4, 0)
        assert (4, 3) in moves  # can capture
        assert (4, 4) not in moves  # blocked after capture
        assert len(moves) == 3  # rows 1, 2, 3


# ---------------------------------------------------------------------------
# Tests: pawn movement
# ---------------------------------------------------------------------------


class TestPawnMovement:
    def test_sente_pawn_one_step_forward(self) -> None:
        """Sente pawn moves one step forward (+row)."""
        game = ShogiGame()
        game._clear_and_place([(4, 3, "pawn", "sente")])
        moves = game._pseudo_legal_moves(4, 3)
        assert moves == [(4, 4)]

    def test_gote_pawn_one_step_forward(self) -> None:
        """Gote pawn moves one step forward (-row)."""
        game = ShogiGame()
        game._clear_and_place([(4, 5, "pawn", "gote")])
        moves = game._pseudo_legal_moves(4, 5)
        assert moves == [(4, 4)]

    def test_pawn_captures_forward(self) -> None:
        """Shogi pawn captures straight ahead (unlike chess)."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 3, "pawn", "sente"),
            (4, 4, "pawn", "gote"),
        ])
        moves = game._pseudo_legal_moves(4, 3)
        assert moves == [(4, 4)]

    def test_pawn_blocked_by_friendly(self) -> None:
        """Pawn blocked by friendly piece ahead."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 3, "pawn", "sente"),
            (4, 4, "pawn", "sente"),
        ])
        moves = game._pseudo_legal_moves(4, 3)
        assert moves == []

    def test_pawn_no_double_push(self) -> None:
        """Shogi pawns never double-push (unlike chess)."""
        game = ShogiGame()
        game._clear_and_place([(4, 2, "pawn", "sente")])
        moves = game._pseudo_legal_moves(4, 2)
        assert len(moves) == 1
        assert moves == [(4, 3)]

    def test_pawn_at_last_rank_no_moves(self) -> None:
        """Unpromoted pawn on last rank has no moves (must have promoted)."""
        game = ShogiGame()
        game._clear_and_place([(4, 8, "pawn", "sente")])
        moves = game._pseudo_legal_moves(4, 8)
        assert moves == []


# ---------------------------------------------------------------------------
# Tests: promoted piece movement
# ---------------------------------------------------------------------------


class TestPromotedPieceMovement:
    def test_dragon_king_slides_and_steps(self) -> None:
        """Dragon king (promoted rook): slide orthogonal + step diagonal."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "dragon_king", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # Orthogonal slides: 16 squares
        # Diagonal steps: 4 squares
        assert len(moves) == 20

    def test_dragon_horse_slides_and_steps(self) -> None:
        """Dragon horse (promoted bishop): slide diagonal + step orthogonal."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "dragon_horse", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        # Diagonal slides: 16 squares
        # Orthogonal steps: 4 squares
        assert len(moves) == 20

    def test_tokin_moves_as_gold(self) -> None:
        """Tokin (promoted pawn) moves as gold general."""
        game = ShogiGame()
        game._clear_and_place([(4, 4, "tokin", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 6
        # Same as gold: forward, left, right, backward, fwd-diag L/R
        assert (4, 5) in moves
        assert (3, 5) in moves
        assert (5, 5) in moves

    def test_promoted_silver_moves_as_gold(self) -> None:
        game = ShogiGame()
        game._clear_and_place([(4, 4, "promoted_silver", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 6

    def test_promoted_knight_moves_as_gold(self) -> None:
        game = ShogiGame()
        game._clear_and_place([(4, 4, "promoted_knight", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 6

    def test_promoted_lance_moves_as_gold(self) -> None:
        game = ShogiGame()
        game._clear_and_place([(4, 4, "promoted_lance", "sente")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 6


# ---------------------------------------------------------------------------
# Tests: move execution and captures
# ---------------------------------------------------------------------------


class TestMoveExecution:
    def test_basic_move(self) -> None:
        """Move a piece from one square to another."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 2, "pawn", "sente"),
        ])
        game.move(4, 2, 4, 3)
        assert game.piece_at(4, 2) is None
        assert game.piece_at(4, 3) == ("pawn", "sente")

    def test_turn_advances(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 2, "pawn", "sente"),
        ])
        assert game.current_player() == "sente"
        game.move(4, 2, 4, 3)
        assert game.current_player() == "gote"

    def test_cannot_move_opponent_piece(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 6, "pawn", "gote"),
        ])
        with pytest.raises(ValueError, match="belongs to gote"):
            game.move(4, 6, 4, 5)

    def test_capture_goes_to_hand(self) -> None:
        """Captured piece switches sides and goes to captor's hand."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 3, "rook", "sente"),
            (4, 6, "pawn", "gote"),
        ])
        game.move(4, 3, 4, 6)
        assert game.piece_at(4, 6) == ("rook", "sente")
        # Captured pawn should be in sente's hand, now owned by sente
        assert game.hand("sente").count() == 1
        cid = game.hand("sente").components[0]
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        assert comp.component_type == "pawn"
        assert comp.owner == "sente"

    def test_capture_promoted_piece_demotes(self) -> None:
        """Captured promoted piece reverts to unpromoted form in hand."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 3, "rook", "sente"),
            (4, 6, "dragon_king", "gote"),  # promoted rook
        ])
        game.move(4, 3, 4, 6)
        cid = game.hand("sente").components[0]
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        assert comp.component_type == "rook"  # demoted from dragon_king
        assert comp.owner == "sente"

    def test_capture_tokin_becomes_pawn(self) -> None:
        """Captured tokin (promoted pawn) reverts to pawn."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 3, "rook", "sente"),
            (4, 6, "tokin", "gote"),
        ])
        game.move(4, 3, 4, 6)
        cid = game.hand("sente").components[0]
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        assert comp.component_type == "pawn"

    def test_promotion_on_move(self) -> None:
        """Piece promotes when entering promotion zone with promote=True."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 5, "pawn", "sente"),
        ])
        # Move pawn from row 5 to row 6 (enters sente's promotion zone)
        game.move(4, 5, 4, 6, promote=True)
        assert game.piece_at(4, 6) == ("tokin", "sente")

    def test_no_promotion_when_not_requested(self) -> None:
        """Piece does NOT promote when promote=False."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 5, "silver", "sente"),
        ])
        game.move(4, 5, 4, 6, promote=False)
        assert game.piece_at(4, 6) == ("silver", "sente")


# ---------------------------------------------------------------------------
# Tests: promotion zone
# ---------------------------------------------------------------------------


class TestPromotionZone:
    def test_sente_promotion_zone(self) -> None:
        """Sente's promotion zone is rows 6, 7, 8."""
        game = ShogiGame()
        assert game.in_promotion_zone(6, "sente") is True
        assert game.in_promotion_zone(7, "sente") is True
        assert game.in_promotion_zone(8, "sente") is True
        assert game.in_promotion_zone(5, "sente") is False

    def test_gote_promotion_zone(self) -> None:
        """Gote's promotion zone is rows 0, 1, 2."""
        game = ShogiGame()
        assert game.in_promotion_zone(0, "gote") is True
        assert game.in_promotion_zone(1, "gote") is True
        assert game.in_promotion_zone(2, "gote") is True
        assert game.in_promotion_zone(3, "gote") is False

    def test_pawn_must_promote_on_last_rank(self) -> None:
        game = ShogiGame()
        assert game.must_promote("pawn", 8, "sente") is True
        assert game.must_promote("pawn", 7, "sente") is False

    def test_lance_must_promote_on_last_rank(self) -> None:
        game = ShogiGame()
        assert game.must_promote("lance", 8, "sente") is True
        assert game.must_promote("lance", 7, "sente") is False

    def test_knight_must_promote_on_last_two_ranks(self) -> None:
        game = ShogiGame()
        assert game.must_promote("knight", 8, "sente") is True
        assert game.must_promote("knight", 7, "sente") is True
        assert game.must_promote("knight", 6, "sente") is False

    def test_gote_mandatory_promotion_ranks(self) -> None:
        game = ShogiGame()
        assert game.must_promote("pawn", 0, "gote") is True
        assert game.must_promote("lance", 0, "gote") is True
        assert game.must_promote("knight", 0, "gote") is True
        assert game.must_promote("knight", 1, "gote") is True

    def test_king_never_must_promote(self) -> None:
        game = ShogiGame()
        assert game.must_promote("king", 8, "sente") is False

    def test_gold_never_must_promote(self) -> None:
        game = ShogiGame()
        assert game.must_promote("gold", 8, "sente") is False


# ---------------------------------------------------------------------------
# Tests: drop mechanics
# ---------------------------------------------------------------------------


class TestDropMechanics:
    def test_basic_drop(self) -> None:
        """Drop a piece from hand onto an empty square."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("pawn", "sente")
        game.drop("pawn", 5, 4)
        assert game.piece_at(5, 4) == ("pawn", "sente")
        assert game.hand("sente").count() == 0

    def test_drop_advances_turn(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("gold", "sente")
        assert game.current_player() == "sente"
        game.drop("gold", 5, 4)
        assert game.current_player() == "gote"

    def test_cannot_drop_on_occupied_square(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (5, 4, "pawn", "sente"),
        ])
        game._add_to_hand("gold", "sente")
        with pytest.raises(ValueError, match="occupied"):
            game.drop("gold", 5, 4)

    def test_cannot_drop_piece_not_in_hand(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        with pytest.raises(ValueError, match="no rook"):
            game.drop("rook", 5, 4)

    def test_nifu_no_two_pawns_in_column(self) -> None:
        """Cannot drop a pawn in a column that already has an unpromoted pawn."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (5, 3, "pawn", "sente"),  # pawn already in column 5
        ])
        game._add_to_hand("pawn", "sente")
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("pawn", 5, 6)  # same column 5

    def test_nifu_allows_different_column(self) -> None:
        """CAN drop pawn in a different column (nifu only applies per-column)."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (5, 3, "pawn", "sente"),
        ])
        game._add_to_hand("pawn", "sente")
        game.drop("pawn", 6, 4)  # column 6, no nifu
        assert game.piece_at(6, 4) == ("pawn", "sente")

    def test_nifu_tokin_does_not_block(self) -> None:
        """A tokin (promoted pawn) in a column does NOT prevent pawn drops."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (5, 7, "tokin", "sente"),  # promoted pawn
        ])
        game._add_to_hand("pawn", "sente")
        game.drop("pawn", 5, 4)
        assert game.piece_at(5, 4) == ("pawn", "sente")

    def test_pawn_cannot_drop_on_last_rank(self) -> None:
        """Pawns cannot be dropped on the last rank."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("pawn", "sente")
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("pawn", 5, 8)  # last rank for sente

    def test_lance_cannot_drop_on_last_rank(self) -> None:
        """Lances cannot be dropped on the last rank."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("lance", "sente")
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("lance", 5, 8)

    def test_knight_cannot_drop_on_last_two_ranks(self) -> None:
        """Knights cannot be dropped on the last two ranks."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("knight", "sente")
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("knight", 5, 8)  # last rank
        game._add_to_hand("knight", "sente")
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("knight", 5, 7)  # second-to-last rank

    def test_gote_drop_restrictions_flipped(self) -> None:
        """Gote's last rank is row 0."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        game._add_to_hand("pawn", "gote")
        # Pass sente's turn first
        game.move(4, 0, 3, 0)
        with pytest.raises(ValueError, match="cannot drop"):
            game.drop("pawn", 5, 0)  # last rank for gote


# ---------------------------------------------------------------------------
# Tests: uchifuzume (pawn drop checkmate restriction)
# ---------------------------------------------------------------------------


class TestUchifuzume:
    def test_pawn_drop_causing_checkmate_is_illegal(self) -> None:
        """Cannot drop a pawn that immediately delivers checkmate."""
        game = ShogiGame()
        # Set up: gote king at (4,8), sente gold nearby blocking escapes
        # Dropping a pawn directly in front of the king causes immediate checkmate
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (3, 8, "gold", "sente"),  # blocks d9
            (5, 8, "gold", "sente"),  # blocks f9
            (3, 7, "gold", "sente"),  # blocks d8
            (5, 7, "gold", "sente"),  # blocks f8
        ])
        game._add_to_hand("pawn", "sente")
        # Dropping pawn at (4,7) attacks king at (4,8). King cannot escape.
        with pytest.raises(ValueError, match="uchifuzume"):
            game.drop("pawn", 4, 7)

    def test_pawn_drop_check_without_checkmate_is_legal(self) -> None:
        """A pawn drop that gives check but NOT checkmate is allowed."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),  # king can escape to (3,8), (5,8), etc.
        ])
        game._add_to_hand("pawn", "sente")
        # Drop pawn at (4,7) — gives check but king has escape squares
        game.drop("pawn", 4, 7)
        assert game.piece_at(4, 7) == ("pawn", "sente")


# ---------------------------------------------------------------------------
# Tests: check and checkmate detection
# ---------------------------------------------------------------------------


class TestCheckDetection:
    def test_rook_gives_check(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 5, "rook", "sente"),  # on same file as gote king
        ])
        assert game.in_check("gote") is True
        assert game.in_check("sente") is False

    def test_gold_gives_check(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 7, "gold", "sente"),  # directly in front of gote king
        ])
        # Gold at (4,7) is sente's, attacks forward for sente = +row.
        # (4,8) is forward for sente gold? Gold at (4,7) with sente forward = +row.
        # Gold moves: forward (4,8), left (3,7), right (5,7), back (4,6),
        # fwd-diag (3,8), (5,8). So yes, attacks (4,8).
        assert game.in_check("gote") is True

    def test_pawn_gives_check(self) -> None:
        """Pawn directly in front of king gives check."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 7, "pawn", "sente"),  # sente pawn attacks forward = (4,8)
        ])
        assert game.in_check("gote") is True

    def test_blocked_check(self) -> None:
        """Check blocked by intervening piece."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 5, "rook", "sente"),
            (4, 6, "pawn", "gote"),  # blocks rook's line
        ])
        assert game.in_check("gote") is False


class TestCheckmate:
    def test_simple_checkmate(self) -> None:
        """Gote king checkmated by rook with gold support."""
        game = ShogiGame()
        # Gote king at (4,8). Sente rook at (4,7) gives check along file.
        # Sente gold at (4,6) defends the rook (gold fwd = (4,7)).
        # Sente gold at (3,7) blocks escape to (3,8) and (3,7).
        # Sente gold at (5,7) blocks escape to (5,8) and (5,7).
        # Rook at (4,7) also attacks (3,7) and (5,7) along the rank.
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 7, "rook", "sente"),  # checks king, attacks whole rank 7
            (4, 6, "gold", "sente"),  # defends rook (gold forward = (4,7))
            (3, 7, "gold", "sente"),  # blocks (3,8), attacked by rook
            (5, 7, "gold", "sente"),  # blocks (5,8), attacked by rook
        ])
        # King at (4,8) is checked by rook at (4,7).
        # Escape squares:
        #   (3,8): gold at (3,7) attacks it (sente gold fwd-diag-right = (4,8), fwd = (3,8))
        #   (5,8): gold at (5,7) attacks it (sente gold fwd = (5,8))
        #   (3,7): occupied by sente gold
        #   (5,7): occupied by sente gold
        #   (4,7): rook there, defended by gold at (4,6)
        assert game.in_check("gote") is True
        assert game.is_checkmate("gote") is True

    def test_not_checkmate_when_escape_exists(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (4, 5, "rook", "sente"),
        ])
        assert game.in_check("gote") is True
        assert game.is_checkmate("gote") is False

    def test_checkmate_triggers_game_end(self) -> None:
        """Delivering checkmate ends the game with a win."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (3, 8, "gold", "sente"),
            (5, 8, "gold", "sente"),
            (4, 6, "gold", "sente"),  # will move to (4,7) to deliver checkmate
        ])
        game.move(4, 6, 4, 7)
        assert game.session.runtime.status == "finished"
        assert game.session.runtime.result is not None
        assert game.session.runtime.result.outcome == "win"
        assert game.session.runtime.result.winner == "sente"
        assert game.session.runtime.result.condition == "checkmate"


# ---------------------------------------------------------------------------
# Tests: legal move filtering (pin detection)
# ---------------------------------------------------------------------------


class TestLegalMoves:
    def test_pinned_piece_restricted(self) -> None:
        """A piece pinned to its king can only move along the pin line."""
        game = ShogiGame()
        # Sente king at (4,0), sente rook at (4,3) pinned by gote rook at (4,8)
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 3, "rook", "sente"),
            (4, 8, "rook", "gote"),
            (0, 8, "king", "gote"),
        ])
        legal = game.legal_moves(4, 3)
        # Rook can only move along column 4
        for tc, tr in legal:
            assert tc == 4, f"pinned rook should only move along file, got ({tc},{tr})"
        # Can move to (4,1), (4,2), (4,4), (4,5), (4,6), (4,7), (4,8)
        assert len(legal) == 7

    def test_king_cannot_move_into_check(self) -> None:
        """King cannot step to a square attacked by enemy."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (0, 8, "king", "gote"),
            (5, 8, "rook", "gote"),  # attacks column 5
        ])
        legal = game.legal_moves(4, 0)
        assert (5, 0) not in legal  # column 5 attacked by rook
        assert (5, 1) not in legal

    def test_must_block_or_move_when_in_check(self) -> None:
        """When in check, only moves resolving the check are legal."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (0, 8, "king", "gote"),
            (4, 5, "rook", "gote"),  # gives check along column
            (2, 2, "rook", "sente"),  # can block at (4,2) or similar
        ])
        assert game.in_check("sente") is True
        king_legal = game.legal_moves(4, 0)
        # King must move off the file or be blocked
        for tc, tr in king_legal:
            assert tc != 4, "king should not stay on attacked file"


# ---------------------------------------------------------------------------
# Tests: drop squares computation
# ---------------------------------------------------------------------------


class TestDropSquares:
    def test_pawn_drop_excludes_nifu_column(self) -> None:
        """Pawn drop squares exclude columns with existing unpromoted pawns."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (3, 4, "pawn", "sente"),  # pawn in column 3
        ])
        squares = game._legal_drop_squares("pawn", "sente")
        for c, r in squares:
            assert c != 3, "should not allow pawn drop in column with existing pawn"

    def test_pawn_drop_excludes_last_rank(self) -> None:
        """Pawn cannot be dropped on the last rank."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        squares = game._legal_drop_squares("pawn", "sente")
        for c, r in squares:
            assert r != 8, "should not drop pawn on last rank for sente"

    def test_knight_drop_excludes_last_two_ranks(self) -> None:
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        squares = game._legal_drop_squares("knight", "sente")
        for c, r in squares:
            assert r not in (7, 8), "should not drop knight on last two ranks for sente"

    def test_gold_drop_any_empty_square(self) -> None:
        """Gold general can be dropped on any empty square (no extra restrictions)."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
        ])
        squares = game._legal_drop_squares("gold", "sente")
        # 81 total - 2 occupied = 79 empty squares
        assert len(squares) == 79

    def test_drop_excludes_occupied_squares(self) -> None:
        """Cannot drop on any occupied square."""
        game = ShogiGame()
        game._clear_and_place([
            (4, 0, "king", "sente"),
            (4, 8, "king", "gote"),
            (5, 5, "pawn", "sente"),
        ])
        squares = game._legal_drop_squares("gold", "sente")
        assert (5, 5) not in squares
        assert (4, 0) not in squares
        assert (4, 8) not in squares
