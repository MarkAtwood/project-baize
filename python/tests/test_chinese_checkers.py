"""Tests for Chinese Checkers: hex star board, step/hop movement, multi-hop chains.

Supports 2, 3, 4, and 6 players on a 121-position hexagram (6-pointed star).
Six seats clockwise: Red(T1), Green(T2), White(T3), Blue(T4), Yellow(T5), Black(T6).
Opposite pairs: T1-T4, T2-T5, T3-T6. Each player starts in their home triangle
and races to fill the opposite triangle.

Player count determines which seats are active:
  2p: Red(T1), Blue(T4)
  3p: Red(T1), White(T3), Yellow(T5)
  4p: Red(T1), Green(T2), Blue(T4), Yellow(T5)
  6p: all
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

_HEX_DIRS: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]

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

OPPOSITE = {"T1": "T4", "T4": "T1", "T2": "T5", "T5": "T2", "T3": "T6", "T6": "T3"}

# Seat-to-triangle mapping (clockwise around the star)
SEAT_TRIANGLE = {
    "Red": "T1", "Green": "T2", "White": "T3",
    "Blue": "T4", "Yellow": "T5", "Black": "T6",
}

# Which seats are active for each player count
SEATS_BY_COUNT: dict[int, list[str]] = {
    2: ["Red", "Blue"],
    3: ["Red", "White", "Yellow"],
    4: ["Red", "Green", "Blue", "Yellow"],
    6: ["Red", "Green", "White", "Blue", "Yellow", "Black"],
}

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "chinese-checkers.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# ChineseCheckersGame helper
# ---------------------------------------------------------------------------


class ChineseCheckersGame:
    """Chinese Checkers game driver supporting 2/3/4/6 players."""

    ALL_SEATS = ["Red", "Green", "White", "Blue", "Yellow", "Black"]

    def __init__(self, player_count: int = 2) -> None:
        if player_count not in SEATS_BY_COUNT:
            raise ValueError(f"player_count must be 2, 3, 4, or 6, got {player_count}")
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None
        self.active_seats = SEATS_BY_COUNT[player_count]
        self._setup_initial_position()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def home(self, player: str) -> list[tuple[int, int]]:
        return ALL_TRIANGLES[SEAT_TRIANGLE[player]]

    def goal(self, player: str) -> list[tuple[int, int]]:
        return ALL_TRIANGLES[OPPOSITE[SEAT_TRIANGLE[player]]]

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _advance_to_next_active(self) -> None:
        """Advance turn, skipping inactive seats."""
        for _ in range(len(self.ALL_SEATS)):
            self.session.advance_turn()
            if self.current_player() in self.active_seats:
                return
        raise RuntimeError("no active player found")

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
        """Place 10 pegs per active player in their home triangles."""
        for seat in self.active_seats:
            for col, row in self.home(seat):
                self._place(col, row, seat)
        # Advance to first active seat if Red isn't active
        if self.current_player() not in self.active_seats:
            self._advance_to_next_active()

    def piece_at(self, col: int, row: int) -> str | None:
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def is_valid_cell(self, col: int, row: int) -> bool:
        return self.board._cell_valid(col, row)

    def neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        result = []
        for dc, dr in _HEX_DIRS:
            nc, nr = col + dc, row + dr
            if self.is_valid_cell(nc, nr):
                result.append((nc, nr))
        return result

    def step_moves(self, col: int, row: int) -> list[tuple[int, int]]:
        return [(nc, nr) for nc, nr in self.neighbors(col, row)
                if self.piece_at(nc, nr) is None]

    def hop_moves(self, col: int, row: int) -> list[tuple[int, int]]:
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
        return self.step_moves(col, row) + self.hop_moves(col, row)

    def move(self, from_col: int, from_row: int, to_col: int, to_row: int) -> str:
        """Execute a move. Returns 'step' or 'hop'.

        After a hop, turn stays with current player (multi-hop chain).
        After a step, turn advances to next active player.
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()
        owner = self.piece_at(from_col, from_row)
        if owner is None:
            raise ValueError(f"no piece at ({from_col},{from_row})")
        if owner != player:
            raise ValueError(f"piece at ({from_col},{from_row}) belongs to {owner}")

        if (to_col, to_row) in self.step_moves(from_col, from_row):
            move_type = "step"
        elif (to_col, to_row) in self.hop_moves(from_col, from_row):
            move_type = "hop"
        else:
            raise ValueError(f"illegal move ({from_col},{from_row})->({to_col},{to_row})")

        cid = self.board.grid_get(from_col, from_row)
        self.board.grid_set(from_col, from_row, None)
        self.board.grid_set(to_col, to_row, cid)

        if move_type == "step":
            self._finish_turn()

        return move_type

    def end_turn(self) -> None:
        self._finish_turn()

    def _finish_turn(self) -> None:
        player = self.current_player()
        if self._check_win(player):
            self.finished = True
            self.winner = player
            return
        self._advance_to_next_active()

    def _check_win(self, player: str) -> bool:
        """Player wins when all 10 of their pegs are in the goal triangle."""
        for col, row in self.goal(player):
            if self.piece_at(col, row) != player:
                return False
        return True

    def count_in_triangle(self, player: str, triangle: list[tuple[int, int]]) -> int:
        return sum(1 for c, r in triangle if self.piece_at(c, r) == player)

    def _clear_and_place(self, pieces: list[tuple[int, int, str]]) -> None:
        """Clear board and place specific pieces."""
        for r in range(17):
            for c in range(17):
                self.board.grid_set(c, r, None)
        self.session.runtime.components = type(self.session.runtime.components)()
        for col, row, owner in pieces:
            self._place(col, row, owner)


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Chinese Checkers"

    def test_six_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Red", "Green", "White", "Blue", "Yellow", "Black"]

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
        assert len(cp) == 60
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
        game = ChineseCheckersGame()
        all_valid = {
            (c, r) for r in range(17) for c in range(17) if game.is_valid_cell(c, r)
        }
        start = (8, 8)
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
        game = ChineseCheckersGame()
        tips = [(12, 0), (16, 4), (12, 12), (4, 16), (0, 12), (4, 4)]
        for tip in tips:
            n = game.neighbors(*tip)
            assert len(n) == 2, f"tip {tip} has {len(n)} neighbors: {n}"

    def test_opposite_triangle_pairs(self) -> None:
        for t1, t2 in [("T1", "T4"), ("T2", "T5"), ("T3", "T6")]:
            assert OPPOSITE[t1] == t2
            assert OPPOSITE[t2] == t1


