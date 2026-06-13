use std::collections::{HashMap, HashSet};

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

use crate::definition::{
    Capacity, Dimensions, FogOfWarConfig, GameDefinition, InformationType, Players, Visibility,
    Zone, ZoneType,
};
use crate::error::{BaizeError, Result};
use crate::state::{
    CellContents, ClaimWindowState, ComponentInstance, Facing, GameResult, GameState, GameStatus,
    PlayerState, ZoneState,
};

// ---------------------------------------------------------------------------
// Resource budget defaults
// ---------------------------------------------------------------------------

/// Maximum component instances per game session.
pub const MAX_COMPONENTS_PER_GAME: usize = 10_000;

/// Maximum event log entries per game session.
pub const MAX_EVENTS_PER_GAME: usize = 100_000;

/// Maximum serialized state size in bytes (checked periodically, not every move).
pub const MAX_STATE_SIZE_BYTES: usize = 10 * 1024 * 1024; // 10 MB

/// Check state size every N moves (amortized cost).
pub const STATE_SIZE_CHECK_INTERVAL: u64 = 100;

/// Compact component identifier (index into ComponentTable).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ComponentId(pub u32);

/// A game session: static definition + mutable runtime state.
#[derive(Debug, Clone)]
pub struct GameSession {
    pub definition: GameDefinition,
    pub runtime: RuntimeState,
}

/// Active claim window state during trigger resolution.
#[derive(Debug, Clone)]
pub struct ClaimWindow {
    /// Name of the trigger that opened this window.
    pub trigger_name: String,
    /// The action that fired the trigger.
    pub triggering_action: crate::action::Action,
    /// Player who took the triggering action.
    pub triggering_player: String,
    /// Players who may submit claims (computed from eligible rule).
    pub eligible_players: Vec<String>,
    /// Claims submitted so far: player -> claim action name.
    pub submitted_claims: IndexMap<String, String>,
    /// Priority order from the trigger definition.
    pub priority: Vec<String>,
    /// Default action for non-respondents.
    pub default_claim: String,
}

/// The mutable runtime state of a game in progress.
#[derive(Debug, Clone)]
pub struct RuntimeState {
    pub status: GameStatus,
    pub turn_index: usize,
    pub phase_index: usize,
    pub sequence: u64,
    pub move_count: u64,
    pub halfmove_clock: u64,
    pub event_count: u64,
    pub components: ComponentTable,
    pub zones: IndexMap<String, RuntimeZone>,
    pub players: IndexMap<String, RuntimePlayer>,
    pub counters: IndexMap<String, i64>,
    pub pending_commits: IndexMap<String, String>,
    pub simultaneous_actions: IndexMap<String, serde_json::Value>,
    pub history_hashes: Vec<String>,
    pub result: Option<GameResult>,
    pub partnerships: Vec<Vec<String>>,
    /// Per-zone visibility overrides. Key: zone_name or "zone_name[player]" for per-player zones.
    /// If a zone has an override, it takes precedence over the definition's visibility.
    pub visibility_overrides: IndexMap<String, Visibility>,
    /// Active claim window, if a trigger has fired and claims are being collected.
    pub claim_window: Option<ClaimWindow>,
}

impl RuntimeState {
    /// Change a zone's runtime visibility. Returns the previous visibility if it was overridden.
    pub fn change_visibility(
        &mut self,
        zone_key: &str,
        new_visibility: Visibility,
    ) -> Option<Visibility> {
        self.visibility_overrides
            .insert(zone_key.to_string(), new_visibility)
    }
}

/// Arena of all component instances in the game.
#[derive(Debug, Clone)]
pub struct ComponentTable {
    entries: Vec<ComponentData>,
}

/// Internal representation of a single component instance.
#[derive(Debug, Clone)]
pub struct ComponentData {
    pub id: ComponentId,
    pub string_id: String,
    pub component_type: String,
    pub owner: Option<String>,
    pub facing: Option<Facing>,
    pub state: Option<String>,
    pub properties: IndexMap<String, serde_json::Value>,
    /// Cells occupied by this component on a grid (col, row pairs).
    /// Empty for single-cell components.
    pub span_cells: Vec<(u32, u32)>,
    /// Facing direction: 0-5 for hex grids, 0-3 for square grids. None = no facing.
    pub orientation: Option<u32>,
}

/// Maximum number of cells in a sparse grid before we refuse to allocate more.
/// Prevents unbounded memory growth from malicious or buggy game definitions.
const SPARSE_GRID_MAX_CELLS: usize = 1_000_000;

/// Threshold per axis above which we auto-select sparse storage.
const SPARSE_AUTO_THRESHOLD: u32 = 1_000;

/// Grid storage backend — dense (flat Vec) or sparse (HashMap).
///
/// Dense is cache-friendly and fast for small fixed boards (chess, Go).
/// Sparse handles unbounded or very large grids with signed coordinates.
///
/// INVARIANT: Dense cells.len() == (width * height) always.
/// INVARIANT: Sparse never exceeds SPARSE_GRID_MAX_CELLS entries.
#[derive(Debug, Clone)]
pub enum GridStorage {
    Dense {
        width: u32,
        height: u32,
        cells: Vec<Option<ComponentId>>,
    },
    Sparse {
        cells: HashMap<(i32, i32), ComponentId>,
        /// Optional rendering hint — not a hard constraint for sparse grids.
        dimensions: Option<(u32, u32)>,
    },
}

