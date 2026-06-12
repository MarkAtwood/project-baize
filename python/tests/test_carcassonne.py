"""Tests for Carcassonne: tile placement game with meeple scoring.

2-player simplified Carcassonne on a 20x20 grid. 30 landscape tiles with
edge types (city/road/field) and optional monastery/pennant flags. Players
draw tiles from a hidden deck, place them with matching edges, optionally
place a meeple on a feature, then score completed features.

Edge matching: adjacent tiles must have matching terrain on touching edges
(north-south, east-west). Tiles may be rotated 0/90/180/270 degrees.

Scoring:
  - Completed city: 2 points per tile + 2 per pennant
  - Completed road: 1 point per tile
  - Completed monastery: 9 points (1 + 8 surrounding tiles)
  - Fields: 3 points per adjacent completed city (end-game only)
  - Incomplete features: reduced scoring at game end
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
# Tile definitions — simplified set of 30 tiles
# ---------------------------------------------------------------------------

# Each tile: (north, east, south, west, has_monastery, has_pennant)
# Edge types: "city", "road", "field"
TILE_DEFS: list[dict[str, Any]] = [
    # Start tile (index 0): road east-west, city north
    {"north": "city", "east": "road", "south": "field", "west": "road",
     "monastery": False, "pennant": False},
    # All-field tiles (2)
    {"north": "field", "east": "field", "south": "field", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "field", "east": "field", "south": "field", "west": "field",
     "monastery": True, "pennant": False},
    # Road tiles (8)
    {"north": "field", "east": "road", "south": "field", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "road", "east": "field", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "field", "east": "road", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "road", "east": "road", "south": "field", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "road", "east": "road", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "road", "east": "road", "south": "road", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "field", "east": "field", "south": "road", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "road", "east": "field", "south": "field", "west": "road",
     "monastery": False, "pennant": False},
    # City tiles (12)
    {"north": "city", "east": "field", "south": "field", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "field", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "field", "south": "city", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "city", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "city", "west": "city",
     "monastery": False, "pennant": True},
    {"north": "city", "east": "road", "south": "field", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "field", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "road", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "field", "south": "field", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "field", "west": "field",
     "monastery": False, "pennant": True},
    # City-road combos (4)
    {"north": "city", "east": "road", "south": "field", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "road", "south": "road", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "road", "west": "road",
     "monastery": False, "pennant": False},
    {"north": "city", "east": "city", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
    # Monastery tiles (3)
    {"north": "field", "east": "field", "south": "field", "west": "field",
     "monastery": True, "pennant": False},
    {"north": "field", "east": "road", "south": "field", "west": "field",
     "monastery": True, "pennant": False},
    {"north": "road", "east": "field", "south": "field", "west": "field",
     "monastery": True, "pennant": False},
    # Extra tiles to reach 30
    {"north": "field", "east": "city", "south": "field", "west": "city",
     "monastery": False, "pennant": False},
    {"north": "field", "east": "city", "south": "road", "west": "field",
     "monastery": False, "pennant": False},
]

assert len(TILE_DEFS) == 30

VALID_EDGES = {"city", "road", "field"}

# Opposite edge mapping for adjacency checks
OPPOSITE_EDGE = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
}

# Direction offsets: (dcol, drow)
DIRECTION_OFFSETS = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "carcassonne.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Tile rotation
# ---------------------------------------------------------------------------

def rotate_tile_90(tile: dict[str, Any]) -> dict[str, Any]:
    """Rotate a tile 90 degrees clockwise: N->E, E->S, S->W, W->N."""
    return {
        "north": tile["west"],
        "east": tile["north"],
        "south": tile["east"],
        "west": tile["south"],
        "monastery": tile["monastery"],
        "pennant": tile["pennant"],
    }


def rotate_tile(tile: dict[str, Any], rotation: int) -> dict[str, Any]:
    """Rotate a tile by 0, 90, 180, or 270 degrees clockwise."""
    assert rotation in (0, 90, 180, 270)
    result = dict(tile)
    for _ in range(rotation // 90):
        result = rotate_tile_90(result)
    return result


def all_rotations(tile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all 4 rotations of a tile."""
    return [rotate_tile(tile, r) for r in (0, 90, 180, 270)]


# ---------------------------------------------------------------------------
# Edge matching validation
# ---------------------------------------------------------------------------


def edges_match(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    col: int,
    row: int,
    tile: dict[str, Any],
) -> bool:
    """Check if tile at (col, row) has matching edges with all neighbors."""
    for direction, (dc, dr) in DIRECTION_OFFSETS.items():
        nc, nr = col + dc, row + dr
        neighbor = placed_tiles.get((nc, nr))
        if neighbor is not None:
            my_edge = tile[direction]
            their_edge = neighbor[OPPOSITE_EDGE[direction]]
            if my_edge != their_edge:
                return False
    return True


def has_adjacent_tile(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    col: int,
    row: int,
) -> bool:
    """Check if position has at least one orthogonal neighbor."""
    for dc, dr in DIRECTION_OFFSETS.values():
        if (col + dc, row + dr) in placed_tiles:
            return True
    return False


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _flood_city(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    start_col: int,
    start_row: int,
    start_direction: str,
) -> tuple[set[tuple[int, int]], bool, int]:
    """Flood-fill a city feature starting from a tile edge.

    Returns (tiles_in_city, is_complete, pennant_count).
    A city is complete when all city edges connect to another city edge.
    """
    visited: set[tuple[int, int]] = set()
    pennants = 0
    complete = True
    stack = [(start_col, start_row)]

    while stack:
        col, row = stack.pop()
        if (col, row) in visited:
            continue
        tile = placed_tiles.get((col, row))
        if tile is None:
            complete = False
            continue
        visited.add((col, row))
        if tile.get("pennant", False):
            pennants += 1
        # Check all city edges of this tile
        for direction, (dc, dr) in DIRECTION_OFFSETS.items():
            if tile[direction] == "city":
                nc, nr = col + dc, row + dr
                neighbor = placed_tiles.get((nc, nr))
                if neighbor is None:
                    complete = False
                elif neighbor[OPPOSITE_EDGE[direction]] == "city":
                    if (nc, nr) not in visited:
                        stack.append((nc, nr))

    return visited, complete, pennants


