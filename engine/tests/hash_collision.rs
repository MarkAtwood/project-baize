//! Hash collision resistance tests for state hash computation.
//!
//! Each test creates two near-identical states that differ by exactly one field
//! and asserts the hashes are different.

use baize_engine::runtime::*;
use baize_engine::state::*;
use baize_engine::GameDefinition;

fn tic_tac_toe_def() -> GameDefinition {
    serde_json::from_str(
        r#"{
        "game": { "name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
        },
        "components": {
            "mark": { "owner": "per_player", "count": "unlimited" }
        },
        "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
        "end_conditions": [
            { "result": "win", "player": "current", "condition": "three_in_line" },
            { "result": "draw", "condition": "board_is_full" }
        ],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap()
}

/// Helper: create a session and place a mark at the given position.
fn session_with_mark_at(col: u32, row: u32) -> GameSession {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();
    session.runtime.status = GameStatus::InProgress;

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "mark-x-0".into(),
        component_type: "mark".into(),
        owner: Some("X".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
    }).unwrap();

    session
        .runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(col, row, Some(cid));

    session
}

#[test]
fn different_component_position_produces_different_hash() {
    let s1 = session_with_mark_at(0, 0);
    let s2 = session_with_mark_at(1, 0);

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing by component position must hash differently");
}

#[test]
fn different_component_position_row_produces_different_hash() {
    let s1 = session_with_mark_at(0, 0);
    let s2 = session_with_mark_at(0, 1);

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing by component row must hash differently");
}

#[test]
fn different_turn_produces_different_hash() {
    let def = tic_tac_toe_def();
    let s1 = GameSession::new(def).unwrap();

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.advance_turn();
    // Reset sequence/move_count to isolate the turn_index change.
    s2.runtime.sequence = 0;
    s2.runtime.move_count = 0;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by whose turn it is must hash differently");
}

#[test]
fn different_game_status_produces_different_hash() {
    let def = tic_tac_toe_def();
    let s1 = GameSession::new(def).unwrap();
    // Default status is Setup, no need to set it.

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.status = GameStatus::InProgress;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by game status must hash differently");
}

#[test]
fn different_counter_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime.counters.insert("score".into(), 0);

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.counters.insert("score".into(), 1);

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by counter value must hash differently");
}

#[test]
fn different_phase_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime.phase_index = 0;

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.phase_index = 1; // will resolve to "main" since no phases defined, but let's test with phases

    // Since TTT has no phases, phase_index=1 still produces "main". We need
    // to test with a definition that has phases. Instead, test via the wire state directly.
    let mut state1 = s1.to_wire_state();
    state1.phase = "play".to_string();
    let mut state2 = s1.to_wire_state();
    state2.phase = "scoring".to_string();

    let h1 = state1.compute_hash();
    let h2 = state2.compute_hash();
    assert_ne!(h1, h2, "states differing only by phase must hash differently");
}

#[test]
fn different_player_score_produces_different_hash() {
    let def = tic_tac_toe_def();
    let s1 = GameSession::new(def).unwrap();

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.players.get_mut("X").unwrap().score = 10;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by player score must hash differently");
}

#[test]
fn different_player_active_produces_different_hash() {
    let def = tic_tac_toe_def();
    let s1 = GameSession::new(def).unwrap();

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.players.get_mut("X").unwrap().active = false;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by player active status must hash differently");
}

#[test]
fn different_player_counter_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime
        .players
        .get_mut("X")
        .unwrap()
        .counters
        .insert("chips".into(), 100);

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime
        .players
        .get_mut("X")
        .unwrap()
        .counters
        .insert("chips".into(), 200);

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(
        h1, h2,
        "states differing only by player counter must hash differently"
    );
}

#[test]
fn identical_states_produce_same_hash() {
    let def = tic_tac_toe_def();
    let s1 = GameSession::new(def).unwrap();

    let def2 = tic_tac_toe_def();
    let s2 = GameSession::new(def2).unwrap();

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_eq!(h1, h2, "identical states must produce the same hash");
}

#[test]
fn hash_is_deterministic() {
    let session = session_with_mark_at(1, 1);

    let h1 = session.compute_state_hash();
    let h2 = session.compute_state_hash();
    let h3 = session.compute_state_hash();
    assert_eq!(h1, h2);
    assert_eq!(h2, h3);
}

#[test]
fn different_sequence_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime.sequence = 0;

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.sequence = 1;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(h1, h2, "states differing only by sequence must hash differently");
}

#[test]
fn different_halfmove_clock_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime.halfmove_clock = 0;

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.halfmove_clock = 10;

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(
        h1, h2,
        "states differing only by halfmove clock must hash differently"
    );
}

#[test]
fn different_component_facing_produces_different_hash() {
    let def = tic_tac_toe_def();
    let mut s1 = GameSession::new(def).unwrap();
    s1.runtime.status = GameStatus::InProgress;
    let cid1 = s1.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "card-0".into(),
        component_type: "card".into(),
        owner: None,
        facing: Some(Facing::FaceUp),
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
    }).unwrap();
    s1.runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(0, 0, Some(cid1));

    let def2 = tic_tac_toe_def();
    let mut s2 = GameSession::new(def2).unwrap();
    s2.runtime.status = GameStatus::InProgress;
    let cid2 = s2.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "card-0".into(),
        component_type: "card".into(),
        owner: None,
        facing: Some(Facing::FaceDown),
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
    }).unwrap();
    s2.runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(0, 0, Some(cid2));

    let h1 = s1.compute_state_hash();
    let h2 = s2.compute_state_hash();
    assert_ne!(
        h1, h2,
        "states differing only by component facing must hash differently"
    );
}

#[test]
fn cross_implementation_empty_state_hash() {
    // Pin the expected hash for the initial tic-tac-toe state.
    // The Python implementation must produce this exact value.
    let def = tic_tac_toe_def();
    let session = GameSession::new(def).unwrap();
    let hash = session.compute_state_hash();
    assert_eq!(
        hash,
        "2bb4c6638cd5658d3331b062d2c183dc889a915144b279b87647807c6214d903",
        "pinned hash for initial tic-tac-toe state changed unexpectedly"
    );
}