#[allow(dead_code)]
impl GridStorage {
    /// Create a dense grid. Panics on overflow.
    pub fn new_dense(width: u32, height: u32) -> Self {
        assert!(width > 0 && height > 0, "dense grid dimensions must be > 0");
        let cell_count = (width as usize)
            .checked_mul(height as usize)
            .expect("grid dimensions overflow cell count");
        let cells = vec![None; cell_count];
        debug_assert_eq!(cells.len(), (width as usize) * (height as usize));
        GridStorage::Dense { width, height, cells }
    }

    /// Create a sparse grid with optional dimension hint.
    pub fn new_sparse(dimensions: Option<(u32, u32)>) -> Self {
        GridStorage::Sparse {
            cells: HashMap::new(),
            dimensions,
        }
    }

    /// Get the grid dimensions. Dense: exact. Sparse: hint or None.
    pub fn dimensions(&self) -> Option<(u32, u32)> {
        match self {
            GridStorage::Dense { width, height, .. } => Some((*width, *height)),
            GridStorage::Sparse { dimensions, .. } => *dimensions,
        }
    }

    /// Check if a coordinate is valid for this grid.
    pub fn cell_valid(&self, col: i32, row: i32) -> bool {
        match self {
            GridStorage::Dense { width, height, .. } => {
                col >= 0 && row >= 0 && (col as u32) < *width && (row as u32) < *height
            }
            GridStorage::Sparse { dimensions, .. } => {
                if let Some((w, h)) = dimensions {
                    col >= 0 && row >= 0 && (col as u32) < *w && (row as u32) < *h
                } else {
                    true // unbounded
                }
            }
        }
    }

    /// Get the component at a coordinate.
    pub fn get(&self, col: i32, row: i32) -> Option<ComponentId> {
        match self {
            GridStorage::Dense { width, height, cells } => {
                if col < 0 || row < 0 || (col as u32) >= *width || (row as u32) >= *height {
                    return None;
                }
                let idx = (row as usize)
                    .checked_mul(*width as usize)
                    .and_then(|v| v.checked_add(col as usize))?;
                debug_assert_eq!(cells.len(), (*width as usize) * (*height as usize));
                cells.get(idx).copied().flatten()
            }
            GridStorage::Sparse { cells, .. } => cells.get(&(col, row)).copied(),
        }
    }

    /// Set a component at a coordinate. Returns the previous occupant.
    pub fn set(&mut self, col: i32, row: i32, component: Option<ComponentId>) -> Option<ComponentId> {
        match self {
            GridStorage::Dense { width, height, cells } => {
                if col < 0 || row < 0 || (col as u32) >= *width || (row as u32) >= *height {
                    return None;
                }
                let idx = (row as usize)
                    .checked_mul(*width as usize)
                    .and_then(|v| v.checked_add(col as usize));
                let idx = match idx {
                    Some(i) => i,
                    None => return None,
                };
                debug_assert_eq!(cells.len(), (*width as usize) * (*height as usize));
                let prev = cells.get(idx).copied().flatten();
                if let Some(cell) = cells.get_mut(idx) {
                    *cell = component;
                }
                prev
            }
            GridStorage::Sparse { cells, .. } => {
                if let Some(cid) = component {
                    if !cells.contains_key(&(col, row)) && cells.len() >= SPARSE_GRID_MAX_CELLS {
                        return None; // refuse to grow beyond limit
                    }
                    cells.insert((col, row), cid)
                } else {
                    cells.remove(&(col, row))
                }
            }
        }
    }

    /// Number of occupied cells.
    pub fn occupied_count(&self) -> usize {
        match self {
            GridStorage::Dense { cells, .. } => cells.iter().filter(|c| c.is_some()).count(),
            GridStorage::Sparse { cells, .. } => cells.len(),
        }
    }

    /// Iterate over all occupied cells as (col, row, component_id).
    pub fn occupied_cells(&self) -> Vec<(i32, i32, ComponentId)> {
        match self {
            GridStorage::Dense { width, cells, .. } => {
                let w = *width as usize;
                cells
                    .iter()
                    .enumerate()
                    .filter_map(|(idx, cell)| {
                        cell.map(|cid| {
                            let col = (idx % w) as i32;
                            let row = (idx / w) as i32;
                            (col, row, cid)
                        })
                    })
                    .collect()
            }
            GridStorage::Sparse { cells, .. } => cells
                .iter()
                .map(|(&(col, row), &cid)| (col, row, cid))
                .collect(),
        }
    }

}

/// Per-cell per-player fog of war state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FogState {
    Unexplored,
    Visible,
    Fogged,
}

impl FogState {
    /// Parse a fog state from a string, defaulting to Unexplored.
    pub fn from_str_default(s: &str) -> Self {
        match s {
            "visible" => FogState::Visible,
            "fogged" => FogState::Fogged,
            _ => FogState::Unexplored,
        }
    }
}

