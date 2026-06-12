"""Poker showdown resolution tests.

Covers:
  - Winner with best hand gets pot
  - Tie splits pot evenly
  - Tie with odd pot: remainder to first in turn order
  - All-but-one folded: last player wins without showing cards
  - Full game sequence: deal -> bet -> flop -> bet -> turn -> bet -> river -> bet -> showdown
  - Pot amount correct after betting
  - Winner's chips increase by pot amount
  - Losers' chips unchanged at showdown (already deducted during betting)
  - Hand rank names in result
  - Multiple players with different hand ranks
  - Community-only evaluation (both players play the board)
  - Three-way tie split
  - Showdown with no betting state (all players active)
  - Flush beats straight
  - Full house beats flush

Run with:
  cd /home/mark/PROJECT/baize/python && python3 -m pytest tests/test_poker_showdown.py -v
"""

from __future__ import annotations

import random

import pytest

from baize.action import Action
from baize.betting import BettingRoundState
from baize.definition import GameDefinition
from baize.poker import HandRank
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
    StackZone,
)
from baize.showdown import (
    ShowdownResult,
    _card_to_tuple,
    _get_active_players,
    _get_community_cards,
    _get_hand_cards,
    _hand_rank_name,
    resolve_showdown,
)
from baize.transition import apply_action, execute_server_phase


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
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)", "hand_comparison()"]
    }
}"""

THREE_PLAYER_JSON = """{
    "game": {
        "name": "Texas Hold'em 3P",
        "players": ["alice", "bob", "carol"],
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
        "server_only": ["shuffle(deck)", "deal(deck,hand)"],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)"]
    }
}"""


def _make_session(json_str: str, chips: int = 1000) -> GameSession:
    """Create a session with chip counters initialized."""
    definition = GameDefinition.from_json(json_str)
    session = GameSession(definition)
    for player in session.runtime.players.values():
        chip_zone = player.zones.get("player_chips")
        if isinstance(chip_zone, CounterZone):
            chip_zone.value = chips
    return session


def _place_card(
    session: GameSession,
    player: str,
    rank: str,
    suit: str,
) -> ComponentId:
    """Place a specific card into a player's hand zone."""
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=f"card-{rank}-{suit}",
            component_type="card",
            facing="face_down",
            properties={"suit": suit, "rank": rank},
        )
    )
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    hand.set_add(cid)
    return cid


def _place_community(
    session: GameSession,
    cards: list[tuple[str, str]],
) -> None:
    """Place specific cards into the community zone."""
    community = session.runtime.zones["community"]
    assert isinstance(community, SetZone)
    for rank, suit in cards:
        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"card-{rank}-{suit}",
                component_type="card",
                facing="face_up",
                properties={"suit": suit, "rank": rank},
            )
        )
        community.set_add(cid)


def _set_pot(session: GameSession, amount: int) -> None:
    """Set the pot counter to a specific amount."""
    pot = session.runtime.zones.get("pot")
    assert isinstance(pot, CounterZone)
    pot.value = amount


def _get_chips(session: GameSession, player: str) -> int:
    """Get a player's chip count."""
    pstate = session.runtime.players[player]
    chip_zone = pstate.zones.get("player_chips")
    assert isinstance(chip_zone, CounterZone)
    return chip_zone.value


def _init_betting_state(session: GameSession, active: list[str]) -> None:
    """Initialize a betting state with the given active players."""
    bs = BettingRoundState()
    bs.init_round(list(session.runtime.players.keys()))
    # Remove folded players from active list
    bs.active_players = list(active)
    session.runtime.betting_state = bs


def _make_deck(session: GameSession) -> None:
    """Populate the deck with all 52 cards."""
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


# ===========================================================================
# Test: winner with best hand gets entire pot
# ===========================================================================