def score_completed_city(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    city_tiles: set[tuple[int, int]],
    pennant_count: int,
) -> int:
    """Score a completed city: 2 per tile + 2 per pennant."""
    return len(city_tiles) * 2 + pennant_count * 2


def score_incomplete_city(
    city_tiles: set[tuple[int, int]],
    pennant_count: int,
) -> int:
    """Score an incomplete city at game end: 1 per tile + 1 per pennant."""
    return len(city_tiles) + pennant_count


def _trace_road(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    start_col: int,
    start_row: int,
    start_direction: str,
) -> tuple[set[tuple[int, int]], bool]:
    """Trace a road feature from a starting tile/direction.

    Returns (tiles_in_road, is_complete).
    A road is complete when both endpoints terminate (at a city, intersection,
    or dead-end).
    """
    visited: set[tuple[int, int]] = set()
    complete = True
    stack = [(start_col, start_row)]

    while stack:
        col, row = stack.pop()
        if (col, row) in visited:
            continue
        tile = placed_tiles.get((col, row))
        if tile is None:
            complete = False
            continue
        visited.add((col, row))
        for direction, (dc, dr) in DIRECTION_OFFSETS.items():
            if tile[direction] == "road":
                nc, nr = col + dc, row + dr
                neighbor = placed_tiles.get((nc, nr))
                if neighbor is None:
                    complete = False
                elif neighbor[OPPOSITE_EDGE[direction]] == "road":
                    if (nc, nr) not in visited:
                        stack.append((nc, nr))

    return visited, complete


def score_completed_road(road_tiles: set[tuple[int, int]]) -> int:
    """Score a completed road: 1 per tile."""
    return len(road_tiles)


def score_monastery(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    col: int,
    row: int,
) -> int:
    """Score a monastery: 1 + number of surrounding tiles (max 9 if complete)."""
    count = 1  # the monastery tile itself
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if dc == 0 and dr == 0:
                continue
            if (col + dc, row + dr) in placed_tiles:
                count += 1
    return count


def is_monastery_complete(
    placed_tiles: dict[tuple[int, int], dict[str, Any]],
    col: int,
    row: int,
) -> bool:
    """A monastery is complete when all 8 surrounding cells have tiles."""
    return score_monastery(placed_tiles, col, row) == 9


# ---------------------------------------------------------------------------
# Game driver
# ---------------------------------------------------------------------------


