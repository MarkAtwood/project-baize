"""Poker foundation tests: draw-to-SetZone and server phase execution.

Covers:
  - Draw from deck to SetZone hand works
  - Deal 2 cards to each player (4 players = 8 cards drawn)
  - Burn 1 card to discard
  - Reveal 3 cards to community (flop)
  - Reveal 1 card (turn, river)
  - Full deal sequence: deal -> preflop -> flop -> turn -> river
  - Error: draw from empty deck
  - Error: invalid server action string

Run with: cd /home/mark/PROJECT/baize/python && python3 -m pytest tests/test_poker_foundations.py -v
"""

from __future__ import annotations

import random

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.error import IllegalActionError
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
    StackZone,
)
from baize.transition import (
    apply_action,
    execute_server_action,
    execute_server_phase,
    parse_server_action,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

TWO_PLAYER_JSON = """{
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

FOUR_PLAYER_JSON = """{
    "game": {
        "name": "Texas Hold'em 4P",
        "players": ["alice", "bob", "charlie", "diana"],
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
        { "name": "preflop", "type": "betting_round" },
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
        { "result": "win", "condition": "false", "name": "showdown" }
    ],
    "authority": {
        "server_only": ["shuffle(deck)", "deal(deck,hand)", "burn(deck,discard)", "reveal(deck,community)"],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)"]
    }
}"""


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


def _two_player_session() -> GameSession:
    definition = GameDefinition.from_json(TWO_PLAYER_JSON)
    session = GameSession(definition)
    for player in session.runtime.players.values():
        chip_zone = player.zones.get("player_chips")
        if isinstance(chip_zone, CounterZone):
            chip_zone.value = 1000
    return session


def _four_player_session() -> GameSession:
    definition = GameDefinition.from_json(FOUR_PLAYER_JSON)
    session = GameSession(definition)
    for player in session.runtime.players.values():
        chip_zone = player.zones.get("player_chips")
        if isinstance(chip_zone, CounterZone):
            chip_zone.value = 1000
    return session


# ===========================================================================
# Draw from deck to SetZone hand
# ===========================================================================


class TestDrawToSetZone:
    """The draw action delivers cards to SetZone player hands."""

    def test_draw_single_card_to_set_zone_hand(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        session.runtime.status = "in_progress"

        hand = session.runtime.players["alice"].zones["hand"]
        assert isinstance(hand, SetZone)
        assert hand.count() == 0

        draw_action = Action(action_type="draw", zone="deck")
        events = apply_action(session, draw_action)

        assert hand.count() == 1
        assert len(events) >= 1
        assert any(e.event_type == "draw" for e in events)

    def test_draw_advances_turn_between_players(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        session.runtime.status = "in_progress"

        alice_hand = session.runtime.players["alice"].zones["hand"]
        bob_hand = session.runtime.players["bob"].zones["hand"]
        assert isinstance(alice_hand, SetZone)
        assert isinstance(bob_hand, SetZone)

        # First draw goes to alice (current player), then turn advances to bob
        apply_action(session, Action(action_type="draw", zone="deck"))
        assert alice_hand.count() == 1

        # Second draw goes to bob (now current player)
        apply_action(session, Action(action_type="draw", zone="deck"))
        assert bob_hand.count() == 1

    def test_draw_decrements_deck(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        session.runtime.status = "in_progress"

        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 52

        apply_action(session, Action(action_type="draw", zone="deck"))
        assert deck.count() == 51

    def test_draw_card_is_valid_component(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        session.runtime.status = "in_progress"

        apply_action(session, Action(action_type="draw", zone="deck"))

        hand = session.runtime.players["alice"].zones["hand"]
        assert isinstance(hand, SetZone)
        cid = hand.components[0]
        comp = session.runtime.components.get(cid)
        assert comp is not None
        assert comp.component_type == "card"
        assert comp.properties["suit"] in SUITS
        assert comp.properties["rank"] in RANKS


# ===========================================================================
# Deal to each player (4 players = 8 cards)
# ===========================================================================


class TestDealToEachPlayer:
    """Server action deal(deck, hand, count:2, to:each_player) deals to all players."""

    def test_deal_2_to_each_of_4_players(self) -> None:
        session = _four_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        events = execute_server_action(
            session, "deal(deck, hand, count:2, to:each_player)"
        )

        # 4 players * 2 cards = 8 draw events
        assert len(events) == 8
        assert all(e.event_type == "draw" for e in events)

        # Each player has exactly 2 cards
        for player_name in ("alice", "bob", "charlie", "diana"):
            hand = session.runtime.players[player_name].zones["hand"]
            assert isinstance(hand, SetZone)
            assert hand.count() == 2

        # Deck lost 8 cards
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 44

    def test_deal_2_to_each_of_2_players(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        events = execute_server_action(
            session, "deal(deck, hand, count:2, to:each_player)"
        )

        assert len(events) == 4
        for player_name in ("alice", "bob"):
            hand = session.runtime.players[player_name].zones["hand"]
            assert isinstance(hand, SetZone)
            assert hand.count() == 2

    def test_dealt_cards_are_unique(self) -> None:
        session = _four_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        execute_server_action(session, "deal(deck, hand, count:2, to:each_player)")

        all_cids: list[int] = []
        for player in session.runtime.players.values():
            hand = player.zones["hand"]
            assert isinstance(hand, SetZone)
            all_cids.extend(c.value for c in hand.components)
        assert len(all_cids) == len(set(all_cids))


# ===========================================================================
# Burn cards to discard
# ===========================================================================


class TestBurnCards:
    """Server action burn(deck, discard, count:N) moves cards to discard."""

    def test_burn_1_card(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        discard = session.runtime.zones["discard"]
        assert isinstance(discard, SetZone)
        assert discard.count() == 0

        events = execute_server_action(session, "burn(deck, discard, count:1)")

        assert len(events) == 1
        assert discard.count() == 1

        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 51

    def test_burn_event_has_detail(self) -> None:
        session = _two_player_session()
        _make_deck(session)

        events = execute_server_action(session, "burn(deck, discard, count:1)")
        assert events[0].detail == "burn"
        assert events[0].player == "server"


# ===========================================================================
# Reveal cards to community
# ===========================================================================


class TestRevealCards:
    """Server action reveal(deck, community, count:N) moves cards to community."""

    def test_reveal_3_cards_flop(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        community = session.runtime.zones["community"]
        assert isinstance(community, SetZone)
        assert community.count() == 0

        events = execute_server_action(session, "reveal(deck, community, count:3)")

        assert len(events) == 3
        assert all(e.event_type == "reveal" for e in events)
        assert community.count() == 3

    def test_reveal_1_card_turn(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        events = execute_server_action(session, "reveal(deck, community, count:1)")
        assert len(events) == 1
        community = session.runtime.zones["community"]
        assert isinstance(community, SetZone)
        assert community.count() == 1

    def test_reveal_events_have_component_ids(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        events = execute_server_action(session, "reveal(deck, community, count:3)")
        for e in events:
            assert e.component_id is not None
            assert e.component_id.startswith("card-")


# ===========================================================================
# Full deal sequence: deal -> flop -> turn -> river
# ===========================================================================


class TestFullDealSequence:
    """Execute all server phases in order and verify final state."""

    def test_full_sequence_2_players(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        deck = session.runtime.zones["deck"]
        community = session.runtime.zones["community"]
        discard = session.runtime.zones["discard"]
        assert isinstance(deck, StackZone)
        assert isinstance(community, SetZone)
        assert isinstance(discard, SetZone)

        # Deal phase: 2 cards to each of 2 players = 4 cards
        deal_events = execute_server_phase(session, "deal")
        assert len(deal_events) == 4
        assert deck.count() == 48

        # Flop: burn 1 + reveal 3 = 4 cards
        flop_events = execute_server_phase(session, "flop")
        assert len(flop_events) == 4  # 1 burn + 3 reveal
        assert community.count() == 3
        assert discard.count() == 1
        assert deck.count() == 44

        # Turn: burn 1 + reveal 1 = 2 cards
        turn_events = execute_server_phase(session, "turn")
        assert len(turn_events) == 2
        assert community.count() == 4
        assert discard.count() == 2
        assert deck.count() == 42

        # River: burn 1 + reveal 1 = 2 cards
        river_events = execute_server_phase(session, "river")
        assert len(river_events) == 2
        assert community.count() == 5
        assert discard.count() == 3
        assert deck.count() == 40

    def test_full_sequence_4_players(self) -> None:
        session = _four_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        deck = session.runtime.zones["deck"]
        community = session.runtime.zones["community"]
        discard = session.runtime.zones["discard"]
        assert isinstance(deck, StackZone)
        assert isinstance(community, SetZone)
        assert isinstance(discard, SetZone)

        # Deal: 2 * 4 = 8 cards
        execute_server_phase(session, "deal")
        assert deck.count() == 44

        # Flop: burn 1 + reveal 3
        execute_server_phase(session, "flop")
        assert deck.count() == 40
        assert community.count() == 3
        assert discard.count() == 1

        # Turn: burn 1 + reveal 1
        execute_server_phase(session, "turn")
        assert deck.count() == 38
        assert community.count() == 4
        assert discard.count() == 2

        # River: burn 1 + reveal 1
        execute_server_phase(session, "river")
        assert deck.count() == 36
        assert community.count() == 5
        assert discard.count() == 3

    def test_total_cards_accounted_for(self) -> None:
        """After full sequence, all 52 cards are in exactly one location."""
        session = _two_player_session()
        _make_deck(session)
        _shuffle_deck(session)

        execute_server_phase(session, "deal")
        execute_server_phase(session, "flop")
        execute_server_phase(session, "turn")
        execute_server_phase(session, "river")

        deck = session.runtime.zones["deck"]
        community = session.runtime.zones["community"]
        discard = session.runtime.zones["discard"]
        assert isinstance(deck, StackZone)
        assert isinstance(community, SetZone)
        assert isinstance(discard, SetZone)

        total = deck.count() + community.count() + discard.count()
        for player in session.runtime.players.values():
            hand = player.zones["hand"]
            assert isinstance(hand, SetZone)
            total += hand.count()

        assert total == 52


# ===========================================================================
# Error cases
# ===========================================================================


class TestErrors:
    """Error handling for draw and server actions."""

    def test_draw_from_empty_deck_raises(self) -> None:
        session = _two_player_session()
        session.runtime.status = "in_progress"
        # Deck is empty (no cards inserted)
        with pytest.raises(IllegalActionError, match="empty"):
            apply_action(session, Action(action_type="draw", zone="deck"))

    def test_server_deal_from_empty_deck_raises(self) -> None:
        session = _two_player_session()
        # Deck is empty
        with pytest.raises(IllegalActionError, match="empty"):
            execute_server_action(
                session, "deal(deck, hand, count:2, to:each_player)"
            )

    def test_invalid_action_string_no_parens(self) -> None:
        with pytest.raises(IllegalActionError, match="invalid server action"):
            parse_server_action("deal deck hand")

    def test_invalid_action_string_empty_verb(self) -> None:
        with pytest.raises(IllegalActionError, match="invalid server action"):
            parse_server_action("(deck, hand)")

    def test_invalid_action_string_mismatched_parens(self) -> None:
        with pytest.raises(IllegalActionError, match="invalid server action"):
            parse_server_action("deal(deck, hand")

    def test_unknown_verb_raises(self) -> None:
        session = _two_player_session()
        _make_deck(session)
        with pytest.raises(IllegalActionError, match="unknown server action verb"):
            execute_server_action(session, "explode(deck)")

    def test_unknown_phase_raises(self) -> None:
        session = _two_player_session()
        with pytest.raises(IllegalActionError, match="unknown phase"):
            execute_server_phase(session, "nonexistent")

    def test_phase_without_server_action_raises(self) -> None:
        session = _two_player_session()
        with pytest.raises(IllegalActionError, match="no server_action"):
            execute_server_phase(session, "showdown")


# ===========================================================================
# Parser unit tests
# ===========================================================================


class TestParseServerAction:
    """Unit tests for the server action string parser."""

    def test_parse_deal_with_all_args(self) -> None:
        p = parse_server_action("deal(deck, hand, count:2, to:each_player)")
        assert p.verb == "deal"
        assert p.positional == ["deck", "hand"]
        assert p.keyword == {"count": "2", "to": "each_player"}

    def test_parse_burn_no_spaces(self) -> None:
        p = parse_server_action("burn(deck,discard,count:1)")
        assert p.verb == "burn"
        assert p.positional == ["deck", "discard"]
        assert p.keyword == {"count": "1"}

    def test_parse_reveal(self) -> None:
        p = parse_server_action("reveal(deck, community, count:3)")
        assert p.verb == "reveal"
        assert p.positional == ["deck", "community"]
        assert p.keyword == {"count": "3"}

    def test_parse_strips_whitespace(self) -> None:
        p = parse_server_action("  deal( deck , hand , count:2 )  ")
        assert p.verb == "deal"
        assert p.positional == ["deck", "hand"]
        assert p.keyword == {"count": "2"}
