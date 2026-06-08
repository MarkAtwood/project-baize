"""Runtime game state: mutable board state, component tracking, and game session.

Ports the Rust structs from engine/src/runtime.rs:
  - ComponentId, ComponentData, ComponentTable
  - RuntimeZone (Grid, OrderedStack, Set, SingleSlot, Counter, Track)
  - RuntimePlayer, RuntimeState
  - GameSession
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import blake3

from baize.definition import (
    Capacity,
    GameDefinition,
    PlayerRange,
    Zone,
)
from baize.error import (
    IllegalActionError,
    InvalidComponentIdError,
    UnknownZoneError,
    ValidationError,
)
from baize.state import (
    ComponentInstance,
    CounterState,
    FacingLiteral,
    GameState,
    GridState,
    PlayerState,
    SetState,
    SlotState,
    StackState,
    TrackState,
    ZoneState,
)


# ---------------------------------------------------------------------------
# ComponentId
# ---------------------------------------------------------------------------


@dataclass
class ComponentId:
    """Compact component identifier (index into ComponentTable)."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int):
            raise ValidationError(
                f"ComponentId value must be an int, got {type(self.value).__name__}"
            )
        if self.value < 0:
            raise ValidationError(
                f"ComponentId value must be non-negative, got {self.value}"
            )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ComponentId):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)


# ---------------------------------------------------------------------------
# ComponentData
# ---------------------------------------------------------------------------


@dataclass
class ComponentData:
    """Internal representation of a single component instance."""

    id: ComponentId
    string_id: str
    component_type: str
    owner: str | None = None
    facing: FacingLiteral | None = None
    state: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_wire_instance(self) -> ComponentInstance:
        """Convert to wire-format ComponentInstance."""
        return ComponentInstance(
            id=self.string_id,
            component_type=self.component_type,
            owner=self.owner,
            facing=self.facing,
            state=self.state,
            properties=self.properties if self.properties else None,
        )


# ---------------------------------------------------------------------------
# ComponentTable
# ---------------------------------------------------------------------------


class ComponentTable:
    """Arena of all component instances in the game."""

    def __init__(self) -> None:
        self._entries: list[ComponentData] = []

    def insert(self, data: ComponentData) -> ComponentId:
        """Insert a component and return its assigned ID."""
        cid = ComponentId(len(self._entries))
        data.id = cid
        self._entries.append(data)
        return cid

    def get(self, cid: ComponentId) -> ComponentData | None:
        """Get a component by ID, or None if out of range."""
        if not isinstance(cid, ComponentId):
            raise ValidationError(
                f"expected ComponentId, got {type(cid).__name__}"
            )
        if 0 <= cid.value < len(self._entries):
            return self._entries[cid.value]
        return None

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def __iter__(self) -> Iterator[ComponentData]:
        return iter(self._entries)


# ---------------------------------------------------------------------------
# RuntimeZone
# ---------------------------------------------------------------------------


@dataclass
class GridZone:
    """Grid-based zone with width x height cells."""

    width: int
    height: int
    cells: list[ComponentId | None]

    def grid_get(self, col: int, row: int) -> ComponentId | None:
        if col < 0 or row < 0 or col >= self.width or row >= self.height:
            return None
        return self.cells[row * self.width + col]

    def grid_set(
        self, col: int, row: int, component: ComponentId | None
    ) -> ComponentId | None:
        if col < 0 or row < 0 or col >= self.width or row >= self.height:
            return None
        idx = row * self.width + col
        prev = self.cells[idx]
        self.cells[idx] = component
        return prev

    def count(self) -> int:
        return sum(1 for c in self.cells if c is not None)

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity


@dataclass
class StackZone:
    """Ordered stack zone (LIFO)."""

    components: list[ComponentId] = field(default_factory=list)

    def stack_push(self, component: ComponentId) -> None:
        self.components.append(component)

    def stack_pop(self) -> ComponentId | None:
        if self.components:
            return self.components.pop()
        return None

    def count(self) -> int:
        return len(self.components)

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity


@dataclass
class SetZone:
    """Unordered set zone."""

    components: list[ComponentId] = field(default_factory=list)

    def set_add(self, component: ComponentId) -> None:
        self.components.append(component)

    def set_remove(self, component: ComponentId) -> bool:
        for i, c in enumerate(self.components):
            if c == component:
                # swap_remove equivalent
                self.components[i] = self.components[-1]
                self.components.pop()
                return True
        return False

    def count(self) -> int:
        return len(self.components)

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity


@dataclass
class SlotZone:
    """Single-slot zone holding at most one component."""

    component: ComponentId | None = None

    def count(self) -> int:
        return 1 if self.component is not None else 0

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity


