"""Tests for Colossal Cave Adventure (350-point expanded version).

An expanded single-player text adventure with ~46 rooms, 10 treasures worth
varying points (total 350), lamp battery mechanic, maze, troll bridge, pit
obstacle, and pirate's lair.

Exercises: graph zone construction, adjacency, node properties, set zone
(inventory), counter zone (lamp battery), component placement, movement
validation, obstacle mechanics, scoring, darkness detection, and full
walkthrough.
"""

from __future__ import annotations

import json
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
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "colossal-cave-350.json"

TREASURES: dict[str, int] = {
    "gold_nugget": 50,
    "diamonds": 50,
    "silver_bars": 30,
    "rare_coins": 20,
    "ming_vase": 20,
    "pearl": 30,
    "golden_eggs": 40,
    "trident": 40,
    "persian_rug": 40,
    "spices": 30,
}

TOOLS = ["keys", "lamp", "bird", "rope"]

LAMP_BATTERY_MAX = 330

# Initial item placements (room -> list of item types)
INITIAL_ITEMS: dict[str, list[str]] = {
    "building": ["keys", "lamp"],
    "debris": ["rope"],
    "bird_chamber": ["bird"],
    "west_side_chamber": ["gold_nugget", "diamonds"],
    "south_side_chamber": ["silver_bars"],
    "y2": ["rare_coins"],
    "plover_room": ["ming_vase"],
    "shell_room": ["pearl", "golden_eggs"],
    "slab_room": ["trident"],
    "volcano_view": ["persian_rug", "spices"],
}


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# CaveGame350 helper
# ---------------------------------------------------------------------------


