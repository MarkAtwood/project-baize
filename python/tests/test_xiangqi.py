"""Tests for Xiangqi (Chinese Chess): setup, piece movement, and game rules.

Covers:
  - Standard position setup (32 pieces)
  - Pseudo-legal move generation for all 7 piece types
  - Palace confinement (general, advisor)
  - River restriction (elephant)
  - Elephant blocking (intervening diagonal piece)
  - Horse blocking (intervening orthogonal piece)
  - Cannon movement (slide to empty, hop-capture over exactly 1 screen)
  - Soldier forward-only before river, lateral after crossing
  - Flying general rule (generals cannot face on open file)
  - Check, checkmate, and stalemate detection
  - Move execution with captures and turn advancement
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
# Constants
# ---------------------------------------------------------------------------

WIDTH = 9
HEIGHT = 10
ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# Palace bounds (inclusive)
RED_PALACE_COLS = (3, 5)
RED_PALACE_ROWS = (0, 2)
BLACK_PALACE_COLS = (3, 5)
BLACK_PALACE_ROWS = (7, 9)

# River: red territory rows 0-4, black territory rows 5-9
RIVER_RED_MAX = 4
RIVER_BLACK_MIN = 5

# Horse offsets: (dx, dy, block_dx, block_dy)
# The horse moves one step orthogonally first, then one step diagonally.
# The blocking square is the orthogonal intermediate.
HORSE_MOVES = [
    (1, 2, 0, 1),
    (-1, 2, 0, 1),
    (1, -2, 0, -1),
    (-1, -2, 0, -1),
    (2, 1, 1, 0),
    (-2, 1, -1, 0),
    (2, -1, 1, 0),
    (-2, -1, -1, 0),
]

# Elephant offsets: (dx, dy, block_dx, block_dy)
# The blocking square is the diagonal midpoint.
ELEPHANT_MOVES = [
    (2, 2, 1, 1),
    (2, -2, 1, -1),
    (-2, 2, -1, 1),
    (-2, -2, -1, -1),
]


# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "xiangqi.json"


def _load_xiangqi() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _opponent_of(player: str) -> str:
    return "black" if player == "red" else "red"


# ---------------------------------------------------------------------------
# Helper: palace/river checks
# ---------------------------------------------------------------------------

def _in_palace(col: int, row: int, player: str) -> bool:
    if player == "red":
        return RED_PALACE_COLS[0] <= col <= RED_PALACE_COLS[1] and RED_PALACE_ROWS[0] <= row <= RED_PALACE_ROWS[1]
    else:
        return BLACK_PALACE_COLS[0] <= col <= BLACK_PALACE_COLS[1] and BLACK_PALACE_ROWS[0] <= row <= BLACK_PALACE_ROWS[1]


def _on_own_side(row: int, player: str) -> bool:
    if player == "red":
        return row <= RIVER_RED_MAX
    else:
        return row >= RIVER_BLACK_MIN


def _crossed_river(row: int, player: str) -> bool:
    return not _on_own_side(row, player)


# ---------------------------------------------------------------------------
# XiangqiGame helper
# ---------------------------------------------------------------------------

class XiangqiGame:
    """Xiangqi game driver with full rule enforcement."""

    def __init__(self) -> None:
        defn = _load_xiangqi()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
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
        """Place all 32 pieces in standard Xiangqi opening position.

        Red at rows 0-3 (bottom), black at rows 6-9 (top).
        Row 0: R H E A G A E H R (red back rank)
        Row 2: _ C _ _ _ _ _ C _ (red cannons)
        Row 3: S _ S _ S _ S _ S (red soldiers)
        Row 6: S _ S _ S _ S _ S (black soldiers)
        Row 7: _ C _ _ _ _ _ C _ (black cannons)
        Row 9: R H E A G A E H R (black back rank)
        """
        back_rank = ["chariot", "horse", "elephant", "advisor", "general",
                      "advisor", "elephant", "horse", "chariot"]

        # Red back rank (row 0)
        for col, piece_type in enumerate(back_rank):
            self._place(col, 0, piece_type, "red")

        # Red cannons (row 2)
        self._place(1, 2, "cannon", "red")
        self._place(7, 2, "cannon", "red")

        # Red soldiers (row 3)
        for col in range(0, 9, 2):
            self._place(col, 3, "soldier", "red")

        # Black soldiers (row 6)
        for col in range(0, 9, 2):
            self._place(col, 6, "soldier", "black")

        # Black cannons (row 7)
        self._place(1, 7, "cannon", "black")
        self._place(7, 7, "cannon", "black")

        # Black back rank (row 9)
        for col, piece_type in enumerate(back_rank):
            self._place(col, 9, piece_type, "black")

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
        for r in range(HEIGHT):
            for c in range(WIDTH):
                self.board.grid_set(c, r, None)

    def _clear_and_place(self, pieces: list[tuple[int, int, str, str]]) -> None:
        self._clear_board()
        for col, row, piece_type, owner in pieces:
            self._place(col, row, piece_type, owner)

    # ------------------------------------------------------------------
    # Move generation
    # ------------------------------------------------------------------

    def _pseudo_legal_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Generate moves for the piece at (col, row) without check validation."""
        info = self.piece_at(col, row)
        if info is None:
            return []
        piece_type, owner = info

        if piece_type == "general":
            return self._general_moves(col, row, owner)
        elif piece_type == "advisor":
            return self._advisor_moves(col, row, owner)
        elif piece_type == "elephant":
            return self._elephant_moves(col, row, owner)
        elif piece_type == "horse":
            return self._horse_moves(col, row, owner)
        elif piece_type == "chariot":
            return self._chariot_moves(col, row, owner)
        elif piece_type == "cannon":
            return self._cannon_moves(col, row, owner)
        elif piece_type == "soldier":
            return self._soldier_moves(col, row, owner)
        else:
            return []

    def _general_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """General: 1 step orthogonally, must stay in palace."""
        moves = []
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            if _in_palace(nc, nr, owner):
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _advisor_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Advisor: 1 step diagonally, must stay in palace."""
        moves = []
        for dc, dr in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
            nc, nr = col + dc, row + dr
            if _in_palace(nc, nr, owner):
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _elephant_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Elephant: diagonal 2, blocked by intervening piece, cannot cross river."""
        moves = []
        for dx, dy, bx, by in ELEPHANT_MOVES:
            nc, nr = col + dx, row + dy
            bc, br = col + bx, row + by
            if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                # Must stay on own side of river
                if not _on_own_side(nr, owner):
                    continue
                # Blocking square must be empty
                if self.piece_at(bc, br) is not None:
                    continue
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _horse_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Horse: L-shape (1 ortho + 1 diag), blocked by piece on ortho step."""
        moves = []
        for dx, dy, bx, by in HORSE_MOVES:
            nc, nr = col + dx, row + dy
            bc, br = col + bx, row + by
            if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                # Blocking square must be empty
                if self.piece_at(bc, br) is not None:
                    continue
                target = self.piece_at(nc, nr)
                if target is None or target[1] != owner:
                    moves.append((nc, nr))
        return moves

    def _chariot_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Chariot: slides orthogonally (like a chess rook)."""
        moves = []
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            while 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
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

    def _cannon_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Cannon: slides to empty squares; captures by hopping exactly 1 piece."""
        moves = []
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            # Phase 1: slide to empty squares
            while 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                target = self.piece_at(nc, nr)
                if target is None:
                    moves.append((nc, nr))
                else:
                    # Found the screen piece; now look for capture target
                    nc += dc
                    nr += dr
                    while 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                        target2 = self.piece_at(nc, nr)
                        if target2 is not None:
                            if target2[1] != owner:
                                moves.append((nc, nr))
                            break
                        nc += dc
                        nr += dr
                    break
                nc += dc
                nr += dr
        return moves

    def _soldier_moves(self, col: int, row: int, owner: str) -> list[tuple[int, int]]:
        """Soldier: forward 1 always; lateral 1 after crossing river. Never backward."""
        moves = []
        forward = 1 if owner == "red" else -1

        # Forward move
        nr = row + forward
        if 0 <= nr < HEIGHT:
            target = self.piece_at(col, nr)
            if target is None or target[1] != owner:
                moves.append((col, nr))

        # Lateral moves (only after crossing river)
        if _crossed_river(row, owner):
            for dc in (-1, 1):
                nc = col + dc
                if 0 <= nc < WIDTH:
                    target = self.piece_at(nc, row)
                    if target is None or target[1] != owner:
                        moves.append((nc, row))

        return moves

    # ------------------------------------------------------------------
    # Flying general check
    # ------------------------------------------------------------------

    def _generals_facing(self) -> bool:
        """Return True if both generals are on the same file with no pieces between."""
        red_gen = None
        black_gen = None
        for r in range(HEIGHT):
            for c in range(WIDTH):
                info = self.piece_at(c, r)
                if info is not None and info[0] == "general":
                    if info[1] == "red":
                        red_gen = (c, r)
                    else:
                        black_gen = (c, r)

        if red_gen is None or black_gen is None:
            return False

        # Must be on the same file
        if red_gen[0] != black_gen[0]:
            return False

        # Check for intervening pieces
        col = red_gen[0]
        min_row = min(red_gen[1], black_gen[1])
        max_row = max(red_gen[1], black_gen[1])
        for r in range(min_row + 1, max_row):
            if self.piece_at(col, r) is not None:
                return False

        return True

    # ------------------------------------------------------------------
    # Check detection
    # ------------------------------------------------------------------

    def _find_general(self, player: str) -> tuple[int, int] | None:
        for r in range(HEIGHT):
            for c in range(WIDTH):
                info = self.piece_at(c, r)
                if info is not None and info[0] == "general" and info[1] == player:
                    return (c, r)
        return None

    def is_attacked(self, col: int, row: int, by_player: str) -> bool:
        """Check if (col, row) is attacked by any piece of by_player."""
        # Chariot attacks (orthogonal slide)
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            while 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                info = self.piece_at(nc, nr)
                if info is not None:
                    if info[1] == by_player and info[0] == "chariot":
                        return True
                    break
                nc += dc
                nr += dr

        # Horse attacks: for each horse of by_player, check if it can reach (col, row)
        for r2 in range(HEIGHT):
            for c2 in range(WIDTH):
                info = self.piece_at(c2, r2)
                if info is not None and info[1] == by_player and info[0] == "horse":
                    for dx, dy, bx, by in HORSE_MOVES:
                        tc, tr = c2 + dx, r2 + dy
                        if tc == col and tr == row:
                            bc, br = c2 + bx, r2 + by
                            if self.piece_at(bc, br) is None:
                                return True

        # Cannon attacks (hop over exactly 1 piece)
        for dc, dr in ORTHO:
            nc, nr = col + dc, row + dr
            screen_found = False
            while 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                info = self.piece_at(nc, nr)
                if not screen_found:
                    if info is not None:
                        screen_found = True
                else:
                    if info is not None:
                        if info[1] == by_player and info[0] == "cannon":
                            return True
                        break
                nc += dc
                nr += dr

        # Soldier attacks
        # Red soldier attacks forward (row+1) and lateral if crossed river
        # Black soldier attacks forward (row-1) and lateral if crossed river
        # A soldier at (sc, sr) of by_player attacks (col, row) if:
        for r2 in range(HEIGHT):
            for c2 in range(WIDTH):
                info = self.piece_at(c2, r2)
                if info is not None and info[1] == by_player and info[0] == "soldier":
                    forward = 1 if by_player == "red" else -1
                    # Forward attack
                    if c2 == col and r2 + forward == row:
                        return True
                    # Lateral attack (only if soldier has crossed river)
                    if _crossed_river(r2, by_player):
                        if r2 == row and abs(c2 - col) == 1:
                            return True

        # General attacks (flying general: general on same file)
        # The opponent general on the same file with no pieces between
        for r2 in range(HEIGHT):
            info = self.piece_at(col, r2)
            if info is not None and info[1] == by_player and info[0] == "general":
                # Check if file is clear between
                min_r = min(r2, row)
                max_r = max(r2, row)
                clear = True
                for rr in range(min_r + 1, max_r):
                    if self.piece_at(col, rr) is not None:
                        clear = False
                        break
                if clear:
                    return True

        return False

    def in_check(self, player: str) -> bool:
        pos = self._find_general(player)
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
        """Pseudo-legal moves filtered by: no self-check, no flying general."""
        info = self.piece_at(col, row)
        if info is None:
            return []
        owner = info[1]
        result = []
        for tc, tr in self._pseudo_legal_moves(col, row):
            undo = self._try_move(col, row, tc, tr)
            # Must not leave own general in check
            if not self.in_check(owner) and not self._generals_facing():
                result.append((tc, tr))
            self._undo_move(undo)
        return result

    def _has_no_legal_moves(self, player: str) -> bool:
        for r in range(HEIGHT):
            for c in range(WIDTH):
                info = self.piece_at(c, r)
                if info is not None and info[1] == player:
                    if len(self.legal_moves(c, r)) > 0:
                        return False
        return True

    def is_checkmate(self, player: str) -> bool:
        if not self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    def is_stalemate(self, player: str) -> bool:
        if self.in_check(player):
            return False
        return self._has_no_legal_moves(player)

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def move(self, from_col: int, from_row: int, to_col: int, to_row: int) -> None:
        """Execute a move: validate owner, pick up, capture, place, advance turn."""
        player = self.current_player()
        info = self.piece_at(from_col, from_row)
        if info is None:
            raise ValueError(f"no piece at ({from_col},{from_row})")
        if info[1] != player:
            raise ValueError(
                f"piece at ({from_col},{from_row}) belongs to {info[1]}, not {player}"
            )

        # Pick up piece
        cid = self.board.grid_get(from_col, from_row)
        self.board.grid_set(from_col, from_row, None)

        # Capture if enemy present
        target_cid = self.board.grid_get(to_col, to_row)
        if target_cid is not None:
            self.board.grid_set(to_col, to_row, None)

        # Place at destination
        self.board.grid_set(to_col, to_row, cid)

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
                outcome="win",
                winner=_opponent_of(next_player),
                condition="stalemate",
            )


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_xiangqi()
        assert defn.game.name == "Xiangqi"

    def test_two_players(self) -> None:
        defn = _load_xiangqi()
        assert defn.game.players == ["red", "black"]

    def test_9x10_board(self) -> None:
        defn = _load_xiangqi()
        assert defn.zones["board"].dimensions == [9, 10]

    def test_perfect_information(self) -> None:
        defn = _load_xiangqi()
        assert defn.game.information == "perfect"

    def test_seven_component_types(self) -> None:
        defn = _load_xiangqi()
        expected = {"general", "advisor", "elephant", "horse", "chariot", "cannon", "soldier"}
        assert set(defn.components.keys()) == expected


# ---------------------------------------------------------------------------
# Tests: setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_32_pieces_total(self) -> None:
        game = XiangqiGame()
        count = 0
        for r in range(HEIGHT):
            for c in range(WIDTH):
                if game.piece_at(c, r) is not None:
                    count += 1
        assert count == 32

    def test_16_red_pieces(self) -> None:
        game = XiangqiGame()
        count = sum(
            1 for r in range(HEIGHT) for c in range(WIDTH)
            if game.piece_at(c, r) is not None and game.piece_at(c, r)[1] == "red"
        )
        assert count == 16

    def test_16_black_pieces(self) -> None:
        game = XiangqiGame()
        count = sum(
            1 for r in range(HEIGHT) for c in range(WIDTH)
            if game.piece_at(c, r) is not None and game.piece_at(c, r)[1] == "black"
        )
        assert count == 16

    def test_red_general_at_e1(self) -> None:
        game = XiangqiGame()
        assert game.piece_at(4, 0) == ("general", "red")

    def test_black_general_at_e10(self) -> None:
        game = XiangqiGame()
        assert game.piece_at(4, 9) == ("general", "black")

    def test_red_chariots(self) -> None:
        game = XiangqiGame()
        assert game.piece_at(0, 0) == ("chariot", "red")
        assert game.piece_at(8, 0) == ("chariot", "red")

    def test_red_cannons(self) -> None:
        game = XiangqiGame()
        assert game.piece_at(1, 2) == ("cannon", "red")
        assert game.piece_at(7, 2) == ("cannon", "red")

    def test_red_soldiers(self) -> None:
        game = XiangqiGame()
        for col in range(0, 9, 2):
            assert game.piece_at(col, 3) == ("soldier", "red"), f"expected red soldier at ({col}, 3)"

    def test_black_soldiers(self) -> None:
        game = XiangqiGame()
        for col in range(0, 9, 2):
            assert game.piece_at(col, 6) == ("soldier", "black"), f"expected black soldier at ({col}, 6)"


# ---------------------------------------------------------------------------
# Tests: general movement
# ---------------------------------------------------------------------------


class TestGeneralMovement:
    def test_general_center_of_palace(self) -> None:
        """General at center of palace has 4 orthogonal moves."""
        game = XiangqiGame()
        game._clear_and_place([(4, 1, "general", "red")])
        moves = game._pseudo_legal_moves(4, 1)
        assert sorted(moves) == sorted([(3, 1), (5, 1), (4, 0), (4, 2)])

    def test_general_corner_of_palace(self) -> None:
        """General at corner of palace has 2 moves."""
        game = XiangqiGame()
        game._clear_and_place([(3, 0, "general", "red")])
        moves = game._pseudo_legal_moves(3, 0)
        assert sorted(moves) == sorted([(4, 0), (3, 1)])

    def test_general_cannot_leave_palace(self) -> None:
        """General cannot step outside the palace."""
        game = XiangqiGame()
        game._clear_and_place([(5, 2, "general", "red")])
        moves = game._pseudo_legal_moves(5, 2)
        # (6,2) is outside palace, (5,3) is outside palace
        for mc, mr in moves:
            assert _in_palace(mc, mr, "red"), f"({mc},{mr}) is outside red palace"

    def test_black_general_in_palace(self) -> None:
        """Black general stays in its palace (rows 7-9)."""
        game = XiangqiGame()
        game._clear_and_place([(4, 8, "general", "black")])
        moves = game._pseudo_legal_moves(4, 8)
        assert sorted(moves) == sorted([(3, 8), (5, 8), (4, 7), (4, 9)])
        for mc, mr in moves:
            assert _in_palace(mc, mr, "black")


# ---------------------------------------------------------------------------
# Tests: advisor movement
# ---------------------------------------------------------------------------


class TestAdvisorMovement:
    def test_advisor_center_of_palace(self) -> None:
        """Advisor at center of palace has 4 diagonal moves (all in palace)."""
        game = XiangqiGame()
        game._clear_and_place([(4, 1, "advisor", "red")])
        moves = game._pseudo_legal_moves(4, 1)
        assert sorted(moves) == sorted([(3, 0), (5, 0), (3, 2), (5, 2)])

    def test_advisor_corner_of_palace(self) -> None:
        """Advisor at corner of palace has only 1 move (center)."""
        game = XiangqiGame()
        game._clear_and_place([(3, 0, "advisor", "red")])
        moves = game._pseudo_legal_moves(3, 0)
        assert moves == [(4, 1)]

    def test_advisor_cannot_leave_palace(self) -> None:
        """Advisor moves must all stay within palace."""
        game = XiangqiGame()
        game._clear_and_place([(5, 2, "advisor", "red")])
        moves = game._pseudo_legal_moves(5, 2)
        for mc, mr in moves:
            assert _in_palace(mc, mr, "red")


# ---------------------------------------------------------------------------
# Tests: elephant movement
# ---------------------------------------------------------------------------


class TestElephantMovement:
    def test_elephant_center_own_side(self) -> None:
        """Elephant on own side with no blockers has up to 4 diagonal-2 moves."""
        game = XiangqiGame()
        game._clear_and_place([(4, 2, "elephant", "red")])
        moves = game._pseudo_legal_moves(4, 2)
        # Possible: (2,0), (6,0), (2,4), (6,4)
        assert sorted(moves) == sorted([(2, 0), (6, 0), (2, 4), (6, 4)])

    def test_elephant_cannot_cross_river(self) -> None:
        """Elephant cannot land on the other side of the river."""
        game = XiangqiGame()
        game._clear_and_place([(4, 4, "elephant", "red")])
        moves = game._pseudo_legal_moves(4, 4)
        # (2,2) and (6,2) are on own side; (2,6) and (6,6) would cross the river
        for mc, mr in moves:
            assert _on_own_side(mr, "red"), f"({mc},{mr}) crosses river for red"

    def test_elephant_blocked_by_intervening_piece(self) -> None:
        """Elephant is blocked when the diagonal midpoint is occupied."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 2, "elephant", "red"),
            (3, 1, "soldier", "red"),   # blocks (2,0)
            (5, 1, "soldier", "black"), # blocks (6,0)
        ])
        moves = game._pseudo_legal_moves(4, 2)
        assert (2, 0) not in moves
        assert (6, 0) not in moves
        # (2,4) and (6,4) should still be available
        assert (2, 4) in moves
        assert (6, 4) in moves

    def test_black_elephant_stays_own_side(self) -> None:
        """Black elephant cannot cross into red territory."""
        game = XiangqiGame()
        game._clear_and_place([(4, 7, "elephant", "black")])
        moves = game._pseudo_legal_moves(4, 7)
        for mc, mr in moves:
            assert _on_own_side(mr, "black"), f"({mc},{mr}) crosses river for black"


