//! Abuse resistance tests: rate limiting, connection limits, resource exhaustion guards.
//!
//! These tests verify the server's defense-in-depth limits documented in config.rs.

use std::collections::HashMap;
use std::net::{IpAddr, Ipv4Addr};
use std::time::{Duration, Instant};

use baize_engine::GameDefinition;
use baize_engine::GameSession;
use baize_server::config;
use baize_server::protocol::{handle_client_message, HandleResult};
use baize_server::rate_limiter::RateLimiter;
use baize_server::room::{self, Room, RoomRegistry};
use baize_server::vault::Vault;

// =============================================================
// Helpers
// =============================================================

/// Return the placeholder definition used across server tests.
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

// =============================================================
// RateLimiter unit tests
// =============================================================

#[test]
fn rate_limiter_allows_first_message() {
    let mut limiter = RateLimiter::new(5);
    assert!(limiter.check(), "first message must be allowed");
}

#[test]
fn rate_limiter_allows_up_to_limit() {
    let mut limiter = RateLimiter::new(5);
    for i in 0..5 {
        assert!(limiter.check(), "message {i} should be allowed (limit is 5)");
    }
}

#[test]
fn rate_limiter_rejects_at_capacity() {
    let mut limiter = RateLimiter::new(5);
    // Fill to capacity
    for _ in 0..5 {
        assert!(limiter.check());
    }
    // The 6th should be rejected
    assert!(!limiter.check(), "message beyond limit must be rejected");
}

#[test]
fn rate_limiter_rejects_multiple_excess_messages() {
    let mut limiter = RateLimiter::new(3);
    for _ in 0..3 {
        assert!(limiter.check());
    }
    // All subsequent messages within the window should be rejected
    for _ in 0..10 {
        assert!(!limiter.check(), "all excess messages must be rejected");
    }
}

#[test]
fn rate_limiter_recovers_after_window_passes() {
    let mut limiter = RateLimiter::new(3);
    let start = Instant::now();

    // Fill to capacity at time T
    for _ in 0..3 {
        assert!(limiter.check_at(start));
    }
    assert!(!limiter.check_at(start), "should be at capacity");

    // Advance past the 1-second window
    let after_window = start + Duration::from_millis(1001);
    assert!(
        limiter.check_at(after_window),
        "should allow messages after window expires"
    );
}

#[test]
fn rate_limiter_sliding_window_partial_expiry() {
    let mut limiter = RateLimiter::new(3);
    let t0 = Instant::now();

    // Send 2 messages at t0
    assert!(limiter.check_at(t0));
    assert!(limiter.check_at(t0));

    // Send 1 message at t0 + 500ms
    let t500 = t0 + Duration::from_millis(500);
    assert!(limiter.check_at(t500));

    // At t0 + 500ms we're at capacity (3 messages in the window)
    assert!(!limiter.check_at(t500), "should be at capacity at t0+500ms");

    // At t0 + 1001ms, the two t0 messages have expired, but the t500 one remains
    let t1001 = t0 + Duration::from_millis(1001);
    assert!(
        limiter.check_at(t1001),
        "2 of 3 messages expired, should allow"
    );
    assert!(
        limiter.check_at(t1001),
        "still under limit after one new message"
    );
    // Now we have 3 in window again (1 from t500, 2 from t1001)
    assert!(!limiter.check_at(t1001), "back at capacity");
}

#[test]
fn rate_limiter_window_count_tracks_messages() {
    let mut limiter = RateLimiter::new(10);
    assert_eq!(limiter.window_count(), 0);

    limiter.check();
    assert_eq!(limiter.window_count(), 1);

    for _ in 0..4 {
        limiter.check();
    }
    assert_eq!(limiter.window_count(), 5);
}

#[test]
fn rate_limiter_zero_limit_rejects_everything() {
    let mut limiter = RateLimiter::new(0);
    assert!(!limiter.check(), "zero limit should reject all messages");
}

#[test]
fn rate_limiter_limit_of_one() {
    let mut limiter = RateLimiter::new(1);
    assert!(limiter.check(), "first message allowed with limit 1");
    assert!(!limiter.check(), "second message rejected with limit 1");
}

