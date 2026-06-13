//! Tests for the trigger / claim-window system.
//!
//! When a game action matches a trigger's `on_action` field, the engine opens
//! a "claim window" — a mini-simultaneous collection phase where eligible
//! players submit claims. When all respond, the highest-priority non-default
//! claim wins and that player becomes active. If all pass, normal turn order
//! resumes.
//!
//! Uses an inline 3-player game definition with a trigger on "place" actions.

use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::GameSession;
use baize_engine::transition::{apply_action_for_player, apply_claim, EventType};
use baize_engine::GameDefinition;

// ---------------------------------------------------------------------------
// Game definition JSON — 3-player game with a trigger on "place"
// ---------------------------------------------------------------------------

const TRIGGER_GAME_JSON: &str = r#"{
    "game": { "name": "Trigger Test Game", "players": ["Alice", "Bob", "Carol"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "round_robin", "players": ["Alice", "Bob", "Carol"], "actions_per_turn": 1 },
    "end_conditions": [
        { "result": "draw", "condition": "board_is_full" }
    ],
    "triggers": {
        "on_place": {
            "on_action": "place",
            "claim_window": {
                "eligible": "all_except_current",
                "actions": ["claim", "challenge"],
                "priority": ["challenge", "claim"],
                "timeout": 10,
                "default": "pass"
            }
        }
    },
    "authority": { "server_only": [], "client_verifiable": ["place"] }
}"#;

// Game with "next_in_order" eligible rule
const NEXT_IN_ORDER_GAME_JSON: &str = r#"{
    "game": { "name": "Next-In-Order Trigger", "players": ["Alice", "Bob", "Carol"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "round_robin", "players": ["Alice", "Bob", "Carol"], "actions_per_turn": 1 },
    "end_conditions": [
        { "result": "draw", "condition": "board_is_full" }
    ],
    "triggers": {
        "on_place": {
            "on_action": "place",
            "claim_window": {
                "eligible": "next_in_order",
                "actions": ["claim"],
                "priority": ["claim"],
                "timeout": 5,
                "default": "pass"
            }
        }
    },
    "authority": { "server_only": [], "client_verifiable": ["place"] }
}"#;

fn trigger_session() -> GameSession {
    let def = GameDefinition::from_json(TRIGGER_GAME_JSON).unwrap();
    GameSession::new(def).unwrap()
}

fn next_in_order_session() -> GameSession {
    let def = GameDefinition::from_json(NEXT_IN_ORDER_GAME_JSON).unwrap();
    GameSession::new(def).unwrap()
}

fn place_mark(col: u32, row: u32) -> Action {
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
// 1. Trigger fires on matching action
// ---------------------------------------------------------------------------

#[test]
fn test_trigger_fires_on_matching_action() {
    let mut session = trigger_session();
    assert_eq!(session.current_player(), Some("Alice"));

    let events =
        apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    // Must contain trigger_activated event with detail "on_place"
    let trigger_event = events
        .iter()
        .find(|e| e.event_type == EventType::TriggerActivated);
    assert!(
        trigger_event.is_some(),
        "expected trigger_activated event after place action"
    );
    let trigger_event = trigger_event.unwrap();
    assert_eq!(trigger_event.player, "Alice");
    assert_eq!(trigger_event.detail.as_deref(), Some("on_place"));

    // Claim window must be active
    assert!(
        session.runtime.claim_window.is_some(),
        "claim_window should be Some after trigger fires"
    );

    let cw = session.runtime.claim_window.as_ref().unwrap();
    assert_eq!(cw.trigger_name, "on_place");
    assert_eq!(cw.triggering_player, "Alice");
    assert_eq!(cw.eligible_players, vec!["Bob", "Carol"]);
    assert!(cw.submitted_claims.is_empty());

    // Turn should NOT have advanced
    let has_turn_advance = events
        .iter()
        .any(|e| e.event_type == EventType::TurnAdvance);
    assert!(
        !has_turn_advance,
        "turn should not advance when claim window opens"
    );
}

// ---------------------------------------------------------------------------
// 2. Claim window blocks normal actions
// ---------------------------------------------------------------------------

#[test]
fn test_claim_window_blocks_normal_actions() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    // Claim window is now active
    assert!(session.runtime.claim_window.is_some());

    // Trying to place another mark should fail
    let result = apply_action_for_player(&mut session, &place_mark(0, 0), Some("Bob"));
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("claim window"),
        "expected error about claim window, got: {msg}"
    );
}

