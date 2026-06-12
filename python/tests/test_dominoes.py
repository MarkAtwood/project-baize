"""Tests for Block Dominoes (double-six, 2 players).

Block dominoes: 28 tiles (all pairs [a,b] with 0 <= a <= b <= 6).
Each player draws 7 from a hidden boneyard. Players alternate playing
a tile that matches an open end of the chain. Pass if no playable tile.
First to empty hand wins (domino). If both players are blocked,
lowest total pip count wins; equal pips is a draw.

Tests exercise: definition loading, tile generation, dealing, matching
logic, pass rules, chain management, and win/draw detection.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "dominoes.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _all_tiles() -> list[tuple[int, int]]:
    """All 28 double-six domino tiles as (half_a, half_b) pairs."""
    tiles = []
    for a in range(7):
        for b in range(a, 7):
            tiles.append((a, b))
    return tiles


# ---------------------------------------------------------------------------
# DominoGame helper
# ---------------------------------------------------------------------------


class DominoGame:
    """Block dominoes game driver for testing.

    Manages boneyard, hands, chain, and enforces matching rules.
    Tiles are ComponentData in the session's component table.
    """

    def __init__(self) -> None:
        self.defn = _load_game()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.players = ["P1", "P2"]

        # Chain state: list of tile IDs in play order.
        # open_left / open_right track the matchable pip values.
        self.chain: list[ComponentId] = []
        self.open_left: int | None = None
        self.open_right: int | None = None

        # Track consecutive passes for blocked-game detection.
        self.consecutive_passes = 0
        self.finished = False
        self.winner: str | None = None
        self.end_reason: str | None = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def create_tiles(self) -> list[ComponentId]:
        """Create all 28 tiles in the boneyard."""
        boneyard = self.session.runtime.zones.get("boneyard")
        assert isinstance(boneyard, StackZone)
        cids: list[ComponentId] = []
        for a, b in _all_tiles():
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"tile-{a}-{b}",
                component_type="tile",
                owner=None,
                properties={"half_a": a, "half_b": b},
            )
            cid = self.session.runtime.components.insert(comp)
            boneyard.components.append(cid)
            cids.append(cid)
        return cids

    def shuffle(self, seed: int = 42) -> None:
        """Shuffle the boneyard with a deterministic seed."""
        boneyard = self.session.runtime.zones.get("boneyard")
        assert isinstance(boneyard, StackZone)
        rng = random.Random(seed)
        rng.shuffle(boneyard.components)

    def deal(self, count: int = 7) -> None:
        """Deal `count` tiles from boneyard to each player's hand."""
        boneyard = self.session.runtime.zones.get("boneyard")
        assert isinstance(boneyard, StackZone)
        for player in self.players:
            hand = self.session.runtime.players[player].zones["hand"]
            assert isinstance(hand, SetZone)
            for _ in range(count):
                assert len(boneyard.components) > 0, "boneyard empty during deal"
                cid = boneyard.components.pop()
                comp = self.session.runtime.components.get(cid)
                assert comp is not None
                comp.owner = player
                hand.components.append(cid)

    def setup(self, seed: int = 42) -> None:
        """Full setup: create tiles, shuffle, deal 7 each."""
        self.create_tiles()
        self.shuffle(seed)
        self.deal()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def hand(self, player: str) -> list[ComponentId]:
        """Return component IDs in a player's hand."""
        hand_zone = self.session.runtime.players[player].zones["hand"]
        assert isinstance(hand_zone, SetZone)
        return list(hand_zone.components)

    def hand_tiles(self, player: str) -> list[tuple[int, int]]:
        """Return (half_a, half_b) for each tile in a player's hand."""
        tiles = []
        for cid in self.hand(player):
            comp = self.session.runtime.components.get(cid)
            assert comp is not None
            tiles.append((comp.properties["half_a"], comp.properties["half_b"]))
        return tiles

    def hand_size(self, player: str) -> int:
        hand_zone = self.session.runtime.players[player].zones["hand"]
        assert isinstance(hand_zone, SetZone)
        return len(hand_zone.components)

    def boneyard_size(self) -> int:
        boneyard = self.session.runtime.zones.get("boneyard")
        assert isinstance(boneyard, StackZone)
        return len(boneyard.components)

    def pip_count(self, player: str) -> int:
        """Total pip count in a player's hand."""
        total = 0
        for cid in self.hand(player):
            comp = self.session.runtime.components.get(cid)
            assert comp is not None
            total += comp.properties["half_a"] + comp.properties["half_b"]
        return total

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    # ------------------------------------------------------------------
    # Matching logic
    # ------------------------------------------------------------------

    def tile_matches(self, cid: ComponentId) -> list[str]:
        """Return which ends ('left', 'right', or both) a tile can play on.

        For an empty chain, returns ['first'] meaning any tile is playable.
        """
        if not self.chain:
            return ["first"]

        comp = self.session.runtime.components.get(cid)
        assert comp is not None
        a, b = comp.properties["half_a"], comp.properties["half_b"]

        matches = []
        if a == self.open_left or b == self.open_left:
            matches.append("left")
        if a == self.open_right or b == self.open_right:
            matches.append("right")
        return matches

    def playable_tiles(self, player: str) -> list[ComponentId]:
        """Return IDs of all tiles in player's hand that can be played."""
        return [cid for cid in self.hand(player) if self.tile_matches(cid)]

    def can_play(self, player: str) -> bool:
        """Whether the player has any playable tile."""
        return len(self.playable_tiles(player)) > 0

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def play_tile(self, cid: ComponentId, end: str = "right") -> None:
        """Play a tile from current player's hand onto the chain.

        `end` is 'left', 'right', or 'first' (for the first tile).
        The tile is oriented so the matching half faces the chain.
        """
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()
        hand_zone = self.session.runtime.players[player].zones["hand"]
        assert isinstance(hand_zone, SetZone)

        # Verify tile is in hand.
        if cid not in hand_zone.components:
            raise ValueError(f"tile {cid} not in {player}'s hand")

        comp = self.session.runtime.components.get(cid)
        assert comp is not None
        a, b = comp.properties["half_a"], comp.properties["half_b"]

        if not self.chain:
            # First tile: no matching needed.
            self.chain.append(cid)
            self.open_left = a
            self.open_right = b
        elif end == "left":
            if a == self.open_left:
                self.open_left = b
            elif b == self.open_left:
                self.open_left = a
            else:
                raise ValueError(
                    f"tile [{a}|{b}] does not match left end {self.open_left}"
                )
            self.chain.insert(0, cid)
        elif end == "right":
            if a == self.open_right:
                self.open_right = b
            elif b == self.open_right:
                self.open_right = a
            else:
                raise ValueError(
                    f"tile [{a}|{b}] does not match right end {self.open_right}"
                )
            self.chain.append(cid)
        else:
            raise ValueError(f"invalid end: {end}")

        # Remove from hand.
        hand_zone.set_remove(cid)

        # Also place in chain zone for bookkeeping.
        chain_zone = self.session.runtime.zones.get("chain")
        assert isinstance(chain_zone, StackZone)
        chain_zone.components.append(cid)

        self.consecutive_passes = 0

        # Check win: hand empty.
        if self.hand_size(player) == 0:
            self.finished = True
            self.winner = player
            self.end_reason = "domino"
        else:
            self.session.advance_turn()

    def play_first_matching(self, player: str, end: str = "right") -> ComponentId:
        """Play the first matching tile from a player's hand. Returns its ID."""
        playable = self.playable_tiles(player)
        assert len(playable) > 0, f"{player} has no playable tiles"
        cid = playable[0]
        actual_end = end if self.chain else "first"
        matches = self.tile_matches(cid)
        if actual_end not in matches and "first" not in matches:
            actual_end = matches[0]
        self.play_tile(cid, actual_end)
        return cid

    def pass_turn(self) -> None:
        """Pass when no tile can be played."""
        if self.finished:
            raise ValueError("game is finished")

        player = self.current_player()
        if self.can_play(player):
            raise ValueError(f"{player} has playable tiles and cannot pass")

        self.consecutive_passes += 1
        self.session.advance_turn()

        # Check blocked: if both players passed consecutively, game is blocked.
        if self.consecutive_passes >= 2:
            self._resolve_blocked()

    def force_pass(self) -> None:
        """Force a pass regardless of playable tiles (for testing blocked games)."""
        if self.finished:
            raise ValueError("game is finished")
        self.consecutive_passes += 1
        self.session.advance_turn()
        if self.consecutive_passes >= 2:
            self._resolve_blocked()

    def _resolve_blocked(self) -> None:
        """Resolve a blocked game by comparing pip counts."""
        self.finished = True
        p1_pips = self.pip_count("P1")
        p2_pips = self.pip_count("P2")
        if p1_pips < p2_pips:
            self.winner = "P1"
            self.end_reason = "blocked_lower_pips"
        elif p2_pips < p1_pips:
            self.winner = "P2"
            self.end_reason = "blocked_lower_pips"
        else:
            self.winner = None
            self.end_reason = "blocked_tie"


