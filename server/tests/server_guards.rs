use std::collections::HashMap;

use baize_engine::GameDefinition;
use baize_engine::GameSession;
use baize_server::protocol::{handle_client_message, HandleResult};
use baize_server::room::{self, Room};
use baize_server::vault::{self, Vault};

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

// =============================================================
// Vault guard tests
// =============================================================

#[test]
fn vault_draw_from_nonexistent_deck_returns_error() {
    let mut v = Vault::with_seed(100);
    let result = vault::draw_cards(&mut v, "no_such_deck", 5);
    assert!(result.is_err(), "draw from nonexistent deck must return Err");
    let err = result.unwrap_err();
    assert!(
        err.contains("no_such_deck"),
        "error message must mention the deck name, got: {err}"
    );
}

#[test]
fn vault_shuffle_nonexistent_deck_returns_error() {
    let mut v = Vault::with_seed(101);
    let result = vault::shuffle_zone(&mut v, "phantom_deck");
    assert!(result.is_err(), "shuffle nonexistent deck must return Err");
    let err = result.unwrap_err();
    assert!(
        err.contains("phantom_deck"),
        "error message must mention the deck name, got: {err}"
    );
}

#[test]
fn vault_draw_more_than_available_returns_partial() {
    let mut v = Vault::with_seed(102);
    let ids: Vec<String> = vec!["a".into(), "b".into()];
    v.register_deck("tiny", ids);

    // Request 10 from a 2-card deck
    let drawn = vault::draw_cards(&mut v, "tiny", 10).unwrap();
    assert_eq!(
        drawn.len(),
        2,
        "drawing 10 from a 2-card deck must return only 2"
    );

    // Deck should now be empty
    let drawn_again = vault::draw_cards(&mut v, "tiny", 1).unwrap();
    assert!(
        drawn_again.is_empty(),
        "empty deck must return empty vec, got: {drawn_again:?}"
    );
}

#[test]
fn vault_draw_from_empty_deck_returns_empty() {
    let mut v = Vault::with_seed(103);
    v.register_deck("empty_deck", Vec::new());
    let drawn = vault::draw_cards(&mut v, "empty_deck", 5).unwrap();
    assert!(
        drawn.is_empty(),
        "drawing from empty registered deck must return empty vec"
    );
}

#[test]
fn vault_deck_exists_check() {
    let mut v = Vault::with_seed(104);
    assert!(!v.deck_exists("missing"), "unregistered deck must not exist");

    v.register_deck("present", vec!["card_1".into()]);
    assert!(v.deck_exists("present"), "registered deck must exist");
}

#[test]
fn vault_deck_size_tracks_draws() {
    let mut v = Vault::with_seed(105);
    let ids: Vec<String> = (0..5).map(|i| format!("c{i}")).collect();
    v.register_deck("hand", ids);

    assert_eq!(v.deck_size("hand"), 5);
    vault::draw_cards(&mut v, "hand", 2).unwrap();
    assert_eq!(v.deck_size("hand"), 3);
    vault::draw_cards(&mut v, "hand", 3).unwrap();
    assert_eq!(v.deck_size("hand"), 0);
}

#[test]
fn vault_shuffle_preserves_deck_size() {
    let mut v = Vault::with_seed(106);
    let ids: Vec<String> = (0..20).map(|i| format!("card_{i}")).collect();
    v.register_deck("deck", ids);

    let size_before = v.deck_size("deck");
    vault::shuffle_zone(&mut v, "deck").unwrap();
    assert_eq!(
        v.deck_size("deck"),
        size_before,
        "shuffle must not change deck size"
    );
}

#[test]
#[should_panic(expected = "dice faces must be >= 1")]
fn vault_roll_zero_faces_panics() {
    let mut v = Vault::with_seed(107);
    vault::roll_dice(&mut v, 1, 0);
}

#[test]
#[should_panic(expected = "dice count must be >= 1")]
fn vault_roll_zero_count_panics() {
    let mut v = Vault::with_seed(108);
    vault::roll_dice(&mut v, 0, 6);
}

// =============================================================
// Room guard tests
// =============================================================

#[test]
fn room_has_capacity_at_limit() {
    let mut room = make_test_room("cap_test");
    assert_eq!(room.max_players, 2);

    // Room starts empty, should have capacity
    assert!(room::room_has_capacity(&room));

    // Add player 1
    let _rx1 = room::join_room(&mut room, "white".to_string());
    assert!(room::room_has_capacity(&room), "1 of 2 seats used");

    // Add player 2 — at capacity
    let _rx2 = room::join_room(&mut room, "black".to_string());
    assert!(!room::room_has_capacity(&room), "2 of 2 seats used");
}

#[test]
fn room_player_count_after_remove() {
    let mut room = make_test_room("remove_test");
    let _rx1 = room::join_room(&mut room, "white".to_string());
    let _rx2 = room::join_room(&mut room, "black".to_string());
    assert_eq!(room.players.len(), 2);

    room.players.remove("white");
    assert_eq!(room.players.len(), 1);
    assert!(room::room_has_capacity(&room), "should have capacity after removal");
}

#[test]
fn room_token_registration_and_lookup() {
    let mut room = make_test_room("token_test");
    let token = room::register_token(&mut room, "white");

    // Token should be 32 hex chars (128-bit)
    assert_eq!(token.len(), 32, "token must be 32 hex chars");
    assert!(
        token.chars().all(|c| c.is_ascii_hexdigit()),
        "token must be hex: {token}"
    );

    // Lookup by token
    let seat = room::seat_for_token(&room, &token);
    assert_eq!(seat.as_deref(), Some("white"));

    // Unknown token returns None
    assert!(room::seat_for_token(&room, "bogus").is_none());
}

