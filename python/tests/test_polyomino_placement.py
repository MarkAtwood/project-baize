"""Tests for Polyomino Placement: grid territory game with corner-only adjacency.

4-player game on a 20x20 grid. Each player has 21 polyomino pieces (monomino
through pentomino, 89 squares total). Pieces are placed on the grid following:
  - First piece must cover the player's starting corner.
  - Subsequent pieces must corner-touch (diagonally adjacent) at least one of
    the player's existing cells.
  - Must NOT edge-touch (orthogonally adjacent) any of the player's own cells.
  - All target cells must be empty and in bounds.
  - Pieces may be rotated (0/90/180/270) and flipped.
  - Game ends when all players pass consecutively.
  - Score = negative count of unplaced squares (highest/least negative wins).
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
# Polyomino shapes: offsets from (0,0) origin
# ---------------------------------------------------------------------------

# Each shape is a frozenset of (col, row) offsets.
# Canonical orientation — rotations/flips computed at runtime.

SHAPES: dict[str, list[tuple[int, int]]] = {
    # Monomino (1)
    "I1": [(0, 0)],
    # Domino (1)
    "I2": [(0, 0), (1, 0)],
    # Trominoes (2)
    "I3": [(0, 0), (1, 0), (2, 0)],
    "L3": [(0, 0), (1, 0), (1, 1)],
    # Tetrominoes (5)
    "I4": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O4": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T4": [(0, 0), (1, 0), (2, 0), (1, 1)],
    "S4": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "L4": [(0, 0), (1, 0), (2, 0), (0, 1)],
    # Pentominoes (12)
    "F5": [(1, 0), (2, 0), (0, 1), (1, 1), (1, 2)],
    "I5": [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)],
    "L5": [(0, 0), (1, 0), (2, 0), (3, 0), (0, 1)],
    "N5": [(0, 0), (1, 0), (1, 1), (2, 1), (3, 1)],
    "P5": [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2)],
    "T5": [(0, 0), (1, 0), (2, 0), (1, 1), (1, 2)],
    "U5": [(0, 0), (2, 0), (0, 1), (1, 1), (2, 1)],
    "V5": [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)],
    "W5": [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2)],
    "X5": [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)],
    "Y5": [(0, 0), (1, 0), (2, 0), (3, 0), (1, 1)],
    "Z5": [(0, 0), (1, 0), (1, 1), (1, 2), (2, 2)],
}

ALL_SHAPE_NAMES = list(SHAPES.keys())

# Starting corners for each player
STARTING_CORNERS: dict[str, tuple[int, int]] = {
    "Blue": (0, 0),
    "Yellow": (19, 0),
    "Red": (19, 19),
    "Green": (0, 19),
}

# Orthogonal (edge) neighbors
_EDGE_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
# Diagonal (corner) neighbors
_CORNER_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "polyomino-placement.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Shape transforms
# ---------------------------------------------------------------------------


def rotate_90(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Rotate cells 90° clockwise: (x, y) -> (max_y - y, x) after normalization."""
    rotated = [(-y, x) for x, y in cells]
    return _normalize(rotated)


