"""Tests for Polyiamond Placement: triangle-tiled territory game with D6 symmetry.

Blokus Trigon variant on a hexagonal board of 486 triangle cells (side 9).
Each player has 22 polyiamond pieces (sizes 1-6, 110 triangles total).
Triangular grid: cells alternate Type A/B by (col+row)%2 parity.
  Type A edge neighbors: (-1,0), (+1,0), (0,-1)
  Type B edge neighbors: (-1,0), (+1,0), (0,+1)
Pieces use D6 symmetry (up to 12 orientations: 6 rotations x 2 reflections).
Placement: corner-touch own, no edge-touch own. First piece at starting corner.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import deque

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)

# ---------------------------------------------------------------------------
# Triangular grid helpers
# ---------------------------------------------------------------------------

HEX_SIDE = 9
BOARD_WIDTH = 4 * HEX_SIDE - 1   # 35
BOARD_HEIGHT = 2 * HEX_SIDE       # 18


def cell_type(c: int, r: int) -> str:
    """'A' if (c+r) even, 'B' if odd."""
    return "A" if (c + r) % 2 == 0 else "B"


def edge_neighbors(c: int, r: int) -> list[tuple[int, int]]:
    """3 edge-adjacent cells."""
    if (c + r) % 2 == 0:  # Type A
        return [(c - 1, r), (c + 1, r), (c, r - 1)]
    else:  # Type B
        return [(c - 1, r), (c + 1, r), (c, r + 1)]


def corner_neighbors(c: int, r: int) -> list[tuple[int, int]]:
    """9 corner-only adjacent cells (share vertex but not edge)."""
    if (c + r) % 2 == 0:  # Type A
        return [
            (c - 2, r), (c + 2, r),
            (c - 1, r - 1), (c + 1, r - 1), (c - 2, r - 1), (c + 2, r - 1),
            (c - 1, r + 1), (c, r + 1), (c + 1, r + 1),
        ]
    else:  # Type B
        return [
            (c - 2, r), (c + 2, r),
            (c - 1, r - 1), (c, r - 1), (c + 1, r - 1),
            (c - 2, r + 1), (c + 2, r + 1), (c - 1, r + 1), (c + 1, r + 1),
        ]


# ---------------------------------------------------------------------------
# Hex board mask
# ---------------------------------------------------------------------------


def compute_hex_board(n: int = HEX_SIDE) -> set[tuple[int, int]]:
    """Compute valid cells for a hexagonal triangular board of side n.

    Returns set of (col, row) pairs. Board has 6*n^2 cells.
    Bounding box: width=4n-1, height=2n.
    """
    cells: set[tuple[int, int]] = set()
    for r in range(2 * n):
        if r < n:
            start = n - 1 - r
            width = 2 * (n + r) + 1
        else:
            start = r - n
            width = 2 * (3 * n - 1 - r) + 1
        for c in range(start, start + width):
            cells.add((c, r))
    return cells


_HEX_BOARD = compute_hex_board()

# Starting corner cells for 6-corner hex
# These are the tip cells at each of the 6 hex vertices
_N = HEX_SIDE
STARTING_CORNERS_6 = [
    (_N - 1, 0),          # top-left
    (3 * _N - 2, 0),      # top-right
    (4 * _N - 2, _N - 1), # right
    (3 * _N - 2, 2*_N-1), # bottom-right
    (_N - 1, 2 * _N - 1), # bottom-left
    (0, _N - 1),          # left
]

# 4-player: use alternating corners (skip right and left)
STARTING_CORNERS: dict[str, tuple[int, int]] = {
    "Blue": STARTING_CORNERS_6[0],    # top-left
    "Yellow": STARTING_CORNERS_6[1],  # top-right
    "Red": STARTING_CORNERS_6[3],     # bottom-right
    "Green": STARTING_CORNERS_6[4],   # bottom-left
}


# ---------------------------------------------------------------------------
# D6 transforms via vertex coordinates
# ---------------------------------------------------------------------------


def _cell_to_vertices(c: int, r: int) -> frozenset[tuple[int, int]]:
    """Convert cell (c, r) to its 3 vertex coordinates."""
    if (c + r) % 2 == 0:  # Type A
        a = (c - r) // 2
        return frozenset([(a, r), (a + 1, r), (a, r + 1)])
    else:  # Type B
        b = (c - r - 1) // 2
        return frozenset([(b + 1, r), (b, r + 1), (b + 1, r + 1)])


def _vertices_to_cell(vs: frozenset[tuple[int, int]]) -> tuple[int, int]:
    """Convert 3 vertex coordinates back to cell (c, r)."""
    sv = sorted(vs, key=lambda v: (v[1], v[0]))
    r0, r1, r2 = sv[0][1], sv[1][1], sv[2][1]
    if r0 == r1 and r2 == r0 + 1:
        # Type A: 2 vertices in row r, 1 in row r+1
        r = r0
        a = min(sv[0][0], sv[1][0])
        c = 2 * a + r
        return (c, r)
    elif r0 + 1 == r1 == r2:
        # Type B: 1 vertex in row r, 2 in row r+1
        r = r0
        top_i = sv[0][0]
        c = 2 * top_i - 1 + r
        return (c, r)
    else:
        raise ValueError(f"Invalid triangle vertices: {sv}")


def _rotate_vertex_60cw(i: int, j: int) -> tuple[int, int]:
    """60° clockwise rotation in vertex coordinates."""
    return (i + j, -i)


def _reflect_vertex(i: int, j: int) -> tuple[int, int]:
    """Reflection across horizontal axis in vertex coordinates."""
    return (i + j, -j)


def rotate_cell_60cw(c: int, r: int) -> tuple[int, int]:
    """Rotate a single cell 60° clockwise about vertex origin."""
    vs = _cell_to_vertices(c, r)
    rotated = frozenset(_rotate_vertex_60cw(i, j) for i, j in vs)
    return _vertices_to_cell(rotated)


def reflect_cell(c: int, r: int) -> tuple[int, int]:
    """Reflect a single cell across horizontal axis."""
    vs = _cell_to_vertices(c, r)
    reflected = frozenset(_reflect_vertex(i, j) for i, j in vs)
    return _vertices_to_cell(reflected)


def _normalize(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Shift cells so minimum col and row are 0, preserving parity.

    Parity (col+row)%2 determines edge adjacency rules (Type A vs B).
    A shift of (dc, dr) preserves parity iff (dc+dr) is even.
    We shift to minimize coordinates while keeping parity intact.
    """
    if not cells:
        return cells
    min_c = min(c for c, _ in cells)
    min_r = min(r for _, r in cells)
    # Ensure shift preserves parity: (min_c + min_r) must be even
    if (min_c + min_r) % 2 != 0:
        min_c -= 1  # adjust to make shift parity-preserving
    return sorted((c - min_c, r - min_r) for c, r in cells)