# ---------------------------------------------------------------------------
# Tests: initial setup — parameterized by player count
# ---------------------------------------------------------------------------


class TestInitialSetup2P:
    def test_red_starts_in_t1(self) -> None:
        game = ChineseCheckersGame(2)
        for col, row in T1:
            assert game.piece_at(col, row) == "Red"

    def test_blue_starts_in_t4(self) -> None:
        game = ChineseCheckersGame(2)
        for col, row in T4:
            assert game.piece_at(col, row) == "Blue"

    def test_20_pegs_total(self) -> None:
        game = ChineseCheckersGame(2)
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.piece_at(c, r) is not None
        )
        assert count == 20

    def test_unused_triangles_empty(self) -> None:
        game = ChineseCheckersGame(2)
        for tri in [T2, T3, T5, T6]:
            for col, row in tri:
                assert game.piece_at(col, row) is None

    def test_red_moves_first(self) -> None:
        game = ChineseCheckersGame(2)
        assert game.current_player() == "Red"


class TestInitialSetup3P:
    def test_active_seats(self) -> None:
        game = ChineseCheckersGame(3)
        assert game.active_seats == ["Red", "White", "Yellow"]

    def test_home_triangles_filled(self) -> None:
        game = ChineseCheckersGame(3)
        for seat in ["Red", "White", "Yellow"]:
            for col, row in game.home(seat):
                assert game.piece_at(col, row) == seat

    def test_30_pegs_total(self) -> None:
        game = ChineseCheckersGame(3)
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.piece_at(c, r) is not None
        )
        assert count == 30

    def test_unused_triangles_empty(self) -> None:
        game = ChineseCheckersGame(3)
        for tri_name in ["T2", "T4", "T6"]:
            for col, row in ALL_TRIANGLES[tri_name]:
                assert game.piece_at(col, row) is None

    def test_red_moves_first(self) -> None:
        game = ChineseCheckersGame(3)
        assert game.current_player() == "Red"


