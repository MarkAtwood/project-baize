"""Tests for Chess: setup, piece movement (pseudo-legal), and move execution.

Foundation layer covering:
  - Standard position setup (32 pieces)
  - Pseudo-legal move generation for king, queen, rook, bishop, knight, pawn
  - Move execution with captures, turn advancement, and pawn promotion
  - En passant capture and expiration
  - NO castling (separate issue)
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
)
from baize.state import GameResult


# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "chess.json"


def _load_chess() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Direction vectors
# ---------------------------------------------------------------------------

ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ADJACENT = ORTHO + DIAG
KNIGHT_JUMPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]


def _opponent_of(player: str) -> str:
    return "black" if player == "white" else "white"


# ---------------------------------------------------------------------------
# ChessGame helper
# ---------------------------------------------------------------------------

class ChessGame:
    """Chess game driver -- foundation: setup + basic piece movement."""

    def __init__(self) -> None:
        defn = _load_chess()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.has_moved: set[ComponentId] = set()
        self.en_passant_target: tuple[int, int] | None = None
        self.halfmove_clock: int = 0
        self.position_history: list[str] = []
        self._setup_standard_position()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
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

    def _setup_standard_position(self) -> None:
        """Place all 32 pieces in standard chess opening position.

        Row 0 (rank 1): white back rank  R,N,B,Q,K,B,N,R
        Row 1 (rank 2): white pawns
        Row 6 (rank 7): black pawns
        Row 7 (rank 8): black back rank  R,N,B,Q,K,B,N,R
        """
        back_rank = ["rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook"]

        for col, piece_type in enumerate(back_rank):
            self._place(col, 0, piece_type, "white")

        for col in range(8):
            self._place(col, 1, "pawn", "white")

        for col in range(8):
            self._place(col, 6, "pawn", "black")

        for col, piece_type in enumerate(back_rank):
            self._place(col, 7, piece_type, "black")

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
        """Remove all pieces from the board."""
        for r in range(8):
            for c in range(8):
                self.board.grid_set(c, r, None)

    def _clear_and_place(self, pieces: list[tuple[int, int, str, str]]) -> None:
        """Clear the board and place specific pieces.

        Each tuple is (col, row, piece_type, owner).
        """
        self._clear_board()
        for col, row, piece_type, owner in pieces:
            self._place(col, row, piece_type, owner)

    def _pseudo_legal_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Generate moves for the piece at (col, row) WITHOUT check validation.

        Covers king, queen, rook, bishop, knight, pawn.
        """
        info = self.piece_at(col, row)
        if info is None:
            return []
        piece_type, owner = info

        if piece_type == "king":
            return self._king_moves(col, row, owner)
        elif piece_type == "queen":
            return self._slide_moves(col, row, owner, ADJACENT)
        elif piece_type == "rook":
            return self._slide_moves(col, row, owner, ORTHO)
        elif piece_type == "bishop":
            return self._slide_moves(col, row, owner, DIAG)
        elif piece_type == "knight":
            return self._knight_moves(col, row, owner)
        elif piece_type == "pawn":
            return self._pawn_moves(col, row, owner)
        else:
            return []

    def _king_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """King: 1 step in all 8 directions, blocked by friendly pieces, plus castling."""
        moves = []
        for dc, dr in ADJACENT:
            nc, nr = col + dc, row + dr
            if 0 <= nc < 8 and 0 <= nr < 8:
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        moves.extend(self._castling_moves(col, row))
        return moves

    def _castling_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Generate castling moves for the king at (col, row).

        Returns target squares the king can castle to (2 squares left or right).
        Checks: king/rook not moved, path clear, not in/through/into check.
        """
        cid = self.board.grid_get(col, row)
        if cid is None:
            return []
        comp = self.session.runtime.components.get(cid)
        if comp is None:
            return []
        owner = comp.owner
        opponent = _opponent_of(owner)

        # King must not have moved
        if cid in self.has_moved:
            return []

        # King must not be in check
        if self.is_attacked(col, row, opponent):
            return []

        moves: list[tuple[int, int]] = []

        # Kingside: rook at (7, row)
        rook_cid_k = self.board.grid_get(7, row)
        if rook_cid_k is not None and rook_cid_k not in self.has_moved:
            rook_comp = self.session.runtime.components.get(rook_cid_k)
            if (rook_comp is not None
                    and rook_comp.component_type == "rook"
                    and rook_comp.owner == owner):
                # Squares between king and rook must be empty (cols 5, 6)
                if self.piece_at(5, row) is None and self.piece_at(6, row) is None:
                    # King must not pass through or land in check
                    if (not self.is_attacked(5, row, opponent)
                            and not self.is_attacked(6, row, opponent)):
                        moves.append((6, row))

        # Queenside: rook at (0, row)
        rook_cid_q = self.board.grid_get(0, row)
        if rook_cid_q is not None and rook_cid_q not in self.has_moved:
            rook_comp = self.session.runtime.components.get(rook_cid_q)
            if (rook_comp is not None
                    and rook_comp.component_type == "rook"
                    and rook_comp.owner == owner):
                # Squares between king and rook must be empty (cols 1, 2, 3)
                if (self.piece_at(1, row) is None
                        and self.piece_at(2, row) is None
                        and self.piece_at(3, row) is None):
                    # King must not pass through or land in check (cols 3, 2)
                    if (not self.is_attacked(3, row, opponent)
                            and not self.is_attacked(2, row, opponent)):
                        moves.append((2, row))

        return moves

    def _slide_moves(
        self, col: int, row: int, owner: str, directions: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Slide along directions until blocked or capturing."""
        moves = []
        for dc, dr in directions:
            nc, nr = col + dc, row + dr
            while 0 <= nc < 8 and 0 <= nr < 8:
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
        """Knight: leap in L-shapes, not blocked by intervening pieces."""
        moves = []
        for dc, dr in KNIGHT_JUMPS:
            nc, nr = col + dc, row + dr
            if 0 <= nc < 8 and 0 <= nr < 8:
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _pawn_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Pawn: push forward, double push from start, diagonal capture."""
        moves = []
        direction = 1 if owner == "white" else -1
        start_rank = 1 if owner == "white" else 6

        # Single push forward
        nr = row + direction
        if 0 <= nr < 8 and self.piece_at(col, nr) is None:
            moves.append((col, nr))
            # Double push from starting rank
            nr2 = row + 2 * direction
            if row == start_rank and 0 <= nr2 < 8 and self.piece_at(col, nr2) is None:
                moves.append((col, nr2))

        # Diagonal captures
        for dc in (-1, 1):
            nc = col + dc
            nr = row + direction
            if 0 <= nc < 8 and 0 <= nr < 8:
                target = self.piece_at(nc, nr)
                if target is not None and target[1] != owner:
                    moves.append((nc, nr))

        # En passant captures
        for dc in (-1, 1):
            nc = col + dc
            nr = row + direction
            if 0 <= nc < 8 and 0 <= nr < 8:
                if self.en_passant_target == (nc, nr):
                    moves.append((nc, nr))

        return moves

    def move(self, from_col: int, from_row: int, to_col: int, to_row: int, promote_to: str = "queen") -> None:
        """Execute a move. Validate owner, pick up, capture if enemy, place, advance turn."""
        player = self.current_player()
        info = self.piece_at(from_col, from_row)
        if info is None:
            raise ValueError(f"no piece at ({from_col},{from_row})")
        if info[1] != player:
            raise ValueError(
                f"piece at ({from_col},{from_row}) belongs to {info[1]}, not {player}"
            )

        # Halfmove clock: reset on pawn move or capture, otherwise increment
        is_capture = self.piece_at(to_col, to_row) is not None
        is_pawn_move = info[0] == "pawn"
        # Also count en passant as a capture
        if is_pawn_move and from_col != to_col and not is_capture:
            if self.en_passant_target == (to_col, to_row if info[1] == "white" else to_row):
                is_capture = True
        if is_pawn_move or is_capture:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        # Pick up piece
        cid = self.board.grid_get(from_col, from_row)
        self.board.grid_set(from_col, from_row, None)

        # Capture if enemy present
        target_cid = self.board.grid_get(to_col, to_row)
        if target_cid is not None:
            self.board.grid_set(to_col, to_row, None)

        # Place at destination
        self.board.grid_set(to_col, to_row, cid)

        # Castling: king moves 2 squares horizontally -> also move the rook
        assert cid is not None
        comp = self.session.runtime.components.get(cid)
        if comp is not None and comp.component_type == "king" and abs(to_col - from_col) == 2:
            if to_col == 6:  # kingside
                rook_cid = self.board.grid_get(7, from_row)
                self.board.grid_set(7, from_row, None)
                self.board.grid_set(5, from_row, rook_cid)
                if rook_cid is not None:
                    self.has_moved.add(rook_cid)
            elif to_col == 2:  # queenside
                rook_cid = self.board.grid_get(0, from_row)
                self.board.grid_set(0, from_row, None)
                self.board.grid_set(3, from_row, rook_cid)
                if rook_cid is not None:
                    self.has_moved.add(rook_cid)

        # Track piece movement for castling rights
        self.has_moved.add(cid)

        # Determine if moving piece is a pawn (before promotion mutates type)
        is_pawn = comp is not None and comp.component_type == "pawn"

        # En passant capture: pawn moves diagonally to empty square
        if is_pawn and from_col != to_col and target_cid is None:
            # Captured pawn is at (to_col, from_row)
            self.board.grid_set(to_col, from_row, None)

        # Pawn promotion
        if is_pawn and comp is not None:
            promotion_rank = 7 if comp.owner == "white" else 0
            if to_row == promotion_rank:
                comp.component_type = promote_to

        # En passant target: set if pawn double-pushed, otherwise clear
        if is_pawn and abs(to_row - from_row) == 2:
            self.en_passant_target = (from_col, (from_row + to_row) // 2)
        else:
            self.en_passant_target = None

        # Advance turn
        self.session.advance_turn()

        # Detect checkmate / stalemate for the next player
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

        # Record position for threefold repetition (after turn advance)
        self.position_history.append(self._position_key())

        # Draw: fifty-move rule (100 half-moves without pawn move or capture)
        if self.session.runtime.status != "finished":
            if self.halfmove_clock >= 100:
                self.session.runtime.status = "finished"
                self.session.runtime.result = GameResult(
                    outcome="draw",
                    condition="fifty_move_rule",
                )

        # Draw: threefold repetition
        if self.session.runtime.status != "finished":
            current_key = self.position_history[-1]
            if self.position_history.count(current_key) >= 3:
                self.session.runtime.status = "finished"
                self.session.runtime.result = GameResult(
                    outcome="draw",
                    condition="threefold_repetition",
                )

        # Draw: insufficient material
        if self.session.runtime.status != "finished":
            if self.is_insufficient_material():
                self.session.runtime.status = "finished"
                self.session.runtime.result = GameResult(
                    outcome="draw",
                    condition="insufficient_material",
                )

    # ------------------------------------------------------------------
    # Check, checkmate, stalemate detection
    # ------------------------------------------------------------------

    def _find_king(self, player: str) -> tuple[int, int] | None:
        """Find the king position for a player by scanning the board."""
        for r in range(8):
            for c in range(8):
                info = self.piece_at(c, r)
                if info is not None and info[0] == "king" and info[1] == player:
                    return (c, r)
        return None

    def is_attacked(self, col: int, row: int, by_player: str) -> bool:
        """Check if (col, row) is attacked by any piece belonging to by_player.

        Checks orthogonal sliders (rook, queen), diagonal sliders (bishop, queen),
        knights, king adjacency, and pawn diagonal attacks.
        """
        # Orthogonal sliding attacks (rook, queen)
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            while 0 <= nc < 8 and 0 <= nr < 8:
                info = self.piece_at(nc, nr)
                if info is not None:
                    if info[1] == by_player and info[0] in ("rook", "queen"):
                        return True
                    break  # blocked by any piece
                nc += dc
                nr += dr

        # Diagonal sliding attacks (bishop, queen)
        for dc, dr in DIAG:
            nc, nr = col + dc, row + dr
            while 0 <= nc < 8 and 0 <= nr < 8:
                info = self.piece_at(nc, nr)
                if info is not None:
                    if info[1] == by_player and info[0] in ("bishop", "queen"):
                        return True
                    break  # blocked by any piece
                nc += dc
                nr += dr

        # Knight attacks
        for dc, dr in KNIGHT_JUMPS:
            nc, nr = col + dc, row + dr
            if 0 <= nc < 8 and 0 <= nr < 8:
                info = self.piece_at(nc, nr)
                if info is not None and info[1] == by_player and info[0] == "knight":
                    return True

        # King adjacency (prevents kings from touching)
        for dc, dr in ADJACENT:
            nc, nr = col + dc, row + dr
            if 0 <= nc < 8 and 0 <= nr < 8:
                info = self.piece_at(nc, nr)
                if info is not None and info[1] == by_player and info[0] == "king":
                    return True

        # Pawn attacks
        # White pawns attack diagonally UP: a white pawn at (pc, pr) attacks
        # (pc-1, pr+1) and (pc+1, pr+1). So (col, row) is attacked by a white
        # pawn if there is one at (col-1, row-1) or (col+1, row-1).
        # Black pawns attack diagonally DOWN: (col-1, row+1) or (col+1, row+1).
        if by_player == "white":
            pawn_row = row - 1  # white pawn would be one row below
            for dc in (-1, 1):
                pc = col + dc
                if 0 <= pc < 8 and 0 <= pawn_row < 8:
                    info = self.piece_at(pc, pawn_row)
                    if info is not None and info[1] == "white" and info[0] == "pawn":
                        return True
        else:
            pawn_row = row + 1  # black pawn would be one row above
            for dc in (-1, 1):
                pc = col + dc
                if 0 <= pc < 8 and 0 <= pawn_row < 8:
                    info = self.piece_at(pc, pawn_row)
                    if info is not None and info[1] == "black" and info[0] == "pawn":
                        return True

        return False

    def in_check(self, player: str) -> bool:
        """Is the player's king currently attacked?"""
        pos = self._find_king(player)
        if pos is None:
            return False
        return self.is_attacked(pos[0], pos[1], _opponent_of(player))

    def _try_move(self, fc: int, fr: int, tc: int, tr: int) -> tuple[int, int, int, int, ComponentId | None, ComponentId | None]:
        """Temporarily make a move. Returns undo info."""
        piece_cid = self.board.grid_get(fc, fr)
        captured_cid = self.board.grid_get(tc, tr)
        self.board.grid_set(fc, fr, None)
        self.board.grid_set(tc, tr, piece_cid)
        return (fc, fr, tc, tr, piece_cid, captured_cid)

    def _undo_move(self, undo: tuple[int, int, int, int, ComponentId | None, ComponentId | None]) -> None:
        """Undo a temporary move."""
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
        """Player is in check AND has no legal moves."""
        if not self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    def is_stalemate(self, player: str) -> bool:
        """Player is NOT in check AND has no legal moves."""
        if self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    def _has_no_legal_moves(self, player: str) -> bool:
        """Return True if player has no legal moves at all."""
        for r in range(8):
            for c in range(8):
                info = self.piece_at(c, r)
                if info is not None and info[1] == player:
                    if len(self.legal_moves(c, r)) > 0:
                        return False
        return True

    def _position_key(self) -> str:
        """Create a hashable string representing the current position.

        Includes piece positions/types/owners, current player, castling rights,
        and en passant target.
        """
        parts: list[str] = []
        # Board state
        for r in range(8):
            for c in range(8):
                info = self.piece_at(c, r)
                if info is not None:
                    parts.append(f"{c},{r},{info[0]},{info[1]}")
        # Current player to move
        parts.append(f"turn:{self.current_player()}")
        # Castling rights: which kings/rooks haven't moved
        # Check white king (4,0), white rooks (0,0) and (7,0)
        # Check black king (4,7), black rooks (0,7) and (7,7)
        for label, col, row in [
            ("wK", 4, 0), ("wRa", 0, 0), ("wRh", 7, 0),
            ("bK", 4, 7), ("bRa", 0, 7), ("bRh", 7, 7),
        ]:
            cid = self.board.grid_get(col, row)
            if cid is not None and cid not in self.has_moved:
                comp = self.session.runtime.components.get(cid)
                if comp is not None:
                    expected = "king" if "K" in label else "rook"
                    expected_owner = "white" if label.startswith("w") else "black"
                    if comp.component_type == expected and comp.owner == expected_owner:
                        parts.append(f"castle:{label}")
        # En passant target
        if self.en_passant_target is not None:
            parts.append(f"ep:{self.en_passant_target[0]},{self.en_passant_target[1]}")
        return "|".join(parts)

    def is_insufficient_material(self) -> bool:
        """Check if neither side has sufficient material to checkmate.

        Draw conditions:
        - K vs K
        - K+B vs K
        - K+N vs K
        - K+B vs K+B (same color bishops)
        """
        white_pieces: list[tuple[str, int, int]] = []
        black_pieces: list[tuple[str, int, int]] = []
        for r in range(8):
            for c in range(8):
                info = self.piece_at(c, r)
                if info is not None:
                    if info[1] == "white":
                        white_pieces.append((info[0], c, r))
                    else:
                        black_pieces.append((info[0], c, r))

        white_non_king = [(p, c, r) for p, c, r in white_pieces if p != "king"]
        black_non_king = [(p, c, r) for p, c, r in black_pieces if p != "king"]

        # K vs K
        if len(white_non_king) == 0 and len(black_non_king) == 0:
            return True

        # K+B vs K or K+N vs K
        if len(white_non_king) == 1 and len(black_non_king) == 0:
            if white_non_king[0][0] in ("bishop", "knight"):
                return True
        if len(black_non_king) == 1 and len(white_non_king) == 0:
            if black_non_king[0][0] in ("bishop", "knight"):
                return True

        # K+B vs K+B (same color bishops)
        if (len(white_non_king) == 1 and len(black_non_king) == 1
                and white_non_king[0][0] == "bishop"
                and black_non_king[0][0] == "bishop"):
            # Bishop square color: (col + row) % 2
            w_color = (white_non_king[0][1] + white_non_king[0][2]) % 2
            b_color = (black_non_king[0][1] + black_non_king[0][2]) % 2
            if w_color == b_color:
                return True

        return False


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_chess()
        assert defn.game.name == "Chess"

    def test_two_players(self) -> None:
        defn = _load_chess()
        assert defn.game.players == ["white", "black"]

    def test_8x8_board(self) -> None:
        defn = _load_chess()
        assert defn.zones["board"].dimensions == [8, 8]


