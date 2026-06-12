"""Tests for simplified Settlers of Catan: resource production and building.

Simplified 2-player Catan on a 7-hex map (1 center + 6 surrounding).
Exercises: hex_grid zone with cell_properties for resource/number tokens,
graph zone for settlement vertices and road edges, per-player set zones
for resource card hands, counter zones for victory points.

Mechanics:
  - 2d6 dice roll triggers resource production from matching hexes
  - Settlements on hex vertices collect resources
  - Build roads (1 wood + 1 brick), settlements (1 wood + 1 brick + 1 sheep + 1 wheat)
  - Bank trade: 4 identical resources for 1 of any type
  - First to 5 victory points (1 per settlement) wins
"""

from __future__ import annotations

from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GraphZone,
    GridZone,
    SetZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "settlers-of-catan.json"

RESOURCES = ["wood", "brick", "sheep", "wheat", "ore"]

# Hex definitions: (col, row) -> (resource, number_token)
HEX_TILES: dict[tuple[int, int], tuple[str, int]] = {
    (2, 0): ("wheat", 5),
    (1, 1): ("wood", 6),
    (2, 1): ("brick", 8),
    (3, 1): ("sheep", 9),
    (1, 2): ("ore", 10),
    (2, 2): ("wheat", 4),
    (3, 2): ("wood", 3),
}

# Vertex -> list of (resource, number) for adjacent hexes
# Derived from the node_properties "adjacent_hexes" strings in the definition.
VERTEX_RESOURCES: dict[str, list[tuple[str, int]]] = {
    "v0":  [("wheat", 5)],
    "v1":  [("wheat", 5), ("wood", 6)],
    "v2":  [("wheat", 5), ("brick", 8)],
    "v3":  [("wheat", 5), ("sheep", 9)],
    "v4":  [("wheat", 5), ("sheep", 9)],
    "v5":  [("wheat", 5), ("wood", 6)],
    "v6":  [("wood", 6)],
    "v7":  [("wood", 6), ("brick", 8)],
    "v8":  [("brick", 8)],
    "v9":  [("brick", 8), ("sheep", 9)],
    "v10": [("sheep", 9)],
    "v11": [("sheep", 9), ("wood", 6)],
    "v12": [("wood", 6), ("ore", 10)],
    "v13": [("wood", 6), ("brick", 8), ("ore", 10), ("wheat", 4)],
    "v14": [("brick", 8), ("wheat", 4)],
    "v15": [("brick", 8), ("sheep", 9), ("wheat", 4), ("wood", 3)],
    "v16": [("sheep", 9), ("wood", 3)],
    "v17": [("sheep", 9), ("wood", 6), ("wood", 3), ("ore", 10)],
}


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# CatanGame helper
# ---------------------------------------------------------------------------


