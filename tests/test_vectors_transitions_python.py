"""Cross-implementation state transition test vectors -- Python runner.

Reads tests/vectors/state-transitions.json and replays each test case
against the Python transition engine, verifying that observable outcomes
match the expected values in the vector file.

Both this runner and the Rust counterpart must produce identical results
for every vector.
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

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)
from baize.transition import GameEvent, apply_action

VECTORS_PATH = REPO_ROOT / "tests" / "vectors" / "state-transitions.json"


# ---------------------------------------------------------------------------
# Helpers: build engine objects from JSON vector data
# ---------------------------------------------------------------------------


def load_vectors() -> dict[str, Any]:
    raw = VECTORS_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def parse_game_definition(v: dict[str, Any]) -> GameDefinition:
    return GameDefinition.from_json(json.dumps(v))


def setup_session(
    definition: GameDefinition,
    setup: list[dict[str, Any]],
) -> GameSession:
    session = GameSession(definition)
    for item in setup:
        string_id = item["string_id"]
        component_type = item["component_type"]
        owner = item.get("owner")
        facing = item.get("facing")

        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=string_id,
                component_type=component_type,
                owner=owner,
                facing=facing,
            )
        )

        zone_name = item.get("zone")
        if zone_name is not None:
            col = item["col"]
            row = item["row"]
            zone = session.runtime.zones[zone_name]
            assert isinstance(zone, GridZone), f"zone {zone_name} is not a GridZone"
            zone.grid_set(col, row, cid)

    return session


def build_action(v: dict[str, Any]) -> Action:
    return Action(
        action_type=v["action_type"],
        component_id=v.get("component_id"),
        component_type=v.get("component_type"),
        from_pos=v.get("from"),
        to_pos=v.get("to"),
    )


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def assert_events(
    events: list[GameEvent],
    expected: list[dict[str, Any]],
    test_name: str,
    step: int,
) -> None:
    assert len(events) == len(expected), (
        f"[{test_name}] step {step}: expected {len(expected)} events, "
        f"got {len(events)}"
    )

    for i, exp in enumerate(expected):
        actual = events[i]
        assert actual.event_type == exp["event_type"], (
            f"[{test_name}] step {step}, event {i}: "
            f"event_type {actual.event_type!r} != {exp['event_type']!r}"
        )
        assert actual.player == exp["player"], (
            f"[{test_name}] step {step}, event {i}: "
            f"player {actual.player!r} != {exp['player']!r}"
        )

        if "component_id" in exp:
            assert actual.component_id == exp["component_id"], (
                f"[{test_name}] step {step}, event {i}: "
                f"component_id {actual.component_id!r} != {exp['component_id']!r}"
            )

        if "from" in exp:
            assert actual.from_pos == exp["from"], (
                f"[{test_name}] step {step}, event {i}: "
                f"from {actual.from_pos!r} != {exp['from']!r}"
            )

        if "to" in exp:
            assert actual.to_pos == exp["to"], (
                f"[{test_name}] step {step}, event {i}: "
                f"to {actual.to_pos!r} != {exp['to']!r}"
            )


def assert_board_cells(
    session: GameSession,
    expected: dict[str, Any],
    test_name: str,
    step: int,
) -> None:
    board = session.runtime.zones.get("board")
    assert board is not None, f"[{test_name}] step {step}: board zone missing"
    assert isinstance(board, GridZone)

    for coord, exp_comp in expected.items():
        parts = coord.split(",")
        col, row = int(parts[0]), int(parts[1])
        cid = board.grid_get(col, row)
        assert cid is not None, (
            f"[{test_name}] step {step}: expected component at {coord}, "
            f"found empty"
        )
        comp = session.runtime.components.get(cid)
        assert comp is not None, (
            f"[{test_name}] step {step}: component ID at {coord} not in table"
        )

        assert comp.string_id == exp_comp["id"], (
            f"[{test_name}] step {step}: component id at {coord}: "
            f"{comp.string_id!r} != {exp_comp['id']!r}"
        )
        assert comp.component_type == exp_comp["component_type"], (
            f"[{test_name}] step {step}: component_type at {coord}: "
            f"{comp.component_type!r} != {exp_comp['component_type']!r}"
        )
        if "owner" in exp_comp:
            assert comp.owner == exp_comp["owner"], (
                f"[{test_name}] step {step}: owner at {coord}: "
                f"{comp.owner!r} != {exp_comp['owner']!r}"
            )


def assert_empty_cells(
    session: GameSession,
    cells: list[str],
    test_name: str,
    step: int,
) -> None:
    board = session.runtime.zones.get("board")
    assert board is not None, f"[{test_name}] step {step}: board zone missing"
    assert isinstance(board, GridZone)

    for coord in cells:
        parts = coord.split(",")
        col, row = int(parts[0]), int(parts[1])
        assert board.grid_get(col, row) is None, (
            f"[{test_name}] step {step}: expected cell {coord} to be empty"
        )


def assert_hash_chain(
    session: GameSession,
    events: list[GameEvent],
    hash_chain: dict[str, Any],
    test_name: str,
    step: int,
) -> None:
    if "history_length" in hash_chain:
        expected_len = hash_chain["history_length"]
        assert len(session.runtime.history_hashes) == expected_len, (
            f"[{test_name}] step {step}: history_hashes length "
            f"{len(session.runtime.history_hashes)} != {expected_len}"
        )

    # All events should have a non-empty state_hash
    for event in events:
        assert event.state_hash, (
            f"[{test_name}] step {step}: event has empty state_hash"
        )

    if "prev_hash_is_null" in hash_chain:
        prev_null = hash_chain["prev_hash_is_null"]
        if events:
            first_event = events[0]
            if prev_null:
                assert first_event.prev_hash is None, (
                    f"[{test_name}] step {step}: expected prev_hash to be null"
                )
            else:
                assert first_event.prev_hash is not None, (
                    f"[{test_name}] step {step}: expected prev_hash to be non-null"
                )

    if hash_chain.get("hashes_are_distinct"):
        hashes = session.runtime.history_hashes
        if len(hashes) >= 2:
            assert hashes[-1] != hashes[-2], (
                f"[{test_name}] step {step}: last two hashes should be distinct"
            )

    if hash_chain.get("all_hashes_unique"):
        hashes = session.runtime.history_hashes
        assert len(hashes) == len(set(hashes)), (
            f"[{test_name}] step {step}: duplicate hash found in history"
        )


def assert_component_state(
    session: GameSession,
    expected: dict[str, Any],
    test_name: str,
    step: int,
) -> None:
    for string_id, exp_state in expected.items():
        comp = None
        for c in session.runtime.components:
            if c.string_id == string_id:
                comp = c
                break
        assert comp is not None, (
            f"[{test_name}] step {step}: component {string_id} not found"
        )

        if "facing" in exp_state:
            assert comp.facing == exp_state["facing"], (
                f"[{test_name}] step {step}: facing for {string_id}: "
                f"{comp.facing!r} != {exp_state['facing']!r}"
            )


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


def _vector_ids() -> list[str]:
    """Return test case names for parametrize ids."""
    data = load_vectors()
    return [tc["name"] for tc in data["test_cases"]]


def _vector_cases() -> list[dict[str, Any]]:
    """Return test case dicts."""
    data = load_vectors()
    return data["test_cases"]


@pytest.mark.parametrize("tc", _vector_cases(), ids=_vector_ids())
def test_state_transition_vector(tc: dict[str, Any]) -> None:
    name: str = tc["name"]
    definition = parse_game_definition(tc["game_definition"])
    setup: list[dict[str, Any]] = tc.get("initial_setup", [])
    actions: list[dict[str, Any]] = tc["actions"]

    session = setup_session(definition, setup)

    for step, action_entry in enumerate(actions):
        action = build_action(action_entry["action"])
        expected = action_entry["expected"]

        # Verify acting player before applying action
        if "acting_player" in expected:
            assert session.current_player() == expected["acting_player"], (
                f"[{name}] step {step}: acting_player mismatch before action"
            )

        # Apply the action
        events = apply_action(session, action)

        # Verify status
        if "status" in expected:
            assert session.runtime.status == expected["status"], (
                f"[{name}] step {step}: status "
                f"{session.runtime.status!r} != {expected['status']!r}"
            )

        # Verify next turn
        if "next_turn" in expected:
            assert session.current_player() == expected["next_turn"], (
                f"[{name}] step {step}: next_turn "
                f"{session.current_player()!r} != {expected['next_turn']!r}"
            )

        # Verify sequence
        if "sequence" in expected:
            assert session.runtime.sequence == expected["sequence"], (
                f"[{name}] step {step}: sequence "
                f"{session.runtime.sequence} != {expected['sequence']}"
            )

        # Verify move_count
        if "move_count" in expected:
            assert session.runtime.move_count == expected["move_count"], (
                f"[{name}] step {step}: move_count "
                f"{session.runtime.move_count} != {expected['move_count']}"
            )

        # Verify events
        if "events" in expected:
            assert_events(events, expected["events"], name, step)

        # Verify board cells
        if "board_cells" in expected:
            assert_board_cells(session, expected["board_cells"], name, step)

        # Verify board empty cells
        if "board_empty_cells" in expected:
            assert_empty_cells(
                session, expected["board_empty_cells"], name, step
            )

        # Verify hash chain
        if "hash_chain" in expected:
            assert_hash_chain(
                session, events, expected["hash_chain"], name, step
            )

        # Verify component state
        if "component_state" in expected:
            assert_component_state(
                session, expected["component_state"], name, step
            )
