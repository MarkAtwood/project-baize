use baize_engine::moves::legal_moves;
use baize_engine::runtime::*;
use baize_engine::GameDefinition;
use indexmap::IndexMap;
use serde::Deserialize;

#[derive(Deserialize)]
struct TestSuite {
    test_cases: Vec<TestCase>,
}

#[derive(Deserialize)]
struct TestCase {
    name: String,
    #[serde(default, rename = "description")]
    _description: Option<String>,
    game_definition: serde_json::Value,
    setup: Vec<Placement>,
    current_player: String,
    expected_move_count: usize,
    expected_moves: Vec<ExpectedMove>,
}

#[derive(Deserialize)]
struct Placement {
    string_id: String,
    component_type: String,
    owner: String,
    col: u32,
    row: u32,
}

#[derive(Deserialize, Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct ExpectedMove {
    component: String,
    from: String,
    to: String,
}

fn load_test_suite() -> TestSuite {
    // CARGO_MANIFEST_DIR points to engine/, vectors are at ../tests/vectors/
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../tests/vectors/legal-moves.json"
    );
    let content = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read test vectors at {path}: {e}"));
    serde_json::from_str(&content).expect("failed to parse test vectors JSON")
}

fn setup_session(tc: &TestCase) -> GameSession {
    let def: GameDefinition =
        serde_json::from_value(tc.game_definition.clone()).expect("invalid game definition");
    let mut session = GameSession::new(def).unwrap();

    // Advance turn_index until current_player matches
    let max_players = session.runtime.players.len();
    for _ in 0..max_players {
        if session.current_player() == Some(&tc.current_player) {
            break;
        }
        session.runtime.turn_index =
            (session.runtime.turn_index + 1) % max_players;
    }
    assert_eq!(
        session.current_player(),
        Some(tc.current_player.as_str()),
        "could not set current player to '{}'",
        tc.current_player
    );

    for p in &tc.setup {
        let cid = session.runtime.components.insert(ComponentData {
            id: ComponentId(0),
            string_id: p.string_id.clone(),
            component_type: p.component_type.clone(),
            owner: Some(p.owner.clone()),
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
            .expect("zone 'board' not found")
            .grid_set(p.col, p.row, Some(cid));
    }

    session
}

fn extract_move(session: &GameSession, m: &baize_engine::moves::LegalMove) -> ExpectedMove {
    let comp_data = session
        .runtime
        .components
        .get(m.component_id)
        .expect("component not found");

    let from = match &m.action.from {
        Some(baize_engine::action::Position::Structured { cell, .. }) => {
            cell.clone().unwrap_or_default()
        }
        Some(baize_engine::action::Position::Coordinate(c)) => c.clone(),
        None => String::new(),
    };

    let to = match &m.action.to {
        Some(baize_engine::action::Position::Structured { cell, .. }) => {
            cell.clone().unwrap_or_default()
        }
        Some(baize_engine::action::Position::Coordinate(c)) => c.clone(),
        None => String::new(),
    };

    ExpectedMove {
        component: comp_data.string_id.clone(),
        from,
        to,
    }
}

#[test]
fn cross_implementation_legal_moves() {
    let suite = load_test_suite();

    for tc in &suite.test_cases {
        let session = setup_session(tc);
        let moves = legal_moves(&session);

        // Extract and sort actual moves
        let mut actual: Vec<ExpectedMove> =
            moves.iter().map(|m| extract_move(&session, m)).collect();
        actual.sort();

        // Sort expected moves
        let mut expected = tc.expected_moves.clone();
        expected.sort();

        assert_eq!(
            actual.len(),
            tc.expected_move_count,
            "test '{}': expected {} moves, got {}.\nActual: {:#?}",
            tc.name,
            tc.expected_move_count,
            actual.len(),
            actual,
        );

        assert_eq!(
            actual, expected,
            "test '{}': moves do not match.\nExpected: {:#?}\nActual: {:#?}",
            tc.name, expected, actual,
        );
    }
}