class TestWinnerGetsPot:
    """The player with the best hand wins the pot."""

    def test_pair_beats_high_card(self) -> None:
        """Alice has a pair of aces, Bob has high card king."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 200)

        # Alice: A-hearts, A-diamonds (pair of aces)
        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "A", "diamonds")

        # Bob: K-hearts, Q-diamonds (high card)
        _place_card(session, "bob", "K", "hearts")
        _place_card(session, "bob", "Q", "diamonds")

        # Community: 2-clubs, 5-spades, 7-hearts, 9-clubs, J-spades
        _place_community(session, [
            ("2", "clubs"), ("5", "spades"), ("7", "hearts"),
            ("9", "clubs"), ("J", "spades"),
        ])

        result = resolve_showdown(session)

        assert result.winners == ["alice"]
        assert result.hand_rank == HandRank.ONE_PAIR
        assert result.pot_awarded == 200
        assert result.awards == {"alice": 200}

    def test_winner_chips_increase_by_pot(self) -> None:
        """Winner's chip counter increases by exactly the pot amount."""
        session = _make_session(TWO_PLAYER_JSON, chips=900)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 200)

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "A", "diamonds")
        _place_card(session, "bob", "K", "hearts")
        _place_card(session, "bob", "Q", "diamonds")
        _place_community(session, [
            ("2", "clubs"), ("5", "spades"), ("7", "hearts"),
            ("9", "clubs"), ("J", "spades"),
        ])

        alice_before = _get_chips(session, "alice")
        resolve_showdown(session)
        alice_after = _get_chips(session, "alice")

        assert alice_after == alice_before + 200

    def test_loser_chips_unchanged_at_showdown(self) -> None:
        """Loser's chips are not modified during showdown (already deducted in betting)."""
        session = _make_session(TWO_PLAYER_JSON, chips=900)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 200)

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "A", "diamonds")
        _place_card(session, "bob", "K", "hearts")
        _place_card(session, "bob", "Q", "diamonds")
        _place_community(session, [
            ("2", "clubs"), ("5", "spades"), ("7", "hearts"),
            ("9", "clubs"), ("J", "spades"),
        ])

        bob_before = _get_chips(session, "bob")
        resolve_showdown(session)
        bob_after = _get_chips(session, "bob")

        assert bob_after == bob_before

    def test_pot_zeroed_after_showdown(self) -> None:
        """Pot is reset to zero after distribution."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 500)

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "A", "diamonds")
        _place_card(session, "bob", "K", "hearts")
        _place_card(session, "bob", "Q", "diamonds")
        _place_community(session, [
            ("2", "clubs"), ("5", "spades"), ("7", "hearts"),
            ("9", "clubs"), ("J", "spades"),
        ])

        resolve_showdown(session)

        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)
        assert pot.value == 0


# ===========================================================================
# Test: tie splits pot
# ===========================================================================


class TestTieSplitsPot:
    """When two players tie, the pot is split evenly."""

    def test_even_split(self) -> None:
        """Two players with identical hands split the pot evenly."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 200)

        # Both players have the same rank pair; community makes it identical
        # Alice: A-hearts, K-clubs
        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "K", "clubs")
        # Bob: A-diamonds, K-spades
        _place_card(session, "bob", "A", "diamonds")
        _place_card(session, "bob", "K", "spades")

        # Community gives both players the same best hand: pair of aces with K kicker
        # Both will form: A, A, K, Q, J as their best 5-card hand
        _place_community(session, [
            ("A", "clubs"), ("Q", "hearts"), ("J", "diamonds"),
            ("3", "clubs"), ("4", "spades"),
        ])

        result = resolve_showdown(session)

        assert len(result.winners) == 2
        assert "alice" in result.winners
        assert "bob" in result.winners
        assert result.awards["alice"] == 100
        assert result.awards["bob"] == 100
        assert result.pot_awarded == 200

    def test_odd_pot_remainder_to_first_in_turn_order(self) -> None:
        """Odd pot remainder goes to first winner in turn order."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 201)  # odd: 201 / 2 = 100 each, remainder 1 to alice

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "K", "clubs")
        _place_card(session, "bob", "A", "diamonds")
        _place_card(session, "bob", "K", "spades")
        _place_community(session, [
            ("A", "clubs"), ("Q", "hearts"), ("J", "diamonds"),
            ("3", "clubs"), ("4", "spades"),
        ])

        result = resolve_showdown(session)

        assert result.awards["alice"] == 101  # first in turn order gets remainder
        assert result.awards["bob"] == 100
        assert sum(result.awards.values()) == 201

    def test_three_way_tie_split(self) -> None:
        """Three-way tie splits pot three ways."""
        session = _make_session(THREE_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob", "carol"])
        _set_pot(session, 300)

        # All three get identical kicker situations via community
        # Each has an ace and king of different suits
        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "K", "clubs")
        _place_card(session, "bob", "A", "diamonds")
        _place_card(session, "bob", "K", "spades")
        _place_card(session, "carol", "A", "clubs")
        _place_card(session, "carol", "K", "hearts")

        # Community: A-spades, Q, J, 3, 4 — everyone makes trips aces with K, Q kickers
        _place_community(session, [
            ("A", "spades"), ("Q", "diamonds"), ("J", "spades"),
            ("3", "hearts"), ("4", "diamonds"),
        ])

        result = resolve_showdown(session)

        assert len(result.winners) == 3
        assert result.awards["alice"] == 100
        assert result.awards["bob"] == 100
        assert result.awards["carol"] == 100

    def test_three_way_tie_odd_pot(self) -> None:
        """Three-way tie with pot not divisible by 3: remainder chips to earliest players."""
        session = _make_session(THREE_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob", "carol"])
        _set_pot(session, 302)  # 302 / 3 = 100 each, remainder 2

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "K", "clubs")
        _place_card(session, "bob", "A", "diamonds")
        _place_card(session, "bob", "K", "spades")
        _place_card(session, "carol", "A", "clubs")
        _place_card(session, "carol", "K", "hearts")

        _place_community(session, [
            ("A", "spades"), ("Q", "diamonds"), ("J", "spades"),
            ("3", "hearts"), ("4", "diamonds"),
        ])

        result = resolve_showdown(session)

        assert sum(result.awards.values()) == 302
        # First two in turn order get the extra chips
        assert result.awards["alice"] == 101
        assert result.awards["bob"] == 101
        assert result.awards["carol"] == 100


# ===========================================================================
# Test: all-but-one folded
# ===========================================================================


class TestLastPlayerStanding:
    """When all but one player folds, the remaining player wins without showing cards."""

    def test_last_player_wins_pot(self) -> None:
        """Single active player wins the entire pot."""
        session = _make_session(TWO_PLAYER_JSON, chips=900)
        _init_betting_state(session, ["bob"])  # alice folded
        _set_pot(session, 200)

        # No cards needed — bob wins by default
        result = resolve_showdown(session)

        assert result.winners == ["bob"]
        assert result.hand_rank is None
        assert result.hand_name == "last player standing"
        assert result.pot_awarded == 200
        assert result.awards == {"bob": 200}
        assert result.hand_values == {}

    def test_last_player_chips_increase(self) -> None:
        """Last standing player's chips increase correctly."""
        session = _make_session(TWO_PLAYER_JSON, chips=800)
        _init_betting_state(session, ["alice"])  # bob folded
        _set_pot(session, 400)

        bob_before = _get_chips(session, "bob")
        alice_before = _get_chips(session, "alice")

        resolve_showdown(session)

        assert _get_chips(session, "alice") == alice_before + 400
        assert _get_chips(session, "bob") == bob_before  # unchanged

    def test_last_standing_in_three_player(self) -> None:
        """In 3-player game, two fold and one wins."""
        session = _make_session(THREE_PLAYER_JSON)
        _init_betting_state(session, ["carol"])  # alice and bob folded
        _set_pot(session, 300)

        result = resolve_showdown(session)

        assert result.winners == ["carol"]
        assert result.pot_awarded == 300