class TestInitialSetup4P:
    def test_active_seats(self) -> None:
        game = ChineseCheckersGame(4)
        assert game.active_seats == ["Red", "Green", "Blue", "Yellow"]

    def test_home_triangles_filled(self) -> None:
        game = ChineseCheckersGame(4)
        for seat in ["Red", "Green", "Blue", "Yellow"]:
            for col, row in game.home(seat):
                assert game.piece_at(col, row) == seat

    def test_40_pegs_total(self) -> None:
        game = ChineseCheckersGame(4)
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.piece_at(c, r) is not None
        )
        assert count == 40

    def test_unused_triangles_empty(self) -> None:
        game = ChineseCheckersGame(4)
        for tri_name in ["T3", "T6"]:
            for col, row in ALL_TRIANGLES[tri_name]:
                assert game.piece_at(col, row) is None


class TestInitialSetup6P:
    def test_active_seats(self) -> None:
        game = ChineseCheckersGame(6)
        assert game.active_seats == ["Red", "Green", "White", "Blue", "Yellow", "Black"]

    def test_all_triangles_filled(self) -> None:
        game = ChineseCheckersGame(6)
        for seat in game.active_seats:
            for col, row in game.home(seat):
                assert game.piece_at(col, row) == seat

    def test_60_pegs_total(self) -> None:
        game = ChineseCheckersGame(6)
        count = sum(
            1 for r in range(17) for c in range(17)
            if game.piece_at(c, r) is not None
        )
        assert count == 60

    def test_center_hex_empty(self) -> None:
        game = ChineseCheckersGame(6)
        tri_cells = set()
        for cells in ALL_TRIANGLES.values():
            tri_cells.update(cells)
        for r in range(17):
            for c in range(17):
                if game.is_valid_cell(c, r) and (c, r) not in tri_cells:
                    assert game.piece_at(c, r) is None


# ---------------------------------------------------------------------------
# Tests: turn order
# ---------------------------------------------------------------------------


class TestTurnOrder:
    def test_2p_alternates_red_blue(self) -> None:
        game = ChineseCheckersGame(2)
        assert game.current_player() == "Red"
        game.move(9, 3, 8, 4)  # Red steps
        assert game.current_player() == "Blue"
        game.move(7, 13, 8, 12)  # Blue steps
        assert game.current_player() == "Red"

    def test_3p_skips_inactive(self) -> None:
        game = ChineseCheckersGame(3)
        # Active: Red, White, Yellow. Turn order should skip Green, Blue, Black.
        assert game.current_player() == "Red"
        game.move(9, 3, 8, 4)
        assert game.current_player() == "White"
        game.move(12, 9, 11, 9)
        assert game.current_player() == "Yellow"
        game.move(3, 9, 4, 9)
        assert game.current_player() == "Red"

    def test_4p_skips_inactive(self) -> None:
        game = ChineseCheckersGame(4)
        # Active: Red, Green, Blue, Yellow
        assert game.current_player() == "Red"
        game.move(9, 3, 8, 4)
        assert game.current_player() == "Green"
        game.move(13, 7, 12, 7)
        assert game.current_player() == "Blue"
        game.move(7, 13, 8, 12)
        assert game.current_player() == "Yellow"
        game.move(3, 9, 4, 9)
        assert game.current_player() == "Red"

    def test_6p_all_play(self) -> None:
        game = ChineseCheckersGame(6)
        order = []
        for _ in range(6):
            p = game.current_player()
            order.append(p)
            # Each player steps one peg from their triangle base toward center
            home = game.home(p)
            # Find a movable peg (one with an empty neighbor)
            for col, row in home:
                steps = game.step_moves(col, row)
                if steps:
                    game.move(col, row, steps[0][0], steps[0][1])
                    break
        assert order == ["Red", "Green", "White", "Blue", "Yellow", "Black"]


# ---------------------------------------------------------------------------
# Tests: step movement (use 2p for simplicity)
# ---------------------------------------------------------------------------


