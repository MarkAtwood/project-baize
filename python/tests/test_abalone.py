"""Tests for Abalone: hex-grid marble-pushing strategy game.

Two players (Black, White) each start with 14 marbles on a 61-cell regular
hexagonal board (radius 5). Players alternate turns moving 1-3 inline marbles
one step in any hex direction. A group can push a shorter opponent line off
the board edge (sumito): 3v2, 3v1, 2v1. First to push 6 opponent marbles off
the board wins.

Belgian Daisy opening: each player's 14 marbles form two 7-cell rosettes
(center + 6 neighbors). Black near top, White near bottom.

Board coordinates: offset hex grid in a 9x9 bounding box with valid_cells
defining the hexagonal shape. Row widths: 5-6-7-8-9-8-7-6-5 = 61 cells.

Hex neighbors (same convention as other baize hex games):
  (-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)
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


# ---------------------------------------------------------------------------
# Board geometry constants
# ---------------------------------------------------------------------------

HEX_DIRS: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]

# Row ranges: (first_col, last_col) for each row 0..8
ROW_RANGES: list[tuple[int, int]] = [
    (4, 8),  # row 0: 5 cells
    (3, 8),  # row 1: 6 cells
    (2, 8),  # row 2: 7 cells
    (1, 8),  # row 3: 8 cells
    (0, 8),  # row 4: 9 cells
    (0, 7),  # row 5: 8 cells
    (0, 6),  # row 6: 7 cells
    (0, 5),  # row 7: 6 cells
    (0, 4),  # row 8: 5 cells
]

# Belgian Daisy opening positions
BLACK_POSITIONS: list[tuple[int, int]] = [
    # Left daisy: center (4,1) + 6 neighbors
    (4, 0), (5, 0), (3, 1), (4, 1), (5, 1), (3, 2), (4, 2),
    # Right daisy: center (7,1) + 6 neighbors
    (7, 0), (8, 0), (6, 1), (7, 1), (8, 1), (6, 2), (7, 2),
]

WHITE_POSITIONS: list[tuple[int, int]] = [
    # Left daisy: center (1,7) + 6 neighbors
    (0, 7), (1, 7), (2, 7), (1, 6), (2, 6), (0, 8), (1, 8),
    # Right daisy: center (4,7) + 6 neighbors
    (3, 7), (4, 7), (5, 7), (4, 6), (5, 6), (3, 8), (4, 8),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "abalone.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _all_valid_cells() -> set[tuple[int, int]]:
    """Compute the set of valid (col, row) from ROW_RANGES."""
    cells: set[tuple[int, int]] = set()
    for row, (lo, hi) in enumerate(ROW_RANGES):
        for col in range(lo, hi + 1):
            cells.add((col, row))
    return cells


def _is_edge_cell(col: int, row: int) -> bool:
    """True if (col, row) is on the boundary of the hex board."""
    valid = _all_valid_cells()
    if (col, row) not in valid:
        return False
    for dc, dr in HEX_DIRS:
        nc, nr = col + dc, row + dr
        if (nc, nr) not in valid:
            return True
    return False


# ---------------------------------------------------------------------------
# AbaloneGame helper
# ---------------------------------------------------------------------------


class AbaloneGame:
    """Abalone game driver with inline/broadside movement and sumito pushing."""

    def __init__(self) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None
        self.captured: dict[str, int] = {"Black": 0, "White": 0}
        self._valid = _all_valid_cells()
        self._setup_belgian_daisy()

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
                string_id=f"marble-{owner}-{col}-{row}",
                component_type="marble",
                owner=owner,
            )
        )
        self.board.grid_set(col, row, cid)
        return cid

    def _setup_belgian_daisy(self) -> None:
        for col, row in BLACK_POSITIONS:
            self._place(col, row, "Black")
        for col, row in WHITE_POSITIONS:
            self._place(col, row, "White")

    def owner_at(self, col: int, row: int) -> str | None:
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def is_valid(self, col: int, row: int) -> bool:
        return (col, row) in self._valid

    def neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        return [
            (col + dc, row + dr)
            for dc, dr in HEX_DIRS
            if (col + dc, row + dr) in self._valid
        ]

    def _cells_in_direction(
        self, col: int, row: int, dc: int, dr: int, count: int
    ) -> list[tuple[int, int]]:
        """Walk count steps from (col, row) in direction (dc, dr)."""
        result = []
        c, r = col, row
        for _ in range(count):
            c, r = c + dc, r + dr
            result.append((c, r))
        return result

    def _find_inline_group(
        self, col: int, row: int, dc: int, dr: int
    ) -> list[tuple[int, int]]:
        """Find contiguous same-owner marbles starting from (col, row) going (dc, dr).

        Returns up to 3 cells including the start.
        """
        owner = self.owner_at(col, row)
        if owner is None:
            return []
        group = [(col, row)]
        c, r = col + dc, row + dr
        while len(group) < 3 and self.is_valid(c, r) and self.owner_at(c, r) == owner:
            group.append((c, r))
            c, r = c + dc, r + dr
        return group

    def _inline_push_target(
        self, group: list[tuple[int, int]], dc: int, dr: int
    ) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
        """For an inline move with direction (dc, dr), find opponent marbles being pushed.

        The push direction is (dc, dr): the front of the group is the last cell
        in the group, and pushed opponents are beyond that front.

        Returns (opponent_cells, landing_cell_or_None).
        landing_cell is where the last opponent lands (None = off board = captured).
        """
        front_c, front_r = group[-1]
        opponents: list[tuple[int, int]] = []
        c, r = front_c + dc, front_r + dr
        while self.is_valid(c, r):
            opp_owner = self.owner_at(c, r)
            if opp_owner is None:
                # Empty cell: opponents can be pushed here (no capture)
                return opponents, (c, r)
            if opp_owner == self.owner_at(*group[0]):
                # Blocked by own marble
                return [], None
            opponents.append((c, r))
            c, r = c + dc, r + dr

        # We walked off the board: the last opponent is pushed off (captured)
        if opponents:
            return opponents, None
        return [], None

    def move_inline(
        self, cells: list[tuple[int, int]], dc: int, dr: int
    ) -> dict[str, object]:
        """Move a group of 1-3 marbles inline in direction (dc, dr).

        Returns a dict with keys:
          - 'pushed': list of opponent cells that were pushed
          - 'captured': True if an opponent marble was pushed off
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()

        # Validate group
        if not (1 <= len(cells) <= 3):
            raise ValueError(f"group size must be 1-3, got {len(cells)}")

        if (dc, dr) not in HEX_DIRS:
            raise ValueError(f"invalid direction ({dc},{dr})")

        # Check all cells belong to current player
        for c, r in cells:
            if self.owner_at(c, r) != player:
                raise ValueError(
                    f"cell ({c},{r}) does not belong to {player}"
                )

        # Check cells are contiguous along direction
        for i in range(len(cells) - 1):
            c1, r1 = cells[i]
            c2, r2 = cells[i + 1]
            if (c2 - c1, r2 - r1) != (dc, dr):
                raise ValueError("cells are not contiguous along direction")

        # Determine what's in front of the group
        front_c, front_r = cells[-1]
        next_c, next_r = front_c + dc, front_r + dr

        pushed: list[tuple[int, int]] = []
        captured = False

        if self.is_valid(next_c, next_r) and self.owner_at(next_c, next_r) is None:
            # Empty cell ahead: just move the group
            pass
        elif not self.is_valid(next_c, next_r):
            # Can't move the front marble off the board
            raise ValueError("cannot move own marble off the board")
        else:
            # Something is ahead: check for sumito
            opp_owner = self.owner_at(next_c, next_r)
            if opp_owner == player:
                raise ValueError("blocked by own marble")

            # Count opponent marbles in the push line
            opp_cells: list[tuple[int, int]] = []
            c, r = next_c, next_r
            while self.is_valid(c, r) and self.owner_at(c, r) == opp_owner:
                opp_cells.append((c, r))
                c, r = c + dc, r + dr

            if len(opp_cells) >= len(cells):
                raise ValueError(
                    f"cannot push: {len(cells)}v{len(opp_cells)} "
                    f"(must outnumber opponent)"
                )

            # Check what's behind the opponent line
            if self.is_valid(c, r) and self.owner_at(c, r) is not None:
                raise ValueError("push blocked by marble behind opponent line")

            # Execute the push
            pushed = opp_cells
            if not self.is_valid(c, r):
                # Last opponent marble pushed off the board
                captured = True
                last_opp_c, last_opp_r = opp_cells[-1]
                opp_cid = self.board.grid_get(last_opp_c, last_opp_r)
                self.board.grid_set(last_opp_c, last_opp_r, None)
                self.captured[player] += 1
                # Shift remaining opponents forward
                for i in range(len(opp_cells) - 1, 0, -1):
                    oc, orow = opp_cells[i - 1]
                    cid = self.board.grid_get(oc, orow)
                    nc, nr = oc + dc, orow + dr
                    self.board.grid_set(nc, nr, cid)
                    self.board.grid_set(oc, orow, None)
            else:
                # Push opponents forward into empty cell
                # Move from back to front to avoid overwriting
                for i in range(len(opp_cells) - 1, -1, -1):
                    oc, orow = opp_cells[i]
                    cid = self.board.grid_get(oc, orow)
                    nc, nr = oc + dc, orow + dr
                    self.board.grid_set(nc, nr, cid)
                    self.board.grid_set(oc, orow, None)

        # Move own group forward (from front to back to avoid overwriting)
        for i in range(len(cells) - 1, -1, -1):
            c, r = cells[i]
            cid = self.board.grid_get(c, r)
            nc, nr = c + dc, r + dr
            self.board.grid_set(nc, nr, cid)
            self.board.grid_set(c, r, None)

        # Check win
        opponent = "White" if player == "Black" else "Black"
        if self.captured[player] >= 6:
            self.finished = True
            self.winner = player

        self.session.advance_turn()

        return {"pushed": pushed, "captured": captured}

    def move_broadside(
        self, cells: list[tuple[int, int]], dc: int, dr: int
    ) -> None:
        """Move 2-3 marbles broadside (perpendicular to line axis) one step.

        No pushing allowed on broadside moves.
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()

        if not (2 <= len(cells) <= 3):
            raise ValueError(f"broadside requires 2-3 marbles, got {len(cells)}")

        if (dc, dr) not in HEX_DIRS:
            raise ValueError(f"invalid direction ({dc},{dr})")

        for c, r in cells:
            if self.owner_at(c, r) != player:
                raise ValueError(
                    f"cell ({c},{r}) does not belong to {player}"
                )

        # Check all destination cells are empty and valid
        for c, r in cells:
            nc, nr = c + dc, r + dr
            if not self.is_valid(nc, nr):
                raise ValueError(f"destination ({nc},{nr}) is off the board")
            if self.owner_at(nc, nr) is not None:
                raise ValueError(
                    f"destination ({nc},{nr}) is occupied (no pushing on broadside)"
                )

        # Execute the broadside move
        # First remove all from source, then place at destination
        cids = []
        for c, r in cells:
            cid = self.board.grid_get(c, r)
            self.board.grid_set(c, r, None)
            cids.append(cid)

        for (c, r), cid in zip(cells, cids):
            nc, nr = c + dc, r + dr
            self.board.grid_set(nc, nr, cid)

        self.session.advance_turn()

    def count_marbles(self, player: str) -> int:
        """Count marbles on the board for a player."""
        count = 0
        for row in range(9):
            for col in range(9):
                if self.owner_at(col, row) == player:
                    count += 1
        return count

    def clear_and_place(self, pieces: list[tuple[int, int, str]]) -> None:
        """Clear board and place specific pieces."""
        for r in range(9):
            for c in range(9):
                self.board.grid_set(c, r, None)
        self.session.runtime.components = type(self.session.runtime.components)()
        self.captured = {"Black": 0, "White": 0}
        for col, row, owner in pieces:
            self._place(col, row, owner)


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Abalone"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Black", "White"]

    def test_perfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "perfect"

    def test_hex_grid(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.zone_type == "hex_grid"
        assert zone.adjacency == "hex_6"

    def test_dimensions(self) -> None:
        defn = _load_definition()
        dims = defn.zones["board"].dimensions
        assert dims == [9, 9] or dims == 9

    def test_valid_cells_count(self) -> None:
        defn = _load_definition()
        assert len(defn.zones["board"].valid_cells) == 61

    def test_14_marbles_per_player(self) -> None:
        defn = _load_definition()
        assert defn.components["marble"].count == 14

    def test_alternating_turns(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "alternating"
        assert defn.turn_order.players == ["Black", "White"]

    def test_client_verifiable(self) -> None:
        defn = _load_definition()
        assert len(defn.authority.client_verifiable) > 0

    def test_captured_zone_exists(self) -> None:
        defn = _load_definition()
        assert "captured" in defn.zones
        assert defn.zones["captured"].zone_type == "set"
        assert defn.zones["captured"].per_player is True


# ---------------------------------------------------------------------------
# Tests: board geometry
# ---------------------------------------------------------------------------


class TestBoardGeometry:
    def test_61_valid_cells(self) -> None:
        game = AbaloneGame()
        count = sum(
            1 for r in range(9) for c in range(9)
            if game.is_valid(c, r)
        )
        assert count == 61

    def test_row_widths(self) -> None:
        game = AbaloneGame()
        expected_widths = [5, 6, 7, 8, 9, 8, 7, 6, 5]
        for row, expected in enumerate(expected_widths):
            actual = sum(1 for c in range(9) if game.is_valid(c, row))
            assert actual == expected, f"row {row}: expected {expected}, got {actual}"

    def test_center_has_6_neighbors(self) -> None:
        game = AbaloneGame()
        n = game.neighbors(4, 4)
        assert len(n) == 6

    def test_corner_cells_have_3_neighbors(self) -> None:
        """Each of the 6 corners of the hexagon has exactly 3 neighbors."""
        game = AbaloneGame()
        corners = [(4, 0), (8, 0), (8, 4), (4, 8), (0, 8), (0, 4)]
        for c, r in corners:
            n = game.neighbors(c, r)
            assert len(n) == 3, f"corner ({c},{r}) has {len(n)} neighbors: {n}"

    def test_edge_cells_have_fewer_neighbors(self) -> None:
        """Edge cells (non-corner) should have 4 neighbors."""
        game = AbaloneGame()
        # (5,0) is on the top edge but not a corner
        n = game.neighbors(5, 0)
        assert len(n) == 4

    def test_interior_cells_have_6_neighbors(self) -> None:
        """All cells not on the boundary should have 6 neighbors."""
        game = AbaloneGame()
        valid = _all_valid_cells()
        for c, r in valid:
            if not _is_edge_cell(c, r):
                n = game.neighbors(c, r)
                assert len(n) == 6, f"interior ({c},{r}) has {len(n)} neighbors"

    def test_edge_cell_count(self) -> None:
        """A regular hexagon with side 5 has 24 edge cells (6*(5-1) = 24)."""
        valid = _all_valid_cells()
        edge_count = sum(1 for c, r in valid if _is_edge_cell(c, r))
        assert edge_count == 24

    def test_board_connected(self) -> None:
        """All 61 cells form a single connected component."""
        game = AbaloneGame()
        valid = _all_valid_cells()
        start = next(iter(valid))
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
        assert visited == valid


# ---------------------------------------------------------------------------
# Tests: initial setup (Belgian Daisy)
# ---------------------------------------------------------------------------


class TestBelgianDaisy:
    def test_14_black_marbles(self) -> None:
        game = AbaloneGame()
        assert game.count_marbles("Black") == 14

    def test_14_white_marbles(self) -> None:
        game = AbaloneGame()
        assert game.count_marbles("White") == 14

    def test_28_total_marbles(self) -> None:
        game = AbaloneGame()
        total = game.count_marbles("Black") + game.count_marbles("White")
        assert total == 28

    def test_black_positions(self) -> None:
        game = AbaloneGame()
        for col, row in BLACK_POSITIONS:
            assert game.owner_at(col, row) == "Black", f"({col},{row}) should be Black"

    def test_white_positions(self) -> None:
        game = AbaloneGame()
        for col, row in WHITE_POSITIONS:
            assert game.owner_at(col, row) == "White", f"({col},{row}) should be White"

    def test_remaining_cells_empty(self) -> None:
        game = AbaloneGame()
        occupied = set(BLACK_POSITIONS) | set(WHITE_POSITIONS)
        for c, r in _all_valid_cells():
            if (c, r) not in occupied:
                assert game.owner_at(c, r) is None, f"({c},{r}) should be empty"

    def test_black_daisies_are_rosettes(self) -> None:
        """Each black daisy is a center + its 6 hex neighbors."""
        daisy1_center = (4, 1)
        daisy2_center = (7, 1)
        game = AbaloneGame()
        for center in [daisy1_center, daisy2_center]:
            ns = game.neighbors(*center)
            rosette = set(ns) | {center}
            assert len(rosette) == 7
            for c, r in rosette:
                assert game.owner_at(c, r) == "Black", f"({c},{r}) in daisy should be Black"

    def test_white_daisies_are_rosettes(self) -> None:
        """Each white daisy is a center + its 6 hex neighbors."""
        daisy1_center = (1, 7)
        daisy2_center = (4, 7)
        game = AbaloneGame()
        for center in [daisy1_center, daisy2_center]:
            ns = game.neighbors(*center)
            rosette = set(ns) | {center}
            assert len(rosette) == 7
            for c, r in rosette:
                assert game.owner_at(c, r) == "White", f"({c},{r}) in daisy should be White"

    def test_black_moves_first(self) -> None:
        game = AbaloneGame()
        assert game.current_player() == "Black"

    def test_daisies_do_not_overlap(self) -> None:
        assert len(set(BLACK_POSITIONS)) == 14
        assert len(set(WHITE_POSITIONS)) == 14
        assert set(BLACK_POSITIONS).isdisjoint(set(WHITE_POSITIONS))


# ---------------------------------------------------------------------------
# Tests: single marble movement
# ---------------------------------------------------------------------------


class TestSingleMarbleMove:
    def test_move_single_to_empty(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black")])
        result = game.move_inline([(4, 4)], 1, 0)
        assert game.owner_at(4, 4) is None
        assert game.owner_at(5, 4) == "Black"
        assert result["pushed"] == []
        assert result["captured"] is False

    def test_move_advances_turn(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black"), (0, 8, "White")])
        assert game.current_player() == "Black"
        game.move_inline([(4, 4)], 1, 0)
        assert game.current_player() == "White"

    def test_cannot_move_to_occupied_by_self(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black"), (5, 4, "Black")])
        with pytest.raises(ValueError, match="blocked by own"):
            game.move_inline([(4, 4)], 1, 0)

    def test_cannot_move_off_board(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(8, 4, "Black")])
        with pytest.raises(ValueError, match="cannot move own marble off"):
            game.move_inline([(8, 4)], 1, 0)

    def test_all_six_directions(self) -> None:
        """A marble at center can move in all 6 hex directions."""
        for dc, dr in HEX_DIRS:
            game = AbaloneGame()
            game.clear_and_place([(4, 4, "Black")])
            game.move_inline([(4, 4)], dc, dr)
            assert game.owner_at(4 + dc, 4 + dr) == "Black"
            assert game.owner_at(4, 4) is None


# ---------------------------------------------------------------------------
# Tests: inline group movement (no push)
# ---------------------------------------------------------------------------


class TestInlineGroupMove:
    def test_move_two_inline(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(3, 4, "Black"), (4, 4, "Black")])
        game.move_inline([(3, 4), (4, 4)], 1, 0)
        assert game.owner_at(3, 4) is None
        assert game.owner_at(4, 4) == "Black"
        assert game.owner_at(5, 4) == "Black"

    def test_move_three_inline(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(2, 4, "Black"), (3, 4, "Black"), (4, 4, "Black")])
        game.move_inline([(2, 4), (3, 4), (4, 4)], 1, 0)
        assert game.owner_at(2, 4) is None
        assert game.owner_at(3, 4) == "Black"
        assert game.owner_at(4, 4) == "Black"
        assert game.owner_at(5, 4) == "Black"

    def test_cannot_move_four(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([
            (1, 4, "Black"), (2, 4, "Black"),
            (3, 4, "Black"), (4, 4, "Black"),
        ])
        with pytest.raises(ValueError, match="group size must be 1-3"):
            game.move_inline([(1, 4), (2, 4), (3, 4), (4, 4)], 1, 0)

    def test_group_must_be_contiguous(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(2, 4, "Black"), (4, 4, "Black")])
        with pytest.raises(ValueError, match="not contiguous"):
            game.move_inline([(2, 4), (4, 4)], 1, 0)

    def test_group_must_belong_to_current_player(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(3, 4, "White"), (4, 4, "Black")])
        with pytest.raises(ValueError, match="does not belong"):
            game.move_inline([(3, 4), (4, 4)], 1, 0)


# ---------------------------------------------------------------------------
# Tests: sumito (pushing)
# ---------------------------------------------------------------------------


class TestSumito:
    def test_2v1_push(self) -> None:
        """Two marbles push one opponent marble."""
        game = AbaloneGame()
        game.clear_and_place([
            (3, 4, "Black"), (4, 4, "Black"), (5, 4, "White"),
        ])
        result = game.move_inline([(3, 4), (4, 4)], 1, 0)
        assert game.owner_at(3, 4) is None
        assert game.owner_at(4, 4) == "Black"
        assert game.owner_at(5, 4) == "Black"
        assert game.owner_at(6, 4) == "White"
        assert len(result["pushed"]) == 1

    def test_3v1_push(self) -> None:
        """Three marbles push one opponent marble."""
        game = AbaloneGame()
        game.clear_and_place([
            (2, 4, "Black"), (3, 4, "Black"),
            (4, 4, "Black"), (5, 4, "White"),
        ])
        result = game.move_inline([(2, 4), (3, 4), (4, 4)], 1, 0)
        assert game.owner_at(2, 4) is None
        assert game.owner_at(3, 4) == "Black"
        assert game.owner_at(4, 4) == "Black"
        assert game.owner_at(5, 4) == "Black"
        assert game.owner_at(6, 4) == "White"
        assert len(result["pushed"]) == 1

    def test_3v2_push(self) -> None:
        """Three marbles push two opponent marbles."""
        game = AbaloneGame()
        game.clear_and_place([
            (1, 4, "Black"), (2, 4, "Black"),
            (3, 4, "Black"), (4, 4, "White"), (5, 4, "White"),
        ])
        result = game.move_inline([(1, 4), (2, 4), (3, 4)], 1, 0)
        assert game.owner_at(1, 4) is None
        assert game.owner_at(2, 4) == "Black"
        assert game.owner_at(3, 4) == "Black"
        assert game.owner_at(4, 4) == "Black"
        assert game.owner_at(5, 4) == "White"
        assert game.owner_at(6, 4) == "White"
        assert len(result["pushed"]) == 2

    def test_1v1_rejected(self) -> None:
        """Cannot push with equal numbers."""
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black"), (5, 4, "White")])
        with pytest.raises(ValueError, match="cannot push"):
            game.move_inline([(4, 4)], 1, 0)

    def test_2v2_rejected(self) -> None:
        """Cannot push with equal numbers."""
        game = AbaloneGame()
        game.clear_and_place([
            (3, 4, "Black"), (4, 4, "Black"),
            (5, 4, "White"), (6, 4, "White"),
        ])
        with pytest.raises(ValueError, match="cannot push"):
            game.move_inline([(3, 4), (4, 4)], 1, 0)

    def test_3v3_rejected(self) -> None:
        """Cannot push with equal numbers."""
        game = AbaloneGame()
        game.clear_and_place([
            (1, 4, "Black"), (2, 4, "Black"), (3, 4, "Black"),
            (4, 4, "White"), (5, 4, "White"), (6, 4, "White"),
        ])
        with pytest.raises(ValueError, match="cannot push"):
            game.move_inline([(1, 4), (2, 4), (3, 4)], 1, 0)

    def test_push_blocked_by_marble_behind(self) -> None:
        """Push is blocked when there's a marble (of either color) behind the opponent line."""
        game = AbaloneGame()
        game.clear_and_place([
            (3, 4, "Black"), (4, 4, "Black"),
            (5, 4, "White"), (6, 4, "Black"),
        ])
        with pytest.raises(ValueError, match="blocked"):
            game.move_inline([(3, 4), (4, 4)], 1, 0)


