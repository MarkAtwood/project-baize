use std::collections::HashSet;

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
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

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
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();
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

fn grid_10x10_def() -> GameDefinition {
    serde_json::from_str(
        r#"{
        "game": { "name": "Grid Test", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "dimensions": [10, 10], "visibility": "public" }
        },
        "components": {
            "ship": {
                "owner": "per_player",
                "types": {
                    "carrier": { "span": 5 },
                    "destroyer": { "span": 2 }
                }
            }
        },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "win", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap()
}

#[test]
fn grid_place_span_horizontal() {
    let def = grid_10x10_def();
    let mut session = GameSession::new(def).unwrap();

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "carrier-A-0".into(),
        component_type: "carrier".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("board").unwrap();
    let cells = zone.grid_place_span(2, 3, true, 5, cid).unwrap();

    assert_eq!(cells.len(), 5);
    assert_eq!(cells, vec![(2, 3), (3, 3), (4, 3), (5, 3), (6, 3)]);

    // All 5 cells should contain the same ComponentId
    for &(col, row) in &cells {
        assert_eq!(zone.grid_get(col, row), Some(cid));
    }

    // Adjacent cells should be empty
    assert!(zone.grid_get(1, 3).is_none());
    assert!(zone.grid_get(7, 3).is_none());
}

#[test]
fn grid_place_span_vertical() {
    let def = grid_10x10_def();
    let mut session = GameSession::new(def).unwrap();

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "destroyer-A-0".into(),
        component_type: "destroyer".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("board").unwrap();
    let cells = zone.grid_place_span(0, 0, false, 2, cid).unwrap();

    assert_eq!(cells, vec![(0, 0), (0, 1)]);
    assert_eq!(zone.grid_get(0, 0), Some(cid));
    assert_eq!(zone.grid_get(0, 1), Some(cid));
}

#[test]
fn grid_place_span_out_of_bounds() {
    let def = grid_10x10_def();
    let mut session = GameSession::new(def).unwrap();

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "carrier-A-0".into(),
        component_type: "carrier".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("board").unwrap();
    // Span of 5 starting at col 8 would go to col 12 — out of bounds
    let result = zone.grid_place_span(8, 0, true, 5, cid);
    assert!(result.is_err());
}

#[test]
fn grid_place_span_overlap() {
    let def = grid_10x10_def();
    let mut session = GameSession::new(def).unwrap();

    let cid1 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "carrier-A-0".into(),
        component_type: "carrier".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let cid2 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "destroyer-A-0".into(),
        component_type: "destroyer".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("board").unwrap();
    // Place carrier at (0,0) horizontal, spanning cols 0-4
    zone.grid_place_span(0, 0, true, 5, cid1).unwrap();

    // Try to place destroyer at (3,0) horizontal — overlaps at col 3 and 4
    let result = zone.grid_place_span(3, 0, true, 2, cid2);
    assert!(result.is_err());
}

#[test]
fn grid_remove_span() {
    let def = grid_10x10_def();
    let mut session = GameSession::new(def).unwrap();

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "carrier-A-0".into(),
        component_type: "carrier".into(),
        owner: Some("A".into()),
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
                orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("board").unwrap();
    let cells = zone.grid_place_span(0, 0, true, 5, cid).unwrap();

    // All cells occupied
    assert_eq!(zone.grid_get(0, 0), Some(cid));
    assert_eq!(zone.grid_get(4, 0), Some(cid));

    // Remove span
    zone.grid_remove_span(&cells);

    // All cells should now be empty
    for &(col, row) in &cells {
        assert!(zone.grid_get(col, row).is_none());
    }
}

// --- valid_cells mask tests ---

/// Helper: create a 3x3 grid with no valid_cells mask (all cells valid).
fn grid_3x3_no_mask() -> RuntimeZone {
    RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    }
}

/// Helper: create a 3x3 grid where only the diagonal cells (0,0), (1,1), (2,2) are valid.
fn grid_3x3_diagonal_mask() -> RuntimeZone {
    // coordinate tuples: (0,0), (1,1), (2,2)
    RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: Some(HashSet::from([(0, 0), (1, 1), (2, 2)])),
    }
}

#[test]
fn grid_cell_valid_no_mask() {
    let grid = grid_3x3_no_mask();

    // All in-bounds cells are valid
    for row in 0..3u32 {
        for col in 0..3u32 {
            assert!(grid.grid_cell_valid(col, row), "({col},{row}) should be valid");
        }
    }

    // Out-of-bounds cells are invalid
    assert!(!grid.grid_cell_valid(3, 0));
    assert!(!grid.grid_cell_valid(0, 3));
    assert!(!grid.grid_cell_valid(3, 3));
    assert!(!grid.grid_cell_valid(100, 100));
}

