"""Tests for Ogre: hex wargame foundation -- unit placement, hex geometry, scenario setup.

Ogre is a two-player asymmetric hex wargame. One player controls a single
cybertank (the Ogre Mk III), the other defends a command post with conventional
forces. The Ogre enters from the south edge and attempts to destroy the CP
at the north end of the board.

Board conventions:
  - 22x15 hex grid with hex_6 adjacency
  - Hex neighbors: [(-1,0),(1,0),(0,-1),(0,1),(-1,1),(1,-1)]
  - Row 0 = north (defender), Row 14 = south (Ogre entry)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)

# ---------------------------------------------------------------------------
# Unit data
# ---------------------------------------------------------------------------

UNIT_TYPES = {
    "infantry": {"attack": 1, "defense": 1, "range": 1, "move": 2},
    "heavy_tank": {"attack": 4, "defense": 3, "range": 2, "move": 3},
    "missile_tank": {"attack": 3, "defense": 2, "range": 4, "move": 2},
    "howitzer": {"attack": 6, "defense": 1, "range": 8, "move": 0},
    "gev": {"attack": 2, "defense": 2, "range": 2, "move": 4},
    "command_post": {"attack": 0, "defense": 1, "range": 0, "move": 0},
}

# Ogre Mk III subsystems
OGRE_MK3 = {
    "main_battery": {"count": 1, "attack": 4, "range": 3, "defense": 4},
    "secondary_battery": {"count": 4, "attack": 3, "range": 2, "defense": 3},
    "missile": {"count": 2, "attack": 6, "range": 5, "defense": 3},
    "ap_gun": {"count": 8, "attack": 1, "range": 1, "defense": 1},
    "treads": {"count": 45, "defense": 1},
}

# Hex directions for hex_6 adjacency
_HEX_DIRS: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "ogre.json"

# ---------------------------------------------------------------------------
# CRT (Combat Results Table)
# ---------------------------------------------------------------------------

# Results: "NE" = no effect, "X" = destroyed, "D" = disabled (treat as destroyed for simplicity)
CRT: dict[str, list[str]] = {
    # ratio: [roll 1, roll 2, roll 3, roll 4, roll 5, roll 6]
    "1:2": ["NE", "NE", "NE", "NE", "NE", "D"],
    "1:1": ["NE", "NE", "NE", "NE", "D", "X"],
    "2:1": ["NE", "NE", "NE", "D", "X", "X"],
    "3:1": ["NE", "NE", "D", "X", "X", "X"],
    "4:1": ["NE", "D", "X", "X", "X", "X"],
}


def _load_definition() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# OgreGame helper
# ---------------------------------------------------------------------------


class OgreGame:
    """Ogre game driver -- foundation: hex board, unit placement, scenario setup."""

    BOARD_WIDTH = 22
    BOARD_HEIGHT = 15

    def __init__(self) -> None:
        defn = _load_definition()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None
        self.ogre_systems: dict[str, int] = {}
        self.ogre_pos: tuple[int, int] = (0, 0)
        self._setup_standard_scenario()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def _place(self, col: int, row: int, unit_type: str, owner: str) -> ComponentId:
        cid = self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"{unit_type}-{owner}-{col}-{row}",
                component_type=unit_type,
                owner=owner,
            )
        )
        self.board.grid_push(col, row, cid)
        return cid

    def _setup_standard_scenario(self) -> None:
        """Place standard Ogre Mk III scenario.

        Defender: 1 CP at (11,2), 1 howitzer at (11,3), 2 heavy tanks,
        2 missile tanks, 2 GEVs, 12 infantry squads spread around CP.
        Ogre: single marker at (11,14) with Mk III stats.
        """
        # Command post
        self._place(11, 2, "command_post", "Defender")

        # Howitzer behind CP
        self._place(11, 3, "howitzer", "Defender")

        # Heavy tanks flanking
        self._place(9, 4, "heavy_tank", "Defender")
        self._place(13, 4, "heavy_tank", "Defender")

        # Missile tanks further out
        self._place(8, 5, "missile_tank", "Defender")
        self._place(14, 5, "missile_tank", "Defender")

        # GEVs on wings
        self._place(7, 6, "gev", "Defender")
        self._place(15, 6, "gev", "Defender")

        # 12 infantry squads in a screen south of CP
        infantry_positions = [
            (9, 7), (10, 7), (11, 7), (12, 7), (13, 7),
            (10, 8), (11, 8), (12, 8),
            (10, 9), (11, 9), (12, 9),
            (11, 10),
        ]
        for col, row in infantry_positions:
            self._place(col, row, "infantry", "Defender")

        # Ogre Mk III at south edge center
        self.ogre_pos = (11, 14)
        self._place(11, 14, "ogre", "Ogre")

        # Initialize Ogre subsystems from OGRE_MK3 data
        self.ogre_systems = {name: data["count"] for name, data in OGRE_MK3.items()}

    def piece_at(self, col: int, row: int) -> tuple[str, str] | None:
        """Return (unit_type, owner) of top unit at hex, or None."""
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        if comp is None:
            return None
        return (comp.component_type, comp.owner)

    def units_at(self, col: int, row: int) -> list[tuple[str, str]]:
        """Return all (unit_type, owner) at hex, bottom to top."""
        result = []
        for cid in self.board.grid_stack(col, row):
            comp = self.session.runtime.components.get(cid)
            if comp is not None:
                result.append((comp.component_type, comp.owner))
        return result

    def hex_distance(self, c1: int, r1: int, c2: int, r2: int) -> int:
        """Compute hex distance using cube coordinate conversion.

        Cube coords: x=col, z=row, y=-x-z.
        Distance = max(|dx|, |dy|, |dz|).
        """
        dx = c2 - c1
        dz = r2 - r1
        dy = -dx - dz
        return max(abs(dx), abs(dy), abs(dz))

    def is_valid_hex(self, col: int, row: int) -> bool:
        """Check if (col, row) is within the board bounds."""
        return self.board._cell_valid(col, row)

    def hex_neighbors(self, col: int, row: int) -> list[tuple[int, int]]:
        """Return valid neighboring hexes."""
        result = []
        for dc, dr in _HEX_DIRS:
            nc, nr = col + dc, row + dr
            if self.is_valid_hex(nc, nr):
                result.append((nc, nr))
        return result

    def all_units(self, owner: str | None = None) -> list[tuple[int, int, str, str]]:
        """Scan board for all units. Returns list of (col, row, type, owner)."""
        found = []
        for row in range(self.BOARD_HEIGHT):
            for col in range(self.BOARD_WIDTH):
                for cid in self.board.grid_stack(col, row):
                    comp = self.session.runtime.components.get(cid)
                    if comp is not None:
                        if owner is None or comp.owner == owner:
                            found.append((col, row, comp.component_type, comp.owner))
        return found

    # -------------------------------------------------------------------
    # Movement
    # -------------------------------------------------------------------

    def movement_points(self, unit_type: str, owner: str) -> int:
        """Return current movement points for a unit type.

        Conventional units use the static UNIT_TYPES table.
        The Ogre derives MP from remaining treads: (treads + 14) // 15,
        so 45 treads = 3 MP, 30 = 2, 15 = 1, 0 = 0.
        """
        if unit_type == "ogre":
            treads = self.ogre_systems["treads"]
            return max(0, (treads + 14) // 15)
        return UNIT_TYPES[unit_type]["move"]

    def terrain_cost(self, col: int, row: int) -> int:
        """Return movement cost to enter a hex.

        Craters cost 2 MP; everything else costs 1.
        """
        terrain = self.board.get_cell_property(col, row, "terrain")
        if terrain == "crater":
            return 2
        return 1

    def can_move_to(
        self,
        unit_cid: ComponentId,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
    ) -> bool:
        """Check whether a unit can move one hex from (from) to (to).

        Rules:
        - Must be adjacent (hex_distance == 1)
        - Unit must have enough MP (terrain_cost <= MP)
        - Target hex must not contain enemy units
        - Stacking: max 3 non-infantry per hex, infantry unlimited
        - Howitzers and command posts cannot move (MP == 0)
        """
        # Must be adjacent
        if self.hex_distance(from_col, from_row, to_col, to_row) != 1:
            return False

        # Look up unit info
        comp = self.session.runtime.components.get(unit_cid)
        if comp is None:
            return False

        # Check MP
        mp = self.movement_points(comp.component_type, comp.owner)
        if mp <= 0:
            return False
        cost = self.terrain_cost(to_col, to_row)
        if cost > mp:
            return False

        # No entering a hex with enemy units
        occupants = self.units_at(to_col, to_row)
        for _utype, uowner in occupants:
            if uowner != comp.owner:
                return False

        # Stacking limit: max 3 non-infantry per hex
        if comp.component_type != "infantry":
            non_infantry = sum(
                1 for utype, _ in occupants if utype != "infantry"
            )
            if non_infantry >= 3:
                return False

        return True

    def move_unit(self, from_col: int, from_row: int, to_col: int, to_row: int) -> None:
        """Move the top unit at (from) one hex to (to).

        Pops from source, pushes to destination.
        Updates ogre_pos if the moved piece is the Ogre.
        """
        cid = self.board.grid_pop(from_col, from_row)
        assert cid is not None, f"No unit at ({from_col},{from_row})"
        self.board.grid_push(to_col, to_row, cid)
        comp = self.session.runtime.components.get(cid)
        if comp is not None and comp.component_type == "ogre":
            self.ogre_pos = (to_col, to_row)

    def move_ogre(self, path: list[tuple[int, int]]) -> None:
        """Move the Ogre along a multi-hex path.

        Each step must be adjacent; total terrain cost must not exceed
        the Ogre's current movement points. Updates ogre_pos after each step.
        """
        mp = self.movement_points("ogre", "Ogre")
        current = self.ogre_pos
        for to_col, to_row in path:
            assert self.hex_distance(current[0], current[1], to_col, to_row) == 1, (
                f"Path step from {current} to ({to_col},{to_row}) is not adjacent"
            )
            cost = self.terrain_cost(to_col, to_row)
            assert cost <= mp, (
                f"Not enough MP: need {cost}, have {mp}"
            )
            mp -= cost
            self.move_unit(current[0], current[1], to_col, to_row)
            current = (to_col, to_row)

    # -------------------------------------------------------------------
    # Combat resolution (CRT)
    # -------------------------------------------------------------------

    def compute_ratio(self, attack_strength: int, defense: int) -> str:
        """Compute CRT column from total attack strength vs defense.

        Rounds down to nearest table ratio. Attacks weaker than 1:2 still
        use the 1:2 column. Ratios above 4:1 are capped at 4:1.
        """
        if defense <= 0:
            return "4:1"
        if attack_strength < defense:
            return "1:2"
        if attack_strength < 2 * defense:
            return "1:1"
        if attack_strength < 3 * defense:
            return "2:1"
        if attack_strength < 4 * defense:
            return "3:1"
        return "4:1"

    def resolve_combat(self, attack_strength: int, defense: int, roll: int) -> str:
        """Look up CRT result for given attack/defense and d6 roll (1-6)."""
        ratio = self.compute_ratio(attack_strength, defense)
        return CRT[ratio][roll - 1]

    def in_range(self, from_col: int, from_row: int, to_col: int, to_row: int, unit_type: str) -> bool:
        """Check if unit_type at (from_col, from_row) can fire at (to_col, to_row)."""
        unit_range = UNIT_TYPES[unit_type]["range"]
        return self.hex_distance(from_col, from_row, to_col, to_row) <= unit_range

    # -------------------------------------------------------------------
    # Ogre subsystem targeting
    # -------------------------------------------------------------------

    def ogre_subsystem_defense(self, subsystem: str) -> int:
        """Defense value for targeting a specific Ogre subsystem."""
        return OGRE_MK3[subsystem]["defense"]

    def attack_ogre_subsystem(self, attack_strength: int, subsystem: str, roll: int) -> str:
        """Attack a specific Ogre subsystem on the CRT.

        Resolves attack_strength vs subsystem defense. On "D" or "X",
        decrements ogre_systems[subsystem] by 1 (min 0).
        Returns the CRT result.
        """
        defense = self.ogre_subsystem_defense(subsystem)
        result = self.resolve_combat(attack_strength, defense, roll)
        if result in ("D", "X"):
            self.ogre_systems[subsystem] = max(0, self.ogre_systems[subsystem] - 1)
        return result

    def attack_ogre_treads(self, attack_strength: int, roll: int) -> int:
        """Attack Ogre treads. Any non-NE result destroys attack_strength treads.

        Each attack point directed at treads destroys 1 tread on a hit.
        Resolves once on CRT at attack_strength:1. If the result is not "NE",
        destroys min(attack_strength, remaining treads) treads.
        Returns the number of treads destroyed.
        """
        result = self.resolve_combat(attack_strength, 1, roll)
        if result == "NE":
            return 0
        destroyed = min(attack_strength, self.ogre_systems["treads"])
        self.ogre_systems["treads"] = max(0, self.ogre_systems["treads"] - destroyed)
        return destroyed

    def ogre_is_destroyed(self) -> bool:
        """True when ALL weapons are at 0 AND treads are at 0."""
        return all(v == 0 for v in self.ogre_systems.values())

    def ogre_attack_strength(self) -> dict[str, tuple[int, int, int]]:
        """Returns available Ogre weapons: {subsystem: (count, attack, range)}.

        Only includes subsystems with count > 0 and that have attack/range
        (excludes treads).
        """
        result: dict[str, tuple[int, int, int]] = {}
        for name, data in OGRE_MK3.items():
            if name == "treads":
                continue
            count = self.ogre_systems[name]
            if count > 0:
                result[name] = (count, data["attack"], data["range"])
        return result

    # -------------------------------------------------------------------
    # Conventional unit combat
    # -------------------------------------------------------------------

    def attack_unit(
        self,
        attacker_positions: list[tuple[int, int]],
        target_col: int,
        target_row: int,
        roll: int,
    ) -> str:
        """Resolve combined fire from multiple attackers against a target.

        Each attacker must be in range of the target. Attack strengths are
        summed, compared against the target's defense on the CRT, and the
        die roll determines the outcome.

        Returns "NE", "D", or "X". On "D" or "X", removes the target from
        the board.
        """
        # Identify target
        target_info = self.piece_at(target_col, target_row)
        if target_info is None:
            return "NE"
        target_type, _owner = target_info
        defense = UNIT_TYPES[target_type]["defense"]

        # Sum attacker strengths (must each be in range)
        total_attack = 0
        for acol, arow in attacker_positions:
            attacker_info = self.piece_at(acol, arow)
            if attacker_info is None:
                continue
            atype, _aowner = attacker_info
            if not self.in_range(acol, arow, target_col, target_row, atype):
                raise ValueError(
                    f"{atype} at ({acol},{arow}) out of range of ({target_col},{target_row})"
                )
            total_attack += UNIT_TYPES[atype]["attack"]

        result = self.resolve_combat(total_attack, defense, roll)

        # Remove destroyed/disabled unit
        if result in ("D", "X"):
            self.board.grid_pop(target_col, target_row)

        return result

    # -------------------------------------------------------------------
    # GEV second movement phase
    # -------------------------------------------------------------------

    def gev_second_move(
        self, from_col: int, from_row: int, to_col: int, to_row: int
    ) -> None:
        """Move a GEV in the second movement phase (after combat).

        Standard Ogre rules give GEVs full movement (4 MP) in both the
        first and second movement phases. This method enforces the same
        movement rules as a normal move: adjacency, no enemy hexes, valid
        destination.

        Raises AssertionError if the unit at (from) is not a GEV.
        """
        info = self.piece_at(from_col, from_row)
        assert info is not None, f"No unit at ({from_col},{from_row})"
        unit_type, _owner = info
        assert unit_type == "gev", f"Only GEVs get a second move, not {unit_type}"

        cid = self.board.grid_get(from_col, from_row)
        assert cid is not None
        assert self.can_move_to(cid, from_col, from_row, to_col, to_row), (
            f"GEV cannot move from ({from_col},{from_row}) to ({to_col},{to_row})"
        )
        self.move_unit(from_col, from_row, to_col, to_row)

    # -------------------------------------------------------------------
    # Ogre overrun combat
    # -------------------------------------------------------------------

    def ogre_overrun(
        self, target_col: int, target_row: int, roll: int
    ) -> list[str]:
        """Resolve overrun combat when the Ogre enters an occupied hex.

        Each defender in the hex is attacked by one AP gun at 1:1 odds.
        Uses one AP gun per defender (AP guns have attack=1, and each
        defender is resolved individually on the CRT).

        Pops all units from the target hex, resolves combat for each
        defender, then pushes survivors back. The Ogre is not moved
        into the hex by this method.

        Returns a list of CRT results, one per defender present.
        """
        # Collect all units in the hex (pop them all out)
        popped: list[tuple[ComponentId, str, str]] = []
        while True:
            cid = self.board.grid_pop(target_col, target_row)
            if cid is None:
                break
            comp = self.session.runtime.components.get(cid)
            if comp is not None:
                popped.append((cid, comp.component_type, comp.owner))

        ap_attack = OGRE_MK3["ap_gun"]["attack"]  # 1
        results: list[str] = []
        survivors: list[ComponentId] = []

        for cid, utype, owner in popped:
            if owner == "Ogre":
                # Friendly Ogre units are not attacked
                survivors.append(cid)
                continue
            if self.ogre_systems.get("ap_gun", 0) <= 0:
                # No AP guns left; defender survives
                survivors.append(cid)
                continue
            defense = UNIT_TYPES[utype]["defense"]
            result = self.resolve_combat(ap_attack, defense, roll)
            results.append(result)
            if result in ("D", "X"):
                pass  # destroyed, do not push back
            else:
                survivors.append(cid)

        # Push survivors back (bottom-to-top order preserved)
        for cid in survivors:
            self.board.grid_push(target_col, target_row, cid)

        return results

    # -------------------------------------------------------------------
    # Win conditions
    # -------------------------------------------------------------------

    def is_cp_destroyed(self) -> bool:
        """Check if the command post has been removed from the board."""
        for row in range(self.BOARD_HEIGHT):
            for col in range(self.BOARD_WIDTH):
                for cid in self.board.grid_stack(col, row):
                    comp = self.session.runtime.components.get(cid)
                    if comp is not None and comp.component_type == "command_post":
                        return False
        return True

    def _ogre_has_weapon_in_range_of_cp(self) -> bool:
        """Check if any surviving Ogre weapon can reach the command post."""
        # Find CP position
        cp_pos: tuple[int, int] | None = None
        for row in range(self.BOARD_HEIGHT):
            for col in range(self.BOARD_WIDTH):
                for cid in self.board.grid_stack(col, row):
                    comp = self.session.runtime.components.get(cid)
                    if comp is not None and comp.component_type == "command_post":
                        cp_pos = (col, row)
                        break
                if cp_pos is not None:
                    break
            if cp_pos is not None:
                break

        if cp_pos is None:
            return False

        ocol, orow = self.ogre_pos
        dist = self.hex_distance(ocol, orow, cp_pos[0], cp_pos[1])

        weapon_ranges = {
            "main_battery": OGRE_MK3["main_battery"]["range"],
            "secondary_battery": OGRE_MK3["secondary_battery"]["range"],
            "missile": OGRE_MK3["missile"]["range"],
            "ap_gun": OGRE_MK3["ap_gun"]["range"],
        }
        for weapon, wrange in weapon_ranges.items():
            if self.ogre_systems.get(weapon, 0) > 0 and dist <= wrange:
                return True
        return False

    def check_win_condition(self) -> str | None:
        """Check if the game is over.

        Returns:
            "ogre_wins" if the command post is destroyed.
            "defender_wins" if the Ogre is neutralized (all weapons and
                treads at 0, OR treads at 0 with no weapons in range of CP).
            None if the game continues.
        """
        if self.is_cp_destroyed():
            return "ogre_wins"

        if self.ogre_is_destroyed():
            return "defender_wins"

        # Ogre immobilized (no treads) with no weapons that can reach CP
        if self.ogre_systems.get("treads", 0) == 0:
            if not self._ogre_has_weapon_in_range_of_cp():
                return "defender_wins"

        return None


# ===========================================================================
# Tests
# ===========================================================================


class TestDefinition:
    """Verify the game definition loads and has correct structure."""

    def test_loads_json(self) -> None:
        defn = _load_definition()
        assert defn.game.name == "Ogre"

    def test_two_players(self) -> None:
        defn = _load_definition()
        assert defn.game.players == ["Ogre", "Defender"]

    def test_hex_grid_dimensions(self) -> None:
        defn = _load_definition()
        board = defn.zones["board"]
        assert board.zone_type == "hex_grid"
        assert board.dimensions == [22, 15]


class TestUnitData:
    """Verify unit type and Ogre subsystem data tables."""

    def test_six_conventional_unit_types(self) -> None:
        assert len(UNIT_TYPES) == 6
        expected = {"infantry", "heavy_tank", "missile_tank", "howitzer", "gev", "command_post"}
        assert set(UNIT_TYPES.keys()) == expected

    def test_ogre_mk3_five_subsystem_types(self) -> None:
        assert len(OGRE_MK3) == 5
        expected = {"main_battery", "secondary_battery", "missile", "ap_gun", "treads"}
        assert set(OGRE_MK3.keys()) == expected

    def test_ogre_total_treads(self) -> None:
        assert OGRE_MK3["treads"]["count"] == 45


class TestSetup:
    """Verify standard scenario placement."""

    def test_ogre_at_south_edge(self) -> None:
        g = OgreGame()
        result = g.piece_at(11, 14)
        assert result is not None
        assert result == ("ogre", "Ogre")
        assert g.ogre_pos == (11, 14)

    def test_command_post_at_expected_position(self) -> None:
        g = OgreGame()
        result = g.piece_at(11, 2)
        assert result is not None
        assert result == ("command_post", "Defender")

    def test_defender_has_twenty_plus_units(self) -> None:
        g = OgreGame()
        defender_units = g.all_units(owner="Defender")
        # 1 CP + 1 howitzer + 2 heavy + 2 missile + 2 GEV + 12 infantry = 20
        assert len(defender_units) >= 20

    def test_ogre_systems_initialized(self) -> None:
        g = OgreGame()
        assert g.ogre_systems["main_battery"] == 1
        assert g.ogre_systems["secondary_battery"] == 4
        assert g.ogre_systems["missile"] == 2
        assert g.ogre_systems["ap_gun"] == 8
        assert g.ogre_systems["treads"] == 45

    def test_board_not_empty(self) -> None:
        g = OgreGame()
        all_units = g.all_units()
        # 20 defender + 1 ogre = 21
        assert len(all_units) >= 21


class TestHexDistance:
    """Verify hex distance calculations."""

    def test_same_hex_distance_zero(self) -> None:
        g = OgreGame()
        assert g.hex_distance(5, 5, 5, 5) == 0

    def test_adjacent_hex_distance_one(self) -> None:
        g = OgreGame()
        # All 6 hex neighbors should be distance 1
        for dc, dr in _HEX_DIRS:
            assert g.hex_distance(5, 5, 5 + dc, 5 + dr) == 1

    def test_known_distance(self) -> None:
        g = OgreGame()
        # (0,0) to (5,5): cube coords (0,0,0) to (5,-10,5)
        # dx=5, dz=5, dy=-5-5=-10 => max(5,10,5) = 10
        assert g.hex_distance(0, 0, 5, 5) == 10

    def test_symmetric(self) -> None:
        g = OgreGame()
        assert g.hex_distance(3, 7, 10, 2) == g.hex_distance(10, 2, 3, 7)


class TestHexNeighbors:
    """Verify hex neighbor enumeration."""

    def test_center_hex_has_six_neighbors(self) -> None:
        g = OgreGame()
        neighbors = g.hex_neighbors(10, 7)
        assert len(neighbors) == 6

    def test_corner_hex_has_fewer_neighbors(self) -> None:
        g = OgreGame()
        # (0, 0) is top-left corner
        neighbors = g.hex_neighbors(0, 0)
        # Only (1,0) and (0,1) are valid — (-1,0), (0,-1), (-1,1), (1,-1) are out of bounds
        assert len(neighbors) < 6

    def test_all_neighbors_are_valid(self) -> None:
        g = OgreGame()
        for col in range(g.BOARD_WIDTH):
            for row in range(g.BOARD_HEIGHT):
                for nc, nr in g.hex_neighbors(col, row):
                    assert g.is_valid_hex(nc, nr), f"Invalid neighbor ({nc},{nr}) of ({col},{row})"


class TestMovement:
    """Verify movement point calculation, terrain costs, and single-hex moves."""

    def test_heavy_tank_has_3_mp(self) -> None:
        g = OgreGame()
        assert g.movement_points("heavy_tank", "Defender") == 3

    def test_howitzer_has_0_mp(self) -> None:
        g = OgreGame()
        assert g.movement_points("howitzer", "Defender") == 0

    def test_ogre_full_treads_3_mp(self) -> None:
        g = OgreGame()
        assert g.ogre_systems["treads"] == 45
        assert g.movement_points("ogre", "Ogre") == 3

    def test_ogre_15_treads_1_mp(self) -> None:
        g = OgreGame()
        g.ogre_systems["treads"] = 15
        assert g.movement_points("ogre", "Ogre") == 1

    def test_ogre_0_treads_0_mp(self) -> None:
        g = OgreGame()
        g.ogre_systems["treads"] = 0
        assert g.movement_points("ogre", "Ogre") == 0

    def test_move_unit_to_adjacent_empty_hex(self) -> None:
        g = OgreGame()
        # Heavy tank at (9, 4); (8, 4) is empty and adjacent
        cid = g.board.grid_get(9, 4)
        assert cid is not None
        assert g.can_move_to(cid, 9, 4, 8, 4)
        g.move_unit(9, 4, 8, 4)
        assert g.piece_at(8, 4) == ("heavy_tank", "Defender")
        assert g.piece_at(9, 4) is None

    def test_cannot_move_to_non_adjacent_hex(self) -> None:
        g = OgreGame()
        # Heavy tank at (9, 4); (9, 6) is 2 hexes away
        cid = g.board.grid_get(9, 4)
        assert cid is not None
        assert not g.can_move_to(cid, 9, 4, 9, 6)

    def test_cannot_move_howitzer(self) -> None:
        g = OgreGame()
        # Howitzer at (11, 3); (10, 3) is adjacent but howitzer has 0 MP
        cid = g.board.grid_get(11, 3)
        assert cid is not None
        assert not g.can_move_to(cid, 11, 3, 10, 3)


class TestOgreMovement:
    """Verify multi-hex Ogre path movement and tread degradation effects."""

    def test_ogre_moves_3_hex_path(self) -> None:
        g = OgreGame()
        # Ogre at (11, 14) with 45 treads = 3 MP
        # Path north through empty hexes: (11,13), (11,12), (11,11)
        g.move_ogre([(11, 13), (11, 12), (11, 11)])
        assert g.ogre_pos == (11, 11)
        assert g.piece_at(11, 11) == ("ogre", "Ogre")
        assert g.piece_at(11, 14) is None

    def test_ogre_reduced_treads_limited_movement(self) -> None:
        g = OgreGame()
        g.ogre_systems["treads"] = 15  # 1 MP
        # Can only move 1 hex; attempting 2 in one move should fail
        with pytest.raises(AssertionError, match="Not enough MP"):
            g.move_ogre([(11, 13), (11, 12)])

    def test_ogre_position_updates_after_move(self) -> None:
        g = OgreGame()
        assert g.ogre_pos == (11, 14)
        g.move_ogre([(11, 13)])
        assert g.ogre_pos == (11, 13)
        # Board reflects the move
        assert g.piece_at(11, 14) is None
        assert g.piece_at(11, 13) == ("ogre", "Ogre")


# ---------------------------------------------------------------------------
# CRT tests
# ---------------------------------------------------------------------------


class TestCRT:
    """Verify CRT ratio computation and result lookup."""

    def test_ratio_1_vs_2_gives_1_to_2(self) -> None:
        g = OgreGame()
        assert g.compute_ratio(1, 2) == "1:2"

    def test_ratio_4_vs_1_gives_4_to_1(self) -> None:
        g = OgreGame()
        assert g.compute_ratio(4, 1) == "4:1"

    def test_ratio_6_vs_1_capped_at_4_to_1(self) -> None:
        g = OgreGame()
        assert g.compute_ratio(6, 1) == "4:1"

    def test_roll_6_at_1_to_1_is_destroyed(self) -> None:
        g = OgreGame()
        assert g.resolve_combat(2, 2, 6) == "X"

    def test_roll_1_at_4_to_1_is_no_effect(self) -> None:
        g = OgreGame()
        assert g.resolve_combat(8, 2, 1) == "NE"


# ---------------------------------------------------------------------------
# Combat tests
# ---------------------------------------------------------------------------


class TestCombat:
    """Verify combined-fire combat resolution."""

    def test_heavy_tank_vs_infantry(self) -> None:
        """Heavy tank (attack 4) vs infantry (defense 1) at range 1 => 4:1."""
        g = OgreGame()
        # Heavy tank at (9,4), place an enemy infantry adjacent at (9,5)
        g._place(9, 5, "infantry", "Ogre")
        # attack=4 vs defense=1 => 4:1; roll 6 => "X"
        ratio = g.compute_ratio(4, 1)
        assert ratio == "4:1"
        result = g.attack_unit([(9, 4)], 9, 5, 6)
        assert result == "X"
        # Unit should be removed
        assert g.piece_at(9, 5) is None

    def test_howitzer_vs_heavy_tank(self) -> None:
        """Howitzer (attack 6) vs heavy tank (defense 3) at range <= 8 => 2:1."""
        g = OgreGame()
        # Howitzer at (11,3), heavy tank at (9,4) -- distance is 3
        dist = g.hex_distance(11, 3, 9, 4)
        assert dist <= 8, f"Expected howitzer in range, got distance {dist}"
        ratio = g.compute_ratio(6, 3)
        assert ratio == "2:1"
        # Roll 4 at 2:1 => "D" (disabled = removed)
        result = g.attack_unit([(11, 3)], 9, 4, 4)
        assert result == "D"
        assert g.piece_at(9, 4) is None

    def test_combined_fire_two_infantry(self) -> None:
        """2 infantry (total attack 2) vs infantry (defense 1) => 2:1."""
        g = OgreGame()
        # Use two adjacent infantry from the screen: (10,7) and (11,7)
        # Place an Ogre infantry target at (11,6) which is in range of both
        g._place(11, 6, "infantry", "Ogre")
        dist1 = g.hex_distance(10, 7, 11, 6)
        dist2 = g.hex_distance(11, 7, 11, 6)
        assert dist1 <= 1 and dist2 <= 1, f"Distances: {dist1}, {dist2}"
        ratio = g.compute_ratio(2, 1)
        assert ratio == "2:1"
        result = g.attack_unit([(10, 7), (11, 7)], 11, 6, 5)
        assert result == "X"

    def test_out_of_range_raises(self) -> None:
        """Missile tank (range 4) can't hit target at distance 5."""
        g = OgreGame()
        # Missile tank at (8,5); place a target far away at (8,0) -- distance 5
        g._place(8, 0, "infantry", "Ogre")
        dist = g.hex_distance(8, 5, 8, 0)
        assert dist == 5, f"Expected distance 5, got {dist}"
        with pytest.raises(ValueError, match="out of range"):
            g.attack_unit([(8, 5)], 8, 0, 3)