// ---------------------------------------------------------------------------
// 3. Valid claim submission
// ---------------------------------------------------------------------------

#[test]
fn test_claim_submit_valid() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    let events = apply_claim(&mut session, "Bob", "claim").unwrap();

    // Must contain claim_submitted event
    let submitted = events
        .iter()
        .find(|e| e.event_type == EventType::ClaimSubmitted);
    assert!(
        submitted.is_some(),
        "expected claim_submitted event"
    );
    let submitted = submitted.unwrap();
    assert_eq!(submitted.player, "Bob");
    assert_eq!(submitted.detail.as_deref(), Some("claim"));

    // Window still active (Carol hasn't responded yet)
    assert!(session.runtime.claim_window.is_some());
    let cw = session.runtime.claim_window.as_ref().unwrap();
    assert_eq!(cw.submitted_claims.get("Bob").map(|s| s.as_str()), Some("claim"));
}

// ---------------------------------------------------------------------------
// 4. Non-eligible player rejected
// ---------------------------------------------------------------------------

#[test]
fn test_claim_submit_non_eligible_rejected() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    // Alice triggered the action, so she's not eligible
    let result = apply_claim(&mut session, "Alice", "claim");
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("not eligible"),
        "expected 'not eligible' in error, got: {msg}"
    );
}

// ---------------------------------------------------------------------------
// 5. Duplicate claim rejected
// ---------------------------------------------------------------------------

#[test]
fn test_claim_submit_duplicate_rejected() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    apply_claim(&mut session, "Bob", "pass").unwrap();
    let result = apply_claim(&mut session, "Bob", "claim");
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("already submitted"),
        "expected 'already submitted' in error, got: {msg}"
    );
}

// ---------------------------------------------------------------------------
// 6. Invalid claim action rejected
// ---------------------------------------------------------------------------

#[test]
fn test_claim_submit_invalid_action_rejected() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    // "steal" is not in the allowed actions ["claim", "challenge"] or default "pass"
    let result = apply_claim(&mut session, "Bob", "steal");
    assert!(result.is_err());
    let msg = result.unwrap_err().to_string();
    assert!(
        msg.contains("invalid claim"),
        "expected 'invalid claim' in error, got: {msg}"
    );
}

// ---------------------------------------------------------------------------
// 7. All pass advances turn normally
// ---------------------------------------------------------------------------

#[test]
fn test_all_pass_advances_turn() {
    let mut session = trigger_session();
    assert_eq!(session.current_player(), Some("Alice"));

    apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();
    apply_claim(&mut session, "Bob", "pass").unwrap();
    let events = apply_claim(&mut session, "Carol", "pass").unwrap();

    // Claim window should be cleared
    assert!(session.runtime.claim_window.is_none());

    // claim_resolved with "all_passed"
    let resolved = events
        .iter()
        .find(|e| e.event_type == EventType::ClaimResolved);
    assert!(resolved.is_some(), "expected claim_resolved event");
    let resolved = resolved.unwrap();
    assert_eq!(resolved.detail.as_deref(), Some("all_passed"));

    // Turn should advance to Bob (next after Alice in round_robin)
    let turn_advance = events
        .iter()
        .find(|e| e.event_type == EventType::TurnAdvance);
    assert!(turn_advance.is_some(), "expected turn_advance event");
    assert_eq!(turn_advance.unwrap().player, "Bob");
    assert_eq!(session.current_player(), Some("Bob"));
}

