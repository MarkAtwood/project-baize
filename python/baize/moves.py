"""Legal move generator.

Ports the Rust move generation from engine/src/moves.rs:
  - legal_moves(session) -> list[LegalMove]
  - Grid-based movement: step, slide, leap, hop
  - Direction resolution, friendly blocking, enemy capture
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baize.action import Action
from baize.definition import AdjacencyLiteral, Component, DirectionNameLiteral, MovementPrimitive
from baize.runtime import (
    ComponentId,
    GameSession,
    GridZone,
    RuntimeZone,
)

MAX_LEGAL_MOVES = 10_000
"""Maximum number of legal moves to generate before stopping."""


@dataclass
class LegalMove:
    """A legal move that a player can make."""

    component_id: ComponentId
    action: Action


def legal_moves(session: GameSession) -> list[LegalMove]:
    """Generate all legal moves for the current player.

    Returns at most MAX_LEGAL_MOVES moves to prevent combinatorial explosion.
    """
    assert isinstance(session, GameSession), (
        f"session must be GameSession, got {type(session).__name__}"
    )
    player = session.current_player()
    if player is None:
        return []

    moves: list[LegalMove] = []

    # For each component owned by the current player on the board, generate moves
    for zone_name, zone in session.runtime.zones.items():
        if len(moves) >= MAX_LEGAL_MOVES:
            break
        if zone_name not in session.definition.zones:
            continue

        if isinstance(zone, GridZone):
            seen: set[ComponentId] = set()
            for row in range(zone.height):
                if len(moves) >= MAX_LEGAL_MOVES:
                    break
                for col in range(zone.width):
                    if len(moves) >= MAX_LEGAL_MOVES:
                        break
                    idx = row * zone.width + col
                    cid = zone.cells[idx]
                    if cid is None:
                        continue
                    if cid in seen:
                        continue  # Skip duplicate cells of spanning component
                    seen.add(cid)
                    comp_data = session.runtime.components.get(cid)
                    if comp_data is None:
                        continue
                    if comp_data.owner != player:
                        continue
                    comp_def = session.definition.components.get(
                        comp_data.component_type
                    )
                    if comp_def is None:
                        continue
                    zone_def = session.definition.zones[zone_name]
                    _generate_grid_moves(
                        session,
                        zone_name,
                        cid,
                        comp_def,
                        col,
                        row,
                        zone_def.adjacency,
                        moves,
                    )

    # Also check per-player zones
    if len(moves) < MAX_LEGAL_MOVES:
        player_state = session.runtime.players.get(player)
        if player_state is not None:
            for _zone_name, _zone in player_state.zones.items():
                if len(moves) >= MAX_LEGAL_MOVES:
                    break
                _generate_hand_plays(session, player, _zone_name, _zone, moves)

    return moves


def _generate_grid_moves(
    session: GameSession,
    zone_name: str,
    cid: ComponentId,
    comp_def: Component,
    col: int,
    row: int,
    adjacency: AdjacencyLiteral | None,
    moves: list[LegalMove],
) -> None:
    """Generate moves for a piece on a grid using its movement primitives."""
    zone = session.runtime.zones.get(zone_name)
    if zone is None or not isinstance(zone, GridZone):
        return

    comp_data = session.runtime.components.get(cid)
    player = comp_data.owner if comp_data is not None else ""
    if player is None:
        player = ""

    for mp in comp_def.movement:
        if len(moves) >= MAX_LEGAL_MOVES:
            return
        if mp.primitive == "step":
            dirs = _resolve_directions(mp, player, adjacency)
            dist = mp.distance if mp.distance is not None else 1
            for dx, dy in dirs:
                nx = col + dx * dist
                ny = row + dy * dist
                if not zone._cell_valid(nx, ny):
                    continue
                if _check_cell_condition(zone, session, nx, ny, mp, player):
                    moves.append(
                        LegalMove(
                            component_id=cid,
                            action=_make_move_action(zone_name, col, row, nx, ny),
                        )
                    )

        elif mp.primitive == "slide":
            dirs = _resolve_directions(mp, player, adjacency)
            for dx, dy in dirs:
                nx = col + dx
                ny = row + dy
                while zone._cell_valid(nx, ny) and len(moves) < MAX_LEGAL_MOVES:
                    target = zone.grid_get(nx, ny)
                    if target is not None:
                        if _is_enemy(session, target, player):
                            moves.append(
                                LegalMove(
                                    component_id=cid,
                                    action=_make_move_action(
                                        zone_name, col, row, nx, ny
                                    ),
                                )
                            )
                        break
                    moves.append(
                        LegalMove(
                            component_id=cid,
                            action=_make_move_action(zone_name, col, row, nx, ny),
                        )
                    )
                    nx += dx
                    ny += dy

        elif mp.primitive == "leap":
            ldx = mp.dx
            ldy = mp.dy
            if ldx is not None and ldy is not None:
                for sx, sy in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
                    for adx, ady in [(ldx, ldy), (ldy, ldx)]:
                        nx = col + adx * sx
                        ny = row + ady * sy
                        if not zone._cell_valid(nx, ny):
                            continue
                        target = zone.grid_get(nx, ny)
                        if target is None:
                            moves.append(
                                LegalMove(
                                    component_id=cid,
                                    action=_make_move_action(
                                        zone_name, col, row, nx, ny
                                    ),
                                )
                            )
                        elif _is_enemy(session, target, player):
                            moves.append(
                                LegalMove(
                                    component_id=cid,
                                    action=_make_move_action(
                                        zone_name, col, row, nx, ny
                                    ),
                                )
                            )

        elif mp.primitive == "hop":
            dirs = _resolve_directions(mp, player, adjacency)
            for dx, dy in dirs:
                mid_x = col + dx
                mid_y = row + dy
                land_x = col + dx * 2
                land_y = row + dy * 2
                if not zone._cell_valid(mid_x, mid_y):
                    continue
                if not zone._cell_valid(land_x, land_y):
                    continue
                # Middle cell must be occupied
                if zone.grid_get(mid_x, mid_y) is None:
                    continue
                # Landing cell must be empty
                if zone.grid_get(land_x, land_y) is None:
                    moves.append(
                        LegalMove(
                            component_id=cid,
                            action=_make_move_action(
                                zone_name, col, row, land_x, land_y
                            ),
                        )
                    )


def _generate_hand_plays(
    session: GameSession,
    player: str,
    zone_name: str,
    zone: RuntimeZone,
    moves: list[LegalMove],
) -> None:
    """Generate moves for playing from a hand zone (stub)."""
    # Hand plays are game-specific; will be expanded


def _resolve_directions(
    mp: MovementPrimitive,
    player: str,
    adjacency: AdjacencyLiteral | None = None,
) -> list[tuple[int, int]]:
    """Resolve direction names to (dx, dy) vectors, respecting zone adjacency."""
    direction = mp.direction
    if direction is None:
        return _adjacent_directions(adjacency)

    if isinstance(direction, str):
        return _direction_vectors(direction, adjacency)
    if isinstance(direction, list):
        result: list[tuple[int, int]] = []
        for name in direction:
            result.extend(_direction_vectors(name, adjacency))
        return result
    return _adjacent_directions(adjacency)


def _direction_vectors(
    name: str, adjacency: AdjacencyLiteral | None = None
) -> list[tuple[int, int]]:
    """Convert a direction name to (dx, dy) vectors."""
    if name == "orthogonal":
        return [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if name == "diagonal":
        if adjacency == "hex_6":
            return [(-1, 1), (1, -1)]
        return [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    if name == "adjacent":
        return _adjacent_directions(adjacency)
    if name == "forward":
        return [(0, 1)]
    if name == "forward_diagonal":
        return [(1, 1), (-1, 1)]
    if name == "backward":
        return [(0, -1)]
    if name == "backward_diagonal":
        return [(1, -1), (-1, -1)]
    return _adjacent_directions(adjacency)


_HEX_DIRECTIONS: list[tuple[int, int]] = [
    (-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)
]


def _adjacent_directions(
    adjacency: AdjacencyLiteral | None = None,
) -> list[tuple[int, int]]:
    """Return neighbor directions based on adjacency model."""
    if adjacency == "hex_6":
        return list(_HEX_DIRECTIONS)
    if adjacency == "orthogonal_4":
        return [(1, 0), (-1, 0), (0, 1), (0, -1)]
    return [
        (1, 0),
        (-1, 0),
        (0, 1),
        (0, -1),
        (1, 1),
        (1, -1),
        (-1, 1),
        (-1, -1),
    ]


def _is_enemy(session: GameSession, target_id: ComponentId, player: str) -> bool:
    """Check if a component belongs to an enemy player."""
    comp = session.runtime.components.get(target_id)
    if comp is None:
        return False
    if comp.owner is None:
        return False
    return comp.owner != player


def _check_cell_condition(
    zone: GridZone,
    session: GameSession,
    col: int,
    row: int,
    mp: MovementPrimitive,
    player: str,
) -> bool:
    """Check whether a step move can land on the given cell."""
    occupant = zone.grid_get(col, row)
    condition = mp.condition if mp.condition is not None else "empty_or_enemy"

    if condition == "empty":
        return occupant is None
    if condition == "enemy":
        return occupant is not None and _is_enemy(session, occupant, player)
    if condition == "empty_or_enemy":
        return occupant is None or _is_enemy(session, occupant, player)
    # Try CEL evaluation for complex conditions
    from baize.cel import try_eval_move_condition

    cell_empty = occupant is None
    cell_enemy = occupant is not None and _is_enemy(session, occupant, player)
    cel_result = try_eval_move_condition(cell_empty, cell_enemy, condition)
    if cel_result is not None:
        return cel_result
    # Legacy fallback: allow if empty or enemy
    return occupant is None or _is_enemy(session, occupant, player)


def _make_move_action(
    zone: str, from_col: int, from_row: int, to_col: int, to_row: int
) -> Action:
    """Create a MovePiece action for a grid move."""
    return Action(
        action_type="move_piece",
        from_pos={
            "zone": zone,
            "cell": f"{from_col},{from_row}",
        },
        to_pos={
            "zone": zone,
            "cell": f"{to_col},{to_row}",
        },
    )
