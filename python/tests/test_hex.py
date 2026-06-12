"""Tests for Hex: stone placement and graph connectivity win detection.

Two players alternate placing stones on an 11×11 hex grid. Red owns
top and bottom edges; Blue owns left and right edges. First to connect
their two edges through an unbroken chain of their stones wins. No draws
are possible (proven by John Nash, 1949).

Hex connectivity uses 6 neighbors per cell (hex adjacency). Win detection
is BFS from one owned edge, checking if any stone reaches the opposite edge.

Tests use smaller boards (5×5, 7×7) for tractable scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "hex.json"


def _load_hex() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# HexGame helper
# ---------------------------------------------------------------------------

# Hex grid neighbors: 6 directions
# On a rectangular grid representing hex, neighbors of (col, row) are:
#   (col-1, row), (col+1, row),           # left, right
#   (col, row-1), (col, row+1),           # up, down
#   (col-1, row+1), (col+1, row-1)        # diagonal (hex offset)
_HEX_NEIGHBORS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]


class HexGame:
    """Hex game driver with placement and connectivity win detection."""

    def __init__(self, size: int = 11) -> None:
        defn_data = json.loads(_GAME_PATH.read_text())
        defn_data["zones"]["board"]["dimensions"] = [size, size]
        defn = GameDefinition.from_json(json.dumps(defn_data))
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.size = size
        self.finished = False
        self.winner: str | None = None

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def owner_at(self, col: int, row: int) -> str | None:
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def _neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        result = []
        for dc, dr in _HEX_NEIGHBORS:
            nc, nr = col + dc, row + dr
            if 0 <= nc < self.size and 0 <= nr < self.size:
                result.append((nc, nr))
        return result

    def _check_connection(self, player: str) -> bool:
        """BFS: does player connect their two edges?

        Red: top (row=0) to bottom (row=size-1)
        Blue: left (col=0) to right (col=size-1)
        """
        if player == "Red":
            # Start from all Red stones on row 0, target row = size-1
            starts = [
                (c, 0) for c in range(self.size) if self.owner_at(c, 0) == "Red"
            ]
            target_check = lambda c, r: r == self.size - 1
        else:
            # Start from all Blue stones on col 0, target col = size-1
            starts = [
                (0, r) for r in range(self.size) if self.owner_at(0, r) == "Blue"
            ]
            target_check = lambda c, r: c == self.size - 1

        visited: set[tuple[int, int]] = set()
        stack = list(starts)

        while stack:
            col, row = stack.pop()
            if (col, row) in visited:
                continue
            visited.add((col, row))
            if target_check(col, row):
                return True
            for nc, nr in self._neighbors(col, row):
                if (nc, nr) not in visited and self.owner_at(nc, nr) == player:
                    stack.append((nc, nr))

        return False

    def play(self, col: int, row: int) -> bool:
        """Place a stone. Returns True if this move wins."""
        if self.finished:
            raise ValueError("game is finished")
        if self.owner_at(col, row) is not None:
            raise ValueError(f"cell ({col},{row}) is occupied")

        player = self.current_player()

        apply_action(
            self.session,
            Action(
                action_type="place",
                component_type="stone",
                to_pos={"zone": "board", "cell": f"{col},{row}"},
            ),
        )

        if self._check_connection(player):
            self.finished = True
            self.winner = player
            return True

        return False


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestHexDefinition:
    def test_loads(self) -> None:
        defn = _load_hex()
        assert defn.game.name == "Hex"

    def test_two_players(self) -> None:
        defn = _load_hex()
        assert defn.game.players == ["Red", "Blue"]

    def test_hex_grid(self) -> None:
        defn = _load_hex()
        assert defn.zones["board"].zone_type == "hex_grid"

    def test_hex_adjacency(self) -> None:
        defn = _load_hex()
        assert defn.zones["board"].adjacency == "hex_6"


# ---------------------------------------------------------------------------
# Tests: placement
# ---------------------------------------------------------------------------


class TestPlacement:
    def test_place_stone(self) -> None:
        game = HexGame(size=5)
        game.play(2, 2)
        assert game.owner_at(2, 2) == "Red"

    def test_alternating_players(self) -> None:
        game = HexGame(size=5)
        game.play(0, 0)
        assert game.owner_at(0, 0) == "Red"
        game.play(1, 1)
        assert game.owner_at(1, 1) == "Blue"

    def test_occupied_rejected(self) -> None:
        game = HexGame(size=5)
        game.play(2, 2)
        with pytest.raises(ValueError, match="occupied"):
            game.play(2, 2)

    def test_board_starts_empty(self) -> None:
        game = HexGame(size=5)
        for r in range(5):
            for c in range(5):
                assert game.owner_at(c, r) is None


# ---------------------------------------------------------------------------
# Tests: hex neighbors
# ---------------------------------------------------------------------------


class TestNeighbors:
    def test_center_has_6_neighbors(self) -> None:
        game = HexGame(size=5)
        n = game._neighbors(2, 2)
        assert len(n) == 6

    def test_corner_has_2_neighbors(self) -> None:
        game = HexGame(size=5)
        # Top-left corner (0,0): neighbors (1,0) and (0,1)
        # (-1,0), (0,-1), (-1,1), (1,-1) are all out of bounds
        n = game._neighbors(0, 0)
        assert len(n) == 2
        assert (1, 0) in n
        assert (0, 1) in n

    def test_edge_has_4_neighbors(self) -> None:
        game = HexGame(size=5)
        # Top edge middle (2,0)
        n = game._neighbors(2, 0)
        assert len(n) == 4


# ---------------------------------------------------------------------------
# Tests: connectivity win detection
# ---------------------------------------------------------------------------


class TestConnectivity:
    def test_red_wins_top_to_bottom(self) -> None:
        """Red connects top (row=0) to bottom (row=4) on a 5×5 board."""
        game = HexGame(size=5)
        # Red plays column 2, rows 0-4 (straight vertical path)
        # Blue plays column 0
        game.play(2, 0)  # Red
        game.play(0, 0)  # Blue
        game.play(2, 1)  # Red
        game.play(0, 1)  # Blue
        game.play(2, 2)  # Red
        game.play(0, 2)  # Blue
        game.play(2, 3)  # Red
        game.play(0, 3)  # Blue
        won = game.play(2, 4)  # Red — connects top to bottom

        assert won is True
        assert game.winner == "Red"

    def test_blue_wins_left_to_right(self) -> None:
        """Blue connects left (col=0) to right (col=4) on a 5×5 board."""
        game = HexGame(size=5)
        # Blue plays row 2, cols 0-4 (straight horizontal path)
        # Red plays row 4
        game.play(0, 4)  # Red
        game.play(0, 2)  # Blue
        game.play(1, 4)  # Red
        game.play(1, 2)  # Blue
        game.play(2, 4)  # Red
        game.play(2, 2)  # Blue
        game.play(3, 4)  # Red
        game.play(3, 2)  # Blue
        game.play(4, 0)  # Red (throwaway)
        won = game.play(4, 2)  # Blue — connects left to right

        assert won is True
        assert game.winner == "Blue"

    def test_no_win_partial_path(self) -> None:
        """Partial path doesn't trigger win."""
        game = HexGame(size=5)
        game.play(2, 0)  # Red
        game.play(0, 0)  # Blue
        game.play(2, 1)  # Red
        game.play(0, 1)  # Blue
        game.play(2, 2)  # Red — 3 in a column, not connected to bottom
        assert game.finished is False

    def test_diagonal_path_wins(self) -> None:
        """Red wins via a diagonal hex path on 5×5."""
        game = HexGame(size=5)
        # Use hex adjacency: (col+1, row-1) is a neighbor
        # Path: (0,0) → (1,0) → (2,1) → (3,1) → (4,2) ...
        # Actually just do a zigzag that reaches row 4
        # (0,0), (0,1), (1,1), (1,2), (2,2), (2,3), (3,3), (3,4)
        red_path = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 4)]
        blue_moves = [(4, 0), (4, 1), (4, 2), (4, 3), (4, 4), (3, 0), (3, 1)]

        for i, (rc, rr) in enumerate(red_path):
            won = game.play(rc, rr)  # Red
            if won:
                break
            if i < len(blue_moves):
                game.play(*blue_moves[i])  # Blue

        assert game.finished
        assert game.winner == "Red"

    def test_disconnected_stones_no_win(self) -> None:
        """Scattered stones don't form a connection."""
        game = HexGame(size=5)
        game.play(0, 0)  # Red top-left
        game.play(1, 1)  # Blue
        game.play(4, 4)  # Red bottom-right (not connected to 0,0)
        assert game.finished is False


# ---------------------------------------------------------------------------
# Tests: game properties
# ---------------------------------------------------------------------------


class TestGameProperties:
    def test_cannot_play_after_win(self) -> None:
        game = HexGame(size=5)
        for row in range(5):
            game.play(2, row)  # Red column 2
            if row < 4:
                game.play(0, row)  # Blue column 0
        assert game.finished
        with pytest.raises(ValueError, match="finished"):
            game.play(1, 1)

    def test_red_moves_first(self) -> None:
        game = HexGame(size=5)
        assert game.current_player() == "Red"

    def test_7x7_board(self) -> None:
        """Larger board works."""
        game = HexGame(size=7)
        game.play(3, 3)
        assert game.owner_at(3, 3) == "Red"
        assert game.size == 7
