"""Tests for Diplomacy: simultaneous secret orders on a territory graph.

Simplified Diplomacy with 3 players (West, Central, East) on a 12-territory
map. All territories are supply centers. Each turn has four phases: diplomacy
(simultaneous secret order writing), resolution (orders revealed and resolved),
retreat (dislodged units withdraw or disband), and build/disband (adjust units
to match supply center count).

Order types: hold, move, support, convoy.
Combat: equal strength = standoff; support adds strength.
Win: first player to control 7 of 12 supply centers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    GraphZone,
    GameSession,
    runtime_zone_from_definition,
)

# ---------------------------------------------------------------------------
# Map data
# ---------------------------------------------------------------------------

REGIONS: dict[str, list[str]] = {
    "west": ["westport", "highlands", "irongate", "cape_west"],
    "central": ["crossroads", "kingsbridge", "marshfield", "stonekeep"],
    "east": ["eastmere", "ridgewall", "harbor", "dawnspire"],
}

HOME_CENTERS: dict[str, list[str]] = {
    "West": REGIONS["west"],
    "Central": REGIONS["central"],
    "East": REGIONS["east"],
}

COASTAL_TERRITORIES: list[str] = [
    "westport", "cape_west", "marshfield", "eastmere", "harbor",
]

ALL_TERRITORIES: list[str] = [
    "westport", "highlands", "irongate", "cape_west",
    "crossroads", "kingsbridge", "marshfield", "stonekeep",
    "eastmere", "ridgewall", "harbor", "dawnspire",
]

MAJORITY_THRESHOLD = 7
TOTAL_SUPPLY_CENTERS = 12

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "diplomacy.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Order types
# ---------------------------------------------------------------------------


class Order:
    """Represents a single unit order."""

    def __init__(
        self,
        unit_territory: str,
        order_type: str,
        destination: str | None = None,
        support_target: str | None = None,
        support_destination: str | None = None,
    ) -> None:
        self.unit_territory = unit_territory
        self.order_type = order_type  # hold, move, support, convoy
        self.destination = destination
        self.support_target = support_target
        self.support_destination = support_destination


# ---------------------------------------------------------------------------
# DiplomacyGame helper
# ---------------------------------------------------------------------------


class DiplomacyGame:
    """Simplified Diplomacy game driver for testing order resolution."""

    def __init__(self) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.players = ["West", "Central", "East"]
        # Unit state: {territory: (owner, unit_type)}
        self.units: dict[str, tuple[str, str]] = {}
        # Supply center control: {territory: owner}
        self.supply_control: dict[str, str] = {}
        self._graph = self._build_graph()

    def _build_graph(self) -> GraphZone:
        zone_def = self.defn.zones["map"]
        zone = runtime_zone_from_definition(zone_def)
        assert isinstance(zone, GraphZone)
        return zone

    @property
    def graph(self) -> GraphZone:
        return self._graph

    # -----------------------------------------------------------------------
    # Unit management
    # -----------------------------------------------------------------------

    def place_unit(
        self, territory: str, owner: str, unit_type: str = "army"
    ) -> None:
        assert territory in ALL_TERRITORIES, f"Unknown territory: {territory}"
        assert unit_type in ("army", "fleet"), f"Invalid unit type: {unit_type}"
        if unit_type == "fleet":
            assert territory in COASTAL_TERRITORIES, (
                f"Fleet can only be placed on coastal territory, got {territory}"
            )
        self.units[territory] = (owner, unit_type)

    def remove_unit(self, territory: str) -> None:
        self.units.pop(territory, None)

    def unit_at(self, territory: str) -> tuple[str, str] | None:
        return self.units.get(territory)

    def units_owned_by(self, player: str) -> list[str]:
        return [t for t, (o, _) in self.units.items() if o == player]

    def are_adjacent(self, a: str, b: str) -> bool:
        neighbors = self.graph.graph_neighbors(a)
        return b in neighbors

    # -----------------------------------------------------------------------
    # Supply center control
    # -----------------------------------------------------------------------

    def update_supply_control(self) -> None:
        """Update supply center control based on unit positions."""
        for territory in ALL_TERRITORIES:
            unit = self.units.get(territory)
            if unit is not None:
                self.supply_control[territory] = unit[0]

    def supply_centers_controlled_by(self, player: str) -> list[str]:
        return [t for t, o in self.supply_control.items() if o == player]

    def unit_count(self, player: str) -> int:
        return len(self.units_owned_by(player))

    def supply_count(self, player: str) -> int:
        return len(self.supply_centers_controlled_by(player))

    # -----------------------------------------------------------------------
    # Order validation
    # -----------------------------------------------------------------------

    def validate_order(self, order: Order, player: str) -> str | None:
        """Validate an order. Returns error message or None if valid."""
        unit = self.units.get(order.unit_territory)
        if unit is None:
            return f"no unit at {order.unit_territory}"
        if unit[0] != player:
            return f"unit at {order.unit_territory} not owned by {player}"
        if order.order_type not in ("hold", "move", "support", "convoy"):
            return f"invalid order type: {order.order_type}"
        if order.order_type == "move":
            if order.destination is None:
                return "move order requires destination"
            if not self.are_adjacent(order.unit_territory, order.destination):
                return (
                    f"{order.unit_territory} and {order.destination} "
                    f"are not adjacent"
                )
        if order.order_type == "support":
            if order.support_destination is None:
                return "support order requires support_destination"
            if not self.are_adjacent(
                order.unit_territory, order.support_destination
            ):
                return (
                    f"supporter at {order.unit_territory} not adjacent to "
                    f"support destination {order.support_destination}"
                )
        return None

    # -----------------------------------------------------------------------
    # Strength calculation
    # -----------------------------------------------------------------------

    def calculate_strength(
        self,
        territory: str,
        orders: list[Order],
        cut_supports_from: set[str] | None = None,
        supported_from: str | None = None,
    ) -> int:
        """Calculate the effective strength of a move or hold at territory.

        Base strength is 1 for the unit holding or moving there.
        Each valid support adds 1. Supports are cut if the supporting unit
        is attacked from a direction other than the support destination.

        If supported_from is given, only count supports whose support_target
        matches that territory (i.e., supports for the specific unit moving
        from supported_from to territory).
        """
        strength = 1
        if cut_supports_from is None:
            cut_supports_from = set()

        for order in orders:
            if order.order_type != "support":
                continue
            if order.support_destination != territory:
                continue
            if supported_from is not None and order.support_target != supported_from:
                continue
            if order.unit_territory in cut_supports_from:
                continue
            if self.are_adjacent(order.unit_territory, territory):
                strength += 1
        return strength

    # -----------------------------------------------------------------------
    # Order resolution
    # -----------------------------------------------------------------------

    def resolve_orders(
        self, all_orders: dict[str, list[Order]]
    ) -> dict[str, object]:
        """Resolve simultaneous orders.

        Returns a dict with:
          - moves: list of (from, to) tuples for successful moves
          - standoffs: list of territories where standoffs occurred
          - dislodged: list of territories where units were dislodged
          - holds: list of territories where units held position
        """
        flat_orders = []
        for player_orders in all_orders.values():
            flat_orders.extend(player_orders)

        # Collect move attempts to each territory
        move_attempts: dict[str, list[Order]] = {}
        for order in flat_orders:
            if order.order_type == "move" and order.destination is not None:
                move_attempts.setdefault(order.destination, []).append(order)

        # Determine which supports are cut (attacked from non-support direction)
        cut_supports: set[str] = set()
        for order in flat_orders:
            if order.order_type == "move" and order.destination is not None:
                dest_unit = self.units.get(order.destination)
                if dest_unit is not None:
                    # Check if the unit at destination is supporting
                    for sup_order in flat_orders:
                        if (
                            sup_order.order_type == "support"
                            and sup_order.unit_territory == order.destination
                            and sup_order.support_destination
                            != order.unit_territory
                        ):
                            cut_supports.add(sup_order.unit_territory)

        moves: list[tuple[str, str]] = []
        standoffs: list[str] = []
        dislodged: list[str] = []
        holds: list[str] = []

        # Resolve each destination
        resolved_destinations: set[str] = set()

        for dest, movers in move_attempts.items():
            resolved_destinations.add(dest)
            strengths = []
            for mover in movers:
                s = self.calculate_strength(
                    dest, flat_orders, cut_supports,
                    supported_from=mover.unit_territory,
                )
                strengths.append((s, mover))

            # If multiple movers with equal max strength => standoff
            max_strength = max(s for s, _ in strengths)
            max_movers = [(s, m) for s, m in strengths if s == max_strength]

            if len(max_movers) > 1:
                standoffs.append(dest)
                for _, m in max_movers:
                    holds.append(m.unit_territory)
                continue

            # Single strongest mover
            _, winner = max_movers[0]

            # Check if destination is occupied and defender holds
            defender = self.units.get(dest)
            if defender is not None:
                # Defender strength: base 1 + supports for holding at dest
                defend_strength = self.calculate_strength(
                    dest, flat_orders, cut_supports,
                    supported_from=dest,
                )
                if max_strength <= defend_strength:
                    standoffs.append(dest)
                    holds.append(winner.unit_territory)
                    holds.append(dest)
                    continue
                else:
                    dislodged.append(dest)

            # Successful move
            moves.append((winner.unit_territory, dest))

        # Apply successful moves
        for src, dst in moves:
            unit = self.units.pop(src)
            self.units[dst] = unit

        # Units that held (didn't move)
        for order in flat_orders:
            if order.order_type == "hold":
                if order.unit_territory not in [m[0] for m in moves]:
                    holds.append(order.unit_territory)

        return {
            "moves": moves,
            "standoffs": standoffs,
            "dislodged": dislodged,
            "holds": holds,
        }

    # -----------------------------------------------------------------------
    # Retreat
    # -----------------------------------------------------------------------

    def valid_retreats(
        self, territory: str, attack_source: str
    ) -> list[str]:
        """Return valid retreat destinations for a dislodged unit."""
        neighbors = self.graph.graph_neighbors(territory)
        valid = []
        for n in neighbors:
            if n == attack_source:
                continue
            if n in self.units:
                continue
            valid.append(n)
        return sorted(valid)

    def retreat_unit(
        self, territory: str, destination: str, attack_source: str
    ) -> bool:
        """Retreat a dislodged unit. Returns True if successful."""
        valid = self.valid_retreats(territory, attack_source)
        if destination not in valid:
            return False
        unit = self.units.pop(territory, None)
        if unit is None:
            return False
        self.units[destination] = unit
        return True

    # -----------------------------------------------------------------------
    # Build / Disband
    # -----------------------------------------------------------------------

    def can_build(self, player: str) -> int:
        """Return number of units the player can build (positive) or must disband (negative)."""
        return self.supply_count(player) - self.unit_count(player)

    def build_unit(
        self, player: str, territory: str, unit_type: str = "army"
    ) -> str | None:
        """Build a new unit on a home supply center. Returns error or None."""
        if territory not in HOME_CENTERS.get(player, []):
            return f"{territory} is not a home supply center for {player}"
        if territory in self.units:
            return f"{territory} is occupied"
        if self.can_build(player) <= 0:
            return f"{player} cannot build (supply={self.supply_count(player)}, units={self.unit_count(player)})"
        if unit_type == "fleet" and territory not in COASTAL_TERRITORIES:
            return f"fleet can only be built on coastal territory, got {territory}"
        self.place_unit(territory, player, unit_type)
        return None

    def disband_unit(self, player: str, territory: str) -> str | None:
        """Disband a unit. Returns error or None."""
        unit = self.units.get(territory)
        if unit is None:
            return f"no unit at {territory}"
        if unit[0] != player:
            return f"unit at {territory} not owned by {player}"
        self.remove_unit(territory)
        return None

    # -----------------------------------------------------------------------
    # Win condition
    # -----------------------------------------------------------------------

    def check_winner(self) -> str | None:
        """Return the winner if any player controls 7+ supply centers."""
        for player in self.players:
            if self.supply_count(player) >= MAJORITY_THRESHOLD:
                return player
        return None


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and validates."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Diplomacy"

    def test_three_named_players(self) -> None:
        defn = _load_definition()
        assert isinstance(defn.game.players, list)
        assert defn.game.players == ["West", "Central", "East"]

    def test_twelve_territories(self) -> None:
        defn = _load_definition()
        zone = defn.zones["map"]
        assert zone.zone_type == "graph"
        assert zone.nodes is not None
        assert len(zone.nodes) == 12

    def test_four_phases(self) -> None:
        defn = _load_definition()
        assert len(defn.phases) == 4
        names = [p.name for p in defn.phases]
        assert names == ["diplomacy", "resolution", "retreat", "build"]

    def test_diplomacy_phase_is_simultaneous(self) -> None:
        defn = _load_definition()
        assert defn.phases[0].simultaneous is True

    def test_authority_sections(self) -> None:
        defn = _load_definition()
        assert "collect_orders(simultaneous_hidden)" in defn.authority.server_only
        assert len(defn.authority.client_verifiable) == 4

    def test_win_condition(self) -> None:
        defn = _load_definition()
        win_conditions = [ec for ec in defn.end_conditions if ec.result == "win"]
        assert len(win_conditions) == 1
        assert win_conditions[0].name == "majority_control"

    def test_draw_condition(self) -> None:
        defn = _load_definition()
        draw_conditions = [ec for ec in defn.end_conditions if ec.result == "draw"]
        assert len(draw_conditions) == 1
        assert draw_conditions[0].name == "agreed_draw"

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_army_and_fleet_components(self) -> None:
        defn = _load_definition()
        assert "army" in defn.components
        assert "fleet" in defn.components
        assert "supply_marker" in defn.components

    def test_order_box_is_per_player_hidden(self) -> None:
        defn = _load_definition()
        order_box = defn.zones["order_box"]
        assert order_box.per_player is True
        assert order_box.visibility == "hidden"

    def test_simultaneous_turn_order(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "simultaneous"

    def test_notation_piece_symbols(self) -> None:
        defn = _load_definition()
        assert defn.notation is not None
        assert defn.notation["piece_symbols"] == {"army": "A", "fleet": "F"}

    def test_wasm_module_declared(self) -> None:
        defn = _load_definition()
        assert defn.wasm_module == "diplomacy_resolver.wasm"


class TestGraphConnectivity:
    """Verify territory graph adjacency is correct."""

    def test_graph_has_twelve_nodes(self) -> None:
        g = DiplomacyGame()
        assert len(g.graph.node_names) == 12

    def test_irongate_connects_west_to_central(self) -> None:
        """irongate is adjacent to crossroads, bridging west and central."""
        g = DiplomacyGame()
        assert g.are_adjacent("irongate", "crossroads")

    def test_stonekeep_connects_central_to_east(self) -> None:
        """stonekeep is adjacent to eastmere, bridging central and east."""
        g = DiplomacyGame()
        assert g.are_adjacent("stonekeep", "eastmere")

    def test_dawnspire_connects_east_to_west(self) -> None:
        """dawnspire is adjacent to highlands, creating a wraparound."""
        g = DiplomacyGame()
        assert g.are_adjacent("dawnspire", "highlands")

    def test_all_edges_are_bidirectional(self) -> None:
        g = DiplomacyGame()
        for node in ALL_TERRITORIES:
            for neighbor in g.graph.graph_neighbors(node):
                assert node in g.graph.graph_neighbors(neighbor), (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_graph_is_connected(self) -> None:
        """All territories reachable from any starting territory (BFS)."""
        g = DiplomacyGame()
        visited: set[str] = set()
        queue = [ALL_TERRITORIES[0]]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for neighbor in g.graph.graph_neighbors(current):
                if neighbor not in visited:
                    queue.append(neighbor)
        assert visited == set(ALL_TERRITORIES)

    def test_no_self_loops(self) -> None:
        g = DiplomacyGame()
        for node in ALL_TERRITORIES:
            assert node not in g.graph.graph_neighbors(node)

    def test_region_membership(self) -> None:
        """Every territory belongs to exactly one region."""
        all_in_regions: list[str] = []
        for members in REGIONS.values():
            all_in_regions.extend(members)
        assert sorted(all_in_regions) == sorted(ALL_TERRITORIES)

    def test_inter_region_edges_exist(self) -> None:
        """There are edges connecting different regions."""
        g = DiplomacyGame()
        territory_to_region = {}
        for region, members in REGIONS.items():
            for t in members:
                territory_to_region[t] = region
        cross_edges = 0
        for node in ALL_TERRITORIES:
            for neighbor in g.graph.graph_neighbors(node):
                if territory_to_region[node] != territory_to_region[neighbor]:
                    cross_edges += 1
        # Each cross-region edge counted twice (bidirectional); need at least 3 pairs
        assert cross_edges >= 6, f"Expected cross-region edges, found {cross_edges}"

    def test_each_region_internally_connected(self) -> None:
        """Within each region, all 4 territories are reachable from each other."""
        g = DiplomacyGame()
        for region, members in REGIONS.items():
            visited: set[str] = set()
            queue = [members[0]]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in g.graph.graph_neighbors(current):
                    if neighbor in members and neighbor not in visited:
                        queue.append(neighbor)
            assert visited == set(members), (
                f"Region {region} not internally connected: "
                f"reached {visited} from {members[0]}"
            )


class TestUnitPlacement:
    """Verify unit placement rules."""

    def test_place_army(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        assert g.unit_at("westport") == ("West", "army")

    def test_place_fleet_on_coastal(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "fleet")
        assert g.unit_at("westport") == ("West", "fleet")

    def test_fleet_on_inland_rejected(self) -> None:
        g = DiplomacyGame()
        with pytest.raises(AssertionError, match="coastal"):
            g.place_unit("highlands", "West", "fleet")

    def test_units_owned_by(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        assert sorted(g.units_owned_by("West")) == ["highlands", "westport"]
        assert g.units_owned_by("Central") == ["crossroads"]
        assert g.units_owned_by("East") == []


class TestOrderValidation:
    """Verify order validation rules."""

    def _setup_basic(self) -> DiplomacyGame:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        return g

    def test_valid_hold_order(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "hold")
        assert g.validate_order(order, "West") is None

    def test_valid_move_order(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "move", destination="highlands")
        assert g.validate_order(order, "West") is None

    def test_move_to_non_adjacent_rejected(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "move", destination="dawnspire")
        error = g.validate_order(order, "West")
        assert error is not None
        assert "not adjacent" in error

    def test_order_for_wrong_player_rejected(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "hold")
        error = g.validate_order(order, "Central")
        assert error is not None
        assert "not owned" in error

    def test_order_for_empty_territory_rejected(self) -> None:
        g = self._setup_basic()
        order = Order("dawnspire", "hold")
        error = g.validate_order(order, "East")
        assert error is not None
        assert "no unit" in error

    def test_invalid_order_type_rejected(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "teleport")
        error = g.validate_order(order, "West")
        assert error is not None
        assert "invalid order type" in error

    def test_move_without_destination_rejected(self) -> None:
        g = self._setup_basic()
        order = Order("westport", "move")
        error = g.validate_order(order, "West")
        assert error is not None
        assert "requires destination" in error

    def test_valid_support_order(self) -> None:
        g = self._setup_basic()
        # highlands supports westport moving to irongate
        order = Order(
            "highlands", "support",
            support_target="westport",
            support_destination="irongate",
        )
        assert g.validate_order(order, "West") is None

    def test_support_not_adjacent_to_destination_rejected(self) -> None:
        g = self._setup_basic()
        # westport tries to support into dawnspire (not adjacent to westport)
        order = Order(
            "westport", "support",
            support_target="highlands",
            support_destination="dawnspire",
        )
        error = g.validate_order(order, "West")
        assert error is not None
        assert "not adjacent" in error


class TestStrengthCalculation:
    """Verify combat strength calculation."""

    def test_base_strength_is_one(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        orders: list[Order] = []
        assert g.calculate_strength("irongate", orders) == 1

    def test_support_adds_one(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        orders = [
            Order(
                "highlands", "support",
                support_target="westport",
                support_destination="irongate",
            ),
        ]
        assert g.calculate_strength("irongate", orders) == 2

    def test_two_supports_add_two(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("cape_west", "West", "army")
        orders = [
            Order(
                "highlands", "support",
                support_target="westport",
                support_destination="irongate",
            ),
            Order(
                "cape_west", "support",
                support_target="westport",
                support_destination="irongate",
            ),
        ]
        assert g.calculate_strength("irongate", orders) == 3

    def test_cut_support_not_counted(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        orders = [
            Order(
                "highlands", "support",
                support_target="westport",
                support_destination="irongate",
            ),
        ]
        # highlands support is cut
        assert g.calculate_strength(
            "irongate", orders, cut_supports_from={"highlands"}
        ) == 1

    def test_support_not_adjacent_not_counted(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("dawnspire", "West", "army")
        orders = [
            Order(
                "dawnspire", "support",
                support_target="westport",
                support_destination="irongate",
            ),
        ]
        # dawnspire is not adjacent to irongate
        assert g.calculate_strength("irongate", orders) == 1


class TestOrderResolution:
    """Verify simultaneous order resolution."""

    def test_simple_move(self) -> None:
        """A single uncontested move succeeds."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        orders = {
            "West": [Order("westport", "move", destination="highlands")],
        }
        result = g.resolve_orders(orders)
        assert ("westport", "highlands") in result["moves"]
        assert g.unit_at("highlands") == ("West", "army")
        assert g.unit_at("westport") is None

    def test_hold_order(self) -> None:
        """A hold order keeps the unit in place."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        orders = {
            "West": [Order("westport", "hold")],
        }
        result = g.resolve_orders(orders)
        assert g.unit_at("westport") == ("West", "army")
        assert "westport" in result["holds"]

    def test_equal_strength_standoff(self) -> None:
        """Two units moving to same territory with equal strength: standoff."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("irongate", "Central", "army")
        orders = {
            "West": [Order("westport", "move", destination="highlands")],
            "Central": [Order("irongate", "move", destination="highlands")],
        }
        result = g.resolve_orders(orders)
        assert "highlands" in result["standoffs"]
        # Neither unit moved
        assert g.unit_at("westport") == ("West", "army")
        assert g.unit_at("irongate") == ("Central", "army")
        assert g.unit_at("highlands") is None

    def test_supported_move_wins(self) -> None:
        """Supported move beats unsupported move to same destination."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("cape_west", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        orders = {
            "West": [
                Order("westport", "move", destination="irongate"),
                Order(
                    "cape_west", "support",
                    support_target="westport",
                    support_destination="irongate",
                ),
            ],
            "Central": [
                Order("crossroads", "move", destination="irongate"),
            ],
        }
        result = g.resolve_orders(orders)
        assert ("westport", "irongate") in result["moves"]
        assert g.unit_at("irongate") == ("West", "army")

    def test_simultaneous_non_conflicting_moves(self) -> None:
        """Two moves to different territories both succeed."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("eastmere", "East", "army")
        orders = {
            "West": [Order("westport", "move", destination="highlands")],
            "East": [Order("eastmere", "move", destination="harbor")],
        }
        result = g.resolve_orders(orders)
        assert ("westport", "highlands") in result["moves"]
        assert ("eastmere", "harbor") in result["moves"]