# ---------------------------------------------------------------------------
# Tests: horse movement
# ---------------------------------------------------------------------------


class TestHorseMovement:
    def test_horse_center_no_blockers(self) -> None:
        """Horse in center of empty board has 8 L-shaped moves."""
        game = XiangqiGame()
        game._clear_and_place([(4, 4, "horse", "red")])
        moves = game._pseudo_legal_moves(4, 4)
        expected = [
            (5, 6), (3, 6),   # up-right, up-left
            (5, 2), (3, 2),   # down-right, down-left
            (6, 5), (2, 5),   # right-up, left-up
            (6, 3), (2, 3),   # right-down, left-down
        ]
        assert sorted(moves) == sorted(expected)

    def test_horse_blocked_by_orthogonal_piece(self) -> None:
        """Horse is blocked when the orthogonal intermediate square is occupied."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "horse", "red"),
            (4, 5, "soldier", "red"),  # blocks upward moves (4,5 is the ortho step for dy=+2)
        ])
        moves = game._pseudo_legal_moves(4, 4)
        # (5,6) and (3,6) should be blocked (ortho step at (4,5))
        assert (5, 6) not in moves
        assert (3, 6) not in moves
        # Other moves should still be available
        assert (5, 2) in moves
        assert (3, 2) in moves

    def test_horse_not_blocked_by_diagonal_piece(self) -> None:
        """Horse is NOT blocked by a piece on the diagonal (unlike chess knight)."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "horse", "red"),
            (5, 5, "soldier", "red"),  # diagonal, not blocking
        ])
        moves = game._pseudo_legal_moves(4, 4)
        # All 8 moves should be available (diagonal piece doesn't block)
        assert len(moves) == 8

    def test_horse_corner(self) -> None:
        """Horse at corner (0,0) has limited moves."""
        game = XiangqiGame()
        game._clear_and_place([(0, 0, "horse", "red")])
        moves = game._pseudo_legal_moves(0, 0)
        # From (0,0): only (1,2) and (2,1) are on-board
        assert sorted(moves) == sorted([(1, 2), (2, 1)])

    def test_horse_captures_enemy(self) -> None:
        """Horse can capture enemy piece at destination."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "horse", "red"),
            (5, 6, "soldier", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (5, 6) in moves


# ---------------------------------------------------------------------------
# Tests: chariot movement
# ---------------------------------------------------------------------------


class TestChariotMovement:
    def test_chariot_center_empty_board(self) -> None:
        """Chariot in center of empty 9x10 board has many moves."""
        game = XiangqiGame()
        game._clear_and_place([(4, 4, "chariot", "red")])
        moves = game._pseudo_legal_moves(4, 4)
        # Horizontal: 0-3 + 5-8 = 8; Vertical: 0-3 + 5-9 = 9; total = 17
        assert len(moves) == 17

    def test_chariot_blocked_by_friendly(self) -> None:
        """Chariot blocked by friendly piece cannot pass through."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "chariot", "red"),
            (4, 6, "soldier", "red"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (4, 5) in moves
        assert (4, 6) not in moves  # friendly piece
        assert (4, 7) not in moves  # behind friendly piece

    def test_chariot_captures_enemy(self) -> None:
        """Chariot can capture enemy but stops there."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "chariot", "red"),
            (4, 7, "soldier", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        assert (4, 7) in moves   # capture
        assert (4, 8) not in moves  # blocked after capture


# ---------------------------------------------------------------------------
# Tests: cannon movement
# ---------------------------------------------------------------------------


class TestCannonMovement:
    def test_cannon_slides_to_empty(self) -> None:
        """Cannon slides freely to empty squares along orthogonal lines."""
        game = XiangqiGame()
        game._clear_and_place([(4, 4, "cannon", "red")])
        moves = game._pseudo_legal_moves(4, 4)
        # Same as chariot on empty board: 17 moves
        assert len(moves) == 17

    def test_cannon_cannot_capture_without_screen(self) -> None:
        """Cannon cannot capture an adjacent enemy (no screen to jump over)."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 4, "cannon", "red"),
            (4, 5, "soldier", "black"),
        ])
        moves = game._pseudo_legal_moves(4, 4)
        # (4,5) has an enemy, but no screen -> cannon can't capture it
        # Also can't slide to (4,5) because it's occupied
        assert (4, 5) not in moves

    def test_cannon_captures_over_screen(self) -> None:
        """Cannon captures by hopping over exactly one piece (the screen)."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "cannon", "red"),
            (4, 3, "soldier", "red"),   # screen piece
            (4, 7, "soldier", "black"), # capture target
        ])
        moves = game._pseudo_legal_moves(4, 0)
        # Cannon can slide to (4,1), (4,2) (empty squares before screen)
        assert (4, 1) in moves
        assert (4, 2) in moves
        # Cannot slide to (4,3) — screen is there
        assert (4, 3) not in moves
        # Can capture (4,7) by hopping over screen at (4,3)
        assert (4, 7) in moves
        # Cannot go past the capture target
        assert (4, 8) not in moves

    def test_cannon_cannot_capture_over_two_screens(self) -> None:
        """Cannon cannot capture when two pieces are between it and the target."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "cannon", "red"),
            (4, 3, "soldier", "red"),   # first screen
            (4, 5, "soldier", "red"),   # second piece (beyond first screen)
            (4, 8, "soldier", "black"), # target
        ])
        moves = game._pseudo_legal_moves(4, 0)
        # Only first screen matters: cannon jumps (4,3), finds (4,5) which is friendly -> can't capture
        # Target at (4,8) is unreachable (would need to hop 2 pieces)
        assert (4, 8) not in moves
        # But can capture (4,5)? No, (4,5) is friendly
        assert (4, 5) not in moves

    def test_cannon_capture_with_enemy_screen(self) -> None:
        """The screen piece can be either friendly or enemy."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "cannon", "red"),
            (4, 4, "soldier", "black"),  # enemy screen
            (4, 8, "soldier", "black"),  # capture target
        ])
        moves = game._pseudo_legal_moves(4, 0)
        assert (4, 8) in moves  # can capture over enemy screen

    def test_cannon_cannot_capture_friendly(self) -> None:
        """Cannon cannot capture a friendly piece even with a valid screen."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "cannon", "red"),
            (4, 3, "soldier", "black"), # screen
            (4, 7, "soldier", "red"),   # friendly piece behind screen
        ])
        moves = game._pseudo_legal_moves(4, 0)
        assert (4, 7) not in moves  # can't capture own piece