# ---------------------------------------------------------------------------
# Tests: setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_32_pieces_total(self) -> None:
        game = ChessGame()
        count = 0
        for r in range(8):
            for c in range(8):
                if game.piece_at(c, r) is not None:
                    count += 1
        assert count == 32

    def test_white_king_at_e1(self) -> None:
        game = ChessGame()
        assert game.piece_at(4, 0) == ("king", "white")

    def test_black_king_at_e8(self) -> None:
        game = ChessGame()
        assert game.piece_at(4, 7) == ("king", "black")

    def test_white_pawns_on_row_1(self) -> None:
        game = ChessGame()
        for col in range(8):
            assert game.piece_at(col, 1) == ("pawn", "white")

    def test_black_pawns_on_row_6(self) -> None:
        game = ChessGame()
        for col in range(8):
            assert game.piece_at(col, 6) == ("pawn", "black")


# ---------------------------------------------------------------------------
# Tests: king movement
# ---------------------------------------------------------------------------


class TestKingMovement:
    def test_king_center_empty_board(self) -> None:
        """King in center of empty board has 8 moves."""
        game = ChessGame()
        game._clear_and_place([(4, 4, "king", "white")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 8

    def test_king_corner(self) -> None:
        """King in corner has 3 moves."""
        game = ChessGame()
        game._clear_and_place([(0, 0, "king", "white")])
        moves = game._pseudo_legal_moves(0, 0)
        assert len(moves) == 3

    def test_king_blocked_by_friendly(self) -> None:
        """King surrounded by friendly pieces has no moves."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "king", "white"),
            (3, 3, "pawn", "white"),
            (4, 3, "pawn", "white"),
            (5, 3, "pawn", "white"),
            (3, 4, "pawn", "white"),
            (5, 4, "pawn", "white"),
            (3, 5, "pawn", "white"),
            (4, 5, "pawn", "white"),
            (5, 5, "pawn", "white"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0


# ---------------------------------------------------------------------------
# Tests: rook movement
# ---------------------------------------------------------------------------


class TestRookMovement:
    def test_rook_center_empty_board(self) -> None:
        """Rook in center of empty board has 14 moves."""
        game = ChessGame()
        game._clear_and_place([(4, 4, "rook", "white")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 14

    def test_rook_blocked_by_friendly(self) -> None:
        """Rook blocked by friendly pieces on all four sides."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "rook", "white"),
            (4, 5, "pawn", "white"),
            (4, 3, "pawn", "white"),
            (5, 4, "pawn", "white"),
            (3, 4, "pawn", "white"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0

    def test_rook_captures_enemy(self) -> None:
        """Rook can capture an enemy piece but stops there."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "rook", "white"),
            (4, 6, "pawn", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        # Up: 4,5 and 4,6(capture) = 2; Down: 4,3 4,2 4,1 4,0 = 4
        # Right: 5,4 6,4 7,4 = 3; Left: 3,4 2,4 1,4 0,4 = 4
        assert (4, 6) in moves  # can capture
        assert (4, 7) not in moves  # blocked after capture
        assert len(moves) == 13


# ---------------------------------------------------------------------------
# Tests: bishop movement
# ---------------------------------------------------------------------------


class TestBishopMovement:
    def test_bishop_center_empty_board(self) -> None:
        """Bishop in center of empty board has 13 moves."""
        game = ChessGame()
        game._clear_and_place([(4, 4, "bishop", "white")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 13

    def test_bishop_blocked_by_friendly(self) -> None:
        """Bishop blocked by friendly pieces on all diagonals."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "bishop", "white"),
            (5, 5, "pawn", "white"),
            (5, 3, "pawn", "white"),
            (3, 5, "pawn", "white"),
            (3, 3, "pawn", "white"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0

    def test_bishop_captures_enemy(self) -> None:
        """Bishop can capture an enemy piece but stops there."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "bishop", "white"),
            (6, 6, "pawn", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (6, 6) in moves  # can capture
        assert (7, 7) not in moves  # blocked after capture
        # (5,5), (6,6) = 2; (5,3),(6,2),(7,1) = 3; (3,5),(2,6),(1,7) = 3; (3,3),(2,2),(1,1),(0,0) = 4
        assert len(moves) == 12


# ---------------------------------------------------------------------------
# Tests: queen movement
# ---------------------------------------------------------------------------


class TestQueenMovement:
    def test_queen_center_empty_board(self) -> None:
        """Queen in center of empty board has 27 moves (14 ortho + 13 diag)."""
        game = ChessGame()
        game._clear_and_place([(4, 4, "queen", "white")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 27

    def test_queen_blocked(self) -> None:
        """Queen surrounded by friendly pieces has no moves."""
        game = ChessGame()
        game._clear_and_place([
            (4, 4, "queen", "white"),
            (3, 3, "pawn", "white"),
            (4, 3, "pawn", "white"),
            (5, 3, "pawn", "white"),
            (3, 4, "pawn", "white"),
            (5, 4, "pawn", "white"),
            (3, 5, "pawn", "white"),
            (4, 5, "pawn", "white"),
            (5, 5, "pawn", "white"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 0


# ---------------------------------------------------------------------------
# Tests: knight movement
# ---------------------------------------------------------------------------


class TestKnightMovement:
    def test_knight_center(self) -> None:
        """Knight in center of empty board has 8 moves."""
        game = ChessGame()
        game._clear_and_place([(4, 4, "knight", "white")])
        moves = game._pseudo_legal_moves(4, 4)
        assert len(moves) == 8

    def test_knight_corner(self) -> None:
        """Knight in corner has 2 moves."""
        game = ChessGame()
        game._clear_and_place([(0, 0, "knight", "white")])
        moves = game._pseudo_legal_moves(0, 0)
        assert len(moves) == 2

    def test_knight_jumps_over_pieces(self) -> None:
        """Knight is not blocked by intervening pieces."""
        game = ChessGame()
        # Place knight at center surrounded by friendly pieces on all adjacent squares
        game._clear_and_place([
            (4, 4, "knight", "white"),
            (3, 3, "pawn", "white"),
            (4, 3, "pawn", "white"),
            (5, 3, "pawn", "white"),
            (3, 4, "pawn", "white"),
            (5, 4, "pawn", "white"),
            (3, 5, "pawn", "white"),
            (4, 5, "pawn", "white"),
            (5, 5, "pawn", "white"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        # Knight leaps over adjacent blockers; all 8 L-destinations are empty
        assert len(moves) == 8


# ---------------------------------------------------------------------------
# Tests: move execution
# ---------------------------------------------------------------------------


class TestMoveExecution:
    def test_move_piece(self) -> None:
        """Move a piece: old cell empty, new cell occupied."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
        ])
        game.move(0, 0, 0, 4)
        assert game.piece_at(0, 0) is None
        assert game.piece_at(0, 4) == ("rook", "white")

    def test_capture_enemy(self) -> None:
        """Moving to a square with an enemy piece captures it."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
            (0, 5, "pawn", "black"),
        ])
        game.move(0, 0, 0, 5)
        assert game.piece_at(0, 5) == ("rook", "white")
        # Black pawn is gone — verify no second piece at destination
        count = 0
        for r in range(8):
            for c in range(8):
                info = game.piece_at(c, r)
                if info is not None and info == ("pawn", "black"):
                    count += 1
        assert count == 0

    def test_turn_advances(self) -> None:
        """Turn advances from white to black after a move."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
        ])
        assert game.current_player() == "white"
        game.move(0, 0, 0, 4)
        assert game.current_player() == "black"

    def test_cannot_move_opponent_piece(self) -> None:
        """Cannot move a piece belonging to the opponent."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 7, "rook", "black"),
        ])
        with pytest.raises(ValueError, match="belongs to black"):
            game.move(0, 7, 0, 4)


# ---------------------------------------------------------------------------
# Tests: pawn movement
# ---------------------------------------------------------------------------


class TestPawnMovement:
    def test_white_pawn_starting_rank(self) -> None:
        """White pawn on starting rank (row 1) can push 1 or 2 forward."""
        game = ChessGame()
        game._clear_and_place([(4, 1, "pawn", "white")])
        moves = game._pseudo_legal_moves(4, 1)
        assert sorted(moves) == sorted([(4, 2), (4, 3)])

    def test_white_pawn_not_starting_rank(self) -> None:
        """White pawn NOT on starting rank can only push 1 forward."""
        game = ChessGame()
        game._clear_and_place([(4, 3, "pawn", "white")])
        moves = game._pseudo_legal_moves(4, 3)
        assert moves == [(4, 4)]

    def test_pawn_blocked_ahead(self) -> None:
        """Pawn blocked by a piece directly ahead has 0 forward moves."""
        game = ChessGame()
        game._clear_and_place([
            (4, 1, "pawn", "white"),
            (4, 2, "pawn", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 1)
        # Blocked ahead — no push moves, and no diagonal captures either
        # (enemy is straight ahead, not diagonal)
        assert moves == []

    def test_pawn_diagonal_capture(self) -> None:
        """Pawn captures diagonally only when an enemy piece is present."""
        game = ChessGame()
        game._clear_and_place([
            (4, 3, "pawn", "white"),
            (3, 4, "pawn", "black"),
            (5, 4, "pawn", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 3)
        assert sorted(moves) == sorted([(4, 4), (3, 4), (5, 4)])

    def test_black_pawn_moves_opposite(self) -> None:
        """Black pawn moves in the -row direction."""
        game = ChessGame()
        game._clear_and_place([(4, 6, "pawn", "black")])
        moves = game._pseudo_legal_moves(4, 6)
        assert sorted(moves) == sorted([(4, 5), (4, 4)])

    def test_pawn_cannot_push_off_board(self) -> None:
        """A white pawn on row 7 (should have promoted) has no forward moves."""
        game = ChessGame()
        game._clear_and_place([(4, 7, "pawn", "white")])
        moves = game._pseudo_legal_moves(4, 7)
        assert moves == []


# ---------------------------------------------------------------------------
# Tests: pawn promotion
# ---------------------------------------------------------------------------


class TestPromotion:
    def test_white_pawn_promotes_to_queen(self) -> None:
        """White pawn on row 6 moves to row 7 and promotes to queen."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 6, "pawn", "white"),
        ])
        game.move(0, 6, 0, 7)
        assert game.piece_at(0, 7) == ("queen", "white")

    def test_promotion_with_explicit_choice(self) -> None:
        """Promotion can specify a piece other than queen."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 6, "pawn", "white"),
        ])
        game.move(0, 6, 0, 7, promote_to="knight")
        assert game.piece_at(0, 7) == ("knight", "white")

    def test_promoted_piece_retains_owner(self) -> None:
        """Promoted piece keeps the original owner."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 1, "pawn", "black"),
        ])
        # White moves king first to pass turn to black
        game.move(4, 0, 3, 0)
        # Black pawn on row 1 pushes to row 0
        game.move(3, 1, 3, 0)
        assert game.piece_at(3, 0) == ("queen", "black")