# ---------------------------------------------------------------------------
# Subsystem targeting tests
# ---------------------------------------------------------------------------


class TestSubsystemTargeting:
    """Verify Ogre subsystem targeting, degradation, and destruction."""

    def test_attack_main_battery_destroyed_on_hit(self) -> None:
        """Main battery defense 4: ratio 4:4 = 1:1, roll 6 = X, count decremented."""
        g = OgreGame()
        assert g.ogre_systems["main_battery"] == 1
        # attack 4 vs defense 4 => 1:1, roll 6 => "X"
        result = g.attack_ogre_subsystem(4, "main_battery", 6)
        assert result == "X"
        assert g.ogre_systems["main_battery"] == 0

    def test_attack_secondary_battery_destroyed_on_hit(self) -> None:
        """Secondary battery defense 3: attack 3 vs 3 = 1:1, roll 5 = D."""
        g = OgreGame()
        assert g.ogre_systems["secondary_battery"] == 4
        result = g.attack_ogre_subsystem(3, "secondary_battery", 5)
        assert result == "D"
        assert g.ogre_systems["secondary_battery"] == 3

    def test_attack_ap_gun_easy_at_4_to_1(self) -> None:
        """AP gun defense 1: attack 4 vs 1 = 4:1, roll 2 = D."""
        g = OgreGame()
        assert g.ogre_systems["ap_gun"] == 8
        # 4:1 column, roll 2 => "D"
        result = g.attack_ogre_subsystem(4, "ap_gun", 2)
        assert result == "D"
        assert g.ogre_systems["ap_gun"] == 7

    def test_attack_treads_destroys_multiple(self) -> None:
        """4 attack strength at treads: on hit, destroys 4 treads."""
        g = OgreGame()
        assert g.ogre_systems["treads"] == 45
        # attack 4 vs defense 1 => 4:1, roll 3 => "X"
        destroyed = g.attack_ogre_treads(4, 3)
        assert destroyed == 4
        assert g.ogre_systems["treads"] == 41

    def test_failed_attack_no_damage(self) -> None:
        """Roll 1 at 1:1 is NE -- subsystem count unchanged."""
        g = OgreGame()
        assert g.ogre_systems["secondary_battery"] == 4
        # attack 3 vs defense 3 => 1:1, roll 1 => "NE"
        result = g.attack_ogre_subsystem(3, "secondary_battery", 1)
        assert result == "NE"
        assert g.ogre_systems["secondary_battery"] == 4

    def test_multiple_attacks_degrade_ogre(self) -> None:
        """Progressive attacks reduce weapons and treads."""
        g = OgreGame()
        # Destroy the main battery
        g.attack_ogre_subsystem(4, "main_battery", 6)  # X
        assert g.ogre_systems["main_battery"] == 0
        # Destroy 2 secondary batteries
        g.attack_ogre_subsystem(3, "secondary_battery", 5)  # D
        g.attack_ogre_subsystem(3, "secondary_battery", 6)  # X
        assert g.ogre_systems["secondary_battery"] == 2
        # Destroy a missile
        g.attack_ogre_subsystem(6, "missile", 6)  # 2:1, roll 6 => X
        assert g.ogre_systems["missile"] == 1
        # Knock off some treads
        g.attack_ogre_treads(4, 3)  # 4:1, roll 3 => X, destroy 4
        assert g.ogre_systems["treads"] == 41
        # Ogre attack strength reflects degradation
        weapons = g.ogre_attack_strength()
        assert "main_battery" not in weapons
        assert weapons["secondary_battery"] == (2, 3, 2)
        assert weapons["missile"] == (1, 6, 5)
        assert weapons["ap_gun"] == (8, 1, 1)

    def test_ogre_destroyed_when_all_zero(self) -> None:
        """Ogre is destroyed when all weapons and treads are at 0."""
        g = OgreGame()
        assert not g.ogre_is_destroyed()
        # Zero everything out
        g.ogre_systems = {name: 0 for name in g.ogre_systems}
        assert g.ogre_is_destroyed()


