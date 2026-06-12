"""Dataclasses matching game-state.schema.json.

Runtime game state: board positions, player hands, draw piles, scores,
turn pointer, and phase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Enums as Literals
# ---------------------------------------------------------------------------

GameStatusLiteral = Literal["setup", "in_progress", "finished"]
FacingLiteral = Literal["face_up", "face_down"]
OutcomeLiteral = Literal["win", "draw", "abandoned"]
ZoneStateTypeLiteral = Literal[
    "grid", "ordered_stack", "set", "single_slot", "counter", "track",
]


# ---------------------------------------------------------------------------
# ComponentInstance
# ---------------------------------------------------------------------------

@dataclass
class ComponentInstance:
    id: str
    component_type: str
    owner: str | None = None
    facing: FacingLiteral | None = None
    state: str | None = None
    properties: dict[str, Any] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ComponentInstance:
        if "id" not in d:
            raise ValueError("component instance dict missing required 'id' key")
        if "component_type" not in d:
            raise ValueError("component instance dict missing required 'component_type' key")
        return ComponentInstance(
            id=d["id"],
            component_type=d["component_type"],
            owner=d.get("owner"),
            facing=d.get("facing"),
            state=d.get("state"),
            properties=d.get("properties"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "component_type": self.component_type,
        }
        if self.owner is not None:
            out["owner"] = self.owner
        if self.facing is not None:
            out["facing"] = self.facing
        if self.state is not None:
            out["state"] = self.state
        if self.properties is not None:
            out["properties"] = self.properties
        return out


# ---------------------------------------------------------------------------
# Zone states (discriminated by zone_type)
# ---------------------------------------------------------------------------

CellPropertyValue = str | int | bool


@dataclass
class GridState:
    cells: dict[str, ComponentInstance | list[ComponentInstance] | None]
    cell_properties: dict[str, dict[str, CellPropertyValue]] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> GridState:
        cells: dict[str, ComponentInstance | list[ComponentInstance] | None] = {}
        for k, v in d.get("cells", {}).items():
            if v is None:
                cells[k] = None
            elif isinstance(v, list):
                cells[k] = [ComponentInstance.from_dict(ci) for ci in v]
            else:
                cells[k] = ComponentInstance.from_dict(v)
        raw_props = d.get("cell_properties")
        cell_properties = dict(raw_props) if raw_props else None
        return GridState(cells=cells, cell_properties=cell_properties)

    def to_dict(self) -> dict[str, Any]:
        cells_out: dict[str, Any] = {}
        for k, v in self.cells.items():
            if v is None:
                cells_out[k] = None
            elif isinstance(v, list):
                cells_out[k] = [ci.to_dict() for ci in v]
            else:
                cells_out[k] = v.to_dict()
        out: dict[str, Any] = {"zone_type": "grid", "cells": cells_out}
        if self.cell_properties:
            out["cell_properties"] = self.cell_properties
        return out


@dataclass
class StackState:
    components: list[ComponentInstance]
    count: int | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> StackState:
        return StackState(
            components=[ComponentInstance.from_dict(c) for c in d.get("components", [])],
            count=d.get("count"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "zone_type": "ordered_stack",
            "components": [c.to_dict() for c in self.components],
        }
        if self.count is not None:
            out["count"] = self.count
        return out


@dataclass
class SetState:
    components: list[ComponentInstance]
    count: int | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SetState:
        return SetState(
            components=[ComponentInstance.from_dict(c) for c in d.get("components", [])],
            count=d.get("count"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "zone_type": "set",
            "components": [c.to_dict() for c in self.components],
        }
        if self.count is not None:
            out["count"] = self.count
        return out


@dataclass
class SlotState:
    component: ComponentInstance | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> SlotState:
        comp_raw = d.get("component")
        comp = ComponentInstance.from_dict(comp_raw) if comp_raw is not None else None
        return SlotState(component=comp)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"zone_type": "single_slot"}
        if self.component is not None:
            out["component"] = self.component.to_dict()
        else:
            out["component"] = None
        return out


@dataclass
class CounterState:
    value: int | float

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CounterState:
        if "value" not in d:
            raise ValueError("counter state dict missing required 'value' key")
        return CounterState(value=d["value"])

    def to_dict(self) -> dict[str, Any]:
        return {"zone_type": "counter", "value": self.value}


@dataclass
class TrackState:
    positions: dict[str, list[ComponentInstance]]

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TrackState:
        positions: dict[str, list[ComponentInstance]] = {}
        for k, v in d.get("positions", {}).items():
            positions[k] = [ComponentInstance.from_dict(ci) for ci in v]
        return TrackState(positions=positions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_type": "track",
            "positions": {k: [ci.to_dict() for ci in v] for k, v in self.positions.items()},
        }


ZoneState = GridState | StackState | SetState | SlotState | CounterState | TrackState


def _zone_state_from_dict(d: dict[str, Any]) -> ZoneState:
    if "zone_type" not in d:
        raise ValueError(f"zone state dict missing 'zone_type' key: {d!r}")
    zt = d["zone_type"]
    if zt == "grid":
        return GridState.from_dict(d)
    if zt == "ordered_stack":
        return StackState.from_dict(d)
    if zt == "set":
        return SetState.from_dict(d)
    if zt == "single_slot":
        return SlotState.from_dict(d)
    if zt == "counter":
        return CounterState.from_dict(d)
    if zt == "track":
        return TrackState.from_dict(d)
    raise ValueError(f"unknown zone_type: {zt!r}")


def _zone_state_to_dict(zs: ZoneState) -> dict[str, Any]:
    return zs.to_dict()


# ---------------------------------------------------------------------------
# ClockState
# ---------------------------------------------------------------------------

@dataclass
class ClockState:
    remaining_ms: int | None = None
    increment_ms: int | None = None
    running: bool | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ClockState:
        return ClockState(
            remaining_ms=d.get("remaining_ms"),
            increment_ms=d.get("increment_ms"),
            running=d.get("running"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.remaining_ms is not None:
            out["remaining_ms"] = self.remaining_ms
        if self.increment_ms is not None:
            out["increment_ms"] = self.increment_ms
        if self.running is not None:
            out["running"] = self.running
        return out


# ---------------------------------------------------------------------------
# PlayerState
# ---------------------------------------------------------------------------

@dataclass
class PlayerState:
    user_id: str | None = None
    seat: str | None = None
    active: bool | None = None
    connected: bool | None = None
    score: int | float | None = None
    counters: dict[str, int | float] | None = None
    zones: dict[str, ZoneState] | None = None
    clock: ClockState | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PlayerState:
        zones_raw = d.get("zones")
        zones: dict[str, ZoneState] | None = None
        if zones_raw is not None:
            zones = {k: _zone_state_from_dict(v) for k, v in zones_raw.items()}
        clock_raw = d.get("clock")
        clock = ClockState.from_dict(clock_raw) if clock_raw is not None else None
        return PlayerState(
            user_id=d.get("user_id"),
            seat=d.get("seat"),
            active=d.get("active"),
            connected=d.get("connected"),
            score=d.get("score"),
            counters=d.get("counters"),
            zones=zones,
            clock=clock,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.user_id is not None:
            out["user_id"] = self.user_id
        if self.seat is not None:
            out["seat"] = self.seat
        if self.active is not None:
            out["active"] = self.active
        if self.connected is not None:
            out["connected"] = self.connected
        if self.score is not None:
            out["score"] = self.score
        if self.counters is not None:
            out["counters"] = self.counters
        if self.zones is not None:
            out["zones"] = {k: _zone_state_to_dict(v) for k, v in self.zones.items()}
        if self.clock is not None:
            out["clock"] = self.clock.to_dict()
        return out


# ---------------------------------------------------------------------------
# PendingAction
# ---------------------------------------------------------------------------

@dataclass
class PendingAction:
    player: str
    action_type: str
    submitted: bool | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PendingAction:
        if "player" not in d:
            raise ValueError("pending action dict missing required 'player' key")
        if "action_type" not in d:
            raise ValueError("pending action dict missing required 'action_type' key")
        return PendingAction(
            player=d["player"],
            action_type=d["action_type"],
            submitted=d.get("submitted"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "player": self.player,
            "action_type": self.action_type,
        }
        if self.submitted is not None:
            out["submitted"] = self.submitted
        return out


# ---------------------------------------------------------------------------
# GameResult
# ---------------------------------------------------------------------------

@dataclass
class GameResult:
    outcome: OutcomeLiteral
    winner: str | None = None
    condition: str | None = None
    final_scores: dict[str, int | float] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> GameResult:
        if "outcome" not in d:
            raise ValueError("game result dict missing required 'outcome' key")
        return GameResult(
            outcome=d["outcome"],
            winner=d.get("winner"),
            condition=d.get("condition"),
            final_scores=d.get("final_scores"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"outcome": self.outcome}
        if self.winner is not None:
            out["winner"] = self.winner
        if self.condition is not None:
            out["condition"] = self.condition
        if self.final_scores is not None:
            out["final_scores"] = self.final_scores
        return out


# ---------------------------------------------------------------------------
# GameState  (top-level)
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    game_id: str
    schema_ref: str
    sequence: int
    status: GameStatusLiteral
    turn: str
    phase: str
    zones: dict[str, ZoneState]
    players: dict[str, PlayerState]
    state_hash: str | None = None
    result: GameResult | None = None
    move_count: int | None = None
    halfmove_clock: int | None = None
    counters: dict[str, int | float] | None = None
    pending_actions: list[PendingAction] = field(default_factory=list)
    pending_commits: dict[str, str] | None = None
    history_hash: str | None = None
    timestamp: str | None = None

    @classmethod
    def from_json(cls, json_str: str) -> GameState:
        """Parse a GameState from a JSON string."""
        from baize.error import ParseError

        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ParseError(str(exc)) from exc
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> GameState:
        from baize.error import ParseError

        try:
            for required in ("game_id", "schema_ref", "sequence", "status",
                             "turn", "phase", "zones", "players"):
                if required not in d:
                    raise KeyError(f"game state missing required key: {required!r}")
            zones = {k: _zone_state_from_dict(v) for k, v in d["zones"].items()}
            players = {k: PlayerState.from_dict(v) for k, v in d["players"].items()}
            result_raw = d.get("result")
            result = GameResult.from_dict(result_raw) if result_raw is not None else None
            pending = [PendingAction.from_dict(pa) for pa in d.get("pending_actions", [])]

            return cls(
                game_id=d["game_id"],
                schema_ref=d["schema_ref"],
                sequence=d["sequence"],
                status=d["status"],
                turn=d["turn"],
                phase=d["phase"],
                zones=zones,
                players=players,
                state_hash=d.get("state_hash"),
                result=result,
                move_count=d.get("move_count"),
                halfmove_clock=d.get("halfmove_clock"),
                counters=d.get("counters"),
                pending_actions=pending,
                pending_commits=d.get("pending_commits"),
                history_hash=d.get("history_hash"),
                timestamp=d.get("timestamp"),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(str(exc)) from exc

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict[str, Any]:
        # Field order must match Rust's serde struct declaration order
        # for cross-implementation hash consistency.
        out: dict[str, Any] = {
            "game_id": self.game_id,
            "schema_ref": self.schema_ref,
            "sequence": self.sequence,
        }
        if self.state_hash is not None:
            out["state_hash"] = self.state_hash
        out["status"] = self.status
        if self.result is not None:
            out["result"] = self.result.to_dict()
        out["turn"] = self.turn
        out["phase"] = self.phase
        if self.move_count is not None:
            out["move_count"] = self.move_count
        if self.halfmove_clock is not None:
            out["halfmove_clock"] = self.halfmove_clock
        out["zones"] = {k: _zone_state_to_dict(v) for k, v in self.zones.items()}
        out["players"] = {k: v.to_dict() for k, v in self.players.items()}
        if self.counters is not None:
            out["counters"] = self.counters
        if self.pending_actions:
            out["pending_actions"] = [pa.to_dict() for pa in self.pending_actions]
        if self.pending_commits:
            out["pending_commits"] = self.pending_commits
        if self.history_hash is not None:
            out["history_hash"] = self.history_hash
        if self.timestamp is not None:
            out["timestamp"] = self.timestamp
        return out
