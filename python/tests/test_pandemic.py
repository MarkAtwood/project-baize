"""Tests for Pandemic: cooperative network disease control.

Simplified Pandemic with 2 players (medic, scientist) on a 12-city graph.
Disease cubes in 2 colors (blue, yellow) spread via infection cards.
Players cooperate: move between cities, treat disease, discover cures.

Win: cure both diseases. Lose: 8 outbreaks, player deck empty, or cube
supply exhausted.

The board is a graph zone with 12 cities connected by flight routes.
Disease state is tracked per-city via a dict (city -> {color: count}).
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
    CounterZone,
    GameSession,
    GraphZone,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "pandemic.json"

CITIES = [
    "atlanta", "chicago", "montreal", "new_york",
    "washington", "miami", "mexico_city", "bogota",
    "lima", "sao_paulo", "buenos_aires", "santiago",
]

CITY_COLORS: dict[str, str] = {
    "atlanta": "blue", "chicago": "blue", "montreal": "blue",
    "new_york": "blue", "washington": "blue",
    "miami": "yellow", "mexico_city": "yellow", "bogota": "yellow",
    "lima": "yellow", "sao_paulo": "yellow", "buenos_aires": "yellow",
    "santiago": "yellow",
}

# Max disease cubes per color
CUBES_PER_COLOR = 24
MAX_OUTBREAKS = 8
OUTBREAK_THRESHOLD = 3  # 4th cube triggers outbreak

# Infection rate track: index -> cards drawn per infect phase
INFECTION_RATES = [2, 2, 2, 3, 3, 4, 4]


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# PandemicGame helper
# ---------------------------------------------------------------------------


class PandemicGame:
    """Pandemic game driver with disease/outbreak simulation.

    Disease state is tracked outside the graph zone (which holds only one
    occupant per node) using a per-city dict of {color: cube_count}.
    The graph zone tracks pawn positions.
    """

    def __init__(self, seed: int = 42) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.rng = random.Random(seed)

        # Disease cubes per city: {city: {color: count}}
        self.disease: dict[str, dict[str, int]] = {
            city: {"blue": 0, "yellow": 0} for city in CITIES
        }

        # Cube supply per color
        self.cube_supply: dict[str, int] = {
            "blue": CUBES_PER_COLOR,
            "yellow": CUBES_PER_COLOR,
        }

        # Outbreak tracking
        self.outbreaks = 0

        # Cured diseases
        self.cured: set[str] = set()

        # Player positions and pawns
        self.positions: dict[str, str] = {
            "medic": "atlanta",
            "scientist": "atlanta",
        }
        self.pawns: dict[str, ComponentId] = {}
        for player in ["medic", "scientist"]:
            cid = self.session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"pawn-{player}",
                    component_type="pawn",
                    owner=player,
                )
            )
            self.pawns[player] = cid

        # Place pawns on atlanta
        self.board.graph_set("atlanta", self.pawns["medic"])

        # Player hands: {player: list of city names}
        self.hands: dict[str, list[str]] = {"medic": [], "scientist": []}

        # Decks
        self.player_deck: list[str] = []
        self.infection_deck: list[str] = []
        self.infection_discard: list[str] = []

        self.finished = False
        self.won = False
        self.loss_reason: str | None = None

    @property
    def board(self) -> GraphZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GraphZone)
        return zone

    @property
    def outbreak_counter(self) -> CounterZone:
        zone = self.session.runtime.zones["outbreak_counter"]
        assert isinstance(zone, CounterZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def setup_decks(self) -> None:
        """Build and shuffle infection + player decks."""
        self.infection_deck = list(CITIES)
        self.rng.shuffle(self.infection_deck)

        # Player deck: city cards (no epidemics for simplicity in base setup)
        self.player_deck = list(CITIES)
        self.rng.shuffle(self.player_deck)

    def setup_initial_infections(self) -> None:
        """Standard setup: infect 3 cities at 3 cubes, 3 at 2, 3 at 1."""
        for cubes in [3, 2, 1]:
            for _ in range(3):
                if self.infection_deck:
                    city = self.infection_deck.pop()
                    self.infection_discard.append(city)
                    color = CITY_COLORS[city]
                    self._add_cubes(city, color, cubes)

    # -- Actions --------------------------------------------------------------

    def move(self, player: str, destination: str) -> bool:
        """Move player to an adjacent city. Returns True if legal."""
        if self.finished:
            return False
        current = self.positions[player]
        neighbors = self.board.graph_neighbors(current)
        if destination not in neighbors:
            return False
        self.positions[player] = destination
        return True

    def direct_flight(self, player: str, destination: str) -> bool:
        """Discard matching city card to fly to destination."""
        if self.finished:
            return False
        if destination not in self.hands[player]:
            return False
        self.hands[player].remove(destination)
        self.positions[player] = destination
        return True

    def treat(self, player: str, color: str) -> bool:
        """Remove 1 disease cube of color from player's current city.

        If disease is cured, removes all cubes of that color instead.
        """
        if self.finished:
            return False
        city = self.positions[player]
        if self.disease[city][color] <= 0:
            return False

        if color in self.cured:
            # Cured: remove all cubes of this color
            removed = self.disease[city][color]
            self.disease[city][color] = 0
            self.cube_supply[color] += removed
        else:
            self.disease[city][color] -= 1
            self.cube_supply[color] += 1
        return True

    def discover_cure(self, player: str, color: str) -> bool:
        """Discard 5 same-color city cards to cure that disease.

        Simplified: player must be in atlanta (research station).
        """
        if self.finished:
            return False
        if color in self.cured:
            return False
        if self.positions[player] != "atlanta":
            return False

        matching = [c for c in self.hands[player] if CITY_COLORS.get(c) == color]
        if len(matching) < 5:
            return False

        # Discard 5
        for card in matching[:5]:
            self.hands[player].remove(card)
        self.cured.add(color)

        # Check win
        if self.cured == {"blue", "yellow"}:
            self.finished = True
            self.won = True
        return True

    # -- Infection logic -------------------------------------------------------

    def _add_cubes(self, city: str, color: str, count: int) -> None:
        """Add disease cubes, triggering outbreaks as needed."""
        for _ in range(count):
            if self.finished:
                return
            if self.cube_supply[color] <= 0:
                self.finished = True
                self.loss_reason = "disease_overrun"
                return
            current = self.disease[city][color]
            if current >= OUTBREAK_THRESHOLD + 1:
                # Already at max from chain, skip
                continue
            if current == OUTBREAK_THRESHOLD:
                # 4th cube: outbreak
                self._outbreak(city, color, set())
            else:
                self.disease[city][color] += 1
                self.cube_supply[color] -= 1

    def _outbreak(self, city: str, color: str, already_outbroken: set[str]) -> None:
        """Resolve an outbreak: increment counter, spread to neighbors."""
        if city in already_outbroken:
            return
        already_outbroken.add(city)
        self.outbreaks += 1
        self.outbreak_counter.value = self.outbreaks

        if self.outbreaks >= MAX_OUTBREAKS:
            self.finished = True
            self.loss_reason = "too_many_outbreaks"
            return

        # Spread 1 cube of same color to each neighbor
        neighbors = self.board.graph_neighbors(city)
        for neighbor in neighbors:
            if self.finished:
                return
            if self.cube_supply[color] <= 0:
                self.finished = True
                self.loss_reason = "disease_overrun"
                return
            current = self.disease[neighbor][color]
            if current >= OUTBREAK_THRESHOLD + 1:
                continue
            if current == OUTBREAK_THRESHOLD:
                self._outbreak(neighbor, color, already_outbroken)
            else:
                self.disease[neighbor][color] += 1
                self.cube_supply[color] -= 1

    def infect_city(self, city: str) -> None:
        """Infect a city with 1 cube of its native color."""
        color = CITY_COLORS[city]
        self._add_cubes(city, color, 1)

    def draw_infection_cards(self, count: int) -> list[str]:
        """Draw infection cards and infect named cities."""
        drawn: list[str] = []
        for _ in range(count):
            if self.finished:
                break
            if not self.infection_deck:
                break
            city = self.infection_deck.pop()
            self.infection_discard.append(city)
            drawn.append(city)
            self.infect_city(city)
        return drawn

    def draw_player_cards(self, player: str, count: int = 2) -> list[str]:
        """Draw cards from player deck into player's hand."""
        drawn: list[str] = []
        for _ in range(count):
            if not self.player_deck:
                self.finished = True
                self.loss_reason = "out_of_time"
                return drawn
            card = self.player_deck.pop()
            self.hands[player].append(card)
            drawn.append(card)
        return drawn

    def total_cubes_on_board(self) -> int:
        """Total disease cubes placed on all cities."""
        return sum(
            self.disease[city][color]
            for city in CITIES
            for color in ["blue", "yellow"]
        )

    def cubes_on_city(self, city: str) -> dict[str, int]:
        """Disease cubes on a city by color."""
        return dict(self.disease[city])

    def end_turn(self) -> None:
        """Advance to the next player's turn."""
        self.session.advance_turn()


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Pandemic"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["medic", "scientist"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_graph_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].zone_type == "graph"
        assert defn.zones["board"].nodes is not None
        assert len(defn.zones["board"].nodes) == 12

    def test_twelve_cities(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].nodes == CITIES

    def test_edges_defined(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].edges is not None
        assert len(defn.zones["board"].edges) == 18

    def test_node_properties(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].node_properties is not None
        assert defn.zones["board"].node_properties["atlanta"]["color"] == "blue"
        assert defn.zones["board"].node_properties["bogota"]["color"] == "yellow"

    def test_phases(self) -> None:
        defn = _load_game()
        assert defn.phases is not None
        assert [p.name for p in defn.phases] == ["actions", "draw", "infect"]

    def test_end_conditions(self) -> None:
        defn = _load_game()
        names = [ec.name for ec in defn.end_conditions]
        assert "all_diseases_cured" in names
        assert "too_many_outbreaks" in names
        assert "out_of_time" in names
        assert "disease_overrun" in names

    def test_cooperative_win(self) -> None:
        """Win condition has no specific player — both win together."""
        defn = _load_game()
        win = [ec for ec in defn.end_conditions if ec.result == "win"][0]
        assert win.player is None

    def test_authority(self) -> None:
        defn = _load_game()
        assert "shuffle(player_deck)" in defn.authority.server_only
        assert "move(pawn, adjacent_city)" in defn.authority.client_verifiable

    def test_session_creates_graph(self) -> None:
        """GameSession creates a GraphZone for the board."""
        defn = _load_game()
        session = GameSession(defn)
        board = session.runtime.zones["board"]
        assert isinstance(board, GraphZone)
        assert len(board.node_names) == 12

    def test_session_creates_counters(self) -> None:
        """GameSession creates counter zones for outbreak and infection rate."""
        defn = _load_game()
        session = GameSession(defn)
        assert isinstance(session.runtime.zones["outbreak_counter"], CounterZone)
        assert isinstance(session.runtime.zones["infection_rate_counter"], CounterZone)


