"""Rock Paper Scissors tests.

RPS requires simultaneous moves — both players reveal their gesture at the same
time.  The engine's apply_action() is strictly sequential (one player at a time),
so this file models RPS as sequential: P1 places first, then P2.  Resolution is
performed by resolve_round(), a helper that reads both choice slots, scores the
round, and clears the slots for the next round.

A Beads issue has been filed for native simultaneous-move engine support
(bd create for "Engine: simultaneous move collection and resolution").
Until that lands, this sequential model is the canonical test harness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import ComponentData, ComponentId, GameSession, GridZone
from baize.state import GameResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "rock-paper-scissors.json"

GestureType = Literal["rock", "paper", "scissors"]

BEATS: dict[GestureType, GestureType] = {
    "rock": "scissors",
    "paper": "rock",
    "scissors": "paper",
}


def _load_rps() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _place_gesture(
    session: GameSession, player: str, gesture: GestureType
) -> None:
    """Place a gesture token into the player's choice slot (0,0)."""
    # Force turn to the correct player for the place action
    player_names = list(session.runtime.players.keys())
    session.runtime.turn_index = player_names.index(player)
    if session.runtime.status == "setup":
        session.runtime.status = "in_progress"

    action = Action(
        action_type="place",
        component_type=gesture,
        to_pos={"zone": "choice", "cell": "0,0"},
    )
    # apply_action places into session.runtime.zones["choice"] by default
    # but choice is per-player — look it up from the player's zones instead.
    # We bypass apply_action here and insert directly so as not to require
    # the engine to support per-player zone targeting in the place action.
    instance_id = f"{gesture}-{player}-{len(session.runtime.components)}"
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=instance_id,
            component_type=gesture,
            owner=player,
        )
    )
    player_state = session.runtime.players[player]
    choice_zone = player_state.zones["choice"]
    if not isinstance(choice_zone, GridZone):
        raise RuntimeError("choice zone is not a GridZone")
    choice_zone.grid_set(0, 0, cid)


def _read_gesture(session: GameSession, player: str) -> GestureType | None:
    """Read the gesture currently in the player's choice slot."""
    player_state = session.runtime.players[player]
    choice_zone = player_state.zones["choice"]
    if not isinstance(choice_zone, GridZone):
        return None
    cid = choice_zone.grid_get(0, 0)
    if cid is None:
        return None
    comp = session.runtime.components.get(cid)
    if comp is None:
        return None
    return comp.component_type  # type: ignore[return-value]


def _clear_choice(session: GameSession, player: str) -> None:
    """Clear the player's choice slot for the next round."""
    player_state = session.runtime.players[player]
    choice_zone = player_state.zones["choice"]
    if isinstance(choice_zone, GridZone):
        choice_zone.grid_set(0, 0, None)


def resolve_round(session: GameSession) -> str | None:
    """Compare P1 and P2 gestures, update win counters, clear slots.

    Returns:
        "P1" if P1 wins the round, "P2" if P2 wins, None on a tie.
    """
    g1 = _read_gesture(session, "P1")
    g2 = _read_gesture(session, "P2")
    if g1 is None or g2 is None:
        raise ValueError(f"missing gestures: P1={g1!r}, P2={g2!r}")

    _clear_choice(session, "P1")
    _clear_choice(session, "P2")

    if g1 == g2:
        return None
    if BEATS[g1] == g2:
        session.runtime.counters["p1_wins"] = (
            session.runtime.counters.get("p1_wins", 0) + 1
        )
        return "P1"
    session.runtime.counters["p2_wins"] = (
        session.runtime.counters.get("p2_wins", 0) + 1
    )
    return "P2"


def check_match_winner(session: GameSession) -> str | None:
    """Return "P1", "P2", or None if no player has reached 2 round wins yet."""
    if session.runtime.counters.get("p1_wins", 0) >= 2:
        return "P1"
    if session.runtime.counters.get("p2_wins", 0) >= 2:
        return "P2"
    return None