# ---------------------------------------------------------------------------
# GEV second movement tests
# ---------------------------------------------------------------------------


class TestGEV:
    """Verify GEV second movement phase."""

    def test_gev_second_move_after_combat(self) -> None:
        """GEV can make a second move after the combat phase."""
        g = OgreGame()
        # GEV starts at (7, 6). Move it once in phase 1.
        g.move_unit(7, 6, 6, 6)
        assert g.piece_at(6, 6) == ("gev", "Defender")
        # Now use second movement phase to move again
        g.gev_second_move(6, 6, 5, 6)
        assert g.piece_at(5, 6) == ("gev", "Defender")
        assert g.piece_at(6, 6) is None

    def test_gev_second_move_respects_movement_rules(self) -> None:
        """GEV second move must obey adjacency and no-enemy-hex rules."""
        g = OgreGame()
        # GEV at (7, 6). Move it once in phase 1 to (6, 6).
        g.move_unit(7, 6, 6, 6)
        # Place an enemy unit at (5, 6) to block the GEV
        g._place(5, 6, "infantry", "Ogre")
        # GEV cannot enter enemy-occupied hex
        with pytest.raises(AssertionError, match="GEV cannot move"):
            g.gev_second_move(6, 6, 5, 6)

    def test_non_gev_cannot_second_move(self) -> None:
        """Only GEVs get a second movement phase."""
        g = OgreGame()
        # Heavy tank at (9, 4) -- not a GEV
        with pytest.raises(AssertionError, match="Only GEVs"):
            g.gev_second_move(9, 4, 8, 4)