// ---------------------------------------------------------------------------
// 8. Priority resolution — challenge beats claim
// ---------------------------------------------------------------------------

#[test]
fn test_priority_resolution() {
    let mut session = trigger_session();
    apply_action_for_player(&mut session, &place_mark(0, 0), Some("Alice")).unwrap();

    // Bob claims, Carol challenges
    apply_claim(&mut session, "Bob", "claim").unwrap();
    let events = apply_claim(&mut session, "Carol", "challenge").unwrap();

    // claim_resolved should show Carol winning with "challenge"
    let resolved = events
        .iter()
        .find(|e| e.event_type == EventType::ClaimResolved);
    assert!(resolved.is_some(), "expected claim_resolved event");
    let resolved = resolved.unwrap();
    assert_eq!(resolved.player, "Carol");
    assert_eq!(resolved.detail.as_deref(), Some("challenge"));
}

// ---------------------------------------------------------------------------
// 9. Winner becomes active player
// ---------------------------------------------------------------------------

#[test]
fn test_winner_becomes_active_player() {
    let mut session = trigger_session();
    assert_eq!(session.current_player(), Some("Alice"));

    apply_action_for_player(&mut session, &place_mark(0, 0), Some("Alice")).unwrap();

    // Carol challenges, Bob passes
    apply_claim(&mut session, "Bob", "pass").unwrap();
    let events = apply_claim(&mut session, "Carol", "challenge").unwrap();

    // Claim window cleared
    assert!(session.runtime.claim_window.is_none());

    // Carol should now be the active player
    assert_eq!(
        session.current_player(),
        Some("Carol"),
        "Carol should be the active player after winning the challenge"
    );

    // turn_advance event should name Carol
    let turn_advance = events
        .iter()
        .find(|e| e.event_type == EventType::TurnAdvance);
    assert!(turn_advance.is_some());
    assert_eq!(turn_advance.unwrap().player, "Carol");
}

// ---------------------------------------------------------------------------
// 10. No trigger without match
// ---------------------------------------------------------------------------