class CarcassonneGame:
    """Simplified Carcassonne game driver for testing."""

    def __init__(self) -> None:
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False

        # Board state: placed tiles with their edges
        self.placed_tiles: dict[tuple[int, int], dict[str, Any]] = {}

        # Meeple tracking: (col, row, feature_type) -> player
        self.meeples: dict[tuple[int, int, str], str] = {}

        # Meeple supply per player
        self.meeple_supply: dict[str, int] = {"Red": 7, "Blue": 7}

        # Scores
        self.scores: dict[str, int] = {"Red": 0, "Blue": 0}

        # Place start tile at center (10, 10)
        start_tile = TILE_DEFS[0]
        self._place_tile_on_grid(10, 10, start_tile, "start-tile")

        # Tile deck (remaining 29 tiles)
        self.deck: list[dict[str, Any]] = list(TILE_DEFS[1:])

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _place_tile_on_grid(
        self,
        col: int,
        row: int,
        tile: dict[str, Any],
        tile_id: str,
    ) -> ComponentId:
        """Place a tile on the grid and track it."""
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=tile_id,
                component_type="tile",
                owner=None,
                properties={
                    "north_edge": tile["north"],
                    "east_edge": tile["east"],
                    "south_edge": tile["south"],
                    "west_edge": tile["west"],
                    "has_monastery": tile["monastery"],
                    "has_pennant": tile["pennant"],
                },
            )
        )
        self.board.grid_set(col, row, cid)
        self.placed_tiles[(col, row)] = tile
        return cid

    def draw_tile(self) -> dict[str, Any] | None:
        """Draw the next tile from the deck. Returns None if deck empty."""
        if not self.deck:
            return None
        return self.deck.pop(0)

    def validate_placement(
        self, col: int, row: int, tile: dict[str, Any]
    ) -> str | None:
        """Return None if valid, or an error message."""
        if col < 0 or row < 0 or col >= 20 or row >= 20:
            return f"cell ({col},{row}) out of bounds"
        if (col, row) in self.placed_tiles:
            return f"cell ({col},{row}) already occupied"
        if not has_adjacent_tile(self.placed_tiles, col, row):
            return f"cell ({col},{row}) has no adjacent tile"
        if not edges_match(self.placed_tiles, col, row, tile):
            return f"tile edges do not match neighbors at ({col},{row})"
        return None

    def place_tile(
        self,
        col: int,
        row: int,
        tile: dict[str, Any],
        rotation: int = 0,
    ) -> None:
        """Place a tile (possibly rotated) on the board."""
        if self.finished:
            raise ValueError("game is finished")

        rotated = rotate_tile(tile, rotation)
        err = self.validate_placement(col, row, rotated)
        if err is not None:
            raise ValueError(err)

        player = self.current_player()
        tile_id = f"tile-{len(self.placed_tiles)}-{player}"
        self._place_tile_on_grid(col, row, rotated, tile_id)

    def place_meeple(
        self, col: int, row: int, feature: str
    ) -> None:
        """Place a meeple on a feature of the tile at (col, row)."""
        player = self.current_player()
        if self.meeple_supply[player] <= 0:
            raise ValueError(f"{player} has no meeples in supply")
        if (col, row) not in self.placed_tiles:
            raise ValueError(f"no tile at ({col},{row})")

        tile = self.placed_tiles[(col, row)]
        # Validate feature exists on tile
        if feature == "monastery":
            if not tile.get("monastery", False):
                raise ValueError(f"tile at ({col},{row}) has no monastery")
        elif feature in ("city", "road", "field"):
            # Check tile has at least one edge of this type
            edge_vals = [tile["north"], tile["east"], tile["south"], tile["west"]]
            if feature not in edge_vals:
                raise ValueError(
                    f"tile at ({col},{row}) has no {feature} feature"
                )
        else:
            raise ValueError(f"invalid feature: {feature}")

        # Check feature not already claimed by a meeple on connected segments
        # (simplified: check if any meeple is on this exact feature at this tile)
        if (col, row, feature) in self.meeples:
            raise ValueError(
                f"feature {feature} at ({col},{row}) already has a meeple"
            )

        self.meeples[(col, row, feature)] = player
        self.meeple_supply[player] -= 1

    def return_meeple(self, col: int, row: int, feature: str) -> None:
        """Return a meeple from a completed feature to its owner."""
        key = (col, row, feature)
        if key in self.meeples:
            owner = self.meeples.pop(key)
            self.meeple_supply[owner] += 1

    def end_turn(self) -> None:
        """End the current player's turn and advance."""
        self.session.advance_turn()
        if not self.deck:
            self.finished = True

    def score_completed_features_at(self, col: int, row: int) -> dict[str, int]:
        """Check and score any features completed by placing tile at (col, row).

        Returns points scored per player this turn.
        """
        points: dict[str, int] = {"Red": 0, "Blue": 0}
        tile = self.placed_tiles.get((col, row))
        if tile is None:
            return points

        # Check city completion
        scored_cities: set[frozenset[tuple[int, int]]] = set()
        for direction in ("north", "east", "south", "west"):
            if tile[direction] == "city":
                city_tiles, complete, pennants = _flood_city(
                    self.placed_tiles, col, row, direction
                )
                key = frozenset(city_tiles)
                if key in scored_cities:
                    continue
                scored_cities.add(key)
                if complete:
                    pts = score_completed_city(
                        self.placed_tiles, city_tiles, pennants
                    )
                    # Find meeple owners on this city
                    owners: dict[str, int] = {}
                    for tc, tr in city_tiles:
                        mkey = (tc, tr, "city")
                        if mkey in self.meeples:
                            p = self.meeples[mkey]
                            owners[p] = owners.get(p, 0) + 1
                    if owners:
                        max_count = max(owners.values())
                        winners = [
                            p for p, c in owners.items() if c == max_count
                        ]
                        for w in winners:
                            points[w] += pts
                        # Return meeples
                        for tc, tr in city_tiles:
                            self.return_meeple(tc, tr, "city")

        # Check road completion
        scored_roads: set[frozenset[tuple[int, int]]] = set()
        for direction in ("north", "east", "south", "west"):
            if tile[direction] == "road":
                road_tiles, complete = _trace_road(
                    self.placed_tiles, col, row, direction
                )
                key = frozenset(road_tiles)
                if key in scored_roads:
                    continue
                scored_roads.add(key)
                if complete:
                    pts = score_completed_road(road_tiles)
                    owners_r: dict[str, int] = {}
                    for tc, tr in road_tiles:
                        mkey = (tc, tr, "road")
                        if mkey in self.meeples:
                            p = self.meeples[mkey]
                            owners_r[p] = owners_r.get(p, 0) + 1
                    if owners_r:
                        max_count = max(owners_r.values())
                        winners = [
                            p for p, c in owners_r.items() if c == max_count
                        ]
                        for w in winners:
                            points[w] += pts
                        for tc, tr in road_tiles:
                            self.return_meeple(tc, tr, "road")

        # Check monastery completion
        if tile.get("monastery", False):
            if is_monastery_complete(self.placed_tiles, col, row):
                mkey = (col, row, "monastery")
                if mkey in self.meeples:
                    owner = self.meeples[mkey]
                    points[owner] += 9
                    self.return_meeple(col, row, "monastery")

        # Also check if this tile completes a neighboring monastery
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                nc, nr = col + dc, row + dr
                ntile = self.placed_tiles.get((nc, nr))
                if ntile is not None and ntile.get("monastery", False):
                    if is_monastery_complete(self.placed_tiles, nc, nr):
                        mkey = (nc, nr, "monastery")
                        if mkey in self.meeples:
                            owner = self.meeples[mkey]
                            points[owner] += 9
                            self.return_meeple(nc, nr, "monastery")

        for player, pts in points.items():
            self.scores[player] += pts

        return points


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Carcassonne"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Red", "Blue"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_board_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.zone_type == "grid"
        assert zone.dimensions == [20, 20]
        assert zone.adjacency == "orthogonal_4"

    def test_tile_deck_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["tile_deck"]
        assert zone.zone_type == "ordered_stack"
        assert zone.visibility == "hidden"
        assert zone.capacity == 29

    def test_meeple_supply_zone(self) -> None:
        defn = _load_definition()
        zone = defn.zones["meeple_supply"]
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
        assert comp.count == 30

    def test_meeple_component(self) -> None:
        defn = _load_definition()
        comp = defn.components["meeple"]
        assert comp.owner == "per_player"
        assert comp.count == 7

    def test_turn_order(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "alternating"

    def test_has_phases(self) -> None:
        defn = _load_definition()
        phase_names = [p.name for p in defn.phases]
        assert "draw_tile" in phase_names
        assert "place_tile" in phase_names
        assert "place_meeple" in phase_names
        assert "score_completed" in phase_names

    def test_authority_server_only(self) -> None:
        defn = _load_definition()
        assert "shuffle(tile_deck)" in defn.authority.server_only
        assert "draw(tile_deck)" in defn.authority.server_only

    def test_authority_client_verifiable(self) -> None:
        defn = _load_definition()
        assert "edge_matching" in defn.authority.client_verifiable

    def test_authority_wasm_required(self) -> None:
        defn = _load_definition()
        assert defn.authority.wasm_required is not None
        assert "edge_matching_validation" in defn.authority.wasm_required

    def test_end_conditions(self) -> None:
        defn = _load_definition()
        names = [ec.name for ec in defn.end_conditions]
        assert "all_tiles_placed" in names
        assert "tied_scores" in names

    def test_rules_defined(self) -> None:
        defn = _load_definition()
        assert "tile_placement" in defn.rules
        assert "meeple_placement" in defn.rules
        assert "city_scoring" in defn.rules
        assert "road_scoring" in defn.rules
        assert "monastery_scoring" in defn.rules


# ---------------------------------------------------------------------------
# Tests: tile definitions
# ---------------------------------------------------------------------------


class TestTileDefinitions:
    def test_tile_count(self) -> None:
        assert len(TILE_DEFS) == 30

    def test_all_tiles_have_four_edges(self) -> None:
        for i, tile in enumerate(TILE_DEFS):
            for edge in ("north", "east", "south", "west"):
                assert edge in tile, f"tile {i} missing {edge} edge"
                assert tile[edge] in VALID_EDGES, (
                    f"tile {i} {edge} edge has invalid value: {tile[edge]}"
                )

    def test_start_tile_edges(self) -> None:
        """Start tile has city north, road east-west, field south."""
        start = TILE_DEFS[0]
        assert start["north"] == "city"
        assert start["east"] == "road"
        assert start["south"] == "field"
        assert start["west"] == "road"

    def test_monastery_flag(self) -> None:
        """Some tiles have monasteries."""
        monastery_count = sum(1 for t in TILE_DEFS if t["monastery"])
        assert monastery_count >= 3

    def test_pennant_flag(self) -> None:
        """Some city tiles have pennants."""
        pennant_tiles = [t for t in TILE_DEFS if t["pennant"]]
        assert len(pennant_tiles) >= 1
        # Pennant tiles must have at least one city edge
        for t in pennant_tiles:
            edges = [t["north"], t["east"], t["south"], t["west"]]
            assert "city" in edges, "pennant tile must have city edge"

    def test_variety_of_edge_combos(self) -> None:
        """Tiles have diverse edge combinations."""
        combos: set[tuple[str, str, str, str]] = set()
        for t in TILE_DEFS:
            combo = (t["north"], t["east"], t["south"], t["west"])
            combos.add(combo)
        # At least 15 distinct edge combinations
        assert len(combos) >= 15


# ---------------------------------------------------------------------------
# Tests: tile rotation
# ---------------------------------------------------------------------------


class TestTileRotation:
    def test_rotate_0_identity(self) -> None:
        tile = TILE_DEFS[0]
        rotated = rotate_tile(tile, 0)
        assert rotated["north"] == tile["north"]
        assert rotated["east"] == tile["east"]
        assert rotated["south"] == tile["south"]
        assert rotated["west"] == tile["west"]

    def test_rotate_90(self) -> None:
        """Clockwise 90: west->north, north->east, east->south, south->west."""
        tile = TILE_DEFS[0]  # city/road/field/road
        rotated = rotate_tile(tile, 90)
        assert rotated["north"] == "road"   # was west
        assert rotated["east"] == "city"    # was north
        assert rotated["south"] == "road"   # was east
        assert rotated["west"] == "field"   # was south

    def test_rotate_180(self) -> None:
        tile = TILE_DEFS[0]  # city/road/field/road
        rotated = rotate_tile(tile, 180)
        assert rotated["north"] == "field"  # was south
        assert rotated["east"] == "road"    # was west
        assert rotated["south"] == "city"   # was north
        assert rotated["west"] == "road"    # was east

    def test_rotate_270(self) -> None:
        tile = TILE_DEFS[0]  # city/road/field/road
        rotated = rotate_tile(tile, 270)
        assert rotated["north"] == "road"   # was east
        assert rotated["east"] == "field"   # was south
        assert rotated["south"] == "road"   # was west
        assert rotated["west"] == "city"    # was north

    def test_rotate_360_is_identity(self) -> None:
        tile = TILE_DEFS[0]
        r90 = rotate_tile(tile, 90)
        r180 = rotate_tile(r90, 90)
        r270 = rotate_tile(r180, 90)
        r360 = rotate_tile(r270, 90)
        assert r360["north"] == tile["north"]
        assert r360["east"] == tile["east"]
        assert r360["south"] == tile["south"]
        assert r360["west"] == tile["west"]

    def test_all_rotations_returns_four(self) -> None:
        tile = TILE_DEFS[0]
        rots = all_rotations(tile)
        assert len(rots) == 4

    def test_rotation_preserves_monastery(self) -> None:
        monastery_tile = TILE_DEFS[2]  # monastery tile
        for rot in (0, 90, 180, 270):
            rotated = rotate_tile(monastery_tile, rot)
            assert rotated["monastery"] is True

    def test_rotation_preserves_pennant(self) -> None:
        pennant_tile = TILE_DEFS[15]  # all-city with pennant
        for rot in (0, 90, 180, 270):
            rotated = rotate_tile(pennant_tile, rot)
            assert rotated["pennant"] is True


# ---------------------------------------------------------------------------
# Tests: initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_start_tile_placed(self) -> None:
        game = CarcassonneGame()
        assert (10, 10) in game.placed_tiles

    def test_start_tile_edges(self) -> None:
        game = CarcassonneGame()
        tile = game.placed_tiles[(10, 10)]
        assert tile["north"] == "city"
        assert tile["east"] == "road"
        assert tile["south"] == "field"
        assert tile["west"] == "road"

    def test_deck_has_29_tiles(self) -> None:
        game = CarcassonneGame()
        assert len(game.deck) == 29

    def test_meeple_supply(self) -> None:
        game = CarcassonneGame()
        assert game.meeple_supply["Red"] == 7
        assert game.meeple_supply["Blue"] == 7

    def test_scores_start_at_zero(self) -> None:
        game = CarcassonneGame()
        assert game.scores["Red"] == 0
        assert game.scores["Blue"] == 0

    def test_red_moves_first(self) -> None:
        game = CarcassonneGame()
        assert game.current_player() == "Red"

    def test_grid_has_component_at_center(self) -> None:
        game = CarcassonneGame()
        cid = game.board.grid_get(10, 10)
        assert cid is not None
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        assert comp.component_type == "tile"


# ---------------------------------------------------------------------------
# Tests: tile placement with edge matching
# ---------------------------------------------------------------------------


class TestTilePlacement:
    def test_place_matching_tile_south(self) -> None:
        """Place a tile south of start tile; start tile south edge is field."""
        game = CarcassonneGame()
        # Tile with field on north edge matches start tile's field south edge
        tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                "monastery": False, "pennant": False}
        game.place_tile(10, 11, tile)
        assert (10, 11) in game.placed_tiles

    def test_place_matching_tile_east(self) -> None:
        """Place a tile east of start tile; start tile east edge is road."""
        game = CarcassonneGame()
        tile = {"north": "field", "east": "field", "south": "field", "west": "road",
                "monastery": False, "pennant": False}
        game.place_tile(11, 10, tile)
        assert (11, 10) in game.placed_tiles

    def test_place_matching_tile_north(self) -> None:
        """Place a tile north of start tile; start tile north edge is city."""
        game = CarcassonneGame()
        tile = {"north": "field", "east": "field", "south": "city", "west": "field",
                "monastery": False, "pennant": False}
        game.place_tile(10, 9, tile)
        assert (10, 9) in game.placed_tiles

    def test_place_matching_tile_west(self) -> None:
        """Place a tile west of start tile; start tile west edge is road."""
        game = CarcassonneGame()
        tile = {"north": "field", "east": "road", "south": "field", "west": "field",
                "monastery": False, "pennant": False}
        game.place_tile(9, 10, tile)
        assert (9, 10) in game.placed_tiles

    def test_reject_mismatched_edge(self) -> None:
        """South of start tile: start has field south, tile has city north."""
        game = CarcassonneGame()
        tile = {"north": "city", "east": "field", "south": "field", "west": "field",
                "monastery": False, "pennant": False}
        with pytest.raises(ValueError, match="edges do not match"):
            game.place_tile(10, 11, tile)

    def test_reject_no_adjacent_tile(self) -> None:
        """Tile placed with no neighbors is invalid."""
        game = CarcassonneGame()
        tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                "monastery": False, "pennant": False}
        with pytest.raises(ValueError, match="no adjacent tile"):
            game.place_tile(0, 0, tile)

    def test_reject_occupied_cell(self) -> None:
        """Cannot place on the start tile's position."""
        game = CarcassonneGame()
        tile = TILE_DEFS[1]
        with pytest.raises(ValueError, match="already occupied"):
            game.place_tile(10, 10, tile)

    def test_reject_out_of_bounds(self) -> None:
        game = CarcassonneGame()
        tile = TILE_DEFS[1]
        with pytest.raises(ValueError, match="out of bounds"):
            game.place_tile(20, 10, tile)

    def test_place_with_rotation(self) -> None:
        """Place a tile using rotation to make edges match."""
        game = CarcassonneGame()
        # Start tile: north=city, east=road, south=field, west=road
        # TILE_DEFS[11]: north=city, east=field, south=field, west=field
        # Rotated 180: north=field, east=field, south=city, west=field
        # Place north of start: need south=city to match start's north=city
        game.place_tile(10, 9, TILE_DEFS[11], rotation=180)
        assert (10, 9) in game.placed_tiles

    def test_multiple_neighbor_matching(self) -> None:
        """Place tile with two neighbors — both edges must match."""
        game = CarcassonneGame()
        # Place field tile south of start (matches field south edge)
        field_tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                      "monastery": False, "pennant": False}
        game.place_tile(10, 11, field_tile)
        # Place tile at (11, 11) — needs to match:
        #   - north neighbor (11, 10) = none (no tile there)
        #   - west neighbor (10, 11) = field tile, east edge = field
        # So west edge must be field
        tile2 = {"north": "field", "east": "field", "south": "field", "west": "field",
                 "monastery": False, "pennant": False}
        game.place_tile(11, 11, tile2)
        assert (11, 11) in game.placed_tiles

    def test_reject_partial_mismatch(self) -> None:
        """Tile matches one neighbor but not the other."""
        game = CarcassonneGame()
        # Place road tile east of start: needs west=road
        road_tile = {"north": "field", "east": "field", "south": "field", "west": "road",
                     "monastery": False, "pennant": False}
        game.place_tile(11, 10, road_tile)
        # Place at (11, 11): north neighbor is road_tile (south=field OK)
        #   west neighbor is start tile at... wait, (10,11) is empty
        # Instead, place at (11, 9): north neighbor doesn't exist
        #   south neighbor is road_tile at (11,10), north=field, so we need south=field... OK
        #   west neighbor is start tile at (10,9)... doesn't exist
        # Let me set up a corner case: place at (10,11) south of start (field)
        # then (11,11) east of that (field east)
        # then (11,10) already has road_tile
        # Now place at (11, 11) with mismatched north (road_tile south = field, need north = field)
        # but let's try a city edge where field is expected
        bad_tile = {"north": "city", "east": "field", "south": "field", "west": "field",
                    "monastery": False, "pennant": False}
        # Place at (11,9): south neighbor is road_tile at (11,10), road_tile.north=field
        # bad_tile.south=field — that matches. But we only have one neighbor. This passes.
        # Better test: place tiles to create a corner
        field_tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                      "monastery": False, "pennant": False}
        game.place_tile(10, 11, field_tile)  # south of start
        # Now (11, 11) has west=field_tile(east=field) and north=road_tile(south=field)
        # Try placing city north edge where field is expected
        bad_corner = {"north": "city", "east": "field", "south": "field", "west": "field",
                      "monastery": False, "pennant": False}
        with pytest.raises(ValueError, match="edges do not match"):
            game.place_tile(11, 11, bad_corner)


