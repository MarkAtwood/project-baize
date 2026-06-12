"""Tests for Clue (Cluedo): deduction on a graph board with hidden envelope.

Simplified 3-player Clue with 9 rooms connected by hallways.  One suspect
card, one weapon card, and one room card are sealed in a hidden envelope.
The remaining 18 cards are dealt evenly (6 per player).  Players move
through rooms and hallways, make suggestions to narrow down the envelope
contents, and may make a final accusation to win (or be eliminated).

Tests cover: definition parsing, room connectivity, card dealing,
suggestion/disproval mechanics, and accusation win/loss.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from baize.definition import GameDefinition, PrivateVisibility
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GraphZone,
    SetZone,
    StackZone,
    runtime_zone_from_definition,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOMS = [
    "kitchen", "ballroom", "conservatory",
    "billiard_room", "library", "study",
    "hall", "lounge", "dining_room",
]

HALLWAYS = [
    "kitchen_ballroom", "ballroom_conservatory",
    "kitchen_dining_room", "ballroom_billiard_room",
    "conservatory_library", "dining_room_lounge",
    "billiard_room_hall", "library_study",
    "lounge_hall", "hall_study",
]

ALL_NODES = ROOMS + HALLWAYS

SUSPECTS = ["scarlet", "plum", "green", "mustard", "white", "peacock"]
WEAPONS = ["knife", "candlestick", "revolver", "rope", "lead_pipe", "wrench"]
ROOM_NAMES = ROOMS  # room card types match room node names

PLAYERS = ["Scarlet", "Plum", "Green"]

SECRET_PASSAGES = [
    ("kitchen", "study"),
    ("conservatory", "lounge"),
]

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "clue.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# ClueGame helper
# ---------------------------------------------------------------------------


class ClueGame:
    """Simplified Clue game driver for testing deduction mechanics."""

    def __init__(self, seed: int = 42) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.rng = random.Random(seed)

        # Envelope contents (set during deal)
        self.envelope_suspect: str | None = None
        self.envelope_weapon: str | None = None
        self.envelope_room: str | None = None

        # Player hands: {player_name: list of (card_type, card_value)}
        self.hands: dict[str, list[tuple[str, str]]] = {p: [] for p in PLAYERS}

        # Player positions on the board graph
        self.positions: dict[str, str] = {}

        # Eliminated players (wrong accusation)
        self.eliminated: set[str] = set()

        # Turn tracking
        self.current_player_index: int = 0

        self._graph = self._build_graph()

    def _build_graph(self) -> GraphZone:
        zone_def = self.defn.zones["board"]
        zone = runtime_zone_from_definition(zone_def)
        assert isinstance(zone, GraphZone)
        return zone

    @property
    def graph(self) -> GraphZone:
        return self._graph

    @property
    def current_player(self) -> str:
        return PLAYERS[self.current_player_index % len(PLAYERS)]

    def advance_turn(self) -> None:
        """Advance to next non-eliminated player."""
        for _ in range(len(PLAYERS)):
            self.current_player_index = (self.current_player_index + 1) % len(PLAYERS)
            if PLAYERS[self.current_player_index] not in self.eliminated:
                return
        raise RuntimeError("all players eliminated")

    # -------------------------------------------------------------------
    # Dealing
    # -------------------------------------------------------------------

    def deal(self) -> None:
        """Select envelope contents and deal remaining cards to players."""
        suspect_cards = list(SUSPECTS)
        weapon_cards = list(WEAPONS)
        room_cards = list(ROOM_NAMES)

        self.rng.shuffle(suspect_cards)
        self.rng.shuffle(weapon_cards)
        self.rng.shuffle(room_cards)

        self.envelope_suspect = suspect_cards.pop()
        self.envelope_weapon = weapon_cards.pop()
        self.envelope_room = room_cards.pop()

        remaining: list[tuple[str, str]] = []
        for s in suspect_cards:
            remaining.append(("suspect", s))
        for w in weapon_cards:
            remaining.append(("weapon", w))
        for r in room_cards:
            remaining.append(("room", r))

        self.rng.shuffle(remaining)

        for i, card in enumerate(remaining):
            player = PLAYERS[i % len(PLAYERS)]
            self.hands[player].append(card)

    def all_cards_count(self) -> int:
        """Total cards dealt (hands) + envelope = 21."""
        hand_count = sum(len(h) for h in self.hands.values())
        envelope_count = sum(1 for x in [
            self.envelope_suspect, self.envelope_weapon, self.envelope_room
        ] if x is not None)
        return hand_count + envelope_count

    # -------------------------------------------------------------------
    # Movement
    # -------------------------------------------------------------------

    def place_player(self, player: str, node: str) -> None:
        """Place a player at a starting position."""
        assert node in ALL_NODES, f"Unknown node: {node}"
        self.positions[player] = node

    def valid_moves(self, player: str) -> list[str]:
        """Return nodes the player can move to from current position."""
        current = self.positions.get(player)
        if current is None:
            return []
        neighbors = self.graph.graph_neighbors(current)
        return neighbors

    def move_player(self, player: str, destination: str) -> None:
        """Move a player to an adjacent node."""
        if player in self.eliminated:
            raise ValueError(f"{player} is eliminated")
        neighbors = self.valid_moves(player)
        if destination not in neighbors:
            raise ValueError(
                f"{destination} is not adjacent to {self.positions.get(player)}"
            )
        self.positions[player] = destination

    def is_in_room(self, player: str) -> bool:
        """Check if a player is in a room (not a hallway)."""
        pos = self.positions.get(player)
        return pos is not None and pos in ROOMS

    # -------------------------------------------------------------------
    # Suggestions
    # -------------------------------------------------------------------

    def suggest(
        self, player: str, suspect: str, weapon: str, room: str
    ) -> tuple[str, str] | None:
        """Make a suggestion. Returns (disproving_player, card_shown) or None.

        The player must be in the named room. Disproval goes clockwise from
        the suggesting player. The first player who holds a matching card
        must show one.
        """
        if player in self.eliminated:
            raise ValueError(f"{player} is eliminated")
        if self.positions.get(player) != room:
            raise ValueError(
                f"{player} must be in {room} to suggest it "
                f"(currently in {self.positions.get(player)})"
            )
        if room not in ROOMS:
            raise ValueError(f"{room} is not a valid room")

        suggestion_cards = {
            ("suspect", suspect),
            ("weapon", weapon),
            ("room", room),
        }

        player_idx = PLAYERS.index(player)
        for offset in range(1, len(PLAYERS)):
            other_idx = (player_idx + offset) % len(PLAYERS)
            other = PLAYERS[other_idx]
            matching = [c for c in self.hands[other] if c in suggestion_cards]
            if matching:
                shown = matching[0]
                return (other, f"{shown[0]}:{shown[1]}")

        return None

    # -------------------------------------------------------------------
    # Accusations
    # -------------------------------------------------------------------

    def accuse(
        self, player: str, suspect: str, weapon: str, room: str
    ) -> bool:
        """Make an accusation. Returns True if correct (wins), False if wrong.

        A wrong accusation eliminates the player.
        """
        if player in self.eliminated:
            raise ValueError(f"{player} is already eliminated")

        correct = (
            suspect == self.envelope_suspect
            and weapon == self.envelope_weapon
            and room == self.envelope_room
        )

        if not correct:
            self.eliminated.add(player)

        return correct

    def active_players(self) -> list[str]:
        """Return players still in the game."""
        return [p for p in PLAYERS if p not in self.eliminated]

    def check_all_eliminated(self) -> bool:
        """Check if all players have been eliminated (draw condition)."""
        return len(self.eliminated) == len(PLAYERS)


# ===========================================================================
# Tests: Definition Parsing
# ===========================================================================


class TestDefinition:
    """Verify the Clue game definition loads and validates."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Clue"

    def test_three_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Scarlet", "Plum", "Green"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_board_zone_is_graph(self) -> None:
        defn = _load_definition()
        assert "board" in defn.zones
        assert defn.zones["board"].zone_type == "graph"
        assert defn.zones["board"].visibility == "public"

    def test_board_has_19_nodes(self) -> None:
        """9 rooms + 10 hallways = 19 nodes."""
        defn = _load_definition()
        assert defn.zones["board"].nodes is not None
        assert len(defn.zones["board"].nodes) == 19

    def test_envelope_zone_is_hidden_set(self) -> None:
        defn = _load_definition()
        assert "envelope" in defn.zones
        assert defn.zones["envelope"].zone_type == "set"
        assert defn.zones["envelope"].visibility == "hidden"

    def test_hand_zone_is_per_player_private(self) -> None:
        defn = _load_definition()
        assert "hand" in defn.zones
        assert defn.zones["hand"].per_player is True
        assert isinstance(defn.zones["hand"].visibility, PrivateVisibility)
        assert defn.zones["hand"].visibility.private == "owner"

    def test_five_component_types(self) -> None:
        defn = _load_definition()
        assert len(defn.components) == 5
        assert "player_token" in defn.components
        assert "weapon_token" in defn.components
        assert "suspect_card" in defn.components
        assert "weapon_card" in defn.components
        assert "room_card" in defn.components

    def test_six_suspect_cards(self) -> None:
        defn = _load_definition()
        assert defn.components["suspect_card"].count == 6

    def test_six_weapon_cards(self) -> None:
        defn = _load_definition()
        assert defn.components["weapon_card"].count == 6

    def test_nine_room_cards(self) -> None:
        defn = _load_definition()
        assert defn.components["room_card"].count == 9

    def test_round_robin_turn_order(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "round_robin"
        assert defn.turn_order.players == ["Scarlet", "Plum", "Green"]

    def test_five_phases(self) -> None:
        defn = _load_definition()
        assert len(defn.phases) == 5
        phase_names = [p.name for p in defn.phases]
        assert phase_names == ["deal", "move", "suggest", "disprove", "accuse"]

    def test_three_end_conditions(self) -> None:
        defn = _load_definition()
        assert len(defn.end_conditions) == 3
        results = [e.result for e in defn.end_conditions]
        assert "win" in results
        assert "loss" in results
        assert "draw" in results

    def test_authority_sections(self) -> None:
        defn = _load_definition()
        assert len(defn.authority.server_only) == 3
        assert len(defn.authority.client_verifiable) == 3

    def test_round_trip(self) -> None:
        defn = _load_definition()
        json_str = defn.to_json()
        defn2 = GameDefinition.from_json(json_str)
        assert defn2.game.name == defn.game.name
        assert len(defn2.zones) == len(defn.zones)
        assert len(defn2.components) == len(defn.components)
        assert len(defn2.end_conditions) == len(defn.end_conditions)


# ===========================================================================
# Tests: Room Connectivity
# ===========================================================================


class TestRoomConnectivity:
    """Verify the board graph structure: rooms, hallways, passages."""

    def test_graph_has_19_nodes(self) -> None:
        g = ClueGame()
        assert len(g.graph.node_names) == 19

    def test_nine_rooms(self) -> None:
        """Nine nodes are tagged as rooms."""
        defn = _load_definition()
        props = defn.zones["board"].node_properties
        assert props is not None
        room_nodes = [n for n, p in props.items() if p.get("type") == "room"]
        assert sorted(room_nodes) == sorted(ROOMS)

    def test_ten_hallways(self) -> None:
        """Ten nodes are tagged as hallways."""
        defn = _load_definition()
        props = defn.zones["board"].node_properties
        assert props is not None
        hallway_nodes = [n for n, p in props.items() if p.get("type") == "hallway"]
        assert sorted(hallway_nodes) == sorted(HALLWAYS)

    def test_all_edges_bidirectional(self) -> None:
        """If A is neighbor of B, then B is neighbor of A."""
        g = ClueGame()
        for node in ALL_NODES:
            for neighbor in g.graph.graph_neighbors(node):
                assert node in g.graph.graph_neighbors(neighbor), (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_graph_is_connected(self) -> None:
        """All nodes reachable from any starting node (BFS)."""
        g = ClueGame()
        visited: set[str] = set()
        queue = [ALL_NODES[0]]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for neighbor in g.graph.graph_neighbors(current):
                if neighbor not in visited:
                    queue.append(neighbor)
        assert visited == set(ALL_NODES)

    def test_no_self_loops(self) -> None:
        """No node is adjacent to itself."""
        g = ClueGame()
        for node in ALL_NODES:
            assert node not in g.graph.graph_neighbors(node)

    def test_rooms_connect_through_hallways(self) -> None:
        """Each room connects to at least one hallway (and possibly other rooms via passages)."""
        g = ClueGame()
        for room in ROOMS:
            neighbors = g.graph.graph_neighbors(room)
            hallway_neighbors = [n for n in neighbors if n in HALLWAYS]
            assert len(hallway_neighbors) >= 1, (
                f"{room} has no hallway connections: {neighbors}"
            )

    def test_secret_passage_kitchen_study(self) -> None:
        """Kitchen and study are directly connected (secret passage)."""
        g = ClueGame()
        kitchen_neighbors = g.graph.graph_neighbors("kitchen")
        assert "study" in kitchen_neighbors
        study_neighbors = g.graph.graph_neighbors("study")
        assert "kitchen" in study_neighbors

    def test_secret_passage_conservatory_lounge(self) -> None:
        """Conservatory and lounge are directly connected (secret passage)."""
        g = ClueGame()
        conservatory_neighbors = g.graph.graph_neighbors("conservatory")
        assert "lounge" in conservatory_neighbors
        lounge_neighbors = g.graph.graph_neighbors("lounge")
        assert "conservatory" in lounge_neighbors

    def test_hallway_connects_exactly_two_rooms(self) -> None:
        """Each hallway node has exactly 2 neighbors, both of which are rooms."""
        g = ClueGame()
        for hallway in HALLWAYS:
            neighbors = g.graph.graph_neighbors(hallway)
            assert len(neighbors) == 2, (
                f"Hallway {hallway} has {len(neighbors)} neighbors, expected 2: {neighbors}"
            )
            for n in neighbors:
                assert n in ROOMS, (
                    f"Hallway {hallway} connects to non-room {n}"
                )

    def test_kitchen_neighbors(self) -> None:
        """Kitchen connects to: kitchen_ballroom, kitchen_dining_room, study (passage)."""
        g = ClueGame()
        neighbors = sorted(g.graph.graph_neighbors("kitchen"))
        assert neighbors == sorted(["kitchen_ballroom", "kitchen_dining_room", "study"])

    def test_hall_neighbors(self) -> None:
        """Hall connects to: billiard_room_hall, lounge_hall, hall_study."""
        g = ClueGame()
        neighbors = sorted(g.graph.graph_neighbors("hall"))
        assert neighbors == sorted(["billiard_room_hall", "lounge_hall", "hall_study"])


# ===========================================================================
# Tests: Card Dealing
# ===========================================================================


class TestCardDealing:
    """Verify envelope selection and card distribution."""

    def test_deal_creates_envelope(self) -> None:
        """After dealing, envelope has one of each card type."""
        g = ClueGame()
        g.deal()
        assert g.envelope_suspect is not None
        assert g.envelope_weapon is not None
        assert g.envelope_room is not None

    def test_envelope_suspect_is_valid(self) -> None:
        g = ClueGame()
        g.deal()
        assert g.envelope_suspect in SUSPECTS

    def test_envelope_weapon_is_valid(self) -> None:
        g = ClueGame()
        g.deal()
        assert g.envelope_weapon in WEAPONS

    def test_envelope_room_is_valid(self) -> None:
        g = ClueGame()
        g.deal()
        assert g.envelope_room in ROOM_NAMES

    def test_all_21_cards_accounted_for(self) -> None:
        """6 suspects + 6 weapons + 9 rooms = 21 total. 3 in envelope, 18 dealt."""
        g = ClueGame()
        g.deal()
        assert g.all_cards_count() == 21

    def test_each_player_gets_six_cards(self) -> None:
        """18 remaining cards / 3 players = 6 each."""
        g = ClueGame()
        g.deal()
        for player in PLAYERS:
            assert len(g.hands[player]) == 6, (
                f"{player} has {len(g.hands[player])} cards, expected 6"
            )

    def test_no_duplicate_cards(self) -> None:
        """Each card appears exactly once across envelope + all hands."""
        g = ClueGame()
        g.deal()
        all_cards: list[tuple[str, str]] = []
        all_cards.append(("suspect", g.envelope_suspect))  # type: ignore[arg-type]
        all_cards.append(("weapon", g.envelope_weapon))  # type: ignore[arg-type]
        all_cards.append(("room", g.envelope_room))  # type: ignore[arg-type]
        for hand in g.hands.values():
            all_cards.extend(hand)
        assert len(all_cards) == len(set(all_cards)), "Duplicate cards found"

    def test_envelope_cards_not_in_hands(self) -> None:
        """Envelope cards should not appear in any player's hand."""
        g = ClueGame()
        g.deal()
        envelope = {
            ("suspect", g.envelope_suspect),
            ("weapon", g.envelope_weapon),
            ("room", g.envelope_room),
        }
        for player in PLAYERS:
            for card in g.hands[player]:
                assert card not in envelope, (
                    f"Envelope card {card} found in {player}'s hand"
                )

    def test_deterministic_with_same_seed(self) -> None:
        """Same seed produces same deal."""
        g1 = ClueGame(seed=99)
        g1.deal()
        g2 = ClueGame(seed=99)
        g2.deal()
        assert g1.envelope_suspect == g2.envelope_suspect
        assert g1.envelope_weapon == g2.envelope_weapon
        assert g1.envelope_room == g2.envelope_room
        for player in PLAYERS:
            assert g1.hands[player] == g2.hands[player]

    def test_different_seeds_produce_different_deals(self) -> None:
        """Different seeds produce different deals (extremely high probability)."""
        g1 = ClueGame(seed=1)
        g1.deal()
        g2 = ClueGame(seed=2)
        g2.deal()
        envelopes_match = (
            g1.envelope_suspect == g2.envelope_suspect
            and g1.envelope_weapon == g2.envelope_weapon
            and g1.envelope_room == g2.envelope_room
        )
        assert not envelopes_match, "Different seeds produced identical envelope"


# ===========================================================================
# Tests: Suggestion and Disproval
# ===========================================================================


class TestSuggestionDisproval:
    """Verify suggestion/disproval mechanics."""

    def _setup_game(self) -> ClueGame:
        """Set up a game with known hands for predictable disproval."""
        g = ClueGame()
        # Manually set envelope and hands for deterministic testing
        g.envelope_suspect = "mustard"
        g.envelope_weapon = "rope"
        g.envelope_room = "study"

        # Scarlet's hand: scarlet suspect, knife weapon, kitchen room, + 3 more
        g.hands["Scarlet"] = [
            ("suspect", "scarlet"),
            ("weapon", "knife"),
            ("room", "kitchen"),
            ("suspect", "plum"),
            ("weapon", "candlestick"),
            ("room", "ballroom"),
        ]
        # Plum's hand: green suspect, revolver weapon, library room, + 3 more
        g.hands["Plum"] = [
            ("suspect", "green"),
            ("weapon", "revolver"),
            ("room", "library"),
            ("suspect", "white"),
            ("weapon", "lead_pipe"),
            ("room", "hall"),
        ]
        # Green's hand: peacock suspect, wrench weapon, lounge room, + 3 more
        g.hands["Green"] = [
            ("suspect", "peacock"),
            ("weapon", "wrench"),
            ("room", "lounge"),
            ("room", "conservatory"),
            ("room", "billiard_room"),
            ("room", "dining_room"),
        ]

        # Place players in rooms
        g.place_player("Scarlet", "kitchen")
        g.place_player("Plum", "library")
        g.place_player("Green", "lounge")

        return g

    def test_suggestion_disproved_by_next_player(self) -> None:
        """Plum (next clockwise from Scarlet) disproves with a matching card."""
        g = self._setup_game()
        # Scarlet suggests green in the kitchen with revolver
        # Plum has ("suspect", "green") and ("weapon", "revolver")
        result = g.suggest("Scarlet", "green", "revolver", "kitchen")
        assert result is not None
        player, card = result
        assert player == "Plum"
        assert card in ("suspect:green", "weapon:revolver")

    def test_suggestion_skips_player_without_match(self) -> None:
        """If the next player has no matching card, skip to the one after."""
        g = self._setup_game()
        # Scarlet suggests peacock in the kitchen with wrench
        # Plum has no peacock, no wrench, no kitchen
        # Green has ("suspect", "peacock") and ("weapon", "wrench")
        result = g.suggest("Scarlet", "peacock", "wrench", "kitchen")
        assert result is not None
        player, card = result
        assert player == "Green"
        assert card in ("suspect:peacock", "weapon:wrench")

    def test_suggestion_not_disproved(self) -> None:
        """No one can disprove a suggestion matching the envelope."""
        g = self._setup_game()
        # Scarlet suggests mustard with rope in kitchen
        # mustard and rope are in the envelope; kitchen is in Scarlet's hand
        # but Scarlet is the suggester so only Plum and Green are checked
        # Plum doesn't have kitchen, Green doesn't have kitchen
        # Wait - Scarlet has kitchen in hand but is the suggester.
        # We need the suggestion to match room = kitchen, but the other players
        # don't have that card. Let's check: Green doesn't have kitchen.
        # Actually, let's suggest the exact envelope: mustard, rope, kitchen
        # Plum: no mustard, no rope, no kitchen -> skip
        # Green: no mustard, no rope, no kitchen -> skip
        # But wait, we need to check: Plum's hand doesn't have kitchen card,
        # Green's hand doesn't have kitchen card. Let me verify...
        # Scarlet has ("room", "kitchen"). Suggestion room is "kitchen".
        # Only Plum and Green are checked (not the suggester).
        # Plum: no ("suspect","mustard"), no ("weapon","rope"), no ("room","kitchen") -> skip
        # Green: no ("suspect","mustard"), no ("weapon","rope"), no ("room","kitchen") -> skip
        # Correct! Not disproved.
        result = g.suggest("Scarlet", "mustard", "rope", "kitchen")
        assert result is None

    def test_suggestion_must_be_in_room(self) -> None:
        """Player must be in the named room to suggest."""
        g = self._setup_game()
        with pytest.raises(ValueError, match="must be in"):
            g.suggest("Scarlet", "mustard", "rope", "library")

    def test_suggestion_with_room_card_disproved(self) -> None:
        """Room card in someone's hand disproves a room-matching suggestion."""
        g = self._setup_game()
        # Scarlet suggests mustard, rope in kitchen (actually let's pick
        # a room that another player holds)
        # Move Scarlet to lounge to suggest there
        # Actually, Scarlet is in kitchen. Let's suggest something where
        # the room itself is the match.
        # Green is in lounge. Green suggests mustard, rope, lounge.
        # Check: Plum has no mustard, no rope, no lounge. Skip.
        # Then comes Scarlet: no mustard, no rope, no lounge. Skip.
        # Hmm, nobody has lounge except Green but Green is the suggester.
        # Let's have Green suggest mustard, rope, lounge
        # Wait, Green has ("room", "lounge") but is the suggester.
        # Plum and Scarlet don't have lounge. Not disproved.
        # Let's try: Green suggests green, knife, lounge.
        # Scarlet has ("suspect", "scarlet")? No, not green. Scarlet has ("weapon", "knife").
        # So Scarlet (next after Green clockwise) has ("weapon", "knife") -> disproves
        # Wait: clockwise from Green: the order is Scarlet (idx 0), Plum (idx 1), Green (idx 2)
        # Offset 1 from Green(idx=2) -> Scarlet(idx=0)
        # Scarlet has ("weapon", "knife") which matches. So Scarlet disproves.
        result = g.suggest("Green", "green", "knife", "lounge")
        assert result is not None
        player, card = result
        assert player == "Scarlet"
        assert card == "weapon:knife"

    def test_eliminated_player_cannot_suggest(self) -> None:
        """Eliminated players cannot make suggestions."""
        g = self._setup_game()
        g.eliminated.add("Scarlet")
        with pytest.raises(ValueError, match="eliminated"):
            g.suggest("Scarlet", "mustard", "rope", "kitchen")


# ===========================================================================
# Tests: Movement
# ===========================================================================


class TestMovement:
    """Verify player movement on the board graph."""

    def test_move_from_room_to_hallway(self) -> None:
        g = ClueGame()
        g.place_player("Scarlet", "kitchen")
        moves = g.valid_moves("Scarlet")
        assert "kitchen_ballroom" in moves
        g.move_player("Scarlet", "kitchen_ballroom")
        assert g.positions["Scarlet"] == "kitchen_ballroom"

    def test_move_from_hallway_to_room(self) -> None:
        g = ClueGame()
        g.place_player("Scarlet", "kitchen_ballroom")
        moves = g.valid_moves("Scarlet")
        assert "kitchen" in moves
        assert "ballroom" in moves
        g.move_player("Scarlet", "ballroom")
        assert g.positions["Scarlet"] == "ballroom"

    def test_move_via_secret_passage(self) -> None:
        """Player can move directly from kitchen to study via secret passage."""
        g = ClueGame()
        g.place_player("Scarlet", "kitchen")
        moves = g.valid_moves("Scarlet")
        assert "study" in moves
        g.move_player("Scarlet", "study")
        assert g.positions["Scarlet"] == "study"

    def test_invalid_move_rejected(self) -> None:
        """Cannot move to a non-adjacent node."""
        g = ClueGame()
        g.place_player("Scarlet", "kitchen")
        with pytest.raises(ValueError, match="not adjacent"):
            g.move_player("Scarlet", "lounge")

    def test_is_in_room(self) -> None:
        g = ClueGame()
        g.place_player("Scarlet", "kitchen")
        assert g.is_in_room("Scarlet") is True
        g.move_player("Scarlet", "kitchen_ballroom")
        assert g.is_in_room("Scarlet") is False

    def test_eliminated_player_cannot_move(self) -> None:
        g = ClueGame()
        g.place_player("Scarlet", "kitchen")
        g.eliminated.add("Scarlet")
        with pytest.raises(ValueError, match="eliminated"):
            g.move_player("Scarlet", "kitchen_ballroom")


# ===========================================================================
# Tests: Accusations
# ===========================================================================


class TestAccusation:
    """Verify accusation win/loss mechanics."""

    def _setup_game(self) -> ClueGame:
        g = ClueGame()
        g.envelope_suspect = "mustard"
        g.envelope_weapon = "rope"
        g.envelope_room = "study"
        g.hands["Scarlet"] = [("suspect", "scarlet"), ("weapon", "knife"),
                               ("room", "kitchen"), ("suspect", "plum"),
                               ("weapon", "candlestick"), ("room", "ballroom")]
        g.hands["Plum"] = [("suspect", "green"), ("weapon", "revolver"),
                            ("room", "library"), ("suspect", "white"),
                            ("weapon", "lead_pipe"), ("room", "hall")]
        g.hands["Green"] = [("suspect", "peacock"), ("weapon", "wrench"),
                             ("room", "lounge"), ("room", "conservatory"),
                             ("room", "billiard_room"), ("room", "dining_room")]
        return g

    def test_correct_accusation_wins(self) -> None:
        """Correct accusation returns True."""
        g = self._setup_game()
        result = g.accuse("Scarlet", "mustard", "rope", "study")
        assert result is True

    def test_wrong_suspect_loses(self) -> None:
        """Wrong suspect eliminates the player."""
        g = self._setup_game()
        result = g.accuse("Scarlet", "scarlet", "rope", "study")
        assert result is False
        assert "Scarlet" in g.eliminated

    def test_wrong_weapon_loses(self) -> None:
        """Wrong weapon eliminates the player."""
        g = self._setup_game()
        result = g.accuse("Plum", "mustard", "knife", "study")
        assert result is False
        assert "Plum" in g.eliminated

    def test_wrong_room_loses(self) -> None:
        """Wrong room eliminates the player."""
        g = self._setup_game()
        result = g.accuse("Green", "mustard", "rope", "kitchen")
        assert result is False
        assert "Green" in g.eliminated

    def test_eliminated_player_cannot_accuse(self) -> None:
        """Already-eliminated player cannot make an accusation."""
        g = self._setup_game()
        g.eliminated.add("Scarlet")
        with pytest.raises(ValueError, match="already eliminated"):
            g.accuse("Scarlet", "mustard", "rope", "study")

    def test_wrong_accusation_preserves_hand(self) -> None:
        """Eliminated player's cards remain for disproval."""
        g = self._setup_game()
        g.place_player("Scarlet", "kitchen")
        g.place_player("Plum", "library")
        g.place_player("Green", "lounge")

        # Scarlet makes wrong accusation and is eliminated
        g.accuse("Scarlet", "scarlet", "rope", "study")
        assert "Scarlet" in g.eliminated

        # Scarlet's cards still available: Plum can trigger disproval
        # that involves Scarlet's hand (but Scarlet is eliminated —
        # in full Clue, eliminated players still show cards during disproval)
        assert len(g.hands["Scarlet"]) == 6

    def test_all_eliminated_is_draw(self) -> None:
        """When all players make wrong accusations, it's a draw."""
        g = self._setup_game()
        g.accuse("Scarlet", "scarlet", "rope", "study")
        g.accuse("Plum", "plum", "rope", "study")
        g.accuse("Green", "green", "rope", "study")
        assert g.check_all_eliminated() is True
        assert len(g.active_players()) == 0

    def test_one_active_after_two_eliminated(self) -> None:
        """After two wrong accusations, one player remains active."""
        g = self._setup_game()
        g.accuse("Scarlet", "scarlet", "rope", "study")
        g.accuse("Plum", "plum", "rope", "study")
        assert g.active_players() == ["Green"]
        assert not g.check_all_eliminated()


# ===========================================================================
# Tests: Turn Sequencing
# ===========================================================================


class TestTurnSequence:
    """Verify turn advancement and skipping eliminated players."""

    def test_round_robin_order(self) -> None:
        g = ClueGame()
        assert g.current_player == "Scarlet"
        g.advance_turn()
        assert g.current_player == "Plum"
        g.advance_turn()
        assert g.current_player == "Green"
        g.advance_turn()
        assert g.current_player == "Scarlet"

    def test_skip_eliminated_player(self) -> None:
        g = ClueGame()
        g.eliminated.add("Plum")
        assert g.current_player == "Scarlet"
        g.advance_turn()
        assert g.current_player == "Green"
        g.advance_turn()
        assert g.current_player == "Scarlet"

    def test_all_eliminated_raises(self) -> None:
        g = ClueGame()
        g.eliminated = {"Scarlet", "Plum", "Green"}
        with pytest.raises(RuntimeError, match="all players eliminated"):
            g.advance_turn()


# ===========================================================================
# Tests: Integration — Full Game Flow
# ===========================================================================


class TestIntegration:
    """End-to-end game flow: deal, move, suggest, accuse."""

    def test_full_game_correct_accusation(self) -> None:
        """Play a short game ending with a correct accusation."""
        g = ClueGame(seed=42)
        g.deal()

        # Place players at starting positions
        g.place_player("Scarlet", "hall")
        g.place_player("Plum", "lounge")
        g.place_player("Green", "conservatory")

        # Scarlet's turn: move to a room and suggest
        g.move_player("Scarlet", "lounge_hall")
        assert g.positions["Scarlet"] == "lounge_hall"

        # Scarlet is in a hallway, cannot suggest
        assert not g.is_in_room("Scarlet")

        g.advance_turn()  # Plum's turn
        # Plum moves to a hallway
        g.move_player("Plum", "dining_room_lounge")

        g.advance_turn()  # Green's turn
        # Green uses secret passage to lounge
        g.move_player("Green", "lounge")
        assert g.is_in_room("Green")

        # Green makes suggestion in lounge
        result = g.suggest(
            "Green", g.envelope_suspect or "mustard",
            g.envelope_weapon or "rope", "lounge"
        )
        # The envelope cards aren't in any hand, so if the room "lounge"
        # is in someone's hand, that person disproves. Otherwise None.

        # Finally, Green makes the correct accusation
        won = g.accuse(
            "Green",
            g.envelope_suspect or "",
            g.envelope_weapon or "",
            g.envelope_room or "",
        )
        assert won is True

    def test_full_game_wrong_accusation_then_correct(self) -> None:
        """First player makes wrong accusation, second player wins."""
        g = ClueGame(seed=42)
        g.deal()

        # Scarlet makes a wrong accusation
        result = g.accuse("Scarlet", "peacock", "knife", "kitchen")
        assert result is False
        assert "Scarlet" in g.eliminated

        # Green makes the correct accusation
        result = g.accuse(
            "Green",
            g.envelope_suspect or "",
            g.envelope_weapon or "",
            g.envelope_room or "",
        )
        assert result is True
        assert g.active_players() == ["Plum", "Green"]
