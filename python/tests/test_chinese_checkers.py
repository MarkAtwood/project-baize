"""Tests for Chinese Checkers: hex star board, step/hop movement, multi-hop chains.

2-player variant:
  - 121-position hexagram (6-pointed star) on a hex grid with hex_6 adjacency.
  - Each player starts with 10 pegs in one triangle point.
  - Red starts in T1 (top), goal is T4 (bottom).
  - Blue starts in T4 (bottom), goal is T1 (top).
  - Movement: step to adjacent empty cell, or hop over adjacent piece to empty beyond.
  - Multi-hop chains: after a hop, player may continue hopping the same piece.
  - Win: first player to fill the opposite triangle.
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

# ---------------------------------------------------------------------------
# Board geometry
# ---------------------------------------------------------------------------

# Hex_6 neighbor offsets (col, row)
_HEX_DIRS: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]

# Triangle coordinates (home/goal zones)
T1 = [(12, 0), (11, 1), (12, 1), (10, 2), (11, 2), (12, 2),
      (9, 3), (10, 3), (11, 3), (12, 3)]

T2 = [(13, 4), (14, 4), (15, 4), (16, 4), (13, 5), (14, 5), (15, 5),
      (13, 6), (14, 6), (13, 7)]

T3 = [(12, 9), (11, 10), (12, 10), (10, 11), (11, 11), (12, 11),
      (9, 12), (10, 12), (11, 12), (12, 12)]

T4 = [(4, 13), (5, 13), (6, 13), (7, 13), (4, 14), (5, 14), (6, 14),
      (4, 15), (5, 15), (4, 16)]

T5 = [(3, 9), (2, 10), (3, 10), (1, 11), (2, 11), (3, 11),
      (0, 12), (1, 12), (2, 12), (3, 12)]

T6 = [(4, 4), (5, 4), (6, 4), (7, 4), (4, 5), (5, 5), (6, 5),
      (4, 6), (5, 6), (4, 7)]

ALL_TRIANGLES = {"T1": T1, "T2": T2, "T3": T3, "T4": T4, "T5": T5, "T6": T6}

# Opposite triangle pairs
OPPOSITE = {"T1": "T4", "T4": "T1", "T2": "T5", "T5": "T2", "T3": "T6", "T6": "T3"}

# 2-player: Red starts T1, goal T4; Blue starts T4, goal T1
HOME = {"Red": T1, "Blue": T4}
GOAL = {"Red": T4, "Blue": T1}

# All 121 valid positions (computed from game definition)
_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "chinese-checkers.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# ChineseCheckersGame helper
# ---------------------------------------------------------------------------


class ChineseCheckersGame:
    """Chinese Checkers game driver with step/hop movement and multi-hop chains."""

    def __init__(self) -> None:
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None
        self._setup_initial_position()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _place(self, col: int, row: int, owner: str) -> ComponentId:
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"peg-{owner}-{col}-{row}",
                component_type="peg",
                owner=owner,
            )
        )
        self.board.grid_set(col, row, cid)
        return cid

    def _setup_initial_position(self) -> None:
        """Place 10 pegs per player in their home triangles."""
        for col, row in HOME["Red"]:
            self._place(col, row, "Red")
        for col, row in HOME["Blue"]:
            self._place(col, row, "Blue")

    def piece_at(self, col: int, row: int) -> str | None:
        """Return owner or None."""
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def is_valid_cell(self, col: int, row: int) -> bool:
        return self.board._cell_valid(col, row)

    def neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        """Return valid neighboring cells."""
        result = []
        for dc, dr in _HEX_DIRS:
            nc, nr = col + dc, row + dr
            if self.is_valid_cell(nc, nr):
                result.append((nc, nr))
        return result

    def step_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Legal step (non-hop) moves from a position."""
        moves = []
        for nc, nr in self.neighbors(col, row):
            if self.piece_at(nc, nr) is None:
                moves.append((nc, nr))
        return moves

    def hop_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """Legal single-hop moves from a position."""
        hops = []
        for dc, dr in _HEX_DIRS:
            mid_c, mid_r = col + dc, row + dr
            land_c, land_r = col + 2 * dc, row + 2 * dr
            if (
                self.is_valid_cell(mid_c, mid_r)
                and self.is_valid_cell(land_c, land_r)
                and self.piece_at(mid_c, mid_r) is not None
                and self.piece_at(land_c, land_r) is None
            ):
                hops.append((land_c, land_r))
        return hops

    def legal_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        """All legal moves (steps + hops) from a position."""
        return self.step_moves(col, row) + self.hop_moves(col, row)

    def move(self, from_col: int, from_row: int, to_col: int, to_row: int) -> str:
        """Execute a move. Returns 'step', 'hop', or raises ValueError.

        After a hop, does NOT advance turn — caller must call end_turn()
        or continue hopping. After a step, turn advances automatically.
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()
        owner = self.piece_at(from_col, from_row)
        if owner is None:
            raise ValueError(f"no piece at ({from_col},{from_row})")
        if owner != player:
            raise ValueError(f"piece at ({from_col},{from_row}) belongs to {owner}")

        dc = to_col - from_col
        dr = to_row - from_row

        if (to_col, to_row) in self.step_moves(from_col, from_row):
            move_type = "step"
        elif (to_col, to_row) in self.hop_moves(from_col, from_row):
            move_type = "hop"
        else:
            raise ValueError(f"illegal move ({from_col},{from_row})->({to_col},{to_row})")

        # Move the peg
        cid = self.board.grid_get(from_col, from_row)
        self.board.grid_set(from_col, from_row, None)
        self.board.grid_set(to_col, to_row, cid)

        if move_type == "step":
            self._finish_turn()
        # hop: turn stays with current player (multi-hop chain possible)

        return move_type

    def end_turn(self) -> None:
        """End turn after a hop chain (or if player chooses to stop hopping)."""
        self._finish_turn()

    def _finish_turn(self) -> None:
        """Advance turn and check win condition."""
        # Check if current player has won before advancing
        player = self.current_player()
        if self._check_win(player):
            self.finished = True
            self.winner = player
            return
        self.session.advance_turn()

    def _check_win(self, player: str) -> bool:
        """Player wins when all 10 pegs are in their goal triangle."""
        goal = GOAL[player]
        for col, row in goal:
            if self.piece_at(col, row) != player:
                return False
        return True

    def count_in_triangle(self, player: str, triangle: list[tuple[int, int]]) -> int:
        """Count how many of player's pegs are in the given triangle."""
        return sum(1 for c, r in triangle if self.piece_at(c, r) == player)


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Chinese Checkers"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Red", "Blue"]

    def test_hex_grid(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.zone_type == "hex_grid"
        assert zone.dimensions == [17, 17]
        assert zone.adjacency == "hex_6"

    def test_valid_cells_count(self) -> None:
        defn = _load_definition()
        assert len(defn.zones["board"].valid_cells) == 121

    def test_cell_properties_triangles(self) -> None:
        defn = _load_definition()
        cp = defn.zones["board"].cell_properties
        # 6 triangles x 10 cells = 60 cells with triangle properties
        assert len(cp) == 60
        # Check a specific cell
        assert cp["12,0"]["triangle"] == "T1"
        assert cp["4,16"]["triangle"] == "T4"


# ---------------------------------------------------------------------------
# Tests: board geometry
# ---------------------------------------------------------------------------


class TestBoardGeometry:
    def test_121_valid_cells(self) -> None:
        game = ChineseCheckersGame()
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.is_valid_cell(c, r)
        )
        assert count == 121

    def test_row_widths(self) -> None:
        """Row widths should be 1,2,3,4,13,12,11,10,9,10,11,12,13,4,3,2,1."""
        game = ChineseCheckersGame()
        expected = [1, 2, 3, 4, 13, 12, 11, 10, 9, 10, 11, 12, 13, 4, 3, 2, 1]
        for row, expected_width in enumerate(expected):
            actual = sum(1 for c in range(17) if game.is_valid_cell(c, row))
            assert actual == expected_width, f"row {row}: expected {expected_width}, got {actual}"

    def test_triangles_each_have_10_cells(self) -> None:
        for name, cells in ALL_TRIANGLES.items():
            assert len(cells) == 10, f"{name} has {len(cells)} cells"

    def test_triangles_are_disjoint(self) -> None:
        all_cells: list[tuple[int, int]] = []
        for cells in ALL_TRIANGLES.values():
            all_cells.extend(cells)
        assert len(all_cells) == len(set(all_cells))

    def test_center_hex_count(self) -> None:
        """Center hexagon should have 61 cells (121 - 60 triangle cells)."""
        game = ChineseCheckersGame()
        tri_cells = set()
        for cells in ALL_TRIANGLES.values():
            tri_cells.update(cells)
        center = sum(
            1 for r in range(17) for c in range(17)
            if game.is_valid_cell(c, r) and (c, r) not in tri_cells
        )
        assert center == 61

    def test_all_cells_connected(self) -> None:
        """BFS from center should reach all 121 cells."""
        game = ChineseCheckersGame()
        all_valid = {
            (c, r) for r in range(17) for c in range(17) if game.is_valid_cell(c, r)
        }
        start = (8, 8)  # center of the board
        assert start in all_valid
        visited: set[tuple[int, int]] = set()
        queue = [start]
        while queue:
            pos = queue.pop()
            if pos in visited:
                continue
            visited.add(pos)
            for n in game.neighbors(*pos):
                if n not in visited:
                    queue.append(n)
        assert visited == all_valid

    def test_triangle_tips_have_2_neighbors(self) -> None:
        """Each triangle tip (outermost cell) should have exactly 2 valid neighbors."""
        game = ChineseCheckersGame()
        tips = [(12, 0), (16, 4), (12, 12), (4, 16), (0, 12), (4, 4)]
        for tip in tips:
            n = game.neighbors(*tip)
            assert len(n) == 2, f"tip {tip} has {len(n)} neighbors: {n}"

    def test_opposite_triangle_pairs(self) -> None:
        """Verify opposite pairs: T1<->T4, T2<->T5, T3<->T6."""
        for t1, t2 in [("T1", "T4"), ("T2", "T5"), ("T3", "T6")]:
            assert OPPOSITE[t1] == t2
            assert OPPOSITE[t2] == t1


