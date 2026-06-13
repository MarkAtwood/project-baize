"""Tests for the valid_cells mask feature on grid zones.

The valid_cells mask allows grids to have irregular shapes — only cells
listed in the mask are usable. Masked-out cells behave as if they don't
exist: get returns None, set is a no-op, movement skips them.
"""

from __future__ import annotations

import json

from baize.definition import GameDefinition, Zone
from baize.moves import _adjacent_directions, legal_moves
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
    runtime_zone_from_definition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid(
    width: int,
    height: int,
    valid_cells: set[int] | None = None,
) -> GridZone:
    """Create a GridZone with the given dimensions and optional mask."""
    return GridZone(
        width=width,
        height=height,
        cells=[None] * (width * height),
        valid_cells=valid_cells,
    )


def _cid(n: int) -> ComponentId:
    return ComponentId(n)


def _cross_mask_5x5() -> set[int]:
    """A cross-shaped mask on a 5x5 grid.

    Valid cells (col, row):
      row 0:         (2,0)
      row 1:   (1,1) (2,1) (3,1)
      row 2: (0,2) (1,2) (2,2) (3,2) (4,2)
      row 3:   (1,3) (2,3) (3,3)
      row 4:         (2,4)

    Flat indices for width=5: row * 5 + col
    """
    coords = [
        (2, 0),
        (1, 1), (2, 1), (3, 1),
        (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),
        (1, 3), (2, 3), (3, 3),
        (2, 4),
    ]
    return {r * 5 + c for c, r in coords}


def _cross_session() -> GameSession:
    """Build a minimal game session with a 5x5 cross-shaped board.

    Uses step movement with distance=1 for the piece type.
    """
    cross_coords = [
        [2, 0],
        [1, 1], [2, 1], [3, 1],
        [0, 2], [1, 2], [2, 2], [3, 2], [4, 2],
        [1, 3], [2, 3], [3, 3],
        [2, 4],
    ]
    raw = {
        "game": {
            "name": "CrossTest",
            "players": ["white", "black"],
            "information": "perfect",
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [5, 5],
                "visibility": "public",
                "valid_cells": cross_coords,
            },
        },
        "components": {
            "piece": {
                "owner": "per_player",
                "count": 1,
                "movement": [
                    {"primitive": "step", "distance": 1},
                ],
            },
            "hopper": {
                "owner": "per_player",
                "count": 1,
                "movement": [
                    {"primitive": "hop"},
                ],
            },
        },
        "turn_order": {
            "type": "alternating",
            "players": ["white", "black"],
            "actions_per_turn": 1,
            "mandatory": True,
        },
        "end_conditions": [
            {"result": "draw", "condition": "all_cells_occupied"},
        ],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    defn = GameDefinition.from_json(json.dumps(raw), validate_schema=False)
    session = GameSession(defn)
    session.runtime.status = "in_progress"
    return session


def _place(
    session: GameSession,
    comp_type: str,
    owner: str,
    col: int,
    row: int,
) -> ComponentId:
    """Insert a component and place it on the board grid."""
    seq = len(session.runtime.components)
    cid = session.runtime.components.insert(
        ComponentData(
            id=ComponentId(0),
            string_id=f"{comp_type}-{owner}-{seq}",
            component_type=comp_type,
            owner=owner,
        )
    )
    zone = session.runtime.zones["board"]
    assert isinstance(zone, GridZone)
    zone.grid_set(col, row, cid)
    return cid


# ---------------------------------------------------------------------------
# 1. GridZone._cell_valid
# ---------------------------------------------------------------------------


def test_cell_valid_no_mask_in_bounds() -> None:
    """Without valid_cells, all in-bounds cells are valid."""
    grid = _make_grid(4, 3)
    for row in range(3):
        for col in range(4):
            assert grid._cell_valid(col, row) is True


def test_cell_valid_no_mask_out_of_bounds() -> None:
    """Out-of-bounds cells are always invalid, even without a mask."""
    grid = _make_grid(4, 3)
    assert grid._cell_valid(-1, 0) is False
    assert grid._cell_valid(0, -1) is False
    assert grid._cell_valid(4, 0) is False
    assert grid._cell_valid(0, 3) is False
    assert grid._cell_valid(10, 10) is False