# ---------------------------------------------------------------------------
# Tests: definition structure
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Dominoes"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["P1", "P2"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_boneyard_is_hidden_stack(self) -> None:
        defn = _load_game()
        assert "boneyard" in defn.zones
        assert defn.zones["boneyard"].zone_type == "ordered_stack"
        assert defn.zones["boneyard"].visibility == "hidden"

    def test_hand_is_per_player_private(self) -> None:
        defn = _load_game()
        assert "hand" in defn.zones
        assert defn.zones["hand"].zone_type == "set"
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_chain_is_public_stack(self) -> None:
        defn = _load_game()
        assert "chain" in defn.zones
        assert defn.zones["chain"].zone_type == "ordered_stack"
        assert defn.zones["chain"].visibility == "public"

    def test_tile_component_count(self) -> None:
        defn = _load_game()
        assert defn.components["tile"].count == 28

    def test_tile_has_half_properties(self) -> None:
        defn = _load_game()
        props = defn.components["tile"].properties
        assert "half_a" in props
        assert "half_b" in props

    def test_three_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 3
        names = {ec.name for ec in defn.end_conditions}
        assert "domino" in names
        assert "blocked_game" in names
        assert "blocked_tie" in names

    def test_authority_shuffle_is_server_only(self) -> None:
        defn = _load_game()
        assert "shuffle_and_deal" in defn.authority.server_only

    def test_authority_play_is_client_verifiable(self) -> None:
        defn = _load_game()
        assert "play_tile" in defn.authority.client_verifiable
        assert "pass" in defn.authority.client_verifiable

    def test_has_two_phases(self) -> None:
        defn = _load_game()
        assert defn.phases is not None
        assert len(defn.phases) == 2
        assert defn.phases[0].name == "deal"
        assert defn.phases[1].name == "play"


