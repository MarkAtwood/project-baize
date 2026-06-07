"""Visibility model test runner for Baize (baize-562.4).

Loads test vectors from tests/vectors/visibility.json, builds the game
state described therein, then applies visibility filtering for each viewer
and asserts the expected visible/hidden invariants.

Run: python -m pytest tests/test_visibility_python.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure the Python package is importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from baize.definition import GameDefinition, PrivateVisibility, Zone
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    SetZone,
    StackZone,
)
from baize.state import (
    ComponentInstance,
    CounterState,
    GameState,
    GridState,
    PlayerState,
    SetState,
    SlotState,
    StackState,
    TrackState,
    ZoneState,
)

# ---------------------------------------------------------------------------
# Load test vectors
# ---------------------------------------------------------------------------

VECTORS_PATH = PROJECT_ROOT / "tests" / "vectors" / "visibility.json"


def load_vectors() -> dict[str, Any]:
    with open(VECTORS_PATH) as f:
        return json.load(f)


def build_game_definition(vectors: dict[str, Any]) -> GameDefinition:
    raw = json.dumps(vectors["game_definition"])
    return GameDefinition.from_json(raw)


def build_session(vectors: dict[str, Any]) -> GameSession:
    definition = build_game_definition(vectors)
    session = GameSession(definition)
    session.runtime.status = "in_progress"

    setup = vectors["setup"]
    for comp in setup["components"]:
        id_str = comp["id"]
        comp_type = comp["component_type"]
        zone_name = comp["zone"]
        owner = comp.get("owner")
        properties = comp.get("properties", {})

        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=id_str,
                component_type=comp_type,
                owner=owner,
                properties=dict(properties),
            )
        )

        # Place into the correct zone.
        if owner and owner in session.runtime.players:
            player = session.runtime.players[owner]
            if zone_name in player.zones:
                zone = player.zones[zone_name]
                if isinstance(zone, SetZone):
                    zone.set_add(cid)
                elif isinstance(zone, StackZone):
                    zone.stack_push(cid)
                continue

        # Shared zone
        if zone_name in session.runtime.zones:
            zone = session.runtime.zones[zone_name]
            if isinstance(zone, SetZone):
                zone.set_add(cid)
            elif isinstance(zone, StackZone):
                zone.stack_push(cid)
            else:
                raise ValueError(f"unexpected zone type for {zone_name}: {type(zone)}")
        else:
            raise ValueError(f"zone {zone_name} not found")

    return session


# ---------------------------------------------------------------------------
# Visibility filtering (the logic under test)
# ---------------------------------------------------------------------------


def zone_component_ids(zone: ZoneState) -> list[str]:
    """Extract component IDs from a wire zone state."""
    if isinstance(zone, (StackState, SetState)):
        return [c.id for c in zone.components]
    if isinstance(zone, GridState):
        ids = []
        for v in zone.cells.values():
            if v is None:
                continue
            if isinstance(v, list):
                ids.extend(c.id for c in v)
            elif isinstance(v, ComponentInstance):
                ids.append(v.id)
        return ids
    if isinstance(zone, SlotState):
        return [zone.component.id] if zone.component else []
    if isinstance(zone, CounterState):
        return []
    if isinstance(zone, TrackState):
        ids = []
        for cs in zone.positions.values():
            ids.extend(c.id for c in cs)
        return ids
    return []


def zone_component_count(zone: ZoneState) -> int:
    """Count components in a wire zone state."""
    return len(zone_component_ids(zone))


def redacted_zone(zone: ZoneState, count: int) -> ZoneState:
    """Return a redacted copy of a zone: same type, empty contents, count preserved."""
    if isinstance(zone, StackState):
        return StackState(components=[], count=count)
    if isinstance(zone, SetState):
        return SetState(components=[], count=count)
    if isinstance(zone, GridState):
        return GridState(cells={})
    if isinstance(zone, SlotState):
        return SlotState(component=None)
    if isinstance(zone, CounterState):
        return CounterState(value=zone.value)
    if isinstance(zone, TrackState):
        return TrackState(positions={})
    return zone


def filter_for_viewer(
    full_state: GameState,
    viewer: str,
    definition: GameDefinition,
) -> GameState:
    """Apply visibility filtering to produce a player's view.

    - public zones: all components included
    - hidden zones: components stripped, only count retained
    - private zones (owner): owner sees contents, others see only count
    - server ("__server__"): sees everything
    """
    if viewer == "__server__":
        return full_state

    # Deep-copy by round-tripping through dict
    state_dict = json.loads(full_state.to_json())
    filtered = GameState._from_dict(state_dict)

    # Filter shared zones
    for zone_name in list(filtered.zones.keys()):
        zone_def = definition.zones.get(zone_name)
        if zone_def is None:
            continue
        vis = zone_def.visibility

        if vis == "public":
            pass  # keep as-is
        elif vis == "hidden":
            count = zone_component_count(filtered.zones[zone_name])
            filtered.zones[zone_name] = redacted_zone(filtered.zones[zone_name], count)
        elif isinstance(vis, PrivateVisibility):
            count = zone_component_count(filtered.zones[zone_name])
            filtered.zones[zone_name] = redacted_zone(filtered.zones[zone_name], count)

    # Filter per-player zones
    for player_name, player_state in filtered.players.items():
        if player_state.zones is None:
            continue
        for zone_name in list(player_state.zones.keys()):
            zone_def = definition.zones.get(zone_name)
            if zone_def is None:
                continue
            vis = zone_def.visibility

            if vis == "public":
                pass
            elif vis == "hidden":
                count = zone_component_count(player_state.zones[zone_name])
                player_state.zones[zone_name] = redacted_zone(
                    player_state.zones[zone_name], count
                )
            elif isinstance(vis, PrivateVisibility):
                is_owner = vis.private == "owner" and player_name == viewer
                if not is_owner:
                    count = zone_component_count(player_state.zones[zone_name])
                    player_state.zones[zone_name] = redacted_zone(
                        player_state.zones[zone_name], count
                    )

    return filtered


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPublicZone:
    """Public zones: all players see all components."""

    def test_alice_sees_community(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        community = view.zones.get("community")
        assert community is not None
        ids = set(zone_component_ids(community))
        assert ids == {"card-AH", "card-KH", "card-QS"}

    def test_bob_sees_community(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "bob", definition)
        community = view.zones.get("community")
        assert community is not None
        ids = set(zone_component_ids(community))
        assert ids == {"card-AH", "card-KH", "card-QS"}


class TestHiddenZone:
    """Hidden zones: no player sees components; only server does."""

    def test_alice_cannot_see_deck(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        deck = view.zones.get("deck")
        assert deck is not None
        ids = zone_component_ids(deck)
        assert ids == [], f"alice must NOT see deck contents, found: {ids}"

    def test_bob_cannot_see_deck(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "bob", definition)
        deck = view.zones.get("deck")
        assert deck is not None
        ids = zone_component_ids(deck)
        assert ids == [], f"bob must NOT see deck contents, found: {ids}"

    def test_discard_hidden(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        discard = view.zones.get("discard")
        assert discard is not None
        ids = zone_component_ids(discard)
        assert ids == [], f"alice must NOT see discard contents, found: {ids}"

    def test_hidden_zone_count_preserved(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)

        deck = view.zones.get("deck")
        assert isinstance(deck, StackState)
        assert deck.count == 3, f"deck count should be 3, got {deck.count}"

        discard = view.zones.get("discard")
        assert isinstance(discard, SetState)
        assert discard.count == 1, f"discard count should be 1, got {discard.count}"


class TestPrivateZone:
    """Private zones: only the owner sees contents."""

    def test_alice_sees_own_hand(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        alice_player = view.players.get("alice")
        assert alice_player is not None
        assert alice_player.zones is not None
        hand = alice_player.zones.get("hand")
        assert hand is not None
        ids = set(zone_component_ids(hand))
        assert ids == {"card-JD", "card-10S"}

    def test_bob_sees_own_hand(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "bob", definition)
        bob_player = view.players.get("bob")
        assert bob_player is not None
        assert bob_player.zones is not None
        hand = bob_player.zones.get("hand")
        assert hand is not None
        ids = set(zone_component_ids(hand))
        assert ids == {"card-5C", "card-9H", "card-KD"}

    def test_alice_cannot_see_bob_hand(self) -> None:
        """Critical security invariant: alice must NOT see bob's hand."""
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        bob_player = view.players.get("bob")
        assert bob_player is not None
        assert bob_player.zones is not None
        hand = bob_player.zones.get("hand")
        assert hand is not None
        ids = zone_component_ids(hand)
        assert ids == [], f"SECURITY: alice must NOT see bob's hand, found: {ids}"

    def test_bob_cannot_see_alice_hand(self) -> None:
        """Symmetric: bob must NOT see alice's hand."""
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "bob", definition)
        alice_player = view.players.get("alice")
        assert alice_player is not None
        assert alice_player.zones is not None
        hand = alice_player.zones.get("hand")
        assert hand is not None
        ids = zone_component_ids(hand)
        assert ids == [], f"SECURITY: bob must NOT see alice's hand, found: {ids}"

    def test_non_owner_sees_count(self) -> None:
        """Non-owner sees the count of a private zone but not contents."""
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        bob_player = view.players.get("bob")
        assert bob_player is not None
        assert bob_player.zones is not None
        hand = bob_player.zones.get("hand")
        assert isinstance(hand, SetState)
        assert hand.count == 3, f"alice should see bob has 3 cards, got {hand.count}"

        view = filter_for_viewer(full_state, "bob", definition)
        alice_player = view.players.get("alice")
        assert alice_player is not None
        assert alice_player.zones is not None
        hand = alice_player.zones.get("hand")
        assert isinstance(hand, SetState)
        assert hand.count == 2, f"bob should see alice has 2 cards, got {hand.count}"


