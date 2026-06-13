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
from baize.betting import BettingRoundState
from baize.definition import GameDefinition, TriggerDef
from baize.end_conditions import check_end_conditions
from baize.error import IllegalActionError, InvalidCoordinateError, ResourceBudgetError, UnknownZoneError
from baize.runtime import (
    ClaimWindow,
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GridZone,
    MAX_EVENTS_PER_GAME,
    MAX_STATE_SIZE_BYTES,
    SetZone,
    STATE_SIZE_CHECK_INTERVAL,
    StackZone,
)


def _enforce_event_budget(session: GameSession, new_events: int) -> None:
    """Raise ResourceBudgetError if the event budget would be exceeded."""
    new_total = session.runtime.event_count + new_events
    if new_total > MAX_EVENTS_PER_GAME:
        raise ResourceBudgetError(
            "events", new_total, MAX_EVENTS_PER_GAME
        )


def _enforce_state_size(session: GameSession) -> None:
    """Check serialized state size periodically (amortized)."""
    if (
        session.runtime.move_count > 0
        and session.runtime.move_count % STATE_SIZE_CHECK_INTERVAL == 0
    ):
        import json as _json

        wire = session.to_wire_state()
        size = len(_json.dumps(wire._to_dict(), separators=(",", ":")))
        if size > MAX_STATE_SIZE_BYTES:
            raise ResourceBudgetError(
                "state_size_bytes", size, MAX_STATE_SIZE_BYTES
            )


