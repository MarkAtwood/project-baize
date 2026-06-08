use baize_engine::runtime::*;
use baize_engine::state::*;
use baize_engine::GameDefinition;
use indexmap::IndexMap;
use serde::Deserialize;

// ---------------------------------------------------------------------------
// Test vector schema
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct TestSuite {
    test_cases: Vec<TestCase>,
}

#[derive(Deserialize)]
struct TestCase {
    name: String,
    game_definition: serde_json::Value,
    setup: SetupSpec,
}

#[derive(Deserialize)]
struct SetupSpec {
    status: String,
    components: Vec<ComponentSpec>,
    placements: Vec<PlacementSpec>,
    #[serde(default)]
    counters: IndexMap<String, i64>,
    #[serde(default)]
    player_counters: IndexMap<String, IndexMap<String, i64>>,
    #[serde(default)]
    player_zone_counters: IndexMap<String, IndexMap<String, i64>>,
    #[serde(default)]
    pot_zone_value: Option<i64>,
    #[serde(default)]
    advance_turns: u32,
}

#[derive(Deserialize)]
struct ComponentSpec {
    string_id: String,
    component_type: String,
    owner: Option<String>,
    #[serde(default)]
    facing: Option<String>,
    #[serde(default)]
    state: Option<String>,
    #[serde(default)]
    properties: Option<IndexMap<String, serde_json::Value>>,
}

#[derive(Deserialize)]
struct PlacementSpec {
    component_index: usize,
    #[serde(default)]
    zone: Option<String>,
    #[serde(default)]
    col: Option<u32>,
    #[serde(default)]
    row: Option<u32>,
    #[serde(default)]
    player_zone: Option<PlayerZonePlacement>,
    #[serde(default)]
    track_zone: Option<TrackPlacement>,
}

#[derive(Deserialize)]
struct PlayerZonePlacement {
    player: String,
    zone: String,
}

#[derive(Deserialize)]
struct TrackPlacement {
    zone: String,
    position: usize,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn load_test_suite() -> TestSuite {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../tests/vectors/round-trip.json"
    );
    let content = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("failed to read test vectors at {path}: {e}"));
    serde_json::from_str(&content).expect("failed to parse round-trip test vectors")
}

fn parse_facing(s: &str) -> Option<Facing> {
    match s {
        "face_up" => Some(Facing::FaceUp),
        "face_down" => Some(Facing::FaceDown),
        _ => None,
    }
}

fn parse_status(s: &str) -> GameStatus {
    match s {
        "setup" => GameStatus::Setup,
        "in_progress" => GameStatus::InProgress,
        "finished" => GameStatus::Finished,
        other => panic!("unknown status: {other}"),
    }
}