# ---------------------------------------------------------------------------
# Tests: soldier movement
# ---------------------------------------------------------------------------


class TestSoldierMovement:
    def test_red_soldier_before_river(self) -> None:
        """Red soldier before crossing river can only move forward (row+1)."""
        game = XiangqiGame()
        game._clear_and_place([(4, 3, "soldier", "red")])
        moves = game._pseudo_legal_moves(4, 3)
        assert moves == [(4, 4)]

    def test_red_soldier_after_river(self) -> None:
        """Red soldier after crossing river can move forward or sideways."""
        game = XiangqiGame()
        game._clear_and_place([(4, 5, "soldier", "red")])
        moves = game._pseudo_legal_moves(4, 5)
        assert sorted(moves) == sorted([(4, 6), (3, 5), (5, 5)])

    def test_black_soldier_before_river(self) -> None:
        """Black soldier before crossing river can only move forward (row-1)."""
        game = XiangqiGame()
        game._clear_and_place([(4, 6, "soldier", "black")])
        moves = game._pseudo_legal_moves(4, 6)
        assert moves == [(4, 5)]

    def test_black_soldier_after_river(self) -> None:
        """Black soldier after crossing river can move forward or sideways."""
        game = XiangqiGame()
        game._clear_and_place([(4, 4, "soldier", "black")])
        moves = game._pseudo_legal_moves(4, 4)
        assert sorted(moves) == sorted([(4, 3), (3, 4), (5, 4)])

    def test_soldier_cannot_retreat(self) -> None:
        """Soldiers can never move backward."""
        game = XiangqiGame()
        # Red soldier that crossed the river
        game._clear_and_place([(4, 6, "soldier", "red")])
        moves = game._pseudo_legal_moves(4, 6)
        # Should have forward (4,7) and lateral (3,6), (5,6) — no backward (4,5)
        assert (4, 5) not in moves
        assert (4, 7) in moves

    def test_soldier_at_last_rank(self) -> None:
        """Red soldier at row 9 (last rank) can only move sideways."""
        game = XiangqiGame()
        game._clear_and_place([(4, 9, "soldier", "red")])
        moves = game._pseudo_legal_moves(4, 9)
        # Forward would be row 10 (off board), only lateral
        assert sorted(moves) == sorted([(3, 9), (5, 9)])

    def test_soldier_edge_no_wrap(self) -> None:
        """Soldier at left edge after river has forward + right only (no left wrap)."""
        game = XiangqiGame()
        game._clear_and_place([(0, 5, "soldier", "red")])
        moves = game._pseudo_legal_moves(0, 5)
        assert sorted(moves) == sorted([(0, 6), (1, 5)])