#[test]
fn grid_cell_valid_with_mask() {
    let grid = grid_3x3_diagonal_mask();

    // Diagonal cells are valid
    assert!(grid.grid_cell_valid(0, 0));
    assert!(grid.grid_cell_valid(1, 1));
    assert!(grid.grid_cell_valid(2, 2));

    // Off-diagonal in-bounds cells are invalid
    assert!(!grid.grid_cell_valid(1, 0));
    assert!(!grid.grid_cell_valid(0, 1));
    assert!(!grid.grid_cell_valid(2, 0));
    assert!(!grid.grid_cell_valid(0, 2));
    assert!(!grid.grid_cell_valid(2, 1));
    assert!(!grid.grid_cell_valid(1, 2));

    // Out-of-bounds still invalid
    assert!(!grid.grid_cell_valid(3, 3));
}

#[test]
fn grid_cell_valid_non_grid_zone() {
    let zone = RuntimeZone::Set { components: Vec::new() };
    // grid_cell_valid on a non-grid zone always returns false
    assert!(!zone.grid_cell_valid(0, 0));
}

#[test]
fn grid_get_set_masked_out_cell() {
    let mut grid = grid_3x3_diagonal_mask();
    let c1 = ComponentId(0);

    // Set on a masked-out cell (1,0) returns None (no-op)
    let prev = grid.grid_set(1, 0, Some(c1));
    assert!(prev.is_none());

    // Get on that masked-out cell returns None
    assert!(grid.grid_get(1, 0).is_none());

    // The underlying storage should still have None (set was truly a no-op)
    if let RuntimeZone::Grid { storage, .. } = &grid {
        assert!(storage.get(1, 0).is_none());
    }
}

#[test]
fn grid_get_set_valid_cell() {
    let mut grid = grid_3x3_diagonal_mask();
    let c1 = ComponentId(0);

    // Set on a valid cell (1,1) works normally
    let prev = grid.grid_set(1, 1, Some(c1));
    assert!(prev.is_none()); // was empty

    // Get on the valid cell returns the component
    assert_eq!(grid.grid_get(1, 1), Some(c1));

    // Replace it
    let c2 = ComponentId(1);
    let displaced = grid.grid_set(1, 1, Some(c2));
    assert_eq!(displaced, Some(c1)); // previous component returned
    assert_eq!(grid.grid_get(1, 1), Some(c2));
}

#[test]
fn grid_push_masked_cell_is_noop() {
    let mut grid = grid_3x3_diagonal_mask();
    let c1 = ComponentId(0);

    // Push to a masked-out cell (0,1) — should be a no-op
    grid.grid_push(0, 1, c1);

    // Cell should still be empty
    assert!(grid.grid_get(0, 1).is_none());
    assert_eq!(grid.count(), 0);
}

#[test]
fn grid_pop_masked_cell_returns_none() {
    let mut grid = grid_3x3_diagonal_mask();

    // Pop from a masked-out cell (0,1) — should return None
    assert!(grid.grid_pop(0, 1).is_none());
}

#[test]
fn grid_push_pop_valid_cell() {
    let mut grid = grid_3x3_diagonal_mask();
    let c1 = ComponentId(0);
    let c2 = ComponentId(1);

    // Push to a valid cell (0,0) works normally
    grid.grid_push(0, 0, c1);
    assert_eq!(grid.grid_get(0, 0), Some(c1));

    // Push again onto (0,0) — c2 becomes new top, c1 goes to stack
    grid.grid_push(0, 0, c2);
    assert_eq!(grid.grid_get(0, 0), Some(c2));

    // Pop returns c2 (top), then c1
    assert_eq!(grid.grid_pop(0, 0), Some(c2));
    assert_eq!(grid.grid_get(0, 0), Some(c1));
    assert_eq!(grid.grid_pop(0, 0), Some(c1));
    assert!(grid.grid_get(0, 0).is_none());
}

#[test]
fn grid_stack_masked_cell() {
    let grid = grid_3x3_diagonal_mask();

    // grid_stack on masked-out cell returns empty vec
    assert!(grid.grid_stack(1, 0).is_empty());
}

#[test]
fn grid_place_span_masked_cell() {
    let mut grid = grid_3x3_diagonal_mask();
    let c1 = ComponentId(0);

    // Span of 2 starting at (0,0) horizontal would need (0,0) and (1,0).
    // (0,0) is valid but (1,0) is masked out, so this should fail.
    let result = grid.grid_place_span(0, 0, true, 2, c1);
    assert!(result.is_err());
}

