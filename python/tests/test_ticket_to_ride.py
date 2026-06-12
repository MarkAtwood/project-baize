"""Tests for Ticket to Ride — route claiming on a city network graph.

Simplified Ticket to Ride: 2 players, ~10 cities, ~15 routes.
Exercises: graph zones with node_properties, deck management, set zones
for player hands, route claiming by discarding matching cards, scoring
by route length, and double-claim prevention.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GraphZone,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "ticket-to-ride.json"

CARD_COLORS = [
    "red", "orange", "yellow", "green",
    "blue", "pink", "white", "black",
]

# Scoring table: route length -> points
POINTS_TABLE: dict[int, int] = {1: 1, 2: 2, 3: 4, 4: 7}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _session() -> GameSession:
    return GameSession(_load_game())


def _build_deck(session: GameSession) -> list[ComponentId]:
    """Create an 80-card train deck: 10 of each of 8 colors.

    Returns list of created ComponentIds.
    """
    deck = session.runtime.zones.get("deck")
    assert isinstance(deck, StackZone)
    cids: list[ComponentId] = []
    for color in CARD_COLORS:
        for i in range(10):
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"train-{color}-{i}",
                component_type="train_card",
                owner=None,
                properties={"color": color},
            )
            cid = session.runtime.components.insert(comp)
            deck.stack_push(cid)
            cids.append(cid)
    return cids


def _shuffle_deck(session: GameSession, seed: int = 42) -> None:
    """Shuffle deck with deterministic seed."""
    deck = session.runtime.zones.get("deck")
    assert isinstance(deck, StackZone)
    rng = random.Random(seed)
    rng.shuffle(deck.components)


def _deal_cards(session: GameSession, player: str, count: int) -> list[ComponentId]:
    """Deal cards from the top of the deck into a player's hand."""
    deck = session.runtime.zones.get("deck")
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


def _draw_cards(session: GameSession, player: str, count: int = 2) -> list[ComponentId]:
    """Player action: draw cards from deck (their turn action)."""
    return _deal_cards(session, player, count)


def _get_route_properties(
    session: GameSession, route_name: str
) -> dict[str, str | int | bool]:
    """Get the properties of a route node."""
    routes = session.runtime.zones.get("routes")
    assert isinstance(routes, GraphZone)
    idx = routes.name_to_index.get(route_name)
    assert idx is not None, f"unknown route: {route_name}"
    return routes.node_properties.get(idx, {})


def _find_cards_by_color(
    session: GameSession, player: str, color: str
) -> list[ComponentId]:
    """Find all cards in a player's hand matching a specific color."""
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    matching: list[ComponentId] = []
    for cid in hand.components:
        comp = session.runtime.components.get(cid)
        assert comp is not None
        if comp.properties.get("color") == color:
            matching.append(cid)
    return matching


def _claim_route(
    session: GameSession, player: str, route_name: str
) -> bool:
    """Attempt to claim a route. Returns True on success, False on failure.

    Validates: route is unclaimed, player has enough matching cards.
    Discards matching cards, places marker, awards points.
    """
    routes = session.runtime.zones.get("routes")
    assert isinstance(routes, GraphZone)

    # Check route exists
    idx = routes.name_to_index.get(route_name)
    if idx is None:
        return False

    # Check route is unclaimed
    if routes.graph_get(route_name) is not None:
        return False

    # Get route properties
    props = routes.node_properties.get(idx, {})
    route_color = str(props.get("color", "any"))
    route_length = int(props.get("length", 1))
    route_points = int(props.get("points", 0))

    # Find matching cards
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    discard = session.runtime.zones.get("discard")
    assert isinstance(discard, SetZone)

    cards_to_spend: list[ComponentId] = []

    if route_color == "any":
        # For "any" color routes, find the most common color in hand
        color_counts: dict[str, list[ComponentId]] = {}
        for cid in hand.components:
            comp = session.runtime.components.get(cid)
            assert comp is not None
            c = str(comp.properties.get("color", ""))
            if c not in color_counts:
                color_counts[c] = []
            color_counts[c].append(cid)
        # Pick the color with the most cards
        best_color = ""
        best_count = 0
        for c, cids in color_counts.items():
            if len(cids) > best_count:
                best_count = len(cids)
                best_color = c
        if best_count >= route_length:
            cards_to_spend = color_counts[best_color][:route_length]
    else:
        # Must match route color exactly
        matching = _find_cards_by_color(session, player, route_color)
        if len(matching) >= route_length:
            cards_to_spend = matching[:route_length]

    if len(cards_to_spend) < route_length:
        return False

    # Discard the spent cards
    for cid in cards_to_spend:
        hand.set_remove(cid)
        discard.set_add(cid)

    # Place marker on route
    marker = ComponentData(
        id=ComponentId(0),
        string_id=f"marker-{player}-{route_name}",
        component_type="route_marker",
        owner=player,
        properties={},
    )
    marker_cid = session.runtime.components.insert(marker)
    routes.graph_set(route_name, marker_cid)

    # Award points
    score = session.runtime.players[player].zones["score"]
    assert isinstance(score, CounterZone)
    score.value += route_points

    return True