// =============================================================
// Per-IP connection limit tests
// =============================================================

#[tokio::test]
async fn per_ip_connection_limit_enforced() {
    let registry = RoomRegistry::new();
    let ip = IpAddr::V4(Ipv4Addr::new(10, 0, 0, 1));

    // Acquire up to the limit
    let mut guards = Vec::new();
    for i in 0..config::MAX_CONNECTIONS_PER_IP {
        let guard = registry
            .acquire_ip_slot(ip)
            .await
            .unwrap_or_else(|e| panic!("connection {i} should succeed: {e}"));
        guards.push(guard);
    }

    // One more should be rejected
    let result = registry.acquire_ip_slot(ip).await;
    assert!(
        result.is_err(),
        "connection beyond per-IP limit must be rejected"
    );
    let err = result.unwrap_err();
    assert!(
        err.contains("too many connections"),
        "error should mention too many connections, got: {err}"
    );
}

#[tokio::test]
async fn per_ip_connection_slot_released_on_drop() {
    let registry = RoomRegistry::new();
    let ip = IpAddr::V4(Ipv4Addr::new(10, 0, 0, 2));

    // Fill to capacity
    let mut guards = Vec::new();
    for _ in 0..config::MAX_CONNECTIONS_PER_IP {
        guards.push(registry.acquire_ip_slot(ip).await.unwrap());
    }

    // At capacity
    assert!(registry.acquire_ip_slot(ip).await.is_err());

    // Drop one guard to free a slot
    guards.pop();

    // Should now be able to acquire again
    let guard = registry
        .acquire_ip_slot(ip)
        .await
        .expect("should succeed after releasing a slot");
    guards.push(guard);
}

#[tokio::test]
async fn different_ips_have_independent_limits() {
    let registry = RoomRegistry::new();
    let ip1 = IpAddr::V4(Ipv4Addr::new(10, 0, 0, 10));
    let ip2 = IpAddr::V4(Ipv4Addr::new(10, 0, 0, 11));

    // Fill IP1 to capacity
    let mut guards = Vec::new();
    for _ in 0..config::MAX_CONNECTIONS_PER_IP {
        guards.push(registry.acquire_ip_slot(ip1).await.unwrap());
    }
    assert!(registry.acquire_ip_slot(ip1).await.is_err(), "IP1 at capacity");

    // IP2 should still be able to connect
    let guard2 = registry
        .acquire_ip_slot(ip2)
        .await
        .expect("IP2 should not be affected by IP1 being at capacity");
    guards.push(guard2);
}

// =============================================================
// Total connection limit tests
// =============================================================

#[tokio::test]
async fn total_connection_limit_enforced() {
    let registry = RoomRegistry::new();

    // Acquire connections from different IPs until we hit MAX_TOTAL_CONNECTIONS.
    // Each IP gets one connection to avoid hitting per-IP limits.
    let mut guards = Vec::new();
    for i in 0..config::MAX_TOTAL_CONNECTIONS {
        // Use unique IPs: 10.x.y.z
        let ip = IpAddr::V4(Ipv4Addr::new(
            10,
            ((i >> 16) & 0xFF) as u8,
            ((i >> 8) & 0xFF) as u8,
            (i & 0xFF) as u8,
        ));
        let guard = registry
            .acquire_ip_slot(ip)
            .await
            .unwrap_or_else(|e| panic!("connection {i} should succeed: {e}"));
        guards.push(guard);
    }

    assert_eq!(
        registry.total_connection_count(),
        config::MAX_TOTAL_CONNECTIONS,
        "total connections should be at capacity"
    );

    // One more from a new IP should be rejected
    let overflow_ip = IpAddr::V4(Ipv4Addr::new(192, 168, 1, 1));
    let result = registry.acquire_ip_slot(overflow_ip).await;
    assert!(
        result.is_err(),
        "connection beyond total limit must be rejected"
    );
    let err = result.unwrap_err();
    assert!(
        err.contains("connection capacity"),
        "error should mention connection capacity, got: {err}"
    );
}