class TestServerView:
    """Server view includes everything."""

    def test_server_sees_all_zones(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "__server__", definition)

        # Deck
        deck_ids = set(zone_component_ids(view.zones["deck"]))
        assert deck_ids == {"card-2D", "card-3D", "card-4C"}

        # Discard
        discard_ids = zone_component_ids(view.zones["discard"])
        assert discard_ids == ["card-7H"]

        # Community
        comm_ids = set(zone_component_ids(view.zones["community"]))
        assert comm_ids == {"card-AH", "card-KH", "card-QS"}

    def test_server_sees_all_hands(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "__server__", definition)

        alice_hand = view.players["alice"].zones["hand"]
        alice_ids = set(zone_component_ids(alice_hand))
        assert alice_ids == {"card-JD", "card-10S"}

        bob_hand = view.players["bob"].zones["hand"]
        bob_ids = set(zone_component_ids(bob_hand))
        assert bob_ids == {"card-5C", "card-9H", "card-KD"}


class TestPublicCounter:
    """Public per-player counters are visible to all."""

    def test_counters_visible(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        for viewer in ("alice", "bob"):
            view = filter_for_viewer(full_state, viewer, definition)
            for player_name in ("alice", "bob"):
                player = view.players[player_name]
                assert player.zones is not None
                score = player.zones.get("score")
                assert isinstance(
                    score, CounterState
                ), f"{player_name}'s score should be a Counter"


class TestNoLeaks:
    """Full serialization check: no hidden data appears anywhere in the player's JSON view."""

    def test_alice_view_json_no_leaks(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "alice", definition)
        json_str = view.to_json()

        # Hidden deck cards must not appear
        for card_id in ("card-2D", "card-3D", "card-4C", "card-7H"):
            assert card_id not in json_str, (
                f"SECURITY: {card_id} (hidden zone) leaked into alice's view"
            )

        # Bob's hand cards must not appear
        for card_id in ("card-5C", "card-9H", "card-KD"):
            assert card_id not in json_str, (
                f"SECURITY: {card_id} (bob's hand) leaked into alice's view"
            )

        # Alice's own cards and public cards SHOULD appear
        assert "card-JD" in json_str, "alice should see her own card-JD"
        assert "card-10S" in json_str, "alice should see her own card-10S"
        assert "card-AH" in json_str, "alice should see public card-AH"

    def test_bob_view_json_no_leaks(self) -> None:
        vectors = load_vectors()
        session = build_session(vectors)
        definition = build_game_definition(vectors)
        full_state = session.to_wire_state()

        view = filter_for_viewer(full_state, "bob", definition)
        json_str = view.to_json()

        # Hidden deck cards must not appear
        for card_id in ("card-2D", "card-3D", "card-4C", "card-7H"):
            assert card_id not in json_str, (
                f"SECURITY: {card_id} (hidden zone) leaked into bob's view"
            )

        # Alice's hand cards must not appear
        for card_id in ("card-JD", "card-10S"):
            assert card_id not in json_str, (
                f"SECURITY: {card_id} (alice's hand) leaked into bob's view"
            )

        # Bob's own cards and public cards SHOULD appear
        assert "card-5C" in json_str, "bob should see his own card-5C"
        assert "card-9H" in json_str, "bob should see his own card-9H"
        assert "card-KD" in json_str, "bob should see his own card-KD"
        assert "card-AH" in json_str, "bob should see public card-AH"
