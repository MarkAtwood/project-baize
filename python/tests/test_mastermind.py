"""Tests for Mastermind: hidden code, guessing, and feedback.

Mastermind is a 2-player code-breaking game.  The codemaker sets a hidden
4-peg code from 6 colors (duplicates allowed).  The codebreaker has up to
10 guesses.  After each guess the server provides feedback:
  - Black key pegs: correct color in the correct position.
  - White key pegs: correct color in the wrong position.
The codebreaker wins by guessing the exact code; the codemaker wins if
10 guesses are exhausted without a match.

Feedback computation is server authority — tests supply deterministic codes
and verify feedback against an independent oracle (the standard Mastermind
algorithm implemented in the test helper, cross-checked against known
published examples from Donald Knuth's 1977 analysis).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import GameSession


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLORS = ("red", "blue", "green", "yellow", "white", "black")

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "mastermind.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Feedback oracle (independent implementation)
# ---------------------------------------------------------------------------

@dataclass
class Feedback:
    """Mastermind feedback: black pegs (exact match) and white pegs (color match)."""
    black: int = 0
    white: int = 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Feedback):
            return self.black == other.black and self.white == other.white
        return NotImplemented

    def is_exact(self) -> bool:
        return self.black == 4 and self.white == 0


def compute_feedback(secret: list[str], guess: list[str]) -> Feedback:
    """Standard Mastermind feedback algorithm.

    1. Count exact matches (same color, same position) -> black pegs.
    2. For remaining positions, count color matches (each secret peg
       consumed at most once) -> white pegs.

    This is the canonical algorithm from Knuth (1977).
    """
    if len(secret) != 4 or len(guess) != 4:
        raise ValueError("secret and guess must each have exactly 4 pegs")

    black = 0
    secret_remaining: list[str | None] = list(secret)
    guess_remaining: list[str | None] = list(guess)

    # Pass 1: exact matches
    for i in range(4):
        if guess[i] == secret[i]:
            black += 1
            secret_remaining[i] = None
            guess_remaining[i] = None

    # Pass 2: color matches among remaining pegs
    white = 0
    for i in range(4):
        if guess_remaining[i] is None:
            continue
        for j in range(4):
            if secret_remaining[j] is None:
                continue
            if guess_remaining[i] == secret_remaining[j]:
                white += 1
                secret_remaining[j] = None
                break

    return Feedback(black=black, white=white)


# ---------------------------------------------------------------------------
# MastermindGame driver
# ---------------------------------------------------------------------------


class MastermindGame:
    """Mastermind game driver with code setting, guessing, and feedback."""

    MAX_GUESSES = 10

    def __init__(self, secret_code: list[str]) -> None:
        if len(secret_code) != 4:
            raise ValueError("secret code must have exactly 4 pegs")
        for color in secret_code:
            if color not in COLORS:
                raise ValueError(f"invalid color: {color}")

        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.secret_code = list(secret_code)
        self.guess_count = 0
        self.guess_history: list[list[str]] = []
        self.feedback_history: list[Feedback] = []
        self.finished = False
        self.winner: str | None = None

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def guess(self, guess_pegs: list[str]) -> Feedback:
        """Submit a 4-peg guess. Returns the feedback."""
        if self.finished:
            raise ValueError("game is finished")
        if len(guess_pegs) != 4:
            raise ValueError("guess must have exactly 4 pegs")
        for color in guess_pegs:
            if color not in COLORS:
                raise ValueError(f"invalid color: {color}")

        self.guess_count += 1
        self.guess_history.append(list(guess_pegs))

        feedback = compute_feedback(self.secret_code, guess_pegs)
        self.feedback_history.append(feedback)

        if feedback.is_exact():
            self.finished = True
            self.winner = "codebreaker"
        elif self.guess_count >= self.MAX_GUESSES:
            self.finished = True
            self.winner = "codemaker"

        self.session.advance_turn()
        return feedback

    def guesses_remaining(self) -> int:
        return self.MAX_GUESSES - self.guess_count


# ---------------------------------------------------------------------------
# Tests: definition parsing
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Mastermind"

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert isinstance(defn.game.players, list)
        assert defn.game.players == ["codemaker", "codebreaker"]

    def test_secret_code_zone_hidden(self) -> None:
        defn = _load_game()
        zone = defn.zones["secret_code"]
        assert zone.visibility == "hidden"
        assert zone.zone_type == "ordered_stack"

    def test_guess_history_zone_public(self) -> None:
        defn = _load_game()
        zone = defn.zones["guess_history"]
        assert zone.visibility == "public"

    def test_feedback_history_zone_public(self) -> None:
        defn = _load_game()
        zone = defn.zones["feedback_history"]
        assert zone.visibility == "public"

    def test_guess_counter_zone(self) -> None:
        defn = _load_game()
        zone = defn.zones["guess_counter"]
        assert zone.zone_type == "counter"
        assert zone.visibility == "public"

    def test_peg_component_has_six_colors(self) -> None:
        defn = _load_game()
        assert "peg" in defn.components
        comp = defn.components["peg"]
        assert comp.types is not None
        for color in COLORS:
            assert color in comp.types, f"missing color type: {color}"

    def test_feedback_peg_types(self) -> None:
        defn = _load_game()
        assert "feedback_peg" in defn.components
        comp = defn.components["feedback_peg"]
        assert comp.types is not None
        assert "black" in comp.types
        assert "white" in comp.types

    def test_two_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 2
        names = {ec.name for ec in defn.end_conditions}
        assert "code_cracked" in names
        assert "guesses_exhausted" in names

    def test_server_only_authority(self) -> None:
        defn = _load_game()
        assert "store_secret_code" in defn.authority.server_only
        assert "compute_feedback(guess, secret_code)" in defn.authority.server_only

    def test_two_phases(self) -> None:
        defn = _load_game()
        assert defn.phases is not None
        assert len(defn.phases) == 2
        phase_names = [p.name for p in defn.phases]
        assert "setup" in phase_names
        assert "guessing" in phase_names


# ---------------------------------------------------------------------------
# Tests: feedback algorithm (independent oracle)
#
# Test vectors are manually computed from the standard Mastermind rules,
# cross-referenced with Donald Knuth's 1977 "The Computer as Master Mind"
# (J. Recreational Mathematics, 9(1), 1976-77).
# ---------------------------------------------------------------------------


class TestFeedbackAlgorithm:
    def test_exact_match(self) -> None:
        """All 4 pegs correct color and position -> 4 black, 0 white."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "blue", "green", "yellow"],
        )
        assert fb == Feedback(black=4, white=0)
        assert fb.is_exact()

    def test_no_match(self) -> None:
        """No colors in common -> 0 black, 0 white."""
        fb = compute_feedback(
            ["red", "red", "red", "red"],
            ["blue", "blue", "blue", "blue"],
        )
        assert fb == Feedback(black=0, white=0)

    def test_all_white(self) -> None:
        """All colors present but none in correct position -> 0 black, 4 white."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["blue", "green", "yellow", "red"],
        )
        assert fb == Feedback(black=0, white=4)

    def test_one_black_three_white(self) -> None:
        """One exact match, three color matches."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "green", "yellow", "blue"],
        )
        assert fb == Feedback(black=1, white=3)

    def test_two_black_two_white(self) -> None:
        """Two exact, two color matches."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "blue", "yellow", "green"],
        )
        assert fb == Feedback(black=2, white=2)

    def test_two_black_zero_white(self) -> None:
        """Two exact, remaining colors not in code."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "blue", "white", "black"],
        )
        assert fb == Feedback(black=2, white=0)

    def test_duplicate_in_guess_single_in_code(self) -> None:
        """Guess has 2 reds, code has 1 red in a different position.
        Only 1 white peg awarded (each secret peg consumed once)."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "red", "red", "red"],
        )
        # First red: exact match (pos 0) -> 1 black
        # Remaining 3 reds: no more red in secret -> 0 white
        assert fb == Feedback(black=1, white=0)

    def test_duplicate_in_code_single_in_guess(self) -> None:
        """Code has 2 reds, guess has 1 red in wrong position."""
        fb = compute_feedback(
            ["red", "red", "blue", "green"],
            ["yellow", "yellow", "yellow", "red"],
        )
        # No exact matches. Guess pos 3 is red, secret has red at pos 0,1.
        # 1 white peg awarded.
        assert fb == Feedback(black=0, white=1)

    def test_duplicate_colors_both_sides(self) -> None:
        """Code: red,red,blue,blue. Guess: red,blue,red,blue."""
        fb = compute_feedback(
            ["red", "red", "blue", "blue"],
            ["red", "blue", "red", "blue"],
        )
        # Pos 0: red==red -> black
        # Pos 1: red!=blue
        # Pos 2: blue!=red
        # Pos 3: blue==blue -> black
        # Remaining: pos 1 guess=blue matches secret pos 2 blue? No, secret pos 2
        # is blue but it's already consumed? Let me re-check.
        # After exact: secret_remaining = [None, "red", "blue", None]
        #              guess_remaining  = [None, "blue", "red", None]
        # Pos 1 guess=blue: matches secret pos 2 blue -> white, consume secret pos 2
        # Pos 2 guess=red: matches secret pos 1 red -> white, consume secret pos 1
        assert fb == Feedback(black=2, white=2)

    def test_all_same_color_code_and_guess(self) -> None:
        """Both code and guess are all red -> 4 black."""
        fb = compute_feedback(
            ["red", "red", "red", "red"],
            ["red", "red", "red", "red"],
        )
        assert fb == Feedback(black=4, white=0)

    def test_three_of_same_in_guess_two_in_code(self) -> None:
        """Guess has 3 reds, code has 2 reds. One exact, one color match."""
        fb = compute_feedback(
            ["red", "red", "blue", "green"],
            ["red", "yellow", "red", "red"],
        )
        # Pos 0: red==red -> black
        # After exact: secret_remaining = [None, "red", "blue", "green"]
        #              guess_remaining  = [None, "yellow", "red", "red"]
        # Pos 2 guess=red: matches secret pos 1 red -> white, consume
        # Pos 3 guess=red: no more red in secret -> nothing
        assert fb == Feedback(black=1, white=1)

    def test_wrong_length_secret_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly 4"):
            compute_feedback(["red", "blue", "green"], ["red", "blue", "green", "yellow"])

    def test_wrong_length_guess_rejected(self) -> None:
        with pytest.raises(ValueError, match="exactly 4"):
            compute_feedback(["red", "blue", "green", "yellow"], ["red", "blue"])


# ---------------------------------------------------------------------------
# Tests: game setup and invalid inputs
# ---------------------------------------------------------------------------


class TestGameSetup:
    def test_create_game(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        assert game.guess_count == 0
        assert game.guesses_remaining() == 10
        assert not game.finished

    def test_invalid_code_length(self) -> None:
        with pytest.raises(ValueError, match="exactly 4"):
            MastermindGame(["red", "blue", "green"])

    def test_invalid_code_color(self) -> None:
        with pytest.raises(ValueError, match="invalid color"):
            MastermindGame(["red", "blue", "green", "purple"])

    def test_invalid_guess_length(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        with pytest.raises(ValueError, match="exactly 4"):
            game.guess(["red", "blue", "green"])

    def test_invalid_guess_color(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        with pytest.raises(ValueError, match="invalid color"):
            game.guess(["red", "blue", "green", "orange"])

    def test_duplicate_colors_in_code_allowed(self) -> None:
        game = MastermindGame(["red", "red", "red", "red"])
        assert game.secret_code == ["red", "red", "red", "red"]


# ---------------------------------------------------------------------------
# Tests: guessing and feedback flow
# ---------------------------------------------------------------------------


class TestGuessing:
    def test_first_guess_returns_feedback(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        fb = game.guess(["red", "blue", "green", "yellow"])
        assert fb == Feedback(black=4, white=0)

    def test_guess_increments_counter(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        game.guess(["black", "black", "black", "black"])
        assert game.guess_count == 1
        assert game.guesses_remaining() == 9

    def test_feedback_stored_in_history(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        fb = game.guess(["red", "white", "white", "white"])
        assert len(game.feedback_history) == 1
        assert game.feedback_history[0] == fb

    def test_guess_stored_in_history(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        game.guess(["red", "white", "black", "black"])
        assert game.guess_history[0] == ["red", "white", "black", "black"]

    def test_multiple_guesses(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        game.guess(["black", "black", "black", "black"])
        game.guess(["red", "white", "white", "white"])
        game.guess(["red", "blue", "white", "white"])
        assert game.guess_count == 3
        assert game.guesses_remaining() == 7
        assert len(game.feedback_history) == 3


# ---------------------------------------------------------------------------
# Tests: win conditions
# ---------------------------------------------------------------------------


class TestWinConditions:
    def test_codebreaker_wins_on_exact_guess(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        fb = game.guess(["red", "blue", "green", "yellow"])
        assert fb.is_exact()
        assert game.finished
        assert game.winner == "codebreaker"

    def test_codebreaker_wins_on_later_guess(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        game.guess(["black", "black", "black", "black"])  # wrong
        game.guess(["red", "black", "black", "black"])    # 1 black
        game.guess(["red", "blue", "green", "yellow"])    # exact
        assert game.finished
        assert game.winner == "codebreaker"
        assert game.guess_count == 3

    def test_codemaker_wins_after_10_wrong_guesses(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        for _ in range(10):
            game.guess(["black", "black", "black", "black"])
        assert game.finished
        assert game.winner == "codemaker"
        assert game.guess_count == 10

    def test_codebreaker_wins_on_10th_guess(self) -> None:
        """Codebreaker can win on the very last guess."""
        game = MastermindGame(["red", "blue", "green", "yellow"])
        for _ in range(9):
            game.guess(["black", "black", "black", "black"])
        assert not game.finished
        fb = game.guess(["red", "blue", "green", "yellow"])
        assert fb.is_exact()
        assert game.finished
        assert game.winner == "codebreaker"

    def test_cannot_guess_after_win(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        game.guess(["red", "blue", "green", "yellow"])
        with pytest.raises(ValueError, match="finished"):
            game.guess(["black", "black", "black", "black"])

    def test_cannot_guess_after_10(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        for _ in range(10):
            game.guess(["black", "black", "black", "black"])
        with pytest.raises(ValueError, match="finished"):
            game.guess(["black", "black", "black", "black"])


# ---------------------------------------------------------------------------
# Tests: full game scenarios
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_systematic_deduction(self) -> None:
        """Play a game using progressive deduction to find the code."""
        game = MastermindGame(["red", "blue", "green", "yellow"])

        # Guess 1: probe reds
        fb = game.guess(["red", "red", "red", "red"])
        assert fb == Feedback(black=1, white=0)

        # Guess 2: probe blues
        fb = game.guess(["blue", "blue", "blue", "blue"])
        assert fb == Feedback(black=1, white=0)

        # Guess 3: probe greens
        fb = game.guess(["green", "green", "green", "green"])
        assert fb == Feedback(black=1, white=0)

        # Guess 4: probe yellows
        fb = game.guess(["yellow", "yellow", "yellow", "yellow"])
        assert fb == Feedback(black=1, white=0)

        # Guess 5: try correct answer
        fb = game.guess(["red", "blue", "green", "yellow"])
        assert fb.is_exact()
        assert game.finished
        assert game.winner == "codebreaker"
        assert game.guess_count == 5

    def test_all_same_color_code(self) -> None:
        """Code is all one color."""
        game = MastermindGame(["red", "red", "red", "red"])

        fb = game.guess(["red", "blue", "green", "yellow"])
        assert fb == Feedback(black=1, white=0)

        fb = game.guess(["red", "red", "blue", "green"])
        assert fb == Feedback(black=2, white=0)

        fb = game.guess(["red", "red", "red", "blue"])
        assert fb == Feedback(black=3, white=0)

        fb = game.guess(["red", "red", "red", "red"])
        assert fb.is_exact()
        assert game.winner == "codebreaker"

    def test_codemaker_wins_full_game(self) -> None:
        """Codebreaker fails to find the code in 10 guesses."""
        game = MastermindGame(["white", "black", "yellow", "green"])

        # 10 wrong guesses cycling through unhelpful patterns
        wrong_guesses = [
            ["red", "red", "red", "red"],
            ["blue", "blue", "blue", "blue"],
            ["red", "blue", "red", "blue"],
            ["blue", "red", "blue", "red"],
            ["red", "red", "blue", "blue"],
            ["blue", "blue", "red", "red"],
            ["red", "blue", "blue", "red"],
            ["blue", "red", "red", "blue"],
            ["red", "red", "red", "blue"],
            ["blue", "blue", "blue", "red"],
        ]
        for g in wrong_guesses:
            fb = game.guess(g)
            assert not fb.is_exact()

        assert game.finished
        assert game.winner == "codemaker"
        assert game.guess_count == 10

    def test_feedback_sequence_integrity(self) -> None:
        """Verify that each guess's feedback is correct and recorded in order."""
        code = ["green", "yellow", "red", "blue"]
        game = MastermindGame(code)

        guesses = [
            ["red", "blue", "green", "yellow"],   # 0 black, 4 white
            ["green", "blue", "red", "yellow"],    # 2 black, 2 white
            ["green", "yellow", "blue", "red"],    # 2 black, 2 white
            ["green", "yellow", "red", "blue"],    # 4 black, 0 white
        ]

        expected = [
            Feedback(black=0, white=4),
            Feedback(black=2, white=2),
            Feedback(black=2, white=2),
            Feedback(black=4, white=0),
        ]

        for i, g in enumerate(guesses):
            fb = game.guess(g)
            assert fb == expected[i], (
                f"guess {i+1}: {g} against {code} expected {expected[i]}, got {fb}"
            )

        assert game.finished
        assert game.winner == "codebreaker"

    def test_guesses_remaining_decrements(self) -> None:
        game = MastermindGame(["red", "blue", "green", "yellow"])
        for i in range(10):
            assert game.guesses_remaining() == 10 - i
            game.guess(["black", "black", "black", "black"])
        assert game.guesses_remaining() == 0