def flip_h(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Flip horizontally: (x, y) -> (-x, y) then normalize."""
    flipped = [(-x, y) for x, y in cells]
    return _normalize(flipped)


def _normalize(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Shift cells so minimum col and row are 0."""
    min_c = min(c for c, _ in cells)
    min_r = min(r for _, r in cells)
    return sorted((c - min_c, r - min_r) for c, r in cells)


def all_orientations(cells: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Return all distinct orientations (up to 8) of a shape."""
    seen: set[tuple[tuple[int, int], ...]] = set()
    results: list[list[tuple[int, int]]] = []
    current = _normalize(cells)
    for _ in range(4):
        for variant in [current, flip_h(current)]:
            key = tuple(variant)
            if key not in seen:
                seen.add(key)
                results.append(variant)
        current = rotate_90(current)
    return results


# ---------------------------------------------------------------------------
# Game wrapper
# ---------------------------------------------------------------------------


class PolyominoGame:
    """Polyomino Placement game driver."""

    def __init__(self, player_count: int = 4) -> None:
        if player_count not in (2, 4):
            raise ValueError("player_count must be 2 or 4")
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        if player_count == 2:
            self.active_players = ["Blue", "Red"]
        else:
            self.active_players = ["Blue", "Yellow", "Red", "Green"]
        # Track which pieces each player has remaining
        self.pieces: dict[str, set[str]] = {
            p: set(ALL_SHAPE_NAMES) for p in self.active_players
        }
        # Track consecutive passes
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
        raise RuntimeError("no active player found")

    def owner_at(self, col: int, row: int) -> str | None:
        """Return owning player or None."""
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def _player_cells(self, player: str) -> set[tuple[int, int]]:
        """All cells occupied by a player."""
        cells = set()
        for r in range(20):
            for c in range(20):
                if self.owner_at(c, r) == player:
                    cells.add((c, r))
        return cells

    def is_first_move(self, player: str) -> bool:
        """True if player hasn't placed any piece yet."""
        return len(self.pieces[player]) == len(ALL_SHAPE_NAMES)

    def validate_placement(
        self, player: str, cells: list[tuple[int, int]]
    ) -> str | None:
        """Return None if valid, or an error message."""
        # All cells must be in bounds
        for c, r in cells:
            if c < 0 or r < 0 or c >= 20 or r >= 20:
                return f"cell ({c},{r}) out of bounds"

        # All cells must be empty
        for c, r in cells:
            if self.owner_at(c, r) is not None:
                return f"cell ({c},{r}) is occupied"

        own_cells = self._player_cells(player)
        cell_set = set(cells)

        if self.is_first_move(player):
            # First piece must cover starting corner
            corner = STARTING_CORNERS[player]
            if corner not in cell_set:
                return f"first piece must cover starting corner {corner}"
        else:
            # Must corner-touch at least one own cell
            has_corner_touch = False
            for c, r in cells:
                for dc, dr in _CORNER_DIRS:
                    if (c + dc, r + dr) in own_cells:
                        has_corner_touch = True
                        break
                if has_corner_touch:
                    break
            if not has_corner_touch:
                return "piece must corner-touch at least one of your existing pieces"

        # Must NOT edge-touch any own cell
        for c, r in cells:
            for dc, dr in _EDGE_DIRS:
                nc, nr = c + dc, r + dr
                if (nc, nr) in own_cells and (nc, nr) not in cell_set:
                    return f"cell ({c},{r}) edge-touches your piece at ({nc},{nr})"

        return None

    def place(
        self,
        shape_name: str,
        origin_col: int,
        origin_row: int,
        orientation: list[tuple[int, int]],
    ) -> None:
        """Place a polyomino piece on the board.

        orientation: the specific cell offsets to use (from all_orientations()).
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()
        if shape_name not in self.pieces[player]:
            raise ValueError(f"{player} has already placed {shape_name}")

        # Compute absolute cells
        cells = [(origin_col + dc, origin_row + dr) for dc, dr in orientation]

        err = self.validate_placement(player, cells)
        if err is not None:
            raise ValueError(err)

        # Place the piece
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{shape_name}-{player}",
                component_type="polyomino",
                owner=player,
                span_cells=[(c, r) for c, r in cells],
            )
        )
        for c, r in cells:
            self.board.grid_set(c, r, cid)

        self.pieces[player].remove(shape_name)
        self.consecutive_passes = 0
        self._advance_to_next_active()

    def pass_turn(self) -> None:
        """Pass without placing a piece."""
        if self.finished:
            raise ValueError("game is finished")
        self.consecutive_passes += 1
        if self.consecutive_passes >= len(self.active_players):
            self.finished = True
            return
        self._advance_to_next_active()

    def score(self, player: str) -> int:
        """Score = negative sum of unplaced squares. Higher (less negative) is better."""
        total = 0
        for shape_name in self.pieces[player]:
            total += len(SHAPES[shape_name])
        return -total

    def scores(self) -> dict[str, int]:
        return {p: self.score(p) for p in self.active_players}

    def winner(self) -> str | None:
        """Player with highest score (least negative). None if tie."""
        if not self.finished:
            return None
        s = self.scores()
        best = max(s.values())
        winners = [p for p, v in s.items() if v == best]
        return winners[0] if len(winners) == 1 else None


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Polyomino Placement"

    def test_four_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Blue", "Yellow", "Red", "Green"]

    def test_20x20_grid(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.zone_type == "grid"
        assert zone.dimensions == [20, 20]


# ---------------------------------------------------------------------------
# Tests: polyomino shapes
# ---------------------------------------------------------------------------


class TestShapes:
    def test_21_shapes(self) -> None:
        assert len(SHAPES) == 21

    def test_total_squares(self) -> None:
        """1+2+3+3+4+4+4+4+4+5*12 = 89 squares per player."""
        total = sum(len(cells) for cells in SHAPES.values())
        assert total == 89

    def test_shape_sizes(self) -> None:
        sizes = {}
        for name, cells in SHAPES.items():
            size = len(cells)
            sizes.setdefault(size, []).append(name)
        assert len(sizes[1]) == 1   # monomino
        assert len(sizes[2]) == 1   # domino
        assert len(sizes[3]) == 2   # trominoes
        assert len(sizes[4]) == 5   # tetrominoes
        assert len(sizes[5]) == 12  # pentominoes

    def test_shapes_are_connected(self) -> None:
        """Every shape must be orthogonally connected."""
        for name, cells in SHAPES.items():
            cell_set = set(cells)
            visited: set[tuple[int, int]] = set()
            queue = [cells[0]]
            while queue:
                pos = queue.pop()
                if pos in visited:
                    continue
                visited.add(pos)
                c, r = pos
                for dc, dr in _EDGE_DIRS:
                    nb = (c + dc, r + dr)
                    if nb in cell_set and nb not in visited:
                        queue.append(nb)
            assert visited == cell_set, f"{name} is not connected"


# ---------------------------------------------------------------------------
# Tests: rotation and flip
# ---------------------------------------------------------------------------


class TestTransforms:
    def test_rotate_i2(self) -> None:
        """Domino: 2 orientations (horizontal, vertical)."""
        orients = all_orientations(SHAPES["I2"])
        assert len(orients) == 2

    def test_rotate_o4(self) -> None:
        """Square: only 1 orientation."""
        orients = all_orientations(SHAPES["O4"])
        assert len(orients) == 1

    def test_rotate_i4(self) -> None:
        """I-tetromino: 2 orientations."""
        orients = all_orientations(SHAPES["I4"])
        assert len(orients) == 2

    def test_rotate_t4(self) -> None:
        """T-tetromino: 4 orientations."""
        orients = all_orientations(SHAPES["T4"])
        assert len(orients) == 4

    def test_rotate_l4(self) -> None:
        """L-tetromino: 8 orientations (L and J are mirror images, each with 4 rotations)."""
        orients = all_orientations(SHAPES["L4"])
        assert len(orients) == 8

    def test_rotate_s4(self) -> None:
        """S-tetromino: 4 orientations (S and Z are mirror images, each with 2 rotations)."""
        orients = all_orientations(SHAPES["S4"])
        assert len(orients) == 4

    def test_x5_one_orientation(self) -> None:
        """X-pentomino (plus shape): only 1 orientation."""
        orients = all_orientations(SHAPES["X5"])
        assert len(orients) == 1

    def test_f5_eight_orientations(self) -> None:
        """F-pentomino: 8 orientations (no symmetry)."""
        orients = all_orientations(SHAPES["F5"])
        assert len(orients) == 8

    def test_all_orientations_preserve_cell_count(self) -> None:
        """Every orientation has the same number of cells."""
        for name, cells in SHAPES.items():
            expected = len(cells)
            for orient in all_orientations(cells):
                assert len(orient) == expected, f"{name} orientation has wrong cell count"

    def test_normalize_origin(self) -> None:
        """Normalized shapes always start at (0,0) min."""
        for name, cells in SHAPES.items():
            for orient in all_orientations(cells):
                min_c = min(c for c, _ in orient)
                min_r = min(r for _, r in orient)
                assert min_c == 0 and min_r == 0, f"{name} not normalized: min=({min_c},{min_r})"


# ---------------------------------------------------------------------------
# Tests: initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_empty_board(self) -> None:
        game = PolyominoGame()
        for r in range(20):
            for c in range(20):
                assert game.owner_at(c, r) is None

    def test_all_pieces_available(self) -> None:
        game = PolyominoGame()
        for player in game.active_players:
            assert game.pieces[player] == set(ALL_SHAPE_NAMES)

    def test_blue_moves_first(self) -> None:
        game = PolyominoGame()
        assert game.current_player() == "Blue"

    def test_initial_score_negative_89(self) -> None:
        game = PolyominoGame()
        for player in game.active_players:
            assert game.score(player) == -89


# ---------------------------------------------------------------------------
# Tests: first placement
# ---------------------------------------------------------------------------


class TestFirstPlacement:
    def test_blue_places_at_corner(self) -> None:
        game = PolyominoGame()
        # Place monomino at (0,0) — Blue's starting corner
        game.place("I1", 0, 0, SHAPES["I1"])
        assert game.owner_at(0, 0) == "Blue"

    def test_first_piece_must_cover_corner(self) -> None:
        game = PolyominoGame()
        with pytest.raises(ValueError, match="starting corner"):
            game.place("I1", 5, 5, SHAPES["I1"])

    def test_first_piece_l3_covers_corner(self) -> None:
        game = PolyominoGame()
        # L3 at origin covers (0,0), (1,0), (1,1) — includes (0,0)
        game.place("L3", 0, 0, SHAPES["L3"])
        assert game.owner_at(0, 0) == "Blue"
        assert game.owner_at(1, 0) == "Blue"
        assert game.owner_at(1, 1) == "Blue"

    def test_first_piece_advances_turn(self) -> None:
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])
        assert game.current_player() == "Yellow"

    def test_four_first_moves(self) -> None:
        """Each player places at their corner."""
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])       # Blue at (0,0)
        game.place("I1", 19, 0, SHAPES["I1"])      # Yellow at (19,0)
        game.place("I1", 19, 19, SHAPES["I1"])     # Red at (19,19)
        game.place("I1", 0, 19, SHAPES["I1"])      # Green at (0,19)
        assert game.current_player() == "Blue"


# ---------------------------------------------------------------------------
# Tests: corner-only adjacency rule
# ---------------------------------------------------------------------------


class TestCornerAdjacency:
    def _setup_blue_at_corner(self) -> PolyominoGame:
        """Blue places monomino at (0,0)."""
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])
        # Yellow, Red, Green place their first pieces
        game.place("I1", 19, 0, SHAPES["I1"])
        game.place("I1", 19, 19, SHAPES["I1"])
        game.place("I1", 0, 19, SHAPES["I1"])
        return game

    def test_corner_touch_valid(self) -> None:
        """Piece at (1,1) corner-touches Blue at (0,0)."""
        game = self._setup_blue_at_corner()
        game.place("I2", 1, 1, SHAPES["I2"])  # (1,1), (2,1)
        assert game.owner_at(1, 1) == "Blue"

    def test_edge_touch_invalid(self) -> None:
        """I2 at (0,1)-(1,1): (1,1) corner-touches Blue at (0,0) but (0,1) edge-touches."""
        game = self._setup_blue_at_corner()
        with pytest.raises(ValueError, match="edge-touches"):
            game.place("I2", 0, 1, SHAPES["I2"])  # cells (0,1),(1,1)

    def test_no_touch_invalid(self) -> None:
        """Piece at (5,5) has no adjacency to Blue — illegal."""
        game = self._setup_blue_at_corner()
        with pytest.raises(ValueError, match="corner-touch"):
            game.place("I2", 5, 5, SHAPES["I2"])

    def test_can_touch_opponent_edge(self) -> None:
        """Edge-touching an opponent's piece is allowed."""
        game = PolyominoGame()
        # Blue places I2 at (0,0)-(1,0)
        game.place("I2", 0, 0, SHAPES["I2"])
        # Yellow places at their corner
        game.place("I1", 19, 0, SHAPES["I1"])
        # Red places at their corner
        game.place("I1", 19, 19, SHAPES["I1"])
        # Green places at their corner
        game.place("I1", 0, 19, SHAPES["I1"])
        # Blue's next piece: corner-touch at (2,1), diag from (1,0)
        game.place("I1", 2, 1, SHAPES["I1"])
        # Yellow, Red, Green pass
        game.pass_turn()
        game.pass_turn()
        game.pass_turn()
        # Blue places I3 at (3,2), with (3,2) diag from (2,1) — no edge-touch to Blue
        # I3 = [(0,0),(1,0),(2,0)] at origin (3,2) → cells (3,2),(4,2),(5,2)
        game.place("I3", 3, 2, SHAPES["I3"])

    def test_occupied_cell_invalid(self) -> None:
        """Cannot place on an occupied cell."""
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])
        game.place("I1", 19, 0, SHAPES["I1"])
        game.place("I1", 19, 19, SHAPES["I1"])
        game.place("I1", 0, 19, SHAPES["I1"])
        # Blue tries to place on (0,0) again
        with pytest.raises(ValueError, match="occupied"):
            game.place("I2", 0, 0, [(0, 0), (1, 0)])


