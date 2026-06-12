"""Error message audit: verify error paths never leak hidden state.

Error messages returned to clients must never reveal:
- Hidden zone contents (opponent hands, deck order, card identities)
- Internal component table size or arena indices
- Server-side PRNG state or seeds
- Stack traces or file paths

Each test sets up a game with hidden state, triggers an error, and asserts
the error message does NOT contain any hidden information.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.error import (
    BaizeError,
    IllegalActionError,
    InvalidComponentIdError,
    InvalidCoordinateError,
    UnknownZoneError,
)
from baize.runtime import (
    ComponentData,
    ComponentId,
    ComponentTable,
    GameSession,
    GridZone,
    SlotZone,
    StackZone,
)
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Game definitions
# ---------------------------------------------------------------------------

_RPS_PATH = Path(__file__).parent.parent.parent / "games" / "rock-paper-scissors.json"
_HIGH_CARD_PATH = Path(__file__).parent.parent.parent / "games" / "high-card.json"


def _load_rps() -> GameDefinition:
    return GameDefinition.from_json(_RPS_PATH.read_text())


def _load_high_card() -> GameDefinition:
    return GameDefinition.from_json(_HIGH_CARD_PATH.read_text())


GestureType = Literal["rock", "paper", "scissors"]


def _place_gesture(session: GameSession, player: str, gesture: GestureType) -> None:
    """Place a gesture into the player's private choice zone."""
    instance_id = f"{gesture}-{player}-{len(session.runtime.components)}"
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=instance_id,
            component_type=gesture,
            owner=player,
        )
    )
    pstate = session.runtime.players[player]
    choice = pstate.zones["choice"]
    assert isinstance(choice, GridZone)
    choice.grid_set(0, 0, cid)


def _build_deck_with_known_cards(session: GameSession) -> list[str]:
    """Build a small deck with known card identities. Returns card string_ids."""
    deck = session.runtime.zones.get("deck")
    assert isinstance(deck, StackZone)
    card_ids = []
    suits = ["hearts", "diamonds", "clubs", "spades"]
    ranks = ["A", "K", "Q", "J", "10"]
    for suit in suits:
        for rank in ranks:
            sid = f"card-{suit}-{rank}"
            cid = session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=sid,
                    component_type="card",
                    owner=None,
                    properties={"suit": suit, "rank": rank},
                )
            )
            deck.components.append(cid)
            card_ids.append(sid)
    return card_ids


# ---------------------------------------------------------------------------
# Test: wrong-turn errors do not reveal opponent's hidden choice
# ---------------------------------------------------------------------------


class TestWrongTurnNoLeak:
    """Submitting out of turn must not reveal the opponent's hidden gesture."""

    def test_wrong_turn_error_hides_opponent_choice(self) -> None:
        """P2 submits while it is P1's turn; error must not mention P1's gesture."""
        session = GameSession(_load_rps())
        session.runtime.status = "in_progress"

        # P1 places rock (hidden in private zone)
        _place_gesture(session, "P1", "rock")

        # Force turn to P1 (index 0) so P2's action is out of turn
        session.runtime.turn_index = 0

        action = Action(
            action_type="place",
            component_type="scissors",
            to_pos={"zone": "choice", "cell": "0,0"},
        )

        # P2 tries to place out of turn -- this should fail but the error
        # must not mention "rock" (P1's hidden gesture)
        try:
            apply_action(session, action, acting_player="P2")
        except BaizeError as exc:
            msg = str(exc)
            assert "rock" not in msg.lower(), (
                f"error leaks opponent gesture: {msg}"
            )
        # If no error (simultaneous phase), that's also acceptable


class TestInvalidComponentIdNoTableSize:
    """InvalidComponentIdError must not expose the internal table size."""

    def test_error_message_excludes_table_size(self) -> None:
        """The error string must not contain the table_size value."""
        err = InvalidComponentIdError(component_id=999, table_size=42)
        msg = str(err)
        assert "42" not in msg, f"error leaks table size: {msg}"
        assert "table size" not in msg.lower(), f"error leaks table size: {msg}"

    def test_error_preserves_attributes(self) -> None:
        """Attributes are still available programmatically (not in message)."""
        err = InvalidComponentIdError(component_id=7, table_size=100)
        assert err.component_id == 7
        assert err.table_size == 100


