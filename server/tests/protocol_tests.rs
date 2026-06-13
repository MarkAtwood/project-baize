use std::collections::HashMap;
use std::fmt::Write as _;

use baize_engine::GameDefinition;
use baize_engine::GameSession;
use baize_server::config;
use baize_server::protocol::{handle_client_message, HandleResult};
use baize_server::room::Room;
use baize_server::vault::{HiddenFact, Vault};

/// Return the same placeholder definition used by room.rs for auto-created rooms.
fn default_definition_json() -> String {
    serde_json::json!({
        "game": {
            "name": "placeholder",
            "players": ["white", "black"],
            "information": "perfect"
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "visibility": "public",
                "dimensions": [8, 8]
            }
        },
        "components": {},
        "turn_order": {
            "type": "alternating",
            "players": ["white", "black"]
        },
        "phases": [],
        "rules": {},
        "end_conditions": [
            {
                "result": "draw",
                "condition": "no_legal_moves"
            }
        ],
        "authority": {
            "server_only": [],
            "client_verifiable": ["move_piece", "place", "pass", "resign"]
        }
    })
    .to_string()
}

/// Create a test room with the placeholder game definition.
fn make_test_room(room_id: &str) -> Room {
    let json = default_definition_json();
    let definition = GameDefinition::from_json(&json).expect("default definition should parse");
    let max_players = 2;
    let session = GameSession::new(definition).expect("session should initialize");
    Room {
        id: room_id.to_string(),
        session,
        vault: Vault::new(),
        players: HashMap::new(),
        max_players,
        player_tokens: HashMap::new(),
        claim_deadline: None,
        ready_players: std::collections::HashSet::new(),
        room_phase: baize_server::room::RoomPhase::Waiting,
    }
}

/// Helper: extract the error_code from a HandleResult::Error JSON string.
fn extract_error_code(result: &HandleResult) -> Option<String> {
    match result {
        HandleResult::Error(json) => {
            let v: serde_json::Value = serde_json::from_str(json).ok()?;
            v.get("error_code").and_then(|c| c.as_str()).map(String::from)
        }
        _ => None,
    }
}

/// Assert that a HandleResult is an Error with the given error_code.
fn assert_error_code(result: &HandleResult, expected_code: &str) {
    let code = extract_error_code(result);
    assert_eq!(
        code.as_deref(),
        Some(expected_code),
        "expected error_code '{expected_code}', got result: {result:?}",
        result = match result {
            HandleResult::Error(s) => format!("Error({s})"),
            HandleResult::Broadcast(_) => "Broadcast(...)".to_string(),
            HandleResult::Reply(_) => "Reply(...)".to_string(),
            HandleResult::FilteredBroadcast { .. } => "FilteredBroadcast(...)".to_string(),
        }
    );
}

// ---- Test 1: Spectator rejection for SubmitMove ----

#[test]
fn spectator_cannot_submit_move() {
    let mut room = make_test_room("game_1");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "game_1",
        "player": "spectator_0",
        "sequence": 0,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "spectator_0", &msg, &mut seq);
    assert_error_code(&result, "spectator_not_allowed");
}

// ---- Test 2: Spectator rejection for RequestRandom ----

#[test]
fn spectator_cannot_request_random() {
    let mut room = make_test_room("game_2");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "game_2",
        "player": "spectator_0",
        "random_request": {
            "random_type": "roll"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "spectator_0", &msg, &mut seq);
    assert_error_code(&result, "spectator_not_allowed");
}

// ---- Test 3: Spectator allowed for AcknowledgeState ----

#[test]
fn spectator_can_acknowledge_state() {
    let mut room = make_test_room("game_3");
    let mut seq = 0u64;

    // Use a valid 64-char hex string for state_hash
    let fake_hash = "a".repeat(64);

    let msg = serde_json::json!({
        "message_type": "acknowledge_state",
        "game_id": "game_3",
        "player": "spectator_0",
        "state_hash": fake_hash
    })
    .to_string();

    let result = handle_client_message(&mut room, "spectator_0", &msg, &mut seq);

    // Should NOT be an error -- spectators can send AcknowledgeState.
    // The result is Reply (either empty or with a StateSync if hashes diverge).
    match &result {
        HandleResult::Reply(_) => {} // expected
        HandleResult::Error(e) => {
            panic!("spectator AcknowledgeState should not error, got: {e}");
        }
        HandleResult::Broadcast(_) | HandleResult::FilteredBroadcast { .. } => {
            panic!("spectator AcknowledgeState should Reply, not Broadcast");
        }
    }
}

// ---- Test 4: Seat mismatch rejection ----

#[test]
fn seat_mismatch_is_rejected() {
    let mut room = make_test_room("game_4");
    let mut seq = 0u64;

    // Seated as "white" but claims to be "black"
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "game_4",
        "player": "black",
        "sequence": 0,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

// ---- Test 5: Game ID mismatch rejection ----

#[test]
fn game_id_mismatch_is_rejected() {
    let mut room = make_test_room("game_5");
    let mut seq = 0u64;

    // Room is "game_5" but message targets "wrong_game"
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "wrong_game",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "game_id_mismatch");
}

// ---- Test 6: Sequence number enforcement ----

