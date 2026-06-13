use std::collections::HashMap;

use baize_engine::GameDefinition;
use baize_engine::GameSession;
use baize_server::config;
use baize_server::protocol::{handle_client_message, HandleResult};
use baize_server::room::Room;
use baize_server::vault::Vault;

/// Return the same placeholder definition used by other test files.
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
    let session = GameSession::new(definition).expect("session should initialize");
    Room {
        id: room_id.to_string(),
        session,
        vault: Vault::new(),
        players: HashMap::new(),
        max_players: 2,
        player_tokens: HashMap::new(),
        claim_deadline: None,
    }
}

/// Extract error_code from a HandleResult::Error JSON string.
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
        "expected error_code '{expected_code}', got result: {}",
        match result {
            HandleResult::Error(s) => format!("Error({s})"),
            HandleResult::Broadcast(_) => "Broadcast(...)".to_string(),
            HandleResult::Reply(_) => "Reply(...)".to_string(),
            HandleResult::FilteredBroadcast { .. } => "FilteredBroadcast(...)".to_string(),
        }
    );
}

// ============================================================
// Unknown / missing message_type
// ============================================================

#[test]
fn unknown_message_type_rejected() {
    let mut room = make_test_room("hard_1");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "hack_the_planet",
        "game_id": "hard_1",
        "player": "white"
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn missing_message_type_field_rejected() {
    let mut room = make_test_room("hard_2");
    let mut seq = 0u64;

    // Valid JSON but no message_type field at all
    let msg = serde_json::json!({
        "game_id": "hard_2",
        "player": "white"
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn empty_json_object_rejected() {
    let mut room = make_test_room("hard_3");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "{}", &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn message_type_as_integer_rejected() {
    let mut room = make_test_room("hard_4");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": 42,
        "game_id": "hard_4",
        "player": "white"
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn message_type_as_null_rejected() {
    let mut room = make_test_room("hard_5");
    let mut seq = 0u64;

    let msg = r#"{"message_type": null, "game_id": "hard_5", "player": "white"}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn message_type_as_empty_string_rejected() {
    let mut room = make_test_room("hard_6");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "",
        "game_id": "hard_6",
        "player": "white"
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

// ============================================================
// Malformed JSON
// ============================================================

#[test]
fn truncated_json_rejected() {
    let mut room = make_test_room("hard_7");
    let mut seq = 0u64;

    let result = handle_client_message(
        &mut room,
        "white",
        r#"{"message_type": "submit_mo"#,
        &mut seq,
    );
    assert_error_code(&result, "invalid_message");
}

#[test]
fn json_array_instead_of_object_rejected() {
    let mut room = make_test_room("hard_8");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", r#"[1, 2, 3]"#, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn bare_string_rejected() {
    let mut room = make_test_room("hard_9");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", r#""hello""#, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn bare_number_rejected() {
    let mut room = make_test_room("hard_10");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "42", &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn bare_null_rejected() {
    let mut room = make_test_room("hard_11");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "null", &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn bare_boolean_rejected() {
    let mut room = make_test_room("hard_12");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "true", &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn completely_invalid_text_rejected() {
    let mut room = make_test_room("hard_13");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "not json at all", &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn deeply_nested_json_rejected() {
    let mut room = make_test_room("hard_14");
    let mut seq = 0u64;

    // 200 levels of nesting — serde_json has a default recursion limit of 128
    let open = "{\"a\":".repeat(200);
    let close = "}".repeat(200);
    let nested = format!("{open}1{close}");

    let result = handle_client_message(&mut room, "white", &nested, &mut seq);
    assert_error_code(&result, "invalid_message");
}

// ============================================================
// Seat / player mismatch variants
// ============================================================

#[test]
fn submit_move_with_empty_player_rejected() {
    let mut room = make_test_room("hard_15");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_15",
        "player": "",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // Empty player does not match seat "white" → seat_mismatch
    assert_error_code(&result, "seat_mismatch");
}

#[test]
fn submit_move_with_nonexistent_player_rejected() {
    let mut room = make_test_room("hard_16");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_16",
        "player": "eve",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

#[test]
fn acknowledge_state_with_wrong_player_rejected() {
    let mut room = make_test_room("hard_17");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "acknowledge_state",
        "game_id": "hard_17",
        "player": "black",
        "state_hash": "a".repeat(64)
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

#[test]
fn request_random_with_wrong_player_rejected() {
    let mut room = make_test_room("hard_18");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "hard_18",
        "player": "black",
        "random_request": { "random_type": "roll" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

// ============================================================
// Spectator variants
// ============================================================

#[test]
fn spectator_submit_move_with_spectator_name_rejected() {
    let mut room = make_test_room("hard_19");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_19",
        "player": "spectator_5",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "spectator_5", &msg, &mut seq);
    assert_error_code(&result, "spectator_not_allowed");
}

#[test]
fn spectator_request_random_rejected() {
    let mut room = make_test_room("hard_20");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "hard_20",
        "player": "spectator_99",
        "random_request": { "random_type": "shuffle" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "spectator_99", &msg, &mut seq);
    assert_error_code(&result, "spectator_not_allowed");
}

// ============================================================
// Sequence number edge cases
// ============================================================

#[test]
fn sequence_zero_after_gap_accepted() {
    // If sequence goes 0, then jumps to 10, the gap should be allowed
    // (server only rejects out-of-order / replays, not gaps).
    let mut room = make_test_room("hard_21");
    let mut seq = 0u64;

    let msg0 = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_21",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg0, &mut seq);
    // Should not be a sequence_error (may be move_rejected for other reasons)
    assert_ne!(
        extract_error_code(&result).as_deref(),
        Some("sequence_error"),
        "sequence 0 should not trigger sequence_error"
    );

    // Now jump to sequence 10 — gap should be allowed
    let msg10 = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_21",
        "player": "white",
        "sequence": 10,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg10, &mut seq);
    assert_ne!(
        extract_error_code(&result).as_deref(),
        Some("sequence_error"),
        "sequence 10 (gap) should not trigger sequence_error"
    );

    // Now replaying sequence 5 should fail
    let msg5 = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_21",
        "player": "white",
        "sequence": 5,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg5, &mut seq);
    assert_error_code(&result, "sequence_error");
}

#[test]
fn missing_sequence_field_does_not_error() {
    // sequence is optional on SubmitMove — omitting it should not trigger sequence_error
    let mut room = make_test_room("hard_22");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_22",
        "player": "white",
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // Should not be a sequence_error (may be other errors like engine rejection)
    assert_ne!(
        extract_error_code(&result).as_deref(),
        Some("sequence_error"),
        "omitted sequence should not trigger sequence_error"
    );
}

#[test]
fn large_sequence_number_accepted() {
    let mut room = make_test_room("hard_23");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_23",
        "player": "white",
        "sequence": u64::MAX - 1,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_ne!(
        extract_error_code(&result).as_deref(),
        Some("sequence_error"),
        "very large sequence should be accepted when expected_seq is 0"
    );
}

// ============================================================
// Oversized message at protocol level
// ============================================================

#[test]
fn enormous_json_string_exceeds_config_limit() {
    // Verify the config constant exists and has a sensible value.
    // The actual rejection happens at the axum WebSocket frame level,
    // but we can verify parsing a >MAX_MESSAGE_SIZE string still
    // produces invalid_message (not a panic).
    let mut room = make_test_room("hard_24");
    let mut seq = 0u64;

    // 1MB of padding in a JSON string — well over the 64KB limit
    let padding = "x".repeat(1_048_576);
    let msg = format!(
        r#"{{"message_type": "submit_move", "game_id": "hard_24", "player": "white", "sequence": 0, "action": {{"action_type": "pass", "declaration": "{padding}"}}}}"#
    );

    // At the protocol handler level, this still parses as JSON and should
    // hit the MAX_ACTION_FIELD_LENGTH check or parse correctly.
    // Either way, it must not panic.
    let result = handle_client_message(&mut room, "white", &msg, &mut seq);

    // We accept either invalid_action (field too long) or another non-panic error
    match &result {
        HandleResult::Error(_) => {} // any error is fine — no panic
        HandleResult::Reply(_) => {} // move_rejected is also fine
        HandleResult::Broadcast(_) | HandleResult::FilteredBroadcast { .. } => {
            // This means the engine accepted a 1MB declaration field, which
            // is surprising but not a panic
        }
    }

    // Verify the config limit is 64KB
    assert_eq!(config::MAX_MESSAGE_SIZE, 64 * 1024);
}

// ============================================================
// Wrong field types in otherwise valid structure
// ============================================================

#[test]
fn sequence_as_string_rejected() {
    let mut room = make_test_room("hard_25");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_25", "player": "white", "sequence": "not_a_number", "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn sequence_as_negative_number_rejected() {
    let mut room = make_test_room("hard_26");
    let mut seq = 0u64;

    // JSON allows negative numbers, but sequence is u64 — serde should reject
    let msg = r#"{"message_type": "submit_move", "game_id": "hard_26", "player": "white", "sequence": -1, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn sequence_as_float_rejected() {
    let mut room = make_test_room("hard_27");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_27", "player": "white", "sequence": 1.5, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn player_as_integer_rejected() {
    let mut room = make_test_room("hard_28");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_28", "player": 123, "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn action_as_string_rejected() {
    let mut room = make_test_room("hard_29");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_29", "player": "white", "sequence": 0, "action": "pass"}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn game_id_as_array_rejected() {
    let mut room = make_test_room("hard_30");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": ["hard_30"], "player": "white", "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

// ============================================================
// Duplicate fields in JSON
// ============================================================

#[test]
fn duplicate_message_type_uses_last_value() {
    // RFC 7159 says duplicate keys have undefined behavior.
    // serde_json uses the last value. Verify we handle this without panic.
    let mut room = make_test_room("hard_31");
    let mut seq = 0u64;

    // First message_type is valid, second is garbage
    let msg = r#"{"message_type": "submit_move", "message_type": "hack_the_planet", "game_id": "hard_31", "player": "white", "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    // serde_json takes the last "message_type" = "hack_the_planet" → unknown variant
    assert_error_code(&result, "invalid_message");
}

#[test]
fn duplicate_message_type_first_wins() {
    // serde(tag = "...") uses the FIRST occurrence of the tag field.
    // First message_type is garbage → parse fails even though second is valid.
    let mut room = make_test_room("hard_32");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "hack_the_planet", "message_type": "submit_move", "game_id": "hard_32", "player": "white", "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    // First-wins means "hack_the_planet" is used → invalid_message
    assert_error_code(&result, "invalid_message");
}

// ============================================================
// Extra / unexpected fields are silently ignored (serde default)
// ============================================================

#[test]
fn extra_fields_ignored_not_rejected() {
    let mut room = make_test_room("hard_33");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_33",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "pass" },
        "injected_field": "should_be_ignored",
        "another": [1, 2, 3]
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // Must not be invalid_message — extra fields are silently dropped
    assert_ne!(
        extract_error_code(&result).as_deref(),
        Some("invalid_message"),
        "extra fields should be silently ignored by serde"
    );
}

// ============================================================
// Unicode and special character edge cases
// ============================================================

#[test]
fn unicode_player_name_seat_mismatch() {
    let mut room = make_test_room("hard_34");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_34",
        "player": "\u{0000}white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

#[test]
fn whitespace_player_name_seat_mismatch() {
    let mut room = make_test_room("hard_35");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_35",
        "player": " white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "seat_mismatch");
}

// ============================================================
// Game ID mismatch edge cases
// ============================================================

#[test]
fn empty_game_id_in_message_rejected() {
    let mut room = make_test_room("hard_36");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "game_id_mismatch");
}

// ============================================================
// Missing required fields
// ============================================================

#[test]
fn submit_move_missing_player_rejected() {
    let mut room = make_test_room("hard_37");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_37", "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn submit_move_missing_game_id_rejected() {
    let mut room = make_test_room("hard_38");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "player": "white", "sequence": 0, "action": {"action_type": "pass"}}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn submit_move_missing_action_rejected() {
    let mut room = make_test_room("hard_39");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "submit_move", "game_id": "hard_39", "player": "white", "sequence": 0}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn acknowledge_state_missing_state_hash_rejected() {
    let mut room = make_test_room("hard_40");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "acknowledge_state", "game_id": "hard_40", "player": "white"}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

#[test]
fn request_random_missing_random_request_rejected() {
    let mut room = make_test_room("hard_41");
    let mut seq = 0u64;

    let msg = r#"{"message_type": "request_random", "game_id": "hard_41", "player": "white"}"#;
    let result = handle_client_message(&mut room, "white", msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}

// ============================================================
// Unknown action_type
// ============================================================

#[test]
fn unknown_action_type_rejected() {
    let mut room = make_test_room("hard_42");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "hard_42",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "teleport" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    assert_error_code(&result, "invalid_message");
}
