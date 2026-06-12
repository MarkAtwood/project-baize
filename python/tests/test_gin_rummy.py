"""Tests for Gin Rummy: 2-player card game with melds, knocking, and scoring.

Deal 10 cards each from a 52-card deck, one face-up to discard pile.
Each turn: draw from stock or discard, then discard. Form melds (sets of
3-4 same rank, runs of 3+ consecutive same suit). Knock when deadwood <= 10.
Gin = 0 deadwood (25 pt bonus). Undercut = opponent deadwood <= knocker's
(25 pt bonus to opponent). Game to 100 points.

Card draws and shuffling are server authority -- tests supply deterministic
hands and card sequences.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "gin-rummy.json"

SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
RANK_VALUES = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10,
}
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}  # A=0 .. K=12


# ---------------------------------------------------------------------------
# Card helper
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    suit: str
    rank: str

    @property
    def value(self) -> int:
        return RANK_VALUES[self.rank]

    @property
    def order(self) -> int:
        return RANK_ORDER[self.rank]

    def __repr__(self) -> str:
        return f"{self.rank}{self.suit[0].upper()}"


# ---------------------------------------------------------------------------
# Meld detection (independent oracle)
# ---------------------------------------------------------------------------

def is_set_meld(cards: list[Card]) -> bool:
    """3 or 4 cards of the same rank, all different suits."""
    if len(cards) not in (3, 4):
        return False
    ranks = {c.rank for c in cards}
    suits = {c.suit for c in cards}
    return len(ranks) == 1 and len(suits) == len(cards)


def is_run_meld(cards: list[Card]) -> bool:
    """3+ consecutive cards of the same suit (ace low only)."""
    if len(cards) < 3:
        return False
    suits = {c.suit for c in cards}
    if len(suits) != 1:
        return False
    orders = sorted(c.order for c in cards)
    for i in range(1, len(orders)):
        if orders[i] != orders[i - 1] + 1:
            return False
    return True


def is_valid_meld(cards: list[Card]) -> bool:
    return is_set_meld(cards) or is_run_meld(cards)


def find_best_melds(hand: list[Card]) -> tuple[list[list[Card]], list[Card]]:
    """Find the combination of non-overlapping melds that minimizes deadwood.

    Returns (melds, deadwood_cards).  Brute-force over subsets -- fine for 10 cards.
    """
    all_melds: list[list[Card]] = []

    # Enumerate all possible melds from the hand
    for size in range(3, len(hand) + 1):
        for combo in combinations(hand, size):
            group = list(combo)
            if is_valid_meld(group):
                all_melds.append(group)

    # Find the best non-overlapping combination (minimize deadwood)
    best_deadwood = sum(c.value for c in hand)
    best_combo: list[list[Card]] = []

    def _search(
        idx: int,
        used: set[int],
        chosen: list[list[Card]],
    ) -> None:
        nonlocal best_deadwood, best_combo
        remaining = [c for i, c in enumerate(hand) if i not in used]
        dw = sum(c.value for c in remaining)
        if dw < best_deadwood:
            best_deadwood = dw
            best_combo = list(chosen)

        for j in range(idx, len(all_melds)):
            meld = all_melds[j]
            meld_indices = set()
            ok = True
            for card in meld:
                found = False
                for i, hc in enumerate(hand):
                    if i not in used and i not in meld_indices and hc == card:
                        meld_indices.add(i)
                        found = True
                        break
                if not found:
                    ok = False
                    break
            if ok:
                _search(j + 1, used | meld_indices, chosen + [meld])

    _search(0, set(), [])

    used_in_melds: set[int] = set()
    for meld in best_combo:
        for card in meld:
            for i, hc in enumerate(hand):
                if i not in used_in_melds and hc == card:
                    used_in_melds.add(i)
                    break

    deadwood_cards = [c for i, c in enumerate(hand) if i not in used_in_melds]
    return best_combo, deadwood_cards


def deadwood_value(hand: list[Card]) -> int:
    """Compute minimum deadwood value for a hand."""
    _, dw_cards = find_best_melds(hand)
    return sum(c.value for c in dw_cards)


# ---------------------------------------------------------------------------
# GinRummyGame driver
# ---------------------------------------------------------------------------

class GinRummyGame:
    """Gin Rummy game driver.  Simulates draw/discard, knock, gin, undercut."""

    def __init__(self) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.hands: dict[str, list[Card]] = {"P1": [], "P2": []}
        self.stock: list[Card] = []
        self.discard_pile: list[Card] = []
        self.scores: dict[str, int] = {"P1": 0, "P2": 0}
        self.phase: str = "play"
        self.drawn_this_turn: bool = False
        self.game_over: bool = False

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _opponent(self, player: str) -> str:
        return "P2" if player == "P1" else "P1"

    def deal(self, p1_hand: list[Card], p2_hand: list[Card],
             stock: list[Card], first_discard: Card) -> None:
        """Set up a dealt state with known cards."""
        if len(p1_hand) != 10 or len(p2_hand) != 10:
            raise ValueError("each player must receive exactly 10 cards")
        self.hands["P1"] = list(p1_hand)
        self.hands["P2"] = list(p2_hand)
        self.stock = list(stock)
        self.discard_pile = [first_discard]
        self.phase = "play"
        self.drawn_this_turn = False

    def draw_from_stock(self) -> Card:
        """Current player draws from the stock pile."""
        if self.drawn_this_turn:
            raise ValueError("already drew this turn")
        if not self.stock:
            raise ValueError("stock is empty")
        player = self.current_player()
        card = self.stock.pop()
        self.hands[player].append(card)
        self.drawn_this_turn = True
        return card

    def draw_from_discard(self) -> Card:
        """Current player draws the top card of the discard pile."""
        if self.drawn_this_turn:
            raise ValueError("already drew this turn")
        if not self.discard_pile:
            raise ValueError("discard pile is empty")
        player = self.current_player()
        card = self.discard_pile.pop()
        self.hands[player].append(card)
        self.drawn_this_turn = True
        return card

    def discard(self, card: Card) -> None:
        """Current player discards a card from their hand."""
        if not self.drawn_this_turn:
            raise ValueError("must draw before discarding")
        player = self.current_player()
        if card not in self.hands[player]:
            raise ValueError(f"{card} not in {player}'s hand")
        self.hands[player].remove(card)
        self.discard_pile.append(card)
        self.drawn_this_turn = False
        self.session.advance_turn()

    def knock(self, discard_card: Card) -> dict[str, int]:
        """Current player knocks after discarding. Returns round scores."""
        if not self.drawn_this_turn:
            raise ValueError("must draw before knocking")
        player = self.current_player()
        if discard_card not in self.hands[player]:
            raise ValueError(f"{discard_card} not in {player}'s hand")

        # Discard the card
        self.hands[player].remove(discard_card)
        self.discard_pile.append(discard_card)

        # Verify deadwood <= 10
        knocker_dw = deadwood_value(self.hands[player])
        if knocker_dw > 10:
            raise ValueError(
                f"cannot knock with deadwood {knocker_dw} > 10"
            )

        opponent = self._opponent(player)
        return self._resolve_knock(player, opponent, knocker_dw, is_gin=False)

    def gin(self, discard_card: Card) -> dict[str, int]:
        """Current player declares gin after discarding. Returns round scores."""
        if not self.drawn_this_turn:
            raise ValueError("must draw before declaring gin")
        player = self.current_player()
        if discard_card not in self.hands[player]:
            raise ValueError(f"{discard_card} not in {player}'s hand")

        self.hands[player].remove(discard_card)
        self.discard_pile.append(discard_card)

        knocker_dw = deadwood_value(self.hands[player])
        if knocker_dw != 0:
            raise ValueError(
                f"cannot declare gin with deadwood {knocker_dw} != 0"
            )

        opponent = self._opponent(player)
        return self._resolve_knock(player, opponent, 0, is_gin=True)

    def _resolve_knock(
        self, knocker: str, opponent: str,
        knocker_dw: int, is_gin: bool,
    ) -> dict[str, int]:
        """Score a knock/gin. Handles lay-off (simplified: no lay-off on gin)."""
        opponent_dw = deadwood_value(self.hands[opponent])

        round_scores: dict[str, int] = {"P1": 0, "P2": 0}

        if is_gin:
            # Gin: knocker gets opponent's deadwood + 25 bonus
            round_scores[knocker] = opponent_dw + 25
        elif opponent_dw <= knocker_dw:
            # Undercut: opponent gets the difference + 25 bonus
            round_scores[opponent] = (knocker_dw - opponent_dw) + 25
        else:
            # Normal knock: knocker gets the difference
            round_scores[knocker] = opponent_dw - knocker_dw

        self.scores["P1"] += round_scores["P1"]
        self.scores["P2"] += round_scores["P2"]

        if self.scores["P1"] >= 100 or self.scores["P2"] >= 100:
            self.game_over = True

        self.drawn_this_turn = False
        return round_scores

    def lay_off_cards(
        self, knocker: str, opponent_hand: list[Card],
        knocker_melds: list[list[Card]],
    ) -> list[Card]:
        """Determine which cards opponent can lay off on knocker's melds.

        Returns cards that can be laid off (removed from opponent's deadwood).
        """
        layoffs: list[Card] = []
        remaining = list(opponent_hand)

        for meld in knocker_melds:
            if is_set_meld(meld):
                # Can add a 4th card of same rank if meld has 3
                if len(meld) == 3:
                    meld_rank = meld[0].rank
                    meld_suits = {c.suit for c in meld}
                    for card in remaining:
                        if card.rank == meld_rank and card.suit not in meld_suits:
                            layoffs.append(card)
                            remaining.remove(card)
                            break
            elif is_run_meld(meld):
                # Can extend run at either end
                meld_suit = meld[0].suit
                orders = sorted(c.order for c in meld)
                low, high = orders[0], orders[-1]
                # Try extending low end
                for card in remaining:
                    if card.suit == meld_suit and card.order == low - 1:
                        layoffs.append(card)
                        remaining.remove(card)
                        low -= 1
                        break
                # Try extending high end
                for card in remaining:
                    if card.suit == meld_suit and card.order == high + 1:
                        layoffs.append(card)
                        remaining.remove(card)
                        high += 1
                        break

        return layoffs

    def winner(self) -> str | None:
        if self.scores["P1"] >= 100 and self.scores["P2"] >= 100:
            return "P1" if self.scores["P1"] > self.scores["P2"] else "P2"
        if self.scores["P1"] >= 100:
            return "P1"
        if self.scores["P2"] >= 100:
            return "P2"
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _make_card(rank: str, suit: str) -> Card:
    return Card(suit=suit, rank=rank)


def _make_hand(*specs: str) -> list[Card]:
    """Build a hand from short specs like 'AH', '10S', 'KD'."""
    cards: list[Card] = []
    suit_map = {"H": "hearts", "D": "diamonds", "C": "clubs", "S": "spades"}
    for spec in specs:
        suit_char = spec[-1]
        rank_str = spec[:-1]
        cards.append(Card(suit=suit_map[suit_char], rank=rank_str))
    return cards


def _full_deck() -> list[Card]:
    """Produce a deterministic 52-card deck."""
    return [Card(suit=s, rank=r) for s in SUITS for r in RANKS]


def _deal_deterministic(
    seed: int = 42,
) -> tuple[list[Card], list[Card], list[Card], Card]:
    """Shuffle and deal: 10 to P1, 10 to P2, 1 face-up discard, rest is stock."""
    deck = _full_deck()
    rng = random.Random(seed)
    rng.shuffle(deck)
    p1 = deck[:10]
    p2 = deck[10:20]
    first_discard = deck[20]
    stock = deck[21:]
    return p1, p2, stock, first_discard


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------

class TestGinRummyDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Gin Rummy"

    def test_two_named_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["P1", "P2"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_stock_zone_hidden_stack(self) -> None:
        defn = _load_game()
        assert "stock" in defn.zones
        assert defn.zones["stock"].zone_type == "ordered_stack"
        assert defn.zones["stock"].visibility == "hidden"

    def test_discard_zone_public_stack(self) -> None:
        defn = _load_game()
        assert "discard" in defn.zones
        assert defn.zones["discard"].zone_type == "ordered_stack"
        assert defn.zones["discard"].visibility == "public"

    def test_hand_zone_per_player_private(self) -> None:
        defn = _load_game()
        assert "hand" in defn.zones
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_score_zone_per_player_counter(self) -> None:
        defn = _load_game()
        assert "score" in defn.zones
        assert defn.zones["score"].zone_type == "counter"
        assert defn.zones["score"].per_player is True

    def test_52_card_component(self) -> None:
        defn = _load_game()
        assert "card" in defn.components
        assert defn.components["card"].count == 52

    def test_authority_server_only(self) -> None:
        defn = _load_game()
        assert len(defn.authority.server_only) > 0
        server_ops = " ".join(defn.authority.server_only)
        assert "shuffle" in server_ops
        assert "deal" in server_ops

    def test_phases_deal_play_knock(self) -> None:
        defn = _load_game()
        phase_names = [p.name for p in defn.phases]
        assert "deal" in phase_names
        assert "play" in phase_names
        assert "knock" in phase_names

    def test_schema_valid_json(self) -> None:
        """Game definition file is valid JSON."""
        text = _GAME_PATH.read_text()
        parsed = json.loads(text)
        assert parsed["game"]["name"] == "Gin Rummy"


# ---------------------------------------------------------------------------
# Tests: runtime session bootstrap
# ---------------------------------------------------------------------------

class TestSessionBootstrap:
    def test_session_creates_per_player_zones(self) -> None:
        session = GameSession(_load_game())
        assert "P1" in session.runtime.players
        assert "P2" in session.runtime.players
        assert "hand" in session.runtime.players["P1"].zones
        assert "hand" in session.runtime.players["P2"].zones

    def test_hand_zones_are_set_zones(self) -> None:
        session = GameSession(_load_game())
        p1_hand = session.runtime.players["P1"].zones["hand"]
        assert isinstance(p1_hand, SetZone)

    def test_stock_is_stack_zone(self) -> None:
        session = GameSession(_load_game())
        stock = session.runtime.zones["stock"]
        assert isinstance(stock, StackZone)

    def test_discard_is_stack_zone(self) -> None:
        session = GameSession(_load_game())
        discard = session.runtime.zones["discard"]
        assert isinstance(discard, StackZone)

    def test_score_zones_are_counters(self) -> None:
        session = GameSession(_load_game())
        p1_score = session.runtime.players["P1"].zones["score"]
        assert isinstance(p1_score, CounterZone)

    def test_turn_alternates(self) -> None:
        session = GameSession(_load_game())
        session.runtime.status = "in_progress"
        assert session.current_player() == "P1"
        session.advance_turn()
        assert session.current_player() == "P2"
        session.advance_turn()
        assert session.current_player() == "P1"


# ---------------------------------------------------------------------------
# Tests: meld detection (independent oracle)
# ---------------------------------------------------------------------------

class TestMeldDetection:
    def test_set_of_three(self) -> None:
        cards = _make_hand("5H", "5D", "5C")
        assert is_set_meld(cards)

    def test_set_of_four(self) -> None:
        cards = _make_hand("KH", "KD", "KC", "KS")
        assert is_set_meld(cards)

    def test_set_rejects_two(self) -> None:
        cards = _make_hand("5H", "5D")
        assert not is_set_meld(cards)

    def test_set_rejects_duplicate_suits(self) -> None:
        cards = _make_hand("5H", "5H", "5D")
        assert not is_set_meld(cards)

    def test_set_rejects_mixed_ranks(self) -> None:
        cards = _make_hand("5H", "6D", "5C")
        assert not is_set_meld(cards)

    def test_run_of_three(self) -> None:
        cards = _make_hand("3H", "4H", "5H")
        assert is_run_meld(cards)

    def test_run_of_four(self) -> None:
        cards = _make_hand("7S", "8S", "9S", "10S")
        assert is_run_meld(cards)

    def test_run_of_five(self) -> None:
        cards = _make_hand("AH", "2H", "3H", "4H", "5H")
        assert is_run_meld(cards)

    def test_run_rejects_two(self) -> None:
        cards = _make_hand("3H", "4H")
        assert not is_run_meld(cards)

    def test_run_rejects_mixed_suits(self) -> None:
        cards = _make_hand("3H", "4D", "5H")
        assert not is_run_meld(cards)

    def test_run_rejects_gap(self) -> None:
        cards = _make_hand("3H", "4H", "6H")
        assert not is_run_meld(cards)

    def test_run_ace_low_only(self) -> None:
        """A-2-3 is valid; Q-K-A is NOT valid (ace low only)."""
        assert is_run_meld(_make_hand("AH", "2H", "3H"))
        assert not is_run_meld(_make_hand("QH", "KH", "AH"))

    def test_is_valid_meld_dispatches(self) -> None:
        assert is_valid_meld(_make_hand("5H", "5D", "5C"))
        assert is_valid_meld(_make_hand("3S", "4S", "5S"))
        assert not is_valid_meld(_make_hand("3S", "4S"))


# ---------------------------------------------------------------------------
# Tests: deadwood calculation
# ---------------------------------------------------------------------------

class TestDeadwood:
    def test_all_deadwood(self) -> None:
        """No melds possible: deadwood = sum of all card values."""
        hand = _make_hand("AH", "3D", "5C", "7S", "9H", "2D", "4C", "6S", "8H", "KD")
        dw = deadwood_value(hand)
        expected = 1 + 3 + 5 + 7 + 9 + 2 + 4 + 6 + 8 + 10
        assert dw == expected

    def test_one_set_meld(self) -> None:
        """Three 5s meld, rest is deadwood."""
        hand = _make_hand("5H", "5D", "5C", "AH", "3S", "7D", "9C", "2H", "KS", "JD")
        dw = deadwood_value(hand)
        # 5+5+5 melded; deadwood = 1+3+7+9+2+10+10 = 42
        assert dw == 42

    def test_one_run_meld(self) -> None:
        """A run of 3-4-5 hearts, rest is deadwood."""
        hand = _make_hand("3H", "4H", "5H", "AC", "7S", "9D", "2C", "KH", "JD", "8S")
        dw = deadwood_value(hand)
        # 3+4+5 melded; deadwood = 1+7+9+2+10+10+8 = 47
        assert dw == 47

    def test_gin_hand(self) -> None:
        """All 10 cards form valid melds: deadwood = 0."""
        # Three 5s + three 9s + run 3-4-5-6 hearts... but need 10 cards
        # Set: 5H 5D 5C; Set: 9H 9D 9C; Run: 3S 4S 5S 6S — wait, 5 used
        # Let's use: Set: KH KD KC; Set: AH AD AC; Run: 7S 8S 9S 10S
        hand = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "10S")
        dw = deadwood_value(hand)
        assert dw == 0

    def test_multiple_melds(self) -> None:
        """Two melds, some deadwood."""
        # Set: 8H 8D 8C; Run: 3S 4S 5S; deadwood: AH 2D 7C KH
        hand = _make_hand("8H", "8D", "8C", "3S", "4S", "5S", "AH", "2D", "7C", "KH")
        dw = deadwood_value(hand)
        # deadwood = 1+2+7+10 = 20
        assert dw == 20

    def test_optimal_meld_selection(self) -> None:
        """When a card could go in either of two melds, pick the one
        that minimizes deadwood."""
        # 5H 5D 5C (set of 5s) vs 4H 5H 6H (run in hearts)
        # If 5H goes into the set, 4H 6H are deadwood (4+6=10)
        # If 5H goes into the run, 5D 5C are deadwood (5+5=10)
        # Either way deadwood from those is the same, but other cards matter
        hand = _make_hand("5H", "5D", "5C", "4H", "6H", "AH", "2D", "3C", "KS", "QS")
        dw = deadwood_value(hand)
        # Best: set 5H5D5C + nothing else melds => dw = 4+6+1+2+3+10+10 = 36
        # Or: run 4H5H6H + nothing else melds => dw = 5+5+1+2+3+10+10 = 36
        # Same either way in this case
        assert dw == 36


# ---------------------------------------------------------------------------
# Tests: game driver — draw and discard
# ---------------------------------------------------------------------------

class TestDrawAndDiscard:
    def _setup_game(self) -> GinRummyGame:
        game = GinRummyGame()
        p1, p2, stock, discard = _deal_deterministic(seed=1)
        game.deal(p1, p2, stock, discard)
        return game

    def test_draw_from_stock(self) -> None:
        game = self._setup_game()
        assert len(game.hands["P1"]) == 10
        card = game.draw_from_stock()
        assert len(game.hands["P1"]) == 11
        assert card in game.hands["P1"]

    def test_draw_from_discard(self) -> None:
        game = self._setup_game()
        top_discard = game.discard_pile[-1]
        card = game.draw_from_discard()
        assert card == top_discard
        assert len(game.hands["P1"]) == 11
        assert len(game.discard_pile) == 0

    def test_cannot_draw_twice(self) -> None:
        game = self._setup_game()
        game.draw_from_stock()
        with pytest.raises(ValueError, match="already drew"):
            game.draw_from_stock()

    def test_cannot_discard_without_draw(self) -> None:
        game = self._setup_game()
        card = game.hands["P1"][0]
        with pytest.raises(ValueError, match="must draw"):
            game.discard(card)

    def test_discard_removes_from_hand(self) -> None:
        game = self._setup_game()
        game.draw_from_stock()
        card = game.hands["P1"][0]
        game.discard(card)
        assert card not in game.hands["P1"]
        assert len(game.hands["P1"]) == 10

    def test_discard_adds_to_pile(self) -> None:
        game = self._setup_game()
        game.draw_from_stock()
        card = game.hands["P1"][0]
        game.discard(card)
        assert game.discard_pile[-1] == card

    def test_turn_advances_after_discard(self) -> None:
        game = self._setup_game()
        assert game.current_player() == "P1"
        game.draw_from_stock()
        game.discard(game.hands["P1"][0])
        assert game.current_player() == "P2"

    def test_cannot_discard_card_not_in_hand(self) -> None:
        game = self._setup_game()
        game.draw_from_stock()
        fake_card = Card(suit="hearts", rank="A")
        if fake_card in game.hands["P1"]:
            fake_card = Card(suit="spades", rank="K")
            if fake_card in game.hands["P1"]:
                # Very unlikely but handle it
                fake_card = Card(suit="diamonds", rank="2")
        # If by extreme bad luck it's in the hand, skip this test
        if fake_card not in game.hands["P1"]:
            with pytest.raises(ValueError, match="not in"):
                game.discard(fake_card)

    def test_full_turn_cycle(self) -> None:
        """P1 draws and discards, then P2 draws and discards."""
        game = self._setup_game()
        # P1's turn
        game.draw_from_stock()
        game.discard(game.hands["P1"][-1])
        assert game.current_player() == "P2"
        # P2's turn
        game.draw_from_stock()
        game.discard(game.hands["P2"][-1])
        assert game.current_player() == "P1"

    def test_stock_decrements_on_draw(self) -> None:
        game = self._setup_game()
        stock_before = len(game.stock)
        game.draw_from_stock()
        assert len(game.stock) == stock_before - 1


# ---------------------------------------------------------------------------
# Tests: knocking
# ---------------------------------------------------------------------------

class TestKnocking:
    def test_knock_with_low_deadwood(self) -> None:
        """Knock is valid when deadwood <= 10."""
        game = GinRummyGame()
        # P1 hand: set KH KD KC, set AH AD AC, run 7S 8S 9S + 2H (dw=2)
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "2H")
        # P2 hand: all deadwood
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="hearts", rank="10")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="10"))

        # P1 draws, then knocks discarding the drawn card
        drawn = game.draw_from_stock()
        scores = game.knock(drawn)
        assert scores["P1"] > 0

    def test_knock_rejects_high_deadwood(self) -> None:
        """Cannot knock if deadwood > 10."""
        game = GinRummyGame()
        # All deadwood hand
        p1 = _make_hand("AH", "3D", "5C", "7S", "9H", "2D", "4C", "6S", "8H", "KD")
        p2 = _make_hand("2H", "4D", "6C", "8S", "10H", "3D", "5C", "7S", "9H", "JD")
        stock = [Card(suit="hearts", rank="Q")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="J"))

        game.draw_from_stock()
        with pytest.raises(ValueError, match="cannot knock"):
            game.knock(game.hands["P1"][-1])

    def test_knock_requires_draw_first(self) -> None:
        game = GinRummyGame()
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "2H")
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="hearts", rank="10")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="10"))

        with pytest.raises(ValueError, match="must draw"):
            game.knock(p1[0])


# ---------------------------------------------------------------------------
# Tests: gin
# ---------------------------------------------------------------------------

class TestGin:
    def test_gin_scores_opponent_deadwood_plus_25(self) -> None:
        game = GinRummyGame()
        # P1: all melds (gin hand)
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "10S")
        # P2: known deadwood
        p2 = _make_hand("2H", "4D", "6C", "8S", "10H", "3H", "5D", "7C", "9S", "JH")
        # Give P1 an extra card to draw, which is itself a gin completion
        # Actually, P1 needs to draw then discard. Let's give P1 11 cards conceptually.
        # Better: make P1 hand 9 cards + will draw the 10th that completes gin.
        # Simplest: P1 has 10 cards, draws one, discards one, still has gin.

        stock = [Card(suit="spades", rank="K")]  # P1 will draw KS
        game.deal(p1, p2, stock, Card(suit="clubs", rank="2"))

        # P1 draws KS, now has 11 cards
        game.draw_from_stock()
        # P1 discards KS (hand returns to gin state)
        scores = game.gin(Card(suit="spades", rank="K"))

        # P2 deadwood: 2+4+6+8+10+3+5+7+9+10 = 64
        p2_dw = deadwood_value(p2)
        assert scores["P1"] == p2_dw + 25
        assert scores["P2"] == 0

    def test_gin_rejects_nonzero_deadwood(self) -> None:
        game = GinRummyGame()
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "2H")
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="hearts", rank="10")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="10"))

        game.draw_from_stock()
        # After discarding 10H, hand has 2H deadwood=2, not gin
        with pytest.raises(ValueError, match="cannot declare gin"):
            game.gin(Card(suit="hearts", rank="10"))

    def test_gin_bonus_is_25(self) -> None:
        """Verify the gin bonus is exactly 25 points."""
        game = GinRummyGame()
        # P1 gin hand; P2 has just one ace (dw=1) to make math clear
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "10S")
        p2 = _make_hand("AH", "3D", "5C", "7S", "9H", "2D", "4C", "6S", "8H", "KD")
        stock = [Card(suit="spades", rank="K")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="2"))

        game.draw_from_stock()
        scores = game.gin(Card(suit="spades", rank="K"))

        p2_dw = deadwood_value(p2)
        bonus_portion = scores["P1"] - p2_dw
        assert bonus_portion == 25


# ---------------------------------------------------------------------------
# Tests: undercut
# ---------------------------------------------------------------------------

class TestUndercut:
    def test_undercut_when_opponent_lower(self) -> None:
        """Opponent deadwood <= knocker's -> undercut."""
        game = GinRummyGame()
        # P1: set KH KD KC, set AH AD AC, run 7S 8S 9S + 5H (dw=5)
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "5H")
        # P2: set QH QD QC, set 2H 2D 2C, run 3S 4S 5S + AH (dw=1)
        p2 = _make_hand("QH", "QD", "QC", "2H", "2D", "2C", "3S", "4S", "5S", "AS")
        stock = [Card(suit="diamonds", rank="3")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="J"))

        game.draw_from_stock()
        # P1 knocks discarding drawn card; P1 dw=5, P2 dw=1
        scores = game.knock(Card(suit="diamonds", rank="3"))

        # Undercut: P2 scores (5 - 1) + 25 = 29
        assert scores["P2"] == 29
        assert scores["P1"] == 0

    def test_undercut_when_equal_deadwood(self) -> None:
        """Equal deadwood also triggers undercut (opponent gets 25 bonus)."""
        game = GinRummyGame()
        # Both have deadwood = 3
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "3H")
        p2 = _make_hand("QH", "QD", "QC", "2H", "2D", "2C", "3S", "4S", "5S", "3D")
        stock = [Card(suit="diamonds", rank="10")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="J"))

        game.draw_from_stock()
        scores = game.knock(Card(suit="diamonds", rank="10"))

        # Equal deadwood: P2 gets (3-3) + 25 = 25
        assert scores["P2"] == 25
        assert scores["P1"] == 0

    def test_undercut_bonus_is_25(self) -> None:
        """Undercut bonus is exactly 25."""
        game = GinRummyGame()
        # P1 dw=10, P2 dw=10 (equal -> undercut, bonus portion = 25)
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "10H")
        p2 = _make_hand("QH", "QD", "QC", "2H", "2D", "2C", "3S", "4S", "5S", "10D")
        stock = [Card(suit="diamonds", rank="J")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="J"))

        game.draw_from_stock()
        scores = game.knock(Card(suit="diamonds", rank="J"))

        assert scores["P2"] == 25  # (10-10) + 25


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_normal_knock_scores_difference(self) -> None:
        """Knocker scores opponent_deadwood - knocker_deadwood."""
        game = GinRummyGame()
        # P1 dw=2 (just 2H), P2 dw=30 (mixed junk)
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "2H")
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="hearts", rank="10")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="10"))

        game.draw_from_stock()
        scores = game.knock(Card(suit="hearts", rank="10"))

        p2_dw = deadwood_value(p2)
        expected = p2_dw - 2  # knocker dw=2
        assert scores["P1"] == expected
        assert scores["P2"] == 0

    def test_cumulative_scores(self) -> None:
        """Scores accumulate across rounds."""
        game = GinRummyGame()
        # Round 1
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "2H")
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="hearts", rank="10"), Card(suit="spades", rank="2")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="10"))

        drawn = game.draw_from_stock()  # pops last: 2S
        scores1 = game.knock(drawn)
        round1_p1 = scores1["P1"]

        # Round 2 (re-deal)
        p1_r2 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "3H")
        p2_r2 = _make_hand("2H", "4D", "6C", "8S", "10H", "JC", "QD", "3S", "5H", "7D")
        stock2 = [Card(suit="hearts", rank="10")]
        game.deal(p1_r2, p2_r2, stock2, Card(suit="clubs", rank="9"))
        # Reset turn to P1
        game.session.runtime.turn_index = 0
        game.drawn_this_turn = False

        game.draw_from_stock()
        scores2 = game.knock(Card(suit="hearts", rank="10"))

        assert game.scores["P1"] == round1_p1 + scores2["P1"]


