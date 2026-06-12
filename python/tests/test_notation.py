"""Tests for the notation adapter module.

Exercises coordinate mapping, special-move lookup, piece-symbol parsing,
move formatting, and plain-coordinate placement using synthetic game
definitions built from the real dataclasses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from baize.action import Action
from baize.definition import (
    Authority,
    EndCondition,
    GameDefinition,
    GameMetadata,
    GridLabels,
    TurnOrder,
    Zone,
)
from baize.notation import (
    coords_to_label,
    format_move,
    label_to_coords,
    parse_move,
    parse_special_move,
)

_GAMES_DIR = Path(__file__).resolve().parents[2] / "games"


def _load_game_def(filename: str) -> GameDefinition:
    """Load a game definition JSON file from the games directory."""
    import json

    path = _GAMES_DIR / filename
    raw = json.loads(path.read_text())
    return GameDefinition._from_dict(raw)


# ---------------------------------------------------------------------------
# Fixtures: chess-like labels, notation dict, and minimal GameDefinition
# ---------------------------------------------------------------------------

CHESS_LABELS = GridLabels(
    files=["a", "b", "c", "d", "e", "f", "g", "h"],
    ranks=[1, 2, 3, 4, 5, 6, 7, 8],
)

CHESS_NOTATION: dict = {
    "piece_symbols": {
        "king": "K",
        "queen": "Q",
        "rook": "R",
        "bishop": "B",
        "knight": "N",
        "pawn": "",
    },
    "capture_marker": "x",
    "promotion_marker": "=",
    "check_marker": "+",
    "checkmate_marker": "#",
    "special_moves": {
        "O-O": {"action_type": "castle", "side": "kingside"},
        "O-O-O": {"action_type": "castle", "side": "queenside"},
    },
}

TTT_LABELS = GridLabels(
    files=["a", "b", "c"],
    ranks=[1, 2, 3],
)


def _make_chess_def() -> GameDefinition:
    """Minimal chess-like GameDefinition with labels and notation."""
    return GameDefinition(
        game=GameMetadata(name="Chess", players=["white", "black"]),
        zones={
            "board": Zone(
                zone_type="grid",
                visibility="public",
                dimensions=[8, 8],
                labels=CHESS_LABELS,
            ),
        },
        components={},
        turn_order=TurnOrder(type="alternating", players=["white", "black"]),
        end_conditions=[
            EndCondition(result="win", condition="checkmate"),
        ],
        authority=Authority(server_only=[], client_verifiable=["all"]),
        notation=CHESS_NOTATION,
    )


def _make_ttt_def() -> GameDefinition:
    """Minimal tic-tac-toe GameDefinition with labels, no notation spec."""
    return GameDefinition(
        game=GameMetadata(name="Tic-Tac-Toe", players=["X", "O"]),
        zones={
            "board": Zone(
                zone_type="grid",
                visibility="public",
                dimensions=[3, 3],
                labels=TTT_LABELS,
            ),
        },
        components={},
        turn_order=TurnOrder(type="alternating", players=["X", "O"]),
        end_conditions=[
            EndCondition(result="win", condition="three_in_a_row"),
        ],
        authority=Authority(server_only=[], client_verifiable=["all"]),
    )


def _make_no_labels_def() -> GameDefinition:
    """GameDefinition with no grid labels at all."""
    return GameDefinition(
        game=GameMetadata(name="Plain", players=["A", "B"]),
        zones={
            "board": Zone(
                zone_type="grid",
                visibility="public",
                dimensions=[5, 5],
            ),
        },
        components={},
        turn_order=TurnOrder(type="alternating", players=["A", "B"]),
        end_conditions=[
            EndCondition(result="draw", condition="board_full"),
        ],
        authority=Authority(server_only=[], client_verifiable=["all"]),
    )


# ===================================================================
# TestLabelMapping
# ===================================================================


class TestLabelMapping:
    """Layer 1: grid label coordinate mapping."""

    def test_coords_to_label_e4(self) -> None:
        assert coords_to_label(4, 3, CHESS_LABELS) == "e4"

    def test_coords_to_label_a1(self) -> None:
        assert coords_to_label(0, 0, CHESS_LABELS) == "a1"

    def test_label_to_coords_e4(self) -> None:
        assert label_to_coords("e4", CHESS_LABELS) == (4, 3)

    def test_label_to_coords_a1(self) -> None:
        assert label_to_coords("a1", CHESS_LABELS) == (0, 0)

    def test_label_to_coords_invalid(self) -> None:
        assert label_to_coords("z9", CHESS_LABELS) is None


# ===================================================================
# TestSpecialMoves
# ===================================================================


class TestSpecialMoves:
    """Special-move lookup from notation dict."""

    def test_castle_kingside(self) -> None:
        result = parse_special_move("O-O", CHESS_NOTATION)
        assert result == {"action_type": "castle", "side": "kingside"}

    def test_castle_queenside(self) -> None:
        result = parse_special_move("O-O-O", CHESS_NOTATION)
        assert result == {"action_type": "castle", "side": "queenside"}

    def test_not_special(self) -> None:
        result = parse_special_move("e4", CHESS_NOTATION)
        assert result is None


# ===================================================================
# TestParsePieceNotation
# ===================================================================


class TestParsePieceNotation:
    """Layer 2: piece-symbol notation parsing through parse_move."""

    def test_pawn_e4(self) -> None:
        defn = _make_chess_def()
        action = parse_move("e4", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.to_pos == {"col": 4, "row": 3}
        assert action.component_type == "pawn"

    def test_knight_f3(self) -> None:
        defn = _make_chess_def()
        action = parse_move("Nf3", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.to_pos == {"col": 5, "row": 2}
        assert action.component_type == "knight"

    def test_bishop_capture_e5(self) -> None:
        defn = _make_chess_def()
        action = parse_move("Bxe5", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.to_pos == {"col": 4, "row": 4}
        assert action.component_type == "bishop"
        assert action.custom_data is not None
        assert action.custom_data["capture"] is True

    def test_pawn_promotion(self) -> None:
        defn = _make_chess_def()
        action = parse_move("e8=Q", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.to_pos == {"col": 4, "row": 7}
        assert action.component_type == "pawn"
        assert action.promote_to == "queen"

    def test_castle_via_parse_move(self) -> None:
        defn = _make_chess_def()
        action = parse_move("O-O", defn)
        assert action is not None
        assert action.action_type == "castle"
        assert action.side == "kingside"


# ===================================================================
# TestFormatMove
# ===================================================================


class TestFormatMove:
    """Formatting Action objects back to notation strings."""

    def test_format_simple_coordinate(self) -> None:
        defn = _make_chess_def()
        action = Action(
            action_type="move_piece",
            to_pos={"col": 4, "row": 3},
            component_type="pawn",
        )
        result = format_move(action, defn)
        assert result == "e4"

    def test_format_special_move(self) -> None:
        defn = _make_chess_def()
        action = Action(action_type="castle", side="kingside")
        result = format_move(action, defn)
        assert result == "O-O"

    def test_round_trip_preserves_destination(self) -> None:
        defn = _make_chess_def()
        original = "Nf3"
        action = parse_move(original, defn)
        assert action is not None
        formatted = format_move(action, defn)
        # Destination must be preserved: "f3" appears in the output
        assert formatted.endswith("f3")
        # Round-trip should reproduce the notation exactly
        assert formatted == "Nf3"


# ===================================================================
# TestPlainCoordinates
# ===================================================================


class TestPlainCoordinates:
    """Plain coordinate placement (no piece-symbol notation)."""

    def test_ttt_b2(self) -> None:
        defn = _make_ttt_def()
        action = parse_move("b2", defn)
        assert action is not None
        assert action.action_type == "place"
        assert action.to_pos == {"col": 1, "row": 1}
        assert action.zone == "board"

    def test_no_labels_uses_comma_format(self) -> None:
        defn = _make_no_labels_def()
        action = parse_move("2,3", defn)
        assert action is not None
        assert action.action_type == "place"
        assert action.to_pos == {"col": 2, "row": 3}


# ===================================================================
# TestChessSAN — Standard Algebraic Notation via actual chess.json
# ===================================================================


class TestChessSAN:
    """Chess Standard Algebraic Notation: parse and format using chess.json."""

    @staticmethod
    def _load_chess_def() -> GameDefinition:
        """Load the real chess.json game definition."""
        import json
        from pathlib import Path

        chess_path = Path(__file__).resolve().parents[2] / "games" / "chess.json"
        raw = json.loads(chess_path.read_text())
        return GameDefinition._from_dict(raw)

    def test_parse_pawn_e4(self) -> None:
        """Parse 'e4' -> pawn move to e4 (col 4, row 3)."""
        defn = self._load_chess_def()
        action = parse_move("e4", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.component_type == "pawn"
        assert action.to_pos == {"col": 4, "row": 3}

    def test_parse_knight_f3(self) -> None:
        """Parse 'Nf3' -> knight move to f3 (col 5, row 2)."""
        defn = self._load_chess_def()
        action = parse_move("Nf3", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.component_type == "knight"
        assert action.to_pos == {"col": 5, "row": 2}

    def test_parse_castle_kingside(self) -> None:
        """Parse 'O-O' -> castle kingside."""
        defn = self._load_chess_def()
        action = parse_move("O-O", defn)
        assert action is not None
        assert action.action_type == "castle"
        assert action.side == "kingside"

    def test_parse_castle_queenside(self) -> None:
        """Parse 'O-O-O' -> castle queenside."""
        defn = self._load_chess_def()
        action = parse_move("O-O-O", defn)
        assert action is not None
        assert action.action_type == "castle"
        assert action.side == "queenside"

    def test_parse_bishop_capture_e5(self) -> None:
        """Parse 'Bxe5' -> bishop capture at e5."""
        defn = self._load_chess_def()
        action = parse_move("Bxe5", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.component_type == "bishop"
        assert action.to_pos == {"col": 4, "row": 4}
        assert action.custom_data is not None
        assert action.custom_data["capture"] is True

    def test_parse_pawn_promotion(self) -> None:
        """Parse 'e8=Q' -> pawn promotion to queen."""
        defn = self._load_chess_def()
        action = parse_move("e8=Q", defn)
        assert action is not None
        assert action.action_type == "move_piece"
        assert action.component_type == "pawn"
        assert action.to_pos == {"col": 4, "row": 7}
        assert action.promote_to == "queen"

    def test_format_coords_e4(self) -> None:
        """Format coordinates (4, 3) -> 'e4'."""
        defn = self._load_chess_def()
        zone_def = defn.zones["board"]
        assert zone_def.labels is not None
        result = coords_to_label(4, 3, zone_def.labels)
        assert result == "e4"

    def test_chess_json_has_notation_block(self) -> None:
        """Load actual chess.json and verify notation block is present."""
        defn = self._load_chess_def()
        assert defn.notation is not None
        assert "piece_symbols" in defn.notation
        assert defn.notation["piece_symbols"]["knight"] == "N"
        assert defn.notation["piece_symbols"]["pawn"] == ""
        assert defn.notation["capture_marker"] == "x"
        assert defn.notation["promotion_marker"] == "="
        assert defn.notation["check_marker"] == "+"
        assert defn.notation["checkmate_marker"] == "#"
        assert "O-O" in defn.notation["special_moves"]
        assert "O-O-O" in defn.notation["special_moves"]


# ===================================================================
# TestGoNotation — Go notation via actual go.json
# ===================================================================


class TestGoNotation:
    """Go notation: stone placement with pass and resign special moves."""

    def test_go_json_has_notation_block(self) -> None:
        """Load go.json and verify notation block exists with expected keys."""
        defn = _load_game_def("go.json")
        assert defn.notation is not None
        assert "piece_symbols" in defn.notation
        assert defn.notation["piece_symbols"]["stone"] == ""
        assert "pass" in defn.notation["special_moves"]
        assert "resign" in defn.notation["special_moves"]

    def test_parse_pass(self) -> None:
        """Parse 'pass' -> pass action."""
        defn = _load_game_def("go.json")
        action = parse_move("pass", defn)
        assert action is not None
        assert action.action_type == "pass"

    def test_parse_resign(self) -> None:
        """Parse 'resign' -> resign action."""
        defn = _load_game_def("go.json")
        action = parse_move("resign", defn)
        assert action is not None
        assert action.action_type == "resign"


# ===================================================================
# TestTicTacToeNotation — Tic-Tac-Toe notation via actual tic-tac-toe.json
# ===================================================================


class TestTicTacToeNotation:
    """Tic-Tac-Toe notation: coordinate-based placement with labels."""

    def test_ttt_json_loads(self) -> None:
        """Load tic-tac-toe.json and verify notation block exists."""
        defn = _load_game_def("tic-tac-toe.json")
        assert defn.notation is not None
        assert "special_moves" in defn.notation

    def test_ttt_parse_coordinate(self) -> None:
        """Parse 'b2' -> place at col 1, row 1 using labels."""
        defn = _load_game_def("tic-tac-toe.json")
        action = parse_move("b2", defn)
        assert action is not None
        assert action.action_type == "place"
        assert action.to_pos == {"col": 1, "row": 1}
        assert action.zone == "board"


# ===================================================================
# TestCubeNotation — Rubik's Cube Singmaster notation via rubiks-cube.json
# ===================================================================


class TestCubeNotation:
    """Rubik's Cube Singmaster notation: face turns as special moves."""

    def test_cube_json_has_notation_block(self) -> None:
        """Load rubiks-cube.json and verify notation block with all 18 moves."""
        defn = _load_game_def("rubiks-cube.json")
        assert defn.notation is not None
        specials = defn.notation["special_moves"]
        assert len(specials) == 18
        for face in ("U", "D", "L", "R", "F", "B"):
            assert face in specials
            assert f"{face}'" in specials
            assert f"{face}2" in specials

    def test_parse_u(self) -> None:
        """Parse 'U' -> custom action with move_name 'U'."""
        defn = _load_game_def("rubiks-cube.json")
        action = parse_move("U", defn)
        assert action is not None
        assert action.action_type == "custom"
        assert action.custom_data is not None
        assert action.custom_data["move_name"] == "U"

    def test_parse_r_prime(self) -> None:
        """Parse "R'" -> custom action with move_name 'R_prime'."""
        defn = _load_game_def("rubiks-cube.json")
        action = parse_move("R'", defn)
        assert action is not None
        assert action.action_type == "custom"
        assert action.custom_data is not None
        assert action.custom_data["move_name"] == "R_prime"


