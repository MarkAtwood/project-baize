//! Tests for Rubik's Cube face rotation perturber sequences.
//!
//! Each of the 6 CW moves is defined as a sequence of 5 cycles:
//! - 2 face cycles (corners + edges of the rotating face)
//! - 3 strip cycles (edges of the 4 adjacent faces)
//!
//! Convention: each face viewed from outside the cube. (0,0) = top-left.

use baize_engine::perturber::{execute_effect, Effect};
use baize_engine::runtime::{ComponentData, ComponentId, GameSession};
use baize_engine::GameDefinition;
use indexmap::IndexMap;
use serde_json::json;
use std::collections::HashMap;

const FACES: [&str; 6] = ["up", "down", "front", "back", "left", "right"];

fn cube_session() -> GameSession {
    let mut zones = serde_json::Map::new();
    for face in &FACES {
        zones.insert(
            face.to_string(),
            json!({"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"}),
        );
    }
    let def_json = json!({
        "game": {"name": "Cube", "players": ["solver"], "information": "perfect"},
        "zones": zones,
        "components": {"sticker": {"owner": "neutral"}},
        "turn_order": {"type": "alternating", "players": ["solver"], "actions_per_turn": 1, "mandatory": false},
        "end_conditions": [{"result": "draw", "condition": "false"}],
        "authority": {"server_only": [], "client_verifiable": ["all"]}
    });
    let def: GameDefinition = serde_json::from_value(def_json).unwrap();
    let mut session = GameSession::new(def).unwrap();
    session.runtime.status = baize_engine::state::GameStatus::InProgress;

    for face in &FACES {
        for row in 0u32..3 {
            for col in 0u32..3 {
                let name = format!("{face}_{col}_{row}");
                let cid = session
                    .runtime
                    .components
                    .insert(ComponentData {
                        id: ComponentId(0),
                        string_id: name,
                        component_type: "sticker".to_string(),
                        owner: Some("neutral".to_string()),
                        facing: None,
                        state: None,
                        properties: IndexMap::new(),
                        span_cells: Vec::new(),
                    })
                    .unwrap();
                session
                    .runtime
                    .zones
                    .get_mut(*face)
                    .unwrap()
                    .grid_set(col, row, Some(cid));
            }
        }
    }
    session
}

fn read_state(session: &GameSession) -> HashMap<(String, u32, u32), String> {
    let mut state = HashMap::new();
    for face in &FACES {
        for row in 0u32..3 {
            for col in 0u32..3 {
                if let Some(cid) = session.runtime.zones.get(*face).unwrap().grid_get(col, row) {
                    let comp = session.runtime.components.get(cid).unwrap();
                    state.insert((face.to_string(), col, row), comp.string_id.clone());
                }
            }
        }
    }
    state
}

// -- Move construction helpers --

fn cyc(positions: &[(&str, u32, u32)]) -> serde_json::Value {
    json!({"cycle": positions.iter().map(|(z, c, r)| json!({"zone": z, "pos": format!("{c},{r}")})).collect::<Vec<_>>()})
}

fn face_move(face: &str, strips: &[Vec<(&str, u32, u32)>]) -> Effect {
    let mut seq = vec![
        cyc(&[(face, 0, 0), (face, 2, 0), (face, 2, 2), (face, 0, 2)]),
        cyc(&[(face, 1, 0), (face, 2, 1), (face, 1, 2), (face, 0, 1)]),
    ];
    for s in strips {
        seq.push(cyc(s));
    }
    serde_json::from_value(json!({"sequence": seq})).unwrap()
}

fn reverse_move(cw: &Effect) -> Effect {
    if let Effect::Sequence { sequence } = cw {
        let reversed: Vec<serde_json::Value> = sequence
            .iter()
            .map(|e| {
                if let Effect::Cycle { cycle } = e {
                    let mut positions: Vec<_> = cycle
                        .iter()
                        .map(|cp| json!({"zone": cp.zone, "pos": cp.pos}))
                        .collect();
                    if positions.len() > 1 {
                        let first = positions[0].clone();
                        let rest: Vec<_> = positions[1..].iter().rev().cloned().collect();
                        positions = std::iter::once(first).chain(rest).collect();
                    }
                    json!({"cycle": positions})
                } else {
                    serde_json::to_value(e).unwrap()
                }
            })
            .collect();
        serde_json::from_value(json!({"sequence": reversed})).unwrap()
    } else {
        panic!("expected sequence");
    }
}

// -- Move definitions --

fn u_cw() -> Effect {
    face_move("up", &[
        vec![("front", 0, 0), ("right", 0, 0), ("back", 0, 0), ("left", 0, 0)],
        vec![("front", 1, 0), ("right", 1, 0), ("back", 1, 0), ("left", 1, 0)],
        vec![("front", 2, 0), ("right", 2, 0), ("back", 2, 0), ("left", 2, 0)],
    ])
}

fn d_cw() -> Effect {
    face_move("down", &[
        vec![("front", 0, 2), ("left", 0, 2), ("back", 0, 2), ("right", 0, 2)],
        vec![("front", 1, 2), ("left", 1, 2), ("back", 1, 2), ("right", 1, 2)],
        vec![("front", 2, 2), ("left", 2, 2), ("back", 2, 2), ("right", 2, 2)],
    ])
}

fn f_cw() -> Effect {
    face_move("front", &[
        vec![("up", 0, 2), ("right", 0, 0), ("down", 2, 0), ("left", 2, 2)],
        vec![("up", 1, 2), ("right", 0, 1), ("down", 1, 0), ("left", 2, 1)],
        vec![("up", 2, 2), ("right", 0, 2), ("down", 0, 0), ("left", 2, 0)],
    ])
}

