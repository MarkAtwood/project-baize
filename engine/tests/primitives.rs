use baize_engine::action::{Action, ActionType};
use baize_engine::runtime::*;
use baize_engine::transition::{apply_action, EventType};
use baize_engine::GameDefinition;
use indexmap::IndexMap;

/// Helper: create a chess-like session with a few pieces for testing movement primitives.
fn chess_like_session() -> GameSession {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Test", "players": ["white", "black"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "dimensions": [8, 8], "visibility": "public" }
        },
        "components": {
            "pawn": { "owner": "per_player", "count": 8 },
            "queen": { "owner": "per_player", "count": 1 }
        },
        "turn_order": { "type": "alternating", "players": ["white", "black"], "actions_per_turn": 1, "mandatory": true },
        "end_conditions": [
            { "result": "draw", "condition": "all_cells_occupied" }
        ],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();
    let mut session = GameSession::new(def).unwrap();
    session.runtime.status = baize_engine::state::GameStatus::InProgress;
    session
}

fn place_component(
    session: &mut GameSession,
    comp_type: &str,
    owner: &str,
    col: u32,
    row: u32,
) -> String {
    let instance_id = format!("{}-{}-{}", comp_type, owner, session.runtime.components.len());
    let cid = session
        .runtime
        .components
        .insert(ComponentData {
            id: ComponentId(0),
            string_id: instance_id.clone(),
            component_type: comp_type.to_string(),
            owner: Some(owner.to_string()),
            facing: None,
            state: None,
            properties: IndexMap::new(),
            span_cells: Vec::new(),
        })
        .unwrap();
    if let Some(zone) = session.runtime.zones.get_mut("board") {
        zone.grid_set(col, row, Some(cid));
    }
    instance_id
}

fn action_with_defaults(action_type: ActionType) -> Action {
    Action {
        action_type,
        authority: None,
        component_id: None,
        component_type: None,
        from: None,
        to: None,
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
        custom_data: None,
    }
}

#[test]
fn remove_piece_from_grid() {
    let mut session = chess_like_session();
    let pawn_id = place_component(&mut session, "pawn", "white", 3, 1);

    // Verify piece is on the board
    assert!(session.runtime.zones.get("board").unwrap().grid_get(3, 1).is_some());

    let action = Action {
        component_id: Some(pawn_id.clone()),
        ..action_with_defaults(ActionType::Remove)
    };
    let events = apply_action(&mut session, &action).unwrap();

    // Piece should be gone
    assert!(session.runtime.zones.get("board").unwrap().grid_get(3, 1).is_none());

    // Should have a remove event
    assert!(events.iter().any(|e| e.event_type == EventType::Remove));
}

#[test]
fn swap_two_pieces() {
    let mut session = chess_like_session();
    let pawn_id = place_component(&mut session, "pawn", "white", 0, 0);
    let queen_id = place_component(&mut session, "queen", "white", 1, 0);

    let action = Action {
        component_id: Some(pawn_id.clone()),
        swap_with: Some(queen_id.clone()),
        ..action_with_defaults(ActionType::Swap)
    };
    let events = apply_action(&mut session, &action).unwrap();

    // Pieces should have swapped positions
    let board = session.runtime.zones.get("board").unwrap();
    let at_0_0 = board.grid_get(0, 0).unwrap();
    let at_1_0 = board.grid_get(1, 0).unwrap();
    assert_eq!(
        session.runtime.components.get(at_0_0).unwrap().string_id,
        queen_id
    );
    assert_eq!(
        session.runtime.components.get(at_1_0).unwrap().string_id,
        pawn_id
    );

    assert!(events.iter().any(|e| e.event_type == EventType::Swap));
}

#[test]
fn promote_piece_changes_type() {
    let mut session = chess_like_session();
    let pawn_id = place_component(&mut session, "pawn", "white", 4, 7);

    let action = Action {
        component_id: Some(pawn_id.clone()),
        promote_to: Some("queen".into()),
        ..action_with_defaults(ActionType::Promote)
    };
    let events = apply_action(&mut session, &action).unwrap();

    // Piece type should now be queen
    let cid = session
        .runtime
        .components
        .iter()
        .find(|c| c.string_id == pawn_id)
        .unwrap();
    assert_eq!(cid.component_type, "queen");

    assert!(events.iter().any(|e| e.event_type == EventType::Promote));
}

#[test]
fn remove_nonexistent_piece_fails() {
    let mut session = chess_like_session();

    let action = Action {
        component_id: Some("nonexistent".into()),
        ..action_with_defaults(ActionType::Remove)
    };
    let result = apply_action(&mut session, &action);
    assert!(result.is_err());
}

#[test]
fn swap_different_zones_fails() {
    let mut session = chess_like_session();
    let pawn_id = place_component(&mut session, "pawn", "white", 0, 0);

    // Create a second component that's not on any grid (component exists but not placed)
    let orphan_id = format!("queen-white-{}", session.runtime.components.len());
    session
        .runtime
        .components
        .insert(ComponentData {
            id: ComponentId(0),
            string_id: orphan_id.clone(),
            component_type: "queen".to_string(),
            owner: Some("white".to_string()),
            facing: None,
            state: None,
            properties: IndexMap::new(),
            span_cells: Vec::new(),
        })
        .unwrap();

    let action = Action {
        component_id: Some(pawn_id),
        swap_with: Some(orphan_id),
        ..action_with_defaults(ActionType::Swap)
    };
    let result = apply_action(&mut session, &action);
    assert!(result.is_err());
}