fn setup_session(tc: &TestCase) -> GameSession {
    let def: GameDefinition =
        serde_json::from_value(tc.game_definition.clone()).expect("invalid game definition");
    let mut session = GameSession::new(def).unwrap();

    session.runtime.status = parse_status(&tc.setup.status);

    // Insert components into the component table
    let mut cids = Vec::new();
    for comp in &tc.setup.components {
        let facing = comp.facing.as_deref().and_then(parse_facing);
        let properties = comp.properties.clone().unwrap_or_default();
        let cid = session.runtime.components.insert(ComponentData {
            id: ComponentId(0),
            string_id: comp.string_id.clone(),
            component_type: comp.component_type.clone(),
            owner: comp.owner.clone(),
            facing,
            state: comp.state.clone(),
            properties,
        }).unwrap();
        cids.push(cid);
    }

    // Place components
    for placement in &tc.setup.placements {
        let cid = cids[placement.component_index];

        if let Some(zone_name) = &placement.zone {
            let zone = session
                .runtime
                .zones
                .get_mut(zone_name)
                .unwrap_or_else(|| panic!("zone '{}' not found", zone_name));

            match zone {
                RuntimeZone::Grid { .. } => {
                    let col = placement.col.expect("grid placement requires col");
                    let row = placement.row.expect("grid placement requires row");
                    zone.grid_set(col, row, Some(cid));
                }
                RuntimeZone::OrderedStack { components } => {
                    components.push(cid);
                }
                RuntimeZone::Set { components } => {
                    components.push(cid);
                }
                RuntimeZone::SingleSlot { component } => {
                    *component = Some(cid);
                }
                _ => panic!("unsupported zone type for placement"),
            }
        }

        if let Some(pz) = &placement.player_zone {
            let player = session
                .runtime
                .players
                .get_mut(&pz.player)
                .unwrap_or_else(|| panic!("player '{}' not found", pz.player));
            let zone = player
                .zones
                .get_mut(&pz.zone)
                .unwrap_or_else(|| panic!("player zone '{}' not found", pz.zone));

            match zone {
                RuntimeZone::OrderedStack { components } => {
                    components.push(cid);
                }
                RuntimeZone::Set { components } => {
                    components.push(cid);
                }
                RuntimeZone::SingleSlot { component } => {
                    *component = Some(cid);
                }
                _ => panic!("unsupported player zone type for placement"),
            }
        }

        if let Some(tz) = &placement.track_zone {
            let zone = session
                .runtime
                .zones
                .get_mut(&tz.zone)
                .unwrap_or_else(|| panic!("track zone '{}' not found", tz.zone));

            if let RuntimeZone::Track { positions } = zone {
                if tz.position < positions.len() {
                    positions[tz.position].push(cid);
                } else {
                    panic!(
                        "track position {} out of range (len={})",
                        tz.position,
                        positions.len()
                    );
                }
            } else {
                panic!("zone '{}' is not a Track", tz.zone);
            }
        }
    }

    // Set global counters
    for (k, v) in &tc.setup.counters {
        session.runtime.counters.insert(k.clone(), *v);
    }

    // Set per-player counters
    for (player_name, counters) in &tc.setup.player_counters {
        let player = session
            .runtime
            .players
            .get_mut(player_name)
            .unwrap_or_else(|| panic!("player '{}' not found", player_name));
        for (k, v) in counters {
            player.counters.insert(k.clone(), *v);
        }
    }

    // Set per-player zone counters (counter-type zones owned by players)
    for (player_name, zone_counters) in &tc.setup.player_zone_counters {
        let player = session
            .runtime
            .players
            .get_mut(player_name)
            .unwrap_or_else(|| panic!("player '{}' not found", player_name));
        for (zone_name, value) in zone_counters {
            let zone = player
                .zones
                .get_mut(zone_name)
                .unwrap_or_else(|| panic!("player zone '{}' not found", zone_name));
            if let RuntimeZone::Counter { value: v } = zone {
                *v = *value;
            } else {
                panic!("player zone '{}' is not a Counter", zone_name);
            }
        }
    }

    // Set pot zone value if specified
    if let Some(pot_val) = tc.setup.pot_zone_value {
        if let Some(zone) = session.runtime.zones.get_mut("pot_zone") {
            if let RuntimeZone::Counter { value } = zone {
                *value = pot_val;
            }
        }
    }

    // Advance turns
    for _ in 0..tc.setup.advance_turns {
        session.advance_turn();
    }

    session
}

// ---------------------------------------------------------------------------
// Round-trip assertion
// ---------------------------------------------------------------------------