def _give_cards(
    session: GameSession, player: str, color: str, count: int
) -> list[ComponentId]:
    """Directly place cards of a given color into a player's hand (test helper)."""
    hand = session.runtime.players[player].zones["hand"]
    assert isinstance(hand, SetZone)
    cids: list[ComponentId] = []
    for i in range(count):
        comp = ComponentData(
            id=ComponentId(0),
            string_id=f"given-{color}-{player}-{i}",
            component_type="train_card",
            owner=player,
            properties={"color": color},
        )
        cid = session.runtime.components.insert(comp)
        hand.set_add(cid)
        cids.append(cid)
    return cids


# ---------------------------------------------------------------------------
# Tests: definition parsing
# ---------------------------------------------------------------------------


class TestDefinition:
    """Verify the game definition loads and has correct structure."""

    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Ticket to Ride"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["red", "blue"]

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
        assert defn.zones["hand"].visibility.private == "owner"

    def test_routes_zone_is_public_graph(self) -> None:
        defn = _load_game()
        assert "routes" in defn.zones
        assert defn.zones["routes"].zone_type == "graph"
        assert defn.zones["routes"].visibility == "public"

    def test_routes_have_15_nodes(self) -> None:
        defn = _load_game()
        assert defn.zones["routes"].nodes is not None
        assert len(defn.zones["routes"].nodes) == 15

    def test_every_route_has_properties(self) -> None:
        defn = _load_game()
        nodes = defn.zones["routes"].nodes
        props = defn.zones["routes"].node_properties
        assert nodes is not None
        assert props is not None
        for node in nodes:
            assert node in props, f"route {node} missing properties"
            p = props[node]
            assert "city_a" in p, f"route {node} missing city_a"
            assert "city_b" in p, f"route {node} missing city_b"
            assert "color" in p, f"route {node} missing color"
            assert "length" in p, f"route {node} missing length"
            assert "points" in p, f"route {node} missing points"

    def test_score_zone_is_per_player_counter(self) -> None:
        defn = _load_game()
        assert "score" in defn.zones
        assert defn.zones["score"].zone_type == "counter"
        assert defn.zones["score"].per_player is True

    def test_authority_sections_present(self) -> None:
        defn = _load_game()
        assert len(defn.authority.server_only) > 0
        assert len(defn.authority.client_verifiable) > 0


# ---------------------------------------------------------------------------
# Tests: session construction
# ---------------------------------------------------------------------------


class TestSessionConstruction:
    """Verify GameSession builds correct runtime state."""

    def test_session_creates(self) -> None:
        session = _session()
        assert session.runtime.status == "setup"

    def test_shared_zones(self) -> None:
        session = _session()
        assert "deck" in session.runtime.zones
        assert "discard" in session.runtime.zones
        assert "routes" in session.runtime.zones

    def test_per_player_zones(self) -> None:
        session = _session()
        for player in ["red", "blue"]:
            assert "hand" in session.runtime.players[player].zones
            assert "score" in session.runtime.players[player].zones

    def test_routes_graph_zone_type(self) -> None:
        session = _session()
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        assert len(routes.node_names) == 15

    def test_all_routes_initially_unclaimed(self) -> None:
        session = _session()
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        for node in routes.node_names:
            assert routes.graph_get(node) is None


# ---------------------------------------------------------------------------
# Tests: deck and card drawing
# ---------------------------------------------------------------------------