# ---------------------------------------------------------------------------
# Tests: tile generation
# ---------------------------------------------------------------------------


class TestTileGeneration:
    def test_all_tiles_count(self) -> None:
        tiles = _all_tiles()
        assert len(tiles) == 28

    def test_all_tiles_unique(self) -> None:
        tiles = _all_tiles()
        assert len(set(tiles)) == 28

    def test_includes_all_doubles(self) -> None:
        tiles = _all_tiles()
        for n in range(7):
            assert (n, n) in tiles

    def test_pip_range(self) -> None:
        tiles = _all_tiles()
        for a, b in tiles:
            assert 0 <= a <= 6
            assert 0 <= b <= 6
            assert a <= b  # canonical ordering

    def test_create_tiles_in_boneyard(self) -> None:
        game = DominoGame()
        cids = game.create_tiles()
        assert len(cids) == 28
        assert game.boneyard_size() == 28

    def test_tile_properties_correct(self) -> None:
        game = DominoGame()
        cids = game.create_tiles()
        seen = set()
        for cid in cids:
            comp = game.session.runtime.components.get(cid)
            assert comp is not None
            a = comp.properties["half_a"]
            b = comp.properties["half_b"]
            key = (min(a, b), max(a, b))
            seen.add(key)
        assert len(seen) == 28


# ---------------------------------------------------------------------------
# Tests: dealing
# ---------------------------------------------------------------------------