def test_cell_valid_with_mask() -> None:
    """With valid_cells set, only listed cells are valid."""
    # 3x3 grid, only diagonal cells valid: (0,0), (1,1), (2,2)
    mask = {0 * 3 + 0, 1 * 3 + 1, 2 * 3 + 2}  # indices 0, 4, 8
    grid = _make_grid(3, 3, valid_cells=mask)

    assert grid._cell_valid(0, 0) is True
    assert grid._cell_valid(1, 1) is True
    assert grid._cell_valid(2, 2) is True

    # Non-diagonal in-bounds cells are masked out
    assert grid._cell_valid(1, 0) is False
    assert grid._cell_valid(0, 1) is False
    assert grid._cell_valid(2, 0) is False
    assert grid._cell_valid(0, 2) is False


def test_cell_valid_mask_out_of_bounds() -> None:
    """Out-of-bounds cells are invalid even with a permissive mask."""
    mask = {0, 1, 2, 3, 4, 5, 6, 7, 8}  # all cells of a 3x3
    grid = _make_grid(3, 3, valid_cells=mask)

    assert grid._cell_valid(-1, 0) is False
    assert grid._cell_valid(3, 0) is False
    assert grid._cell_valid(0, 3) is False


# ---------------------------------------------------------------------------
# 2. grid_get / grid_set with mask
# ---------------------------------------------------------------------------


def test_grid_set_masked_out_is_noop() -> None:
    """grid_set on a masked-out cell returns None and does not modify storage."""
    mask = {0}  # only (0,0) is valid in a 3x3
    grid = _make_grid(3, 3, valid_cells=mask)

    result = grid.grid_set(1, 1, _cid(42))
    assert result is None
    # Underlying storage at index 4 should still be None
    assert grid.cells[1 * 3 + 1] is None


def test_grid_get_masked_out_returns_none() -> None:
    """grid_get on a masked-out cell returns None even if storage has data."""
    mask = {0}  # only (0,0) is valid
    grid = _make_grid(3, 3, valid_cells=mask)

    # Manually inject data into underlying storage at a masked-out cell
    grid.cells[1 * 3 + 1] = _cid(99)

    # grid_get should respect the mask and return None
    assert grid.grid_get(1, 1) is None


def test_grid_set_valid_cell_works() -> None:
    """grid_set on a valid cell works normally."""
    mask = {0, 4}  # (0,0) and (1,1) in a 3x3
    grid = _make_grid(3, 3, valid_cells=mask)

    prev = grid.grid_set(0, 0, _cid(10))
    assert prev is None  # was empty

    got = grid.grid_get(0, 0)
    assert got is not None
    assert got == _cid(10)

    # Overwrite
    prev2 = grid.grid_set(0, 0, _cid(20))
    assert prev2 == _cid(10)
    assert grid.grid_get(0, 0) == _cid(20)


# ---------------------------------------------------------------------------
# 3. grid_push / grid_pop with mask
# ---------------------------------------------------------------------------


def test_grid_push_masked_out_is_noop() -> None:
    """Push onto a masked-out cell does nothing."""
    mask = {0}
    grid = _make_grid(3, 3, valid_cells=mask)

    grid.grid_push(1, 1, _cid(5))
    assert grid.cells[1 * 3 + 1] is None
    assert (1 * 3 + 1) not in grid.stacks


def test_grid_pop_masked_out_returns_none() -> None:
    """Pop from a masked-out cell returns None."""
    mask = {0}
    grid = _make_grid(3, 3, valid_cells=mask)

    # Manually inject data at masked-out cell
    grid.cells[1 * 3 + 1] = _cid(5)

    result = grid.grid_pop(1, 1)
    assert result is None
    # Storage was not modified by pop (mask blocked it)
    assert grid.cells[1 * 3 + 1] == _cid(5)


def test_grid_push_pop_valid_cell() -> None:
    """Push and pop on a valid cell work normally."""
    mask = {4}  # only (1,1) in a 3x3
    grid = _make_grid(3, 3, valid_cells=mask)
    grid.stacking_limit = 0  # unlimited stacking for push/pop test

    grid.grid_push(1, 1, _cid(10))
    assert grid.grid_get(1, 1) == _cid(10)

    grid.grid_push(1, 1, _cid(20))
    assert grid.grid_get(1, 1) == _cid(20)

    popped = grid.grid_pop(1, 1)
    assert popped == _cid(20)
    assert grid.grid_get(1, 1) == _cid(10)

    popped2 = grid.grid_pop(1, 1)
    assert popped2 == _cid(10)
    assert grid.grid_get(1, 1) is None


# ---------------------------------------------------------------------------
# 4. Movement with valid_cells
# ---------------------------------------------------------------------------


