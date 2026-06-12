use baize_engine::action::{Action, ActionType, Position};
use baize_engine::runtime::*;
use baize_engine::state::GameStatus;
use baize_engine::transition::apply_action;
use baize_engine::GameDefinition;

fn place(col: u32, row: u32) -> Action {
    Action {
        action_type: ActionType::Place,
        component_type: Some("mark".into()),
        to: Some(Position::Structured {
            zone: Some("board".into()),
            cell: Some(format!("{col},{row}")),
            index: None,
        }),
        // all other fields None
        authority: None,
        component_id: None,
        from: None,
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

fn resign_action() -> Action {
    Action {
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
        commitment: None,
        custom_data: None,
    }
}

fn load_session() -> GameSession {
    let def = GameDefinition::from_json(include_str!("../../games/tic-tac-toe.json")).unwrap();
    GameSession::new(def).unwrap()
}

/// Play a complete tic-tac-toe game where X wins with the top row.
///
/// Move sequence: X(0,0) O(0,1) X(1,0) O(1,1) X(2,0)
///
/// Board after final move:
///   X X X
///   O O .
///   . . .
///
/// Tests the CEL composable expression:
///   lines.exists(line, line.all(cell, cell == current_player))
#[test]
fn x_wins_tic_tac_toe() {
    let mut session = load_session();

    apply_action(&mut session, &place(0, 0)).unwrap(); // X
    apply_action(&mut session, &place(0, 1)).unwrap(); // O
    apply_action(&mut session, &place(1, 0)).unwrap(); // X
    apply_action(&mut session, &place(1, 1)).unwrap(); // O
    apply_action(&mut session, &place(2, 0)).unwrap(); // X wins

    assert_eq!(session.runtime.status, GameStatus::Finished);

    let result = session.runtime.result.as_ref().unwrap();
    assert_eq!(
        result.outcome,
        baize_engine::state::GameOutcome::Win,
        "expected a win outcome"
    );
    assert_eq!(
        result.winner.as_deref(),
        Some("X"),
        "expected X to be the winner"
    );
    assert_eq!(
        result.condition.as_deref(),
        Some("three_in_a_row"),
        "expected three_in_a_row condition"
    );
}

/// Play a complete tic-tac-toe game that ends in a draw by filling
/// all 9 cells without either player completing a line.
///
/// Move sequence (alternating X/O):
///   X(0,0) O(1,0) X(2,0) O(2,1) X(0,1) O(0,2) X(1,1) O(2,2) X(1,2)
///
/// Board:
///   X O X
///   X X O
///   O X O
///
/// Tests the CEL expression: occupied_count == cell_count
#[test]
fn draw_tic_tac_toe() {
    let mut session = load_session();

    apply_action(&mut session, &place(0, 0)).unwrap(); // X
    apply_action(&mut session, &place(1, 0)).unwrap(); // O
    apply_action(&mut session, &place(2, 0)).unwrap(); // X
    apply_action(&mut session, &place(2, 1)).unwrap(); // O
    apply_action(&mut session, &place(0, 1)).unwrap(); // X
    apply_action(&mut session, &place(0, 2)).unwrap(); // O
    apply_action(&mut session, &place(1, 1)).unwrap(); // X
    apply_action(&mut session, &place(2, 2)).unwrap(); // O
    apply_action(&mut session, &place(1, 2)).unwrap(); // X — board full, draw

    assert_eq!(session.runtime.status, GameStatus::Finished);

    let result = session.runtime.result.as_ref().unwrap();
    assert_eq!(
        result.outcome,
        baize_engine::state::GameOutcome::Draw,
        "expected a draw outcome"
    );
    assert!(
        result.winner.is_none(),
        "draw should have no winner"
    );
    assert_eq!(
        result.condition.as_deref(),
        Some("board_full"),
        "expected board_full condition"
    );
}

/// X makes one move, then resigns. The game should end immediately.
#[test]
fn resign_ends_game() {
    let mut session = load_session();

    apply_action(&mut session, &place(0, 0)).unwrap(); // X places
    apply_action(&mut session, &resign_action()).unwrap(); // O resigns

    assert_eq!(
        session.runtime.status,
        GameStatus::Finished,
        "resign should end the game"
    );
}