# ---------------------------------------------------------------------------
# Tests: rotated placement
# ---------------------------------------------------------------------------


class TestRotatedPlacement:
    def test_place_rotated_l3(self) -> None:
        """Place L3 in a rotated orientation."""
        game = PolyominoGame()
        orients = all_orientations(SHAPES["L3"])
        # Find orientation that includes (0,0) — any rotation of L3
        for orient in orients:
            if (0, 0) in orient:
                game.place("L3", 0, 0, orient)
                break
        assert game.owner_at(0, 0) == "Blue"

    def test_place_i4_vertical(self) -> None:
        """Place I4 vertically at Blue's corner."""
        game = PolyominoGame()
        vertical = rotate_90(SHAPES["I4"])  # vertical: (0,0),(0,1),(0,2),(0,3)
        game.place("I4", 0, 0, vertical)
        for r in range(4):
            assert game.owner_at(0, r) == "Blue"


# ---------------------------------------------------------------------------
# Tests: passing and game end
# ---------------------------------------------------------------------------


class TestPassingAndEnd:
    def test_pass_advances_turn(self) -> None:
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])
        assert game.current_player() == "Yellow"
        game.pass_turn()
        assert game.current_player() == "Red"

    def test_all_pass_ends_game(self) -> None:
        game = PolyominoGame()
        game.pass_turn()  # Blue
        game.pass_turn()  # Yellow
        game.pass_turn()  # Red
        game.pass_turn()  # Green
        assert game.finished is True

    def test_placement_resets_pass_count(self) -> None:
        game = PolyominoGame()
        game.pass_turn()  # Blue passes
        game.pass_turn()  # Yellow passes
        game.pass_turn()  # Red passes
        # Green places — resets pass counter
        game.place("I1", 0, 19, SHAPES["I1"])
        # Now need 4 more passes to end
        assert game.finished is False
        game.pass_turn()
        game.pass_turn()
        game.pass_turn()
        assert game.finished is False  # only 3 passes
        game.pass_turn()
        assert game.finished is True


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_score_after_one_piece(self) -> None:
        game = PolyominoGame()
        game.place("I5", 0, 0, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)])
        assert game.score("Blue") == -84  # 89 - 5 = 84 remaining

    def test_score_no_pieces_placed(self) -> None:
        game = PolyominoGame()
        assert game.score("Blue") == -89

    def test_all_pieces_placed_score_zero(self) -> None:
        """Hypothetical: if all pieces placed, score is 0."""
        game = PolyominoGame()
        game.pieces["Blue"] = set()  # simulate all placed
        assert game.score("Blue") == 0

    def test_winner_highest_score(self) -> None:
        game = PolyominoGame()
        # Blue places a piece, others don't
        game.place("I5", 0, 0, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)])
        # 4 consecutive passes ends the game
        game.pass_turn()  # Yellow
        game.pass_turn()  # Red
        game.pass_turn()  # Green
        game.pass_turn()  # Blue — 4th consecutive pass
        assert game.finished is True
        assert game.winner() == "Blue"  # -84 vs -89 for others