def test_step_movement_respects_mask() -> None:
    """A piece with step movement can only move to valid masked cells."""
    session = _cross_session()
    # Place white piece at center (2,2) — valid cell
    _place(session, "piece", "white", 2, 2)

    moves = legal_moves(session)
    destinations = set()
    for m in moves:
        cell = m.action.to_pos["cell"]  # type: ignore[index]
        col, row = map(int, cell.split(","))
        destinations.add((col, row))

    # From (2,2) in a cross with step distance=1 and default adjacency (8 dirs):
    #   orthogonal: (1,2), (3,2), (2,1), (2,3) — all valid
    #   diagonal: (1,1), (3,1), (1,3), (3,3) — all valid in the cross
    # All 8 neighbors of (2,2) are valid in the cross mask
    expected = {(1, 2), (3, 2), (2, 1), (2, 3), (1, 1), (3, 1), (1, 3), (3, 3)}
    assert destinations == expected


def test_step_movement_blocked_by_mask() -> None:
    """A piece on an edge of the cross cannot step to masked-out cells."""
    session = _cross_session()
    # Place white piece at (0,2) — left edge of cross
    _place(session, "piece", "white", 0, 2)

    moves = legal_moves(session)
    destinations = set()
    for m in moves:
        cell = m.action.to_pos["cell"]  # type: ignore[index]
        col, row = map(int, cell.split(","))
        destinations.add((col, row))

    # From (0,2), the 8-adjacency neighbors are:
    #   (-1,1) OOB, (-1,2) OOB, (-1,3) OOB — all out of bounds
    #   (0,1) masked out, (0,3) masked out
    #   (1,1) valid, (1,2) valid, (1,3) valid
    expected = {(1, 1), (1, 2), (1, 3)}
    assert destinations == expected


def test_hop_movement_respects_mask() -> None:
    """Hop movement: both mid-cell and landing must be valid."""
    session = _cross_session()
    # Place white hopper at (2,2) center
    _place(session, "hopper", "white", 2, 2)
    # Place black piece at (2,1) to hop over (north)
    _place(session, "piece", "black", 2, 1)
    # Place black piece at (3,2) to hop over (east)
    _place(session, "piece", "black", 3, 2)

    # Switch turn back to white (advance_turn was not called for black)
    # Actually, we haven't called advance_turn at all — it's still white's turn.

    moves = legal_moves(session)
    hop_destinations = set()
    for m in moves:
        if m.action.action_type == "move_piece":
            from_cell = m.action.from_pos["cell"]  # type: ignore[index]
            to_cell = m.action.to_pos["cell"]  # type: ignore[index]
            fc, fr = map(int, from_cell.split(","))
            tc, tr = map(int, to_cell.split(","))
            # Only count hops (distance > 1 from origin)
            if abs(tc - fc) > 1 or abs(tr - fr) > 1:
                hop_destinations.add((tc, tr))

    # Hop over (2,1) lands at (2,0) — valid in cross
    # Hop over (3,2) lands at (4,2) — valid in cross
    # Hop in diagonal directions: mid and landing both need to be valid and mid occupied
    #   (1,1) has no piece -> no hop SW
    #   (3,1) has no piece -> no hop NE diag
    #   (1,3) has no piece -> no hop
    #   (3,3) has no piece -> no hop
    # Other adjacency dirs with pieces: only (2,1) and (3,2)
    assert (2, 0) in hop_destinations
    assert (4, 2) in hop_destinations


def test_hop_blocked_when_landing_masked_out() -> None:
    """Hop is blocked when the landing cell is masked out."""
    session = _cross_session()
    # Place white hopper at (1,2) — left part of cross arm
    _place(session, "hopper", "white", 1, 2)
    # Place black piece at (0,2) to hop over westward
    _place(session, "piece", "black", 0, 2)

    moves = legal_moves(session)
    hop_destinations = set()
    for m in moves:
        if m.action.action_type == "move_piece":
            from_cell = m.action.from_pos["cell"]  # type: ignore[index]
            to_cell = m.action.to_pos["cell"]  # type: ignore[index]
            fc, fr = map(int, from_cell.split(","))
            tc, tr = map(int, to_cell.split(","))
            if abs(tc - fc) > 1 or abs(tr - fr) > 1:
                hop_destinations.add((tc, tr))

    # Hopping west over (0,2) would land at (-1,2) — out of bounds, blocked
    assert (-1, 2) not in hop_destinations

    # Hopping north over (1,1) if occupied... but (1,1) is empty so no hop north
    # Let's check that any diagonal hops also respect the mask:
    # From (1,2), diagonal (-1,+1) mid=(0,3) masked out -> blocked
    # From (1,2), diagonal (-1,-1) mid=(0,1) masked out -> blocked
    assert (0, 1) not in hop_destinations
    assert (0, 3) not in hop_destinations