# ---------------------------------------------------------------------------
# Tests: flying general rule
# ---------------------------------------------------------------------------


class TestFlyingGeneral:
    def test_generals_facing_detected(self) -> None:
        """Detect when generals face each other on open file."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
        ])
        assert game._generals_facing() is True

    def test_generals_not_facing_with_piece_between(self) -> None:
        """Generals on same file with a piece between are not facing."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 5, "soldier", "red"),
            (4, 9, "general", "black"),
        ])
        assert game._generals_facing() is False

    def test_generals_not_facing_different_files(self) -> None:
        """Generals on different files are not facing."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (5, 9, "general", "black"),
        ])
        assert game._generals_facing() is False

    def test_flying_general_blocks_move(self) -> None:
        """A move that would expose generals facing each other is illegal."""
        game = XiangqiGame()
        # Place a piece between the generals; removing it would violate flying general
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 5, "chariot", "red"),  # shielding piece
            (4, 9, "general", "black"),
        ])
        # Chariot can normally move off the file, but doing so exposes flying general
        legal = game.legal_moves(4, 5)
        # Chariot can move along the file (stays between generals), but not off file
        for mc, mr in legal:
            assert mc == 4, f"chariot should stay on file 4 to avoid flying general, got ({mc},{mr})"

    def test_general_cannot_move_to_face_opponent(self) -> None:
        """General cannot move to a file where it faces the opponent general."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
        ])
        legal = game.legal_moves(3, 0)
        # Moving to (4,0) would face black general at (4,9)
        assert (4, 0) not in legal