# ---------------------------------------------------------------------------
# Tests: is_attacked
# ---------------------------------------------------------------------------


class TestIsAttacked:
    def test_rook_attacks_along_rank(self) -> None:
        """Rook attacks squares along its rank and file."""
        game = ChessGame()
        game._clear_and_place([
            (0, 0, "rook", "white"),
            (4, 4, "king", "black"),
        ])
        # Rook at (0,0) attacks along col 0 and row 0
        assert game.is_attacked(0, 5, "white") is True  # same file
        assert game.is_attacked(5, 0, "white") is True  # same rank
        assert game.is_attacked(3, 3, "white") is False  # not on rank or file

    def test_bishop_attacks_along_diagonal(self) -> None:
        """Bishop attacks squares along its diagonals."""
        game = ChessGame()
        game._clear_and_place([
            (2, 2, "bishop", "white"),
            (4, 4, "king", "black"),
        ])
        assert game.is_attacked(4, 4, "white") is True  # on diagonal
        assert game.is_attacked(0, 0, "white") is True  # on diagonal
        assert game.is_attacked(2, 5, "white") is False  # not on any diagonal

    def test_knight_attacks_via_l_shape(self) -> None:
        """Knight attacks via L-shaped jumps."""
        game = ChessGame()
        game._clear_and_place([
            (3, 3, "knight", "white"),
            (7, 7, "king", "black"),
        ])
        # All 8 L-shape destinations from (3,3)
        for tc, tr in [(4, 5), (5, 4), (5, 2), (4, 1), (2, 1), (1, 2), (1, 4), (2, 5)]:
            assert game.is_attacked(tc, tr, "white") is True, f"({tc},{tr}) should be attacked"
        # Not attacked: adjacent square
        assert game.is_attacked(3, 4, "white") is False

    def test_pawn_attacks_diagonally(self) -> None:
        """Pawn attacks diagonally forward (not straight ahead)."""
        game = ChessGame()
        # White pawn at (4,3) attacks (3,4) and (5,4)
        game._clear_and_place([
            (4, 3, "pawn", "white"),
            (4, 6, "pawn", "black"),
            (7, 0, "king", "white"),
            (7, 7, "king", "black"),
        ])
        assert game.is_attacked(3, 4, "white") is True  # diagonal left
        assert game.is_attacked(5, 4, "white") is True  # diagonal right
        assert game.is_attacked(4, 4, "white") is False  # straight ahead: NOT attacked
        # Black pawn at (4,6) attacks (3,5) and (5,5)
        assert game.is_attacked(3, 5, "black") is True
        assert game.is_attacked(5, 5, "black") is True
        assert game.is_attacked(4, 5, "black") is False  # straight ahead


