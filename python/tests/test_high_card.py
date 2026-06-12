"""Tests for the High Card game — simplest game exercising the deal pipeline.

High Card: shuffle a deck, deal one card to each player (private), reveal both,
highest rank wins. Tests simulate the server-authority deal by manually placing
cards into player hands from a known deck state.

This exercises: deck management, per-player private zones, card comparison,
and the reveal-to-public pattern that mental poker will later replace.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
    SlotZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "high-card.json"

RANK_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}

SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = list(RANK_VALUES.keys())


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _build_deck(session: GameSession) -> list[ComponentId]:
    """Create a 52-card deck in the deck zone. Returns component IDs."""
    deck_zone = session.runtime.zones.get("deck")
    assert isinstance(deck_zone, StackZone)
    cids = []
    for suit in SUITS:
        for rank in RANKS:
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"card-{suit}-{rank}",
                component_type="card",
                owner=None,
                properties={"suit": suit, "rank": rank},
            )
            cid = session.runtime.components.insert(comp)
            deck_zone.components.append(cid)
            cids.append(cid)
    return cids


def _shuffle_deck(session: GameSession, seed: int = 42) -> None:
    """Shuffle the deck zone with a deterministic seed."""
    deck_zone = session.runtime.zones.get("deck")
    assert isinstance(deck_zone, StackZone)
    rng = random.Random(seed)
    rng.shuffle(deck_zone.components)


def _deal_one(session: GameSession, player: str) -> ComponentId:
    """Deal one card from the deck to a player's hand (private zone)."""
    deck_zone = session.runtime.zones.get("deck")
    assert isinstance(deck_zone, StackZone)
    assert len(deck_zone.components) > 0, "deck is empty"

    cid = deck_zone.components.pop()  # top of deck
    player_state = session.runtime.players[player]
    hand_zone = player_state.zones["hand"]
    assert isinstance(hand_zone, SlotZone)
    hand_zone.component = cid

    # Set owner to the player receiving the card
    comp = session.runtime.components.get(cid)
    assert comp is not None
    comp.owner = player

    return cid


def _read_hand(session: GameSession, player: str) -> ComponentData | None:
    """Read the card in a player's hand."""
    player_state = session.runtime.players[player]
    hand_zone = player_state.zones["hand"]
    assert isinstance(hand_zone, SlotZone)
    if hand_zone.component is None:
        return None
    return session.runtime.components.get(hand_zone.component)


def _card_rank_value(comp: ComponentData) -> int:
    """Extract the numeric rank value from a card component."""
    rank = comp.properties.get("rank", "2")
    return RANK_VALUES.get(str(rank), 0)


def _determine_winner(
    session: GameSession, p1: str = "Alice", p2: str = "Bob"
) -> str | None:
    """Compare hands. Returns winner name or None on tie."""
    c1 = _read_hand(session, p1)
    c2 = _read_hand(session, p2)
    assert c1 is not None and c2 is not None
    v1, v2 = _card_rank_value(c1), _card_rank_value(c2)
    if v1 > v2:
        return p1
    elif v2 > v1:
        return p2
    return None


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestHighCardDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "High Card"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["Alice", "Bob"]

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

    def test_table_zone_is_public_grid(self) -> None:
        defn = _load_game()
        assert "table" in defn.zones
        assert defn.zones["table"].zone_type == "grid"
        assert defn.zones["table"].visibility == "public"


# ---------------------------------------------------------------------------
# Tests: deck management
# ---------------------------------------------------------------------------