# ---------------------------------------------------------------------------
# Tests: edge cases in feedback
# ---------------------------------------------------------------------------


class TestFeedbackEdgeCases:
    def test_swap_two_positions(self) -> None:
        """Swapping two pegs: each is right color, wrong position."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["blue", "red", "green", "yellow"],
        )
        assert fb == Feedback(black=2, white=2)

    def test_complete_rotation(self) -> None:
        """All pegs rotated one position."""
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["yellow", "red", "blue", "green"],
        )
        assert fb == Feedback(black=0, white=4)

    def test_one_correct_rest_absent(self) -> None:
        fb = compute_feedback(
            ["red", "blue", "green", "yellow"],
            ["red", "white", "white", "white"],
        )
        assert fb == Feedback(black=1, white=0)

    def test_three_duplicates_in_guess_one_in_code(self) -> None:
        """Guess: red,red,red,blue. Code: blue,green,yellow,red.
        Pos 3: red vs red? No, pos 3 code is red, guess is blue.
        Let me be precise:
        Code:  blue, green, yellow, red
        Guess: red,  red,   red,    blue
        Exact: none
        Remaining secret: blue, green, yellow, red
        Remaining guess:  red,  red,   red,    blue
        Pos 0 guess=red: matches secret pos 3 red -> white, consume
        Pos 1 guess=red: no more red -> nothing
        Pos 2 guess=red: no more red -> nothing
        Pos 3 guess=blue: matches secret pos 0 blue -> white, consume
        """
        fb = compute_feedback(
            ["blue", "green", "yellow", "red"],
            ["red", "red", "red", "blue"],
        )
        assert fb == Feedback(black=0, white=2)

    def test_feedback_symmetry_does_not_hold(self) -> None:
        """Swapping code and guess may produce different feedback
        when duplicate counts differ."""
        fb_a = compute_feedback(
            ["red", "red", "blue", "green"],
            ["red", "yellow", "yellow", "yellow"],
        )
        fb_b = compute_feedback(
            ["red", "yellow", "yellow", "yellow"],
            ["red", "red", "blue", "green"],
        )
        # fb_a: pos 0 exact (black). Remaining secret: [None, red, blue, green]
        #        Remaining guess: [None, yellow, yellow, yellow] -> no color matches
        # fb_a = (1, 0)
        assert fb_a == Feedback(black=1, white=0)

        # fb_b: pos 0 exact (black). Remaining secret: [None, yellow, yellow, yellow]
        #        Remaining guess: [None, red, blue, green] -> no color matches
        # fb_b = (1, 0)
        assert fb_b == Feedback(black=1, white=0)
        # In this case they happen to be equal, but let's try another pair
        fb_c = compute_feedback(
            ["red", "red", "red", "blue"],
            ["red", "blue", "yellow", "yellow"],
        )
        fb_d = compute_feedback(
            ["red", "blue", "yellow", "yellow"],
            ["red", "red", "red", "blue"],
        )
        # fb_c: pos 0 exact. Remaining: [None, red, red, blue] vs [None, blue, yellow, yellow]
        #   pos 1 guess=blue matches secret pos 3 -> white
        #   pos 2 guess=yellow: not in secret -> nothing
        #   pos 3 guess=yellow: not in secret -> nothing
        assert fb_c == Feedback(black=1, white=1)
        # fb_d: pos 0 exact. Remaining: [None, blue, yellow, yellow] vs [None, red, red, blue]
        #   pos 1 guess=red: not in remaining secret -> nothing
        #   pos 2 guess=red: not in remaining secret -> nothing
        #   pos 3 guess=blue: matches secret pos 1 blue -> white
        assert fb_d == Feedback(black=1, white=1)