@dataclass
class CounterZone:
    """Counter zone holding a numeric value (no components)."""

    value: int = 0

    def count(self) -> int:
        return 0

    def is_full(self, capacity: Capacity | None) -> bool:
        return False


@dataclass
class TrackZone:
    """Track zone: a linear sequence of positions, each holding components."""

    positions: list[list[ComponentId]] = field(default_factory=list)

    def count(self) -> int:
        return sum(len(p) for p in self.positions)

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity


RuntimeZone = GridZone | StackZone | SetZone | SlotZone | CounterZone | TrackZone


def runtime_zone_from_definition(zone_def: Zone) -> RuntimeZone:
    """Create an empty runtime zone from a zone definition."""
    zt = zone_def.zone_type
    if zt in ("grid", "hex_grid"):
        dims = zone_def.dimensions
        if isinstance(dims, list) and len(dims) == 2:
            w, h = dims[0], dims[1]
        elif isinstance(dims, int):
            w, h = dims, dims
        elif zone_def.dynamic is True:
            w, h = 0, 0
        else:
            raise ValidationError("grid zone requires dimensions")
        if not isinstance(w, int) or not isinstance(h, int):
            raise ValidationError(
                f"grid dimensions must be integers, got ({type(w).__name__}, {type(h).__name__})"
            )
        if w < 0 or h < 0:
            raise ValidationError(
                f"grid dimensions must be non-negative, got ({w}, {h})"
            )
        return GridZone(width=w, height=h, cells=[None] * (w * h))
    if zt == "ordered_stack":
        return StackZone()
    if zt == "set":
        return SetZone()
    if zt == "queue":
        return StackZone()
    if zt == "single_slot":
        return SlotZone()
    if zt == "counter":
        return CounterZone()
    if zt == "track":
        length = zone_def.length or zone_def.points or 1
        if not isinstance(length, int) or length < 1:
            raise ValidationError(
                f"track length must be a positive integer, got {length!r}"
            )
        return TrackZone(positions=[[] for _ in range(length)])
    if zt == "graph":
        return SetZone()
    raise ValidationError(f"unknown zone type: {zt}")


# ---------------------------------------------------------------------------
# RuntimePlayer
# ---------------------------------------------------------------------------


@dataclass
class RuntimePlayer:
    """Per-player runtime state."""

    seat: str
    active: bool = True
    score: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    zones: dict[str, RuntimeZone] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RuntimeState
# ---------------------------------------------------------------------------


@dataclass
class RuntimeState:
    """The mutable runtime state of a game in progress."""

    status: str  # GameStatusLiteral
    turn_index: int = 0
    phase_index: int = 0
    sequence: int = 0
    move_count: int = 0
    halfmove_clock: int = 0
    components: ComponentTable = field(default_factory=ComponentTable)
    zones: dict[str, RuntimeZone] = field(default_factory=dict)
    players: dict[str, RuntimePlayer] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    history_hashes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GameSession
# ---------------------------------------------------------------------------