# ---------------------------------------------------------------------------
# Tests: capture (push off edge)
# ---------------------------------------------------------------------------


class TestCapture:
    def test_2v1_push_off_edge(self) -> None:
        """2v1 push on the edge: opponent marble falls off."""
        game = AbaloneGame()
        # White marble at (8,4), edge of board. Black pushes right.
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
        ])
        result = game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert result["captured"] is True
        assert game.owner_at(8, 4) == "Black"
        assert game.captured["Black"] == 1

    def test_3v1_push_off_edge(self) -> None:
        """3v1 push: opponent falls off."""
        game = AbaloneGame()
        game.clear_and_place([
            (5, 4, "Black"), (6, 4, "Black"),
            (7, 4, "Black"), (8, 4, "White"),
        ])
        result = game.move_inline([(5, 4), (6, 4), (7, 4)], 1, 0)
        assert result["captured"] is True
        assert game.captured["Black"] == 1
        assert game.owner_at(8, 4) == "Black"

    def test_3v2_push_off_edge(self) -> None:
        """3v2 push on edge: one opponent falls off, one stays."""
        game = AbaloneGame()
        # Push right along row 4. White at (7,4) and (8,4). 8,4 is edge.
        game.clear_and_place([
            (4, 4, "Black"), (5, 4, "Black"),
            (6, 4, "Black"), (7, 4, "White"), (8, 4, "White"),
        ])
        result = game.move_inline([(4, 4), (5, 4), (6, 4)], 1, 0)
        assert result["captured"] is True
        assert game.captured["Black"] == 1
        # (7,4) White should have moved to (8,4), and (8,4) White fell off
        assert game.owner_at(8, 4) == "White"
        assert game.owner_at(7, 4) == "Black"

    def test_captured_marble_removed_from_board(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
        ])
        assert game.count_marbles("White") == 1
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.count_marbles("White") == 0

    def test_capture_increments_counter(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
        ])
        assert game.captured["Black"] == 0
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.captured["Black"] == 1

    def test_push_off_different_edges(self) -> None:
        """Push off the top edge (row 0 direction)."""
        game = AbaloneGame()
        # Row 0 has cols 4-8. Push marble at (5,0) upward via direction (0,-1)
        # means pushing toward row -1 which is off-board.
        game.clear_and_place([
            (5, 2, "Black"), (5, 1, "Black"), (5, 0, "White"),
        ])
        # Direction (0,-1) = upward
        result = game.move_inline([(5, 2), (5, 1)], 0, -1)
        assert result["captured"] is True
        assert game.captured["Black"] == 1


