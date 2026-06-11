//! Cross-implementation state transition test vectors.
//!
//! Reads `tests/vectors/state-transitions.json` and replays each test case
//! against the Rust transition engine, verifying that observable outcomes match
//! the expected values in the vector file.
//!
//! Both this runner and the Python counterpart must produce identical results
//! for every vector.

use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::*;
use baize_engine::state::{Facing, GameStatus};
use baize_engine::transition::{apply_action, EventType};
use baize_engine::GameDefinition;
use indexmap::IndexMap;
use serde_json::Value;

/// Path to the shared test vector file.
/// CARGO_MANIFEST_DIR is `engine/`, vectors live at `../tests/vectors/`.
const VECTORS_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../tests/vectors/state-transitions.json"
);

// ---------------------------------------------------------------------------
// Helpers: build engine objects from JSON vector data
// ---------------------------------------------------------------------------

fn load_vectors() -> Value {
    let raw = std::fs::read_to_string(VECTORS_PATH)
        .unwrap_or_else(|e| panic!("failed to read {VECTORS_PATH}: {e}"));
    serde_json::from_str(&raw).expect("invalid JSON in test vectors")
}

fn parse_game_definition(v: &Value) -> GameDefinition {
    serde_json::from_value(v.clone()).expect("failed to parse game_definition from vector")
}

fn setup_session(def: GameDefinition, setup: &[Value]) -> GameSession {
    let mut session = GameSession::new(def).unwrap();
    for item in setup {
        let string_id = item["string_id"].as_str().unwrap().to_string();
        let component_type = item["component_type"].as_str().unwrap().to_string();
        let owner = item.get("owner").and_then(|v| v.as_str()).map(String::from);
        let facing = item.get("facing").and_then(|v| v.as_str()).map(|f| match f {
            "face_up" => Facing::FaceUp,
            "face_down" => Facing::FaceDown,
            other => panic!("unknown facing: {other}"),
        });

        let cid = session.runtime.components.insert(ComponentData {
            id: ComponentId(0),
            string_id,
            component_type,
            owner,
            facing,
            state: None,
            properties: IndexMap::new(),
            span_cells: Vec::new(),
        }).unwrap();

        if let Some(zone_name) = item.get("zone").and_then(|v| v.as_str()) {
            let col = item["col"].as_u64().unwrap() as u32;
            let row = item["row"].as_u64().unwrap() as u32;
            let zone = session
                .runtime
                .zones
                .get_mut(zone_name)
                .unwrap_or_else(|| panic!("zone {zone_name} not found in definition"));
            zone.grid_set(col, row, Some(cid));
        }
    }
    session
}

fn build_action(v: &Value) -> Action {
    let action_type = match v["action_type"].as_str().unwrap() {
        "place" => ActionType::Place,
        "move_piece" => ActionType::MovePiece,
        "pass" => ActionType::Pass,
        "resign" => ActionType::Resign,
        "flip" => ActionType::Flip,
        other => panic!("unsupported action_type in vector: {other}"),
    };

    let from = v.get("from").map(|p| parse_position(p));
    let to = v.get("to").map(|p| parse_position(p));
    let component_type = v.get("component_type").and_then(|v| v.as_str()).map(String::from);
    let component_id = v.get("component_id").and_then(|v| v.as_str()).map(String::from);

    Action {
        action_type,
        authority: None,
        component_id,
        component_type,
        from,
        to,
        zone: None,
        count: None,
        promote_to: None,
        orientation: None,
        rotation: None,
        amount: None,
        side: None,
        dice_count: None,
        dice_type: None,
        swap_with: None,
        declaration: None,
        custom_data: None,
    }
}

fn parse_position(v: &Value) -> Position {
    if v.is_string() {
        return Position::Coordinate(v.as_str().unwrap().to_string());
    }
    Position::Structured {
        zone: v.get("zone").and_then(|z| z.as_str()).map(String::from),
        cell: v.get("cell").and_then(|c| c.as_str()).map(String::from),
        index: v.get("index").and_then(|i| i.as_u64()).map(|i| i as u32),
    }
}

fn str_to_event_type(s: &str) -> EventType {
    match s {
        "move_piece" => EventType::MovePiece,
        "place" => EventType::Place,
        "capture" => EventType::Capture,
        "draw" => EventType::Draw,
        "play_card" => EventType::PlayCard,
        "discard" => EventType::Discard,
        "flip" => EventType::Flip,
        "promote" => EventType::Promote,
        "swap" => EventType::Swap,
        "remove" => EventType::Remove,
        "pass" => EventType::Pass,
        "resign" => EventType::Resign,
        "turn_advance" => EventType::TurnAdvance,
        "game_end" => EventType::GameEnd,
        other => panic!("unknown event type: {other}"),
    }
}