class CatanGame:
    """Simplified Catan game driver for testing resource management and building."""

    def __init__(self) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.players = ["red", "blue"]
        # Track which vertices have settlements: vertex -> owner
        self.settlements: dict[str, str] = {}
        # Track which edges have roads: frozenset({v_a, v_b}) -> owner
        self.roads: dict[frozenset[str], str] = {}
        self._next_id = 0

    @property
    def graph(self) -> GraphZone:
        zone = self.session.runtime.zones.get("settlement_map")
        assert isinstance(zone, GraphZone)
        return zone

    @property
    def hex_grid(self) -> GridZone:
        zone = self.session.runtime.zones.get("hex_map")
        assert isinstance(zone, GridZone)
        return zone

    def hand(self, player: str) -> SetZone:
        hand = self.session.runtime.players[player].zones["hand"]
        assert isinstance(hand, SetZone)
        return hand

    def vp(self, player: str) -> int:
        counter = self.session.runtime.players[player].zones["victory_points"]
        assert isinstance(counter, CounterZone)
        return counter.value

    def set_vp(self, player: str, value: int) -> None:
        counter = self.session.runtime.players[player].zones["victory_points"]
        assert isinstance(counter, CounterZone)
        counter.value = value

    # -------------------------------------------------------------------
    # Resource management
    # -------------------------------------------------------------------

    def give_resource(self, player: str, resource: str, count: int = 1) -> list[ComponentId]:
        """Add resource cards directly to a player's hand (test helper)."""
        hand = self.hand(player)
        cids: list[ComponentId] = []
        for i in range(count):
            self._next_id += 1
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"res-{resource}-{player}-{self._next_id}",
                component_type="resource_card",
                owner=player,
                properties={"resource": resource},
            )
            cid = self.session.runtime.components.insert(comp)
            hand.set_add(cid)
            cids.append(cid)
        return cids

    def count_resource(self, player: str, resource: str) -> int:
        """Count how many cards of a specific resource a player has."""
        hand = self.hand(player)
        total = 0
        for cid in hand.components:
            comp = self.session.runtime.components.get(cid)
            assert comp is not None
            if comp.properties.get("resource") == resource:
                total += 1
        return total

    def hand_size(self, player: str) -> int:
        return self.hand(player).count()

    def remove_resource(self, player: str, resource: str, count: int = 1) -> bool:
        """Remove resource cards from a player's hand. Returns False if insufficient."""
        hand = self.hand(player)
        to_remove: list[ComponentId] = []
        for cid in hand.components:
            comp = self.session.runtime.components.get(cid)
            assert comp is not None
            if comp.properties.get("resource") == resource and len(to_remove) < count:
                to_remove.append(cid)
        if len(to_remove) < count:
            return False
        for cid in to_remove:
            hand.set_remove(cid)
        return True

    # -------------------------------------------------------------------
    # Dice and resource production
    # -------------------------------------------------------------------

    def produce_resources(self, roll: int) -> dict[str, dict[str, int]]:
        """Simulate resource production for a given dice roll.

        Returns {player: {resource: count}} for resources produced.
        """
        produced: dict[str, dict[str, int]] = {p: {} for p in self.players}
        for vertex, owner in self.settlements.items():
            for resource, number in VERTEX_RESOURCES.get(vertex, []):
                if number == roll:
                    produced[owner][resource] = produced[owner].get(resource, 0) + 1
                    self.give_resource(owner, resource)
        return produced

    # -------------------------------------------------------------------
    # Building
    # -------------------------------------------------------------------

    def can_build_road(self, player: str, v_a: str, v_b: str) -> str | None:
        """Validate road building. Returns error message or None if valid."""
        edge = frozenset({v_a, v_b})
        if edge in self.roads:
            return f"edge {v_a}-{v_b} already has a road"
        neighbors_a = self.graph.graph_neighbors(v_a)
        if v_b not in neighbors_a:
            return f"{v_a} and {v_b} are not adjacent"
        if self.count_resource(player, "wood") < 1:
            return "need 1 wood"
        if self.count_resource(player, "brick") < 1:
            return "need 1 brick"
        has_connection = (
            self.settlements.get(v_a) == player
            or self.settlements.get(v_b) == player
            or any(
                player == self.roads.get(frozenset({v_a, n}))
                for n in self.graph.graph_neighbors(v_a)
            )
            or any(
                player == self.roads.get(frozenset({v_b, n}))
                for n in self.graph.graph_neighbors(v_b)
            )
        )
        if not has_connection:
            return "must connect to your existing network"
        return None

    def build_road(self, player: str, v_a: str, v_b: str) -> None:
        """Build a road on edge (v_a, v_b)."""
        error = self.can_build_road(player, v_a, v_b)
        if error is not None:
            raise ValueError(error)
        self.remove_resource(player, "wood", 1)
        self.remove_resource(player, "brick", 1)
        self.roads[frozenset({v_a, v_b})] = player

    def can_build_settlement(self, player: str, vertex: str, setup: bool = False) -> str | None:
        """Validate settlement building. Returns error message or None if valid."""
        if vertex not in self.graph.name_to_index:
            return f"unknown vertex: {vertex}"
        if vertex in self.settlements:
            return f"{vertex} already has a settlement"
        # Distance rule: no adjacent vertex may have a settlement
        for neighbor in self.graph.graph_neighbors(vertex):
            if neighbor in self.settlements:
                return f"too close to settlement at {neighbor}"
        if not setup:
            if self.count_resource(player, "wood") < 1:
                return "need 1 wood"
            if self.count_resource(player, "brick") < 1:
                return "need 1 brick"
            if self.count_resource(player, "sheep") < 1:
                return "need 1 sheep"
            if self.count_resource(player, "wheat") < 1:
                return "need 1 wheat"
            # Must have a road to this vertex
            has_road = any(
                player == self.roads.get(frozenset({vertex, n}))
                for n in self.graph.graph_neighbors(vertex)
            )
            if not has_road:
                return "no road connection to vertex"
        return None

    def build_settlement(self, player: str, vertex: str, setup: bool = False) -> None:
        """Build a settlement at vertex."""
        error = self.can_build_settlement(player, vertex, setup=setup)
        if error is not None:
            raise ValueError(error)
        if not setup:
            self.remove_resource(player, "wood", 1)
            self.remove_resource(player, "brick", 1)
            self.remove_resource(player, "sheep", 1)
            self.remove_resource(player, "wheat", 1)
        self.settlements[vertex] = player
        counter = self.session.runtime.players[player].zones["victory_points"]
        assert isinstance(counter, CounterZone)
        counter.value += 1
        # Place marker on graph
        comp = ComponentData(
            id=ComponentId(0),
            string_id=f"settlement-{player}-{vertex}",
            component_type="settlement",
            owner=player,
            properties={},
        )
        cid = self.session.runtime.components.insert(comp)
        self.graph.graph_set(vertex, cid)

    # -------------------------------------------------------------------
    # Trading
    # -------------------------------------------------------------------

    def bank_trade(self, player: str, give: str, want: str) -> bool:
        """Trade 4 of one resource for 1 of another. Returns success."""
        if self.count_resource(player, give) < 4:
            return False
        if give == want:
            return False
        self.remove_resource(player, give, 4)
        self.give_resource(player, want, 1)
        return True

    # -------------------------------------------------------------------
    # Win check
    # -------------------------------------------------------------------

    def check_winner(self) -> str | None:
        """Return the winner if any player has >= 5 VP, else None."""
        for player in self.players:
            if self.vp(player) >= 5:
                return player
        return None


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and validates."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Settlers of Catan"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["red", "blue"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_hex_map_zone(self) -> None:
        defn = _load_definition()
        assert "hex_map" in defn.zones
        assert defn.zones["hex_map"].zone_type == "hex_grid"

    def test_seven_valid_hex_cells(self) -> None:
        defn = _load_definition()
        assert defn.zones["hex_map"].valid_cells is not None
        assert len(defn.zones["hex_map"].valid_cells) == 7

    def test_settlement_map_is_graph(self) -> None:
        defn = _load_definition()
        assert "settlement_map" in defn.zones
        assert defn.zones["settlement_map"].zone_type == "graph"

    def test_18_vertices(self) -> None:
        defn = _load_definition()
        assert defn.zones["settlement_map"].nodes is not None
        assert len(defn.zones["settlement_map"].nodes) == 18

    def test_30_edges(self) -> None:
        defn = _load_definition()
        assert defn.zones["settlement_map"].edges is not None
        assert len(defn.zones["settlement_map"].edges) == 30

    def test_hand_zone_is_per_player_private(self) -> None:
        defn = _load_definition()
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_vp_zone_is_per_player_counter(self) -> None:
        defn = _load_definition()
        assert defn.zones["victory_points"].zone_type == "counter"
        assert defn.zones["victory_points"].per_player is True

    def test_three_phases(self) -> None:
        defn = _load_definition()
        assert len(defn.phases) == 3
        names = [p.name for p in defn.phases]
        assert names == ["roll_dice", "collect_resources", "trade_or_build"]

    def test_win_condition(self) -> None:
        defn = _load_definition()
        assert len(defn.end_conditions) == 1
        assert defn.end_conditions[0].result == "win"
        assert defn.end_conditions[0].name == "five_victory_points"

    def test_authority_sections(self) -> None:
        defn = _load_definition()
        assert "roll(2d6)" in defn.authority.server_only
        assert len(defn.authority.client_verifiable) == 3

    def test_all_vertices_have_properties(self) -> None:
        defn = _load_definition()
        nodes = defn.zones["settlement_map"].nodes
        props = defn.zones["settlement_map"].node_properties
        assert nodes is not None
        assert props is not None
        for node in nodes:
            assert node in props, f"vertex {node} missing properties"


class TestSession:
    """Verify GameSession builds correct runtime state."""

    def test_session_creates(self) -> None:
        g = CatanGame()
        assert g.session.runtime.status == "in_progress"

    def test_shared_zones(self) -> None:
        g = CatanGame()
        assert "hex_map" in g.session.runtime.zones
        assert "settlement_map" in g.session.runtime.zones

    def test_per_player_zones(self) -> None:
        g = CatanGame()
        for player in ["red", "blue"]:
            assert "hand" in g.session.runtime.players[player].zones
            assert "victory_points" in g.session.runtime.players[player].zones

    def test_graph_has_18_nodes(self) -> None:
        g = CatanGame()
        assert len(g.graph.node_names) == 18

    def test_all_vertices_initially_empty(self) -> None:
        g = CatanGame()
        for node in g.graph.node_names:
            assert g.graph.graph_get(node) is None

    def test_hex_cell_properties_loaded(self) -> None:
        g = CatanGame()
        for (col, row), (resource, number) in HEX_TILES.items():
            assert g.hex_grid.get_cell_property(col, row, "resource") == resource
            assert g.hex_grid.get_cell_property(col, row, "number") == number


class TestGraphConnectivity:
    """Verify settlement graph structure."""

    def test_all_edges_bidirectional(self) -> None:
        g = CatanGame()
        for node in g.graph.node_names:
            for neighbor in g.graph.graph_neighbors(node):
                assert node in g.graph.graph_neighbors(neighbor), (
                    f"{node} -> {neighbor} but not reverse"
                )

    def test_no_self_loops(self) -> None:
        g = CatanGame()
        for node in g.graph.node_names:
            assert node not in g.graph.graph_neighbors(node)

    def test_graph_is_connected(self) -> None:
        """All vertices are reachable from any starting vertex (BFS)."""
        g = CatanGame()
        visited: set[str] = set()
        queue = [g.graph.node_names[0]]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for neighbor in g.graph.graph_neighbors(current):
                if neighbor not in visited:
                    queue.append(neighbor)
        assert visited == set(g.graph.node_names)

    def test_inner_ring_has_three_neighbors(self) -> None:
        """Inner ring vertices (v0-v5) each have exactly 3 neighbors."""
        g = CatanGame()
        for i in range(6):
            node = f"v{i}"
            neighbors = g.graph.graph_neighbors(node)
            assert len(neighbors) == 3, f"{node} has {len(neighbors)} neighbors, expected 3"

    def test_outer_ring_has_three_neighbors(self) -> None:
        """Outer ring vertices (v12-v17) each have exactly 3 neighbors."""
        g = CatanGame()
        for i in range(12, 18):
            node = f"v{i}"
            neighbors = g.graph.graph_neighbors(node)
            assert len(neighbors) == 3, f"{node} has {len(neighbors)} neighbors"


class TestResourceProduction:
    """Verify dice rolls produce correct resources."""

    def test_roll_matching_hex_produces_resources(self) -> None:
        """Rolling a 5 produces wheat for settlements adjacent to the wheat-5 hex."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)  # adjacent to wheat-5
        result = g.produce_resources(5)
        assert result["red"].get("wheat", 0) == 1

    def test_roll_not_matching_produces_nothing(self) -> None:
        """Rolling a 7 matches no hex, so nothing is produced."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        result = g.produce_resources(7)
        assert all(len(res) == 0 for res in result.values())

    def test_vertex_touching_two_hexes(self) -> None:
        """v1 touches wheat-5 and wood-6. Rolling 5 gives wheat, rolling 6 gives wood."""
        g = CatanGame()
        g.build_settlement("red", "v1", setup=True)
        r5 = g.produce_resources(5)
        assert r5["red"].get("wheat", 0) == 1
        r6 = g.produce_resources(6)
        assert r6["red"].get("wood", 0) == 1

    def test_multiple_settlements_same_hex(self) -> None:
        """Two settlements adjacent to the same hex each produce resources."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)    # adjacent to wheat-5
        g.build_settlement("blue", "v2", setup=True)   # adjacent to wheat-5
        result = g.produce_resources(5)
        assert result["red"].get("wheat", 0) == 1
        assert result["blue"].get("wheat", 0) == 1

    def test_no_settlement_no_production(self) -> None:
        """No settlements means no resources regardless of roll."""
        g = CatanGame()
        result = g.produce_resources(8)
        assert all(len(res) == 0 for res in result.values())

    def test_production_adds_to_hand(self) -> None:
        """Produced resources appear in the player's hand."""
        g = CatanGame()
        g.build_settlement("red", "v7", setup=True)  # wood-6 and brick-8
        assert g.hand_size("red") == 0
        g.produce_resources(6)
        assert g.count_resource("red", "wood") == 1
        g.produce_resources(8)
        assert g.count_resource("red", "brick") == 1
        assert g.hand_size("red") == 2

    def test_hub_vertex_produces_four_resources(self) -> None:
        """v13 touches 4 hexes: wood-6, brick-8, ore-10, wheat-4."""
        g = CatanGame()
        g.build_settlement("red", "v13", setup=True)
        g.produce_resources(6)
        assert g.count_resource("red", "wood") == 1
        g.produce_resources(8)
        assert g.count_resource("red", "brick") == 1
        g.produce_resources(10)
        assert g.count_resource("red", "ore") == 1
        g.produce_resources(4)
        assert g.count_resource("red", "wheat") == 1


class TestBuildRoad:
    """Verify road building rules."""

    def test_build_road_costs_wood_and_brick(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 1)
        g.give_resource("red", "brick", 1)
        g.build_road("red", "v0", "v1")
        assert g.count_resource("red", "wood") == 0
        assert g.count_resource("red", "brick") == 0
        assert frozenset({"v0", "v1"}) in g.roads

    def test_build_road_without_wood_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "brick", 1)
        with pytest.raises(ValueError, match="need 1 wood"):
            g.build_road("red", "v0", "v1")

    def test_build_road_without_brick_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 1)
        with pytest.raises(ValueError, match="need 1 brick"):
            g.build_road("red", "v0", "v1")

    def test_build_road_on_existing_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 2)
        g.give_resource("red", "brick", 2)
        g.build_road("red", "v0", "v1")
        with pytest.raises(ValueError, match="already has a road"):
            g.build_road("red", "v0", "v1")

    def test_build_road_non_adjacent_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 1)
        g.give_resource("red", "brick", 1)
        with pytest.raises(ValueError, match="not adjacent"):
            g.build_road("red", "v0", "v14")

    def test_build_road_no_connection_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 1)
        g.give_resource("red", "brick", 1)
        # v8-v9 is far from red's settlement at v0
        with pytest.raises(ValueError, match="must connect"):
            g.build_road("red", "v8", "v9")

    def test_extend_road_from_existing_road(self) -> None:
        """Can build a road connected to an existing road (not just settlements)."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 2)
        g.give_resource("red", "brick", 2)
        g.build_road("red", "v0", "v1")
        # v1-v2 connects to existing road at v1
        g.build_road("red", "v1", "v2")
        assert frozenset({"v1", "v2"}) in g.roads


class TestBuildSettlement:
    """Verify settlement building rules."""

    def test_build_settlement_costs_resources(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 2)
        g.give_resource("red", "brick", 2)
        g.give_resource("red", "sheep", 1)
        g.give_resource("red", "wheat", 1)
        # Build road to v6, then settlement at v6
        g.build_road("red", "v0", "v6")
        # v6 neighbors: v0 (has settlement), v7, v11, v12
        # Need a vertex not adjacent to v0: v6 is adjacent to v0, skip
        # v0's neighbors: v1, v2, v3, v4, v5, v6 — all adjacent
        # Build road from v6 to v12, settle at v12
        g.give_resource("red", "wood", 1)
        g.give_resource("red", "brick", 1)
        g.build_road("red", "v6", "v12")
        g.build_settlement("red", "v12")
        assert g.count_resource("red", "wood") == 0
        assert g.count_resource("red", "brick") == 0
        assert g.count_resource("red", "sheep") == 0
        assert g.count_resource("red", "wheat") == 0
        assert g.vp("red") == 2

    def test_build_settlement_grants_vp(self) -> None:
        g = CatanGame()
        assert g.vp("red") == 0
        g.build_settlement("red", "v0", setup=True)
        assert g.vp("red") == 1

    def test_distance_rule_blocks_adjacent(self) -> None:
        """Cannot build a settlement adjacent to an existing one."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        error = g.can_build_settlement("blue", "v1", setup=True)
        assert error is not None
        assert "too close" in error

    def test_distance_rule_allows_two_apart(self) -> None:
        """Settlements 2 edges apart are allowed."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        # v7 is 2 edges from v0 (v0-v1-v7 or v0-v6-v7)
        error = g.can_build_settlement("blue", "v7", setup=True)
        assert error is None

    def test_build_on_occupied_vertex_fails(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        error = g.can_build_settlement("blue", "v0", setup=True)
        assert error is not None
        assert "already has a settlement" in error

    def test_build_settlement_requires_road_outside_setup(self) -> None:
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        g.give_resource("red", "wood", 1)
        g.give_resource("red", "brick", 1)
        g.give_resource("red", "sheep", 1)
        g.give_resource("red", "wheat", 1)
        # v8 is far from v0 with no road
        error = g.can_build_settlement("red", "v8")
        assert error is not None
        assert "no road" in error

    def test_build_settlement_unknown_vertex_fails(self) -> None:
        g = CatanGame()
        error = g.can_build_settlement("red", "v99")
        assert error is not None
        assert "unknown vertex" in error


class TestBankTrade:
    """Verify 4:1 bank trading."""

    def test_trade_four_for_one(self) -> None:
        g = CatanGame()
        g.give_resource("red", "wood", 4)
        result = g.bank_trade("red", "wood", "ore")
        assert result is True
        assert g.count_resource("red", "wood") == 0
        assert g.count_resource("red", "ore") == 1

    def test_trade_insufficient_fails(self) -> None:
        g = CatanGame()
        g.give_resource("red", "wood", 3)
        result = g.bank_trade("red", "wood", "ore")
        assert result is False
        assert g.count_resource("red", "wood") == 3

    def test_trade_same_resource_fails(self) -> None:
        g = CatanGame()
        g.give_resource("red", "wood", 4)
        result = g.bank_trade("red", "wood", "wood")
        assert result is False
        assert g.count_resource("red", "wood") == 4

    def test_trade_preserves_other_cards(self) -> None:
        g = CatanGame()
        g.give_resource("red", "wood", 5)
        g.give_resource("red", "brick", 2)
        g.bank_trade("red", "wood", "ore")
        assert g.count_resource("red", "wood") == 1
        assert g.count_resource("red", "brick") == 2
        assert g.count_resource("red", "ore") == 1


class TestWinCondition:
    """Verify victory point win condition."""

    def test_no_winner_at_start(self) -> None:
        g = CatanGame()
        assert g.check_winner() is None

    def test_no_winner_below_five(self) -> None:
        g = CatanGame()
        g.set_vp("red", 4)
        assert g.check_winner() is None

    def test_winner_at_five(self) -> None:
        g = CatanGame()
        g.set_vp("red", 5)
        assert g.check_winner() == "red"

    def test_winner_above_five(self) -> None:
        g = CatanGame()
        g.set_vp("blue", 7)
        assert g.check_winner() == "blue"

    def test_first_player_wins_on_tie_check(self) -> None:
        """If both players have >= 5, the first in order is returned."""
        g = CatanGame()
        g.set_vp("red", 5)
        g.set_vp("blue", 5)
        # check_winner iterates in order, red comes first
        assert g.check_winner() == "red"


class TestIntegration:
    """Full turn sequences combining production, building, and winning."""

    def test_setup_and_first_production(self) -> None:
        """Place initial settlements and collect first resources."""
        g = CatanGame()
        g.build_settlement("red", "v1", setup=True)    # wheat-5, wood-6
        g.build_settlement("blue", "v9", setup=True)   # brick-8, sheep-9

        # Roll a 6: red gets wood (v1 touches wood-6)
        result = g.produce_resources(6)
        assert result["red"].get("wood", 0) == 1
        assert result["blue"].get("wood", 0) == 0

        # Roll an 8: blue gets brick (v9 touches brick-8)
        result = g.produce_resources(8)
        assert result["blue"].get("brick", 0) == 1
        assert result["red"].get("brick", 0) == 0

    def test_build_road_and_settlement_sequence(self) -> None:
        """Full sequence: setup, produce, build road, build settlement."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)
        assert g.vp("red") == 1

        # Give resources for 2 roads (2 wood + 2 brick) + 1 settlement (1 wood + 1 brick + 1 sheep + 1 wheat)
        g.give_resource("red", "wood", 3)
        g.give_resource("red", "brick", 3)
        g.give_resource("red", "sheep", 1)
        g.give_resource("red", "wheat", 1)

        # Build road v0->v6
        g.build_road("red", "v0", "v6")
        # Build road v6->v12
        g.build_road("red", "v6", "v12")
        # Build settlement at v12 (2 edges from v0, not adjacent to v0)
        g.build_settlement("red", "v12")
        assert g.vp("red") == 2
        assert "v12" in g.settlements

    def test_play_to_victory(self) -> None:
        """Simulate a game to 5 VP using setup settlements + building."""
        g = CatanGame()
        # Setup: each player places 2 settlements
        # v0 neighbors: v1, v5, v6
        # v9 neighbors: v3, v8, v10, v15 (none adjacent to v0)
        g.build_settlement("red", "v0", setup=True)     # VP=1
        g.build_settlement("blue", "v14", setup=True)
        g.build_settlement("red", "v9", setup=True)     # VP=2
        g.build_settlement("blue", "v16", setup=True)

        assert g.vp("red") == 2

        # Red builds road from v0 toward v12 and settles there
        g.give_resource("red", "wood", 3)
        g.give_resource("red", "brick", 3)
        g.give_resource("red", "sheep", 1)
        g.give_resource("red", "wheat", 1)
        g.build_road("red", "v0", "v6")
        g.build_road("red", "v6", "v12")
        g.build_settlement("red", "v12")  # VP=3
        assert g.vp("red") == 3

        # Directly set VP for remaining to test win condition
        g.set_vp("red", 5)
        assert g.check_winner() == "red"

    def test_bank_trade_enables_building(self) -> None:
        """Use bank trade to convert excess resources into needed ones."""
        g = CatanGame()
        g.build_settlement("red", "v0", setup=True)

        # Red has lots of wood but needs sheep
        g.give_resource("red", "wood", 8)
        g.give_resource("red", "brick", 3)
        g.give_resource("red", "wheat", 1)
        assert g.count_resource("red", "sheep") == 0

        # Trade 4 wood for 1 sheep
        g.bank_trade("red", "wood", "sheep")
        assert g.count_resource("red", "sheep") == 1
        assert g.count_resource("red", "wood") == 4

        # Now has: 4 wood, 3 brick, 1 sheep, 1 wheat
        # Build road v0->v6 (1 wood + 1 brick) => 3 wood, 2 brick, 1 sheep, 1 wheat
        g.build_road("red", "v0", "v6")
        # Build road v6->v12 (1 wood + 1 brick) => 2 wood, 1 brick, 1 sheep, 1 wheat
        g.build_road("red", "v6", "v12")

        # Settle at v12 (1 wood + 1 brick + 1 sheep + 1 wheat) => 1 wood, 0 brick, 0 sheep, 0 wheat
        g.build_settlement("red", "v12")
        assert g.vp("red") == 2
        assert g.count_resource("red", "wood") == 1
        assert g.count_resource("red", "brick") == 0

    def test_both_players_independent_hands(self) -> None:
        """Each player's hand is tracked independently."""
        g = CatanGame()
        g.give_resource("red", "wood", 3)
        g.give_resource("blue", "ore", 2)
        assert g.hand_size("red") == 3
        assert g.hand_size("blue") == 2
        assert g.count_resource("red", "ore") == 0
        assert g.count_resource("blue", "wood") == 0