fn b_cw() -> Effect {
    face_move("back", &[
        vec![("up", 2, 0), ("left", 0, 0), ("down", 0, 2), ("right", 2, 2)],
        vec![("up", 1, 0), ("left", 0, 1), ("down", 1, 2), ("right", 2, 1)],
        vec![("up", 0, 0), ("left", 0, 2), ("down", 2, 2), ("right", 2, 0)],
    ])
}

fn r_cw() -> Effect {
    face_move("right", &[
        vec![("up", 2, 0), ("front", 2, 0), ("down", 2, 0), ("back", 0, 2)],
        vec![("up", 2, 1), ("front", 2, 1), ("down", 2, 1), ("back", 0, 1)],
        vec![("up", 2, 2), ("front", 2, 2), ("down", 2, 2), ("back", 0, 0)],
    ])
}

fn l_cw() -> Effect {
    face_move("left", &[
        vec![("up", 0, 0), ("back", 2, 2), ("down", 0, 0), ("front", 0, 0)],
        vec![("up", 0, 1), ("back", 2, 1), ("down", 0, 1), ("front", 0, 1)],
        vec![("up", 0, 2), ("back", 2, 0), ("down", 0, 2), ("front", 0, 2)],
    ])
}

// -- Tests --

macro_rules! test_4x_identity {
    ($name:ident, $move_fn:expr) => {
        #[test]
        fn $name() {
            let mut session = cube_session();
            let initial = read_state(&session);
            let m = $move_fn;
            for _ in 0..4 {
                execute_effect(&mut session, &m).unwrap();
            }
            assert_eq!(read_state(&session), initial);
        }
    };
}

test_4x_identity!(u_4x_identity, u_cw());
test_4x_identity!(d_4x_identity, d_cw());
test_4x_identity!(f_4x_identity, f_cw());
test_4x_identity!(b_4x_identity, b_cw());
test_4x_identity!(r_4x_identity, r_cw());
test_4x_identity!(l_4x_identity, l_cw());

macro_rules! test_cw_ccw_identity {
    ($name:ident, $move_fn:expr) => {
        #[test]
        fn $name() {
            let mut session = cube_session();
            let initial = read_state(&session);
            let cw = $move_fn;
            let ccw = reverse_move(&cw);
            execute_effect(&mut session, &cw).unwrap();
            execute_effect(&mut session, &ccw).unwrap();
            assert_eq!(read_state(&session), initial);
        }
    };
}

test_cw_ccw_identity!(u_cw_ccw, u_cw());
test_cw_ccw_identity!(d_cw_ccw, d_cw());
test_cw_ccw_identity!(f_cw_ccw, f_cw());
test_cw_ccw_identity!(b_cw_ccw, b_cw());
test_cw_ccw_identity!(r_cw_ccw, r_cw());
test_cw_ccw_identity!(l_cw_ccw, l_cw());

#[test]
fn u_cw_specific_positions() {
    let mut session = cube_session();
    execute_effect(&mut session, &u_cw()).unwrap();
    let s = read_state(&session);

    // F top row → R top row
    assert_eq!(s[&("right".into(), 0, 0)], "front_0_0");
    assert_eq!(s[&("right".into(), 1, 0)], "front_1_0");
    assert_eq!(s[&("right".into(), 2, 0)], "front_2_0");
    // R → B
    assert_eq!(s[&("back".into(), 0, 0)], "right_0_0");
    // B → L
    assert_eq!(s[&("left".into(), 0, 0)], "back_0_0");
    // L → F
    assert_eq!(s[&("front".into(), 0, 0)], "left_0_0");
    // Face corner rotation
    assert_eq!(s[&("up".into(), 2, 0)], "up_0_0");
    // Center stays
    assert_eq!(s[&("up".into(), 1, 1)], "up_1_1");
}

#[test]
fn each_cw_moves_20_stickers() {
    let moves: [(&str, Effect); 6] = [
        ("U", u_cw()),
        ("D", d_cw()),
        ("F", f_cw()),
        ("B", b_cw()),
        ("R", r_cw()),
        ("L", l_cw()),
    ];
    for (name, m) in &moves {
        let mut session = cube_session();
        let initial = read_state(&session);
        execute_effect(&mut session, m).unwrap();
        let after = read_state(&session);
        let moved = initial.iter().filter(|(k, v)| after[k] != **v).count();
        assert_eq!(moved, 20, "{name} moved {moved} stickers, expected 20");
    }
}

#[test]
fn sexy_move_6x_identity() {
    // (R U R' U') applied 6 times = identity
    let mut session = cube_session();
    let initial = read_state(&session);
    let r = r_cw();
    let u = u_cw();
    let r_prime = reverse_move(&r);
    let u_prime = reverse_move(&u);
    let sexy: Effect =
        serde_json::from_value(json!({"sequence": [
            serde_json::to_value(&r).unwrap(),
            serde_json::to_value(&u).unwrap(),
            serde_json::to_value(&r_prime).unwrap(),
            serde_json::to_value(&u_prime).unwrap(),
        ]}))
        .unwrap();
    for _ in 0..6 {
        execute_effect(&mut session, &sexy).unwrap();
    }
    assert_eq!(read_state(&session), initial);
}

#[test]
fn double_move_2x_identity() {
    // U2 applied twice = identity
    let mut session = cube_session();
    let initial = read_state(&session);
    let u = u_cw();
    let u2: Effect = serde_json::from_value(json!({"sequence": [
        serde_json::to_value(&u).unwrap(),
        serde_json::to_value(&u).unwrap(),
    ]}))
    .unwrap();
    execute_effect(&mut session, &u2).unwrap();
    execute_effect(&mut session, &u2).unwrap();
    assert_eq!(read_state(&session), initial);
}