def _validate_grid_coords(
    zone: GridZone, col: int, row: int, zone_name: str
) -> None:
    """Raise InvalidCoordinateError if (col, row) is outside the grid."""
    if zone._sparse:
        # Sparse grids with dimension hints still enforce bounds
        if zone.width > 0 and zone.height > 0:
            if col < 0 or row < 0 or col >= zone.width or row >= zone.height:
                raise InvalidCoordinateError(col, row, zone.width, zone.height)
        # Unbounded sparse grids accept any coordinate (negative coords
        # are still disallowed by _parse_coord_str for standard actions)
        return
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
    "fold",
    "check",
    "call",
    "raise",
    "all_in",
    "action_submitted",
    "trigger_activated",
    "claim_submitted",
    "claim_resolved",
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

    # If a claim window is active, reject normal actions
    if session.runtime.claim_window is not None:
        raise IllegalActionError(
            "claim window is active — use apply_claim instead"
        )

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

    # Check if any trigger matches the action just applied
    trigger_match = _find_matching_trigger(session, action)
    if trigger_match is not None:
        trigger_name, trigger_def = trigger_match
        eligible = _compute_eligible_players(session, trigger_def.claim_window.eligible)

        if eligible:
            session.runtime.claim_window = ClaimWindow(
                trigger_name=trigger_name,
                triggering_action=action,
                triggering_player=player,
                eligible_players=eligible,
                submitted_claims={},
                priority=list(trigger_def.claim_window.priority),
                default_claim=trigger_def.claim_window.default,
            )

            events.append(GameEvent(
                sequence=session.runtime.sequence,
                event_type="trigger_activated",
                player=player,
                detail=trigger_name,
                state_hash="",
                prev_hash=prev_hash,
            ))

            # Hash state but do NOT advance turn
            _enforce_event_budget(session, len(events))
            new_hash = session.compute_state_hash()
            session.runtime.history_hashes.append(new_hash)
            for event in events:
                event.state_hash = new_hash
            session.runtime.event_count += len(events)
            return events

    # Enforce resource budgets
    _enforce_event_budget(session, len(events) + 1)  # +1 for turn_advance/game_end
    _enforce_state_size(session)

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

            session.runtime.event_count += len(events)
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

    session.runtime.event_count += len(events)
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

        # Enforce resource budgets
        _enforce_event_budget(session, len(events) + 1)
        _enforce_state_size(session)

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
                session.runtime.event_count += len(events)
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
        session.runtime.event_count += len(events)

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

        # Check for capture or stacking
        captured = zone.grid_get(to_col, to_row)
        if captured is not None:
            if zone.stacking_limit == 1:
                # Capture: replace occupant
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
                zone.grid_set(from_col, from_row, None)
                zone.grid_set(to_col, to_row, cid)
            else:
                # Stacking: push onto destination
                zone.grid_set(from_col, from_row, None)
                zone.grid_push(to_col, to_row, cid)
        else:
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

        # Recompute fog after move on fog-enabled zones
        _recompute_fog_for_player(session, zone, player)

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

        existing = zone.grid_get(to_col, to_row)
        if existing is not None:
            if zone.stacking_limit == 1:
                raise IllegalActionError(
                    f"cell ({to_col},{to_row}) is already occupied"
                )
            # stacking_limit > 1 or 0 (unlimited): push onto stack
            zone.grid_push(to_col, to_row, cid)
        else:
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

        # Recompute fog after place on fog-enabled zones
        _recompute_fog_for_player(session, zone, player)

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
            elif isinstance(first_hand, SetZone):
                first_hand.set_add(cid_drawn)
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

    elif action.action_type == "fold":
        bs = _get_or_init_betting_state(session, player)
        if player not in bs.active_players:
            raise IllegalActionError("player already folded")
        bs.active_players.remove(player)
        bs.acted.discard(player)
        events.append(
            _make_event(
                session.runtime.sequence,
                "fold",
                player,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "check":
        bs = _get_or_init_betting_state(session, player)
        if player not in bs.active_players:
            raise IllegalActionError("player has folded")
        player_contrib = bs.contributions.get(player, 0)
        if bs.current_bet != player_contrib:
            raise IllegalActionError(
                f"cannot check: current bet is {bs.current_bet}, "
                f"player has contributed {player_contrib}"
            )
        bs.acted.add(player)
        events.append(
            _make_event(
                session.runtime.sequence,
                "check",
                player,
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "call":
        bs = _get_or_init_betting_state(session, player)
        if player not in bs.active_players:
            raise IllegalActionError("player has folded")
        player_contrib = bs.contributions.get(player, 0)
        call_amount = bs.current_bet - player_contrib
        if call_amount <= 0:
            raise IllegalActionError("nothing to call")
        chips = _get_player_chips(session, player)
        if chips < call_amount:
            raise IllegalActionError(
                f"not enough chips to call: need {call_amount}, have {chips}"
            )
        _transfer_chips(session, player, call_amount)
        bs.contributions[player] = bs.current_bet
        bs.acted.add(player)
        events.append(
            _make_event(
                session.runtime.sequence,
                "call",
                player,
                detail=str(call_amount),
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "raise":
        bs = _get_or_init_betting_state(session, player)
        if player not in bs.active_players:
            raise IllegalActionError("player has folded")
        raise_to = action.amount
        if raise_to is None:
            raise IllegalActionError("raise requires amount")
        raise_to = int(raise_to)
        if raise_to <= bs.current_bet:
            raise IllegalActionError(
                f"raise amount {raise_to} must exceed current bet {bs.current_bet}"
            )
        player_contrib = bs.contributions.get(player, 0)
        cost = raise_to - player_contrib
        chips = _get_player_chips(session, player)
        if chips < cost:
            raise IllegalActionError(
                f"not enough chips to raise: need {cost}, have {chips}"
            )
        _transfer_chips(session, player, cost)
        bs.contributions[player] = raise_to
        bs.current_bet = raise_to
        bs.last_raiser = player
        # Reset acted: everyone else must respond to the raise
        bs.acted = {player}
        events.append(
            _make_event(
                session.runtime.sequence,
                "raise",
                player,
                detail=str(raise_to),
                prev_hash=prev_hash,
            )
        )

    elif action.action_type == "all_in":
        bs = _get_or_init_betting_state(session, player)
        if player not in bs.active_players:
            raise IllegalActionError("player has folded")
        chips = _get_player_chips(session, player)
        if chips <= 0:
            raise IllegalActionError("player has no chips")
        player_contrib = bs.contributions.get(player, 0)
        total_after = player_contrib + chips
        _transfer_chips(session, player, chips)
        bs.contributions[player] = total_after
        bs.all_in_players.add(player)
        bs.acted.add(player)
        if total_after > bs.current_bet:
            # All-in acts as a raise
            bs.current_bet = total_after
            bs.last_raiser = player
            bs.acted = {player}
        events.append(
            _make_event(
                session.runtime.sequence,
                "all_in",
                player,
                detail=str(chips),
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


def _recompute_fog_for_player(
    session: GameSession, zone: GridZone, player: str
) -> None:
    """Recompute fog for a player on a fog-enabled zone.

    Finds all of the player's units on the zone and recomputes fog using
    the zone's configured vision_range.
    """
    if zone.fog_config is None or zone.cell_fog is None:
        return
    unit_positions: list[tuple[int, int]] = []
    for col, row, cid in zone.occupied_cells():
        comp = session.runtime.components.get(cid)
        if comp is not None and comp.owner == player:
            unit_positions.append((col, row))
    zone.recompute_fog(player, unit_positions, zone.fog_config.vision_range)


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
            for col, row, cid in zone.occupied_cells():
                if cid == target_cid:
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
    detail: str | None = None,
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
        detail=detail,
        state_hash="",  # filled in after state mutation
        prev_hash=prev_hash,
    )


# ---------------------------------------------------------------------------
# Betting helpers
# ---------------------------------------------------------------------------


def _get_or_init_betting_state(
    session: GameSession, player: str
) -> BettingRoundState:
    """Return the session's BettingRoundState, initializing if needed."""
    if session.runtime.betting_state is None:
        bs = BettingRoundState()
        bs.init_round(list(session.runtime.players.keys()))
        session.runtime.betting_state = bs
    return session.runtime.betting_state


def _get_player_chips(session: GameSession, player: str) -> int:
    """Get a player's chip count from their player_chips counter zone."""
    pstate = session.runtime.players.get(player)
    if pstate is None:
        raise IllegalActionError(f"unknown player: {player}")
    chip_zone = pstate.zones.get("player_chips")
    if isinstance(chip_zone, CounterZone):
        return chip_zone.value
    raise IllegalActionError(f"player {player} has no chip counter")


def _transfer_chips(session: GameSession, player: str, amount: int) -> None:
    """Deduct chips from a player and add to the pot."""
    pstate = session.runtime.players.get(player)
    if pstate is None:
        raise IllegalActionError(f"unknown player: {player}")
    chip_zone = pstate.zones.get("player_chips")
    if not isinstance(chip_zone, CounterZone):
        raise IllegalActionError(f"player {player} has no chip counter")
    chip_zone.value -= amount
    pot = session.runtime.zones.get("pot")
    if isinstance(pot, CounterZone):
        pot.value += amount


# ---------------------------------------------------------------------------
# Server action parsing and execution (poker phases)
# ---------------------------------------------------------------------------


@dataclass
class ParsedServerAction:
    """Parsed representation of a server action string."""

    verb: str
    positional: list[str]
    keyword: dict[str, str]


def parse_server_action(action_str: str) -> ParsedServerAction:
    """Parse a server action string like ``deal(deck, hand, count:2, to:each_player)``.

    Returns a :class:`ParsedServerAction` with verb, positional args, and keyword args.
    """
    action_str = action_str.strip()
    paren_open = action_str.find("(")
    paren_close = action_str.rfind(")")
    if paren_open == -1 or paren_close == -1 or paren_close <= paren_open:
        raise IllegalActionError(f"invalid server action string: {action_str!r}")
    verb = action_str[:paren_open].strip()
    if not verb:
        raise IllegalActionError(f"invalid server action string: {action_str!r}")
    args_str = action_str[paren_open + 1 : paren_close].strip()
    positional: list[str] = []
    keyword: dict[str, str] = {}
    if args_str:
        for part in args_str.split(","):
            part = part.strip()
            if ":" in part:
                key, _, val = part.partition(":")
                keyword[key.strip()] = val.strip()
            else:
                positional.append(part)
    return ParsedServerAction(verb=verb, positional=positional, keyword=keyword)


def _resolve_zone(
    session: GameSession,
    zone_name: str,
    player_name: str | None = None,
) -> StackZone | SetZone:
    """Look up a zone from the session, checking per-player zones if needed."""
    # Try per-player zone first if player specified
    if player_name is not None:
        player_state = session.runtime.players.get(player_name)
        if player_state is not None:
            pzone = player_state.zones.get(zone_name)
            if pzone is not None:
                if not isinstance(pzone, (StackZone, SetZone)):
                    raise IllegalActionError(
                        f"player zone {zone_name!r} is not a stack or set"
                    )
                return pzone
    # Try shared zones
    zone = session.runtime.zones.get(zone_name)
    if zone is not None:
        if not isinstance(zone, (StackZone, SetZone)):
            raise IllegalActionError(f"zone {zone_name!r} is not a stack or set")
        return zone
    raise UnknownZoneError(zone_name)


def _pop_from_stack(session: GameSession, zone_name: str) -> ComponentId:
    """Pop one component from a named StackZone; raises on empty or wrong type."""
    zone = session.runtime.zones.get(zone_name)
    if zone is None:
        raise UnknownZoneError(zone_name)
    if not isinstance(zone, StackZone):
        raise IllegalActionError(f"zone {zone_name!r} is not a stack")
    cid = zone.stack_pop()
    if cid is None:
        raise IllegalActionError(f"zone {zone_name!r} is empty")
    return cid


def _add_to_zone(zone: StackZone | SetZone, cid: ComponentId) -> None:
    """Add a component to either a StackZone or SetZone."""
    if isinstance(zone, StackZone):
        zone.stack_push(cid)
    elif isinstance(zone, SetZone):
        zone.set_add(cid)


def execute_server_action(session: GameSession, action_str: str) -> list[GameEvent]:
    """Execute a single server action string against the session.

    Supported verbs:
      - ``deal(src, dst, count:N, to:each_player)`` — deal N cards from src to
        each player's dst zone
      - ``deal(src, dst, count:N)`` — deal N cards from src to active player's dst
      - ``burn(src, dst, count:N)`` — move N cards from src to shared dst zone
      - ``reveal(src, dst, count:N)`` — move N cards from src to shared dst zone
    """
    parsed = parse_server_action(action_str)
    events: list[GameEvent] = []

    if parsed.verb == "deal":
        if len(parsed.positional) < 2:
            raise IllegalActionError(
                f"deal requires at least src and dst zones, got: {action_str!r}"
            )
        src_name = parsed.positional[0]
        dst_name = parsed.positional[1]
        count = int(parsed.keyword.get("count", "1"))
        to = parsed.keyword.get("to")

        if to == "each_player":
            for _ in range(count):
                for player_name in session.runtime.players:
                    cid = _pop_from_stack(session, src_name)
                    dst = _resolve_zone(session, dst_name, player_name)
                    _add_to_zone(dst, cid)
                    comp_data = session.runtime.components.get(cid)
                    comp_id = comp_data.string_id if comp_data is not None else ""
                    events.append(
                        _make_event(
                            session.runtime.sequence,
                            "draw",
                            player_name,
                            component_id=comp_id,
                        )
                    )
                    session.runtime.sequence += 1
        else:
            # Deal to active player (or first player)
            player_name = next(iter(session.runtime.players), "server")
            for _ in range(count):
                cid = _pop_from_stack(session, src_name)
                dst = _resolve_zone(session, dst_name, player_name)
                _add_to_zone(dst, cid)
                comp_data = session.runtime.components.get(cid)
                comp_id = comp_data.string_id if comp_data is not None else ""
                events.append(
                    _make_event(
                        session.runtime.sequence,
                        "draw",
                        player_name,
                        component_id=comp_id,
                    )
                )
                session.runtime.sequence += 1

    elif parsed.verb == "burn":
        if len(parsed.positional) < 2:
            raise IllegalActionError(
                f"burn requires src and dst zones, got: {action_str!r}"
            )
        src_name = parsed.positional[0]
        dst_name = parsed.positional[1]
        count = int(parsed.keyword.get("count", "1"))
        dst = _resolve_zone(session, dst_name)
        for _ in range(count):
            cid = _pop_from_stack(session, src_name)
            _add_to_zone(dst, cid)
            events.append(
                _make_event(
                    session.runtime.sequence,
                    "draw",
                    "server",
                    detail="burn",
                )
            )
            session.runtime.sequence += 1

    elif parsed.verb == "reveal":
        if len(parsed.positional) < 2:
            raise IllegalActionError(
                f"reveal requires src and dst zones, got: {action_str!r}"
            )
        src_name = parsed.positional[0]
        dst_name = parsed.positional[1]
        count = int(parsed.keyword.get("count", "1"))
        dst = _resolve_zone(session, dst_name)
        for _ in range(count):
            cid = _pop_from_stack(session, src_name)
            _add_to_zone(dst, cid)
            comp_data = session.runtime.components.get(cid)
            comp_id = comp_data.string_id if comp_data is not None else ""
            events.append(
                _make_event(
                    session.runtime.sequence,
                    "reveal",
                    "server",
                    component_id=comp_id,
                )
            )
            session.runtime.sequence += 1

    else:
        raise IllegalActionError(f"unknown server action verb: {parsed.verb!r}")

    return events


def execute_server_phase(session: GameSession, phase_name: str) -> list[GameEvent]:
    """Find a phase by name and execute its server_action(s).

    Raises ``IllegalActionError`` if the phase is not found or has no server_action.
    """
    phase = None
    for p in session.definition.phases:
        if p.name == phase_name:
            phase = p
            break
    if phase is None:
        raise IllegalActionError(f"unknown phase: {phase_name!r}")
    if phase.server_action is None:
        raise IllegalActionError(f"phase {phase_name!r} has no server_action")

    actions: list[str]
    if isinstance(phase.server_action, str):
        actions = [phase.server_action]
    else:
        actions = phase.server_action

    all_events: list[GameEvent] = []
    for action_str in actions:
        all_events.extend(execute_server_action(session, action_str))
    return all_events


# ---------------------------------------------------------------------------
# Trigger / claim window
# ---------------------------------------------------------------------------


def _find_matching_trigger(
    session: GameSession,
    action: Action,
) -> tuple[str, TriggerDef] | None:
    """Find a trigger whose on_action matches the given action type."""
    action_type = action.action_type
    for name, trigger in session.definition.triggers.items():
        if trigger.on_action == action_type:
            return (name, trigger)
    return None


def _compute_eligible_players(
    session: GameSession,
    eligible_rule: str,
) -> list[str]:
    """Compute which players are eligible for a claim window."""
    current = session.current_player() or ""
    all_players = list(session.runtime.players.keys())

    if eligible_rule == "all_except_current":
        return [p for p in all_players if p != current]
    elif eligible_rule == "next_in_order":
        player_count = len(all_players)
        if player_count == 0:
            return []
        next_index = (session.runtime.turn_index + 1) % player_count
        return [all_players[next_index]]
    else:
        raise IllegalActionError(f"unknown eligible rule: {eligible_rule!r}")


def apply_claim(
    session: GameSession,
    player: str,
    claim: str,
) -> list[GameEvent]:
    """Submit a claim during an active claim window.

    When all eligible players have responded, resolves the window:
    highest-priority claim wins, that player becomes active.
    """
    assert isinstance(session, GameSession), (
        f"session must be GameSession, got {type(session).__name__}"
    )

    window = session.runtime.claim_window
    if window is None:
        raise IllegalActionError("no active claim window")

    # Defensive: player must be eligible
    if player not in window.eligible_players:
        raise IllegalActionError(
            f"player {player!r} is not eligible for this claim window"
        )

    # Defensive: no double-submission
    if player in window.submitted_claims:
        raise IllegalActionError(
            f"player {player!r} has already submitted a claim"
        )

    # Defensive: claim must be valid
    trigger_def = session.definition.triggers.get(window.trigger_name)
    if trigger_def is None:
        raise IllegalActionError("trigger definition not found")

    valid_claims = set(trigger_def.claim_window.actions) | {trigger_def.claim_window.default}
    if claim not in valid_claims:
        raise IllegalActionError(
            f"invalid claim {claim!r} — valid: {sorted(valid_claims)}"
        )

    window.submitted_claims[player] = claim

    prev_hash = (
        session.runtime.history_hashes[-1]
        if session.runtime.history_hashes
        else None
    )

    events: list[GameEvent] = [
        GameEvent(
            sequence=session.runtime.sequence,
            event_type="claim_submitted",
            player=player,
            detail=claim,
            state_hash="",
            prev_hash=prev_hash,
        )
    ]

    # Check if all eligible players have submitted
    all_submitted = all(
        p in window.submitted_claims for p in window.eligible_players
    )

    if all_submitted:
        events.extend(_resolve_claim_window(session, prev_hash))
    else:
        new_hash = session.compute_state_hash()
        session.runtime.history_hashes.append(new_hash)
        for event in events:
            event.state_hash = new_hash
        session.runtime.event_count += len(events)

    return events


def _resolve_claim_window(
    session: GameSession,
    prev_hash: str | None,
) -> list[GameEvent]:
    """Resolve an active claim window after all claims are submitted."""
    window = session.runtime.claim_window
    assert window is not None, "resolve_claim_window called without active window"

    # Take ownership — clear the window
    session.runtime.claim_window = None

    # Find highest-priority non-default claim
    winning_claim: tuple[str, str] | None = None  # (player, claim)
    for priority_action in window.priority:
        for player, claim in window.submitted_claims.items():
            if claim == priority_action and claim != window.default_claim:
                winning_claim = (player, claim)
                break
        if winning_claim is not None:
            break

    events: list[GameEvent] = []

    if winning_claim is not None:
        winner, claim = winning_claim
        # Winner becomes the active player
        player_names = list(session.runtime.players.keys())
        assert winner in player_names, f"winner {winner!r} not in player list"
        winner_index = player_names.index(winner)
        session.runtime.turn_index = winner_index

        events.append(GameEvent(
            sequence=session.runtime.sequence,
            event_type="claim_resolved",
            player=winner,
            detail=claim,
            state_hash="",
            prev_hash=prev_hash,
        ))
    else:
        # All passed — advance turn normally
        session.advance_turn()
        events.append(GameEvent(
            sequence=session.runtime.sequence,
            event_type="claim_resolved",
            player="",
            detail="all_passed",
            state_hash="",
            prev_hash=prev_hash,
        ))

    new_hash = session.compute_state_hash()
    session.runtime.history_hashes.append(new_hash)
    for event in events:
        event.state_hash = new_hash

    # Add turn_advance event
    next_player = session.current_player() or ""
    events.append(GameEvent(
        sequence=session.runtime.sequence,
        event_type="turn_advance",
        player=next_player,
        state_hash=new_hash,
        prev_hash=prev_hash,
    ))

    session.runtime.event_count += len(events)
    return events