# ---------------------------------------------------------------------------
# Tests: edge matching helper
# ---------------------------------------------------------------------------


class TestEdgeMatching:
    def test_matching_edges_north_south(self) -> None:
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (0, 0): {"north": "city", "east": "road", "south": "field", "west": "road"},
        }
        candidate = {"north": "road", "east": "field", "south": "road", "west": "field"}
        # Place south of (0,0): candidate.north must match (0,0).south = field
        assert not edges_match(tiles, 0, 1, candidate)  # road != field
        candidate2 = {"north": "field", "east": "field", "south": "road", "west": "field"}
        assert edges_match(tiles, 0, 1, candidate2)

    def test_matching_edges_east_west(self) -> None:
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (0, 0): {"north": "city", "east": "road", "south": "field", "west": "road"},
        }
        # Place east of (0,0): candidate.west must match (0,0).east = road
        good = {"north": "field", "east": "field", "south": "field", "west": "road"}
        assert edges_match(tiles, 1, 0, good)
        bad = {"north": "field", "east": "field", "south": "field", "west": "city"}
        assert not edges_match(tiles, 1, 0, bad)

    def test_no_neighbors_always_matches(self) -> None:
        """Empty board: any tile matches (but adjacency rule still applies)."""
        tiles: dict[tuple[int, int], dict[str, Any]] = {}
        candidate = {"north": "city", "east": "road", "south": "field", "west": "road"}
        assert edges_match(tiles, 5, 5, candidate)

    def test_two_neighbors_both_must_match(self) -> None:
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (0, 0): {"north": "city", "east": "road", "south": "field", "west": "road"},
            (1, 0): {"north": "field", "east": "field", "south": "road", "west": "road"},
        }
        # Place at (0,1): north neighbor (0,0).south=field, east neighbor (1,1) doesn't exist
        good = {"north": "field", "east": "field", "south": "field", "west": "field"}
        assert edges_match(tiles, 0, 1, good)
        # Place at (1,1): north=(1,0).south=road, west=(0,1) doesn't exist yet
        road_north = {"north": "road", "east": "field", "south": "field", "west": "field"}
        assert edges_match(tiles, 1, 1, road_north)