#[test]
fn sequence_replay_is_rejected() {
    let mut room = make_test_room("game_6");
    let mut seq = 0u64;

    // Send sequences 0, 1, 2 -- all should pass validation
    // (they may fail later on turn/engine logic, but not on sequence check)
    for s in 0..3 {
        let msg = serde_json::json!({
            "message_type": "submit_move",
            "game_id": "game_6",
            "player": "white",
            "sequence": s,
            "action": {
                "action_type": "pass"
            }
        })
        .to_string();

        let result = handle_client_message(&mut room, "white", &msg, &mut seq);
        // These should NOT fail on sequence validation
        assert!(
            extract_error_code(&result).as_deref() != Some("sequence_error"),
            "sequence {s} should not trigger sequence_error"
        );
    }

    // Now seq should be 3 (after processing 0, 1, 2).
    // Replaying sequence 1 should fail.
    let replay_msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "game_6",
        "player": "white",
        "sequence": 1,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &replay_msg, &mut seq);
    assert_error_code(&result, "sequence_error");
}

// ---- Test 7: State hash format validation ----

#[test]
fn invalid_state_hash_too_short() {
    let mut room = make_test_room("game_7");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "acknowledge_state",
        "game_id": "game_7",
        "player": "white",
        "state_hash": "abcd1234"
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_state_hash");
}

#[test]
fn invalid_state_hash_non_hex() {
    let mut room = make_test_room("game_7b");
    let mut seq = 0u64;

    // 64 chars but contains 'g' which is not hex
    let bad_hash = "g".repeat(64);

    let msg = serde_json::json!({
        "message_type": "acknowledge_state",
        "game_id": "game_7b",
        "player": "white",
        "state_hash": bad_hash
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_state_hash");
}

#[test]
fn invalid_state_hash_too_long() {
    let mut room = make_test_room("game_7c");
    let mut seq = 0u64;

    // 65 hex chars (one too many)
    let long_hash = "a".repeat(65);

    let msg = serde_json::json!({
        "message_type": "acknowledge_state",
        "game_id": "game_7c",
        "player": "white",
        "state_hash": long_hash
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_state_hash");
}

// ---- Test 8: Turn check on RequestRandom ----

#[test]
fn request_random_rejected_when_not_your_turn() {
    let mut room = make_test_room("game_8");
    let mut seq = 0u64;

    // In the default definition, turn_order is ["white", "black"]
    // with alternating turns starting at index 0 = "white".
    // So "black" is NOT the current player.
    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "game_8",
        "player": "black",
        "random_request": {
            "random_type": "roll"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "black", &msg, &mut seq);
    assert_error_code(&result, "not_your_turn");
}

// ---- Test 9: Move count limit ----

#[test]
fn moves_rejected_after_max_moves_per_game() {
    let mut room = make_test_room("game_9");
    let mut seq = 0u64;

    // Artificially set the sequence to the maximum to trigger the limit.
    room.session.runtime.sequence = config::MAX_MOVES_PER_GAME;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "game_9",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);

    // This should result in a MoveRejected reply, not a protocol error.
    // The move is rejected because the game exceeded the max move count.
    match &result {
        HandleResult::Reply(msgs) => {
            assert_eq!(msgs.len(), 1, "expected exactly one MoveRejected reply");
            let json = serde_json::to_value(&msgs[0]).expect("should serialize");
            assert_eq!(
                json.get("message_type").and_then(|v| v.as_str()),
                Some("move_rejected"),
                "expected move_rejected, got: {json}"
            );
            let reason = json.get("reason").and_then(|v| v.as_str()).unwrap_or("");
            assert!(
                reason.contains("maximum move count"),
                "reason should mention maximum move count, got: {reason}"
            );
        }
        HandleResult::Error(e) => {
            panic!("expected Reply(MoveRejected), got Error: {e}");
        }
        HandleResult::Broadcast(_) | HandleResult::FilteredBroadcast { .. } => {
            panic!("expected Reply(MoveRejected), got Broadcast");
        }
    }
}

// ---- Debug redaction tests for Room ----

#[test]
fn room_debug_does_not_leak_hidden_state() {
    let mut room = make_test_room("redact_test");

    // Populate the vault with secret deck contents
    room.vault.register_deck(
        "draw_pile",
        vec!["ace_spades".into(), "king_hearts".into()],
    );
    room.vault.add_hidden_fact(
        "alice",
        HiddenFact {
            zone: "hand".into(),
            component_id: "secret_card_42".into(),
            properties: serde_json::json!({"suit": "diamonds", "rank": 42}),
        },
    );

    let mut debug_output = String::new();
    write!(&mut debug_output, "{:?}", room).expect("Debug formatting should not fail");

    // Room Debug must not leak vault deck contents
    assert!(
        !debug_output.contains("ace_spades"),
        "Room Debug must not contain deck card names, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("king_hearts"),
        "Room Debug must not contain deck card names, got: {debug_output}"
    );

    // Room Debug must not leak hidden facts
    assert!(
        !debug_output.contains("secret_card_42"),
        "Room Debug must not contain hidden fact IDs, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("diamonds"),
        "Room Debug must not contain hidden fact properties, got: {debug_output}"
    );

    // Should show the room ID (non-secret metadata)
    assert!(
        debug_output.contains("redact_test"),
        "Room Debug should include the room ID, got: {debug_output}"
    );

    // Should show redacted placeholders
    assert!(
        debug_output.contains("redacted"),
        "Room Debug should mention redaction, got: {debug_output}"
    );
}

#[test]
fn room_debug_does_not_leak_player_tokens() {
    let mut room = make_test_room("token_test");

    // Insert a fake player token
    room.player_tokens
        .insert("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4".into(), "white".into());

    let mut debug_output = String::new();
    write!(&mut debug_output, "{:?}", room).expect("Debug formatting should not fail");

    assert!(
        !debug_output.contains("a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"),
        "Room Debug must not contain player auth tokens, got: {debug_output}"
    );
    assert!(
        debug_output.contains("tokens redacted"),
        "Room Debug should indicate tokens are redacted, got: {debug_output}"
    );
}
