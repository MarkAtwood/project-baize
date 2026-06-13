//! Tests for engine invariant assertions: invalid ComponentIds, out-of-bounds
//! grid access, invalid zone dimensions, and other impossible states that
//! should fail loudly rather than silently corrupt.

use std::collections::HashSet;

use baize_engine::error::BaizeError;
use baize_engine::runtime::*;
use baize_engine::GameDefinition;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

fn make_component(table: &mut ComponentTable, name: &str) -> ComponentId {
    table
        .insert(ComponentData {
            id: ComponentId(0),
            string_id: name.to_string(),
            component_type: "mark".into(),
            owner: Some("X".into()),
            facing: None,
            state: None,
            properties: Default::default(),
            span_cells: Vec::new(),
            orientation: None,
        })
        .unwrap()
}

// ---------------------------------------------------------------------------
// ComponentId validity
// ---------------------------------------------------------------------------

#[test]
fn component_table_get_invalid_id_returns_none() {
    let table = ComponentTable::new();
    // Out-of-range IDs return None (not panic) in release mode
    assert!(table.get(ComponentId(0)).is_none());
    assert!(table.get(ComponentId(999)).is_none());
    assert!(table.get(ComponentId(u32::MAX)).is_none());
}

#[test]
fn component_table_get_mut_invalid_id_returns_none() {
    let mut table = ComponentTable::new();
    assert!(table.get_mut(ComponentId(0)).is_none());
    assert!(table.get_mut(ComponentId(42)).is_none());
}

#[test]
fn component_table_get_valid_id_returns_data() {
    let mut table = ComponentTable::new();
    let cid = make_component(&mut table, "test-0");
    assert!(table.get(cid).is_some());
    assert_eq!(table.get(cid).unwrap().string_id, "test-0");
}

#[test]
fn component_table_insert_returns_sequential_ids() {
    let mut table = ComponentTable::new();
    let c0 = make_component(&mut table, "a");
    let c1 = make_component(&mut table, "b");
    let c2 = make_component(&mut table, "c");
    assert_eq!(c0.0, 0);
    assert_eq!(c1.0, 1);
    assert_eq!(c2.0, 2);
    assert_eq!(table.len(), 3);
}

// ---------------------------------------------------------------------------
// Grid bounds
// ---------------------------------------------------------------------------

#[test]
fn grid_get_out_of_bounds_returns_none() {
    let zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    assert!(zone.grid_get(3, 0).is_none());
    assert!(zone.grid_get(0, 3).is_none());
    assert!(zone.grid_get(100, 100).is_none());
    assert!(zone.grid_get(u32::MAX, u32::MAX).is_none());
}

#[test]
fn grid_set_out_of_bounds_is_noop() {
    let mut zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    let cid = ComponentId(0);
    // Setting out of bounds returns None and doesn't modify state
    assert!(zone.grid_set(3, 0, Some(cid)).is_none());
    assert!(zone.grid_set(0, 3, Some(cid)).is_none());
    assert_eq!(zone.count(), 0);
}

#[test]
fn grid_push_out_of_bounds_is_noop() {
    let mut zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(2, 2),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    assert!(zone.grid_push(5, 5, ComponentId(0)).is_err());
    assert_eq!(zone.count(), 0);
}

#[test]
fn grid_pop_out_of_bounds_returns_none() {
    let mut zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(2, 2),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    assert!(zone.grid_pop(5, 5).is_none());
}

#[test]
fn grid_stack_out_of_bounds_returns_empty() {
    let zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(2, 2),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    assert!(zone.grid_stack(5, 5).is_empty());
}

#[test]
fn grid_cell_valid_rejects_u32_max() {
    let zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    assert!(!zone.grid_cell_valid(u32::MAX, 0));
    assert!(!zone.grid_cell_valid(0, u32::MAX));
    assert!(!zone.grid_cell_valid(u32::MAX, u32::MAX));
}

// ---------------------------------------------------------------------------
// Zone creation with invalid dimensions
// ---------------------------------------------------------------------------

#[test]
fn grid_zone_missing_dimensions_errors() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "No Dims", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "visibility": "public" }
        },
        "components": { "piece": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let result = GameSession::new(def);
    assert!(result.is_err());
    match result.unwrap_err() {
        BaizeError::Validation(msg) => assert!(msg.contains("dimensions")),
        other => panic!("expected Validation error, got: {other:?}"),
    }
}