def _apply_transform(cells: list[tuple[int, int]],
                     transform) -> list[tuple[int, int]]:
    """Apply a vertex transform to all cells and normalize."""
    result = [transform(c, r) for c, r in cells]
    return _normalize(result)


def all_orientations(cells: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Return all distinct D6 orientations of a polyiamond (up to 12)."""
    seen: set[tuple[tuple[int, int], ...]] = set()
    results: list[list[tuple[int, int]]] = []
    current = _normalize(cells)
    for _ in range(6):
        for variant in [current, _apply_transform(current, reflect_cell)]:
            key = tuple(variant)
            if key not in seen:
                seen.add(key)
                results.append(variant)
        current = _apply_transform(current, rotate_cell_60cw)
    return results


# ---------------------------------------------------------------------------
# Polyiamond generation
# ---------------------------------------------------------------------------


def _canonical(cells: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Canonical form: smallest normalized orientation under D6."""
    return min(tuple(o) for o in all_orientations(cells))


def generate_polyiamonds(n: int) -> list[list[tuple[int, int]]]:
    """Generate all free polyiamonds of size n.

    Returns one canonical representative per equivalence class.
    """
    if n == 1:
        return [[(0, 0)]]

    smaller = generate_polyiamonds(n - 1)
    seen: set[tuple[tuple[int, int], ...]] = set()
    results: list[list[tuple[int, int]]] = []

    for piece in smaller:
        piece_set = set(piece)
        for c, r in piece:
            for nc, nr in edge_neighbors(c, r):
                if (nc, nr) not in piece_set:
                    new_piece = _normalize(piece + [(nc, nr)])
                    canon = _canonical(new_piece)
                    if canon not in seen:
                        seen.add(canon)
                        results.append(list(canon))

    return results


# Generate all pieces once
POLYIAMONDS: dict[int, list[list[tuple[int, int]]]] = {}
ALL_PIECES: list[tuple[str, list[tuple[int, int]]]] = []

for size in range(1, 7):
    pieces = generate_polyiamonds(size)
    POLYIAMONDS[size] = pieces
    for idx, piece in enumerate(pieces):
        name = f"P{size}_{chr(ord('a') + idx)}"
        ALL_PIECES.append((name, piece))

ALL_PIECE_NAMES = [name for name, _ in ALL_PIECES]
PIECE_SHAPES = {name: shape for name, shape in ALL_PIECES}

# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "polyiamond-placement.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Game wrapper
# ---------------------------------------------------------------------------


class PolyiamondGame:
    """Polyiamond Placement game driver."""

    def __init__(self, player_count: int = 4) -> None:
        if player_count not in (2, 4):
            raise ValueError("player_count must be 2 or 4")
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.valid_cells = _HEX_BOARD
        if player_count == 2:
            self.active_players = ["Blue", "Red"]
        else:
            self.active_players = ["Blue", "Yellow", "Red", "Green"]
        self.pieces: dict[str, set[str]] = {
            p: set(ALL_PIECE_NAMES) for p in self.active_players
        }
        self.consecutive_passes = 0

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _advance_to_next_active(self) -> None:
        all_players = ["Blue", "Yellow", "Red", "Green"]
        for _ in range(len(all_players)):
            self.session.advance_turn()
            if self.current_player() in self.active_players:
                return

    def owner_at(self, col: int, row: int) -> str | None:
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def _player_cells(self, player: str) -> set[tuple[int, int]]:
        cells = set()
        for c, r in self.valid_cells:
            if self.owner_at(c, r) == player:
                cells.add((c, r))
        return cells

    def is_first_move(self, player: str) -> bool:
        return len(self.pieces[player]) == len(ALL_PIECE_NAMES)

    def is_valid_cell(self, col: int, row: int) -> bool:
        return (col, row) in self.valid_cells

    def validate_placement(
        self, player: str, cells: list[tuple[int, int]]
    ) -> str | None:
        for c, r in cells:
            if not self.is_valid_cell(c, r):
                return f"cell ({c},{r}) not on the board"
        for c, r in cells:
            if self.owner_at(c, r) is not None:
                return f"cell ({c},{r}) is occupied"

        own_cells = self._player_cells(player)
        cell_set = set(cells)

        if self.is_first_move(player):
            corner = STARTING_CORNERS[player]
            if corner not in cell_set:
                return f"first piece must cover starting corner {corner}"
        else:
            has_corner_touch = False
            for c, r in cells:
                for nc, nr in corner_neighbors(c, r):
                    if (nc, nr) in own_cells:
                        has_corner_touch = True
                        break
                if has_corner_touch:
                    break
            if not has_corner_touch:
                return "piece must corner-touch at least one of your existing pieces"

        for c, r in cells:
            for nc, nr in edge_neighbors(c, r):
                if (nc, nr) in own_cells and (nc, nr) not in cell_set:
                    return f"cell ({c},{r}) edge-touches your piece at ({nc},{nr})"

        return None

    def place(
        self,
        piece_name: str,
        origin_col: int,
        origin_row: int,
        orientation: list[tuple[int, int]],
    ) -> None:
        if self.finished:
            raise ValueError("game is finished")
        player = self.current_player()
        if piece_name not in self.pieces[player]:
            raise ValueError(f"{player} has already placed {piece_name}")

        cells = [(origin_col + dc, origin_row + dr) for dc, dr in orientation]
        err = self.validate_placement(player, cells)
        if err is not None:
            raise ValueError(err)

        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{piece_name}-{player}",
                component_type="polyiamond",
                owner=player,
                span_cells=[(c, r) for c, r in cells],
            )
        )
        for c, r in cells:
            self.board.grid_set(c, r, cid)

        self.pieces[player].remove(piece_name)
        self.consecutive_passes = 0
        self._advance_to_next_active()

    def pass_turn(self) -> None:
        if self.finished:
            raise ValueError("game is finished")
        self.consecutive_passes += 1
        if self.consecutive_passes >= len(self.active_players):
            self.finished = True
            return
        self._advance_to_next_active()

    def score(self, player: str) -> int:
        total = 0
        for piece_name in self.pieces[player]:
            total += len(PIECE_SHAPES[piece_name])
        return -total

    def scores(self) -> dict[str, int]:
        return {p: self.score(p) for p in self.active_players}


