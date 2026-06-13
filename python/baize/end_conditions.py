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
            winner = _team_winner(session, winner)
            return GameResult(outcome="win", winner=winner, condition=ec.name)
        elif ec.result == "draw":
            return GameResult(outcome="draw", condition=ec.name)
        elif ec.result == "loss":
            opponent = next(
                (p for p in session.runtime.players if p != current_player),
                None,
            )
            if opponent is not None:
                opponent = _team_winner(session, opponent)
            return GameResult(outcome="win", winner=opponent, condition=ec.name)

    return None


def _team_winner(session: GameSession, player: str) -> str:
    """If the player has teammates, return team name (e.g. 'North/South'); otherwise the player name."""
    team = session.team_of(player)
    if team is None or len(team) <= 1:
        return player
    return "/".join(team)


def _eval_condition(
    session: GameSession, condition: str, current_player: str
) -> bool:
    """Evaluate a condition: resolve library, try CEL, then legacy dispatch."""
    from baize.cel import try_eval_end_condition

    # Resolve library expression references
    library = getattr(session.definition, "library", {})
    entry = library.get(condition)
    resolved = entry if isinstance(entry, str) else condition

    variables = _build_end_condition_variables(session, current_player)
    cel_result = try_eval_end_condition(variables, resolved)
    if cel_result is not None:
        return cel_result

    # Legacy string dispatch for non-CEL condition strings
    base = resolved.split("(")[0].strip()
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
    # Inject all runtime counters into CEL context
    for name, value in session.runtime.counters.items():
        variables[name] = value
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
        variables["occupied_count"] = zone.count()

        # Windowed sub-lines: lines_N contains all N-length consecutive
        # windows in every direction (horizontal, vertical, both diagonals).
        # e.g. lines_4.exists(line, line.all(cell, cell == current_player))
        max_dim = max(w, h)
        for n in range(3, max_dim + 1):
            windows: list[list[str]] = []
            if n <= w:
                for row in range(h):
                    for sc in range(w - n + 1):
                        windows.append(
                            [owner_at(sc + i, row) for i in range(n)]
                        )
            if n <= h:
                for col in range(w):
                    for sr in range(h - n + 1):
                        windows.append(
                            [owner_at(col, sr + i) for i in range(n)]
                        )
            if n <= w and n <= h:
                for sc in range(w - n + 1):
                    for sr in range(h - n + 1):
                        windows.append(
                            [owner_at(sc + i, sr + i) for i in range(n)]
                        )
                for sc in range(n - 1, w):
                    for sr in range(h - n + 1):
                        windows.append(
                            [owner_at(sc - i, sr + i) for i in range(n)]
                        )
            if windows:
                variables[f"lines_{n}"] = windows

        # Component-type-based rows/cols (for placement constraints)
        def type_at(col: int, row: int) -> str:
            cid = zone.grid_get(col, row)
            if cid is None:
                return ""
            comp = session.runtime.components.get(cid)
            if comp is None:
                return ""
            return comp.component_type

        variables["type_rows"] = [
            [type_at(c, r) for c in range(w)] for r in range(h)
        ]
        variables["type_cols"] = [
            [type_at(c, r) for r in range(h)] for c in range(w)
        ]

        # Cell properties: expose prop_{key} as 2D arrays (rows format).
        # Each cell value is the property value as a string, or "" if unset.
        if zone.cell_properties:
            all_keys: set[str] = set()
            for props in zone.cell_properties.values():
                all_keys.update(props.keys())
            for key in sorted(all_keys):
                prop_rows = []
                for row in range(h):
                    prop_row = []
                    for col in range(w):
                        val = zone.get_cell_property(col, row, key)
                        prop_row.append(str(val) if val is not None else "")
                    prop_rows.append(prop_row)
                variables[f"prop_{key}"] = prop_rows

        break  # Use the first grid zone

    # Per-zone uniform-type booleans: zone_uniform_<name> is true when all
    # cells in the named grid zone are occupied and have the same component type.
    for name, zone in session.runtime.zones.items():
        if isinstance(zone, GridZone):
            if zone._sparse:
                # For sparse grids: need dimension hints to determine "all cells"
                if zone.width > 0 and zone.height > 0:
                    expected = zone.width * zone.height
                    if zone.count() == expected and expected > 0:
                        types: set[str] = set()
                        for _col, _row, cid in zone.occupied_cells():
                            comp = session.runtime.components.get(cid)
                            if comp is None:
                                break
                            types.add(comp.component_type)
                        else:
                            variables[f"zone_uniform_{name}"] = len(types) == 1
                            continue
                variables[f"zone_uniform_{name}"] = False
            else:
                if zone.width > 0 and zone.height > 0 and zone.cells:
                    type_list: list[str] = []
                    for cid in zone.cells:
                        if cid is None:
                            break
                        comp = session.runtime.components.get(cid)
                        if comp is None:
                            break
                        type_list.append(comp.component_type)
                    else:
                        uniform = len(set(type_list)) == 1
                        variables[f"zone_uniform_{name}"] = uniform
                        continue
                variables[f"zone_uniform_{name}"] = False


def _check_any_grid_full(session: GameSession) -> bool:
    """Check whether any grid zone has all cells occupied."""
    for zone in session.runtime.zones.values():
        if isinstance(zone, GridZone):
            if zone._sparse:
                if zone.width > 0 and zone.height > 0:
                    expected = zone.width * zone.height
                    if expected > 0 and zone.count() >= expected:
                        return True
            else:
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
    if zone._sparse:
        if zone.width > 0 and zone.height > 0:
            expected = zone.width * zone.height
            return expected > 0 and zone.count() >= expected
        return False
    return len(zone.cells) > 0 and all(c is not None for c in zone.cells)


def _extract_paren_arg(s: str) -> str | None:
    open_idx = s.find("(")
    close_idx = s.find(")")
    if open_idx >= 0 and close_idx > open_idx + 1:
        return s[open_idx + 1 : close_idx].strip()
    return None