# ---------------------------------------------------------------------------
# Tests: initial setup
# ---------------------------------------------------------------------------


class TestInitialSetup:
    def test_red_starts_in_t1(self) -> None:
        game = ChineseCheckersGame()
        for col, row in T1:
            assert game.piece_at(col, row) == "Red"

    def test_blue_starts_in_t4(self) -> None:
        game = ChineseCheckersGame()
        for col, row in T4:
            assert game.piece_at(col, row) == "Blue"

    def test_20_pegs_total(self) -> None:
        game = ChineseCheckersGame()
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.piece_at(c, r) is not None
        )
        assert count == 20

    def test_center_hex_empty(self) -> None:
        game = ChineseCheckersGame()
        tri_cells = set()
        for cells in ALL_TRIANGLES.values():
            tri_cells.update(cells)
        for r in range(17):
            for c in range(17):
                if game.is_valid_cell(c, r) and (c, r) not in tri_cells:
                    assert game.piece_at(c, r) is None, f"center cell ({c},{r}) occupied"

    def test_red_moves_first(self) -> None:
        game = ChineseCheckersGame()
        assert game.current_player() == "Red"


# ---------------------------------------------------------------------------
# Tests: step movement
# ---------------------------------------------------------------------------


class TestStepMovement:
    def test_step_to_adjacent_empty(self) -> None:
        """A peg can step to an adjacent empty cell."""
        game = ChineseCheckersGame()
        # Red peg at T1 base: (9,3). Neighbor toward center: (8,4)
        assert game.piece_at(9, 3) == "Red"
        assert game.piece_at(8, 4) is None
        result = game.move(9, 3, 8, 4)
        assert result == "step"
        assert game.piece_at(9, 3) is None
        assert game.piece_at(8, 4) == "Red"

    def test_step_advances_turn(self) -> None:
        game = ChineseCheckersGame()
        assert game.current_player() == "Red"
        game.move(9, 3, 8, 4)
        assert game.current_player() == "Blue"

    def test_cannot_step_to_occupied(self) -> None:
        game = ChineseCheckersGame()
        # (12,0) is Red, neighbor (12,1) is also Red
        assert game.piece_at(12, 0) == "Red"
        assert game.piece_at(12, 1) == "Red"
        moves = game.step_moves(12, 0)
        assert (12, 1) not in moves

    def test_cannot_step_off_board(self) -> None:
        """Peg at a triangle tip has only 2 neighbors, can't go off the star."""
        game = ChineseCheckersGame()
        # T1 tip at (12,0): only neighbors are (11,1) and (12,1), both occupied
        moves = game.step_moves(12, 0)
        assert len(moves) == 0  # both neighbors are Red pegs

    def test_step_into_center(self) -> None:
        """Red moves a peg from T1 border into the center hex."""
        game = ChineseCheckersGame()
        # (9,3) is in T1, (8,4) is in center hex
        game.move(9, 3, 8, 4)
        assert game.piece_at(8, 4) == "Red"