class TestStepMovement:
    def test_step_to_adjacent_empty(self) -> None:
        game = ChineseCheckersGame(2)
        assert game.piece_at(9, 3) == "Red"
        assert game.piece_at(8, 4) is None
        result = game.move(9, 3, 8, 4)
        assert result == "step"
        assert game.piece_at(9, 3) is None
        assert game.piece_at(8, 4) == "Red"

    def test_step_advances_turn(self) -> None:
        game = ChineseCheckersGame(2)
        assert game.current_player() == "Red"
        game.move(9, 3, 8, 4)
        assert game.current_player() == "Blue"

    def test_cannot_step_to_occupied(self) -> None:
        game = ChineseCheckersGame(2)
        assert game.piece_at(12, 0) == "Red"
        assert game.piece_at(12, 1) == "Red"
        moves = game.step_moves(12, 0)
        assert (12, 1) not in moves

    def test_cannot_step_off_board(self) -> None:
        game = ChineseCheckersGame(2)
        moves = game.step_moves(12, 0)
        assert len(moves) == 0

    def test_step_into_center(self) -> None:
        game = ChineseCheckersGame(2)
        game.move(9, 3, 8, 4)
        assert game.piece_at(8, 4) == "Red"


# ---------------------------------------------------------------------------
# Tests: hop movement
# ---------------------------------------------------------------------------


