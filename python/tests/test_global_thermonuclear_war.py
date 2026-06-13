"""Tests for Global Thermonuclear War: definition-level validation.

Global Thermonuclear War is a two-player simultaneous nuclear strategy game
inspired by the 1983 film WarGames. Players (USA and USSR) manage nuclear
arsenals and ABM defenses across 40 cities, deciding whether to negotiate,
escalate, or launch.

These tests verify the game DEFINITION (JSON structure), not engine
behavior. All assertions are against the parsed GameDefinition dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "global-thermonuclear-war.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _raw_json() -> dict:
    """Return the raw parsed JSON dict for text-level searches."""
    return json.loads(_GAME_PATH.read_text())


# ===========================================================================
# Tests
# ===========================================================================


class TestGameLoads:
    """Verify the game definition loads and has correct high-level structure."""

    def test_loads_and_validates(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Global Thermonuclear War", (
            f"game name must be 'Global Thermonuclear War', got {defn.game.name!r}"
        )

    def test_player_names(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["USA", "USSR"], (
            f"expected players ['USA', 'USSR'], got {defn.game.players}"
        )

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect", (
            f"expected imperfect information, got {defn.game.information}"
        )


class TestCities:
    """Verify the 40 cities in the world_map graph zone."""

    def test_world_map_is_graph(self) -> None:
        defn = _load_game()
        world_map = defn.zones["world_map"]
        assert world_map.zone_type == "graph", (
            f"expected graph zone type, got {world_map.zone_type}"
        )

    def test_40_cities_total(self) -> None:
        defn = _load_game()
        world_map = defn.zones["world_map"]
        assert world_map.nodes is not None, "world_map must have nodes"
        assert len(world_map.nodes) == 40, (
            f"expected 40 city nodes, got {len(world_map.nodes)}"
        )

    def test_20_usa_cities(self) -> None:
        defn = _load_game()
        props = defn.zones["world_map"].node_properties
        assert props is not None, "world_map must have node_properties"
        usa_cities = [c for c, p in props.items() if p.get("side") == "USA"]
        assert len(usa_cities) == 20, (
            f"expected 20 USA cities, got {len(usa_cities)}: {usa_cities}"
        )

    def test_20_ussr_cities(self) -> None:
        defn = _load_game()
        props = defn.zones["world_map"].node_properties
        assert props is not None, "world_map must have node_properties"
        ussr_cities = [c for c, p in props.items() if p.get("side") == "USSR"]
        assert len(ussr_cities) == 20, (
            f"expected 20 USSR cities, got {len(ussr_cities)}: {ussr_cities}"
        )

    def test_all_cities_have_population(self) -> None:
        defn = _load_game()
        props = defn.zones["world_map"].node_properties
        assert props is not None, "world_map must have node_properties"
        for city, p in props.items():
            assert "population" in p, (
                f"city {city!r} missing population in node_properties"
            )
            assert isinstance(p["population"], int), (
                f"city {city!r} population should be int, got {type(p['population'])}"
            )
            assert p["population"] > 0, (
                f"city {city!r} population should be positive, got {p['population']}"
            )

    def test_every_node_has_properties(self) -> None:
        """Every node listed in nodes[] must have a corresponding entry in node_properties."""
        defn = _load_game()
        world_map = defn.zones["world_map"]
        assert world_map.nodes is not None
        assert world_map.node_properties is not None
        for node in world_map.nodes:
            assert node in world_map.node_properties, (
                f"node {node!r} listed in nodes but missing from node_properties"
            )


class TestComponents:
    """Verify missile types and interceptor component definitions."""

    def test_missile_component_exists(self) -> None:
        defn = _load_game()
        assert "missile" in defn.components, "missile component missing"

    def test_interceptor_component_exists(self) -> None:
        defn = _load_game()
        assert "interceptor" in defn.components, "interceptor component missing"

    def test_missile_has_three_types(self) -> None:
        defn = _load_game()
        missile = defn.components["missile"]
        assert missile.types is not None, "missile must have types"
        assert set(missile.types.keys()) == {"icbm", "slbm", "bomber"}, (
            f"expected missile types {{icbm, slbm, bomber}}, got {set(missile.types.keys())}"
        )

    def test_icbm_stats(self) -> None:
        defn = _load_game()
        icbm = defn.components["missile"].types["icbm"]
        assert icbm["warheads"] == 3, f"ICBM warheads should be 3, got {icbm['warheads']}"
        assert icbm["yield"] == 10, f"ICBM yield should be 10, got {icbm['yield']}"

    def test_slbm_stats(self) -> None:
        defn = _load_game()
        slbm = defn.components["missile"].types["slbm"]
        assert slbm["warheads"] == 1, f"SLBM warheads should be 1, got {slbm['warheads']}"
        assert slbm["yield"] == 5, f"SLBM yield should be 5, got {slbm['yield']}"

    def test_bomber_stats(self) -> None:
        defn = _load_game()
        bomber = defn.components["missile"].types["bomber"]
        assert bomber["warheads"] == 2, f"bomber warheads should be 2, got {bomber['warheads']}"
        assert bomber["yield"] == 8, f"bomber yield should be 8, got {bomber['yield']}"
        assert bomber.get("recallable") is True, "bomber should be recallable"

    def test_interceptor_intercept_chance(self) -> None:
        defn = _load_game()
        interceptor = defn.components["interceptor"]
        assert interceptor.properties is not None, "interceptor must have properties"
        assert interceptor.properties["intercept_chance"] == "30", (
            f"intercept_chance should be '30', got {interceptor.properties['intercept_chance']!r}"
        )

    def test_missiles_are_per_player(self) -> None:
        defn = _load_game()
        assert defn.components["missile"].owner == "per_player", (
            "missiles should be owned per_player"
        )

    def test_interceptors_are_per_player(self) -> None:
        defn = _load_game()
        assert defn.components["interceptor"].owner == "per_player", (
            "interceptors should be owned per_player"
        )


class TestPhases:
    """Verify 6 phases in correct order with simultaneous marking."""

    _EXPECTED_NAMES = [
        "defcon_5_diplomacy",
        "abm_deployment",
        "targeting",
        "launch",
        "resolution",
        "assessment",
    ]

    def test_six_phases(self) -> None:
        defn = _load_game()
        assert len(defn.phases) == 6, (
            f"expected 6 phases, got {len(defn.phases)}"
        )

    def test_phase_order(self) -> None:
        defn = _load_game()
        names = [p.name for p in defn.phases]
        assert names == self._EXPECTED_NAMES, (
            f"expected phases {self._EXPECTED_NAMES}, got {names}"
        )

    def test_diplomacy_is_simultaneous(self) -> None:
        defn = _load_game()
        phase = defn.phases[0]
        assert phase.name == "defcon_5_diplomacy"
        assert phase.simultaneous is True, "diplomacy phase should be simultaneous"

    def test_abm_deployment_is_simultaneous(self) -> None:
        defn = _load_game()
        phase = defn.phases[1]
        assert phase.name == "abm_deployment"
        assert phase.simultaneous is True, "ABM deployment phase should be simultaneous"

    def test_targeting_is_simultaneous(self) -> None:
        defn = _load_game()
        phase = defn.phases[2]
        assert phase.name == "targeting"
        assert phase.simultaneous is True, "targeting phase should be simultaneous"

    def test_launch_is_simultaneous(self) -> None:
        defn = _load_game()
        phase = defn.phases[3]
        assert phase.name == "launch"
        assert phase.simultaneous is True, "launch phase should be simultaneous"

    def test_resolution_has_resolve(self) -> None:
        defn = _load_game()
        phase = defn.phases[4]
        assert phase.name == "resolution"
        assert phase.resolve == "resolve_strikes", (
            f"resolution phase resolve should be 'resolve_strikes', got {phase.resolve!r}"
        )

    def test_assessment_has_resolve(self) -> None:
        defn = _load_game()
        phase = defn.phases[5]
        assert phase.name == "assessment"
        assert phase.resolve == "assess_damage", (
            f"assessment phase resolve should be 'assess_damage', got {phase.resolve!r}"
        )


class TestRules:
    """Verify all 8 rules are present with correct structure."""

    _EXPECTED_RULES = {
        "missile_allocation",
        "abm_defense",
        "intercept_resolution",
        "city_destruction",
        "bomber_recall",
        "mutual_destruction",
        "first_strike",
        "negotiation",
    }

    def test_eight_rules(self) -> None:
        defn = _load_game()
        assert len(defn.rules) == 8, (
            f"expected 8 rules, got {len(defn.rules)}"
        )

    def test_all_rule_keys_present(self) -> None:
        defn = _load_game()
        actual = set(defn.rules.keys())
        assert actual == self._EXPECTED_RULES, (
            f"rule keys mismatch: missing={self._EXPECTED_RULES - actual}, "
            f"extra={actual - self._EXPECTED_RULES}"
        )

    def test_missile_allocation_has_constraints(self) -> None:
        defn = _load_game()
        rule = defn.rules["missile_allocation"]
        assert rule.definition is not None, "missile_allocation should have a definition"
        assert len(rule.constraints) == 3, (
            f"missile_allocation should have 3 constraints, got {len(rule.constraints)}"
        )

    def test_abm_defense_has_constraints(self) -> None:
        defn = _load_game()
        rule = defn.rules["abm_defense"]
        assert rule.definition is not None, "abm_defense should have a definition"
        assert len(rule.constraints) == 2, (
            f"abm_defense should have 2 constraints, got {len(rule.constraints)}"
        )

    def test_intercept_resolution_has_server_resolves(self) -> None:
        defn = _load_game()
        rule = defn.rules["intercept_resolution"]
        assert rule.server_resolves is not None, (
            "intercept_resolution should have server_resolves"
        )

    def test_city_destruction_has_effect(self) -> None:
        defn = _load_game()
        rule = defn.rules["city_destruction"]
        assert rule.effect is not None, "city_destruction should have an effect"

    def test_bomber_recall_has_constraint(self) -> None:
        defn = _load_game()
        rule = defn.rules["bomber_recall"]
        assert rule.constraint is not None, "bomber_recall should have a constraint"

    def test_mutual_destruction_has_effect(self) -> None:
        defn = _load_game()
        rule = defn.rules["mutual_destruction"]
        assert rule.effect is not None, "mutual_destruction should have an effect"


class TestEndConditions:
    """Verify the 4 end conditions: peace, mutual_destruction, strategic_victory, de_escalation."""

    def _by_name(self, name: str) -> object:
        defn = _load_game()
        cond = next((e for e in defn.end_conditions if e.name == name), None)
        assert cond is not None, f"end condition {name!r} missing"
        return cond

    def test_four_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 4, (
            f"expected 4 end conditions, got {len(defn.end_conditions)}"
        )

    def test_peace_is_draw(self) -> None:
        cond = self._by_name("peace")
        assert cond.result == "draw", (
            f"peace should be a draw, got {cond.result!r}"
        )

    def test_mutual_destruction_is_draw(self) -> None:
        cond = self._by_name("mutual_destruction")
        assert cond.result == "draw", (
            f"mutual_destruction should be a draw, got {cond.result!r}"
        )

    def test_strategic_victory_is_win(self) -> None:
        cond = self._by_name("strategic_victory")
        assert cond.result == "win", (
            f"strategic_victory should be a win, got {cond.result!r}"
        )
        assert cond.player == "current", (
            f"strategic_victory player should be 'current', got {cond.player!r}"
        )

    def test_de_escalation_is_draw(self) -> None:
        cond = self._by_name("de_escalation")
        assert cond.result == "draw", (
            f"de_escalation should be a draw, got {cond.result!r}"
        )

    def test_end_condition_names(self) -> None:
        defn = _load_game()
        names = {e.name for e in defn.end_conditions}
        expected = {"peace", "mutual_destruction", "strategic_victory", "de_escalation"}
        assert names == expected, (
            f"end condition names mismatch: missing={expected - names}, extra={names - expected}"
        )


class TestAuthority:
    """Verify the authority declaration for trust services."""

    def test_server_only_includes_roll_intercept(self) -> None:
        defn = _load_game()
        assert "roll_intercept" in defn.authority.server_only, (
            "roll_intercept should be in server_only"
        )

    def test_server_only_includes_resolve_strikes(self) -> None:
        defn = _load_game()
        assert "resolve_strikes" in defn.authority.server_only, (
            "resolve_strikes should be in server_only"
        )

    def test_server_only_includes_assess_damage(self) -> None:
        defn = _load_game()
        assert "assess_damage" in defn.authority.server_only, (
            "assess_damage should be in server_only"
        )

    def test_server_only_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.server_only) == 3, (
            f"expected 3 server_only entries, got {len(defn.authority.server_only)}"
        )

    def test_wasm_required_includes_damage_calculation(self) -> None:
        defn = _load_game()
        assert "damage_calculation" in defn.authority.wasm_required, (
            "damage_calculation should be in wasm_required"
        )

    def test_wasm_required_includes_population_assessment(self) -> None:
        defn = _load_game()
        assert "population_assessment" in defn.authority.wasm_required, (
            "population_assessment should be in wasm_required"
        )

    def test_wasm_required_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.wasm_required) == 2, (
            f"expected 2 wasm_required entries, got {len(defn.authority.wasm_required)}"
        )

    def test_client_verifiable_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.client_verifiable) == 3, (
            f"expected 3 client_verifiable entries, got {len(defn.authority.client_verifiable)}"
        )


class TestMutualDestruction:
    """Verify the mutual_destruction end condition references 25% threshold."""

    def test_mutual_destruction_references_25_percent(self) -> None:
        defn = _load_game()
        cond = next(
            (e for e in defn.end_conditions if e.name == "mutual_destruction"), None
        )
        assert cond is not None, "mutual_destruction end condition missing"
        assert "25%" in cond.condition, (
            f"mutual_destruction condition should reference '25%', got {cond.condition!r}"
        )

    def test_mutual_destruction_rule_mentions_25_percent(self) -> None:
        defn = _load_game()
        rule = defn.rules["mutual_destruction"]
        assert "25%" in (rule.definition or ""), (
            f"mutual_destruction rule definition should mention '25%', got {rule.definition!r}"
        )


class TestWarGamesQuote:
    """Verify 'The only winning move is not to play' appears in the definition."""

    def test_quote_present(self) -> None:
        raw_text = _GAME_PATH.read_text()
        assert "The only winning move is not to play" in raw_text, (
            "WarGames quote 'The only winning move is not to play' not found in definition"
        )

    def test_quote_in_mutual_destruction_rule(self) -> None:
        defn = _load_game()
        rule = defn.rules["mutual_destruction"]
        assert "The only winning move is not to play" in (rule.effect or ""), (
            f"WarGames quote should be in mutual_destruction rule effect, got {rule.effect!r}"
        )