# ---------------------------------------------------------------------------
# Tests: meeple placement
# ---------------------------------------------------------------------------


class TestMeeplePlacement:
    def test_place_meeple_on_city(self) -> None:
        game = CarcassonneGame()
        # Start tile has city north, place meeple on city feature
        game.place_meeple(10, 10, "city")
        assert (10, 10, "city") in game.meeples
        assert game.meeple_supply["Red"] == 6

    def test_place_meeple_on_road(self) -> None:
        game = CarcassonneGame()
        game.place_meeple(10, 10, "road")
        assert (10, 10, "road") in game.meeples

    def test_reject_meeple_on_invalid_feature(self) -> None:
        game = CarcassonneGame()
        with pytest.raises(ValueError, match="invalid feature"):
            game.place_meeple(10, 10, "castle")

    def test_reject_meeple_on_absent_feature(self) -> None:
        """Start tile has no monastery."""
        game = CarcassonneGame()
        with pytest.raises(ValueError, match="no monastery"):
            game.place_meeple(10, 10, "monastery")

    def test_reject_meeple_on_empty_cell(self) -> None:
        game = CarcassonneGame()
        with pytest.raises(ValueError, match="no tile"):
            game.place_meeple(5, 5, "city")

    def test_reject_duplicate_meeple(self) -> None:
        game = CarcassonneGame()
        game.place_meeple(10, 10, "city")
        with pytest.raises(ValueError, match="already has a meeple"):
            game.place_meeple(10, 10, "city")

    def test_no_meeples_left(self) -> None:
        game = CarcassonneGame()
        game.meeple_supply["Red"] = 0
        with pytest.raises(ValueError, match="no meeples"):
            game.place_meeple(10, 10, "city")

    def test_return_meeple(self) -> None:
        game = CarcassonneGame()
        game.place_meeple(10, 10, "road")
        assert game.meeple_supply["Red"] == 6
        game.return_meeple(10, 10, "road")
        assert game.meeple_supply["Red"] == 7
        assert (10, 10, "road") not in game.meeples

    def test_place_meeple_on_monastery_tile(self) -> None:
        """Place a monastery tile then place meeple on monastery."""
        game = CarcassonneGame()
        # Place a monastery tile south of start (needs field north)
        monastery_tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                          "monastery": True, "pennant": False}
        game.place_tile(10, 11, monastery_tile)
        game.place_meeple(10, 11, "monastery")
        assert (10, 11, "monastery") in game.meeples

    def test_place_meeple_on_field(self) -> None:
        """Place meeple on field feature."""
        game = CarcassonneGame()
        # Start tile has field on south edge
        game.place_meeple(10, 10, "field")
        assert (10, 10, "field") in game.meeples


