use thiserror::Error;

#[derive(Debug, Error)]
pub enum BaizeError {
    #[error("failed to parse game definition: {0}")]
    Parse(#[from] serde_json::Error),

    #[error("invalid game definition: {0}")]
    Validation(String),

    #[error("unknown zone: {0}")]
    UnknownZone(String),

    #[error("unknown component type: {0}")]
    UnknownComponent(String),

    #[error("illegal action: {0}")]
    IllegalAction(String),

    #[error("out of bounds: {0}")]
    OutOfBounds(String),

    #[error("invalid component id: {0}")]
    InvalidComponentId(String),

    #[error("invalid player: {0}")]
    InvalidPlayer(String),

    #[error("integer overflow: {0}")]
    Overflow(String),

    #[error("resource budget exceeded: {0}")]
    ResourceBudget(String),
}

pub type Result<T> = std::result::Result<T, BaizeError>;
