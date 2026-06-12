"""Tests for Liar's Dice (Perudo): hidden dice, bidding, bluffing, challenge.

Each player has dice hidden in a cup. Players take turns bidding on the
total count of a face value across ALL players' dice. Bids must escalate.
A challenge (dudo) reveals all dice — loser forfeits a die. Last player
with dice wins.

Dice rolls are server authority — tests supply deterministic values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import GameSession


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "liars-dice.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# LiarsDiceGame helper
# ---------------------------------------------------------------------------

@dataclass
class Bid:
    quantity: int
    face: int  # 1-6

    def __str__(self) -> str:
        return f"{self.quantity}×{self.face}"


class LiarsDiceGame:
    """Liar's Dice game driver with bidding, challenge, and elimination."""

    def __init__(self, dice_per_player: int = 5) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.players = ["P1", "P2"]
        self.dice: dict[str, list[int]] = {}
        self.dice_count: dict[str, int] = {p: dice_per_player for p in self.players}
        self.current_bid: Bid | None = None
        self.bidder: str | None = None
        self.finished = False
        self.winner: str | None = None
        self.round_active = False

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _opponent(self, player: str) -> str:
        return "P2" if player == "P1" else "P1"

    def start_round(self, p1_dice: list[int], p2_dice: list[int]) -> None:
        """Start a new round with given dice values (simulating server roll)."""
        if self.finished:
            raise ValueError("game is finished")
        if len(p1_dice) != self.dice_count["P1"]:
            raise ValueError(
                f"P1 needs {self.dice_count['P1']} dice, got {len(p1_dice)}"
            )
        if len(p2_dice) != self.dice_count["P2"]:
            raise ValueError(
                f"P2 needs {self.dice_count['P2']} dice, got {len(p2_dice)}"
            )
        self.dice = {"P1": list(p1_dice), "P2": list(p2_dice)}
        self.current_bid = None
        self.bidder = None
        self.round_active = True

    def bid(self, quantity: int, face: int) -> None:
        """Make a bid: claim at least `quantity` dice showing `face` exist."""
        if self.finished:
            raise ValueError("game is finished")
        if not self.round_active:
            raise ValueError("no active round — call start_round first")
        if face < 1 or face > 6:
            raise ValueError(f"face must be 1-6, got {face}")
        if quantity < 1:
            raise ValueError("quantity must be >= 1")

        player = self.current_player()

        if self.current_bid is not None:
            # Must raise: higher quantity, or same quantity with higher face
            old = self.current_bid
            valid = (
                quantity > old.quantity
                or (quantity == old.quantity and face > old.face)
            )
            if not valid:
                raise ValueError(
                    f"bid {quantity}×{face} does not raise {old}"
                )

        self.current_bid = Bid(quantity=quantity, face=face)
        self.bidder = player
        self.session.advance_turn()

    def challenge(self) -> dict:
        """Challenge the current bid. Returns resolution details."""
        if self.finished:
            raise ValueError("game is finished")
        if self.current_bid is None:
            raise ValueError("nothing to challenge — no bid has been made")
        if not self.round_active:
            raise ValueError("no active round")

        challenger = self.current_player()
        bid = self.current_bid

        # Count actual dice matching the bid face across all players
        all_dice = []
        for p in self.players:
            if self.dice_count[p] > 0:
                all_dice.extend(self.dice[p])

        actual_count = sum(1 for d in all_dice if d == bid.face)

        # Bid is correct if actual count >= bid quantity
        bid_correct = actual_count >= bid.quantity

        if bid_correct:
            # Challenger loses a die
            loser = challenger
        else:
            # Bidder loses a die
            loser = self.bidder
            assert loser is not None

        self.dice_count[loser] -= 1
        self.round_active = False

        # Check elimination
        if self.dice_count[loser] <= 0:
            self.finished = True
            self.winner = self._opponent(loser)

        # Loser starts next round
        player_names = list(self.session.runtime.players.keys())
        self.session.runtime.turn_index = player_names.index(loser)

        return {
            "challenger": challenger,
            "bidder": self.bidder,
            "bid": str(bid),
            "actual_count": actual_count,
            "bid_correct": bid_correct,
            "loser": loser,
            "all_dice": dict(self.dice),
        }

    def total_dice(self) -> int:
        return sum(self.dice_count.values())


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Liar's Dice"

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_per_player_cups(self) -> None:
        defn = _load_game()
        assert defn.zones["cup"].per_player is True


