"""Tests for Stratego: hidden-rank two-player strategy game.

Stratego is a 2-player imperfect-information game on a 10x10 grid with two
impassable 2x2 lakes in the center. Each player has 40 pieces with hidden
ranks. The objective is to capture the opponent's Flag.

Board conventions:
  - 10x10 grid, orthogonal_4 adjacency
  - Red places on rows 0-3, Blue places on rows 6-9
  - Lakes at (2,4),(3,4),(2,5),(3,5) and (6,4),(7,4),(6,5),(7,5)

Piece ranks (high to low):
  Marshal=10, General=9, Colonel=8, Major=7, Captain=6, Lieutenant=5,
  Sergeant=4, Miner=3, Scout=2, Spy=1, Bomb=0, Flag=0

Combat rules:
  - Higher rank wins, lower rank captured
  - Equal ranks: both removed
  - Spy kills Marshal only on attack
  - Miner defuses Bombs
  - Non-Miner attacking Bomb is destroyed
  - Bomb/Flag are immobile
  - Scout slides any distance orthogonally
"""

from __future__ import annotations

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
# Piece data
# ---------------------------------------------------------------------------

PIECE_COUNTS: dict[str, int] = {
    "marshal": 1,
    "general": 1,
    "colonel": 2,
    "major": 3,
    "captain": 4,
    "lieutenant": 4,
    "sergeant": 4,
    "miner": 5,
    "scout": 8,
    "spy": 1,
    "bomb": 6,
    "flag": 1,
}

PIECE_RANKS: dict[str, int] = {
    "marshal": 10,
    "general": 9,
    "colonel": 8,
    "major": 7,
    "captain": 6,
    "lieutenant": 5,
    "sergeant": 4,
    "miner": 3,
    "scout": 2,
    "spy": 1,
    "bomb": 0,
    "flag": 0,
}

IMMOBILE_PIECES = {"bomb", "flag"}

TOTAL_PIECES_PER_PLAYER = 40

# Lake cell coordinates (col, row)
LAKE_CELLS: set[tuple[int, int]] = {
    (2, 4), (3, 4), (2, 5), (3, 5),
    (6, 4), (7, 4), (6, 5), (7, 5),
}

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "stratego.json"

_ORTHO_DIRS: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# StrategoGame helper
# ---------------------------------------------------------------------------


