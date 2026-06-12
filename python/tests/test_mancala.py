"""Tests for Mancala (Kalah variant) game definition and engine integration.

Mancala (Kalah) rules:
  - 2 players (south, north), 6 pits each + 1 store each = 14 zones.
  - Start: 4 seeds per pit, 0 in stores (48 seeds total).
  - On your turn: pick a non-empty pit on your side, sow seeds one per pit
    counterclockwise, skipping the opponent's store.
  - Last seed in your store: take another turn.
  - Last seed in an empty pit on your side: capture that seed + opposite pit's
    seeds into your store.
  - Game ends when one side is empty. Remaining seeds go to that side's store.
  - Higher store total wins.

The engine's apply_action/advance_turn is not used directly because Mancala
requires variable-length turns (extra turns on store landing) and capture
logic. Tests use a MancalaGame helper that drives state through
session.runtime counters and execute_effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from baize.cel import try_eval_end_condition
from baize.definition import GameDefinition
from baize.end_conditions import check_end_conditions
from baize.perturber import execute_effect
from baize.runtime import CounterZone, GameSession


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANCALA_JSON = Path(__file__).resolve().parent.parent.parent / "games" / "mancala.json"

# Counterclockwise traversal order from south's perspective:
# south pits 1-6, south store, north pits 1-6, north store
_ALL_PITS = [
    "south_1", "south_2", "south_3", "south_4", "south_5", "south_6",
    "south_store",
    "north_1", "north_2", "north_3", "north_4", "north_5", "north_6",
    "north_store",
]

_SOUTH_PITS = ["south_1", "south_2", "south_3", "south_4", "south_5", "south_6"]
_NORTH_PITS = ["north_1", "north_2", "north_3", "north_4", "north_5", "north_6"]

# Mapping from each pit to the pit directly opposite (for captures).
_OPPOSITE = {
    "south_1": "north_6",
    "south_2": "north_5",
    "south_3": "north_4",
    "south_4": "north_3",
    "south_5": "north_2",
    "south_6": "north_1",
    "north_1": "south_6",
    "north_2": "south_5",
    "north_3": "south_4",
    "north_4": "south_3",
    "north_5": "south_2",
    "north_6": "south_1",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_mancala() -> GameDefinition:
    return GameDefinition.from_json(_MANCALA_JSON.read_text())


class MancalaGame:
    """Mancala (Kalah) game driver with sowing, capture, and extra-turn logic.

    All state is kept in session.runtime counters via CounterZone values.
    Each pit and store is a counter zone.
    """

    PLAYERS = ("south", "north")
    INITIAL_SEEDS = 4

    def __init__(self) -> None:
        defn = _load_mancala()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self._init_board()

    def _init_board(self) -> None:
        """Set each pit to 4 seeds and each store to 0."""
        effects: list[dict] = []
        for pit in _SOUTH_PITS + _NORTH_PITS:
            effects.append({"set_counter": {"counter": pit, "value": self.INITIAL_SEEDS}})
        effects.append({"set_counter": {"counter": "south_store", "value": 0}})
        effects.append({"set_counter": {"counter": "north_store", "value": 0}})
        execute_effect(self.session, {"sequence": effects})

    # ------------------------------------------------------------------
    # Counter accessors
    # ------------------------------------------------------------------

    def pit(self, name: str) -> int:
        """Get seed count for a named pit or store."""
        return self.session.runtime.counters.get(name, 0)

    def south_store(self) -> int:
        return self.pit("south_store")

    def north_store(self) -> int:
        return self.pit("north_store")

    def south_total(self) -> int:
        """Total seeds on south's side (pits only, not store)."""
        return sum(self.pit(p) for p in _SOUTH_PITS)

    def north_total(self) -> int:
        """Total seeds on north's side (pits only, not store)."""
        return sum(self.pit(p) for p in _NORTH_PITS)

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _set_pit(self, name: str, value: int) -> None:
        execute_effect(
            self.session,
            {"set_counter": {"counter": name, "value": value}},
        )

    def _pits_for(self, player: str) -> list[str]:
        return _SOUTH_PITS if player == "south" else _NORTH_PITS

    def _store_for(self, player: str) -> str:
        return "south_store" if player == "south" else "north_store"

    def _opponent(self, player: str) -> str:
        return "north" if player == "south" else "south"

    # ------------------------------------------------------------------
    # Sowing
    # ------------------------------------------------------------------

    def sow(self, pit_index: int) -> str:
        """Sow seeds from the given pit (1-based index on current player's side).

        Returns:
          "extra_turn" if last seed lands in current player's store,
          "capture" if a capture occurred,
          "normal" otherwise.

        Raises ValueError if pit is empty or index is out of range.
        """
        player = self.current_player()
        pits = self._pits_for(player)
        if pit_index < 1 or pit_index > 6:
            raise ValueError(f"pit_index must be 1-6, got {pit_index}")
        pit_name = pits[pit_index - 1]
        seeds = self.pit(pit_name)
        if seeds == 0:
            raise ValueError(f"pit {pit_name} is empty")

        # Pick up all seeds
        self._set_pit(pit_name, 0)

        # Build the sowing path: skip opponent's store
        opponent_store = self._store_for(self._opponent(player))
        start_idx = _ALL_PITS.index(pit_name)
        path = []
        idx = start_idx
        while len(path) < seeds:
            idx = (idx + 1) % len(_ALL_PITS)
            if _ALL_PITS[idx] == opponent_store:
                continue
            path.append(_ALL_PITS[idx])

        # Drop one seed in each pit along the path
        for target in path:
            current_val = self.pit(target)
            self._set_pit(target, current_val + 1)

        # Determine outcome based on where the last seed landed
        last_pit = path[-1]
        result = "normal"

        # Extra turn: last seed in own store
        own_store = self._store_for(player)
        if last_pit == own_store:
            result = "extra_turn"
        # Capture: last seed in empty own-side pit (now has exactly 1 seed)
        elif last_pit in self._pits_for(player) and self.pit(last_pit) == 1:
            opposite = _OPPOSITE[last_pit]
            opp_seeds = self.pit(opposite)
            if opp_seeds > 0:
                # Capture: move both the landing seed and opposite seeds to store
                captured = 1 + opp_seeds
                self._set_pit(last_pit, 0)
                self._set_pit(opposite, 0)
                store_val = self.pit(own_store)
                self._set_pit(own_store, store_val + captured)
                result = "capture"

        # Check if game is over (one side empty)
        if self._is_game_over():
            self._sweep_remaining()
            self.session.runtime.status = "finished"
        elif result != "extra_turn":
            self.session.advance_turn()

        return result

    def _is_game_over(self) -> bool:
        return self.south_total() == 0 or self.north_total() == 0

    def _sweep_remaining(self) -> None:
        """Move remaining seeds to respective stores when game ends."""
        for pit in _SOUTH_PITS:
            seeds = self.pit(pit)
            if seeds > 0:
                self._set_pit(pit, 0)
                store_val = self.pit("south_store")
                self._set_pit("south_store", store_val + seeds)
        for pit in _NORTH_PITS:
            seeds = self.pit(pit)
            if seeds > 0:
                self._set_pit(pit, 0)
                store_val = self.pit("north_store")
                self._set_pit("north_store", store_val + seeds)

    def check_winner(self) -> str | None:
        """Return winning player name if an end condition is met, else None."""
        result = check_end_conditions(self.session)
        if result is not None and result.outcome == "win":
            return result.winner
        return None

    def is_draw(self) -> bool:
        """Return True if the game ended in a draw."""
        result = check_end_conditions(self.session)
        return result is not None and result.outcome == "draw"

    def total_seeds(self) -> int:
        """Total seeds across all pits and stores (should always be 48)."""
        return (
            self.south_total()
            + self.north_total()
            + self.south_store()
            + self.north_store()
        )