class GameSession:
    """A game session: static definition + mutable runtime state."""

    def __init__(self, definition: GameDefinition) -> None:
        self.definition = definition

        zones: dict[str, RuntimeZone] = {}
        player_zone_defs: dict[str, Zone] = {}

        for name, zone_def in definition.zones.items():
            if zone_def.per_player is True:
                player_zone_defs[name] = zone_def
            else:
                zones[name] = runtime_zone_from_definition(zone_def)

        # Determine player names
        if isinstance(definition.game.players, list):
            player_names: list[str] = definition.game.players
        elif isinstance(definition.game.players, PlayerRange):
            if definition.game.players.min < 0:
                raise ValidationError(
                    f"player range min must be non-negative, got {definition.game.players.min}"
                )
            player_names = [
                f"player_{i}" for i in range(definition.game.players.min)
            ]
        else:
            raise ValidationError(
                f"players must be a list or PlayerRange, got {type(definition.game.players).__name__}"
            )

        players: dict[str, RuntimePlayer] = {}
        for pname in player_names:
            pzones: dict[str, RuntimeZone] = {}
            for zname, zdef in player_zone_defs.items():
                pzones[zname] = runtime_zone_from_definition(zdef)
            players[pname] = RuntimePlayer(seat=pname, zones=pzones)

        self.runtime = RuntimeState(
            status="setup",
            zones=zones,
            players=players,
        )

    def current_player(self) -> str | None:
        """The name of the player whose turn it is."""
        if isinstance(self.definition.game.players, list):
            names = self.definition.game.players
            if self.runtime.turn_index < len(names):
                return names[self.runtime.turn_index]
            return None
        # PlayerRange: use player dict ordering
        player_keys = list(self.runtime.players.keys())
        if self.runtime.turn_index < len(player_keys):
            return player_keys[self.runtime.turn_index]
        return None

    def is_perfect_information(self) -> bool:
        """Whether this is a perfect-information game."""
        return self.definition.game.information == "perfect"

    def advance_turn(self) -> None:
        """Advance the turn to the next player."""
        player_count = len(self.runtime.players)
        if player_count > 0:
            self.runtime.turn_index = (self.runtime.turn_index + 1) % player_count
        self.runtime.sequence += 1
        self.runtime.move_count += 1

    def compute_state_hash(self) -> str:
        """Compute a BLAKE3 hash of the current state for repetition detection.

        Uses compact JSON (no whitespace) with field order matching
        the Rust serde serialization for cross-implementation consistency.
        """
        state = self.to_wire_state()
        canonical = json.dumps(
            state._to_dict(), separators=(",", ":"), sort_keys=False
        )
        return blake3.blake3(canonical.encode("utf-8")).hexdigest()

    def to_wire_state(self) -> GameState:
        """Convert runtime state to wire-format GameState for serialization."""
        turn = self.current_player() or ""
        if (
            self.definition.phases
            and self.runtime.phase_index < len(self.definition.phases)
        ):
            phase = self.definition.phases[self.runtime.phase_index].name
        else:
            phase = "main"

        wire_zones: dict[str, ZoneState] = {}
        for name, zone in self.runtime.zones.items():
            wire_zones[name] = self._zone_to_wire(zone)

        wire_players: dict[str, PlayerState] = {}
        for name, player in self.runtime.players.items():
            pzones: dict[str, ZoneState] = {}
            for zname, zone in player.zones.items():
                pzones[zname] = self._zone_to_wire(zone)
            wire_players[name] = PlayerState(
                seat=player.seat,
                active=player.active,
                score=player.score,
                counters=dict(player.counters) if player.counters else None,
                zones=pzones if pzones else None,
            )

        counters: dict[str, int | float] | None = None
        if self.runtime.counters:
            counters = dict(self.runtime.counters)

        return GameState(
            game_id="",
            schema_ref="",
            sequence=self.runtime.sequence,
            status=self.runtime.status,  # type: ignore[arg-type]
            turn=turn,
            phase=phase,
            zones=wire_zones,
            players=wire_players,
            move_count=self.runtime.move_count,
            halfmove_clock=self.runtime.halfmove_clock,
            counters=counters,
            history_hash=(
                self.runtime.history_hashes[-1]
                if self.runtime.history_hashes
                else None
            ),
        )

    def _zone_to_wire(self, zone: RuntimeZone) -> ZoneState:
        """Convert a runtime zone to wire-format ZoneState."""
        if isinstance(zone, GridZone):
            cells: dict[str, ComponentInstance | list[ComponentInstance] | None] = {}
            for row in range(zone.height):
                for col in range(zone.width):
                    idx = row * zone.width + col
                    cid = zone.cells[idx]
                    if cid is not None:
                        comp = self.runtime.components.get(cid)
                        if comp is not None:
                            coord = f"{col},{row}"
                            cells[coord] = comp.to_wire_instance()
            return GridState(cells=cells)

        if isinstance(zone, StackZone):
            components = []
            for cid in zone.components:
                comp = self.runtime.components.get(cid)
                if comp is not None:
                    components.append(comp.to_wire_instance())
            return StackState(components=components)

        if isinstance(zone, SetZone):
            components = []
            for cid in zone.components:
                comp = self.runtime.components.get(cid)
                if comp is not None:
                    components.append(comp.to_wire_instance())
            return SetState(components=components)

        if isinstance(zone, SlotZone):
            comp_instance = None
            if zone.component is not None:
                comp = self.runtime.components.get(zone.component)
                if comp is not None:
                    comp_instance = comp.to_wire_instance()
            return SlotState(component=comp_instance)

        if isinstance(zone, CounterZone):
            return CounterState(value=zone.value)

        if isinstance(zone, TrackZone):
            positions: dict[str, list[ComponentInstance]] = {}
            for i, pos in enumerate(zone.positions):
                if pos:
                    instances = []
                    for cid in pos:
                        comp = self.runtime.components.get(cid)
                        if comp is not None:
                            instances.append(comp.to_wire_instance())
                    positions[str(i)] = instances
            return TrackState(positions=positions)

        raise ValidationError(f"unknown zone type: {type(zone)}")