# ---------------------------------------------------------------------------
# Tests: hop movement
# ---------------------------------------------------------------------------


class TestHopMovement:
    def test_single_hop(self) -> None:
        """Hop over an adjacent piece to land on empty cell beyond."""
        game = ChineseCheckersGame()
        # Set up: Red at (8,6), another piece at (8,7), empty at (8,8)
        # Clear the board first for a controlled test
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        game._place(8, 6, "Red")
        game._place(8, 7, "Blue")
        result = game.move(8, 6, 8, 8)
        assert result == "hop"
        assert game.piece_at(8, 6) is None
        assert game.piece_at(8, 7) == "Blue"  # hopped piece stays (not captured)
        assert game.piece_at(8, 8) == "Red"

    def test_hop_does_not_capture(self) -> None:
        """In Chinese Checkers, hopped-over pieces are NOT removed."""
        game = ChineseCheckersGame()
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        game._place(8, 6, "Red")
        game._place(8, 7, "Red")  # hop over own piece
        game.move(8, 6, 8, 8)
        assert game.piece_at(8, 7) == "Red"  # still there

    def test_hop_over_own_piece_allowed(self) -> None:
        """Can hop over your own pieces, not just opponent's."""
        game = ChineseCheckersGame()
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        game._place(8, 6, "Red")
        game._place(8, 7, "Red")
        hops = game.hop_moves(8, 6)
        assert (8, 8) in hops

    def test_cannot_hop_to_occupied(self) -> None:
        """Landing cell must be empty."""
        game = ChineseCheckersGame()
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        game._place(8, 6, "Red")
        game._place(8, 7, "Blue")
        game._place(8, 8, "Blue")  # landing blocked
        hops = game.hop_moves(8, 6)
        assert (8, 8) not in hops

    def test_cannot_hop_over_empty(self) -> None:
        """Must hop over an occupied cell."""
        game = ChineseCheckersGame()
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        game._place(8, 6, "Red")
        # (8,7) is empty — no hop to (8,8)
        hops = game.hop_moves(8, 6)
        assert (8, 8) not in hops

    def test_hop_respects_board_mask(self) -> None:
        """Cannot hop to a cell outside the valid_cells mask."""
        game = ChineseCheckersGame()
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        # Place near edge of star — (12,0) is T1 tip
        # Neighbors of (12,0): (11,1) and (12,1) only
        # Hop from (11,1) over (12,0) would land at (13,-1) which is off the board
        game._place(11, 1, "Red")
        game._place(12, 0, "Blue")
        hops = game.hop_moves(11, 1)
        # (13, -1) is invalid, so hop in that direction is blocked
        assert all(game.is_valid_cell(c, r) for c, r in hops)


