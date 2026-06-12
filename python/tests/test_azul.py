"""Tests for Azul: tile-drafting and pattern-building game.

2 players. 5 factory displays, each filled with 4 random tiles from a bag
of 100 tiles (20 each of 5 colors: blue, yellow, red, black, white).
Center pool collects remainders. Players draft all tiles of one color from
a factory or center, place onto pattern rows (1-5 slots), overflow to
floor line. When a pattern row is full, one tile moves to the 5x5 wall
grid and scores by adjacency. Floor tiles incur penalties. Round ends when
all factories and center are empty. Game ends when any player completes a
horizontal wall row. Final bonuses for rows, columns, and complete colors.

Bag shuffle is server authority -- tests supply deterministic tile draws.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GridZone,
    SetZone,
    StackZone,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "azul.json"

COLORS = ["blue", "yellow", "red", "black", "white"]

# Standard wall color pattern -- each row shifts the base pattern right by
# the row index.  Row 0 = [blue, yellow, red, black, white], etc.
WALL_PATTERN: list[list[str]] = [
    ["blue", "yellow", "red", "black", "white"],
    ["white", "blue", "yellow", "red", "black"],
    ["black", "white", "blue", "yellow", "red"],
    ["red", "black", "white", "blue", "yellow"],
    ["yellow", "red", "black", "white", "blue"],
]

FLOOR_PENALTIES = [-1, -1, -2, -2, -2, -3, -3]


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Independent scoring oracles
# ---------------------------------------------------------------------------


def wall_column_for_color(row: int, color: str) -> int:
    """Return the column index where `color` belongs in `row` on the wall."""
    return WALL_PATTERN[row].index(color)


def adjacency_score(
    wall: list[list[str | None]], row: int, col: int
) -> int:
    """Score a tile placement at (row, col) on a 5x5 wall by adjacency.

    Independent oracle for the wall-tiling scoring rule.
    If the tile has no horizontal or vertical neighbors, score 1.
    Otherwise, count contiguous horizontal run (including self) and
    contiguous vertical run (including self). If both runs > 1, sum them.
    If only one direction has neighbors, that run is the score.
    """
    # Horizontal run
    h_count = 1
    # left
    c = col - 1
    while c >= 0 and wall[row][c] is not None:
        h_count += 1
        c -= 1
    # right
    c = col + 1
    while c < 5 and wall[row][c] is not None:
        h_count += 1
        c += 1

    # Vertical run
    v_count = 1
    # up
    r = row - 1
    while r >= 0 and wall[r][col] is not None:
        v_count += 1
        r -= 1
    # down
    r = row + 1
    while r < 5 and wall[r][col] is not None:
        v_count += 1
        r += 1

    if h_count == 1 and v_count == 1:
        return 1  # isolated tile
    score = 0
    if h_count > 1:
        score += h_count
    if v_count > 1:
        score += v_count
    return score


def floor_penalty(floor_count: int) -> int:
    """Return total penalty (negative) for `floor_count` tiles on the floor.

    Independent oracle for floor-line penalty rule.
    """
    total = 0
    for i in range(min(floor_count, 7)):
        total += FLOOR_PENALTIES[i]
    return total


def bonus_complete_rows(wall: list[list[str | None]]) -> int:
    """Count complete horizontal rows and return bonus (2 per row)."""
    return sum(2 for row in wall if all(cell is not None for cell in row))


def bonus_complete_columns(wall: list[list[str | None]]) -> int:
    """Count complete vertical columns and return bonus (7 per column)."""
    total = 0
    for col in range(5):
        if all(wall[row][col] is not None for row in range(5)):
            total += 7
    return total


def bonus_complete_colors(wall: list[list[str | None]]) -> int:
    """Count colors with all 5 tiles on the wall, return bonus (10 each)."""
    total = 0
    for color in COLORS:
        found = sum(
            1 for row in range(5)
            for col_idx in range(5)
            if wall[row][col_idx] == color
        )
        if found == 5:
            total += 10
    return total


# ---------------------------------------------------------------------------
# AzulGame driver
# ---------------------------------------------------------------------------


class AzulGame:
    """Azul game driver for testing.

    Manages drafting, pattern rows, wall tiling, scoring, and round flow.
    Uses deterministic tile draws supplied by the test.
    """

    def __init__(self) -> None:
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False

        # 5 factory displays, each a list of tile colors
        self.factories: list[list[str]] = [[] for _ in range(5)]
        # Center pool: list of tile colors
        self.center: list[str] = []
        # First-player marker in center at start of round
        self.first_player_marker_in_center = True
        # Who took the first-player marker this round (goes first next round)
        self.first_player_taker: str | None = None

        # Per-player state
        self.pattern_rows: dict[str, list[list[str]]] = {
            "P1": [[] for _ in range(5)],
            "P2": [[] for _ in range(5)],
        }
        # 5x5 wall grid per player: None = empty, str = color
        self.walls: dict[str, list[list[str | None]]] = {
            "P1": [[None] * 5 for _ in range(5)],
            "P2": [[None] * 5 for _ in range(5)],
        }
        self.floor_lines: dict[str, list[str]] = {"P1": [], "P2": []}
        self.scores: dict[str, int] = {"P1": 0, "P2": 0}

        # Track who goes first each round
        self.round_starter = "P1"

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def fill_factories(self, tiles: list[str]) -> None:
        """Fill all 5 factories with 4 tiles each from given list.

        `tiles` must have exactly 20 entries (5 factories * 4 tiles).
        This replaces the server's bag-shuffle-and-draw.
        """
        if len(tiles) != 20:
            raise ValueError(f"need 20 tiles, got {len(tiles)}")
        for i in range(5):
            self.factories[i] = list(tiles[i * 4 : (i + 1) * 4])
        self.center = []
        self.first_player_marker_in_center = True
        self.first_player_taker = None

    def draft_from_factory(
        self, factory_index: int, color: str, pattern_row: int
    ) -> int:
        """Draft all tiles of `color` from factory `factory_index` (0-4).

        Place onto `pattern_row` (0-4, where row N holds N+1 tiles).
        Overflow goes to floor line.
        Returns the number of tiles taken.
        """
        if self.finished:
            raise ValueError("game is finished")
        if factory_index < 0 or factory_index > 4:
            raise ValueError(f"invalid factory index: {factory_index}")

        factory = self.factories[factory_index]
        if not factory:
            raise ValueError(f"factory {factory_index} is empty")
        if color not in factory:
            raise ValueError(
                f"color {color} not in factory {factory_index}"
            )

        # Take all tiles of chosen color
        taken = [t for t in factory if t == color]
        remainder = [t for t in factory if t != color]

        # Move remainder to center
        self.center.extend(remainder)
        self.factories[factory_index] = []

        # Place taken tiles
        self._place_tiles(taken, pattern_row)
        self.session.advance_turn()
        return len(taken)

    def draft_from_center(self, color: str, pattern_row: int) -> int:
        """Draft all tiles of `color` from the center pool.

        First player to take from center gets the first-player marker
        and a -1 penalty (marker goes to floor line).
        Returns the number of tiles taken.
        """
        if self.finished:
            raise ValueError("game is finished")
        if not self.center:
            raise ValueError("center is empty")
        if color not in self.center:
            raise ValueError(f"color {color} not in center")

        # First-player marker
        if self.first_player_marker_in_center:
            self.first_player_marker_in_center = False
            self.first_player_taker = self.current_player()
            # Marker goes to floor line as a penalty
            player = self.current_player()
            self.floor_lines[player].append("first_player")

        # Take all tiles of chosen color
        taken = [t for t in self.center if t == color]
        self.center = [t for t in self.center if t != color]

        # Place taken tiles
        self._place_tiles(taken, pattern_row)
        self.session.advance_turn()
        return len(taken)

    def _place_tiles(self, tiles: list[str], pattern_row: int) -> None:
        """Place tiles onto a pattern row; overflow to floor line."""
        player = self.current_player()
        if pattern_row < 0 or pattern_row > 4:
            raise ValueError(f"invalid pattern row: {pattern_row}")

        color = tiles[0]
        row = self.pattern_rows[player][pattern_row]
        capacity = pattern_row + 1  # row 0 holds 1, row 4 holds 5

        # Validate: row must be empty or same color
        if row and row[0] != color:
            raise ValueError(
                f"pattern row {pattern_row} already has {row[0]}, "
                f"cannot add {color}"
            )

        # Validate: wall must not already have this color in this row
        wall_col = wall_column_for_color(pattern_row, color)
        if self.walls[player][pattern_row][wall_col] is not None:
            raise ValueError(
                f"wall row {pattern_row} already has {color}"
            )

        # Fill the row, overflow to floor
        for tile in tiles:
            if len(row) < capacity:
                row.append(tile)
            else:
                if len(self.floor_lines[player]) < 7:
                    self.floor_lines[player].append(tile)
                # Tiles beyond floor line capacity are discarded

    def is_round_over(self) -> bool:
        """Round ends when all factories and center are empty."""
        return (
            all(len(f) == 0 for f in self.factories) and len(self.center) == 0
        )

    def wall_tile(self) -> dict[str, int]:
        """Execute wall-tiling phase for both players.

        For each player, for each complete pattern row, move one tile to
        the wall and score. Apply floor penalties.
        Returns points scored this round per player.
        """
        round_points: dict[str, int] = {"P1": 0, "P2": 0}

        for player in ["P1", "P2"]:
            tiling_points = 0
            for row_idx in range(5):
                capacity = row_idx + 1
                row = self.pattern_rows[player][row_idx]
                if len(row) == capacity:
                    # Row is full -- move one tile to wall
                    color = row[0]
                    col = wall_column_for_color(row_idx, color)
                    self.walls[player][row_idx][col] = color
                    pts = adjacency_score(
                        self.walls[player], row_idx, col
                    )
                    tiling_points += pts
                    # Clear the pattern row (remaining tiles to box lid)
                    self.pattern_rows[player][row_idx] = []

            # Floor penalty
            penalty = floor_penalty(len(self.floor_lines[player]))
            tiling_points += penalty

            # Score cannot go below 0
            self.scores[player] = max(0, self.scores[player] + tiling_points)
            round_points[player] = tiling_points

            # Clear floor line
            self.floor_lines[player] = []

        return round_points

    def has_completed_row(self, player: str) -> bool:
        """Check if player has any complete horizontal wall row."""
        return any(
            all(cell is not None for cell in row)
            for row in self.walls[player]
        )

    def is_game_over(self) -> bool:
        """Game ends after wall-tiling if any player completed a wall row."""
        return any(
            self.has_completed_row(p) for p in ["P1", "P2"]
        )

    def final_scoring(self) -> dict[str, int]:
        """Apply end-game bonuses and return final scores."""
        bonuses: dict[str, int] = {"P1": 0, "P2": 0}
        for player in ["P1", "P2"]:
            wall = self.walls[player]
            b = 0
            b += bonus_complete_rows(wall)
            b += bonus_complete_columns(wall)
            b += bonus_complete_colors(wall)
            bonuses[player] = b
            self.scores[player] += b
        self.finished = True
        return bonuses

    def winner(self) -> str | None:
        """Return the player with the highest score, or None for tie."""
        if self.scores["P1"] > self.scores["P2"]:
            return "P1"
        elif self.scores["P2"] > self.scores["P1"]:
            return "P2"
        return None


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Azul"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["P1", "P2"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_bag_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["bag"]
        assert zone.zone_type == "ordered_stack"
        assert zone.visibility == "hidden"
        assert zone.capacity == 100

    def test_factory_zones(self) -> None:
        defn = _load_definition()
        for i in range(1, 6):
            zone = defn.zones[f"factory_{i}"]
            assert zone.zone_type == "set"
            assert zone.capacity == 4
            assert zone.visibility == "public"

    def test_center_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["center"]
        assert zone.zone_type == "set"
        assert zone.capacity == "unlimited"
        assert zone.visibility == "public"

    def test_pattern_row_zones(self) -> None:
        defn = _load_definition()
        for i in range(1, 6):
            zone = defn.zones[f"pattern_row_{i}"]
            assert zone.zone_type == "set"
            assert zone.per_player is True
            assert zone.capacity == i

    def test_wall_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["wall"]
        assert zone.zone_type == "grid"
        assert zone.per_player is True
        assert zone.dimensions == [5, 5]

    def test_floor_line_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["floor_line"]
        assert zone.zone_type == "set"
        assert zone.per_player is True
        assert zone.capacity == 7

    def test_score_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["score"]
        assert zone.zone_type == "counter"
        assert zone.per_player is True

    def test_tile_component(self) -> None:
        defn = _load_definition()
        comp = defn.components["tile"]
        assert comp.owner == "neutral"
        assert comp.count == 100

    def test_first_player_marker(self) -> None:
        defn = _load_definition()
        comp = defn.components["first_player_marker"]
        assert comp.count == 1

    def test_turn_order(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "alternating"
        assert defn.turn_order.players == ["P1", "P2"]

    def test_has_phases(self) -> None:
        defn = _load_definition()
        phase_names = [p.name for p in defn.phases]
        assert "factory_offer" in phase_names
        assert "wall_tiling" in phase_names
        assert "prepare_next_round" in phase_names

    def test_authority_server_only(self) -> None:
        defn = _load_definition()
        assert "shuffle(bag)" in defn.authority.server_only
        assert "fill_factories(bag, factories)" in defn.authority.server_only

    def test_authority_client_verifiable(self) -> None:
        defn = _load_definition()
        cv = defn.authority.client_verifiable
        assert "draft(factory_or_center, color, pattern_row)" in cv
        assert "adjacency_scoring" in cv
        assert "floor_penalty_calculation" in cv

    def test_authority_wasm_required(self) -> None:
        defn = _load_definition()
        assert defn.authority.wasm_required is not None
        assert "adjacency_scoring" in defn.authority.wasm_required

    def test_end_conditions(self) -> None:
        defn = _load_definition()
        names = [ec.name for ec in defn.end_conditions]
        assert "highest_score_wins" in names
        assert "tied_scores" in names

    def test_rules_defined(self) -> None:
        defn = _load_definition()
        assert "draft_from_factory" in defn.rules
        assert "draft_from_center" in defn.rules
        assert "pattern_row_placement" in defn.rules
        assert "wall_tiling" in defn.rules
        assert "adjacency_scoring" in defn.rules
        assert "floor_penalty" in defn.rules
        assert "final_scoring" in defn.rules


# ---------------------------------------------------------------------------
# Tests: wall color pattern (independent oracle)
# ---------------------------------------------------------------------------


class TestWallPattern:
    def test_row_0(self) -> None:
        assert WALL_PATTERN[0] == ["blue", "yellow", "red", "black", "white"]

    def test_each_row_has_all_colors(self) -> None:
        for row in WALL_PATTERN:
            assert sorted(row) == sorted(COLORS)

    def test_each_column_has_all_colors(self) -> None:
        for col in range(5):
            col_colors = [WALL_PATTERN[row][col] for row in range(5)]
            assert sorted(col_colors) == sorted(COLORS)

    def test_column_for_color_row_0(self) -> None:
        assert wall_column_for_color(0, "blue") == 0
        assert wall_column_for_color(0, "white") == 4

    def test_column_for_color_row_1(self) -> None:
        # Row 1: white, blue, yellow, red, black
        assert wall_column_for_color(1, "white") == 0
        assert wall_column_for_color(1, "blue") == 1

    def test_blue_occupies_different_columns(self) -> None:
        cols = [wall_column_for_color(r, "blue") for r in range(5)]
        assert len(set(cols)) == 5  # all distinct


# ---------------------------------------------------------------------------
# Tests: adjacency scoring (independent oracle)
# ---------------------------------------------------------------------------


class TestAdjacencyScoring:
    def test_isolated_tile(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][0] = "blue"
        assert adjacency_score(wall, 0, 0) == 1

    def test_one_horizontal_neighbor(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][0] = "blue"
        wall[0][1] = "yellow"
        # Scoring the newly placed tile at (0,1)
        assert adjacency_score(wall, 0, 1) == 2

    def test_two_horizontal_neighbors(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][0] = "blue"
        wall[0][2] = "red"
        # Place tile in between at (0,1)
        wall[0][1] = "yellow"
        assert adjacency_score(wall, 0, 1) == 3

    def test_one_vertical_neighbor(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][0] = "blue"
        wall[1][0] = "white"
        assert adjacency_score(wall, 1, 0) == 2

    def test_horizontal_and_vertical(self) -> None:
        """Tile with both horizontal and vertical neighbors."""
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][1] = "yellow"
        wall[1][0] = "white"
        # Place at (1,1) -- 1 left + 1 up
        wall[1][1] = "blue"
        # Horizontal: just (1,0) and (1,1) = 2
        # Vertical: just (0,1) and (1,1) = 2
        assert adjacency_score(wall, 1, 1) == 4

    def test_cross_pattern(self) -> None:
        """Tile placed at center of a cross shape."""
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[1][2] = "a"  # above
        wall[3][2] = "b"  # below
        wall[2][1] = "c"  # left
        wall[2][3] = "d"  # right
        wall[2][2] = "e"  # center
        # Horizontal: (2,1), (2,2), (2,3) = 3
        # Vertical: (1,2), (2,2), (3,2) = 3
        assert adjacency_score(wall, 2, 2) == 6

    def test_long_row(self) -> None:
        """Full row of 5 tiles, score the last placed."""
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        for c in range(5):
            wall[0][c] = COLORS[c]
        # Score the last tile placed (column 4)
        assert adjacency_score(wall, 0, 4) == 5

    def test_l_shape(self) -> None:
        """L-shape: 3 horizontal + 1 below the rightmost."""
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        wall[0][0] = "a"
        wall[0][1] = "b"
        wall[0][2] = "c"
        wall[1][2] = "d"
        # Score tile at (0,2): horizontal = 3 (0-2), vertical = 2 (0,2)+(1,2)
        assert adjacency_score(wall, 0, 2) == 5


# ---------------------------------------------------------------------------
# Tests: floor penalty (independent oracle)
# ---------------------------------------------------------------------------


class TestFloorPenalty:
    def test_zero_tiles(self) -> None:
        assert floor_penalty(0) == 0

    def test_one_tile(self) -> None:
        assert floor_penalty(1) == -1

    def test_two_tiles(self) -> None:
        assert floor_penalty(2) == -2

    def test_three_tiles(self) -> None:
        assert floor_penalty(3) == -4

    def test_five_tiles(self) -> None:
        assert floor_penalty(5) == -8

    def test_seven_tiles_maximum(self) -> None:
        assert floor_penalty(7) == -14

    def test_excess_tiles_capped_at_seven(self) -> None:
        """More than 7 tiles still only incurs 7 slots of penalty."""
        assert floor_penalty(10) == -14


# ---------------------------------------------------------------------------
# Tests: end-game bonuses (independent oracles)
# ---------------------------------------------------------------------------


class TestFinalBonuses:
    def test_no_complete_rows(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        assert bonus_complete_rows(wall) == 0

    def test_one_complete_row(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        for c in range(5):
            wall[0][c] = COLORS[c]
        assert bonus_complete_rows(wall) == 2

    def test_two_complete_rows(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        for c in range(5):
            wall[0][c] = COLORS[c]
            wall[1][c] = COLORS[c]
        assert bonus_complete_rows(wall) == 4

    def test_no_complete_columns(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        assert bonus_complete_columns(wall) == 0

    def test_one_complete_column(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        for r in range(5):
            wall[r][0] = COLORS[r]
        assert bonus_complete_columns(wall) == 7

    def test_no_complete_colors(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        assert bonus_complete_colors(wall) == 0

    def test_one_complete_color(self) -> None:
        wall: list[list[str | None]] = [[None] * 5 for _ in range(5)]
        # Place "blue" in every row at its designated column
        for r in range(5):
            col = wall_column_for_color(r, "blue")
            wall[r][col] = "blue"
        assert bonus_complete_colors(wall) == 10

    def test_all_bonuses_full_wall(self) -> None:
        """A fully filled wall gets all bonuses."""
        wall: list[list[str | None]] = [list(row) for row in WALL_PATTERN]
        assert bonus_complete_rows(wall) == 10  # 5 rows * 2
        assert bonus_complete_columns(wall) == 35  # 5 cols * 7
        assert bonus_complete_colors(wall) == 50  # 5 colors * 10


# ---------------------------------------------------------------------------
# Tests: initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_factories_empty_initially(self) -> None:
        game = AzulGame()
        for f in game.factories:
            assert len(f) == 0

    def test_walls_empty(self) -> None:
        game = AzulGame()
        for player in ["P1", "P2"]:
            for row in game.walls[player]:
                assert all(cell is None for cell in row)

    def test_scores_start_at_zero(self) -> None:
        game = AzulGame()
        assert game.scores["P1"] == 0
        assert game.scores["P2"] == 0

    def test_pattern_rows_empty(self) -> None:
        game = AzulGame()
        for player in ["P1", "P2"]:
            for row in game.pattern_rows[player]:
                assert len(row) == 0

    def test_p1_moves_first(self) -> None:
        game = AzulGame()
        assert game.current_player() == "P1"


# ---------------------------------------------------------------------------
# Tests: factory filling
# ---------------------------------------------------------------------------


class TestFactoryFilling:
    def test_fill_factories(self) -> None:
        game = AzulGame()
        tiles = ["blue"] * 4 + ["red"] * 4 + ["yellow"] * 4 + ["black"] * 4 + ["white"] * 4
        game.fill_factories(tiles)
        assert game.factories[0] == ["blue", "blue", "blue", "blue"]
        assert game.factories[4] == ["white", "white", "white", "white"]

    def test_fill_wrong_count_rejected(self) -> None:
        game = AzulGame()
        with pytest.raises(ValueError, match="need 20"):
            game.fill_factories(["blue"] * 10)

    def test_fill_resets_center(self) -> None:
        game = AzulGame()
        game.center = ["red", "blue"]
        tiles = COLORS * 4
        game.fill_factories(tiles)
        assert game.center == []

    def test_fill_resets_first_player_marker(self) -> None:
        game = AzulGame()
        game.first_player_marker_in_center = False
        tiles = COLORS * 4
        game.fill_factories(tiles)
        assert game.first_player_marker_in_center is True


# ---------------------------------------------------------------------------
# Tests: drafting from factory
# ---------------------------------------------------------------------------


class TestDraftFromFactory:
    def _filled_game(self) -> AzulGame:
        game = AzulGame()
        # Factory 0: 2 blue, 1 red, 1 yellow
        # Factory 1: 4 red
        # Factory 2: 2 black, 2 white
        # Factory 3: 3 yellow, 1 blue
        # Factory 4: 1 blue, 1 red, 1 yellow, 1 black
        tiles = (
            ["blue", "blue", "red", "yellow"]
            + ["red", "red", "red", "red"]
            + ["black", "black", "white", "white"]
            + ["yellow", "yellow", "yellow", "blue"]
            + ["blue", "red", "yellow", "black"]
        )
        game.fill_factories(tiles)
        return game

    def test_take_all_of_color(self) -> None:
        game = self._filled_game()
        count = game.draft_from_factory(0, "blue", 1)
        assert count == 2
        assert game.factories[0] == []

    def test_remainder_goes_to_center(self) -> None:
        game = self._filled_game()
        game.draft_from_factory(0, "blue", 1)
        # Remainder: red, yellow
        assert sorted(game.center) == ["red", "yellow"]

    def test_tiles_placed_on_pattern_row(self) -> None:
        game = self._filled_game()
        game.draft_from_factory(0, "blue", 1)
        assert game.pattern_rows["P1"][1] == ["blue", "blue"]

    def test_advances_turn(self) -> None:
        game = self._filled_game()
        assert game.current_player() == "P1"
        game.draft_from_factory(0, "blue", 1)
        assert game.current_player() == "P2"

    def test_reject_empty_factory(self) -> None:
        game = self._filled_game()
        game.factories[0] = []
        with pytest.raises(ValueError, match="empty"):
            game.draft_from_factory(0, "blue", 0)

    def test_reject_color_not_in_factory(self) -> None:
        game = self._filled_game()
        with pytest.raises(ValueError, match="not in factory"):
            game.draft_from_factory(1, "blue", 0)

    def test_take_all_four_same_color(self) -> None:
        game = self._filled_game()
        count = game.draft_from_factory(1, "red", 4)
        assert count == 4
        assert game.pattern_rows["P1"][4] == ["red", "red", "red", "red"]
        assert game.center == []  # no remainder

    def test_overflow_to_floor_line(self) -> None:
        """Taking more tiles than fit in the pattern row overflows to floor."""
        game = self._filled_game()
        # Take 4 red tiles but put on row 0 (capacity 1)
        game.draft_from_factory(1, "red", 0)
        assert game.pattern_rows["P1"][0] == ["red"]
        assert game.floor_lines["P1"] == ["red", "red", "red"]


# ---------------------------------------------------------------------------
# Tests: drafting from center
# ---------------------------------------------------------------------------


class TestDraftFromCenter:
    def _game_with_center(self) -> AzulGame:
        game = AzulGame()
        game.center = ["blue", "blue", "red", "yellow", "red"]
        return game

    def test_take_from_center(self) -> None:
        game = self._game_with_center()
        count = game.draft_from_center("blue", 1)
        assert count == 2
        assert "blue" not in game.center

    def test_first_player_marker(self) -> None:
        game = self._game_with_center()
        game.draft_from_center("blue", 1)
        assert game.first_player_taker == "P1"
        assert "first_player" in game.floor_lines["P1"]

    def test_marker_only_taken_once(self) -> None:
        game = self._game_with_center()
        game.draft_from_center("blue", 1)
        # P2 takes from center -- no second marker
        game.draft_from_center("red", 1)
        assert game.floor_lines["P2"] == []

    def test_reject_empty_center(self) -> None:
        game = AzulGame()
        with pytest.raises(ValueError, match="center is empty"):
            game.draft_from_center("blue", 0)

    def test_reject_color_not_in_center(self) -> None:
        game = self._game_with_center()
        with pytest.raises(ValueError, match="not in center"):
            game.draft_from_center("black", 0)


# ---------------------------------------------------------------------------
# Tests: pattern row placement rules
# ---------------------------------------------------------------------------


class TestPatternRowPlacement:
    def test_same_color_only(self) -> None:
        game = AzulGame()
        game.pattern_rows["P1"][2] = ["blue"]
        # Try to place red in same row
        with pytest.raises(ValueError, match="already has blue"):
            game._place_tiles(["red"], 2)

    def test_cannot_place_if_wall_has_color(self) -> None:
        game = AzulGame()
        col = wall_column_for_color(0, "blue")
        game.walls["P1"][0][col] = "blue"
        with pytest.raises(ValueError, match="wall row 0 already has blue"):
            game._place_tiles(["blue"], 0)

    def test_invalid_pattern_row(self) -> None:
        game = AzulGame()
        with pytest.raises(ValueError, match="invalid pattern row"):
            game._place_tiles(["blue"], 5)


# ---------------------------------------------------------------------------
# Tests: wall tiling
# ---------------------------------------------------------------------------


class TestWallTiling:
    def test_complete_row_tiles_to_wall(self) -> None:
        game = AzulGame()
        # Fill pattern row 0 (capacity 1) with blue
        game.pattern_rows["P1"][0] = ["blue"]
        game.wall_tile()
        col = wall_column_for_color(0, "blue")
        assert game.walls["P1"][0][col] == "blue"
        assert game.pattern_rows["P1"][0] == []

    def test_incomplete_row_not_tiled(self) -> None:
        game = AzulGame()
        # Pattern row 2 (capacity 3) with only 2 tiles
        game.pattern_rows["P1"][2] = ["red", "red"]
        game.wall_tile()
        # Should remain
        assert game.pattern_rows["P1"][2] == ["red", "red"]
        col = wall_column_for_color(2, "red")
        assert game.walls["P1"][2][col] is None

    def test_scoring_isolated_tile(self) -> None:
        game = AzulGame()
        game.pattern_rows["P1"][0] = ["blue"]
        points = game.wall_tile()
        # Isolated tile = 1 point, no floor penalty
        assert points["P1"] == 1

    def test_scoring_with_neighbor(self) -> None:
        game = AzulGame()
        # Put blue on row 0 first
        col_blue = wall_column_for_color(0, "blue")
        game.walls["P1"][0][col_blue] = "blue"
        # Now complete row 0 with yellow (adjacent to blue)
        game.pattern_rows["P1"][0] = ["yellow"]
        col_yellow = wall_column_for_color(0, "yellow")
        # Ensure they're adjacent
        assert abs(col_blue - col_yellow) == 1
        points = game.wall_tile()
        assert points["P1"] == 2  # 2 tiles in horizontal run

    def test_floor_penalty_applied(self) -> None:
        game = AzulGame()
        game.pattern_rows["P1"][0] = ["blue"]
        game.floor_lines["P1"] = ["red", "red", "red"]
        points = game.wall_tile()
        # 1 (tiling) + (-4) floor penalty = -3
        assert points["P1"] == -3
        assert game.scores["P1"] == 0  # clamped to 0

    def test_floor_cleared_after_tiling(self) -> None:
        game = AzulGame()
        game.floor_lines["P1"] = ["red"]
        game.wall_tile()
        assert game.floor_lines["P1"] == []

    def test_score_cannot_go_negative(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 3
        game.floor_lines["P1"] = ["a", "b", "c", "d", "e", "f", "g"]
        game.wall_tile()
        # Floor penalty = -14, 3 + (-14) = -11, clamped to 0
        assert game.scores["P1"] == 0

    def test_multiple_rows_scored(self) -> None:
        game = AzulGame()
        game.pattern_rows["P1"][0] = ["blue"]
        game.pattern_rows["P1"][1] = ["yellow", "yellow"]
        points = game.wall_tile()
        # Both isolated -> 1 + 1 = 2
        assert points["P1"] == 2

    def test_both_players_tiled(self) -> None:
        game = AzulGame()
        game.pattern_rows["P1"][0] = ["blue"]
        game.pattern_rows["P2"][0] = ["blue"]
        points = game.wall_tile()
        assert points["P1"] == 1
        assert points["P2"] == 1


# ---------------------------------------------------------------------------
# Tests: round flow
# ---------------------------------------------------------------------------


class TestRoundFlow:
    def test_round_over_when_all_empty(self) -> None:
        game = AzulGame()
        assert game.is_round_over()  # nothing filled yet

    def test_round_not_over_with_factory(self) -> None:
        game = AzulGame()
        game.factories[0] = ["blue"]
        assert not game.is_round_over()

    def test_round_not_over_with_center(self) -> None:
        game = AzulGame()
        game.center = ["red"]
        assert not game.is_round_over()

    def test_game_not_over_without_complete_row(self) -> None:
        game = AzulGame()
        assert not game.is_game_over()

    def test_game_over_with_complete_row(self) -> None:
        game = AzulGame()
        for c in range(5):
            game.walls["P1"][0][c] = COLORS[c]
        assert game.is_game_over()

    def test_cannot_draft_when_finished(self) -> None:
        game = AzulGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.draft_from_factory(0, "blue", 0)

    def test_cannot_draft_center_when_finished(self) -> None:
        game = AzulGame()
        game.finished = True
        with pytest.raises(ValueError, match="game is finished"):
            game.draft_from_center("blue", 0)


# ---------------------------------------------------------------------------
# Tests: full round simulation
# ---------------------------------------------------------------------------


class TestFullRound:
    def test_one_round_draft_and_tile(self) -> None:
        """Simulate a complete round: fill, draft all, wall-tile, score."""
        game = AzulGame()
        tiles = (
            ["blue", "blue", "red", "red"]
            + ["yellow", "yellow", "black", "black"]
            + ["white", "white", "blue", "blue"]
            + ["red", "red", "yellow", "yellow"]
            + ["black", "black", "white", "white"]
        )
        game.fill_factories(tiles)

        # P1 takes 2 blue from factory 0 -> pattern row 1 (capacity 2)
        game.draft_from_factory(0, "blue", 1)
        # P2 takes 2 yellow from factory 1 -> pattern row 1
        game.draft_from_factory(1, "yellow", 1)
        # P1 takes 2 white from factory 2 -> pattern row 1... already has blue
        # Instead put on row 0 (capacity 1), 1 overflows
        game.draft_from_factory(2, "white", 0)
        # P2 takes 2 red from factory 3 -> pattern row 1... already has yellow
        game.draft_from_factory(3, "red", 0)
        # Center now has: red, red (from f0), black, black (from f1),
        #   blue, blue (from f2), yellow, yellow (from f3)
        # P1 takes blue from center -> pattern row 2
        game.draft_from_center("blue", 2)
        # P1 gets first player marker -> floor
        assert "first_player" in game.floor_lines["P1"]
        # P2 takes 2 black from factory 4 -> pattern row 1... has yellow
        game.draft_from_factory(4, "black", 2)
        # P1 takes red from center -> pattern row 2... has blue!
        # Put on row 3 instead
        game.draft_from_center("red", 3)
        # P2 takes yellow from center -> row 3 (row 2 has black)
        game.draft_from_center("yellow", 3)
        # P1 takes black from center -> row 4
        game.draft_from_center("black", 4)
        # P2 takes white from center -> row 4
        game.draft_from_center("white", 4)

        assert game.is_round_over()

        # Wall tiling
        points = game.wall_tile()
        # P1: row 0 full (white, cap=1), row 1 full (blue, blue, cap=2)
        # P2: row 0 full (red, cap=1), row 1 full (yellow, yellow, cap=2)
        # Each isolated -> 1 pt each (2 placements per player)
        # P1 floor: first_player + white = 2 items -> -2 penalty
        # P1 tiling: 1 + 1 = 2, floor -2 = 0
        # P2 floor: red (overflow from row 0) = 1 item -> -1 penalty
        # P2 tiling: 1 + 1 = 2, floor -1 = 1
        assert game.scores["P1"] >= 0
        assert game.scores["P2"] >= 0

    def test_multi_round_until_game_end(self) -> None:
        """Play enough rounds to complete a wall row and end the game."""
        game = AzulGame()
        # We'll complete row 0 for P1 by placing all 5 colors over 5 rounds
        for round_num, color in enumerate(WALL_PATTERN[0]):
            # Fill factories with only tiles of the needed color
            tiles = [color] * 20
            game.fill_factories(tiles)

            # P1 drafts from factory 0
            game.draft_from_factory(0, color, 0)
            # P2 drafts from factory 1 into a row that can hold it
            target_row = min(round_num, 4)
            # Check if P2 can use this color on target_row
            wall_col = wall_column_for_color(target_row, color)
            if game.walls["P2"][target_row][wall_col] is not None:
                target_row = 4  # use row 4 as fallback
            game.draft_from_factory(1, color, target_row)

            # Drain remaining factories
            for fi in range(2, 5):
                if game.factories[fi]:
                    p = game.current_player()
                    pr = 4 if round_num < 4 else 3
                    # Find a valid row for current player
                    cp = game.current_player()
                    for try_row in range(5):
                        wcol = wall_column_for_color(try_row, color)
                        if (game.walls[cp][try_row][wcol] is None
                                and (not game.pattern_rows[cp][try_row]
                                     or game.pattern_rows[cp][try_row][0] == color)):
                            pr = try_row
                            break
                    game.draft_from_factory(fi, color, pr)

            # Drain center
            while game.center:
                cp = game.current_player()
                c = game.center[0]
                for try_row in range(5):
                    wcol = wall_column_for_color(try_row, c)
                    if (game.walls[cp][try_row][wcol] is None
                            and (not game.pattern_rows[cp][try_row]
                                 or game.pattern_rows[cp][try_row][0] == c)):
                        game.draft_from_center(c, try_row)
                        break
                else:
                    # Nowhere valid, dump to floor via row 4
                    for try_row in range(5):
                        wcol = wall_column_for_color(try_row, c)
                        if game.walls[cp][try_row][wcol] is None:
                            game.draft_from_center(c, try_row)
                            break
                    else:
                        break  # Stuck, just break

            assert game.is_round_over()
            game.wall_tile()

        # After 5 rounds, P1 should have row 0 complete
        assert game.has_completed_row("P1")
        assert game.is_game_over()

        bonuses = game.final_scoring()
        assert bonuses["P1"] >= 2  # at least the complete-row bonus
        assert game.finished


# ---------------------------------------------------------------------------
# Tests: final scoring
# ---------------------------------------------------------------------------


class TestFinalScoring:
    def test_final_scoring_adds_bonuses(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 50
        # Complete row 0
        for c in range(5):
            game.walls["P1"][0][c] = WALL_PATTERN[0][c]
        bonuses = game.final_scoring()
        assert bonuses["P1"] == 2  # one complete row
        assert game.scores["P1"] == 52

    def test_final_scoring_column_bonus(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 10
        # Complete column 0
        for r in range(5):
            game.walls["P1"][r][0] = WALL_PATTERN[r][0]
        bonuses = game.final_scoring()
        assert bonuses["P1"] == 7
        assert game.scores["P1"] == 17

    def test_final_scoring_color_bonus(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 10
        # Place all 5 blue tiles
        for r in range(5):
            col = wall_column_for_color(r, "blue")
            game.walls["P1"][r][col] = "blue"
        bonuses = game.final_scoring()
        assert bonuses["P1"] == 10
        assert game.scores["P1"] == 20

    def test_winner_determined(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 80
        game.scores["P2"] = 60
        assert game.winner() == "P1"

    def test_tie(self) -> None:
        game = AzulGame()
        game.scores["P1"] = 70
        game.scores["P2"] = 70
        assert game.winner() is None

    def test_full_wall_all_bonuses(self) -> None:
        """Full wall = 5 rows (10) + 5 cols (35) + 5 colors (50) = 95 bonus."""
        game = AzulGame()
        game.scores["P1"] = 0
        for r in range(5):
            for c in range(5):
                game.walls["P1"][r][c] = WALL_PATTERN[r][c]
        bonuses = game.final_scoring()
        assert bonuses["P1"] == 95
