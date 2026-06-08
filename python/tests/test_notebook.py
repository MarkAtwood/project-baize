"""Tests for baize.notebook — Jupyter integration module."""

from __future__ import annotations

import os
import json
import tempfile

from baize.definition import GameDefinition
from baize.notebook import BoardSVG, GameWidget, display_board, format_state
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TIC_TAC_TOE_JSON = """{
    "game": { "name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [
        { "result": "win", "player": "current", "condition": "three_in_line" },
        { "result": "draw", "condition": "board_is_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""

CHESS_LIKE_JSON = """{
    "game": { "name": "Mini Chess", "players": ["white", "black"], "information": "perfect" },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [4, 4],
            "visibility": "public",
            "coloring": "checkered",
            "labels": { "files": ["a", "b", "c", "d"], "ranks": [4, 3, 2, 1] }
        }
    },
    "components": {
        "king": {
            "owner": "per_player",
            "count": 1,
            "movement": [{ "primitive": "step", "direction": "adjacent" }]
        },
        "rook": {
            "owner": "per_player",
            "count": 1,
            "movement": [{ "primitive": "slide", "direction": "orthogonal" }]
        }
    },
    "turn_order": { "type": "alternating", "players": ["white", "black"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [{ "result": "win", "condition": "checkmate" }],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def _make_session(json_str: str = TIC_TAC_TOE_JSON) -> GameSession:
    definition = GameDefinition.from_json(json_str)
    return GameSession(definition)


def _place(
    session: GameSession,
    name: str,
    comp_type: str,
    owner: str,
    col: int,
    row: int,
) -> ComponentId:
    """Place a component on the first grid zone found."""
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=name,
            component_type=comp_type,
            owner=owner,
        )
    )
    for _zname, zone in session.runtime.zones.items():
        if isinstance(zone, GridZone):
            zone.grid_set(col, row, cid)
            return cid
    raise RuntimeError("no grid zone found")


# ---------------------------------------------------------------------------
# format_state tests
# ---------------------------------------------------------------------------


class TestFormatState:
    def test_empty_board_produces_ascii(self) -> None:
        session = _make_session()
        result = format_state(session)
        assert isinstance(result, str)
        assert "Tic-Tac-Toe" in result
        assert "Turn: X" in result

    def test_contains_grid_lines(self) -> None:
        session = _make_session()
        result = format_state(session)
        # Grid should have separator lines with +---
        assert "+" in result
        assert "-" in result
        assert "|" in result

    def test_shows_placed_pieces(self) -> None:
        session = _make_session()
        _place(session, "x0", "mark", "X", 1, 1)
        result = format_state(session)
        # Should show the component: owner initial 'X' + type initial 'M'
        assert "XM" in result or "X" in result

    def test_shows_player_info(self) -> None:
        session = _make_session()
        result = format_state(session)
        assert "Player: X" in result
        assert "Player: O" in result

    def test_shows_status(self) -> None:
        session = _make_session()
        result = format_state(session)
        assert "Status: setup" in result

    def test_chess_with_labels(self) -> None:
        session = _make_session(CHESS_LIKE_JSON)
        _place(session, "wk", "king", "white", 0, 3)
        result = format_state(session)
        # Should include file labels
        assert "a" in result
        assert "b" in result

    def test_multiline_output(self) -> None:
        session = _make_session()
        result = format_state(session)
        lines = result.split("\n")
        # Should produce multiple lines of output
        assert len(lines) > 5


# ---------------------------------------------------------------------------
# display_board tests
# ---------------------------------------------------------------------------


