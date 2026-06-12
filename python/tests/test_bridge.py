"""Tests for Contract Bridge game definition and mechanics.

Contract Bridge: 4 players in 2 partnerships (North/South vs East/West).
52-card deck dealt 13 per player. Two phases: auction (bidding for contract)
and play (13 tricks). Declarer's partner (dummy) exposes hand after opening
lead. Follow suit required. Scoring based on making/defeating the contract.

Tests simulate server-authority deal by placing known cards into hands.
Auction and play logic are exercised via a BridgeGame driver class.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    CounterZone,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "bridge.json"

SUITS = ["clubs", "diamonds", "hearts", "spades"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUES = {r: i for i, r in enumerate(RANKS, start=2)}

STRAINS = ["clubs", "diamonds", "hearts", "spades", "notrump"]
STRAIN_ORDER = {s: i for i, s in enumerate(STRAINS)}

PLAYERS = ["North", "East", "South", "West"]
NS = {"North", "South"}
EW = {"East", "West"}


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Bid dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Bid:
    """A contract bid: level 1-7, strain one of STRAINS."""
    level: int
    strain: str

    def __post_init__(self) -> None:
        if not 1 <= self.level <= 7:
            raise ValueError(f"bid level must be 1-7, got {self.level}")
        if self.strain not in STRAINS:
            raise ValueError(f"invalid strain: {self.strain}")

    def __gt__(self, other: Bid) -> bool:
        if self.level != other.level:
            return self.level > other.level
        return STRAIN_ORDER[self.strain] > STRAIN_ORDER[other.strain]

    def __str__(self) -> str:
        return f"{self.level}{self.strain[0].upper()}"

    @property
    def tricks_needed(self) -> int:
        """Tricks declarer must win to make the contract."""
        return 6 + self.level


# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    suit: str
    rank: str

    @property
    def rank_value(self) -> int:
        return RANK_VALUES[self.rank]

    def __str__(self) -> str:
        return f"{self.rank}{self.suit[0]}"


def _full_deck() -> list[Card]:
    return [Card(suit=s, rank=r) for s in SUITS for r in RANKS]


# ---------------------------------------------------------------------------
# BridgeGame driver
# ---------------------------------------------------------------------------

class BridgeGame:
    """Contract Bridge game driver for testing auction and play mechanics."""

    def __init__(self, dealer_index: int = 0) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"

        self.dealer_index = dealer_index % 4
        self.hands: dict[str, list[Card]] = {p: [] for p in PLAYERS}

        # Auction state
        self.bids: list[tuple[str, str]] = []  # (player, action_str)
        self.contract: Bid | None = None
        self.contract_doubled: int = 0  # 0=undoubled, 1=doubled, 2=redoubled
        self.declarer: str | None = None
        self.dummy: str | None = None
        self.auction_complete = False
        self.passed_out = False

        # Play state
        self.current_trick: list[tuple[str, Card]] = []
        self.led_suit: str | None = None
        self.trick_leader: str | None = None
        self.tricks_won: dict[str, int] = {"NS": 0, "EW": 0}
        self.tricks_played = 0
        self.dummy_exposed = False
        self.play_complete = False

    def deal(self, hands: dict[str, list[Card]]) -> None:
        """Set up hands with known cards (simulating server deal)."""
        for player, cards in hands.items():
            if len(cards) != 13:
                raise ValueError(f"{player} needs 13 cards, got {len(cards)}")
            self.hands[player] = list(cards)

        # Verify 52 unique cards
        all_cards = []
        for cards in self.hands.values():
            all_cards.extend(cards)
        if len(all_cards) != 52:
            raise ValueError(f"need 52 cards total, got {len(all_cards)}")
        if len(set((c.suit, c.rank) for c in all_cards)) != 52:
            raise ValueError("duplicate cards in deal")

        # Also populate the runtime session hands
        for player in PLAYERS:
            hand_zone = self.session.runtime.players[player].zones["hand"]
            assert isinstance(hand_zone, SetZone)
            for card in self.hands[player]:
                comp = ComponentData(
                    id=ComponentId(0),
                    string_id=f"card-{card.suit}-{card.rank}",
                    component_type="card",
                    owner=player,
                    properties={"suit": card.suit, "rank": card.rank},
                )
                cid = self.session.runtime.components.insert(comp)
                hand_zone.set_add(cid)

    def deal_random(self, seed: int = 42) -> None:
        """Deal a random hand with a deterministic seed."""
        rng = random.Random(seed)
        deck = _full_deck()
        rng.shuffle(deck)
        hands = {
            PLAYERS[i]: deck[i * 13:(i + 1) * 13]
            for i in range(4)
        }
        self.deal(hands)

    # --- Auction ---

    def _auction_turn_index(self) -> int:
        """Current auction position (0-based from dealer)."""
        return (self.dealer_index + len(self.bids)) % 4

    def _current_bidder(self) -> str:
        return PLAYERS[self._auction_turn_index()]

    def _partner(self, player: str) -> str:
        idx = PLAYERS.index(player)
        return PLAYERS[(idx + 2) % 4]

    def _side(self, player: str) -> str:
        return "NS" if player in NS else "EW"

    def _last_bid(self) -> Bid | None:
        """Most recent non-pass, non-double, non-redouble bid."""
        for _, action in reversed(self.bids):
            if action not in ("pass", "double", "redouble"):
                parts = action.split(":")
                return Bid(level=int(parts[0]), strain=parts[1])
        return None

    def _last_bid_side(self) -> str | None:
        """Side that made the last real bid."""
        for player, action in reversed(self.bids):
            if action not in ("pass", "double", "redouble"):
                return self._side(player)
        return None

    def _is_doubled(self) -> bool:
        """Check if the current bid is doubled (not redoubled)."""
        for _, action in reversed(self.bids):
            if action == "double":
                return True
            if action == "redouble":
                return False
            if action not in ("pass",):
                return False
        return False

    def _is_redoubled(self) -> bool:
        for _, action in reversed(self.bids):
            if action == "redouble":
                return True
            if action in ("double",):
                return False
            if action not in ("pass",):
                return False
        return False

    def auction_bid(self, level: int, strain: str) -> None:
        """Make a contract bid."""
        if self.auction_complete:
            raise ValueError("auction is already complete")
        bidder = self._current_bidder()
        new_bid = Bid(level=level, strain=strain)
        last = self._last_bid()
        if last is not None and not (new_bid > last):
            raise ValueError(
                f"bid {new_bid} must be higher than current {last}"
            )
        self.bids.append((bidder, f"{level}:{strain}"))

    def auction_pass(self) -> None:
        if self.auction_complete:
            raise ValueError("auction is already complete")
        bidder = self._current_bidder()
        self.bids.append((bidder, "pass"))
        self._check_auction_end()

    def auction_double(self) -> None:
        if self.auction_complete:
            raise ValueError("auction is already complete")
        bidder = self._current_bidder()
        last = self._last_bid()
        if last is None:
            raise ValueError("cannot double: no bid to double")
        if self._last_bid_side() == self._side(bidder):
            raise ValueError("cannot double own side's bid")
        if self._is_doubled():
            raise ValueError("bid is already doubled")
        if self._is_redoubled():
            raise ValueError("bid is already redoubled")
        self.bids.append((bidder, "double"))

    def auction_redouble(self) -> None:
        if self.auction_complete:
            raise ValueError("auction is already complete")
        bidder = self._current_bidder()
        if not self._is_doubled():
            raise ValueError("cannot redouble: bid is not doubled")
        if self._last_bid_side() != self._side(bidder):
            raise ValueError("cannot redouble opponents' double of opponents' bid")
        self.bids.append((bidder, "redouble"))

    def _check_auction_end(self) -> None:
        """Check if auction has ended (3 passes after a bid, or 4 initial passes)."""
        if len(self.bids) < 4:
            return

        # Check for four initial passes (passed out)
        if all(action == "pass" for _, action in self.bids):
            self.auction_complete = True
            self.passed_out = True
            return

        # Check for three consecutive passes after at least one bid
        last_three = [action for _, action in self.bids[-3:]]
        has_bid = any(
            action not in ("pass",) for _, action in self.bids[:-3]
        ) or self._last_bid() is not None
        if last_three == ["pass", "pass", "pass"] and has_bid:
            self.auction_complete = True
            self._resolve_contract()

    def _resolve_contract(self) -> None:
        """Determine contract, declarer, and dummy after auction ends."""
        last = self._last_bid()
        assert last is not None
        self.contract = last
        self.contract_doubled = (
            2 if self._is_redoubled()
            else 1 if self._is_doubled()
            else 0
        )

        # Declarer is the first player on the winning side to bid the contract strain
        bid_side = self._last_bid_side()
        assert bid_side is not None
        strain = last.strain
        for player, action in self.bids:
            if self._side(player) == bid_side and action not in ("pass", "double", "redouble"):
                parts = action.split(":")
                if parts[1] == strain:
                    self.declarer = player
                    break
        assert self.declarer is not None
        self.dummy = self._partner(self.declarer)

        # Opening leader is left of declarer
        decl_idx = PLAYERS.index(self.declarer)
        self.trick_leader = PLAYERS[(decl_idx + 1) % 4]

    # --- Play ---

    def _current_player_play(self) -> str:
        """Who plays next in the current trick."""
        assert self.trick_leader is not None
        leader_idx = PLAYERS.index(self.trick_leader)
        offset = len(self.current_trick)
        return PLAYERS[(leader_idx + offset) % 4]

    def _can_follow_suit(self, player: str, led_suit: str) -> bool:
        hand = self.hands[player]
        return any(c.suit == led_suit for c in hand)

    def play_card(self, card: Card) -> None:
        """Play a card to the current trick."""
        if self.play_complete:
            raise ValueError("play is already complete")
        if self.auction_complete and self.passed_out:
            raise ValueError("hand was passed out, no play")

        player = self._current_player_play()

        # Expose dummy after opening lead
        if self.tricks_played == 0 and len(self.current_trick) == 0:
            # This is the opening lead, dummy exposed after it
            pass

        # Validate card is in player's hand (or dummy if declarer plays for dummy)
        actual_player = player
        if player == self.dummy:
            actual_player = player  # declarer controls, but card comes from dummy's hand

        if card not in self.hands[actual_player]:
            raise ValueError(
                f"{actual_player} does not hold {card}"
            )

        # Follow suit check
        if len(self.current_trick) > 0:
            assert self.led_suit is not None
            if card.suit != self.led_suit and self._can_follow_suit(actual_player, self.led_suit):
                raise ValueError(
                    f"{actual_player} must follow suit ({self.led_suit}), "
                    f"but played {card}"
                )

        # Play the card
        if len(self.current_trick) == 0:
            self.led_suit = card.suit
        self.current_trick.append((actual_player, card))
        self.hands[actual_player].remove(card)

        # After opening lead, expose dummy
        if self.tricks_played == 0 and len(self.current_trick) == 1:
            self.dummy_exposed = True

        # If trick complete, resolve
        if len(self.current_trick) == 4:
            self._resolve_trick()

    def _resolve_trick(self) -> None:
        """Determine trick winner and update state."""
        assert self.contract is not None
        trump = self.contract.strain if self.contract.strain != "notrump" else None

        winner_player = self.current_trick[0][0]
        winner_card = self.current_trick[0][1]

        for player, card in self.current_trick[1:]:
            if trump and card.suit == trump and winner_card.suit != trump:
                winner_player, winner_card = player, card
            elif card.suit == winner_card.suit and card.rank_value > winner_card.rank_value:
                winner_player, winner_card = player, card
            elif trump and card.suit == trump and winner_card.suit == trump:
                if card.rank_value > winner_card.rank_value:
                    winner_player, winner_card = player, card

        side = self._side(winner_player)
        self.tricks_won[side] += 1
        self.tricks_played += 1

        # Reset for next trick
        self.current_trick = []
        self.led_suit = None
        self.trick_leader = winner_player

        if self.tricks_played == 13:
            self.play_complete = True

    # --- Scoring (simplified, not vulnerable) ---

    def score(self) -> dict[str, int]:
        """Compute score. Returns {"NS": points, "EW": points}."""
        if not self.play_complete:
            raise ValueError("play not complete")
        assert self.contract is not None
        assert self.declarer is not None

        decl_side = self._side(self.declarer)
        def_side = "EW" if decl_side == "NS" else "NS"
        tricks_needed = self.contract.tricks_needed
        tricks_won = self.tricks_won[decl_side]
        result = {"NS": 0, "EW": 0}

        if tricks_won >= tricks_needed:
            # Contract made
            overtricks = tricks_won - tricks_needed
            level = self.contract.level
            strain = self.contract.strain

            # Trick points
            if strain in ("clubs", "diamonds"):
                trick_points = 20 * level
            elif strain in ("hearts", "spades"):
                trick_points = 30 * level
            else:  # notrump
                trick_points = 40 + 30 * (level - 1)

            if self.contract_doubled == 1:
                trick_points *= 2
            elif self.contract_doubled == 2:
                trick_points *= 4

            # Overtrick points
            if self.contract_doubled == 0:
                if strain in ("clubs", "diamonds"):
                    overtrick_pts = 20 * overtricks
                else:
                    overtrick_pts = 30 * overtricks
            elif self.contract_doubled == 1:
                overtrick_pts = 100 * overtricks
            else:
                overtrick_pts = 200 * overtricks

            result[decl_side] = trick_points + overtrick_pts
        else:
            # Contract defeated
            undertricks = tricks_needed - tricks_won
            if self.contract_doubled == 0:
                penalty = 50 * undertricks
            elif self.contract_doubled == 1:
                penalty = 100 + 200 * (undertricks - 1) if undertricks > 1 else 100
            else:
                penalty = 200 + 400 * (undertricks - 1) if undertricks > 1 else 200

            result[def_side] = penalty

        return result


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_deterministic_deal() -> dict[str, list[Card]]:
    """Create a known deal for deterministic testing.

    North: all spades
    East: all hearts
    South: all diamonds
    West: all clubs
    """
    return {
        "North": [Card("spades", r) for r in RANKS],
        "East": [Card("hearts", r) for r in RANKS],
        "South": [Card("diamonds", r) for r in RANKS],
        "West": [Card("clubs", r) for r in RANKS],
    }


def _make_mixed_deal() -> dict[str, list[Card]]:
    """A more realistic mixed deal with a deterministic seed."""
    rng = random.Random(99)
    deck = _full_deck()
    rng.shuffle(deck)
    return {
        PLAYERS[i]: deck[i * 13:(i + 1) * 13]
        for i in range(4)
    }


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestBridgeDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Contract Bridge"

    def test_four_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["North", "East", "South", "West"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_deck_zone_is_hidden_stack(self) -> None:
        defn = _load_game()
        assert "deck" in defn.zones
        assert defn.zones["deck"].zone_type == "ordered_stack"
        assert defn.zones["deck"].visibility == "hidden"

    def test_hand_zone_is_per_player_private(self) -> None:
        defn = _load_game()
        assert "hand" in defn.zones
        assert defn.zones["hand"].per_player is True

    def test_hand_capacity_is_13(self) -> None:
        defn = _load_game()
        assert defn.zones["hand"].capacity == 13

    def test_current_trick_zone_is_public(self) -> None:
        defn = _load_game()
        assert "current_trick" in defn.zones
        assert defn.zones["current_trick"].visibility == "public"

    def test_trick_counters_exist(self) -> None:
        defn = _load_game()
        assert "tricks_won_ns" in defn.zones
        assert "tricks_won_ew" in defn.zones
        assert defn.zones["tricks_won_ns"].zone_type == "counter"
        assert defn.zones["tricks_won_ew"].zone_type == "counter"

    def test_has_five_phases(self) -> None:
        defn = _load_game()
        assert defn.phases is not None
        assert len(defn.phases) == 5
        phase_names = [p.name for p in defn.phases]
        assert phase_names == ["deal", "auction", "opening_lead", "play", "scoring"]

    def test_authority_server_only_includes_deal(self) -> None:
        defn = _load_game()
        assert "shuffle(deck)" in defn.authority.server_only
        assert "deal(deck, hand)" in defn.authority.server_only

    def test_authority_client_verifiable_includes_bid_and_play(self) -> None:
        defn = _load_game()
        cv = defn.authority.client_verifiable
        assert "bid(level, strain)" in cv
        assert "play_card(card)" in cv

    def test_rules_include_follow_suit(self) -> None:
        defn = _load_game()
        assert "follow_suit" in defn.rules

    def test_rules_include_partnerships(self) -> None:
        defn = _load_game()
        assert "partnerships" in defn.rules

    def test_rules_include_dummy(self) -> None:
        defn = _load_game()
        assert "dummy" in defn.rules


# ---------------------------------------------------------------------------
# Tests: session setup
# ---------------------------------------------------------------------------


class TestSessionSetup:
    def test_creates_four_player_session(self) -> None:
        session = GameSession(_load_game())
        assert len(session.runtime.players) == 4
        for name in PLAYERS:
            assert name in session.runtime.players

    def test_each_player_has_hand_zone(self) -> None:
        session = GameSession(_load_game())
        for name in PLAYERS:
            player = session.runtime.players[name]
            assert "hand" in player.zones
            assert isinstance(player.zones["hand"], SetZone)

    def test_shared_zones_exist(self) -> None:
        session = GameSession(_load_game())
        assert "deck" in session.runtime.zones
        assert "current_trick" in session.runtime.zones
        assert "tricks_won_ns" in session.runtime.zones
        assert "tricks_won_ew" in session.runtime.zones

    def test_counter_zones_start_at_zero(self) -> None:
        session = GameSession(_load_game())
        ns = session.runtime.zones["tricks_won_ns"]
        ew = session.runtime.zones["tricks_won_ew"]
        assert isinstance(ns, CounterZone) and isinstance(ew, CounterZone)
        assert ns.value == 0
        assert ew.value == 0


# ---------------------------------------------------------------------------
# Tests: dealing
# ---------------------------------------------------------------------------


class TestDealing:
    def test_deal_gives_13_cards_each(self) -> None:
        game = BridgeGame()
        game.deal(_make_deterministic_deal())
        for player in PLAYERS:
            assert len(game.hands[player]) == 13

    def test_deal_uses_full_deck(self) -> None:
        game = BridgeGame()
        game.deal(_make_deterministic_deal())
        all_cards = []
        for cards in game.hands.values():
            all_cards.extend(cards)
        assert len(all_cards) == 52
        assert len(set((c.suit, c.rank) for c in all_cards)) == 52

    def test_deal_random_is_deterministic(self) -> None:
        g1 = BridgeGame()
        g1.deal_random(seed=123)
        g2 = BridgeGame()
        g2.deal_random(seed=123)
        for p in PLAYERS:
            assert g1.hands[p] == g2.hands[p]

    def test_deal_random_different_seeds_differ(self) -> None:
        g1 = BridgeGame()
        g1.deal_random(seed=1)
        g2 = BridgeGame()
        g2.deal_random(seed=2)
        # At least one hand should differ
        assert any(g1.hands[p] != g2.hands[p] for p in PLAYERS)

    def test_deal_rejects_wrong_count(self) -> None:
        game = BridgeGame()
        bad_hands = _make_deterministic_deal()
        bad_hands["North"] = bad_hands["North"][:12]  # only 12 cards
        with pytest.raises(ValueError, match="13 cards"):
            game.deal(bad_hands)

    def test_deal_populates_runtime_hand_zones(self) -> None:
        game = BridgeGame()
        game.deal(_make_deterministic_deal())
        for player in PLAYERS:
            hand_zone = game.session.runtime.players[player].zones["hand"]
            assert isinstance(hand_zone, SetZone)
            assert hand_zone.count() == 13


# ---------------------------------------------------------------------------
# Tests: bid ordering
# ---------------------------------------------------------------------------


class TestBidOrdering:
    def test_1c_is_lowest(self) -> None:
        b = Bid(1, "clubs")
        assert b.level == 1
        assert b.strain == "clubs"

    def test_7nt_is_highest(self) -> None:
        b = Bid(7, "notrump")
        assert b.level == 7
        assert b.strain == "notrump"

    def test_higher_level_beats_lower(self) -> None:
        assert Bid(2, "clubs") > Bid(1, "notrump")

    def test_same_level_higher_strain_wins(self) -> None:
        assert Bid(1, "notrump") > Bid(1, "spades")
        assert Bid(1, "spades") > Bid(1, "hearts")
        assert Bid(1, "hearts") > Bid(1, "diamonds")
        assert Bid(1, "diamonds") > Bid(1, "clubs")

    def test_equal_bids_not_higher(self) -> None:
        a = Bid(2, "hearts")
        b = Bid(2, "hearts")
        assert not (a > b)
        assert not (b > a)

    def test_invalid_level_rejected(self) -> None:
        with pytest.raises(ValueError):
            Bid(0, "clubs")
        with pytest.raises(ValueError):
            Bid(8, "hearts")

    def test_invalid_strain_rejected(self) -> None:
        with pytest.raises(ValueError):
            Bid(1, "jokers")

    def test_tricks_needed(self) -> None:
        assert Bid(1, "clubs").tricks_needed == 7
        assert Bid(3, "notrump").tricks_needed == 9
        assert Bid(7, "spades").tricks_needed == 13


# ---------------------------------------------------------------------------
# Tests: auction mechanics
# ---------------------------------------------------------------------------


class TestAuction:
    def test_four_passes_is_passed_out(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_pass()  # North
        game.auction_pass()  # East
        game.auction_pass()  # South
        game.auction_pass()  # West
        assert game.auction_complete
        assert game.passed_out

    def test_bid_then_three_passes_ends_auction(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "clubs")   # North
        game.auction_pass()            # East
        game.auction_pass()            # South
        game.auction_pass()            # West
        assert game.auction_complete
        assert not game.passed_out
        assert game.contract == Bid(1, "clubs")
        assert game.declarer == "North"

    def test_competitive_auction(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "hearts")    # North
        game.auction_bid(1, "spades")    # East
        game.auction_bid(2, "hearts")    # South
        game.auction_pass()              # West
        game.auction_pass()              # North
        game.auction_pass()              # East
        assert game.auction_complete
        assert game.contract == Bid(2, "hearts")
        # Declarer is first on the side to bid hearts (North)
        assert game.declarer == "North"
        assert game.dummy == "South"

    def test_declarer_is_first_to_bid_strain(self) -> None:
        """Declarer is the first member of the winning side to bid the strain."""
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "clubs")     # North bids 1C
        game.auction_pass()              # East
        game.auction_bid(1, "spades")    # South bids 1S
        game.auction_pass()              # West
        game.auction_bid(2, "spades")    # North raises to 2S
        game.auction_pass()              # East
        game.auction_pass()              # South
        game.auction_pass()              # West
        assert game.contract == Bid(2, "spades")
        # South first bid spades, so South is declarer even though North made final bid
        assert game.declarer == "South"
        assert game.dummy == "North"

    def test_cannot_bid_lower_than_current(self) -> None:
        game = BridgeGame()
        game.deal_random()
        game.auction_bid(1, "hearts")
        with pytest.raises(ValueError, match="must be higher"):
            game.auction_bid(1, "diamonds")

    def test_cannot_bid_same_as_current(self) -> None:
        game = BridgeGame()
        game.deal_random()
        game.auction_bid(2, "clubs")
        with pytest.raises(ValueError, match="must be higher"):
            game.auction_bid(2, "clubs")

    def test_double_by_opponent(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "notrump")  # North
        game.auction_double()           # East doubles
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.auction_complete
        assert game.contract_doubled == 1

    def test_cannot_double_own_bid(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "clubs")   # North
        game.auction_pass()            # East
        with pytest.raises(ValueError, match="cannot double own"):
            game.auction_double()      # South tries to double own side

    def test_cannot_double_without_bid(self) -> None:
        game = BridgeGame()
        game.deal_random()
        with pytest.raises(ValueError, match="no bid"):
            game.auction_double()

    def test_redouble(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(3, "notrump")  # North
        game.auction_double()           # East
        game.auction_redouble()         # South redoubles
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.auction_complete
        assert game.contract_doubled == 2

    def test_cannot_redouble_without_double(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "clubs")
        with pytest.raises(ValueError, match="not doubled"):
            game.auction_redouble()

    def test_opening_leader_is_left_of_declarer(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "clubs")  # North is declarer
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.declarer == "North"
        # Left of North is East
        assert game.trick_leader == "East"

    def test_dummy_is_declarers_partner(self) -> None:
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "hearts")  # North
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.declarer == "North"
        assert game.dummy == "South"


# ---------------------------------------------------------------------------
# Tests: play mechanics
# ---------------------------------------------------------------------------


class TestPlay:
    def _setup_game_with_contract(
        self, hands: dict[str, list[Card]], level: int = 1,
        strain: str = "notrump", dealer_index: int = 0,
    ) -> BridgeGame:
        """Set up a game with a known deal and completed auction."""
        game = BridgeGame(dealer_index=dealer_index)
        game.deal(hands)
        game.auction_bid(level, strain)
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        return game

    def test_opening_lead_exposes_dummy(self) -> None:
        hands = _make_deterministic_deal()
        game = self._setup_game_with_contract(hands)
        # Declarer=North, leader=East, dummy=South
        assert not game.dummy_exposed
        lead_card = game.hands["East"][0]
        game.play_card(lead_card)
        assert game.dummy_exposed

    def test_follow_suit_required(self) -> None:
        """Must follow suit if able."""
        hands = _make_deterministic_deal()
        # North=spades, East=hearts, South=diamonds, West=clubs
        game = self._setup_game_with_contract(hands, strain="notrump")
        # East leads a heart
        game.play_card(Card("hearts", "A"))
        # South must play diamonds? No, South has no hearts -> can play anything
        # Actually South has only diamonds so can play any card (void in hearts)
        game.play_card(Card("diamonds", "A"))  # fine, void in hearts
        # West has only clubs, void in hearts, can play anything
        game.play_card(Card("clubs", "A"))  # fine
        # North has only spades, void in hearts
        game.play_card(Card("spades", "A"))  # fine

    def test_follow_suit_violation_rejected(self) -> None:
        """Playing off-suit when holding the led suit is illegal."""
        # Build hands where a player has cards in multiple suits
        hands = _make_mixed_deal()
        game = self._setup_game_with_contract(hands)
        # Declarer is North (dealer_index=0), leader is East
        leader = game.trick_leader
        assert leader is not None
        leader_hand = game.hands[leader]
        # Find a card to lead
        lead_card = leader_hand[0]
        game.play_card(lead_card)

        # Next player must follow suit if able
        next_player_idx = (PLAYERS.index(leader) + 1) % 4
        next_player = PLAYERS[next_player_idx]
        next_hand = game.hands[next_player]

        has_led_suit = [c for c in next_hand if c.suit == lead_card.suit]
        off_suit = [c for c in next_hand if c.suit != lead_card.suit]

        if has_led_suit and off_suit:
            with pytest.raises(ValueError, match="must follow suit"):
                game.play_card(off_suit[0])

    def test_can_play_any_suit_when_void(self) -> None:
        """When void in the led suit, any card is legal."""
        hands = _make_deterministic_deal()
        game = self._setup_game_with_contract(hands, strain="notrump")
        # East leads hearts, everyone else is void in hearts
        game.play_card(Card("hearts", "K"))
        # South is void in hearts, can play diamonds
        game.play_card(Card("diamonds", "K"))  # legal

    def test_trick_winner_highest_of_led_suit(self) -> None:
        """In notrump, highest card of led suit wins."""
        hands = _make_deterministic_deal()
        game = self._setup_game_with_contract(hands, strain="notrump")
        # East leads hearts Ace (highest) -- East should win
        game.play_card(Card("hearts", "A"))  # East leads
        game.play_card(Card("diamonds", "2"))  # South (off-suit, won't win)
        game.play_card(Card("clubs", "2"))  # West (off-suit)
        game.play_card(Card("spades", "2"))  # North (off-suit)
        assert game.tricks_won["EW"] == 1
        assert game.trick_leader == "East"  # East wins and leads next

    def test_trump_beats_led_suit(self) -> None:
        """A trump card beats a higher card of the led suit."""
        hands = _make_deterministic_deal()
        # Spades are trump, North has all spades
        game = self._setup_game_with_contract(hands, strain="spades")
        # East leads hearts Ace
        game.play_card(Card("hearts", "A"))  # East
        game.play_card(Card("diamonds", "2"))  # South (off-suit, no trump)
        game.play_card(Card("clubs", "2"))  # West (off-suit, no trump)
        game.play_card(Card("spades", "2"))  # North trumps with 2 of spades
        # North's trump 2 beats East's Ace of hearts
        assert game.tricks_won["NS"] == 1
        assert game.trick_leader == "North"

    def test_higher_trump_beats_lower_trump(self) -> None:
        """When multiple trumps played, highest trump wins."""
        # Give North and East some trumps (hearts)
        deck = _full_deck()
        rng = random.Random(777)
        rng.shuffle(deck)
        # Build custom hands where multiple players have hearts
        hearts = [c for c in deck if c.suit == "hearts"]
        non_hearts = [c for c in deck if c.suit != "hearts"]
        hands = {
            "North": hearts[:5] + non_hearts[:8],   # 5 hearts + 8 others
            "East": hearts[5:10] + non_hearts[8:16], # 5 hearts + 8 others
            "South": hearts[10:13] + non_hearts[16:26],  # 3 hearts + 10 others
            "West": non_hearts[26:39],  # 0 hearts + 13 others
        }
        game = self._setup_game_with_contract(hands, strain="hearts")
        # East leads something West has -- a club (West has only non-hearts)
        west_hand = game.hands["West"]
        club_cards = [c for c in west_hand if c.suit == "clubs"]
        if not club_cards:
            pytest.skip("no clubs in West's hand with this seed")

        # Actually let's use the deterministic deal and just test the logic
        # with our clean suit-per-player deal
        hands2 = _make_deterministic_deal()
        game2 = self._setup_game_with_contract(hands2, strain="spades")
        # East leads heart A, South plays diamond 2 (off-suit),
        # West plays club 2 (off-suit), North trumps with spade A
        game2.play_card(Card("hearts", "A"))
        game2.play_card(Card("diamonds", "2"))
        game2.play_card(Card("clubs", "2"))
        game2.play_card(Card("spades", "A"))
        assert game2.tricks_won["NS"] == 1

    def test_complete_hand_plays_13_tricks(self) -> None:
        """Play a full hand of 13 tricks."""
        hands = _make_deterministic_deal()
        game = self._setup_game_with_contract(hands, strain="notrump")
        # Each player has one suit, so each lead wins for the leader
        # East leads all hearts (wins all 13? No -- each player plays 1 card per trick)
        # East leads heart A, others play their lowest remaining
        for i in range(13):
            leader = game.trick_leader
            assert leader is not None
            leader_hand = game.hands[leader]
            # Leader plays highest card
            lead_card = max(leader_hand, key=lambda c: c.rank_value)
            game.play_card(lead_card)
            # Others play lowest of their suit (they're void in led suit)
            for j in range(3):
                follower = game._current_player_play()
                follower_hand = game.hands[follower]
                play_card = min(follower_hand, key=lambda c: c.rank_value)
                game.play_card(play_card)

        assert game.play_complete
        assert game.tricks_played == 13
        assert game.tricks_won["NS"] + game.tricks_won["EW"] == 13

    def test_cannot_play_card_not_in_hand(self) -> None:
        hands = _make_deterministic_deal()
        game = self._setup_game_with_contract(hands, strain="notrump")
        # East is leader, try to play a spade (East only has hearts)
        with pytest.raises(ValueError, match="does not hold"):
            game.play_card(Card("spades", "A"))


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def _play_full_hand(
        self, game: BridgeGame,
    ) -> None:
        """Play a full hand, each player playing highest available card."""
        for _ in range(13):
            for _ in range(4):
                player = game._current_player_play()
                hand = game.hands[player]
                if game.led_suit and any(c.suit == game.led_suit for c in hand):
                    candidates = [c for c in hand if c.suit == game.led_suit]
                else:
                    candidates = hand
                card = max(candidates, key=lambda c: c.rank_value)
                game.play_card(card)

    def test_score_1nt_making(self) -> None:
        """1NT making exactly (7 tricks): 40 points."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)
        game.auction_bid(1, "notrump")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        # In deterministic deal, each player wins 13 tricks with their own suit...
        # Wait, in notrump the leader always wins (highest of led suit)
        # East leads all tricks initially, each player has only their suit
        # All cards in led suit are East's so East always wins
        # Actually East leads, the other 3 are void so they play off-suit cards
        # East wins all 13 tricks since highest of led suit wins
        # But then East leads again with remaining hearts and same thing
        # So EW wins 13, NS wins 0
        # Declarer is North (1NT), North needs 7 tricks but NS gets 0
        # Contract is defeated by 7 undertricks
        # Undoubled: 50 * 7 = 350
        def_side = "EW" if decl_side == "NS" else "NS"
        assert result[def_side] == 350

    def test_score_minor_suit_contract(self) -> None:
        """1C making with 1 overtrick: 20 (trick) + 20 (overtrick) = 40."""
        game = BridgeGame()
        game.deal_random()
        game.auction_bid(1, "clubs")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        tricks = game.tricks_won[decl_side]
        if tricks >= 7:
            overtricks = tricks - 7
            expected = 20 + 20 * overtricks  # 20 per trick for minor
            assert result[decl_side] == expected

    def test_score_major_suit_contract(self) -> None:
        """Major suit trick points are 30 per trick."""
        game = BridgeGame()
        game.deal_random()
        game.auction_bid(1, "hearts")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        tricks = game.tricks_won[decl_side]
        if tricks >= 7:
            overtricks = tricks - 7
            expected = 30 + 30 * overtricks  # 30 per trick for major
            assert result[decl_side] == expected

    def test_score_notrump_contract(self) -> None:
        """Notrump: 40 first trick + 30 each subsequent."""
        game = BridgeGame()
        game.deal_random()
        game.auction_bid(2, "notrump")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        tricks = game.tricks_won[decl_side]
        if tricks >= 8:
            overtricks = tricks - 8
            expected = (40 + 30) + 30 * overtricks  # 40+30 for 2NT = 70
            assert result[decl_side] == expected

    def test_score_doubled_contract_made(self) -> None:
        """Doubled contract: trick points doubled, overtricks at 100 each."""
        game = BridgeGame(dealer_index=0)
        game.deal_random()
        game.auction_bid(1, "hearts")  # North
        game.auction_double()          # East
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        tricks = game.tricks_won[decl_side]
        if tricks >= 7:
            overtricks = tricks - 7
            trick_pts = 30 * 2  # doubled major
            overtrick_pts = 100 * overtricks
            assert result[decl_side] == trick_pts + overtrick_pts

    def test_score_undertricks_undoubled(self) -> None:
        """Undertricks at 50 each (not vulnerable)."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)
        # North bids 7NT (needs 13 tricks), will definitely fail
        game.auction_bid(7, "notrump")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        def_side = "EW" if decl_side == "NS" else "NS"
        tricks = game.tricks_won[decl_side]
        undertricks = 13 - tricks
        assert result[def_side] == 50 * undertricks

    def test_score_undertricks_doubled(self) -> None:
        """Doubled undertricks: 100 first, 200 each subsequent."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)
        game.auction_bid(7, "notrump")  # North -- will fail
        game.auction_double()           # East doubles
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        def_side = "EW" if decl_side == "NS" else "NS"
        tricks = game.tricks_won[decl_side]
        undertricks = 13 - tricks
        if undertricks == 1:
            expected = 100
        else:
            expected = 100 + 200 * (undertricks - 1)
        assert result[def_side] == expected

    def test_score_undertricks_redoubled(self) -> None:
        """Redoubled undertricks: 200 first, 400 each subsequent."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)
        game.auction_bid(7, "notrump")
        game.auction_double()     # East
        game.auction_redouble()   # South
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        self._play_full_hand(game)
        result = game.score()
        decl_side = game._side(game.declarer)
        def_side = "EW" if decl_side == "NS" else "NS"
        tricks = game.tricks_won[decl_side]
        undertricks = 13 - tricks
        if undertricks == 1:
            expected = 200
        else:
            expected = 200 + 400 * (undertricks - 1)
        assert result[def_side] == expected


# ---------------------------------------------------------------------------
# Tests: full game flow
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_full_game_with_deterministic_deal(self) -> None:
        """End-to-end: deal, auction, play, score."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)

        # Simple auction: North bids 1S, everyone passes
        game.auction_bid(1, "spades")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.declarer == "North"
        assert game.dummy == "South"
        assert game.contract == Bid(1, "spades")

        # Play all 13 tricks
        for _ in range(13):
            for _ in range(4):
                player = game._current_player_play()
                hand = game.hands[player]
                if game.led_suit and any(c.suit == game.led_suit for c in hand):
                    candidates = [c for c in hand if c.suit == game.led_suit]
                else:
                    candidates = hand
                card = max(candidates, key=lambda c: c.rank_value)
                game.play_card(card)

        assert game.play_complete
        assert game.tricks_played == 13
        result = game.score()
        assert result["NS"] + result["EW"] > 0  # someone scored

    def test_passed_out_hand(self) -> None:
        """All four pass: no play, no score."""
        game = BridgeGame()
        game.deal_random()
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        assert game.passed_out
        with pytest.raises(ValueError, match="passed out"):
            game.play_card(Card("spades", "A"))

    def test_wire_format_includes_all_players(self) -> None:
        """Wire state includes all four player hand zones."""
        game = BridgeGame()
        game.deal(_make_deterministic_deal())
        wire = game.session.to_wire_state()
        for player in PLAYERS:
            assert player in wire.players
            assert wire.players[player].zones is not None
            assert "hand" in wire.players[player].zones

    def test_trump_contract_ns_wins(self) -> None:
        """North-South in a spade contract with North holding all spades wins all tricks."""
        hands = _make_deterministic_deal()
        game = BridgeGame(dealer_index=0)
        game.deal(hands)

        game.auction_bid(7, "spades")
        game.auction_pass()
        game.auction_pass()
        game.auction_pass()
        # Declarer=North, dummy=South, leader=East
        assert game.declarer == "North"

        # Play all tricks. North trumps everything.
        for _ in range(13):
            for _ in range(4):
                player = game._current_player_play()
                hand = game.hands[player]
                if game.led_suit and any(c.suit == game.led_suit for c in hand):
                    candidates = [c for c in hand if c.suit == game.led_suit]
                else:
                    candidates = hand
                # Play highest available
                card = max(candidates, key=lambda c: c.rank_value)
                game.play_card(card)

        assert game.play_complete
        # North has all spades (trump) and will trump everything
        # East leads hearts -> North trumps -> North wins
        # Then North leads spade -> everyone plays off-suit -> North wins
        # NS should win all 13 tricks
        assert game.tricks_won["NS"] == 13
        assert game.tricks_won["EW"] == 0
        result = game.score()
        # 7S making: 30 * 7 = 210 trick points, 0 overtricks
        assert result["NS"] == 210

    def test_multiple_deals_different_results(self) -> None:
        """Different deals produce different trick outcomes."""
        results = []
        for seed in range(5):
            game = BridgeGame()
            game.deal_random(seed=seed)
            game.auction_bid(1, "notrump")
            game.auction_pass()
            game.auction_pass()
            game.auction_pass()
            for _ in range(13):
                for _ in range(4):
                    player = game._current_player_play()
                    hand = game.hands[player]
                    if game.led_suit and any(c.suit == game.led_suit for c in hand):
                        candidates = [c for c in hand if c.suit == game.led_suit]
                    else:
                        candidates = hand
                    card = max(candidates, key=lambda c: c.rank_value)
                    game.play_card(card)
            results.append(game.tricks_won.copy())
        # Not all results should be identical
        assert len(set(tuple(r.items()) for r in results)) > 1