fn str_to_status(s: &str) -> GameStatus {
    match s {
        "setup" => GameStatus::Setup,
        "in_progress" => GameStatus::InProgress,
        "finished" => GameStatus::Finished,
        other => panic!("unknown status: {other}"),
    }
}

// ---------------------------------------------------------------------------
// Assertion helpers
// ---------------------------------------------------------------------------

fn assert_events(
    events: &[baize_engine::transition::GameEvent],
    expected: &[Value],
    test_name: &str,
    step: usize,
) {
    assert_eq!(
        events.len(),
        expected.len(),
        "[{test_name}] step {step}: expected {} events, got {}",
        expected.len(),
        events.len()
    );

    for (i, exp) in expected.iter().enumerate() {
        let actual = &events[i];
        let exp_type = exp["event_type"].as_str().unwrap();
        assert_eq!(
            actual.event_type,
            str_to_event_type(exp_type),
            "[{test_name}] step {step}, event {i}: event_type mismatch"
        );

        let exp_player = exp["player"].as_str().unwrap();
        assert_eq!(
            actual.player, exp_player,
            "[{test_name}] step {step}, event {i}: player mismatch"
        );

        if let Some(exp_cid) = exp.get("component_id").and_then(|v| v.as_str()) {
            assert_eq!(
                actual.component_id.as_deref(),
                Some(exp_cid),
                "[{test_name}] step {step}, event {i}: component_id mismatch"
            );
        }

        if let Some(exp_from) = exp.get("from").and_then(|v| v.as_str()) {
            assert_eq!(
                actual.from.as_deref(),
                Some(exp_from),
                "[{test_name}] step {step}, event {i}: from mismatch"
            );
        }

        if let Some(exp_to) = exp.get("to").and_then(|v| v.as_str()) {
            assert_eq!(
                actual.to.as_deref(),
                Some(exp_to),
                "[{test_name}] step {step}, event {i}: to mismatch"
            );
        }
    }
}

fn assert_board_cells(session: &GameSession, expected: &Value, test_name: &str, step: usize) {
    let board = session
        .runtime
        .zones
        .get("board")
        .expect("board zone missing");

    if let Some(cells) = expected.as_object() {
        for (coord, exp_comp) in cells {
            let parts: Vec<&str> = coord.split(',').collect();
            let col = parts[0].parse::<u32>().unwrap();
            let row = parts[1].parse::<u32>().unwrap();
            let cid = board.grid_get(col, row);
            assert!(
                cid.is_some(),
                "[{test_name}] step {step}: expected component at {coord}, found empty"
            );
            let comp = session.runtime.components.get(cid.unwrap()).unwrap();

            let exp_id = exp_comp["id"].as_str().unwrap();
            assert_eq!(
                comp.string_id, exp_id,
                "[{test_name}] step {step}: component id at {coord} mismatch"
            );

            let exp_ctype = exp_comp["component_type"].as_str().unwrap();
            assert_eq!(
                comp.component_type, exp_ctype,
                "[{test_name}] step {step}: component_type at {coord} mismatch"
            );

            if let Some(exp_owner) = exp_comp.get("owner").and_then(|v| v.as_str()) {
                assert_eq!(
                    comp.owner.as_deref(),
                    Some(exp_owner),
                    "[{test_name}] step {step}: owner at {coord} mismatch"
                );
            }
        }
    }
}

fn assert_empty_cells(session: &GameSession, cells: &[Value], test_name: &str, step: usize) {
    let board = session.runtime.zones.get("board").expect("board zone missing");
    for cell_val in cells {
        let coord = cell_val.as_str().unwrap();
        let parts: Vec<&str> = coord.split(',').collect();
        let col = parts[0].parse::<u32>().unwrap();
        let row = parts[1].parse::<u32>().unwrap();
        assert!(
            board.grid_get(col, row).is_none(),
            "[{test_name}] step {step}: expected cell {coord} to be empty"
        );
    }
}

fn assert_hash_chain(
    session: &GameSession,
    events: &[baize_engine::transition::GameEvent],
    hash_chain: &Value,
    test_name: &str,
    step: usize,
) {
    if let Some(len) = hash_chain.get("history_length").and_then(|v| v.as_u64()) {
        assert_eq!(
            session.runtime.history_hashes.len(),
            len as usize,
            "[{test_name}] step {step}: history_hashes length mismatch"
        );
    }

    // All events should have a non-empty state_hash
    for event in events {
        assert!(
            !event.state_hash.is_empty(),
            "[{test_name}] step {step}: event has empty state_hash"
        );
    }

    if let Some(prev_null) = hash_chain.get("prev_hash_is_null").and_then(|v| v.as_bool()) {
        // Check the first event's prev_hash
        if let Some(first_event) = events.first() {
            if prev_null {
                assert!(
                    first_event.prev_hash.is_none(),
                    "[{test_name}] step {step}: expected prev_hash to be null"
                );
            } else {
                assert!(
                    first_event.prev_hash.is_some(),
                    "[{test_name}] step {step}: expected prev_hash to be non-null"
                );
            }
        }
    }

    if let Some(true) = hash_chain.get("hashes_are_distinct").and_then(|v| v.as_bool()) {
        let hashes = &session.runtime.history_hashes;
        if hashes.len() >= 2 {
            let last = &hashes[hashes.len() - 1];
            let prev = &hashes[hashes.len() - 2];
            assert_ne!(
                last, prev,
                "[{test_name}] step {step}: last two hashes should be distinct"
            );
        }
    }

    if let Some(true) = hash_chain.get("all_hashes_unique").and_then(|v| v.as_bool()) {
        let hashes = &session.runtime.history_hashes;
        let mut seen = std::collections::HashSet::new();
        for h in hashes {
            assert!(
                seen.insert(h),
                "[{test_name}] step {step}: duplicate hash found in history"
            );
        }
    }
}