/// Runtime zone — efficient storage for each zone type.
#[derive(Debug, Clone)]
pub enum RuntimeZone {
    Grid {
        storage: GridStorage,
        /// Additional components below the top at each cell (sparse).
        /// Only populated when stacking_limit > 1.
        stacks: IndexMap<(i32, i32), Vec<ComponentId>>,
        /// Maximum components per cell: 1 = no stacking (default), 0 = unlimited.
        stacking_limit: u32,
        /// Arbitrary key-value properties per cell (sparse).
        cell_properties: IndexMap<(i32, i32), IndexMap<String, serde_json::Value>>,
        /// If present, only these coordinates are valid board positions.
        /// Cells outside this set are treated as out-of-bounds.
        valid_cells: Option<HashSet<(i32, i32)>>,
        /// Per-cell per-player fog state. Only present when fog_of_war is configured.
        /// Key: (col, row), Value: player_name -> FogState.
        cell_fog: Option<IndexMap<(i32, i32), IndexMap<String, FogState>>>,
        /// Fog of war configuration from the zone definition.
        fog_config: Option<FogOfWarConfig>,
    },
    OrderedStack {
        components: Vec<ComponentId>,
    },
    Set {
        components: Vec<ComponentId>,
    },
    SingleSlot {
        component: Option<ComponentId>,
    },
    Counter {
        value: i64,
    },
    Track {
        positions: Vec<Vec<ComponentId>>,
    },
    Graph {
        /// Node names in order (index = node ID)
        node_names: Vec<String>,
        /// Map from node name to index
        name_to_index: IndexMap<String, usize>,
        /// Adjacency list: for each node index, the set of neighbor indices
        adjacency: Vec<Vec<usize>>,
        /// Per-node occupant (like grid cells)
        occupants: Vec<Option<ComponentId>>,
        /// Per-node properties (sparse)
        node_properties: IndexMap<usize, IndexMap<String, serde_json::Value>>,
    },
}

/// Per-player runtime state.
#[derive(Debug, Clone)]
pub struct RuntimePlayer {
    pub seat: String,
    pub active: bool,
    pub score: i64,
    pub counters: IndexMap<String, i64>,
    pub zones: IndexMap<String, RuntimeZone>,
}

// --- ComponentTable ---

impl Default for ComponentTable {
    fn default() -> Self {
        Self::new()
    }
}

impl ComponentTable {
    pub fn new() -> Self {
        Self { entries: Vec::new() }
    }

    pub fn insert(&mut self, data: ComponentData) -> Result<ComponentId> {
        if self.entries.len() >= MAX_COMPONENTS_PER_GAME {
            return Err(BaizeError::ResourceBudget(format!(
                "component count ({}) reached limit ({})",
                self.entries.len(),
                MAX_COMPONENTS_PER_GAME
            )));
        }
        let len: u32 = self.entries.len().try_into().map_err(|_| {
            BaizeError::Overflow("component table exceeds u32::MAX entries".into())
        })?;
        let id = ComponentId(len);
        self.entries.push(data);
        self.entries
            .last_mut()
            .expect("push guarantees entries is non-empty")
            .id = id;
        Ok(id)
    }

    pub fn get(&self, id: ComponentId) -> Option<&ComponentData> {
        self.entries.get(id.0 as usize)
    }

    pub fn get_mut(&mut self, id: ComponentId) -> Option<&mut ComponentData> {
        self.entries.get_mut(id.0 as usize)
    }

    /// Returns true if the given ComponentId is valid (in range).
    pub fn contains(&self, id: ComponentId) -> bool {
        (id.0 as usize) < self.entries.len()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = &ComponentData> {
        self.entries.iter()
    }
}

// --- RuntimeZone ---

impl RuntimeZone {
    /// Create an empty zone from a zone definition.
    pub fn from_definition(zone_def: &Zone) -> Result<Self> {
        match zone_def.zone_type {
            ZoneType::Grid | ZoneType::HexGrid => {
                let (w, h) = match zone_def.dimensions {
                    Some(Dimensions::Grid([w, h])) => (w, h),
                    Some(Dimensions::Single(s)) => (s, s),
                    None if zone_def.dynamic == Some(true) => (0, 0),
                    None => {
                        return Err(BaizeError::Validation(
                            "grid zone requires dimensions".into(),
                        ))
                    }
                };

                // Auto-select storage backend
                let use_sparse = zone_def.storage.as_deref() == Some("sparse")
                    || zone_def.dimensions.is_none()
                    || w > SPARSE_AUTO_THRESHOLD
                    || h > SPARSE_AUTO_THRESHOLD;

                let storage = if use_sparse {
                    let dims = if w > 0 && h > 0 {
                        Some((w, h))
                    } else {
                        None // unbounded sparse — dynamic grid with no initial dimensions
                    };
                    GridStorage::new_sparse(dims)
                } else {
                    // Validate cell count for dense allocation
                    let _cell_count =
                        (w as usize).checked_mul(h as usize).ok_or_else(|| {
                            BaizeError::Overflow(format!(
                                "grid dimensions {w}x{h} overflow cell count"
                            ))
                        })?;
                    GridStorage::new_dense(w, h)
                };

                let mut cell_props = IndexMap::new();
                if let Some(ref cp) = zone_def.cell_properties {
                    for (coord, props) in cp {
                        let parts: Vec<&str> = coord.split(',').collect();
                        if parts.len() == 2 {
                            if let (Ok(c), Ok(r)) = (
                                parts[0].trim().parse::<u32>(),
                                parts[1].trim().parse::<u32>(),
                            ) {
                                if w == 0 || (c < w && r < h) {
                                    cell_props
                                        .insert((c as i32, r as i32), props.clone());
                                }
                            }
                        }
                    }
                }
                let vc = zone_def.valid_cells.as_ref().map(|coords| {
                    coords
                        .iter()
                        .filter(|[c, r]| w == 0 || (*c < w && *r < h))
                        .map(|[c, r]| (*c as i32, *r as i32))
                        .collect::<HashSet<(i32, i32)>>()
                });
                // Initialize fog of war if configured
                let (cell_fog, fog_config) = if let Some(ref fow) = zone_def.fog_of_war {
                    // For dense grids, we defer population until players are known
                    // (fog is per-player). Start with an empty map; cells will be
                    // initialized to default_state lazily via cell_fog_state().
                    (Some(IndexMap::new()), Some(fow.clone()))
                } else {
                    (None, None)
                };

                Ok(RuntimeZone::Grid {
                    storage,
                    stacks: IndexMap::new(),
                    stacking_limit: zone_def.stacking_limit.unwrap_or(1),
                    cell_properties: cell_props,
                    valid_cells: vc,
                    cell_fog,
                    fog_config,
                })
            }
            ZoneType::OrderedStack => Ok(RuntimeZone::OrderedStack {
                components: Vec::new(),
            }),
            ZoneType::Set => Ok(RuntimeZone::Set {
                components: Vec::new(),
            }),
            ZoneType::Queue => Ok(RuntimeZone::OrderedStack {
                components: Vec::new(),
            }),
            ZoneType::SingleSlot => Ok(RuntimeZone::SingleSlot { component: None }),
            ZoneType::Counter => Ok(RuntimeZone::Counter { value: 0 }),
            ZoneType::Track => {
                let raw_len = zone_def.length.or(zone_def.points).unwrap_or(1);
                if raw_len == 0 {
                    return Err(BaizeError::Validation(
                        "track zone length must be at least 1".into(),
                    ));
                }
                let len = raw_len as usize;
                Ok(RuntimeZone::Track {
                    positions: vec![Vec::new(); len],
                })
            }
            ZoneType::Graph => {
                let nodes = zone_def.nodes.as_ref().ok_or_else(|| {
                    BaizeError::Validation("graph zone requires nodes".into())
                })?;
                let mut name_to_index = IndexMap::new();
                for (i, name) in nodes.iter().enumerate() {
                    name_to_index.insert(name.clone(), i);
                }
                let mut adjacency = vec![Vec::new(); nodes.len()];
                if let Some(ref edges) = zone_def.edges {
                    for edge in edges {
                        let a = *name_to_index.get(&edge[0]).ok_or_else(|| {
                            BaizeError::Validation(format!("unknown node in edge: {}", edge[0]))
                        })?;
                        let b = *name_to_index.get(&edge[1]).ok_or_else(|| {
                            BaizeError::Validation(format!("unknown node in edge: {}", edge[1]))
                        })?;
                        adjacency[a].push(b);
                        adjacency[b].push(a); // undirected
                    }
                }
                let mut node_props = IndexMap::new();
                if let Some(ref np) = zone_def.node_properties {
                    for (name, props) in np {
                        if let Some(&idx) = name_to_index.get(name) {
                            node_props.insert(idx, props.clone());
                        }
                    }
                }
                Ok(RuntimeZone::Graph {
                    node_names: nodes.clone(),
                    name_to_index,
                    adjacency,
                    occupants: vec![None; nodes.len()],
                    node_properties: node_props,
                })
            }
        }
    }