class TestHopMovement:
    def test_single_hop(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Blue")])
        result = game.move(8, 6, 8, 8)
        assert result == "hop"
        assert game.piece_at(8, 6) is None
        assert game.piece_at(8, 7) == "Blue"  # not captured
        assert game.piece_at(8, 8) == "Red"

    def test_hop_does_not_capture(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Red")])
        game.move(8, 6, 8, 8)
        assert game.piece_at(8, 7) == "Red"

    def test_hop_over_own_piece_allowed(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Red")])
        assert (8, 8) in game.hop_moves(8, 6)

    def test_cannot_hop_to_occupied(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Blue"), (8, 8, "Blue")])
        assert (8, 8) not in game.hop_moves(8, 6)

    def test_cannot_hop_over_empty(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red")])
        assert (8, 8) not in game.hop_moves(8, 6)

    def test_hop_respects_board_mask(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(11, 1, "Red"), (12, 0, "Blue")])
        hops = game.hop_moves(11, 1)
        assert all(game.is_valid_cell(c, r) for c, r in hops)


# ---------------------------------------------------------------------------
# Tests: multi-hop chains
# ---------------------------------------------------------------------------


class TestMultiHop:
    def test_hop_does_not_advance_turn(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Blue")])
        assert game.current_player() == "Red"
        game.move(8, 6, 8, 8)
        assert game.current_player() == "Red"

    def test_end_turn_after_hop(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "Blue")])
        game.move(8, 6, 8, 8)
        game.end_turn()
        assert game.current_player() == "Blue"

    def test_multi_hop_chain(self) -> None:
        game = ChineseCheckersGame(2)
        game._clear_and_place([(8, 4, "Red"), (8, 5, "Blue"), (8, 7, "Blue")])
        result1 = game.move(8, 4, 8, 6)
        assert result1 == "hop"
        assert game.current_player() == "Red"

        result2 = game.move(8, 6, 8, 8)
        assert result2 == "hop"
        assert game.current_player() == "Red"

        game.end_turn()
        assert game.current_player() == "Blue"
        assert game.piece_at(8, 8) == "Red"
        assert game.piece_at(8, 4) is None

    def test_multi_hop_3p(self) -> None:
        """Multi-hop in a 3-player game: after hop chain, turn goes to next active."""
        game = ChineseCheckersGame(3)
        game._clear_and_place([(8, 6, "Red"), (8, 7, "White")])
        game.move(8, 6, 8, 8)
        game.end_turn()
        # Red -> skip Green -> White
        assert game.current_player() == "White"


# ---------------------------------------------------------------------------
# Tests: win condition — all player counts
# ---------------------------------------------------------------------------


class TestWinCondition:
    def test_2p_red_wins(self) -> None:
        game = ChineseCheckersGame(2)
        pieces = [(c, r, "Red") for c, r in T4]
        pieces.extend([(c, r, "Blue") for c, r in T1])
        game._clear_and_place(pieces)
        assert game._check_win("Red") is True
        assert game._check_win("Blue") is True  # Blue also in goal (swapped)

    def test_3p_white_wins(self) -> None:
        """White(T3) wins by filling T6."""
        game = ChineseCheckersGame(3)
        pieces = [(c, r, "White") for c, r in T6]
        pieces.extend([(c, r, "Red") for c, r in T1])
        pieces.extend([(c, r, "Yellow") for c, r in T5])
        game._clear_and_place(pieces)
        assert game._check_win("White") is True
        assert game._check_win("Red") is False
        assert game._check_win("Yellow") is False

    def test_4p_green_wins(self) -> None:
        """Green(T2) wins by filling T5."""
        game = ChineseCheckersGame(4)
        pieces = [(c, r, "Green") for c, r in T5]
        pieces.extend([(c, r, "Red") for c, r in T1])
        pieces.extend([(c, r, "Blue") for c, r in T4])
        pieces.extend([(c, r, "Yellow") for c, r in T3])
        game._clear_and_place(pieces)
        assert game._check_win("Green") is True

    def test_6p_black_wins(self) -> None:
        """Black(T6) wins by filling T3."""
        game = ChineseCheckersGame(6)
        # Black's pegs in T3 (goal). Other players in center so they don't overlap.
        pieces = [(c, r, "Black") for c, r in T3]
        # Place other players' pegs in the center hex (avoiding T3)
        center_cells = [
            (c, r) for r in range(17) for c in range(17)
            if game.is_valid_cell(c, r) and (c, r) not in T3
        ]
        idx = 0
        for seat in ["Red", "Green", "White", "Blue", "Yellow"]:
            for _ in range(10):
                pieces.append((center_cells[idx][0], center_cells[idx][1], seat))
                idx += 1
        game._clear_and_place(pieces)
        assert game._check_win("Black") is True

    def test_not_won_initially(self) -> None:
        for pc in [2, 3, 4, 6]:
            game = ChineseCheckersGame(pc)
            for seat in game.active_seats:
                assert game._check_win(seat) is False

    def test_partial_fill_not_a_win(self) -> None:
        game = ChineseCheckersGame(2)
        pieces = [(c, r, "Red") for c, r in T4[:9]]
        pieces.append((8, 8, "Red"))
        pieces.extend([(c, r, "Blue") for c, r in T1])
        game._clear_and_place(pieces)
        assert game._check_win("Red") is False

    def test_win_triggers_on_move(self) -> None:
        game = ChineseCheckersGame(2)
        t4_sorted = sorted(T4)
        pieces = [(c, r, "Red") for c, r in t4_sorted[:9]]
        last_col, last_row = t4_sorted[9]
        adj = None
        for dc, dr in _HEX_DIRS:
            nc, nr = last_col + dc, last_row + dr
            if game.is_valid_cell(nc, nr) and (nc, nr) not in T4:
                adj = (nc, nr)
                break
        assert adj is not None
        pieces.append((adj[0], adj[1], "Red"))
        pieces.extend([(c, r, "Blue") for c, r in T1])
        game._clear_and_place(pieces)

        game.move(adj[0], adj[1], last_col, last_row)
        assert game.finished is True
        assert game.winner == "Red"


# ---------------------------------------------------------------------------
# Tests: goal triangle correctness
# ---------------------------------------------------------------------------


class TestGoalMapping:
    @pytest.mark.parametrize("seat,home_tri,goal_tri", [
        ("Red", "T1", "T4"),
        ("Green", "T2", "T5"),
        ("White", "T3", "T6"),
        ("Blue", "T4", "T1"),
        ("Yellow", "T5", "T2"),
        ("Black", "T6", "T3"),
    ])
    def test_home_goal_opposite(self, seat: str, home_tri: str, goal_tri: str) -> None:
        game = ChineseCheckersGame(6)
        assert game.home(seat) == ALL_TRIANGLES[home_tri]
        assert game.goal(seat) == ALL_TRIANGLES[goal_tri]


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_invalid_player_count(self) -> None:
        with pytest.raises(ValueError, match="must be 2, 3, 4, or 6"):
            ChineseCheckersGame(5)

    def test_invalid_move_no_piece(self) -> None:
        game = ChineseCheckersGame(2)
        with pytest.raises(ValueError, match="no piece"):
            game.move(8, 8, 8, 9)

    def test_invalid_move_wrong_player(self) -> None:
        game = ChineseCheckersGame(2)
        with pytest.raises(ValueError, match="belongs to"):
            game.move(4, 16, 4, 15)

    def test_invalid_move_illegal_destination(self) -> None:
        game = ChineseCheckersGame(2)
        with pytest.raises(ValueError, match="illegal move"):
            game.move(9, 3, 6, 6)

    def test_move_after_game_over_raises(self) -> None:
        game = ChineseCheckersGame(2)
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.move(9, 3, 8, 4)