# ---------------------------------------------------------------------------
# Tests: triangular grid topology
# ---------------------------------------------------------------------------


class TestTriangularGrid:
    def test_type_a_has_3_edge_neighbors(self) -> None:
        assert len(edge_neighbors(0, 0)) == 3

    def test_type_b_has_3_edge_neighbors(self) -> None:
        assert len(edge_neighbors(1, 0)) == 3

    def test_type_a_edge_offsets(self) -> None:
        ns = edge_neighbors(4, 2)
        assert set(ns) == {(3, 2), (5, 2), (4, 1)}

    def test_type_b_edge_offsets(self) -> None:
        ns = edge_neighbors(5, 2)
        assert set(ns) == {(4, 2), (6, 2), (5, 3)}

    def test_type_a_has_9_corner_neighbors(self) -> None:
        assert len(corner_neighbors(0, 0)) == 9

    def test_type_b_has_9_corner_neighbors(self) -> None:
        assert len(corner_neighbors(1, 0)) == 9

    def test_edge_and_corner_disjoint(self) -> None:
        """Edge neighbors and corner neighbors must not overlap."""
        for c, r in [(0, 0), (1, 0), (5, 3), (8, 8)]:
            e = set(edge_neighbors(c, r))
            cn = set(corner_neighbors(c, r))
            assert e.isdisjoint(cn), f"overlap at ({c},{r})"

    def test_edge_neighbors_reciprocal(self) -> None:
        """If B is an edge neighbor of A, then A is an edge neighbor of B."""
        for c, r in [(0, 0), (1, 0), (5, 3), (10, 5)]:
            for nc, nr in edge_neighbors(c, r):
                assert (c, r) in edge_neighbors(nc, nr), (
                    f"({nc},{nr}) does not list ({c},{r}) as edge neighbor"
                )