# ---------------------------------------------------------------------------
# Oracle: independent seed count verification
# ---------------------------------------------------------------------------


def _expected_seeds_after_sow(
    pits: dict[str, int], player: str, pit_index: int
) -> dict[str, int]:
    """Independent oracle: compute board state after sowing from a given pit.

    Takes a flat dict of pit_name -> seed_count, returns a new dict with
    the result of sowing. Does NOT handle capture or extra turn — just the
    raw sowing. Used to cross-validate the MancalaGame sow logic.
    """
    result = dict(pits)
    own_pits = _SOUTH_PITS if player == "south" else _NORTH_PITS
    pit_name = own_pits[pit_index - 1]
    seeds = result[pit_name]
    result[pit_name] = 0

    opponent_store = "north_store" if player == "south" else "south_store"
    idx = _ALL_PITS.index(pit_name)
    for _ in range(seeds):
        idx = (idx + 1) % len(_ALL_PITS)
        while _ALL_PITS[idx] == opponent_store:
            idx = (idx + 1) % len(_ALL_PITS)
        result[_ALL_PITS[idx]] = result.get(_ALL_PITS[idx], 0) + 1
    return result


def _get_all_pits(game: MancalaGame) -> dict[str, int]:
    """Snapshot all pit/store values from a MancalaGame."""
    return {name: game.pit(name) for name in _ALL_PITS}


