//! Tests for hostile/malformed game definitions.
//!
//! Verifies the engine rejects or handles gracefully:
//! - Empty JSON, wrong types, binary garbage
//! - Absurd grid dimensions, zero/negative dimensions
//! - Too many players (>100), too many components (>10000)
//! - Very long strings, missing required fields
//! - Null in required positions

use baize_engine::definition::GameDefinition;
use baize_engine::error::BaizeError;

fn minimal_json() -> serde_json::Value {
    serde_json::json!({
        "game": {
            "name": "Test",
            "players": ["A", "B"],
            "information": "perfect"
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public"
            }
        },
        "components": {
            "piece": {
                "owner": "per_player",
                "count": "unlimited"
            }
        },
        "turn_order": {
            "type": "alternating",
            "players": ["A", "B"]
        },
        "end_conditions": [
            { "result": "draw", "condition": "board_is_full" }
        ],
        "authority": {
            "server_only": [],
            "client_verifiable": ["all"]
        }
    })
}

// -----------------------------------------------------------------------
// Empty and structurally wrong JSON
// -----------------------------------------------------------------------

#[test]
fn reject_empty_json_object() {
    let result = GameDefinition::from_json("{}");
    assert!(result.is_err());
}

#[test]
fn reject_empty_string() {
    let result = GameDefinition::from_json("");
    assert!(result.is_err());
}

#[test]
fn reject_json_array() {
    let result = GameDefinition::from_json("[1, 2, 3]");
    assert!(result.is_err());
}

#[test]
fn reject_json_number() {
    let result = GameDefinition::from_json("42");
    assert!(result.is_err());
}