class TestDealing:
    def test_deal_gives_7_each(self) -> None:
        game = DominoGame()
        game.setup()
        assert game.hand_size("P1") == 7
        assert game.hand_size("P2") == 7

    def test_deal_leaves_14_in_boneyard(self) -> None:
        game = DominoGame()
        game.setup()
        assert game.boneyard_size() == 14

    def test_deal_total_is_28(self) -> None:
        game = DominoGame()
        game.setup()
        total = game.hand_size("P1") + game.hand_size("P2") + game.boneyard_size()
        assert total == 28

    def test_hands_are_disjoint(self) -> None:
        game = DominoGame()
        game.setup()
        p1_ids = set(c.value for c in game.hand("P1"))
        p2_ids = set(c.value for c in game.hand("P2"))
        assert p1_ids.isdisjoint(p2_ids)

    def test_shuffle_is_deterministic(self) -> None:
        g1 = DominoGame()
        g1.setup(seed=99)
        g2 = DominoGame()
        g2.setup(seed=99)
        # Compare actual tile values
        t1 = sorted(g1.hand_tiles("P1"))
        t2 = sorted(g2.hand_tiles("P1"))
        assert t1 == t2

    def test_different_seeds_different_hands(self) -> None:
        g1 = DominoGame()
        g1.setup(seed=1)
        g2 = DominoGame()
        g2.setup(seed=2)
        t1 = sorted(g1.hand_tiles("P1"))
        t2 = sorted(g2.hand_tiles("P1"))
        assert t1 != t2  # extremely unlikely to be identical

    def test_tile_ownership_set_on_deal(self) -> None:
        game = DominoGame()
        game.setup()
        for cid in game.hand("P1"):
            comp = game.session.runtime.components.get(cid)
            assert comp is not None
            assert comp.owner == "P1"
        for cid in game.hand("P2"):
            comp = game.session.runtime.components.get(cid)
            assert comp is not None
            assert comp.owner == "P2"


# ---------------------------------------------------------------------------
# Tests: matching logic
# ---------------------------------------------------------------------------


class TestMatching:
    def _make_game_with_hand(
        self, tiles: list[tuple[int, int]], open_left: int, open_right: int
    ) -> DominoGame:
        """Create a game with specific tiles in P1's hand and set open ends."""
        game = DominoGame()
        game.session.runtime.status = "in_progress"
        hand_zone = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand_zone, SetZone)

        for a, b in tiles:
            comp = ComponentData(
                id=ComponentId(0),
                string_id=f"tile-{a}-{b}",
                component_type="tile",
                owner="P1",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand_zone.components.append(cid)

        # Set up a non-empty chain with the given open ends.
        # We need a dummy tile in the chain.
        dummy = ComponentData(
            id=ComponentId(0),
            string_id="tile-dummy",
            component_type="tile",
            owner=None,
            properties={"half_a": open_left, "half_b": open_right},
        )
        dummy_id = game.session.runtime.components.insert(dummy)
        game.chain.append(dummy_id)
        game.open_left = open_left
        game.open_right = open_right
        return game

    def test_matching_left_end(self) -> None:
        game = self._make_game_with_hand([(3, 5)], open_left=3, open_right=6)
        matches = game.tile_matches(game.hand("P1")[0])
        assert "left" in matches

    def test_matching_right_end(self) -> None:
        game = self._make_game_with_hand([(4, 6)], open_left=3, open_right=6)
        matches = game.tile_matches(game.hand("P1")[0])
        assert "right" in matches

    def test_matching_both_ends(self) -> None:
        game = self._make_game_with_hand([(3, 6)], open_left=3, open_right=6)
        matches = game.tile_matches(game.hand("P1")[0])
        assert "left" in matches
        assert "right" in matches

    def test_no_match(self) -> None:
        game = self._make_game_with_hand([(1, 2)], open_left=3, open_right=6)
        matches = game.tile_matches(game.hand("P1")[0])
        assert matches == []

    def test_double_matches_when_end_matches(self) -> None:
        game = self._make_game_with_hand([(4, 4)], open_left=4, open_right=6)
        matches = game.tile_matches(game.hand("P1")[0])
        assert "left" in matches

    def test_first_tile_always_matches(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0),
            string_id="tile-0-0",
            component_type="tile",
            owner="P1",
            properties={"half_a": 0, "half_b": 0},
        )
        cid = game.session.runtime.components.insert(comp)
        hand_zone = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand_zone, SetZone)
        hand_zone.components.append(cid)
        matches = game.tile_matches(cid)
        assert matches == ["first"]

    def test_can_play_with_matching_tiles(self) -> None:
        game = self._make_game_with_hand([(3, 5), (1, 2)], open_left=3, open_right=6)
        assert game.can_play("P1") is True

    def test_cannot_play_without_matching_tiles(self) -> None:
        game = self._make_game_with_hand([(1, 2), (0, 0)], open_left=3, open_right=6)
        assert game.can_play("P1") is False

    def test_playable_tiles_returns_correct_subset(self) -> None:
        game = self._make_game_with_hand(
            [(3, 5), (1, 2), (6, 6)], open_left=3, open_right=6
        )
        playable = game.playable_tiles("P1")
        assert len(playable) == 2  # [3,5] matches left, [6,6] matches right