# ---------------------------------------------------------------------------
# Tests: check detection
# ---------------------------------------------------------------------------


class TestCheck:
    def test_king_in_check_from_rook(self) -> None:
        """King is in check when a rook attacks along rank/file."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (4, 5, "rook", "white"),  # white rook on same file as black king
        ])
        assert game.in_check("black") is True
        assert game.in_check("white") is False

    def test_king_not_in_check_when_blocked(self) -> None:
        """King is not in check when a friendly piece blocks the attacker."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (4, 5, "rook", "white"),  # white rook aimed at black king
            (4, 6, "pawn", "black"),  # black pawn blocks the rook
        ])
        assert game.in_check("black") is False

    def test_pinned_piece_cannot_move(self) -> None:
        """A piece pinned to its king has no legal moves that expose the king."""
        game = ChessGame()
        # White king at e1 (4,0), white bishop at d2 (3,1), black rook at a4 (0,3)
        # The bishop is on the a4-e1 diagonal — moving it exposes the king to the rook.
        # Actually, rook attacks orthogonally. Let's use a file pin:
        # White king at (4,0), white rook at (4,3), black rook at (4,7)
        # The white rook at (4,3) is pinned along the file.
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 3, "rook", "white"),  # pinned to king along file
            (4, 7, "rook", "black"),  # pins the white rook
            (0, 7, "king", "black"),
        ])
        legal = game.legal_moves(4, 3)
        # White rook can only move along the file (4,1), (4,2), (4,4)...(4,7)
        # because moving off the file would expose the king
        for tc, tr in legal:
            assert tc == 4, f"pinned rook should only move along file, got ({tc},{tr})"
        # It should be able to move to (4,1), (4,2), (4,4), (4,5), (4,6), (4,7)
        assert len(legal) == 6


