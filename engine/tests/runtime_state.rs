use baize_engine::runtime::*;
use baize_engine::state::*;
use baize_engine::GameDefinition;

fn tic_tac_toe_def() -> GameDefinition {
    serde_json::from_str(
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
    .unwrap()
}

#[test]
fn session_init() {
    let def = tic_tac_toe_def();
    let session = GameSession::new(def).unwrap();

    assert_eq!(session.runtime.status, GameStatus::Setup);
    assert_eq!(session.runtime.players.len(), 2);
    assert!(session.runtime.players.contains_key("X"));
    assert!(session.runtime.players.contains_key("O"));
    assert_eq!(session.runtime.zones.len(), 1);
    assert!(session.runtime.zones.contains_key("board"));
    assert!(session.is_perfect_information());
}

#[test]
fn current_player() {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();

    assert_eq!(session.current_player(), Some("X"));
    session.advance_turn();
    assert_eq!(session.current_player(), Some("O"));
    session.advance_turn();
    assert_eq!(session.current_player(), Some("X"));
}

#[test]
fn grid_operations() {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();

    // Place a component at (1, 1) — center
    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "mark-x-0".into(),
        component_type: "mark".into(),
        owner: Some("X".into()),
        facing: None,
        state: None,
        properties: Default::default(),
    });

    let board = session.runtime.zones.get_mut("board").unwrap();
    assert!(board.grid_get(1, 1).is_none());
    board.grid_set(1, 1, Some(cid));
    assert_eq!(board.grid_get(1, 1), Some(cid));
    assert_eq!(board.count(), 1);

    // Out of bounds returns None
    assert!(board.grid_get(5, 5).is_none());
}

#[test]
fn stack_operations() {
    let mut zone = RuntimeZone::OrderedStack {
        components: Vec::new(),
    };

    let c1 = ComponentId(0);
    let c2 = ComponentId(1);
    let c3 = ComponentId(2);

    zone.stack_push(c1);
    zone.stack_push(c2);
    zone.stack_push(c3);
    assert_eq!(zone.count(), 3);

    assert_eq!(zone.stack_pop(), Some(c3));
    assert_eq!(zone.stack_pop(), Some(c2));
    assert_eq!(zone.count(), 1);
}

#[test]
fn set_operations() {
    let mut zone = RuntimeZone::Set {
        components: Vec::new(),
    };

    let c1 = ComponentId(0);
    let c2 = ComponentId(1);

    zone.set_add(c1);
    zone.set_add(c2);
    assert_eq!(zone.count(), 2);

    assert!(zone.set_remove(c1));
    assert_eq!(zone.count(), 1);
    assert!(!zone.set_remove(c1)); // already removed
}

#[test]
fn wire_round_trip() {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();
    session.runtime.status = GameStatus::InProgress;

    // Place a mark
    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "mark-x-0".into(),
        component_type: "mark".into(),
        owner: Some("X".into()),
        facing: None,
        state: None,
        properties: Default::default(),
    });
    session
        .runtime
        .zones
        .get_mut("board")
        .unwrap()
        .grid_set(1, 1, Some(cid));

    // Convert to wire format and verify
    let wire = session.to_wire_state();
    assert_eq!(wire.turn, "X");
    assert_eq!(wire.status, GameStatus::InProgress);

    // Serialize and re-parse
    let json = serde_json::to_string_pretty(&wire).unwrap();
    let parsed: GameState = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.turn, "X");
}

#[test]
fn state_hashing() {
    let def = tic_tac_toe_def();
    let session = GameSession::new(def).unwrap();

    let h1 = session.compute_state_hash();
    let h2 = session.compute_state_hash();
    assert_eq!(h1, h2); // deterministic

    // Different state should produce different hash
    let def2 = tic_tac_toe_def();
    let mut session2 = GameSession::new(def2).unwrap();
    session2.advance_turn();
    let h3 = session2.compute_state_hash();
    assert_ne!(h1, h3);
}

#[test]
fn per_player_zones() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Card Game", "players": { "min": 2, "max": 4 }, "information": "imperfect" },
        "zones": {
            "deck": { "zone_type": "ordered_stack", "capacity": 52, "visibility": "hidden" },
            "hand": { "zone_type": "set", "per_player": true, "capacity": 5, "visibility": { "private": "owner" } }
        },
        "components": {
            "card": { "count": 52 }
        },
        "turn_order": { "type": "round_robin" },
        "end_conditions": [{ "result": "win", "condition": "hand_empty" }],
        "authority": { "server_only": ["deal"], "client_verifiable": ["play_card"] }
    }"#,
    )
    .unwrap();

    let session = GameSession::new(def).unwrap();

    // Shared zone
    assert!(session.runtime.zones.contains_key("deck"));
    // Per-player zones are on the player, not on the top-level zones
    assert!(!session.runtime.zones.contains_key("hand"));

    // Each player has their own hand
    for (_, player) in &session.runtime.players {
        assert!(player.zones.contains_key("hand"));
    }
}
