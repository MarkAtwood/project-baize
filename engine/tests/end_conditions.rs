use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::GameSession;
use baize_engine::state::{GameOutcome, GameStatus};
use baize_engine::transition::{apply_action, EventType};
use baize_engine::GameDefinition;

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
            { "result": "win", "player": "current", "condition": "three_in_line", "name": "three_in_a_row" },
            { "result": "draw", "condition": "board_is_full", "name": "board_full" }
        ],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();
    GameSession::new(def).unwrap()
}

fn place(col: u32, row: u32) -> Action {
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
        mental_poker_data: None,
    }
}

#[test]
fn x_wins_top_row() {
    let mut session = tic_tac_toe_session();

    // X(0,0) O(0,1) X(1,0) O(1,1) X(2,0) — X wins with top row
    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(1, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    let events = apply_action(&mut session, &place(2, 0)).unwrap();

    assert_eq!(session.runtime.status, GameStatus::Finished);
    assert!(events.iter().any(|e| e.event_type == EventType::GameEnd));
    assert!(!events.iter().any(|e| e.event_type == EventType::TurnAdvance));

    let result = session.runtime.result.as_ref().unwrap();
    assert_eq!(result.outcome, GameOutcome::Win);
    assert_eq!(result.winner.as_deref(), Some("X"));
    assert_eq!(result.condition.as_deref(), Some("three_in_a_row"));
}

#[test]
fn o_wins_diagonal() {
    let mut session = tic_tac_toe_session();

    // X(0,0) O(1,1) X(0,1) O(2,0) X(2,2) O(0,2) — O wins with anti-diagonal
    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(2, 0)).unwrap();
    apply_action(&mut session, &place(2, 2)).unwrap();
    let events = apply_action(&mut session, &place(0, 2)).unwrap();

    assert_eq!(session.runtime.status, GameStatus::Finished);
    let result = session.runtime.result.as_ref().unwrap();
    assert_eq!(result.outcome, GameOutcome::Win);
    assert_eq!(result.winner.as_deref(), Some("O"));
    assert!(events.iter().any(|e| e.event_type == EventType::GameEnd));
}

#[test]
fn draw_when_board_full() {
    let mut session = tic_tac_toe_session();

    // Play a draw game:
    // X O X
    // X X O
    // O X O
    apply_action(&mut session, &place(0, 0)).unwrap(); // X
    apply_action(&mut session, &place(1, 0)).unwrap(); // O
    apply_action(&mut session, &place(2, 0)).unwrap(); // X
    apply_action(&mut session, &place(2, 1)).unwrap(); // O
    apply_action(&mut session, &place(0, 1)).unwrap(); // X
    apply_action(&mut session, &place(0, 2)).unwrap(); // O
    apply_action(&mut session, &place(1, 1)).unwrap(); // X
    apply_action(&mut session, &place(2, 2)).unwrap(); // O
    let events = apply_action(&mut session, &place(1, 2)).unwrap();

    assert_eq!(session.runtime.status, GameStatus::Finished);
    let result = session.runtime.result.as_ref().unwrap();
    assert_eq!(result.outcome, GameOutcome::Draw);
    assert!(result.winner.is_none());
    assert_eq!(result.condition.as_deref(), Some("board_full"));
    assert!(events.iter().any(|e| e.event_type == EventType::GameEnd));
}

#[test]
fn no_moves_after_win() {
    let mut session = tic_tac_toe_session();

    // X wins top row
    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(1, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    apply_action(&mut session, &place(2, 0)).unwrap();

    // Trying to move after game is over should fail
    let result = apply_action(&mut session, &place(2, 2));
    assert!(result.is_err());
}

#[test]
fn win_checked_before_turn_advance() {
    let mut session = tic_tac_toe_session();

    // After X wins, turn should NOT have advanced to O
    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(1, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    apply_action(&mut session, &place(2, 0)).unwrap();

    // Turn index should still point to X (index 0) since we didn't advance
    assert_eq!(session.runtime.turn_index, 0);
    assert_eq!(session.current_player(), Some("X"));
}

#[test]
fn game_end_event_has_state_hash() {
    let mut session = tic_tac_toe_session();

    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(1, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    let events = apply_action(&mut session, &place(2, 0)).unwrap();

    let game_end = events
        .iter()
        .find(|e| e.event_type == EventType::GameEnd)
        .unwrap();
    assert!(!game_end.state_hash.is_empty());
}

#[test]
fn wire_state_includes_result() {
    let mut session = tic_tac_toe_session();

    apply_action(&mut session, &place(0, 0)).unwrap();
    apply_action(&mut session, &place(0, 1)).unwrap();
    apply_action(&mut session, &place(1, 0)).unwrap();
    apply_action(&mut session, &place(1, 1)).unwrap();
    apply_action(&mut session, &place(2, 0)).unwrap();

    let wire = session.to_wire_state();
    let result = wire.result.unwrap();
    assert_eq!(result.outcome, GameOutcome::Win);
    assert_eq!(result.winner.as_deref(), Some("X"));
}
