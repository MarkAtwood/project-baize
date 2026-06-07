use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::*;
use baize_engine::state::GameStatus;
use baize_engine::transition::{apply_action, EventType};
use baize_engine::GameDefinition;
use indexmap::IndexMap;

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

fn place_action(col: u32, row: u32) -> Action {
    Action {
        action_type: ActionType::Place,
        authority: None,
        component_id: None,
        component_type: Some("mark".into()),
        from: None,
        to: Some(Position::Structured {
            zone: Some("board".into()),
            cell: Some(format!("{},{}", col, row)),
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
        custom_data: None,
    }
}

fn move_action(from_col: u32, from_row: u32, to_col: u32, to_row: u32) -> Action {
    Action {
        action_type: ActionType::MovePiece,
        authority: None,
        component_id: None,
        component_type: None,
        from: Some(Position::Structured {
            zone: Some("board".into()),
            cell: Some(format!("{},{}", from_col, from_row)),
            index: None,
        }),
        to: Some(Position::Structured {
            zone: Some("board".into()),
            cell: Some(format!("{},{}", to_col, to_row)),
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
        custom_data: None,
    }
}

#[test]
fn place_marks_alternating() {
    let mut session = tic_tac_toe_session();
    assert_eq!(session.current_player(), Some("X"));

    let events = apply_action(&mut session, &place_action(1, 1)).unwrap();
    assert!(events.iter().any(|e| e.event_type == EventType::Place));
    assert!(events
        .iter()
        .any(|e| e.event_type == EventType::TurnAdvance));
    assert_eq!(session.current_player(), Some("O"));

    // Board should have a mark at (1,1)
    let board = session.runtime.zones.get("board").unwrap();
    assert!(board.grid_get(1, 1).is_some());

    // O places
    let _events = apply_action(&mut session, &place_action(0, 0)).unwrap();
    assert_eq!(session.current_player(), Some("X"));
    assert!(session
        .runtime
        .zones
        .get("board")
        .unwrap()
        .grid_get(0, 0)
        .is_some());

    // Sequence should advance
    assert_eq!(session.runtime.sequence, 2);
    assert_eq!(session.runtime.move_count, 2);
}

#[test]
fn move_piece_on_grid() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Test", "players": ["white", "black"], "information": "perfect" },
        "zones": { "board": { "zone_type": "grid", "dimensions": [8, 8], "visibility": "public" } },
        "components": { "rook": { "owner": "per_player", "count": 2 } },
        "turn_order": { "type": "alternating", "players": ["white", "black"] },
        "end_conditions": [{ "result": "win", "condition": "checkmate" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();
    let mut session = GameSession::new(def).unwrap();

    // Manually place a rook
    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "wr1".into(),
        component_type: "rook".into(),
        owner: Some("white".into()),
        facing: None,
        state: None,
        properties: IndexMap::new(),
    });
    session
        .runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(0, 0, Some(cid));

    // Move rook from (0,0) to (0,5)
    let events = apply_action(&mut session, &move_action(0, 0, 0, 5)).unwrap();
    assert!(events
        .iter()
        .any(|e| e.event_type == EventType::MovePiece));

    let board = session.runtime.zones.get("board").unwrap();
    assert!(board.grid_get(0, 0).is_none());
    assert_eq!(board.grid_get(0, 5), Some(cid));
}

#[test]
fn capture_enemy_piece() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Test", "players": ["white", "black"], "information": "perfect" },
        "zones": { "board": { "zone_type": "grid", "dimensions": [8, 8], "visibility": "public" } },
        "components": { "rook": { "owner": "per_player", "count": 2 } },
        "turn_order": { "type": "alternating", "players": ["white", "black"] },
        "end_conditions": [{ "result": "win", "condition": "checkmate" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();
    let mut session = GameSession::new(def).unwrap();

    let wr = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "wr1".into(),
        component_type: "rook".into(),
        owner: Some("white".into()),
        facing: None,
        state: None,
        properties: IndexMap::new(),
    });
    let br = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "br1".into(),
        component_type: "rook".into(),
        owner: Some("black".into()),
        facing: None,
        state: None,
        properties: IndexMap::new(),
    });

    let board = session.runtime.zones.get_mut("board").unwrap();
    board.grid_set(0, 0, Some(wr));
    board.grid_set(0, 5, Some(br));

    // White rook captures black rook
    let events = apply_action(&mut session, &move_action(0, 0, 0, 5)).unwrap();
    assert!(events.iter().any(|e| e.event_type == EventType::Capture));
    assert!(events
        .iter()
        .any(|e| e.event_type == EventType::MovePiece));

    let board = session.runtime.zones.get("board").unwrap();
    assert!(board.grid_get(0, 0).is_none());
    assert_eq!(board.grid_get(0, 5), Some(wr)); // white rook is now there
}

#[test]
fn hash_chain_integrity() {
    let mut session = tic_tac_toe_session();

    apply_action(&mut session, &place_action(1, 1)).unwrap();
    assert_eq!(session.runtime.history_hashes.len(), 1);

    apply_action(&mut session, &place_action(0, 0)).unwrap();
    assert_eq!(session.runtime.history_hashes.len(), 2);

    // Hashes should be different
    assert_ne!(
        session.runtime.history_hashes[0],
        session.runtime.history_hashes[1]
    );
}

#[test]
fn resign_ends_game() {
    let mut session = tic_tac_toe_session();

    let resign = Action {
        action_type: ActionType::Resign,
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
    };

    let events = apply_action(&mut session, &resign).unwrap();
    assert!(events.iter().any(|e| e.event_type == EventType::Resign));
    assert_eq!(session.runtime.status, GameStatus::Finished);
}

#[test]
fn cannot_act_after_game_over() {
    let mut session = tic_tac_toe_session();
    session.runtime.status = GameStatus::Finished;

    let result = apply_action(&mut session, &place_action(0, 0));
    assert!(result.is_err());
}

#[test]
fn events_are_jsonl_serializable() {
    let mut session = tic_tac_toe_session();
    let events = apply_action(&mut session, &place_action(1, 1)).unwrap();

    for event in &events {
        let json = serde_json::to_string(event).unwrap();
        assert!(!json.is_empty());
        // Each event serializes to a single JSON line
        assert!(!json.contains('\n'));
    }
}