# ---------------------------------------------------------------------------
# Tests: checkmate detection
# ---------------------------------------------------------------------------


class TestCheckmate:
    def test_scholars_mate(self) -> None:
        """Scholar's mate position: white queen on f7, bishop on c4, checkmate."""
        game = ChessGame()
        # Classic scholar's mate final position (simplified):
        # Black king at e8 (4,7), white queen at f7 (5,6) delivering check,
        # white bishop at c4 (2,3) covering escape. Black pieces block other escapes.
        game._clear_and_place([
            (4, 7, "king", "black"),
            (5, 6, "queen", "white"),   # delivers check on f7
            (2, 3, "bishop", "white"),  # covers d7 escape via diagonal
            (4, 0, "king", "white"),
            # Black pieces blocking escape squares
            (3, 7, "rook", "black"),    # d8 blocked by own piece
            (5, 7, "bishop", "black"),  # f8 blocked by own piece
            (3, 6, "pawn", "black"),    # d7 blocked by own pawn
            (4, 6, "pawn", "black"),    # e7 blocked by own pawn
        ])
        # Queen at (5,6) attacks king at (4,7): diagonal.
        # King escape squares: (3,7) own rook, (3,6) own pawn,
        # (4,6) own pawn, (5,7) own bishop,
        # (5,6) queen itself — but that's the attacker, can king take?
        # Queen is protected by bishop at (2,3) via diagonal to (5,6).
        # So king can't take the queen. All escapes blocked. Checkmate.
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is True
        assert game.is_stalemate("black") is False

    def test_back_rank_mate(self) -> None:
        """Back rank mate: rook delivers checkmate on back rank."""
        game = ChessGame()
        # Black king trapped behind pawns, white rook delivers mate on rank 8
        game._clear_and_place([
            (6, 7, "king", "black"),   # g8
            (5, 6, "pawn", "black"),   # f7 — blocks escape
            (6, 6, "pawn", "black"),   # g7 — blocks escape
            (7, 6, "pawn", "black"),   # h7 — blocks escape
            (0, 7, "rook", "white"),   # a8 — delivers check along rank 8
            (4, 0, "king", "white"),
        ])
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is True

    def test_not_checkmate_when_escape_exists(self) -> None:
        """Not checkmate if the king can escape the check."""
        game = ChessGame()
        game._clear_and_place([
            (4, 7, "king", "black"),
            (4, 5, "rook", "white"),   # check along file
            (4, 0, "king", "white"),
        ])
        # King is in check from the rook, but can move to d8, f8, d7, f7, e8->blocked by check
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is False