# ===========================================================================
# Test: hand rank names and result structure
# ===========================================================================


class TestHandRankNames:
    """ShowdownResult includes correct hand rank info."""

    def test_flush_beats_straight(self) -> None:
        """Flush beats straight."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 400)

        # Alice: flush (all hearts)
        _place_card(session, "alice", "2", "hearts")
        _place_card(session, "alice", "4", "hearts")

        # Bob: straight (5-6-7-8-9)
        _place_card(session, "bob", "8", "clubs")
        _place_card(session, "bob", "9", "diamonds")

        # Community: 5-hearts, 6-hearts, 7-hearts, J-clubs, Q-spades
        # Alice makes flush: 2h, 4h, 5h, 6h, 7h
        # Bob makes straight: 5, 6, 7, 8, 9
        _place_community(session, [
            ("5", "hearts"), ("6", "hearts"), ("7", "hearts"),
            ("J", "clubs"), ("Q", "spades"),
        ])

        result = resolve_showdown(session)

        assert result.winners == ["alice"]
        assert result.hand_rank == HandRank.FLUSH
        assert result.hand_name == "flush"

    def test_full_house_beats_flush(self) -> None:
        """Full house beats flush."""
        session = _make_session(TWO_PLAYER_JSON)
        _init_betting_state(session, ["alice", "bob"])
        _set_pot(session, 600)

        # Alice: full house (three 10s + pair of 5s)
        _place_card(session, "alice", "10", "hearts")
        _place_card(session, "alice", "10", "diamonds")

        # Bob: flush (all spades)
        _place_card(session, "bob", "2", "spades")
        _place_card(session, "bob", "4", "spades")

        # Community: 10-clubs, 5-hearts, 5-spades, 8-spades, 9-spades
        # Alice: 10h, 10d, 10c, 5h, 5s = full house
        # Bob: 2s, 4s, 5s, 8s, 9s = flush
        _place_community(session, [
            ("10", "clubs"), ("5", "hearts"), ("5", "spades"),
            ("8", "spades"), ("9", "spades"),
        ])

        result = resolve_showdown(session)

        assert result.winners == ["alice"]
        assert result.hand_rank == HandRank.FULL_HOUSE
        assert result.hand_name == "full house"

    def test_hand_rank_name_values(self) -> None:
        """All hand rank names are correct."""
        assert _hand_rank_name(HandRank.HIGH_CARD) == "high card"
        assert _hand_rank_name(HandRank.ONE_PAIR) == "one pair"
        assert _hand_rank_name(HandRank.TWO_PAIR) == "two pair"
        assert _hand_rank_name(HandRank.THREE_OF_A_KIND) == "three of a kind"
        assert _hand_rank_name(HandRank.STRAIGHT) == "straight"
        assert _hand_rank_name(HandRank.FLUSH) == "flush"
        assert _hand_rank_name(HandRank.FULL_HOUSE) == "full house"
        assert _hand_rank_name(HandRank.FOUR_OF_A_KIND) == "four of a kind"
        assert _hand_rank_name(HandRank.STRAIGHT_FLUSH) == "straight flush"
        assert _hand_rank_name(HandRank.ROYAL_FLUSH) == "royal flush"


# ===========================================================================
# Test: no betting state (all players active)
# ===========================================================================


class TestNoBettingState:
    """When no betting state exists, all players are considered active."""

    def test_all_players_active_without_betting_state(self) -> None:
        """Without betting state, all players participate in showdown."""
        session = _make_session(TWO_PLAYER_JSON)
        # No betting state set — both players should be active
        _set_pot(session, 100)

        _place_card(session, "alice", "A", "hearts")
        _place_card(session, "alice", "K", "hearts")
        _place_card(session, "bob", "2", "clubs")
        _place_card(session, "bob", "3", "diamonds")

        _place_community(session, [
            ("5", "spades"), ("7", "hearts"), ("9", "clubs"),
            ("J", "diamonds"), ("Q", "spades"),
        ])

        result = resolve_showdown(session)

        assert result.winners == ["alice"]
        assert len(result.hand_values) == 2


# ===========================================================================
# Test: card conversion helper
# ===========================================================================


class TestCardConversion:
    """The _card_to_tuple helper correctly maps card properties."""

    def test_ace_hearts(self) -> None:
        comp = ComponentData(
            id=ComponentId(0),
            string_id="card-A-hearts",
            component_type="card",
            properties={"rank": "A", "suit": "hearts"},
        )
        assert _card_to_tuple(comp) == (14, "hearts")

    def test_ten_spades(self) -> None:
        comp = ComponentData(
            id=ComponentId(0),
            string_id="card-10-spades",
            component_type="card",
            properties={"rank": "10", "suit": "spades"},
        )
        assert _card_to_tuple(comp) == (10, "spades")

    def test_two_clubs(self) -> None:
        comp = ComponentData(
            id=ComponentId(0),
            string_id="card-2-clubs",
            component_type="card",
            properties={"rank": "2", "suit": "clubs"},
        )
        assert _card_to_tuple(comp) == (2, "clubs")

    def test_jack_diamonds(self) -> None:
        comp = ComponentData(
            id=ComponentId(0),
            string_id="card-J-diamonds",
            component_type="card",
            properties={"rank": "J", "suit": "diamonds"},
        )
        assert _card_to_tuple(comp) == (11, "diamonds")


# ===========================================================================
# Test: full game sequence with betting and showdown
# ===========================================================================


class TestFullGameSequence:
    """End-to-end test: deal -> bet -> community -> bet -> showdown."""

    def test_deal_bet_flop_bet_turn_bet_river_bet_showdown(self) -> None:
        """Full Texas Hold'em hand through all phases to showdown."""
        session = _make_session(TWO_PLAYER_JSON, chips=1000)
        _make_deck(session)
        _shuffle_deck(session, seed=99)
        session.runtime.status = "in_progress"

        # Phase 1: Deal
        execute_server_phase(session, "deal")
        alice_hand = session.runtime.players["alice"].zones["hand"]
        bob_hand = session.runtime.players["bob"].zones["hand"]
        assert isinstance(alice_hand, SetZone)
        assert isinstance(bob_hand, SetZone)
        assert alice_hand.count() == 2
        assert bob_hand.count() == 2

        # Phase 2: Preflop betting — both check
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        session.runtime.betting_state = bs

        apply_action(session, Action(action_type="check"), acting_player="alice")
        apply_action(session, Action(action_type="check"), acting_player="bob")

        # Phase 3: Flop
        execute_server_phase(session, "flop")
        community = session.runtime.zones["community"]
        assert isinstance(community, SetZone)
        assert community.count() == 3

        # Phase 4: Flop betting — both check
        bs2 = BettingRoundState()
        bs2.init_round(["alice", "bob"])
        session.runtime.betting_state = bs2
        apply_action(session, Action(action_type="check"), acting_player="alice")
        apply_action(session, Action(action_type="check"), acting_player="bob")

        # Phase 5: Turn
        execute_server_phase(session, "turn")
        assert community.count() == 4

        # Phase 6: Turn betting — alice raises, bob calls
        bs3 = BettingRoundState()
        bs3.init_round(["alice", "bob"])
        session.runtime.betting_state = bs3
        apply_action(
            session,
            Action(action_type="raise", amount=50),
            acting_player="alice",
        )
        apply_action(
            session,
            Action(action_type="call"),
            acting_player="bob",
        )

        # Phase 7: River
        execute_server_phase(session, "river")
        assert community.count() == 5

        # Phase 8: River betting — both check
        bs4 = BettingRoundState()
        bs4.init_round(["alice", "bob"])
        session.runtime.betting_state = bs4
        apply_action(session, Action(action_type="check"), acting_player="alice")
        apply_action(session, Action(action_type="check"), acting_player="bob")

        # Verify pot has the right amount (each player put in 50 during turn)
        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)
        assert pot.value == 100

        # Phase 9: Showdown
        result = resolve_showdown(session)

        assert len(result.winners) >= 1
        assert result.pot_awarded == 100
        assert sum(result.awards.values()) == 100

        # Verify pot is zeroed
        assert pot.value == 0

        # Verify winner received chips
        for winner in result.winners:
            # Winner should have more than 950 (started with 1000, bet 50, won something)
            assert _get_chips(session, winner) >= 950

    def test_fold_during_betting_wins_pot(self) -> None:
        """When one player folds during betting, the other wins at showdown."""
        session = _make_session(TWO_PLAYER_JSON, chips=1000)
        _make_deck(session)
        _shuffle_deck(session, seed=7)
        session.runtime.status = "in_progress"

        # Deal
        execute_server_phase(session, "deal")

        # Preflop: alice raises, bob folds
        bs = BettingRoundState()
        bs.init_round(["alice", "bob"])
        session.runtime.betting_state = bs

        apply_action(
            session,
            Action(action_type="raise", amount=100),
            acting_player="alice",
        )
        apply_action(
            session,
            Action(action_type="fold"),
            acting_player="bob",
        )

        # Pot should have alice's raise
        pot = session.runtime.zones["pot"]
        assert isinstance(pot, CounterZone)
        pot_amount = pot.value

        # Showdown: only alice is active
        result = resolve_showdown(session)

        assert result.winners == ["alice"]
        assert result.hand_name == "last player standing"
        assert result.pot_awarded == pot_amount