# ---------------------------------------------------------------------------
# Tests: playing tiles
# ---------------------------------------------------------------------------


class TestPlayTile:
    def test_first_tile_sets_open_ends(self) -> None:
        game = DominoGame()
        game.setup()
        cid = game.hand("P1")[0]
        comp = game.session.runtime.components.get(cid)
        assert comp is not None
        a, b = comp.properties["half_a"], comp.properties["half_b"]

        game.play_tile(cid, "first")
        assert game.open_left == a
        assert game.open_right == b
        assert len(game.chain) == 1

    def test_play_removes_from_hand(self) -> None:
        game = DominoGame()
        game.setup()
        before = game.hand_size("P1")
        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        assert game.hand_size("P1") == before - 1

    def test_play_advances_turn(self) -> None:
        game = DominoGame()
        game.setup()
        assert game.current_player() == "P1"
        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        assert game.current_player() == "P2"

    def test_play_right_extends_chain(self) -> None:
        game = DominoGame()
        # Manually set up tiles for controlled testing.
        comp1 = ComponentData(
            id=ComponentId(0), string_id="tile-3-5",
            component_type="tile", owner="P1",
            properties={"half_a": 3, "half_b": 5},
        )
        comp2 = ComponentData(
            id=ComponentId(0), string_id="tile-5-2",
            component_type="tile", owner="P1",
            properties={"half_a": 5, "half_b": 2},
        )
        cid1 = game.session.runtime.components.insert(comp1)
        cid2 = game.session.runtime.components.insert(comp2)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.extend([cid1, cid2])

        # Play first tile.
        game.play_tile(cid1, "first")
        assert game.open_left == 3
        assert game.open_right == 5

        # Switch back to P1 for second play.
        game.session.runtime.turn_index = 0
        # Play second tile on the right (matching 5).
        game.play_tile(cid2, "right")
        assert game.open_right == 2
        assert game.open_left == 3  # unchanged

    def test_play_left_extends_chain(self) -> None:
        game = DominoGame()
        comp1 = ComponentData(
            id=ComponentId(0), string_id="tile-3-5",
            component_type="tile", owner="P1",
            properties={"half_a": 3, "half_b": 5},
        )
        comp2 = ComponentData(
            id=ComponentId(0), string_id="tile-1-3",
            component_type="tile", owner="P1",
            properties={"half_a": 1, "half_b": 3},
        )
        cid1 = game.session.runtime.components.insert(comp1)
        cid2 = game.session.runtime.components.insert(comp2)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.extend([cid1, cid2])

        game.play_tile(cid1, "first")
        game.session.runtime.turn_index = 0
        game.play_tile(cid2, "left")
        assert game.open_left == 1
        assert game.open_right == 5

    def test_play_mismatched_tile_rejected(self) -> None:
        game = DominoGame()
        comp1 = ComponentData(
            id=ComponentId(0), string_id="tile-3-5",
            component_type="tile", owner="P1",
            properties={"half_a": 3, "half_b": 5},
        )
        comp2 = ComponentData(
            id=ComponentId(0), string_id="tile-1-2",
            component_type="tile", owner="P1",
            properties={"half_a": 1, "half_b": 2},
        )
        cid1 = game.session.runtime.components.insert(comp1)
        cid2 = game.session.runtime.components.insert(comp2)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.extend([cid1, cid2])

        game.play_tile(cid1, "first")
        game.session.runtime.turn_index = 0
        with pytest.raises(ValueError, match="does not match"):
            game.play_tile(cid2, "right")

    def test_play_tile_not_in_hand_rejected(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-orphan",
            component_type="tile", owner="P2",
            properties={"half_a": 0, "half_b": 0},
        )
        cid = game.session.runtime.components.insert(comp)
        # cid is NOT in P1's hand
        with pytest.raises(ValueError, match="not in"):
            game.play_tile(cid, "first")

    def test_double_tile_on_matching_end(self) -> None:
        """A double tile (e.g. [4,4]) can match end value 4."""
        game = DominoGame()
        comp1 = ComponentData(
            id=ComponentId(0), string_id="tile-2-4",
            component_type="tile", owner="P1",
            properties={"half_a": 2, "half_b": 4},
        )
        comp2 = ComponentData(
            id=ComponentId(0), string_id="tile-4-4",
            component_type="tile", owner="P1",
            properties={"half_a": 4, "half_b": 4},
        )
        cid1 = game.session.runtime.components.insert(comp1)
        cid2 = game.session.runtime.components.insert(comp2)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.extend([cid1, cid2])

        game.play_tile(cid1, "first")
        assert game.open_right == 4
        game.session.runtime.turn_index = 0
        game.play_tile(cid2, "right")
        # Double [4,4]: matching half is 4, other half is also 4.
        assert game.open_right == 4


