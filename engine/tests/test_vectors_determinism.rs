//! Cross-engine determinism verification.
//!
//! Loads test vector JSON files from `tests/vectors/ttt-*.json` and replays
//! each game through the Rust engine, verifying that the final status, result,
//! board state, and move count match the expected values.
//!
//! The Python engine runs the same vectors independently
//! (`python/tests/test_cross_engine.py`), so agreement constitutes
//! cross-engine determinism verification.

use baize_engine::action::Action;
use baize_engine::runtime::GameSession;
use baize_engine::state::{GameOutcome, GameStatus};
use baize_engine::transition::apply_action;
use baize_engine::GameDefinition;
use serde_json::Value;
use std::path::PathBuf;

/// Project root: engine/ is CARGO_MANIFEST_DIR, go up one level.
fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

/// Discover all ttt-*.json vector files.
fn discover_vectors() -> Vec<PathBuf> {
    let vectors_dir = project_root().join("tests").join("vectors");
    let mut paths: Vec<PathBuf> = std::fs::read_dir(&vectors_dir)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", vectors_dir.display()))
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("ttt-") && name.ends_with(".json") {
                Some(entry.path())
            } else {
                None
            }
        })
        .collect();
    paths.sort();
    assert!(!paths.is_empty(), "no ttt-*.json vectors found");
    paths
}

/// Load a vector file and parse it as JSON.
fn load_vector(path: &std::path::Path) -> Value {
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("invalid JSON in {}: {e}", path.display()))
}

/// Load the game definition referenced by the vector.
fn load_definition(vector: &Value) -> GameDefinition {
    let def_file = vector["definition_file"]
        .as_str()
        .expect("vector missing definition_file");
    let def_path = project_root().join(def_file);
    let raw = std::fs::read_to_string(&def_path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", def_path.display()));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("invalid game definition in {}: {e}", def_path.display()))
}

/// Replay all actions from the vector onto a fresh session.
fn replay_game(definition: GameDefinition, actions: &[Value]) -> GameSession {
    let mut session = GameSession::new(definition).expect("failed to create session");
    for (i, act_val) in actions.iter().enumerate() {
        let action: Action = serde_json::from_value(act_val.clone())
            .unwrap_or_else(|e| panic!("failed to parse action {i}: {e}"));
        apply_action(&mut session, &action)
            .unwrap_or_else(|e| panic!("apply_action failed at step {i}: {e}"));
    }
    session
}

#[test]
fn determinism_final_status() {
    for path in discover_vectors() {
        let name = path.file_stem().unwrap().to_string_lossy();
        let vector = load_vector(&path);
        let definition = load_definition(&vector);
        let actions = vector["actions"].as_array().expect("actions is not an array");
        let session = replay_game(definition, actions);

        let expected_status = vector["expected_final_status"]
            .as_str()
            .expect("missing expected_final_status");
        let actual_status = match session.runtime.status {
            GameStatus::Setup => "setup",
            GameStatus::InProgress => "in_progress",
            GameStatus::Finished => "finished",
        };
        assert_eq!(
            actual_status, expected_status,
            "[{name}] status mismatch: got {actual_status}, expected {expected_status}"
        );
    }
}

#[test]
fn determinism_result() {
    for path in discover_vectors() {
        let name = path.file_stem().unwrap().to_string_lossy();
        let vector = load_vector(&path);
        let definition = load_definition(&vector);
        let actions = vector["actions"].as_array().expect("actions is not an array");
        let session = replay_game(definition, actions);

        let expected = &vector["expected_result"];
        let result = session
            .runtime
            .result
            .as_ref()
            .unwrap_or_else(|| panic!("[{name}] expected a game result, got None"));

        let expected_outcome = expected["outcome"].as_str().unwrap();
        let actual_outcome = match result.outcome {
            GameOutcome::Win => "win",
            GameOutcome::Draw => "draw",
            GameOutcome::Abandoned => "abandoned",
        };
        assert_eq!(
            actual_outcome, expected_outcome,
            "[{name}] outcome mismatch"
        );

        let expected_winner = expected.get("winner").and_then(|v| v.as_str());
        let actual_winner = result.winner.as_deref();
        assert_eq!(
            actual_winner, expected_winner,
            "[{name}] winner mismatch"
        );

        let expected_condition = expected.get("condition").and_then(|v| v.as_str());
        let actual_condition = result.condition.as_deref();
        assert_eq!(
            actual_condition, expected_condition,
            "[{name}] condition mismatch"
        );
    }
}

#[test]
fn determinism_board_state() {
    for path in discover_vectors() {
        let name = path.file_stem().unwrap().to_string_lossy();
        let vector = load_vector(&path);
        let definition = load_definition(&vector);
        let actions = vector["actions"].as_array().expect("actions is not an array");
        let session = replay_game(definition, actions);

        let expected_board = match vector.get("expected_board").and_then(|v| v.as_object()) {
            Some(b) => b,
            None => continue,
        };

        let board = session
            .runtime
            .zones
            .get("board")
            .expect("board zone missing");

        // Verify occupied cells match
        for (coord, expected_comp) in expected_board {
            let parts: Vec<&str> = coord.split(',').collect();
            let col = parts[0].parse::<u32>().unwrap();
            let row = parts[1].parse::<u32>().unwrap();
            let cid = board.grid_get(col, row);
            assert!(
                cid.is_some(),
                "[{name}] expected component at {coord}, found empty"
            );
            let comp = session.runtime.components.get(cid.unwrap()).unwrap();

            let exp_ctype = expected_comp["component_type"].as_str().unwrap();
            assert_eq!(
                comp.component_type, exp_ctype,
                "[{name}] component_type at {coord} mismatch"
            );

            let exp_owner = expected_comp["owner"].as_str().unwrap();
            assert_eq!(
                comp.owner.as_deref(),
                Some(exp_owner),
                "[{name}] owner at {coord} mismatch"
            );
        }

        // Verify empty cells are actually empty
        let (width, height) = match board {
            baize_engine::runtime::RuntimeZone::Grid { width, height, .. } => (*width, *height),
            _ => panic!("[{name}] board zone is not a grid"),
        };
        for row in 0..height {
            for col in 0..width {
                let coord = format!("{col},{row}");
                if !expected_board.contains_key(&coord) {
                    assert!(
                        board.grid_get(col, row).is_none(),
                        "[{name}] expected cell ({col},{row}) to be empty"
                    );
                }
            }
        }
    }
}

#[test]
fn determinism_move_count() {
    for path in discover_vectors() {
        let name = path.file_stem().unwrap().to_string_lossy();
        let vector = load_vector(&path);
        let definition = load_definition(&vector);
        let actions = vector["actions"].as_array().expect("actions is not an array");
        let session = replay_game(definition, actions);

        if let Some(expected_mc) = vector.get("expected_move_count").and_then(|v| v.as_u64()) {
            assert_eq!(
                session.runtime.move_count, expected_mc,
                "[{name}] move_count mismatch"
            );
        }
    }
}