    /// Number of components currently in this zone.
    pub fn count(&self) -> usize {
        match self {
            RuntimeZone::Grid { storage, .. } => storage.occupied_count(),
            RuntimeZone::OrderedStack { components } | RuntimeZone::Set { components } => {
                components.len()
            }
            RuntimeZone::SingleSlot { component } => usize::from(component.is_some()),
            RuntimeZone::Counter { .. } => 0,
            RuntimeZone::Track { positions } => positions.iter().map(|p| p.len()).sum(),
            RuntimeZone::Graph { occupants, .. } => occupants.iter().filter(|o| o.is_some()).count(),
        }
    }

    /// Check if a zone is at capacity.
    pub fn is_full(&self, capacity: Option<&Capacity>) -> bool {
        match capacity {
            None | Some(Capacity::Unlimited(_)) => false,
            Some(Capacity::Limit(max)) => self.count() >= *max as usize,
        }
    }
}

// --- Grid helpers ---

impl RuntimeZone {
    /// Returns the stacking limit for a grid zone. 1 = no stacking, 0 = unlimited.
    /// Non-grid zones return 1.
    pub fn grid_stacking_limit(&self) -> u32 {
        match self {
            RuntimeZone::Grid { stacking_limit, .. } => *stacking_limit,
            _ => 1,
        }
    }

    /// Check if a grid cell is valid (in bounds and in the valid_cells mask if present).
    pub fn grid_cell_valid(&self, col: u32, row: u32) -> bool {
        match self {
            RuntimeZone::Grid { storage, valid_cells, .. } => {
                let c = col as i32;
                let r = row as i32;
                if !storage.cell_valid(c, r) {
                    return false;
                }
                if let Some(vc) = valid_cells {
                    vc.contains(&(c, r))
                } else {
                    true
                }
            }
            _ => false,
        }
    }

    /// Get component at grid coordinate. Returns None if out of bounds, masked out, or empty.
    pub fn grid_get(&self, col: u32, row: u32) -> Option<ComponentId> {
        match self {
            RuntimeZone::Grid { storage, valid_cells, .. } => {
                let c = col as i32;
                let r = row as i32;
                if let Some(vc) = valid_cells {
                    if !vc.contains(&(c, r)) {
                        return None;
                    }
                }
                storage.get(c, r)
            }
            _ => None,
        }
    }

    /// Place a component at a grid coordinate. Returns the displaced component if any.
    pub fn grid_set(
        &mut self,
        col: u32,
        row: u32,
        component: Option<ComponentId>,
    ) -> Option<ComponentId> {
        match self {
            RuntimeZone::Grid { storage, valid_cells, .. } => {
                let c = col as i32;
                let r = row as i32;
                if let Some(vc) = valid_cells {
                    if !vc.contains(&(c, r)) {
                        return None;
                    }
                }
                storage.set(c, r, component)
            }
            _ => None,
        }
    }