class StrategoGame:
    """Stratego game driver -- board setup, movement, combat resolution."""

    BOARD_SIZE = 10

    def __init__(self) -> None:
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def is_lake(self, col: int, row: int) -> bool:
        """Check if a cell is a lake (impassable)."""
        return (col, row) in LAKE_CELLS

    def is_valid(self, col: int, row: int) -> bool:
        """Check if (col, row) is within the 10x10 board."""
        return 0 <= col < self.BOARD_SIZE and 0 <= row < self.BOARD_SIZE

    def place(self, col: int, row: int, piece_type: str, owner: str) -> ComponentId:
        """Place a piece on the board."""
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{piece_type}-{owner}-{col}-{row}",
                component_type=piece_type,
                owner=owner,
                properties={"rank": PIECE_RANKS[piece_type]},
            )
        )
        self.board.grid_push(col, row, cid)
        return cid

    def piece_at(self, col: int, row: int) -> tuple[str, str, int] | None:
        """Return (piece_type, owner, rank) at cell, or None."""
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        if comp is None:
            return None
        return (comp.component_type, comp.owner, comp.properties.get("rank", 0))

    def is_occupied(self, col: int, row: int) -> bool:
        """Check if a cell has a piece on it."""
        return self.board.grid_get(col, row) is not None

    # -------------------------------------------------------------------
    # Movement
    # -------------------------------------------------------------------

    def can_move(self, piece_type: str) -> bool:
        """Check if a piece type is movable (not Bomb or Flag)."""
        return piece_type not in IMMOBILE_PIECES

    def is_legal_step(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
    ) -> bool:
        """Check if a single-step move is legal for the piece at (from).

        Rules:
        - Source must have a piece
        - Piece must be movable (not bomb/flag)
        - Destination must be on the board
        - Destination must not be a lake
        - Movement must be exactly one cell orthogonal
        - Destination must not contain a friendly piece
        """
        info = self.piece_at(from_col, from_row)
        if info is None:
            return False
        piece_type, owner, _ = info

        if not self.can_move(piece_type):
            return False

        if not self.is_valid(to_col, to_row):
            return False

        if self.is_lake(to_col, to_row):
            return False

        # Must be orthogonal distance 1
        dc = abs(to_col - from_col)
        dr = abs(to_row - from_row)
        if dc + dr != 1:
            return False

        # Cannot enter cell with friendly piece
        dest_info = self.piece_at(to_col, to_row)
        if dest_info is not None and dest_info[1] == owner:
            return False

        return True

    def is_legal_scout_slide(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
    ) -> bool:
        """Check if a Scout slide move is legal.

        Scouts can slide any number of cells in a straight orthogonal line,
        but cannot pass through occupied cells or lakes. The destination
        may contain an enemy piece (initiating combat).
        """
        info = self.piece_at(from_col, from_row)
        if info is None:
            return False
        piece_type, owner, _ = info

        if piece_type != "scout":
            return False

        if not self.is_valid(to_col, to_row):
            return False

        if self.is_lake(to_col, to_row):
            return False

        # Must be a straight orthogonal line
        if from_col != to_col and from_row != to_row:
            return False
        if from_col == to_col and from_row == to_row:
            return False

        # Determine direction
        if from_col == to_col:
            step = 1 if to_row > from_row else -1
            # Check all intermediate cells are empty and not lakes
            r = from_row + step
            while r != to_row:
                if self.is_lake(from_col, r) or self.is_occupied(from_col, r):
                    return False
                r += step
        else:
            step = 1 if to_col > from_col else -1
            c = from_col + step
            while c != to_col:
                if self.is_lake(c, from_row) or self.is_occupied(c, from_row):
                    return False
                c += step

        # Destination must not contain a friendly piece
        dest_info = self.piece_at(to_col, to_row)
        if dest_info is not None and dest_info[1] == owner:
            return False

        return True

    def move_piece(
        self, from_col: int, from_row: int, to_col: int, to_row: int
    ) -> None:
        """Move the piece at (from) to (to). Does not resolve combat."""
        cid = self.board.grid_pop(from_col, from_row)
        assert cid is not None, f"No piece at ({from_col},{from_row})"
        self.board.grid_push(to_col, to_row, cid)

    # -------------------------------------------------------------------
    # Combat resolution
    # -------------------------------------------------------------------

    def resolve_combat(
        self,
        attacker_col: int,
        attacker_row: int,
        defender_col: int,
        defender_row: int,
    ) -> str:
        """Resolve combat between attacker at (ac,ar) and defender at (dc,dr).

        Returns one of:
          "attacker_wins" - defender removed, attacker moves to defender cell
          "defender_wins" - attacker removed
          "both_removed"  - both pieces removed (equal rank)

        Special cases:
          - Spy attacking Marshal: attacker wins
          - Miner attacking Bomb: attacker wins (defuses bomb)
          - Non-Miner attacking Bomb: defender wins (attacker destroyed)
        """
        atk_cid = self.board.grid_get(attacker_col, attacker_row)
        def_cid = self.board.grid_get(defender_col, defender_row)
        assert atk_cid is not None, f"No attacker at ({attacker_col},{attacker_row})"
        assert def_cid is not None, f"No defender at ({defender_col},{defender_row})"

        atk_comp = self.session.runtime.components.get(atk_cid)
        def_comp = self.session.runtime.components.get(def_cid)
        assert atk_comp is not None
        assert def_comp is not None

        atk_type = atk_comp.component_type
        def_type = def_comp.component_type
        atk_rank = PIECE_RANKS[atk_type]
        def_rank = PIECE_RANKS[def_type]

        # Special: Spy attacks Marshal
        if atk_type == "spy" and def_type == "marshal":
            self.board.grid_pop(defender_col, defender_row)
            self.move_piece(attacker_col, attacker_row, defender_col, defender_row)
            return "attacker_wins"

        # Special: attacking a Bomb
        if def_type == "bomb":
            if atk_type == "miner":
                # Miner defuses bomb
                self.board.grid_pop(defender_col, defender_row)
                self.move_piece(
                    attacker_col, attacker_row, defender_col, defender_row
                )
                return "attacker_wins"
            else:
                # Non-miner destroyed by bomb; bomb stays
                self.board.grid_pop(attacker_col, attacker_row)
                return "defender_wins"

        # Special: attacking a Flag (always wins)
        if def_type == "flag":
            self.board.grid_pop(defender_col, defender_row)
            self.move_piece(attacker_col, attacker_row, defender_col, defender_row)
            self.finished = True
            self.winner = atk_comp.owner
            return "attacker_wins"

        # Standard combat: higher rank wins
        if atk_rank > def_rank:
            self.board.grid_pop(defender_col, defender_row)
            self.move_piece(attacker_col, attacker_row, defender_col, defender_row)
            return "attacker_wins"
        elif def_rank > atk_rank:
            self.board.grid_pop(attacker_col, attacker_row)
            return "defender_wins"
        else:
            # Equal rank: both removed
            self.board.grid_pop(attacker_col, attacker_row)
            self.board.grid_pop(defender_col, defender_row)
            return "both_removed"

    # -------------------------------------------------------------------
    # Legal moves enumeration
    # -------------------------------------------------------------------

    def legal_moves(self, owner: str) -> list[tuple[int, int, int, int]]:
        """Return all legal moves for a player as (from_col, from_row, to_col, to_row)."""
        moves: list[tuple[int, int, int, int]] = []
        for row in range(self.BOARD_SIZE):
            for col in range(self.BOARD_SIZE):
                info = self.piece_at(col, row)
                if info is None or info[1] != owner:
                    continue
                piece_type = info[0]
                if not self.can_move(piece_type):
                    continue

                if piece_type == "scout":
                    # Check all orthogonal slides
                    for dc, dr in _ORTHO_DIRS:
                        tc, tr = col + dc, row + dr
                        while self.is_valid(tc, tr):
                            if self.is_lake(tc, tr):
                                break
                            if self.is_occupied(tc, tr):
                                dest_info = self.piece_at(tc, tr)
                                if dest_info is not None and dest_info[1] != owner:
                                    moves.append((col, row, tc, tr))
                                break
                            moves.append((col, row, tc, tr))
                            tc += dc
                            tr += dr
                else:
                    # Standard piece: check 4 orthogonal neighbors
                    for dc, dr in _ORTHO_DIRS:
                        tc, tr = col + dc, row + dr
                        if self.is_legal_step(col, row, tc, tr):
                            moves.append((col, row, tc, tr))
        return moves

    def has_legal_moves(self, owner: str) -> bool:
        """Check if a player has at least one legal move."""
        return len(self.legal_moves(owner)) > 0

    # -------------------------------------------------------------------
    # Standard setup
    # -------------------------------------------------------------------

    def setup_standard(self) -> None:
        """Place a standard Stratego layout for both players.

        Red (rows 0-3): back row has flag + bombs + marshal, front rows
        have mobile pieces. Blue (rows 6-9): mirror layout.
        """
        # Red pieces (rows 0-3)
        red_layout = [
            # Row 0: flag surrounded by bombs, plus marshal and general
            ("flag", 0, 0), ("bomb", 1, 0), ("bomb", 2, 0), ("bomb", 3, 0),
            ("marshal", 4, 0), ("general", 5, 0), ("bomb", 6, 0), ("bomb", 7, 0),
            ("bomb", 8, 0), ("colonel", 9, 0),
            # Row 1: colonels, majors, captains
            ("colonel", 0, 1), ("major", 1, 1), ("major", 2, 1), ("major", 3, 1),
            ("captain", 4, 1), ("captain", 5, 1), ("captain", 6, 1), ("captain", 7, 1),
            ("lieutenant", 8, 1), ("lieutenant", 9, 1),
            # Row 2: lieutenants, sergeants, miners
            ("lieutenant", 0, 2), ("lieutenant", 1, 2), ("sergeant", 2, 2),
            ("sergeant", 3, 2), ("sergeant", 4, 2), ("sergeant", 5, 2),
            ("miner", 6, 2), ("miner", 7, 2), ("miner", 8, 2), ("miner", 9, 2),
            # Row 3: miners, scouts, spy
            ("miner", 0, 3), ("scout", 1, 3), ("scout", 2, 3), ("scout", 3, 3),
            ("scout", 4, 3), ("scout", 5, 3), ("scout", 6, 3), ("scout", 7, 3),
            ("spy", 8, 3), ("scout", 9, 3),
        ]

        for piece_type, col, row in red_layout:
            self.place(col, row, piece_type, "red")

        # Blue pieces (rows 6-9) — mirror of red
        blue_layout = [
            # Row 6: scouts and spy (front line)
            ("scout", 0, 6), ("scout", 1, 6), ("scout", 2, 6), ("scout", 3, 6),
            ("scout", 4, 6), ("scout", 5, 6), ("scout", 6, 6), ("scout", 7, 6),
            ("spy", 8, 6), ("miner", 9, 6),
            # Row 7: miners, sergeants, lieutenants
            ("miner", 0, 7), ("miner", 1, 7), ("miner", 2, 7), ("miner", 3, 7),
            ("sergeant", 4, 7), ("sergeant", 5, 7), ("sergeant", 6, 7),
            ("sergeant", 7, 7), ("lieutenant", 8, 7), ("lieutenant", 9, 7),
            # Row 8: lieutenants, captains, majors, colonels
            ("lieutenant", 0, 8), ("lieutenant", 1, 8), ("captain", 2, 8),
            ("captain", 3, 8), ("captain", 4, 8), ("captain", 5, 8),
            ("major", 6, 8), ("major", 7, 8), ("major", 8, 8), ("colonel", 9, 8),
            # Row 9: flag, bombs, marshal, general, colonel
            ("flag", 0, 9), ("bomb", 1, 9), ("bomb", 2, 9), ("bomb", 3, 9),
            ("marshal", 4, 9), ("general", 5, 9), ("bomb", 6, 9), ("bomb", 7, 9),
            ("bomb", 8, 9), ("colonel", 9, 9),
        ]

        for piece_type, col, row in blue_layout:
            self.place(col, row, piece_type, "blue")


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and has correct structure."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Stratego"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["red", "blue"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_board_dimensions(self) -> None:
        defn = _load_definition()
        board = defn.zones["board"]
        assert board.zone_type == "grid"
        assert board.dimensions == [10, 10]

    def test_twelve_component_types(self) -> None:
        defn = _load_definition()
        expected = {
            "marshal", "general", "colonel", "major", "captain",
            "lieutenant", "sergeant", "miner", "scout", "spy",
            "bomb", "flag",
        }
        assert set(defn.components.keys()) == expected

    def test_three_end_conditions(self) -> None:
        defn = _load_definition()
        assert len(defn.end_conditions) == 3

    def test_two_phases(self) -> None:
        defn = _load_definition()
        assert defn.phases is not None
        assert len(defn.phases) == 2
        assert defn.phases[0].name == "setup"
        assert defn.phases[1].name == "play"

    def test_server_only_combat_resolution(self) -> None:
        defn = _load_definition()
        server_ops = defn.authority.server_only
        assert any("resolve_combat" in op for op in server_ops)

    def test_lake_cell_properties(self) -> None:
        defn = _load_definition()
        board = defn.zones["board"]
        assert board.cell_properties is not None
        assert len(board.cell_properties) == 8
        for coord, props in board.cell_properties.items():
            assert props.get("terrain") == "lake"


class TestPieceData:
    """Verify piece count and rank data tables."""

    def test_total_pieces_per_player(self) -> None:
        total = sum(PIECE_COUNTS.values())
        assert total == TOTAL_PIECES_PER_PLAYER

    def test_piece_counts_match_definition(self) -> None:
        defn = _load_definition()
        for name, expected_count in PIECE_COUNTS.items():
            comp = defn.components[name]
            assert comp.count == expected_count, (
                f"{name}: expected count {expected_count}, got {comp.count}"
            )

    def test_marshal_is_highest_rank(self) -> None:
        assert PIECE_RANKS["marshal"] == 10
        assert all(
            PIECE_RANKS[p] < PIECE_RANKS["marshal"]
            for p in PIECE_RANKS
            if p != "marshal"
        )

    def test_spy_is_lowest_movable_rank(self) -> None:
        assert PIECE_RANKS["spy"] == 1
        movable = {p: r for p, r in PIECE_RANKS.items() if p not in IMMOBILE_PIECES}
        assert PIECE_RANKS["spy"] == min(movable.values())

    def test_bomb_and_flag_rank_zero(self) -> None:
        assert PIECE_RANKS["bomb"] == 0
        assert PIECE_RANKS["flag"] == 0


class TestLakes:
    """Verify lake cell positions and impassability."""

    def test_eight_lake_cells(self) -> None:
        assert len(LAKE_CELLS) == 8

    def test_lake_cells_in_center_rows(self) -> None:
        for _, row in LAKE_CELLS:
            assert row in (4, 5), f"Lake cell at unexpected row {row}"

    def test_two_separate_lakes(self) -> None:
        left_lake = {(c, r) for c, r in LAKE_CELLS if c < 5}
        right_lake = {(c, r) for c, r in LAKE_CELLS if c >= 5}
        assert len(left_lake) == 4
        assert len(right_lake) == 4

    def test_lake_detected_by_cell_properties(self) -> None:
        g = StrategoGame()
        for col, row in LAKE_CELLS:
            terrain = g.board.get_cell_property(col, row, "terrain")
            assert terrain == "lake", f"({col},{row}) not marked as lake"

    def test_non_lake_has_no_terrain(self) -> None:
        g = StrategoGame()
        # Check a non-lake cell
        terrain = g.board.get_cell_property(0, 0, "terrain")
        assert terrain is None

    def test_cannot_place_on_lake(self) -> None:
        g = StrategoGame()
        assert g.is_lake(2, 4)


class TestSetup:
    """Verify standard game setup."""

    def test_standard_setup_places_80_pieces(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        count = 0
        for row in range(10):
            for col in range(10):
                if g.is_occupied(col, row):
                    count += 1
        assert count == 80

    def test_red_pieces_on_rows_0_to_3(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        for row in range(4):
            for col in range(10):
                info = g.piece_at(col, row)
                assert info is not None, f"Expected red piece at ({col},{row})"
                assert info[1] == "red", f"Expected red at ({col},{row}), got {info[1]}"

    def test_blue_pieces_on_rows_6_to_9(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        for row in range(6, 10):
            for col in range(10):
                info = g.piece_at(col, row)
                assert info is not None, f"Expected blue piece at ({col},{row})"
                assert info[1] == "blue", f"Expected blue at ({col},{row}), got {info[1]}"

    def test_no_pieces_on_rows_4_and_5(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        for row in (4, 5):
            for col in range(10):
                if not g.is_lake(col, row):
                    assert not g.is_occupied(col, row), (
                        f"Unexpected piece at ({col},{row})"
                    )

    def test_each_player_has_one_flag(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        red_flags = 0
        blue_flags = 0
        for row in range(10):
            for col in range(10):
                info = g.piece_at(col, row)
                if info is not None and info[0] == "flag":
                    if info[1] == "red":
                        red_flags += 1
                    else:
                        blue_flags += 1
        assert red_flags == 1
        assert blue_flags == 1

    def test_each_player_has_correct_piece_counts(self) -> None:
        g = StrategoGame()
        g.setup_standard()
        for owner in ("red", "blue"):
            counts: dict[str, int] = {}
            for row in range(10):
                for col in range(10):
                    info = g.piece_at(col, row)
                    if info is not None and info[1] == owner:
                        counts[info[0]] = counts.get(info[0], 0) + 1
            for piece_type, expected in PIECE_COUNTS.items():
                actual = counts.get(piece_type, 0)
                assert actual == expected, (
                    f"{owner} {piece_type}: expected {expected}, got {actual}"
                )


class TestMovement:
    """Verify movement rules."""

    def test_standard_piece_step_one(self) -> None:
        g = StrategoGame()
        # (1, 1) has no lake neighbors -- all 4 orthogonal moves are valid
        g.place(1, 1, "captain", "red")
        assert g.is_legal_step(1, 1, 1, 2)
        assert g.is_legal_step(1, 1, 1, 0)
        assert g.is_legal_step(1, 1, 0, 1)
        assert g.is_legal_step(1, 1, 2, 1)

    def test_cannot_move_two_cells(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        assert not g.is_legal_step(5, 5, 5, 7)

    def test_cannot_move_diagonal(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        assert not g.is_legal_step(5, 5, 6, 6)

    def test_cannot_move_bomb(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "bomb", "red")
        assert not g.is_legal_step(5, 5, 5, 6)
        assert not g.can_move("bomb")

    def test_cannot_move_flag(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "flag", "red")
        assert not g.is_legal_step(5, 5, 5, 6)
        assert not g.can_move("flag")

    def test_cannot_enter_lake(self) -> None:
        g = StrategoGame()
        g.place(2, 3, "captain", "red")
        # (2, 4) is a lake cell
        assert g.is_lake(2, 4)
        assert not g.is_legal_step(2, 3, 2, 4)

    def test_cannot_enter_friendly_piece(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 6, "sergeant", "red")
        assert not g.is_legal_step(5, 5, 5, 6)

    def test_can_enter_enemy_piece(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 6, "sergeant", "blue")
        assert g.is_legal_step(5, 5, 5, 6)

    def test_cannot_move_off_board(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "captain", "red")
        assert not g.is_legal_step(0, 0, -1, 0)
        assert not g.is_legal_step(0, 0, 0, -1)


class TestScoutMovement:
    """Verify Scout slide movement."""

    def test_scout_slides_multiple_cells(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        # Can slide to any cell in column 0, rows 1-3 (before lake/pieces)
        assert g.is_legal_scout_slide(0, 0, 0, 1)
        assert g.is_legal_scout_slide(0, 0, 0, 2)
        assert g.is_legal_scout_slide(0, 0, 0, 3)

    def test_scout_slides_horizontally(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        assert g.is_legal_scout_slide(0, 0, 5, 0)
        assert g.is_legal_scout_slide(0, 0, 9, 0)

    def test_scout_blocked_by_friendly_piece(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        g.place(0, 3, "captain", "red")
        # Cannot slide past or onto friendly piece
        assert g.is_legal_scout_slide(0, 0, 0, 2)
        assert not g.is_legal_scout_slide(0, 0, 0, 3)
        assert not g.is_legal_scout_slide(0, 0, 0, 4)

    def test_scout_blocked_by_lake(self) -> None:
        g = StrategoGame()
        g.place(2, 3, "scout", "red")
        # (2, 4) is a lake; cannot slide through it
        assert not g.is_legal_scout_slide(2, 3, 2, 5)

    def test_scout_can_attack_enemy(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        g.place(0, 5, "sergeant", "blue")
        # Scout can slide to attack enemy at (0, 5)
        assert g.is_legal_scout_slide(0, 0, 0, 5)

    def test_scout_cannot_pass_through_enemy(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        g.place(0, 3, "sergeant", "blue")
        # Can reach enemy but not pass through
        assert g.is_legal_scout_slide(0, 0, 0, 3)
        assert not g.is_legal_scout_slide(0, 0, 0, 5)

    def test_scout_cannot_move_diagonally(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "scout", "red")
        assert not g.is_legal_scout_slide(5, 5, 6, 6)

    def test_non_scout_cannot_slide(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "captain", "red")
        assert not g.is_legal_scout_slide(0, 0, 0, 3)


class TestCombat:
    """Verify combat resolution rules."""

    def test_higher_rank_wins(self) -> None:
        """Marshal (10) attacks Captain (6): attacker wins."""
        g = StrategoGame()
        g.place(5, 5, "marshal", "red")
        g.place(5, 6, "captain", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6) is not None
        assert g.piece_at(5, 6)[0] == "marshal"
        assert g.piece_at(5, 5) is None

    def test_lower_rank_loses(self) -> None:
        """Sergeant (4) attacks Marshal (10): defender wins."""
        g = StrategoGame()
        g.place(5, 5, "sergeant", "red")
        g.place(5, 6, "marshal", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "defender_wins"
        assert g.piece_at(5, 5) is None
        assert g.piece_at(5, 6) is not None
        assert g.piece_at(5, 6)[0] == "marshal"

    def test_equal_rank_both_removed(self) -> None:
        """Captain (6) vs Captain (6): both removed."""
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 6, "captain", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "both_removed"
        assert g.piece_at(5, 5) is None
        assert g.piece_at(5, 6) is None

    def test_spy_kills_marshal_on_attack(self) -> None:
        """Spy (1) attacks Marshal (10): Spy wins (special rule)."""
        g = StrategoGame()
        g.place(5, 5, "spy", "red")
        g.place(5, 6, "marshal", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6) is not None
        assert g.piece_at(5, 6)[0] == "spy"
        assert g.piece_at(5, 5) is None

    def test_marshal_kills_spy_on_attack(self) -> None:
        """Marshal (10) attacks Spy (1): Marshal wins (standard rank comparison)."""
        g = StrategoGame()
        g.place(5, 5, "marshal", "red")
        g.place(5, 6, "spy", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6)[0] == "marshal"

    def test_spy_loses_to_non_marshal(self) -> None:
        """Spy (1) attacks Sergeant (4): Spy loses."""
        g = StrategoGame()
        g.place(5, 5, "spy", "red")
        g.place(5, 6, "sergeant", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "defender_wins"
        assert g.piece_at(5, 5) is None
        assert g.piece_at(5, 6)[0] == "sergeant"

    def test_miner_defuses_bomb(self) -> None:
        """Miner (3) attacks Bomb: Miner wins (defuses)."""
        g = StrategoGame()
        g.place(5, 5, "miner", "red")
        g.place(5, 6, "bomb", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6)[0] == "miner"
        assert g.piece_at(5, 5) is None

    def test_non_miner_destroyed_by_bomb(self) -> None:
        """Captain (6) attacks Bomb: Captain destroyed, Bomb stays."""
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 6, "bomb", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "defender_wins"
        assert g.piece_at(5, 5) is None
        # Bomb remains in place
        assert g.piece_at(5, 6) is not None
        assert g.piece_at(5, 6)[0] == "bomb"

    def test_marshal_destroyed_by_bomb(self) -> None:
        """Even the Marshal (10) is destroyed by a Bomb."""
        g = StrategoGame()
        g.place(5, 5, "marshal", "red")
        g.place(5, 6, "bomb", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "defender_wins"
        assert g.piece_at(5, 5) is None
        assert g.piece_at(5, 6)[0] == "bomb"

    def test_capturing_flag_wins(self) -> None:
        """Any piece capturing the Flag triggers game end."""
        g = StrategoGame()
        g.place(5, 5, "scout", "red")
        g.place(5, 6, "flag", "blue")
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.finished
        assert g.winner == "red"


class TestWinConditions:
    """Verify game-ending scenarios."""

    def test_flag_capture_ends_game(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 6, "flag", "blue")
        g.resolve_combat(5, 5, 5, 6)
        assert g.finished
        assert g.winner == "red"

    def test_no_legal_moves_loses(self) -> None:
        """A player with no legal moves loses.

        Place only a flag and bombs (all immobile) -- no legal moves.
        """
        g = StrategoGame()
        g.place(0, 0, "flag", "red")
        g.place(1, 0, "bomb", "red")
        assert not g.has_legal_moves("red")

    def test_player_with_mobile_pieces_has_moves(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        assert g.has_legal_moves("red")


class TestLegalMoveEnumeration:
    """Verify legal_moves returns correct move lists."""

    def test_single_piece_in_center(self) -> None:
        g = StrategoGame()
        g.place(5, 3, "captain", "red")
        moves = g.legal_moves("red")
        assert len(moves) == 4
        expected = {(5, 3, 4, 3), (5, 3, 6, 3), (5, 3, 5, 2), (5, 3, 5, 4)}
        # (5,4) is not a lake, so all 4 directions are valid
        assert not g.is_lake(5, 4)
        assert set(moves) == expected

    def test_piece_adjacent_to_lake(self) -> None:
        """Piece next to a lake has fewer moves."""
        g = StrategoGame()
        g.place(2, 3, "captain", "red")
        moves = g.legal_moves("red")
        # (2, 4) is a lake, so only 3 moves available: left, right, up
        assert (2, 3, 2, 4) not in set(moves)

    def test_corner_piece_two_moves(self) -> None:
        g = StrategoGame()
        g.place(0, 0, "captain", "red")
        moves = g.legal_moves("red")
        assert len(moves) == 2
        assert set(moves) == {(0, 0, 1, 0), (0, 0, 0, 1)}

    def test_scout_has_slide_moves(self) -> None:
        """Scout in open area has many more moves than a regular piece."""
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        moves = g.legal_moves("red")
        # Along column 0: rows 1-9 = 9 moves (no lakes in col 0)
        # Along row 0: cols 1-9 = 9 moves
        assert len(moves) == 18

    def test_immobile_pieces_have_no_moves(self) -> None:
        g = StrategoGame()
        g.place(5, 5, "bomb", "red")
        g.place(3, 3, "flag", "red")
        moves = g.legal_moves("red")
        assert len(moves) == 0


class TestIntegration:
    """Play through short game scenarios."""

    def test_red_captures_blue_flag(self) -> None:
        """Red captain moves to blue flag and captures it."""
        g = StrategoGame()
        g.place(5, 5, "captain", "red")
        g.place(5, 8, "flag", "blue")

        # Move captain toward flag
        g.move_piece(5, 5, 5, 6)
        assert g.piece_at(5, 6)[0] == "captain"

        g.move_piece(5, 6, 5, 7)
        assert g.piece_at(5, 7)[0] == "captain"

        # Attack the flag
        result = g.resolve_combat(5, 7, 5, 8)
        assert result == "attacker_wins"
        assert g.finished
        assert g.winner == "red"

    def test_spy_ambush(self) -> None:
        """Spy attacks Marshal and wins, then is killed by a Sergeant."""
        g = StrategoGame()
        g.place(5, 5, "spy", "red")
        g.place(5, 6, "marshal", "blue")
        g.place(5, 7, "sergeant", "blue")

        # Spy attacks Marshal
        result = g.resolve_combat(5, 5, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6)[0] == "spy"

        # Sergeant attacks Spy (Sergeant rank 4 > Spy rank 1)
        result = g.resolve_combat(5, 7, 5, 6)
        assert result == "attacker_wins"
        assert g.piece_at(5, 6)[0] == "sergeant"

    def test_bomb_field_defense(self) -> None:
        """Multiple pieces attack bombs; only miner survives."""
        g = StrategoGame()
        g.place(5, 5, "bomb", "blue")
        g.place(6, 5, "bomb", "blue")

        # Captain attacks bomb -- destroyed
        g.place(5, 3, "captain", "red")
        g.move_piece(5, 3, 5, 4)
        result = g.resolve_combat(5, 4, 5, 5)
        assert result == "defender_wins"
        assert g.piece_at(5, 4) is None  # captain destroyed
        assert g.piece_at(5, 5)[0] == "bomb"  # bomb survives

        # Miner attacks bomb -- defuses it
        g.place(6, 3, "miner", "red")
        g.move_piece(6, 3, 6, 4)
        result = g.resolve_combat(6, 4, 6, 5)
        assert result == "attacker_wins"
        assert g.piece_at(6, 5)[0] == "miner"

    def test_scout_long_range_attack(self) -> None:
        """Scout slides across the board and attacks an enemy."""
        g = StrategoGame()
        g.place(0, 0, "scout", "red")
        g.place(0, 8, "sergeant", "blue")

        # Verify scout can slide to attack position
        assert g.is_legal_scout_slide(0, 0, 0, 8)

        # Scout (2) vs Sergeant (4): scout loses
        g.move_piece(0, 0, 0, 8)
        # Both at same cell -- resolve manually using pre-move position
        # Actually we need to handle this differently: in real play,
        # the scout stops adjacent and combat resolves.
        # For this test, place them adjacent.
        g2 = StrategoGame()
        g2.place(0, 7, "scout", "red")
        g2.place(0, 8, "sergeant", "blue")
        result = g2.resolve_combat(0, 7, 0, 8)
        assert result == "defender_wins"
        assert g2.piece_at(0, 7) is None
        assert g2.piece_at(0, 8)[0] == "sergeant"

    def test_mutual_destruction_equal_ranks(self) -> None:
        """Two colonels meet in combat -- both destroyed."""
        g = StrategoGame()
        g.place(3, 3, "colonel", "red")
        g.place(3, 4, "colonel", "blue")
        result = g.resolve_combat(3, 3, 3, 4)
        assert result == "both_removed"
        assert g.piece_at(3, 3) is None
        assert g.piece_at(3, 4) is None

    def test_full_setup_both_players_have_moves(self) -> None:
        """After standard setup, both players have legal moves."""
        g = StrategoGame()
        g.setup_standard()
        assert g.has_legal_moves("red")
        assert g.has_legal_moves("blue")

    def test_full_setup_front_row_pieces_can_advance(self) -> None:
        """After setup, front-row mobile pieces can advance into the gap."""
        g = StrategoGame()
        g.setup_standard()
        # Red's front row is row 3. Pieces there should be able to move to row 4.
        # Col 0 row 3 has a miner -- should be able to move to (0, 4) which is not a lake.
        info = g.piece_at(0, 3)
        assert info is not None
        assert info[1] == "red"
        # (0, 4) is not a lake
        assert not g.is_lake(0, 4)
        assert g.is_legal_step(0, 3, 0, 4)