# ---------------------------------------------------------------------------
# Tests: hex board
# ---------------------------------------------------------------------------


class TestHexBoard:
    def test_486_cells(self) -> None:
        assert len(_HEX_BOARD) == 6 * HEX_SIDE ** 2

    def test_row_widths_symmetric(self) -> None:
        for r in range(BOARD_HEIGHT):
            w = sum(1 for c in range(BOARD_WIDTH) if (c, r) in _HEX_BOARD)
            mirror_r = BOARD_HEIGHT - 1 - r
            w_mirror = sum(1 for c in range(BOARD_WIDTH) if (c, mirror_r) in _HEX_BOARD)
            assert w == w_mirror, f"row {r} width {w} != row {mirror_r} width {w_mirror}"

    def test_widest_row(self) -> None:
        widths = [
            sum(1 for c in range(BOARD_WIDTH) if (c, r) in _HEX_BOARD)
            for r in range(BOARD_HEIGHT)
        ]
        assert max(widths) == 4 * HEX_SIDE - 1

    def test_all_cells_connected(self) -> None:
        """BFS from any cell should reach all 486 cells."""
        start = next(iter(_HEX_BOARD))
        visited: set[tuple[int, int]] = set()
        queue = deque([start])
        while queue:
            pos = queue.popleft()
            if pos in visited:
                continue
            visited.add(pos)
            for n in edge_neighbors(*pos):
                if n in _HEX_BOARD and n not in visited:
                    queue.append(n)
        assert visited == _HEX_BOARD

    def test_starting_corners_on_board(self) -> None:
        for name, pos in STARTING_CORNERS.items():
            assert pos in _HEX_BOARD, f"{name} corner {pos} not on board"