# ---------------------------------------------------------------------------
# Tests: stalemate detection
# ---------------------------------------------------------------------------


class TestStalemate:
    def test_classic_stalemate_k_vs_kq(self) -> None:
        """Classic stalemate: lone king cornered with no legal moves, not in check."""
        game = ChessGame()
        # Black king at a8 (0,7), white queen at b6 (1,5), white king at c7... wait,
        # need to be careful. Classic stalemate:
        # Black king at a8 (0,7).
        # White queen at b6 (1,5) — controls a7, b7, b8.
        # White king at c7 (2,6) — controls b7, b6(queen), c6, d7, d6.
        # But we need queen not attacking king directly.
        # Let's use: black king h8 (7,7), white queen g6 (6,5), white king f7 (5,6).
        # Queen at g6 controls: g7, h7, h6, h5 via diag; g8 via file.
        # King at f7 controls: e6, e7, f6, g6(queen), g7, g8, e8.
        # So black king at h8: can go to g8(controlled by queen file + white king), h7(controlled by queen), g7(controlled by white king + queen).
        # Not in check at h8: queen at g6 doesn't attack h8 (not on same rank/file/diag... g6 to h8 is diagonal? (6,5)->(7,7): dc=1, dr=2, not a diagonal).
        # Actually let me just use a well-known stalemate position.
        # Simplest: Black king at a8 (0,7), White queen at c7 (2,6), White king at b5 (1,4).
        # Black king escapes: a7 (0,6) — queen controls c7->a7 via rank? No, queen at (2,6) controls row 6. (0,6) is on row 6, so yes attacked.
        # b8 (1,7) — queen at (2,6): diagonal to (1,7)? dc=-1, dr=+1 -> yes diagonal. Attacked.
        # b7 (1,6) — queen at (2,6): same row, adjacent. Attacked.
        # That's all neighbors of (0,7): (0,6), (1,6), (1,7). All attacked. King not in check.
        # Queen at (2,6) to (0,7): dc=-2, dr=+1 — not a standard attack. Good.
        game._clear_and_place([
            (0, 7, "king", "black"),
            (2, 6, "queen", "white"),
            (1, 4, "king", "white"),
        ])
        assert game.in_check("black") is False
        assert game.is_stalemate("black") is True
        assert game.is_checkmate("black") is False

    def test_not_stalemate_when_moves_exist(self) -> None:
        """Not stalemate when the player has legal moves."""
        game = ChessGame()
        game._clear_and_place([
            (4, 7, "king", "black"),
            (4, 0, "king", "white"),
            (0, 0, "queen", "white"),
        ])
        # Black king has plenty of moves available
        assert game.in_check("black") is False
        assert game.is_stalemate("black") is False


