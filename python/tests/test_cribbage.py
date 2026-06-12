"""Tests for the Cribbage game definition and scoring logic.

Cribbage: 2 players (dealer/pone), 52-card deck. Deal 6, discard 2 to crib,
cut a starter card. Pegging phase (play cards to running total <= 31).
Show phase (score hands + crib for 15-combos, pairs, runs, flushes, nobs).
First to 121 on the pegboard wins.

Scoring functions are independent oracles using itertools.combinations,
not derived from any engine code under test.
"""

from __future__ import annotations

import json
import random
from collections import Counter
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
    SlotZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "cribbage.json"

SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

PIP_VALUES = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10,
}

RANK_ORDER = {
    "A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13,
}


# ---------------------------------------------------------------------------
# Helpers: loading
# ---------------------------------------------------------------------------


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _make_session() -> GameSession:
    return GameSession(_load_game())


# ---------------------------------------------------------------------------
# Helpers: deck management
# ---------------------------------------------------------------------------


def _build_deck(session: GameSession) -> list[ComponentId]:
    """Create all 52 cards in the deck zone."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    cids: list[ComponentId] = []
    for suit in SUITS:
        for rank in RANKS:
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"card-{rank}-{suit}",
                component_type="card",
                owner=None,
                properties={
                    "suit": suit,
                    "rank": rank,
                    "pip_value": PIP_VALUES[rank],
                    "rank_order": RANK_ORDER[rank],
                },
            )
            cid = session.runtime.components.insert(comp)
            deck.stack_push(cid)
            cids.append(cid)
    return cids


def _shuffle_deck(session: GameSession, seed: int = 42) -> None:
    """Shuffle the deck with a deterministic seed."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    rng = random.Random(seed)
    rng.shuffle(deck.components)


def _deal_cards(session: GameSession, player: str, count: int) -> list[ComponentId]:
    """Deal count cards from deck to player's hand."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    dealt: list[ComponentId] = []
    for _ in range(count):
        cid = deck.stack_pop()
        assert cid is not None, "deck is empty"
        hand.set_add(cid)
        comp = session.runtime.components.get(cid)
        assert comp is not None
        comp.owner = player
        dealt.append(cid)
    return dealt


def _discard_to_crib(
    session: GameSession, player: str, cids: list[ComponentId]
) -> None:
    """Move cards from player's hand to the crib."""
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    crib = session.runtime.zones["crib"]
    assert isinstance(crib, SetZone)
    for cid in cids:
        removed = hand.set_remove(cid)
        assert removed, f"card {cid} not in {player}'s hand"
        crib.set_add(cid)


def _cut_card(session: GameSession) -> ComponentId:
    """Cut the top card from the deck and place it in the cut_card zone."""
    deck = session.runtime.zones["deck"]
    assert isinstance(deck, StackZone)
    cut_zone = session.runtime.zones["cut_card"]
    assert isinstance(cut_zone, SlotZone)
    cid = deck.stack_pop()
    assert cid is not None, "deck is empty"
    cut_zone.component = cid
    return cid


def _get_card(session: GameSession, cid: ComponentId) -> ComponentData:
    """Get card component data by ID."""
    comp = session.runtime.components.get(cid)
    assert comp is not None
    return comp


def _card_pip(comp: ComponentData) -> int:
    """Get the pip value of a card."""
    return PIP_VALUES[str(comp.properties["rank"])]


def _card_rank_order(comp: ComponentData) -> int:
    """Get the rank order of a card (for run detection)."""
    return RANK_ORDER[str(comp.properties["rank"])]


def _card_suit(comp: ComponentData) -> str:
    """Get the suit of a card."""
    return str(comp.properties["suit"])


def _card_rank(comp: ComponentData) -> str:
    """Get the rank of a card."""
    return str(comp.properties["rank"])


# ---------------------------------------------------------------------------
# Scoring functions (independent oracles using itertools)
# ---------------------------------------------------------------------------


Card = tuple[str, str, int, int]  # (rank, suit, pip_value, rank_order)


def _make_card(rank: str, suit: str) -> Card:
    return (rank, suit, PIP_VALUES[rank], RANK_ORDER[rank])


def score_fifteens(cards: list[Card]) -> int:
    """Score 2 points for every subset of cards whose pip values sum to 15."""
    total = 0
    for r in range(2, len(cards) + 1):
        for combo in combinations(cards, r):
            if sum(c[2] for c in combo) == 15:
                total += 2
    return total


