//! Tests for per-session resource budgets: component limits, event limits, state size.

use baize_engine::definition::GameDefinition;
use baize_engine::error::BaizeError;
use baize_engine::runtime::{
    ComponentData, ComponentId, GameSession, MAX_COMPONENTS_PER_GAME, MAX_EVENTS_PER_GAME,
};
use baize_engine::transition::apply_action;

fn tic_tac_toe_json() -> String {
    serde_json::json!({
        "game": {
            "name": "Tic-Tac-Toe",
            "players": ["X", "O"],
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
            "players": ["X", "O"]
        },
        "end_conditions": [{"result": "draw", "condition": "board_is_full"}],
        "authority": {
            "server_only": [],
            "client_verifiable": ["all"]
        }
    })
    .to_string()
}

fn make_component(name: &str) -> ComponentData {
    ComponentData {
        id: ComponentId(0),
        string_id: name.into(),
        component_type: "piece".into(),
        owner: None,
        facing: None,
        state: None,
        properties: indexmap::IndexMap::new(),
        span_cells: Vec::new(),
        orientation: None,
    }
}

fn place_action(coord: &str) -> baize_engine::action::Action {
    serde_json::from_value(serde_json::json!({
        "action_type": "place",
        "to": coord,
        "component_type": "piece"
    }))
    .expect("valid action JSON")
}

// ---------------------------------------------------------------------------
// Component limits
// ---------------------------------------------------------------------------

#[test]
fn component_insert_within_limit() {
    let def = GameDefinition::from_json(&tic_tac_toe_json()).unwrap();
    let mut session = GameSession::new(def).unwrap();
    for i in 0..100 {
        let result = session
            .runtime
            .components
            .insert(make_component(&format!("test-{i}")));
        assert!(result.is_ok(), "insert {i} should succeed");
    }
}

#[test]
fn component_insert_at_limit_fails() {
    let def = GameDefinition::from_json(&tic_tac_toe_json()).unwrap();
    let mut session = GameSession::new(def).unwrap();

    for i in 0..MAX_COMPONENTS_PER_GAME {
        session
            .runtime
            .components
            .insert(make_component(&format!("fill-{i}")))
            .unwrap();
    }

    let result = session
        .runtime
        .components
        .insert(make_component("overflow"));
    assert!(matches!(result, Err(BaizeError::ResourceBudget(_))));
}

#[test]
fn place_action_fails_at_component_limit() {
    let def = GameDefinition::from_json(&tic_tac_toe_json()).unwrap();
    let mut session = GameSession::new(def).unwrap();

    for i in 0..MAX_COMPONENTS_PER_GAME {
        session
            .runtime
            .components
            .insert(make_component(&format!("pre-{i}")))
            .unwrap();
    }

    let action = place_action("0,0");
    let result = apply_action(&mut session, &action);
    assert!(matches!(result, Err(BaizeError::ResourceBudget(_))));
}

// ---------------------------------------------------------------------------
// Event count limits
// ---------------------------------------------------------------------------

#[test]
fn event_count_tracked() {
    let def = GameDefinition::from_json(&tic_tac_toe_json()).unwrap();
    let mut session = GameSession::new(def).unwrap();
    assert_eq!(session.runtime.event_count, 0);

    let action = place_action("0,0");
    let events = apply_action(&mut session, &action).unwrap();
    assert!(!events.is_empty());
    assert_eq!(session.runtime.event_count, events.len() as u64);
}

#[test]
fn event_count_accumulates() {
    let def = GameDefinition::from_json(&tic_tac_toe_json()).unwrap();
    let mut session = GameSession::new(def).unwrap();

    let coords = ["0,0", "1,0", "0,1", "1,1"];
    let mut total: u64 = 0;
    for coord in coords {
        let action = place_action(coord);
        let events = apply_action(&mut session, &action).unwrap();
        total += events.len() as u64;
    }
    assert_eq!(session.runtime.event_count, total);
}

// ---------------------------------------------------------------------------
// Constants are reasonable for reference games
// ---------------------------------------------------------------------------

#[test]
fn limits_are_generous() {
    assert!(MAX_COMPONENTS_PER_GAME >= 10_000);
    assert!(MAX_EVENTS_PER_GAME >= 100_000);
}

#[test]
fn all_reference_games_within_budgets() {
    let games_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("games");
    if !games_dir.exists() {
        return;
    }
    for entry in std::fs::read_dir(&games_dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.extension().is_some_and(|e| e == "json") {
            let json = std::fs::read_to_string(&path).unwrap();
            let def = GameDefinition::from_json(&json);
            assert!(
                def.is_ok(),
                "Reference game {:?} failed: {:?}",
                path.file_name().unwrap(),
                def.err()
            );
            let session = GameSession::new(def.unwrap());
            assert!(
                session.is_ok(),
                "Reference game {:?} session failed: {:?}",
                path.file_name().unwrap(),
                session.err()
            );
        }
    }
}
