"""Hash collision resistance tests for state hash computation.

Each test creates two near-identical states that differ by exactly one field
and asserts the hashes are different.
"""

from __future__ import annotations

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)


TIC_TAC_TOE_JSON = """{
    "game": { "name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [
        { "result": "win", "player": "current", "condition": "three_in_line" },
        { "result": "draw", "condition": "board_is_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def tic_tac_toe_def() -> GameDefinition:
    return GameDefinition.from_json(TIC_TAC_TOE_JSON)


def session_with_mark_at(col: int, row: int) -> GameSession:
    """Create a session and place a mark at the given position."""
    definition = tic_tac_toe_def()
    session = GameSession(definition)
    session.runtime.status = "in_progress"

    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="mark-x-0",
            component_type="mark",
            owner="X",
        )
    )

    board = session.runtime.zones["board"]
    assert isinstance(board, GridZone)
    board.grid_set(col, row, cid)

    return session


def test_different_component_position_produces_different_hash() -> None:
    s1 = session_with_mark_at(0, 0)
    s2 = session_with_mark_at(1, 0)

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing by component position must hash differently"


def test_different_component_position_row_produces_different_hash() -> None:
    s1 = session_with_mark_at(0, 0)
    s2 = session_with_mark_at(0, 1)

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing by component row must hash differently"


def test_different_turn_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())

    s2 = GameSession(tic_tac_toe_def())
    s2.advance_turn()
    # Reset sequence/move_count to isolate the turn_index change.
    s2.runtime.sequence = 0
    s2.runtime.move_count = 0

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by whose turn it is must hash differently"


def test_different_game_status_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.status = "setup"

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.status = "in_progress"

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by game status must hash differently"


def test_different_counter_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.counters["score"] = 0

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.counters["score"] = 1

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by counter value must hash differently"


def test_different_phase_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s2 = GameSession(tic_tac_toe_def())

    # TTT has no phases, so test via wire state directly.
    state1 = s1.to_wire_state()
    state1.phase = "play"
    state2 = s2.to_wire_state()
    state2.phase = "scoring"

    import blake3 as _blake3
    import json

    h1 = _blake3.blake3(
        json.dumps(state1._to_dict(), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    h2 = _blake3.blake3(
        json.dumps(state2._to_dict(), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert h1 != h2, "states differing only by phase must hash differently"


def test_different_player_score_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.players["X"].score = 10

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by player score must hash differently"


def test_different_player_active_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.players["X"].active = False

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by player active status must hash differently"


def test_different_player_counter_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.players["X"].counters["chips"] = 100

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.players["X"].counters["chips"] = 200

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by player counter must hash differently"


def test_identical_states_produce_same_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s2 = GameSession(tic_tac_toe_def())

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 == h2, "identical states must produce the same hash"


def test_hash_is_deterministic() -> None:
    session = session_with_mark_at(1, 1)

    h1 = session.compute_state_hash()
    h2 = session.compute_state_hash()
    h3 = session.compute_state_hash()
    assert h1 == h2
    assert h2 == h3


def test_different_sequence_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.sequence = 0

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.sequence = 1

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by sequence must hash differently"


def test_different_halfmove_clock_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.halfmove_clock = 0

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.halfmove_clock = 10

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by halfmove clock must hash differently"


def test_different_component_facing_produces_different_hash() -> None:
    s1 = GameSession(tic_tac_toe_def())
    s1.runtime.status = "in_progress"
    cid1 = s1.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="card-0",
            component_type="card",
            facing="face_up",
        )
    )
    board1 = s1.runtime.zones["board"]
    assert isinstance(board1, GridZone)
    board1.grid_set(0, 0, cid1)

    s2 = GameSession(tic_tac_toe_def())
    s2.runtime.status = "in_progress"
    cid2 = s2.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id="card-0",
            component_type="card",
            facing="face_down",
        )
    )
    board2 = s2.runtime.zones["board"]
    assert isinstance(board2, GridZone)
    board2.grid_set(0, 0, cid2)

    h1 = s1.compute_state_hash()
    h2 = s2.compute_state_hash()
    assert h1 != h2, "states differing only by component facing must hash differently"


def test_cross_implementation_empty_state_hash() -> None:
    """Verify the empty state hash matches the Rust implementation.

    The Rust engine produces a known hash for the initial tic-tac-toe state.
    This test ensures the Python implementation produces the same value,
    guaranteeing cross-implementation consistency.
    """
    session = GameSession(tic_tac_toe_def())
    py_hash = session.compute_state_hash()

    # This value is computed by the Rust engine for the same initial state.
    # If this test fails, the serialization format has diverged between
    # the two implementations.
    rust_hash = "2bb4c6638cd5658d3331b062d2c183dc889a915144b279b87647807c6214d903"
    assert py_hash == rust_hash, (
        f"Python hash {py_hash} does not match Rust hash {rust_hash}"
    )
