"""Tests for simultaneous move collection and resolution.

When a phase has simultaneous=true, apply_action buffers each player's
action. When all players have submitted, it resolves by applying each
action in player order, then advances the turn.

Uses RPS as the reference game since it now declares a simultaneous phase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession, GridZone
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "rock-paper-scissors.json"

GestureType = Literal["rock", "paper", "scissors"]


def _load_rps() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _place_action(gesture: GestureType) -> Action:
    return Action(
        action_type="place",
        component_type=gesture,
        to_pos={"zone": "choice", "cell": "0,0"},
    )


def _read_gesture(session: GameSession, player: str) -> str | None:
    player_state = session.runtime.players[player]
    choice_zone = player_state.zones["choice"]
    if not isinstance(choice_zone, GridZone):
        return None
    cid = choice_zone.grid_get(0, 0)
    if cid is None:
        return None
    comp = session.runtime.components.get(cid)
    return comp.component_type if comp is not None else None


# ---------------------------------------------------------------------------
# Tests: phase detection
# ---------------------------------------------------------------------------


class TestPhaseDetection:
    """The engine detects simultaneous phases from the game definition."""

    def test_rps_has_simultaneous_phase(self) -> None:
        defn = _load_rps()
        assert len(defn.phases) > 0
        assert defn.phases[0].simultaneous is True

    def test_rps_phase_named_choose(self) -> None:
        defn = _load_rps()
        assert defn.phases[0].name == "choose"


# ---------------------------------------------------------------------------
# Tests: buffering
# ---------------------------------------------------------------------------


class TestBuffering:
    """Actions are buffered in simultaneous phases, not applied immediately."""

    def test_first_submit_buffers(self) -> None:
        session = GameSession(_load_rps())
        events = apply_action(session, _place_action("rock"), acting_player="P1")

        # Action is buffered, not applied
        assert "P1" in session.runtime.simultaneous_actions
        assert _read_gesture(session, "P1") is None  # not placed yet

        # Got an action_submitted event but no turn_advance
        event_types = [e.event_type for e in events]
        assert "action_submitted" in event_types
        assert "turn_advance" not in event_types

    def test_second_submit_triggers_resolution(self) -> None:
        session = GameSession(_load_rps())
        apply_action(session, _place_action("rock"), acting_player="P1")
        events = apply_action(session, _place_action("scissors"), acting_player="P2")

        # Buffer cleared after resolution
        assert len(session.runtime.simultaneous_actions) == 0

        # Both gestures placed
        assert _read_gesture(session, "P1") == "rock"
        assert _read_gesture(session, "P2") == "scissors"

        # Resolution emits place events and turn_advance
        event_types = [e.event_type for e in events]
        assert "action_submitted" in event_types
        assert "place" in event_types
        assert "turn_advance" in event_types

    def test_duplicate_submit_rejected(self) -> None:
        session = GameSession(_load_rps())
        apply_action(session, _place_action("rock"), acting_player="P1")
        with pytest.raises(Exception, match="already submitted"):
            apply_action(session, _place_action("paper"), acting_player="P1")

    def test_unknown_player_rejected(self) -> None:
        session = GameSession(_load_rps())
        with pytest.raises(Exception, match="unknown player"):
            apply_action(session, _place_action("rock"), acting_player="P3")


# ---------------------------------------------------------------------------
# Tests: resolution order
# ---------------------------------------------------------------------------


class TestResolutionOrder:
    """Actions resolve in player definition order, regardless of submit order."""

    def test_p2_submits_first_p1_resolves_first(self) -> None:
        session = GameSession(_load_rps())
        # P2 submits first
        apply_action(session, _place_action("scissors"), acting_player="P2")
        events = apply_action(session, _place_action("rock"), acting_player="P1")

        # Both placed
        assert _read_gesture(session, "P1") == "rock"
        assert _read_gesture(session, "P2") == "scissors"

        # Place events should be in player order (P1 first)
        place_events = [e for e in events if e.event_type == "place"]
        assert len(place_events) == 2
        # P1's place event comes first because resolution uses player order
        assert place_events[0].player == "P1"
        assert place_events[1].player == "P2"


# ---------------------------------------------------------------------------
# Tests: state hash
# ---------------------------------------------------------------------------


class TestStateHash:
    """Buffered actions change the state hash."""

    def test_buffer_changes_hash(self) -> None:
        session = GameSession(_load_rps())
        session.runtime.status = "in_progress"
        h1 = session.compute_state_hash()

        session.runtime.simultaneous_actions["P1"] = {"action_type": "place"}
        h2 = session.compute_state_hash()
        assert h1 != h2


# ---------------------------------------------------------------------------
# Tests: non-simultaneous games unaffected
# ---------------------------------------------------------------------------


class TestNonSimultaneousUnaffected:
    """Games without simultaneous phases work exactly as before."""

    def test_tic_tac_toe_unchanged(self) -> None:
        from pathlib import Path

        ttt_path = Path(__file__).parent.parent.parent / "games" / "tic-tac-toe.json"
        defn = GameDefinition.from_json(ttt_path.read_text())
        session = GameSession(defn)

        events = apply_action(
            session,
            Action(
                action_type="place",
                component_type="X",
                to_pos={"zone": "board", "cell": "1,1"},
            ),
        )
        event_types = [e.event_type for e in events]
        assert "place" in event_types
        assert "turn_advance" in event_types
        # No buffering happened
        assert len(session.runtime.simultaneous_actions) == 0
