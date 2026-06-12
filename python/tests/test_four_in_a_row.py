"""Tests for Four in a Row game.

Win condition note (baize-935.1): The built-in CEL evaluator cannot express
'4 consecutive same-owner cells in a subline' — it lacks integer indexing and
window primitives. The four_in_line condition in the game definition does NOT
fire automatically via the engine's end-condition check. Win tests verify
correct board state using a standalone Python oracle. The draw test uses the
engine result directly, since occupied_count == cell_count IS supported by CEL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession, GridZone
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_game() -> GameDefinition:
    path = Path(__file__).parent.parent.parent / "games" / "four-in-a-row.json"
    return GameDefinition.from_json(path.read_text())


def _drop(session: GameSession, col: int) -> list:
    """Drop the current player's disc into the given column (gravity fills from bottom).

    Scans rows from the bottom (row 5) upward to find the first empty cell,
    then places at that position. Raises ValueError if the column is full.
    """
    zone = session.runtime.zones.get("board")
    assert isinstance(zone, GridZone)
    target_row: int | None = None
    for row in range(zone.height - 1, -1, -1):
        if zone.grid_get(col, row) is None:
            target_row = row
            break
    if target_row is None:
        raise ValueError(f"column {col} is full")
    return apply_action(
        session,
        Action(
            action_type="place",
            component_type="disc",
            to_pos={"zone": "board", "cell": f"{col},{target_row}"},
        ),
    )


def _owner_at(session: GameSession, col: int, row: int) -> str | None:
    """Return the owner of the disc at (col, row), or None if empty."""
    zone = session.runtime.zones.get("board")
    assert isinstance(zone, GridZone)
    cid = zone.grid_get(col, row)
    if cid is None:
        return None
    comp = session.runtime.components.get(cid)
    return comp.owner if comp is not None else None


def _has_four_in_a_row(session: GameSession, player: str) -> bool:
    """Independent oracle: check if player has 4 in a row anywhere on the board.

    Checks all horizontal, vertical, and diagonal 4-cell windows.
    This is the reference oracle used to validate test outcomes;
    it is independent of the engine's end-condition machinery.
    """
    zone = session.runtime.zones.get("board")
    assert isinstance(zone, GridZone)
    w, h = zone.width, zone.height

    def owned(col: int, row: int) -> bool:
        return _owner_at(session, col, row) == player

    # Horizontal windows
    for row in range(h):
        for col in range(w - 3):
            if all(owned(col + i, row) for i in range(4)):
                return True

    # Vertical windows
    for col in range(w):
        for row in range(h - 3):
            if all(owned(col, row + i) for i in range(4)):
                return True

    # Diagonal: top-left to bottom-right
    for col in range(w - 3):
        for row in range(h - 3):
            if all(owned(col + i, row + i) for i in range(4)):
                return True

    # Diagonal: top-right to bottom-left
    for col in range(3, w):
        for row in range(h - 3):
            if all(owned(col - i, row + i) for i in range(4)):
                return True

    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFourInARowPlacement:
    """Verify gravity-based placement: discs land on the lowest empty row."""

    def test_gravity_single_column(self) -> None:
        """Dropping two discs into column 3 stacks them from the bottom up."""
        defn = _load_game()
        session = GameSession(defn)

        # Red drops into col 3 — should land at row 5 (bottom)
        _drop(session, 3)
        assert _owner_at(session, 3, 5) == "Red"

        # Yellow drops into col 3 — should land at row 4
        _drop(session, 3)
        assert _owner_at(session, 3, 4) == "Yellow"

    def test_column_full_raises(self) -> None:
        """Dropping a disc into a full column raises ValueError."""
        defn = _load_game()
        session = GameSession(defn)
        # Fill column 0 (6 rows): alternates Red, Yellow
        for _ in range(6):
            _drop(session, 0)
        with pytest.raises(ValueError, match="column 0 is full"):
            _drop(session, 0)


class TestFourInARowVerticalWin:
    """Verify that 4 discs stacked in a column constitute a vertical win."""

    def test_red_wins_vertical(self) -> None:
        """Red drops 4 into column 2; Yellow drops elsewhere.

        Board after 7 moves (col=2 for Red, col=6 for Yellow):
          Red lands at rows 5,4,3,2 in col 2.
          Yellow lands at rows 5,4,3 in col 6.
        """
        defn = _load_game()
        session = GameSession(defn)

        # Interleave: Red into col 2, Yellow into col 6
        _drop(session, 2)  # Red   -> col2,row5
        _drop(session, 6)  # Yellow-> col6,row5
        _drop(session, 2)  # Red   -> col2,row4
        _drop(session, 6)  # Yellow-> col6,row4
        _drop(session, 2)  # Red   -> col2,row3
        _drop(session, 6)  # Yellow-> col6,row3
        _drop(session, 2)  # Red   -> col2,row2  (4th in column)

        # Verify discs are at the expected positions
        assert _owner_at(session, 2, 5) == "Red"
        assert _owner_at(session, 2, 4) == "Red"
        assert _owner_at(session, 2, 3) == "Red"
        assert _owner_at(session, 2, 2) == "Red"

        # Oracle confirms a vertical four-in-a-row for Red
        assert _has_four_in_a_row(session, "Red")
        assert not _has_four_in_a_row(session, "Yellow")


class TestFourInARowHorizontalWin:
    """Verify that 4 discs in the same row constitute a horizontal win."""

    def test_red_wins_horizontal(self) -> None:
        """Red fills columns 0-3 on the bottom row; Yellow fills col 6 each turn.

        Move sequence:
          Red col0, Yellow col6,
          Red col1, Yellow col6,
          Red col2, Yellow col6,
          Red col3 -> horizontal win on row 5.
        """
        defn = _load_game()
        session = GameSession(defn)

        _drop(session, 0)  # Red   -> col0,row5
        _drop(session, 6)  # Yellow-> col6,row5
        _drop(session, 1)  # Red   -> col1,row5
        _drop(session, 6)  # Yellow-> col6,row4
        _drop(session, 2)  # Red   -> col2,row5
        _drop(session, 6)  # Yellow-> col6,row3
        _drop(session, 3)  # Red   -> col3,row5  (4th in row)

        assert _owner_at(session, 0, 5) == "Red"
        assert _owner_at(session, 1, 5) == "Red"
        assert _owner_at(session, 2, 5) == "Red"
        assert _owner_at(session, 3, 5) == "Red"

        assert _has_four_in_a_row(session, "Red")
        assert not _has_four_in_a_row(session, "Yellow")


def _draw_drop_sequence() -> list[int]:
    """Return a 42-move column sequence that fills the board with no 4-in-a-row.

    Target board (R=Red, Y=Yellow, row 0=top, row 5=bottom):
      col:  0 1 2 3 4 5 6
      row0: R R Y Y R R Y
      row1: Y Y R R Y Y R
      row2: R R Y Y R R Y
      row3: Y Y R R Y Y R
      row4: R R Y Y R R Y
      row5: Y Y R R Y Y R

    Pattern: cell(c,r) = Red if ((c // 2) + r) % 2 == 0, else Yellow.
    Max same-player run in any direction is 2, so no 4-in-a-row can form.

    The sequence is built by a greedy scheduler: at each turn it scans columns
    left-to-right and picks the first column whose lowest-unplaced cell belongs
    to the current player. This schedule was verified to complete all 42 moves
    without deadlock.
    """

    def target_owner(c: int, r: int) -> str:
        return "Red" if ((c // 2) + r) % 2 == 0 else "Yellow"

    col_queues = [
        [target_owner(c, r) for r in range(5, -1, -1)] for c in range(7)
    ]

    players = ["Red", "Yellow"]
    pointers = [0] * 7
    sequence: list[int] = []

    for turn in range(42):
        current = players[turn % 2]
        chosen: int | None = None
        for c in range(7):
            if pointers[c] < 6 and col_queues[c][pointers[c]] == current:
                chosen = c
                break
        assert chosen is not None, (
            f"draw sequence scheduler stuck at turn {turn} for {current}"
        )
        sequence.append(chosen)
        pointers[chosen] += 1

    return sequence


class TestFourInARowDiagonalWin:
    """Verify that 4 discs on a rising diagonal constitute a diagonal win."""

    def test_red_wins_diagonal_rising(self) -> None:
        """Red wins on a rising diagonal (col,row): (0,5),(1,4),(2,3),(3,2).

        Yellow fillers are spread across cols 4, 5, 6 (3 drops each, rows 5,4,3),
        so Yellow never gets 4 consecutive in any direction.

        Move plan (0-indexed turns, Red=even):
          0  Red   col0 -> (0,5)  diagonal cell 1
          1  Yellow col4 -> (4,5)
          2  Red   col1 -> (1,5)  filler under (1,4)
          3  Yellow col4 -> (4,4)
          4  Red   col1 -> (1,4)  diagonal cell 2
          5  Yellow col4 -> (4,3)
          6  Red   col2 -> (2,5)  filler under (2,4)
          7  Yellow col5 -> (5,5)
          8  Red   col2 -> (2,4)  filler under (2,3)
          9  Yellow col5 -> (5,4)
         10  Red   col2 -> (2,3)  diagonal cell 3
         11  Yellow col5 -> (5,3)
         12  Red   col3 -> (3,5)  filler under (3,4)
         13  Yellow col6 -> (6,5)
         14  Red   col3 -> (3,4)  filler under (3,3)
         15  Yellow col6 -> (6,4)
         16  Red   col3 -> (3,3)  filler under (3,2)
         17  Yellow col6 -> (6,3)
         18  Red   col3 -> (3,2)  diagonal cell 4 — winning disc

        Yellow ends with 3 discs each in cols 4, 5, 6 at rows 5,4,3.
        Max Yellow run: 3 in a column or 3 horizontal across cols 4-6 — no 4-in-a-row.
        """
        defn = _load_game()
        session = GameSession(defn)

        moves = [
            0, 4,  # Red (0,5) diag1;  Yellow (4,5)
            1, 4,  # Red (1,5) filler; Yellow (4,4)
            1, 4,  # Red (1,4) diag2;  Yellow (4,3)
            2, 5,  # Red (2,5) filler; Yellow (5,5)
            2, 5,  # Red (2,4) filler; Yellow (5,4)
            2, 5,  # Red (2,3) diag3;  Yellow (5,3)
            3, 6,  # Red (3,5) filler; Yellow (6,5)
            3, 6,  # Red (3,4) filler; Yellow (6,4)
            3, 6,  # Red (3,3) filler; Yellow (6,3)
            3,     # Red (3,2) diag4 — winning disc
        ]
        for col in moves:
            _drop(session, col)

        assert _owner_at(session, 0, 5) == "Red"
        assert _owner_at(session, 1, 4) == "Red"
        assert _owner_at(session, 2, 3) == "Red"
        assert _owner_at(session, 3, 2) == "Red"

        assert _has_four_in_a_row(session, "Red")
        assert not _has_four_in_a_row(session, "Yellow")


class TestFourInARowDraw:
    """Verify the draw condition: board full with no four-in-a-row.

    The engine's CEL evaluator handles occupied_count == cell_count correctly,
    so the draw end-condition fires when the board is full and no win condition
    has triggered (the four_in_line condition is a no-op in the current engine
    per baize-935.1, meaning the board fills completely before the game ends).
    """

    def test_draw_full_board(self) -> None:
        """Fill all 42 cells with no 4-in-a-row; engine declares a draw.

        Uses _draw_drop_sequence() which produces a board where the max run
        of any player in any direction is 2.
        """
        defn = _load_game()
        session = GameSession(defn)

        sequence = _draw_drop_sequence()
        assert len(sequence) == 42

        for col in sequence:
            _drop(session, col)

        assert not _has_four_in_a_row(session, "Red")
        assert not _has_four_in_a_row(session, "Yellow")

        zone = session.runtime.zones.get("board")
        assert isinstance(zone, GridZone)
        assert all(zone.cells[i] is not None for i in range(42))

        assert session.runtime.status == "finished"
        result = session.runtime.result
        assert result is not None
        assert result.outcome == "draw"
        assert result.condition == "board_full"