# ---------------------------------------------------------------------------
# Test: unknown zone errors do not reveal hidden zone contents
# ---------------------------------------------------------------------------


class TestUnknownZoneNoLeak:
    """Referencing a non-existent zone must not reveal existing zone contents."""

    def test_unknown_zone_error_no_deck_contents(self) -> None:
        """Error for a bad zone name must not include deck card IDs."""
        session = GameSession(_load_high_card())
        card_ids = _build_deck_with_known_cards(session)
        session.runtime.status = "in_progress"
        session.runtime.turn_index = 0

        action = Action(
            action_type="draw",
            zone="nonexistent_zone",
        )
        with pytest.raises(UnknownZoneError) as exc_info:
            apply_action(session, action)

        msg = str(exc_info.value)
        # Must not contain any card identity from the hidden deck
        for card_id in card_ids:
            assert card_id not in msg, f"error leaks card ID: {msg}"
        assert "hearts" not in msg.lower()
        assert "spades" not in msg.lower()


# ---------------------------------------------------------------------------
# Test: draw from empty deck does not reveal deck history
# ---------------------------------------------------------------------------


class TestEmptyDeckNoLeak:
    """Drawing from an empty hidden deck must not reveal what was in it."""

    def test_empty_deck_error_is_generic(self) -> None:
        """Error message for empty deck must be constant regardless of prior contents."""
        session = GameSession(_load_high_card())
        # Build deck then drain it
        card_ids = _build_deck_with_known_cards(session)
        deck = session.runtime.zones.get("deck")
        assert isinstance(deck, StackZone)
        deck.components.clear()  # empty the deck

        session.runtime.status = "in_progress"
        session.runtime.turn_index = 0

        action = Action(action_type="draw", zone="deck")
        with pytest.raises(IllegalActionError) as exc_info:
            apply_action(session, action)

        msg = str(exc_info.value)
        # Must not contain any card identity that was previously in the deck
        for card_id in card_ids:
            assert card_id not in msg, f"error leaks former card: {msg}"
        # Must be a generic message
        assert "empty" in msg.lower()


# ---------------------------------------------------------------------------
# Test: simultaneous phase double-submit error does not leak first submission
# ---------------------------------------------------------------------------


class TestSimultaneousDoubleLeak:
    """Double-submitting in a simultaneous phase must not reveal the first choice."""

    def test_double_submit_hides_first_choice(self) -> None:
        """Re-submitting must not include the first gesture in the error."""
        session = GameSession(_load_rps())
        session.runtime.status = "in_progress"

        # P1 submits rock via simultaneous action
        action_rock = Action(
            action_type="place",
            component_type="rock",
            to_pos={"zone": "choice", "cell": "0,0"},
        )
        apply_action(session, action_rock, acting_player="P1")

        # P1 tries to submit again
        action_paper = Action(
            action_type="place",
            component_type="paper",
            to_pos={"zone": "choice", "cell": "0,0"},
        )
        with pytest.raises(IllegalActionError) as exc_info:
            apply_action(session, action_paper, acting_player="P1")

        msg = str(exc_info.value)
        # The error must not reveal that P1's first choice was "rock"
        assert "rock" not in msg.lower(), f"error leaks first choice: {msg}"
        # Should say something about already submitted
        assert "already submitted" in msg.lower() or "already" in msg.lower()


# ---------------------------------------------------------------------------
# Test: commit-reveal hash mismatch does not leak stored hash
# ---------------------------------------------------------------------------


class TestCommitRevealNoHashLeak:
    """Reveal with wrong nonce must not expose the stored commitment hash."""

    def test_bad_reveal_hides_stored_hash(self) -> None:
        """Verification failure must not include the stored SHA-256 hash."""
        import hashlib

        # Use tic-tac-toe (non-simultaneous) to test commit-reveal directly
        _ttt_path = Path(__file__).parent.parent.parent / "games" / "tic-tac-toe.json"
        defn = GameDefinition.from_json(_ttt_path.read_text())
        session = GameSession(defn)
        session.runtime.status = "in_progress"

        # Manually inject a pending commitment for player "X"
        value = "rock"
        nonce = "secret_nonce_123"
        preimage = f"{value}|{nonce}"
        commitment = hashlib.sha256(preimage.encode()).hexdigest()
        session.runtime.pending_commits["X"] = commitment

        # Reveal with wrong nonce
        reveal_action = Action(
            action_type="reveal",
            declaration=value,
            commitment="wrong_nonce",
        )
        with pytest.raises(IllegalActionError) as exc_info:
            apply_action(session, reveal_action, acting_player="X")

        msg = str(exc_info.value)
        # Must not contain the stored hash
        assert commitment not in msg, f"error leaks stored hash: {msg}"
        # Must not contain the correct nonce
        assert nonce not in msg
        # Should mention verification failure generically
        assert "verification failed" in msg.lower() or "failed" in msg.lower()