# ---------------------------------------------------------------------------
# Tests: definition structure
# ---------------------------------------------------------------------------


class TestMancalaDefinition:
    """mancala.json loads and has the expected structure."""

    def test_loads_without_error(self) -> None:
        defn = _load_mancala()
        assert defn.game.name == "Mancala"

    def test_two_named_players(self) -> None:
        defn = _load_mancala()
        assert defn.game.players == ["south", "north"]

    def test_perfect_information(self) -> None:
        defn = _load_mancala()
        assert defn.game.information == "perfect"

    def test_fourteen_counter_zones(self) -> None:
        defn = _load_mancala()
        counter_zones = [
            name for name, z in defn.zones.items() if z.zone_type == "counter"
        ]
        assert len(counter_zones) == 14

    def test_all_zones_are_public(self) -> None:
        defn = _load_mancala()
        for name, z in defn.zones.items():
            assert z.visibility == "public", f"zone {name} is not public"

    def test_three_end_conditions(self) -> None:
        defn = _load_mancala()
        assert len(defn.end_conditions) == 3
        names = {ec.name for ec in defn.end_conditions}
        assert names == {"south_wins", "north_wins", "draw"}

    def test_authority_client_verifiable(self) -> None:
        defn = _load_mancala()
        assert len(defn.authority.server_only) == 0
        assert len(defn.authority.client_verifiable) > 0

    def test_library_has_game_conditions(self) -> None:
        defn = _load_mancala()
        for key in ("south_side_empty", "north_side_empty", "game_over",
                     "south_wins", "north_wins", "draw"):
            assert key in defn.library, f"missing library entry: {key}"


# ---------------------------------------------------------------------------
# Tests: initial board state
# ---------------------------------------------------------------------------


class TestMancalaInitialState:
    """Board starts with 4 seeds per pit and 0 in stores."""

    def test_each_pit_has_four_seeds(self) -> None:
        game = MancalaGame()
        for pit in _SOUTH_PITS + _NORTH_PITS:
            assert game.pit(pit) == 4, f"{pit} should have 4 seeds"

    def test_stores_are_empty(self) -> None:
        game = MancalaGame()
        assert game.south_store() == 0
        assert game.north_store() == 0

    def test_total_seeds_is_48(self) -> None:
        game = MancalaGame()
        assert game.total_seeds() == 48

    def test_south_moves_first(self) -> None:
        game = MancalaGame()
        assert game.current_player() == "south"


# ---------------------------------------------------------------------------
# Tests: basic sowing
# ---------------------------------------------------------------------------