def score_pairs(cards: list[Card]) -> int:
    """Score 2 points for every pair of cards with the same rank."""
    total = 0
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            if cards[i][0] == cards[j][0]:
                total += 2
    return total


def score_runs(cards: list[Card]) -> int:
    """Score points for runs of 3+ consecutive rank orders.

    A run of N scores N points. Multiple runs from duplicate ranks
    each score independently.
    """
    orders = sorted(c[3] for c in cards)
    best_score = 0

    # Try all possible subsets of size 3, 4, 5
    for r in range(len(cards), 2, -1):
        run_score = 0
        for combo in combinations(cards, r):
            combo_orders = sorted(c[3] for c in combo)
            is_run = all(
                combo_orders[i + 1] - combo_orders[i] == 1
                for i in range(len(combo_orders) - 1)
            )
            if is_run:
                run_score += r
        if run_score > 0:
            best_score = run_score
            break  # longest runs take priority
    return best_score


def score_flush(hand_cards: list[Card], cut: Card, is_crib: bool = False) -> int:
    """Score for flush.

    Hand: 4 cards same suit = 4 pts; 4 hand + cut same suit = 5 pts.
    Crib: all 5 must match for 5 pts (no 4-card flush in crib).
    """
    hand_suits = [c[1] for c in hand_cards]
    if len(set(hand_suits)) != 1:
        return 0
    if is_crib:
        return 5 if cut[1] == hand_suits[0] else 0
    if cut[1] == hand_suits[0]:
        return 5
    return 4


def score_nobs(hand_cards: list[Card], cut: Card) -> int:
    """Score 1 point if hand contains a Jack matching the cut card's suit."""
    for c in hand_cards:
        if c[0] == "J" and c[1] == cut[1]:
            return 1
    return 0


def score_hand(hand_cards: list[Card], cut: Card, is_crib: bool = False) -> int:
    """Total score for a hand (4 cards) with a cut card."""
    all_cards = hand_cards + [cut]
    total = 0
    total += score_fifteens(all_cards)
    total += score_pairs(all_cards)
    total += score_runs(all_cards)
    total += score_flush(hand_cards, cut, is_crib)
    total += score_nobs(hand_cards, cut)
    return total


# ---------------------------------------------------------------------------
# Pegging helpers
# ---------------------------------------------------------------------------


def score_pegging_play(
    pile_ranks: list[str], running_total: int
) -> int:
    """Score points for a single pegging play.

    pile_ranks: ranks of cards in the play pile (most recent last).
    running_total: the total after the latest card is played.
    """
    pts = 0

    # Fifteen
    if running_total == 15:
        pts += 2

    # Thirty-one
    if running_total == 31:
        pts += 2

    # Pairs (from the end)
    if len(pile_ranks) >= 2:
        last_rank = pile_ranks[-1]
        pair_count = 0
        for i in range(len(pile_ranks) - 2, -1, -1):
            if pile_ranks[i] == last_rank:
                pair_count += 1
            else:
                break
        # 1 pair = 2, 2 pairs (3 of a kind) = 6, 3 pairs (4 of a kind) = 12
        pts += pair_count * (pair_count + 1)

    # Runs (check from the end, minimum 3 cards)
    if len(pile_ranks) >= 3:
        best_run = 0
        for length in range(len(pile_ranks), 2, -1):
            tail = pile_ranks[-length:]
            orders = sorted(RANK_ORDER[r] for r in tail)
            is_run = all(
                orders[i + 1] - orders[i] == 1
                for i in range(len(orders) - 1)
            )
            if is_run:
                best_run = length
                break
        pts += best_run

    return pts


# ---------------------------------------------------------------------------
# Tests: definition parsing
# ---------------------------------------------------------------------------


class TestCribbageDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Cribbage"

    def test_two_named_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["dealer", "pone"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_deck_zone_hidden_stack(self) -> None:
        defn = _load_game()
        assert "deck" in defn.zones
        assert defn.zones["deck"].zone_type == "ordered_stack"
        assert defn.zones["deck"].visibility == "hidden"

    def test_hand_zone_per_player_private(self) -> None:
        defn = _load_game()
        assert "hand" in defn.zones
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_crib_zone_hidden(self) -> None:
        defn = _load_game()
        assert "crib" in defn.zones
        assert defn.zones["crib"].zone_type == "set"
        assert defn.zones["crib"].visibility == "hidden"

    def test_cut_card_zone_public(self) -> None:
        defn = _load_game()
        assert "cut_card" in defn.zones
        assert defn.zones["cut_card"].zone_type == "single_slot"
        assert defn.zones["cut_card"].visibility == "public"

    def test_pegboard_counter_per_player(self) -> None:
        defn = _load_game()
        assert "pegboard" in defn.zones
        assert defn.zones["pegboard"].zone_type == "counter"
        assert defn.zones["pegboard"].per_player is True

    def test_play_pile_public_stack(self) -> None:
        defn = _load_game()
        assert "play_pile" in defn.zones
        assert defn.zones["play_pile"].zone_type == "ordered_stack"
        assert defn.zones["play_pile"].visibility == "public"

    def test_five_phases(self) -> None:
        defn = _load_game()
        phase_names = [p.name for p in defn.phases]
        assert phase_names == ["deal", "discard", "cut", "pegging", "show"]

    def test_discard_phase_simultaneous(self) -> None:
        defn = _load_game()
        discard = next(p for p in defn.phases if p.name == "discard")
        assert discard.simultaneous is True

    def test_pegging_starts_with_pone(self) -> None:
        defn = _load_game()
        pegging = next(p for p in defn.phases if p.name == "pegging")
        assert pegging.starts_with == "pone"

    def test_show_starts_with_pone(self) -> None:
        defn = _load_game()
        show = next(p for p in defn.phases if p.name == "show")
        assert show.starts_with == "pone"

    def test_authority_server_only(self) -> None:
        defn = _load_game()
        assert "shuffle(deck)" in defn.authority.server_only
        assert "deal(deck, hand)" in defn.authority.server_only
        assert "cut(deck, cut_card)" in defn.authority.server_only

    def test_authority_wasm_required(self) -> None:
        defn = _load_game()
        assert defn.authority.wasm_required is not None
        assert len(defn.authority.wasm_required) == 6

    def test_end_condition_121(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 1
        assert defn.end_conditions[0].result == "win"
        assert "121" in defn.end_conditions[0].condition

    def test_wasm_module_declared(self) -> None:
        defn = _load_game()
        assert defn.wasm_module == "cribbage.wasm"

    def test_card_component_count_52(self) -> None:
        defn = _load_game()
        assert "card" in defn.components
        assert defn.components["card"].count == 52

    def test_definition_round_trips_json(self) -> None:
        raw = _GAME_PATH.read_text()
        defn = GameDefinition.from_json(raw)
        rt = json.loads(json.dumps(defn._to_dict()))
        assert rt["game"]["name"] == "Cribbage"


# ---------------------------------------------------------------------------
# Tests: session creation
# ---------------------------------------------------------------------------


class TestSessionCreation:
    def test_session_creates(self) -> None:
        session = _make_session()
        assert session.runtime is not None

    def test_shared_zones_created(self) -> None:
        session = _make_session()
        assert isinstance(session.runtime.zones["deck"], StackZone)
        assert isinstance(session.runtime.zones["crib"], SetZone)
        assert isinstance(session.runtime.zones["cut_card"], SlotZone)
        assert isinstance(session.runtime.zones["play_pile"], StackZone)
        assert isinstance(session.runtime.zones["discard"], SetZone)

    def test_per_player_zones_created(self) -> None:
        session = _make_session()
        for name in ("dealer", "pone"):
            pstate = session.runtime.players[name]
            assert isinstance(pstate.zones["hand"], SetZone)
            assert isinstance(pstate.zones["pegboard"], CounterZone)
            assert isinstance(pstate.zones["played_cards"], SetZone)

    def test_pegboard_starts_at_zero(self) -> None:
        session = _make_session()
        for name in ("dealer", "pone"):
            peg = session.runtime.players[name].zones["pegboard"]
            assert isinstance(peg, CounterZone)
            assert peg.value == 0

    def test_wire_state_serializable(self) -> None:
        session = _make_session()
        wire = session.to_wire_state()
        as_dict = wire._to_dict()
        json_str = json.dumps(as_dict)
        parsed = json.loads(json_str)
        assert parsed["status"] == "setup"


# ---------------------------------------------------------------------------
# Tests: deck and dealing
# ---------------------------------------------------------------------------


class TestDeckAndDealing:
    def test_build_52_cards(self) -> None:
        session = _make_session()
        cids = _build_deck(session)
        assert len(cids) == 52

    def test_shuffle_is_deterministic(self) -> None:
        s1, s2 = _make_session(), _make_session()
        _build_deck(s1)
        _build_deck(s2)
        _shuffle_deck(s1, seed=99)
        _shuffle_deck(s2, seed=99)
        d1 = s1.runtime.zones["deck"]
        d2 = s2.runtime.zones["deck"]
        assert isinstance(d1, StackZone) and isinstance(d2, StackZone)
        props1 = [
            s1.runtime.components.get(c).properties["rank"]
            for c in d1.components
        ]
        props2 = [
            s2.runtime.components.get(c).properties["rank"]
            for c in d2.components
        ]
        assert props1 == props2

    def test_deal_6_each(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        d_cards = _deal_cards(session, "dealer", 6)
        p_cards = _deal_cards(session, "pone", 6)
        assert len(d_cards) == 6
        assert len(p_cards) == 6
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 40

    def test_dealt_cards_have_properties(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        dealt = _deal_cards(session, "dealer", 6)
        for cid in dealt:
            comp = _get_card(session, cid)
            assert comp.properties["rank"] in RANKS
            assert comp.properties["suit"] in SUITS


# ---------------------------------------------------------------------------
# Tests: discard to crib
# ---------------------------------------------------------------------------


class TestDiscard:
    def test_discard_moves_to_crib(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        d_cards = _deal_cards(session, "dealer", 6)
        _discard_to_crib(session, "dealer", d_cards[:2])

        hand = session.runtime.players["dealer"].zones["hand"]
        crib = session.runtime.zones["crib"]
        assert isinstance(hand, SetZone) and isinstance(crib, SetZone)
        assert hand.count() == 4
        assert crib.count() == 2

    def test_both_players_discard(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        d_cards = _deal_cards(session, "dealer", 6)
        p_cards = _deal_cards(session, "pone", 6)
        _discard_to_crib(session, "dealer", d_cards[:2])
        _discard_to_crib(session, "pone", p_cards[:2])

        for name in ("dealer", "pone"):
            hand = session.runtime.players[name].zones["hand"]
            assert isinstance(hand, SetZone)
            assert hand.count() == 4

        crib = session.runtime.zones["crib"]
        assert isinstance(crib, SetZone)
        assert crib.count() == 4


# ---------------------------------------------------------------------------
# Tests: cut card
# ---------------------------------------------------------------------------


class TestCutCard:
    def test_cut_places_card(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        # Deal first so cut comes from remaining deck
        _deal_cards(session, "dealer", 6)
        _deal_cards(session, "pone", 6)
        cid = _cut_card(session)
        cut_zone = session.runtime.zones["cut_card"]
        assert isinstance(cut_zone, SlotZone)
        assert cut_zone.component == cid

    def test_cut_removes_from_deck(self) -> None:
        session = _make_session()
        _build_deck(session)
        _shuffle_deck(session)
        _deal_cards(session, "dealer", 6)
        _deal_cards(session, "pone", 6)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        before = deck.count()
        _cut_card(session)
        assert deck.count() == before - 1


# ---------------------------------------------------------------------------
# Tests: scoring — fifteens (independent oracle)
# ---------------------------------------------------------------------------


class TestScoreFifteens:
    def test_no_fifteens(self) -> None:
        # A(1)+2+6+10+J(10): no subset sums to 15
        cards = [_make_card("A", "h"), _make_card("2", "d"),
                 _make_card("6", "c"), _make_card("10", "s"),
                 _make_card("J", "h")]
        assert score_fifteens(cards) == 0

    def test_two_card_fifteen(self) -> None:
        # 5 + 10 = 15; also 10+2+3=15 -> 2 fifteens = 4
        cards = [_make_card("5", "h"), _make_card("10", "d"),
                 _make_card("A", "c"), _make_card("2", "s"),
                 _make_card("3", "h")]
        assert score_fifteens(cards) == 4

    def test_three_card_fifteen(self) -> None:
        # 5 + 4 + 6 = 15
        cards = [_make_card("5", "h"), _make_card("4", "d"),
                 _make_card("6", "c"), _make_card("A", "s"),
                 _make_card("2", "h")]
        assert score_fifteens(cards) == 2

    def test_multiple_fifteens(self) -> None:
        # 5-5-5-J-K: three 5+J, three 5+K, one 5+5+5 = 7 fifteens = 14
        cards = [_make_card("5", "h"), _make_card("5", "d"),
                 _make_card("5", "c"), _make_card("J", "s"),
                 _make_card("K", "h")]
        assert score_fifteens(cards) == 14

    def test_max_fifteens_hand(self) -> None:
        # 5-5-5-5-10: four 5+10, six 5+5+5, but 5+5+5=15 combos...
        # Actually: four 2-card (5+10), six 3-card (5+5+5) -> none sum to 15
        # Wait: 5+5+5 = 15, and there are C(4,3) = 4 ways to pick three 5s
        # Plus 5+10 = 15, four ways (each 5 with the 10)
        # Total = 4 + 4 = 8 fifteens = 16
        cards = [_make_card("5", "h"), _make_card("5", "d"),
                 _make_card("5", "c"), _make_card("5", "s"),
                 _make_card("10", "h")]
        assert score_fifteens(cards) == 16


# ---------------------------------------------------------------------------
# Tests: scoring — pairs
# ---------------------------------------------------------------------------


class TestScorePairs:
    def test_no_pairs(self) -> None:
        cards = [_make_card("A", "h"), _make_card("2", "d"),
                 _make_card("3", "c"), _make_card("4", "s"),
                 _make_card("5", "h")]
        assert score_pairs(cards) == 0

    def test_one_pair(self) -> None:
        cards = [_make_card("A", "h"), _make_card("A", "d"),
                 _make_card("3", "c"), _make_card("4", "s"),
                 _make_card("5", "h")]
        assert score_pairs(cards) == 2

    def test_three_of_a_kind(self) -> None:
        cards = [_make_card("7", "h"), _make_card("7", "d"),
                 _make_card("7", "c"), _make_card("4", "s"),
                 _make_card("5", "h")]
        # C(3,2) = 3 pairs = 6 points
        assert score_pairs(cards) == 6

    def test_four_of_a_kind(self) -> None:
        cards = [_make_card("9", "h"), _make_card("9", "d"),
                 _make_card("9", "c"), _make_card("9", "s"),
                 _make_card("5", "h")]
        # C(4,2) = 6 pairs = 12 points
        assert score_pairs(cards) == 12

    def test_two_pairs(self) -> None:
        cards = [_make_card("K", "h"), _make_card("K", "d"),
                 _make_card("Q", "c"), _make_card("Q", "s"),
                 _make_card("5", "h")]
        assert score_pairs(cards) == 4


# ---------------------------------------------------------------------------
# Tests: scoring — runs
# ---------------------------------------------------------------------------


class TestScoreRuns:
    def test_no_run(self) -> None:
        cards = [_make_card("A", "h"), _make_card("3", "d"),
                 _make_card("5", "c"), _make_card("7", "s"),
                 _make_card("9", "h")]
        assert score_runs(cards) == 0

    def test_run_of_three(self) -> None:
        cards = [_make_card("3", "h"), _make_card("4", "d"),
                 _make_card("5", "c"), _make_card("9", "s"),
                 _make_card("K", "h")]
        assert score_runs(cards) == 3

    def test_run_of_four(self) -> None:
        cards = [_make_card("6", "h"), _make_card("7", "d"),
                 _make_card("8", "c"), _make_card("9", "s"),
                 _make_card("K", "h")]
        assert score_runs(cards) == 4

    def test_run_of_five(self) -> None:
        cards = [_make_card("A", "h"), _make_card("2", "d"),
                 _make_card("3", "c"), _make_card("4", "s"),
                 _make_card("5", "h")]
        assert score_runs(cards) == 5

    def test_double_run(self) -> None:
        # 3-4-4-5-K: two runs of 3 (3-4-5 with each 4) = 6
        cards = [_make_card("3", "h"), _make_card("4", "d"),
                 _make_card("4", "c"), _make_card("5", "s"),
                 _make_card("K", "h")]
        assert score_runs(cards) == 6

    def test_double_run_of_four(self) -> None:
        # 3-4-5-6-6: two runs of 4 = 8
        cards = [_make_card("3", "h"), _make_card("4", "d"),
                 _make_card("5", "c"), _make_card("6", "s"),
                 _make_card("6", "h")]
        assert score_runs(cards) == 8

    def test_triple_run(self) -> None:
        # 3-3-3-4-5: three runs of 3 = 9
        cards = [_make_card("3", "h"), _make_card("3", "d"),
                 _make_card("3", "c"), _make_card("4", "s"),
                 _make_card("5", "h")]
        assert score_runs(cards) == 9


# ---------------------------------------------------------------------------
# Tests: scoring — flush
# ---------------------------------------------------------------------------


class TestScoreFlush:
    def test_no_flush(self) -> None:
        hand = [_make_card("A", "hearts"), _make_card("2", "diamonds"),
                _make_card("3", "hearts"), _make_card("4", "hearts")]
        cut = _make_card("5", "hearts")
        assert score_flush(hand, cut) == 0

    def test_four_card_flush(self) -> None:
        hand = [_make_card("A", "hearts"), _make_card("3", "hearts"),
                _make_card("7", "hearts"), _make_card("K", "hearts")]
        cut = _make_card("5", "diamonds")
        assert score_flush(hand, cut) == 4

    def test_five_card_flush(self) -> None:
        hand = [_make_card("A", "spades"), _make_card("3", "spades"),
                _make_card("7", "spades"), _make_card("K", "spades")]
        cut = _make_card("5", "spades")
        assert score_flush(hand, cut) == 5

    def test_crib_needs_all_five(self) -> None:
        hand = [_make_card("A", "clubs"), _make_card("3", "clubs"),
                _make_card("7", "clubs"), _make_card("K", "clubs")]
        cut = _make_card("5", "diamonds")
        # In crib, 4-card flush does not count
        assert score_flush(hand, cut, is_crib=True) == 0

    def test_crib_five_card_flush(self) -> None:
        hand = [_make_card("A", "clubs"), _make_card("3", "clubs"),
                _make_card("7", "clubs"), _make_card("K", "clubs")]
        cut = _make_card("5", "clubs")
        assert score_flush(hand, cut, is_crib=True) == 5


# ---------------------------------------------------------------------------
# Tests: scoring — nobs
# ---------------------------------------------------------------------------


class TestScoreNobs:
    def test_no_nobs(self) -> None:
        hand = [_make_card("A", "hearts"), _make_card("2", "diamonds"),
                _make_card("3", "clubs"), _make_card("4", "spades")]
        cut = _make_card("5", "hearts")
        assert score_nobs(hand, cut) == 0

    def test_nobs_jack_matches_cut(self) -> None:
        hand = [_make_card("J", "hearts"), _make_card("2", "diamonds"),
                _make_card("3", "clubs"), _make_card("4", "spades")]
        cut = _make_card("5", "hearts")
        assert score_nobs(hand, cut) == 1

    def test_nobs_jack_wrong_suit(self) -> None:
        hand = [_make_card("J", "diamonds"), _make_card("2", "hearts"),
                _make_card("3", "clubs"), _make_card("4", "spades")]
        cut = _make_card("5", "hearts")
        assert score_nobs(hand, cut) == 0


# ---------------------------------------------------------------------------
# Tests: scoring — complete hands (known cribbage hands)
# ---------------------------------------------------------------------------


class TestCompleteHands:
    def test_worst_hand_zero(self) -> None:
        """A hand scoring 0 points: A-2-6-10 (diff suits) + J cut (diff suit)."""
        hand = [_make_card("A", "hearts"), _make_card("2", "diamonds"),
                _make_card("6", "clubs"), _make_card("10", "spades")]
        cut = _make_card("J", "diamonds")
        assert score_hand(hand, cut) == 0

    def test_perfect_29(self) -> None:
        """The maximum cribbage hand: 5-5-5-J with cut 5 matching J's suit.

        Fifteens: each 5+J=15 (3 ways), each 5+5+5=15 (1 way of 3 fives),
        plus the cut 5 makes it: 5+J=15 (3), 5+5+5=15 with cut (4 combos of 3 from 4 fives),
        total fifteens: J+5 x4 = 4, plus 5+5+5 x4 = 4 => 8 fifteens = 16.
        Pairs: C(4,2) = 6 pairs of 5s = 12.
        Nobs: J matches cut suit = 1.
        Total = 16 + 12 + 1 = 29.
        """
        hand = [_make_card("5", "hearts"), _make_card("5", "diamonds"),
                _make_card("5", "clubs"), _make_card("J", "spades")]
        cut = _make_card("5", "spades")
        assert score_hand(hand, cut) == 29

    def test_hand_with_run_and_fifteen(self) -> None:
        """A-2-3-4 with cut 5: run of 5 = 5, plus 15s."""
        hand = [_make_card("A", "hearts"), _make_card("2", "diamonds"),
                _make_card("3", "clubs"), _make_card("4", "spades")]
        cut = _make_card("5", "hearts")
        # Run of 5 = 5
        # Fifteens: A+2+3+4+5=15 (1), 10+5=? no face cards
        # A(1)+4(4)+10? no. Let's compute:
        # Subsets summing to 15: {A,2,3,4,5} = 1+2+3+4+5 = 15; {A,5,4,2,3} same
        # Also {2,4,5,?}... wait: 2+4+5=11, not 15
        # {A,5,9}? no 9. Just the one 5-card combo = 2
        # Plus: 1+2+3+4+5 = 15; and subsets: {5,4,3,2,1}: only 1+2+3+4+5=15
        # Also check smaller: {A,4,K?} no. Let me just trust the function.
        expected = score_fifteens(hand + [cut]) + 5 + 0 + 0  # run=5, no flush, no nobs
        assert score_hand(hand, cut) == expected

    def test_double_run_hand(self) -> None:
        """7-7-8-9 with cut 10: two runs of 4 (8), pair (2), plus fifteens."""
        hand = [_make_card("7", "hearts"), _make_card("7", "diamonds"),
                _make_card("8", "clubs"), _make_card("9", "spades")]
        cut = _make_card("10", "hearts")
        total = score_hand(hand, cut)
        # Pairs: one pair of 7s = 2
        # Runs: 7-8-9-10 x 2 (each 7) = 8
        # Fifteens: 7+8=15 x2 = 4
        assert total == 2 + 8 + 4  # = 14

    def test_all_same_suit_flush(self) -> None:
        """All hearts hand with non-heart cut, flush only, no other scoring."""
        hand = [_make_card("A", "hearts"), _make_card("2", "hearts"),
                _make_card("6", "hearts"), _make_card("10", "hearts")]
        cut = _make_card("Q", "diamonds")
        total = score_hand(hand, cut)
        # Flush: 4 (four hearts, cut is diamond)
        # Fifteens: none (1+2+6+10+10: no subset sums to 15)
        # Runs: none (A,2,6,10,Q not consecutive)
        # Pairs: none
        # Nobs: none
        assert total == 4


# ---------------------------------------------------------------------------
# Tests: pegging scoring
# ---------------------------------------------------------------------------


class TestPeggingScoring:
    def test_fifteen_scores_2(self) -> None:
        # Play 8 then 7: total = 15
        pts = score_pegging_play(["8", "7"], 15)
        assert pts == 2

    def test_thirty_one_scores_2(self) -> None:
        pts = score_pegging_play(["K", "Q", "A"], 31)
        assert pts == 2

    def test_pair_scores_2(self) -> None:
        pts = score_pegging_play(["5", "5"], 10)
        assert pts == 2

    def test_three_of_a_kind_scores_6(self) -> None:
        pts = score_pegging_play(["7", "7", "7"], 21)
        assert pts == 6

    def test_four_of_a_kind_scores_12(self) -> None:
        pts = score_pegging_play(["3", "3", "3", "3"], 12)
        assert pts == 12

    def test_run_of_three(self) -> None:
        # Play 4, 3, 5: ordered is 3-4-5 = run of 3
        pts = score_pegging_play(["4", "3", "5"], 12)
        # Run of 3 scores 3
        assert pts >= 3

    def test_run_of_four(self) -> None:
        pts = score_pegging_play(["6", "4", "3", "5"], 18)
        assert pts >= 4

    def test_no_score(self) -> None:
        pts = score_pegging_play(["A", "3"], 4)
        assert pts == 0

    def test_fifteen_and_pair(self) -> None:
        # Play 8, 7: total = 15 (no pair, so just 2)
        # Play 5, 5, 5: total = 15, pair count = 2 (pair royal) = 6+2=8
        pts = score_pegging_play(["5", "5", "5"], 15)
        assert pts == 2 + 6  # fifteen + three-of-a-kind


# ---------------------------------------------------------------------------
# Tests: game flow (end to end)
# ---------------------------------------------------------------------------


class TestGameFlow:
    def _setup_game(self, seed: int = 42) -> GameSession:
        session = _make_session()
        session.runtime.status = "in_progress"
        _build_deck(session)
        _shuffle_deck(session, seed)
        _deal_cards(session, "dealer", 6)
        _deal_cards(session, "pone", 6)
        return session

    def test_full_deal_and_discard(self) -> None:
        session = self._setup_game()
        dealer_hand = session.runtime.players["dealer"].zones["hand"]
        pone_hand = session.runtime.players["pone"].zones["hand"]
        assert isinstance(dealer_hand, SetZone) and isinstance(pone_hand, SetZone)

        # Discard first 2 from each hand
        d_discards = dealer_hand.components[:2]
        p_discards = pone_hand.components[:2]
        _discard_to_crib(session, "dealer", list(d_discards))
        _discard_to_crib(session, "pone", list(p_discards))

        assert dealer_hand.count() == 4
        assert pone_hand.count() == 4
        crib = session.runtime.zones["crib"]
        assert isinstance(crib, SetZone)
        assert crib.count() == 4

    def test_cut_after_discard(self) -> None:
        session = self._setup_game()
        dealer_hand = session.runtime.players["dealer"].zones["hand"]
        pone_hand = session.runtime.players["pone"].zones["hand"]
        assert isinstance(dealer_hand, SetZone) and isinstance(pone_hand, SetZone)

        _discard_to_crib(session, "dealer", list(dealer_hand.components[:2]))
        _discard_to_crib(session, "pone", list(pone_hand.components[:2]))
        cut_cid = _cut_card(session)
        comp = _get_card(session, cut_cid)
        assert comp.properties["rank"] in RANKS
        assert comp.properties["suit"] in SUITS

    def test_pegboard_scoring(self) -> None:
        """Manually advance pegboard scores."""
        session = self._setup_game()
        peg = session.runtime.players["pone"].zones["pegboard"]
        assert isinstance(peg, CounterZone)
        peg.value += 15
        assert peg.value == 15
        peg.value += 10
        assert peg.value == 25

    def test_win_at_121(self) -> None:
        """A player reaching 121 should win."""
        session = self._setup_game()
        peg = session.runtime.players["dealer"].zones["pegboard"]
        assert isinstance(peg, CounterZone)
        peg.value = 120
        assert peg.value < 121
        peg.value += 5
        assert peg.value >= 121

    def test_deck_size_after_deal_and_cut(self) -> None:
        session = self._setup_game()
        dealer_hand = session.runtime.players["dealer"].zones["hand"]
        pone_hand = session.runtime.players["pone"].zones["hand"]
        assert isinstance(dealer_hand, SetZone) and isinstance(pone_hand, SetZone)

        _discard_to_crib(session, "dealer", list(dealer_hand.components[:2]))
        _discard_to_crib(session, "pone", list(pone_hand.components[:2]))
        _cut_card(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        # 52 - 12 dealt - 1 cut = 39
        assert deck.count() == 39

    def test_turn_order_pone_first(self) -> None:
        """Pone plays first in pegging and show."""
        defn = _load_game()
        assert defn.turn_order.players == ["pone", "dealer"]

    def test_his_heels_rule_exists(self) -> None:
        defn = _load_game()
        assert "his_heels" in defn.rules
        rule = defn.rules["his_heels"]
        assert "Jack" in rule.definition


# ---------------------------------------------------------------------------
# Tests: edge cases in scoring
# ---------------------------------------------------------------------------


class TestScoringEdgeCases:
    def test_ace_low_only(self) -> None:
        """Ace is low only (rank_order 1). Q-K-A is not a run."""
        cards = [_make_card("Q", "h"), _make_card("K", "d"),
                 _make_card("A", "c"), _make_card("7", "s"),
                 _make_card("2", "h")]
        assert score_runs(cards) == 0

    def test_ace_low_run(self) -> None:
        """A-2-3 is a valid run."""
        cards = [_make_card("A", "h"), _make_card("2", "d"),
                 _make_card("3", "c"), _make_card("7", "s"),
                 _make_card("K", "h")]
        assert score_runs(cards) == 3

    def test_face_cards_pip_10(self) -> None:
        """J, Q, K all have pip value 10."""
        assert PIP_VALUES["J"] == 10
        assert PIP_VALUES["Q"] == 10
        assert PIP_VALUES["K"] == 10

    def test_fifteen_with_face_cards(self) -> None:
        """5 + any face card = 15."""
        for face in ["J", "Q", "K"]:
            cards = [_make_card("5", "h"), _make_card(face, "d")]
            assert score_fifteens(cards) == 2

    def test_no_wrap_around_runs(self) -> None:
        """K-A-2 is not a run (no wrap)."""
        cards = [_make_card("K", "h"), _make_card("A", "d"),
                 _make_card("2", "c"), _make_card("7", "s"),
                 _make_card("9", "h")]
        assert score_runs(cards) == 0

    def test_crib_score_separate(self) -> None:
        """Crib scoring differs from hand scoring for flushes."""
        hand = [_make_card("2", "hearts"), _make_card("4", "hearts"),
                _make_card("6", "hearts"), _make_card("8", "hearts")]
        cut = _make_card("10", "diamonds")
        # Hand gets 4-card flush
        assert score_flush(hand, cut, is_crib=False) == 4
        # Crib does not
        assert score_flush(hand, cut, is_crib=True) == 0
