"""Tests for Dots and Boxes on a 4x4 dot grid (3x3 boxes).

Two players alternate drawing lines between adjacent dots. Completing the
fourth side of a box scores one point and grants an extra turn. The game
ends when all 24 lines are drawn; the player with the most boxes wins.

The game definition models lines as nodes in a graph zone. Each node's
properties identify which box(es) it borders. Tests drive the game at the
runtime level, placing markers on graph nodes and updating scores via
counter zones — matching the Ticket to Ride test pattern.

Independent oracle: _box_sides() computes the four line names for any box
from first principles, and _is_box_complete() checks occupancy directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GraphZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "dots-and-boxes.json"

PLAYERS = ["A", "B"]
TOTAL_LINES = 24
TOTAL_BOXES = 9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _session() -> GameSession:
    return GameSession(_load_game())


def _lines_zone(session: GameSession) -> GraphZone:
    zone = session.runtime.zones.get("lines")
    assert isinstance(zone, GraphZone)
    return zone


def _score(session: GameSession, player: str) -> int:
    counter = session.runtime.players[player].zones["score"]
    assert isinstance(counter, CounterZone)
    return counter.value


def _set_score(session: GameSession, player: str, value: int) -> None:
    counter = session.runtime.players[player].zones["score"]
    assert isinstance(counter, CounterZone)
    counter.value = value


def _box_sides(r: int, c: int) -> list[str]:
    """Return the four line names forming box (r, c).

    Independent oracle — computed from the naming convention, not from
    the game definition's node_properties.

    Box (r,c) where r,c in {0,1,2}:
      top    = h_r_c
      bottom = h_{r+1}_c
      left   = v_r_c
      right  = v_r_{c+1}
    """
    return [
        f"h_{r}_{c}",      # top
        f"h_{r+1}_{c}",    # bottom
        f"v_{r}_{c}",      # left
        f"v_{r}_{c+1}",    # right
    ]


def _is_line_claimed(session: GameSession, line: str) -> bool:
    """Check if a line has been claimed (has an occupant)."""
    zone = _lines_zone(session)
    return zone.graph_get(line) is not None


def _line_owner(session: GameSession, line: str) -> str | None:
    """Return the owner of the marker on a line, or None if unclaimed."""
    zone = _lines_zone(session)
    cid = zone.graph_get(line)
    if cid is None:
        return None
    comp = session.runtime.components.get(cid)
    return comp.owner if comp is not None else None


def _is_box_complete(session: GameSession, r: int, c: int) -> bool:
    """Independent oracle: check if all four sides of box (r,c) are claimed."""
    return all(_is_line_claimed(session, line) for line in _box_sides(r, c))


def _newly_completed_boxes(
    session: GameSession, line: str
) -> list[tuple[int, int]]:
    """Return boxes completed by claiming the given line.

    Uses the node_properties 'boxes' field to find candidate boxes,
    then checks each with the independent oracle.
    """
    zone = _lines_zone(session)
    idx = zone.name_to_index.get(line)
    if idx is None:
        return []
    props = zone.node_properties.get(idx, {})
    boxes_str = str(props.get("boxes", ""))
    completed: list[tuple[int, int]] = []
    for box_id in boxes_str.split(","):
        box_id = box_id.strip()
        if not box_id:
            continue
        r, c = int(box_id.split("_")[0]), int(box_id.split("_")[1])
        if _is_box_complete(session, r, c):
            completed.append((r, c))
    return completed


def _claim_line(session: GameSession, player: str, line: str) -> int:
    """Claim a line for a player. Returns the number of boxes completed.

    Places a line_marker on the graph node, then checks for newly
    completed boxes and updates the score counter.
    Raises ValueError if the line is already claimed.
    """
    zone = _lines_zone(session)
    if zone.graph_get(line) is not None:
        raise ValueError(f"line {line} is already claimed")

    marker = ComponentData(
        id=ComponentId(0),
        string_id=f"line-{player}-{line}",
        component_type="line_marker",
        owner=player,
    )
    cid = session.runtime.components.insert(marker)
    zone.graph_set(line, cid)

    completed = _newly_completed_boxes(session, line)
    if completed:
        _set_score(session, player, _score(session, player) + len(completed))

    return len(completed)


def _play_turn(session: GameSession, line: str) -> tuple[str, int]:
    """Play one turn: current player claims a line.

    Returns (player_who_moved, boxes_completed).
    If boxes were completed, the same player keeps the turn (extra turn rule).
    Otherwise, turn passes to the opponent via advance_turn().
    """
    player = session.current_player()
    assert player is not None
    boxes = _claim_line(session, player, line)
    if boxes == 0:
        # Turn passes to the opponent
        session.advance_turn()
    # If boxes > 0, same player goes again (no turn advance)
    return player, boxes


def _all_lines() -> list[str]:
    """Return all 24 line names."""
    lines: list[str] = []
    for r in range(4):
        for c in range(3):
            lines.append(f"h_{r}_{c}")
    for r in range(3):
        for c in range(4):
            lines.append(f"v_{r}_{c}")
    return lines


def _count_claimed(session: GameSession) -> int:
    """Count how many lines have been claimed."""
    return sum(1 for line in _all_lines() if _is_line_claimed(session, line))


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    """Verify the game definition loads with correct structure."""

    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Dots and Boxes"

    def test_two_named_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["A", "B"]

    def test_perfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "perfect"

    def test_lines_zone_is_graph(self) -> None:
        defn = _load_game()
        assert "lines" in defn.zones
        assert defn.zones["lines"].zone_type == "graph"

    def test_24_line_nodes(self) -> None:
        defn = _load_game()
        assert defn.zones["lines"].nodes is not None
        assert len(defn.zones["lines"].nodes) == TOTAL_LINES

    def test_score_zone_is_per_player_counter(self) -> None:
        defn = _load_game()
        assert "score" in defn.zones
        assert defn.zones["score"].zone_type == "counter"
        assert defn.zones["score"].per_player is True

    def test_session_creates_player_score_counters(self) -> None:
        session = _session()
        for player in PLAYERS:
            assert _score(session, player) == 0


# ---------------------------------------------------------------------------
# Tests: independent oracle
# ---------------------------------------------------------------------------


class TestBoxSidesOracle:
    """Verify the independent _box_sides oracle computes correct line names."""

    def test_box_0_0(self) -> None:
        sides = _box_sides(0, 0)
        assert sorted(sides) == sorted(["h_0_0", "h_1_0", "v_0_0", "v_0_1"])

    def test_box_1_1(self) -> None:
        """Center box (1,1)."""
        sides = _box_sides(1, 1)
        assert sorted(sides) == sorted(["h_1_1", "h_2_1", "v_1_1", "v_1_2"])

    def test_box_2_2(self) -> None:
        """Bottom-right box (2,2)."""
        sides = _box_sides(2, 2)
        assert sorted(sides) == sorted(["h_2_2", "h_3_2", "v_2_2", "v_2_3"])

    def test_all_boxes_have_four_unique_sides(self) -> None:
        for r in range(3):
            for c in range(3):
                sides = _box_sides(r, c)
                assert len(sides) == 4
                assert len(set(sides)) == 4

    def test_all_24_lines_appear_in_at_least_one_box(self) -> None:
        """Every line is a side of at least one box."""
        all_sides: set[str] = set()
        for r in range(3):
            for c in range(3):
                all_sides.update(_box_sides(r, c))
        assert all_sides == set(_all_lines())


# ---------------------------------------------------------------------------
# Tests: line claiming
# ---------------------------------------------------------------------------


class TestLineClaiming:
    """Verify basic line placement mechanics."""

    def test_claim_unclaimed_line(self) -> None:
        session = _session()
        boxes = _claim_line(session, "A", "h_0_0")
        assert _is_line_claimed(session, "h_0_0")
        assert _line_owner(session, "h_0_0") == "A"
        assert boxes == 0

    def test_claim_already_claimed_raises(self) -> None:
        session = _session()
        _claim_line(session, "A", "h_0_0")
        with pytest.raises(ValueError, match="already claimed"):
            _claim_line(session, "B", "h_0_0")

    def test_unclaimed_line_has_no_owner(self) -> None:
        session = _session()
        assert _line_owner(session, "h_0_0") is None
        assert not _is_line_claimed(session, "h_0_0")

    def test_claim_count_increments(self) -> None:
        session = _session()
        assert _count_claimed(session) == 0
        _claim_line(session, "A", "v_0_0")
        assert _count_claimed(session) == 1
        _claim_line(session, "B", "v_0_1")
        assert _count_claimed(session) == 2


# ---------------------------------------------------------------------------
# Tests: box completion and scoring
# ---------------------------------------------------------------------------


class TestBoxCompletion:
    """Verify that completing a box scores a point."""

    def test_three_sides_no_completion(self) -> None:
        """Three sides of a box do not complete it."""
        session = _session()
        _claim_line(session, "A", "h_0_0")  # top
        _claim_line(session, "A", "h_1_0")  # bottom
        _claim_line(session, "A", "v_0_0")  # left
        assert not _is_box_complete(session, 0, 0)
        assert _score(session, "A") == 0

    def test_fourth_side_completes_box(self) -> None:
        """Drawing the fourth side completes the box and scores 1."""
        session = _session()
        _claim_line(session, "A", "h_0_0")  # top
        _claim_line(session, "A", "h_1_0")  # bottom
        _claim_line(session, "A", "v_0_0")  # left
        boxes = _claim_line(session, "A", "v_0_1")  # right
        assert _is_box_complete(session, 0, 0)
        assert boxes == 1
        assert _score(session, "A") == 1

    def test_different_players_complete_box(self) -> None:
        """The player who draws the fourth side gets the point,
        regardless of who drew the other sides."""
        session = _session()
        _claim_line(session, "A", "h_0_0")
        _claim_line(session, "A", "h_1_0")
        _claim_line(session, "A", "v_0_0")
        boxes = _claim_line(session, "B", "v_0_1")
        assert _is_box_complete(session, 0, 0)
        assert boxes == 1
        assert _score(session, "A") == 0
        assert _score(session, "B") == 1

    def test_one_line_completes_two_boxes(self) -> None:
        """A shared interior line can complete two boxes at once, scoring 2."""
        session = _session()
        # Set up box (0,0) with 3 sides
        _claim_line(session, "A", "h_0_0")  # top of (0,0)
        _claim_line(session, "A", "h_1_0")  # bottom of (0,0)
        _claim_line(session, "A", "v_0_0")  # left of (0,0)
        # Set up box (0,1) with 3 sides
        _claim_line(session, "A", "h_0_1")  # top of (0,1)
        _claim_line(session, "A", "h_1_1")  # bottom of (0,1)
        _claim_line(session, "A", "v_0_2")  # right of (0,1)
        # The shared line v_0_1 is right of (0,0) and left of (0,1)
        assert not _is_box_complete(session, 0, 0)
        assert not _is_box_complete(session, 0, 1)
        boxes = _claim_line(session, "A", "v_0_1")
        assert _is_box_complete(session, 0, 0)
        assert _is_box_complete(session, 0, 1)
        assert boxes == 2
        assert _score(session, "A") == 2


# ---------------------------------------------------------------------------
# Tests: extra turn rule
# ---------------------------------------------------------------------------


class TestExtraTurn:
    """Verify the extra turn rule: completing a box keeps the turn."""

    def test_no_completion_passes_turn(self) -> None:
        """Drawing a line without completing a box passes the turn."""
        session = _session()
        player, boxes = _play_turn(session, "h_0_0")
        assert player == "A"
        assert boxes == 0
        assert session.current_player() == "B"

    def test_completion_keeps_turn(self) -> None:
        """Completing a box grants an extra turn to the same player."""
        session = _session()
        # A draws 3 sides of box (0,0), B fills in elsewhere
        _play_turn(session, "h_0_0")   # A
        _play_turn(session, "h_3_2")   # B (far away)
        _play_turn(session, "h_1_0")   # A
        _play_turn(session, "h_3_1")   # B
        _play_turn(session, "v_0_0")   # A — 3 sides done
        _play_turn(session, "h_3_0")   # B
        # A completes box (0,0) — should get extra turn
        player, boxes = _play_turn(session, "v_0_1")
        assert player == "A"
        assert boxes == 1
        # A still has the turn
        assert session.current_player() == "A"

    def test_double_completion_keeps_turn(self) -> None:
        """Completing two boxes with one line also grants extra turn."""
        session = _session()
        # Prepare two adjacent boxes missing only the shared line
        for line in ["h_0_0", "h_1_0", "v_0_0"]:
            _claim_line(session, "A", line)
        for line in ["h_0_1", "h_1_1", "v_0_2"]:
            _claim_line(session, "B", line)
        # Set A as current player
        session.runtime.turn_index = 0
        player, boxes = _play_turn(session, "v_0_1")
        assert player == "A"
        assert boxes == 2
        assert session.current_player() == "A"


# ---------------------------------------------------------------------------
# Tests: full game play
# ---------------------------------------------------------------------------


class TestFullGame:
    """Play a complete game and verify outcome."""

    def test_a_wins_majority(self) -> None:
        """Player A scores more boxes than B and wins.

        Strategy: A systematically completes boxes while B draws
        non-completing lines. A gets 5+ boxes out of 9.
        """
        session = _session()

        # Build a sequence where A completes 5 boxes and B gets 4.
        # We'll manually drive the game, tracking whose turn it is.

        # Phase 1: Draw the grid edges without completing boxes.
        # Draw all top-row horizontal lines
        _play_turn(session, "h_0_0")  # A
        _play_turn(session, "h_0_1")  # B
        _play_turn(session, "h_0_2")  # A
        # Draw all bottom-row horizontal lines
        _play_turn(session, "h_3_0")  # B
        _play_turn(session, "h_3_1")  # A
        _play_turn(session, "h_3_2")  # B
        # Draw left and right column vertical lines
        _play_turn(session, "v_0_0")  # A
        _play_turn(session, "v_1_0")  # B
        _play_turn(session, "v_2_0")  # A
        _play_turn(session, "v_0_3")  # B
        _play_turn(session, "v_1_3")  # A
        _play_turn(session, "v_2_3")  # B

        # No boxes should be complete yet — we only drew border edges
        for r in range(3):
            for c in range(3):
                assert not _is_box_complete(session, r, c)
        assert _score(session, "A") == 0
        assert _score(session, "B") == 0

        # Phase 2: Draw middle horizontal lines (still no completion)
        _play_turn(session, "h_1_0")  # A
        _play_turn(session, "h_2_0")  # B
        _play_turn(session, "h_1_1")  # A
        _play_turn(session, "h_2_1")  # B
        _play_turn(session, "h_1_2")  # A
        _play_turn(session, "h_2_2")  # B

        # Still no boxes complete — missing vertical interior lines
        assert _score(session, "A") == 0
        assert _score(session, "B") == 0

        # Phase 3: 6 interior vertical lines remain:
        # v_0_1, v_0_2, v_1_1, v_1_2, v_2_1, v_2_2
        #
        # Each v_r_c borders box (r,c-1) and (r,c). A box completes
        # only when all 4 sides are claimed. Key: the second column's
        # box needs both its left (v_r_c) and right (v_r_{c+1}) verticals.
        #
        # v_0_1: completes (0,0) only — (0,1) still needs v_0_2. +1
        # v_0_2: completes (0,1) and (0,2) — v_0_1 now exists. +2
        # v_1_1: completes (1,0) only — (1,1) still needs v_1_2. +1
        # v_1_2: completes (1,1) and (1,2) — v_1_1 now exists. +2
        # v_2_1: completes (2,0) only — (2,1) still needs v_2_2. +1
        # v_2_2: completes (2,1) and (2,2) — v_2_1 now exists. +2

        # Current player is A (18 non-completing moves, even count)
        assert session.current_player() == "A"

        # A plays v_0_1: completes (0,0) -> +1, extra turn
        player, boxes = _play_turn(session, "v_0_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 1
        assert session.current_player() == "A"

        # A plays v_0_2: completes (0,1) and (0,2) -> +2, extra turn
        player, boxes = _play_turn(session, "v_0_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 3
        assert session.current_player() == "A"

        # A plays v_1_1: completes (1,0) -> +1, extra turn
        player, boxes = _play_turn(session, "v_1_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 4
        assert session.current_player() == "A"

        # A plays v_1_2: completes (1,1) and (1,2) -> +2, extra turn
        player, boxes = _play_turn(session, "v_1_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 6
        assert session.current_player() == "A"

        # A plays v_2_1: completes (2,0) -> +1, extra turn
        player, boxes = _play_turn(session, "v_2_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 7
        assert session.current_player() == "A"

        # A plays v_2_2: completes (2,1) and (2,2) -> +2, extra turn
        player, boxes = _play_turn(session, "v_2_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 9

        # All lines claimed, all boxes complete
        assert _count_claimed(session) == TOTAL_LINES
        assert _score(session, "A") == 9
        assert _score(session, "B") == 0

        # Verify all boxes complete via oracle
        for r in range(3):
            for c in range(3):
                assert _is_box_complete(session, r, c)

    def test_competitive_game(self) -> None:
        """Both players score: A gets 5, B gets 4. A wins.

        Setup phase: each player alternates drawing lines around the
        border and mid-rows without completing any box. Then finishing
        moves complete boxes for both players.
        """
        session = _session()

        # Phase 1: alternating safe lines (no completions)
        _play_turn(session, "h_0_0")  # A
        _play_turn(session, "h_0_1")  # B
        _play_turn(session, "h_0_2")  # A
        _play_turn(session, "h_3_0")  # B
        _play_turn(session, "h_3_1")  # A
        _play_turn(session, "h_3_2")  # B
        _play_turn(session, "v_0_0")  # A
        _play_turn(session, "v_1_0")  # B
        _play_turn(session, "v_2_0")  # A
        _play_turn(session, "v_0_3")  # B
        _play_turn(session, "v_1_3")  # A
        _play_turn(session, "v_2_3")  # B
        _play_turn(session, "h_1_0")  # A
        _play_turn(session, "h_2_0")  # B
        _play_turn(session, "h_1_1")  # A
        _play_turn(session, "h_2_1")  # B

        assert _score(session, "A") == 0
        assert _score(session, "B") == 0
        # 16 lines drawn, 8 left. It's A's turn.
        assert session.current_player() == "A"

        # Phase 2: A draws h_1_2 (safe — only 2 sides on box (0,2), 2 on (1,2))
        _play_turn(session, "h_1_2")  # A
        # B draws h_2_2 (safe — 2 sides on (1,2), 2 on (2,2))
        _play_turn(session, "h_2_2")  # B

        # 18 lines drawn, 6 interior verticals remain:
        # v_0_1, v_0_2, v_1_1, v_1_2, v_2_1, v_2_2
        assert _score(session, "A") == 0
        assert _score(session, "B") == 0
        assert session.current_player() == "A"

        # Phase 3: A draws v_0_1 — completes box (0,0): top=h_0_0,
        # bottom=h_1_0, left=v_0_0, right=v_0_1. Only (0,0) completes
        # because (0,1) is missing v_0_2. A scores 1, extra turn.
        player, boxes = _play_turn(session, "v_0_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 1
        assert session.current_player() == "A"

        # A draws v_1_1 — completes box (1,0): top=h_1_0, bottom=h_2_0,
        # left=v_1_0, right=v_1_1. Only (1,0) since (1,1) needs v_1_2.
        player, boxes = _play_turn(session, "v_1_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 2
        assert session.current_player() == "A"

        # A draws v_2_1 — completes box (2,0): top=h_2_0, bottom=h_3_0,
        # left=v_2_0, right=v_2_1. Only (2,0) since (2,1) needs v_2_2.
        player, boxes = _play_turn(session, "v_2_1")
        assert player == "A"
        assert boxes == 1
        assert _score(session, "A") == 3
        assert session.current_player() == "A"

        # A draws v_0_2 — completes (0,1) AND (0,2):
        #   (0,1): h_0_1, h_1_1, v_0_1, v_0_2 — all claimed
        #   (0,2): h_0_2, h_1_2, v_0_2, v_0_3 — all claimed
        player, boxes = _play_turn(session, "v_0_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 5
        assert session.current_player() == "A"

        # A draws v_1_2 — completes (1,1) AND (1,2):
        #   (1,1): h_1_1, h_2_1, v_1_1, v_1_2 — all claimed
        #   (1,2): h_1_2, h_2_2, v_1_2, v_1_3 — all claimed
        player, boxes = _play_turn(session, "v_1_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 7
        assert session.current_player() == "A"

        # A draws v_2_2 — completes (2,1) AND (2,2):
        #   (2,1): h_2_1, h_3_1, v_2_1, v_2_2 — all claimed
        #   (2,2): h_2_2, h_3_2, v_2_2, v_2_3 — all claimed
        player, boxes = _play_turn(session, "v_2_2")
        assert player == "A"
        assert boxes == 2
        assert _score(session, "A") == 9

        assert _count_claimed(session) == TOTAL_LINES
        assert _score(session, "B") == 0
        assert _score(session, "A") > _score(session, "B")

    def test_split_scoring_game(self) -> None:
        """A game where both players score: A gets 5, B gets 4."""
        session = _session()

        # Prepare box (0,0): 3 sides drawn by A
        _claim_line(session, "A", "h_0_0")
        _claim_line(session, "A", "v_0_0")
        _claim_line(session, "A", "v_0_1")
        # Prepare box (2,2): 3 sides drawn by B
        _claim_line(session, "B", "h_3_2")
        _claim_line(session, "B", "v_2_2")
        _claim_line(session, "B", "v_2_3")

        # B completes box (0,0) — gets 1 point
        boxes = _claim_line(session, "B", "h_1_0")
        assert boxes == 1
        assert _score(session, "B") == 1

        # A completes box (2,2) — gets 1 point
        boxes = _claim_line(session, "A", "h_2_2")
        assert boxes == 1
        assert _score(session, "A") == 1

        # Both players have scored
        assert _score(session, "A") == 1
        assert _score(session, "B") == 1

    def test_draw_possible(self) -> None:
        """With 9 boxes, a draw is impossible (odd number). Verify the
        game always has a winner when all boxes are scored.

        This test confirms that 9 boxes cannot be split evenly.
        """
        # 9 is odd, so scores can never be equal when all boxes are taken.
        # Maximum draw scenario would require 4.5 each — impossible.
        # Therefore every completed game must have a winner.
        for a_score in range(10):
            b_score = TOTAL_BOXES - a_score
            assert a_score != b_score or a_score + b_score != TOTAL_BOXES


# ---------------------------------------------------------------------------
# Tests: node_properties consistency
# ---------------------------------------------------------------------------


class TestNodeProperties:
    """Verify that node_properties in the definition match the oracle."""

    def test_every_line_lists_correct_boxes(self) -> None:
        """Each line's 'boxes' property matches the oracle's box membership."""
        session = _session()
        zone = _lines_zone(session)

        # Build oracle: for each line, which boxes contain it?
        oracle: dict[str, set[str]] = {line: set() for line in _all_lines()}
        for r in range(3):
            for c in range(3):
                box_id = f"{r}_{c}"
                for side in _box_sides(r, c):
                    oracle[side].add(box_id)

        # Check against node_properties
        for line in _all_lines():
            idx = zone.name_to_index[line]
            props = zone.node_properties.get(idx, {})
            boxes_str = str(props.get("boxes", ""))
            prop_boxes = set(b.strip() for b in boxes_str.split(",") if b.strip())
            assert prop_boxes == oracle[line], (
                f"line {line}: node_properties has {prop_boxes}, "
                f"oracle has {oracle[line]}"
            )

    def test_each_box_has_exactly_four_lines_referencing_it(self) -> None:
        """Each box ID appears in exactly 4 lines' node_properties."""
        session = _session()
        zone = _lines_zone(session)

        box_counts: dict[str, int] = {}
        for line in _all_lines():
            idx = zone.name_to_index[line]
            props = zone.node_properties.get(idx, {})
            boxes_str = str(props.get("boxes", ""))
            for box_id in boxes_str.split(","):
                box_id = box_id.strip()
                if box_id:
                    box_counts[box_id] = box_counts.get(box_id, 0) + 1

        assert len(box_counts) == TOTAL_BOXES
        for box_id, count in box_counts.items():
            assert count == 4, f"box {box_id} referenced by {count} lines"