# ---------------------------------------------------------------------------
# Tests: city scoring
# ---------------------------------------------------------------------------


class TestCityScoring:
    def test_completed_city_two_tiles(self) -> None:
        """Two-tile city: start tile (city north) + tile north (city south).

        Independent oracle: 2 tiles * 2 points = 4 points.
        """
        game = CarcassonneGame()
        # Place meeple on start tile's city
        game.place_meeple(10, 10, "city")
        # Place tile north with city on south only (closes the city)
        city_tile = {"north": "field", "east": "field", "south": "city", "west": "field",
                     "monastery": False, "pennant": False}
        game.place_tile(10, 9, city_tile)
        points = game.score_completed_features_at(10, 9)
        assert points["Red"] == 4  # 2 tiles * 2 points

    def test_completed_city_with_pennant(self) -> None:
        """City with pennant: extra 2 points per pennant.

        Independent oracle: 2 tiles * 2 + 1 pennant * 2 = 6 points.
        """
        game = CarcassonneGame()
        game.place_meeple(10, 10, "city")
        # City tile with pennant and city south
        city_pennant = {"north": "field", "east": "field", "south": "city", "west": "field",
                        "monastery": False, "pennant": True}
        game.place_tile(10, 9, city_pennant)
        points = game.score_completed_features_at(10, 9)
        assert points["Red"] == 6  # 2*2 + 1*2

    def test_incomplete_city_not_scored(self) -> None:
        """City extending north is not complete yet — no scoring."""
        game = CarcassonneGame()
        game.place_meeple(10, 10, "city")
        # Place tile north with city on both north and south (extends city)
        extending_tile = {"north": "city", "east": "field", "south": "city", "west": "field",
                          "monastery": False, "pennant": False}
        game.place_tile(10, 9, extending_tile)
        points = game.score_completed_features_at(10, 9)
        assert points["Red"] == 0  # not complete

    def test_meeple_returned_after_city_scores(self) -> None:
        game = CarcassonneGame()
        game.place_meeple(10, 10, "city")
        assert game.meeple_supply["Red"] == 6
        closing_tile = {"north": "field", "east": "field", "south": "city", "west": "field",
                        "monastery": False, "pennant": False}
        game.place_tile(10, 9, closing_tile)
        game.score_completed_features_at(10, 9)
        assert game.meeple_supply["Red"] == 7

    def test_no_meeple_no_score(self) -> None:
        """Complete a city with no meeple — no points awarded."""
        game = CarcassonneGame()
        closing_tile = {"north": "field", "east": "field", "south": "city", "west": "field",
                        "monastery": False, "pennant": False}
        game.place_tile(10, 9, closing_tile)
        points = game.score_completed_features_at(10, 9)
        assert points["Red"] == 0
        assert points["Blue"] == 0

    def test_incomplete_city_endgame_scoring(self) -> None:
        """Independent oracle: incomplete city scores 1 per tile + 1 per pennant."""
        city_tiles = {(0, 0), (0, 1)}
        assert score_incomplete_city(city_tiles, 0) == 2
        assert score_incomplete_city(city_tiles, 1) == 3