# ---------------------------------------------------------------------------
# Tests: broadside movement
# ---------------------------------------------------------------------------


class TestBroadsideMove:
    def test_broadside_two(self) -> None:
        """Two marbles move perpendicular to their line axis."""
        game = AbaloneGame()
        # Two marbles side by side horizontally, move them down (0,1)
        game.clear_and_place([(3, 4, "Black"), (4, 4, "Black")])
        game.move_broadside([(3, 4), (4, 4)], 0, 1)
        assert game.owner_at(3, 4) is None
        assert game.owner_at(4, 4) is None
        assert game.owner_at(3, 5) == "Black"
        assert game.owner_at(4, 5) == "Black"

    def test_broadside_three(self) -> None:
        """Three marbles move perpendicular."""
        game = AbaloneGame()
        game.clear_and_place([
            (2, 4, "Black"), (3, 4, "Black"), (4, 4, "Black"),
        ])
        game.move_broadside([(2, 4), (3, 4), (4, 4)], 0, 1)
        assert game.owner_at(2, 5) == "Black"
        assert game.owner_at(3, 5) == "Black"
        assert game.owner_at(4, 5) == "Black"

    def test_broadside_no_push(self) -> None:
        """Broadside move is blocked if destination is occupied."""
        game = AbaloneGame()
        game.clear_and_place([
            (3, 4, "Black"), (4, 4, "Black"), (3, 5, "White"),
        ])
        with pytest.raises(ValueError, match="occupied"):
            game.move_broadside([(3, 4), (4, 4)], 0, 1)

    def test_broadside_off_board(self) -> None:
        """Broadside move is blocked if destination is off board."""
        game = AbaloneGame()
        # (8,0) and (8,1) are on the right edge; moving (1,-1) takes (8,0)
        # to (9,-1) which is off-board.
        game.clear_and_place([(8, 0, "Black"), (8, 1, "Black")])
        with pytest.raises(ValueError, match="off the board"):
            game.move_broadside([(8, 0), (8, 1)], 0, -1)

    def test_broadside_advances_turn(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(3, 4, "Black"), (4, 4, "Black"), (0, 8, "White")])
        assert game.current_player() == "Black"
        game.move_broadside([(3, 4), (4, 4)], 0, 1)
        assert game.current_player() == "White"


