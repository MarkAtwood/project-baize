"""Tests for the commit-reveal cryptographic protocol.

Commit-reveal eliminates the need for simultaneous moves in hidden-choice games.
Each player submits SHA-256(choice|nonce) as a commitment, then reveals
(choice, nonce) for verification. Hash commitment makes move order irrelevant.

Tests use RPS as the reference game: two players commit gestures, then reveal.
The engine verifies SHA-256(gesture|nonce) == stored hash before accepting reveals.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Literal

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import ComponentData, ComponentId, GameSession, GridZone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GestureType = Literal["rock", "paper", "scissors"]

BEATS: dict[GestureType, GestureType] = {
    "rock": "scissors",
    "paper": "rock",
    "scissors": "paper",
}


def _load_rps() -> GameDefinition:
    """Load RPS without the simultaneous phase (commit-reveal replaces it)."""
    import json

    path = Path(__file__).parent.parent.parent / "games" / "rock-paper-scissors.json"
    data = json.loads(path.read_text())
    data.pop("phases", None)  # remove simultaneous phase for commit-reveal tests
    return GameDefinition.from_json(json.dumps(data))


def _make_commitment(choice: str, nonce: str) -> str:
    """SHA-256(choice|nonce) as hex string."""
    return hashlib.sha256(f"{choice}|{nonce}".encode()).hexdigest()


def _commit(session: GameSession, player: str, hash_hex: str) -> list:
    """Submit a commit action for the given player."""
    player_names = list(session.runtime.players.keys())
    session.runtime.turn_index = player_names.index(player)
    return _apply(session, Action(action_type="commit", declaration=hash_hex))


def _reveal(
    session: GameSession,
    player: str,
    choice: str,
    nonce: str,
    zone: str = "choice",
) -> list:
    """Submit a reveal action that verifies hash and places component."""
    player_names = list(session.runtime.players.keys())
    session.runtime.turn_index = player_names.index(player)
    return _apply(
        session,
        Action(
            action_type="reveal",
            declaration=choice,
            commitment=nonce,
            component_type=choice,
            to_pos={"zone": zone, "cell": "0,0"},
        ),
    )


def _apply(session: GameSession, action: Action) -> list:
    """Apply action, handling the setup→in_progress transition."""
    from baize.transition import apply_action

    if session.runtime.status == "setup":
        session.runtime.status = "in_progress"
    return apply_action(session, action)


def _read_gesture(session: GameSession, player: str) -> str | None:
    """Read the gesture currently in the player's choice slot."""
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
# Tests: commit action
# ---------------------------------------------------------------------------


class TestCommit:
    """Commit stores a SHA-256 hash in pending_commits."""

    def test_commit_stores_hash(self) -> None:
        session = GameSession(_load_rps())
        nonce = secrets.token_hex(16)
        h = _make_commitment("rock", nonce)
        _commit(session, "P1", h)
        assert session.runtime.pending_commits["P1"] == h

    def test_commit_emits_event(self) -> None:
        session = GameSession(_load_rps())
        h = _make_commitment("paper", "nonce1")
        events = _commit(session, "P1", h)
        commit_events = [e for e in events if e.event_type == "commit"]
        assert len(commit_events) == 1

    def test_double_commit_rejected(self) -> None:
        session = GameSession(_load_rps())
        h1 = _make_commitment("rock", "n1")
        h2 = _make_commitment("paper", "n2")
        _commit(session, "P1", h1)
        with pytest.raises(Exception, match="already has a pending commitment"):
            _commit(session, "P1", h2)

    def test_both_players_can_commit(self) -> None:
        session = GameSession(_load_rps())
        h1 = _make_commitment("rock", "n1")
        h2 = _make_commitment("scissors", "n2")
        _commit(session, "P1", h1)
        _commit(session, "P2", h2)
        assert "P1" in session.runtime.pending_commits
        assert "P2" in session.runtime.pending_commits


# ---------------------------------------------------------------------------
# Tests: reveal action
# ---------------------------------------------------------------------------


class TestReveal:
    """Reveal verifies hash and places the revealed component."""

    def test_reveal_verifies_and_places(self) -> None:
        session = GameSession(_load_rps())
        nonce = "test_nonce_123"
        h = _make_commitment("rock", nonce)
        _commit(session, "P1", h)
        _reveal(session, "P1", "rock", nonce)

        # Commitment cleared
        assert "P1" not in session.runtime.pending_commits
        # Component placed in per-player choice zone
        assert _read_gesture(session, "P1") == "rock"

    def test_wrong_value_rejected(self) -> None:
        session = GameSession(_load_rps())
        nonce = "nonce_abc"
        h = _make_commitment("rock", nonce)
        _commit(session, "P1", h)
        with pytest.raises(Exception, match="commitment verification failed"):
            _reveal(session, "P1", "paper", nonce)  # wrong choice

    def test_wrong_nonce_rejected(self) -> None:
        session = GameSession(_load_rps())
        nonce = "correct_nonce"
        h = _make_commitment("scissors", nonce)
        _commit(session, "P1", h)
        with pytest.raises(Exception, match="commitment verification failed"):
            _reveal(session, "P1", "scissors", "wrong_nonce")

    def test_reveal_without_commit_rejected(self) -> None:
        session = GameSession(_load_rps())
        with pytest.raises(Exception, match="no pending commitment"):
            _reveal(session, "P1", "rock", "nonce")

    def test_reveal_emits_event(self) -> None:
        session = GameSession(_load_rps())
        nonce = "n1"
        _commit(session, "P1", _make_commitment("paper", nonce))
        events = _reveal(session, "P1", "paper", nonce)
        reveal_events = [e for e in events if e.event_type == "reveal"]
        assert len(reveal_events) == 1