#[test]
fn reject_json_string() {
    let result = GameDefinition::from_json(r#""hello""#);
    assert!(result.is_err());
}

#[test]
fn reject_json_null() {
    let result = GameDefinition::from_json("null");
    assert!(result.is_err());
}

#[test]
fn reject_json_true() {
    let result = GameDefinition::from_json("true");
    assert!(result.is_err());
}

// -----------------------------------------------------------------------
// Binary garbage
// -----------------------------------------------------------------------

#[test]
fn reject_binary_garbage_ascii() {
    let result = GameDefinition::from_json("\x00\x01\x02\x03 garbage !@#$%^");
    assert!(result.is_err());
}

#[test]
fn reject_binary_garbage_from_bytes() {
    let garbage: &[u8] = &[0xFE, 0xFF, 0x00, 0x80, 0x90, 0xAB];
    let lossy = String::from_utf8_lossy(garbage);
    let result = GameDefinition::from_json(&lossy);
    assert!(result.is_err());
}

// -----------------------------------------------------------------------
// Wrong types for known fields
// -----------------------------------------------------------------------

#[test]
fn reject_players_as_number() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(42);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_players_as_string() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!("two");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_zones_as_array() {
    let mut v = minimal_json();
    v["zones"] = serde_json::json!([1, 2, 3]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_end_conditions_as_string() {
    let mut v = minimal_json();
    v["end_conditions"] = serde_json::json!("none");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_dimensions_as_string() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!("big");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_turn_order_type_as_number() {
    let mut v = minimal_json();
    v["turn_order"]["type"] = serde_json::json!(999);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

// -----------------------------------------------------------------------
// Missing required fields
// -----------------------------------------------------------------------

#[test]
fn reject_missing_game_field() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("game");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_missing_zones_field() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("zones");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_missing_end_conditions() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("end_conditions");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_missing_authority() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("authority");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_missing_turn_order() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("turn_order");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_missing_components() {
    let mut v = minimal_json();
    v.as_object_mut().unwrap().remove("components");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_empty_end_conditions() {
    let mut v = minimal_json();
    v["end_conditions"] = serde_json::json!([]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

// -----------------------------------------------------------------------
// Null in required positions
// -----------------------------------------------------------------------

#[test]
fn reject_null_game() {
    let mut v = minimal_json();
    v["game"] = serde_json::Value::Null;
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_null_game_name() {
    let mut v = minimal_json();
    v["game"]["name"] = serde_json::Value::Null;
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_null_players() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::Value::Null;
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_null_zones() {
    let mut v = minimal_json();
    v["zones"] = serde_json::Value::Null;
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

// -----------------------------------------------------------------------
// Absurd grid dimensions
// -----------------------------------------------------------------------

#[test]
fn reject_dimension_zero() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([0, 3]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_both_dimensions_zero() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([0, 0]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_dimension_1001() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1001, 1]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_dimension_million() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1000000, 1000000]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_dimension_u32_max() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([4294967295u64, 1]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn accept_dimension_at_limit() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1000, 1000]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_ok());
}

#[test]
fn accept_dimension_1x1() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1, 1]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_ok());
}

// -----------------------------------------------------------------------
// Player count limits
// -----------------------------------------------------------------------

#[test]
fn reject_empty_player_list() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!([]);
    v["turn_order"]["players"] = serde_json::json!([]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_101_named_players() {
    let names: Vec<String> = (0..101).map(|i| format!("p{i}")).collect();
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(&names);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_player_range_zero_min() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!({"min": 0, "max": 4});
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

#[test]
fn reject_player_range_inverted() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!({"min": 10, "max": 2});
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
}

// -----------------------------------------------------------------------
// Component count limits
// -----------------------------------------------------------------------

#[test]
fn reject_component_count_exceeds_10000() {
    let mut v = minimal_json();
    // Single component type with count 10001
    v["components"] = serde_json::json!({
        "stone": { "count": 10001 }
    });
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_per_player_component_overflow() {
    // 100 players x 101 each = 10100 > 10000
    let names: Vec<String> = (0..100).map(|i| format!("p{i}")).collect();
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(&names);
    v["turn_order"]["players"] = serde_json::json!(&names);
    v["components"] = serde_json::json!({
        "piece": { "owner": "per_player", "count": 101 }
    });
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

// -----------------------------------------------------------------------
// Long strings
// -----------------------------------------------------------------------

#[test]
fn reject_empty_game_name() {
    let mut v = minimal_json();
    v["game"]["name"] = serde_json::json!("");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_whitespace_only_game_name() {
    let mut v = minimal_json();
    v["game"]["name"] = serde_json::json!("   ");
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn accept_very_long_game_name() {
    // A 1MB name is unusual but not structurally invalid after parsing
    let long_name = "A".repeat(1_000_000);
    let mut v = minimal_json();
    v["game"]["name"] = serde_json::json!(long_name);
    let result = GameDefinition::from_value(v);
    assert!(result.is_ok());
}

#[test]
fn reject_empty_player_name() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(["", "B"]);
    v["turn_order"]["players"] = serde_json::json!(["", "B"]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_duplicate_player_names() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(["Alice", "Alice"]);
    v["turn_order"]["players"] = serde_json::json!(["Alice", "Alice"]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

// -----------------------------------------------------------------------
// Grid zone without dimensions
// -----------------------------------------------------------------------

#[test]
fn reject_grid_zone_without_dimensions() {
    let mut v = minimal_json();
    v["zones"]["board"] = serde_json::json!({
        "zone_type": "grid",
        "visibility": "public"
    });
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn accept_dynamic_grid_without_dimensions() {
    let mut v = minimal_json();
    v["zones"]["board"] = serde_json::json!({
        "zone_type": "grid",
        "visibility": "public",
        "dynamic": true
    });
    let result = GameDefinition::from_value(v);
    assert!(result.is_ok());
}

// -----------------------------------------------------------------------
// Turn order references
// -----------------------------------------------------------------------

#[test]
fn reject_turn_order_unknown_player() {
    let mut v = minimal_json();
    v["turn_order"]["players"] = serde_json::json!(["A", "Z"]);
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

// -----------------------------------------------------------------------
// Movement target zone references
// -----------------------------------------------------------------------

#[test]
fn reject_movement_referencing_unknown_zone() {
    let mut v = minimal_json();
    v["components"]["piece"] = serde_json::json!({
        "movement": [
            { "primitive": "move_to", "target_zone": "nonexistent" }
        ]
    });
    let result = GameDefinition::from_value(v);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}