#[test]
fn from_definition_valid_cells_populated() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Mask Test", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
                "valid_cells": [[0, 0], [1, 1], [2, 2]]
            }
        },
        "components": { "piece": { "count": 3 } },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let session = GameSession::new(def).unwrap();
    let board = session.runtime.zones.get("board").unwrap();

    // Check that valid_cells is correctly populated
    if let RuntimeZone::Grid { valid_cells, storage, .. } = board {
        let vc = valid_cells.as_ref().expect("valid_cells should be Some");
        assert_eq!(storage.dimensions(), Some((3, 3)));
        assert_eq!(vc.len(), 3);
        assert!(vc.contains(&(0, 0)));
        assert!(vc.contains(&(1, 1)));
        assert!(vc.contains(&(2, 2)));
    } else {
        panic!("board should be a Grid");
    }

    // Verify via grid_cell_valid
    assert!(board.grid_cell_valid(0, 0));
    assert!(board.grid_cell_valid(1, 1));
    assert!(board.grid_cell_valid(2, 2));
    assert!(!board.grid_cell_valid(1, 0));
    assert!(!board.grid_cell_valid(0, 1));
}

#[test]
fn from_definition_valid_cells_filters_out_of_bounds() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Mask OOB", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
                "valid_cells": [[0, 0], [1, 1], [99, 99], [3, 0], [0, 3]]
            }
        },
        "components": { "piece": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let session = GameSession::new(def).unwrap();
    let board = session.runtime.zones.get("board").unwrap();

    if let RuntimeZone::Grid { valid_cells, .. } = board {
        let vc = valid_cells.as_ref().expect("valid_cells should be Some");
        // Only (0,0) and (1,1) should survive; (99,99), (3,0), (0,3) are out of bounds
        assert_eq!(vc.len(), 2);
        assert!(vc.contains(&(0, 0)));
        assert!(vc.contains(&(1, 1)));
    } else {
        panic!("board should be a Grid");
    }
}

// --- Graph zone tests ---
//
// Test graph: 5 nodes, 5 edges
//   Nodes: A, B, C, D, E
//   Edges: A-B, A-C, B-C, B-D, D-E