fn assert_component_state(
    session: &GameSession,
    expected: &Value,
    test_name: &str,
    step: usize,
) {
    if let Some(components) = expected.as_object() {
        for (string_id, exp_state) in components {
            let comp = session
                .runtime
                .components
                .iter()
                .find(|c| c.string_id == *string_id)
                .unwrap_or_else(|| {
                    panic!("[{test_name}] step {step}: component {string_id} not found")
                });

            if let Some(exp_facing) = exp_state.get("facing").and_then(|v| v.as_str()) {
                let expected_facing = match exp_facing {
                    "face_up" => Some(Facing::FaceUp),
                    "face_down" => Some(Facing::FaceDown),
                    other => panic!("unknown facing: {other}"),
                };
                assert_eq!(
                    comp.facing, expected_facing,
                    "[{test_name}] step {step}: facing for {string_id} mismatch"
                );
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Test entry point
// ---------------------------------------------------------------------------

#[test]
fn run_all_state_transition_vectors() {
    let vectors = load_vectors();
    let test_cases = vectors["test_cases"].as_array().expect("test_cases is not an array");

    for tc in test_cases {
        let name = tc["name"].as_str().unwrap();
        let def = parse_game_definition(&tc["game_definition"]);
        let setup: Vec<Value> = tc["initial_setup"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let actions = tc["actions"].as_array().expect("actions is not an array");

        let mut session = setup_session(def, &setup);

        for (step, action_entry) in actions.iter().enumerate() {
            let action = build_action(&action_entry["action"]);
            let expected = &action_entry["expected"];

            // Verify acting player before applying action
            if let Some(exp_player) = expected.get("acting_player").and_then(|v| v.as_str()) {
                assert_eq!(
                    session.current_player(),
                    Some(exp_player),
                    "[{name}] step {step}: acting_player mismatch before action"
                );
            }

            // Apply the action
            let events = apply_action(&mut session, &action)
                .unwrap_or_else(|e| panic!("[{name}] step {step}: apply_action failed: {e}"));

            // Verify status
            if let Some(exp_status) = expected.get("status").and_then(|v| v.as_str()) {
                assert_eq!(
                    session.runtime.status,
                    str_to_status(exp_status),
                    "[{name}] step {step}: status mismatch"
                );
            }

            // Verify next turn
            if let Some(exp_turn) = expected.get("next_turn").and_then(|v| v.as_str()) {
                assert_eq!(
                    session.current_player(),
                    Some(exp_turn),
                    "[{name}] step {step}: next_turn mismatch"
                );
            }

            // Verify sequence
            if let Some(exp_seq) = expected.get("sequence").and_then(|v| v.as_u64()) {
                assert_eq!(
                    session.runtime.sequence, exp_seq,
                    "[{name}] step {step}: sequence mismatch"
                );
            }

            // Verify move_count
            if let Some(exp_mc) = expected.get("move_count").and_then(|v| v.as_u64()) {
                assert_eq!(
                    session.runtime.move_count, exp_mc,
                    "[{name}] step {step}: move_count mismatch"
                );
            }

            // Verify events
            if let Some(exp_events) = expected.get("events").and_then(|v| v.as_array()) {
                assert_events(&events, exp_events, name, step);
            }

            // Verify board cells
            if let Some(exp_cells) = expected.get("board_cells") {
                assert_board_cells(&session, exp_cells, name, step);
            }

            // Verify board empty cells
            if let Some(exp_empty) = expected.get("board_empty_cells").and_then(|v| v.as_array()) {
                assert_empty_cells(&session, exp_empty, name, step);
            }

            // Verify hash chain
            if let Some(hash_chain) = expected.get("hash_chain") {
                assert_hash_chain(&session, &events, hash_chain, name, step);
            }

            // Verify component state
            if let Some(comp_state) = expected.get("component_state") {
                assert_component_state(&session, comp_state, name, step);
            }
        }
    }
}