# ---------------------------------------------------------------------------
# 5. Hex adjacency directions
# ---------------------------------------------------------------------------


def test_hex_6_returns_6_directions() -> None:
    """_adjacent_directions('hex_6') returns exactly 6 hex neighbor vectors."""
    dirs = _adjacent_directions("hex_6")
    assert len(dirs) == 6
    expected = {(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)}
    assert set(dirs) == expected


def test_default_adjacency_returns_8_directions() -> None:
    """_adjacent_directions(None) returns 8 directions (king moves)."""
    dirs = _adjacent_directions(None)
    assert len(dirs) == 8
    expected = {
        (1, 0), (-1, 0), (0, 1), (0, -1),
        (1, 1), (1, -1), (-1, 1), (-1, -1),
    }
    assert set(dirs) == expected


def test_orthogonal_4_returns_4_directions() -> None:
    """_adjacent_directions('orthogonal_4') returns 4 cardinal directions."""
    dirs = _adjacent_directions("orthogonal_4")
    assert len(dirs) == 4
    expected = {(1, 0), (-1, 0), (0, 1), (0, -1)}
    assert set(dirs) == expected


# ---------------------------------------------------------------------------
# 6. runtime_zone_from_definition with valid_cells
# ---------------------------------------------------------------------------


def test_zone_from_definition_with_valid_cells() -> None:
    """Build a GridZone from a Zone definition that has valid_cells."""
    zone_def = Zone.from_dict({
        "zone_type": "grid",
        "dimensions": [5, 5],
        "visibility": "public",
        "valid_cells": [[0, 0], [1, 1], [2, 2]],
    })
    grid = runtime_zone_from_definition(zone_def)
    assert isinstance(grid, GridZone)
    assert grid.valid_cells is not None
    assert len(grid.valid_cells) == 3

    # Check the flat indices: (col=0,row=0)->0, (col=1,row=1)->6, (col=2,row=2)->12
    assert 0 * 5 + 0 in grid.valid_cells  # (0,0) -> 0
    assert 1 * 5 + 1 in grid.valid_cells  # (1,1) -> 6
    assert 2 * 5 + 2 in grid.valid_cells  # (2,2) -> 12


def test_zone_from_definition_without_valid_cells() -> None:
    """Without valid_cells, the grid has no mask (valid_cells is None)."""
    zone_def = Zone.from_dict({
        "zone_type": "grid",
        "dimensions": [3, 3],
        "visibility": "public",
    })
    grid = runtime_zone_from_definition(zone_def)
    assert isinstance(grid, GridZone)
    assert grid.valid_cells is None


def test_zone_from_definition_out_of_bounds_cells_ignored() -> None:
    """Out-of-bounds coordinates in valid_cells are silently ignored."""
    zone_def = Zone.from_dict({
        "zone_type": "grid",
        "dimensions": [3, 3],
        "visibility": "public",
        "valid_cells": [[0, 0], [10, 10], [2, 2]],
    })
    grid = runtime_zone_from_definition(zone_def)
    assert isinstance(grid, GridZone)
    assert grid.valid_cells is not None
    # Only 2 cells should be in the set (10,10 is out of bounds for 3x3)
    assert len(grid.valid_cells) == 2
    assert 0 in grid.valid_cells  # (0,0)
    assert 2 * 3 + 2 in grid.valid_cells  # (2,2) -> 8


def test_zone_from_definition_valid_cells_integration() -> None:
    """GridZone built from definition properly gates operations via mask."""
    zone_def = Zone.from_dict({
        "zone_type": "grid",
        "dimensions": [4, 4],
        "visibility": "public",
        "valid_cells": [[1, 1], [2, 2]],
    })
    grid = runtime_zone_from_definition(zone_def)
    assert isinstance(grid, GridZone)

    # Set on valid cell works
    prev = grid.grid_set(1, 1, _cid(7))
    assert prev is None
    assert grid.grid_get(1, 1) == _cid(7)

    # Set on masked-out cell is a no-op
    prev2 = grid.grid_set(0, 0, _cid(8))
    assert prev2 is None
    assert grid.grid_get(0, 0) is None
