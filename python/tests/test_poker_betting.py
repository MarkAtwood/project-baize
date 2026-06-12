"""Poker betting round state machine and action tests.

Covers:
  - BettingRoundState initialization and state tracking
  - fold / check / call / raise / all_in action execution via transition.py
  - Betting round completion detection
  - Edge cases: double fold, check with outstanding bet, raise resets acted, etc.

Run with:
  cd /home/mark/PROJECT/baize/python && python3 -m pytest tests/test_poker_betting.py -v
"""

from __future__ import annotations

import pytest

from baize.action import Action
from baize.betting import BettingRoundState
from baize.definition import GameDefinition
from baize.error import IllegalActionError
from baize.runtime import (
    CounterZone,
    GameSession,
)
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Shared fixture: minimal poker definition and session builder
# ---------------------------------------------------------------------------

POKER_JSON = """{
    "game": {
        "name": "Texas Hold'em",
        "players": ["alice", "bob", "carol"],
        "information": "imperfect"
    },
    "zones": {
        "deck":         { "zone_type": "ordered_stack", "capacity": 52, "visibility": "hidden" },
        "community":    { "zone_type": "set", "capacity": 5, "visibility": "public" },
        "discard":      { "zone_type": "set", "visibility": "hidden" },
        "pot":          { "zone_type": "counter", "visibility": "public" },
        "hand":         { "zone_type": "set", "per_player": true, "capacity": 2,
                          "visibility": { "private": "owner" } },
        "player_chips": { "zone_type": "counter", "per_player": true, "visibility": "public" }
    },
    "components": {
        "card": {
            "properties": {
                "suit": ["hearts", "diamonds", "clubs", "spades"],
                "rank": ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
            },
            "facing": "face_down",
            "count": 52
        }
    },
    "turn_order": { "type": "round_robin" },
    "phases": [
        { "name": "preflop", "type": "betting_round" }
    ],
    "betting_round": {
        "actions": ["fold", "check", "call", "raise", "all_in"],
        "ends_when": "all active players have acted and bets are equal"
    },
    "end_conditions": [
        { "result": "win", "condition": "false", "name": "never" }
    ],
    "authority": {
        "server_only": ["shuffle(deck)"],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)"]
    }
}"""


TWO_PLAYER_JSON = """{
    "game": {
        "name": "Heads-Up Poker",
        "players": ["alice", "bob"],
        "information": "imperfect"
    },
    "zones": {
        "deck":         { "zone_type": "ordered_stack", "capacity": 52, "visibility": "hidden" },
        "community":    { "zone_type": "set", "capacity": 5, "visibility": "public" },
        "discard":      { "zone_type": "set", "visibility": "hidden" },
        "pot":          { "zone_type": "counter", "visibility": "public" },
        "hand":         { "zone_type": "set", "per_player": true, "capacity": 2,
                          "visibility": { "private": "owner" } },
        "player_chips": { "zone_type": "counter", "per_player": true, "visibility": "public" }
    },
    "components": {
        "card": { "count": 52 }
    },
    "turn_order": { "type": "round_robin" },
    "phases": [
        { "name": "preflop", "type": "betting_round" }
    ],
    "betting_round": {
        "actions": ["fold", "check", "call", "raise", "all_in"],
        "ends_when": "all active players have acted and bets are equal"
    },
    "end_conditions": [
        { "result": "win", "condition": "false", "name": "never" }
    ],
    "authority": {
        "server_only": [],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)"]
    }
}"""


def _make_session(json_str: str = POKER_JSON, chips: int = 1000) -> GameSession:
    """Create a poker session with players starting with given chip count."""
    defn = GameDefinition.from_json(json_str)
    session = GameSession(defn)
    session.runtime.status = "in_progress"
    for player in session.runtime.players.values():
        chip_zone = player.zones.get("player_chips")
        if isinstance(chip_zone, CounterZone):
            chip_zone.value = chips
    return session


def _chips(session: GameSession, player: str) -> int:
    zone = session.runtime.players[player].zones["player_chips"]
    assert isinstance(zone, CounterZone)
    return zone.value


def _pot(session: GameSession) -> int:
    zone = session.runtime.zones["pot"]
    assert isinstance(zone, CounterZone)
    return zone.value


# ===========================================================================
# BettingRoundState unit tests
# ===========================================================================


