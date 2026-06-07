"""Cross-implementation legal move test vectors.

Reads tests/vectors/legal-moves.json and validates each test case against the
Python move generator, ensuring parity with the Rust engine.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any

import pytest

from baize.definition import GameDefinition
from baize.moves import legal_moves
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)

VECTORS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "vectors"
    / "legal-moves.json"
)


@dataclass(frozen=True, order=True)
class ExpectedMove:
    component: str
    from_cell: str
    to_cell: str


def load_test_cases() -> list[dict[str, Any]]:
    content = VECTORS_PATH.read_text(encoding="utf-8")
    suite = json.loads(content)
    return suite["test_cases"]


def setup_session(tc: dict[str, Any]) -> GameSession:
    """Build a GameSession from a test case dict."""
    def_json = json.dumps(tc["game_definition"])
    definition = GameDefinition.from_json(def_json)
    session = GameSession(definition)

    # Advance turn_index until current_player matches
    target = tc["current_player"]
    max_players = len(session.runtime.players)
    for _ in range(max_players):
        if session.current_player() == target:
            break
        session.runtime.turn_index = (
            (session.runtime.turn_index + 1) % max_players
        )
    assert session.current_player() == target, (
        f"could not set current player to '{target}'"
    )

    board = session.runtime.zones.get("board")
    assert isinstance(board, GridZone), "zone 'board' must be a GridZone"

    for p in tc["setup"]:
        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=p["string_id"],
                component_type=p["component_type"],
                owner=p["owner"],
            )
        )
        board.grid_set(p["col"], p["row"], cid)

    return session


def extract_move(
    session: GameSession, m: Any
) -> ExpectedMove:
    """Convert an engine LegalMove to an ExpectedMove for comparison."""
    comp = session.runtime.components.get(m.component_id)
    assert comp is not None

    from_pos = m.action.from_pos
    to_pos = m.action.to_pos

    if isinstance(from_pos, dict):
        from_cell = from_pos.get("cell", "")
    elif isinstance(from_pos, str):
        from_cell = from_pos
    else:
        from_cell = ""

    if isinstance(to_pos, dict):
        to_cell = to_pos.get("cell", "")
    elif isinstance(to_pos, str):
        to_cell = to_pos
    else:
        to_cell = ""

    return ExpectedMove(
        component=comp.string_id,
        from_cell=from_cell,
        to_cell=to_cell,
    )


TEST_CASES = load_test_cases()


@pytest.mark.parametrize(
    "tc",
    TEST_CASES,
    ids=[tc["name"] for tc in TEST_CASES],
)
def test_cross_implementation_legal_moves(tc: dict[str, Any]) -> None:
    session = setup_session(tc)
    moves = legal_moves(session)

    actual = sorted(extract_move(session, m) for m in moves)

    expected = sorted(
        ExpectedMove(
            component=em["component"],
            from_cell=em["from"],
            to_cell=em["to"],
        )
        for em in tc["expected_moves"]
    )

    assert len(actual) == tc["expected_move_count"], (
        f"expected {tc['expected_move_count']} moves, got {len(actual)}.\n"
        f"Actual: {actual}"
    )

    assert actual == expected, (
        f"moves do not match.\n"
        f"Expected: {expected}\n"
        f"Actual: {actual}"
    )
