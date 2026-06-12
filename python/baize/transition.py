"""State transitions: apply actions and emit events.

Ports the Rust transition logic from engine/src/transition.rs:
  - apply_action(session, action) -> list[GameEvent]
  - Move piece, place, pass, resign, flip
  - Capture detection
  - JSONL event emission with hash chaining
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from baize.action import Action, Position
from baize.definition import GameDefinition
from baize.end_conditions import check_end_conditions
from baize.error import IllegalActionError, InvalidCoordinateError, UnknownZoneError
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
    StackZone,
)


def _validate_grid_coords(
    zone: GridZone, col: int, row: int, zone_name: str
) -> None:
    """Raise InvalidCoordinateError if (col, row) is outside the grid."""
    if col < 0 or row < 0 or col >= zone.width or row >= zone.height:
        raise InvalidCoordinateError(col, row, zone.width, zone.height)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EventTypeLiteral = Literal[
    "move_piece",
    "place",
    "capture",
    "draw",
    "play_card",
    "discard",
    "flip",
    "promote",
    "swap",
    "remove",
    "pass",
    "resign",
    "fire",
    "hit",
    "miss",
    "sunk",
    "commit",
    "reveal",
    "action_submitted",
    "turn_advance",
    "game_end",
]


# ---------------------------------------------------------------------------
# GameEvent
# ---------------------------------------------------------------------------


@dataclass
class GameEvent:
    """An event emitted by a state transition, for JSONL event logging."""

    sequence: int
    event_type: EventTypeLiteral
    player: str
    component_id: str | None = None
    from_pos: str | None = None
    to_pos: str | None = None
    captured: str | None = None
    detail: str | None = None
    state_hash: str = ""
    prev_hash: str | None = None

    def to_json_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        out: dict[str, Any] = {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "player": self.player,
        }
        if self.component_id is not None:
            out["component_id"] = self.component_id
        if self.from_pos is not None:
            out["from"] = self.from_pos
        if self.to_pos is not None:
            out["to"] = self.to_pos
        if self.captured is not None:
            out["captured"] = self.captured
        if self.detail is not None:
            out["detail"] = self.detail
        out["state_hash"] = self.state_hash
        if self.prev_hash is not None:
            out["prev_hash"] = self.prev_hash
        return json.dumps(out, separators=(",", ":"))


# ---------------------------------------------------------------------------
# apply_action
# ---------------------------------------------------------------------------


def _current_phase(session: GameSession):
    """Return the current Phase definition, or None if no phases defined."""
    if session.definition.phases and session.runtime.phase_index < len(
        session.definition.phases
    ):
        return session.definition.phases[session.runtime.phase_index]
    return None


def apply_action(
    session: GameSession,
    action: Action,
    *,
    acting_player: str | None = None,
) -> list[GameEvent]:
    """Apply an action to the game session, mutating state and returning events.

    For simultaneous phases, pass acting_player to identify the submitter.
    Actions are buffered until all players submit, then resolved atomically.
    """
    assert isinstance(session, GameSession), (
        f"session must be GameSession, got {type(session).__name__}"
    )
    assert isinstance(action, Action), (
        f"action must be Action, got {type(action).__name__}"
    )
    if session.runtime.status == "finished":
        raise IllegalActionError("game is finished")

    if session.runtime.status == "setup":
        session.runtime.status = "in_progress"

    # Check if we're in a simultaneous phase
    phase = _current_phase(session)
    if phase and phase.simultaneous:
        return _apply_simultaneous(session, action, acting_player)

    player = acting_player or session.current_player()
    if player is None:
        raise IllegalActionError("no current player")

    prev_hash = (
        session.runtime.history_hashes[-1]
        if session.runtime.history_hashes
        else None
    )

    events = _execute_action(session, player, action, prev_hash)

    # Check end conditions before advancing turn ("current" = player who just moved)
    if session.runtime.status != "finished":
        result = check_end_conditions(session)
        if result is not None:
            session.runtime.status = "finished"
            session.runtime.result = result

            new_hash = session.compute_state_hash()
            session.runtime.history_hashes.append(new_hash)

            for event in events:
                event.state_hash = new_hash

            events.append(
                GameEvent(
                    sequence=session.runtime.sequence,
                    event_type="game_end",
                    player=result.winner or "",
                    detail=result.condition,
                    state_hash=new_hash,
                    prev_hash=prev_hash,
                )
            )

            return events

    # Advance turn
    session.advance_turn()
    new_hash = session.compute_state_hash()
    session.runtime.history_hashes.append(new_hash)

    for event in events:
        event.state_hash = new_hash

    next_player = session.current_player() or ""
    events.append(
        GameEvent(
            sequence=session.runtime.sequence,
            event_type="turn_advance",
            player=next_player,
            state_hash=new_hash,
            prev_hash=prev_hash,
        )
    )

    return events


def _apply_simultaneous(
    session: GameSession, action: Action, acting_player: str | None
) -> list[GameEvent]:
    """Buffer an action for a simultaneous phase; resolve when all submit."""
    player = acting_player or session.current_player()
    if player is None:
        raise IllegalActionError("no player specified for simultaneous action")
    if player not in session.runtime.players:
        raise IllegalActionError(f"unknown player: {player}")
    if player in session.runtime.simultaneous_actions:
        raise IllegalActionError(
            f"player {player} has already submitted for this phase"
        )

    prev_hash = (
        session.runtime.history_hashes[-1]
        if session.runtime.history_hashes
        else None
    )

    # Buffer the action
    session.runtime.simultaneous_actions[player] = action.to_dict()
    events: list[GameEvent] = [
        _make_event(
            session.runtime.sequence,
            "action_submitted",
            player,
            prev_hash=prev_hash,
        )
    ]

    # Check if all players have submitted
    all_players = list(session.runtime.players.keys())
    if all(p in session.runtime.simultaneous_actions for p in all_players):
        # Resolve: apply each action in player order
        buffered = dict(session.runtime.simultaneous_actions)
        session.runtime.simultaneous_actions.clear()

        for p in all_players:
            act = Action.from_dict(buffered[p])
            resolve_events = _execute_action(session, p, act, prev_hash)
            events.extend(resolve_events)

        # Check end conditions after all actions resolved
        if session.runtime.status != "finished":
            result = check_end_conditions(session)
            if result is not None:
                session.runtime.status = "finished"
                session.runtime.result = result

                new_hash = session.compute_state_hash()
                session.runtime.history_hashes.append(new_hash)
                for event in events:
                    event.state_hash = new_hash
                events.append(
                    GameEvent(
                        sequence=session.runtime.sequence,
                        event_type="game_end",
                        player=result.winner or "",
                        detail=result.condition,
                        state_hash=new_hash,
                        prev_hash=prev_hash,
                    )
                )
                return events

        # Advance turn after resolution
        session.advance_turn()
        new_hash = session.compute_state_hash()
        session.runtime.history_hashes.append(new_hash)
        for event in events:
            event.state_hash = new_hash
        events.append(
            GameEvent(
                sequence=session.runtime.sequence,
                event_type="turn_advance",
                player=session.current_player() or "",
                state_hash=new_hash,
                prev_hash=prev_hash,
            )
        )

    return events


def _execute_action(
    session: GameSession, player: str, action: Action, prev_hash: str | None
) -> list[GameEvent]:
    """Execute action mechanics: mutate state and return events.

    Does NOT advance turn or check end conditions — caller handles that.
    """
    assert isinstance(player, str) and len(player) > 0, (
        f"player must be a non-empty string, got {player!r}"
    )
    assert isinstance(action, Action), (
        f"action must be Action, got {type(action).__name__}"
    )
    events: list[GameEvent] = []

    if action.action_type == "move_piece":
        from_col, from_row = _parse_position(action.from_pos)
        to_col, to_row = _parse_position(action.to_pos)
        zone_name = _position_zone(action.from_pos) or "board"

        zone = session.runtime.zones.get(zone_name)
        if zone is None:
            raise UnknownZoneError(zone_name)
        if not isinstance(zone, GridZone):
            raise IllegalActionError(f"zone {zone_name} is not a grid")

        _validate_grid_coords(zone, from_col, from_row, zone_name)
        _validate_grid_coords(zone, to_col, to_row, zone_name)

        cid = zone.grid_get(from_col, from_row)
        if cid is None:
            raise IllegalActionError("no piece at source")

        # Check for capture
        captured = zone.grid_get(to_col, to_row)
        if captured is not None:
            cap_data = session.runtime.components.get(captured)
            cap_name = cap_data.string_id if cap_data is not None else ""
            events.append(
                _make_event(
                    session.runtime.sequence,
                    "capture",
                    player,
                    component_id=cap_name,
                    to_pos=f"{to_col},{to_row}",
                    prev_hash=prev_hash,
                )
            )

        # Move the piece
        zone.grid_set(from_col, from_row, None)
        zone.grid_set(to_col, to_row, cid)

        comp_data = session.runtime.components.get(cid)
        comp_name = comp_data.string_id if comp_data is not None else ""
        events.append(
            _make_event(
                session.runtime.sequence,
                "move_piece",
                player,
                component_id=comp_name,
                from_pos=f"{from_col},{from_row}",
                to_pos=f"{to_col},{to_row}",
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "place":
        to_col, to_row = _parse_position(action.to_pos)
        zone_name = _position_zone(action.to_pos) or "board"
        comp_type = action.component_type
        if comp_type is None:
            raise IllegalActionError("place requires component_type")

        # Create a new component instance
        instance_id = f"{comp_type}-{player}-{len(session.runtime.components)}"
        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=instance_id,
                component_type=comp_type,
                owner=player,
            )
        )

        zone: GridZone | None = None
        pstate = session.runtime.players.get(player)
        if pstate is not None:
            pz = pstate.zones.get(zone_name)
            if isinstance(pz, GridZone):
                zone = pz
        if zone is None:
            gz = session.runtime.zones.get(zone_name)
            if isinstance(gz, GridZone):
                zone = gz
        if zone is None:
            raise UnknownZoneError(zone_name)
        _validate_grid_coords(zone, to_col, to_row, zone_name)
        zone.grid_set(to_col, to_row, cid)

        events.append(
            _make_event(
                session.runtime.sequence,
                "place",
                player,
                component_id=instance_id,
                to_pos=f"{to_col},{to_row}",
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "pass":
        events.append(
            _make_event(
                session.runtime.sequence,
                "pass",
                player,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "resign":
        events.append(
            _make_event(
                session.runtime.sequence,
                "resign",
                player,
                prev_hash=prev_hash,
            )
        )
        session.runtime.status = "finished"

    elif action.action_type == "flip":
        comp_id_str = action.component_id
        if comp_id_str is not None:
            target_cid: ComponentId | None = None
            for comp in session.runtime.components:
                if comp.string_id == comp_id_str:
                    target_cid = comp.id
                    break
            if target_cid is not None:
                comp_mut = session.runtime.components.get(target_cid)
                if comp_mut is not None:
                    if comp_mut.facing == "face_up":
                        comp_mut.facing = "face_down"
                    else:
                        comp_mut.facing = "face_up"
                events.append(
                    _make_event(
                        session.runtime.sequence,
                        "flip",
                        player,
                        component_id=comp_id_str,
                        prev_hash=prev_hash,
                    )
                )

    elif action.action_type == "remove":
        comp_id_str = action.component_id
        if comp_id_str is None:
            raise IllegalActionError("remove requires component_id")
        remove_cid, zone_name, col, row = _find_component_on_grid(
            session, comp_id_str
        )
        zone = session.runtime.zones.get(zone_name)
        if zone is None or not isinstance(zone, GridZone):
            raise IllegalActionError(f"zone {zone_name} is not a grid")
        # Check for spanning component
        comp_data = session.runtime.components.get(remove_cid)
        if comp_data is not None and comp_data.span_cells:
            zone.grid_remove_span(comp_data.span_cells)
        else:
            zone.grid_set(col, row, None)
        events.append(
            _make_event(
                session.runtime.sequence,
                "remove",
                player,
                component_id=comp_id_str,
                from_pos=f"{col},{row}",
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "swap":
        comp_id_str = action.component_id
        swap_with_str = action.swap_with
        if comp_id_str is None:
            raise IllegalActionError("swap requires component_id")
        if swap_with_str is None:
            raise IllegalActionError("swap requires swap_with")
        _cid_a, zone_a, col_a, row_a = _find_component_on_grid(
            session, comp_id_str
        )
        _cid_b, zone_b, col_b, row_b = _find_component_on_grid(
            session, swap_with_str
        )
        if zone_a != zone_b:
            raise IllegalActionError(
                "swap requires both components in the same zone"
            )
        zone = session.runtime.zones.get(zone_a)
        if zone is None or not isinstance(zone, GridZone):
            raise IllegalActionError(f"zone {zone_a} is not a grid")
        a = zone.grid_get(col_a, row_a)
        b = zone.grid_get(col_b, row_b)
        zone.grid_set(col_a, row_a, b)
        zone.grid_set(col_b, row_b, a)
        events.append(
            _make_event(
                session.runtime.sequence,
                "swap",
                player,
                component_id=comp_id_str,
                from_pos=f"{col_a},{row_a}",
                to_pos=f"{col_b},{row_b}",
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "promote":
        comp_id_str = action.component_id
        promote_to = action.promote_to
        if comp_id_str is None:
            raise IllegalActionError("promote requires component_id")
        if promote_to is None:
            raise IllegalActionError("promote requires promote_to")
        target_cid_p: ComponentId | None = None
        for comp in session.runtime.components:
            if comp.string_id == comp_id_str:
                target_cid_p = comp.id
                break
        if target_cid_p is None:
            raise IllegalActionError(f"component {comp_id_str!r} not found")
        comp_mut = session.runtime.components.get(target_cid_p)
        if comp_mut is not None:
            comp_mut.component_type = promote_to
        events.append(
            _make_event(
                session.runtime.sequence,
                "promote",
                player,
                component_id=comp_id_str,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "draw":
        source_zone_name = action.zone
        if source_zone_name is None:
            raise IllegalActionError("draw requires zone")
        source_zone = session.runtime.zones.get(source_zone_name)
        if source_zone is None:
            raise UnknownZoneError(source_zone_name)
        if not isinstance(source_zone, StackZone):
            raise IllegalActionError(f"zone {source_zone_name} is not a stack")
        cid_drawn = source_zone.stack_pop()
        if cid_drawn is None:
            raise IllegalActionError("source zone is empty")
        comp_data = session.runtime.components.get(cid_drawn)
        comp_name = comp_data.string_id if comp_data is not None else ""
        # Add to player's first per-player zone (hand)
        player_state = session.runtime.players.get(player)
        if player_state is not None and player_state.zones:
            first_hand = next(iter(player_state.zones.values()))
            if isinstance(first_hand, StackZone):
                first_hand.stack_push(cid_drawn)
        events.append(
            _make_event(
                session.runtime.sequence,
                "draw",
                player,
                component_id=comp_name,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "place_ship":
        to_col, to_row = _parse_position(action.to_pos)
        zone_name = _position_zone(action.to_pos) or "board"
        comp_type = action.component_type
        if comp_type is None:
            raise IllegalActionError("place_ship requires component_type")
        if action.orientation is None:
            raise IllegalActionError("place_ship requires orientation")
        horizontal = action.orientation == "horizontal"

        # Look up span from definition
        span = _lookup_span(session.definition, comp_type)

        instance_id = f"{comp_type}-{player}-{len(session.runtime.components)}"
        cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=instance_id,
                component_type=comp_type,
                owner=player,
            )
        )

        # Try player zone first, then shared zones
        zone: GridZone | None = None
        player_state = session.runtime.players.get(player)
        if player_state is not None:
            pz = player_state.zones.get(zone_name)
            if isinstance(pz, GridZone):
                zone = pz
        if zone is None:
            z = session.runtime.zones.get(zone_name)
            if isinstance(z, GridZone):
                zone = z
        if zone is None:
            raise UnknownZoneError(zone_name)

        span_cells = zone.grid_place_span(
            to_col, to_row, horizontal, span, cid
        )

        # Store span cells on the component
        comp_data = session.runtime.components.get(cid)
        if comp_data is not None:
            comp_data.span_cells = span_cells

        events.append(
            _make_event(
                session.runtime.sequence,
                "place",
                player,
                component_id=instance_id,
                to_pos=f"{to_col},{to_row}",
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "fire":
        target_col, target_row = _parse_position(action.to_pos)
        target_zone_name = _position_zone(action.to_pos) or "ocean"
        peg_zone_name = action.zone or "target"

        # Find opponent
        opponent: str | None = None
        for p in session.runtime.players:
            if p != player:
                opponent = p
                break
        if opponent is None:
            raise IllegalActionError("no opponent found")

        # Check duplicate fire (attacker's target grid)
        attacker_state = session.runtime.players.get(player)
        if attacker_state is not None:
            atk_target = attacker_state.zones.get(peg_zone_name)
            if isinstance(atk_target, GridZone):
                if atk_target.grid_get(target_col, target_row) is not None:
                    raise IllegalActionError(
                        f"already fired at ({target_col},{target_row})"
                    )

        # Check opponent's ocean grid
        opp_state = session.runtime.players.get(opponent)
        hit_cid: ComponentId | None = None
        if opp_state is not None:
            opp_ocean = opp_state.zones.get(target_zone_name)
            if isinstance(opp_ocean, GridZone):
                hit_cid = opp_ocean.grid_get(target_col, target_row)

        is_hit = hit_cid is not None

        # Create peg on attacker's target grid
        peg_type = "hit" if is_hit else "miss"
        peg_id = f"{peg_type}-{player}-{len(session.runtime.components)}"
        peg_cid = session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=peg_id,
                component_type=peg_type,
                owner=player,
            )
        )

        atk_state = session.runtime.players.get(player)
        if atk_state is not None:
            atk_zone = atk_state.zones.get(peg_zone_name)
            if isinstance(atk_zone, GridZone):
                atk_zone.grid_set(target_col, target_row, peg_cid)

        events.append(
            _make_event(
                session.runtime.sequence,
                "fire",
                player,
                to_pos=f"{target_col},{target_row}",
                prev_hash=prev_hash,
            )
        )

        if is_hit:
            assert hit_cid is not None
            # Increment hit_count on the ship
            comp = session.runtime.components.get(hit_cid)
            if comp is not None:
                prev_hits = comp.properties.get("hit_count", 0)
                new_hits = int(prev_hits) + 1
                comp.properties["hit_count"] = new_hits
                ship_type = comp.component_type
                span_len = len(comp.span_cells)

            events.append(
                _make_event(
                    session.runtime.sequence,
                    "hit",
                    player,
                    component_id=peg_id,
                    to_pos=f"{target_col},{target_row}",
                    prev_hash=prev_hash,
                )
            )

            # Check sunk
            if comp is not None and span_len > 0 and new_hits >= span_len:
                events.append(
                    GameEvent(
                        sequence=session.runtime.sequence,
                        event_type="sunk",
                        player=player,
                        component_id=ship_type,
                        state_hash="",
                        prev_hash=prev_hash,
                    )
                )
                # Decrement opponent ships_remaining
                opp = session.runtime.players.get(opponent)
                if opp is not None and "ships_remaining" in opp.counters:
                    opp.counters["ships_remaining"] = max(
                        0, opp.counters["ships_remaining"] - 1
                    )
        else:
            events.append(
                _make_event(
                    session.runtime.sequence,
                    "miss",
                    player,
                    component_id=peg_id,
                    to_pos=f"{target_col},{target_row}",
                    prev_hash=prev_hash,
                )
            )

    elif action.action_type == "commit":
        # Commit-reveal protocol: store SHA-256 commitment hash
        if not action.declaration:
            raise IllegalActionError("commit action requires declaration (hash)")
        if player in session.runtime.pending_commits:
            raise IllegalActionError(
                f"player {player} already has a pending commitment"
            )
        session.runtime.pending_commits[player] = action.declaration
        events.append(
            _make_event(
                session.runtime.sequence,
                "commit",
                player,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "reveal":
        # Commit-reveal protocol: verify hash and place revealed component
        import hashlib
        import hmac

        if player not in session.runtime.pending_commits:
            raise IllegalActionError(
                f"player {player} has no pending commitment to reveal"
            )
        if not action.declaration:
            raise IllegalActionError("reveal action requires declaration (value)")
        if not action.commitment:
            raise IllegalActionError("reveal action requires commitment (nonce)")

        expected = session.runtime.pending_commits[player]
        preimage = f"{action.declaration}|{action.commitment}"
        actual = hashlib.sha256(preimage.encode()).hexdigest()
        # Constant-time comparison to prevent timing side-channel attacks
        if not hmac.compare_digest(actual, expected):
            raise IllegalActionError(
                f"commitment verification failed: "
                f"SHA-256({action.declaration}|<nonce>) != stored hash"
            )
        del session.runtime.pending_commits[player]

        # Place the revealed component (same logic as place action)
        if action.component_type and action.to_pos:
            to_col, to_row = _parse_position(action.to_pos)
            zone_name = _position_zone(action.to_pos) or "board"
            zone = session.runtime.zones.get(zone_name)
            if zone is None:
                rp = session.runtime.players.get(player)
                if rp is not None:
                    zone = rp.zones.get(zone_name)
            if zone is not None and isinstance(zone, GridZone):
                instance_id = (
                    f"{action.component_type}-{player}"
                    f"-{len(session.runtime.components)}"
                )
                comp = ComponentData(
                    id=ComponentId(0),
                    string_id=instance_id,
                    component_type=action.component_type,
                    owner=player,
                )
                cid = session.runtime.components.insert(comp)
                zone.grid_set(to_col, to_row, cid)

        events.append(
            _make_event(
                session.runtime.sequence,
                "reveal",
                player,
                prev_hash=prev_hash,
            )
        )

    else:
        raise IllegalActionError(
            f"action type {action.action_type!r} not yet implemented"
        )

    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_component_on_grid(
    session: GameSession, comp_id_str: str
) -> tuple[ComponentId, str, int, int]:
    """Find a component by string ID on any grid zone."""
    target_cid: ComponentId | None = None
    for comp in session.runtime.components:
        if comp.string_id == comp_id_str:
            target_cid = comp.id
            break
    if target_cid is None:
        raise IllegalActionError(f"component {comp_id_str!r} not found")

    for zone_name, zone in session.runtime.zones.items():
        if isinstance(zone, GridZone):
            for row in range(zone.height):
                for col in range(zone.width):
                    if zone.grid_get(col, row) == target_cid:
                        return target_cid, zone_name, col, row

    raise IllegalActionError(
        f"component {comp_id_str!r} not found on any grid"
    )


def _parse_position(pos: Position | None) -> tuple[int, int]:
    """Parse a Position into (col, row) coordinates."""
    if pos is None:
        raise IllegalActionError("missing position")
    if isinstance(pos, str):
        return _parse_coord_str(pos)
    if isinstance(pos, dict):
        cell = pos.get("cell", "0,0")
        return _parse_coord_str(cell)
    raise IllegalActionError(f"invalid position: {pos!r}")


def _parse_coord_str(s: str) -> tuple[int, int]:
    """Parse a 'col,row' string into (col, row) tuple."""
    parts = s.split(",")
    if len(parts) != 2:
        raise IllegalActionError(f"invalid coordinate format: {s}")
    try:
        col = int(parts[0].strip())
        row = int(parts[1].strip())
    except ValueError as exc:
        raise IllegalActionError(f"invalid coordinate: {s}") from exc
    if col < 0 or row < 0:
        raise IllegalActionError(
            f"coordinates must be non-negative, got ({col}, {row})"
        )
    return col, row


def _lookup_span(definition: GameDefinition, comp_type: str) -> int:
    """Look up span for a component type from the game definition.

    Checks (in order):
    1. Component types[comp_type]["span"] (per-type span)
    2. Component-level span
    3. Default: 1
    """
    for comp_def in definition.components.values():
        if comp_def.types is not None and comp_type in comp_def.types:
            type_def = comp_def.types[comp_type]
            if isinstance(type_def, dict) and "span" in type_def:
                return int(type_def["span"])
        if comp_def.span is not None:
            return comp_def.span
    return 1


def _position_zone(pos: Position | None) -> str | None:
    """Extract zone name from a position, if it's structured."""
    if isinstance(pos, dict):
        zone = pos.get("zone")
        if isinstance(zone, str):
            return zone
    return None


def _make_event(
    sequence: int,
    event_type: EventTypeLiteral,
    player: str,
    component_id: str | None = None,
    from_pos: str | None = None,
    to_pos: str | None = None,
    prev_hash: str | None = None,
) -> GameEvent:
    """Create a GameEvent with state_hash placeholder."""
    return GameEvent(
        sequence=sequence,
        event_type=event_type,
        player=player,
        component_id=component_id,
        from_pos=from_pos,
        to_pos=to_pos,
        state_hash="",  # filled in after state mutation
        prev_hash=prev_hash,
    )