/// Serialize wire state to JSON, parse back, re-serialize, compare.
/// Comparison is done at the serde_json::Value level to ignore
/// insignificant formatting differences.
fn assert_round_trip(wire: &GameState, test_name: &str) {
    // First serialization
    let json1 = serde_json::to_string(wire)
        .unwrap_or_else(|e| panic!("[{test_name}] first serialization failed: {e}"));

    // Parse back
    let parsed: GameState = GameState::from_json(&json1)
        .unwrap_or_else(|e| panic!("[{test_name}] parse failed: {e}"));

    // Second serialization
    let json2 = serde_json::to_string(&parsed)
        .unwrap_or_else(|e| panic!("[{test_name}] second serialization failed: {e}"));

    // Compare as serde_json::Value for structural equality
    let val1: serde_json::Value = serde_json::from_str(&json1)
        .unwrap_or_else(|e| panic!("[{test_name}] parsing json1 to Value failed: {e}"));
    let val2: serde_json::Value = serde_json::from_str(&json2)
        .unwrap_or_else(|e| panic!("[{test_name}] parsing json2 to Value failed: {e}"));

    assert_eq!(
        val1, val2,
        "[{test_name}] round-trip mismatch.\nFirst:  {json1}\nSecond: {json2}"
    );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn round_trip_all_vectors() {
    let suite = load_test_suite();

    for tc in &suite.test_cases {
        let session = setup_session(tc);
        let wire = session.to_wire_state();
        assert_round_trip(&wire, &tc.name);
    }
}

#[test]
fn round_trip_empty_tic_tac_toe() {
    let suite = load_test_suite();
    let tc = suite
        .test_cases
        .iter()
        .find(|t| t.name == "empty_tic_tac_toe")
        .expect("test case not found");
    let session = setup_session(tc);
    let wire = session.to_wire_state();

    // Verify expected structure before round-trip
    assert_eq!(wire.status, GameStatus::Setup);
    assert!(wire.zones.contains_key("board"));
    if let ZoneState::Grid { ref cells } = wire.zones["board"] {
        assert!(cells.is_empty(), "empty board should have no cells");
    } else {
        panic!("board should be a Grid zone");
    }

    assert_round_trip(&wire, &tc.name);
}

#[test]
fn round_trip_mid_game_tic_tac_toe() {
    let suite = load_test_suite();
    let tc = suite
        .test_cases
        .iter()
        .find(|t| t.name == "mid_game_tic_tac_toe")
        .expect("test case not found");
    let session = setup_session(tc);
    let wire = session.to_wire_state();

    // Verify we have components on the board
    assert_eq!(wire.status, GameStatus::InProgress);
    if let ZoneState::Grid { ref cells } = wire.zones["board"] {
        assert_eq!(cells.len(), 5, "should have 5 marks placed");
    } else {
        panic!("board should be a Grid zone");
    }

    assert_round_trip(&wire, &tc.name);
}

#[test]
fn round_trip_chess_opening() {
    let suite = load_test_suite();
    let tc = suite
        .test_cases
        .iter()
        .find(|t| t.name == "chess_opening")
        .expect("test case not found");
    let session = setup_session(tc);
    let wire = session.to_wire_state();

    // Verify multiple piece types
    if let ZoneState::Grid { ref cells } = wire.zones["board"] {
        assert_eq!(cells.len(), 16, "should have 16 pieces placed");
    } else {
        panic!("board should be a Grid zone");
    }

    assert_round_trip(&wire, &tc.name);
}

#[test]
fn round_trip_poker_counters() {
    let suite = load_test_suite();
    let tc = suite
        .test_cases
        .iter()
        .find(|t| t.name == "poker_like_with_counters")
        .expect("test case not found");
    let session = setup_session(tc);
    let wire = session.to_wire_state();

    // Verify global counters
    assert!(wire.counters.contains_key("pot"));
    assert!(wire.counters.contains_key("round"));

    // Verify per-player counters
    for (_, player) in &wire.players {
        assert!(!player.counters.is_empty());
    }

    assert_round_trip(&wire, &tc.name);
}

#[test]
fn round_trip_per_player_zones() {
    let suite = load_test_suite();
    let tc = suite
        .test_cases
        .iter()
        .find(|t| t.name == "board_game_with_per_player_zones")
        .expect("test case not found");
    let session = setup_session(tc);
    let wire = session.to_wire_state();

    // Verify per-player zones exist
    for (_, player) in &wire.players {
        assert!(player.zones.contains_key("reserve"));
        assert!(player.zones.contains_key("power"));
    }

    // Verify track zone has components
    if let ZoneState::Track { ref positions } = wire.zones["score_track"] {
        assert!(
            !positions.is_empty(),
            "score_track should have components on it"
        );
    } else {
        panic!("score_track should be a Track zone");
    }

    assert_round_trip(&wire, &tc.name);
}