# ---------------------------------------------------------------------------
# Tests: en passant
# ---------------------------------------------------------------------------


class TestEnPassant:
    def test_white_en_passant_capture(self) -> None:
        """White pawn captures en passant after black double-pushes."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 4, "pawn", "white"),  # white pawn on row 4 (5th rank)
            (4, 6, "pawn", "black"),  # black pawn on starting rank
        ])
        # White moves king to pass turn to black
        game.move(4, 0, 3, 0)
        # Black double-pushes pawn from row 6 to row 4
        game.move(4, 6, 4, 4)
        assert game.en_passant_target == (4, 5)
        # White captures en passant
        game.move(3, 4, 4, 5)
        assert game.piece_at(4, 5) == ("pawn", "white")
        assert game.piece_at(4, 4) is None  # captured pawn removed

    def test_black_en_passant_capture(self) -> None:
        """Black pawn captures en passant after white double-pushes."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (2, 1, "pawn", "white"),  # white pawn on starting rank
            (3, 3, "pawn", "black"),  # black pawn on row 3 (4th rank)
        ])
        # White double-pushes pawn from row 1 to row 3
        game.move(2, 1, 2, 3)
        assert game.en_passant_target == (2, 2)
        # Black captures en passant
        game.move(3, 3, 2, 2)
        assert game.piece_at(2, 2) == ("pawn", "black")
        assert game.piece_at(2, 3) is None  # captured pawn removed

    def test_en_passant_expires_after_one_turn(self) -> None:
        """En passant is only available immediately after the double push."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 4, "pawn", "white"),  # white pawn on row 4
            (4, 6, "pawn", "black"),  # black pawn on starting rank
            (0, 0, "rook", "white"),  # extra piece for a waiting move
        ])
        # White moves king to pass turn
        game.move(4, 0, 3, 0)
        # Black double-pushes
        game.move(4, 6, 4, 4)
        assert game.en_passant_target == (4, 5)
        # White makes a different move (rook) instead of capturing en passant
        game.move(0, 0, 0, 1)
        # En passant target should be cleared after any move
        assert game.en_passant_target is None
        # Black moves king
        game.move(4, 7, 5, 7)
        # Now white's pawn can NOT capture en passant (target expired)
        moves = game._pseudo_legal_moves(3, 4)
        assert (4, 5) not in moves

    def test_en_passant_removes_captured_pawn(self) -> None:
        """En passant removes the captured pawn from its actual position."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (5, 4, "pawn", "white"),  # white pawn on row 4
            (6, 6, "pawn", "black"),  # black pawn on starting rank
        ])
        # White moves king to pass turn
        game.move(4, 0, 3, 0)
        # Black double-pushes pawn from (6,6) to (6,4)
        game.move(6, 6, 6, 4)
        # White captures en passant: pawn at (5,4) captures to (6,5)
        game.move(5, 4, 6, 5)
        # Verify: no pawn at the captured pawn's actual position
        assert game.piece_at(6, 4) is None
        # Verify: white pawn is at the en passant target square
        assert game.piece_at(6, 5) == ("pawn", "white")
        # Count total pawns on board — should be zero black pawns
        black_pawns = 0
        for r in range(8):
            for c in range(8):
                info = game.piece_at(c, r)
                if info is not None and info == ("pawn", "black"):
                    black_pawns += 1
        assert black_pawns == 0

    def test_no_en_passant_on_single_push(self) -> None:
        """Cannot en passant a pawn that only moved one square."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 4, "pawn", "white"),  # white pawn on row 4
            (4, 5, "pawn", "black"),  # black pawn on row 5 (already advanced)
        ])
        # White moves king to pass turn
        game.move(4, 0, 3, 0)
        # Black single-pushes pawn from row 5 to row 4
        game.move(4, 5, 4, 4)
        # No en passant target should be set (only single push)
        assert game.en_passant_target is None
        # White pawn should not have en passant as a valid move
        moves = game._pseudo_legal_moves(3, 4)
        assert (4, 5) not in moves


# ---------------------------------------------------------------------------
# Tests: castling
# ---------------------------------------------------------------------------


class TestCastling:
    def test_white_kingside_castle(self) -> None:
        """White king e1->g1, rook h1->f1."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (4, 7, "king", "black"),
        ])
        moves = game.legal_moves(4, 0)
        assert (6, 0) in moves
        game.move(4, 0, 6, 0)
        assert game.piece_at(6, 0) == ("king", "white")
        assert game.piece_at(5, 0) == ("rook", "white")
        assert game.piece_at(4, 0) is None
        assert game.piece_at(7, 0) is None

    def test_white_queenside_castle(self) -> None:
        """White king e1->c1, rook a1->d1."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (0, 0, "rook", "white"),
            (4, 7, "king", "black"),
        ])
        moves = game.legal_moves(4, 0)
        assert (2, 0) in moves
        game.move(4, 0, 2, 0)
        assert game.piece_at(2, 0) == ("king", "white")
        assert game.piece_at(3, 0) == ("rook", "white")
        assert game.piece_at(4, 0) is None
        assert game.piece_at(0, 0) is None

    def test_cannot_castle_king_moved(self) -> None:
        """Castling forbidden after king has moved."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (4, 7, "king", "black"),
        ])
        # Move king away then back
        game.move(4, 0, 3, 0)  # white king d1
        game.move(4, 7, 3, 7)  # black king d8
        game.move(3, 0, 4, 0)  # white king back to e1
        game.move(3, 7, 4, 7)  # black king back to e8
        # King has moved, castling should be gone
        moves = game.legal_moves(4, 0)
        assert (6, 0) not in moves

    def test_cannot_castle_rook_moved(self) -> None:
        """Castling forbidden after rook has moved."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (4, 7, "king", "black"),
        ])
        # Move rook away then back
        game.move(7, 0, 7, 4)  # white rook h5
        game.move(4, 7, 3, 7)  # black king d8
        game.move(7, 4, 7, 0)  # white rook back to h1
        game.move(3, 7, 4, 7)  # black king back to e8
        # Rook has moved, castling should be gone
        moves = game.legal_moves(4, 0)
        assert (6, 0) not in moves

    def test_cannot_castle_through_check(self) -> None:
        """Castling forbidden when f1 is attacked (king passes through check)."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (4, 7, "king", "black"),
            (5, 7, "rook", "black"),  # attacks f1 (col 5, row 0)
        ])
        moves = game.legal_moves(4, 0)
        assert (6, 0) not in moves

    def test_cannot_castle_while_in_check(self) -> None:
        """Castling forbidden when king is currently in check."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (4, 7, "king", "black"),
            (4, 5, "rook", "black"),  # checks white king along file
        ])
        moves = game.legal_moves(4, 0)
        assert (6, 0) not in moves

    def test_cannot_castle_pieces_between(self) -> None:
        """Castling forbidden when pieces are between king and rook."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (7, 0, "rook", "white"),
            (6, 0, "knight", "white"),  # blocks kingside castling
            (4, 7, "king", "black"),
        ])
        moves = game.legal_moves(4, 0)
        assert (6, 0) not in moves