#[tokio::test]
async fn total_connection_count_decrements_on_drop() {
    let registry = RoomRegistry::new();
    let ip = IpAddr::V4(Ipv4Addr::new(10, 0, 0, 50));

    assert_eq!(registry.total_connection_count(), 0);

    let guard = registry.acquire_ip_slot(ip).await.unwrap();
    assert_eq!(registry.total_connection_count(), 1);

    drop(guard);
    assert_eq!(registry.total_connection_count(), 0);
}

// =============================================================
// Room capacity tests
// =============================================================

#[test]
fn room_rejects_players_beyond_max_capacity() {
    let mut room = make_test_room("capacity_test");
    assert_eq!(room.max_players, 2);

    // Fill to capacity
    let _rx1 = room::join_room(&mut room, "white".to_string());
    let _rx2 = room::join_room(&mut room, "black".to_string());

    // Room should be full
    assert!(
        !room::room_has_capacity(&room),
        "room at max_players should have no capacity"
    );
}

#[test]
fn room_has_capacity_with_one_slot() {
    let mut room = make_test_room("capacity_one_slot");
    let _rx1 = room::join_room(&mut room, "white".to_string());
    assert!(
        room::room_has_capacity(&room),
        "room with 1 of 2 seats filled should have capacity"
    );
}

// =============================================================
// Max moves per game (DoS prevention)
// =============================================================

#[test]
fn move_rejected_at_exact_move_limit() {
    let mut room = make_test_room("move_limit_exact");
    let mut seq = 0u64;

    // Set sequence to exactly MAX_MOVES_PER_GAME
    room.session.runtime.sequence = config::MAX_MOVES_PER_GAME;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "move_limit_exact",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    match &result {
        HandleResult::Reply(msgs) => {
            let json = serde_json::to_value(&msgs[0]).unwrap();
            assert_eq!(
                json.get("message_type").and_then(|v| v.as_str()),
                Some("move_rejected")
            );
            let reason = json.get("reason").and_then(|v| v.as_str()).unwrap_or("");
            assert!(
                reason.contains("maximum move count"),
                "reason should mention maximum move count, got: {reason}"
            );
        }
        _ => panic!("expected Reply(MoveRejected) at move limit"),
    }
}

#[test]
fn move_allowed_below_move_limit() {
    let mut room = make_test_room("move_limit_below");
    let mut seq = 0u64;

    // Set sequence to one below the limit — move should not be rejected for move count
    room.session.runtime.sequence = config::MAX_MOVES_PER_GAME - 1;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "move_limit_below",
        "player": "white",
        "sequence": 0,
        "action": { "action_type": "pass" }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // Should NOT be rejected for move count (may fail for other reasons like
    // engine validation, but not for the move count limit)
    match &result {
        HandleResult::Reply(msgs) => {
            let json = serde_json::to_value(&msgs[0]).unwrap();
            let reason = json.get("reason").and_then(|v| v.as_str()).unwrap_or("");
            assert!(
                !reason.contains("maximum move count"),
                "should not be rejected for move count below limit, got: {reason}"
            );
        }
        HandleResult::FilteredBroadcast { .. } => {
            // Move was accepted and applied
        }
        HandleResult::Broadcast(_) => {
            // Move was accepted
        }
        HandleResult::Error(e) => {
            // Protocol error is acceptable (not a move count rejection)
            assert!(
                !e.contains("maximum move count"),
                "should not see move count error below limit"
            );
        }
    }
}

// =============================================================
// Action field length limits (MAX_ACTION_FIELD_LENGTH = 256)
// =============================================================

#[test]
fn action_field_within_limit_accepted() {
    let mut room = make_test_room("field_limit_ok");
    let mut seq = 0u64;

    // A zone name at the boundary (but must be a valid zone in the definition)
    // Since "board" is the only valid zone, use that
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "field_limit_ok",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "move_piece",
            "zone": "board"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // Should not be rejected for field length (may fail for other reasons)
    let code = extract_error_code(&result);
    assert_ne!(
        code.as_deref(),
        Some("invalid_action"),
        "valid-length field should not trigger invalid_action for length"
    );
}

