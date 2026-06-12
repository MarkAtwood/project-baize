"""Tests for Scrabble: tile placement word game on a 15x15 premium-square board.

2-player Scrabble. 100 letter tiles (98 letters + 2 blanks) drawn from a hidden
bag into 7-tile private racks. Players place words on the board, exchange tiles,
or pass. Scoring: letter values multiplied by premium squares (double/triple
letter/word). First word must cross center (7,7). Word validation via WASM.

Premium square layout follows the standard Scrabble board:
  - 8 triple word squares (corners + mid-edges)
  - 16 double word squares (diagonals) + center star
  - 12 triple letter squares
  - 24 double letter squares
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentId,
    CounterZone,
    GameSession,
    GridZone,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "scrabble.json"


def _load_scrabble() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Standard Scrabble premium square positions (col, row) — 0-indexed
# ---------------------------------------------------------------------------

TRIPLE_WORD = {
    (0, 0), (7, 0), (14, 0),
    (0, 7), (14, 7),
    (0, 14), (7, 14), (14, 14),
}

DOUBLE_WORD = {
    (1, 1), (2, 2), (3, 3), (4, 4),
    (10, 4), (11, 3), (12, 2), (13, 1),
    (1, 13), (2, 12), (3, 11), (4, 10),
    (10, 10), (11, 11), (12, 12), (13, 13),
}

CENTER_STAR = {(7, 7)}

TRIPLE_LETTER = {
    (5, 1), (9, 1),
    (1, 5), (5, 5), (9, 5), (13, 5),
    (1, 9), (5, 9), (9, 9), (13, 9),
    (5, 13), (9, 13),
}

DOUBLE_LETTER = {
    (3, 0), (11, 0),
    (6, 2), (8, 2),
    (0, 3), (7, 3), (14, 3),
    (2, 6), (6, 6), (8, 6), (12, 6),
    (3, 7), (11, 7),
    (2, 8), (6, 8), (8, 8), (12, 8),
    (0, 11), (7, 11), (14, 11),
    (6, 12), (8, 12),
    (3, 14), (11, 14),
}

ALL_PREMIUM = TRIPLE_WORD | DOUBLE_WORD | CENTER_STAR | TRIPLE_LETTER | DOUBLE_LETTER


# ---------------------------------------------------------------------------
# Scoring oracle — independent of engine, used to cross-validate
# ---------------------------------------------------------------------------

# Standard letter point values
LETTER_POINTS: dict[str, int] = {
    "A": 1, "B": 3, "C": 3, "D": 2, "E": 1, "F": 4, "G": 2, "H": 4,
    "I": 1, "J": 8, "K": 5, "L": 1, "M": 3, "N": 1, "O": 1, "P": 3,
    "Q": 10, "R": 1, "S": 1, "T": 1, "U": 1, "V": 4, "W": 4, "X": 8,
    "Y": 4, "Z": 10, " ": 0,
}

# Standard tile distribution
TILE_DISTRIBUTION: dict[str, int] = {
    "A": 9, "B": 2, "C": 2, "D": 4, "E": 12, "F": 2, "G": 3, "H": 2,
    "I": 9, "J": 1, "K": 1, "L": 4, "M": 2, "N": 6, "O": 8, "P": 2,
    "Q": 1, "R": 6, "S": 4, "T": 6, "U": 4, "V": 2, "W": 2, "X": 1,
    "Y": 2, "Z": 1, " ": 2,
}


def score_word(
    letters: list[str],
    positions: list[tuple[int, int]],
    premiums_used: set[tuple[int, int]] | None = None,
) -> int:
    """Score a word given letters and their board positions.

    premiums_used: positions where the premium has already been consumed.
    """
    if premiums_used is None:
        premiums_used = set()

    word_multiplier = 1
    total = 0
    for letter, pos in zip(letters, positions):
        pts = LETTER_POINTS.get(letter, 0)
        if pos not in premiums_used:
            if pos in DOUBLE_LETTER:
                pts *= 2
            elif pos in TRIPLE_LETTER:
                pts *= 3
            if pos in DOUBLE_WORD or pos in CENTER_STAR:
                word_multiplier *= 2
            elif pos in TRIPLE_WORD:
                word_multiplier *= 3
        total += pts
    return total * word_multiplier


# ---------------------------------------------------------------------------
# Tests: definition loading and schema validation
# ---------------------------------------------------------------------------


class TestScrabbleDefinition:
    """The Scrabble game definition loads and passes schema validation."""

    def test_loads_from_file(self) -> None:
        defn = _load_scrabble()
        assert defn.game.name == "Scrabble"

    def test_imperfect_information(self) -> None:
        defn = _load_scrabble()
        assert defn.game.information == "imperfect"

    def test_two_players(self) -> None:
        defn = _load_scrabble()
        assert defn.game.players == ["P1", "P2"]


# ---------------------------------------------------------------------------
# Tests: board zone
# ---------------------------------------------------------------------------


class TestScrabbleBoard:
    """The board is a 15x15 grid with correct premium square cell properties."""

    def test_board_dimensions(self) -> None:
        defn = _load_scrabble()
        board_zone = defn.zones["board"]
        assert board_zone.dimensions == [15, 15]

    def test_board_is_grid(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["board"].zone_type == "grid"

    def test_board_is_public(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["board"].visibility == "public"

    def test_board_stacking_limit_in_definition(self) -> None:
        """stacking_limit is declared in the JSON; runtime GridZone enforces it."""
        raw = json.loads(_GAME_PATH.read_text())
        assert raw["zones"]["board"]["stacking_limit"] == 1

    def test_board_labels(self) -> None:
        defn = _load_scrabble()
        board = defn.zones["board"]
        assert board.labels is not None
        assert board.labels.files is not None
        assert len(board.labels.files) == 15
        assert board.labels.ranks is not None
        assert len(board.labels.ranks) == 15


# ---------------------------------------------------------------------------
# Tests: premium squares
# ---------------------------------------------------------------------------


class TestPremiumSquares:
    """All 61 premium squares are defined with correct cell_properties."""

    def test_total_premium_count(self) -> None:
        """Board has exactly 61 premium squares (8 TW + 17 DW/center + 12 TL + 24 DL)."""
        defn = _load_scrabble()
        board = defn.zones["board"]
        assert board.cell_properties is not None
        assert len(board.cell_properties) == 61

    def test_triple_word_squares(self) -> None:
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        for col, row in TRIPLE_WORD:
            key = f"{col},{row}"
            assert key in props, f"Missing triple word at {key}"
            assert props[key]["premium"] == "triple_word"

    def test_double_word_squares(self) -> None:
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        for col, row in DOUBLE_WORD:
            key = f"{col},{row}"
            assert key in props, f"Missing double word at {key}"
            assert props[key]["premium"] == "double_word"

    def test_center_star(self) -> None:
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        assert props["7,7"]["premium"] == "center_star"

    def test_triple_letter_squares(self) -> None:
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        for col, row in TRIPLE_LETTER:
            key = f"{col},{row}"
            assert key in props, f"Missing triple letter at {key}"
            assert props[key]["premium"] == "triple_letter"

    def test_double_letter_squares(self) -> None:
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        for col, row in DOUBLE_LETTER:
            key = f"{col},{row}"
            assert key in props, f"Missing double letter at {key}"
            assert props[key]["premium"] == "double_letter"

    def test_premium_symmetry(self) -> None:
        """Standard Scrabble board has 4-fold rotational symmetry.
        For every premium at (c,r), (14-c,r), (c,14-r), (14-c,14-r) exist."""
        defn = _load_scrabble()
        props = defn.zones["board"].cell_properties
        assert props is not None
        for key, val in props.items():
            col, row = (int(x) for x in key.split(","))
            premium = val["premium"]
            for c2, r2 in [
                (14 - col, row),
                (col, 14 - row),
                (14 - col, 14 - row),
            ]:
                sym_key = f"{c2},{r2}"
                assert sym_key in props, (
                    f"Symmetry violation: ({col},{row}) is {premium} "
                    f"but ({c2},{r2}) is missing"
                )
                assert props[sym_key]["premium"] == premium, (
                    f"Symmetry violation: ({col},{row}) is {premium} "
                    f"but ({c2},{r2}) is {props[sym_key]['premium']}"
                )

    def test_no_overlapping_premium_positions(self) -> None:
        """Each premium position belongs to exactly one category."""
        all_positions = list(TRIPLE_WORD) + list(DOUBLE_WORD) + list(CENTER_STAR) + \
                        list(TRIPLE_LETTER) + list(DOUBLE_LETTER)
        assert len(all_positions) == len(set(all_positions)), "Duplicate premium positions"


# ---------------------------------------------------------------------------
# Tests: tile bag zone
# ---------------------------------------------------------------------------


class TestTileBag:
    """The tile bag is a hidden ordered stack holding 100 tiles."""

    def test_tile_bag_type(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["tile_bag"].zone_type == "ordered_stack"

    def test_tile_bag_capacity(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["tile_bag"].capacity == 100

    def test_tile_bag_hidden(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["tile_bag"].visibility == "hidden"


# ---------------------------------------------------------------------------
# Tests: rack zone
# ---------------------------------------------------------------------------


class TestRack:
    """Each player has a private 7-tile rack."""

    def test_rack_type(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["rack"].zone_type == "set"

    def test_rack_per_player(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["rack"].per_player is True

    def test_rack_capacity(self) -> None:
        defn = _load_scrabble()
        assert defn.zones["rack"].capacity == 7

    def test_rack_private(self) -> None:
        defn = _load_scrabble()
        vis = defn.zones["rack"].visibility
        assert vis == {"private": "owner"} or (
            hasattr(vis, "private") and vis.private == "owner"
        )


# ---------------------------------------------------------------------------
# Tests: components
# ---------------------------------------------------------------------------


class TestLetterTiles:
    """Letter tiles reference the registry and have correct count."""

    def test_tile_count(self) -> None:
        defn = _load_scrabble()
        assert defn.components["letter_tile"].count == 100

    def test_tile_registry_reference(self) -> None:
        defn = _load_scrabble()
        assert defn.components["letter_tile"].registry == "standard:letter-tiles-english"

    def test_tile_facing(self) -> None:
        defn = _load_scrabble()
        assert defn.components["letter_tile"].facing == "face_down"


# ---------------------------------------------------------------------------
# Tests: turn order
# ---------------------------------------------------------------------------


class TestTurnOrder:
    """Alternating turn order, one action per turn."""

    def test_alternating(self) -> None:
        defn = _load_scrabble()
        assert defn.turn_order.type == "alternating"

    def test_player_order(self) -> None:
        defn = _load_scrabble()
        assert defn.turn_order.players == ["P1", "P2"]

    def test_actions_per_turn(self) -> None:
        defn = _load_scrabble()
        assert defn.turn_order.actions_per_turn == 1

    def test_mandatory_turn(self) -> None:
        defn = _load_scrabble()
        assert defn.turn_order.mandatory is True


# ---------------------------------------------------------------------------
# Tests: authority declarations
# ---------------------------------------------------------------------------


class TestAuthority:
    """Server-only, client-verifiable, and WASM-required operations."""

    def test_server_only_includes_shuffle(self) -> None:
        defn = _load_scrabble()
        assert "shuffle(tile_bag)" in defn.authority.server_only

    def test_server_only_includes_draw(self) -> None:
        defn = _load_scrabble()
        assert "draw(tile_bag, rack)" in defn.authority.server_only

    def test_wasm_required_includes_word_validation(self) -> None:
        defn = _load_scrabble()
        assert defn.authority.wasm_required is not None
        assert "word_validation" in defn.authority.wasm_required

    def test_wasm_required_includes_cross_word(self) -> None:
        defn = _load_scrabble()
        assert defn.authority.wasm_required is not None
        assert "cross_word_validation" in defn.authority.wasm_required

    def test_wasm_required_includes_scoring(self) -> None:
        defn = _load_scrabble()
        assert defn.authority.wasm_required is not None
        assert "scoring_calculation" in defn.authority.wasm_required

    def test_client_verifiable_includes_place(self) -> None:
        defn = _load_scrabble()
        assert "place_word(tiles, positions)" in defn.authority.client_verifiable


# ---------------------------------------------------------------------------
# Tests: end conditions
# ---------------------------------------------------------------------------


class TestEndConditions:
    """Game ends when tiles exhausted or consecutive zero-score turns."""

    def test_has_tiles_exhausted_condition(self) -> None:
        defn = _load_scrabble()
        names = [ec.name for ec in defn.end_conditions]
        assert "tiles_exhausted" in names

    def test_has_consecutive_zero_condition(self) -> None:
        defn = _load_scrabble()
        names = [ec.name for ec in defn.end_conditions]
        assert "consecutive_zero_score_turns" in names

    def test_has_draw_condition(self) -> None:
        defn = _load_scrabble()
        results = [ec.result for ec in defn.end_conditions]
        assert "draw" in results


# ---------------------------------------------------------------------------
# Tests: runtime session creation
# ---------------------------------------------------------------------------


class TestScrabbleSession:
    """A GameSession can be created from the Scrabble definition."""

    def test_session_creates(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        assert session is not None

    def test_board_zone_is_grid(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GridZone)

    def test_board_grid_size(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.width == 15
        assert board.height == 15

    def test_board_starts_empty(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        for r in range(15):
            for c in range(15):
                assert board.grid_get(c, r) is None

    def test_cell_properties_loaded_at_runtime(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.get_cell_property(0, 0, "premium") == "triple_word"
        assert board.get_cell_property(7, 7, "premium") == "center_star"
        assert board.get_cell_property(5, 1, "premium") == "triple_letter"
        assert board.get_cell_property(3, 0, "premium") == "double_letter"

    def test_non_premium_cell_has_no_property(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.get_cell_property(1, 0, "premium") is None

    def test_tile_bag_zone_exists(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        assert "tile_bag" in session.runtime.zones
        assert isinstance(session.runtime.zones["tile_bag"], StackZone)

    def test_per_player_rack_exists(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        for player_name in ["P1", "P2"]:
            player = session.runtime.players[player_name]
            assert "rack" in player.zones

    def test_per_player_score_exists(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        for player_name in ["P1", "P2"]:
            player = session.runtime.players[player_name]
            assert "score" in player.counters or "score" in player.zones

    def test_current_player_starts_p1(self) -> None:
        defn = _load_scrabble()
        session = GameSession(defn)
        assert session.current_player() == "P1"


# ---------------------------------------------------------------------------
# Tests: scoring oracle (independent of engine)
# ---------------------------------------------------------------------------


class TestScoringOracle:
    """Independent scoring oracle produces correct results."""

    def test_tile_distribution_sums_to_100(self) -> None:
        assert sum(TILE_DISTRIBUTION.values()) == 100

    def test_simple_word_no_premium(self) -> None:
        # CAT at (1,0), (2,0), (3,0) — but (3,0) is double_letter
        # Actually test on non-premium squares
        # Place at row 6: (4,6), (5,6), (6,6) — (6,6) is double_letter
        # Use row 1 cols 2,3,4 — (2,1) no premium, (3,1) no premium, (4,1) no premium
        letters = ["C", "A", "T"]
        positions = [(2, 1), (3, 1), (4, 1)]
        # C=3, A=1, T=1 = 5
        assert score_word(letters, positions) == 5

    def test_double_letter_premium(self) -> None:
        # Place H at (3,0) which is double_letter
        letters = ["H"]
        positions = [(3, 0)]
        # H=4, doubled = 8
        assert score_word(letters, positions) == 8

    def test_triple_letter_premium(self) -> None:
        # Place Q at (5,1) which is triple_letter
        letters = ["Q"]
        positions = [(5, 1)]
        # Q=10, tripled = 30
        assert score_word(letters, positions) == 30

    def test_double_word_premium(self) -> None:
        # CAT crossing (1,1) which is double_word
        # (1,1)=C, (2,1)=A, (3,1)=T — (1,1) is DW
        letters = ["C", "A", "T"]
        positions = [(1, 1), (2, 1), (3, 1)]
        # C=3, A=1, T=1 = 5, doubled = 10
        assert score_word(letters, positions) == 10

    def test_triple_word_premium(self) -> None:
        # Place GO at (0,0) which is triple_word
        letters = ["G", "O"]
        positions = [(0, 0), (1, 0)]
        # G=2, O=1 = 3, tripled = 9
        assert score_word(letters, positions) == 9

    def test_center_star_doubles(self) -> None:
        # First word crossing center (7,7)
        letters = ["H", "E", "L", "L", "O"]
        positions = [(7, 5), (7, 6), (7, 7), (7, 8), (7, 9)]
        # H=4, E=1, L=1, L=1, O=1 = 8
        # (7,7) is center_star => word doubled = 16
        assert score_word(letters, positions) == 16

    def test_premiums_already_used(self) -> None:
        # Same word as above but premiums already consumed
        letters = ["H", "E", "L", "L", "O"]
        positions = [(7, 5), (7, 6), (7, 7), (7, 8), (7, 9)]
        premiums_used = {(7, 7)}
        # H=4, E=1, L=1, L=1, O=1 = 8 (no multiplier)
        assert score_word(letters, positions, premiums_used) == 8

    def test_blank_tile_scores_zero(self) -> None:
        # Blank representing A
        letters = [" "]
        positions = [(5, 5)]  # triple_letter
        # blank = 0 points, even tripled = 0
        assert score_word(letters, positions) == 0

    def test_bingo_bonus_not_in_score_word(self) -> None:
        """score_word does not include the 50-point bingo bonus; it's added separately."""
        letters = ["S", "C", "R", "A", "B", "L", "E"]
        positions = [(4, 7), (5, 7), (6, 7), (7, 7), (8, 7), (9, 7), (10, 7)]
        base = score_word(letters, positions)
        # S=1,C=3,R=1,A=1,B=3,L=1,E=1 = 11
        # (7,7)=center_star => doubled = 22
        assert base == 22
        # With bingo: 22 + 50 = 72
        assert base + 50 == 72

    def test_multiple_word_multipliers(self) -> None:
        # Word crossing two triple-word squares
        # Row 0: (0,0) TW and (7,0) TW — word spanning cols 0-7
        letters = ["Q", "U", "I", "C", "K", "L", "Y", "S"]
        positions = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0)]
        # Q=10,U=1,I=1,C=3,K=5,L=1,Y=4,S=1
        # (3,0) is DL => C doubled = 6
        # letter sum: 10 + 1 + 1 + 6 + 5 + 1 + 4 + 1 = 29
        # (0,0) TW * (7,0) TW => x9
        # 29 * 9 = 261
        assert score_word(letters, positions) == 261
