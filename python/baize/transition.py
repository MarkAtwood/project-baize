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
from baize.error import IllegalActionError, InvalidCoordinateError, UnknownZoneError
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
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


def apply_action(session: GameSession, action: Action) -> list[GameEvent]:
    """Apply an action to the game session, mutating state and returning events."""
    player = session.current_player()
    if player is None:
        raise IllegalActionError("no current player")

    if session.runtime.status == "finished":
        raise IllegalActionError("game is finished")

    if session.runtime.status == "setup":
        session.runtime.status = "in_progress"

    prev_hash = (
        session.runtime.history_hashes[-1]
        if session.runtime.history_hashes
        else None
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

        zone = session.runtime.zones.get(zone_name)
        if zone is None:
            raise UnknownZoneError(zone_name)
        if not isinstance(zone, GridZone):
            raise IllegalActionError(f"zone {zone_name} is not a grid")
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

    else:
        raise IllegalActionError(
            f"action type {action.action_type!r} not yet implemented"
        )

    # Advance turn
    session.advance_turn()
    new_hash = session.compute_state_hash()
    session.runtime.history_hashes.append(new_hash)

    # Update hashes on all events
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
