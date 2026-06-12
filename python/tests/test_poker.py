"""Texas Hold'em poker engine capability assessment tests.

Tests are organized into three tiers:
  TIER 1 — What works today (must pass)
  TIER 2 — What is structurally present but broken (expected failures, documenting gaps)
  TIER 3 — What is entirely missing (skipped, filed as beads)

Run with: cd /home/mark/PROJECT/baize/python && python3 -m pytest tests/test_poker.py -v
"""

from __future__ import annotations

import json
import random

import pytest

from baize.action import Action
from baize.definition import (
    BettingRound,
    GameDefinition,
    Phase,
)
from baize.error import IllegalActionError
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
    StackZone,
)
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Minimal poker definition (parseable, no registry lookup required)
# ---------------------------------------------------------------------------

POKER_JSON = """{
    "game": {
        "name": "Texas Hold'em",
        "players": ["alice", "bob"],
        "information": "imperfect"
    },
    "zones": {
        "deck":         { "zone_type": "ordered_stack", "capacity": 52, "visibility": "hidden" },
        "community":    { "zone_type": "set", "capacity": 5, "visibility": "public" },
        "discard":      { "zone_type": "set", "visibility": "hidden" },
        "pot":          { "zone_type": "counter", "visibility": "public" },
        "hand":         { "zone_type": "set", "per_player": true, "capacity": 2, "visibility": { "private": "owner" } },
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
        { "name": "deal",    "server_action": "deal(deck, hand, count:2, to:each_player)" },
        { "name": "preflop", "type": "betting_round", "starts_with": "player_after(big_blind)" },
        { "name": "flop",    "server_action": ["burn(deck,discard,count:1)", "reveal(deck,community,count:3)"] },
        { "name": "turn",    "server_action": ["burn(deck,discard,count:1)", "reveal(deck,community,count:1)"] },
        { "name": "river",   "server_action": ["burn(deck,discard,count:1)", "reveal(deck,community,count:1)"] },
        { "name": "showdown" }
    ],
    "hand_rankings": [
        "royal_flush", "straight_flush", "four_of_a_kind", "full_house",
        "flush", "straight", "three_of_a_kind", "two_pair", "one_pair", "high_card"
    ],
    "betting_round": {
        "actions": ["fold", "check", "call", "raise", "all_in"],
        "ends_when": "all active players have acted and bets are equal"
    },
    "end_conditions": [
        { "result": "win", "condition": "last_player_standing (all others folded)", "name": "all_fold" },
        { "result": "win", "condition": "false", "name": "showdown" }
    ],
    "authority": {
        "server_only": ["shuffle(deck)", "deal(deck,hand)", "burn(deck,discard)", "reveal(deck,community)"],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)", "hand_comparison()"]
    }
}"""


SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def _make_deck(session: GameSession) -> None:
    """Populate the deck zone with all 52 cards (deterministic order)."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    for suit in SUITS:
        for rank in RANKS:
            cid = session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"card-{rank}-{suit}",
                    component_type="card",
                    facing="face_down",
                    properties={"suit": suit, "rank": rank},
                )
            )
            deck.stack_push(cid)


def _shuffle_deck(session: GameSession, seed: int = 42) -> None:
    """Fisher-Yates shuffle of the deck zone using a seeded RNG."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    rng = random.Random(seed)
    rng.shuffle(deck.components)


def poker_session() -> GameSession:
    definition = GameDefinition.from_json(POKER_JSON)
    session = GameSession(definition)
    # Give each player starting chips
    for player in session.runtime.players.values():
        chip_zone = player.zones.get("player_chips")
        if isinstance(chip_zone, CounterZone):
            chip_zone.value = 1000
    return session


# ===========================================================================
# TIER 1 — Works today
# ===========================================================================