    /// Push a component onto a cell's stack (new component becomes top).
    ///
    /// Returns `Err` if the push would exceed the zone's `stacking_limit`.
    /// A `stacking_limit` of 0 means unlimited stacking.
    pub fn grid_push(&mut self, col: u32, row: u32, component: ComponentId) -> Result<()> {
        if let RuntimeZone::Grid { storage, stacks, stacking_limit, valid_cells, .. } = self {
            let c = col as i32;
            let r = row as i32;
            if !storage.cell_valid(c, r) {
                return Err(BaizeError::IllegalAction(format!(
                    "cell ({col},{row}) is out of bounds"
                )));
            }
            if let Some(vc) = valid_cells {
                if !vc.contains(&(c, r)) {
                    return Err(BaizeError::IllegalAction(format!(
                        "cell ({col},{row}) is not a valid cell"
                    )));
                }
            }
            // Compute current stack depth (stack below + top occupant)
            let current_depth = stacks
                .get(&(c, r))
                .map(|s| s.len())
                .unwrap_or(0)
                + if storage.get(c, r).is_some() { 1 } else { 0 };
            // Enforce stacking limit (0 = unlimited)
            if *stacking_limit > 0 && current_depth + 1 > *stacking_limit as usize {
                return Err(BaizeError::IllegalAction(format!(
                    "stacking limit ({}) exceeded at ({col},{row})",
                    stacking_limit
                )));
            }
            if let Some(existing) = storage.get(c, r) {
                // Move current top to stack, put new component on top
                stacks.entry((c, r)).or_default().push(existing);
                storage.set(c, r, Some(component));
            } else {
                storage.set(c, r, Some(component));
            }
            Ok(())
        } else {
            Err(BaizeError::IllegalAction(
                "grid_push called on non-grid zone".into(),
            ))
        }
    }

    /// Pop the top component from a cell's stack.
    pub fn grid_pop(&mut self, col: u32, row: u32) -> Option<ComponentId> {
        if let RuntimeZone::Grid { storage, stacks, valid_cells, .. } = self {
            let c = col as i32;
            let r = row as i32;
            if !storage.cell_valid(c, r) {
                return None;
            }
            if let Some(vc) = valid_cells {
                if !vc.contains(&(c, r)) {
                    return None;
                }
            }
            let top = storage.get(c, r)?;
            // Promote next from stack, or clear cell
            let key = (c, r);
            if let Some(stack) = stacks.get_mut(&key) {
                if let Some(next) = stack.pop() {
                    storage.set(c, r, Some(next));
                } else {
                    stacks.swap_remove(&key);
                    storage.set(c, r, None);
                }
            } else {
                storage.set(c, r, None);
            }
            Some(top)
        } else {
            None
        }
    }

    /// Get all components at a grid position (bottom to top).
    pub fn grid_stack(&self, col: u32, row: u32) -> Vec<ComponentId> {
        if let RuntimeZone::Grid { storage, stacks, valid_cells, .. } = self {
            let c = col as i32;
            let r = row as i32;
            if !storage.cell_valid(c, r) {
                return Vec::new();
            }
            if let Some(vc) = valid_cells {
                if !vc.contains(&(c, r)) {
                    return Vec::new();
                }
            }
            let key = (c, r);
            let mut result = stacks.get(&key).cloned().unwrap_or_default();
            if let Some(top) = storage.get(c, r) {
                result.push(top);
            }
            result
        } else {
            Vec::new()
        }
    }

    /// Place a spanning component on a grid. Returns the list of occupied cells.
    ///
    /// Validates that all cells are within bounds and currently empty.
    /// `orientation`: 0 = horizontal (span along columns), 1 = vertical (span along rows).
    pub fn grid_place_span(
        &mut self,
        origin_col: u32,
        origin_row: u32,
        horizontal: bool,
        span: u32,
        component: ComponentId,
    ) -> crate::error::Result<Vec<(u32, u32)>> {
        if !matches!(self, RuntimeZone::Grid { .. }) {
            return Err(crate::error::BaizeError::IllegalAction(
                "grid_place_span called on non-grid zone".into(),
            ));
        }

        // Compute all cells
        let mut cells_to_set = Vec::with_capacity(span as usize);
        for i in 0..span {
            let (col, row) = if horizontal {
                (origin_col + i, origin_row)
            } else {
                (origin_col, origin_row + i)
            };
            if !self.grid_cell_valid(col, row) {
                return Err(crate::error::BaizeError::IllegalAction(format!(
                    "span cell ({col},{row}) is out of bounds or masked"
                )));
            }
            cells_to_set.push((col, row));
        }

        // Check all cells are empty
        for &(col, row) in &cells_to_set {
            if self.grid_get(col, row).is_some() {
                return Err(crate::error::BaizeError::IllegalAction(format!(
                    "span cell ({col},{row}) is already occupied"
                )));
            }
        }

        // Place component in all cells
        for &(col, row) in &cells_to_set {
            self.grid_set(col, row, Some(component));
        }

        Ok(cells_to_set)
    }

    /// Remove a spanning component from a grid by clearing all its occupied cells.
    pub fn grid_remove_span(&mut self, span_cells: &[(u32, u32)]) {
        for &(col, row) in span_cells {
            self.grid_set(col, row, None);
        }
    }

    /// Push a component onto a stack (top = end).
    pub fn stack_push(&mut self, component: ComponentId) {
        if let RuntimeZone::OrderedStack { components } = self {
            components.push(component);
        }
    }

    /// Pop the top component from a stack.
    pub fn stack_pop(&mut self) -> Option<ComponentId> {
        if let RuntimeZone::OrderedStack { components } = self {
            components.pop()
        } else {
            None
        }
    }