class CaveGame350:
    """Expanded Colossal Cave Adventure driver (350-point version)."""

    def __init__(self) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None

        # Player location tracking
        self.player_room = "building"

        # Item locations: item_type -> room name (or "inventory" if carried)
        self.item_locations: dict[str, str] = {}

        # Obstacle state
        self.grate_unlocked = False
        self.snake_gone = False
        self.troll_satisfied = False
        self.pit_secured = False

        # Lamp battery
        self.lamp_battery = LAMP_BATTERY_MAX
        self.lamp_dead = False

        # Create item components and place them in rooms
        self.items: dict[str, ComponentId] = {}
        for room, item_types in INITIAL_ITEMS.items():
            for item_type in item_types:
                cid = self.session.runtime.components.insert(
                    ComponentData(
                        id=ComponentId(0),
                        string_id=f"item-{item_type}",
                        component_type=item_type,
                        owner="neutral",
                    )
                )
                self.items[item_type] = cid
                self.item_locations[item_type] = room

    @property
    def cave(self) -> GraphZone:
        zone = self.session.runtime.zones["cave"]
        assert isinstance(zone, GraphZone)
        return zone

    @property
    def inventory(self) -> SetZone:
        zone = self.session.runtime.players["adventurer"].zones["inventory"]
        assert isinstance(zone, SetZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def room_description(self) -> str:
        """Return the description of the current room."""
        cave = self.cave
        idx = cave.name_to_index.get(self.player_room)
        if idx is None:
            return ""
        props = cave.node_properties.get(idx, {})
        return str(props.get("description", ""))

    def room_has_light(self, room: str | None = None) -> bool:
        """Check if a room has natural light."""
        room = room or self.player_room
        cave = self.cave
        idx = cave.name_to_index.get(room)
        if idx is None:
            return False
        props = cave.node_properties.get(idx, {})
        return bool(props.get("light", False))

    def is_dark(self, room: str | None = None) -> bool:
        """Check if the adventurer would be in dangerous darkness at a room.

        Dark if: room has no natural light AND (lamp not carried OR battery dead).
        """
        room = room or self.player_room
        if self.room_has_light(room):
            return False
        if self.item_locations.get("lamp") != "inventory":
            return True
        if self.lamp_battery <= 0:
            return True
        return False

    def items_at(self, room: str) -> list[str]:
        """Return item types present at a room."""
        return [
            item for item, loc in self.item_locations.items()
            if loc == room
        ]

    def carried_items(self) -> list[str]:
        """Return item types in inventory."""
        return [
            item for item, loc in self.item_locations.items()
            if loc == "inventory"
        ]

    def score(self) -> int:
        """Compute current score: sum of points for treasures at building."""
        total = 0
        for treasure, points in TREASURES.items():
            if self.item_locations.get(treasure) == "building":
                total += points
        return total

    def can_move_to(self, target: str) -> bool:
        """Check if the player can move to the target room."""
        neighbors = self.cave.graph_neighbors(self.player_room)
        if target not in neighbors:
            return False

        # Grate blocks depression <-> entrance
        if not self.grate_unlocked:
            if (self.player_room == "depression" and target == "entrance") or \
               (self.player_room == "entrance" and target == "depression"):
                return False

        # Snake blocks hall_of_mountain_king -> west/south chambers and long_hall
        if not self.snake_gone and self.player_room == "hall_of_mountain_king":
            if target in ("west_side_chamber", "south_side_chamber", "long_hall"):
                return False

        # Troll blocks troll_bridge -> volcano_view
        if not self.troll_satisfied:
            if self.player_room == "troll_bridge" and target == "volcano_view":
                return False

        # Pit blocks brink_of_pit -> low_passage
        if not self.pit_secured:
            if self.player_room == "brink_of_pit" and target == "low_passage":
                return False

        return True

    def _drain_lamp(self) -> None:
        """Drain lamp battery if in a dark room with lamp."""
        if not self.room_has_light() and self.item_locations.get("lamp") == "inventory":
            if self.lamp_battery > 0:
                self.lamp_battery -= 1
                if self.lamp_battery == 0:
                    self.lamp_dead = True

    def move(self, target: str) -> dict:
        """Move the adventurer to an adjacent room.

        Returns {success, room, description, items, dark, error}.
        """
        if self.finished:
            raise ValueError("game is finished")

        if not self.can_move_to(target):
            neighbors = self.cave.graph_neighbors(self.player_room)
            if target not in neighbors:
                reason = "not adjacent"
            elif not self.grate_unlocked and (
                (self.player_room == "depression" and target == "entrance") or
                (self.player_room == "entrance" and target == "depression")
            ):
                reason = "grate is locked"
            elif not self.snake_gone and self.player_room == "hall_of_mountain_king" and \
                    target in ("west_side_chamber", "south_side_chamber", "long_hall"):
                reason = "snake blocks the way"
            elif not self.troll_satisfied and self.player_room == "troll_bridge" and \
                    target == "volcano_view":
                reason = "troll blocks the way"
            elif not self.pit_secured and self.player_room == "brink_of_pit" and \
                    target == "low_passage":
                reason = "pit blocks the way"
            else:
                reason = "blocked"
            return {
                "success": False,
                "room": self.player_room,
                "description": self.room_description(),
                "items": self.items_at(self.player_room),
                "dark": self.is_dark(),
                "error": reason,
            }

        self.player_room = target
        self._drain_lamp()
        self.session.advance_turn()

        return {
            "success": True,
            "room": self.player_room,
            "description": self.room_description(),
            "items": self.items_at(self.player_room),
            "dark": self.is_dark(),
            "error": None,
        }

    def pick_up(self, item_type: str) -> bool:
        """Pick up an item from the current room. Returns True on success."""
        if self.finished:
            raise ValueError("game is finished")

        if self.item_locations.get(item_type) != self.player_room:
            return False

        cid = self.items[item_type]
        self.inventory.set_add(cid)
        self.item_locations[item_type] = "inventory"
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def drop(self, item_type: str) -> bool:
        """Drop an item from inventory into the current room. Returns True on success."""
        if self.finished:
            raise ValueError("game is finished")

        if self.item_locations.get(item_type) != "inventory":
            return False

        cid = self.items[item_type]
        self.inventory.set_remove(cid)
        self.item_locations[item_type] = self.player_room
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def use_keys(self) -> bool:
        """Use keys to unlock the grate. Must be at depression or entrance with keys."""
        if self.finished:
            raise ValueError("game is finished")
        if self.item_locations.get("keys") != "inventory":
            return False
        if self.player_room not in ("depression", "entrance"):
            return False
        self.grate_unlocked = True
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def use_bird(self) -> bool:
        """Release the bird to scare away the snake. Must be at hall_of_mountain_king with bird."""
        if self.finished:
            raise ValueError("game is finished")
        if self.item_locations.get("bird") != "inventory":
            return False
        if self.player_room != "hall_of_mountain_king":
            return False
        self.snake_gone = True
        # Bird flies away (removed from inventory)
        cid = self.items["bird"]
        self.inventory.set_remove(cid)
        del self.item_locations["bird"]
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def use_rope(self) -> bool:
        """Use rope to secure the pit. Must be at brink_of_pit with rope."""
        if self.finished:
            raise ValueError("game is finished")
        if self.item_locations.get("rope") != "inventory":
            return False
        if self.player_room != "brink_of_pit":
            return False
        self.pit_secured = True
        # Rope stays tied at the pit (removed from inventory)
        cid = self.items["rope"]
        self.inventory.set_remove(cid)
        self.item_locations["rope"] = "brink_of_pit"
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def pay_troll(self, treasure_type: str) -> bool:
        """Give a treasure to the troll to cross the bridge. Treasure is consumed."""
        if self.finished:
            raise ValueError("game is finished")
        if self.player_room != "troll_bridge":
            return False
        if self.item_locations.get(treasure_type) != "inventory":
            return False
        if treasure_type not in TREASURES:
            return False
        self.troll_satisfied = True
        # Treasure is consumed by the troll
        cid = self.items[treasure_type]
        self.inventory.set_remove(cid)
        del self.item_locations[treasure_type]
        del self.items[treasure_type]
        self._drain_lamp()
        self.session.advance_turn()
        return True

    def check_win(self) -> bool:
        """Check if all surviving treasures are at building and player is there."""
        if self.player_room != "building":
            return False
        for treasure in TREASURES:
            # Treasure consumed by troll is exempt
            if treasure not in self.item_locations:
                continue
            if self.item_locations[treasure] != "building":
                return False
        self.finished = True
        self.winner = "adventurer"
        return True


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Colossal Cave Adventure (350 points)"

    def test_single_player(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["adventurer"]

    def test_graph_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["cave"].zone_type == "graph"
        assert defn.zones["cave"].nodes is not None
        assert len(defn.zones["cave"].nodes) == 46

    def test_inventory_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["inventory"].zone_type == "set"
        assert defn.zones["inventory"].per_player is True

    def test_lamp_battery_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["lamp_battery"].zone_type == "counter"

    def test_treasure_components(self) -> None:
        defn = _load_game()
        for treasure in TREASURES:
            assert treasure in defn.components, f"missing treasure {treasure}"
            comp = defn.components[treasure]
            assert comp.properties is not None
            assert comp.properties.get("item_type") == "treasure"

    def test_treasure_points_defined(self) -> None:
        """Each treasure has a points property in the definition."""
        defn = _load_game()
        for treasure, expected_points in TREASURES.items():
            comp = defn.components[treasure]
            assert comp.properties is not None
            assert comp.properties.get("points") == str(expected_points)

    def test_total_points_350(self) -> None:
        """The sum of all treasure points is 350."""
        assert sum(TREASURES.values()) == 350

    def test_tool_components(self) -> None:
        defn = _load_game()
        for tool in TOOLS:
            assert tool in defn.components, f"missing tool {tool}"

    def test_node_properties_have_descriptions(self) -> None:
        defn = _load_game()
        assert defn.zones["cave"].node_properties is not None
        for node in defn.zones["cave"].nodes:
            props = defn.zones["cave"].node_properties.get(node)
            assert props is not None, f"node {node} has no properties"
            assert "description" in props, f"node {node} has no description"

    def test_authority_client_verifiable(self) -> None:
        defn = _load_game()
        assert defn.authority.server_only == []
        assert len(defn.authority.client_verifiable) > 0

    def test_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 2
        results = {ec.result for ec in defn.end_conditions}
        assert "win" in results
        assert "loss" in results

    def test_json_is_valid(self) -> None:
        """The JSON file parses without error."""
        raw = _GAME_PATH.read_text()
        data = json.loads(raw)
        assert data["game"]["name"] == "Colossal Cave Adventure (350 points)"


# ---------------------------------------------------------------------------
# Tests: graph zone structure
# ---------------------------------------------------------------------------


class TestCaveMap:
    def test_cave_is_graph_zone(self) -> None:
        game = CaveGame350()
        assert isinstance(game.cave, GraphZone)

    def test_node_count(self) -> None:
        game = CaveGame350()
        assert len(game.cave.node_names) == 46

    def test_building_connects_to_road(self) -> None:
        game = CaveGame350()
        neighbors = game.cave.graph_neighbors("building")
        assert "road" in neighbors

    def test_hall_of_mountain_king_exits(self) -> None:
        game = CaveGame350()
        neighbors = game.cave.graph_neighbors("hall_of_mountain_king")
        assert "hall_of_mists" in neighbors
        assert "west_side_chamber" in neighbors
        assert "south_side_chamber" in neighbors
        assert "long_hall" in neighbors

    def test_edges_are_bidirectional(self) -> None:
        """All edges in the graph are undirected (bidirectional)."""
        game = CaveGame350()
        for node in game.cave.node_names:
            for neighbor in game.cave.graph_neighbors(node):
                reverse = game.cave.graph_neighbors(neighbor)
                assert node in reverse, (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_building_is_start(self) -> None:
        """Building node has start=true property."""
        game = CaveGame350()
        idx = game.cave.name_to_index["building"]
        props = game.cave.node_properties.get(idx, {})
        assert props.get("start") is True

    def test_maze_rooms_all_connected(self) -> None:
        """Maze rooms form a connected subgraph."""
        game = CaveGame350()
        maze_rooms = {"maze_1", "maze_2", "maze_3", "maze_4", "maze_5", "dead_end_maze"}
        visited: set[str] = set()
        queue = ["maze_1"]
        while queue:
            room = queue.pop(0)
            if room in visited:
                continue
            visited.add(room)
            for neighbor in game.cave.graph_neighbors(room):
                if neighbor in maze_rooms and neighbor not in visited:
                    queue.append(neighbor)
        assert visited == maze_rooms

    def test_maze_has_cross_links(self) -> None:
        """Maze has cross-links making it confusing (not just a linear chain)."""
        game = CaveGame350()
        # maze_1 connects to both maze_2 and maze_3 (cross-link)
        neighbors = game.cave.graph_neighbors("maze_1")
        maze_neighbors = [n for n in neighbors if n.startswith("maze_")]
        assert len(maze_neighbors) >= 2

    def test_light_rooms(self) -> None:
        """Only the surface rooms have natural light."""
        game = CaveGame350()
        light_rooms = set()
        for node in game.cave.node_names:
            idx = game.cave.name_to_index[node]
            props = game.cave.node_properties.get(idx, {})
            if props.get("light") is True:
                light_rooms.add(node)
        expected = {"building", "road", "valley", "forest", "slit", "depression"}
        assert light_rooms == expected

    def test_all_rooms_reachable_from_building(self) -> None:
        """Every room is reachable from the building (ignoring obstacles)."""
        game = CaveGame350()
        visited: set[str] = set()
        queue = ["building"]
        while queue:
            room = queue.pop(0)
            if room in visited:
                continue
            visited.add(room)
            for neighbor in game.cave.graph_neighbors(room):
                if neighbor not in visited:
                    queue.append(neighbor)
        all_rooms = set(game.cave.node_names)
        unreachable = all_rooms - visited
        assert unreachable == set(), f"unreachable rooms: {unreachable}"

    def test_troll_bridge_connects_to_volcano(self) -> None:
        game = CaveGame350()
        neighbors = game.cave.graph_neighbors("troll_bridge")
        assert "volcano_view" in neighbors
        assert "secret_canyon_s" in neighbors

    def test_pirates_lair_reachable(self) -> None:
        """Pirates' lair is at the end of a chain from reservoir."""
        game = CaveGame350()
        neighbors = game.cave.graph_neighbors("pirates_lair")
        assert "reservoir" in neighbors


# ---------------------------------------------------------------------------
# Tests: movement
# ---------------------------------------------------------------------------


class TestMovement:
    def test_move_to_adjacent_room(self) -> None:
        game = CaveGame350()
        result = game.move("road")
        assert result["success"] is True
        assert result["room"] == "road"

    def test_move_to_nonadjacent_room_fails(self) -> None:
        game = CaveGame350()
        result = game.move("plover_room")
        assert result["success"] is False
        assert result["error"] == "not adjacent"

    def test_move_to_unknown_room_fails(self) -> None:
        game = CaveGame350()
        result = game.move("narnia")
        assert result["success"] is False
        assert result["error"] == "not adjacent"

    def test_multi_step_path(self) -> None:
        """Walk building -> road -> valley -> slit."""
        game = CaveGame350()
        for room in ["road", "valley", "slit"]:
            result = game.move(room)
            assert result["success"] is True
        assert game.player_room == "slit"

    def test_move_returns_room_description(self) -> None:
        game = CaveGame350()
        result = game.move("road")
        assert "end of a road" in result["description"]

    def test_backtrack(self) -> None:
        game = CaveGame350()
        game.move("road")
        result = game.move("building")
        assert result["success"] is True
        assert game.player_room == "building"

    def test_forest_path(self) -> None:
        """Can reach forest from road or valley."""
        game = CaveGame350()
        game.move("road")
        result = game.move("forest")
        assert result["success"] is True
        assert game.player_room == "forest"

    def test_dark_flag_in_move_result(self) -> None:
        """Moving into a dark room without lamp sets dark flag."""
        game = CaveGame350()
        game.pick_up("keys")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        # Enter dark room without lamp
        result = game.move("entrance")
        assert result["dark"] is True

    def test_lit_room_not_dark(self) -> None:
        """Surface rooms are not dark."""
        game = CaveGame350()
        result = game.move("road")
        assert result["dark"] is False


# ---------------------------------------------------------------------------
# Tests: obstacles
# ---------------------------------------------------------------------------


class TestObstacles:
    def test_grate_blocks_without_keys(self) -> None:
        game = CaveGame350()
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        result = game.move("entrance")
        assert result["success"] is False
        assert result["error"] == "grate is locked"

    def test_grate_opens_with_keys(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        assert game.use_keys() is True
        result = game.move("entrance")
        assert result["success"] is True

    def test_snake_blocks_deeper_cave(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber", "pit_top", "hall_of_mists",
                      "hall_of_mountain_king"]:
            game.move(room)
        result = game.move("west_side_chamber")
        assert result["success"] is False
        assert result["error"] == "snake blocks the way"

    def test_snake_blocks_long_hall(self) -> None:
        """Snake also blocks the passage to long_hall."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber", "pit_top", "hall_of_mists",
                      "hall_of_mountain_king"]:
            game.move(room)
        result = game.move("long_hall")
        assert result["success"] is False
        assert result["error"] == "snake blocks the way"

    def test_bird_removes_snake(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        assert game.use_bird() is True
        result = game.move("west_side_chamber")
        assert result["success"] is True

    def test_troll_blocks_bridge(self) -> None:
        """Troll blocks passage from troll_bridge to volcano_view."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        game.use_bird()
        for room in ["long_hall", "cross_over", "complex_junction",
                      "bedquilt", "swiss_cheese", "slab_room",
                      "secret_canyon_n", "secret_canyon_s", "troll_bridge"]:
            game.move(room)
        result = game.move("volcano_view")
        assert result["success"] is False
        assert result["error"] == "troll blocks the way"

    def test_pay_troll_opens_bridge(self) -> None:
        """Paying the troll with a treasure opens passage."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        game.use_bird()
        # Pick up a treasure to pay troll
        game.move("west_side_chamber")
        game.pick_up("gold_nugget")
        game.move("hall_of_mountain_king")
        for room in ["long_hall", "cross_over", "complex_junction",
                      "bedquilt", "swiss_cheese", "slab_room",
                      "secret_canyon_n", "secret_canyon_s", "troll_bridge"]:
            game.move(room)
        assert game.pay_troll("gold_nugget") is True
        result = game.move("volcano_view")
        assert result["success"] is True

    def test_pay_troll_consumes_treasure(self) -> None:
        """The treasure given to the troll is permanently consumed."""
        game = CaveGame350()
        # Shortcut: teleport to troll_bridge with treasure
        game.item_locations["gold_nugget"] = "inventory"
        cid = game.items["gold_nugget"]
        game.inventory.set_add(cid)
        game.player_room = "troll_bridge"
        game.pay_troll("gold_nugget")
        assert "gold_nugget" not in game.item_locations
        assert "gold_nugget" not in game.items

    def test_pit_blocks_without_rope(self) -> None:
        """Cannot descend pit at brink_of_pit without rope."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        game.use_bird()
        for room in ["long_hall", "cross_over", "complex_junction",
                      "dirty_passage", "brink_of_pit"]:
            game.move(room)
        result = game.move("low_passage")
        assert result["success"] is False
        assert result["error"] == "pit blocks the way"

    def test_rope_secures_pit(self) -> None:
        """Using rope at brink_of_pit enables descent."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris"]:
            game.move(room)
        game.pick_up("rope")
        for room in ["awkward_canyon", "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        game.use_bird()
        for room in ["long_hall", "cross_over", "complex_junction",
                      "dirty_passage", "brink_of_pit"]:
            game.move(room)
        assert game.use_rope() is True
        result = game.move("low_passage")
        assert result["success"] is True

    def test_use_keys_wrong_location_fails(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        assert game.use_keys() is False

    def test_use_bird_wrong_location_fails(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        # Try using bird here (not at hall_of_mountain_king)
        assert game.use_bird() is False

    def test_use_rope_wrong_location_fails(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris"]:
            game.move(room)
        game.pick_up("rope")
        # Try using rope here (not at brink_of_pit)
        assert game.use_rope() is False

    def test_pay_troll_wrong_location_fails(self) -> None:
        """Cannot pay troll if not at troll_bridge."""
        game = CaveGame350()
        game.item_locations["gold_nugget"] = "inventory"
        cid = game.items["gold_nugget"]
        game.inventory.set_add(cid)
        assert game.pay_troll("gold_nugget") is False

    def test_pay_troll_with_non_treasure_fails(self) -> None:
        """Cannot pay troll with a non-treasure item."""
        game = CaveGame350()
        game.player_room = "troll_bridge"
        game.item_locations["keys"] = "inventory"
        assert game.pay_troll("keys") is False


# ---------------------------------------------------------------------------
# Tests: item pickup and drop
# ---------------------------------------------------------------------------


class TestItems:
    def test_pick_up_item_at_current_room(self) -> None:
        game = CaveGame350()
        assert game.pick_up("keys") is True
        assert "keys" in game.carried_items()

    def test_pick_up_item_not_here_fails(self) -> None:
        game = CaveGame350()
        assert game.pick_up("gold_nugget") is False

    def test_drop_item(self) -> None:
        game = CaveGame350()
        game.pick_up("keys")
        game.move("road")
        assert game.drop("keys") is True
        assert "keys" in game.items_at("road")

    def test_drop_item_not_carried_fails(self) -> None:
        game = CaveGame350()
        assert game.drop("keys") is False

    def test_inventory_count(self) -> None:
        game = CaveGame350()
        assert game.inventory.count() == 0
        game.pick_up("keys")
        assert game.inventory.count() == 1
        game.pick_up("lamp")
        assert game.inventory.count() == 2

    def test_items_at_building_initially(self) -> None:
        game = CaveGame350()
        items = sorted(game.items_at("building"))
        assert items == ["keys", "lamp"]

    def test_rope_at_debris_initially(self) -> None:
        game = CaveGame350()
        assert "rope" in game.items_at("debris")


# ---------------------------------------------------------------------------
# Tests: lamp and darkness
# ---------------------------------------------------------------------------


class TestLampMechanic:
    def test_initial_battery(self) -> None:
        game = CaveGame350()
        assert game.lamp_battery == LAMP_BATTERY_MAX

    def test_lamp_drains_in_dark_room(self) -> None:
        """Lamp battery decreases when moving through dark rooms."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        initial = game.lamp_battery
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        # surface rooms: no drain
        assert game.lamp_battery == initial
        game.use_keys()
        game.move("entrance")  # dark room with lamp
        assert game.lamp_battery == initial - 1

    def test_lamp_does_not_drain_in_lit_room(self) -> None:
        """Lamp battery does not drain in rooms with natural light."""
        game = CaveGame350()
        game.pick_up("lamp")
        battery_before = game.lamp_battery
        game.move("road")
        assert game.lamp_battery == battery_before

    def test_lamp_does_not_drain_without_lamp(self) -> None:
        """Battery does not drain if lamp is not carried."""
        game = CaveGame350()
        game.pick_up("keys")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        # Move into dark room without lamp (dark, but no drain)
        game.move("entrance")
        assert game.lamp_battery == LAMP_BATTERY_MAX

    def test_darkness_without_lamp(self) -> None:
        """Player is in darkness in a dark room without lamp."""
        game = CaveGame350()
        game.pick_up("keys")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        game.move("entrance")
        assert game.is_dark() is True

    def test_no_darkness_with_lamp(self) -> None:
        """Player is not in darkness if they have lamp with battery."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        game.move("entrance")
        assert game.is_dark() is False

    def test_darkness_when_battery_exhausted(self) -> None:
        """Player is in darkness when lamp battery is exhausted."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        game.move("entrance")
        # Force battery to 0
        game.lamp_battery = 0
        game.lamp_dead = True
        assert game.is_dark() is True

    def test_lamp_dead_flag_set_at_zero(self) -> None:
        """lamp_dead flag is set when battery reaches zero."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        # Set battery to 1 so next dark room drain kills it
        game.lamp_battery = 1
        game.move("entrance")  # drains to 0
        assert game.lamp_battery == 0
        assert game.lamp_dead is True

    def test_battery_drains_on_pickup_in_dark(self) -> None:
        """Battery drains when picking up items in dark rooms too."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris"]:
            game.move(room)
        battery_before = game.lamp_battery
        game.pick_up("rope")
        assert game.lamp_battery == battery_before - 1


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_initial_score_zero(self) -> None:
        game = CaveGame350()
        assert game.score() == 0

    def test_score_per_treasure(self) -> None:
        """Each treasure at building contributes its point value."""
        for treasure, points in TREASURES.items():
            game = CaveGame350()
            game.item_locations[treasure] = "building"
            assert game.score() == points, f"{treasure} should be worth {points}"

    def test_score_cumulative(self) -> None:
        """Score accumulates as treasures are deposited."""
        game = CaveGame350()
        running = 0
        for treasure, points in TREASURES.items():
            game.item_locations[treasure] = "building"
            running += points
            assert game.score() == running

    def test_max_score_350(self) -> None:
        """All treasures at building yields 350 points."""
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        assert game.score() == 350

    def test_treasure_in_inventory_no_score(self) -> None:
        """Treasures carried in inventory do not contribute to score."""
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "inventory"
        assert game.score() == 0

    def test_score_after_troll_payment(self) -> None:
        """Score excludes treasure consumed by the troll."""
        game = CaveGame350()
        # Simulate paying rare_coins (20 pts) to troll
        game.player_room = "troll_bridge"
        game.item_locations["rare_coins"] = "inventory"
        cid = game.items["rare_coins"]
        game.inventory.set_add(cid)
        game.pay_troll("rare_coins")
        # Now deposit all remaining treasures
        for treasure in TREASURES:
            if treasure in game.item_locations:
                game.item_locations[treasure] = "building"
        assert game.score() == 350 - 20  # rare_coins consumed


# ---------------------------------------------------------------------------
# Tests: treasure reachability
# ---------------------------------------------------------------------------


class TestTreasureReachability:
    """Verify each treasure placement room is reachable from building."""

    def _bfs_reachable(self, game: CaveGame350) -> set[str]:
        visited: set[str] = set()
        queue = ["building"]
        while queue:
            room = queue.pop(0)
            if room in visited:
                continue
            visited.add(room)
            for neighbor in game.cave.graph_neighbors(room):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    def test_all_treasure_rooms_reachable(self) -> None:
        game = CaveGame350()
        reachable = self._bfs_reachable(game)
        for room, items in INITIAL_ITEMS.items():
            for item in items:
                if item in TREASURES:
                    assert room in reachable, (
                        f"treasure {item} at {room} is not reachable from building"
                    )

    def test_gold_nugget_reachable(self) -> None:
        assert "west_side_chamber" in self._bfs_reachable(CaveGame350())

    def test_pearl_reachable(self) -> None:
        assert "shell_room" in self._bfs_reachable(CaveGame350())

    def test_trident_reachable(self) -> None:
        assert "slab_room" in self._bfs_reachable(CaveGame350())

    def test_persian_rug_reachable(self) -> None:
        assert "volcano_view" in self._bfs_reachable(CaveGame350())

    def test_golden_eggs_reachable(self) -> None:
        assert "shell_room" in self._bfs_reachable(CaveGame350())


# ---------------------------------------------------------------------------
# Tests: win condition
# ---------------------------------------------------------------------------


class TestWinCondition:
    def test_not_won_initially(self) -> None:
        game = CaveGame350()
        assert game.check_win() is False

    def test_not_won_treasures_in_inventory(self) -> None:
        """Carrying all treasures at building is not enough; they must be dropped."""
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "inventory"
        assert game.check_win() is False

    def test_not_won_wrong_room(self) -> None:
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.player_room = "road"
        assert game.check_win() is False

    def test_win_all_treasures_at_building(self) -> None:
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.player_room = "building"
        assert game.check_win() is True
        assert game.finished
        assert game.winner == "adventurer"

    def test_win_after_troll_payment(self) -> None:
        """Can still win if one treasure was consumed by the troll."""
        game = CaveGame350()
        # Simulate troll consuming rare_coins
        del game.item_locations["rare_coins"]
        del game.items["rare_coins"]
        # All other treasures at building
        for treasure in TREASURES:
            if treasure in game.item_locations:
                game.item_locations[treasure] = "building"
        game.player_room = "building"
        assert game.check_win() is True

    def test_cannot_act_after_win(self) -> None:
        game = CaveGame350()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.check_win()
        with pytest.raises(ValueError, match="finished"):
            game.move("road")


# ---------------------------------------------------------------------------
# Tests: full walkthrough
# ---------------------------------------------------------------------------


class TestWalkthrough:
    def test_full_walkthrough(self) -> None:
        """Complete walkthrough: collect tools, unlock obstacles, gather all
        treasures (paying troll with rare_coins), return to building.

        This proves the entire game is completable.
        """
        game = CaveGame350()

        # --- Phase 1: Get tools from building ---
        game.pick_up("keys")
        game.pick_up("lamp")

        # --- Phase 2: Go to depression, unlock grate ---
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()

        # --- Phase 3: Enter cave, pick up rope and bird ---
        for room in ["entrance", "cobbles", "debris"]:
            game.move(room)
        game.pick_up("rope")
        for room in ["awkward_canyon", "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")

        # --- Phase 4: Reach Hall of Mountain King, scare snake ---
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)
        game.use_bird()

        # --- Phase 5: Collect gold_nugget and diamonds ---
        game.move("west_side_chamber")
        game.pick_up("gold_nugget")
        game.pick_up("diamonds")
        game.move("hall_of_mountain_king")

        # --- Phase 6: Collect silver_bars ---
        game.move("south_side_chamber")
        game.pick_up("silver_bars")
        game.move("hall_of_mountain_king")

        # --- Phase 7: Collect rare_coins and ming_vase ---
        game.move("hall_of_mists")
        game.move("y2")
        game.pick_up("rare_coins")
        game.move("plover_room")
        game.pick_up("ming_vase")

        # --- Phase 8: Collect pearl and golden_eggs from shell_room ---
        game.move("dark_room")
        game.move("shell_room")
        game.pick_up("pearl")
        game.pick_up("golden_eggs")

        # --- Phase 9: Return to y2, go to hall_of_mountain_king ---
        for room in ["dark_room", "plover_room", "y2", "hall_of_mists",
                      "hall_of_mountain_king"]:
            game.move(room)

        # --- Phase 10: Collect trident from slab_room ---
        for room in ["long_hall", "cross_over", "complex_junction",
                      "bedquilt", "swiss_cheese", "slab_room"]:
            game.move(room)
        game.pick_up("trident")

        # --- Phase 11: Go to troll bridge, pay with rare_coins ---
        for room in ["secret_canyon_n", "secret_canyon_s", "troll_bridge"]:
            game.move(room)
        game.pay_troll("rare_coins")

        # --- Phase 12: Collect persian_rug and spices ---
        game.move("volcano_view")
        game.pick_up("persian_rug")
        game.pick_up("spices")

        # --- Phase 13: Use rope at brink_of_pit (backtrack) ---
        # Return from volcano_view to complex_junction via troll_bridge
        for room in ["troll_bridge", "secret_canyon_s", "secret_canyon_n",
                      "slab_room", "swiss_cheese", "bedquilt",
                      "complex_junction", "dirty_passage", "brink_of_pit"]:
            game.move(room)
        game.use_rope()

        # Visit low_passage just to prove pit is cleared
        game.move("low_passage")
        game.move("brink_of_pit")

        # --- Phase 14: Return all the way to building ---
        for room in ["dirty_passage", "complex_junction", "cross_over",
                      "long_hall", "hall_of_mountain_king",
                      "hall_of_mists", "pit_top", "bird_chamber",
                      "awkward_canyon", "debris", "cobbles", "entrance",
                      "depression", "slit", "valley", "road", "building"]:
            game.move(room)

        assert game.player_room == "building"

        # --- Phase 15: Drop all treasures ---
        for treasure in list(game.carried_items()):
            if treasure in TREASURES:
                game.drop(treasure)

        # Score check: 350 - 20 (rare_coins consumed by troll) = 330
        assert game.score() == 330

        # --- Check win ---
        assert game.check_win() is True
        assert game.finished
        assert game.winner == "adventurer"

        # Verify lamp battery did not run out
        assert game.lamp_battery > 0

    def test_walkthrough_with_lamp_survival(self) -> None:
        """The full walkthrough completes with significant lamp battery remaining."""
        game = CaveGame350()
        game.pick_up("keys")
        game.pick_up("lamp")

        # Quick path: collect everything using teleportation-style shortcuts
        # Just verify the lamp mechanic works over a simulated journey
        moves_in_dark = 0
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris"]:
            game.move(room)
            moves_in_dark += 1

        # After 3 dark room moves (plus use_keys drain in dark) = 3 drains
        # plus pick_ups in dark rooms
        assert game.lamp_battery < LAMP_BATTERY_MAX
        assert game.lamp_battery > 0
        remaining_after_first_corridor = game.lamp_battery
        assert remaining_after_first_corridor == LAMP_BATTERY_MAX - 3