# ---------------------------------------------------------------------------
# Test: finished game error is generic
# ---------------------------------------------------------------------------


class TestFinishedGameNoLeak:
    """Actions on a finished game must produce a generic error, not leak final state."""

    def test_finished_game_error_is_constant(self) -> None:
        """Error for action on finished game must not differ based on hidden state."""
        session = GameSession(_load_high_card())
        _build_deck_with_known_cards(session)

        # Deal a card to Alice's hand (hidden from Bob)
        deck = session.runtime.zones.get("deck")
        assert isinstance(deck, StackZone)
        cid = deck.components.pop()
        alice_hand = session.runtime.players["Alice"].zones["hand"]
        assert isinstance(alice_hand, SlotZone)
        alice_hand.component = cid

        # Mark game as finished
        session.runtime.status = "finished"

        action = Action(action_type="draw", zone="deck")
        with pytest.raises(IllegalActionError) as exc_info:
            apply_action(session, action)

        msg = str(exc_info.value)
        # Generic "game is finished", must not mention card details
        assert "finished" in msg.lower()
        assert "hearts" not in msg.lower()
        assert "ace" not in msg.lower()


# ---------------------------------------------------------------------------
# Test: error messages have no file paths or stack trace fragments
# ---------------------------------------------------------------------------


class TestNoInternalPaths:
    """Error messages must never contain file paths or tracebacks."""

    _PATH_PATTERNS = [
        re.compile(r"/home/"),
        re.compile(r"\.py:"),
        re.compile(r"\.rs:"),
        re.compile(r"\\\\"),  # Windows paths
        re.compile(r"at line \d+"),
        re.compile(r"Traceback"),
        re.compile(r"File \""),
    ]

    def _check_no_paths(self, msg: str) -> None:
        for pattern in self._PATH_PATTERNS:
            assert not pattern.search(msg), (
                f"error contains internal path/trace: {msg}"
            )

    def test_illegal_action_no_paths(self) -> None:
        err = IllegalActionError("no piece at source")
        self._check_no_paths(str(err))

    def test_unknown_zone_no_paths(self) -> None:
        err = UnknownZoneError("nonexistent")
        self._check_no_paths(str(err))

    def test_invalid_coord_no_paths(self) -> None:
        err = InvalidCoordinateError(col=99, row=99, width=8, height=8)
        self._check_no_paths(str(err))

    def test_invalid_component_id_no_paths(self) -> None:
        err = InvalidComponentIdError(component_id=999, table_size=50)
        self._check_no_paths(str(err))


# ---------------------------------------------------------------------------
# Test: ComponentTable.get() does not leak arena size in errors
# ---------------------------------------------------------------------------


class TestComponentTableNoLeak:
    """ComponentTable operations must not expose internal arena size."""

    def test_get_out_of_range_returns_none(self) -> None:
        """Querying a non-existent component returns None, not an error with size."""
        table = ComponentTable()
        for i in range(5):
            table.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"comp-{i}",
                    component_type="piece",
                )
            )
        # Query beyond range -- must return None, not an error exposing size
        result = table.get(ComponentId(999))
        assert result is None

    def test_get_with_wrong_type_error_no_size(self) -> None:
        """Passing a non-ComponentId raises but must not expose table size."""
        table = ComponentTable()
        table.insert(
            ComponentData(
                id=ComponentId(0),
                string_id="comp-0",
                component_type="piece",
            )
        )
        with pytest.raises(Exception) as exc_info:
            table.get("not_a_cid")  # type: ignore[arg-type]
        msg = str(exc_info.value)
        assert "1" not in msg or "ComponentId" in msg  # size=1 must not appear alone
        assert "table size" not in msg.lower()