#[test]
fn action_field_exceeding_limit_rejected() {
    let mut room = make_test_room("field_limit_over");
    let mut seq = 0u64;

    // Create a zone name that exceeds MAX_ACTION_FIELD_LENGTH
    let long_zone = "a".repeat(config::MAX_ACTION_FIELD_LENGTH + 1);
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "field_limit_over",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "move_piece",
            "zone": long_zone
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "oversized field should produce invalid_action error"
    );
}

#[test]
fn action_component_id_exceeding_limit_rejected() {
    let mut room = make_test_room("field_cid_over");
    let mut seq = 0u64;

    let long_cid = "x".repeat(config::MAX_ACTION_FIELD_LENGTH + 1);
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "field_cid_over",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "move_piece",
            "component_id": long_cid
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "oversized component_id should produce invalid_action error"
    );
}

#[test]
fn action_declaration_exceeding_limit_rejected() {
    let mut room = make_test_room("field_decl_over");
    let mut seq = 0u64;

    let long_decl = "d".repeat(config::MAX_ACTION_FIELD_LENGTH + 1);
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "field_decl_over",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "place",
            "declaration": long_decl
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "oversized declaration should produce invalid_action error"
    );
}

#[test]
fn action_empty_field_rejected() {
    let mut room = make_test_room("field_empty");
    let mut seq = 0u64;

    // An empty component_id is rejected (non-empty validation)
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "field_empty",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "move_piece",
            "component_id": ""
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "empty component_id should produce invalid_action error"
    );
}

// =============================================================
// Dice and random request limits
// =============================================================

#[test]
fn dice_count_exceeding_limit_rejected() {
    let mut room = make_test_room("dice_count_over");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "dice_count_over",
        "player": "white",
        "random_request": {
            "random_type": "roll",
            "dice_count": config::MAX_DICE_COUNT + 1,
            "dice_type": "d6"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "dice_count exceeding limit should produce invalid_random_request"
    );
}

#[test]
fn dice_faces_exceeding_limit_rejected() {
    let mut room = make_test_room("dice_faces_over");
    let mut seq = 0u64;

    let dice_type = format!("d{}", config::MAX_DICE_FACES + 1);
    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "dice_faces_over",
        "player": "white",
        "random_request": {
            "random_type": "roll",
            "dice_count": 1,
            "dice_type": dice_type
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "dice_faces exceeding limit should produce invalid_random_request"
    );
}

#[test]
fn draw_count_exceeding_limit_rejected() {
    let mut room = make_test_room("draw_count_over");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "draw_count_over",
        "player": "white",
        "random_request": {
            "random_type": "draw",
            "draw_count": config::MAX_DRAW_COUNT + 1,
            "draw_from": "board"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "draw_count exceeding limit should produce invalid_random_request"
    );
}

#[test]
fn zone_name_exceeding_length_rejected() {
    let mut room = make_test_room("zone_name_long");
    let mut seq = 0u64;

    let long_zone = "z".repeat(config::MAX_ZONE_NAME_LENGTH + 1);
    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "zone_name_long",
        "player": "white",
        "random_request": {
            "random_type": "draw",
            "draw_count": 1,
            "draw_from": long_zone
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "zone name exceeding length limit should produce invalid_random_request"
    );
}

#[test]
fn shuffle_zone_name_exceeding_length_rejected() {
    let mut room = make_test_room("shuffle_zone_long");
    let mut seq = 0u64;

    let long_zone = "s".repeat(config::MAX_ZONE_NAME_LENGTH + 1);
    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "shuffle_zone_long",
        "player": "white",
        "random_request": {
            "random_type": "shuffle",
            "shuffle_zone": long_zone
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "shuffle zone name exceeding length limit should produce invalid_random_request"
    );
}

#[test]
fn dice_count_zero_rejected() {
    let mut room = make_test_room("dice_count_zero");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "dice_count_zero",
        "player": "white",
        "random_request": {
            "random_type": "roll",
            "dice_count": 0,
            "dice_type": "d6"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "zero dice_count should produce invalid_random_request"
    );
}