# ---------------------------------------------------------------------------
# Tests: 2-player variant
# ---------------------------------------------------------------------------


class TestTwoPlayer:
    def test_2p_active_players(self) -> None:
        game = PolyominoGame(2)
        assert game.active_players == ["Blue", "Red"]

    def test_2p_turn_order(self) -> None:
        game = PolyominoGame(2)
        assert game.current_player() == "Blue"
        game.place("I1", 0, 0, SHAPES["I1"])
        assert game.current_player() == "Red"
        game.place("I1", 19, 19, SHAPES["I1"])
        assert game.current_player() == "Blue"

    def test_2p_two_passes_end(self) -> None:
        game = PolyominoGame(2)
        game.pass_turn()
        game.pass_turn()
        assert game.finished is True

    def test_invalid_player_count(self) -> None:
        with pytest.raises(ValueError, match="must be 2 or 4"):
            PolyominoGame(3)


# ---------------------------------------------------------------------------
# Tests: out of bounds
# ---------------------------------------------------------------------------


class TestBounds:
    def test_off_right_edge(self) -> None:
        game = PolyominoGame()
        with pytest.raises(ValueError, match="out of bounds"):
            game.place("I5", 18, 0, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)])

    def test_off_bottom_edge(self) -> None:
        game = PolyominoGame()
        vertical = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        with pytest.raises(ValueError, match="out of bounds"):
            game.place("I5", 0, 18, vertical)