class TestBasicSowing:
    """Seeds are distributed counterclockwise one per pit."""

    def test_sow_from_south_1(self) -> None:
        """Sowing south pit 1 (4 seeds) fills south_2, south_3, south_4, south_5."""
        game = MancalaGame()
        before = _get_all_pits(game)
        expected = _expected_seeds_after_sow(before, "south", 1)

        game.sow(1)

        assert game.pit("south_1") == 0
        assert game.pit("south_2") == expected["south_2"]
        assert game.pit("south_3") == expected["south_3"]
        assert game.pit("south_4") == expected["south_4"]
        assert game.pit("south_5") == expected["south_5"]

    def test_sow_from_south_4(self) -> None:
        """Sowing south pit 4 (4 seeds) fills south_5, south_6, south_store, north_1."""
        game = MancalaGame()
        before = _get_all_pits(game)
        expected = _expected_seeds_after_sow(before, "south", 4)

        game.sow(4)

        assert game.pit("south_4") == 0
        assert game.pit("south_5") == expected["south_5"]
        assert game.pit("south_6") == expected["south_6"]
        assert game.pit("south_store") == expected["south_store"]
        assert game.pit("north_1") == expected["north_1"]

    def test_seed_conservation_after_sow(self) -> None:
        """Total seed count remains 48 after sowing."""
        game = MancalaGame()
        game.sow(3)
        assert game.total_seeds() == 48

    def test_sow_empty_pit_raises(self) -> None:
        """Sowing from an empty pit raises ValueError."""
        game = MancalaGame()
        # Empty south_1
        game._set_pit("south_1", 0)
        with pytest.raises(ValueError, match="empty"):
            game.sow(1)

    def test_sow_invalid_index_raises(self) -> None:
        """Pit index outside 1-6 raises ValueError."""
        game = MancalaGame()
        with pytest.raises(ValueError, match="pit_index"):
            game.sow(0)
        with pytest.raises(ValueError, match="pit_index"):
            game.sow(7)


# ---------------------------------------------------------------------------
# Tests: skip opponent's store
# ---------------------------------------------------------------------------


class TestSkipOpponentStore:
    """Seeds skip the opponent's store during sowing."""

    def test_south_skips_north_store(self) -> None:
        """When south sows enough seeds to wrap around, north_store is skipped."""
        game = MancalaGame()
        # Give south_6 a large count so sowing wraps past north_store
        game._set_pit("south_6", 10)
        game.sow(6)
        # After sowing 10 from south_6:
        # south_store, north_1..north_6 (7 pits), then skip north_store,
        # south_1, south_2 = 9 more pits, so 10 seeds total.
        # north_store should remain 0 (was 0, never sowed into).
        assert game.pit("north_store") == 0

    def test_north_skips_south_store(self) -> None:
        """When north sows enough seeds to wrap around, south_store is skipped."""
        game = MancalaGame()
        # Move to north's turn
        game.sow(1)  # south sows, turn passes to north
        # Give north_6 a large count
        game._set_pit("north_6", 10)
        old_south_store = game.south_store()
        game.sow(6)
        # south_store should not have changed from sowing
        assert game.south_store() == old_south_store


# ---------------------------------------------------------------------------
# Tests: extra turn
# ---------------------------------------------------------------------------


class TestExtraTurn:
    """Last seed landing in own store grants an extra turn."""

    def test_south_gets_extra_turn(self) -> None:
        """South sows from pit 4 (4 seeds -> south_5, south_6, south_store, north_1).
        Wait — that puts last seed in north_1, not store.
        Instead: sow from pit 3 with 4 seeds -> south_4, south_5, south_6, south_store.
        Wait — pit 3 has index 3, so seeds go to south_4, south_5, south_6, south_store.
        That's 4 seeds landing the last in south_store.

        Actually let's be precise. south_3 is at _ALL_PITS index 2.
        Next 4 positions: index 3 (south_4), 4 (south_5), 5 (south_6), 6 (south_store).
        Last seed lands in south_store -> extra turn.
        """
        game = MancalaGame()
        # Arrange: ensure south_3 has exactly 4 seeds (default is 4)
        assert game.pit("south_3") == 4
        result = game.sow(3)
        assert result == "extra_turn"
        assert game.current_player() == "south"

    def test_extra_turn_keeps_player(self) -> None:
        """After extra turn, it is still south's turn."""
        game = MancalaGame()
        game.sow(3)  # extra turn
        assert game.current_player() == "south"
        # South can sow again
        game.sow(1)
        # Now turn should pass to north (pit 1 has 4 seeds -> south_2..south_5, no store)
        assert game.current_player() == "north"

    def test_north_gets_extra_turn(self) -> None:
        """North gets extra turn when last seed lands in north_store."""
        game = MancalaGame()
        # South goes first (normal move, not extra turn)
        game.sow(1)  # south sows pit 1, turn passes to north
        assert game.current_player() == "north"
        # North sows pit 3 (4 seeds): north_3 is at index 9.
        # Next 4: index 10 (north_4), 11 (north_5), 12 (north_6), 13 (north_store).
        result = game.sow(3)
        assert result == "extra_turn"
        assert game.current_player() == "north"


