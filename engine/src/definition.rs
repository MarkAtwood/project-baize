use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

/// Top-level game definition. This is the "document" a game designer authors.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameDefinition {
    pub game: GameMetadata,
    pub zones: IndexMap<String, Zone>,
    pub components: IndexMap<String, Component>,
    pub turn_order: TurnOrder,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub phases: Vec<Phase>,
    #[serde(default, skip_serializing_if = "IndexMap::is_empty")]
    pub rules: IndexMap<String, Rule>,
    pub end_conditions: Vec<EndCondition>,
    pub authority: Authority,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wasm_module: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub hand_rankings: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub betting_round: Option<BettingRound>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GameMetadata {
    pub name: String,
    pub players: Players,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub information: Option<InformationType>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Players {
    Named(Vec<String>),
    Range { min: u32, max: u32 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InformationType {
    Perfect,
    Imperfect,
}

// --- Visibility ---

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Visibility {
    Tier(VisibilityTier),
    Private { private: String },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VisibilityTier {
    Public,
    Hidden,
}

// --- Zones ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Zone {
    pub zone_type: ZoneType,
    pub visibility: Visibility,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub per_player: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capacity: Option<Capacity>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dimensions: Option<Dimensions>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub intersections: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub labels: Option<GridLabels>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coloring: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub adjacency: Option<Adjacency>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub star_points: Option<Vec<[u32; 2]>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub draw_visibility: Option<Visibility>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dynamic: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub length: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lanes: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub points: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub connectivity: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub edge_ownership: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cell_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub direction: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ZoneType {
    Grid,
    HexGrid,
    Graph,
    OrderedStack,
    Set,
    Queue,
    SingleSlot,
    Track,
    Counter,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Capacity {
    Limit(u32),
    Unlimited(UnlimitedTag),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UnlimitedTag;

impl Serialize for UnlimitedTag {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str("unlimited")
    }
}

impl<'de> Deserialize<'de> for UnlimitedTag {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        if s == "unlimited" {
            Ok(UnlimitedTag)
        } else {
            Err(serde::de::Error::custom(format!("expected \"unlimited\", got \"{s}\"")))
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Dimensions {
    Grid([u32; 2]),
    Single(u32),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GridLabels {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub files: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ranks: Option<Vec<serde_json::Value>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Adjacency {
    #[serde(rename = "orthogonal_4")]
    Orthogonal4,
    #[serde(rename = "orthogonal_8")]
    Orthogonal8,
    #[serde(rename = "hex_6")]
    Hex6,
}

// --- Components ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Component {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub registry: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extends: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner: Option<Owner>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub count: Option<ComponentCount>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub movement: Vec<MovementPrimitive>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub properties: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub facing: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub promotion: Option<Promotion>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub constraints: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub special: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub types: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub one_of_each: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub span: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supply: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub adds: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Owner {
    PerPlayer(PerPlayerTag),
    Named(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PerPlayerTag;

impl Serialize for PerPlayerTag {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str("per_player")
    }
}

impl<'de> Deserialize<'de> for PerPlayerTag {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        if s == "per_player" {
            Ok(PerPlayerTag)
        } else {
            Err(serde::de::Error::custom(format!("expected \"per_player\", got \"{s}\"")))
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ComponentCount {
    Finite(u32),
    Unlimited(UnlimitedTag),
}

// --- Movement ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MovementPrimitive {
    pub primitive: PrimitiveType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub direction: Option<Direction>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub distance: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dx: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dy: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_zone: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub condition: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repeat: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub after: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub side: Option<CastleSide>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub over: Option<u32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PrimitiveType {
    Step,
    Slide,
    Hop,
    Leap,
    Place,
    Draw,
    MoveTo,
    Swap,
    Remove,
    Promote,
    Flip,
    Castle,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Direction {
    Single(DirectionName),
    Multiple(Vec<DirectionName>),
    Custom(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DirectionName {
    Orthogonal,
    Diagonal,
    Adjacent,
    Forward,
    ForwardDiagonal,
    Backward,
    BackwardDiagonal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CastleSide {
    Kingside,
    Queenside,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Promotion {
    pub trigger: String,
    pub choices: Vec<String>,
}

// --- Turn structure ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnOrder {
    #[serde(rename = "type")]
    pub turn_type: TurnOrderType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub players: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub actions_per_turn: Option<ActionsPerTurn>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mandatory: Option<bool>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TurnOrderType {
    Alternating,
    RoundRobin,
    Simultaneous,
    Reactive,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ActionsPerTurn {
    Count(u32),
    Structured(Vec<IndexMap<String, serde_json::Value>>),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Phase {
    pub name: String,
    #[serde(default, rename = "type", skip_serializing_if = "Option::is_none")]
    pub phase_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub simultaneous: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_action: Option<ServerAction>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub action: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub actions_per_turn: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub starts_with: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trigger: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub choices: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ends_when: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub then: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resolve: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ServerAction {
    Single(String),
    Multiple(Vec<String>),
}

// --- Rules ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rule {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub definition: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub action: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub constraint: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub constraints: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trigger: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub effect: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub requires: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_resolves: Option<String>,
}

// --- End conditions ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EndCondition {
    pub result: EndResult,
    pub condition: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub player: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EndResult {
    Win,
    Loss,
    Draw,
}

// --- Authority ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Authority {
    pub server_only: Vec<String>,
    pub client_verifiable: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub wasm_required: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BettingRound {
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub actions: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ends_when: Option<String>,
}

// --- Parsing ---

impl GameDefinition {
    pub fn from_json(json: &str) -> crate::error::Result<Self> {
        let def: Self = serde_json::from_str(json)?;
        def.validate()?;
        Ok(def)
    }

    pub fn from_value(value: serde_json::Value) -> crate::error::Result<Self> {
        let def: Self = serde_json::from_value(value)?;
        def.validate()?;
        Ok(def)
    }

    /// Semantic validation beyond what serde can enforce.
    ///
    /// Checks:
    /// - Players list is non-empty
    /// - Game name is non-empty
    /// - At least one end condition exists
    /// - Grid zones have dimensions
    /// - Turn order player references match game.players
    /// - Movement target_zone references exist
    /// - No empty component names or zone names
    pub fn validate(&self) -> crate::error::Result<()> {
        use crate::error::BaizeError;

        // Game name must be non-empty
        if self.game.name.trim().is_empty() {
            return Err(BaizeError::Validation("game name must not be empty".into()));
        }

        // Players: at least one
        let player_names: Vec<&str> = match &self.game.players {
            Players::Named(names) => {
                if names.is_empty() {
                    return Err(BaizeError::Validation(
                        "game must have at least one player".into(),
                    ));
                }
                let mut seen = std::collections::HashSet::new();
                for name in names {
                    if name.trim().is_empty() {
                        return Err(BaizeError::Validation(
                            "player names must not be empty".into(),
                        ));
                    }
                    if !seen.insert(name.as_str()) {
                        return Err(BaizeError::Validation(format!(
                            "duplicate player name {name:?}"
                        )));
                    }
                }
                names.iter().map(|s| s.as_str()).collect()
            }
            Players::Range { min, max } => {
                if *min == 0 {
                    return Err(BaizeError::Validation(
                        "min players must be at least 1".into(),
                    ));
                }
                if *max < *min {
                    return Err(BaizeError::Validation(
                        "max players must be >= min players".into(),
                    ));
                }
                Vec::new() // can't enumerate at parse time
            }
        };

        // At least one end condition
        if self.end_conditions.is_empty() {
            return Err(BaizeError::Validation(
                "game must have at least one end condition".into(),
            ));
        }

        // Zone names must be non-empty
        for name in self.zones.keys() {
            if name.trim().is_empty() {
                return Err(BaizeError::Validation(
                    "zone names must not be empty".into(),
                ));
            }
        }

        // Grid zones must have dimensions (unless dynamic), and dimensions
        // must be positive and bounded to prevent memory exhaustion.
        const MAX_GRID_DIMENSION: u32 = 1000;
        for (name, zone) in &self.zones {
            if matches!(zone.zone_type, ZoneType::Grid | ZoneType::HexGrid)
                && zone.dimensions.is_none()
                && zone.dynamic != Some(true)
            {
                return Err(BaizeError::Validation(format!(
                    "grid zone {name:?} requires dimensions or dynamic: true"
                )));
            }
            if let Some(ref dims) = zone.dimensions {
                let values: &[u32] = match dims {
                    Dimensions::Grid(arr) => arr.as_slice(),
                    Dimensions::Single(v) => std::slice::from_ref(v),
                };
                for (i, &d) in values.iter().enumerate() {
                    if d == 0 {
                        return Err(BaizeError::Validation(format!(
                            "zone {name:?} dimension[{i}] must be > 0"
                        )));
                    }
                    if d > MAX_GRID_DIMENSION {
                        return Err(BaizeError::Validation(format!(
                            "zone {name:?} dimension[{i}] = {d} exceeds maximum ({MAX_GRID_DIMENSION})"
                        )));
                    }
                }
            }
        }

        // Component names must be non-empty
        for name in self.components.keys() {
            if name.trim().is_empty() {
                return Err(BaizeError::Validation(
                    "component names must not be empty".into(),
                ));
            }
        }

        // Movement target_zone references must exist in zones
        for (comp_name, comp) in &self.components {
            for prim in &comp.movement {
                if let Some(ref target) = prim.target_zone {
                    if !self.zones.contains_key(target) {
                        return Err(BaizeError::Validation(format!(
                            "component {comp_name:?} references unknown zone {target:?}"
                        )));
                    }
                }
            }
        }

        // Turn order player references (if named) must match game.players
        if let Some(ref turn_players) = self.turn_order.players {
            if !player_names.is_empty() {
                for tp in turn_players {
                    if !player_names.contains(&tp.as_str()) {
                        return Err(BaizeError::Validation(format!(
                            "turn_order references unknown player {tp:?}"
                        )));
                    }
                }
            }
        }

        Ok(())
    }
}