# ---------------------------------------------------------------------------
# Tests: check detection
# ---------------------------------------------------------------------------


class TestCheck:
    def test_chariot_check(self) -> None:
        """General in check from chariot on same file."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 5, "chariot", "red"),  # checks black general
        ])
        assert game.in_check("black") is True

    def test_horse_check(self) -> None:
        """General in check from horse."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (3, 7, "horse", "red"),  # at (3,7), attacks (4,9) via dx=1,dy=2, block at (3,8)
        ])
        # Horse at (3,7) -> (4,9): dx=1, dy=2, block square = (3,8) which is empty
        assert game.in_check("black") is True

    def test_horse_check_blocked(self) -> None:
        """Horse check is blocked by piece on orthogonal intermediate."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (3, 7, "horse", "red"),    # would check black general
            (3, 8, "soldier", "black"), # blocks the horse's path
        ])
        assert game.in_check("black") is False

    def test_cannon_check(self) -> None:
        """General in check from cannon with a screen."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 2, "cannon", "red"),    # cannon aimed at black general
            (4, 5, "soldier", "red"),   # screen piece
        ])
        assert game.in_check("black") is True

    def test_cannon_no_screen_no_check(self) -> None:
        """Cannon on same file without a screen does not check."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 2, "cannon", "red"),
        ])
        # No screen between cannon and general -> no check
        # But wait: flying general rule! The generals face each other.
        # For this test, offset the generals.
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 2, "cannon", "red"),
        ])
        assert game.in_check("black") is False

    def test_soldier_check(self) -> None:
        """Soldier that crossed river checks general from adjacent square."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 8, "soldier", "red"),   # red soldier forward from (4,8) attacks (4,9)
        ])
        assert game.in_check("black") is True


