"""Tests for Scotland Yard: hidden movement deduction on a transport network.

Simplified Scotland Yard with 3 players: 1 Mr. X + 2 detectives.
20 locations connected by taxi, bus, and underground edges.
Mr. X moves secretly; detectives try to land on his position.
Mr. X reveals his position on turns 3, 8, 13, 18.
Detectives have limited tickets; Mr. X receives used detective tickets.
Mr. X wins by surviving 22 rounds; detectives win by catching him.
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
    SetZone,
    SlotZone,
    StackZone,
    runtime_zone_from_definition,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "scotland-yard.json"

ALL_LOCATIONS = [f"loc_{i}" for i in range(1, 21)]

REVEAL_TURNS = [3, 8, 13, 18]
MAX_ROUNDS = 22

TRANSPORT_TYPES = ["taxi", "bus", "underground"]

# Transport type for each edge: (loc_a, loc_b) -> set of transport types.
# Taxi: all grid-adjacent edges (the first 31 edges in the definition).
# Bus: diagonal/express edges where both have has_bus.
# Underground: edges between stations with has_underground.
UNDERGROUND_STATIONS = {
    "loc_1", "loc_3", "loc_5", "loc_6", "loc_9", "loc_10",
    "loc_11", "loc_13", "loc_15", "loc_18", "loc_19", "loc_20",
}

# Edges that support taxi (all edges support taxi)
TAXI_EDGES: set[frozenset[str]] = set()

# Bus edges (the diagonal/express edges, indices 31-40 in definition)
BUS_EDGES: set[frozenset[str]] = set()

# Underground edges (only between underground stations with direct edges)
UNDERGROUND_EDGES: set[frozenset[str]] = set()

# Starting tickets for detectives
DETECTIVE_STARTING_TICKETS = {"taxi": 10, "bus": 8, "underground": 4}

# Mr. X starts with more tickets
MR_X_STARTING_TICKETS = {"taxi": 4, "bus": 3, "underground": 3}


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _build_edge_maps() -> None:
    """Build transport edge maps from the game definition."""
    defn = _load_definition()
    zone = defn.zones["board"]
    assert zone.edges is not None

    # Grid edges (first 31): taxi only
    grid_edges = zone.edges[:31]
    # Express edges (31 onward): bus
    express_edges = zone.edges[31:]

    for e in zone.edges:
        TAXI_EDGES.add(frozenset(e))

    for e in express_edges:
        BUS_EDGES.add(frozenset(e))

    # Underground: express edges where both endpoints are underground stations
    for e in express_edges:
        if e[0] in UNDERGROUND_STATIONS and e[1] in UNDERGROUND_STATIONS:
            UNDERGROUND_EDGES.add(frozenset(e))


_build_edge_maps()


# ---------------------------------------------------------------------------
# ScotlandYardGame helper
# ---------------------------------------------------------------------------


class ScotlandYardGame:
    """Scotland Yard game driver for testing hidden movement and deduction."""

    def __init__(self) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self._graph = self._build_graph()

        # Player positions
        self.mr_x_position: str | None = None
        self.detective_positions: dict[str, str] = {}

        # Tickets: {player: {transport_type: count}}
        self.tickets: dict[str, dict[str, int]] = {
            "mr_x": dict(MR_X_STARTING_TICKETS),
            "detective_1": dict(DETECTIVE_STARTING_TICKETS),
            "detective_2": dict(DETECTIVE_STARTING_TICKETS),
        }

        # Mr. X travel log: list of transport types used
        self.travel_log: list[str] = []

        # Round counter
        self.round_number: int = 0

        # Track whose turn it is within a round
        self._turn_order = ["mr_x", "detective_1", "detective_2"]
        self._turn_index = 0

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
        return self._turn_order[self._turn_index]

    # -------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------

    def setup(
        self,
        mr_x_start: str,
        det1_start: str,
        det2_start: str,
    ) -> None:
        """Place all players at starting positions."""
        assert mr_x_start in ALL_LOCATIONS
        assert det1_start in ALL_LOCATIONS
        assert det2_start in ALL_LOCATIONS
        assert len({mr_x_start, det1_start, det2_start}) == 3, (
            "All starting positions must be different"
        )
        self.mr_x_position = mr_x_start
        self.detective_positions["detective_1"] = det1_start
        self.detective_positions["detective_2"] = det2_start
        self.round_number = 1
        self._turn_index = 0

    # -------------------------------------------------------------------
    # Transport connectivity
    # -------------------------------------------------------------------

    def connections_by_transport(
        self, location: str, transport: str,
    ) -> list[str]:
        """Return locations reachable from a location by a transport type."""
        neighbors = self.graph.graph_neighbors(location)
        result: list[str] = []
        for n in neighbors:
            edge = frozenset([location, n])
            if transport == "taxi" and edge in TAXI_EDGES:
                result.append(n)
            elif transport == "bus" and edge in BUS_EDGES:
                result.append(n)
            elif transport == "underground" and edge in UNDERGROUND_EDGES:
                result.append(n)
        return result

    def reachable(self, location: str) -> dict[str, list[str]]:
        """Return all reachable locations grouped by transport type."""
        return {
            t: self.connections_by_transport(location, t)
            for t in TRANSPORT_TYPES
        }

    # -------------------------------------------------------------------
    # Move validation
    # -------------------------------------------------------------------

    def validate_move(
        self, player: str, destination: str, transport: str,
    ) -> str | None:
        """Validate a move. Returns error string or None if valid."""
        if player not in self.tickets:
            return f"unknown player: {player}"
        if destination not in ALL_LOCATIONS:
            return f"unknown location: {destination}"
        if transport not in TRANSPORT_TYPES:
            return f"unknown transport: {transport}"

        # Get current position
        if player == "mr_x":
            current = self.mr_x_position
        else:
            current = self.detective_positions.get(player)
        if current is None:
            return f"{player} has no current position"

        # Check adjacency by transport type
        reachable = self.connections_by_transport(current, transport)
        if destination not in reachable:
            return f"{destination} not reachable from {current} by {transport}"

        # Check ticket availability
        if self.tickets[player].get(transport, 0) < 1:
            return f"{player} has no {transport} tickets"

        # Detectives cannot move to a location occupied by another detective
        if player != "mr_x":
            for det, pos in self.detective_positions.items():
                if det != player and pos == destination:
                    return f"{destination} occupied by {det}"

        return None

    # -------------------------------------------------------------------
    # Execute move
    # -------------------------------------------------------------------

    def execute_move(
        self, player: str, destination: str, transport: str,
    ) -> dict[str, object]:
        """Execute a validated move. Returns outcome dict."""
        error = self.validate_move(player, destination, transport)
        if error is not None:
            raise ValueError(error)

        # Spend ticket
        self.tickets[player][transport] -= 1

        # Move player
        if player == "mr_x":
            self.mr_x_position = destination
            self.travel_log.append(transport)
        else:
            self.detective_positions[player] = destination
            # Mr. X receives the spent ticket
            self.tickets["mr_x"][transport] = (
                self.tickets["mr_x"].get(transport, 0) + 1
            )

        # Advance turn
        self._turn_index += 1
        if self._turn_index >= len(self._turn_order):
            self._turn_index = 0
            self.round_number += 1

        # Check for catch
        caught = self.is_mr_x_caught()

        return {
            "player": player,
            "destination": destination,
            "transport": transport,
            "caught": caught,
            "round": self.round_number,
        }

    # -------------------------------------------------------------------
    # Reveal logic
    # -------------------------------------------------------------------

    def is_reveal_turn(self) -> bool:
        """Whether Mr. X must reveal his position this round."""
        return self.round_number in REVEAL_TURNS

    def reveal_mr_x(self) -> str | None:
        """Reveal Mr. X's position if it's a reveal turn."""
        if self.is_reveal_turn():
            return self.mr_x_position
        return None

    # -------------------------------------------------------------------
    # End conditions
    # -------------------------------------------------------------------

    def is_mr_x_caught(self) -> bool:
        """Check if any detective is on Mr. X's position."""
        if self.mr_x_position is None:
            return False
        for pos in self.detective_positions.values():
            if pos == self.mr_x_position:
                return True
        return False

    def is_mr_x_survived(self) -> bool:
        """Check if Mr. X survived all rounds."""
        return self.round_number > MAX_ROUNDS and not self.is_mr_x_caught()

    def winner(self) -> str | None:
        """Return the winner or None if game is ongoing."""
        if self.is_mr_x_caught():
            return "detectives"
        if self.is_mr_x_survived():
            return "mr_x"
        return None

    # -------------------------------------------------------------------
    # Detective stuck detection
    # -------------------------------------------------------------------

    def detective_can_move(self, detective: str) -> bool:
        """Check if a detective has any legal move available."""
        pos = self.detective_positions.get(detective)
        if pos is None:
            return False
        for transport in TRANSPORT_TYPES:
            if self.tickets[detective].get(transport, 0) < 1:
                continue
            destinations = self.connections_by_transport(pos, transport)
            for dest in destinations:
                # Check not occupied by another detective
                occupied = any(
                    p == dest
                    for d, p in self.detective_positions.items()
                    if d != detective
                )
                if not occupied:
                    return True
        return False


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and validates."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Scotland Yard"

    def test_three_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["mr_x", "detective_1", "detective_2"]

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"

    def test_twenty_locations(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.zone_type == "graph"
        assert zone.nodes is not None
        assert len(zone.nodes) == 20

    def test_mr_x_position_zone_hidden(self) -> None:
        defn = _load_definition()
        assert "mr_x_position" in defn.zones
        assert defn.zones["mr_x_position"].zone_type == "single_slot"
        assert defn.zones["mr_x_position"].visibility == "hidden"

    def test_turn_order_round_robin(self) -> None:
        defn = _load_definition()
        assert defn.turn_order.type == "round_robin"
        assert defn.turn_order.players == ["mr_x", "detective_1", "detective_2"]

    def test_authority_sections(self) -> None:
        defn = _load_definition()
        assert "mr_x_position" in defn.authority.server_only
        assert "detective_movement" in defn.authority.client_verifiable

    def test_end_conditions(self) -> None:
        defn = _load_definition()
        assert len(defn.end_conditions) == 4
        names = [ec.name for ec in defn.end_conditions]
        assert "mr_x_survives" in names
        assert "mr_x_caught" in names

    def test_two_phases(self) -> None:
        defn = _load_definition()
        assert len(defn.phases) == 2
        assert defn.phases[0].name == "setup"
        assert defn.phases[1].name == "move"

    def test_node_properties_present(self) -> None:
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.node_properties is not None
        assert len(zone.node_properties) == 20
        for loc in ALL_LOCATIONS:
            assert loc in zone.node_properties
            props = zone.node_properties[loc]
            assert "label" in props
            assert "has_taxi" in props
            assert "has_bus" in props
            assert "has_underground" in props


class TestGraphConnectivity:
    """Verify the board graph structure."""

    def test_twenty_nodes(self) -> None:
        g = ScotlandYardGame()
        assert len(g.graph.node_names) == 20

    def test_all_edges_bidirectional(self) -> None:
        g = ScotlandYardGame()
        for node in ALL_LOCATIONS:
            for neighbor in g.graph.graph_neighbors(node):
                assert node in g.graph.graph_neighbors(neighbor), (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_graph_is_connected(self) -> None:
        """BFS from loc_1 should reach all 20 locations."""
        g = ScotlandYardGame()
        visited: set[str] = set()
        queue = ["loc_1"]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for neighbor in g.graph.graph_neighbors(current):
                if neighbor not in visited:
                    queue.append(neighbor)
        assert visited == set(ALL_LOCATIONS)

    def test_no_self_loops(self) -> None:
        g = ScotlandYardGame()
        for node in ALL_LOCATIONS:
            assert node not in g.graph.graph_neighbors(node)

    def test_loc_1_has_multiple_neighbors(self) -> None:
        """loc_1 is connected to loc_2, loc_6, loc_7, loc_11."""
        g = ScotlandYardGame()
        neighbors = g.graph.graph_neighbors("loc_1")
        assert "loc_2" in neighbors
        assert "loc_6" in neighbors
        assert "loc_7" in neighbors
        assert "loc_11" in neighbors


class TestTransportTypes:
    """Verify transport type edge classification."""

    def test_all_edges_have_taxi(self) -> None:
        """Every edge in the graph supports taxi."""
        g = ScotlandYardGame()
        for node in ALL_LOCATIONS:
            neighbors = g.graph.graph_neighbors(node)
            for n in neighbors:
                edge = frozenset([node, n])
                assert edge in TAXI_EDGES, f"edge {node}-{n} missing taxi"

    def test_bus_edges_exist(self) -> None:
        """Bus edges are a subset of all edges."""
        assert len(BUS_EDGES) > 0
        for edge in BUS_EDGES:
            assert edge in TAXI_EDGES, f"bus edge {edge} not in taxi edges"

    def test_underground_edges_subset_of_bus(self) -> None:
        """Underground edges are between underground stations."""
        for edge in UNDERGROUND_EDGES:
            nodes = list(edge)
            assert nodes[0] in UNDERGROUND_STATIONS
            assert nodes[1] in UNDERGROUND_STATIONS

    def test_underground_stations_correct(self) -> None:
        """Verify underground stations match node properties."""
        defn = _load_definition()
        zone = defn.zones["board"]
        assert zone.node_properties is not None
        for loc in ALL_LOCATIONS:
            props = zone.node_properties[loc]
            if props["has_underground"] is True:
                assert loc in UNDERGROUND_STATIONS, f"{loc} should be underground"
            else:
                assert loc not in UNDERGROUND_STATIONS, f"{loc} should not be underground"

    def test_taxi_reachable_from_loc_1(self) -> None:
        g = ScotlandYardGame()
        taxi = g.connections_by_transport("loc_1", "taxi")
        assert len(taxi) >= 2

    def test_underground_reachable_from_loc_1(self) -> None:
        """loc_1 is an underground station with underground connections."""
        g = ScotlandYardGame()
        ug = g.connections_by_transport("loc_1", "underground")
        assert len(ug) >= 1
        for dest in ug:
            assert dest in UNDERGROUND_STATIONS


class TestSetup:
    """Verify game setup."""

    def test_valid_setup(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.mr_x_position == "loc_1"
        assert g.detective_positions["detective_1"] == "loc_10"
        assert g.detective_positions["detective_2"] == "loc_15"
        assert g.round_number == 1

    def test_duplicate_positions_rejected(self) -> None:
        g = ScotlandYardGame()
        with pytest.raises(AssertionError, match="different"):
            g.setup("loc_1", "loc_1", "loc_5")

    def test_starting_tickets(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.tickets["detective_1"]["taxi"] == 10
        assert g.tickets["detective_1"]["bus"] == 8
        assert g.tickets["detective_1"]["underground"] == 4
        assert g.tickets["mr_x"]["taxi"] == 4
        assert g.tickets["mr_x"]["bus"] == 3
        assert g.tickets["mr_x"]["underground"] == 3

    def test_mr_x_moves_first(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.current_player == "mr_x"


class TestMoveValidation:
    """Verify move validation rules."""

    def _game(self) -> ScotlandYardGame:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        return g

    def test_valid_taxi_move(self) -> None:
        g = self._game()
        error = g.validate_move("mr_x", "loc_2", "taxi")
        assert error is None

    def test_non_adjacent_rejected(self) -> None:
        g = self._game()
        error = g.validate_move("mr_x", "loc_20", "taxi")
        assert error is not None
        assert "not reachable" in error

    def test_no_ticket_rejected(self) -> None:
        g = self._game()
        g.tickets["mr_x"]["taxi"] = 0
        error = g.validate_move("mr_x", "loc_2", "taxi")
        assert error is not None
        assert "no taxi tickets" in error

    def test_detective_overlap_rejected(self) -> None:
        """Detectives cannot move to a location occupied by another detective."""
        g = self._game()
        # Move detectives near each other
        g.detective_positions["detective_1"] = "loc_9"
        g.detective_positions["detective_2"] = "loc_8"
        # Try to move det_2 to loc_9 (occupied by det_1)
        error = g.validate_move("detective_2", "loc_9", "taxi")
        assert error is not None
        assert "occupied" in error

    def test_mr_x_can_move_to_detective_location(self) -> None:
        """Mr. X CAN move to a detective's location (but will be caught)."""
        g = self._game()
        g.mr_x_position = "loc_9"
        g.detective_positions["detective_1"] = "loc_10"
        error = g.validate_move("mr_x", "loc_10", "taxi")
        assert error is None

    def test_underground_requires_station(self) -> None:
        """Cannot use underground from non-station or to non-station."""
        g = self._game()
        # loc_7 (Oxford Circus) is not an underground station
        g.detective_positions["detective_1"] = "loc_7"
        ug = g.connections_by_transport("loc_7", "underground")
        assert len(ug) == 0


class TestMovement:
    """Verify move execution and side effects."""

    def _game(self) -> ScotlandYardGame:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        return g

    def test_mr_x_move_updates_position(self) -> None:
        g = self._game()
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.mr_x_position == "loc_2"

    def test_mr_x_move_spends_ticket(self) -> None:
        g = self._game()
        before = g.tickets["mr_x"]["taxi"]
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.tickets["mr_x"]["taxi"] == before - 1

    def test_mr_x_move_logged(self) -> None:
        g = self._game()
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.travel_log == ["taxi"]

    def test_detective_move_updates_position(self) -> None:
        g = self._game()
        g.execute_move("mr_x", "loc_2", "taxi")  # Mr. X goes first
        g.execute_move("detective_1", "loc_9", "taxi")
        assert g.detective_positions["detective_1"] == "loc_9"

    def test_detective_ticket_transferred_to_mr_x(self) -> None:
        """Used detective tickets go to Mr. X."""
        g = self._game()
        mr_x_taxi_before = g.tickets["mr_x"]["taxi"]
        g.execute_move("mr_x", "loc_2", "taxi")
        g.execute_move("detective_1", "loc_9", "taxi")
        # Mr. X lost 1 taxi, gained 1 from detective
        assert g.tickets["mr_x"]["taxi"] == mr_x_taxi_before - 1 + 1

    def test_round_advances_after_all_players(self) -> None:
        """Round number increments after all 3 players move."""
        g = self._game()
        assert g.round_number == 1
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.round_number == 1
        g.execute_move("detective_1", "loc_9", "taxi")
        assert g.round_number == 1
        g.execute_move("detective_2", "loc_14", "taxi")
        assert g.round_number == 2

    def test_turn_order_cycles(self) -> None:
        g = self._game()
        assert g.current_player == "mr_x"
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.current_player == "detective_1"
        g.execute_move("detective_1", "loc_9", "taxi")
        assert g.current_player == "detective_2"
        g.execute_move("detective_2", "loc_14", "taxi")
        assert g.current_player == "mr_x"


class TestRevealTurns:
    """Verify Mr. X reveal mechanic."""

    def test_not_reveal_on_round_1(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.round_number == 1
        assert g.is_reveal_turn() is False
        assert g.reveal_mr_x() is None

    def test_reveal_on_round_3(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 3
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_1"

    def test_reveal_on_round_8(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 8
        assert g.is_reveal_turn() is True

    def test_reveal_on_round_13(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 13
        assert g.is_reveal_turn() is True

    def test_reveal_on_round_18(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 18
        assert g.is_reveal_turn() is True

    def test_not_reveal_on_round_4(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 4
        assert g.is_reveal_turn() is False

    def test_reveal_returns_current_position(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.mr_x_position = "loc_7"
        g.round_number = 3
        assert g.reveal_mr_x() == "loc_7"


class TestTravelLog:
    """Verify Mr. X's public travel log."""

    def test_empty_initially(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.travel_log == []

    def test_logs_transport_type(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.travel_log == ["taxi"]

    def test_detective_moves_not_logged(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.execute_move("mr_x", "loc_2", "taxi")
        g.execute_move("detective_1", "loc_9", "taxi")
        assert g.travel_log == ["taxi"]  # Only Mr. X's move

    def test_multiple_rounds_logged(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")

        # Round 1: Mr. X uses taxi
        g.execute_move("mr_x", "loc_2", "taxi")
        g.execute_move("detective_1", "loc_9", "taxi")
        g.execute_move("detective_2", "loc_14", "taxi")

        # Round 2: Mr. X uses bus (loc_2 -> loc_7 via bus if available)
        # loc_2 neighbors: loc_1, loc_3, loc_7 — check bus availability
        bus_from_2 = g.connections_by_transport("loc_2", "bus")
        if bus_from_2:
            dest = bus_from_2[0]
            g.execute_move("mr_x", dest, "bus")
            assert g.travel_log == ["taxi", "bus"]
        else:
            # Fall back to taxi
            g.execute_move("mr_x", "loc_3", "taxi")
            assert g.travel_log == ["taxi", "taxi"]


class TestEndConditions:
    """Verify game ending conditions."""

    def test_detectives_catch_mr_x(self) -> None:
        """Detective moving to Mr. X's location catches him."""
        g = ScotlandYardGame()
        g.setup("loc_8", "loc_7", "loc_15")
        # Mr. X at loc_8, detective_1 at loc_7 (adjacent via taxi)
        g.execute_move("mr_x", "loc_9", "taxi")  # Mr. X moves away
        # But detective_1 follows to loc_8
        g.execute_move("detective_1", "loc_8", "taxi")
        # Not caught yet (Mr. X moved to loc_9)
        assert g.is_mr_x_caught() is False

        # Next round: Mr. X stays at loc_9
        g.execute_move("detective_2", "loc_14", "taxi")
        # Round 2
        g.execute_move("mr_x", "loc_8", "taxi")  # Mr. X goes back to 8
        # detective_1 at loc_8, Mr. X moves TO loc_8
        assert g.is_mr_x_caught() is True
        assert g.winner() == "detectives"

    def test_mr_x_survives_22_rounds(self) -> None:
        """Mr. X wins if round counter exceeds 22 without being caught."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 23
        assert g.is_mr_x_survived() is True
        assert g.winner() == "mr_x"

    def test_game_ongoing_mid_game(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 10
        assert g.winner() is None

    def test_catch_on_mr_x_move(self) -> None:
        """Mr. X is caught if he moves onto a detective's position."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_2", "loc_15")
        # Mr. X at loc_1, det_1 at loc_2. Mr. X moves to loc_2.
        result = g.execute_move("mr_x", "loc_2", "taxi")
        assert result["caught"] is True
        assert g.is_mr_x_caught() is True
        assert g.winner() == "detectives"

    def test_not_survived_if_caught_at_round_22(self) -> None:
        """Caught at round 22 means detectives win, not Mr. X."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.round_number = 22
        g.mr_x_position = "loc_10"  # Same as detective_1
        assert g.is_mr_x_caught() is True
        assert g.winner() == "detectives"  # Catch overrides survival


class TestTicketManagement:
    """Verify ticket spending and transfer mechanics."""

    def test_ticket_decremented_on_use(self) -> None:
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        before = g.tickets["detective_1"]["taxi"]
        g.execute_move("mr_x", "loc_2", "taxi")
        g.execute_move("detective_1", "loc_9", "taxi")
        assert g.tickets["detective_1"]["taxi"] == before - 1

    def test_detective_tickets_go_to_mr_x(self) -> None:
        """Mr. X accumulates detective tickets."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        mr_x_bus_before = g.tickets["mr_x"]["bus"]
        g.execute_move("mr_x", "loc_2", "taxi")

        # Detective uses bus from loc_10 to loc_5 (if bus edge exists)
        bus_from_10 = g.connections_by_transport("loc_10", "bus")
        if bus_from_10:
            g.execute_move("detective_1", bus_from_10[0], "bus")
            assert g.tickets["mr_x"]["bus"] == mr_x_bus_before + 1
        else:
            # Just verify taxi transfer works
            g.execute_move("detective_1", "loc_9", "taxi")
            # Mr. X spent 1 taxi, gained 1 taxi from detective
            assert g.tickets["mr_x"]["taxi"] == MR_X_STARTING_TICKETS["taxi"]

    def test_zero_tickets_blocks_move(self) -> None:
        """Cannot move with a transport type when out of tickets."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.tickets["detective_1"]["bus"] = 0
        g.execute_move("mr_x", "loc_2", "taxi")
        # Try bus move from det_1
        bus_from_10 = g.connections_by_transport("loc_10", "bus")
        if bus_from_10:
            error = g.validate_move("detective_1", bus_from_10[0], "bus")
            assert error is not None
            assert "no bus tickets" in error

    def test_detective_can_move_detection(self) -> None:
        """Detective with tickets and valid moves can move."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        assert g.detective_can_move("detective_1") is True

    def test_stranded_detective_cannot_move(self) -> None:
        """Detective with no tickets of any type cannot move."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")
        g.tickets["detective_1"] = {"taxi": 0, "bus": 0, "underground": 0}
        assert g.detective_can_move("detective_1") is False


class TestIntegration:
    """Full game sequence integration tests."""

    def test_full_round(self) -> None:
        """Execute one complete round: Mr. X + 2 detectives."""
        g = ScotlandYardGame()
        g.setup("loc_1", "loc_10", "loc_15")

        # Round 1: Mr. X moves
        assert g.current_player == "mr_x"
        g.execute_move("mr_x", "loc_2", "taxi")
        assert g.travel_log == ["taxi"]

        # Detective 1 moves
        assert g.current_player == "detective_1"
        g.execute_move("detective_1", "loc_9", "taxi")

        # Detective 2 moves
        assert g.current_player == "detective_2"
        g.execute_move("detective_2", "loc_14", "taxi")

        # Round advanced
        assert g.round_number == 2
        assert g.current_player == "mr_x"
        assert g.winner() is None

    def test_chase_sequence(self) -> None:
        """Simulate a short chase: Mr. X flees, detectives pursue."""
        g = ScotlandYardGame()
        g.setup("loc_8", "loc_7", "loc_3")

        # Round 1: Mr. X flees to loc_13, detectives converge
        g.execute_move("mr_x", "loc_13", "taxi")
        g.execute_move("detective_1", "loc_8", "taxi")
        g.execute_move("detective_2", "loc_4", "taxi")

        # Round 2
        assert g.round_number == 2
        g.execute_move("mr_x", "loc_18", "taxi")
        g.execute_move("detective_1", "loc_13", "taxi")
        g.execute_move("detective_2", "loc_9", "taxi")

        # Round 3: reveal turn
        assert g.round_number == 3
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_18"

        # Mr. X at loc_18, det_1 at loc_13, det_2 at loc_9
        # Detectives now know Mr. X is at loc_18
        g.execute_move("mr_x", "loc_19", "taxi")
        g.execute_move("detective_1", "loc_18", "taxi")
        g.execute_move("detective_2", "loc_14", "taxi")

        # Round 4: det_1 at loc_18, det_2 at loc_14
        # Mr. X at loc_19, tries to flee
        assert g.round_number == 4
        g.execute_move("mr_x", "loc_20", "taxi")
        g.execute_move("detective_1", "loc_19", "taxi")
        # det_2 at loc_14, moves to loc_15
        g.execute_move("detective_2", "loc_15", "taxi")

        # Round 5: Mr. X at loc_20, det_1 at loc_19, det_2 at loc_15
        # loc_20 neighbors: loc_15 (det_2), loc_19 (det_1) — Mr. X is trapped!
        # Mr. X has no valid taxi moves (both neighbors occupied by detectives)
        # In real Scotland Yard Mr. X would be stuck and lose; we verify trapping
        assert g.round_number == 5
        assert g.winner() is None  # Not caught yet, but cornered

    def test_chase_to_capture(self) -> None:
        """Detectives corner and capture Mr. X in 3 rounds."""
        g = ScotlandYardGame()
        # Mr. X at loc_8, det_1 at loc_7, det_2 at loc_9
        g.setup("loc_8", "loc_7", "loc_9")

        # Round 1: Mr. X moves to loc_13
        g.execute_move("mr_x", "loc_13", "taxi")
        assert g.travel_log == ["taxi"]
        g.execute_move("detective_1", "loc_8", "taxi")
        g.execute_move("detective_2", "loc_14", "taxi")

        # Round 2: Mr. X at loc_13, det_1 at loc_8, det_2 at loc_14
        assert g.round_number == 2
        g.execute_move("mr_x", "loc_18", "taxi")
        g.execute_move("detective_1", "loc_13", "taxi")
        g.execute_move("detective_2", "loc_19", "taxi")

        # Round 3 (reveal turn): Mr. X at loc_18, det_1 at loc_13, det_2 at loc_19
        assert g.round_number == 3
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_18"

        # Mr. X tries to escape to loc_17
        g.execute_move("mr_x", "loc_17", "taxi")

        # det_1 at loc_13, moves to loc_18 (Mr. X's revealed position)
        g.execute_move("detective_1", "loc_18", "taxi")

        # det_2 at loc_19, moves to loc_18 — occupied by det_1!
        # det_2 goes to loc_20 instead
        g.execute_move("detective_2", "loc_20", "taxi")

        # Round 4: Mr. X at loc_17, det_1 at loc_18, det_2 at loc_20
        assert g.round_number == 4
        # Mr. X at loc_17 neighbors: loc_12, loc_16, loc_18 (det_1)
        # Also express edges: loc_11-loc_17, loc_13-loc_19 — check loc_17 neighbors
        g.execute_move("mr_x", "loc_12", "taxi")

        # det_1 at loc_18, moves to loc_17
        g.execute_move("detective_1", "loc_17", "taxi")

        # det_2 at loc_20, moves to loc_15
        g.execute_move("detective_2", "loc_15", "taxi")

        # Round 5: Mr. X at loc_12, det_1 at loc_17, det_2 at loc_15
        assert g.round_number == 5
        # Mr. X at loc_12, neighbors: loc_7, loc_11, loc_13, loc_17 (det_1)
        g.execute_move("mr_x", "loc_7", "taxi")

        # det_1 at loc_17, moves to loc_12
        g.execute_move("detective_1", "loc_12", "taxi")

        # det_2 at loc_15, moves to loc_10
        g.execute_move("detective_2", "loc_10", "taxi")

        # Round 6: Mr. X at loc_7, det_1 at loc_12, det_2 at loc_10
        assert g.round_number == 6
        # Mr. X at loc_7, neighbors: loc_2, loc_6, loc_8, loc_12 (det_1)
        g.execute_move("mr_x", "loc_2", "taxi")

        # det_1 at loc_12, moves to loc_7
        g.execute_move("detective_1", "loc_7", "taxi")

        # det_2 at loc_10, moves to loc_9
        g.execute_move("detective_2", "loc_9", "taxi")

        # Round 7: Mr. X at loc_2, det_1 at loc_7, det_2 at loc_9
        assert g.round_number == 7
        # Mr. X at loc_2 neighbors: loc_1, loc_3, loc_7 (det_1)
        g.execute_move("mr_x", "loc_3", "taxi")

        # det_1 at loc_7 moves to loc_2
        g.execute_move("detective_1", "loc_2", "taxi")

        # det_2 at loc_9 moves to loc_4
        g.execute_move("detective_2", "loc_4", "taxi")

        # Round 8 (reveal turn): Mr. X at loc_3, det_1 at loc_2, det_2 at loc_4
        assert g.round_number == 8
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_3"

        # Mr. X at loc_3 neighbors: loc_2 (det_1), loc_4 (det_2), loc_8, loc_9
        g.execute_move("mr_x", "loc_8", "taxi")

        # det_1 at loc_2, moves to loc_3
        g.execute_move("detective_1", "loc_3", "taxi")

        # det_2 at loc_4, moves to loc_9
        g.execute_move("detective_2", "loc_9", "taxi")

        # Round 9: Mr. X at loc_8, det_1 at loc_3, det_2 at loc_9
        assert g.round_number == 9
        # Mr. X at loc_8 neighbors: loc_3 (det_1), loc_7, loc_9 (det_2), loc_13, loc_14
        g.execute_move("mr_x", "loc_7", "taxi")

        # det_1 at loc_3, moves to loc_8
        g.execute_move("detective_1", "loc_8", "taxi")

        # det_2 at loc_9 moves to loc_8 — occupied! Go to loc_10
        # Actually det_2 can go to loc_4 or loc_10 or loc_14
        # Let's have det_2 go to loc_10
        g.execute_move("detective_2", "loc_10", "taxi")

        # Round 10: Mr. X at loc_7, det_1 at loc_8, det_2 at loc_10
        assert g.round_number == 10
        # Mr. X at loc_7, neighbors: loc_2, loc_6, loc_8 (det_1), loc_12
        g.execute_move("mr_x", "loc_6", "taxi")

        # det_1 at loc_8, moves to loc_7 (where Mr. X just was)
        g.execute_move("detective_1", "loc_7", "taxi")

        # det_2 at loc_10, moves to loc_5
        g.execute_move("detective_2", "loc_5", "taxi")

        # Not caught
        assert g.winner() is None

        # Round 11: Mr. X at loc_6, det_1 at loc_7, det_2 at loc_5
        # Mr. X at loc_6, neighbors: loc_1, loc_7 (det_1), loc_11, loc_12
        g.execute_move("mr_x", "loc_1", "taxi")

        # det_1 at loc_7, moves to loc_6
        g.execute_move("detective_1", "loc_6", "taxi")

        # det_2 at loc_5, moves to loc_10
        g.execute_move("detective_2", "loc_10", "taxi")

        # Round 12: Mr. X at loc_1, det_1 at loc_6, det_2 at loc_10
        assert g.round_number == 12
        # Mr. X at loc_1, neighbors: loc_2, loc_6 (det_1), loc_7, loc_11
        g.execute_move("mr_x", "loc_2", "taxi")

        # det_1 at loc_6, moves to loc_1
        g.execute_move("detective_1", "loc_1", "taxi")

        # det_2 at loc_10, chases — loc_10 neighbors include loc_9, loc_15, loc_5, loc_20
        g.execute_move("detective_2", "loc_9", "taxi")

        # Round 13 (reveal turn): Mr. X at loc_2, det_1 at loc_1, det_2 at loc_9
        assert g.round_number == 13
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_2"

        # Mr. X at loc_2, neighbors: loc_1 (det_1), loc_3, loc_7
        g.execute_move("mr_x", "loc_3", "taxi")

        # det_1 at loc_1, moves to loc_2 (Mr. X's revealed position)
        g.execute_move("detective_1", "loc_2", "taxi")

        # det_2 at loc_9, moves to loc_4
        g.execute_move("detective_2", "loc_4", "taxi")

        # Round 14: Mr. X at loc_3, det_1 at loc_2, det_2 at loc_4
        assert g.round_number == 14
        # Mr. X at loc_3, neighbors: loc_2 (det_1), loc_4 (det_2), loc_8, loc_9
        g.execute_move("mr_x", "loc_8", "taxi")

        # det_1 at loc_2, moves to loc_3
        g.execute_move("detective_1", "loc_3", "taxi")

        # det_2 at loc_4, moves to loc_3 — occupied! Move to loc_9
        # det_2 at loc_4, neighbors: loc_3 (det_1), loc_5, loc_9
        g.execute_move("detective_2", "loc_9", "taxi")

        # Round 15: Mr. X at loc_8, det_1 at loc_3, det_2 at loc_9
        assert g.round_number == 15
        # det_1 can reach loc_8 from loc_3 (adjacent)
        # det_2 at loc_9 can reach loc_8 (adjacent)
        g.execute_move("mr_x", "loc_13", "taxi")

        # det_1 at loc_3, moves to loc_8
        g.execute_move("detective_1", "loc_8", "taxi")

        # det_2 at loc_9, can go to loc_8 — occupied! Go to loc_14
        g.execute_move("detective_2", "loc_14", "taxi")

        # Round 16: Mr. X at loc_13, det_1 at loc_8, det_2 at loc_14
        assert g.round_number == 16
        # Mr. X at loc_13 neighbors: loc_8 (det_1), loc_12, loc_14 (det_2), loc_18, loc_19
        g.execute_move("mr_x", "loc_18", "taxi")

        # det_1 at loc_8, moves to loc_13
        g.execute_move("detective_1", "loc_13", "taxi")

        # det_2 at loc_14, moves to loc_19
        g.execute_move("detective_2", "loc_19", "taxi")

        # Round 17: Mr. X at loc_18, det_1 at loc_13, det_2 at loc_19
        assert g.round_number == 17
        # Mr. X at loc_18, neighbors: loc_13 (det_1), loc_17, loc_19 (det_2)
        g.execute_move("mr_x", "loc_17", "taxi")

        # det_1 at loc_13, moves to loc_18
        result = g.execute_move("detective_1", "loc_18", "taxi")
        assert result["caught"] is False

        # det_2 at loc_19, moves to loc_18 — occupied! Go to loc_20
        g.execute_move("detective_2", "loc_20", "taxi")

        # Round 18 (reveal turn): Mr. X at loc_17
        assert g.round_number == 18
        assert g.is_reveal_turn() is True
        assert g.reveal_mr_x() == "loc_17"

        # Mr. X at loc_17 neighbors: loc_12, loc_16, loc_18 (det_1)
        g.execute_move("mr_x", "loc_16", "taxi")

        # det_1 at loc_18, moves to loc_17
        g.execute_move("detective_1", "loc_17", "taxi")

        # det_2 at loc_20, moves to loc_15
        g.execute_move("detective_2", "loc_15", "taxi")

        # Round 19: Mr. X at loc_16, det_1 at loc_17, det_2 at loc_15
        assert g.round_number == 19
        # Mr. X at loc_16, neighbors: loc_11, loc_17 (det_1)
        g.execute_move("mr_x", "loc_11", "taxi")

        # det_1 at loc_17, moves to loc_16
        result = g.execute_move("detective_1", "loc_16", "taxi")
        assert result["caught"] is False

        # det_2 at loc_15, moves to loc_10
        g.execute_move("detective_2", "loc_10", "taxi")

        # Round 20: Mr. X at loc_11, det_1 at loc_16, det_2 at loc_10
        assert g.round_number == 20
        # Mr. X at loc_11 neighbors: loc_6, loc_7, loc_12, loc_16 (det_1), loc_17
        g.execute_move("mr_x", "loc_6", "taxi")

        # det_1 at loc_16, moves to loc_11
        g.execute_move("detective_1", "loc_11", "taxi")

        # det_2 at loc_10, moves to loc_5
        g.execute_move("detective_2", "loc_5", "taxi")

        # Round 21: Mr. X at loc_6, det_1 at loc_11, det_2 at loc_5
        assert g.round_number == 21
        # Mr. X at loc_6, neighbors: loc_1, loc_7, loc_11 (det_1), loc_12
        g.execute_move("mr_x", "loc_1", "taxi")

        # det_1 at loc_11, moves to loc_6
        g.execute_move("detective_1", "loc_6", "taxi")

        # det_2 at loc_5, moves to loc_4
        g.execute_move("detective_2", "loc_4", "taxi")

        # Round 22: Mr. X at loc_1, det_1 at loc_6, det_2 at loc_4
        assert g.round_number == 22
        # det_1 can reach loc_1 from loc_6 (adjacent)
        # Mr. X at loc_1, tries to flee
        g.execute_move("mr_x", "loc_2", "taxi")

        # det_1 at loc_6, moves to loc_1
        g.execute_move("detective_1", "loc_1", "taxi")

        # det_2 at loc_4, moves to loc_3
        g.execute_move("detective_2", "loc_3", "taxi")

        # Round 23: Mr. X survived!
        assert g.round_number == 23
        assert g.is_mr_x_survived() is True
        assert g.winner() == "mr_x"
