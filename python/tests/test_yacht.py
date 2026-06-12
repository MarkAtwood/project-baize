"""Tests for Yacht (Yahtzee): multi-phase dice, keep/re-roll, scoring categories.

Each turn: roll 5d6 → optionally keep and re-roll up to 2 times → assign to
one of 13 scoring categories. Game ends when all categories filled.
Highest total score wins.

Dice rolls are server authority — tests supply deterministic values.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import GameSession


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "yahtzee.json"


def _load_yacht() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Scoring functions (independent oracles)
# ---------------------------------------------------------------------------


def score_upper(dice: list[int], face: int) -> int:
    """Score for Ones through Sixes: sum of dice matching face."""
    return sum(d for d in dice if d == face)


def score_n_of_a_kind(dice: list[int], n: int) -> int:
    """Score for Three/Four of a Kind: sum of all dice if condition met, else 0."""
    counts = Counter(dice)
    if any(c >= n for c in counts.values()):
        return sum(dice)
    return 0


def score_full_house(dice: list[int]) -> int:
    """25 if exactly one pair and one triple."""
    counts = sorted(Counter(dice).values())
    return 25 if counts == [2, 3] else 0


def score_small_straight(dice: list[int]) -> int:
    """30 if dice contain 4 consecutive values."""
    unique = set(dice)
    for start in range(1, 4):
        if all(v in unique for v in range(start, start + 4)):
            return 30
    return 0


def score_large_straight(dice: list[int]) -> int:
    """40 if dice contain 5 consecutive values."""
    unique = sorted(set(dice))
    return 40 if len(unique) == 5 and unique[-1] - unique[0] == 4 else 0


def score_yacht(dice: list[int]) -> int:
    """50 if all five dice are the same."""
    return 50 if len(set(dice)) == 1 else 0


def score_chance(dice: list[int]) -> int:
    """Sum of all dice (always valid)."""
    return sum(dice)


CATEGORIES = {
    "ones": lambda d: score_upper(d, 1),
    "twos": lambda d: score_upper(d, 2),
    "threes": lambda d: score_upper(d, 3),
    "fours": lambda d: score_upper(d, 4),
    "fives": lambda d: score_upper(d, 5),
    "sixes": lambda d: score_upper(d, 6),
    "three_of_a_kind": lambda d: score_n_of_a_kind(d, 3),
    "four_of_a_kind": lambda d: score_n_of_a_kind(d, 4),
    "full_house": score_full_house,
    "small_straight": score_small_straight,
    "large_straight": score_large_straight,
    "yacht": score_yacht,
    "chance": score_chance,
}


# ---------------------------------------------------------------------------
# YachtGame helper
# ---------------------------------------------------------------------------


class YachtGame:
    """Yacht game driver with dice, keep/re-roll, and category assignment."""

    def __init__(self) -> None:
        defn = _load_yacht()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.dice: list[int] = [0, 0, 0, 0, 0]
        self.rolls_remaining = 0
        self.scores: dict[str, dict[str, int | None]] = {
            "P1": {cat: None for cat in CATEGORIES},
            "P2": {cat: None for cat in CATEGORIES},
        }
        self.finished = False

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def start_turn(self, values: list[int]) -> list[int]:
        """Start a turn by rolling all 5 dice with given values."""
        if self.finished:
            raise ValueError("game is finished")
        if len(values) != 5:
            raise ValueError("must provide 5 die values")
        if not all(1 <= v <= 6 for v in values):
            raise ValueError("die values must be 1-6")
        self.dice = list(values)
        self.rolls_remaining = 2
        return self.dice

    def reroll(self, keep_mask: list[bool], new_values: list[int]) -> list[int]:
        """Keep some dice, re-roll others.

        keep_mask: True = keep this die, False = re-roll.
        new_values: replacement values for re-rolled dice.
        """
        if self.rolls_remaining <= 0:
            raise ValueError("no re-rolls remaining")
        if len(keep_mask) != 5:
            raise ValueError("keep_mask must have 5 entries")

        reroll_count = sum(1 for k in keep_mask if not k)
        if len(new_values) != reroll_count:
            raise ValueError(
                f"need {reroll_count} new values, got {len(new_values)}"
            )

        vi = 0
        for i in range(5):
            if not keep_mask[i]:
                self.dice[i] = new_values[vi]
                vi += 1

        self.rolls_remaining -= 1
        return self.dice

    def assign(self, category: str) -> int:
        """Assign current dice to a scoring category. Returns score."""
        player = self.current_player()
        if category not in CATEGORIES:
            raise ValueError(f"unknown category: {category}")
        if self.scores[player][category] is not None:
            raise ValueError(f"{player} already used category {category}")

        score = CATEGORIES[category](self.dice)
        self.scores[player][category] = score
        self.dice = [0, 0, 0, 0, 0]
        self.rolls_remaining = 0

        # Advance turn
        self.session.advance_turn()

        # Check game end: all categories filled for both players
        if all(
            all(v is not None for v in self.scores[p].values())
            for p in ["P1", "P2"]
        ):
            self.finished = True

        return score

    def total_score(self, player: str) -> int:
        return sum(v for v in self.scores[player].values() if v is not None)

    def upper_bonus(self, player: str) -> int:
        """35-point bonus if upper section (ones-sixes) totals >= 63."""
        upper = sum(
            self.scores[player][cat] or 0
            for cat in ["ones", "twos", "threes", "fours", "fives", "sixes"]
        )
        return 35 if upper >= 63 else 0

    def winner(self) -> str | None:
        s1 = self.total_score("P1") + self.upper_bonus("P1")
        s2 = self.total_score("P2") + self.upper_bonus("P2")
        if s1 > s2:
            return "P1"
        elif s2 > s1:
            return "P2"
        return None


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestYachtDefinition:
    def test_loads(self) -> None:
        defn = _load_yacht()
        assert defn.game.name == "Yahtzee"

    def test_two_players(self) -> None:
        defn = _load_yacht()
        assert defn.game.players == ["P1", "P2"]


# ---------------------------------------------------------------------------
# Tests: scoring functions (independent oracles)
# ---------------------------------------------------------------------------


class TestScoring:
    def test_ones(self) -> None:
        assert score_upper([1, 1, 3, 4, 5], 1) == 2

    def test_sixes(self) -> None:
        assert score_upper([6, 6, 6, 1, 2], 6) == 18

    def test_three_of_a_kind(self) -> None:
        assert score_n_of_a_kind([3, 3, 3, 2, 5], 3) == 16
        assert score_n_of_a_kind([1, 2, 3, 4, 5], 3) == 0

    def test_four_of_a_kind(self) -> None:
        assert score_n_of_a_kind([4, 4, 4, 4, 2], 4) == 18
        assert score_n_of_a_kind([4, 4, 4, 3, 2], 4) == 0

    def test_full_house(self) -> None:
        assert score_full_house([2, 2, 3, 3, 3]) == 25
        assert score_full_house([1, 2, 3, 4, 5]) == 0
        assert score_full_house([3, 3, 3, 3, 3]) == 0  # not a full house

    def test_small_straight(self) -> None:
        assert score_small_straight([1, 2, 3, 4, 6]) == 30
        assert score_small_straight([2, 3, 4, 5, 5]) == 30
        assert score_small_straight([1, 2, 3, 5, 6]) == 0

    def test_large_straight(self) -> None:
        assert score_large_straight([1, 2, 3, 4, 5]) == 40
        assert score_large_straight([2, 3, 4, 5, 6]) == 40
        assert score_large_straight([1, 2, 3, 4, 6]) == 0

    def test_yacht(self) -> None:
        assert score_yacht([5, 5, 5, 5, 5]) == 50
        assert score_yacht([5, 5, 5, 5, 4]) == 0

    def test_chance(self) -> None:
        assert score_chance([1, 2, 3, 4, 5]) == 15
        assert score_chance([6, 6, 6, 6, 6]) == 30


# ---------------------------------------------------------------------------
# Tests: turn flow
# ---------------------------------------------------------------------------


class TestTurnFlow:
    def test_start_turn(self) -> None:
        game = YachtGame()
        dice = game.start_turn([1, 2, 3, 4, 5])
        assert dice == [1, 2, 3, 4, 5]
        assert game.rolls_remaining == 2

    def test_reroll_replaces_dice(self) -> None:
        game = YachtGame()
        game.start_turn([1, 2, 3, 4, 5])
        # Keep 4 and 5, re-roll others
        dice = game.reroll([False, False, False, True, True], [6, 6, 6])
        assert dice == [6, 6, 6, 4, 5]
        assert game.rolls_remaining == 1

    def test_two_rerolls_max(self) -> None:
        game = YachtGame()
        game.start_turn([1, 1, 1, 1, 1])
        game.reroll([True, True, True, True, False], [2])
        game.reroll([True, True, True, True, False], [3])
        with pytest.raises(ValueError, match="no re-rolls"):
            game.reroll([True, True, True, True, False], [4])

    def test_keep_all_dice(self) -> None:
        game = YachtGame()
        game.start_turn([5, 5, 5, 5, 5])
        dice = game.reroll([True, True, True, True, True], [])
        assert dice == [5, 5, 5, 5, 5]

    def test_assign_advances_turn(self) -> None:
        game = YachtGame()
        assert game.current_player() == "P1"
        game.start_turn([1, 2, 3, 4, 5])
        game.assign("chance")
        assert game.current_player() == "P2"

    def test_category_used_once(self) -> None:
        game = YachtGame()
        game.start_turn([1, 2, 3, 4, 5])
        game.assign("chance")
        # P2's turn
        game.start_turn([1, 1, 1, 1, 1])
        game.assign("ones")
        # P1's turn again — chance already used
        game.start_turn([6, 6, 6, 6, 6])
        with pytest.raises(ValueError, match="already used"):
            game.assign("chance")


# ---------------------------------------------------------------------------
# Tests: game end
# ---------------------------------------------------------------------------


class TestGameEnd:
    def test_game_ends_after_26_assignments(self) -> None:
        """13 categories × 2 players = 26 total assignments."""
        game = YachtGame()
        cats = list(CATEGORIES.keys())
        for round_num in range(13):
            # P1
            game.start_turn([1, 1, 1, 1, 1])
            game.assign(cats[round_num])
            # P2
            game.start_turn([1, 1, 1, 1, 1])
            game.assign(cats[round_num])
        assert game.finished

    def test_winner_by_total_score(self) -> None:
        game = YachtGame()
        cats = list(CATEGORIES.keys())
        for cat in cats:
            # P1 always rolls high, P2 always rolls low
            game.start_turn([6, 6, 6, 6, 6])
            game.assign(cat)
            game.start_turn([1, 1, 1, 2, 2])
            game.assign(cat)

        assert game.finished
        # P1 scores higher on sixes, chance, n-of-a-kind, yacht
        assert game.total_score("P1") > game.total_score("P2")
        assert game.winner() == "P1"


# ---------------------------------------------------------------------------
# Tests: upper bonus
# ---------------------------------------------------------------------------


class TestUpperBonus:
    def test_no_bonus_below_63(self) -> None:
        game = YachtGame()
        game.scores["P1"]["ones"] = 3
        game.scores["P1"]["twos"] = 6
        game.scores["P1"]["threes"] = 9
        game.scores["P1"]["fours"] = 12
        game.scores["P1"]["fives"] = 15
        game.scores["P1"]["sixes"] = 17  # total 62
        assert game.upper_bonus("P1") == 0

    def test_bonus_at_63(self) -> None:
        game = YachtGame()
        game.scores["P1"]["ones"] = 3
        game.scores["P1"]["twos"] = 6
        game.scores["P1"]["threes"] = 9
        game.scores["P1"]["fours"] = 12
        game.scores["P1"]["fives"] = 15
        game.scores["P1"]["sixes"] = 18  # total 63
        assert game.upper_bonus("P1") == 35