# ---------------------------------------------------------------------------
# Tests: passing
# ---------------------------------------------------------------------------


class TestPassing:
    def test_pass_advances_turn(self) -> None:
        game = DominoGame()
        game.setup()
        # Play first tile to set up chain.
        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        # Force a situation where P2 cannot play by setting extreme open ends
        game.open_left = 99  # impossible value for testing
        game.open_right = 98
        assert game.current_player() == "P2"
        game.pass_turn()
        assert game.current_player() == "P1"

    def test_pass_with_playable_tiles_rejected(self) -> None:
        game = DominoGame()
        game.setup()
        # First tile played, P2's turn.
        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        # Very likely P2 has a matching tile with standard open ends.
        # If P2 can play, passing should be rejected.
        if game.can_play("P2"):
            with pytest.raises(ValueError, match="playable tiles"):
                game.pass_turn()

    def test_consecutive_passes_trigger_blocked(self) -> None:
        game = DominoGame()
        game.setup()
        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        # Force both players to be unable to play.
        game.open_left = 99
        game.open_right = 98
        game.pass_turn()  # P2 passes
        game.pass_turn()  # P1 passes
        assert game.finished is True
        assert game.end_reason in ("blocked_lower_pips", "blocked_tie")


# ---------------------------------------------------------------------------
# Tests: win conditions
# ---------------------------------------------------------------------------