#[test]
fn dice_zero_faces_rejected() {
    let mut room = make_test_room("dice_zero_faces");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "dice_zero_faces",
        "player": "white",
        "random_request": {
            "random_type": "roll",
            "dice_count": 1,
            "dice_type": "d0"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "d0 should produce invalid_random_request"
    );
}

#[test]
fn draw_count_zero_rejected() {
    let mut room = make_test_room("draw_count_zero");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "draw_count_zero",
        "player": "white",
        "random_request": {
            "random_type": "draw",
            "draw_count": 0,
            "draw_from": "board"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_random_request"),
        "zero draw_count should produce invalid_random_request"
    );
}

// =============================================================
// Action field boundary: dice_count on action
// =============================================================

#[test]
fn action_dice_count_exceeding_limit_rejected() {
    let mut room = make_test_room("action_dice_over");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "action_dice_over",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "pass",
            "dice_count": config::MAX_DICE_COUNT + 1
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "action dice_count exceeding limit should produce invalid_action"
    );
}

#[test]
fn action_rotation_out_of_range_rejected() {
    let mut room = make_test_room("rotation_over");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "rotation_over",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "pass",
            "rotation": 360
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "rotation >= 360 should produce invalid_action"
    );
}

// =============================================================
// Room registry: max rooms limit
// =============================================================

#[tokio::test]
async fn room_creation_beyond_max_rooms_rejected() {
    let registry = RoomRegistry::new();
    let def_json = default_definition_json();

    // Fill to capacity
    for i in 0..config::MAX_ROOMS {
        let id = format!("abuse_{i}");
        registry
            .create_room(id, &def_json)
            .await
            .expect("should create room within limit");
    }

    assert_eq!(registry.room_count().await, config::MAX_ROOMS);

    // One more should fail
    let result = registry
        .create_room("overflow".to_string(), &def_json)
        .await;
    assert!(result.is_err(), "creating room beyond MAX_ROOMS must fail");
    let err = result.unwrap_err();
    assert!(
        err.contains("capacity"),
        "error should mention capacity, got: {err}"
    );
}

// =============================================================
// Idle timeout documentation test
// =============================================================
//
// The idle timeout (IDLE_TIMEOUT_SECS = 300) is enforced in
// connection.rs via tokio::time::timeout in the select loop.
// Testing this requires an actual WebSocket connection with
// async wait, which would make this test take 5+ minutes.
// The mechanism is verified by code review:
//   - connection.rs line 294: tokio::time::timeout(idle_timeout, socket.recv())
//   - On Err(_elapsed), sends "idle_timeout" error and breaks
//
// The idle timeout is NOT reset by binary/ping frames (line 383
// comment: "do NOT reset idle timer for binary frames to prevent
// keep-alive abuse").

// =============================================================
// Config constants are reasonable
// =============================================================

#[test]
fn config_constants_are_sane() {
    // These assertions document the expected values and catch
    // accidental changes to security-critical constants.
    assert_eq!(config::MAX_MESSAGE_SIZE, 64 * 1024);
    assert_eq!(config::MAX_MESSAGES_PER_SECOND, 30);
    assert_eq!(config::IDLE_TIMEOUT_SECS, 300);
    assert_eq!(config::MAX_ROOMS, 100);
    assert_eq!(config::MAX_CONNECTIONS_PER_IP, 10);
    assert_eq!(config::MAX_ROOM_ID_LENGTH, 64);
    assert_eq!(config::MAX_DICE_COUNT, 100);
    assert_eq!(config::MAX_DICE_FACES, 1000);
    assert_eq!(config::MAX_DRAW_COUNT, 1000);
    assert_eq!(config::MAX_ZONE_NAME_LENGTH, 128);
    assert_eq!(config::MAX_OUTBOUND_QUEUE, 256);
    assert_eq!(config::MAX_MOVES_PER_GAME, 10_000);
    assert_eq!(config::MAX_ACTION_FIELD_LENGTH, 256);
    assert_eq!(config::MAX_TOTAL_CONNECTIONS, 500);
    assert_eq!(config::MAX_EVENTS_PER_GAME, 100_000);
    assert_eq!(config::MAX_STATE_SIZE, 10 * 1024 * 1024);
}