#[test]
fn track_zone_zero_length_errors() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Zero Track", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "path": { "zone_type": "track", "length": 0, "visibility": "public" }
        },
        "components": { "piece": { "count": 1 } },
        "turn_order": { "type": "alternating", "players": ["A", "B"] },
        "end_conditions": [{ "result": "draw", "condition": "false" }],
        "authority": { "server_only": [], "client_verifiable": ["all"] }
    }"#,
    )
    .unwrap();

    let result = GameSession::new(def);
    assert!(result.is_err());
    match result.unwrap_err() {
        BaizeError::Validation(msg) => assert!(msg.contains("track")),
        other => panic!("expected Validation error, got: {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// Grid place_span with invalid inputs
// ---------------------------------------------------------------------------

#[test]
fn grid_place_span_zero_span_succeeds_with_empty_result() {
    let mut zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(5, 5),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    let cid = ComponentId(0);
    let result = zone.grid_place_span(0, 0, true, 0, cid).unwrap();
    assert!(result.is_empty());
    assert_eq!(zone.count(), 0);
}

#[test]
fn grid_place_span_exceeds_grid_boundary() {
    let mut zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: None,
    cell_fog: None,
    fog_config: None,
    };

    let cid = ComponentId(0);
    // Span of 4 on a 3-wide grid from col 0 goes out of bounds
    let result = zone.grid_place_span(0, 0, true, 4, cid);
    assert!(result.is_err());
}

// ---------------------------------------------------------------------------
// Non-grid zone operations on wrong zone types
// ---------------------------------------------------------------------------

#[test]
fn stack_pop_on_empty_returns_none() {
    let mut zone = RuntimeZone::OrderedStack {
        components: Vec::new(),
    };
    assert!(zone.stack_pop().is_none());
}

#[test]
fn set_remove_nonexistent_returns_false() {
    let mut zone = RuntimeZone::Set {
        components: Vec::new(),
    };
    assert!(!zone.set_remove(ComponentId(42)));
}

#[test]
fn grid_operations_on_non_grid_zone() {
    let zone = RuntimeZone::OrderedStack {
        components: Vec::new(),
    };

    // All grid operations on non-grid zones should return None/empty/false
    assert!(!zone.grid_cell_valid(0, 0));
    assert!(zone.grid_get(0, 0).is_none());
    assert!(zone.grid_stack(0, 0).is_empty());
}

#[test]
fn graph_operations_on_non_graph_zone() {
    let zone = RuntimeZone::Set {
        components: Vec::new(),
    };

    assert!(zone.graph_get("node").is_none());
    assert!(zone.graph_neighbors("node").is_empty());
}

// ---------------------------------------------------------------------------
// Turn index integrity
// ---------------------------------------------------------------------------

#[test]
fn advance_turn_wraps_correctly() {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();

    assert_eq!(session.runtime.turn_index, 0);
    session.advance_turn();
    assert_eq!(session.runtime.turn_index, 1);
    session.advance_turn();
    assert_eq!(session.runtime.turn_index, 0); // wraps
}

#[test]
fn current_player_valid_for_all_indices() {
    let def = tic_tac_toe_def();
    let mut session = GameSession::new(def).unwrap();

    for _ in 0..10 {
        let player = session.current_player();
        assert!(player.is_some(), "current_player should always be Some");
        let name = player.unwrap();
        assert!(
            session.runtime.players.contains_key(name),
            "current_player {:?} not in players map",
            name
        );
        session.advance_turn();
    }
}

// ---------------------------------------------------------------------------
// Grid with valid_cells mask edge cases
// ---------------------------------------------------------------------------

#[test]
fn grid_with_empty_valid_cells_mask() {
    // A grid where NO cells are valid
    let zone = RuntimeZone::Grid {
        storage: GridStorage::new_dense(3, 3),
        stacks: Default::default(),
        stacking_limit: 1,
        cell_properties: Default::default(),
        valid_cells: Some(HashSet::new()),
    cell_fog: None,
    fog_config: None,
    };

    // Every cell should be invalid
    for row in 0..3u32 {
        for col in 0..3u32 {
            assert!(!zone.grid_cell_valid(col, row));
            assert!(zone.grid_get(col, row).is_none());
        }
    }
}

// ---------------------------------------------------------------------------
// Counter zone
// ---------------------------------------------------------------------------

#[test]
fn counter_zone_count_is_zero() {
    let zone = RuntimeZone::Counter { value: 42 };
    assert_eq!(zone.count(), 0);
}

// ---------------------------------------------------------------------------
// Dynamic grid (0x0)
// ---------------------------------------------------------------------------

#[test]
fn dynamic_grid_zero_dimensions() {
    let def: GameDefinition = serde_json::from_str(
        r#"{
        "game": { "name": "Dynamic", "players": ["A", "B"], "information": "perfect" },
        "zones": {
            "board": { "zone_type": "grid", "visibility": "public", "dynamic": true }
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

    // Dynamic grid with no dimensions: sparse unbounded.
    // All coordinates are valid, but the grid starts empty.
    assert!(board.grid_cell_valid(0, 0)); // unbounded sparse: any coord is valid
    assert!(board.grid_get(0, 0).is_none()); // but nothing placed yet
    assert_eq!(board.count(), 0);
}