# ---------------------------------------------------------------------------
# Tests: bidding
# ---------------------------------------------------------------------------


class TestBidding:
    def test_first_bid(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [2, 3, 4, 5, 6])
        game.bid(2, 3)
        assert game.current_bid == Bid(2, 3)

    def test_bid_advances_turn(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [2, 3, 4, 5, 6])
        assert game.current_player() == "P1"
        game.bid(1, 2)
        assert game.current_player() == "P2"

    def test_raise_quantity(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [2, 2, 2, 2, 2])
        game.bid(2, 3)
        game.bid(3, 3)  # higher quantity, same face
        assert game.current_bid == Bid(3, 3)

    def test_raise_face(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [2, 2, 2, 2, 2])
        game.bid(2, 3)
        game.bid(2, 4)  # same quantity, higher face
        assert game.current_bid == Bid(2, 4)

    def test_lower_bid_rejected(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [2, 2, 2, 2, 2])
        game.bid(3, 4)
        with pytest.raises(ValueError, match="does not raise"):
            game.bid(2, 4)

    def test_equal_bid_rejected(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [2, 2, 2, 2, 2])
        game.bid(3, 4)
        with pytest.raises(ValueError, match="does not raise"):
            game.bid(3, 4)

    def test_lower_face_same_quantity_rejected(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [2, 2, 2, 2, 2])
        game.bid(3, 5)
        with pytest.raises(ValueError, match="does not raise"):
            game.bid(3, 3)


# ---------------------------------------------------------------------------
# Tests: challenge
# ---------------------------------------------------------------------------


class TestChallenge:
    def test_correct_bid_challenger_loses(self) -> None:
        """Bid says 3×2, actually there are 3 twos — challenger loses."""
        game = LiarsDiceGame()
        game.start_round([2, 2, 3, 4, 5], [2, 3, 4, 5, 6])
        game.bid(3, 2)  # P1 bids 3 twos — correct (2,2 from P1 + 2 from P2)
        result = game.challenge()  # P2 challenges
        assert result["bid_correct"] is True
        assert result["loser"] == "P2"
        assert result["actual_count"] == 3
        assert game.dice_count["P2"] == 4

    def test_wrong_bid_bidder_loses(self) -> None:
        """Bid says 5×6, actually there's only 1 six — bidder loses."""
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [1, 2, 3, 4, 6])
        game.bid(5, 6)  # P1 bids 5 sixes — way too high
        result = game.challenge()  # P2 challenges
        assert result["bid_correct"] is False
        assert result["loser"] == "P1"
        assert result["actual_count"] == 1
        assert game.dice_count["P1"] == 4

    def test_challenge_reveals_all_dice(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 1, 1, 1, 1], [6, 6, 6, 6, 6])
        game.bid(1, 1)
        result = game.challenge()
        assert result["all_dice"]["P1"] == [1, 1, 1, 1, 1]
        assert result["all_dice"]["P2"] == [6, 6, 6, 6, 6]

    def test_challenge_without_bid_rejected(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        with pytest.raises(ValueError, match="no bid"):
            game.challenge()

    def test_loser_starts_next_round(self) -> None:
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [1, 2, 3, 4, 6])
        game.bid(5, 6)  # P1 bids badly
        result = game.challenge()  # P2 challenges, P1 loses
        assert result["loser"] == "P1"
        assert game.current_player() == "P1"  # loser starts next


# ---------------------------------------------------------------------------
# Tests: elimination and game end
# ---------------------------------------------------------------------------