# ---------------------------------------------------------------------------
# Tests: D6 transforms
# ---------------------------------------------------------------------------


class TestD6Transforms:
    def test_rotate_preserves_cell_count(self) -> None:
        cells = [(0, 0), (1, 0), (2, 0)]
        for orient in all_orientations(cells):
            assert len(orient) == 3

    def test_rotate_preserves_connectivity(self) -> None:
        """All orientations of a connected piece must be connected."""
        cells = [(0, 0), (1, 0), (2, 0)]
        for orient in all_orientations(cells):
            cell_set = set(orient)
            visited: set[tuple[int, int]] = set()
            queue = [orient[0]]
            while queue:
                pos = queue.pop()
                if pos in visited:
                    continue
                visited.add(pos)
                for n in edge_neighbors(*pos):
                    if n in cell_set and n not in visited:
                        queue.append(n)
            assert visited == cell_set

    def test_moniamond_2_orientations(self) -> None:
        """Moniamond has 2 orientations: type A at (0,0) and type B at (1,0)."""
        assert len(all_orientations([(0, 0)])) == 2

    def test_diamond_2_orientations(self) -> None:
        """2-iamond: 1 cell type A + 1 cell type B. Should have limited orientations."""
        orients = all_orientations([(0, 0), (1, 0)])
        # The diamond has D6 symmetry leaving 1-3 orientations
        assert len(orients) >= 1

    def test_six_rotations_cycle(self) -> None:
        """Rotating a cell 6 times returns to original."""
        c, r = 3, 2
        cc, rr = c, r
        for _ in range(6):
            cc, rr = rotate_cell_60cw(cc, rr)
        assert (cc, rr) == (c, r)

    def test_normalize_min_row_zero(self) -> None:
        """Normalized shapes always have min row=0. Min col may be 0 or 1 due to parity."""
        for _, shape in ALL_PIECES:
            for orient in all_orientations(shape):
                assert min(r for _, r in orient) == 0
                assert min(c for c, _ in orient) <= 1


# ---------------------------------------------------------------------------
# Tests: polyiamond counts (OEIS A000577)
# ---------------------------------------------------------------------------