// =============================================================
// Protocol guard tests — turn enforcement
// =============================================================

#[test]
fn protocol_rejects_move_when_not_your_turn() {
    let mut room = make_test_room("turn_test");
    let mut seq = 0u64;

    // Turn order is ["white", "black"], starting with "white".
    // "black" tries to move — should be rejected.
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "turn_test",
        "player": "black",
        "sequence": 0,
        "action": {
            "action_type": "pass"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "black", &msg, &mut seq);
    match &result {
        HandleResult::Reply(msgs) => {
            assert_eq!(msgs.len(), 1);
            let json = serde_json::to_value(&msgs[0]).expect("should serialize");
            assert_eq!(
                json.get("message_type").and_then(|v| v.as_str()),
                Some("move_rejected"),
            );
            let reason = json.get("reason").and_then(|v| v.as_str()).unwrap_or("");
            assert!(
                reason.contains("not your turn"),
                "reason should mention turn, got: {reason}"
            );
        }
        _ => panic!("expected Reply(MoveRejected), got different result"),
    }
}

#[test]
fn protocol_draw_from_nonexistent_deck_returns_error_result() {
    let mut room = make_test_room("draw_guard");
    let mut seq = 0u64;

    // "white" is current player. Request a draw from a deck that does not exist.
    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "draw_guard",
        "player": "white",
        "random_request": {
            "random_type": "draw",
            "draw_count": 5,
            "draw_from": "board"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    // The protocol handler returns a RandomResult with an error field
    // (not a protocol Error) when a deck does not exist.
    match &result {
        HandleResult::Broadcast(msgs) => {
            assert_eq!(msgs.len(), 1);
            let json = serde_json::to_value(&msgs[0]).expect("should serialize");
            assert_eq!(
                json.get("message_type").and_then(|v| v.as_str()),
                Some("random_result"),
            );
            let rv = json.get("random_value").expect("must have random_value");
            assert!(
                rv.get("error").is_some(),
                "random_value must contain error for nonexistent deck, got: {rv}"
            );
        }
        HandleResult::Error(e) => {
            // Also acceptable — protocol-level rejection
            let v: serde_json::Value = serde_json::from_str(e).expect("should be JSON");
            let code = v.get("error_code").and_then(|c| c.as_str()).unwrap_or("");
            assert!(
                !code.is_empty(),
                "error should have an error_code, got: {e}"
            );
        }
        _ => panic!("expected Broadcast or Error for nonexistent deck draw"),
    }
}

#[test]
fn protocol_shuffle_nonexistent_deck_returns_error_result() {
    let mut room = make_test_room("shuffle_guard");
    let mut seq = 0u64;

    let msg = serde_json::json!({
        "message_type": "request_random",
        "game_id": "shuffle_guard",
        "player": "white",
        "random_request": {
            "random_type": "shuffle",
            "shuffle_zone": "board"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    match &result {
        HandleResult::Broadcast(msgs) => {
            assert_eq!(msgs.len(), 1);
            let json = serde_json::to_value(&msgs[0]).expect("should serialize");
            let rv = json.get("random_value").expect("must have random_value");
            assert!(
                rv.get("error").is_some(),
                "random_value must contain error for nonexistent shuffle zone, got: {rv}"
            );
        }
        HandleResult::Error(e) => {
            let v: serde_json::Value = serde_json::from_str(e).expect("should be JSON");
            let code = v.get("error_code").and_then(|c| c.as_str()).unwrap_or("");
            assert!(!code.is_empty(), "error should have an error_code");
        }
        _ => panic!("expected Broadcast or Error for nonexistent shuffle zone"),
    }
}

#[test]
fn protocol_malformed_json_rejected() {
    let mut room = make_test_room("malformed_test");
    let mut seq = 0u64;

    let result = handle_client_message(&mut room, "white", "not json at all", &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_message"),
        "malformed JSON must produce invalid_message error"
    );
}

#[test]
fn protocol_invalid_action_zone_rejected() {
    let mut room = make_test_room("zone_test");
    let mut seq = 0u64;

    // Reference a zone that does not exist in the definition
    let msg = serde_json::json!({
        "message_type": "submit_move",
        "game_id": "zone_test",
        "player": "white",
        "sequence": 0,
        "action": {
            "action_type": "move_piece",
            "zone": "nonexistent_zone"
        }
    })
    .to_string();

    let result = handle_client_message(&mut room, "white", &msg, &mut seq);
    let code = extract_error_code(&result);
    assert_eq!(
        code.as_deref(),
        Some("invalid_action"),
        "unknown zone must produce invalid_action error"
    );
}

// =============================================================
// Room registry capacity test
// =============================================================

#[tokio::test]
async fn room_registry_respects_room_limit() {
    use baize_server::room::RoomRegistry;

    let registry = RoomRegistry::new();
    let def_json = default_definition_json();

    // Fill to capacity
    for i in 0..baize_server::config::MAX_ROOMS {
        let id = format!("room_{i}");
        registry
            .create_room(id, &def_json)
            .await
            .expect("should create room within limit");
    }

    // One more should fail
    let result = registry
        .create_room("overflow".to_string(), &def_json)
        .await;
    assert!(
        result.is_err(),
        "creating room beyond MAX_ROOMS must fail"
    );
    let err = result.unwrap_err();
    assert!(
        err.contains("capacity"),
        "error should mention capacity, got: {err}"
    );
}