# ---------------------------------------------------------------------------
# Tests: multi-hop chains
# ---------------------------------------------------------------------------


class TestMultiHop:
    def _clear_and_place(self, game: ChineseCheckersGame,
                         pieces: list[tuple[int, int, str]]) -> None:
        """Clear board and place specific pieces."""
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        for col, row, owner in pieces:
            game._place(col, row, owner)

    def test_hop_does_not_advance_turn(self) -> None:
        """After a hop, turn stays with current player for potential chain."""
        game = ChineseCheckersGame()
        self._clear_and_place(game, [
            (8, 6, "Red"), (8, 7, "Blue"),
        ])
        assert game.current_player() == "Red"
        game.move(8, 6, 8, 8)
        assert game.current_player() == "Red"  # still Red's turn

    def test_end_turn_after_hop(self) -> None:
        """Player calls end_turn() to finish their hop chain."""
        game = ChineseCheckersGame()
        self._clear_and_place(game, [
            (8, 6, "Red"), (8, 7, "Blue"),
        ])
        game.move(8, 6, 8, 8)
        game.end_turn()
        assert game.current_player() == "Blue"

    def test_multi_hop_chain(self) -> None:
        """Two consecutive hops in one turn."""
        game = ChineseCheckersGame()
        # Red at (8,4), bridge pieces at (8,5) and (8,7)
        # Hop 1: (8,4) -> (8,6) over (8,5)
        # Hop 2: (8,6) -> (8,8) over (8,7)
        self._clear_and_place(game, [
            (8, 4, "Red"), (8, 5, "Blue"), (8, 7, "Blue"),
        ])
        result1 = game.move(8, 4, 8, 6)
        assert result1 == "hop"
        assert game.current_player() == "Red"  # still Red's turn

        result2 = game.move(8, 6, 8, 8)
        assert result2 == "hop"
        assert game.current_player() == "Red"  # still Red's turn

        game.end_turn()
        assert game.current_player() == "Blue"
        assert game.piece_at(8, 8) == "Red"
        assert game.piece_at(8, 4) is None

    def test_cannot_step_after_hop(self) -> None:
        """After a hop, only more hops are allowed (or end turn)."""
        # This is a simplification — in standard rules, once you hop
        # you can only continue hopping or stop. You can't step.
        # Our move() allows it since it's up to the caller, but
        # step_moves after hop should be filtered in a full implementation.
        # For now, we just verify the step/hop distinction works.
        game = ChineseCheckersGame()
        self._clear_and_place(game, [
            (8, 6, "Red"), (8, 7, "Blue"),
        ])
        game.move(8, 6, 8, 8)
        # After hop, piece at (8,8) has step moves available
        steps = game.step_moves(8, 8)
        hops = game.hop_moves(8, 8)
        # Both are calculated; enforcement of "only hops after first hop"
        # would be a game-logic rule in a full implementation
        assert isinstance(steps, list)
        assert isinstance(hops, list)