# ---------------------------------------------------------------------------
# Overrun combat tests
# ---------------------------------------------------------------------------


class TestOverrun:
    """Verify Ogre overrun combat when entering occupied hexes."""

    def test_overrun_infantry(self) -> None:
        """Ogre overruns a single infantry: AP gun (attack 1) vs defense 1 = 1:1."""
        g = OgreGame()
        # Place a lone defender infantry at an empty hex
        g._place(5, 5, "infantry", "Defender")
        # Overrun: AP attack=1 vs infantry defense=1 => 1:1
        # Roll 6 at 1:1 => "X" (destroyed)
        results = g.ogre_overrun(5, 5, 6)
        assert len(results) == 1
        assert results[0] == "X"
        # Infantry should be removed
        assert g.units_at(5, 5) == []

    def test_overrun_multiple_units(self) -> None:
        """Ogre overruns multiple defenders: one AP gun per defender."""
        g = OgreGame()
        # Place two defender infantry at the same hex
        g._place(5, 5, "infantry", "Defender")
        g._place(5, 5, "infantry", "Defender")
        assert len(g.units_at(5, 5)) == 2
        # Roll 6 at 1:1 => "X" for each
        results = g.ogre_overrun(5, 5, 6)
        assert len(results) == 2
        assert all(r == "X" for r in results)
        assert g.units_at(5, 5) == []

    def test_overrun_results_depend_on_crt(self) -> None:
        """Overrun results vary with the die roll per the CRT."""
        g = OgreGame()
        # Place a single defender infantry
        g._place(5, 5, "infantry", "Defender")
        # AP attack=1 vs infantry defense=1 => 1:1
        # Roll 1 at 1:1 => "NE" (no effect)
        results = g.ogre_overrun(5, 5, 1)
        assert len(results) == 1
        assert results[0] == "NE"
        # Infantry survives
        assert len(g.units_at(5, 5)) == 1
        assert g.units_at(5, 5)[0] == ("infantry", "Defender")