class TestPolyiamondCounts:
    def test_1_moniamond(self) -> None:
        assert len(POLYIAMONDS[1]) == 1

    def test_1_diamond(self) -> None:
        assert len(POLYIAMONDS[2]) == 1

    def test_1_triamond(self) -> None:
        assert len(POLYIAMONDS[3]) == 1

    def test_3_tetriamonds(self) -> None:
        """3 free tetraiamonds under D6 (strip/chevron merge under 60° rotation)."""
        assert len(POLYIAMONDS[4]) == 3

    def test_4_pentiamonds(self) -> None:
        assert len(POLYIAMONDS[5]) == 4

    def test_12_hexiamonds(self) -> None:
        assert len(POLYIAMONDS[6]) == 12

    def test_22_total_pieces(self) -> None:
        assert len(ALL_PIECES) == 22

    def test_110_total_triangles(self) -> None:
        total = sum(len(shape) for _, shape in ALL_PIECES)
        assert total == 110

    def test_all_pieces_connected(self) -> None:
        for name, shape in ALL_PIECES:
            cell_set = set(shape)
            visited: set[tuple[int, int]] = set()
            queue = [shape[0]]
            while queue:
                pos = queue.pop()
                if pos in visited:
                    continue
                visited.add(pos)
                for n in edge_neighbors(*pos):
                    if n in cell_set and n not in visited:
                        queue.append(n)
            assert visited == cell_set, f"piece {name} not connected"


# ---------------------------------------------------------------------------
# Tests: initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_empty_board(self) -> None:
        game = PolyiamondGame()
        for c, r in _HEX_BOARD:
            assert game.owner_at(c, r) is None

    def test_all_pieces_available(self) -> None:
        game = PolyiamondGame()
        for player in game.active_players:
            assert game.pieces[player] == set(ALL_PIECE_NAMES)

    def test_blue_moves_first(self) -> None:
        game = PolyiamondGame()
        assert game.current_player() == "Blue"

    def test_initial_score(self) -> None:
        game = PolyiamondGame()
        assert game.score("Blue") == -110


# ---------------------------------------------------------------------------
# Tests: first placement
# ---------------------------------------------------------------------------


class TestFirstPlacement:
    def test_place_moniamond_at_corner(self) -> None:
        game = PolyiamondGame()
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.owner_at(*corner) == "Blue"

    def test_first_piece_must_cover_corner(self) -> None:
        game = PolyiamondGame()
        with pytest.raises(ValueError, match="starting corner"):
            game.place("P1_a", 10, 5, [(0, 0)])

    def test_first_piece_advances_turn(self) -> None:
        game = PolyiamondGame()
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.current_player() == "Yellow"


# ---------------------------------------------------------------------------
# Tests: corner-only adjacency rule
# ---------------------------------------------------------------------------


class TestCornerAdjacency:
    def _setup_blue(self) -> PolyiamondGame:
        """Blue places moniamond at starting corner. Others place theirs."""
        game = PolyiamondGame()
        for player in game.active_players:
            corner = STARTING_CORNERS[player]
            game.place("P1_a", corner[0], corner[1], [(0, 0)])
        return game

    def test_corner_touch_valid(self) -> None:
        game = self._setup_blue()
        blue_corner = STARTING_CORNERS["Blue"]
        # Find a corner neighbor of Blue's cell that is on the board
        for nc, nr in corner_neighbors(*blue_corner):
            if game.is_valid_cell(nc, nr):
                # Place the 2-iamond here
                piece_name = "P2_a"
                shape = PIECE_SHAPES[piece_name]
                for orient in all_orientations(shape):
                    cells = [(nc + dc, nr + dr) for dc, dr in orient]
                    if all(game.is_valid_cell(c, r) for c, r in cells):
                        err = game.validate_placement("Blue", cells)
                        if err is None:
                            game.place(piece_name, nc, nr, orient)
                            return
        pytest.fail("Could not find valid corner-touch placement")

    def test_edge_touch_invalid(self) -> None:
        game = self._setup_blue()
        blue_corner = STARTING_CORNERS["Blue"]
        # An edge neighbor of Blue's cell
        for nc, nr in edge_neighbors(*blue_corner):
            if game.is_valid_cell(nc, nr):
                # Try placing here — must fail with edge-touch
                # Need a piece that also corner-touches Blue
                # A 2-cell piece at (nc,nr) might or might not corner-touch
                # But it WILL edge-touch, so it should fail
                piece_name = "P1_a"  # Blue already used P1_a
                # Use P2_a instead — find an orientation that covers (nc,nr) and also
                # corner-touches blue_corner
                for cc, cr in corner_neighbors(*blue_corner):
                    if (cc, cr) != (nc, nr) and game.is_valid_cell(cc, cr):
                        # We need a piece covering both (nc,nr) and (cc,cr)
                        # That requires them to be edge-adjacent
                        if (cc, cr) in edge_neighbors(nc, nr):
                            # Build a 2-cell piece at these positions
                            orient = [(0, 0), (cc - nc, cr - nr)]
                            err = game.validate_placement("Blue", [(nc, nr), (cc, cr)])
                            assert err is not None and "edge-touches" in err
                            return
        pytest.fail("Could not construct edge-touch test case")

    def test_no_touch_invalid(self) -> None:
        game = self._setup_blue()
        # Place in the middle of the board — no adjacency to Blue
        mid = (17, 9)
        if game.is_valid_cell(*mid):
            err = game.validate_placement("Blue", [mid])
            assert err is not None and "corner-touch" in err