# ---------------------------------------------------------------------------
# Tests: fifty-move rule
# ---------------------------------------------------------------------------


class TestFiftyMoveRule:
    def test_fifty_moves_draws(self) -> None:
        """Moving kings back and forth for 50 full moves (100 half-moves) is a draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
        ])
        # 100 half-moves with no pawn moves or captures triggers the rule.
        # Alternate king moves: e1<->d1 for white, e8<->d8 for black.
        for i in range(50):
            if game.session.runtime.status == "finished":
                break
            if i % 2 == 0:
                game.move(4, 0, 3, 0)  # white e1->d1
                if game.session.runtime.status == "finished":
                    break
                game.move(4, 7, 3, 7)  # black e8->d8
            else:
                game.move(3, 0, 4, 0)  # white d1->e1
                if game.session.runtime.status == "finished":
                    break
                game.move(3, 7, 4, 7)  # black d8->e8
        assert game.session.runtime.status == "finished"
        assert game.session.runtime.result is not None
        assert game.session.runtime.result.outcome == "draw"

    def test_halfmove_clock_resets_on_pawn_move(self) -> None:
        """Halfmove clock resets to 0 when a pawn moves."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 1, "pawn", "white"),
        ])
        # Make some king moves to build up the clock
        game.move(4, 0, 3, 0)  # halfmove_clock = 1
        game.move(4, 7, 3, 7)  # halfmove_clock = 2
        game.move(3, 0, 4, 0)  # halfmove_clock = 3
        game.move(3, 7, 4, 7)  # halfmove_clock = 4
        assert game.halfmove_clock == 4
        # Pawn move resets the clock
        game.move(0, 1, 0, 2)
        assert game.halfmove_clock == 0

    def test_halfmove_clock_resets_on_capture(self) -> None:
        """Halfmove clock resets to 0 on a capture."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
            (0, 5, "pawn", "black"),
        ])
        # Build up the clock
        game.move(4, 0, 3, 0)  # halfmove_clock = 1
        game.move(4, 7, 3, 7)  # halfmove_clock = 2
        assert game.halfmove_clock == 2
        # Capture resets the clock
        game.move(0, 0, 0, 5)  # rook captures pawn
        assert game.halfmove_clock == 0


# ---------------------------------------------------------------------------
# Tests: threefold repetition
# ---------------------------------------------------------------------------


class TestThreefoldRepetition:
    def test_threefold_repetition_draws(self) -> None:
        """Same position occurring 3 times is a draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
            (0, 7, "rook", "black"),
        ])
        # Position history is recorded after each half-move. The initial
        # position (before any move) is NOT recorded. Once a rook moves,
        # its castling rights are lost even after returning, so the position
        # key after cycle 1 differs from the pre-game state.
        # Positions match after each complete cycle (4 half-moves):
        #   After cycle 1 (move 4): occurrence 1
        #   After cycle 2 (move 8): occurrence 2
        #   After cycle 3 (move 12): occurrence 3 -> DRAW
        for cycle in range(3):
            if game.session.runtime.status == "finished":
                break
            game.move(0, 0, 0, 1)  # white rook a1->a2
            if game.session.runtime.status == "finished":
                break
            game.move(0, 7, 0, 6)  # black rook a8->a7
            if game.session.runtime.status == "finished":
                break
            game.move(0, 1, 0, 0)  # white rook a2->a1
            if game.session.runtime.status == "finished":
                break
            game.move(0, 6, 0, 7)  # black rook a7->a8
        assert game.session.runtime.status == "finished"
        assert game.session.runtime.result is not None
        assert game.session.runtime.result.outcome == "draw"
        assert game.session.runtime.result.condition == "threefold_repetition"

    def test_different_positions_no_draw(self) -> None:
        """Different positions each time: no threefold repetition draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (0, 0, "rook", "white"),
            (7, 7, "rook", "black"),
        ])
        # Move pieces to different squares each time
        game.move(0, 0, 0, 1)  # white rook a1->a2
        game.move(7, 7, 7, 6)  # black rook h8->h7
        game.move(0, 1, 0, 2)  # white rook a2->a3
        game.move(7, 6, 7, 5)  # black rook h7->h6
        game.move(0, 2, 0, 3)  # white rook a3->a4
        game.move(7, 5, 7, 4)  # black rook h6->h5
        assert game.session.runtime.status != "finished"


# ---------------------------------------------------------------------------
# Tests: insufficient material
# ---------------------------------------------------------------------------


class TestInsufficientMaterial:
    def test_king_vs_king(self) -> None:
        """K vs K: insufficient material, draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
        ])
        assert game.is_insufficient_material() is True

    def test_king_knight_vs_king(self) -> None:
        """K+N vs K: insufficient material, draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 0, "knight", "white"),
        ])
        assert game.is_insufficient_material() is True

    def test_king_bishop_vs_king(self) -> None:
        """K+B vs K: insufficient material, draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (2, 0, "bishop", "white"),
        ])
        assert game.is_insufficient_material() is True

    def test_king_queen_vs_king_sufficient(self) -> None:
        """K+Q vs K: sufficient material, NOT a draw."""
        game = ChessGame()
        game._clear_and_place([
            (4, 0, "king", "white"),
            (4, 7, "king", "black"),
            (3, 0, "queen", "white"),
        ])
        assert game.is_insufficient_material() is False
