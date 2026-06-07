use crate::action::Action;
use crate::state::GameState;

/// Trait for game-specific Tier 2 WASM extensions.
///
/// When a game's declarative schema isn't sufficient (complex scoring,
/// chain reactions, custom validation), a WASM module implements this
/// trait to provide the missing logic.
///
/// The engine calls these methods at the appropriate points:
/// - `is_legal` before accepting a move
/// - `legal_moves` when generating moves (supplements declarative moves)
/// - `apply_effect` after a move to handle chain reactions
/// - `score` when scoring is needed (end-of-turn or end-of-game)
/// - `check_end` after each move to test game-over conditions
pub trait GameExtension {
    /// Check whether a proposed move is legal in the given state.
    /// Called after the declarative rules have been checked.
    /// Return `None` to defer to the declarative engine's decision.
    fn is_legal(&self, state: &GameState, player: &str, action: &Action) -> Option<bool>;

    /// Return additional legal moves not expressible declaratively.
    /// These are appended to the declarative move list.
    fn legal_moves(&self, state: &GameState, player: &str) -> Vec<Action>;

    /// Apply a triggered effect after a move (chain reactions, cascades).
    /// Returns a modified state and any additional events.
    /// Called when the game definition declares `wasm_required` effects.
    fn apply_effect(
        &self,
        state: &GameState,
        trigger: &str,
    ) -> Result<GameState, ExtensionError>;

    /// Compute scores for all players.
    /// Used for scoring that's too complex for declarative predicates
    /// (e.g., Carcassonne field scoring, Go territory counting).
    fn score(&self, state: &GameState) -> Result<Vec<PlayerScore>, ExtensionError>;

    /// Check whether the game has ended.
    /// Returns the game result if the game is over, None otherwise.
    /// Used for end conditions that require complex computation
    /// (e.g., checkmate detection, Go life-and-death).
    fn check_end(&self, state: &GameState) -> Option<EndCheckResult>;
}

/// A player's score from the extension module.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PlayerScore {
    pub player: String,
    pub score: i64,
    pub breakdown: Vec<ScoreEntry>,
}

/// A single scoring entry (for detailed score breakdowns).
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ScoreEntry {
    pub category: String,
    pub points: i64,
    pub description: String,
}

/// Result of an end-condition check.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct EndCheckResult {
    pub game_over: bool,
    pub winner: Option<String>,
    pub condition: String,
}

/// Errors from extension modules.
#[derive(Debug, Clone, thiserror::Error)]
pub enum ExtensionError {
    #[error("extension computation failed: {0}")]
    ComputationFailed(String),

    #[error("invalid state for extension: {0}")]
    InvalidState(String),
}

/// A no-op extension that defers everything to the declarative engine.
/// Used when no WASM module is loaded.
pub struct NoExtension;

impl GameExtension for NoExtension {
    fn is_legal(&self, _state: &GameState, _player: &str, _action: &Action) -> Option<bool> {
        None
    }

    fn legal_moves(&self, _state: &GameState, _player: &str) -> Vec<Action> {
        Vec::new()
    }

    fn apply_effect(
        &self,
        state: &GameState,
        _trigger: &str,
    ) -> Result<GameState, ExtensionError> {
        Ok(state.clone())
    }

    fn score(&self, _state: &GameState) -> Result<Vec<PlayerScore>, ExtensionError> {
        Ok(Vec::new())
    }

    fn check_end(&self, _state: &GameState) -> Option<EndCheckResult> {
        None
    }
}
