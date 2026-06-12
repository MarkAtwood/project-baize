use indexmap::IndexMap;

use crate::definition::{
    Capacity, Dimensions, GameDefinition, InformationType, Players, Zone, ZoneType,
};
use crate::error::{BaizeError, Result};
use crate::state::{
    CellContents, ComponentInstance, Facing, GameResult, GameState, GameStatus, PlayerState,
    ZoneState,
};

/// Compact component identifier (index into ComponentTable).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ComponentId(pub u32);

/// A game session: static definition + mutable runtime state.
#[derive(Debug, Clone)]
pub struct GameSession {
    pub definition: GameDefinition,
    pub runtime: RuntimeState,
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
    pub components: ComponentTable,
    pub zones: IndexMap<String, RuntimeZone>,
    pub players: IndexMap<String, RuntimePlayer>,
    pub counters: IndexMap<String, i64>,
    pub pending_commits: IndexMap<String, String>,
    pub history_hashes: Vec<String>,
    pub result: Option<GameResult>,
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

/// Runtime zone — efficient storage for each zone type.
#[derive(Debug, Clone)]
pub enum RuntimeZone {
    Grid {
        width: u32,
        height: u32,
        cells: Vec<Option<ComponentId>>,
        /// Additional components below the top at each cell (sparse).
        /// Only populated when stacking_limit > 1.
        stacks: IndexMap<usize, Vec<ComponentId>>,
        /// Maximum components per cell: 1 = no stacking (default), 0 = unlimited.
        stacking_limit: u32,
        /// Arbitrary key-value properties per cell (sparse).
        cell_properties: IndexMap<usize, IndexMap<String, serde_json::Value>>,
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
                let cell_count = (w as usize).checked_mul(h as usize).ok_or_else(|| {
                    BaizeError::Overflow(format!(
                        "grid dimensions {w}x{h} overflow cell count"
                    ))
                })?;
                let mut cell_props = IndexMap::new();
                if let Some(ref cp) = zone_def.cell_properties {
                    for (coord, props) in cp {
                        let parts: Vec<&str> = coord.split(',').collect();
                        if parts.len() == 2 {
                            if let (Ok(c), Ok(r)) = (
                                parts[0].trim().parse::<u32>(),
                                parts[1].trim().parse::<u32>(),
                            ) {
                                if c < w && r < h {
                                    let idx = (r as usize) * (w as usize) + (c as usize);
                                    cell_props.insert(idx, props.clone());
                                }
                            }
                        }
                    }
                }
                Ok(RuntimeZone::Grid {
                    width: w,
                    height: h,
                    cells: vec![None; cell_count],
                    stacks: IndexMap::new(),
                    stacking_limit: 1,
                    cell_properties: cell_props,
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
                let len = zone_def.length.or(zone_def.points).unwrap_or(1) as usize;
                Ok(RuntimeZone::Track {
                    positions: vec![Vec::new(); len],
                })
            }
            ZoneType::Graph => Ok(RuntimeZone::Set {
                components: Vec::new(),
            }),
        }
    }