#[test]
fn test_no_trigger_without_match() {
    // Use a game definition without triggers
    let no_trigger_json = r#"{
        "game": { "name": "No Triggers", "players": ["X", "O"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
        },
        "components": {
            "mark": { "owner": "per_player", "count": "unlimited" }
        },
        "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
        "end_conditions": [
            { "result": "draw", "condition": "board_is_full" }
        ],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#;

    let def = GameDefinition::from_json(no_trigger_json).unwrap();
    let mut session = GameSession::new(def).unwrap();

    let events =
        apply_action_for_player(&mut session, &place_mark(1, 1), None).unwrap();

    // No trigger_activated event
    let has_trigger = events
        .iter()
        .any(|e| e.event_type == EventType::TriggerActivated);
    assert!(!has_trigger, "no trigger_activated event expected");

    // No claim window
    assert!(session.runtime.claim_window.is_none());

    // Turn advanced normally
    let has_turn_advance = events
        .iter()
        .any(|e| e.event_type == EventType::TurnAdvance);
    assert!(has_turn_advance, "turn should advance normally");
}

// ---------------------------------------------------------------------------
// 11. Trigger definition roundtrip (parse -> serialize -> parse)
// ---------------------------------------------------------------------------

#[test]
fn test_trigger_definition_roundtrip() {
    let def1 = GameDefinition::from_json(TRIGGER_GAME_JSON).unwrap();

    // Must have parsed the trigger
    assert!(def1.triggers.contains_key("on_place"));
    let trigger = &def1.triggers["on_place"];
    assert_eq!(trigger.on_action, "place");
    assert_eq!(trigger.claim_window.eligible, "all_except_current");
    assert_eq!(trigger.claim_window.actions, vec!["claim", "challenge"]);
    assert_eq!(trigger.claim_window.priority, vec!["challenge", "claim"]);
    assert_eq!(trigger.claim_window.default, "pass");
    assert_eq!(trigger.claim_window.timeout, Some(10));

    // Serialize to JSON
    let json1 = serde_json::to_string(&def1).unwrap();

    // Parse again
    let def2 = GameDefinition::from_json(&json1).unwrap();
    let json2 = serde_json::to_string(&def2).unwrap();

    // Round-trip must be bitwise identical
    assert_eq!(json1, json2, "trigger definition roundtrip not identical");
}

// ---------------------------------------------------------------------------
// 12. next_in_order eligible rule
// ---------------------------------------------------------------------------

#[test]
fn test_next_in_order_eligible() {
    let mut session = next_in_order_session();
    assert_eq!(session.current_player(), Some("Alice"));

    // Alice places — next_in_order means only Bob (index 1) is eligible
    let events =
        apply_action_for_player(&mut session, &place_mark(1, 1), Some("Alice")).unwrap();

    let has_trigger = events
        .iter()
        .any(|e| e.event_type == EventType::TriggerActivated);
    assert!(has_trigger, "trigger should fire");

    let cw = session.runtime.claim_window.as_ref().unwrap();
    assert_eq!(
        cw.eligible_players,
        vec!["Bob"],
        "only next-in-order player (Bob) should be eligible"
    );

    // Bob claims — since he's the only eligible player, this resolves immediately
    let events = apply_claim(&mut session, "Bob", "claim").unwrap();

    let resolved = events
        .iter()
        .find(|e| e.event_type == EventType::ClaimResolved);
    assert!(resolved.is_some());
    assert_eq!(resolved.unwrap().player, "Bob");
    assert_eq!(resolved.unwrap().detail.as_deref(), Some("claim"));

    // Bob is now active
    assert_eq!(session.current_player(), Some("Bob"));
    assert!(session.runtime.claim_window.is_none());
}

// ---------------------------------------------------------------------------
// Cross-implementation test vector runner
// ---------------------------------------------------------------------------

#[test]
fn run_trigger_test_vectors() {
    let vectors_path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../tests/vectors/triggers.json"
    );
    let raw = std::fs::read_to_string(vectors_path)
        .unwrap_or_else(|e| panic!("failed to read {vectors_path}: {e}"));
    let vectors: serde_json::Value =
        serde_json::from_str(&raw).expect("invalid JSON in trigger test vectors");

    let game_def: GameDefinition =
        serde_json::from_value(vectors["game_definition"].clone())
            .expect("failed to parse game_definition from vector");

    let test_cases = vectors["test_cases"]
        .as_array()
        .expect("test_cases is not an array");

    for tc in test_cases {
        let name = tc["name"].as_str().unwrap();
        let steps = tc["steps"].as_array().expect("steps is not an array");

        // Fresh session for each test case
        let mut session = GameSession::new(game_def.clone()).unwrap();

        for (step_idx, step) in steps.iter().enumerate() {
            let step_type = step["type"].as_str().unwrap();
            let expected = &step["expected"];

            match step_type {
                "action" => {
                    let player = step["player"].as_str().unwrap();
                    let action_val = &step["action"];
                    let action_type = match action_val["action_type"].as_str().unwrap() {
                        "place" => ActionType::Place,
                        other => panic!("[{name}] unsupported action_type: {other}"),
                    };
                    let to = action_val.get("to").map(|p| Position::Structured {
                        zone: p.get("zone").and_then(|z| z.as_str()).map(String::from),
                        cell: p.get("cell").and_then(|c| c.as_str()).map(String::from),
                        index: None,
                    });
                    let action = Action {
                        action_type,
                        authority: None,
                        component_id: None,
                        component_type: action_val
                            .get("component_type")
                            .and_then(|v| v.as_str())
                            .map(String::from),
                        from: None,
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
                        commitment: None,
                        custom_data: None,
                    };

                    let events =
                        apply_action_for_player(&mut session, &action, Some(player))
                            .unwrap_or_else(|e| {
                                panic!("[{name}] step {step_idx}: action failed: {e}")
                            });

                    verify_step_expected(&session, &events, expected, name, step_idx);
                }
                "claim" => {
                    let player = step["player"].as_str().unwrap();
                    let claim = step["claim"].as_str().unwrap();
                    let events = apply_claim(&mut session, player, claim)
                        .unwrap_or_else(|e| {
                            panic!("[{name}] step {step_idx}: claim failed: {e}")
                        });

                    verify_step_expected(&session, &events, expected, name, step_idx);
                }
                other => panic!("[{name}] unknown step type: {other}"),
            }
        }
    }
}

