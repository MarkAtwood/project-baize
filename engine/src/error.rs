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
}

pub type Result<T> = std::result::Result<T, BaizeError>;