class TestBettingRoundStateInit:
    """BettingRoundState initialization and basic state queries."""

    def test_default_state(self) -> None:
        bs = BettingRoundState()
        assert bs.current_bet == 0
        assert bs.contributions == {}
        assert bs.active_players == []
        assert bs.acted == set()
        assert bs.all_in_players == set()

    def test_init_round_sets_players(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob", "carol"])
        assert bs.active_players == ["alice", "bob", "carol"]
        assert bs.contributions == {"alice": 0, "bob": 0, "carol": 0}
        assert bs.current_bet == 0
        assert bs.acted == set()

    def test_players_who_must_act_initially(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        assert set(bs.players_who_must_act()) == {"alice", "bob"}

    def test_players_who_must_act_after_acting(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.acted.add("alice")
        assert bs.players_who_must_act() == ["bob"]

    def test_remaining_active_count(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob", "carol"])
        assert bs.remaining_active_count() == 3
        bs.active_players.remove("carol")
        assert bs.remaining_active_count() == 2


class TestBettingRoundCompletion:
    """Tests for is_round_complete() logic."""

    def test_not_complete_when_nobody_acted(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        assert not bs.is_round_complete()

    def test_complete_when_all_checked(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.acted = {"alice", "bob"}
        assert bs.is_round_complete()

    def test_not_complete_when_contributions_unequal(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.current_bet = 100
        bs.contributions["alice"] = 100
        bs.contributions["bob"] = 50
        bs.acted = {"alice", "bob"}
        assert not bs.is_round_complete()

    def test_complete_when_contributions_match_bet(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.current_bet = 100
        bs.contributions["alice"] = 100
        bs.contributions["bob"] = 100
        bs.acted = {"alice", "bob"}
        assert bs.is_round_complete()

    def test_all_in_player_skipped_for_completion(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.current_bet = 200
        bs.contributions["alice"] = 200
        bs.contributions["bob"] = 50  # all-in with fewer chips
        bs.all_in_players.add("bob")
        bs.acted = {"alice"}
        assert bs.is_round_complete()

    def test_not_complete_after_raise_resets_acted(self) -> None:
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        bs.current_bet = 100
        bs.contributions = {"alice": 100, "bob": 100}
        # bob raises, resetting acted
        bs.current_bet = 200
        bs.contributions["bob"] = 200
        bs.acted = {"bob"}
        assert not bs.is_round_complete()


# ===========================================================================
# Betting actions via transition.py
# ===========================================================================


class TestCheckAction:
    """Check action: valid only when no outstanding bet."""

    def test_check_valid_no_bet(self) -> None:
        session = _make_session()
        events = apply_action(
            session, Action(action_type="check"), acting_player="alice"
        )
        check_events = [e for e in events if e.event_type == "check"]
        assert len(check_events) == 1
        assert check_events[0].player == "alice"

    def test_check_invalid_with_outstanding_bet(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        # alice raises to 100
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        # bob tries to check — should fail
        with pytest.raises(IllegalActionError, match="cannot check"):
            apply_action(
                session, Action(action_type="check"), acting_player="bob"
            )

    def test_check_marks_acted(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="check"), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert "alice" in bs.acted


class TestCallAction:
    """Call action: match the current bet."""

    def test_call_matches_bet(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.contributions["bob"] == 100
        assert _chips(session, "bob") == 900
        assert _pot(session) == 200

    def test_call_nothing_to_call_raises(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        with pytest.raises(IllegalActionError, match="nothing to call"):
            apply_action(
                session, Action(action_type="call"), acting_player="alice"
            )

    def test_call_insufficient_chips_raises(self) -> None:
        session = _make_session(TWO_PLAYER_JSON, chips=50)
        # Give alice enough chips to raise, but bob only has 50
        alice_zone = session.runtime.players["alice"].zones["player_chips"]
        assert isinstance(alice_zone, CounterZone)
        alice_zone.value = 1000
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        # bob has 50 chips, needs 100 to call
        with pytest.raises(IllegalActionError, match="not enough chips to call"):
            apply_action(
                session, Action(action_type="call"), acting_player="bob"
            )

    def test_call_deducts_difference(self) -> None:
        """If player already contributed, call only pays the gap."""
        session = _make_session()
        # alice raises to 50
        apply_action(
            session, Action(action_type="raise", amount=50), acting_player="alice"
        )
        # bob raises to 100
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="bob"
        )
        # alice calls (needs 100 - 50 = 50 more)
        apply_action(
            session, Action(action_type="call"), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.contributions["alice"] == 100
        # alice paid 50 (raise) + 50 (call) = 100 total
        assert _chips(session, "alice") == 900


class TestRaiseAction:
    """Raise action: set a new bet level."""

    def test_raise_sets_current_bet(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=200), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.current_bet == 200

    def test_raise_deducts_chips(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=200), acting_player="alice"
        )
        assert _chips(session, "alice") == 800
        assert _pot(session) == 200

    def test_raise_resets_acted_set(self) -> None:
        session = _make_session()
        # alice checks
        apply_action(
            session, Action(action_type="check"), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert "alice" in bs.acted
        # bob raises — should reset acted, only bob is in acted
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="bob"
        )
        assert bs.acted == {"bob"}

    def test_raise_must_exceed_current_bet(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="must exceed current bet"):
            apply_action(
                session, Action(action_type="raise", amount=50), acting_player="bob"
            )

    def test_raise_equal_to_current_bet_rejected(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="must exceed current bet"):
            apply_action(
                session, Action(action_type="raise", amount=100), acting_player="bob"
            )

    def test_raise_requires_amount(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        with pytest.raises(IllegalActionError, match="raise requires amount"):
            apply_action(
                session, Action(action_type="raise"), acting_player="alice"
            )

    def test_raise_insufficient_chips(self) -> None:
        session = _make_session(TWO_PLAYER_JSON, chips=100)
        with pytest.raises(IllegalActionError, match="not enough chips"):
            apply_action(
                session, Action(action_type="raise", amount=200), acting_player="alice"
            )

    def test_multiple_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="raise", amount=50), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="bob"
        )
        apply_action(
            session, Action(action_type="raise", amount=200), acting_player="carol"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.current_bet == 200
        assert _pot(session) == 350  # 50 + 100 + 200


class TestFoldAction:
    """Fold action: remove player from active list."""

    def test_fold_removes_from_active(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert "alice" not in bs.active_players

    def test_fold_emits_event(self) -> None:
        session = _make_session()
        events = apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        fold_events = [e for e in events if e.event_type == "fold"]
        assert len(fold_events) == 1
        assert fold_events[0].player == "alice"

    def test_fold_already_folded_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="already folded"):
            apply_action(
                session, Action(action_type="fold"), acting_player="alice"
            )

    def test_fold_last_player_wins(self) -> None:
        """In heads-up, if one folds the other is last standing."""
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.remaining_active_count() == 1
        assert bs.active_players == ["bob"]

    def test_fold_does_not_refund_chips(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        # alice raises
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        assert _chips(session, "alice") == 900
        # alice folds (the bet stays in pot)
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        assert _chips(session, "alice") == 900
        assert _pot(session) == 100


class TestAllInAction:
    """All-in action: put all chips in."""

    def test_all_in_more_than_bet_is_raise(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        # bob has 1000 chips, goes all-in: total = 0 + 1000 = 1000 > 100
        apply_action(
            session, Action(action_type="all_in"), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.current_bet == 1000
        assert "bob" in bs.all_in_players
        assert _chips(session, "bob") == 0
        assert _pot(session) == 1100  # alice's 100 + bob's 1000

    def test_all_in_fewer_than_bet_is_call(self) -> None:
        session = _make_session(TWO_PLAYER_JSON, chips=50)
        # Manually set alice to have lots of chips, bob only 50
        alice_zone = session.runtime.players["alice"].zones["player_chips"]
        assert isinstance(alice_zone, CounterZone)
        alice_zone.value = 1000
        apply_action(
            session, Action(action_type="raise", amount=200), acting_player="alice"
        )
        # bob has 50 chips, goes all-in: total = 0 + 50 = 50 < 200
        apply_action(
            session, Action(action_type="all_in"), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        # current bet stays at 200 (bob didn't raise)
        assert bs.current_bet == 200
        assert "bob" in bs.all_in_players
        assert bs.contributions["bob"] == 50
        assert _chips(session, "bob") == 0

    def test_all_in_no_chips_raises(self) -> None:
        session = _make_session(TWO_PLAYER_JSON, chips=0)
        with pytest.raises(IllegalActionError, match="no chips"):
            apply_action(
                session, Action(action_type="all_in"), acting_player="alice"
            )

    def test_all_in_emits_event_with_amount(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        events = apply_action(
            session, Action(action_type="all_in"), acting_player="alice"
        )
        all_in_events = [e for e in events if e.event_type == "all_in"]
        assert len(all_in_events) == 1
        assert all_in_events[0].detail == "1000"


class TestBettingRoundCompletionIntegration:
    """Integration: round completion after sequences of actions."""

    def test_both_check_round_complete(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="check"), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="check"), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.is_round_complete()

    def test_raise_then_call_round_complete(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.is_round_complete()

    def test_raise_round_not_complete(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert not bs.is_round_complete()

    def test_three_player_raise_call_call_complete(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="bob"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="carol"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.is_round_complete()

    def test_re_raise_extends_round(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="raise", amount=50), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="bob"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        # Only bob has acted (raise resets acted)
        assert not bs.is_round_complete()
        # alice and carol must still respond
        must_act = set(bs.players_who_must_act())
        assert must_act == {"alice", "carol"}

    def test_fold_and_call_completes(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="fold"), acting_player="bob"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="carol"
        )
        bs = session.runtime.betting_state
        assert bs is not None
        assert bs.is_round_complete()
        assert bs.remaining_active_count() == 2


class TestFullPreflopSequence:
    """Full preflop betting sequence: blinds then actions."""

    def test_preflop_blinds_raise_call_check(self) -> None:
        """Simulated preflop: post blinds, then bet/call/check."""
        session = _make_session()

        # Manually post blinds by adjusting betting state
        bs = BettingRoundState()
        bs.init_round(["alice", "bob", "carol"])
        # alice posts small blind (50)
        bs.contributions["alice"] = 50
        bs.current_bet = 100
        # bob posts big blind (100)
        bs.contributions["bob"] = 100
        session.runtime.betting_state = bs

        # Manually deduct blind chips
        alice_chips = session.runtime.players["alice"].zones["player_chips"]
        bob_chips = session.runtime.players["bob"].zones["player_chips"]
        pot = session.runtime.zones["pot"]
        assert isinstance(alice_chips, CounterZone)
        assert isinstance(bob_chips, CounterZone)
        assert isinstance(pot, CounterZone)
        alice_chips.value -= 50
        bob_chips.value -= 100
        pot.value += 150

        # carol raises to 200
        apply_action(
            session, Action(action_type="raise", amount=200), acting_player="carol"
        )
        assert bs.current_bet == 200
        assert _chips(session, "carol") == 800

        # alice calls (needs 200 - 50 = 150)
        apply_action(
            session, Action(action_type="call"), acting_player="alice"
        )
        assert bs.contributions["alice"] == 200
        assert _chips(session, "alice") == 800

        # bob calls (needs 200 - 100 = 100)
        apply_action(
            session, Action(action_type="call"), acting_player="bob"
        )
        assert bs.contributions["bob"] == 200
        assert _chips(session, "bob") == 800

        # All have acted and matched bet
        assert bs.is_round_complete()
        assert _pot(session) == 600  # 150 blinds + 200 carol + 150 alice + 100 bob


class TestBettingAfterFold:
    """Folded players cannot act."""

    def test_check_after_fold_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="has folded"):
            apply_action(
                session, Action(action_type="check"), acting_player="alice"
            )

    def test_call_after_fold_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="bob"
        )
        with pytest.raises(IllegalActionError, match="has folded"):
            apply_action(
                session, Action(action_type="call"), acting_player="alice"
            )

    def test_raise_after_fold_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="has folded"):
            apply_action(
                session, Action(action_type="raise", amount=100), acting_player="alice"
            )

    def test_all_in_after_fold_raises(self) -> None:
        session = _make_session()
        apply_action(
            session, Action(action_type="fold"), acting_player="alice"
        )
        with pytest.raises(IllegalActionError, match="has folded"):
            apply_action(
                session, Action(action_type="all_in"), acting_player="alice"
            )


class TestChipAccounting:
    """Verify chips move correctly between players and pot."""

    def test_total_chips_conserved_after_betting(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        total_before = _chips(session, "alice") + _chips(session, "bob") + _pot(session)
        apply_action(
            session, Action(action_type="raise", amount=100), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="call"), acting_player="bob"
        )
        total_after = _chips(session, "alice") + _chips(session, "bob") + _pot(session)
        assert total_before == total_after

    def test_total_chips_conserved_with_all_in(self) -> None:
        session = _make_session(TWO_PLAYER_JSON)
        total_before = _chips(session, "alice") + _chips(session, "bob") + _pot(session)
        apply_action(
            session, Action(action_type="all_in"), acting_player="alice"
        )
        apply_action(
            session, Action(action_type="all_in"), acting_player="bob"
        )
        total_after = _chips(session, "alice") + _chips(session, "bob") + _pot(session)
        assert total_before == total_after