class TestDeckManagement:
    """Deck building, shuffling, and drawing."""

    def test_build_deck_creates_80_cards(self) -> None:
        session = _session()
        cids = _build_deck(session)
        assert len(cids) == 80

    def test_deck_has_10_per_color(self) -> None:
        session = _session()
        _build_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        color_counts: dict[str, int] = {}
        for cid in deck.components:
            comp = session.runtime.components.get(cid)
            assert comp is not None
            c = str(comp.properties.get("color", ""))
            color_counts[c] = color_counts.get(c, 0) + 1
        for color in CARD_COLORS:
            assert color_counts.get(color, 0) == 10, f"{color} count wrong"

    def test_shuffle_changes_order(self) -> None:
        session = _session()
        _build_deck(session)
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        before = list(deck.components)
        _shuffle_deck(session)
        after = list(deck.components)
        assert before != after

    def test_draw_cards_moves_to_hand(self) -> None:
        session = _session()
        _build_deck(session)
        _shuffle_deck(session)
        dealt = _draw_cards(session, "red", 2)
        assert len(dealt) == 2
        hand = session.runtime.players["red"].zones["hand"]
        assert isinstance(hand, SetZone)
        assert hand.count() == 2
        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 78

    def test_draw_sets_owner(self) -> None:
        session = _session()
        _build_deck(session)
        _shuffle_deck(session)
        dealt = _draw_cards(session, "blue", 2)
        for cid in dealt:
            comp = session.runtime.components.get(cid)
            assert comp is not None
            assert comp.owner == "blue"


# ---------------------------------------------------------------------------
# Tests: route claiming
# ---------------------------------------------------------------------------


class TestRouteClaiming:
    """Claiming routes by spending matching cards."""

    def test_claim_route_with_matching_cards(self) -> None:
        """Green route of length 1 requires 1 green card."""
        session = _session()
        _give_cards(session, "red", "green", 1)
        result = _claim_route(session, "red", "seattle-portland")
        assert result is True
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        assert routes.graph_get("seattle-portland") is not None

    def test_claim_route_discards_cards(self) -> None:
        """Claiming a route removes cards from hand and puts them in discard."""
        session = _session()
        _give_cards(session, "red", "green", 3)
        hand = session.runtime.players["red"].zones["hand"]
        assert isinstance(hand, SetZone)
        assert hand.count() == 3

        _claim_route(session, "red", "seattle-portland")  # length 1

        assert hand.count() == 2
        discard = session.runtime.zones["discard"]
        assert isinstance(discard, SetZone)
        assert discard.count() == 1

    def test_claim_route_insufficient_cards_fails(self) -> None:
        """Cannot claim a route without enough matching cards."""
        session = _session()
        _give_cards(session, "red", "green", 1)
        # denver-el-paso is green, length 4
        result = _claim_route(session, "red", "denver-el-paso")
        assert result is False
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        assert routes.graph_get("denver-el-paso") is None

    def test_claim_route_wrong_color_fails(self) -> None:
        """Cannot claim a colored route with the wrong color cards."""
        session = _session()
        _give_cards(session, "red", "blue", 3)
        # portland-san-francisco is pink, length 3
        result = _claim_route(session, "red", "portland-san-francisco")
        assert result is False

    def test_claim_any_color_route(self) -> None:
        """Routes with color 'any' can be claimed with any single color."""
        session = _session()
        _give_cards(session, "blue", "orange", 4)
        # seattle-calgary is 'any' color, length 4
        result = _claim_route(session, "blue", "seattle-calgary")
        assert result is True

    def test_double_claim_prevented(self) -> None:
        """A claimed route cannot be claimed again."""
        session = _session()
        _give_cards(session, "red", "green", 2)
        _give_cards(session, "blue", "green", 2)

        result1 = _claim_route(session, "red", "seattle-portland")
        assert result1 is True

        result2 = _claim_route(session, "blue", "seattle-portland")
        assert result2 is False

    def test_double_claim_preserves_original_owner(self) -> None:
        """After a failed double-claim, original owner's marker remains."""
        session = _session()
        _give_cards(session, "red", "green", 1)
        _give_cards(session, "blue", "green", 1)

        _claim_route(session, "red", "seattle-portland")
        _claim_route(session, "blue", "seattle-portland")

        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        marker_cid = routes.graph_get("seattle-portland")
        assert marker_cid is not None
        marker = session.runtime.components.get(marker_cid)
        assert marker is not None
        assert marker.owner == "red"

    def test_claim_nonexistent_route_fails(self) -> None:
        """Claiming a route that doesn't exist returns False."""
        session = _session()
        result = _claim_route(session, "red", "narnia-mordor")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    """Points awarded correctly per route length."""

    def test_length_1_scores_1_point(self) -> None:
        session = _session()
        _give_cards(session, "red", "green", 1)
        _claim_route(session, "red", "seattle-portland")  # length 1
        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 1

    def test_length_2_scores_2_points(self) -> None:
        session = _session()
        _give_cards(session, "red", "red", 2)
        _claim_route(session, "red", "salt-lake-city-denver")  # red, length 2
        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 2

    def test_length_3_scores_4_points(self) -> None:
        session = _session()
        _give_cards(session, "red", "pink", 3)
        _claim_route(session, "red", "portland-san-francisco")  # pink, length 3
        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 4

    def test_length_4_scores_7_points(self) -> None:
        session = _session()
        _give_cards(session, "red", "green", 4)
        _claim_route(session, "red", "denver-el-paso")  # green, length 4
        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 7

    def test_cumulative_scoring(self) -> None:
        """Multiple route claims accumulate points."""
        session = _session()
        _give_cards(session, "red", "green", 5)  # 1 for seattle-portland + 4 for denver-el-paso
        _give_cards(session, "red", "red", 2)    # 2 for salt-lake-city-denver

        _claim_route(session, "red", "seattle-portland")      # 1 pt
        _claim_route(session, "red", "salt-lake-city-denver")  # 2 pt
        _claim_route(session, "red", "denver-el-paso")         # 7 pt

        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 10  # 1 + 2 + 7

    def test_failed_claim_no_points(self) -> None:
        """Failed route claim awards no points."""
        session = _session()
        _give_cards(session, "red", "blue", 1)
        _claim_route(session, "red", "seattle-portland")  # needs green, not blue
        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 0

    def test_both_players_score_independently(self) -> None:
        """Each player has their own score counter."""
        session = _session()
        _give_cards(session, "red", "green", 1)
        _give_cards(session, "blue", "red", 2)

        _claim_route(session, "red", "seattle-portland")       # 1 pt
        _claim_route(session, "blue", "salt-lake-city-denver")  # 2 pt

        red_score = session.runtime.players["red"].zones["score"]
        blue_score = session.runtime.players["blue"].zones["score"]
        assert isinstance(red_score, CounterZone)
        assert isinstance(blue_score, CounterZone)
        assert red_score.value == 1
        assert blue_score.value == 2