# ---------------------------------------------------------------------------
# Win condition tests
# ---------------------------------------------------------------------------


class TestWinConditions:
    """Verify game end detection."""

    def test_cp_destroyed_ogre_wins(self) -> None:
        """Destroying the command post means the Ogre wins."""
        g = OgreGame()
        assert not g.is_cp_destroyed()
        # Remove the CP from the board
        g.board.grid_pop(11, 2)
        assert g.is_cp_destroyed()
        assert g.check_win_condition() == "ogre_wins"

    def test_all_ogre_systems_zero_defender_wins(self) -> None:
        """All Ogre weapons + treads at 0 means the defender wins."""
        g = OgreGame()
        g.ogre_systems = {name: 0 for name in g.ogre_systems}
        assert g.ogre_is_destroyed()
        assert g.check_win_condition() == "defender_wins"

    def test_game_continues_while_both_capable(self) -> None:
        """Game is not over when both sides still have capability."""
        g = OgreGame()
        assert g.check_win_condition() is None

    def test_ogre_immobilized_no_weapons_in_range(self) -> None:
        """Ogre with no treads and no weapons in range of CP => defender wins."""
        g = OgreGame()
        # Ogre is at (11, 14), CP is at (11, 2) -- distance 12
        dist = g.hex_distance(11, 14, 11, 2)
        assert dist == 12
        # Zero treads so Ogre is immobilized
        g.ogre_systems["treads"] = 0
        # Keep only missiles (range 5) -- not enough to reach CP at distance 12
        g.ogre_systems["main_battery"] = 0  # range 3
        g.ogre_systems["secondary_battery"] = 0  # range 2
        g.ogre_systems["ap_gun"] = 0  # range 1
        # missile has range 5, Ogre is 12 hexes from CP -- out of range
        assert g.ogre_systems["missile"] == 2
        assert not g._ogre_has_weapon_in_range_of_cp()
        assert g.check_win_condition() == "defender_wins"