# ---------------------------------------------------------------------------
# Tests: graph connectivity
# ---------------------------------------------------------------------------


class TestGraphConnectivity:
    def test_atlanta_neighbors(self) -> None:
        game = PandemicGame()
        neighbors = game.board.graph_neighbors("atlanta")
        assert sorted(neighbors) == ["chicago", "miami", "washington"]

    def test_bogota_neighbors(self) -> None:
        game = PandemicGame()
        neighbors = game.board.graph_neighbors("bogota")
        assert sorted(neighbors) == [
            "buenos_aires", "lima", "mexico_city", "miami", "sao_paulo",
        ]

    def test_santiago_neighbors(self) -> None:
        """Santiago has only one connection (lima)."""
        game = PandemicGame()
        assert game.board.graph_neighbors("santiago") == ["lima"]

    def test_symmetry(self) -> None:
        """All edges are bidirectional."""
        game = PandemicGame()
        for city in CITIES:
            for neighbor in game.board.graph_neighbors(city):
                assert city in game.board.graph_neighbors(neighbor), (
                    f"{city} -> {neighbor} but not {neighbor} -> {city}"
                )


# ---------------------------------------------------------------------------
# Tests: player movement
# ---------------------------------------------------------------------------


class TestMovement:
    def test_move_to_adjacent_city(self) -> None:
        game = PandemicGame()
        assert game.positions["medic"] == "atlanta"
        assert game.move("medic", "chicago")
        assert game.positions["medic"] == "chicago"

    def test_move_to_non_adjacent_fails(self) -> None:
        game = PandemicGame()
        assert not game.move("medic", "santiago")
        assert game.positions["medic"] == "atlanta"

    def test_move_chain(self) -> None:
        """Move through multiple connected cities."""
        game = PandemicGame()
        assert game.move("medic", "miami")
        assert game.move("medic", "bogota")
        assert game.move("medic", "lima")
        assert game.positions["medic"] == "lima"

    def test_both_players_move_independently(self) -> None:
        game = PandemicGame()
        game.move("medic", "chicago")
        game.move("scientist", "washington")
        assert game.positions["medic"] == "chicago"
        assert game.positions["scientist"] == "washington"

    def test_direct_flight(self) -> None:
        """Discard a city card to fly directly to that city."""
        game = PandemicGame()
        game.hands["medic"] = ["santiago", "bogota"]
        assert game.direct_flight("medic", "santiago")
        assert game.positions["medic"] == "santiago"
        assert "santiago" not in game.hands["medic"]

    def test_direct_flight_without_card_fails(self) -> None:
        game = PandemicGame()
        assert not game.direct_flight("medic", "santiago")
        assert game.positions["medic"] == "atlanta"