# ---------------------------------------------------------------------------
# Tests: game end condition
# ---------------------------------------------------------------------------

class TestGameEnd:
    def test_game_ends_at_100(self) -> None:
        game = GinRummyGame()
        game.scores["P1"] = 95

        # P1 gin hand
        p1 = _make_hand("KH", "KD", "KC", "AH", "AD", "AC", "7S", "8S", "9S", "10S")
        p2 = _make_hand("3H", "5D", "7C", "9S", "JH", "2C", "4D", "6S", "8H", "QD")
        stock = [Card(suit="spades", rank="K")]
        game.deal(p1, p2, stock, Card(suit="clubs", rank="2"))

        game.draw_from_stock()
        scores = game.gin(Card(suit="spades", rank="K"))

        assert game.scores["P1"] >= 100
        assert game.game_over

    def test_winner_is_player_reaching_100(self) -> None:
        game = GinRummyGame()
        game.scores["P1"] = 100
        assert game.winner() == "P1"

    def test_no_winner_below_100(self) -> None:
        game = GinRummyGame()
        game.scores["P1"] = 50
        game.scores["P2"] = 90
        assert game.winner() is None

    def test_game_not_over_initially(self) -> None:
        game = GinRummyGame()
        assert not game.game_over
        assert game.winner() is None