# ---------------------------------------------------------------------------
# Integration tests — full game scenarios
# ---------------------------------------------------------------------------


class TestIntegration:
    """Play through complete Ogre game scenarios exercising multiple systems."""

    def test_ogre_advance_and_destroy_cp(self) -> None:
        """Ogre advances toward CP over 3 turns, then destroys it.

        Turn 1: Ogre moves 3 hexes north (11,14) -> (11,11).
        Turn 2: Clear infantry at (11,10) (simulating prior combat), move (11,11) -> (11,8).
        Turn 3: Clear infantry at (11,7) (simulating prior combat), move (11,8) -> (11,5).
        Fire phase: Main battery (attack 4) vs CP (defense 1) = 4:1, roll 3 = "X".
        Result: CP destroyed, ogre_wins.
        """
        g = OgreGame()
        assert g.check_win_condition() is None

        # --- Turn 1: Ogre advances 3 hexes north through empty terrain ---
        assert g.ogre_pos == (11, 14)
        g.move_ogre([(11, 13), (11, 12), (11, 11)])
        assert g.ogre_pos == (11, 11)

        # --- Turn 2: Defenders at (11,10) destroyed in combat (simulated) ---
        # Infantry at (11,10) blocks the path; remove it as a combat result
        assert g.piece_at(11, 10) == ("infantry", "Defender")
        g.board.grid_pop(11, 10)
        assert g.piece_at(11, 10) is None

        # Ogre advances 3 more hexes: (11,10), (11,9), (11,8)
        # First clear (11,9) infantry too (simulating defender losses)
        assert g.piece_at(11, 9) == ("infantry", "Defender")
        g.board.grid_pop(11, 9)

        g.move_ogre([(11, 10), (11, 9), (11, 8)])
        assert g.ogre_pos == (11, 8)

        # --- Turn 3: Clear more infantry, advance toward CP ---
        # Clear (11,7) infantry blocking the path
        assert g.piece_at(11, 7) == ("infantry", "Defender")
        g.board.grid_pop(11, 7)

        g.move_ogre([(11, 7), (11, 6), (11, 5)])
        assert g.ogre_pos == (11, 5)

        # Verify Ogre is now within main battery range (3) of CP at (11,2)
        dist_to_cp = g.hex_distance(11, 5, 11, 2)
        assert dist_to_cp == 3
        assert dist_to_cp <= OGRE_MK3["main_battery"]["range"]

        # --- Fire phase: Main battery fires on CP ---
        # attack 4 vs CP defense 1 = 4:1, roll 3 => "X" (destroyed)
        ratio = g.compute_ratio(4, 1)
        assert ratio == "4:1"
        result = g.resolve_combat(4, 1, 3)
        assert result == "X"

        # Remove CP from board (destroyed)
        assert g.piece_at(11, 2) == ("command_post", "Defender")
        g.board.grid_pop(11, 2)
        assert g.is_cp_destroyed()

        # --- Victory check ---
        assert g.check_win_condition() == "ogre_wins"

    def test_defenders_destroy_ogre(self) -> None:
        """Defenders systematically strip all Ogre subsystems and treads.

        Heavy tanks and other units combine fire to destroy every weapon
        system, then pound treads until the Ogre is immobilized and
        completely neutralized.
        """
        g = OgreGame()
        assert not g.ogre_is_destroyed()

        # --- Destroy main battery (1 unit) ---
        # attack 4 vs defense 4 = 1:1, roll 6 = "X"
        result = g.attack_ogre_subsystem(4, "main_battery", 6)
        assert result == "X"
        assert g.ogre_systems["main_battery"] == 0

        # --- Destroy all 4 secondary batteries ---
        for i in range(4):
            count_before = g.ogre_systems["secondary_battery"]
            # attack 3 vs defense 3 = 1:1, roll 6 = "X"
            result = g.attack_ogre_subsystem(3, "secondary_battery", 6)
            assert result == "X"
            assert g.ogre_systems["secondary_battery"] == count_before - 1
        assert g.ogre_systems["secondary_battery"] == 0

        # --- Destroy both missiles ---
        for i in range(2):
            count_before = g.ogre_systems["missile"]
            # attack 6 vs defense 3 = 2:1, roll 5 = "X"
            result = g.attack_ogre_subsystem(6, "missile", 5)
            assert result == "X"
            assert g.ogre_systems["missile"] == count_before - 1
        assert g.ogre_systems["missile"] == 0

        # --- Destroy all 8 AP guns ---
        for i in range(8):
            count_before = g.ogre_systems["ap_gun"]
            # attack 4 vs defense 1 = 4:1, roll 3 = "X"
            result = g.attack_ogre_subsystem(4, "ap_gun", 3)
            assert result == "X"
            assert g.ogre_systems["ap_gun"] == count_before - 1
        assert g.ogre_systems["ap_gun"] == 0

        # Verify all weapons gone but treads remain
        assert g.ogre_attack_strength() == {}
        assert g.ogre_systems["treads"] == 45
        assert not g.ogre_is_destroyed()

        # --- Destroy all 45 treads using concentrated fire ---
        # Each attack_ogre_treads with attack 10 at 4:1, roll 3 = "X"
        # destroys min(10, remaining) treads per hit
        remaining = g.ogre_systems["treads"]
        while remaining > 0:
            destroyed = g.attack_ogre_treads(10, 3)
            expected = min(10, remaining)
            assert destroyed == expected
            remaining = g.ogre_systems["treads"]
        assert g.ogre_systems["treads"] == 0

        # --- Victory check ---
        assert g.ogre_is_destroyed()
        assert g.check_win_condition() == "defender_wins"

    def test_ogre_overrun_on_advance(self) -> None:
        """Ogre moves into a hex with infantry, overrun resolves.

        Place Ogre and infantry on adjacent hexes. Resolve overrun in
        the infantry's hex, then move the Ogre in. Verify the infantry
        is destroyed and the Ogre occupies the new position.
        """
        g = OgreGame()

        # Move Ogre north to (11, 13) first
        g.move_ogre([(11, 13)])
        assert g.ogre_pos == (11, 13)

        # Place a defender infantry adjacent at (11, 12)
        g._place(11, 12, "infantry", "Defender")
        assert g.piece_at(11, 12) == ("infantry", "Defender")

        # Ogre overruns the infantry hex before entering
        # AP gun attack=1 vs infantry defense=1 = 1:1, roll 6 = "X"
        results = g.ogre_overrun(11, 12, 6)
        assert len(results) == 1
        assert results[0] == "X"

        # Infantry destroyed
        assert g.units_at(11, 12) == []

        # Now move Ogre into the cleared hex
        g.move_ogre([(11, 12)])
        assert g.ogre_pos == (11, 12)
        assert g.piece_at(11, 12) == ("ogre", "Ogre")
        assert g.piece_at(11, 13) is None

    def test_combined_fire_from_multiple_units(self) -> None:
        """Three heavy tanks combine fire on an Ogre secondary battery.

        Place 3 heavy tanks around the Ogre (all within range 2).
        Combined attack: 3 * 4 = 12 vs secondary battery defense 3 = 4:1.
        Roll resolves and subsystem takes damage.
        """
        g = OgreGame()

        # Move Ogre to a position surrounded by empty hexes
        # Standard Ogre at (11,14); move to (11,13) for elbow room
        g.move_ogre([(11, 13)])
        assert g.ogre_pos == (11, 13)

        # Place 3 heavy tanks within range 2 of Ogre at (11,13)
        tank_positions = [(10, 12), (12, 12), (11, 12)]
        for col, row in tank_positions:
            g._place(col, row, "heavy_tank", "Defender")

        # Verify all tanks are in range (distance <= 2 = heavy tank range)
        for col, row in tank_positions:
            dist = g.hex_distance(col, row, 11, 13)
            assert dist <= UNIT_TYPES["heavy_tank"]["range"], (
                f"Tank at ({col},{row}) is {dist} hexes from Ogre, out of range"
            )

        # Combined attack: 3 heavy tanks * attack 4 = 12 total
        total_attack = 3 * UNIT_TYPES["heavy_tank"]["attack"]
        assert total_attack == 12

        # Target: secondary battery, defense 3
        # Ratio: 12 vs 3 = 4:1, roll 3 = "X"
        sec_defense = OGRE_MK3["secondary_battery"]["defense"]
        ratio = g.compute_ratio(total_attack, sec_defense)
        assert ratio == "4:1"

        count_before = g.ogre_systems["secondary_battery"]
        assert count_before == 4

        result = g.attack_ogre_subsystem(total_attack, "secondary_battery", 3)
        assert result == "X"
        assert g.ogre_systems["secondary_battery"] == count_before - 1

    def test_gev_hit_and_run(self) -> None:
        """GEV advances, attacks an Ogre AP gun, then retreats to safety.

        Phase 1 movement: GEV moves into range of the Ogre.
        Combat: GEV (attack 2) vs AP gun (defense 1) = 2:1, roll 5 = "X".
        Phase 2 movement: GEV retreats away from Ogre.
        """
        g = OgreGame()

        # Move Ogre to (11, 13) so it's away from the standard defenders
        g.move_ogre([(11, 13)])
        assert g.ogre_pos == (11, 13)

        # Place a GEV at (11, 11) -- 2 hexes from Ogre, within GEV range (2)
        g._place(11, 11, "gev", "Defender")
        assert g.piece_at(11, 11) == ("gev", "Defender")

        # --- Phase 1 movement: move GEV closer (into range) ---
        # GEV moves from (11, 11) to (11, 12) -- 1 hex from Ogre, still in range
        g.move_unit(11, 11, 11, 12)
        assert g.piece_at(11, 12) == ("gev", "Defender")

        # Verify GEV is in range of Ogre
        dist = g.hex_distance(11, 12, 11, 13)
        assert dist <= UNIT_TYPES["gev"]["range"]

        # --- Combat: GEV fires at Ogre AP gun ---
        # GEV attack 2 vs AP gun defense 1 = 2:1, roll 5 = "X"
        gev_attack = UNIT_TYPES["gev"]["attack"]
        ap_defense = OGRE_MK3["ap_gun"]["defense"]
        ratio = g.compute_ratio(gev_attack, ap_defense)
        assert ratio == "2:1"

        ap_before = g.ogre_systems["ap_gun"]
        assert ap_before == 8

        result = g.attack_ogre_subsystem(gev_attack, "ap_gun", 5)
        assert result == "X"
        assert g.ogre_systems["ap_gun"] == ap_before - 1

        # --- Phase 2 movement: GEV retreats to safety ---
        # GEV at (11, 12) retreats to (11, 11) -- away from Ogre
        g.gev_second_move(11, 12, 11, 11)
        assert g.piece_at(11, 11) == ("gev", "Defender")
        assert g.piece_at(11, 12) is None

        # Verify GEV is now at safe distance (2 hexes from Ogre)
        safe_dist = g.hex_distance(11, 11, 11, 13)
        assert safe_dist == 2
        # AP guns only have range 1, so GEV is out of AP range
        assert safe_dist > OGRE_MK3["ap_gun"]["range"]