# ---------------------------------------------------------------------------
# Tests: checkmate
# ---------------------------------------------------------------------------


class TestCheckmate:
    def test_chariot_mate_back_rank(self) -> None:
        """Chariot delivers checkmate on back rank."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 9, "chariot", "red"),   # checks along rank 9
            (3, 8, "chariot", "red"),   # covers escape to (3,9) and (3,8)
        ])
        # Black general at (4,9), checked by chariot at (0,9) along rank.
        # Escape squares: (3,9) covered by chariot at (3,8)+(0,9), (5,9) covered by (0,9),
        # (4,8) covered by chariot at (3,8)? No, (3,8) is a chariot not on same file.
        # Let me verify more carefully. Actually let me use a simpler setup.
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 9, "chariot", "red"),   # checks along rank 9
            (5, 8, "chariot", "red"),   # covers (5,9), (5,8), (4,8)
        ])
        # General at (4,9) in check from (0,9).
        # Escape: (3,9) still attacked by chariot at (0,9).
        # (5,9) attacked by chariot at (0,9) AND chariot at (5,8).
        # (4,8) attacked by chariot at (5,8)? No, (5,8) is not on file 4 or rank 8... wait.
        # Chariot at (5,8) attacks along file 5 and rank 8.
        # (4,8) is on rank 8 -> attacked by chariot at (5,8). Yes.
        # (3,8) is also on rank 8 -> attacked by chariot at (5,8)? Only if nothing between.
        # (4,8) is between (3,8) and (5,8) but (4,8) is empty. So (3,8) IS attacked.
        # But wait, we need to also check: can black capture the checking chariot?
        # Chariot at (0,9): can general reach it? (4,9) to (0,9) is 4 squares away. No.
        # Can any black piece block? No other black pieces. Checkmate.
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is True

    def test_not_checkmate_can_block(self) -> None:
        """Not checkmate when a piece can block the check."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 5, "chariot", "red"),   # checks along file
            (3, 8, "chariot", "black"), # can block by moving to (4,8)
        ])
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is False

    def test_not_checkmate_can_capture_attacker(self) -> None:
        """Not checkmate when the checking piece can be captured."""
        game = XiangqiGame()
        game._clear_and_place([
            (3, 0, "general", "red"),
            (4, 9, "general", "black"),
            (4, 8, "chariot", "red"),   # checks general, but adjacent
            (3, 9, "advisor", "black"),
        ])
        # General can capture the chariot at (4,8)
        assert game.in_check("black") is True
        assert game.is_checkmate("black") is False