# ---------------------------------------------------------------------------
# Tests: treat action
# ---------------------------------------------------------------------------


class TestTreat:
    def test_treat_removes_one_cube(self) -> None:
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 2
        game.cube_supply["blue"] = CUBES_PER_COLOR - 2
        assert game.treat("medic", "blue")
        assert game.disease["atlanta"]["blue"] == 1
        assert game.cube_supply["blue"] == CUBES_PER_COLOR - 1

    def test_treat_empty_city_fails(self) -> None:
        game = PandemicGame()
        assert not game.treat("medic", "blue")

    def test_treat_cured_removes_all(self) -> None:
        """When disease is cured, treat removes all cubes of that color."""
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 3
        game.cured.add("blue")
        assert game.treat("medic", "blue")
        assert game.disease["atlanta"]["blue"] == 0
        assert game.cube_supply["blue"] == CUBES_PER_COLOR

    def test_treat_returns_cubes_to_supply(self) -> None:
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 1
        game.cube_supply["blue"] = CUBES_PER_COLOR - 1
        game.treat("medic", "blue")
        assert game.cube_supply["blue"] == CUBES_PER_COLOR

    def test_treat_at_remote_city(self) -> None:
        """Treat works at whatever city the player is in."""
        game = PandemicGame()
        game.move("medic", "miami")
        game.disease["miami"]["yellow"] = 2
        game.cube_supply["yellow"] = CUBES_PER_COLOR - 2
        assert game.treat("medic", "yellow")
        assert game.disease["miami"]["yellow"] == 1