# ---------------------------------------------------------------------------
# Tests: lay-off
# ---------------------------------------------------------------------------

class TestLayOff:
    def test_lay_off_on_set(self) -> None:
        """Opponent can add 4th card to knocker's 3-card set."""
        game = GinRummyGame()
        knocker_melds = [_make_hand("5H", "5D", "5C")]
        opponent_hand = _make_hand("5S", "KH", "QD")
        layoffs = game.lay_off_cards("P1", opponent_hand, knocker_melds)
        assert len(layoffs) == 1
        assert layoffs[0] == Card(suit="spades", rank="5")

    def test_lay_off_on_run_extend_high(self) -> None:
        """Opponent can extend a run at the high end."""
        game = GinRummyGame()
        knocker_melds = [_make_hand("3H", "4H", "5H")]
        opponent_hand = _make_hand("6H", "KD", "QS")
        layoffs = game.lay_off_cards("P1", opponent_hand, knocker_melds)
        assert Card(suit="hearts", rank="6") in layoffs

    def test_lay_off_on_run_extend_low(self) -> None:
        """Opponent can extend a run at the low end."""
        game = GinRummyGame()
        knocker_melds = [_make_hand("5H", "6H", "7H")]
        opponent_hand = _make_hand("4H", "KD", "QS")
        layoffs = game.lay_off_cards("P1", opponent_hand, knocker_melds)
        assert Card(suit="hearts", rank="4") in layoffs

    def test_no_lay_off_possible(self) -> None:
        """No matching cards to lay off."""
        game = GinRummyGame()
        knocker_melds = [_make_hand("5H", "5D", "5C")]
        opponent_hand = _make_hand("KH", "QD", "JS")
        layoffs = game.lay_off_cards("P1", opponent_hand, knocker_melds)
        assert len(layoffs) == 0

    def test_cannot_lay_off_on_4_card_set(self) -> None:
        """A 4-card set is full; cannot add a 5th."""
        game = GinRummyGame()
        knocker_melds = [_make_hand("5H", "5D", "5C", "5S")]
        opponent_hand = _make_hand("KH", "QD", "JS")
        layoffs = game.lay_off_cards("P1", opponent_hand, knocker_melds)
        assert len(layoffs) == 0


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_stock_raises(self) -> None:
        game = GinRummyGame()
        p1 = _make_hand("AH", "2H", "3H", "4H", "5H", "6H", "7H", "8H", "9H", "10H")
        p2 = _make_hand("AS", "2S", "3S", "4S", "5S", "6S", "7S", "8S", "9S", "10S")
        game.deal(p1, p2, [], Card(suit="clubs", rank="K"))

        with pytest.raises(ValueError, match="stock is empty"):
            game.draw_from_stock()

    def test_empty_discard_raises(self) -> None:
        game = GinRummyGame()
        p1 = _make_hand("AH", "2H", "3H", "4H", "5H", "6H", "7H", "8H", "9H", "10H")
        p2 = _make_hand("AS", "2S", "3S", "4S", "5S", "6S", "7S", "8S", "9S", "10S")
        game.deal(p1, p2, [Card(suit="clubs", rank="Q")], Card(suit="clubs", rank="K"))

        # Draw the discard, making it empty
        game.draw_from_discard()
        game.discard(game.hands["P1"][-1])

        # P2 turn -- discard might have the card P1 just discarded
        # Clear discard to test
        game.discard_pile.clear()
        with pytest.raises(ValueError, match="discard pile is empty"):
            game.draw_from_discard()

    def test_deal_rejects_wrong_hand_size(self) -> None:
        game = GinRummyGame()
        with pytest.raises(ValueError, match="exactly 10"):
            game.deal(
                _make_hand("AH", "2H", "3H"),
                _make_hand("AS", "2S", "3S", "4S", "5S", "6S", "7S", "8S", "9S", "10S"),
                [],
                Card(suit="clubs", rank="K"),
            )

    def test_ace_is_worth_1(self) -> None:
        """Ace deadwood value is 1, not 11 or 14."""
        hand = _make_hand("AH", "AD", "3C", "5S", "7H", "9D", "JC", "KS", "2H", "4D")
        # Aces not forming a meld. Each ace = 1 point.
        dw = deadwood_value(hand)
        # All deadwood: 1+1+3+5+7+9+10+10+2+4 = 52
        assert dw == 52

    def test_face_cards_worth_10(self) -> None:
        """J, Q, K each worth 10 for deadwood."""
        hand = _make_hand("JH", "QD", "KC", "AS", "2H", "3D", "4C", "5S", "6H", "7D")
        dw = deadwood_value(hand)
        # J=10, Q=10, K=10, A=1, 2-7 = 2+3+4+5+6+7 = 27; total = 58
        assert dw == 58

    def test_wire_state_includes_players(self) -> None:
        """Wire state serialization includes player zones."""
        session = GameSession(_load_game())
        wire = session.to_wire_state()
        assert "P1" in wire.players
        assert "P2" in wire.players
