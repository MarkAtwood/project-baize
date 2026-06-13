"""Runtime game state: mutable board state, component tracking, and game session.

Ports the Rust structs from engine/src/runtime.rs:
  - ComponentId, ComponentData, ComponentTable
  - RuntimeZone (Grid, OrderedStack, Set, SingleSlot, Counter, Track, Graph)
  - RuntimePlayer, RuntimeState
  - GameSession
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import blake3

from baize.betting import BettingRoundState
from baize.definition import (
    Capacity,
    FogOfWarConfig,
    GameDefinition,
    PlayerRange,
    Zone,
    _VALID_FOG_STATES,
)
from baize.error import (
    IllegalActionError,
    InvalidComponentIdError,
    ResourceBudgetError,
    UnknownZoneError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Resource budget defaults
# ---------------------------------------------------------------------------

#: Maximum component instances per game session.
MAX_COMPONENTS_PER_GAME: int = 10_000

#: Maximum event log entries per game session.
MAX_EVENTS_PER_GAME: int = 100_000

#: Maximum serialized state size in bytes (checked periodically, not every move).
MAX_STATE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB

#: Check state size every N moves (amortized cost).
STATE_SIZE_CHECK_INTERVAL: int = 100

#: Maximum cells in a sparse grid — prevents unbounded memory growth.
SPARSE_GRID_MAX_CELLS: int = 1_000_000

#: Per-axis threshold above which we auto-select sparse storage.
SPARSE_AUTO_THRESHOLD: int = 1_000
from baize.state import (
    ComponentInstance,
    CounterState,
    FacingLiteral,
    GameResult,
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
    span_cells: list[tuple[int, int]] = field(default_factory=list)
    orientation: int | None = None

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
        if len(self._entries) >= MAX_COMPONENTS_PER_GAME:
            raise ResourceBudgetError(
                "components",
                len(self._entries),
                MAX_COMPONENTS_PER_GAME,
            )
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
    """Grid-based zone with width x height cells.

    Supports two storage modes:
    - **Dense** (default): flat ``list[ComponentId | None]`` indexed by
      ``row * width + col``.  Requires ``width > 0`` and ``height > 0``.
    - **Sparse**: ``dict[tuple[int, int], ComponentId]`` keyed by
      ``(col, row)``.  Supports arbitrarily large or unbounded coordinates
      (including negative values).  Activated when ``_sparse=True``.
    """

    width: int
    height: int
    cells: list[ComponentId | None]
    stacks: dict[int, list[ComponentId]] = field(default_factory=dict)
    stacking_limit: int = 1
    cell_properties: dict[int, dict[str, str | int | bool]] = field(
        default_factory=dict
    )
    valid_cells: set[int] | None = None
    _sparse: bool = False
    _sparse_cells: dict[tuple[int, int], ComponentId] = field(default_factory=dict)
    _sparse_stacks: dict[tuple[int, int], list[ComponentId]] = field(
        default_factory=dict
    )
    _sparse_cell_properties: dict[tuple[int, int], dict[str, str | int | bool]] = field(
        default_factory=dict
    )
    cell_fog: dict[tuple[int, int], dict[str, str]] | None = None
    fog_config: FogOfWarConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.width, int) or not isinstance(self.height, int):
            raise ValidationError(
                f"grid dimensions must be integers, got "
                f"({type(self.width).__name__}, {type(self.height).__name__})"
            )
        if self._sparse:
            if len(self._sparse_cells) > SPARSE_GRID_MAX_CELLS:
                raise ResourceBudgetError(
                    "sparse_grid_cells",
                    len(self._sparse_cells),
                    SPARSE_GRID_MAX_CELLS,
                )
        else:
            if self.width < 0 or self.height < 0:
                raise ValidationError(
                    f"grid dimensions must be non-negative, got ({self.width}, {self.height})"
                )
            expected_len = self.width * self.height
            if len(self.cells) != expected_len:
                raise ValidationError(
                    f"cells length {len(self.cells)} != width*height "
                    f"{self.width}x{self.height} = {expected_len}"
                )

    # -- Factory methods ----------------------------------------------------

    @classmethod
    def create_dense(
        cls, width: int, height: int, stacking_limit: int = 1
    ) -> "GridZone":
        """Create a dense grid. Validates dimensions."""
        if width <= 0 or height <= 0:
            raise ValueError(
                f"Dense grid dimensions must be positive: {width}x{height}"
            )
        if width > 10_000 or height > 10_000:
            raise ValueError(
                f"Dense grid dimensions too large: {width}x{height}"
            )
        cells: list[ComponentId | None] = [None] * (width * height)
        return cls(
            width=width, height=height, cells=cells, stacking_limit=stacking_limit
        )

    @classmethod
    def create_sparse(
        cls, width: int = 0, height: int = 0, stacking_limit: int = 1
    ) -> "GridZone":
        """Create a sparse grid with optional dimension hints."""
        return cls(
            width=width,
            height=height,
            cells=[],
            stacking_limit=stacking_limit,
            _sparse=True,
        )

    # -- Cell validity ------------------------------------------------------

    def _cell_valid(self, col: int, row: int) -> bool:
        if self._sparse:
            if self.width > 0 and self.height > 0:
                if col < 0 or row < 0 or col >= self.width or row >= self.height:
                    return False
            if self.valid_cells is not None:
                if self.width > 0:
                    return (row * self.width + col) in self.valid_cells
                return False
            return True
        if col < 0 or row < 0 or col >= self.width or row >= self.height:
            return False
        if self.valid_cells is not None:
            return (row * self.width + col) in self.valid_cells
        return True

    # -- Core accessors -----------------------------------------------------

    def grid_get(self, col: int, row: int) -> ComponentId | None:
        if not self._cell_valid(col, row):
            return None
        if self._sparse:
            return self._sparse_cells.get((col, row))
        return self.cells[row * self.width + col]

    def grid_set(
        self, col: int, row: int, component: ComponentId | None
    ) -> ComponentId | None:
        if not self._cell_valid(col, row):
            return None
        if self._sparse:
            prev = self._sparse_cells.pop((col, row), None)
            if component is not None:
                self._sparse_cells[(col, row)] = component
                if len(self._sparse_cells) > SPARSE_GRID_MAX_CELLS:
                    raise ResourceBudgetError(
                        "sparse_grid_cells",
                        len(self._sparse_cells),
                        SPARSE_GRID_MAX_CELLS,
                    )
            return prev
        idx = row * self.width + col
        prev = self.cells[idx]
        self.cells[idx] = component
        return prev

    def grid_push(self, col: int, row: int, component: ComponentId) -> None:
        """Push a component onto a cell (new component becomes top).

        Raises ``IllegalActionError`` if the stacking limit would be exceeded.
        """
        if not self._cell_valid(col, row):
            return
        # Enforce stacking limit before pushing
        if self.stacking_limit > 0:
            depth = len(self.grid_stack(col, row))
            if depth >= self.stacking_limit:
                raise IllegalActionError(
                    f"stacking limit ({self.stacking_limit}) reached at ({col},{row})"
                )
        if self._sparse:
            existing = self._sparse_cells.get((col, row))
            if existing is not None:
                self._sparse_stacks.setdefault((col, row), []).append(existing)
            self._sparse_cells[(col, row)] = component
            if len(self._sparse_cells) > SPARSE_GRID_MAX_CELLS:
                raise ResourceBudgetError(
                    "sparse_grid_cells",
                    len(self._sparse_cells),
                    SPARSE_GRID_MAX_CELLS,
                )
            return
        idx = row * self.width + col
        existing = self.cells[idx]
        if existing is not None:
            self.stacks.setdefault(idx, []).append(existing)
        self.cells[idx] = component

    def grid_pop(self, col: int, row: int) -> ComponentId | None:
        """Pop the top component from a cell. Promotes stack below."""
        if not self._cell_valid(col, row):
            return None
        if self._sparse:
            top = self._sparse_cells.get((col, row))
            if top is None:
                return None
            stack = self._sparse_stacks.get((col, row))
            if stack:
                self._sparse_cells[(col, row)] = stack.pop()
                if not stack:
                    del self._sparse_stacks[(col, row)]
            else:
                del self._sparse_cells[(col, row)]
            return top
        idx = row * self.width + col
        top = self.cells[idx]
        if top is None:
            return None
        stack = self.stacks.get(idx)
        if stack:
            self.cells[idx] = stack.pop()
            if not stack:
                del self.stacks[idx]
        else:
            self.cells[idx] = None
        return top

    def grid_stack(self, col: int, row: int) -> list[ComponentId]:
        """Get all components at a position (bottom to top)."""
        if not self._cell_valid(col, row):
            return []
        if self._sparse:
            result = list(self._sparse_stacks.get((col, row), []))
            top = self._sparse_cells.get((col, row))
            if top is not None:
                result.append(top)
            return result
        idx = row * self.width + col
        result = list(self.stacks.get(idx, []))
        top = self.cells[idx]
        if top is not None:
            result.append(top)
        return result

    def grid_place_span(
        self,
        origin_col: int,
        origin_row: int,
        horizontal: bool,
        span: int,
        component: ComponentId,
    ) -> list[tuple[int, int]]:
        """Place a spanning component on the grid. Returns list of occupied cells.

        Validates all cells are within bounds and currently empty.
        """
        cells_to_set: list[tuple[int, int]] = []
        for i in range(span):
            if horizontal:
                col, row = origin_col + i, origin_row
            else:
                col, row = origin_col, origin_row + i
            if not self._cell_valid(col, row):
                raise IllegalActionError(
                    f"span cell ({col},{row}) is out of bounds or masked"
                )
            cells_to_set.append((col, row))

        if self._sparse:
            new_cells = len(self._sparse_cells)
            for col, row in cells_to_set:
                if self.grid_get(col, row) is not None:
                    raise IllegalActionError(
                        f"span cell ({col},{row}) is already occupied"
                    )
                if (col, row) not in self._sparse_cells:
                    new_cells += 1
            if new_cells > SPARSE_GRID_MAX_CELLS:
                raise ResourceBudgetError(
                    "sparse_grid_cells", new_cells, SPARSE_GRID_MAX_CELLS
                )
        else:
            for col, row in cells_to_set:
                if self.grid_get(col, row) is not None:
                    raise IllegalActionError(
                        f"span cell ({col},{row}) is already occupied"
                    )

        for col, row in cells_to_set:
            self.grid_set(col, row, component)

        return cells_to_set

    def grid_remove_span(self, span_cells: list[tuple[int, int]]) -> None:
        """Remove a spanning component by clearing all its occupied cells."""
        for col, row in span_cells:
            self.grid_set(col, row, None)

    # -- Counting and capacity ----------------------------------------------

    def count(self) -> int:
        if self._sparse:
            return len(self._sparse_cells)
        return sum(1 for c in self.cells if c is not None)

    def get_cell_property(
        self, col: int, row: int, key: str
    ) -> str | int | bool | None:
        """Get a single cell property, or None if not set."""
        if not self._cell_valid(col, row):
            return None
        if self._sparse:
            props = self._sparse_cell_properties.get((col, row))
            if props is None:
                return None
            return props.get(key)
        idx = row * self.width + col
        props = self.cell_properties.get(idx)
        if props is None:
            return None
        return props.get(key)

    def set_cell_property(
        self, col: int, row: int, key: str, value: str | int | bool
    ) -> None:
        """Set a cell property."""
        if not self._cell_valid(col, row):
            return
        if self._sparse:
            if (col, row) not in self._sparse_cell_properties:
                self._sparse_cell_properties[(col, row)] = {}
            self._sparse_cell_properties[(col, row)][key] = value
            return
        idx = row * self.width + col
        if idx not in self.cell_properties:
            self.cell_properties[idx] = {}
        self.cell_properties[idx][key] = value

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        if not isinstance(capacity, int):
            raise ValidationError(
                f"capacity must be an int or 'unlimited', got {type(capacity).__name__}"
            )
        return self.count() >= capacity

    # -- Iteration helpers --------------------------------------------------

    def occupied_cells(self) -> Iterator[tuple[int, int, ComponentId]]:
        """Yield ``(col, row, component_id)`` for every occupied cell.

        Works for both dense and sparse grids.
        """
        if self._sparse:
            for (col, row), cid in self._sparse_cells.items():
                yield col, row, cid
        else:
            for idx, cid in enumerate(self.cells):
                if cid is not None:
                    col = idx % self.width
                    row = idx // self.width
                    yield col, row, cid

    # -- Fog of war methods -------------------------------------------------

    def cell_fog_state(self, col: int, row: int, player: str) -> str:
        """Get fog state for a cell and player.

        Returns the stored state, or the default_state from fog_config
        if not explicitly set. Returns "visible" if fog is not enabled.
        """
        if self.fog_config is None or self.cell_fog is None:
            return "visible"
        cell_data = self.cell_fog.get((col, row))
        if cell_data is None:
            return self.fog_config.default_state
        return cell_data.get(player, self.fog_config.default_state)

    def set_cell_fog(self, col: int, row: int, player: str, state: str) -> None:
        """Set fog state for a cell and player.

        Raises ValueError if state is not a valid fog state or if fog
        is not enabled on this zone.
        """
        if state not in _VALID_FOG_STATES:
            raise ValidationError(
                f"invalid fog state {state!r}, must be one of {_VALID_FOG_STATES}"
            )
        if self.fog_config is None or self.cell_fog is None:
            raise ValidationError("fog of war is not enabled on this zone")
        if (col, row) not in self.cell_fog:
            self.cell_fog[(col, row)] = {}
        self.cell_fog[(col, row)][player] = state

    def recompute_fog(
        self,
        player: str,
        unit_positions: list[tuple[int, int]],
        vision_range: int,
    ) -> None:
        """Recompute fog for a player based on unit positions and vision range.

        Cells within Manhattan distance of any unit position become "visible".
        Previously "visible" cells out of range become "fogged".
        "unexplored" cells out of range stay "unexplored".

        Args:
            player: The player whose fog to recompute.
            unit_positions: List of (col, row) positions of the player's units.
            vision_range: Manhattan distance for visibility.

        Raises:
            ValidationError: If fog is not enabled or vision_range < 0.
        """
        if self.fog_config is None or self.cell_fog is None:
            raise ValidationError("fog of war is not enabled on this zone")
        if vision_range < 0:
            raise ValidationError(
                f"vision_range must be >= 0, got {vision_range}"
            )

        # Collect all cells within Manhattan distance of any unit
        visible_cells: set[tuple[int, int]] = set()
        for ux, uy in unit_positions:
            for dx in range(-vision_range, vision_range + 1):
                remaining = vision_range - abs(dx)
                for dy in range(-remaining, remaining + 1):
                    cx, cy = ux + dx, uy + dy
                    if self._cell_valid(cx, cy):
                        visible_cells.add((cx, cy))

        # Transition previously visible cells to fogged,
        # then mark newly visible cells
        for (col, row), fog_data in self.cell_fog.items():
            if player in fog_data and fog_data[player] == "visible":
                if (col, row) not in visible_cells:
                    fog_data[player] = "fogged"

        for col, row in visible_cells:
            if (col, row) not in self.cell_fog:
                self.cell_fog[(col, row)] = {}
            self.cell_fog[(col, row)][player] = "visible"


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

    def __post_init__(self) -> None:
        if len(self.positions) == 0:
            raise ValidationError("track zone must have at least 1 position")

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


@dataclass
class GraphZone:
    """Graph-based zone with named nodes and explicit edges."""

    node_names: list[str]
    name_to_index: dict[str, int]
    adjacency: dict[int, list[int]]
    occupants: list[ComponentId | None]
    node_properties: dict[int, dict[str, str | int | bool]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.node_names) != len(self.occupants):
            raise ValidationError(
                f"graph occupants length {len(self.occupants)} != "
                f"node count {len(self.node_names)}"
            )

    def graph_get(self, node: str) -> ComponentId | None:
        idx = self.name_to_index.get(node)
        if idx is None:
            return None
        return self.occupants[idx]

    def graph_set(self, node: str, component: ComponentId | None) -> ComponentId | None:
        idx = self.name_to_index.get(node)
        if idx is None:
            return None
        prev = self.occupants[idx]
        self.occupants[idx] = component
        return prev

    def graph_neighbors(self, node: str) -> list[str]:
        idx = self.name_to_index.get(node)
        if idx is None:
            return []
        return [self.node_names[i] for i in self.adjacency.get(idx, [])]

    def count(self) -> int:
        return sum(1 for o in self.occupants if o is not None)

    def is_full(self, capacity: Capacity | None) -> bool:
        if capacity is None or capacity == "unlimited":
            return False
        return self.count() >= capacity


RuntimeZone = GridZone | StackZone | SetZone | SlotZone | CounterZone | TrackZone | GraphZone


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

        # Decide dense vs sparse storage.
        # Auto-select sparse when explicitly requested or dimensions are omitted
        # (dynamic grids).  Large dimensions auto-select sparse only when the
        # definition explicitly opts in via storage="sparse"; otherwise the
        # existing dimension cap (1000) is enforced to prevent accidental
        # dense-allocation of huge grids.
        use_sparse = (
            zone_def.storage == "sparse"
            or (zone_def.dimensions is None and zone_def.dynamic is True)
        )
        if zone_def.storage == "dense":
            use_sparse = False

        sl = zone_def.stacking_limit if zone_def.stacking_limit is not None else 1

        if use_sparse:
            vc: set[int] | None = None
            if zone_def.valid_cells is not None and w > 0:
                vc = set()
                for pair in zone_def.valid_cells:
                    c, r = pair[0], pair[1]
                    if 0 <= c < w and 0 <= r < h:
                        vc.add(r * w + c)
            fog_cfg = zone_def.fog_of_war
            grid = GridZone(
                width=w, height=h, cells=[], _sparse=True,
                stacking_limit=sl, valid_cells=vc,
                cell_fog={} if fog_cfg is not None else None,
                fog_config=fog_cfg,
            )
            if zone_def.cell_properties:
                for coord, props in zone_def.cell_properties.items():
                    parts = coord.split(",")
                    if len(parts) == 2:
                        c, r = int(parts[0].strip()), int(parts[1].strip())
                        grid._sparse_cell_properties[(c, r)] = dict(props)
            return grid

        # Dense path
        if w > 1000 or h > 1000:
            raise ValidationError(
                f"grid dimensions ({w}, {h}) exceed maximum (1000)"
            )
        vc_dense: set[int] | None = None
        if zone_def.valid_cells is not None:
            vc_dense = set()
            for pair in zone_def.valid_cells:
                c, r = pair[0], pair[1]
                if 0 <= c < w and 0 <= r < h:
                    vc_dense.add(r * w + c)
        fog_cfg_dense = zone_def.fog_of_war
        grid = GridZone(
            width=w, height=h, cells=[None] * (w * h),
            stacking_limit=sl, valid_cells=vc_dense,
            cell_fog={} if fog_cfg_dense is not None else None,
            fog_config=fog_cfg_dense,
        )
        if zone_def.cell_properties:
            for coord, props in zone_def.cell_properties.items():
                parts = coord.split(",")
                if len(parts) == 2:
                    c, r = int(parts[0].strip()), int(parts[1].strip())
                    if 0 <= c < w and 0 <= r < h:
                        idx = r * w + c
                        grid.cell_properties[idx] = dict(props)
        return grid
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
        nodes = zone_def.nodes
        if nodes is None:
            raise ValidationError("graph zone requires nodes")
        name_to_index = {name: i for i, name in enumerate(nodes)}
        adjacency: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
        if zone_def.edges is not None:
            for edge in zone_def.edges:
                a = name_to_index.get(edge[0])
                b = name_to_index.get(edge[1])
                if a is None:
                    raise ValidationError(f"unknown node in edge: {edge[0]}")
                if b is None:
                    raise ValidationError(f"unknown node in edge: {edge[1]}")
                adjacency[a].append(b)
                adjacency[b].append(a)
        node_props: dict[int, dict[str, str | int | bool]] = {}
        if zone_def.node_properties is not None:
            for name, props in zone_def.node_properties.items():
                idx = name_to_index.get(name)
                if idx is not None:
                    node_props[idx] = dict(props)
        return GraphZone(
            node_names=list(nodes),
            name_to_index=name_to_index,
            adjacency=adjacency,
            occupants=[None] * len(nodes),
            node_properties=node_props,
        )
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
    event_count: int = 0
    components: ComponentTable = field(default_factory=ComponentTable)
    zones: dict[str, RuntimeZone] = field(default_factory=dict)
    players: dict[str, RuntimePlayer] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    pending_commits: dict[str, str] = field(default_factory=dict)
    simultaneous_actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    history_hashes: list[str] = field(default_factory=list)
    result: GameResult | None = None
    betting_state: BettingRoundState | None = None
    visibility_overrides: dict[str, str] = field(default_factory=dict)
    partnerships: list[list[str]] = field(default_factory=list)


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
            partnerships=list(definition.partnerships),
        )

    def current_player(self) -> str | None:
        """The name of the player whose turn it is."""
        assert self.runtime.players or self.runtime.turn_index == 0, (
            f"turn_index {self.runtime.turn_index} out of range "
            f"for {len(self.runtime.players)} players"
        )
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

    def team_of(self, player: str) -> list[str] | None:
        """Find which team a player belongs to."""
        for team in self.runtime.partnerships:
            if player in team:
                return team
        return None

    def is_partner(self, player_a: str, player_b: str) -> bool:
        """Check if two players are on the same team."""
        if not self.runtime.partnerships:
            return False
        team = self.team_of(player_a)
        return team is not None and player_b in team

    def teammates(self, player: str) -> list[str]:
        """Get all players on the same team (including self)."""
        team = self.team_of(player)
        if team is None:
            return [player]
        return list(team)

    def is_perfect_information(self) -> bool:
        """Whether this is a perfect-information game."""
        return self.definition.game.information == "perfect"

    def advance_turn(self) -> None:
        """Advance the turn to the next player."""
        player_count = len(self.runtime.players)
        if player_count > 0:
            self.runtime.turn_index = (self.runtime.turn_index + 1) % player_count
            assert self.runtime.turn_index < player_count, (
                f"turn_index {self.runtime.turn_index} >= "
                f"player_count {player_count} after advance"
            )
        self.runtime.sequence += 1
        self.runtime.move_count += 1

    def change_visibility(self, zone_key: str, new_visibility: str) -> str | None:
        """Change a zone's runtime visibility. Returns previous override if any.

        Args:
            zone_key: Zone name, or "zone_name[player]" for per-player zones.
            new_visibility: "public" or "hidden".

        Raises:
            ValidationError: If new_visibility is not a valid value.
            UnknownZoneError: If the base zone name is not in the definition.
        """
        if new_visibility not in ("public", "hidden"):
            raise ValidationError(
                f"new_visibility must be 'public' or 'hidden', got {new_visibility!r}"
            )
        # Extract base zone name (strip [player] suffix if present)
        base_zone = zone_key.split("[")[0]
        if base_zone not in self.definition.zones:
            raise UnknownZoneError(base_zone)
        prev = self.runtime.visibility_overrides.get(zone_key)
        self.runtime.visibility_overrides[zone_key] = new_visibility
        return prev

    def get_zone_visibility(self, zone_name: str, player: str | None = None) -> str:
        """Get the effective visibility for a zone, checking overrides first.

        Args:
            zone_name: The zone name from the definition.
            player: Optional player name for per-player zone keys.

        Returns:
            The effective visibility: "public", "hidden", or the definition default.
        """
        # Check player-specific override first
        if player is not None:
            player_key = f"{zone_name}[{player}]"
            override = self.runtime.visibility_overrides.get(player_key)
            if override is not None:
                return override
        # Check zone-level override
        override = self.runtime.visibility_overrides.get(zone_name)
        if override is not None:
            return override
        # Fall back to definition
        zone_def = self.definition.zones.get(zone_name)
        if zone_def is None:
            raise UnknownZoneError(zone_name)
        vis = zone_def.visibility
        if isinstance(vis, str):
            return vis
        # PrivateVisibility maps to "hidden" for external callers
        return "hidden"

    def advance_phase(self) -> str | None:
        """Advance to the next phase and apply any visibility transitions.

        Returns the new phase name, or None if no phases are defined.
        """
        if not self.definition.phases:
            return None
        self.runtime.phase_index = (
            (self.runtime.phase_index + 1) % len(self.definition.phases)
        )
        new_phase = self.definition.phases[self.runtime.phase_index].name
        self._apply_visibility_transitions(new_phase)
        return new_phase

    def _apply_visibility_transitions(self, new_phase: str) -> None:
        """Apply visibility transitions that match the given phase."""
        for vt in self.definition.visibility_transitions:
            if vt.phase == new_phase:
                if vt.player is not None:
                    zone_key = f"{vt.zone}[{vt.player}]"
                else:
                    zone_key = vt.zone
                self.change_visibility(zone_key, vt.new_visibility)

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
            result=self.runtime.result,
            turn=turn,
            phase=phase,
            zones=wire_zones,
            players=wire_players,
            move_count=self.runtime.move_count,
            halfmove_clock=self.runtime.halfmove_clock,
            counters=counters,
            pending_commits=(
                dict(self.runtime.pending_commits)
                if self.runtime.pending_commits
                else None
            ),
            simultaneous_actions=(
                dict(self.runtime.simultaneous_actions)
                if self.runtime.simultaneous_actions
                else None
            ),
            history_hash=(
                self.runtime.history_hashes[-1]
                if self.runtime.history_hashes
                else None
            ),
            visibility_overrides=(
                dict(self.runtime.visibility_overrides)
                if self.runtime.visibility_overrides
                else None
            ),
        )

    def _zone_to_wire(self, zone: RuntimeZone) -> ZoneState:
        """Convert a runtime zone to wire-format ZoneState."""
        if isinstance(zone, GridZone):
            cells: dict[str, ComponentInstance | list[ComponentInstance] | None] = {}
            for col, row, cid in zone.occupied_cells():
                comp = self.runtime.components.get(cid)
                if comp is not None:
                    coord = f"{col},{row}"
                    cells[coord] = comp.to_wire_instance()
            wire_props: dict[str, dict[str, str | int | bool]] | None = None
            if zone._sparse:
                if zone._sparse_cell_properties:
                    wire_props = {}
                    for (col, row), props in zone._sparse_cell_properties.items():
                        wire_props[f"{col},{row}"] = dict(props)
            elif zone.cell_properties:
                wire_props = {}
                for idx, props in zone.cell_properties.items():
                    col = idx % zone.width
                    row = idx // zone.width
                    wire_props[f"{col},{row}"] = dict(props)
            return GridState(cells=cells, cell_properties=wire_props)

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

        if isinstance(zone, GraphZone):
            components = []
            for cid in zone.occupants:
                if cid is not None:
                    comp = self.runtime.components.get(cid)
                    if comp is not None:
                        components.append(comp.to_wire_instance())
            return SetState(components=components)

        raise ValidationError(f"unknown zone type: {type(zone)}")

    def to_player_wire_state(self, viewing_player: str) -> GameState:
        """Convert runtime state to wire-format GameState filtered for a specific player.

        For fog-enabled grid zones, cells are filtered based on the player's fog state:
        - "unexplored": component and cell_properties are hidden
        - "fogged": component is hidden; cell_properties shown if remember_terrain
        - "visible": everything shown

        The player's own fog map is included in the wire state.
        Other players' fog data is never exposed.
        """
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
            wire_zones[name] = self._zone_to_wire_for_player(zone, viewing_player)

        wire_players: dict[str, PlayerState] = {}
        for name, player in self.runtime.players.items():
            pzones: dict[str, ZoneState] = {}
            for zname, zone in player.zones.items():
                pzones[zname] = self._zone_to_wire_for_player(zone, viewing_player)
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
            result=self.runtime.result,
            turn=turn,
            phase=phase,
            zones=wire_zones,
            players=wire_players,
            move_count=self.runtime.move_count,
            halfmove_clock=self.runtime.halfmove_clock,
            counters=counters,
            pending_commits=(
                dict(self.runtime.pending_commits)
                if self.runtime.pending_commits
                else None
            ),
            simultaneous_actions=(
                dict(self.runtime.simultaneous_actions)
                if self.runtime.simultaneous_actions
                else None
            ),
            history_hash=(
                self.runtime.history_hashes[-1]
                if self.runtime.history_hashes
                else None
            ),
            visibility_overrides=(
                dict(self.runtime.visibility_overrides)
                if self.runtime.visibility_overrides
                else None
            ),
        )

    def _zone_to_wire_for_player(
        self, zone: RuntimeZone, viewing_player: str
    ) -> ZoneState:
        """Convert a runtime zone to wire-format, filtered for a specific player's fog."""
        if not isinstance(zone, GridZone) or zone.fog_config is None or zone.cell_fog is None:
            return self._zone_to_wire(zone)

        # Fog-enabled grid: filter cells based on player's fog state
        cells: dict[str, ComponentInstance | list[ComponentInstance] | None] = {}
        wire_props: dict[str, dict[str, str | int | bool]] | None = None
        wire_fog: dict[str, str] = {}
        remember_terrain = zone.fog_config.remember_terrain

        for col, row, cid in zone.occupied_cells():
            coord = f"{col},{row}"
            fog_st = zone.cell_fog_state(col, row, viewing_player)
            wire_fog[coord] = fog_st
            if fog_st == "visible":
                comp = self.runtime.components.get(cid)
                if comp is not None:
                    cells[coord] = comp.to_wire_instance()

        # Include fog states for cells without components too
        if zone._sparse:
            all_coords: set[tuple[int, int]] = set(zone._sparse_cells.keys())
            all_coords.update(zone._sparse_cell_properties.keys())
            all_coords.update(zone.cell_fog.keys())
        else:
            all_coords = set()
            for r in range(zone.height):
                for c in range(zone.width):
                    if not zone._cell_valid(c, r):
                        continue
                    all_coords.add((c, r))

        for col, row in all_coords:
            coord = f"{col},{row}"
            if coord in wire_fog:
                continue
            fog_st = zone.cell_fog_state(col, row, viewing_player)
            if fog_st != zone.fog_config.default_state:
                wire_fog[coord] = fog_st

        # Filter cell_properties based on fog
        if zone._sparse:
            if zone._sparse_cell_properties:
                for (col, row), props in zone._sparse_cell_properties.items():
                    coord = f"{col},{row}"
                    fog_st = zone.cell_fog_state(col, row, viewing_player)
                    if fog_st == "visible":
                        if wire_props is None:
                            wire_props = {}
                        wire_props[coord] = dict(props)
                    elif fog_st == "fogged" and remember_terrain:
                        if wire_props is None:
                            wire_props = {}
                        wire_props[coord] = dict(props)
        elif zone.cell_properties:
            for idx, props in zone.cell_properties.items():
                col = idx % zone.width
                row = idx // zone.width
                coord = f"{col},{row}"
                fog_st = zone.cell_fog_state(col, row, viewing_player)
                if fog_st == "visible":
                    if wire_props is None:
                        wire_props = {}
                    wire_props[coord] = dict(props)
                elif fog_st == "fogged" and remember_terrain:
                    if wire_props is None:
                        wire_props = {}
                    wire_props[coord] = dict(props)

        return GridState(
            cells=cells,
            cell_properties=wire_props,
            cell_fog=wire_fog if wire_fog else None,
        )