class TestElimination:
    def test_player_eliminated_at_zero_dice(self) -> None:
        game = LiarsDiceGame(dice_per_player=1)
        game.start_round([3], [5])
        game.bid(2, 5)  # P1 bids 2 fives — only 1 exists
        result = game.challenge()  # P2 challenges, P1 loses die
        assert game.dice_count["P1"] == 0
        assert game.finished
        assert game.winner == "P2"

    def test_multiple_rounds_to_elimination(self) -> None:
        game = LiarsDiceGame(dice_per_player=2)

        # Round 1: P1 bids wrong, loses a die
        game.start_round([1, 2], [3, 4])
        game.bid(3, 5)  # P1: bad bid
        game.challenge()  # P2 challenges, P1 loses
        assert game.dice_count["P1"] == 1
        assert not game.finished

        # Round 2: P1 bids wrong again, eliminated
        game.start_round([1], [3, 4])
        game.bid(3, 6)  # P1: bad bid
        game.challenge()  # P2 challenges, P1 loses
        assert game.dice_count["P1"] == 0
        assert game.finished
        assert game.winner == "P2"

    def test_cannot_play_after_finished(self) -> None:
        game = LiarsDiceGame(dice_per_player=1)
        game.start_round([1], [2])
        game.bid(2, 3)
        game.challenge()
        assert game.finished
        with pytest.raises(ValueError, match="finished"):
            game.start_round([1], [2])


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_exact_count_bid_is_correct(self) -> None:
        """Bid exactly matching count is correct (challenger loses)."""
        game = LiarsDiceGame(dice_per_player=3)
        game.start_round([4, 4, 1], [4, 2, 3])
        game.bid(3, 4)  # exactly 3 fours
        result = game.challenge()
        assert result["bid_correct"] is True
        assert result["actual_count"] == 3

    def test_bid_one_of_common_face(self) -> None:
        """Minimum bid of 1 is always safe if that face exists."""
        game = LiarsDiceGame()
        game.start_round([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        game.bid(1, 1)  # 1 one — there are 2
        result = game.challenge()
        assert result["bid_correct"] is True

    def test_bluff_with_zero_matching(self) -> None:
        """Bid on a face that doesn't exist at all."""
        game = LiarsDiceGame(dice_per_player=2)
        game.start_round([1, 1], [1, 1])
        game.bid(1, 6)  # no sixes exist
        result = game.challenge()
        assert result["bid_correct"] is False
        assert result["actual_count"] == 0


# ---------------------------------------------------------------------------
# Tests: full game
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_short_game(self) -> None:
        """Play a complete short game."""
        game = LiarsDiceGame(dice_per_player=2)

        # Round 1
        game.start_round([3, 3], [5, 5])
        game.bid(2, 3)  # P1: 2 threes (correct — 2 exist)
        game.bid(3, 3)  # P2: 3 threes (wrong — only 2)
        result = game.challenge()  # P1 challenges
        assert result["loser"] == "P2"
        assert game.dice_count["P2"] == 1

        # Round 2: P2 starts (loser)
        game.start_round([3, 3], [5])
        game.bid(1, 5)  # P2: 1 five (correct)
        game.bid(2, 5)  # P1: 2 fives (wrong — only 1)
        result = game.challenge()  # P2 challenges
        assert result["loser"] == "P1"
        assert game.dice_count["P1"] == 1

        # Round 3
        game.start_round([6], [4])
        game.bid(2, 6)  # P1: 2 sixes (wrong — only 1)
        result = game.challenge()  # P2 challenges
        assert result["loser"] == "P1"
        assert game.finished
        assert game.winner == "P2"

    def test_dice_total_decreases(self) -> None:
        game = LiarsDiceGame(dice_per_player=3)
        assert game.total_dice() == 6
        game.start_round([1, 1, 1], [2, 2, 2])
        game.bid(4, 1)  # bad bid
        game.challenge()
        assert game.total_dice() == 5
