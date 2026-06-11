"""Full-game integration tests: play complete games and verify outcomes."""

import json
from pathlib import Path

from baize.action import Action
from baize.cel import try_eval_end_condition
from baize.definition import GameDefinition
from baize.perturber import execute_effect
from baize.runtime import GameSession
from baize.transition import apply_action


def _load_ttt() -> GameDefinition:
    path = Path(__file__).parent.parent.parent / "games" / "tic-tac-toe.json"
    return GameDefinition.from_json(path.read_text())


def _place(col: int, row: int) -> Action:
    return Action(
        action_type="place",
        component_type="mark",
        to_pos={"zone": "board", "cell": f"{col},{row}"},
    )


# ===================================================================
# TestTicTacToeFullGame
# ===================================================================


class TestTicTacToeFullGame:
    """Play complete tic-tac-toe games through the engine."""

    def test_x_wins_top_row(self) -> None:
        """X fills row 0 (the top row) and wins."""
        defn = _load_ttt()
        session = GameSession(defn)

        # X at (0,0)
        apply_action(session, _place(0, 0))
        # O at (0,1)
        apply_action(session, _place(0, 1))
        # X at (1,0)
        apply_action(session, _place(1, 0))
        # O at (1,1)
        apply_action(session, _place(1, 1))
        # X at (2,0) — completes row 0
        events = apply_action(session, _place(2, 0))

        assert session.runtime.status == "finished"
        result = session.runtime.result
        assert result is not None
        assert result.outcome == "win"
        assert result.winner == "X"
        assert result.condition == "three_in_a_row"

        # Verify a game_end event was emitted
        end_events = [e for e in events if e.event_type == "game_end"]
        assert len(end_events) == 1

    def test_draw_full_board(self) -> None:
        """Fill all 9 cells with no winning line — game ends in a draw.

        Board layout (col, row):
            col0  col1  col2
        row0:  X     O     X
        row1:  O     X     X
        row2:  O     X     O
        """
        defn = _load_ttt()
        session = GameSession(defn)

        moves = [
            (0, 0),  # X
            (1, 0),  # O
            (2, 0),  # X
            (0, 1),  # O
            (1, 1),  # X
            (0, 2),  # O
            (2, 1),  # X
            (2, 2),  # O
            (1, 2),  # X — fills the board
        ]
        for col, row in moves:
            apply_action(session, _place(col, row))

        assert session.runtime.status == "finished"
        result = session.runtime.result
        assert result is not None
        assert result.outcome == "draw"

    def test_resign(self) -> None:
        """X places one mark, then O resigns. Game should be finished."""
        defn = _load_ttt()
        session = GameSession(defn)

        # X places a mark
        apply_action(session, _place(0, 0))

        # O resigns (it's now O's turn after X placed)
        apply_action(session, Action(action_type="resign"))

        assert session.runtime.status == "finished"


# ===================================================================
# TestPerturberIntegration
# ===================================================================


class TestPerturberIntegration:
    """Perturber effects mutate game state correctly."""

    def test_counter_effects_during_game(self) -> None:
        """set_counter then add_counter updates the counter value."""
        defn = _load_ttt()
        session = GameSession(defn)
        session.runtime.status = "in_progress"

        # Set a counter to 10
        execute_effect(session, {"set_counter": {"counter": "score", "value": 10}})
        assert session.runtime.counters["score"] == 10

        # Add 5 to it
        execute_effect(session, {"add_counter": {"counter": "score", "value": 5}})
        assert session.runtime.counters["score"] == 15

        # Sequence of effects
        execute_effect(
            session,
            {
                "sequence": [
                    {"set_counter": {"counter": "bonus", "value": 3}},
                    {"add_counter": {"counter": "bonus", "value": 7}},
                ]
            },
        )
        assert session.runtime.counters["bonus"] == 10

    def test_repeat_until_stable_fixpoint(self) -> None:
        """repeat_until_stable with an idempotent set_counter terminates immediately."""
        defn = _load_ttt()
        session = GameSession(defn)
        session.runtime.status = "in_progress"

        # Set counter to 42, then repeat_until_stable setting same value.
        # The set is idempotent, so the hash should not change after the
        # first iteration, causing the loop to terminate.
        execute_effect(session, {"set_counter": {"counter": "fixed", "value": 42}})

        execute_effect(
            session,
            {
                "repeat_until_stable": {
                    "fuel": 100,
                    "apply": {"set_counter": {"counter": "fixed", "value": 42}},
                }
            },
        )

        assert session.runtime.counters["fixed"] == 42


# ===================================================================
# TestCELComposableExpressions
# ===================================================================


class TestCELComposableExpressions:
    """CEL expression evaluation for end-condition detection."""

    def test_cel_lines_win_detection(self) -> None:
        """Evaluate the tic-tac-toe win condition CEL expression directly."""
        # Simulate a board where X owns the entire first row
        variables: dict[str, object] = {
            "current_player": "X",
            "lines": [
                ["X", "X", "X"],  # row 0 — all X
                ["", "", ""],
                ["", "", ""],
                # columns
                ["X", "", ""],
                ["X", "", ""],
                ["X", "", ""],
                # diagonals
                ["X", "", ""],
                ["X", "", ""],
            ],
        }

        result = try_eval_end_condition(
            variables,
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        assert result is True

    def test_cel_occupied_count(self) -> None:
        """Evaluate the draw condition: occupied_count == cell_count."""
        variables: dict[str, object] = {
            "occupied_count": 9,
            "cell_count": 9,
        }

        result = try_eval_end_condition(variables, "occupied_count == cell_count")
        assert result is True

        # Not full yet
        variables_partial: dict[str, object] = {
            "occupied_count": 7,
            "cell_count": 9,
        }
        result_partial = try_eval_end_condition(
            variables_partial, "occupied_count == cell_count"
        )
        assert result_partial is False