# ---------------------------------------------------------------------------
# Tests: capture
# ---------------------------------------------------------------------------


class TestCapture:
    """Last seed in an empty own-side pit captures opposite seeds."""

    def test_south_captures_opposite(self) -> None:
        """South sows and last seed lands in empty south_2 -> capture north_5's seeds."""
        game = MancalaGame()
        # Setup: empty south_2, put 1 seed in south_1 so it lands in south_2
        game._set_pit("south_1", 1)
        game._set_pit("south_2", 0)
        # north_5 (opposite of south_2) has 4 seeds
        assert game.pit("north_5") == 4

        result = game.sow(1)

        assert result == "capture"
        # south_2 should be empty (seed was captured)
        assert game.pit("south_2") == 0
        # north_5 should be empty (seeds were captured)
        assert game.pit("north_5") == 0
        # south_store should have 1 + 4 = 5 captured seeds
        assert game.south_store() == 5

    def test_no_capture_if_opposite_empty(self) -> None:
        """Landing in empty own pit with empty opposite does not capture."""
        game = MancalaGame()
        # Setup: south_1 has 1 seed, south_2 empty, north_5 also empty
        game._set_pit("south_1", 1)
        game._set_pit("south_2", 0)
        game._set_pit("north_5", 0)

        result = game.sow(1)

        # No capture (opposite is empty) — just a normal sow
        assert result == "normal"
        assert game.pit("south_2") == 1  # seed stays

    def test_no_capture_on_opponents_side(self) -> None:
        """Landing in an empty pit on the opponent's side does not trigger capture."""
        game = MancalaGame()
        # Setup: south_6 has 2 seeds -> sow into south_store and north_1
        # Empty north_1 first
        game._set_pit("south_6", 2)
        game._set_pit("north_1", 0)
        # south_6 (opposite of north_1) still has seeds, but capture should not fire
        # because the landing pit is on north's side, not south's

        result = game.sow(6)

        # Should not be capture — north_1 is opponent's pit
        assert result != "capture"

    def test_capture_seed_conservation(self) -> None:
        """Total seeds remain 48 after a capture."""
        game = MancalaGame()
        game._set_pit("south_1", 1)
        game._set_pit("south_2", 0)
        game.sow(1)
        assert game.total_seeds() == 48


# ---------------------------------------------------------------------------
# Tests: game end conditions
# ---------------------------------------------------------------------------


class TestGameEnd:
    """Game ends when one side is empty; remaining seeds swept to store."""

    def test_game_ends_when_south_empty(self) -> None:
        """When all south pits are empty, game ends."""
        game = MancalaGame()
        # Set all south pits to 0 except south_1 which has 1
        for pit in _SOUTH_PITS:
            game._set_pit(pit, 0)
        game._set_pit("south_1", 1)
        game._set_pit("south_2", 0)

        # Sow the last seed from south_1 -> south_2 (normal move)
        # But south_2 was empty and opposite (north_5) has 4 seeds -> capture
        game.sow(1)

        # All south pits are now empty -> game over
        assert game.south_total() == 0

    def test_sweep_remaining_seeds(self) -> None:
        """When game ends, remaining seeds on non-empty side go to that side's store."""
        game = MancalaGame()
        # Setup: only south_1 has 1 seed, all other south pits empty
        for pit in _SOUTH_PITS:
            game._set_pit(pit, 0)
        game._set_pit("south_1", 1)
        # Empty south_2's opposite so no capture interferes
        game._set_pit("north_5", 0)

        # North side has seeds in pits (default 4 each for the ones we didn't touch)
        north_before = game.north_total()
        north_store_before = game.north_store()

        game.sow(1)  # south_1 -> south_2, south empty -> game ends

        # North's remaining pit seeds should be swept to north_store
        assert game.north_total() == 0
        assert game.north_store() == north_store_before + north_before
        assert game.total_seeds() == 48

    def test_winner_is_higher_store(self) -> None:
        """Player with more seeds in store wins."""
        game = MancalaGame()
        # Force end state: south has 30 in store, north has 18
        for pit in _SOUTH_PITS + _NORTH_PITS:
            game._set_pit(pit, 0)
        game._set_pit("south_store", 30)
        game._set_pit("north_store", 18)
        game.session.runtime.status = "finished"

        assert game.check_winner() == "south"

    def test_north_wins(self) -> None:
        """North wins with higher store total."""
        game = MancalaGame()
        for pit in _SOUTH_PITS + _NORTH_PITS:
            game._set_pit(pit, 0)
        game._set_pit("south_store", 20)
        game._set_pit("north_store", 28)
        game.session.runtime.status = "finished"

        assert game.check_winner() == "north"

    def test_draw(self) -> None:
        """Equal stores result in a draw."""
        game = MancalaGame()
        for pit in _SOUTH_PITS + _NORTH_PITS:
            game._set_pit(pit, 0)
        game._set_pit("south_store", 24)
        game._set_pit("north_store", 24)
        game.session.runtime.status = "finished"

        assert game.is_draw()