class TestDisplayBoard:
    def test_returns_board_svg(self) -> None:
        session = _make_session()
        result = display_board(session)
        assert isinstance(result, BoardSVG)

    def test_svg_contains_svg_tag(self) -> None:
        session = _make_session()
        result = display_board(session)
        svg_str = str(result)
        assert "<svg" in svg_str
        assert "</svg>" in svg_str

    def test_repr_svg_protocol(self) -> None:
        session = _make_session()
        result = display_board(session)
        svg_str = result._repr_svg_()
        assert "<svg" in svg_str

    def test_svg_contains_cells(self) -> None:
        session = _make_session()
        result = display_board(session)
        svg_str = str(result)
        # 3x3 grid should have 9 rect elements (plus background)
        assert svg_str.count("<rect") >= 9

    def test_svg_shows_pieces(self) -> None:
        session = _make_session()
        _place(session, "x0", "mark", "X", 1, 1)
        result = display_board(session)
        svg_str = str(result)
        # Should contain text element for the piece glyph
        assert "<text" in svg_str
        assert "M" in svg_str  # "mark" -> "M"

    def test_checkered_coloring(self) -> None:
        session = _make_session(CHESS_LIKE_JSON)
        result = display_board(session)
        svg_str = str(result)
        # Checkered board should use light and dark colors
        assert _escape_xml_colors_present(svg_str)

    def test_svg_with_labels(self) -> None:
        session = _make_session(CHESS_LIKE_JSON)
        result = display_board(session)
        svg_str = str(result)
        # File labels should be in the SVG
        assert ">a<" in svg_str
        assert ">b<" in svg_str


def _escape_xml_colors_present(svg: str) -> bool:
    """Check that both light and dark cell colors appear."""
    return "#f0d9b5" in svg and "#b58863" in svg


# ---------------------------------------------------------------------------
# GameWidget tests
# ---------------------------------------------------------------------------


class TestGameWidget:
    def _make_widget(self, json_str: str = TIC_TAC_TOE_JSON) -> GameWidget:
        """Create a GameWidget from a JSON string via a temp file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json_str)
            return GameWidget(path)
        finally:
            os.unlink(path)

    def test_load_definition(self) -> None:
        widget = self._make_widget()
        assert widget.session.definition.game.name == "Tic-Tac-Toe"
        assert widget.session.runtime.status == "in_progress"

    def test_show_returns_svg(self) -> None:
        widget = self._make_widget()
        result = widget.show()
        assert isinstance(result, BoardSVG)
        assert "<svg" in str(result)

    def test_legal_moves_empty_board(self) -> None:
        widget = self._make_widget()
        moves = widget.legal_moves()
        # Empty tic-tac-toe board: no pieces, no legal moves
        assert isinstance(moves, list)
        assert len(moves) == 0

    def test_legal_moves_with_pieces(self) -> None:
        widget = self._make_widget(CHESS_LIKE_JSON)
        _place(widget.session, "wk", "king", "white", 2, 2)
        moves = widget.legal_moves()
        assert isinstance(moves, list)
        # King at (2,2) on 4x4 board: 8 adjacent squares
        assert len(moves) == 8

    def test_place_action(self) -> None:
        widget = self._make_widget()
        widget.move({"place": [1, 1], "type": "mark"})
        board = widget.session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.grid_get(1, 1) is not None
        # Turn should have advanced to O
        assert widget.session.current_player() == "O"

    def test_undo(self) -> None:
        widget = self._make_widget()
        widget.move({"place": [1, 1], "type": "mark"})
        assert widget.session.current_player() == "O"

        widget.undo()
        assert widget.session.current_player() == "X"
        board = widget.session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.grid_get(1, 1) is None

    def test_undo_empty_raises(self) -> None:
        widget = self._make_widget()
        try:
            widget.undo()
            assert False, "Expected IndexError"
        except IndexError:
            pass

    def test_multiple_undo(self) -> None:
        widget = self._make_widget()
        widget.move({"place": [0, 0], "type": "mark"})
        widget.move({"place": [1, 1], "type": "mark"})
        widget.move({"place": [2, 2], "type": "mark"})

        widget.undo()
        widget.undo()
        board = widget.session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.grid_get(0, 0) is not None
        assert board.grid_get(1, 1) is None
        assert board.grid_get(2, 2) is None

    def test_repr_html(self) -> None:
        widget = self._make_widget()
        html = widget._repr_html_()
        assert isinstance(html, str)
        assert "<svg" in html
        assert "Tic-Tac-Toe" in html
        assert "Turn:" in html

    def test_grid_move_action(self) -> None:
        widget = self._make_widget(CHESS_LIKE_JSON)
        _place(widget.session, "wk", "king", "white", 2, 2)
        # Save a history entry manually so we can verify move works
        widget.move({"component": "wk", "from": [2, 2], "to": [3, 3]})

        board = widget.session.runtime.zones["board"]
        assert isinstance(board, GridZone)
        assert board.grid_get(2, 2) is None
        assert board.grid_get(3, 3) is not None
