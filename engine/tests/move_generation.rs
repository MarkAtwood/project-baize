use baize_engine::moves::legal_moves;
use baize_engine::runtime::*;
use baize_engine::GameDefinition;
use indexmap::IndexMap;

fn simple_chess_def() -> GameDefinition {
    serde_json::from_str(
        r#"{
        "game": { "name": "Simple Chess", "players": ["white", "black"], "information": "perfect" },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [8, 8],
                "visibility": "public"
            }
        },
        "components": {
            "king": {
                "owner": "per_player",
                "count": 1,
                "movement": [
                    { "primitive": "step", "direction": "adjacent" }
                ]
            },
            "rook": {
                "owner": "per_player",
                "count": 2,
                "movement": [
                    { "primitive": "slide", "direction": "orthogonal" }
                ]
            },
            "knight": {
                "owner": "per_player",
                "count": 2,
                "movement": [
                    { "primitive": "leap", "dx": 1, "dy": 2 }
                ]
            },
            "bishop": {
                "owner": "per_player",
                "count": 2,
                "movement": [
                    { "primitive": "slide", "direction": "diagonal" }
                ]
            }
        },
        "turn_order": { "type": "alternating", "players": ["white", "black"], "actions_per_turn": 1, "mandatory": true },
        "end_conditions": [{ "result": "win", "condition": "checkmate" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap()
}

fn place_piece(
    session: &mut GameSession,
    name: &str,
    comp_type: &str,
    owner: &str,
    col: u32,
    row: u32,
) -> ComponentId {
    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: name.into(),
        component_type: comp_type.into(),
        owner: Some(owner.into()),
        facing: None,
        state: None,
        properties: IndexMap::new(),
            span_cells: Vec::new(),
                orientation: None,
    }).unwrap();
    session
        .runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(col, row, Some(cid));
    cid
}

#[test]
fn king_center_of_empty_board() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wk", "king", "white", 4, 4);

    let moves = legal_moves(&session);
    // King at (4,4) on an empty board: 8 adjacent squares
    assert_eq!(moves.len(), 8);
}

#[test]
fn king_corner() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wk", "king", "white", 0, 0);

    let moves = legal_moves(&session);
    // King at (0,0): 3 adjacent squares
    assert_eq!(moves.len(), 3);
}

#[test]
fn rook_empty_board() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wr", "rook", "white", 4, 4);

    let moves = legal_moves(&session);
    // Rook at (4,4) on 8x8: 7 up + 7 right + ... no, 4+3+4+3 = 14
    // Actually: 4 right (5,6,7 col) = 3, 4 left (3,2,1,0) = 4, 4 up = 3, 4 down = 4 => 14
    assert_eq!(moves.len(), 14);
}

#[test]
fn rook_blocked_by_friendly() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wr", "rook", "white", 0, 0);
    place_piece(&mut session, "wk", "king", "white", 0, 2); // blocks vertical

    let moves_all = legal_moves(&session);
    // Rook at (0,0): right 7, up 1 (blocked at row 2 by friendly king), down 0 (edge)
    // up: row 1 only (row 2 is friendly, can't capture or pass)
    // right: cols 1-7 = 7
    // left: 0 (edge)
    // down: 0 (edge)
    // Total rook moves: 7 + 1 = 8
    // King at (0,2): has some moves too
    let rook_moves: Vec<_> = moves_all
        .iter()
        .filter(|m| {
            session
                .runtime
                .components
                .get(m.component_id)
                .map(|c| c.component_type == "rook")
                .unwrap_or(false)
        })
        .collect();
    assert_eq!(rook_moves.len(), 8);
}

#[test]
fn rook_can_capture_enemy() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wr", "rook", "white", 0, 0);
    place_piece(&mut session, "bk", "king", "black", 0, 3); // enemy on same file

    let moves_all = legal_moves(&session);
    let rook_moves: Vec<_> = moves_all
        .iter()
        .filter(|m| {
            session
                .runtime
                .components
                .get(m.component_id)
                .map(|c| c.component_type == "rook")
                .unwrap_or(false)
        })
        .collect();
    // Rook at (0,0): right 7, up to row 3 (capture enemy) = 3, left 0, down 0
    // Total: 7 + 3 = 10
    assert_eq!(rook_moves.len(), 10);
}

#[test]
fn knight_moves() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wn", "knight", "white", 4, 4);

    let moves = legal_moves(&session);
    // Knight at (4,4) on 8x8: all 8 L-shapes are in bounds
    assert_eq!(moves.len(), 8);
}

#[test]
fn knight_corner() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wn", "knight", "white", 0, 0);

    let moves = legal_moves(&session);
    // Knight at (0,0): only (1,2) and (2,1) are in bounds
    assert_eq!(moves.len(), 2);
}

#[test]
fn bishop_empty_board() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wb", "bishop", "white", 4, 4);

    let moves = legal_moves(&session);
    // Bishop at (4,4) on 8x8: diagonals
    // NE: 3, NW: 3, SE: 4, SW: 4 => wait let me count
    // (4,4): NE(+1,+1): (5,5),(6,6),(7,7) = 3
    //        NW(-1,+1): (3,5),(2,6),(1,7) = 3
    //        SE(+1,-1): (5,3),(6,2),(7,1) = 3... wait (7,0) too? (8 is out) hmm
    //        Actually from (4,4) going (+1,-1): (5,3),(6,2),(7,1) = 3
    //        (8,0) is out of bounds
    //        SW(-1,-1): (3,3),(2,2),(1,1),(0,0) = 4
    // Total: 3+3+3+4 = 13
    assert_eq!(moves.len(), 13);
}

#[test]
fn only_current_player_moves() {
    let def = simple_chess_def();
    let mut session = GameSession::new(def).unwrap();
    place_piece(&mut session, "wk", "king", "white", 4, 4);
    place_piece(&mut session, "bk", "king", "black", 0, 0);

    // White's turn
    let moves = legal_moves(&session);
    // Only white king should move (8 moves)
    assert_eq!(moves.len(), 8);

    // Advance to black's turn
    session.advance_turn();
    let moves = legal_moves(&session);
    // Only black king should move (3 moves from corner)
    assert_eq!(moves.len(), 3);
}