    /// Add a component to a set.
    pub fn set_add(&mut self, component: ComponentId) {
        if let RuntimeZone::Set { components } = self {
            components.push(component);
        }
    }

    /// Remove a component from a set by ID. Returns true if found.
    pub fn set_remove(&mut self, component: ComponentId) -> bool {
        if let RuntimeZone::Set { components } = self {
            if let Some(pos) = components.iter().position(|c| *c == component) {
                components.swap_remove(pos);
                return true;
            }
        }
        false
    }

    // --- Graph helpers ---

    /// Get occupant at a named graph node.
    pub fn graph_get(&self, node: &str) -> Option<ComponentId> {
        match self {
            RuntimeZone::Graph { name_to_index, occupants, .. } => {
                let idx = *name_to_index.get(node)?;
                occupants.get(idx).copied().flatten()
            }
            _ => None,
        }
    }

    /// Set occupant at a named graph node. Returns previous occupant.
    pub fn graph_set(
        &mut self,
        node: &str,
        component: Option<ComponentId>,
    ) -> Option<ComponentId> {
        match self {
            RuntimeZone::Graph { name_to_index, occupants, .. } => {
                let idx = *name_to_index.get(node)?;
                let prev = occupants.get(idx).copied().flatten();
                if let Some(slot) = occupants.get_mut(idx) {
                    *slot = component;
                }
                prev
            }
            _ => None,
        }
    }

    /// Get neighbor node names for a graph node.
    pub fn graph_neighbors(&self, node: &str) -> Vec<&str> {
        match self {
            RuntimeZone::Graph { name_to_index, adjacency, node_names, .. } => {
                if let Some(&idx) = name_to_index.get(node) {
                    adjacency[idx].iter().map(|&i| node_names[i].as_str()).collect()
                } else {
                    Vec::new()
                }
            }
            _ => Vec::new(),
        }
    }

    // --- Fog of war helpers ---

    /// Get the fog state for a specific cell and player.
    ///
    /// Returns the stored state, or the configured default_state if no entry
    /// exists. For non-fog zones, returns `FogState::Visible`.
    pub fn cell_fog_state(&self, col: i32, row: i32, player: &str) -> FogState {
        match self {
            RuntimeZone::Grid { cell_fog: Some(fog), fog_config, .. } => {
                let default = fog_config
                    .as_ref()
                    .map(|c| FogState::from_str_default(&c.default_state))
                    .unwrap_or(FogState::Unexplored);
                fog.get(&(col, row))
                    .and_then(|players| players.get(player))
                    .copied()
                    .unwrap_or(default)
            }
            _ => FogState::Visible,
        }
    }

    /// Set the fog state for a specific cell and player.
    ///
    /// No-op for non-fog zones.
    pub fn set_cell_fog(&mut self, col: i32, row: i32, player: &str, state: FogState) {
        if let RuntimeZone::Grid { cell_fog: Some(fog), .. } = self {
            fog.entry((col, row))
                .or_default()
                .insert(player.to_string(), state);
        }
    }

    /// Recompute fog for a player based on their unit positions.
    ///
    /// Cells within Manhattan distance `vision_range` of any unit become Visible.
    /// Previously Visible cells now out of range become Fogged.
    /// Unexplored cells not in range stay Unexplored.
    ///
    /// No-op if vision_range is 0 (manual fog control) or zone has no fog.
    pub fn recompute_fog(
        &mut self,
        player: &str,
        unit_positions: &[(i32, i32)],
        vision_range: u32,
    ) {
        if vision_range == 0 {
            return;
        }

        let RuntimeZone::Grid {
            cell_fog: Some(fog),
            fog_config: Some(config),
            storage,
            ..
        } = self
        else {
            return;
        };

        let default_state = FogState::from_str_default(&config.default_state);
        let range = vision_range as i32;

        // Collect all cells that are now visible (within range of any unit)
        let mut newly_visible: HashSet<(i32, i32)> = HashSet::new();
        for &(ux, uy) in unit_positions {
            for dx in -range..=range {
                let remaining = range - dx.abs();
                for dy in -remaining..=remaining {
                    let cx = ux + dx;
                    let cy = uy + dy;
                    if storage.cell_valid(cx, cy) {
                        newly_visible.insert((cx, cy));
                    }
                }
            }
        }

        // Update fog state for all cells that have player entries
        // 1. Previously visible cells not in newly_visible -> Fogged
        // 2. Newly visible cells -> Visible
        // First pass: scan existing fog entries for this player
        let existing_cells: Vec<(i32, i32)> = fog
            .iter()
            .filter_map(|(&coord, players)| {
                if players.contains_key(player) {
                    Some(coord)
                } else {
                    None
                }
            })
            .collect();

        for coord in existing_cells {
            let current = fog
                .get(&coord)
                .and_then(|p| p.get(player))
                .copied()
                .unwrap_or(default_state);

            if !newly_visible.contains(&coord) && current == FogState::Visible {
                // Was visible, now out of range -> Fogged
                fog.entry(coord)
                    .or_default()
                    .insert(player.to_string(), FogState::Fogged);
            }
        }

        // Second pass: mark all newly visible cells
        for coord in newly_visible {
            fog.entry(coord)
                .or_default()
                .insert(player.to_string(), FogState::Visible);
        }
    }

    /// Get the fog of war configuration for this zone, if any.
    pub fn fog_config(&self) -> Option<&FogOfWarConfig> {
        match self {
            RuntimeZone::Grid { fog_config, .. } => fog_config.as_ref(),
            _ => None,
        }
    }