# ===================================================================
# TestBackgammonNotation
# ===================================================================


class TestBackgammonNotation:
    """Backgammon notation: move_separator, hit_marker, special moves."""

    @staticmethod
    def _load_backgammon_def() -> GameDefinition:
        import json

        raw = json.loads((_GAMES_DIR / "backgammon.json").read_text())
        return GameDefinition._from_dict(raw)

    def test_notation_block_exists(self) -> None:
        """Load backgammon.json and verify notation block is present."""
        defn = self._load_backgammon_def()
        assert defn.notation is not None
        assert defn.notation["move_separator"] == "/"
        assert defn.notation["hit_marker"] == "*"
        assert "bar" in defn.notation["special_moves"]
        assert "off" in defn.notation["special_moves"]

    def test_parse_special_move_bar(self) -> None:
        """'bar' maps to enter action from bar zone."""
        defn = self._load_backgammon_def()
        result = parse_special_move("bar", defn.notation)
        assert result == {"action_type": "enter", "from": "bar"}

    def test_parse_special_move_off(self) -> None:
        """'off' maps to bear_off action."""
        defn = self._load_backgammon_def()
        result = parse_special_move("off", defn.notation)
        assert result == {"action_type": "bear_off"}


# ===================================================================
# TestTileKingdomsNotation
# ===================================================================


class TestTileKingdomsNotation:
    """Tile Kingdoms (Carcassonne-style) notation: pass special move."""

    @staticmethod
    def _load_tile_kingdoms_def() -> GameDefinition:
        import json

        raw = json.loads((_GAMES_DIR / "tile-kingdoms.json").read_text())
        return GameDefinition._from_dict(raw)

    def test_notation_block_exists(self) -> None:
        """Load tile-kingdoms.json and verify notation block is present."""
        defn = self._load_tile_kingdoms_def()
        assert defn.notation is not None
        assert "pass" in defn.notation["special_moves"]

    def test_parse_special_move_pass(self) -> None:
        """'pass' maps to pass action."""
        defn = self._load_tile_kingdoms_def()
        result = parse_special_move("pass", defn.notation)
        assert result == {"action_type": "pass"}