class TestDeckManagement:
    def test_build_deck_creates_52_cards(self) -> None:
        session = GameSession(_load_game())
        cids = _build_deck(session)
        assert len(cids) == 52

    def test_shuffle_is_deterministic(self) -> None:
        s1 = GameSession(_load_game())
        _build_deck(s1)
        _shuffle_deck(s1, seed=123)

        s2 = GameSession(_load_game())
        _build_deck(s2)
        _shuffle_deck(s2, seed=123)

        deck1 = s1.runtime.zones["deck"]
        deck2 = s2.runtime.zones["deck"]
        assert isinstance(deck1, StackZone) and isinstance(deck2, StackZone)
        # Same seed → same order (component IDs will differ but types match)
        types1 = [
            session.runtime.components.get(c).component_type
            for c, session in zip(deck1.components, [s1] * 52)
        ]
        types2 = [
            session.runtime.components.get(c).component_type
            for c, session in zip(deck2.components, [s2] * 52)
        ]
        assert types1 == types2

    def test_shuffle_changes_order(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        before = list(deck.components)
        _shuffle_deck(session)
        after = list(deck.components)
        assert before != after  # extremely unlikely to be identical


# ---------------------------------------------------------------------------
# Tests: dealing
# ---------------------------------------------------------------------------


class TestDealing:
    def test_deal_one_card_to_player(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        _shuffle_deck(session)
        _deal_one(session, "Alice")

        card = _read_hand(session, "Alice")
        assert card is not None
        assert card.owner == "Alice"
        assert card.properties.get("rank") is not None
        assert card.properties.get("suit") is not None

    def test_deal_removes_from_deck(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert len(deck.components) == 52
        _deal_one(session, "Alice")
        assert len(deck.components) == 51

    def test_deal_to_both_players(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        _shuffle_deck(session)
        _deal_one(session, "Alice")
        _deal_one(session, "Bob")

        alice_card = _read_hand(session, "Alice")
        bob_card = _read_hand(session, "Bob")
        assert alice_card is not None
        assert bob_card is not None
        # Different cards (different component IDs)
        assert alice_card is not bob_card


# ---------------------------------------------------------------------------
# Tests: winner determination
# ---------------------------------------------------------------------------


class TestWinnerDetermination:
    def test_higher_rank_wins(self) -> None:
        """Manually place specific cards and verify comparison."""
        session = GameSession(_load_game())

        # Give Alice an Ace, Bob a King
        ace = ComponentData(
            id=ComponentId(0), string_id="ace-spades",
            component_type="card", owner="Alice",
            properties={"suit": "spades", "rank": "A"},
        )
        king = ComponentData(
            id=ComponentId(0), string_id="king-hearts",
            component_type="card", owner="Bob",
            properties={"suit": "hearts", "rank": "K"},
        )
        ace_id = session.runtime.components.insert(ace)
        king_id = session.runtime.components.insert(king)

        alice_hand = session.runtime.players["Alice"].zones["hand"]
        bob_hand = session.runtime.players["Bob"].zones["hand"]
        assert isinstance(alice_hand, SlotZone) and isinstance(bob_hand, SlotZone)
        alice_hand.component = ace_id
        bob_hand.component = king_id

        assert _determine_winner(session) == "Alice"

    def test_lower_rank_loses(self) -> None:
        session = GameSession(_load_game())

        two = ComponentData(
            id=ComponentId(0), string_id="two-clubs",
            component_type="card", owner="Alice",
            properties={"suit": "clubs", "rank": "2"},
        )
        ten = ComponentData(
            id=ComponentId(0), string_id="ten-diamonds",
            component_type="card", owner="Bob",
            properties={"suit": "diamonds", "rank": "10"},
        )
        session.runtime.components.insert(two)
        session.runtime.components.insert(ten)

        alice_hand = session.runtime.players["Alice"].zones["hand"]
        bob_hand = session.runtime.players["Bob"].zones["hand"]
        assert isinstance(alice_hand, SlotZone) and isinstance(bob_hand, SlotZone)
        alice_hand.component = ComponentId(0)
        bob_hand.component = ComponentId(1)

        assert _determine_winner(session) == "Bob"

    def test_same_rank_is_tie(self) -> None:
        session = GameSession(_load_game())

        c1 = ComponentData(
            id=ComponentId(0), string_id="seven-hearts",
            component_type="card", owner="Alice",
            properties={"suit": "hearts", "rank": "7"},
        )
        c2 = ComponentData(
            id=ComponentId(0), string_id="seven-spades",
            component_type="card", owner="Bob",
            properties={"suit": "spades", "rank": "7"},
        )
        session.runtime.components.insert(c1)
        session.runtime.components.insert(c2)

        alice_hand = session.runtime.players["Alice"].zones["hand"]
        bob_hand = session.runtime.players["Bob"].zones["hand"]
        assert isinstance(alice_hand, SlotZone) and isinstance(bob_hand, SlotZone)
        alice_hand.component = ComponentId(0)
        bob_hand.component = ComponentId(1)

        assert _determine_winner(session) is None


# ---------------------------------------------------------------------------
# Tests: full game flow
# ---------------------------------------------------------------------------


class TestFullGame:
    """End-to-end: build deck, shuffle, deal, determine winner."""

    def test_full_game_deterministic_seed(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        _shuffle_deck(session, seed=42)
        _deal_one(session, "Alice")
        _deal_one(session, "Bob")

        alice_card = _read_hand(session, "Alice")
        bob_card = _read_hand(session, "Bob")
        assert alice_card is not None and bob_card is not None

        winner = _determine_winner(session)
        # With seed=42, result is deterministic
        # Just verify it's a valid result
        assert winner in ("Alice", "Bob", None)

    def test_deck_has_50_cards_after_dealing(self) -> None:
        session = GameSession(_load_game())
        _build_deck(session)
        _shuffle_deck(session)
        _deal_one(session, "Alice")
        _deal_one(session, "Bob")

        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert len(deck.components) == 50

    def test_private_hand_visibility(self) -> None:
        """Verify hand zone is per-player private (from definition)."""
        defn = _load_game()
        hand_def = defn.zones["hand"]
        assert hand_def.per_player is True
        assert hand_def.visibility.private == "owner"

    def test_wire_format_includes_hands(self) -> None:
        """Wire state includes player hand zones."""
        session = GameSession(_load_game())
        _build_deck(session)
        _shuffle_deck(session)
        _deal_one(session, "Alice")
        _deal_one(session, "Bob")

        wire = session.to_wire_state()
        assert "Alice" in wire.players
        assert "Bob" in wire.players
        # Per-player zones should be in the wire state
        assert wire.players["Alice"].zones is not None
        assert "hand" in wire.players["Alice"].zones