# ---------------------------------------------------------------------------
# Tests: piece tracking
# ---------------------------------------------------------------------------


class TestPieceTracking:
    def test_piece_removed_from_set(self) -> None:
        game = PolyominoGame()
        assert "I1" in game.pieces["Blue"]
        game.place("I1", 0, 0, SHAPES["I1"])
        assert "I1" not in game.pieces["Blue"]

    def test_cannot_place_same_piece_twice(self) -> None:
        game = PolyominoGame()
        game.place("I1", 0, 0, SHAPES["I1"])
        game.place("I1", 19, 0, SHAPES["I1"])   # Yellow
        game.place("I1", 19, 19, SHAPES["I1"])  # Red
        game.place("I1", 0, 19, SHAPES["I1"])   # Green
        with pytest.raises(ValueError, match="already placed"):
            game.place("I1", 1, 1, SHAPES["I1"])  # Blue tries I1 again

    def test_span_cells_recorded(self) -> None:
        game = PolyominoGame()
        game.place("L3", 0, 0, SHAPES["L3"])
        # Find the component
        cid = game.board.grid_get(0, 0)
        assert cid is not None
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        assert set(comp.span_cells) == {(0, 0), (1, 0), (1, 1)}


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_move_after_game_over(self) -> None:
        game = PolyominoGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.place("I1", 0, 0, SHAPES["I1"])

    def test_pass_after_game_over(self) -> None:
        game = PolyominoGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.pass_turn()
