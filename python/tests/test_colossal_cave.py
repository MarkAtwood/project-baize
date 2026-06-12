"""Tests for Colossal Cave Adventure: graph zone text adventure.

A single-player text adventure using a graph zone for the cave map.
The adventurer explores rooms, collects tools and treasures, overcomes
obstacles, and wins by returning all five treasures to the starting room.

Exercises: graph zone construction, adjacency, node properties, set zone
(inventory), component placement, movement validation, and end conditions.
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
    GraphZone,
    SetZone,
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "colossal-cave.json"

TREASURES = ["gold_nugget", "diamonds", "silver_bars", "rare_coins", "ming_vase"]
TOOLS = ["keys", "lamp", "bird"]

# Initial item placements (room -> list of item types)
INITIAL_ITEMS: dict[str, list[str]] = {
    "building": ["keys", "lamp"],
    "bird_chamber": ["bird"],
    "west_side_chamber": ["gold_nugget", "diamonds"],
    "south_side_chamber": ["silver_bars"],
    "y2": ["rare_coins"],
    "plover_room": ["ming_vase"],
}


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# CaveGame helper
# ---------------------------------------------------------------------------


class CaveGame:
    """Colossal Cave Adventure driver with graph zone movement."""

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
        desc = props.get("description", "")
        return str(desc)

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

        # Snake blocks hall_of_mountain_king -> west/south chambers
        if not self.snake_gone and self.player_room == "hall_of_mountain_king":
            if target in ("west_side_chamber", "south_side_chamber"):
                return False

        return True

    def move(self, target: str) -> dict:
        """Move the adventurer to an adjacent room.

        Returns {success, room, description, items, error}.
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
            else:
                reason = "snake blocks the way"
            return {
                "success": False,
                "room": self.player_room,
                "description": self.room_description(),
                "items": self.items_at(self.player_room),
                "error": reason,
            }

        self.player_room = target
        self.session.advance_turn()

        return {
            "success": True,
            "room": self.player_room,
            "description": self.room_description(),
            "items": self.items_at(self.player_room),
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
        self.session.advance_turn()
        return True

    def check_win(self) -> bool:
        """Check if all treasures are at the building and player is there."""
        if self.player_room != "building":
            return False
        for treasure in TREASURES:
            if self.item_locations.get(treasure) != "building":
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
        assert defn.game.name == "Colossal Cave Adventure"

    def test_single_player(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["adventurer"]

    def test_graph_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["cave"].zone_type == "graph"
        assert defn.zones["cave"].nodes is not None
        assert len(defn.zones["cave"].nodes) == 17

    def test_inventory_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["inventory"].zone_type == "set"
        assert defn.zones["inventory"].per_player is True

    def test_treasure_components(self) -> None:
        defn = _load_game()
        for treasure in TREASURES:
            assert treasure in defn.components
            comp = defn.components[treasure]
            assert comp.properties is not None
            assert comp.properties.get("item_type") == "treasure"

    def test_tool_components(self) -> None:
        defn = _load_game()
        for tool in TOOLS:
            assert tool in defn.components

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

    def test_end_condition_win(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 1
        assert defn.end_conditions[0].result == "win"


# ---------------------------------------------------------------------------
# Tests: graph zone structure
# ---------------------------------------------------------------------------


class TestCaveMap:
    def test_cave_is_graph_zone(self) -> None:
        game = CaveGame()
        assert isinstance(game.cave, GraphZone)

    def test_node_count(self) -> None:
        game = CaveGame()
        assert len(game.cave.node_names) == 17

    def test_building_connects_to_road(self) -> None:
        game = CaveGame()
        neighbors = game.cave.graph_neighbors("building")
        assert "road" in neighbors

    def test_hall_of_mountain_king_has_three_exits(self) -> None:
        game = CaveGame()
        neighbors = game.cave.graph_neighbors("hall_of_mountain_king")
        assert sorted(neighbors) == [
            "hall_of_mists", "south_side_chamber", "west_side_chamber",
        ]

    def test_edges_are_bidirectional(self) -> None:
        """All edges in the graph are undirected (bidirectional)."""
        game = CaveGame()
        for node in game.cave.node_names:
            for neighbor in game.cave.graph_neighbors(node):
                reverse = game.cave.graph_neighbors(neighbor)
                assert node in reverse, (
                    f"{node} -> {neighbor} but not {neighbor} -> {node}"
                )

    def test_plover_room_is_leaf(self) -> None:
        """Plover room connects only to y2."""
        game = CaveGame()
        neighbors = game.cave.graph_neighbors("plover_room")
        assert neighbors == ["y2"]

    def test_building_is_start(self) -> None:
        """Building node has start=true property."""
        game = CaveGame()
        idx = game.cave.name_to_index["building"]
        props = game.cave.node_properties.get(idx, {})
        assert props.get("start") is True


# ---------------------------------------------------------------------------
# Tests: movement
# ---------------------------------------------------------------------------


class TestMovement:
    def test_move_to_adjacent_room(self) -> None:
        game = CaveGame()
        result = game.move("road")
        assert result["success"] is True
        assert result["room"] == "road"
        assert game.player_room == "road"

    def test_move_to_nonadjacent_room_fails(self) -> None:
        game = CaveGame()
        result = game.move("plover_room")
        assert result["success"] is False
        assert result["error"] == "not adjacent"
        assert game.player_room == "building"

    def test_move_to_unknown_room_fails(self) -> None:
        game = CaveGame()
        result = game.move("narnia")
        assert result["success"] is False
        assert result["error"] == "not adjacent"

    def test_multi_step_path(self) -> None:
        """Walk building -> road -> valley -> slit."""
        game = CaveGame()
        for room in ["road", "valley", "slit"]:
            result = game.move(room)
            assert result["success"] is True
        assert game.player_room == "slit"

    def test_move_returns_room_description(self) -> None:
        game = CaveGame()
        result = game.move("road")
        assert "end of a road" in result["description"]

    def test_backtrack(self) -> None:
        """Move forward then back to the starting room."""
        game = CaveGame()
        game.move("road")
        result = game.move("building")
        assert result["success"] is True
        assert game.player_room == "building"


# ---------------------------------------------------------------------------
# Tests: obstacles
# ---------------------------------------------------------------------------


class TestObstacles:
    def test_grate_blocks_without_keys(self) -> None:
        """Cannot pass through the grate without unlocking it."""
        game = CaveGame()
        # Navigate to depression
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        assert game.player_room == "depression"
        result = game.move("entrance")
        assert result["success"] is False
        assert result["error"] == "grate is locked"

    def test_grate_opens_with_keys(self) -> None:
        """Using keys unlocks the grate."""
        game = CaveGame()
        game.pick_up("keys")
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        assert game.use_keys() is True
        result = game.move("entrance")
        assert result["success"] is True
        assert game.player_room == "entrance"

    def test_snake_blocks_deeper_cave(self) -> None:
        """Snake blocks passage to west and south side chambers."""
        game = CaveGame()
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

    def test_bird_removes_snake(self) -> None:
        """Using the bird at hall_of_mountain_king removes the snake."""
        game = CaveGame()
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

    def test_use_keys_wrong_location_fails(self) -> None:
        """Using keys at building (not at grate) fails."""
        game = CaveGame()
        game.pick_up("keys")
        assert game.use_keys() is False

    def test_use_bird_wrong_location_fails(self) -> None:
        """Using bird at the wrong room fails."""
        game = CaveGame()
        game.pick_up("keys")
        game.pick_up("lamp")
        # Pick up bird
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)
        game.pick_up("bird")
        # Try using bird here (not at hall_of_mountain_king)
        assert game.use_bird() is False


# ---------------------------------------------------------------------------
# Tests: item pickup and drop
# ---------------------------------------------------------------------------


class TestItems:
    def test_pick_up_item_at_current_room(self) -> None:
        game = CaveGame()
        assert game.pick_up("keys") is True
        assert "keys" in game.carried_items()
        assert "keys" not in game.items_at("building")

    def test_pick_up_item_not_here_fails(self) -> None:
        game = CaveGame()
        assert game.pick_up("gold_nugget") is False

    def test_drop_item(self) -> None:
        game = CaveGame()
        game.pick_up("keys")
        game.move("road")
        assert game.drop("keys") is True
        assert "keys" in game.items_at("road")
        assert "keys" not in game.carried_items()

    def test_drop_item_not_carried_fails(self) -> None:
        game = CaveGame()
        assert game.drop("keys") is False

    def test_inventory_count(self) -> None:
        game = CaveGame()
        assert game.inventory.count() == 0
        game.pick_up("keys")
        assert game.inventory.count() == 1
        game.pick_up("lamp")
        assert game.inventory.count() == 2

    def test_pick_up_and_drop_round_trip(self) -> None:
        """Pick up an item, move, drop it, verify it's at the new room."""
        game = CaveGame()
        game.pick_up("lamp")
        game.move("road")
        game.drop("lamp")
        assert game.items_at("road") == ["lamp"]
        assert game.items_at("building") == ["keys"]

    def test_items_at_building_initially(self) -> None:
        game = CaveGame()
        items = sorted(game.items_at("building"))
        assert items == ["keys", "lamp"]


# ---------------------------------------------------------------------------
# Tests: win condition
# ---------------------------------------------------------------------------


class TestWinCondition:
    def test_not_won_initially(self) -> None:
        game = CaveGame()
        assert game.check_win() is False

    def test_not_won_treasures_in_inventory(self) -> None:
        """Carrying all treasures at building is not enough; they must be dropped."""
        game = CaveGame()
        # Cheat: put all treasures in inventory at building
        for treasure in TREASURES:
            game.item_locations[treasure] = "inventory"
        assert game.check_win() is False

    def test_not_won_wrong_room(self) -> None:
        """All treasures at building but player elsewhere."""
        game = CaveGame()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.player_room = "road"
        assert game.check_win() is False

    def test_win_all_treasures_at_building(self) -> None:
        """Win when all 5 treasures are at building and player is there."""
        game = CaveGame()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.player_room = "building"
        assert game.check_win() is True
        assert game.finished
        assert game.winner == "adventurer"

    def test_cannot_act_after_win(self) -> None:
        """Actions raise after game is finished."""
        game = CaveGame()
        for treasure in TREASURES:
            game.item_locations[treasure] = "building"
        game.check_win()
        with pytest.raises(ValueError, match="finished"):
            game.move("road")

    def test_full_walkthrough(self) -> None:
        """Complete walkthrough: collect tools, unlock grate, scare snake,
        gather all treasures, return to building."""
        game = CaveGame()

        # Pick up tools at building
        game.pick_up("keys")
        game.pick_up("lamp")

        # Walk to depression and unlock grate
        for room in ["road", "valley", "slit", "depression"]:
            game.move(room)
        game.use_keys()

        # Enter the cave
        for room in ["entrance", "cobbles", "debris", "awkward_canyon",
                      "bird_chamber"]:
            game.move(room)

        # Pick up bird
        game.pick_up("bird")

        # Continue to hall of mountain king
        for room in ["pit_top", "hall_of_mists", "hall_of_mountain_king"]:
            game.move(room)

        # Use bird to scare snake
        game.use_bird()

        # Collect gold and diamonds from west side chamber
        game.move("west_side_chamber")
        game.pick_up("gold_nugget")
        game.pick_up("diamonds")

        # Back to hall, collect silver bars from south
        game.move("hall_of_mountain_king")
        game.move("south_side_chamber")
        game.pick_up("silver_bars")

        # Back to hall_of_mists, go to y2 for rare coins
        game.move("hall_of_mountain_king")
        game.move("hall_of_mists")
        game.move("y2")
        game.pick_up("rare_coins")

        # Go to plover room for ming vase
        game.move("plover_room")
        game.pick_up("ming_vase")

        # Return all the way to building
        for room in ["y2", "hall_of_mists", "pit_top", "bird_chamber",
                      "awkward_canyon", "debris", "cobbles", "entrance",
                      "depression", "slit", "valley", "road", "building"]:
            game.move(room)

        assert game.player_room == "building"

        # Drop all treasures
        for treasure in TREASURES:
            game.drop(treasure)

        # Check win
        assert game.check_win() is True
        assert game.finished
        assert game.winner == "adventurer"