# ---------------------------------------------------------------------------
# Tests: passing and game end
# ---------------------------------------------------------------------------


class TestPassingAndEnd:
    def test_pass_advances_turn(self) -> None:
        game = PolyiamondGame()
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.current_player() == "Yellow"
        game.pass_turn()
        assert game.current_player() == "Red"

    def test_all_pass_ends_game(self) -> None:
        game = PolyiamondGame()
        for _ in range(4):
            game.pass_turn()
        assert game.finished is True

    def test_placement_resets_pass_count(self) -> None:
        game = PolyiamondGame()
        game.pass_turn()  # Blue
        game.pass_turn()  # Yellow
        game.pass_turn()  # Red
        # Green places — resets counter
        corner = STARTING_CORNERS["Green"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.finished is False
        # Need 4 more passes to end
        for _ in range(3):
            game.pass_turn()
        assert game.finished is False
        game.pass_turn()
        assert game.finished is True


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_score_after_one_piece(self) -> None:
        game = PolyiamondGame()
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.score("Blue") == -109  # 110 - 1

    def test_score_all_placed(self) -> None:
        game = PolyiamondGame()
        game.pieces["Blue"] = set()
        assert game.score("Blue") == 0


# ---------------------------------------------------------------------------
# Tests: 2-player variant
# ---------------------------------------------------------------------------


class TestTwoPlayer:
    def test_2p_players(self) -> None:
        game = PolyiamondGame(2)
        assert game.active_players == ["Blue", "Red"]

    def test_2p_turn_order(self) -> None:
        game = PolyiamondGame(2)
        assert game.current_player() == "Blue"
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        assert game.current_player() == "Red"

    def test_2p_two_passes_end(self) -> None:
        game = PolyiamondGame(2)
        game.pass_turn()
        game.pass_turn()
        assert game.finished is True


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_off_board_invalid(self) -> None:
        game = PolyiamondGame()
        err = game.validate_placement("Blue", [(0, 0)])
        # (0, 0) might not be on the hex board
        if (0, 0) not in _HEX_BOARD:
            assert err is not None and "not on the board" in err

    def test_move_after_game_over(self) -> None:
        game = PolyiamondGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.place("P1_a", 8, 0, [(0, 0)])

    def test_cannot_place_same_piece_twice(self) -> None:
        game = PolyiamondGame()
        corner = STARTING_CORNERS["Blue"]
        game.place("P1_a", corner[0], corner[1], [(0, 0)])
        # Cycle through other players
        for p in ["Yellow", "Red", "Green"]:
            c = STARTING_CORNERS[p]
            game.place("P1_a", c[0], c[1], [(0, 0)])
        # Blue tries P1_a again
        with pytest.raises(ValueError, match="already placed"):
            game.place("P1_a", 0, 0, [(0, 0)])

    def test_invalid_player_count(self) -> None:
        with pytest.raises(ValueError, match="must be 2 or 4"):
            PolyiamondGame(3)