    /// Get the cell_fog map reference for this zone, if any.
    pub fn cell_fog(&self) -> Option<&IndexMap<(i32, i32), IndexMap<String, FogState>>> {
        match self {
            RuntimeZone::Grid { cell_fog, .. } => cell_fog.as_ref(),
            _ => None,
        }
    }
}

// --- GameSession ---

impl GameSession {
    /// Initialize a new game session from a definition.
    /// Creates empty zones and players; does not deal cards or place pieces.
    pub fn new(definition: GameDefinition) -> Result<Self> {
        let mut zones = IndexMap::new();
        let mut player_zones = IndexMap::new();

        for (name, zone_def) in &definition.zones {
            if zone_def.per_player == Some(true) {
                player_zones.insert(name.clone(), zone_def);
            } else {
                zones.insert(name.clone(), RuntimeZone::from_definition(zone_def)?);
            }
        }

        let player_names = match &definition.game.players {
            Players::Named(names) => names.clone(),
            Players::Range { min, .. } => (0..*min).map(|i| format!("player_{i}")).collect(),
        };

        let mut players = IndexMap::new();
        for name in &player_names {
            let mut pzones = IndexMap::new();
            for (zname, zdef) in &player_zones {
                pzones.insert(zname.clone(), RuntimeZone::from_definition(zdef)?);
            }
            players.insert(
                name.clone(),
                RuntimePlayer {
                    seat: name.clone(),
                    active: true,
                    score: 0,
                    counters: IndexMap::new(),
                    zones: pzones,
                },
            );
        }

        let partnerships = definition.partnerships.clone();

        Ok(GameSession {
            runtime: RuntimeState {
                status: GameStatus::Setup,
                turn_index: 0,
                phase_index: 0,
                sequence: 0,
                move_count: 0,
                halfmove_clock: 0,
                event_count: 0,
                components: ComponentTable::new(),
                zones,
                players,
                counters: IndexMap::new(),
                pending_commits: IndexMap::new(),
                simultaneous_actions: IndexMap::new(),
                history_hashes: Vec::new(),
                result: None,
                partnerships,
                visibility_overrides: IndexMap::new(),
                claim_window: None,
            },
            definition,
        })
    }

    /// The name of the player whose turn it is.
    pub fn current_player(&self) -> Option<&str> {
        debug_assert!(
            self.runtime.players.is_empty()
                || self.runtime.turn_index < self.runtime.players.len(),
            "turn_index {} out of range for {} players",
            self.runtime.turn_index,
            self.runtime.players.len()
        );
        match &self.definition.game.players {
            Players::Named(names) => names.get(self.runtime.turn_index).map(|s| s.as_str()),
            Players::Range { .. } => self
                .runtime
                .players
                .get_index(self.runtime.turn_index)
                .map(|(name, _)| name.as_str()),
        }
    }

    /// Whether this is a perfect-information game.
    pub fn is_perfect_information(&self) -> bool {
        self.definition.game.information == Some(InformationType::Perfect)
    }

    /// Find which team a player belongs to. Returns None if player has no team.
    pub fn team_of(&self, player: &str) -> Option<&[String]> {
        self.runtime
            .partnerships
            .iter()
            .find(|team| team.iter().any(|p| p == player))
            .map(|v| v.as_slice())
    }

    /// Check if two players are on the same team.
    pub fn is_partner(&self, player_a: &str, player_b: &str) -> bool {
        self.runtime
            .partnerships
            .iter()
            .any(|team| {
                team.iter().any(|p| p == player_a) && team.iter().any(|p| p == player_b)
            })
    }

    /// Get all players on the same team as the given player (including self).
    pub fn teammates<'a>(&'a self, player: &'a str) -> Vec<&'a str> {
        match self.team_of(player) {
            Some(team) => team.iter().map(|s| s.as_str()).collect(),
            None => vec![player],
        }
    }

    /// Get the team name for a player: "A/B" if partnered, or the player name if solo.
    pub fn team_name(&self, player: &str) -> String {
        match self.team_of(player) {
            Some(team) => team.join("/"),
            None => player.to_string(),
        }
    }

    /// Sum the scores of all teammates of a given player.
    pub fn team_score(&self, player: &str) -> i64 {
        let members = self.teammates(player);
        members
            .iter()
            .filter_map(|p| self.runtime.players.get(*p))
            .map(|rp| rp.score)
            .sum()
    }

    /// Advance the turn to the next player.
    pub fn advance_turn(&mut self) {
        let player_count = self.runtime.players.len();
        if player_count > 0 {
            self.runtime.turn_index = (self.runtime.turn_index + 1) % player_count;
            debug_assert!(
                self.runtime.turn_index < player_count,
                "turn_index {} >= player_count {} after advance",
                self.runtime.turn_index,
                player_count
            );
        }
        self.runtime.sequence = self.runtime.sequence.saturating_add(1);
        self.runtime.move_count = self.runtime.move_count.saturating_add(1);
    }

    /// Compute a BLAKE3 hash of the current state for repetition detection.
    pub fn compute_state_hash(&self) -> String {
        let state = self.to_wire_state();
        state.compute_hash()
    }