class TestRetreat:
    """Verify retreat mechanics."""

    def test_valid_retreat_destinations(self) -> None:
        """Retreating unit can go to adjacent empty territory, not attack source."""
        g = DiplomacyGame()
        g.place_unit("irongate", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        # irongate was attacked from crossroads
        valid = g.valid_retreats("irongate", attack_source="crossroads")
        assert "crossroads" not in valid
        # All valid retreats are adjacent, empty, not attack source
        for t in valid:
            assert g.are_adjacent("irongate", t)
            assert g.unit_at(t) is None

    def test_retreat_to_occupied_territory_rejected(self) -> None:
        """Cannot retreat to an occupied territory."""
        g = DiplomacyGame()
        g.place_unit("irongate", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        g.place_unit("highlands", "West", "army")
        valid = g.valid_retreats("irongate", attack_source="crossroads")
        assert "highlands" not in valid

    def test_no_valid_retreat_means_disband(self) -> None:
        """When all retreat paths blocked, no valid retreats exist."""
        g = DiplomacyGame()
        g.place_unit("irongate", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        g.place_unit("highlands", "Central", "army")
        g.place_unit("westport", "Central", "army")
        g.place_unit("cape_west", "Central", "army")
        # irongate attacked from crossroads; highlands, westport, cape_west occupied
        valid = g.valid_retreats("irongate", attack_source="crossroads")
        assert valid == []

    def test_retreat_moves_unit(self) -> None:
        """Successful retreat moves unit to new territory."""
        g = DiplomacyGame()
        g.place_unit("irongate", "West", "army")
        success = g.retreat_unit("irongate", "highlands", attack_source="crossroads")
        assert success is True
        assert g.unit_at("irongate") is None
        assert g.unit_at("highlands") == ("West", "army")

    def test_retreat_to_attack_source_fails(self) -> None:
        """Cannot retreat to the territory the attack came from."""
        g = DiplomacyGame()
        g.place_unit("irongate", "West", "army")
        success = g.retreat_unit("irongate", "crossroads", attack_source="crossroads")
        assert success is False
        assert g.unit_at("irongate") == ("West", "army")


class TestSupplyCenters:
    """Verify supply center control and build mechanics."""

    def test_initial_no_control(self) -> None:
        g = DiplomacyGame()
        for player in g.players:
            assert g.supply_count(player) == 0

    def test_update_control_from_units(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        g.update_supply_control()
        assert g.supply_count("West") == 2
        assert g.supply_count("Central") == 1
        assert g.supply_count("East") == 0

    def test_control_persists_after_unit_moves(self) -> None:
        """Supply center control persists until another player occupies it."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.update_supply_control()
        assert g.supply_control["westport"] == "West"
        # Unit moves away
        g.remove_unit("westport")
        g.place_unit("highlands", "West", "army")
        # Control persists without another update
        assert g.supply_control["westport"] == "West"

    def test_control_changes_on_occupation(self) -> None:
        """Control changes when another player occupies the supply center."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.update_supply_control()
        assert g.supply_control["westport"] == "West"
        # Central occupies westport
        g.remove_unit("westport")
        g.place_unit("westport", "Central", "army")
        g.update_supply_control()
        assert g.supply_control["westport"] == "Central"

    def test_can_build_positive(self) -> None:
        """Player with more supply centers than units can build."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.supply_control = {
            "westport": "West",
            "highlands": "West",
            "irongate": "West",
        }
        assert g.can_build("West") == 2  # 3 supply - 1 unit = 2

    def test_can_build_negative_means_disband(self) -> None:
        """Player with fewer supply centers than units must disband."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("irongate", "West", "army")
        g.supply_control = {"westport": "West"}
        assert g.can_build("West") == -2  # 1 supply - 3 units = -2

    def test_build_on_home_supply_center(self) -> None:
        g = DiplomacyGame()
        g.supply_control = {"westport": "West", "highlands": "West"}
        error = g.build_unit("West", "westport", "army")
        assert error is None
        assert g.unit_at("westport") == ("West", "army")

    def test_build_on_non_home_rejected(self) -> None:
        g = DiplomacyGame()
        g.supply_control = {"crossroads": "West"}
        error = g.build_unit("West", "crossroads", "army")
        assert error is not None
        assert "not a home supply center" in error

    def test_build_on_occupied_rejected(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.supply_control = {"westport": "West", "highlands": "West"}
        error = g.build_unit("West", "westport", "army")
        assert error is not None
        assert "occupied" in error

    def test_build_fleet_on_inland_rejected(self) -> None:
        g = DiplomacyGame()
        g.supply_control = {"highlands": "West", "westport": "West"}
        error = g.build_unit("West", "highlands", "fleet")
        assert error is not None
        assert "coastal" in error

    def test_build_fleet_on_coastal_succeeds(self) -> None:
        g = DiplomacyGame()
        g.supply_control = {"westport": "West", "highlands": "West"}
        error = g.build_unit("West", "westport", "fleet")
        assert error is None
        assert g.unit_at("westport") == ("West", "fleet")

    def test_disband_unit(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        error = g.disband_unit("West", "westport")
        assert error is None
        assert g.unit_at("westport") is None

    def test_disband_wrong_player_rejected(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        error = g.disband_unit("Central", "westport")
        assert error is not None
        assert "not owned" in error

    def test_build_when_no_allowance_rejected(self) -> None:
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.supply_control = {"westport": "West"}
        # 1 supply, 1 unit, can_build = 0
        error = g.build_unit("West", "highlands", "army")
        assert error is not None
        assert "cannot build" in error


class TestWinCondition:
    """Verify game-ending win condition: majority of supply centers."""

    def test_no_winner_initial(self) -> None:
        g = DiplomacyGame()
        assert g.check_winner() is None

    def test_no_winner_with_split_control(self) -> None:
        g = DiplomacyGame()
        for t in REGIONS["west"]:
            g.supply_control[t] = "West"
        for t in REGIONS["central"]:
            g.supply_control[t] = "Central"
        for t in REGIONS["east"]:
            g.supply_control[t] = "East"
        assert g.check_winner() is None  # 4 each, none >= 7

    def test_winner_with_seven_centers(self) -> None:
        g = DiplomacyGame()
        # West controls 7 supply centers
        for t in REGIONS["west"] + REGIONS["central"][:3]:
            g.supply_control[t] = "West"
        assert g.supply_count("West") == 7
        assert g.check_winner() == "West"

    def test_winner_with_all_twelve(self) -> None:
        g = DiplomacyGame()
        for t in ALL_TERRITORIES:
            g.supply_control[t] = "East"
        assert g.check_winner() == "East"

    def test_six_centers_not_enough(self) -> None:
        g = DiplomacyGame()
        for t in REGIONS["west"] + REGIONS["central"][:2]:
            g.supply_control[t] = "West"
        assert g.supply_count("West") == 6
        assert g.check_winner() is None


class TestIntegration:
    """Full turn sequence: orders, resolution, retreat, build."""

    def test_full_turn_sequence(self) -> None:
        """Execute a complete turn: diplomacy orders, resolve, retreat, build."""
        g = DiplomacyGame()
        # Setup: each player starts with 3 units on 3 of their 4 home centers
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("irongate", "West", "army")
        g.place_unit("crossroads", "Central", "army")
        g.place_unit("kingsbridge", "Central", "army")
        g.place_unit("marshfield", "Central", "fleet")
        g.place_unit("eastmere", "East", "fleet")
        g.place_unit("ridgewall", "East", "army")
        g.place_unit("harbor", "East", "fleet")

        # Mark initial supply control
        for player, homes in HOME_CENTERS.items():
            for t in homes:
                if g.unit_at(t) is not None:
                    g.supply_control[t] = player

        assert g.supply_count("West") == 3
        assert g.supply_count("Central") == 3
        assert g.supply_count("East") == 3

        # Phase 1: Diplomacy — all players write orders simultaneously
        orders = {
            "West": [
                Order("westport", "hold"),
                Order("highlands", "hold"),
                Order("irongate", "move", destination="crossroads"),
            ],
            "Central": [
                Order("crossroads", "hold"),
                Order("kingsbridge", "hold"),
                Order("marshfield", "hold"),
            ],
            "East": [
                Order("eastmere", "hold"),
                Order("ridgewall", "hold"),
                Order("harbor", "hold"),
            ],
        }

        # Phase 2: Resolution
        result = g.resolve_orders(orders)
        # irongate vs crossroads: move strength 1 vs hold strength 1 = standoff
        assert "crossroads" in result["standoffs"]
        assert g.unit_at("irongate") == ("West", "army")
        assert g.unit_at("crossroads") == ("Central", "army")

        # Phase 3: No retreats needed (no dislodgements)
        assert result["dislodged"] == []

        # Phase 4: Build — each player has supply = units, no builds needed
        for player in g.players:
            assert g.can_build(player) == 0

    def test_supported_attack_dislodges_defender(self) -> None:
        """Supported attack dislodges the defender, who must retreat."""
        g = DiplomacyGame()
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("irongate", "Central", "army")

        orders = {
            "West": [
                Order("westport", "move", destination="irongate"),
                Order(
                    "highlands", "support",
                    support_target="westport",
                    support_destination="irongate",
                ),
            ],
            "Central": [
                Order("irongate", "hold"),
            ],
        }
        result = g.resolve_orders(orders)

        # West's move to irongate had strength 2, Central's hold had strength 1
        assert ("westport", "irongate") in result["moves"]
        assert g.unit_at("irongate") == ("West", "army")

    def test_build_after_conquest(self) -> None:
        """After conquering supply centers, player can build new units."""
        g = DiplomacyGame()
        # West controls 5 supply centers but only has 3 units
        g.place_unit("westport", "West", "army")
        g.place_unit("highlands", "West", "army")
        g.place_unit("irongate", "West", "army")
        for t in REGIONS["west"]:
            g.supply_control[t] = "West"
        g.supply_control["crossroads"] = "West"

        assert g.supply_count("West") == 5
        assert g.unit_count("West") == 3
        assert g.can_build("West") == 2

        # Build on unoccupied home supply center
        error = g.build_unit("West", "cape_west", "fleet")
        assert error is None
        assert g.unit_at("cape_west") == ("West", "fleet")
        assert g.can_build("West") == 1
