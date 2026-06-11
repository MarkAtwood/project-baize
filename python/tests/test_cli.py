"""Tests for the terminal client rendering and command parsing."""

from baize.cli import parse_move, render_grid, render_status


class TestRenderGrid:
    def test_empty_board(self) -> None:
        state = {"zones": {"board": {"cells": {}}}}
        output = render_grid(state)
        assert "[board]" in output
        assert "." in output

    def test_tic_tac_toe_board(self) -> None:
        state = {
            "zones": {
                "board": {
                    "cells": {
                        "0,0": {"component_type": "mark", "owner": "X"},
                        "1,1": {"component_type": "mark", "owner": "O"},
                    }
                }
            }
        }
        output = render_grid(state)
        assert "X" in output
        assert "O" in output
        assert "." in output

    def test_chess_pieces(self) -> None:
        state = {
            "zones": {
                "board": {
                    "cells": {
                        "4,0": {"component_type": "king", "owner": "white"},
                        "4,7": {"component_type": "king", "owner": "black"},
                    }
                }
            }
        }
        output = render_grid(state)
        assert "K" in output  # white king
        assert "k" in output  # black king

    def test_no_grid_zones(self) -> None:
        output = render_grid({"zones": {}})
        assert "no grid" in output


class TestRenderStatus:
    def test_in_progress(self) -> None:
        state = {"status": "in_progress", "turn": "X", "sequence": 3}
        output = render_status(state, "X")
        assert "your turn" in output
        assert "X" in output

    def test_not_your_turn(self) -> None:
        state = {"status": "in_progress", "turn": "O", "sequence": 3}
        output = render_status(state, "X")
        assert "your turn" not in output

    def test_game_over(self) -> None:
        state = {
            "status": "finished",
            "result": {"outcome": "win", "winner": "X", "condition": "three_in_a_row"},
        }
        output = render_status(state, "X")
        assert "GAME OVER" in output
        assert "X wins" in output


class TestParseMove:
    def test_place(self) -> None:
        action = parse_move("place mark 1,1")
        assert action is not None
        assert action["action_type"] == "place"
        assert action["component_type"] == "mark"
        assert action["to"]["cell"] == "1,1"

    def test_move(self) -> None:
        action = parse_move("move 0,0 1,1")
        assert action is not None
        assert action["action_type"] == "move_piece"

    def test_pass(self) -> None:
        action = parse_move("pass")
        assert action is not None
        assert action["action_type"] == "pass"

    def test_resign(self) -> None:
        action = parse_move("resign")
        assert action is not None
        assert action["action_type"] == "resign"

    def test_flip(self) -> None:
        action = parse_move("flip card-1")
        assert action is not None
        assert action["action_type"] == "flip"
        assert action["component_id"] == "card-1"

    def test_remove(self) -> None:
        action = parse_move("remove pawn-0")
        assert action is not None
        assert action["action_type"] == "remove"

    def test_empty_returns_none(self) -> None:
        assert parse_move("") is None

    def test_unknown_returns_none(self) -> None:
        assert parse_move("dance") is None