class TestTier1ParseAndSessionCreation:
    """The definition parses and a valid session is created with correct zones."""

    def test_poker_definition_parses(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        assert defn.game.name == "Texas Hold'em"
        assert defn.game.information == "imperfect"

    def test_player_count_range(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        # Two named players
        assert defn.game.players == ["alice", "bob"]

    def test_zones_created_correctly(self) -> None:
        session = poker_session()
        rt = session.runtime

        assert isinstance(rt.zones["deck"], StackZone)
        assert isinstance(rt.zones["community"], SetZone)
        assert isinstance(rt.zones["discard"], SetZone)
        assert isinstance(rt.zones["pot"], CounterZone)

    def test_per_player_hand_zones_created(self) -> None:
        session = poker_session()
        for player_name in ("alice", "bob"):
            pstate = session.runtime.players[player_name]
            assert "hand" in pstate.zones
            assert isinstance(pstate.zones["hand"], SetZone)

    def test_per_player_chip_counters_created(self) -> None:
        session = poker_session()
        for player_name in ("alice", "bob"):
            pstate = session.runtime.players[player_name]
            assert "player_chips" in pstate.zones
            assert isinstance(pstate.zones["player_chips"], CounterZone)

    def test_betting_round_parsed(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        assert defn.betting_round is not None
        assert isinstance(defn.betting_round, BettingRound)
        assert "fold" in defn.betting_round.actions
        assert "check" in defn.betting_round.actions
        assert "call" in defn.betting_round.actions
        assert "raise" in defn.betting_round.actions
        assert "all_in" in defn.betting_round.actions

    def test_hand_rankings_parsed(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        assert defn.hand_rankings[0] == "royal_flush"
        assert defn.hand_rankings[-1] == "high_card"
        assert len(defn.hand_rankings) == 10

    def test_phases_parsed(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        phase_names = [p.name for p in defn.phases]
        assert phase_names == ["deal", "preflop", "flop", "turn", "river", "showdown"]

    def test_preflop_phase_is_betting_round(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        preflop = next(p for p in defn.phases if p.name == "preflop")
        assert preflop.type == "betting_round"

    def test_authority_parsed(self) -> None:
        defn = GameDefinition.from_json(POKER_JSON)
        assert "shuffle(deck)" in defn.authority.server_only
        assert "fold()" in defn.authority.client_verifiable

    def test_initial_pot_is_zero(self) -> None:
        session = poker_session()
        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)
        assert pot.value == 0

    def test_initial_chip_counts(self) -> None:
        session = poker_session()
        for player_name in ("alice", "bob"):
            chip_zone = session.runtime.players[player_name].zones["player_chips"]
            assert isinstance(chip_zone, CounterZone)
            assert chip_zone.value == 1000

    def test_wire_state_serializable(self) -> None:
        session = poker_session()
        wire = session.to_wire_state()
        as_dict = wire._to_dict()
        # Must round-trip through JSON
        json_str = json.dumps(as_dict)
        parsed = json.loads(json_str)
        assert parsed["status"] == "setup"


class TestTier1DeckOperations:
    """Manual deck population and stack operations work."""

    def test_deck_starts_empty(self) -> None:
        session = poker_session()
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 0

    def test_populate_deck_52_cards(self) -> None:
        session = poker_session()
        _make_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 52

    def test_deck_cards_have_properties(self) -> None:
        session = poker_session()
        _make_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        # Top card is the last pushed (spades ace, last in iteration)
        top_cid = deck.components[-1]
        top = session.runtime.components.get(top_cid)
        assert top is not None
        assert top.properties["suit"] == "spades"
        assert top.properties["rank"] == "A"

    def test_shuffle_deck_changes_order(self) -> None:
        session = poker_session()
        _make_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        order_before = list(deck.components)
        _shuffle_deck(session, seed=42)
        order_after = list(deck.components)
        assert order_before != order_after

    def test_shuffle_preserves_count(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 52

    def test_shuffle_preserves_all_cards(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        card_ids = {session.runtime.components.get(c).string_id  # type: ignore[union-attr]
                    for c in deck.components}
        assert len(card_ids) == 52
        # All 52 unique combinations present
        expected = {f"card-{rank}-{suit}" for suit in SUITS for rank in RANKS}
        assert card_ids == expected

    def test_stack_pop_decrements_count(self) -> None:
        session = poker_session()
        _make_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        popped = deck.stack_pop()
        assert popped is not None
        assert deck.count() == 51

    def test_empty_stack_pop_returns_none(self) -> None:
        session = poker_session()
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.stack_pop() is None


class TestTier1ManualDeal:
    """Manually dealing cards into per-player SetZone hands works."""

    def _deal_hole_cards(self, session: GameSession, count: int = 2) -> None:
        """Server-side deal: pop cards from deck into each player's hand SetZone."""
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        for _i in range(count):
            for player in session.runtime.players.values():
                hand = player.zones["hand"]
                assert isinstance(hand, SetZone)
                cid = deck.stack_pop()
                assert cid is not None
                hand.set_add(cid)

    def test_deal_hole_cards_empties_deck_by_4(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        self._deal_hole_cards(session, count=2)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 48  # 52 - 2 players * 2 cards

    def test_each_player_has_two_hole_cards(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        self._deal_hole_cards(session, count=2)
        for player_name in ("alice", "bob"):
            hand = session.runtime.players[player_name].zones["hand"]
            assert isinstance(hand, SetZone)
            assert hand.count() == 2

    def test_hole_cards_are_unique(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        self._deal_hole_cards(session, count=2)
        all_cards: list[ComponentId] = []
        for player in session.runtime.players.values():
            hand = player.zones["hand"]
            assert isinstance(hand, SetZone)
            all_cards.extend(hand.components)
        # No duplicate card ids
        assert len(all_cards) == len(set(c.value for c in all_cards))

    def test_community_reveal_flop(self) -> None:
        """Burn 1, deal 3 to community zone."""
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        self._deal_hole_cards(session, count=2)

        deck = session.runtime.zones["deck"]
        discard = session.runtime.zones["discard"]
        community = session.runtime.zones["community"]
        assert isinstance(deck, StackZone)
        assert isinstance(discard, SetZone)
        assert isinstance(community, SetZone)

        # Burn 1
        burn = deck.stack_pop()
        assert burn is not None
        discard.set_add(burn)

        # Reveal 3
        for _ in range(3):
            cid = deck.stack_pop()
            assert cid is not None
            community.set_add(cid)

        assert community.count() == 3
        assert discard.count() == 1
        assert deck.count() == 44  # 52 - 4 hole - 1 burn - 3 flop

    def test_community_reveal_full_board(self) -> None:
        """Full board: flop (burn+3), turn (burn+1), river (burn+1) = 5 community."""
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)
        self._deal_hole_cards(session, count=2)

        deck = session.runtime.zones["deck"]
        discard = session.runtime.zones["discard"]
        community = session.runtime.zones["community"]
        assert isinstance(deck, StackZone)
        assert isinstance(discard, SetZone)
        assert isinstance(community, SetZone)

        for reveals in (3, 1, 1):
            burn = deck.stack_pop()
            assert burn is not None
            discard.set_add(burn)
            for _ in range(reveals):
                cid = deck.stack_pop()
                assert cid is not None
                community.set_add(cid)

        assert community.count() == 5
        assert discard.count() == 3
        assert deck.count() == 40  # 52 - 4 hole - 3 burns - 5 community


class TestTier1PotAndChipAccounting:
    """CounterZone arithmetic for pot and chip tracking."""

    def test_bet_moves_chips_to_pot(self) -> None:
        session = poker_session()
        alice_chips = session.runtime.players["alice"].zones["player_chips"]
        pot = session.runtime.zones["pot"]
        assert isinstance(alice_chips, CounterZone)
        assert isinstance(pot, CounterZone)

        bet_amount = 100
        alice_chips.value -= bet_amount
        pot.value += bet_amount

        assert alice_chips.value == 900
        assert pot.value == 100

    def test_two_player_preflop_antes(self) -> None:
        session = poker_session()
        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)

        small_blind = 50
        big_blind = 100

        alice_chips = session.runtime.players["alice"].zones["player_chips"]
        bob_chips = session.runtime.players["bob"].zones["player_chips"]
        assert isinstance(alice_chips, CounterZone)
        assert isinstance(bob_chips, CounterZone)

        alice_chips.value -= small_blind
        pot.value += small_blind
        bob_chips.value -= big_blind
        pot.value += big_blind

        assert pot.value == 150
        assert alice_chips.value == 950
        assert bob_chips.value == 900

    def test_pot_distribution_to_winner(self) -> None:
        session = poker_session()
        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)
        pot.value = 500

        winner_chips = session.runtime.players["alice"].zones["player_chips"]
        assert isinstance(winner_chips, CounterZone)
        winner_chips.value += pot.value
        pot.value = 0

        assert winner_chips.value == 1500
        assert pot.value == 0


class TestTier1WireStateIncludesPokerZones:
    """Wire-format state snapshot exposes poker zones correctly."""

    def test_wire_state_has_deck_zone(self) -> None:
        session = poker_session()
        _make_deck(session)
        wire = session.to_wire_state()
        assert "deck" in wire.zones

    def test_wire_state_has_community_zone(self) -> None:
        session = poker_session()
        wire = session.to_wire_state()
        assert "community" in wire.zones

    def test_wire_state_per_player_hand(self) -> None:
        session = poker_session()
        wire = session.to_wire_state()
        for name in ("alice", "bob"):
            assert name in wire.players
            assert wire.players[name].zones is not None
            assert "hand" in wire.players[name].zones  # type: ignore[operator]

    def test_wire_state_hash_stable_on_empty_deck(self) -> None:
        session = poker_session()
        h1 = session.compute_state_hash()
        h2 = session.compute_state_hash()
        assert h1 == h2

    def test_wire_state_hash_changes_after_deal(self) -> None:
        session = poker_session()
        h_before = session.compute_state_hash()
        _make_deck(session)
        h_after = session.compute_state_hash()
        assert h_before != h_after


# ===========================================================================
# TIER 2 — Structurally present but broken (document gaps via xfail)
# ===========================================================================


class TestTier2DrawActionGap:
    """The 'draw' action delivers cards to SetZone hands (fixed)."""

    def test_draw_action_delivers_to_set_zone_hand(self) -> None:
        session = poker_session()
        _make_deck(session)
        session.runtime.status = "in_progress"

        hand = session.runtime.players["alice"].zones["hand"]
        assert isinstance(hand, SetZone)
        assert hand.count() == 0

        draw_action = Action(action_type="draw", zone="deck")
        apply_action(session, draw_action)

        assert hand.count() == 1


class TestTier2BettingActions:
    """fold/check/call/raise/all_in betting actions (implemented)."""

    def test_fold_action_is_handled(self) -> None:
        session = poker_session()
        session.runtime.status = "in_progress"
        fold_action = Action(action_type="fold")
        events = apply_action(session, fold_action)
        assert any(e.event_type == "fold" for e in events)

    def test_check_action_is_handled(self) -> None:
        session = poker_session()
        session.runtime.status = "in_progress"
        check_action = Action(action_type="check")
        events = apply_action(session, check_action)
        assert any(e.event_type == "check" for e in events)

    def test_call_action_is_handled(self) -> None:
        session = poker_session()
        session.runtime.status = "in_progress"
        # Must have an outstanding bet to call
        raise_action = Action(action_type="raise", amount=200)
        apply_action(session, raise_action)
        call_action = Action(action_type="call")
        events = apply_action(session, call_action, acting_player="bob")
        assert any(e.event_type == "call" for e in events)

    def test_raise_action_is_handled(self) -> None:
        session = poker_session()
        session.runtime.status = "in_progress"
        raise_action = Action(action_type="raise", amount=200)
        events = apply_action(session, raise_action)
        assert any(e.event_type == "raise" for e in events)


class TestTier2ServerDealGap:
    """Server phase execution: deal phase populates player hands (fixed)."""

    def test_advance_to_deal_phase_populates_hands(self) -> None:
        session = poker_session()
        _make_deck(session)
        _shuffle_deck(session)

        from baize.transition import execute_server_phase

        execute_server_phase(session, "deal")

        for player_name in ("alice", "bob"):
            hand = session.runtime.players[player_name].zones["hand"]
            assert isinstance(hand, SetZone)
            assert hand.count() == 2


# ===========================================================================
# TIER 3 — Entirely missing (skipped, each maps to a filed bead)
# ===========================================================================


@pytest.mark.skip(reason="GAP: no betting round state machine. Bead: poker-betting-round-fsm")
def test_betting_round_ends_when_bets_equal() -> None:
    """Betting round should end when all active players have matched the current bet."""
    raise NotImplementedError


@pytest.mark.skip(reason="GAP: no hand ranking evaluator. Bead: poker-hand-ranking")
def test_best_hand_from_seven_cards() -> None:
    """Given 2 hole + 5 community cards, select best 5-card hand and rank it."""
    raise NotImplementedError


@pytest.mark.skip(reason="GAP: no showdown resolution. Bead: poker-showdown-resolution")
def test_showdown_winner_gets_pot() -> None:
    """At showdown, player with best hand wins the pot."""
    raise NotImplementedError


@pytest.mark.skip(reason="GAP: no side pot logic. Bead: poker-side-pots")
def test_side_pot_created_on_all_in() -> None:
    """When a player goes all-in with fewer chips than the current bet, a side pot is created."""
    raise NotImplementedError


@pytest.mark.skip(reason="GAP: no community reveal via server action. Bead: poker-server-deal-action")
def test_flop_server_action_burns_and_reveals() -> None:
    """Executing the flop server_action should burn 1 card and reveal 3 to community."""
    raise NotImplementedError
