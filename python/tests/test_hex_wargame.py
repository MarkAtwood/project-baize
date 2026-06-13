"""Tests for Hex Wargame: definition-level validation of a hex wargame.

Hex Wargame is a two-player wargame on a 20x15 hex grid. A river bisects
the map along columns 9-10, crossable only at bridge hexes (rows 3 and 11).
Mountains line the north edge. Eight objective towns (4 per side) determine
victory after turn 10.

These tests verify the game DEFINITION (JSON structure), not engine
behavior. All assertions are against the parsed GameDefinition dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import GameSession, GridZone

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "hex-wargame.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _session() -> GameSession:
    return GameSession(_load_game())


def _cell_properties() -> dict[str, dict[str, str | int | bool]]:
    """Return the raw cell_properties dict from the board zone definition."""
    defn = _load_game()
    return defn.zones["board"].cell_properties or {}


def _cells_with_terrain(terrain: str) -> list[str]:
    """Return sorted coordinate strings for cells with the given terrain."""
    cp = _cell_properties()
    return sorted(
        coord for coord, props in cp.items() if props.get("terrain") == terrain
    )


def _cells_with_property(key: str, value: str | int | bool) -> list[str]:
    """Return sorted coordinate strings for cells where key == value."""
    cp = _cell_properties()
    return sorted(
        coord for coord, props in cp.items() if props.get(key) == value
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestGameDefinitionLoads:
    """Verify the game definition loads and has correct high-level structure."""

    def test_loads_and_validates(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Hex Wargame", "game name must be 'Hex Wargame'"

    def test_has_300_cells(self) -> None:
        cp = _cell_properties()
        assert len(cp) == 300, (
            f"expected 300 cell_properties entries (20x15 grid), got {len(cp)}"
        )

    def test_has_20_units_per_side(self) -> None:
        defn = _load_game()
        unit = defn.components["unit"]
        assert unit.count == 20, f"expected 20 units per side, got {unit.count}"

    def test_has_5_phases(self) -> None:
        defn = _load_game()
        assert len(defn.phases) == 5, (
            f"expected 5 phases, got {len(defn.phases)}"
        )

    def test_has_12_rules(self) -> None:
        defn = _load_game()
        assert len(defn.rules) == 12, (
            f"expected 12 rules, got {len(defn.rules)}"
        )

    def test_has_8_objectives(self) -> None:
        objectives = _cells_with_property("objective", "true")
        assert len(objectives) == 8, (
            f"expected 8 objective cells, got {len(objectives)}: {objectives}"
        )

    def test_has_2_bridges(self) -> None:
        bridges = _cells_with_terrain("bridge")
        assert len(bridges) == 2, (
            f"expected 2 bridge cells, got {len(bridges)}: {bridges}"
        )

    def test_river_blocks_map(self) -> None:
        rivers = _cells_with_terrain("river")
        assert len(rivers) == 26, (
            f"expected 26 river cells, got {len(rivers)}"
        )

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["Blue", "Red"], (
            f"expected players ['Blue', 'Red'], got {defn.game.players}"
        )

    def test_hex_grid_dimensions(self) -> None:
        defn = _load_game()
        board = defn.zones["board"]
        assert board.zone_type == "hex_grid", (
            f"expected hex_grid zone type, got {board.zone_type}"
        )
        assert board.dimensions == [20, 15], (
            f"expected [20, 15] dimensions, got {board.dimensions}"
        )

    def test_hex_6_adjacency(self) -> None:
        defn = _load_game()
        board = defn.zones["board"]
        assert board.adjacency == "hex_6", (
            f"expected hex_6 adjacency, got {board.adjacency}"
        )

    def test_stacking_limit_3(self) -> None:
        defn = _load_game()
        board = defn.zones["board"]
        assert board.stacking_limit == 3, (
            f"expected stacking_limit 3, got {board.stacking_limit}"
        )

    def test_perfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "perfect", (
            f"expected perfect information, got {defn.game.information}"
        )

    def test_casualties_zone_exists(self) -> None:
        defn = _load_game()
        assert "casualties" in defn.zones, "expected a 'casualties' zone"
        cas = defn.zones["casualties"]
        assert cas.zone_type == "set", (
            f"expected casualties zone type 'set', got {cas.zone_type}"
        )
        assert cas.per_player is True, "casualties zone must be per_player"

    def test_wasm_module(self) -> None:
        defn = _load_game()
        assert defn.wasm_module == "wargame.wasm", (
            f"expected wasm_module 'wargame.wasm', got {defn.wasm_module}"
        )

    def test_alternating_turn_order(self) -> None:
        defn = _load_game()
        assert defn.turn_order.type == "alternating", (
            f"expected alternating turn order, got {defn.turn_order.type}"
        )

    def test_three_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 3, (
            f"expected 3 end conditions, got {len(defn.end_conditions)}"
        )


class TestTerrainProperties:
    """Verify terrain types are assigned correctly across the map."""

    def test_clear_terrain(self) -> None:
        clear = _cells_with_terrain("clear")
        assert len(clear) == 135, (
            f"expected 135 clear cells, got {len(clear)}"
        )

    def test_forest_terrain(self) -> None:
        forests = _cells_with_terrain("forest")
        assert len(forests) == 28, (
            f"expected 28 forest cells, got {len(forests)}"
        )
        # Spot-check a known forest cell
        assert "7,0" in forests, "cell 7,0 should be forest"
        assert "5,1" in forests, "cell 5,1 should be forest"

    def test_mountain_terrain(self) -> None:
        mountains = _cells_with_terrain("mountain")
        assert len(mountains) == 15, (
            f"expected 15 mountain cells, got {len(mountains)}"
        )
        # All mountains should be in rows 0-2
        for coord in mountains:
            row = int(coord.split(",")[1])
            assert row <= 2, (
                f"mountain at {coord} is in row {row}, expected rows 0-2"
            )

    def test_river_terrain(self) -> None:
        rivers = _cells_with_terrain("river")
        # All river cells should be in columns 9 or 10
        for coord in rivers:
            col = int(coord.split(",")[0])
            assert col in (9, 10), (
                f"river at {coord} has col {col}, expected 9 or 10"
            )

    def test_bridge_terrain(self) -> None:
        bridges = _cells_with_terrain("bridge")
        assert sorted(bridges) == ["9,11", "9,3"], (
            f"expected bridges at 9,3 and 9,11, got {bridges}"
        )

    def test_road_terrain(self) -> None:
        roads = _cells_with_terrain("road")
        assert len(roads) == 65, (
            f"expected 65 road cells, got {len(roads)}"
        )
        # Road should span across the map (multiple columns)
        road_cols = set()
        for coord in roads:
            col = int(coord.split(",")[0])
            road_cols.add(col)
        assert len(road_cols) >= 10, (
            f"expected roads spanning at least 10 columns, got {len(road_cols)}"
        )

    def test_hills_terrain(self) -> None:
        hills = _cells_with_terrain("hills")
        assert len(hills) == 21, (
            f"expected 21 hills cells, got {len(hills)}"
        )

    def test_town_objectives(self) -> None:
        """All 8 towns must have terrain=town and objective=true."""
        towns = _cells_with_terrain("town")
        assert len(towns) == 8, f"expected 8 town cells, got {len(towns)}"
        cp = _cell_properties()
        for coord in towns:
            props = cp[coord]
            assert props.get("objective") == "true", (
                f"town at {coord} should have objective=true"
            )

    def test_terrain_types_are_exhaustive(self) -> None:
        """Every cell has a recognized terrain type."""
        valid_terrains = {
            "clear", "forest", "mountain", "river", "bridge",
            "road", "hills", "town",
        }
        cp = _cell_properties()
        for coord, props in cp.items():
            terrain = props.get("terrain")
            assert terrain in valid_terrains, (
                f"cell {coord} has unknown terrain {terrain!r}"
            )


class TestUnitTypes:
    """Verify unit type statistics match the game definition."""

    def _get_unit_types(self) -> dict:
        defn = _load_game()
        return defn.components["unit"].types

    def test_infantry_stats(self) -> None:
        types = self._get_unit_types()
        inf = types["infantry"]
        props = inf["properties"]
        assert props["attack"] == 2, f"infantry attack should be 2, got {props['attack']}"
        assert props["defense"] == 3, f"infantry defense should be 3, got {props['defense']}"
        assert props["movement_points"] == 4, f"infantry MP should be 4, got {props['movement_points']}"
        assert props["steps"] == 2, f"infantry steps should be 2, got {props['steps']}"

    def test_armor_stats(self) -> None:
        types = self._get_unit_types()
        armor = types["armor"]
        props = armor["properties"]
        assert props["attack"] == 6, f"armor attack should be 6, got {props['attack']}"
        assert props["defense"] == 4, f"armor defense should be 4, got {props['defense']}"
        assert props["movement_points"] == 8, f"armor MP should be 8, got {props['movement_points']}"
        assert props["steps"] == 2, f"armor steps should be 2, got {props['steps']}"

    def test_mechanized_stats(self) -> None:
        types = self._get_unit_types()
        mech = types["mechanized"]
        props = mech["properties"]
        assert props["attack"] == 4, f"mechanized attack should be 4, got {props['attack']}"
        assert props["defense"] == 3, f"mechanized defense should be 3, got {props['defense']}"
        assert props["movement_points"] == 6, f"mechanized MP should be 6, got {props['movement_points']}"
        assert props["steps"] == 2, f"mechanized steps should be 2, got {props['steps']}"

    def test_artillery_stats(self) -> None:
        types = self._get_unit_types()
        art = types["artillery"]
        props = art["properties"]
        assert props["attack"] == 3, f"artillery attack should be 3, got {props['attack']}"
        assert props["defense"] == 1, f"artillery defense should be 1, got {props['defense']}"
        assert props["movement_points"] == 3, f"artillery MP should be 3, got {props['movement_points']}"
        assert props["steps"] == 1, f"artillery steps should be 1, got {props['steps']}"

    def test_headquarters_stats(self) -> None:
        types = self._get_unit_types()
        hq = types["headquarters"]
        props = hq["properties"]
        assert props["attack"] == 0, f"HQ attack should be 0, got {props['attack']}"
        assert props["defense"] == 1, f"HQ defense should be 1, got {props['defense']}"
        assert props["movement_points"] == 4, f"HQ MP should be 4, got {props['movement_points']}"
        assert props["steps"] == 1, f"HQ steps should be 1, got {props['steps']}"

    def test_recon_stats(self) -> None:
        types = self._get_unit_types()
        recon = types["recon"]
        props = recon["properties"]
        assert props["attack"] == 1, f"recon attack should be 1, got {props['attack']}"
        assert props["defense"] == 1, f"recon defense should be 1, got {props['defense']}"
        assert props["movement_points"] == 10, f"recon MP should be 10, got {props['movement_points']}"
        assert props["steps"] == 1, f"recon steps should be 1, got {props['steps']}"

    def test_unit_counts(self) -> None:
        types = self._get_unit_types()
        assert types["infantry"]["count"] == 6, "infantry count should be 6"
        assert types["armor"]["count"] == 4, "armor count should be 4"
        assert types["mechanized"]["count"] == 4, "mechanized count should be 4"
        assert types["artillery"]["count"] == 3, "artillery count should be 3"
        assert types["headquarters"]["count"] == 1, "HQ count should be 1"
        assert types["recon"]["count"] == 2, "recon count should be 2"

    def test_total_unit_count_matches(self) -> None:
        """Sum of sub-type counts should equal the top-level count."""
        defn = _load_game()
        unit = defn.components["unit"]
        types = unit.types
        total = sum(t["count"] for t in types.values())
        assert total == unit.count, (
            f"sum of type counts ({total}) != unit.count ({unit.count})"
        )

    def test_units_are_per_player(self) -> None:
        defn = _load_game()
        assert defn.components["unit"].owner == "per_player", (
            "units should be owned per_player"
        )


class TestPhaseStructure:
    """Verify the phase sequence and phase-specific fields."""

    def test_phase_names(self) -> None:
        defn = _load_game()
        names = [p.name for p in defn.phases]
        expected = ["reinforcement", "movement", "combat", "exploitation", "supply"]
        assert names == expected, f"expected phases {expected}, got {names}"

    def test_reinforcement_has_server_action(self) -> None:
        defn = _load_game()
        reinf = defn.phases[0]
        assert reinf.name == "reinforcement"
        assert reinf.server_action == "place_reinforcements", (
            f"reinforcement phase server_action should be 'place_reinforcements', "
            f"got {reinf.server_action!r}"
        )

    def test_movement_phase_action(self) -> None:
        defn = _load_game()
        movement = defn.phases[1]
        assert movement.name == "movement"
        assert movement.action == "move_piece", (
            f"movement phase action should be 'move_piece', got {movement.action!r}"
        )

    def test_combat_phase_action(self) -> None:
        defn = _load_game()
        combat = defn.phases[2]
        assert combat.name == "combat"
        assert combat.action == "declare_action", (
            f"combat phase action should be 'declare_action', got {combat.action!r}"
        )

    def test_exploitation_phase_action(self) -> None:
        defn = _load_game()
        exploit = defn.phases[3]
        assert exploit.name == "exploitation"
        assert exploit.action == "move_piece", (
            f"exploitation phase action should be 'move_piece', got {exploit.action!r}"
        )

    def test_supply_has_resolve(self) -> None:
        defn = _load_game()
        supply = defn.phases[4]
        assert supply.name == "supply"
        assert supply.resolve == "check_supply_lines", (
            f"supply phase resolve should be 'check_supply_lines', "
            f"got {supply.resolve!r}"
        )


class TestRulesCompleteness:
    """Verify all 12 rules exist with expected structure."""

    def _rules(self) -> dict:
        defn = _load_game()
        return defn.rules

    def test_terrain_movement_rule_exists(self) -> None:
        rules = self._rules()
        assert "terrain_movement" in rules, "terrain_movement rule missing"
        rule = rules["terrain_movement"]
        assert len(rule.constraints) == 8, (
            f"terrain_movement should have 8 constraints, got {len(rule.constraints)}"
        )

    def test_zoc_rule_exists(self) -> None:
        rules = self._rules()
        assert "zone_of_control" in rules, "zone_of_control rule missing"
        rule = rules["zone_of_control"]
        assert len(rule.constraints) == 3, (
            f"zone_of_control should have 3 constraints, got {len(rule.constraints)}"
        )

    def test_combat_resolution_rule_exists(self) -> None:
        rules = self._rules()
        assert "combat_resolution" in rules, "combat_resolution rule missing"
        rule = rules["combat_resolution"]
        assert rule.trigger == "combat phase", (
            f"combat_resolution trigger should be 'combat phase', got {rule.trigger!r}"
        )
        assert rule.effect is not None, "combat_resolution should have an effect"

    def test_stacking_rule_exists(self) -> None:
        rules = self._rules()
        assert "stacking" in rules, "stacking rule missing"
        rule = rules["stacking"]
        assert rule.definition is not None, "stacking rule should have a definition"

    def test_mandatory_combat_rule_exists(self) -> None:
        rules = self._rules()
        assert "mandatory_combat" in rules, "mandatory_combat rule missing"
        rule = rules["mandatory_combat"]
        assert rule.trigger == "combat phase", (
            f"mandatory_combat trigger should be 'combat phase', got {rule.trigger!r}"
        )

    def test_retreat_rule_exists(self) -> None:
        rules = self._rules()
        assert "retreat" in rules, "retreat rule missing"
        rule = rules["retreat"]
        assert len(rule.constraints) == 4, (
            f"retreat should have 4 constraints, got {len(rule.constraints)}"
        )

    def test_advance_after_combat_rule_exists(self) -> None:
        rules = self._rules()
        assert "advance_after_combat" in rules, "advance_after_combat rule missing"
        rule = rules["advance_after_combat"]
        assert rule.constraint is not None, (
            "advance_after_combat should have a constraint"
        )

    def test_step_losses_rule_exists(self) -> None:
        rules = self._rules()
        assert "step_losses" in rules, "step_losses rule missing"
        rule = rules["step_losses"]
        assert len(rule.constraints) == 3, (
            f"step_losses should have 3 constraints, got {len(rule.constraints)}"
        )

    def test_supply_line_rule_exists(self) -> None:
        rules = self._rules()
        assert "supply_line" in rules, "supply_line rule missing"
        rule = rules["supply_line"]
        assert len(rule.constraints) == 4, (
            f"supply_line should have 4 constraints, got {len(rule.constraints)}"
        )

    def test_river_crossing_rule_exists(self) -> None:
        rules = self._rules()
        assert "river_crossing" in rules, "river_crossing rule missing"
        rule = rules["river_crossing"]
        assert rule.constraint is not None, (
            "river_crossing should have a constraint"
        )

    def test_road_bonus_rule_exists(self) -> None:
        rules = self._rules()
        assert "road_bonus" in rules, "road_bonus rule missing"
        rule = rules["road_bonus"]
        assert rule.constraint is not None, (
            "road_bonus should have a constraint"
        )

    def test_exploitation_eligibility_rule_exists(self) -> None:
        rules = self._rules()
        assert "exploitation_eligibility" in rules, (
            "exploitation_eligibility rule missing"
        )
        rule = rules["exploitation_eligibility"]
        assert rule.constraint is not None, (
            "exploitation_eligibility should have a constraint"
        )

    def test_all_twelve_rules_present(self) -> None:
        """Guard against future regressions -- all rule keys must be present."""
        expected_rules = {
            "terrain_movement",
            "zone_of_control",
            "combat_resolution",
            "stacking",
            "road_bonus",
            "mandatory_combat",
            "retreat",
            "advance_after_combat",
            "step_losses",
            "supply_line",
            "river_crossing",
            "exploitation_eligibility",
        }
        actual = set(self._rules().keys())
        assert actual == expected_rules, (
            f"rule keys mismatch: missing={expected_rules - actual}, "
            f"extra={actual - expected_rules}"
        )


class TestMapGeography:
    """Verify spatial relationships: river, mountains, towns, bridges."""

    def test_river_runs_north_south(self) -> None:
        """River cells span multiple rows in columns 9-10."""
        rivers = _cells_with_terrain("river")
        river_rows = set()
        for coord in rivers:
            row = int(coord.split(",")[1])
            river_rows.add(row)
        # River must span at least 10 rows to constitute a real barrier
        assert len(river_rows) >= 10, (
            f"river should span at least 10 rows, got {len(river_rows)}: {sorted(river_rows)}"
        )
        # Verify it spans from near top to near bottom
        assert min(river_rows) == 0, "river should start at row 0"
        assert max(river_rows) == 14, "river should extend to row 14"

    def test_mountains_in_north(self) -> None:
        """Mountains are concentrated in rows 0-2 (north edge)."""
        mountains = _cells_with_terrain("mountain")
        assert len(mountains) > 0, "expected at least one mountain cell"
        for coord in mountains:
            row = int(coord.split(",")[1])
            assert row <= 2, (
                f"mountain at {coord} is in row {row}, "
                f"expected all mountains in rows 0-2"
            )

    def test_towns_distributed_both_sides(self) -> None:
        """4 towns on the west side of the river, 4 on the east side."""
        towns = _cells_with_terrain("town")
        west = [c for c in towns if int(c.split(",")[0]) < 9]
        east = [c for c in towns if int(c.split(",")[0]) > 10]
        assert len(west) == 4, (
            f"expected 4 towns west of river, got {len(west)}: {west}"
        )
        assert len(east) == 4, (
            f"expected 4 towns east of river, got {len(east)}: {east}"
        )

    def test_bridges_on_river(self) -> None:
        """Bridges must be at river crossing points (column 9, gap rows)."""
        bridges = _cells_with_terrain("bridge")
        for coord in bridges:
            col = int(coord.split(",")[0])
            assert col == 9, (
                f"bridge at {coord} has col {col}, expected col 9"
            )

    def test_bridges_at_river_gaps(self) -> None:
        """Bridges exist at rows where the river has gaps (rows 3 and 11)."""
        bridges = _cells_with_terrain("bridge")
        bridge_rows = sorted(int(c.split(",")[1]) for c in bridges)
        assert bridge_rows == [3, 11], (
            f"expected bridges at rows 3 and 11, got rows {bridge_rows}"
        )

    def test_no_river_at_bridge_rows(self) -> None:
        """At bridge rows (3 and 11), there should be no river in the same row+col area."""
        rivers = _cells_with_terrain("river")
        river_set = set(rivers)
        # Bridge at 9,3 replaces what would be river
        assert "9,3" not in river_set, "9,3 should be bridge, not river"
        # Bridge at 9,11 replaces what would be river
        assert "9,11" not in river_set, "9,11 should be bridge, not river"

    def test_grid_fully_populated(self) -> None:
        """Every cell in the 20x15 grid should have a terrain property."""
        cp = _cell_properties()
        for row in range(15):
            for col in range(20):
                coord = f"{col},{row}"
                assert coord in cp, (
                    f"cell {coord} missing from cell_properties"
                )
                assert "terrain" in cp[coord], (
                    f"cell {coord} missing terrain property"
                )


class TestAuthorityModel:
    """Verify the authority declaration for trust services."""

    def test_server_only_includes_dice(self) -> None:
        defn = _load_game()
        assert "roll_dice" in defn.authority.server_only, (
            "roll_dice should be in server_only"
        )

    def test_server_only_includes_combat(self) -> None:
        defn = _load_game()
        assert "resolve_combat" in defn.authority.server_only, (
            "resolve_combat should be in server_only"
        )

    def test_server_only_includes_reinforcements(self) -> None:
        defn = _load_game()
        assert "place_reinforcements" in defn.authority.server_only, (
            "place_reinforcements should be in server_only"
        )

    def test_wasm_required_includes_crt(self) -> None:
        defn = _load_game()
        assert "crt_lookup" in defn.authority.wasm_required, (
            "crt_lookup should be in wasm_required"
        )

    def test_wasm_required_includes_supply(self) -> None:
        defn = _load_game()
        assert "supply_line_tracing" in defn.authority.wasm_required, (
            "supply_line_tracing should be in wasm_required"
        )

    def test_wasm_required_includes_terrain_cost(self) -> None:
        defn = _load_game()
        assert "terrain_cost_calculation" in defn.authority.wasm_required, (
            "terrain_cost_calculation should be in wasm_required"
        )

    def test_wasm_required_includes_zoc(self) -> None:
        defn = _load_game()
        assert "zoc_computation" in defn.authority.wasm_required, (
            "zoc_computation should be in wasm_required"
        )

    def test_wasm_required_includes_vp(self) -> None:
        defn = _load_game()
        assert "victory_point_scoring" in defn.authority.wasm_required, (
            "victory_point_scoring should be in wasm_required"
        )

    def test_client_verifiable_includes_movement(self) -> None:
        defn = _load_game()
        assert "movement_cost" in defn.authority.client_verifiable, (
            "movement_cost should be in client_verifiable"
        )

    def test_client_verifiable_includes_stacking(self) -> None:
        defn = _load_game()
        assert "stacking_limit" in defn.authority.client_verifiable, (
            "stacking_limit should be in client_verifiable"
        )

    def test_client_verifiable_includes_zoc_check(self) -> None:
        defn = _load_game()
        assert "zoc_check" in defn.authority.client_verifiable, (
            "zoc_check should be in client_verifiable"
        )

    def test_server_only_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.server_only) == 3, (
            f"expected 3 server_only entries, got {len(defn.authority.server_only)}"
        )

    def test_client_verifiable_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.client_verifiable) == 3, (
            f"expected 3 client_verifiable entries, got {len(defn.authority.client_verifiable)}"
        )

    def test_wasm_required_count(self) -> None:
        defn = _load_game()
        assert len(defn.authority.wasm_required) == 5, (
            f"expected 5 wasm_required entries, got {len(defn.authority.wasm_required)}"
        )


class TestEndConditions:
    """Verify end condition definitions."""

    def test_elimination_win(self) -> None:
        defn = _load_game()
        elim = next(
            (e for e in defn.end_conditions if e.name == "elimination"), None
        )
        assert elim is not None, "elimination end condition missing"
        assert elim.result == "win", "elimination should be a win condition"
        assert elim.player == "current", (
            f"elimination player should be 'current', got {elim.player!r}"
        )

    def test_objective_control_win(self) -> None:
        defn = _load_game()
        obj = next(
            (e for e in defn.end_conditions if e.name == "objective_control"),
            None,
        )
        assert obj is not None, "objective_control end condition missing"
        assert obj.result == "win", "objective_control should be a win condition"

    def test_draw_condition(self) -> None:
        defn = _load_game()
        draw = next(
            (e for e in defn.end_conditions if e.name == "draw"), None
        )
        assert draw is not None, "draw end condition missing"
        assert draw.result == "draw", "draw condition should have result 'draw'"


class TestLibrary:
    """Verify the library section contains expected helper definitions."""

    def test_terrain_cost_defined(self) -> None:
        defn = _load_game()
        assert "terrain_cost" in defn.library, "terrain_cost missing from library"

    def test_attack_odds_defined(self) -> None:
        defn = _load_game()
        assert "attack_odds" in defn.library, "attack_odds missing from library"

    def test_crt_columns_defined(self) -> None:
        defn = _load_game()
        assert "crt_columns" in defn.library, "crt_columns missing from library"

    def test_supply_trace_defined(self) -> None:
        defn = _load_game()
        assert "supply_trace" in defn.library, "supply_trace missing from library"

    def test_step_loss_calc_defined(self) -> None:
        defn = _load_game()
        assert "step_loss_calc" in defn.library, "step_loss_calc missing from library"

    def test_retreat_validation_defined(self) -> None:
        defn = _load_game()
        assert "retreat_validation" in defn.library, (
            "retreat_validation missing from library"
        )


class TestRuntimeSetup:
    """Verify the game session can be created from the definition."""

    def test_session_creates_board(self) -> None:
        session = _session()
        assert "board" in session.runtime.zones, "board zone missing from runtime"
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone), (
            f"board zone should be GridZone, got {type(zone).__name__}"
        )

    def test_board_dimensions(self) -> None:
        session = _session()
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.width == 20, f"board width should be 20, got {zone.width}"
        assert zone.height == 15, f"board height should be 15, got {zone.height}"

    def test_cell_properties_loaded_at_runtime(self) -> None:
        """Cell properties from the definition are available at runtime."""
        session = _session()
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        # Check a known clear cell
        assert zone.get_cell_property(0, 0, "terrain") == "clear", (
            "cell (0,0) should have terrain 'clear' at runtime"
        )
        # Check a known mountain cell
        assert zone.get_cell_property(12, 0, "terrain") == "mountain", (
            "cell (12,0) should have terrain 'mountain' at runtime"
        )
        # Check a town with objective
        assert zone.get_cell_property(0, 5, "terrain") == "town", (
            "cell (0,5) should have terrain 'town' at runtime"
        )
        assert zone.get_cell_property(0, 5, "objective") == "true", (
            "cell (0,5) should have objective 'true' at runtime"
        )

    def test_two_players_created(self) -> None:
        session = _session()
        assert "Blue" in session.runtime.players, "Blue player missing"
        assert "Red" in session.runtime.players, "Red player missing"
        assert len(session.runtime.players) == 2, (
            f"expected 2 players, got {len(session.runtime.players)}"
        )

    def test_per_player_casualties_zones(self) -> None:
        """Each player should have their own casualties zone."""
        session = _session()
        for player_name in ("Blue", "Red"):
            player = session.runtime.players[player_name]
            assert "casualties" in player.zones, (
                f"{player_name} missing per-player casualties zone"
            )

    def test_stacking_limit_at_runtime(self) -> None:
        session = _session()
        zone = session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        assert zone.stacking_limit == 3, (
            f"runtime stacking_limit should be 3, got {zone.stacking_limit}"
        )


class TestTerrainMovementCosts:
    """Verify terrain movement cost constraints in the rule definition."""

    def test_clear_costs_1_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "clear costs 1 MP" in rule.constraints

    def test_forest_costs_2_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "forest costs 2 MP" in rule.constraints

    def test_hills_costs_2_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "hills costs 2 MP" in rule.constraints

    def test_mountain_costs_3_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "mountain costs 3 MP" in rule.constraints

    def test_road_costs_1_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "road costs 1 MP" in rule.constraints

    def test_town_costs_1_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "town costs 1 MP" in rule.constraints

    def test_bridge_costs_1_mp(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "bridge costs 1 MP" in rule.constraints

    def test_river_is_impassable(self) -> None:
        defn = _load_game()
        rule = defn.rules["terrain_movement"]
        assert "river is impassable" in rule.constraints