fn verify_step_expected(
    session: &GameSession,
    events: &[baize_engine::transition::GameEvent],
    expected: &serde_json::Value,
    test_name: &str,
    step: usize,
) {
    // Check claim_window_active
    if let Some(active) = expected.get("claim_window_active").and_then(|v| v.as_bool()) {
        assert_eq!(
            session.runtime.claim_window.is_some(),
            active,
            "[{test_name}] step {step}: claim_window_active mismatch"
        );
    }

    // Check current_player
    if let Some(exp_player) = expected.get("current_player").and_then(|v| v.as_str()) {
        assert_eq!(
            session.current_player(),
            Some(exp_player),
            "[{test_name}] step {step}: current_player mismatch"
        );
    }

    // Check events_contain
    if let Some(exp_events) = expected.get("events_contain").and_then(|v| v.as_array()) {
        for exp_ev in exp_events {
            let exp_type = exp_ev["event_type"].as_str().unwrap();
            let matching = events.iter().find(|e| {
                let type_str = serde_json::to_value(&e.event_type)
                    .unwrap()
                    .as_str()
                    .unwrap()
                    .to_string();
                if type_str != exp_type {
                    return false;
                }
                if let Some(exp_player) = exp_ev.get("player").and_then(|v| v.as_str()) {
                    if e.player != exp_player {
                        return false;
                    }
                }
                if let Some(exp_detail) = exp_ev.get("detail").and_then(|v| v.as_str()) {
                    if e.detail.as_deref() != Some(exp_detail) {
                        return false;
                    }
                }
                true
            });
            assert!(
                matching.is_some(),
                "[{test_name}] step {step}: expected event {exp_ev} not found in {events:?}"
            );
        }
    }

    // Check events_must_not_contain
    if let Some(excluded) = expected
        .get("events_must_not_contain")
        .and_then(|v| v.as_array())
    {
        for excl in excluded {
            let excl_type = excl.as_str().unwrap();
            let found = events.iter().any(|e| {
                let type_str = serde_json::to_value(&e.event_type)
                    .unwrap()
                    .as_str()
                    .unwrap()
                    .to_string();
                type_str == excl_type
            });
            assert!(
                !found,
                "[{test_name}] step {step}: event type {excl_type} should not be present"
            );
        }
    }

    // Check claim_window details
    if let Some(exp_cw) = expected.get("claim_window").and_then(|v| v.as_object()) {
        let cw = session
            .runtime
            .claim_window
            .as_ref()
            .expect("claim_window expected to be active");

        if let Some(tn) = exp_cw.get("trigger_name").and_then(|v| v.as_str()) {
            assert_eq!(
                cw.trigger_name, tn,
                "[{test_name}] step {step}: trigger_name mismatch"
            );
        }
        if let Some(tp) = exp_cw.get("triggering_player").and_then(|v| v.as_str()) {
            assert_eq!(
                cw.triggering_player, tp,
                "[{test_name}] step {step}: triggering_player mismatch"
            );
        }
        if let Some(ep) = exp_cw.get("eligible_players").and_then(|v| v.as_array()) {
            let expected_eligible: Vec<String> = ep
                .iter()
                .map(|v| v.as_str().unwrap().to_string())
                .collect();
            assert_eq!(
                cw.eligible_players, expected_eligible,
                "[{test_name}] step {step}: eligible_players mismatch"
            );
        }
    }
}
