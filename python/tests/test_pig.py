"""Tests for the Pig dice game definition and engine integration.

Pig is a push-your-luck dice game:
  - 2 players alternate turns.
  - On your turn: roll a d6. Roll 2–6 → add to turn score. Roll 1 → bust
    (lose turn score) and end turn.
  - Instead of rolling, you may bank: add turn score to total and end turn.
  - First player to reach 100 total wins.

The engine's apply_action/advance_turn is not used here because Pig requires
variable-length turns (a player may roll many times before banking or busting).
Instead tests use a PigGame helper that drives state through session.runtime
counters and execute_effect, then calls check_end_conditions manually.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from baize.cel import try_eval_end_condition
from baize.definition import GameDefinition
from baize.perturber import execute_effect
from baize.runtime import CounterZone, GameSession


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_PIG_JSON = Path(__file__).resolve().parent.parent.parent / "games" / "pig.json"

PlayerName = Literal["Alice", "Bob"]


def _load_pig() -> GameDefinition:
    return GameDefinition.from_json(_PIG_JSON.read_text())


class PigGame:
    """Thin wrapper around GameSession that enforces Pig rules.

    State is kept entirely in session.runtime.counters:
      alice_total  — Alice's banked score
      bob_total    — Bob's banked score
      turn_score   — current player's accumulated score this turn
    """

    PLAYERS: tuple[str, str] = ("Alice", "Bob")
    WIN_SCORE = 100

    def __init__(self) -> None:
        defn = _load_pig()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        # Initialise all counters to zero.
        execute_effect(
            self.session,
            {
                "sequence": [
                    {"set_counter": {"counter": "alice_total", "value": 0}},
                    {"set_counter": {"counter": "bob_total", "value": 0}},
                    {"set_counter": {"counter": "turn_score", "value": 0}},
                ]
            },
        )

    # ------------------------------------------------------------------
    # Counter accessors
    # ------------------------------------------------------------------

    @property
    def alice_total(self) -> int:
        return self.session.runtime.counters.get("alice_total", 0)

    @property
    def bob_total(self) -> int:
        return self.session.runtime.counters.get("bob_total", 0)

    @property
    def turn_score(self) -> int:
        return self.session.runtime.counters.get("turn_score", 0)

    def _total_counter(self, player: str) -> str:
        return f"{player.lower()}_total"

    # ------------------------------------------------------------------
    # Game actions
    # ------------------------------------------------------------------

    def roll(self, face: int) -> str:
        """Simulate a die roll with a known face value.

        Returns "bust" if the face is 1, else "ok".
        The caller (a test) supplies the face value because die rolls are
        server-authority in the real game; tests choose specific values to
        exercise deterministic scenarios.
        """
        if face < 1 or face > 6:
            raise ValueError(f"invalid die face: {face}")

        # Record the die face in the zone counter.
        die_zone = self.session.runtime.zones.get("die_face")
        assert isinstance(die_zone, CounterZone)
        die_zone.value = face

        if face == 1:
            # Bust: lose turn score, end turn.
            execute_effect(
                self.session,
                {"set_counter": {"counter": "turn_score", "value": 0}},
            )
            self._advance_turn()
            return "bust"

        # Normal roll: add to turn score.
        execute_effect(
            self.session,
            {"add_counter": {"counter": "turn_score", "value": face}},
        )
        return "ok"

    def bank(self) -> None:
        """Current player banks their turn score."""
        player = self.session.current_player()
        assert player is not None
        counter = self._total_counter(player)
        # Add turn_score to the player's total, reset turn_score.
        execute_effect(
            self.session,
            {
                "sequence": [
                    {
                        "add_counter": {
                            "counter": counter,
                            "value": self.turn_score,
                        }
                    },
                    {"set_counter": {"counter": "turn_score", "value": 0}},
                ]
            },
        )
        self._advance_turn()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _advance_turn(self) -> None:
        """Advance to the next player."""
        self.session.advance_turn()

    def check_winner(self) -> str | None:
        """Return winning player name if an end condition is met, else None.

        check_end_conditions() does not expose session.runtime.counters to the
        CEL evaluator, so we evaluate the library CEL expressions directly with
        the counter values as variables.
        """
        variables: dict[str, int] = {
            "alice_total": self.alice_total,
            "bob_total": self.bob_total,
        }
        for ec in self.session.definition.end_conditions:
            lib = self.session.definition.library
            expr = lib.get(ec.condition)
            if not isinstance(expr, str):
                expr = ec.condition
            result = try_eval_end_condition(variables, expr)
            if result is True and ec.result == "win" and ec.player is not None:
                return ec.player
        return None

    def current_player(self) -> str:
        player = self.session.current_player()
        assert player is not None
        return player


# ---------------------------------------------------------------------------
# Tests: definition structure
# ---------------------------------------------------------------------------


class TestPigDefinition:
    """pig.json loads and has the expected structure."""

    def test_loads_without_error(self) -> None:
        defn = _load_pig()
        assert defn.game.name == "Pig"

    def test_two_named_players(self) -> None:
        defn = _load_pig()
        assert defn.game.players == ["Alice", "Bob"]

    def test_perfect_information(self) -> None:
        defn = _load_pig()
        assert defn.game.information == "perfect"

    def test_die_face_counter_zone(self) -> None:
        defn = _load_pig()
        assert "die_face" in defn.zones
        assert defn.zones["die_face"].zone_type == "counter"

    def test_die_component_exists(self) -> None:
        defn = _load_pig()
        assert "die" in defn.components

    def test_two_end_conditions(self) -> None:
        defn = _load_pig()
        assert len(defn.end_conditions) == 2
        names = {ec.name for ec in defn.end_conditions}
        assert "alice_reaches_100" in names
        assert "bob_reaches_100" in names

    def test_end_condition_results_are_win(self) -> None:
        defn = _load_pig()
        for ec in defn.end_conditions:
            assert ec.result == "win"

    def test_authority_roll_is_server_only(self) -> None:
        defn = _load_pig()
        assert any("roll_dice" in s for s in defn.authority.server_only)

    def test_library_conditions(self) -> None:
        defn = _load_pig()
        assert "alice_wins" in defn.library
        assert "bob_wins" in defn.library


# ---------------------------------------------------------------------------
# Tests: counter initialisation
# ---------------------------------------------------------------------------


class TestCounterInit:
    """Session counters start at zero."""

    def test_all_counters_zero_at_start(self) -> None:
        game = PigGame()
        assert game.alice_total == 0
        assert game.bob_total == 0
        assert game.turn_score == 0

    def test_alice_moves_first(self) -> None:
        game = PigGame()
        assert game.current_player() == "Alice"

    def test_die_face_zone_starts_zero(self) -> None:
        game = PigGame()
        die_zone = game.session.runtime.zones.get("die_face")
        assert isinstance(die_zone, CounterZone)
        assert die_zone.value == 0


# ---------------------------------------------------------------------------
# Tests: rolling
# ---------------------------------------------------------------------------


class TestRolling:
    """Rolling the die accumulates turn score or busts."""

    def test_roll_non_one_adds_to_turn_score(self) -> None:
        game = PigGame()
        result = game.roll(4)
        assert result == "ok"
        assert game.turn_score == 4

    def test_multiple_non_one_rolls_accumulate(self) -> None:
        game = PigGame()
        game.roll(3)
        game.roll(5)
        game.roll(2)
        assert game.turn_score == 10

    def test_all_non_one_faces_add_correctly(self) -> None:
        for face in (2, 3, 4, 5, 6):
            game = PigGame()
            result = game.roll(face)
            assert result == "ok"
            assert game.turn_score == face

    def test_roll_one_busts(self) -> None:
        game = PigGame()
        game.roll(5)
        game.roll(3)
        assert game.turn_score == 8
        result = game.roll(1)
        assert result == "bust"
        assert game.turn_score == 0

    def test_bust_does_not_add_to_total(self) -> None:
        game = PigGame()
        game.roll(6)
        game.roll(1)
        assert game.alice_total == 0

    def test_bust_advances_turn_to_bob(self) -> None:
        game = PigGame()
        game.roll(1)
        assert game.current_player() == "Bob"

    def test_die_face_recorded_in_zone(self) -> None:
        game = PigGame()
        game.roll(5)
        die_zone = game.session.runtime.zones.get("die_face")
        assert isinstance(die_zone, CounterZone)
        assert die_zone.value == 5


# ---------------------------------------------------------------------------
# Tests: banking
# ---------------------------------------------------------------------------


class TestBanking:
    """Banking adds turn score to total and ends the turn."""

    def test_bank_adds_turn_score_to_total(self) -> None:
        game = PigGame()
        game.roll(4)
        game.roll(5)
        game.bank()
        assert game.alice_total == 9

    def test_bank_resets_turn_score(self) -> None:
        game = PigGame()
        game.roll(6)
        game.bank()
        assert game.turn_score == 0

    def test_bank_advances_turn_to_bob(self) -> None:
        game = PigGame()
        game.roll(3)
        game.bank()
        assert game.current_player() == "Bob"

    def test_bob_banking_adds_to_bobs_total(self) -> None:
        game = PigGame()
        # Alice's turn — bust to hand off.
        game.roll(1)
        # Bob's turn — roll then bank.
        game.roll(6)
        game.roll(4)
        game.bank()
        assert game.bob_total == 10
        assert game.alice_total == 0

    def test_bank_with_zero_turn_score(self) -> None:
        """Banking with zero (e.g. after a bust mid-game) adds 0."""
        game = PigGame()
        # Force turn_score to 0 and bank immediately.
        game.bank()
        assert game.alice_total == 0
        assert game.current_player() == "Bob"

    def test_multiple_banks_accumulate_across_turns(self) -> None:
        """Both players bank several times; totals accumulate independently."""
        game = PigGame()
        # Turn 1: Alice rolls 5, banks → alice_total = 5.
        game.roll(5)
        game.bank()
        # Turn 2: Bob rolls 3, banks → bob_total = 3.
        game.roll(3)
        game.bank()
        # Turn 3: Alice rolls 6, banks → alice_total = 11.
        game.roll(6)
        game.bank()
        assert game.alice_total == 11
        assert game.bob_total == 3


# ---------------------------------------------------------------------------
# Tests: turn alternation
# ---------------------------------------------------------------------------


class TestTurnAlternation:
    """Turn index advances correctly through alternating play."""

    def test_bank_switches_from_alice_to_bob(self) -> None:
        game = PigGame()
        assert game.current_player() == "Alice"
        game.bank()
        assert game.current_player() == "Bob"

    def test_bank_switches_from_bob_to_alice(self) -> None:
        game = PigGame()
        game.bank()  # Alice → Bob
        game.bank()  # Bob → Alice
        assert game.current_player() == "Alice"

    def test_bust_switches_player(self) -> None:
        game = PigGame()
        game.roll(1)  # Alice busts → Bob
        assert game.current_player() == "Bob"
        game.roll(1)  # Bob busts → Alice
        assert game.current_player() == "Alice"


# ---------------------------------------------------------------------------
# Tests: win condition (CEL expression evaluation)
# ---------------------------------------------------------------------------


class TestWinConditionCEL:
    """The library CEL expressions evaluate correctly for threshold detection."""

    def test_alice_wins_at_100(self) -> None:
        variables = {"alice_total": 100}
        result = try_eval_end_condition(variables, "alice_total >= 100")
        assert result is True

    def test_alice_does_not_win_below_100(self) -> None:
        variables = {"alice_total": 99}
        result = try_eval_end_condition(variables, "alice_total >= 100")
        assert result is False

    def test_alice_wins_above_100(self) -> None:
        variables = {"alice_total": 105}
        result = try_eval_end_condition(variables, "alice_total >= 100")
        assert result is True

    def test_bob_wins_at_100(self) -> None:
        variables = {"bob_total": 100}
        result = try_eval_end_condition(variables, "bob_total >= 100")
        assert result is True

    def test_bob_does_not_win_below_100(self) -> None:
        variables = {"bob_total": 99}
        result = try_eval_end_condition(variables, "bob_total >= 100")
        assert result is False

    def test_zero_total_does_not_win(self) -> None:
        for expr in ("alice_total >= 100", "bob_total >= 100"):
            result = try_eval_end_condition({"alice_total": 0, "bob_total": 0}, expr)
            assert result is False


# ---------------------------------------------------------------------------
# Tests: full game scenarios
# ---------------------------------------------------------------------------


class TestFullGame:
    """End-to-end game scenarios exercising Pig rules."""

    def test_alice_wins_by_banking_exactly_100(self) -> None:
        """Alice accumulates exactly 100 across several turns."""
        game = PigGame()
        # Turn 1 Alice: 6+6+6+6+6 = 30, bank → alice_total = 30.
        for _ in range(5):
            game.roll(6)
        game.bank()
        # Turn 2 Bob: busts.
        game.roll(1)
        # Turn 3 Alice: 6+6+6+6+6+6 = 36, bank → alice_total = 66.
        for _ in range(6):
            game.roll(6)
        game.bank()
        # Turn 4 Bob: busts.
        game.roll(1)
        # Turn 5 Alice: needs 34 more. 6+6+6+6+5+5 = 34, bank → alice_total = 100.
        for _ in range(4):
            game.roll(6)
        game.roll(5)
        game.roll(5)
        game.bank()

        assert game.alice_total == 100
        winner = game.check_winner()
        assert winner == "Alice"

    def test_bob_wins_by_banking_over_100(self) -> None:
        """Bob surpasses 100 (banking is not capped at 100 exactly)."""
        game = PigGame()
        # Alice busts immediately every turn to give Bob all rolls.
        game.roll(1)  # Alice busts → Bob
        # Bob banks 30 (5×6).
        for _ in range(5):
            game.roll(6)
        game.bank()  # bob_total = 30 → Alice
        game.roll(1)  # Alice busts → Bob
        # Bob banks 36 (6×6).
        for _ in range(6):
            game.roll(6)
        game.bank()  # bob_total = 66 → Alice
        game.roll(1)  # Alice busts → Bob
        # Bob banks 42 (7×6): total = 108 > 100.
        for _ in range(7):
            game.roll(6)
        game.bank()  # bob_total = 108

        assert game.bob_total == 108
        winner = game.check_winner()
        assert winner == "Bob"

    def test_bust_sequence_gives_neither_player_points(self) -> None:
        """Repeated busts keep both totals at zero."""
        game = PigGame()
        for _ in range(6):
            game.roll(1)
        assert game.alice_total == 0
        assert game.bob_total == 0

    def test_no_winner_before_reaching_100(self) -> None:
        """check_winner returns None while both totals are below 100."""
        game = PigGame()
        for _ in range(4):
            game.roll(6)
        game.bank()  # alice_total = 24
        assert game.check_winner() is None

    def test_turn_score_does_not_count_toward_win(self) -> None:
        """Accumulated turn score is not a win — only the banked total matters."""
        game = PigGame()
        # Roll up a large turn score without banking.
        for _ in range(20):
            game.roll(6)  # turn_score = 120, but not banked
        # Win condition checks banked totals only.
        assert game.alice_total == 0
        assert game.check_winner() is None

    def test_alice_wins_from_prestaged_total(self) -> None:
        """With alice_total at 95, banking 5 more wins the game."""
        game = PigGame()
        execute_effect(
            game.session,
            {"set_counter": {"counter": "alice_total", "value": 95}},
        )
        game.roll(5)
        game.bank()  # alice_total = 100
        assert game.alice_total == 100
        assert game.check_winner() == "Alice"

    def test_bob_wins_from_prestaged_total(self) -> None:
        """With bob_total at 95, Bob banking 6 more wins the game."""
        game = PigGame()
        execute_effect(
            game.session,
            {"set_counter": {"counter": "bob_total", "value": 95}},
        )
        # Move to Bob's turn.
        game.roll(1)  # Alice busts → Bob's turn
        game.roll(6)
        game.bank()  # bob_total = 101
        assert game.bob_total == 101
        assert game.check_winner() == "Bob"

    def test_counters_are_independent_across_players(self) -> None:
        """Banking for one player does not affect the other's total."""
        game = PigGame()
        for _ in range(4):
            game.roll(5)  # turn_score = 20
        game.bank()  # alice_total = 20
        assert game.bob_total == 0

    def test_typical_short_game(self) -> None:
        """Play a complete game where Alice wins after a few turns."""
        game = PigGame()
        turns = [
            # (player_expected, rolls, should_bank)
            ("Alice", [6, 6, 6, 6, 6], True),      # +30 → 30
            ("Bob",   [3, 4, 5], True),              # +12 → 12
            ("Alice", [5, 6, 6, 6, 6, 5], True),    # +34 → 64
            ("Bob",   [1], False),                   # bust → 12
            ("Alice", [6, 6, 6, 6, 6, 6], True),    # +36 → 100
        ]
        for expected_player, rolls, should_bank in turns:
            assert game.current_player() == expected_player, (
                f"expected {expected_player}, got {game.current_player()}"
            )
            for face in rolls:
                result = game.roll(face)
                if result == "bust":
                    break
            else:
                if should_bank:
                    game.bank()

        assert game.alice_total == 100
        assert game.check_winner() == "Alice"