# ---------------------------------------------------------------------------
# Tests: infection
# ---------------------------------------------------------------------------


class TestInfection:
    def test_infect_adds_cube(self) -> None:
        game = PandemicGame()
        game.infect_city("atlanta")
        assert game.disease["atlanta"]["blue"] == 1

    def test_infect_uses_city_color(self) -> None:
        game = PandemicGame()
        game.infect_city("miami")
        assert game.disease["miami"]["yellow"] == 1
        assert game.disease["miami"]["blue"] == 0

    def test_infect_accumulates(self) -> None:
        game = PandemicGame()
        game.infect_city("atlanta")
        game.infect_city("atlanta")
        game.infect_city("atlanta")
        assert game.disease["atlanta"]["blue"] == 3

    def test_infect_reduces_supply(self) -> None:
        game = PandemicGame()
        game.infect_city("atlanta")
        assert game.cube_supply["blue"] == CUBES_PER_COLOR - 1

    def test_draw_infection_cards(self) -> None:
        game = PandemicGame()
        game.setup_decks()
        drawn = game.draw_infection_cards(2)
        assert len(drawn) == 2
        for city in drawn:
            assert city in CITIES
            color = CITY_COLORS[city]
            assert game.disease[city][color] >= 1

    def test_initial_setup_infects_nine_cities(self) -> None:
        """Standard setup infects 9 cities (3 at 3, 3 at 2, 3 at 1)."""
        game = PandemicGame()
        game.setup_decks()
        game.setup_initial_infections()
        total = game.total_cubes_on_board()
        # 3*3 + 3*2 + 3*1 = 9+6+3 = 18
        assert total == 18


