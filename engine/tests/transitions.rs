use baize_engine::action::{Action, ActionType, Orientation, Position};
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
            span_cells: Vec::new(),
    }).unwrap();
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
            span_cells: Vec::new(),
    }).unwrap();
    let br = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "br1".into(),
        component_type: "rook".into(),
        owner: Some("black".into()),
        facing: None,
        state: None,
        properties: IndexMap::new(),
            span_cells: Vec::new(),
    }).unwrap();

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

fn battleship_session() -> GameSession {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Battleship", "players": ["A", "B"], "information": "imperfect" },
        "zones": {
            "ocean": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
            "target": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
            "ships_remaining": { "zone_type": "counter", "per_player": true, "visibility": "public" }
        },
        "components": {
            "ship": {
                "owner": "per_player",
                "types": {
                    "carrier": { "span": 5 },
                    "destroyer": { "span": 2 }
                }
            },
            "peg": { "owner": "per_player", "count": "unlimited" }
        },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "win", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();
    let mut session = GameSession::new(def).unwrap();
    // Initialize ships_remaining counters
    for (_, player) in session.runtime.players.iter_mut() {
        player.counters.insert("ships_remaining".into(), 2);
    }
    session
}

fn place_ship_action(comp_type: &str, col: u32, row: u32, orient: Orientation) -> Action {
    Action {
        action_type: ActionType::PlaceShip,
        authority: None,
        component_id: None,
        component_type: Some(comp_type.to_string()),
        from: None,
        to: Some(Position::Structured {
            zone: Some("ocean".to_string()),
            cell: Some(format!("{col},{row}")),
            index: None,
        }),
        zone: None,
        count: None,
        promote_to: None,
        orientation: Some(orient),
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

fn fire_action(col: u32, row: u32) -> Action {
    Action {
        action_type: ActionType::Fire,
        authority: None,
        component_id: None,
        component_type: None,
        from: None,
        to: Some(Position::Structured {
            zone: Some("ocean".to_string()),
            cell: Some(format!("{col},{row}")),
            index: None,
        }),
        zone: Some("target".to_string()),
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
fn place_ship_horizontal() {
    let mut session = battleship_session();

    let events = apply_action(
        &mut session,
        &place_ship_action("carrier", 0, 0, Orientation::Horizontal),
    )
    .unwrap();

    assert!(events.iter().any(|e| e.event_type == EventType::Place));

    // Component should occupy 5 cells on player A's ocean
    let ocean = session.runtime.players.get("A").unwrap().zones.get("ocean").unwrap();
    let cid = ocean.grid_get(0, 0).expect("cell 0,0 should be occupied");
    for col in 0..5u32 {
        assert_eq!(ocean.grid_get(col, 0), Some(cid));
    }
    assert!(ocean.grid_get(5, 0).is_none());

    // Component data should have span_cells populated
    let comp = session.runtime.components.get(cid).unwrap();
    assert_eq!(comp.span_cells.len(), 5);
    assert_eq!(comp.component_type, "carrier");
}

#[test]
fn place_ship_vertical() {
    let mut session = battleship_session();

    let events = apply_action(
        &mut session,
        &place_ship_action("destroyer", 9, 8, Orientation::Vertical),
    )
    .unwrap();

    assert!(events.iter().any(|e| e.event_type == EventType::Place));

    let ocean = session.runtime.players.get("A").unwrap().zones.get("ocean").unwrap();
    let cid = ocean.grid_get(9, 8).unwrap();
    assert_eq!(ocean.grid_get(9, 9), Some(cid));
    assert!(ocean.grid_get(9, 7).is_none());
}

#[test]
fn place_ship_overlap_rejected() {
    let mut session = battleship_session();

    apply_action(
        &mut session,
        &place_ship_action("carrier", 0, 0, Orientation::Horizontal),
    )
    .unwrap();

    session.runtime.turn_index = 0;

    let result = apply_action(
        &mut session,
        &place_ship_action("destroyer", 3, 0, Orientation::Horizontal),
    );
    assert!(result.is_err());
}

#[test]
fn place_ship_out_of_bounds_rejected() {
    let mut session = battleship_session();

    let result = apply_action(
        &mut session,
        &place_ship_action("carrier", 8, 0, Orientation::Horizontal),
    );
    assert!(result.is_err());
}

#[test]
fn fire_miss() {
    let mut session = battleship_session();
    session.runtime.status = GameStatus::InProgress;

    // Player B places a destroyer at (5,5) on their ocean
    session.runtime.turn_index = 1; // B's turn
    apply_action(
        &mut session,
        &place_ship_action("destroyer", 5, 5, Orientation::Horizontal),
    )
    .unwrap();

    // Player A fires at (0,0) — empty cell on B's ocean
    session.runtime.turn_index = 0; // A's turn
    let events = apply_action(&mut session, &fire_action(0, 0)).unwrap();

    assert!(events.iter().any(|e| e.event_type == EventType::Fire));
    assert!(events.iter().any(|e| e.event_type == EventType::Miss));
    assert!(!events.iter().any(|e| e.event_type == EventType::Hit));

    // A's target grid should have a miss peg at (0,0)
    let target = session.runtime.players.get("A").unwrap().zones.get("target").unwrap();
    let peg = target.grid_get(0, 0);
    assert!(peg.is_some());
    let peg_comp = session.runtime.components.get(peg.unwrap()).unwrap();
    assert_eq!(peg_comp.component_type, "miss");
}

#[test]
fn fire_hit() {
    let mut session = battleship_session();
    session.runtime.status = GameStatus::InProgress;

    // Player B places a destroyer at (5,5) horizontal on their ocean
    session.runtime.turn_index = 1;
    apply_action(
        &mut session,
        &place_ship_action("destroyer", 5, 5, Orientation::Horizontal),
    )
    .unwrap();

    // Player A fires at (5,5) — hit!
    session.runtime.turn_index = 0;
    let events = apply_action(&mut session, &fire_action(5, 5)).unwrap();

    assert!(events.iter().any(|e| e.event_type == EventType::Hit));
    assert!(!events.iter().any(|e| e.event_type == EventType::Miss));

    // A's target grid should have a hit peg at (5,5)
    let target = session.runtime.players.get("A").unwrap().zones.get("target").unwrap();
    let peg = target.grid_get(5, 5);
    assert!(peg.is_some());
    let peg_comp = session.runtime.components.get(peg.unwrap()).unwrap();
    assert_eq!(peg_comp.component_type, "hit");
}

#[test]
fn fire_sunk() {
    let mut session = battleship_session();
    session.runtime.status = GameStatus::InProgress;

    // Player B places a destroyer (span 2) at (5,5) horizontal
    session.runtime.turn_index = 1;
    apply_action(
        &mut session,
        &place_ship_action("destroyer", 5, 5, Orientation::Horizontal),
    )
    .unwrap();

    // Player A fires at (5,5) — first hit
    session.runtime.turn_index = 0;
    let events1 = apply_action(&mut session, &fire_action(5, 5)).unwrap();
    assert!(events1.iter().any(|e| e.event_type == EventType::Hit));
    assert!(!events1.iter().any(|e| e.event_type == EventType::Sunk));

    // Player A fires at (6,5) — second hit, ship sunk!
    session.runtime.turn_index = 0;
    let events2 = apply_action(&mut session, &fire_action(6, 5)).unwrap();
    assert!(events2.iter().any(|e| e.event_type == EventType::Hit));
    assert!(events2.iter().any(|e| e.event_type == EventType::Sunk));

    // B's ships_remaining should be decremented
    let b_ships = session.runtime.players.get("B").unwrap().counters.get("ships_remaining").unwrap();
    assert_eq!(*b_ships, 1); // was 2, now 1
}

#[test]
fn fire_duplicate_rejected() {
    let mut session = battleship_session();
    session.runtime.status = GameStatus::InProgress;

    // Player A fires at (0,0) — miss
    session.runtime.turn_index = 0;
    apply_action(&mut session, &fire_action(0, 0)).unwrap();

    // Player A tries to fire at (0,0) again — should be rejected
    session.runtime.turn_index = 0;
    let result = apply_action(&mut session, &fire_action(0, 0));
    assert!(result.is_err());
}