# ---------------------------------------------------------------------------
# Tests: CEL end condition expressions
# ---------------------------------------------------------------------------


class TestCELConditions:
    """Library CEL expressions evaluate correctly for Mancala end conditions."""

    def test_south_side_empty_true(self) -> None:
        variables = {f"south_{i}": 0 for i in range(1, 7)}
        result = try_eval_end_condition(
            variables,
            "south_1 == 0 && south_2 == 0 && south_3 == 0 && south_4 == 0 && south_5 == 0 && south_6 == 0",
        )
        assert result is True

    def test_south_side_empty_false(self) -> None:
        variables = {f"south_{i}": 0 for i in range(1, 7)}
        variables["south_3"] = 2
        result = try_eval_end_condition(
            variables,
            "south_1 == 0 && south_2 == 0 && south_3 == 0 && south_4 == 0 && south_5 == 0 && south_6 == 0",
        )
        assert result is False

    def test_south_wins_expression(self) -> None:
        variables = {
            **{f"south_{i}": 0 for i in range(1, 7)},
            **{f"north_{i}": 0 for i in range(1, 7)},
            "south_store": 30,
            "north_store": 18,
        }
        result = try_eval_end_condition(
            variables,
            "(south_1 == 0 && south_2 == 0 && south_3 == 0 && south_4 == 0 && south_5 == 0 && south_6 == 0 || north_1 == 0 && north_2 == 0 && north_3 == 0 && north_4 == 0 && north_5 == 0 && north_6 == 0) && south_store > north_store",
        )
        assert result is True

    def test_draw_expression(self) -> None:
        variables = {
            **{f"south_{i}": 0 for i in range(1, 7)},
            **{f"north_{i}": 0 for i in range(1, 7)},
            "south_store": 24,
            "north_store": 24,
        }
        result = try_eval_end_condition(
            variables,
            "(south_1 == 0 && south_2 == 0 && south_3 == 0 && south_4 == 0 && south_5 == 0 && south_6 == 0 || north_1 == 0 && north_2 == 0 && north_3 == 0 && north_4 == 0 && north_5 == 0 && north_6 == 0) && south_store == north_store",
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests: turn alternation
# ---------------------------------------------------------------------------


class TestTurnAlternation:
    """Turn passes correctly between players."""

    def test_normal_sow_passes_turn(self) -> None:
        """A normal sow (no extra turn) passes to the other player."""
        game = MancalaGame()
        assert game.current_player() == "south"
        game.sow(1)  # 4 seeds -> south_2..south_5, no store landing
        assert game.current_player() == "north"

    def test_double_extra_turn(self) -> None:
        """Two consecutive extra turns keep the same player."""
        game = MancalaGame()
        # First extra turn: sow pit 3 (4 seeds -> south_4,5,6,store)
        result1 = game.sow(3)
        assert result1 == "extra_turn"
        assert game.current_player() == "south"

        # Setup second extra turn: put 1 seed in south_6
        game._set_pit("south_6", 1)
        result2 = game.sow(6)
        # south_6 (1 seed) -> south_store: extra turn
        assert result2 == "extra_turn"
        assert game.current_player() == "south"


# ---------------------------------------------------------------------------
# Tests: full game scenario
# ---------------------------------------------------------------------------


class TestFullGame:
    """End-to-end game scenario exercising all Mancala mechanics."""

    def test_seed_conservation_throughout_game(self) -> None:
        """Seeds are conserved across multiple moves including captures."""
        game = MancalaGame()
        assert game.total_seeds() == 48

        game.sow(3)  # south extra turn
        assert game.total_seeds() == 48

        game.sow(1)  # south normal
        assert game.total_seeds() == 48

        game.sow(3)  # north extra turn
        assert game.total_seeds() == 48

        game.sow(1)  # north normal
        assert game.total_seeds() == 48

    def test_complete_game_to_finish(self) -> None:
        """Play a game to completion and verify a winner is determined.

        Strategy: south and north alternate simple moves until the game ends.
        We play greedily — always pick the lowest-index non-empty pit.
        """
        game = MancalaGame()
        moves = 0
        max_moves = 200  # Safety limit

        while game.session.runtime.status != "finished" and moves < max_moves:
            player = game.current_player()
            pits = game._pits_for(player)
            # Find first non-empty pit
            chosen = None
            for i, pit in enumerate(pits, 1):
                if game.pit(pit) > 0:
                    chosen = i
                    break
            if chosen is None:
                # All pits empty — game should have ended
                break
            game.sow(chosen)
            moves += 1
            assert game.total_seeds() == 48, f"seed leak at move {moves}"

        assert game.session.runtime.status == "finished"
        assert game.total_seeds() == 48
        # Winner or draw must be determined
        winner = game.check_winner()
        draw = game.is_draw()
        assert winner is not None or draw, "game must have a winner or be a draw"

    def test_known_opening_sequence(self) -> None:
        """Verify a specific opening sequence produces expected board state.

        Opening: south sows pit 4 (4 seeds).
        south_4 (index 3) -> south_5, south_6, south_store, north_1.

        Expected after move:
          south: [4, 4, 4, 0, 5, 5]  store: 1
          north: [5, 4, 4, 4, 4, 4]  store: 0
        """
        game = MancalaGame()
        game.sow(4)

        assert game.pit("south_1") == 4
        assert game.pit("south_2") == 4
        assert game.pit("south_3") == 4
        assert game.pit("south_4") == 0
        assert game.pit("south_5") == 5
        assert game.pit("south_6") == 5
        assert game.south_store() == 1
        assert game.pit("north_1") == 5
        assert game.pit("north_2") == 4
        assert game.pit("north_3") == 4
        assert game.pit("north_4") == 4
        assert game.pit("north_5") == 4
        assert game.pit("north_6") == 4
        assert game.north_store() == 0

    def test_wraparound_sow(self) -> None:
        """Sowing a large pit wraps around past the opponent's store correctly."""
        game = MancalaGame()
        # Give south_1 many seeds to force wraparound
        game._set_pit("south_1", 13)
        # 13 seeds from south_1 (index 0):
        # south_2(1), south_3(2), south_4(3), south_5(4), south_6(5),
        # south_store(6), north_1(7), north_2(8), north_3(9), north_4(10),
        # north_5(11), north_6(12), skip north_store, south_1(13)
        game.sow(1)

        # south_1 should have gotten 1 seed from wraparound (started at 4, emptied, +1 = 1)
        # Actually original south_1 was set to 13 and emptied. It gets 1 back from wraparound.
        assert game.pit("south_1") == 1
        assert game.pit("north_store") == 0  # skipped

        # Verify all 13 seeds were distributed (plus the existing seeds)
        assert game.total_seeds() == 48 + 9  # we added 9 extra seeds (13 - 4 original)

    def test_opposite_pit_mapping(self) -> None:
        """Verify the opposite pit mapping is symmetric and correct."""
        assert _OPPOSITE["south_1"] == "north_6"
        assert _OPPOSITE["south_6"] == "north_1"
        assert _OPPOSITE["north_1"] == "south_6"
        assert _OPPOSITE["north_6"] == "south_1"
        # Symmetry check
        for pit, opp in _OPPOSITE.items():
            assert _OPPOSITE[opp] == pit, f"opposite mapping not symmetric for {pit}"