fn graph_zone_def() -> GameDefinition {
    serde_json::from_str(
        r#"{
        "game": { "name": "Graph Test", "players": ["P1", "P2"], "information": "perfect" },
        "zones": {
            "map": {
                "zone_type": "graph",
                "visibility": "public",
                "nodes": ["A", "B", "C", "D", "E"],
                "edges": [["A", "B"], ["A", "C"], ["B", "C"], ["B", "D"], ["D", "E"]]
            }
        },
        "components": { "token": { "count": 10 } },
        "turn_order": { "type": "alternating", "players": ["P1", "P2"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap()
}

#[test]
fn graph_construction_from_definition() {
    let def = graph_zone_def();
    let session = GameSession::new(def).unwrap();
    let zone = session.runtime.zones.get("map").unwrap();

    if let RuntimeZone::Graph { node_names, adjacency, .. } = zone {
        assert_eq!(node_names.len(), 5);
        assert_eq!(node_names, &["A", "B", "C", "D", "E"]);
        // A (0) adjacent to B (1), C (2)
        let mut a_adj = adjacency[0].clone();
        a_adj.sort();
        assert_eq!(a_adj, vec![1, 2]);
        // B (1) adjacent to A (0), C (2), D (3)
        let mut b_adj = adjacency[1].clone();
        b_adj.sort();
        assert_eq!(b_adj, vec![0, 2, 3]);
        // E (4) adjacent to D (3) only
        assert_eq!(adjacency[4], vec![3]);
    } else {
        panic!("map should be a Graph zone");
    }
}

#[test]
fn graph_get_empty_returns_none() {
    let def = graph_zone_def();
    let session = GameSession::new(def).unwrap();
    let zone = session.runtime.zones.get("map").unwrap();

    assert!(zone.graph_get("A").is_none());
    assert!(zone.graph_get("E").is_none());
}

#[test]
fn graph_set_and_get() {
    let def = graph_zone_def();
    let mut session = GameSession::new(def).unwrap();

    let cid = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-0".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("map").unwrap();
    zone.graph_set("B", Some(cid));
    assert_eq!(zone.graph_get("B"), Some(cid));
}

#[test]
fn graph_set_returns_previous() {
    let def = graph_zone_def();
    let mut session = GameSession::new(def).unwrap();

    let c1 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-0".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let c2 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-1".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("map").unwrap();
    let prev1 = zone.graph_set("A", Some(c1));
    assert!(prev1.is_none());

    let prev2 = zone.graph_set("A", Some(c2));
    assert_eq!(prev2, Some(c1));
    assert_eq!(zone.graph_get("A"), Some(c2));
}

#[test]
fn graph_unknown_node_returns_none() {
    let def = graph_zone_def();
    let mut session = GameSession::new(def).unwrap();
    let zone = session.runtime.zones.get_mut("map").unwrap();

    assert!(zone.graph_get("Z").is_none());
    assert!(zone.graph_set("Z", Some(ComponentId(99))).is_none());
}

#[test]
fn graph_neighbors() {
    let def = graph_zone_def();
    let session = GameSession::new(def).unwrap();
    let zone = session.runtime.zones.get("map").unwrap();

    // A -> [B, C]
    let mut a_neigh: Vec<&str> = zone.graph_neighbors("A");
    a_neigh.sort();
    assert_eq!(a_neigh, vec!["B", "C"]);

    // D -> [B, E]
    let mut d_neigh: Vec<&str> = zone.graph_neighbors("D");
    d_neigh.sort();
    assert_eq!(d_neigh, vec!["B", "E"]);

    // Unknown node -> empty
    assert!(zone.graph_neighbors("Z").is_empty());
}

#[test]
fn graph_count() {
    let def = graph_zone_def();
    let mut session = GameSession::new(def).unwrap();

    // Empty graph
    assert_eq!(session.runtime.zones.get("map").unwrap().count(), 0);

    let c1 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-0".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let c2 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-1".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let c3 = session.runtime.components.insert(ComponentData {
        id: ComponentId(0),
        string_id: "token-2".into(),
        component_type: "token".into(),
        owner: None,
        facing: None,
        state: None,
        properties: Default::default(),
        span_cells: Vec::new(),
        orientation: None,
    }).unwrap();

    let zone = session.runtime.zones.get_mut("map").unwrap();
    zone.graph_set("A", Some(c1));
    zone.graph_set("C", Some(c2));
    zone.graph_set("E", Some(c3));
    assert_eq!(zone.count(), 3);
}

#[test]
fn graph_node_properties() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Graph Props", "players": ["P1", "P2"], "information": "perfect" },
        "zones": {
            "map": {
                "zone_type": "graph",
                "visibility": "public",
                "nodes": ["A", "B", "C"],
                "edges": [["A", "B"]],
                "node_properties": {
                    "A": { "color": "red", "value": 10 },
                    "C": { "color": "blue" }
                }
            }
        },
        "components": { "token": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["P1", "P2"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let session = GameSession::new(def).unwrap();
    let zone = session.runtime.zones.get("map").unwrap();

    if let RuntimeZone::Graph { node_properties, name_to_index, .. } = zone {
        // A (index 0) has color=red, value=10
        let a_idx = name_to_index.get("A").unwrap();
        let a_props = node_properties.get(a_idx).unwrap();
        assert_eq!(a_props.get("color").unwrap(), &serde_json::json!("red"));
        assert_eq!(a_props.get("value").unwrap(), &serde_json::json!(10));

        // C (index 2) has color=blue
        let c_idx = name_to_index.get("C").unwrap();
        let c_props = node_properties.get(c_idx).unwrap();
        assert_eq!(c_props.get("color").unwrap(), &serde_json::json!("blue"));

        // B has no properties
        let b_idx = name_to_index.get("B").unwrap();
        assert!(node_properties.get(b_idx).is_none());
    } else {
        panic!("map should be a Graph zone");
    }
}

#[test]
fn graph_missing_nodes_errors() {
    let result: std::result::Result<GameDefinition, _> = serde_json::from_str(
        r#"{
        "game": { "name": "No Nodes", "players": ["P1", "P2"], "information": "perfect" },
        "zones": {
            "map": {
                "zone_type": "graph",
                "visibility": "public"
            }
        },
        "components": { "token": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["P1", "P2"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    );

    // This may fail at deserialization or at session creation
    match result {
        Ok(def) => {
            let session_result = GameSession::new(def);
            assert!(session_result.is_err(), "should fail: graph zone requires nodes");
        }
        Err(_) => {
            // Also acceptable: deserialization itself failed
        }
    }
}

#[test]
fn graph_unknown_node_in_edge_errors() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Bad Edge", "players": ["P1", "P2"], "information": "perfect" },
        "zones": {
            "map": {
                "zone_type": "graph",
                "visibility": "public",
                "nodes": ["A", "B"],
                "edges": [["A", "Z"]]
            }
        },
        "components": { "token": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["P1", "P2"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let result = GameSession::new(def);
    assert!(result.is_err(), "should fail: unknown node Z in edge");
}