    /// Number of components currently in this zone.
    pub fn count(&self) -> usize {
        match self {
            RuntimeZone::Grid { cells, .. } => cells.iter().filter(|c| c.is_some()).count(),
            RuntimeZone::OrderedStack { components } | RuntimeZone::Set { components } => {
                components.len()
            }
            RuntimeZone::SingleSlot { component } => usize::from(component.is_some()),
            RuntimeZone::Counter { .. } => 0,
            RuntimeZone::Track { positions } => positions.iter().map(|p| p.len()).sum(),
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
    /// Get component at grid coordinate. Returns None if out of bounds or empty.
    pub fn grid_get(&self, col: u32, row: u32) -> Option<ComponentId> {
        match self {
            RuntimeZone::Grid { width, height, cells, .. } => {
                if col >= *width || row >= *height {
                    return None;
                }
                let idx = (row as usize)
                    .checked_mul(*width as usize)
                    .and_then(|v| v.checked_add(col as usize))?;
                cells.get(idx).copied().flatten()
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
            RuntimeZone::Grid { width, height, cells, .. } => {
                if col >= *width || row >= *height {
                    return None;
                }
                let idx = (row as usize)
                    .checked_mul(*width as usize)
                    .and_then(|v| v.checked_add(col as usize))?;
                let prev = cells.get(idx).copied().flatten();
                if let Some(cell) = cells.get_mut(idx) {
                    *cell = component;
                }
                prev
            }
            _ => None,
        }
    }

    /// Push a component onto a cell's stack (below existing top).
    pub fn grid_push(&mut self, col: u32, row: u32, component: ComponentId) {
        if let RuntimeZone::Grid { width, height, cells, stacks, .. } = self {
            if col >= *width || row >= *height {
                return;
            }
            let idx = (row as usize) * (*width as usize) + (col as usize);
            if let Some(existing) = cells.get(idx).copied().flatten() {
                // Move current top to stack, put new component on top
                stacks.entry(idx).or_default().push(existing);
                if let Some(cell) = cells.get_mut(idx) {
                    *cell = Some(component);
                }
            } else if let Some(cell) = cells.get_mut(idx) {
                *cell = Some(component);
            }
        }
    }

    /// Pop the top component from a cell's stack.
    pub fn grid_pop(&mut self, col: u32, row: u32) -> Option<ComponentId> {
        if let RuntimeZone::Grid { width, height, cells, stacks, .. } = self {
            if col >= *width || row >= *height {
                return None;
            }
            let idx = (row as usize) * (*width as usize) + (col as usize);
            let top = cells.get(idx).copied().flatten()?;
            // Promote next from stack, or clear cell
            if let Some(stack) = stacks.get_mut(&idx) {
                if let Some(next) = stack.pop() {
                    if let Some(cell) = cells.get_mut(idx) {
                        *cell = Some(next);
                    }
                } else {
                    stacks.swap_remove(&idx);
                    if let Some(cell) = cells.get_mut(idx) {
                        *cell = None;
                    }
                }
            } else if let Some(cell) = cells.get_mut(idx) {
                *cell = None;
            }
            Some(top)
        } else {
            None
        }
    }

    /// Get all components at a grid position (bottom to top).
    pub fn grid_stack(&self, col: u32, row: u32) -> Vec<ComponentId> {
        if let RuntimeZone::Grid { width, height, cells, stacks, .. } = self {
            if col >= *width || row >= *height {
                return Vec::new();
            }
            let idx = (row as usize) * (*width as usize) + (col as usize);
            let mut result = stacks.get(&idx).cloned().unwrap_or_default();
            if let Some(top) = cells.get(idx).copied().flatten() {
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
        let (width, height) = match self {
            RuntimeZone::Grid { width, height, .. } => (*width, *height),
            _ => {
                return Err(crate::error::BaizeError::IllegalAction(
                    "grid_place_span called on non-grid zone".into(),
                ))
            }
        };

        // Compute all cells
        let mut cells_to_set = Vec::with_capacity(span as usize);
        for i in 0..span {
            let (col, row) = if horizontal {
                (origin_col + i, origin_row)
            } else {
                (origin_col, origin_row + i)
            };
            if col >= width || row >= height {
                return Err(crate::error::BaizeError::IllegalAction(format!(
                    "span cell ({col},{row}) is out of bounds ({width}x{height})"
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

        Ok(GameSession {
            runtime: RuntimeState {
                status: GameStatus::Setup,
                turn_index: 0,
                phase_index: 0,
                sequence: 0,
                move_count: 0,
                halfmove_clock: 0,
                components: ComponentTable::new(),
                zones,
                players,
                counters: IndexMap::new(),
                pending_commits: IndexMap::new(),
                history_hashes: Vec::new(),
                result: None,
            },
            definition,
        })
    }

    /// The name of the player whose turn it is.
    pub fn current_player(&self) -> Option<&str> {
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

    /// Advance the turn to the next player.
    pub fn advance_turn(&mut self) {
        let player_count = self.runtime.players.len();
        if player_count > 0 {
            self.runtime.turn_index = (self.runtime.turn_index + 1) % player_count;
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
            history_hash: self.runtime.history_hashes.last().cloned(),
            timestamp: None,
        }
    }

    fn zone_to_wire(&self, zone: &RuntimeZone) -> ZoneState {
        match zone {
            RuntimeZone::Grid { width, height, cells, cell_properties, .. } => {
                let mut wire_cells = IndexMap::new();
                for row in 0..*height {
                    for col in 0..*width {
                        let idx = match (row as usize)
                            .checked_mul(*width as usize)
                            .and_then(|v| v.checked_add(col as usize))
                        {
                            Some(i) => i,
                            None => continue,
                        };
                        if let Some(Some(cid)) = cells.get(idx) {
                            let coord = format!("{},{}", col, row);
                            if let Some(data) = self.runtime.components.get(*cid) {
                                wire_cells
                                    .insert(coord, CellContents::Single(data.to_wire_instance()));
                            }
                        }
                    }
                }
                let wire_props = if cell_properties.is_empty() {
                    None
                } else {
                    let mut props_map = IndexMap::new();
                    for (idx, props) in cell_properties {
                        let col = idx % (*width as usize);
                        let row = idx / (*width as usize);
                        props_map.insert(format!("{},{}", col, row), props.clone());
                    }
                    Some(props_map)
                };
                ZoneState::Grid { cells: wire_cells, cell_properties: wire_props }
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
