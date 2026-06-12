"""Cross-engine determinism verification.

Loads test vector JSON files from tests/vectors/ttt-*.json and replays each
game through the Python engine, verifying that the final status, result, board
state, and move count match the expected values in the vector.

The Rust engine uses the same vectors independently
(engine/tests/test_vectors_determinism.rs), so agreement between the two test
runners constitutes cross-engine determinism verification.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession, GridZone
from baize.transition import apply_action

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
VECTORS_DIR = PROJECT_ROOT / "tests" / "vectors"

VECTOR_FILES = sorted(VECTORS_DIR.glob("ttt-*.json"))


def load_vector(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_definition(vector: dict[str, Any]) -> GameDefinition:
    def_path = PROJECT_ROOT / vector["definition_file"]
    return GameDefinition.from_json(def_path.read_text(encoding="utf-8"))


def replay_game(
    definition: GameDefinition, actions: list[dict[str, Any]]
) -> GameSession:
    session = GameSession(definition)
    for act_dict in actions:
        action = Action.from_dict(act_dict)
        apply_action(session, action)
    return session


@pytest.mark.parametrize(
    "vector_path",
    VECTOR_FILES,
    ids=[p.stem for p in VECTOR_FILES],
)
def test_determinism_final_status(vector_path: pathlib.Path) -> None:
    """Final game status matches expected value."""
    vector = load_vector(vector_path)
    definition = load_definition(vector)
    session = replay_game(definition, vector["actions"])

    assert session.runtime.status == vector["expected_final_status"], (
        f"status mismatch: got {session.runtime.status!r}, "
        f"expected {vector['expected_final_status']!r}"
    )


@pytest.mark.parametrize(
    "vector_path",
    VECTOR_FILES,
    ids=[p.stem for p in VECTOR_FILES],
)
def test_determinism_result(vector_path: pathlib.Path) -> None:
    """Game result (outcome, winner, condition) matches expected."""
    vector = load_vector(vector_path)
    definition = load_definition(vector)
    session = replay_game(definition, vector["actions"])

    expected = vector["expected_result"]
    result = session.runtime.result
    assert result is not None, "expected a game result, got None"

    assert result.outcome == expected["outcome"], (
        f"outcome mismatch: got {result.outcome!r}, expected {expected['outcome']!r}"
    )

    expected_winner = expected.get("winner")
    assert result.winner == expected_winner, (
        f"winner mismatch: got {result.winner!r}, expected {expected_winner!r}"
    )

    expected_condition = expected.get("condition")
    assert result.condition == expected_condition, (
        f"condition mismatch: got {result.condition!r}, "
        f"expected {expected_condition!r}"
    )


@pytest.mark.parametrize(
    "vector_path",
    VECTOR_FILES,
    ids=[p.stem for p in VECTOR_FILES],
)
def test_determinism_board_state(vector_path: pathlib.Path) -> None:
    """Board cell contents match expected after all moves."""
    vector = load_vector(vector_path)
    definition = load_definition(vector)
    session = replay_game(definition, vector["actions"])

    expected_board = vector.get("expected_board", {})
    board = session.runtime.zones.get("board")
    assert isinstance(board, GridZone), "board zone must be a GridZone"

    for coord, expected_comp in expected_board.items():
        parts = coord.split(",")
        col, row = int(parts[0]), int(parts[1])
        cid = board.grid_get(col, row)
        assert cid is not None, (
            f"expected component at ({col},{row}), found empty"
        )
        comp = session.runtime.components.get(cid)
        assert comp is not None, (
            f"component ID at ({col},{row}) not in component table"
        )
        assert comp.component_type == expected_comp["component_type"], (
            f"component_type at ({col},{row}): "
            f"got {comp.component_type!r}, "
            f"expected {expected_comp['component_type']!r}"
        )
        assert comp.owner == expected_comp["owner"], (
            f"owner at ({col},{row}): "
            f"got {comp.owner!r}, expected {expected_comp['owner']!r}"
        )

    # Verify cells NOT in expected_board are empty
    for row in range(board.height):
        for col in range(board.width):
            coord = f"{col},{row}"
            if coord not in expected_board:
                cid = board.grid_get(col, row)
                assert cid is None, (
                    f"expected cell ({col},{row}) to be empty, "
                    f"but found component"
                )


@pytest.mark.parametrize(
    "vector_path",
    VECTOR_FILES,
    ids=[p.stem for p in VECTOR_FILES],
)
def test_determinism_move_count(vector_path: pathlib.Path) -> None:
    """Move count matches expected after all moves."""
    vector = load_vector(vector_path)
    definition = load_definition(vector)
    session = replay_game(definition, vector["actions"])

    expected_mc = vector.get("expected_move_count")
    if expected_mc is not None:
        assert session.runtime.move_count == expected_mc, (
            f"move_count mismatch: got {session.runtime.move_count}, "
            f"expected {expected_mc}"
        )