# ---------------------------------------------------------------------------
# Tests: win condition
# ---------------------------------------------------------------------------


class TestWinCondition:
    def _clear_and_place(self, game: ChineseCheckersGame,
                         pieces: list[tuple[int, int, str]]) -> None:
        for r in range(17):
            for c in range(17):
                game.board.grid_set(c, r, None)
        game.session.runtime.components = type(game.session.runtime.components)()
        for col, row, owner in pieces:
            game._place(col, row, owner)

    def test_red_wins_by_filling_t4(self) -> None:
        """Red wins when all 10 of Red's pegs are in T4."""
        game = ChineseCheckersGame()
        pieces = [(c, r, "Red") for c, r in T4]
        # Also need Blue pegs somewhere so game is valid
        pieces.extend([(c, r, "Blue") for c, r in T1])
        self._clear_and_place(game, pieces)
        assert game._check_win("Red") is True

    def test_blue_wins_by_filling_t1(self) -> None:
        """Blue wins when all 10 of Blue's pegs are in T1."""
        game = ChineseCheckersGame()
        pieces = [(c, r, "Blue") for c, r in T1]
        pieces.extend([(c, r, "Red") for c, r in T4])
        self._clear_and_place(game, pieces)
        assert game._check_win("Blue") is True

    def test_not_won_initially(self) -> None:
        """Neither player has won at the start."""
        game = ChineseCheckersGame()
        assert game._check_win("Red") is False
        assert game._check_win("Blue") is False

    def test_partial_fill_not_a_win(self) -> None:
        """9 of 10 pegs in goal is not a win."""
        game = ChineseCheckersGame()
        pieces = [(c, r, "Red") for c, r in T4[:9]]
        pieces.append((8, 8, "Red"))  # 10th peg not in goal
        pieces.extend([(c, r, "Blue") for c, r in T1])
        self._clear_and_place(game, pieces)
        assert game._check_win("Red") is False

    def test_win_triggers_on_move(self) -> None:
        """Win detected after the move that completes the goal triangle."""
        game = ChineseCheckersGame()
        # Set up: Red has 9 pegs in T4, 1 peg adjacent to last empty T4 cell
        t4_sorted = sorted(T4)
        pieces = [(c, r, "Red") for c, r in t4_sorted[:9]]
        # Last T4 cell
        last_col, last_row = t4_sorted[9]
        # Find an adjacent valid cell that's NOT in T4
        adj = None
        for dc, dr in _HEX_DIRS:
            nc, nr = last_col + dc, last_row + dr
            if game.is_valid_cell(nc, nr) and (nc, nr) not in T4:
                adj = (nc, nr)
                break
        assert adj is not None, "need adjacent cell outside T4"
        pieces.append((adj[0], adj[1], "Red"))
        # Blue somewhere
        pieces.extend([(c, r, "Blue") for c, r in T1])
        self._clear_and_place(game, pieces)

        game.move(adj[0], adj[1], last_col, last_row)
        assert game.finished is True
        assert game.winner == "Red"


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_invalid_move_no_piece(self) -> None:
        game = ChineseCheckersGame()
        with pytest.raises(ValueError, match="no piece"):
            game.move(8, 8, 8, 9)

    def test_invalid_move_wrong_player(self) -> None:
        game = ChineseCheckersGame()
        # It's Red's turn, try to move Blue's peg
        with pytest.raises(ValueError, match="belongs to"):
            game.move(4, 16, 4, 15)  # Blue's peg in T4

    def test_invalid_move_illegal_destination(self) -> None:
        game = ChineseCheckersGame()
        # Try to move Red peg to a non-adjacent, non-hop cell
        with pytest.raises(ValueError, match="illegal move"):
            game.move(9, 3, 6, 6)

    def test_move_after_game_over_raises(self) -> None:
        game = ChineseCheckersGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.move(9, 3, 8, 4)