# ---------------------------------------------------------------------------
# Tests: stalemate
# ---------------------------------------------------------------------------


class TestStalemate:
    def test_stalemate_general_trapped(self) -> None:
        """Stalemate: general has no legal moves but is not in check.

        In Xiangqi, stalemate is a loss for the stalemated player.
        """
        game = XiangqiGame()
        # Black general at (3,9), red chariots covering all exits
        game._clear_and_place([
            (3, 0, "general", "red"),
            (3, 9, "general", "black"),
            (2, 8, "chariot", "red"),   # covers col 2 and row 8
            (0, 9, "chariot", "red"),   # covers row 9
        ])
        # General at (3,9): neighbors in palace are (4,9) and (3,8).
        # (4,9) attacked by chariot at (0,9) on rank 9.
        # (3,8) attacked by chariot at (2,8) on rank 8.
        # Is (3,9) in check? Chariot at (0,9) on rank 9 attacks (3,9)? Yes, if path clear.
        # (1,9) and (2,9) are empty, so chariot at (0,9) attacks (3,9). That's check, not stalemate.
        # Let me redesign:
        game._clear_and_place([
            (5, 0, "general", "red"),
            (4, 9, "general", "black"),
            (3, 7, "chariot", "red"),   # covers row 7 and col 3
            (5, 7, "chariot", "red"),   # covers row 7 and col 5
        ])
        # General at (4,9). Palace moves: (3,9), (5,9), (4,8).
        # (4,8): not attacked by either chariot (col 3 and 5, row 7, not col 4 or row 8). So (4,8) is safe.
        # That's not stalemate. Let me think differently.

        # Simpler: general at corner (3,9), only moves to (4,9) and (3,8).
        # Block (4,9) by a friendly piece, and have (3,8) attacked.
        game._clear_and_place([
            (5, 0, "general", "red"),
            (3, 9, "general", "black"),
            (4, 9, "advisor", "black"),  # blocks (4,9) for the general
            (3, 5, "chariot", "red"),    # covers col 3 including (3,8)
        ])
        # General at (3,9). Palace moves: (4,9) blocked by own advisor, (3,8) attacked by chariot on col 3.
        # Is general in check? Chariot at (3,5) on col 3 attacks (3,9)? Path: (3,6),(3,7),(3,8) must be empty. Yes.
        # So that's check again, not stalemate. The chariot directly checks the general.

        # Let me use an indirect block: chariot NOT on same file/rank as general.
        game._clear_and_place([
            (5, 0, "general", "red"),
            (3, 9, "general", "black"),
            (4, 9, "advisor", "black"),  # blocks (4,9)
            (2, 8, "chariot", "red"),    # covers rank 8, so (3,8) attacked
        ])
        # (3,9) in check? Chariot at (2,8) is on rank 8, not rank 9. Not on col 3.
        # So (3,9) not directly attacked. Good.
        # General moves: (4,9) own piece. (3,8) attacked by chariot at (2,8) on rank 8.
        # But wait: does the advisor at (4,9) have moves? Yes, advisor at (4,9) corner -> can move to (3,8) or (5,8).
        # If advisor moves to (3,8)... but (3,8) is attacked, that's fine for the advisor (no check constraint on advisors).
        # So it's NOT stalemate because the advisor can move.

        # For true stalemate, black must have NO pieces with legal moves.
        game._clear_and_place([
            (5, 0, "general", "red"),
            (3, 9, "general", "black"),
            (2, 8, "chariot", "red"),    # covers rank 8: (3,8) attacked
            (4, 8, "chariot", "red"),    # covers col 4 and rank 8
        ])
        # General at (3,9): palace moves (4,9) and (3,8).
        # (4,9): chariot at (4,8) covers (4,9) on col 4. Attacked.
        # (3,8): chariot at (2,8) covers (3,8) on rank 8. Also chariot at (4,8) covers (3,8) on rank 8.
        # Is (3,9) in check? Neither chariot is on col 3 or rank 9. Not in check.
        assert game.in_check("black") is False
        assert game.is_stalemate("black") is True

    def test_not_stalemate_has_moves(self) -> None:
        """Not stalemate when the player has legal moves."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
        ])
        # Both generals have moves
        assert game.is_stalemate("black") is False


# ---------------------------------------------------------------------------
# Tests: move execution
# ---------------------------------------------------------------------------


class TestMoveExecution:
    def test_move_piece(self) -> None:
        """Move a piece: old cell empty, new cell occupied."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 0, "chariot", "red"),
        ])
        game.move(0, 0, 0, 5)
        assert game.piece_at(0, 0) is None
        assert game.piece_at(0, 5) == ("chariot", "red")

    def test_capture_enemy(self) -> None:
        """Moving onto an enemy piece captures it."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 0, "chariot", "red"),
            (0, 7, "soldier", "black"),
        ])
        game.move(0, 0, 0, 7)
        assert game.piece_at(0, 7) == ("chariot", "red")

    def test_turn_advances(self) -> None:
        """Turn advances from red to black after a move."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 0, "chariot", "red"),
        ])
        assert game.current_player() == "red"
        game.move(0, 0, 0, 5)
        assert game.current_player() == "black"

    def test_cannot_move_opponent_piece(self) -> None:
        """Cannot move a piece belonging to the opponent."""
        game = XiangqiGame()
        game._clear_and_place([
            (4, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 9, "chariot", "black"),
        ])
        with pytest.raises(ValueError, match="belongs to black"):
            game.move(0, 9, 0, 5)

    def test_checkmate_ends_game(self) -> None:
        """A move that delivers checkmate ends the game."""
        game = XiangqiGame()
        game._clear_and_place([
            (5, 0, "general", "red"),
            (4, 9, "general", "black"),
            (0, 0, "chariot", "red"),
            (8, 0, "chariot", "red"),
        ])
        # Move chariot to rank 9, delivering double-chariot mate
        # After (0,0) -> (0,9): check from chariot on rank 9.
        # Chariot at (8,0) does NOT cover escapes yet. Let's think:
        # General at (4,9). Chariot at (0,9) checks on rank 9.
        # Escapes: (4,8), (3,9), (5,9).
        # (3,9) attacked by chariot (0,9). (5,9) attacked by chariot (0,9).
        # (4,8) is free. Not checkmate yet.
        # Better setup:
        game._clear_and_place([
            (5, 0, "general", "red"),
            (4, 9, "general", "black"),
            (3, 8, "chariot", "red"),  # will stay, covers rank 8 and col 3
            (0, 0, "chariot", "red"),  # will move to (0,9) to deliver check
        ])
        game.move(0, 0, 0, 9)
        # General at (4,9) checked by (0,9) on rank 9.
        # Escapes: (3,9) attacked by (0,9). (5,9) attacked by (0,9).
        # (4,8) attacked by chariot at (3,8) on rank 8. Yes, (4,8) on rank 8.
        # (3,8) chariot itself covers rank 8 entirely.
        # No escapes. No blockers (no black pieces). Checkmate.
        assert game.session.runtime.status == "finished"
        assert game.session.runtime.result is not None
        assert game.session.runtime.result.outcome == "win"
        assert game.session.runtime.result.winner == "red"
        assert game.session.runtime.result.condition == "checkmate"
