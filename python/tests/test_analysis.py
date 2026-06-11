"""Tests for baize.analysis — game analysis tools."""

from __future__ import annotations

import json
from pathlib import Path

from baize.action import Action
from baize.analysis import (
    branching_factor,
    complexity_profile,
    find_shortest_game,
    game_tree_depth,
    hidden_info_ratio,
    replay_game,
)
from baize.definition import GameDefinition
from baize.runtime import GameSession


GAMES_DIR = Path(__file__).resolve().parent.parent.parent / "games"


def _load_definition(name: str) -> GameDefinition:
    path = GAMES_DIR / f"{name}.json"
    return GameDefinition.from_json(path.read_text())


# ---------------------------------------------------------------------------
# branching_factor
# ---------------------------------------------------------------------------


def test_branching_factor_tictactoe_start() -> None:
    """Tic-tac-toe starts with 9 empty cells, so branching factor is 9."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    assert branching_factor(session) == 9


def test_branching_factor_after_one_move() -> None:
    """After one placement, tic-tac-toe has 8 empty cells."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    action = Action(
        action_type="place",
        component_type="mark",
        to_pos={"zone": "board", "cell": "1,1"},
    )
    from baize.transition import apply_action

    apply_action(session, action)
    assert branching_factor(session) == 8


# ---------------------------------------------------------------------------
# hidden_info_ratio
# ---------------------------------------------------------------------------


def test_hidden_info_ratio_tictactoe() -> None:
    """Tic-tac-toe has all public zones, so ratio is 0.0."""
    defn = _load_definition("tic-tac-toe")
    assert hidden_info_ratio(defn) == 0.0


def test_hidden_info_ratio_poker() -> None:
    """Texas Hold'em has hidden and private zones, so ratio > 0."""
    defn = _load_definition("texas-holdem")
    ratio = hidden_info_ratio(defn)
    assert ratio > 0.0
    # 6 zones total: deck(hidden), community(public), hand(private),
    # pot(public), player_chips(public), discard(hidden)
    # hidden/private = 3, total = 6, ratio = 0.5
    assert ratio == 0.5


# ---------------------------------------------------------------------------
# replay_game
# ---------------------------------------------------------------------------


def test_replay_game_short_sequence() -> None:
    """Replay 3 placements and verify we get 3 intermediate states."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    actions = [
        Action(
            action_type="place",
            component_type="mark",
            to_pos={"zone": "board", "cell": "0,0"},
        ),
        Action(
            action_type="place",
            component_type="mark",
            to_pos={"zone": "board", "cell": "1,1"},
        ),
        Action(
            action_type="place",
            component_type="mark",
            to_pos={"zone": "board", "cell": "2,2"},
        ),
    ]
    states = replay_game(session, actions)
    assert len(states) == 3
    # First state should have 1 piece on the board
    assert states[0].status == "in_progress"
    # Turn should alternate between X and O
    assert states[0].turn == "O"
    assert states[1].turn == "X"
    assert states[2].turn == "O"


def test_replay_game_empty_actions() -> None:
    """Replaying zero actions returns empty list."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    states = replay_game(session, [])
    assert states == []


# ---------------------------------------------------------------------------
# complexity_profile
# ---------------------------------------------------------------------------


def test_complexity_profile_runs() -> None:
    """complexity_profile returns expected keys and sensible values."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    profile = complexity_profile(session, n_games=10)
    assert "min_length" in profile
    assert "max_length" in profile
    assert "avg_length" in profile
    assert "avg_branching_factor" in profile
    assert "win_rates" in profile
    # With end-condition detection, tic-tac-toe games end when someone
    # wins (min 5 moves) or the board fills (max 9 moves)
    assert 5 <= profile["min_length"] <= 9
    assert 5 <= profile["max_length"] <= 9
    assert 5.0 <= profile["avg_length"] <= 9.0


def test_complexity_profile_win_rates_sum() -> None:
    """Win rates should sum to at most 1.0 (draws may not be counted)."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    profile = complexity_profile(session, n_games=20)
    total = sum(profile["win_rates"].values())
    assert total <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# game_tree_depth
# ---------------------------------------------------------------------------


def test_game_tree_depth_tictactoe() -> None:
    """Average tic-tac-toe game length should be between 5 and 9."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    depth = game_tree_depth(session, max_depth=100, n_samples=20)
    assert 5 <= depth <= 9


# ---------------------------------------------------------------------------
# find_shortest_game
# ---------------------------------------------------------------------------


def test_find_shortest_game_tictactoe() -> None:
    """Find shortest tic-tac-toe game (5 moves for earliest possible win)."""
    defn = _load_definition("tic-tac-toe")
    session = GameSession(defn)
    shortest = find_shortest_game(session, max_attempts=50)
    # Shortest possible tic-tac-toe win: 5 moves (3 by first player, 2 by second)
    assert len(shortest) == 5