# ---------------------------------------------------------------------------
# Tests: outbreaks
# ---------------------------------------------------------------------------


class TestOutbreaks:
    def test_fourth_cube_triggers_outbreak(self) -> None:
        """Placing a 4th cube on a city triggers an outbreak."""
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 3
        game.infect_city("atlanta")
        assert game.outbreaks == 1
        # Atlanta stays at 3 (outbreak instead of 4th cube)
        assert game.disease["atlanta"]["blue"] == 3

    def test_outbreak_spreads_to_neighbors(self) -> None:
        """Outbreak adds 1 cube of same color to each adjacent city."""
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 3
        game.infect_city("atlanta")  # outbreak!
        # Atlanta's neighbors: chicago, washington, miami
        assert game.disease["chicago"]["blue"] >= 1
        assert game.disease["washington"]["blue"] >= 1
        assert game.disease["miami"]["blue"] >= 1

    def test_chain_outbreak(self) -> None:
        """Outbreak spreading to a city at 3 cubes causes chain outbreak."""
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 3
        game.disease["chicago"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 6
        game.infect_city("atlanta")
        # Atlanta outbreaks -> spreads to chicago (at 3) -> chain outbreak
        assert game.outbreaks >= 2

    def test_chain_outbreak_no_infinite_loop(self) -> None:
        """Each city outbreaks at most once per chain (no infinite loop)."""
        game = PandemicGame()
        # Set up a cycle: atlanta-chicago-montreal all at 3
        game.disease["atlanta"]["blue"] = 3
        game.disease["chicago"]["blue"] = 3
        game.disease["montreal"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 9
        game.infect_city("atlanta")
        # Should outbreak at most once each, not loop forever
        assert game.outbreaks <= 3

    def test_eight_outbreaks_loses(self) -> None:
        """Game is lost when outbreak counter reaches 8."""
        game = PandemicGame()
        game.outbreaks = 7
        game.outbreak_counter.value = 7
        game.disease["atlanta"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 3
        game.infect_city("atlanta")  # 8th outbreak
        assert game.finished
        assert game.loss_reason == "too_many_outbreaks"

    def test_outbreak_counter_tracks(self) -> None:
        """Outbreak counter zone value matches outbreak count."""
        game = PandemicGame()
        game.disease["atlanta"]["blue"] = 3
        game.cube_supply["blue"] = CUBES_PER_COLOR - 3
        game.infect_city("atlanta")
        assert game.outbreak_counter.value == 1


# ---------------------------------------------------------------------------
# Tests: loss conditions
# ---------------------------------------------------------------------------


class TestLossConditions:
    def test_player_deck_empty_loses(self) -> None:
        """Game lost when player deck runs out during draw."""
        game = PandemicGame()
        game.player_deck = ["atlanta"]  # only 1 card
        game.draw_player_cards("medic", 2)  # tries to draw 2
        assert game.finished
        assert game.loss_reason == "out_of_time"

    def test_cube_supply_exhausted_loses(self) -> None:
        """Game lost when cube supply runs out."""
        game = PandemicGame()
        game.cube_supply["blue"] = 1
        game.disease["atlanta"]["blue"] = 0
        game.disease["chicago"]["blue"] = 0
        game.infect_city("atlanta")  # uses last blue cube
        assert game.cube_supply["blue"] == 0
        game.infect_city("chicago")  # no cubes left
        assert game.finished
        assert game.loss_reason == "disease_overrun"


# ---------------------------------------------------------------------------
# Tests: discover cure and win
# ---------------------------------------------------------------------------


class TestCure:
    def test_discover_cure(self) -> None:
        """Discard 5 same-color cards at atlanta to cure disease."""
        game = PandemicGame()
        game.hands["medic"] = [
            "atlanta", "chicago", "montreal", "new_york", "washington",
        ]
        assert game.discover_cure("medic", "blue")
        assert "blue" in game.cured
        assert len(game.hands["medic"]) == 0

    def test_discover_cure_needs_five_cards(self) -> None:
        game = PandemicGame()
        game.hands["medic"] = ["atlanta", "chicago", "montreal", "new_york"]
        assert not game.discover_cure("medic", "blue")

    def test_discover_cure_needs_atlanta(self) -> None:
        """Must be at atlanta (research station) to discover cure."""
        game = PandemicGame()
        game.move("medic", "miami")
        game.hands["medic"] = [
            "miami", "mexico_city", "bogota", "lima", "santiago",
        ]
        assert not game.discover_cure("medic", "yellow")

    def test_cannot_cure_twice(self) -> None:
        game = PandemicGame()
        game.cured.add("blue")
        game.hands["medic"] = [
            "atlanta", "chicago", "montreal", "new_york", "washington",
        ]
        assert not game.discover_cure("medic", "blue")

    def test_win_by_curing_both(self) -> None:
        """Game is won when both diseases are cured."""
        game = PandemicGame()
        game.hands["medic"] = [
            "atlanta", "chicago", "montreal", "new_york", "washington",
        ]
        game.discover_cure("medic", "blue")
        assert not game.finished

        game.hands["medic"] = [
            "miami", "mexico_city", "bogota", "lima", "santiago",
        ]
        game.discover_cure("medic", "yellow")
        assert game.finished
        assert game.won


# ---------------------------------------------------------------------------
# Tests: full turn flow
# ---------------------------------------------------------------------------


class TestTurnFlow:
    def test_turn_alternates(self) -> None:
        game = PandemicGame()
        assert game.current_player() == "medic"
        game.end_turn()
        assert game.current_player() == "scientist"
        game.end_turn()
        assert game.current_player() == "medic"

    def test_full_turn_sequence(self) -> None:
        """Execute a full turn: 4 actions, draw 2, infect 2."""
        game = PandemicGame()
        game.setup_decks()

        player = game.current_player()

        # Phase 1: actions (4)
        game.move(player, "chicago")
        game.move(player, "montreal")
        game.move(player, "new_york")
        game.move(player, "washington")
        assert game.positions[player] == "washington"

        # Phase 2: draw 2 player cards
        drawn = game.draw_player_cards(player, 2)
        assert len(drawn) == 2
        assert len(game.hands[player]) == 2

        # Phase 3: infect cities
        infected = game.draw_infection_cards(2)
        assert len(infected) == 2

        game.end_turn()
        assert game.current_player() == "scientist"

    def test_cannot_move_after_game_over(self) -> None:
        game = PandemicGame()
        game.finished = True
        assert not game.move("medic", "chicago")