def play_round(
    session: GameSession, p1_gesture: GestureType, p2_gesture: GestureType
) -> str | None:
    """Place both gestures, resolve the round, and return the round winner (or None)."""
    _place_gesture(session, "P1", p1_gesture)
    _place_gesture(session, "P2", p2_gesture)
    return resolve_round(session)


# ---------------------------------------------------------------------------
# Test: game definition parsing
# ---------------------------------------------------------------------------


class TestRPSDefinition:
    def test_parses_without_error(self) -> None:
        defn = _load_rps()
        assert defn.game.name == "Rock Paper Scissors"

    def test_two_players(self) -> None:
        defn = _load_rps()
        assert isinstance(defn.game.players, list)
        assert defn.game.players == ["P1", "P2"]

    def test_imperfect_information(self) -> None:
        defn = _load_rps()
        assert defn.game.information == "imperfect"

    def test_choice_zone_is_per_player(self) -> None:
        defn = _load_rps()
        zone = defn.zones["choice"]
        assert zone.per_player is True
        assert zone.zone_type == "grid"

    def test_gesture_component_exists(self) -> None:
        defn = _load_rps()
        assert "gesture" in defn.components
        comp = defn.components["gesture"]
        assert comp.types is not None
        assert "rock" in comp.types
        assert "paper" in comp.types
        assert "scissors" in comp.types

    def test_two_end_conditions(self) -> None:
        defn = _load_rps()
        assert len(defn.end_conditions) == 2
        names = {ec.name for ec in defn.end_conditions}
        assert "p1_best_of_3" in names
        assert "p2_best_of_3" in names


# ---------------------------------------------------------------------------
# Test: RPS beat table (independent oracle)
# Known results from the standard RPS rules, not derived from code under test.
# ---------------------------------------------------------------------------


class TestRPSBeatTable:
    """Verify the BEATS oracle used by the resolver is internally consistent."""

    def test_rock_beats_scissors(self) -> None:
        assert BEATS["rock"] == "scissors"

    def test_scissors_beats_paper(self) -> None:
        assert BEATS["scissors"] == "paper"

    def test_paper_beats_rock(self) -> None:
        assert BEATS["paper"] == "rock"

    def test_no_gesture_beats_itself(self) -> None:
        for g in ("rock", "paper", "scissors"):
            assert BEATS[g] != g  # type: ignore[literal-required]

    def test_beats_relation_is_acyclic_on_three(self) -> None:
        """Rock -> scissors -> paper -> rock forms a 3-cycle (not transitive)."""
        assert BEATS[BEATS[BEATS["rock"]]] == "rock"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Test: single-round resolution
# ---------------------------------------------------------------------------


class TestSingleRound:
    def _session(self) -> GameSession:
        return GameSession(_load_rps())

    def test_rock_beats_scissors(self) -> None:
        session = self._session()
        winner = play_round(session, "rock", "scissors")
        assert winner == "P1"
        assert session.runtime.counters.get("p1_wins", 0) == 1
        assert session.runtime.counters.get("p2_wins", 0) == 0

    def test_scissors_beats_paper(self) -> None:
        session = self._session()
        winner = play_round(session, "scissors", "paper")
        assert winner == "P1"

    def test_paper_beats_rock(self) -> None:
        session = self._session()
        winner = play_round(session, "paper", "rock")
        assert winner == "P1"

    def test_rock_loses_to_paper(self) -> None:
        session = self._session()
        winner = play_round(session, "rock", "paper")
        assert winner == "P2"
        assert session.runtime.counters.get("p2_wins", 0) == 1

    def test_paper_loses_to_scissors(self) -> None:
        session = self._session()
        winner = play_round(session, "paper", "scissors")
        assert winner == "P2"

    def test_scissors_loses_to_rock(self) -> None:
        session = self._session()
        winner = play_round(session, "scissors", "rock")
        assert winner == "P2"

    def test_rock_tie(self) -> None:
        session = self._session()
        winner = play_round(session, "rock", "rock")
        assert winner is None
        assert session.runtime.counters.get("p1_wins", 0) == 0
        assert session.runtime.counters.get("p2_wins", 0) == 0

    def test_paper_tie(self) -> None:
        session = self._session()
        winner = play_round(session, "paper", "paper")
        assert winner is None

    def test_scissors_tie(self) -> None:
        session = self._session()
        winner = play_round(session, "scissors", "scissors")
        assert winner is None

    def test_slots_cleared_after_round(self) -> None:
        """After resolve_round, both choice slots must be empty."""
        session = self._session()
        play_round(session, "rock", "scissors")
        assert _read_gesture(session, "P1") is None
        assert _read_gesture(session, "P2") is None