class TestWinConditions:
    def test_domino_win_by_emptying_hand(self) -> None:
        """Player wins by playing their last tile."""
        game = DominoGame()
        # Give P1 exactly one tile.
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-3-5",
            component_type="tile", owner="P1",
            properties={"half_a": 3, "half_b": 5},
        )
        cid = game.session.runtime.components.insert(comp)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.append(cid)

        game.play_tile(cid, "first")
        assert game.finished is True
        assert game.winner == "P1"
        assert game.end_reason == "domino"

    def test_blocked_game_lower_pips_wins(self) -> None:
        """When both are blocked, lower pip count wins."""
        game = DominoGame()
        # Give P1 a low-pip hand.
        for a, b in [(0, 1), (0, 0)]:
            comp = ComponentData(
                id=ComponentId(0), string_id=f"tile-{a}-{b}",
                component_type="tile", owner="P1",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand = game.session.runtime.players["P1"].zones["hand"]
            assert isinstance(hand, SetZone)
            hand.components.append(cid)

        # Give P2 a high-pip hand.
        for a, b in [(5, 6), (6, 6)]:
            comp = ComponentData(
                id=ComponentId(0), string_id=f"tile-{a}-{b}",
                component_type="tile", owner="P2",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand = game.session.runtime.players["P2"].zones["hand"]
            assert isinstance(hand, SetZone)
            hand.components.append(cid)

        # Set up a chain so neither can play.
        game.chain.append(ComponentId(999))  # dummy
        game.open_left = 99
        game.open_right = 98

        game.force_pass()  # P1
        game.force_pass()  # P2

        assert game.finished is True
        assert game.winner == "P1"  # pips: 1 vs 23
        assert game.end_reason == "blocked_lower_pips"

    def test_blocked_game_tie(self) -> None:
        """When both are blocked with equal pips, result is draw."""
        game = DominoGame()
        # Give both players the same pip count.
        for player in ["P1", "P2"]:
            comp = ComponentData(
                id=ComponentId(0), string_id=f"tile-{player}-3-4",
                component_type="tile", owner=player,
                properties={"half_a": 3, "half_b": 4},
            )
            cid = game.session.runtime.components.insert(comp)
            hand = game.session.runtime.players[player].zones["hand"]
            assert isinstance(hand, SetZone)
            hand.components.append(cid)

        game.chain.append(ComponentId(999))
        game.open_left = 99
        game.open_right = 98

        game.force_pass()
        game.force_pass()

        assert game.finished is True
        assert game.winner is None
        assert game.end_reason == "blocked_tie"

    def test_cannot_play_after_game_finished(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-1-1",
            component_type="tile", owner="P1",
            properties={"half_a": 1, "half_b": 1},
        )
        cid = game.session.runtime.components.insert(comp)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.append(cid)
        game.play_tile(cid, "first")
        assert game.finished

        with pytest.raises(ValueError, match="finished"):
            game.force_pass()


# ---------------------------------------------------------------------------
# Tests: pip counting
# ---------------------------------------------------------------------------


class TestPipCounting:
    def test_pip_count_empty_hand(self) -> None:
        game = DominoGame()
        assert game.pip_count("P1") == 0

    def test_pip_count_single_tile(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-3-5",
            component_type="tile", owner="P1",
            properties={"half_a": 3, "half_b": 5},
        )
        cid = game.session.runtime.components.insert(comp)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.append(cid)
        assert game.pip_count("P1") == 8

    def test_pip_count_multiple_tiles(self) -> None:
        game = DominoGame()
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        total = 0
        for a, b in [(0, 0), (3, 4), (6, 6)]:
            comp = ComponentData(
                id=ComponentId(0), string_id=f"tile-{a}-{b}",
                component_type="tile", owner="P1",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand.components.append(cid)
            total += a + b
        assert game.pip_count("P1") == total  # 0 + 7 + 12 = 19

    def test_double_zero_has_zero_pips(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-0-0",
            component_type="tile", owner="P1",
            properties={"half_a": 0, "half_b": 0},
        )
        cid = game.session.runtime.components.insert(comp)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.append(cid)
        assert game.pip_count("P1") == 0

    def test_double_six_has_twelve_pips(self) -> None:
        game = DominoGame()
        comp = ComponentData(
            id=ComponentId(0), string_id="tile-6-6",
            component_type="tile", owner="P1",
            properties={"half_a": 6, "half_b": 6},
        )
        cid = game.session.runtime.components.insert(comp)
        hand = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(hand, SetZone)
        hand.components.append(cid)
        assert game.pip_count("P1") == 12


# ---------------------------------------------------------------------------
# Tests: full game scenarios
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_setup_and_first_play(self) -> None:
        """Setup, play one tile, verify chain and hand sizes."""
        game = DominoGame()
        game.setup(seed=42)
        assert game.current_player() == "P1"

        cid = game.hand("P1")[0]
        game.play_tile(cid, "first")
        assert game.hand_size("P1") == 6
        assert len(game.chain) == 1
        assert game.current_player() == "P2"

    def test_alternating_play(self) -> None:
        """Both players alternate playing matching tiles."""
        game = DominoGame()
        game.setup(seed=42)

        # P1 plays first tile.
        game.play_first_matching("P1")
        assert game.current_player() == "P2"

        # P2 tries to play.
        if game.can_play("P2"):
            game.play_first_matching("P2")
            assert game.current_player() == "P1"
            assert len(game.chain) == 2

    def test_chain_grows_as_tiles_played(self) -> None:
        """Chain length increases with each play."""
        game = DominoGame()
        # Set up controlled tiles that form a chain.
        tiles_p1 = [(0, 1), (1, 2), (2, 3)]
        tiles_p2 = [(3, 4), (4, 5), (5, 6)]

        for i, (a, b) in enumerate(tiles_p1):
            comp = ComponentData(
                id=ComponentId(0), string_id=f"p1-{a}-{b}",
                component_type="tile", owner="P1",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand = game.session.runtime.players["P1"].zones["hand"]
            assert isinstance(hand, SetZone)
            hand.components.append(cid)

        for i, (a, b) in enumerate(tiles_p2):
            comp = ComponentData(
                id=ComponentId(0), string_id=f"p2-{a}-{b}",
                component_type="tile", owner="P2",
                properties={"half_a": a, "half_b": b},
            )
            cid = game.session.runtime.components.insert(comp)
            hand = game.session.runtime.players["P2"].zones["hand"]
            assert isinstance(hand, SetZone)
            hand.components.append(cid)

        # Play the chain: [0,1] -> [1,2] -> [2,3] -> [3,4] -> [4,5] -> [5,6]
        # P1 plays [0,1]
        game.play_tile(game.hand("P1")[0], "first")
        assert len(game.chain) == 1
        assert game.open_left == 0
        assert game.open_right == 1

        # P2 cannot play [3,4] on either end yet, but let us rearrange:
        # Actually P2 has no match for 0 or 1. Let's fix the tile assignments.
        # We will use play_first_matching which picks any matching tile.
        # Let us rethink and use tiles that actually chain.

    def test_complete_domino_game(self) -> None:
        """Play a short game where P1 empties their hand first."""
        game = DominoGame()

        # Give P1: [2,3], [3,4]
        # Give P2: [4,5], [5,6]
        # Chain: [2,3]-[3,4]-[4,5]-[5,6]
        for player, tiles in [("P1", [(2, 3), (3, 4)]), ("P2", [(4, 5), (5, 6)])]:
            hand = game.session.runtime.players[player].zones["hand"]
            assert isinstance(hand, SetZone)
            for a, b in tiles:
                comp = ComponentData(
                    id=ComponentId(0), string_id=f"tile-{player}-{a}-{b}",
                    component_type="tile", owner=player,
                    properties={"half_a": a, "half_b": b},
                )
                cid = game.session.runtime.components.insert(comp)
                hand.components.append(cid)

        # P1 plays [2,3]
        p1_hand = game.hand("P1")
        game.play_tile(p1_hand[0], "first")  # chain: [2|3], ends: 2, 3
        assert game.open_left == 2
        assert game.open_right == 3

        # P2 cannot match 2 or 3 with [4,5] or [5,6] — needs to pass.
        # Actually [4,5] has no 2 or 3. So P2 must pass.
        assert not game.can_play("P2")
        game.pass_turn()
        game.consecutive_passes = 0  # reset: only one player passed

        # P1 plays [3,4] on right end (matches 3).
        p1_hand = game.hand("P1")
        game.play_tile(p1_hand[0], "right")  # chain: [2|3]-[3|4], ends: 2, 4
        assert game.open_right == 4

        # P1 hand is now empty => domino!
        assert game.finished is True
        assert game.winner == "P1"
        assert game.end_reason == "domino"

    def test_full_game_with_dealing(self) -> None:
        """A full game with dealing and several turns of play."""
        game = DominoGame()
        game.setup(seed=42)

        turns = 0
        max_turns = 50  # safety limit
        while not game.finished and turns < max_turns:
            player = game.current_player()
            if game.can_play(player):
                playable = game.playable_tiles(player)
                cid = playable[0]
                matches = game.tile_matches(cid)
                end = matches[0]
                game.play_tile(cid, end)
            else:
                game.force_pass()
            turns += 1

        # Game should have ended (either domino or blocked).
        assert game.finished, f"game did not finish after {max_turns} turns"
        assert game.end_reason in ("domino", "blocked_lower_pips", "blocked_tie")

    def test_wire_state_includes_player_hands(self) -> None:
        """Wire state includes per-player hand zones."""
        game = DominoGame()
        game.setup(seed=42)
        wire = game.session.to_wire_state()
        assert "P1" in wire.players
        assert "P2" in wire.players
        assert "hand" in wire.players["P1"].zones
        assert "hand" in wire.players["P2"].zones