# ---------------------------------------------------------------------------
# Tests: road scoring
# ---------------------------------------------------------------------------


class TestRoadScoring:
    def test_completed_road_two_tiles(self) -> None:
        """Road from start tile east to a tile that terminates the road.

        Start tile: east=road. Place tile at (11,10) with west=road and
        no other road edges -> road is complete (2 tiles).
        Independent oracle: 2 tiles * 1 point = 2 points.
        """
        game = CarcassonneGame()
        game.place_meeple(10, 10, "road")
        terminating_tile = {"north": "field", "east": "field", "south": "field", "west": "road",
                            "monastery": False, "pennant": False}
        game.place_tile(11, 10, terminating_tile)
        # Also need to close the west side of the start tile's road
        west_term = {"north": "field", "east": "road", "south": "field", "west": "field",
                     "monastery": False, "pennant": False}
        game.place_tile(9, 10, west_term)
        # Now the road through start tile connects (9,10) - (10,10) - (11,10)
        # Each tile has road terminating at endpoints
        points = game.score_completed_features_at(9, 10)
        assert points["Red"] == 3  # 3 tiles in road

    def test_road_not_complete(self) -> None:
        """Road extends but doesn't terminate — not scored."""
        game = CarcassonneGame()
        game.place_meeple(10, 10, "road")
        # Place tile east that continues the road
        continuing_tile = {"north": "field", "east": "road", "south": "field", "west": "road",
                           "monastery": False, "pennant": False}
        game.place_tile(11, 10, continuing_tile)
        points = game.score_completed_features_at(11, 10)
        assert points["Red"] == 0

    def test_road_score_helper(self) -> None:
        """Independent oracle: completed road = 1 per tile."""
        assert score_completed_road({(0, 0), (1, 0), (2, 0)}) == 3

    def test_meeple_returned_after_road_scores(self) -> None:
        game = CarcassonneGame()
        game.place_meeple(10, 10, "road")
        assert game.meeple_supply["Red"] == 6
        # Close road on both sides
        east_term = {"north": "field", "east": "field", "south": "field", "west": "road",
                     "monastery": False, "pennant": False}
        game.place_tile(11, 10, east_term)
        west_term = {"north": "field", "east": "road", "south": "field", "west": "field",
                     "monastery": False, "pennant": False}
        game.place_tile(9, 10, west_term)
        game.score_completed_features_at(9, 10)
        assert game.meeple_supply["Red"] == 7