# ---------------------------------------------------------------------------
# Tests: full commit-reveal RPS round
# ---------------------------------------------------------------------------


class TestCommitRevealRound:
    """Full RPS round using commit-reveal protocol."""

    def test_full_round_rock_beats_scissors(self) -> None:
        """P1=rock, P2=scissors. Commit-reveal flow, then manual resolution."""
        session = GameSession(_load_rps())
        n1, n2 = secrets.token_hex(16), secrets.token_hex(16)

        # Phase 1: Both commit (order doesn't matter — hashes are opaque)
        _commit(session, "P1", _make_commitment("rock", n1))
        _commit(session, "P2", _make_commitment("scissors", n2))

        # Phase 2: Both reveal (order doesn't matter — committed values are locked)
        _reveal(session, "P1", "rock", n1)
        _reveal(session, "P2", "scissors", n2)

        # Verify placed gestures
        assert _read_gesture(session, "P1") == "rock"
        assert _read_gesture(session, "P2") == "scissors"

        # Resolve: rock beats scissors
        g1, g2 = _read_gesture(session, "P1"), _read_gesture(session, "P2")
        assert g1 is not None and g2 is not None
        assert BEATS[g1] == g2  # rock beats scissors

    def test_full_round_tie(self) -> None:
        """Both pick paper — tie."""
        session = GameSession(_load_rps())
        n1, n2 = "nonce_a", "nonce_b"

        _commit(session, "P1", _make_commitment("paper", n1))
        _commit(session, "P2", _make_commitment("paper", n2))
        _reveal(session, "P1", "paper", n1)
        _reveal(session, "P2", "paper", n2)

        assert _read_gesture(session, "P1") == "paper"
        assert _read_gesture(session, "P2") == "paper"

    def test_p2_commits_first(self) -> None:
        """P2 commits before P1 — order doesn't affect outcome."""
        session = GameSession(_load_rps())
        n1, n2 = "n1", "n2"

        # P2 commits first
        _commit(session, "P2", _make_commitment("scissors", n2))
        _commit(session, "P1", _make_commitment("rock", n1))

        # P2 reveals first
        _reveal(session, "P2", "scissors", n2)
        _reveal(session, "P1", "rock", n1)

        assert _read_gesture(session, "P1") == "rock"
        assert _read_gesture(session, "P2") == "scissors"

    def test_cheating_detected_after_commit(self) -> None:
        """Player commits rock but tries to reveal paper — caught."""
        session = GameSession(_load_rps())
        nonce = "my_nonce"
        _commit(session, "P1", _make_commitment("rock", nonce))

        with pytest.raises(Exception, match="commitment verification failed"):
            _reveal(session, "P1", "paper", nonce)

    def test_state_hash_includes_commits(self) -> None:
        """Pending commits change the state hash."""
        session = GameSession(_load_rps())
        session.runtime.status = "in_progress"
        h1 = session.compute_state_hash()

        session.runtime.pending_commits["P1"] = "abc123"
        h2 = session.compute_state_hash()
        assert h1 != h2


# ---------------------------------------------------------------------------
# Tests: commitment is cryptographically binding
# ---------------------------------------------------------------------------


class TestCryptographicBinding:
    """Verify SHA-256 commitment properties."""

    def test_same_inputs_same_hash(self) -> None:
        h1 = _make_commitment("rock", "nonce42")
        h2 = _make_commitment("rock", "nonce42")
        assert h1 == h2

    def test_different_choice_different_hash(self) -> None:
        h1 = _make_commitment("rock", "same_nonce")
        h2 = _make_commitment("paper", "same_nonce")
        assert h1 != h2

    def test_different_nonce_different_hash(self) -> None:
        h1 = _make_commitment("rock", "nonce_a")
        h2 = _make_commitment("rock", "nonce_b")
        assert h1 != h2

    def test_hash_is_64_hex_chars(self) -> None:
        h = _make_commitment("scissors", "test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Tests: constant-time comparison
# ---------------------------------------------------------------------------


class TestConstantTimeComparison:
    """Verify that the reveal path rejects near-miss hashes correctly.

    These tests exercise the hmac.compare_digest comparison path
    by testing hashes that differ in exactly one character.
    """

    def test_near_miss_single_char_rejected(self) -> None:
        """Hash differing by one hex digit is rejected."""
        session = GameSession(_load_rps())
        nonce = "near_miss_nonce"
        correct_hash = _make_commitment("rock", nonce)

        # Flip the last hex digit
        last = correct_hash[-1]
        flipped = "1" if last == "0" else "0"
        tampered = correct_hash[:-1] + flipped
        assert correct_hash != tampered
        assert sum(a != b for a, b in zip(correct_hash, tampered)) == 1

        _commit(session, "P1", tampered)
        with pytest.raises(Exception, match="commitment verification failed"):
            _reveal(session, "P1", "rock", nonce)

    def test_near_miss_first_char_rejected(self) -> None:
        """Hash differing only in the first character is rejected."""
        session = GameSession(_load_rps())
        nonce = "first_char_nonce"
        correct_hash = _make_commitment("paper", nonce)

        first = correct_hash[0]
        flipped = "1" if first == "0" else "0"
        tampered = flipped + correct_hash[1:]
        assert correct_hash != tampered

        _commit(session, "P1", tampered)
        with pytest.raises(Exception, match="commitment verification failed"):
            _reveal(session, "P1", "paper", nonce)

    def test_uses_hmac_compare_digest(self) -> None:
        """Verify the reveal code path calls hmac.compare_digest."""
        import ast
        import inspect
        from baize import transition

        source = inspect.getsource(transition)
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compare_digest"
        ]
        assert len(calls) >= 1, "hmac.compare_digest not found in transition module"
