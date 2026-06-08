"""Round-trip serialization tests -- Python runner.

Reads tests/vectors/round-trip.json and for each test case:
  1. Builds a GameSession from the embedded game definition
  2. Sets up the described state (components, placements, counters)
  3. Calls to_wire_state() to produce a GameState
  4. Serializes to JSON
  5. Parses the JSON back into a new GameState
  6. Re-serializes to JSON
  7. Asserts the two JSON outputs are structurally identical

Both this runner and the Rust counterpart must produce identical
round-trip behavior for every vector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure the Python package is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GridZone,
    SetZone,
    SlotZone,
    StackZone,
    TrackZone,
)
from baize.state import GameState

VECTORS_PATH = REPO_ROOT / "tests" / "vectors" / "round-trip.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_vectors() -> dict[str, Any]:
    raw = VECTORS_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def parse_game_definition(v: dict[str, Any]) -> GameDefinition:
    return GameDefinition.from_json(json.dumps(v))


def setup_session(tc: dict[str, Any]) -> GameSession:
    definition = parse_game_definition(tc["game_definition"])
    session = GameSession(definition)
    setup = tc["setup"]

    # Set status
    session.runtime.status = setup["status"]

    # Insert components
    cids: list[ComponentId] = []
    for comp in setup.get("components", []):
        props = comp.get("properties", {})
        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=comp["string_id"],
                component_type=comp["component_type"],
                owner=comp.get("owner"),
                facing=comp.get("facing"),
                state=comp.get("state"),
                properties=props if props else {},
            )
        )
        cids.append(cid)

    # Place components
    for placement in setup.get("placements", []):
        cid = cids[placement["component_index"]]

        if "zone" in placement:
            zone_name = placement["zone"]
            zone = session.runtime.zones[zone_name]
            if isinstance(zone, GridZone):
                col = placement["col"]
                row = placement["row"]
                zone.grid_set(col, row, cid)
            elif isinstance(zone, StackZone):
                zone.stack_push(cid)
            elif isinstance(zone, SetZone):
                zone.set_add(cid)
            elif isinstance(zone, SlotZone):
                zone.component = cid
            else:
                raise ValueError(f"unsupported zone type for placement: {type(zone)}")

        if "player_zone" in placement:
            pz = placement["player_zone"]
            player = session.runtime.players[pz["player"]]
            zone = player.zones[pz["zone"]]
            if isinstance(zone, StackZone):
                zone.stack_push(cid)
            elif isinstance(zone, SetZone):
                zone.set_add(cid)
            elif isinstance(zone, SlotZone):
                zone.component = cid
            else:
                raise ValueError(
                    f"unsupported player zone type for placement: {type(zone)}"
                )

        if "track_zone" in placement:
            tz = placement["track_zone"]
            zone = session.runtime.zones[tz["zone"]]
            assert isinstance(zone, TrackZone), (
                f"zone '{tz['zone']}' is not a TrackZone"
            )
            pos = tz["position"]
            assert pos < len(zone.positions), (
                f"track position {pos} out of range (len={len(zone.positions)})"
            )
            zone.positions[pos].append(cid)

    # Set global counters
    for k, v in setup.get("counters", {}).items():
        session.runtime.counters[k] = v

    # Set per-player counters
    for player_name, counters in setup.get("player_counters", {}).items():
        player = session.runtime.players[player_name]
        for k, v in counters.items():
            player.counters[k] = v

    # Set per-player zone counters (counter-type zones owned by players)
    for player_name, zone_counters in setup.get("player_zone_counters", {}).items():
        player = session.runtime.players[player_name]
        for zone_name, value in zone_counters.items():
            zone = player.zones[zone_name]
            assert isinstance(zone, CounterZone), (
                f"player zone '{zone_name}' is not a CounterZone"
            )
            zone.value = value

    # Set pot zone value if specified
    pot_val = setup.get("pot_zone_value")
    if pot_val is not None:
        pot_zone = session.runtime.zones.get("pot_zone")
        if pot_zone is not None and isinstance(pot_zone, CounterZone):
            pot_zone.value = pot_val

    # Advance turns
    for _ in range(setup.get("advance_turns", 0)):
        session.advance_turn()

    return session


def assert_round_trip(wire: GameState, test_name: str) -> None:
    """Serialize, parse, re-serialize, and compare at the dict level."""
    # First serialization
    json1 = wire.to_json(indent=None)

    # Parse back
    parsed = GameState.from_json(json1)

    # Second serialization
    json2 = parsed.to_json(indent=None)

    # Compare as dicts for structural equality (avoids key-order sensitivity)
    val1 = json.loads(json1)
    val2 = json.loads(json2)

    assert val1 == val2, (
        f"[{test_name}] round-trip mismatch.\n"
        f"First:  {json1}\n"
        f"Second: {json2}"
    )


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


def _vector_ids() -> list[str]:
    data = load_vectors()
    return [tc["name"] for tc in data["test_cases"]]


def _vector_cases() -> list[dict[str, Any]]:
    data = load_vectors()
    return data["test_cases"]


@pytest.mark.parametrize("tc", _vector_cases(), ids=_vector_ids())
def test_round_trip_vector(tc: dict[str, Any]) -> None:
    """Each test vector must survive a full round-trip without information loss."""
    session = setup_session(tc)
    wire = session.to_wire_state()
    assert_round_trip(wire, tc["name"])


# ---------------------------------------------------------------------------
# Individual named tests for clarity
# ---------------------------------------------------------------------------


class TestRoundTripEmpty:
    def test_empty_tic_tac_toe(self) -> None:
        data = load_vectors()
        tc = next(t for t in data["test_cases"] if t["name"] == "empty_tic_tac_toe")
        session = setup_session(tc)
        wire = session.to_wire_state()

        assert wire.status == "setup"
        assert "board" in wire.zones
        # Empty board should have no cells in the grid
        board = wire.zones["board"]
        assert hasattr(board, "cells")
        assert len(board.cells) == 0  # type: ignore[arg-type]

        assert_round_trip(wire, tc["name"])


class TestRoundTripMidGame:
    def test_mid_game_tic_tac_toe(self) -> None:
        data = load_vectors()
        tc = next(
            t for t in data["test_cases"] if t["name"] == "mid_game_tic_tac_toe"
        )
        session = setup_session(tc)
        wire = session.to_wire_state()

        assert wire.status == "in_progress"
        board = wire.zones["board"]
        assert hasattr(board, "cells")
        assert len(board.cells) == 5  # type: ignore[arg-type]

        assert_round_trip(wire, tc["name"])


class TestRoundTripChess:
    def test_chess_opening(self) -> None:
        data = load_vectors()
        tc = next(t for t in data["test_cases"] if t["name"] == "chess_opening")
        session = setup_session(tc)
        wire = session.to_wire_state()

        board = wire.zones["board"]
        assert hasattr(board, "cells")
        assert len(board.cells) == 16  # type: ignore[arg-type]

        assert_round_trip(wire, tc["name"])


class TestRoundTripCounters:
    def test_poker_like_with_counters(self) -> None:
        data = load_vectors()
        tc = next(
            t for t in data["test_cases"] if t["name"] == "poker_like_with_counters"
        )
        session = setup_session(tc)
        wire = session.to_wire_state()

        # Verify global counters
        assert wire.counters is not None
        assert "pot" in wire.counters
        assert "round" in wire.counters

        # Verify per-player counters exist
        for player in wire.players.values():
            assert player.counters is not None
            assert len(player.counters) > 0

        assert_round_trip(wire, tc["name"])


class TestRoundTripPerPlayerZones:
    def test_board_game_with_per_player_zones(self) -> None:
        data = load_vectors()
        tc = next(
            t
            for t in data["test_cases"]
            if t["name"] == "board_game_with_per_player_zones"
        )
        session = setup_session(tc)
        wire = session.to_wire_state()

        # Verify per-player zones
        for player in wire.players.values():
            assert player.zones is not None
            assert "reserve" in player.zones
            assert "power" in player.zones

        # Verify track zone has components
        track = wire.zones["score_track"]
        assert hasattr(track, "positions")
        assert len(track.positions) > 0  # type: ignore[union-attr]

        assert_round_trip(wire, tc["name"])