# ---------------------------------------------------------------------------
# Tests: full game flow
# ---------------------------------------------------------------------------


class TestFullGameFlow:
    """End-to-end game simulation."""

    def test_setup_deal_and_claim(self) -> None:
        """Full flow: build deck, shuffle, deal, claim a route."""
        session = _session()
        _build_deck(session)
        _shuffle_deck(session, seed=7)

        # Deal 4 cards to each player
        _deal_cards(session, "red", 4)
        _deal_cards(session, "blue", 4)

        deck = session.runtime.zones["deck"]
        assert isinstance(deck, StackZone)
        assert deck.count() == 72  # 80 - 8

        # Give red extra green cards to guarantee a claim
        _give_cards(session, "red", "green", 2)

        result = _claim_route(session, "red", "seattle-portland")
        assert result is True

        score = session.runtime.players["red"].zones["score"]
        assert isinstance(score, CounterZone)
        assert score.value == 1

    def test_alternating_turns_draw_and_claim(self) -> None:
        """Simulate several turns of alternating draw/claim actions."""
        session = _session()
        _build_deck(session)
        _shuffle_deck(session, seed=99)

        # Initial deal
        _deal_cards(session, "red", 4)
        _deal_cards(session, "blue", 4)

        # Turn 1: red draws 2 cards
        _draw_cards(session, "red", 2)
        session.advance_turn()

        # Turn 2: blue draws 2 cards
        _draw_cards(session, "blue", 2)
        session.advance_turn()

        # Turn 3: give red enough to claim, then claim
        _give_cards(session, "red", "yellow", 2)
        result = _claim_route(session, "red", "san-francisco-los-angeles")
        assert result is True
        session.advance_turn()

        # Verify state
        assert session.current_player() == "blue"
        red_hand = session.runtime.players["red"].zones["hand"]
        assert isinstance(red_hand, SetZone)
        # red started with 4 dealt + 2 drawn + 2 given = 8, claimed route cost 2 = 6
        assert red_hand.count() == 6

    def test_route_properties_accessible(self) -> None:
        """Route node_properties are correctly accessible at runtime."""
        session = _session()
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)

        props = _get_route_properties(session, "denver-omaha")
        assert props["city_a"] == "denver"
        assert props["city_b"] == "omaha"
        assert props["color"] == "pink"
        assert props["length"] == 4
        assert props["points"] == 7

    def test_all_routes_have_valid_scoring(self) -> None:
        """Every route's points match the POINTS_TABLE for its length."""
        session = _session()
        routes = session.runtime.zones["routes"]
        assert isinstance(routes, GraphZone)
        for name in routes.node_names:
            props = _get_route_properties(session, name)
            length = int(props["length"])
            expected_points = POINTS_TABLE[length]
            actual_points = int(props["points"])
            assert actual_points == expected_points, (
                f"route {name}: length {length} should score "
                f"{expected_points}, got {actual_points}"
            )
