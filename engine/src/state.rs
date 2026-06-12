use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

/// Runtime game state snapshot.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameState {
    pub game_id: String,
    pub schema_ref: String,
    pub sequence: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state_hash: Option<String>,
    pub status: GameStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<GameResult>,
    pub turn: String,
    pub phase: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub move_count: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub halfmove_clock: Option<u64>,
    pub zones: IndexMap<String, ZoneState>,
    pub players: IndexMap<String, PlayerState>,
    #[serde(default, skip_serializing_if = "IndexMap::is_empty")]
    pub counters: IndexMap<String, serde_json::Number>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub pending_actions: Vec<PendingAction>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pending_commits: Option<IndexMap<String, String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub simultaneous_actions: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub history_hash: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GameStatus {
    Setup,
    InProgress,
    Finished,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameResult {
    pub outcome: GameOutcome,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub winner: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub condition: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub final_scores: Option<IndexMap<String, serde_json::Number>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GameOutcome {
    Win,
    Draw,
    Abandoned,
}

// --- Zone states ---

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "zone_type", rename_all = "snake_case")]
pub enum ZoneState {
    Grid {
        cells: IndexMap<String, CellContents>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        cell_properties: Option<IndexMap<String, IndexMap<String, serde_json::Value>>>,
    },
    OrderedStack {
        components: Vec<ComponentInstance>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        count: Option<u32>,
    },
    Set {
        components: Vec<ComponentInstance>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        count: Option<u32>,
    },
    SingleSlot {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        component: Option<ComponentInstance>,
    },
    Counter {
        value: serde_json::Number,
    },
    Track {
        positions: IndexMap<String, Vec<ComponentInstance>>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum CellContents {
    Single(ComponentInstance),
    Multiple(Vec<ComponentInstance>),
    Empty,
}

/// A specific component instance in play.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentInstance {
    pub id: String,
    pub component_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub facing: Option<Facing>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub state: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub properties: Option<IndexMap<String, serde_json::Value>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Facing {
    FaceUp,
    FaceDown,
}

// --- Player state ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlayerState {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub seat: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub connected: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub score: Option<serde_json::Number>,
    #[serde(default, skip_serializing_if = "IndexMap::is_empty")]
    pub counters: IndexMap<String, serde_json::Number>,
    #[serde(default, skip_serializing_if = "IndexMap::is_empty")]
    pub zones: IndexMap<String, ZoneState>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub clock: Option<ClockState>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClockState {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub remaining_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub increment_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub running: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PendingAction {
    pub player: String,
    pub action_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub submitted: Option<bool>,
}

// --- Hashing ---

impl GameState {
    pub fn from_json(json: &str) -> crate::error::Result<Self> {
        serde_json::from_str(json).map_err(Into::into)
    }

    /// Compute a BLAKE3 hash of the canonical JSON serialization.
    ///
    /// Serialization of a well-formed `GameState` is infallible (all fields
    /// are plain data types), so this unwrap is safe in practice.  We keep
    /// `unwrap` rather than returning `Result` because every call-site needs
    /// a `String`, and a serialization failure here would indicate a bug in
    /// the struct definition, not user-supplied data.
    pub fn compute_hash(&self) -> String {
        // Safety rationale: GameState contains only String, u64, Option,
        // Vec, IndexMap<String, _>, and serde_json::Number — all of which
        // are infallibly serializable by serde_json.
        let canonical = serde_json::to_string(self)
            .expect("GameState serialization is infallible: all fields are plain data types");
        blake3::hash(canonical.as_bytes()).to_hex().to_string()
    }
}
