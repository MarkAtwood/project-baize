#![allow(unused_imports)]

#[cfg(feature = "wasm")]
use wasm_bindgen::prelude::*;

#[cfg(feature = "wasm")]
use crate::action::Action;
#[cfg(feature = "wasm")]
use crate::definition::GameDefinition;
#[cfg(feature = "wasm")]
use crate::moves::legal_moves;
#[cfg(feature = "wasm")]
use crate::runtime::GameSession;
#[cfg(feature = "wasm")]
use crate::transition::apply_action;

/// WASM-exposed game engine. Thin FFI layer over the core Rust engine.
/// All data crosses the boundary as JSON strings.
#[cfg(feature = "wasm")]
#[wasm_bindgen]
pub struct BaizeEngine {
    session: Option<GameSession>,
}

#[cfg(feature = "wasm")]
#[wasm_bindgen]
impl BaizeEngine {
    /// Create a new engine instance.
    #[wasm_bindgen(constructor)]
    pub fn new() -> Self {
        Self { session: None }
    }

    /// Load a game definition from a JSON string.
    /// Returns an error string on failure, or null on success.
    #[wasm_bindgen(js_name = "loadDefinition")]
    pub fn load_definition(&mut self, json: &str) -> Result<(), JsError> {
        let def: GameDefinition =
            serde_json::from_str(json).map_err(|e| JsError::new(&e.to_string()))?;
        let session =
            GameSession::new(def).map_err(|e| JsError::new(&e.to_string()))?;
        self.session = Some(session);
        Ok(())
    }

    /// Get all legal moves for the current player as a JSON array.
    #[wasm_bindgen(js_name = "legalMoves")]
    pub fn legal_moves_json(&self) -> Result<String, JsError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| JsError::new("no game loaded"))?;
        let moves = legal_moves(session);
        let actions: Vec<&Action> = moves.iter().map(|m| &m.action).collect();
        serde_json::to_string(&actions).map_err(|e| JsError::new(&e.to_string()))
    }

    /// Apply a player action (JSON string). Returns JSONL events.
    #[wasm_bindgen(js_name = "applyAction")]
    pub fn apply_action_json(&mut self, action_json: &str) -> Result<String, JsError> {
        let session = self
            .session
            .as_mut()
            .ok_or_else(|| JsError::new("no game loaded"))?;
        let action: Action =
            serde_json::from_str(action_json).map_err(|e| JsError::new(&e.to_string()))?;
        let events =
            apply_action(session, &action).map_err(|e| JsError::new(&e.to_string()))?;
        // Return events as JSONL (one JSON object per line)
        let lines: Vec<String> = events
            .iter()
            .map(|e| {
                serde_json::to_string(e)
                    .map_err(|e| JsError::new(&e.to_string()))
            })
            .collect::<std::result::Result<Vec<_>, _>>()?;
        Ok(lines.join("\n"))
    }

    /// Get the current game state as JSON.
    #[wasm_bindgen(js_name = "getState")]
    pub fn get_state_json(&self) -> Result<String, JsError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| JsError::new("no game loaded"))?;
        let state = session.to_wire_state();
        serde_json::to_string(&state).map_err(|e| JsError::new(&e.to_string()))
    }

    /// Get the current player's name.
    #[wasm_bindgen(js_name = "currentPlayer")]
    pub fn current_player(&self) -> Result<String, JsError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| JsError::new("no game loaded"))?;
        Ok(session
            .current_player()
            .unwrap_or("")
            .to_string())
    }

    /// Compute a BLAKE3 hash of the current state.
    #[wasm_bindgen(js_name = "stateHash")]
    pub fn state_hash(&self) -> Result<String, JsError> {
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| JsError::new("no game loaded"))?;
        Ok(session.compute_state_hash())
    }
}
