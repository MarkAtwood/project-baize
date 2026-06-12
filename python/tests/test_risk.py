"""Tests for Risk: territory control with dice combat on a graph map.

Simplified Risk with 12 territories in 3 continents, played by 2-3 players.
Territories are nodes in a graph zone; edges define adjacency for attacks
and fortification. Each turn has three phases: reinforce, attack, fortify.

Combat resolution: attacker rolls up to 3d6, defender rolls up to 2d6.
Dice are sorted descending and compared pairwise; loser of each pair
removes one army. Defender wins ties.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition, PlayerRange
from baize.runtime import (
    GraphZone,
    GameSession,
    runtime_zone_from_definition,
)

# ---------------------------------------------------------------------------
# Map data
# ---------------------------------------------------------------------------

CONTINENTS: dict[str, list[str]] = {
    "northlands": [
        "eastern_frontier",
        "northern_pass",
        "western_reach",
        "central_plains",
    ],
    "midlands": [
        "iron_coast",
        "silver_hills",
        "crimson_vale",
        "stormhold",
    ],
    "southlands": [
        "old_forest",
        "sunken_marsh",
        "dragon_peak",
        "ashen_waste",
    ],
}

CONTINENT_BONUS: dict[str, int] = {
    "northlands": 3,
    "midlands": 5,
    "southlands": 7,
}

ALL_TERRITORIES: list[str] = [
    "eastern_frontier",
    "northern_pass",
    "western_reach",
    "central_plains",
    "iron_coast",
    "silver_hills",
    "crimson_vale",
    "stormhold",
    "old_forest",
    "sunken_marsh",
    "dragon_peak",
    "ashen_waste",
]

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "risk.json"


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# RiskGame helper
# ---------------------------------------------------------------------------


class RiskGame:
    """Simplified Risk game driver for testing territory control and combat."""

    def __init__(self, players: list[str] | None = None) -> None:
        self.defn = _load_definition()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.players = players or ["Red", "Blue"]
        # Territory state: {territory_name: (owner, army_count)}
        self.territories: dict[str, tuple[str, int]] = {}
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
    # Territory management
    # -----------------------------------------------------------------------

    def set_territory(self, name: str, owner: str, armies: int) -> None:
        """Set ownership and army count for a territory."""
        assert name in ALL_TERRITORIES, f"Unknown territory: {name}"
        assert armies >= 1, f"Territory must have at least 1 army, got {armies}"
        self.territories[name] = (owner, armies)

    def owner_of(self, name: str) -> str | None:
        entry = self.territories.get(name)
        return entry[0] if entry else None

    def armies_at(self, name: str) -> int:
        entry = self.territories.get(name)
        return entry[1] if entry else 0

    def territories_owned_by(self, player: str) -> list[str]:
        return [t for t, (o, _) in self.territories.items() if o == player]

    def are_adjacent(self, a: str, b: str) -> bool:
        """Check if two territories are adjacent on the graph."""
        neighbors = self.graph.graph_neighbors(a)
        return b in neighbors

    # -----------------------------------------------------------------------
    # Reinforcement
    # -----------------------------------------------------------------------

    def reinforcement_count(self, player: str) -> int:
        """Calculate reinforcement armies for a player.

        Base: max(3, territories_owned // 3)
        Plus continent bonus for each fully controlled continent.
        """
        owned = self.territories_owned_by(player)
        base = max(3, len(owned) // 3)
        bonus = 0
        for continent, members in CONTINENTS.items():
            if all(self.owner_of(t) == player for t in members):
                bonus += CONTINENT_BONUS[continent]
        return base + bonus

    # -----------------------------------------------------------------------
    # Combat
    # -----------------------------------------------------------------------

    def attack_dice_count(self, territory: str) -> int:
        """Maximum attack dice from a territory: min(armies - 1, 3)."""
        return min(self.armies_at(territory) - 1, 3)

    def defend_dice_count(self, territory: str) -> int:
        """Maximum defend dice for a territory: min(armies, 2)."""
        return min(self.armies_at(territory), 2)

    def validate_attack(self, source: str, target: str, attacker: str) -> str | None:
        """Validate an attack. Returns error message or None if valid."""
        if source not in self.territories:
            return f"source territory {source} has no owner"
        if target not in self.territories:
            return f"target territory {target} has no owner"
        if self.owner_of(source) != attacker:
            return f"{source} not owned by {attacker}"
        if self.owner_of(target) == attacker:
            return f"cannot attack own territory {target}"
        if not self.are_adjacent(source, target):
            return f"{source} and {target} are not adjacent"
        if self.armies_at(source) < 2:
            return f"{source} needs at least 2 armies to attack"
        return None

    def resolve_combat(
        self,
        attacker_rolls: list[int],
        defender_rolls: list[int],
    ) -> tuple[int, int]:
        """Resolve combat by comparing sorted dice.

        Returns (attacker_losses, defender_losses).
        Dice are sorted descending and compared pairwise.
        Defender wins ties.
        """
        a_sorted = sorted(attacker_rolls, reverse=True)
        d_sorted = sorted(defender_rolls, reverse=True)
        attacker_losses = 0
        defender_losses = 0
        for a_die, d_die in zip(a_sorted, d_sorted):
            if a_die > d_die:
                defender_losses += 1
            else:
                attacker_losses += 1
        return attacker_losses, defender_losses

    def execute_attack(
        self,
        source: str,
        target: str,
        attacker: str,
        attacker_rolls: list[int],
        defender_rolls: list[int],
    ) -> dict[str, object]:
        """Execute an attack with provided dice rolls.

        Returns a dict describing the outcome:
          - attacker_losses, defender_losses: armies removed
          - conquered: whether the target was taken
          - armies_moved: how many armies moved into conquered territory
        """
        error = self.validate_attack(source, target, attacker)
        if error is not None:
            raise ValueError(error)

        a_losses, d_losses = self.resolve_combat(attacker_rolls, defender_rolls)

        src_owner, src_armies = self.territories[source]
        tgt_owner, tgt_armies = self.territories[target]

        src_armies -= a_losses
        tgt_armies -= d_losses

        conquered = tgt_armies <= 0
        armies_moved = 0

        if conquered:
            armies_moved = len(attacker_rolls)
            src_armies -= armies_moved
            self.territories[source] = (src_owner, max(1, src_armies))
            self.territories[target] = (attacker, armies_moved)
        else:
            self.territories[source] = (src_owner, src_armies)
            self.territories[target] = (tgt_owner, tgt_armies)

        return {
            "attacker_losses": a_losses,
            "defender_losses": d_losses,
            "conquered": conquered,
            "armies_moved": armies_moved,
        }

    # -----------------------------------------------------------------------
    # Fortify
    # -----------------------------------------------------------------------

    def validate_fortify(self, source: str, target: str, player: str, count: int) -> str | None:
        """Validate a fortify move. Returns error message or None if valid."""
        if self.owner_of(source) != player:
            return f"{source} not owned by {player}"
        if self.owner_of(target) != player:
            return f"{target} not owned by {player}"
        if not self.are_adjacent(source, target):
            return f"{source} and {target} are not adjacent"
        if self.armies_at(source) - count < 1:
            return f"must leave at least 1 army in {source}"
        if count < 1:
            return "must move at least 1 army"
        return None

    def fortify(self, source: str, target: str, player: str, count: int) -> None:
        """Move armies from source to target during fortify phase."""
        error = self.validate_fortify(source, target, player, count)
        if error is not None:
            raise ValueError(error)
        src_owner, src_armies = self.territories[source]
        tgt_owner, tgt_armies = self.territories[target]
        self.territories[source] = (src_owner, src_armies - count)
        self.territories[target] = (tgt_owner, tgt_armies + count)

    # -----------------------------------------------------------------------
    # Win condition
    # -----------------------------------------------------------------------

    def check_winner(self) -> str | None:
        """Return the winner if one player controls all territories, else None."""
        if len(self.territories) < len(ALL_TERRITORIES):
            return None
        owners = {o for o, _ in self.territories.values()}
        if len(owners) == 1:
            return owners.pop()
        return None


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and validates."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Risk"

    def test_player_range(self) -> None:
        defn = _load_definition()
        assert defn.game.players == PlayerRange(min=2, max=3)

    def test_twelve_territories(self) -> None:
        defn = _load_definition()
        zone = defn.zones["map"]
        assert zone.zone_type == "graph"
        assert zone.nodes is not None
        assert len(zone.nodes) == 12

    def test_three_phases(self) -> None:
        defn = _load_definition()
        assert len(defn.phases) == 3
        names = [p.name for p in defn.phases]
        assert names == ["reinforce", "attack", "fortify"]

    def test_authority_sections(self) -> None:
        defn = _load_definition()
        assert "roll_dice(attack)" in defn.authority.server_only
        assert "roll_dice(defend)" in defn.authority.server_only
        assert len(defn.authority.client_verifiable) == 3

    def test_win_condition(self) -> None:
        defn = _load_definition()
        assert len(defn.end_conditions) == 1
        assert defn.end_conditions[0].result == "win"
        assert defn.end_conditions[0].name == "world_conquest"

    def test_imperfect_information(self) -> None:
        defn = _load_definition()
        assert defn.game.information == "imperfect"


class TestGraphConnectivity:
    """Verify territory graph adjacency is correct."""

    def test_graph_has_twelve_nodes(self) -> None:
        g = RiskGame()
        assert len(g.graph.node_names) == 12

    def test_central_plains_is_hub(self) -> None:
        """central_plains connects to 5 territories (highest degree)."""
        g = RiskGame()
        neighbors = g.graph.graph_neighbors("central_plains")
        assert sorted(neighbors) == [
            "eastern_frontier",
            "iron_coast",
            "northern_pass",
            "silver_hills",
            "western_reach",
        ]

    def test_ashen_waste_is_leaf_like(self) -> None:
        """ashen_waste connects to 2 territories (low degree)."""
        g = RiskGame()
        neighbors = g.graph.graph_neighbors("ashen_waste")
        assert sorted(neighbors) == ["dragon_peak", "sunken_marsh"]

    def test_all_edges_are_bidirectional(self) -> None:
        """If A is neighbor of B, then B is neighbor of A."""
        g = RiskGame()
        for node in ALL_TERRITORIES:
            for neighbor in g.graph.graph_neighbors(node):
                assert node in g.graph.graph_neighbors(neighbor), (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_graph_is_connected(self) -> None:
        """All territories are reachable from any starting territory (BFS)."""
        g = RiskGame()
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
        """No territory is adjacent to itself."""
        g = RiskGame()
        for node in ALL_TERRITORIES:
            assert node not in g.graph.graph_neighbors(node)

    def test_continent_membership(self) -> None:
        """Every territory belongs to exactly one continent."""
        all_in_continents: list[str] = []
        for members in CONTINENTS.values():
            all_in_continents.extend(members)
        assert sorted(all_in_continents) == sorted(ALL_TERRITORIES)

    def test_inter_continent_edges_exist(self) -> None:
        """There are edges connecting different continents."""
        g = RiskGame()
        territory_to_continent = {}
        for continent, members in CONTINENTS.items():
            for t in members:
                territory_to_continent[t] = continent
        cross_edges = 0
        for node in ALL_TERRITORIES:
            for neighbor in g.graph.graph_neighbors(node):
                if territory_to_continent[node] != territory_to_continent[neighbor]:
                    cross_edges += 1
        # Each cross-continent edge is counted twice (once per direction)
        assert cross_edges >= 4, f"Expected cross-continent edges, found {cross_edges}"


class TestReinforcement:
    """Verify reinforcement calculation."""

    def test_minimum_three_armies(self) -> None:
        """Player with 1 territory still gets minimum 3 armies."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 1)
        assert g.reinforcement_count("Red") == 3

    def test_four_territories_gives_three(self) -> None:
        """4 territories // 3 = 1, but min is 3."""
        g = RiskGame()
        for t in CONTINENTS["northlands"]:
            g.set_territory(t, "Red", 1)
        # 4 // 3 = 1, min(3,1) = 3, plus continent bonus 3 = 6
        # But without continent bonus: just base
        # Red owns all northlands => bonus applies
        assert g.reinforcement_count("Red") == 3 + 3  # base 3 + northlands bonus

    def test_six_territories_base(self) -> None:
        """6 territories // 3 = 2, but min is 3."""
        g = RiskGame()
        territories = ALL_TERRITORIES[:6]
        for t in territories:
            g.set_territory(t, "Red", 1)
        # No full continent (northlands has 4, but only first 4 of ALL_TERRITORIES
        # are northlands, and we have 6 which includes 2 midlands)
        # All northlands owned + 2 midlands: northlands bonus applies
        base = max(3, 6 // 3)  # max(3, 2) = 3
        bonus = 3  # northlands
        assert g.reinforcement_count("Red") == base + bonus

    def test_twelve_territories_all_bonuses(self) -> None:
        """Player owning all 12 territories gets max reinforcement."""
        g = RiskGame()
        for t in ALL_TERRITORIES:
            g.set_territory(t, "Red", 1)
        base = max(3, 12 // 3)  # max(3, 4) = 4
        bonus = 3 + 5 + 7  # all continent bonuses
        assert g.reinforcement_count("Red") == base + bonus

    def test_continent_bonus_only_when_fully_controlled(self) -> None:
        """Partial continent ownership gives no bonus."""
        g = RiskGame()
        # Red owns 3 of 4 northlands territories
        g.set_territory("eastern_frontier", "Red", 1)
        g.set_territory("northern_pass", "Red", 1)
        g.set_territory("western_reach", "Red", 1)
        g.set_territory("central_plains", "Blue", 1)  # Blue owns 1
        # No continent bonus for Red
        base = max(3, 3 // 3)  # max(3, 1) = 3
        assert g.reinforcement_count("Red") == base

    def test_zero_territories_gives_three(self) -> None:
        """Edge case: player with no territories still gets 3 (base minimum)."""
        g = RiskGame()
        assert g.reinforcement_count("Red") == 3


class TestAttackValidation:
    """Verify attack validation rules."""

    def _setup_basic(self) -> RiskGame:
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 5)
        g.set_territory("northern_pass", "Blue", 3)
        g.set_territory("central_plains", "Red", 2)
        return g

    def test_valid_attack_adjacent(self) -> None:
        """Attack between adjacent territories owned by different players."""
        g = self._setup_basic()
        error = g.validate_attack("eastern_frontier", "northern_pass", "Red")
        assert error is None

    def test_attack_non_adjacent_rejected(self) -> None:
        """Attack between non-adjacent territories is rejected."""
        g = self._setup_basic()
        g.set_territory("ashen_waste", "Blue", 2)
        error = g.validate_attack("eastern_frontier", "ashen_waste", "Red")
        assert error is not None
        assert "not adjacent" in error

    def test_attack_own_territory_rejected(self) -> None:
        """Cannot attack a territory you own."""
        g = self._setup_basic()
        error = g.validate_attack("eastern_frontier", "central_plains", "Red")
        assert error is not None
        assert "own territory" in error

    def test_attack_with_one_army_rejected(self) -> None:
        """Need at least 2 armies to attack (must leave 1 behind)."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 1)
        g.set_territory("northern_pass", "Blue", 1)
        error = g.validate_attack("eastern_frontier", "northern_pass", "Red")
        assert error is not None
        assert "at least 2" in error

    def test_attack_not_owned_by_attacker(self) -> None:
        """Cannot attack from a territory you don't own."""
        g = self._setup_basic()
        error = g.validate_attack("northern_pass", "eastern_frontier", "Red")
        assert error is not None
        assert "not owned" in error


class TestCombat:
    """Verify dice combat resolution."""

    def test_attacker_wins_both_pairs(self) -> None:
        """Attacker rolls [6,5], defender rolls [4,3]: attacker wins both."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([6, 5], [4, 3])
        assert a_losses == 0
        assert d_losses == 2

    def test_defender_wins_both_pairs(self) -> None:
        """Attacker rolls [3,2], defender rolls [5,4]: defender wins both."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([3, 2], [5, 4])
        assert a_losses == 2
        assert d_losses == 0

    def test_split_result(self) -> None:
        """Attacker rolls [6,1], defender rolls [3,5]: split 1-1."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([6, 1], [3, 5])
        # Sorted: attacker [6,1] vs defender [5,3]
        # 6 > 5 => defender loses, 1 <= 3 => attacker loses
        assert a_losses == 1
        assert d_losses == 1

    def test_defender_wins_ties(self) -> None:
        """Equal dice: defender wins ties."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([4], [4])
        assert a_losses == 1
        assert d_losses == 0

    def test_three_vs_two(self) -> None:
        """Only min(3,2)=2 pairs compared when attacker has 3 dice."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([6, 5, 4], [3, 2])
        # Sorted: attacker [6,5,4] vs defender [3,2]
        # Compare 2 pairs: 6>3, 5>2
        assert a_losses == 0
        assert d_losses == 2

    def test_one_vs_one(self) -> None:
        """Single die each."""
        g = RiskGame()
        a_losses, d_losses = g.resolve_combat([5], [3])
        assert a_losses == 0
        assert d_losses == 1

    def test_dice_count_limits(self) -> None:
        """Attack dice capped at armies-1 (max 3), defend at armies (max 2)."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 10)
        g.set_territory("northern_pass", "Blue", 5)
        assert g.attack_dice_count("eastern_frontier") == 3  # min(9, 3)
        assert g.defend_dice_count("northern_pass") == 2  # min(5, 2)

    def test_attack_dice_with_two_armies(self) -> None:
        """Territory with 2 armies can roll 1 attack die."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 2)
        assert g.attack_dice_count("eastern_frontier") == 1


class TestConquest:
    """Verify territory conquest after combat."""

    def test_conquest_changes_ownership(self) -> None:
        """Defender reduced to 0 armies: attacker conquers territory."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 5)
        g.set_territory("northern_pass", "Blue", 1)
        # Attacker rolls [6,5,4], defender rolls [3]
        # 1 pair compared: 6>3 => defender loses 1, reaches 0
        result = g.execute_attack(
            "eastern_frontier", "northern_pass", "Red",
            attacker_rolls=[6, 5, 4],
            defender_rolls=[3],
        )
        assert result["conquered"] is True
        assert g.owner_of("northern_pass") == "Red"
        assert g.armies_at("northern_pass") == 3  # moved 3 (attack dice count)

    def test_failed_attack_no_conquest(self) -> None:
        """Defender survives: no ownership change."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 4)
        g.set_territory("northern_pass", "Blue", 3)
        # Attacker rolls [1,1,1], defender rolls [6,6]
        # 2 pairs: 1<=6, 1<=6 => attacker loses 2
        result = g.execute_attack(
            "eastern_frontier", "northern_pass", "Red",
            attacker_rolls=[1, 1, 1],
            defender_rolls=[6, 6],
        )
        assert result["conquered"] is False
        assert g.owner_of("northern_pass") == "Blue"
        assert g.armies_at("northern_pass") == 3  # unchanged
        assert g.armies_at("eastern_frontier") == 2  # lost 2

    def test_source_keeps_minimum_garrison(self) -> None:
        """After conquest, source territory keeps at least 1 army."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 4)
        g.set_territory("northern_pass", "Blue", 1)
        result = g.execute_attack(
            "eastern_frontier", "northern_pass", "Red",
            attacker_rolls=[6, 5, 4],
            defender_rolls=[1],
        )
        assert result["conquered"] is True
        assert g.armies_at("eastern_frontier") >= 1


class TestContinentBonus:
    """Verify continent bonus applies when all territories owned."""

    def test_northlands_bonus(self) -> None:
        """Controlling all northlands gives +3 bonus."""
        g = RiskGame()
        for t in CONTINENTS["northlands"]:
            g.set_territory(t, "Red", 1)
        # Also give Blue some territory so it's not just Red
        g.set_territory("iron_coast", "Blue", 1)
        base = max(3, 4 // 3)  # 3
        assert g.reinforcement_count("Red") == base + 3

    def test_midlands_bonus(self) -> None:
        """Controlling all midlands gives +5 bonus."""
        g = RiskGame()
        for t in CONTINENTS["midlands"]:
            g.set_territory(t, "Red", 1)
        base = max(3, 4 // 3)  # 3
        assert g.reinforcement_count("Red") == base + 5

    def test_southlands_bonus(self) -> None:
        """Controlling all southlands gives +7 bonus."""
        g = RiskGame()
        for t in CONTINENTS["southlands"]:
            g.set_territory(t, "Red", 1)
        base = max(3, 4 // 3)  # 3
        assert g.reinforcement_count("Red") == base + 7

    def test_multiple_continent_bonuses_stack(self) -> None:
        """Player controlling 2 continents gets both bonuses."""
        g = RiskGame()
        for t in CONTINENTS["northlands"] + CONTINENTS["southlands"]:
            g.set_territory(t, "Red", 1)
        base = max(3, 8 // 3)  # max(3, 2) = 3
        bonus = 3 + 7  # northlands + southlands
        assert g.reinforcement_count("Red") == base + bonus

    def test_no_bonus_partial_control(self) -> None:
        """Missing one territory in a continent means no bonus."""
        g = RiskGame()
        g.set_territory("old_forest", "Red", 1)
        g.set_territory("sunken_marsh", "Red", 1)
        g.set_territory("dragon_peak", "Red", 1)
        g.set_territory("ashen_waste", "Blue", 1)  # Blue spoils it
        base = max(3, 3 // 3)  # 3
        assert g.reinforcement_count("Red") == base  # no bonus


class TestFortify:
    """Verify fortification phase."""

    def test_valid_fortify(self) -> None:
        """Move armies between adjacent owned territories."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 5)
        g.set_territory("northern_pass", "Red", 2)
        g.fortify("eastern_frontier", "northern_pass", "Red", 3)
        assert g.armies_at("eastern_frontier") == 2
        assert g.armies_at("northern_pass") == 5

    def test_must_leave_one_army(self) -> None:
        """Cannot move all armies out of a territory."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 3)
        g.set_territory("northern_pass", "Red", 1)
        with pytest.raises(ValueError, match="at least 1"):
            g.fortify("eastern_frontier", "northern_pass", "Red", 3)

    def test_cannot_fortify_non_adjacent(self) -> None:
        """Cannot fortify to a non-adjacent territory."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 5)
        g.set_territory("ashen_waste", "Red", 1)
        with pytest.raises(ValueError, match="not adjacent"):
            g.fortify("eastern_frontier", "ashen_waste", "Red", 2)

    def test_cannot_fortify_enemy_territory(self) -> None:
        """Cannot fortify into an enemy territory."""
        g = RiskGame()
        g.set_territory("eastern_frontier", "Red", 5)
        g.set_territory("northern_pass", "Blue", 2)
        with pytest.raises(ValueError, match="not owned"):
            g.fortify("eastern_frontier", "northern_pass", "Red", 2)


class TestWinCondition:
    """Verify game-ending win condition."""

    def test_no_winner_with_split_map(self) -> None:
        """No winner when territories are split between players."""
        g = RiskGame()
        for t in CONTINENTS["northlands"]:
            g.set_territory(t, "Red", 1)
        for t in CONTINENTS["midlands"] + CONTINENTS["southlands"]:
            g.set_territory(t, "Blue", 1)
        assert g.check_winner() is None

    def test_winner_when_all_controlled(self) -> None:
        """Player controlling all 12 territories wins."""
        g = RiskGame()
        for t in ALL_TERRITORIES:
            g.set_territory(t, "Red", 1)
        assert g.check_winner() == "Red"

    def test_no_winner_with_unowned_territories(self) -> None:
        """No winner when some territories have no owner."""
        g = RiskGame()
        for t in ALL_TERRITORIES[:6]:
            g.set_territory(t, "Red", 1)
        assert g.check_winner() is None


class TestIntegration:
    """Full turn sequence: reinforce, attack, fortify."""

    def test_full_turn_sequence(self) -> None:
        """Execute a complete turn: reinforce, attack, fortify."""
        g = RiskGame()
        # Setup: Red owns northlands, Blue owns rest
        for t in CONTINENTS["northlands"]:
            g.set_territory(t, "Red", 3)
        for t in CONTINENTS["midlands"] + CONTINENTS["southlands"]:
            g.set_territory(t, "Blue", 2)

        # Phase 1: Reinforce
        reinforcements = g.reinforcement_count("Red")
        # 4 territories // 3 = 1, min 3, + northlands bonus 3 = 6
        assert reinforcements == 6
        # Place all reinforcements on central_plains (adjacent to midlands)
        current = g.armies_at("central_plains")
        g.territories["central_plains"] = ("Red", current + reinforcements)
        assert g.armies_at("central_plains") == 9

        # Phase 2: Attack iron_coast from central_plains
        error = g.validate_attack("central_plains", "iron_coast", "Red")
        assert error is None
        result = g.execute_attack(
            "central_plains", "iron_coast", "Red",
            attacker_rolls=[6, 5, 4],
            defender_rolls=[3, 2],
        )
        assert result["conquered"] is True
        assert g.owner_of("iron_coast") == "Red"

        # Phase 3: Fortify — move armies from eastern_frontier to central_plains
        g.fortify("eastern_frontier", "central_plains", "Red", 2)
        assert g.armies_at("eastern_frontier") == 1
        assert g.armies_at("central_plains") >= 1

    def test_chain_of_conquests(self) -> None:
        """Red conquers multiple territories in sequence."""
        g = RiskGame()
        # Red has strong position in northlands
        g.set_territory("central_plains", "Red", 20)
        g.set_territory("eastern_frontier", "Red", 1)
        g.set_territory("northern_pass", "Red", 1)
        g.set_territory("western_reach", "Red", 1)
        # Blue holds everything else with 1 army each
        for t in CONTINENTS["midlands"] + CONTINENTS["southlands"]:
            g.set_territory(t, "Blue", 1)

        # Attack iron_coast
        g.execute_attack(
            "central_plains", "iron_coast", "Red",
            attacker_rolls=[6, 6, 6], defender_rolls=[1],
        )
        assert g.owner_of("iron_coast") == "Red"

        # Attack silver_hills from iron_coast (if enough armies)
        # iron_coast got 3 armies from conquest
        if g.armies_at("iron_coast") >= 2:
            g.execute_attack(
                "iron_coast", "silver_hills", "Red",
                attacker_rolls=[6], defender_rolls=[1],
            )
            assert g.owner_of("silver_hills") == "Red"