# ---------------------------------------------------------------------------
# Tests: win condition
# ---------------------------------------------------------------------------


class TestWinCondition:
    def test_six_captures_wins(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black")])
        game.captured["Black"] = 5
        # Manually set up a capture scenario
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
        ])
        game.captured["Black"] = 5
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.finished is True
        assert game.winner == "Black"

    def test_five_captures_not_enough(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
        ])
        game.captured["Black"] = 4
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.finished is False

    def test_white_can_win(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([
            (4, 4, "Black"),
            (6, 4, "White"), (7, 4, "White"), (8, 4, "Black"),
        ])
        game.captured["White"] = 5
        # Black moves first (throwaway)
        game.move_inline([(4, 4)], -1, 0)
        # White pushes Black off the right edge: 2v1
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.finished is True
        assert game.winner == "White"

    def test_no_play_after_win(self) -> None:
        game = AbaloneGame()
        game.finished = True
        game.winner = "Black"
        with pytest.raises(ValueError, match="game is finished"):
            game.move_inline([(4, 4)], 1, 0)


# ---------------------------------------------------------------------------
# Tests: edge cases and illegal moves
# ---------------------------------------------------------------------------


class TestIllegalMoves:
    def test_invalid_direction(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black")])
        with pytest.raises(ValueError, match="invalid direction"):
            game.move_inline([(4, 4)], 2, 0)

    def test_move_empty_cell(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black")])
        with pytest.raises(ValueError, match="does not belong"):
            game.move_inline([(5, 4)], 1, 0)

    def test_move_opponent_marble(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "White")])
        with pytest.raises(ValueError, match="does not belong"):
            game.move_inline([(4, 4)], 1, 0)

    def test_empty_group(self) -> None:
        game = AbaloneGame()
        with pytest.raises(ValueError, match="group size must be 1-3"):
            game.move_inline([], 1, 0)

    def test_broadside_single_marble_rejected(self) -> None:
        game = AbaloneGame()
        game.clear_and_place([(4, 4, "Black")])
        with pytest.raises(ValueError, match="broadside requires 2-3"):
            game.move_broadside([(4, 4)], 0, 1)


# ---------------------------------------------------------------------------
# Tests: complex scenarios
# ---------------------------------------------------------------------------


class TestScenarios:
    def test_push_does_not_capture_own_marbles(self) -> None:
        """Pushing never removes the pushing player's marbles."""
        game = AbaloneGame()
        game.clear_and_place([
            (3, 4, "Black"), (4, 4, "Black"), (5, 4, "White"),
        ])
        game.move_inline([(3, 4), (4, 4)], 1, 0)
        assert game.count_marbles("Black") == 2
        assert game.count_marbles("White") == 1

    def test_alternating_turns_full_round(self) -> None:
        """Black and White alternate correctly over multiple moves."""
        game = AbaloneGame()
        game.clear_and_place([
            (4, 4, "Black"), (0, 8, "White"),
        ])
        assert game.current_player() == "Black"
        game.move_inline([(4, 4)], 1, 0)
        assert game.current_player() == "White"
        game.move_inline([(0, 8)], 1, 0)
        assert game.current_player() == "Black"

    def test_push_along_diagonal_direction(self) -> None:
        """Sumito works in diagonal hex directions too."""
        game = AbaloneGame()
        # Direction (-1, 1): diagonal
        game.clear_and_place([
            (5, 3, "Black"), (4, 4, "Black"), (3, 5, "White"),
        ])
        result = game.move_inline([(5, 3), (4, 4)], -1, 1)
        assert len(result["pushed"]) == 1
        assert game.owner_at(3, 5) == "Black"
        assert game.owner_at(2, 6) == "White"

    def test_multiple_captures_over_game(self) -> None:
        """Track captures accumulating over multiple pushes."""
        game = AbaloneGame()

        # First capture: push off right edge
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
            (0, 8, "White"),  # White needs a marble on board
        ])
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.captured["Black"] == 1

        # White turn (throwaway)
        game.move_inline([(0, 8)], 0, -1)

        # Second capture: push another off right edge
        game.clear_and_place([
            (6, 4, "Black"), (7, 4, "Black"), (8, 4, "White"),
            (0, 7, "White"),
        ])
        game.captured["Black"] = 1  # preserve count
        game.move_inline([(6, 4), (7, 4)], 1, 0)
        assert game.captured["Black"] == 2
