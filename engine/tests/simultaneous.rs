//! Tests for simultaneous move collection and resolution.
//!
//! When a phase has `simultaneous: true`, `apply_action` buffers each player's
//! action. When all players have submitted, it resolves by applying each
//! action in player order, then advances the turn.
//!
//! Uses the Rock-Paper-Scissors game definition which declares a simultaneous
//! "choose" phase.

use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::GameSession;
use baize_engine::transition::{apply_action_for_player, EventType};
use baize_engine::GameDefinition;

fn rps_session() -> GameSession {
    let json = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join("games/rock-paper-scissors.json"),
    )
    .expect("rock-paper-scissors.json must exist");
    let def = GameDefinition::from_json(&json).unwrap();
    GameSession::new(def).unwrap()
}

fn place_gesture(gesture: &str) -> Action {
    Action {
        action_type: ActionType::Place,
        authority: None,
        component_id: None,
        component_type: Some(gesture.to_string()),
        from: None,
        to: Some(Position::Structured {
            zone: Some("choice".into()),
            cell: Some("0,0".into()),
            index: None,
        }),
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
        commitment: None,
        custom_data: None,
    }
}

fn tic_tac_toe_session() -> GameSession {
    let def: GameDefinition = serde_json::from_str(
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
    .unwrap();
    GameSession::new(def).unwrap()
}

fn ttt_place(col: u32, row: u32) -> Action {
    Action {
        action_type: ActionType::Place,
        authority: None,
        component_id: None,
        component_type: Some("mark".into()),
        from: None,
        to: Some(Position::Structured {
            zone: Some("board".into()),
            cell: Some(format!("{col},{row}")),
            index: None,
        }),
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
        commitment: None,
        custom_data: None,
    }
}

// ---------------------------------------------------------------------------
// Phase detection
// ---------------------------------------------------------------------------

#[test]
fn rps_has_simultaneous_phase() {
    let session = rps_session();
    assert!(!session.definition.phases.is_empty());
    assert_eq!(session.definition.phases[0].simultaneous, Some(true));
    assert_eq!(session.definition.phases[0].name, "choose");
}

// ---------------------------------------------------------------------------
// Buffering
// ---------------------------------------------------------------------------

#[test]
fn first_submit_buffers_action() {
    let mut session = rps_session();
    let events =
        apply_action_for_player(&mut session, &place_gesture("rock"), Some("P1")).unwrap();

    // Action is buffered, not applied
    assert!(session.runtime.simultaneous_actions.contains_key("P1"));

    // Got an action_submitted event but no turn_advance
    let types: Vec<_> = events.iter().map(|e| e.event_type).collect();
    assert!(types.contains(&EventType::ActionSubmitted));
    assert!(!types.contains(&EventType::TurnAdvance));
}

#[test]
fn second_submit_triggers_resolution() {
    let mut session = rps_session();
    apply_action_for_player(&mut session, &place_gesture("rock"), Some("P1")).unwrap();
    let events =
        apply_action_for_player(&mut session, &place_gesture("scissors"), Some("P2")).unwrap();

    // Buffer cleared after resolution
    assert!(session.runtime.simultaneous_actions.is_empty());

    // Resolution emits place events and turn_advance
    let types: Vec<_> = events.iter().map(|e| e.event_type).collect();
    assert!(types.contains(&EventType::ActionSubmitted));
    assert!(types.contains(&EventType::Place));
    assert!(types.contains(&EventType::TurnAdvance));
}

#[test]
fn duplicate_submit_rejected() {
    let mut session = rps_session();
    apply_action_for_player(&mut session, &place_gesture("rock"), Some("P1")).unwrap();
    let result =
        apply_action_for_player(&mut session, &place_gesture("paper"), Some("P1"));
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("already submitted"),
        "expected 'already submitted' in error: {msg}"
    );
}

#[test]
fn unknown_player_rejected() {
    let mut session = rps_session();
    let result =
        apply_action_for_player(&mut session, &place_gesture("rock"), Some("P3"));
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("unknown player"),
        "expected 'unknown player' in error: {msg}"
    );
}

// ---------------------------------------------------------------------------
// Resolution order
// ---------------------------------------------------------------------------

#[test]
fn p2_submits_first_p1_resolves_first() {
    let mut session = rps_session();
    // P2 submits first
    apply_action_for_player(&mut session, &place_gesture("scissors"), Some("P2")).unwrap();
    let events =
        apply_action_for_player(&mut session, &place_gesture("rock"), Some("P1")).unwrap();

    // Place events should be in player order (P1 first)
    let place_events: Vec<_> = events
        .iter()
        .filter(|e| e.event_type == EventType::Place)
        .collect();
    assert_eq!(place_events.len(), 2);
    assert_eq!(place_events[0].player, "P1");
    assert_eq!(place_events[1].player, "P2");
}

// ---------------------------------------------------------------------------
// State hash changes with buffered actions
// ---------------------------------------------------------------------------

#[test]
fn buffer_changes_state_hash() {
    let mut session = rps_session();
    session.runtime.status = baize_engine::state::GameStatus::InProgress;
    let h1 = session.compute_state_hash();

    session.runtime.simultaneous_actions.insert(
        "P1".into(),
        serde_json::json!({"action_type": "place"}),
    );
    let h2 = session.compute_state_hash();
    assert_ne!(h1, h2);
}

// ---------------------------------------------------------------------------
// Non-simultaneous games unaffected
// ---------------------------------------------------------------------------

#[test]
fn tic_tac_toe_unchanged() {
    let mut session = tic_tac_toe_session();
    let events = apply_action_for_player(&mut session, &ttt_place(1, 1), None).unwrap();

    let types: Vec<_> = events.iter().map(|e| e.event_type).collect();
    assert!(types.contains(&EventType::Place));
    assert!(types.contains(&EventType::TurnAdvance));
    // No buffering happened
    assert!(session.runtime.simultaneous_actions.is_empty());
}

// ---------------------------------------------------------------------------
// apply_action (no player) still works for non-simultaneous
// ---------------------------------------------------------------------------

#[test]
fn apply_action_backward_compatible() {
    use baize_engine::transition::apply_action;

    let mut session = tic_tac_toe_session();
    let events = apply_action(&mut session, &ttt_place(0, 0)).unwrap();
    let types: Vec<_> = events.iter().map(|e| e.event_type).collect();
    assert!(types.contains(&EventType::Place));
    assert!(types.contains(&EventType::TurnAdvance));
}
