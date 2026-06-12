//! Tests for computational DoS prevention: player/component/grid limits.

use baize_engine::definition::GameDefinition;
use baize_engine::error::BaizeError;

fn minimal_json() -> serde_json::Value {
    serde_json::json!({
        "game": {
            "name": "Test Game",
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
            {
                "result": "draw",
                "condition": "board_is_full"
            }
        ],
        "authority": {
            "server_only": [],
            "client_verifiable": ["all"]
        }
    })
}

fn parse_value(v: serde_json::Value) -> Result<GameDefinition, BaizeError> {
    GameDefinition::from_value(v)
}

// --- Player count limits ---

#[test]
fn accept_100_players() {
    let names: Vec<String> = (0..100).map(|i| format!("p{i}")).collect();
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(&names);
    v["turn_order"]["players"] = serde_json::json!(&names);
    parse_value(v).expect("100 player game should parse");
}

#[test]
fn reject_101_players() {
    let names: Vec<String> = (0..101).map(|i| format!("p{i}")).collect();
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!(&names);
    let err = parse_value(v).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_player_range_101_max() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!({"min": 2, "max": 101});
    let err = parse_value(v).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn accept_player_range_100_max() {
    let mut v = minimal_json();
    v["game"]["players"] = serde_json::json!({"min": 2, "max": 100});
    parse_value(v).expect("max 100 player range should parse");
}

// --- Component count limits ---

#[test]
fn reject_too_many_components() {
    let mut v = minimal_json();
    let mut components = serde_json::Map::new();
    for i in 0..10001 {
        components.insert(
            format!("c{i}"),
            serde_json::json!({"count": 1}),
        );
    }
    v["components"] = serde_json::Value::Object(components);
    let err = parse_value(v).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn accept_many_components_within_limit() {
    let mut v = minimal_json();
    let mut components = serde_json::Map::new();
    for i in 0..100 {
        components.insert(
            format!("c{i}"),
            serde_json::json!({"count": 1}),
        );
    }
    v["components"] = serde_json::Value::Object(components);
    parse_value(v).expect("100 components should parse");
}

// --- Grid dimension limits ---

#[test]
fn accept_max_grid_dimension() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1000, 1000]);
    parse_value(v).expect("1000x1000 grid should parse");
}

#[test]
fn reject_grid_dimension_1001() {
    let mut v = minimal_json();
    v["zones"]["board"]["dimensions"] = serde_json::json!([1001, 1]);
    let err = parse_value(v).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

// --- All reference games still work ---

#[test]
fn all_reference_games_within_limits() {
    let games_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("games");
    if !games_dir.exists() {
        return; // Skip if games dir not found
    }
    for entry in std::fs::read_dir(&games_dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.extension().map_or(false, |e| e == "json") {
            let json = std::fs::read_to_string(&path).unwrap();
            let result = GameDefinition::from_json(&json);
            assert!(
                result.is_ok(),
                "Reference game {:?} failed validation: {:?}",
                path.file_name().unwrap(),
                result.err()
            );
        }
    }
}