    /// Convert runtime state to wire-format GameState for serialization.
    pub fn to_wire_state(&self) -> GameState {
        let turn = self.current_player().unwrap_or("").to_string();
        let phase = self
            .definition
            .phases
            .get(self.runtime.phase_index)
            .map(|p| p.name.clone())
            .unwrap_or_else(|| "main".to_string());

        let mut wire_zones = IndexMap::new();
        for (name, zone) in &self.runtime.zones {
            wire_zones.insert(name.clone(), self.zone_to_wire(zone));
        }

        let mut wire_players = IndexMap::new();
        for (name, player) in &self.runtime.players {
            let mut pzones = IndexMap::new();
            for (zname, zone) in &player.zones {
                pzones.insert(zname.clone(), self.zone_to_wire(zone));
            }
            wire_players.insert(
                name.clone(),
                PlayerState {
                    user_id: None,
                    seat: Some(player.seat.clone()),
                    active: Some(player.active),
                    connected: None,
                    score: Some(serde_json::Number::from(player.score)),
                    counters: player
                        .counters
                        .iter()
                        .map(|(k, v)| (k.clone(), serde_json::Number::from(*v)))
                        .collect(),
                    zones: pzones,
                    clock: None,
                },
            );
        }

        GameState {
            game_id: String::new(),
            schema_ref: String::new(),
            sequence: self.runtime.sequence,
            state_hash: None,
            status: self.runtime.status,
            result: self.runtime.result.clone(),
            turn,
            phase,
            move_count: Some(self.runtime.move_count),
            halfmove_clock: Some(self.runtime.halfmove_clock),
            zones: wire_zones,
            players: wire_players,
            counters: self
                .runtime
                .counters
                .iter()
                .map(|(k, v)| (k.clone(), serde_json::Number::from(*v)))
                .collect(),
            pending_actions: Vec::new(),
            pending_commits: if self.runtime.pending_commits.is_empty() {
                None
            } else {
                Some(self.runtime.pending_commits.clone())
            },
            simultaneous_actions: if self.runtime.simultaneous_actions.is_empty() {
                None
            } else {
                Some(self.runtime.simultaneous_actions.clone())
            },
            history_hash: self.runtime.history_hashes.last().cloned(),
            timestamp: None,
            partnerships: self.runtime.partnerships.clone(),
            visibility_overrides: self.runtime.visibility_overrides.clone(),
            claim_window: self.runtime.claim_window.as_ref().map(|cw| {
                let submitted: Vec<String> = cw.submitted_claims.keys().cloned().collect();
                let awaiting: Vec<String> = cw
                    .eligible_players
                    .iter()
                    .filter(|p| !cw.submitted_claims.contains_key(*p))
                    .cloned()
                    .collect();
                ClaimWindowState {
                    trigger_name: cw.trigger_name.clone(),
                    triggering_player: cw.triggering_player.clone(),
                    eligible_players: cw.eligible_players.clone(),
                    submitted,
                    awaiting,
                }
            }),
        }
    }

    fn zone_to_wire(&self, zone: &RuntimeZone) -> ZoneState {
        match zone {
            RuntimeZone::Grid { storage, cell_properties, .. } => {
                let mut wire_cells = IndexMap::new();
                for (col, row, cid) in storage.occupied_cells() {
                    let coord = format!("{},{}", col, row);
                    if let Some(data) = self.runtime.components.get(cid) {
                        wire_cells
                            .insert(coord, CellContents::Single(data.to_wire_instance()));
                    }
                }
                let wire_props = if cell_properties.is_empty() {
                    None
                } else {
                    let mut props_map = IndexMap::new();
                    for (&(col, row), props) in cell_properties {
                        props_map.insert(format!("{},{}", col, row), props.clone());
                    }
                    Some(props_map)
                };
                ZoneState::Grid { cells: wire_cells, cell_properties: wire_props, cell_fog: None }
            }
            RuntimeZone::OrderedStack { components } => ZoneState::OrderedStack {
                components: components
                    .iter()
                    .filter_map(|cid| self.runtime.components.get(*cid))
                    .map(|d| d.to_wire_instance())
                    .collect(),
                count: None,
            },
            RuntimeZone::Set { components } => ZoneState::Set {
                components: components
                    .iter()
                    .filter_map(|cid| self.runtime.components.get(*cid))
                    .map(|d| d.to_wire_instance())
                    .collect(),
                count: None,
            },
            RuntimeZone::SingleSlot { component } => ZoneState::SingleSlot {
                component: component
                    .and_then(|cid| self.runtime.components.get(cid))
                    .map(|d| d.to_wire_instance()),
            },
            RuntimeZone::Counter { value } => ZoneState::Counter {
                value: serde_json::Number::from(*value),
            },
            RuntimeZone::Track { positions } => {
                let mut wire_positions = IndexMap::new();
                for (i, pos) in positions.iter().enumerate() {
                    if !pos.is_empty() {
                        wire_positions.insert(
                            i.to_string(),
                            pos.iter()
                                .filter_map(|cid| self.runtime.components.get(*cid))
                                .map(|d| d.to_wire_instance())
                                .collect(),
                        );
                    }
                }
                ZoneState::Track {
                    positions: wire_positions,
                }
            }
            RuntimeZone::Graph { node_names, occupants, .. } => {
                let mut wire_cells = IndexMap::new();
                for (i, name) in node_names.iter().enumerate() {
                    if let Some(Some(cid)) = occupants.get(i) {
                        if let Some(data) = self.runtime.components.get(*cid) {
                            wire_cells
                                .insert(name.clone(), CellContents::Single(data.to_wire_instance()));
                        }
                    }
                }
                ZoneState::Grid { cells: wire_cells, cell_properties: None, cell_fog: None }
            }
        }
    }
}

impl ComponentData {
    fn to_wire_instance(&self) -> ComponentInstance {
        ComponentInstance {
            id: self.string_id.clone(),
            component_type: self.component_type.clone(),
            owner: self.owner.clone(),
            facing: self.facing,
            state: self.state.clone(),
            properties: if self.properties.is_empty() {
                None
            } else {
                Some(self.properties.clone())
            },
        }
    }
}
