"""End condition evaluation: check if the game has ended.

Pre-CEL implementation: matches condition strings to hardcoded evaluators.
Unrecognized conditions are silently skipped (forward-compatible with CEL).
"""

from __future__ import annotations

from baize.runtime import GameSession, GridZone
from baize.state import GameResult


def check_end_conditions(session: GameSession) -> GameResult | None:
    """Check all end conditions against the current game state.

    Must be called BEFORE advance_turn() so "current" refers to
    the player who just moved.
    """
    current_player = session.current_player()
    if current_player is None:
        return None

    for ec in session.definition.end_conditions:
        if not _eval_condition(session, ec.condition, current_player):
            continue

        if ec.result == "win":
            player_ref = ec.player or "current"
            winner = current_player if player_ref == "current" else player_ref
            return GameResult(outcome="win", winner=winner, condition=ec.name)
        elif ec.result == "draw":
            return GameResult(outcome="draw", condition=ec.name)
        elif ec.result == "loss":
            opponent = next(
                (p for p in session.runtime.players if p != current_player),
                None,
            )
            return GameResult(outcome="win", winner=opponent, condition=ec.name)

    return None


def _eval_condition(
    session: GameSession, condition: str, current_player: str
) -> bool:
    """Evaluate a condition: try CEL first, then legacy dispatch."""
    from baize.cel import try_eval_end_condition

    variables = _build_end_condition_variables(session, current_player)
    cel_result = try_eval_end_condition(variables, condition)
    if cel_result is not None:
        return cel_result

    # Legacy string dispatch for non-CEL condition strings
    base = condition.split("(")[0].strip()
    if base == "three_in_line":
        return _check_line_win(session, current_player)
    if base in ("all_cells_occupied", "board_is_full"):
        return _check_all_cells_occupied(session, condition)
    return False


def _build_end_condition_variables(
    session: GameSession, current_player: str
) -> dict[str, object]:
    """Build the CEL variable context for end-condition evaluation."""
    variables: dict[str, object] = {
        "current_player": current_player,
        "move_count": int(session.runtime.move_count),
        "halfmove_clock": int(session.runtime.halfmove_clock),
        # Legacy boolean variables (backward compat)
        "three_in_line": _check_line_win(session, current_player),
        "all_cells_occupied": _check_any_grid_full(session),
        "board_is_full": _check_any_grid_full(session),
    }
    # Grid structure: rows, cols, diags, lines as lists of owner strings
    _populate_grid_lines(variables, session)
    return variables


def _populate_grid_lines(
    variables: dict[str, object], session: GameSession
) -> None:
    """Serialize grid zones into lists for composable CEL line queries."""
    for zone in session.runtime.zones.values():
        if not isinstance(zone, GridZone):
            continue
        w, h = zone.width, zone.height

        def owner_at(col: int, row: int) -> str:
            cid = zone.grid_get(col, row)
            if cid is None:
                return ""
            comp = session.runtime.components.get(cid)
            if comp is None or comp.owner is None:
                return ""
            return comp.owner

        rows = [[owner_at(c, r) for c in range(w)] for r in range(h)]
        cols = [[owner_at(c, r) for r in range(h)] for c in range(w)]
        diags: list[list[str]] = []
        if w == h and w > 0:
            diags.append([owner_at(i, i) for i in range(w)])
            diags.append([owner_at(w - 1 - i, i) for i in range(w)])

        variables["rows"] = rows
        variables["cols"] = cols
        variables["diags"] = diags
        variables["lines"] = rows + cols + diags
        variables["board_width"] = w
        variables["board_height"] = h
        variables["cell_count"] = w * h
        variables["occupied_count"] = sum(
            1 for c in zone.cells if c is not None
        )
        break  # Use the first grid zone


def _check_any_grid_full(session: GameSession) -> bool:
    """Check whether any grid zone has all cells occupied."""
    for zone in session.runtime.zones.values():
        if isinstance(zone, GridZone):
            if len(zone.cells) > 0 and all(c is not None for c in zone.cells):
                return True
    return False


def _check_line_win(session: GameSession, player: str) -> bool:
    for zone in session.runtime.zones.values():
        if isinstance(zone, GridZone):
            if _has_complete_line(session, zone, player):
                return True
    return False


def _has_complete_line(
    session: GameSession, zone: GridZone, player: str
) -> bool:
    w, h = zone.width, zone.height

    for row in range(h):
        if w > 0 and all(
            _cell_owned_by(session, zone, col, row, player) for col in range(w)
        ):
            return True

    for col in range(w):
        if h > 0 and all(
            _cell_owned_by(session, zone, col, row, player) for row in range(h)
        ):
            return True

    if w == h and w > 0:
        if all(
            _cell_owned_by(session, zone, i, i, player) for i in range(w)
        ):
            return True
        if all(
            _cell_owned_by(session, zone, w - 1 - i, i, player)
            for i in range(w)
        ):
            return True

    return False


def _cell_owned_by(
    session: GameSession, zone: GridZone, col: int, row: int, player: str
) -> bool:
    cid = zone.grid_get(col, row)
    if cid is None:
        return False
    comp = session.runtime.components.get(cid)
    if comp is None:
        return False
    return comp.owner == player


def _check_all_cells_occupied(session: GameSession, condition: str) -> bool:
    zone_name = _extract_paren_arg(condition) or "board"
    zone = session.runtime.zones.get(zone_name)
    if zone is None or not isinstance(zone, GridZone):
        return False
    return len(zone.cells) > 0 and all(c is not None for c in zone.cells)


def _extract_paren_arg(s: str) -> str | None:
    open_idx = s.find("(")
    close_idx = s.find(")")
    if open_idx >= 0 and close_idx > open_idx + 1:
        return s[open_idx + 1 : close_idx].strip()
    return None