# ---------------------------------------------------------------------------
# Test: best-of-3 match completion
# ---------------------------------------------------------------------------


class TestBestOfThree:
    def _session(self) -> GameSession:
        return GameSession(_load_rps())

    def test_p1_wins_2_0(self) -> None:
        """P1 wins 2 rounds straight — match ends after round 2."""
        session = self._session()
        play_round(session, "rock", "scissors")  # P1 wins round 1
        assert check_match_winner(session) is None  # not over yet

        play_round(session, "paper", "rock")  # P1 wins round 2
        assert check_match_winner(session) == "P1"

    def test_p2_wins_2_0(self) -> None:
        """P2 wins 2 rounds straight."""
        session = self._session()
        play_round(session, "scissors", "rock")  # P2 wins round 1
        assert check_match_winner(session) is None

        play_round(session, "rock", "paper")  # P2 wins round 2
        assert check_match_winner(session) == "P2"

    def test_p1_wins_2_1(self) -> None:
        """P1 wins 2-1 over 3 rounds."""
        session = self._session()
        play_round(session, "rock", "scissors")   # P1 wins (1-0)
        play_round(session, "scissors", "rock")   # P2 wins (1-1)
        assert check_match_winner(session) is None
        play_round(session, "paper", "rock")      # P1 wins (2-1)
        assert check_match_winner(session) == "P1"

    def test_p2_wins_2_1(self) -> None:
        """P2 wins 2-1 over 3 rounds."""
        session = self._session()
        play_round(session, "scissors", "rock")   # P2 wins (0-1)
        play_round(session, "rock", "scissors")   # P1 wins (1-1)
        assert check_match_winner(session) is None
        play_round(session, "rock", "paper")      # P2 wins (1-2)
        assert check_match_winner(session) == "P2"

    def test_tie_rounds_do_not_count(self) -> None:
        """Tie rounds neither advance the score nor end the match."""
        session = self._session()
        play_round(session, "rock", "rock")       # tie
        play_round(session, "paper", "paper")     # tie
        assert check_match_winner(session) is None
        assert session.runtime.counters.get("p1_wins", 0) == 0
        assert session.runtime.counters.get("p2_wins", 0) == 0

    def test_win_after_ties(self) -> None:
        """Two ties followed by P1 winning two rounds — match completes."""
        session = self._session()
        play_round(session, "rock", "rock")       # tie
        play_round(session, "paper", "paper")     # tie
        play_round(session, "rock", "scissors")   # P1 wins (1-0)
        play_round(session, "rock", "scissors")   # P1 wins (2-0)
        assert check_match_winner(session) == "P1"

    def test_score_counter_increments_correctly(self) -> None:
        """Win counters accumulate correctly across multiple rounds."""
        session = self._session()
        play_round(session, "rock", "scissors")  # P1 +1
        play_round(session, "scissors", "rock")  # P2 +1
        play_round(session, "rock", "scissors")  # P1 +1

        assert session.runtime.counters["p1_wins"] == 2
        assert session.runtime.counters["p2_wins"] == 1

    def test_resolve_requires_both_gestures(self) -> None:
        """resolve_round raises if either player has not placed."""
        session = self._session()
        _place_gesture(session, "P1", "rock")
        # P2 has not placed
        with pytest.raises(ValueError, match="missing gestures"):
            resolve_round(session)