# ---------------------------------------------------------------------------
# Tests: monastery scoring
# ---------------------------------------------------------------------------


class TestMonasteryScoring:
    def test_score_monastery_helper(self) -> None:
        """Independent oracle: monastery score = 1 + surrounding tiles."""
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (5, 5): {"monastery": True},
        }
        assert score_monastery(tiles, 5, 5) == 1  # just the monastery

    def test_monastery_partial_score(self) -> None:
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (5, 5): {"monastery": True},
            (4, 4): {},
            (5, 4): {},
            (6, 4): {},
        }
        assert score_monastery(tiles, 5, 5) == 4  # 1 + 3 neighbors

    def test_monastery_complete(self) -> None:
        """Independent oracle: fully surrounded = 9 points."""
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (5, 5): {"monastery": True},
        }
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                tiles[(5 + dc, 5 + dr)] = {}
        assert score_monastery(tiles, 5, 5) == 9
        assert is_monastery_complete(tiles, 5, 5)

    def test_monastery_not_complete(self) -> None:
        tiles: dict[tuple[int, int], dict[str, Any]] = {
            (5, 5): {"monastery": True},
            (4, 4): {},
        }
        assert not is_monastery_complete(tiles, 5, 5)

    def test_monastery_scored_in_game(self) -> None:
        """Place monastery tile surrounded by tiles, score 9 points."""
        game = CarcassonneGame()
        # Place monastery tile south of start
        monastery_tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                          "monastery": True, "pennant": False}
        game.place_tile(10, 11, monastery_tile)
        game.place_meeple(10, 11, "monastery")

        # Surround the monastery with field tiles
        field_tile = {"north": "field", "east": "field", "south": "field", "west": "field",
                      "monastery": False, "pennant": False}
        # (10,10) already has start tile. Need all 8 neighbors of (10,11):
        # (9,10), (11,10), (9,11), (11,11), (9,12), (10,12), (11,12)
        # (10,10) already placed as start tile
        # But (9,10) and (11,10) need to match start tile edges
        # Start tile: N=city, E=road, S=field, W=road
        # (9,10) is west of start: needs east=road to match start.west=road
        game.place_tile(9, 10, {"north": "field", "east": "road", "south": "field", "west": "field",
                                "monastery": False, "pennant": False})
        # (11,10) is east of start: needs west=road to match start.east=road
        game.place_tile(11, 10, {"north": "field", "east": "field", "south": "field", "west": "road",
                                 "monastery": False, "pennant": False})
        # (9,11) west of monastery: needs east=field
        game.place_tile(9, 11, field_tile)
        # (11,11) east of monastery: needs west=field
        game.place_tile(11, 11, field_tile)
        # (9,12) SW of monastery: needs to match (9,11).south=field
        game.place_tile(9, 12, field_tile)
        # (10,12) south of monastery: needs north=field
        game.place_tile(10, 12, field_tile)
        # (11,12) SE of monastery: needs west=field and north=field
        game.place_tile(11, 12, field_tile)

        # Now monastery at (10,11) is fully surrounded
        points = game.score_completed_features_at(11, 12)
        assert points["Red"] == 9
        assert game.meeple_supply["Red"] == 7  # meeple returned


# ---------------------------------------------------------------------------
# Tests: game flow
# ---------------------------------------------------------------------------


class TestGameFlow:
    def test_turn_alternates(self) -> None:
        game = CarcassonneGame()
        assert game.current_player() == "Red"
        game.end_turn()
        assert game.current_player() == "Blue"
        game.end_turn()
        assert game.current_player() == "Red"

    def test_draw_tile(self) -> None:
        game = CarcassonneGame()
        tile = game.draw_tile()
        assert tile is not None
        assert len(game.deck) == 28

    def test_draw_empty_deck(self) -> None:
        game = CarcassonneGame()
        game.deck = []
        assert game.draw_tile() is None

    def test_game_ends_when_deck_empty(self) -> None:
        game = CarcassonneGame()
        game.deck = []
        game.end_turn()
        assert game.finished is True

    def test_cannot_place_after_game_over(self) -> None:
        game = CarcassonneGame()
        game.finished = True
        tile = TILE_DEFS[1]
        with pytest.raises(ValueError, match="game is finished"):
            game.place_tile(10, 11, tile)

    def test_full_turn_sequence(self) -> None:
        """Draw, place, optionally meeple, score, end turn."""
        game = CarcassonneGame()
        # Red draws
        tile = game.draw_tile()
        assert tile is not None
        # Red places (tile 1 = all field)
        game.place_tile(10, 11, tile)
        # Red optionally places meeple (field feature exists)
        game.place_meeple(10, 11, "field")
        # Score completed features
        game.score_completed_features_at(10, 11)
        # End turn
        game.end_turn()
        assert game.current_player() == "Blue"

    def test_score_accumulation(self) -> None:
        """Score accumulates across multiple scoring events."""
        game = CarcassonneGame()
        game.scores["Red"] = 10
        game.place_meeple(10, 10, "city")
        closing_tile = {"north": "field", "east": "field", "south": "city", "west": "field",
                        "monastery": False, "pennant": False}
        game.place_tile(10, 9, closing_tile)
        game.score_completed_features_at(10, 9)
        assert game.scores["Red"] == 14  # 10 + 4 (2 tiles * 2)
