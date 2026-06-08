use serde::{Deserialize, Serialize};

// --- Client messages ---

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "message_type", rename_all = "snake_case")]
#[allow(clippy::large_enum_variant)]
pub enum ClientMessage {
    SubmitMove {
        game_id: String,
        player: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        sequence: Option<u64>,
        action: Action,
    },
    RequestRandom {
        game_id: String,
        player: String,
        random_request: RandomRequest,
    },
    AcknowledgeState {
        game_id: String,
        player: String,
        state_hash: String,
    },
}

// --- Server messages ---

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "message_type", rename_all = "snake_case")]
pub enum ServerMessage {
    MoveConfirmed {
        game_id: String,
        sequence: u64,
        action: Action,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        result_state: Option<serde_json::Value>,
    },
    MoveRejected {
        game_id: String,
        action: Action,
        reason: String,
    },
    RandomResult {
        game_id: String,
        random_type: String,
        random_value: serde_json::Value,
    },
    Reveal {
        game_id: String,
        reveal_to: String,
        facts: Vec<Fact>,
    },
    StateSync {
        game_id: String,
        sequence: u64,
        full_state: serde_json::Value,
    },
}

// --- Actions ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Action {
    pub action_type: ActionType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub authority: Option<AuthorityTag>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub component_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub component_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub from: Option<Position>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to: Option<Position>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub zone: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub promote_to: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub orientation: Option<Orientation>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rotation: Option<u16>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub amount: Option<serde_json::Number>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub side: Option<crate::definition::CastleSide>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dice_count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dice_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub swap_with: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub declaration: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub custom_data: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionType {
    MovePiece,
    Place,
    Draw,
    PlayCard,
    Discard,
    RollDice,
    Flip,
    Promote,
    Swap,
    Remove,
    Pass,
    Resign,
    OfferDraw,
    AcceptDraw,
    DeclineDraw,
    Fold,
    Check,
    Call,
    Raise,
    AllIn,
    PlaceShip,
    Fire,
    Castle,
    EnPassant,
    DeclareAction,
    Custom,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthorityTag {
    ClientVerifiable,
    ServerOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Orientation {
    Horizontal,
    Vertical,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Position {
    Coordinate(String),
    Structured {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        zone: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        cell: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        index: Option<u32>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RandomRequest {
    pub random_type: RandomType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dice_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dice_count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub draw_from: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub draw_count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shuffle_zone: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RandomType {
    Roll,
    Draw,
    Shuffle,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fact {
    pub fact_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub component_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub zone: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub position: Option<Position>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub properties: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_visibility: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub new_visibility: Option<String>,
}
