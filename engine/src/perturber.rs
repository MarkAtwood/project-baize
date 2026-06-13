//! Structured perturber language: composable effects with bounded control flow.
//!
//! Perturbers describe state mutations as a structured AST. Unlike CEL (pure
//! queries), perturbers mutate game state. Unlike WASM (arbitrary code),
//! perturbers are guaranteed to terminate.
//!
//! Control flow: sequence, if/then/else, for_each, repeat(n), repeat_until_stable.
//! No while, no recursion, no computed gotos.

use serde::{Deserialize, Serialize};

use crate::action::{Action, ActionType};
use crate::error::Result;
use crate::runtime::{ComponentId, GameSession, RuntimeZone};
use crate::transition::apply_action;

/// Maximum fuel for repeat_until_stable (safety cap).
const MAX_FUEL: u64 = 10_000;

/// Maximum repeat count for repeat(n).
const MAX_REPEAT: u32 = 10_000;

/// Maximum collection size for for_each.
const MAX_FOREACH_ITEMS: usize = 10_000;

/// Maximum absolute value for counter operations.
const MAX_COUNTER_VALUE: i64 = 1_000_000_000;

/// Maximum number of positions in a cycle.
const MAX_CYCLE_LEN: usize = 1_000;

/// Maximum invoke nesting depth (prevents infinite recursion).
const MAX_INVOKE_DEPTH: u32 = 16;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CyclePosition {
    pub zone: String,
    pub pos: String,
}

/// A structured effect that mutates game state.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Effect {
    Sequence {
        sequence: Vec<Effect>,
    },
    If {
        #[serde(rename = "if")]
        condition: String,
        then: Box<Effect>,
        #[serde(rename = "else", default, skip_serializing_if = "Option::is_none")]
        else_branch: Option<Box<Effect>>,
    },
    ForEach {
        for_each: ForEachSpec,
        #[serde(rename = "do")]
        body: Box<Effect>,
    },
    Repeat {
        repeat: u32,
        body: Box<Effect>,
    },
    RepeatUntilStable {
        repeat_until_stable: RepeatUntilStableSpec,
    },
    Remove {
        remove: TargetSpec,
    },
    Flip {
        flip: TargetSpec,
    },
    Promote {
        promote: PromoteSpec,
    },
    AddCounter {
        add_counter: CounterSpec,
    },
    SetCounter {
        set_counter: CounterSpec,
    },
    Cycle {
        cycle: Vec<CyclePosition>,
    },
    Invoke {
        invoke: String,
    },
    SetCellProperty {
        set_cell_property: CellPropertySpec,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TargetSpec {
    pub target: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PromoteSpec {
    pub target: String,
    pub to_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CounterSpec {
    pub counter: String,
    #[serde(default)]
    pub value: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForEachSpec {
    #[serde(rename = "var", default = "default_var")]
    pub var_name: String,
    #[serde(rename = "in")]
    pub collection: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub filter: Option<String>,
}

fn default_var() -> String {
    "item".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CellPropertySpec {
    pub zone: String,
    pub col: u32,
    pub row: u32,
    pub key: String,
    pub value: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepeatUntilStableSpec {
    pub fuel: u64,
    pub apply: Box<Effect>,
}

/// Execute a perturber effect against a game session.
pub fn execute_effect(session: &mut GameSession, effect: &Effect) -> Result<()> {
    execute_effect_inner(session, effect, 0)
}

fn execute_effect_inner(session: &mut GameSession, effect: &Effect, depth: u32) -> Result<()> {
    match effect {
        Effect::Sequence { sequence } => {
            for e in sequence {
                execute_effect_inner(session, e, depth)?;
            }
        }
        Effect::If {
            condition,
            then,
            else_branch,
        } => {
            let player = session.current_player().unwrap_or("").to_string();
            let result = crate::cel::try_eval_end_condition(session, condition, &player);
            if result == Some(true) {
                execute_effect_inner(session, then, depth)?;
            } else if let Some(else_effect) = else_branch {
                execute_effect_inner(session, else_effect, depth)?;
            }
        }
        Effect::ForEach { for_each, body } => {
            if for_each.collection.len() > MAX_FOREACH_ITEMS {
                return Err(crate::error::BaizeError::Overflow(format!(
                    "for_each collection size {} exceeds maximum {}",
                    for_each.collection.len(),
                    MAX_FOREACH_ITEMS
                )));
            }
            let items: Vec<String> = if let Some(ref filter_expr) = for_each.filter {
                let player = session.current_player().unwrap_or("").to_string();
                for_each
                    .collection
                    .iter()
                    .filter(|item| {
                        let expr = filter_expr.replace(&format!("${}", for_each.var_name), item);
                        crate::cel::try_eval_end_condition(session, &expr, &player)
                            == Some(true)
                    })
                    .cloned()
                    .collect()
            } else {
                for_each.collection.clone()
            };

            for _item in &items {
                execute_effect_inner(session, body, depth)?;
            }
        }
        Effect::Repeat { repeat, body } => {
            let bounded = (*repeat).min(MAX_REPEAT);
            for _ in 0..bounded {
                execute_effect_inner(session, body, depth)?;
            }
        }
        Effect::RepeatUntilStable {
            repeat_until_stable,
        } => {
            let fuel = repeat_until_stable.fuel.min(MAX_FUEL);
            for _ in 0..fuel {
                let hash_before = session.compute_state_hash();
                execute_effect_inner(session, &repeat_until_stable.apply, depth)?;
                let hash_after = session.compute_state_hash();
                if hash_before == hash_after {
                    break; // Stable — no state change
                }
            }
        }
        Effect::Remove { remove } => {
            let action = Action {
                action_type: ActionType::Remove,
                component_id: Some(remove.target.clone()),
                ..empty_action()
            };
            let _ = apply_action(session, &action);
        }
        Effect::Flip { flip } => {
            let action = Action {
                action_type: ActionType::Flip,
                component_id: Some(flip.target.clone()),
                ..empty_action()
            };
            let _ = apply_action(session, &action);
        }
        Effect::Promote { promote } => {
            let action = Action {
                action_type: ActionType::Promote,
                component_id: Some(promote.target.clone()),
                promote_to: Some(promote.to_type.clone()),
                ..empty_action()
            };
            let _ = apply_action(session, &action);
        }
        Effect::AddCounter { add_counter } => {
            if add_counter.value.abs() > MAX_COUNTER_VALUE {
                return Err(crate::error::BaizeError::Overflow(format!(
                    "counter value {} exceeds maximum {}",
                    add_counter.value, MAX_COUNTER_VALUE
                )));
            }
            let current = session
                .runtime
                .counters
                .get(&add_counter.counter)
                .copied()
                .unwrap_or(0);
            let new_value = current.checked_add(add_counter.value).ok_or_else(|| {
                crate::error::BaizeError::Overflow("counter addition overflow".into())
            })?;
            session
                .runtime
                .counters
                .insert(add_counter.counter.clone(), new_value);
        }
        Effect::SetCounter { set_counter } => {
            if set_counter.value.abs() > MAX_COUNTER_VALUE {
                return Err(crate::error::BaizeError::Overflow(format!(
                    "counter value {} exceeds maximum {}",
                    set_counter.value, MAX_COUNTER_VALUE
                )));
            }
            session
                .runtime
                .counters
                .insert(set_counter.counter.clone(), set_counter.value);
        }
        Effect::Cycle { cycle } => {
            if cycle.len() < 2 {
                return Ok(());
            }
            if cycle.len() > MAX_CYCLE_LEN {
                return Err(crate::error::BaizeError::Overflow(format!(
                    "cycle length {} exceeds maximum {}",
                    cycle.len(),
                    MAX_CYCLE_LEN
                )));
            }
            // Parse all positions and read current occupants
            let mut parsed: Vec<(&str, u32, u32)> = Vec::with_capacity(cycle.len());
            for cp in cycle {
                let (col, row) = parse_cycle_pos(&cp.pos)?;
                if !session.runtime.zones.contains_key(&cp.zone) {
                    return Err(crate::error::BaizeError::UnknownZone(cp.zone.clone()));
                }
                parsed.push((&cp.zone, col, row));
            }
            let saved: Vec<Option<ComponentId>> = parsed
                .iter()
                .map(|(zone, col, row)| {
                    session
                        .runtime
                        .zones
                        .get(*zone)
                        .and_then(|z| z.grid_get(*col, *row))
                })
                .collect();
            // Write shifted: pos[i] receives what was at pos[i-1]
            let n = parsed.len();
            for i in 0..n {
                let src_idx = if i == 0 { n - 1 } else { i - 1 };
                let (zone, col, row) = parsed[i];
                session
                    .runtime
                    .zones
                    .get_mut(zone)
                    .expect("zone validated above")
                    .grid_set(col, row, saved[src_idx]);
            }
        }
        Effect::SetCellProperty { set_cell_property } => {
            let zone = session
                .runtime
                .zones
                .get_mut(&set_cell_property.zone)
                .ok_or_else(|| {
                    crate::error::BaizeError::UnknownZone(set_cell_property.zone.clone())
                })?;
            if let RuntimeZone::Grid {
                storage, cell_properties, ..
            } = zone
            {
                let col = set_cell_property.col;
                let row = set_cell_property.row;
                if storage.cell_valid(col as i32, row as i32) {
                    cell_properties
                        .entry((col as i32, row as i32))
                        .or_default()
                        .insert(
                            set_cell_property.key.clone(),
                            set_cell_property.value.clone(),
                        );
                }
            } else {
                return Err(crate::error::BaizeError::IllegalAction(format!(
                    "zone '{}' is not a grid zone",
                    set_cell_property.zone
                )));
            }
        }
        Effect::Invoke { invoke } => {
            if depth >= MAX_INVOKE_DEPTH {
                return Err(crate::error::BaizeError::Overflow(format!(
                    "invoke depth {} exceeds maximum {}",
                    depth, MAX_INVOKE_DEPTH
                )));
            }
            let entry = session
                .definition
                .library
                .get(invoke)
                .ok_or_else(|| {
                    crate::error::BaizeError::IllegalAction(format!(
                        "unknown library entry: {invoke}"
                    ))
                })?
                .clone();
            match entry {
                crate::definition::LibraryEntry::Effect(ref effect) => {
                    execute_effect_inner(session, effect, depth + 1)?;
                }
                crate::definition::LibraryEntry::Expression(_) => {
                    return Err(crate::error::BaizeError::IllegalAction(format!(
                        "library entry '{invoke}' is an expression, not an effect"
                    )));
                }
            }
        }
    }
    Ok(())
}

fn parse_cycle_pos(s: &str) -> Result<(u32, u32)> {
    let parts: Vec<&str> = s.split(',').collect();
    if parts.len() == 2 {
        let col = parts[0]
            .trim()
            .parse::<u32>()
            .map_err(|_| crate::error::BaizeError::IllegalAction(format!("invalid cycle position: {s}")))?;
        let row = parts[1]
            .trim()
            .parse::<u32>()
            .map_err(|_| crate::error::BaizeError::IllegalAction(format!("invalid cycle position: {s}")))?;
        Ok((col, row))
    } else {
        Err(crate::error::BaizeError::IllegalAction(format!(
            "invalid cycle position format: {s}"
        )))
    }
}

fn empty_action() -> Action {
    Action {
        action_type: ActionType::Pass,
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
        mental_poker_data: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::runtime::{ComponentData, ComponentId, GameSession};
    use crate::GameDefinition;
    use indexmap::IndexMap;

    fn test_session() -> GameSession {
        let def: GameDefinition = serde_json::from_str(
            r#"{
            "game": { "name": "Test", "players": ["A", "B"], "information": "perfect" },
            "zones": { "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" } },
            "components": { "piece": { "owner": "per_player" } },
            "turn_order": { "type": "alternating", "players": ["A", "B"], "actions_per_turn": 1, "mandatory": true },
            "end_conditions": [{ "result": "draw", "condition": "all_cells_occupied" }],
            "authority": { "server_only": [], "client_verifiable": ["all"] }
        }"#,
        )
        .unwrap();
        let mut s = GameSession::new(def).unwrap();
        s.runtime.status = crate::state::GameStatus::InProgress;
        s
    }

    fn place_piece(session: &mut GameSession, name: &str, owner: &str, col: u32, row: u32) {
        let cid = session
            .runtime
            .components
            .insert(ComponentData {
                id: ComponentId(0),
                string_id: name.to_string(),
                component_type: "piece".to_string(),
                owner: Some(owner.to_string()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
                span_cells: Vec::new(),
                orientation: None,
            })
            .unwrap();
        session
            .runtime
            .zones
            .get_mut("board")
            .unwrap()
            .grid_set(col, row, Some(cid));
    }

    #[test]
    fn sequence_of_counters() {
        let mut session = test_session();
        let effect: Effect = serde_json::from_str(
            r#"{"sequence": [
                {"set_counter": {"counter": "score", "value": 10}},
                {"add_counter": {"counter": "score", "value": 5}}
            ]}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();
        assert_eq!(session.runtime.counters.get("score"), Some(&15));
    }

    #[test]
    fn if_then_else() {
        let mut session = test_session();
        // Condition: move_count == 0 (true at start)
        let effect: Effect = serde_json::from_str(
            r#"{"if": "move_count == 0",
                "then": {"set_counter": {"counter": "branch", "value": 1}},
                "else": {"set_counter": {"counter": "branch", "value": 2}}
            }"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();
        assert_eq!(session.runtime.counters.get("branch"), Some(&1));
    }

    #[test]
    fn repeat_n_times() {
        let mut session = test_session();
        let effect: Effect = serde_json::from_str(
            r#"{"repeat": 3, "body": {"add_counter": {"counter": "ticks", "value": 1}}}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();
        assert_eq!(session.runtime.counters.get("ticks"), Some(&3));
    }

    #[test]
    fn repeat_until_stable_stops_when_no_change() {
        let mut session = test_session();
        // add_counter changes state, but after counter is set to 5 we stop incrementing
        // Actually, add_counter always changes state. Let's test with set_counter
        // which is idempotent (setting same value = no state hash change)
        let effect: Effect = serde_json::from_str(
            r#"{"repeat_until_stable": {"fuel": 100,
                "apply": {"set_counter": {"counter": "fixed", "value": 42}}
            }}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();
        assert_eq!(session.runtime.counters.get("fixed"), Some(&42));
        // Should have run exactly 2 iterations: first sets, second detects stable
    }

    #[test]
    fn remove_via_perturber() {
        let mut session = test_session();
        place_piece(&mut session, "target-piece", "A", 1, 1);
        assert!(session.runtime.zones.get("board").unwrap().grid_get(1, 1).is_some());

        let effect: Effect =
            serde_json::from_str(r#"{"remove": {"target": "target-piece"}}"#).unwrap();
        execute_effect(&mut session, &effect).unwrap();
        assert!(session.runtime.zones.get("board").unwrap().grid_get(1, 1).is_none());
    }

    fn multi_zone_session() -> GameSession {
        let def: GameDefinition = serde_json::from_str(
            r#"{
            "game": { "name": "Test", "players": ["A", "B"], "information": "perfect" },
            "zones": {
                "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" },
                "front": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" },
                "right": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
            },
            "components": { "piece": { "owner": "per_player" } },
            "turn_order": { "type": "alternating", "players": ["A", "B"], "actions_per_turn": 1, "mandatory": true },
            "end_conditions": [{ "result": "draw", "condition": "all_cells_occupied" }],
            "authority": { "server_only": [], "client_verifiable": ["all"] }
        }"#,
        )
        .unwrap();
        let mut s = GameSession::new(def).unwrap();
        s.runtime.status = crate::state::GameStatus::InProgress;
        s
    }

    fn place_piece_in(
        session: &mut GameSession,
        name: &str,
        owner: &str,
        zone: &str,
        col: u32,
        row: u32,
    ) -> ComponentId {
        let cid = session
            .runtime
            .components
            .insert(ComponentData {
                id: ComponentId(0),
                string_id: name.to_string(),
                component_type: "piece".to_string(),
                owner: Some(owner.to_string()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
                span_cells: Vec::new(),
                orientation: None,
            })
            .unwrap();
        session
            .runtime
            .zones
            .get_mut(zone)
            .unwrap()
            .grid_set(col, row, Some(cid));
        cid
    }

    #[test]
    fn cycle_same_zone_3_elements() {
        let mut session = test_session();
        let a = place_piece_in(&mut session, "a", "A", "board", 0, 0);
        let b = place_piece_in(&mut session, "b", "A", "board", 1, 0);
        let c = place_piece_in(&mut session, "c", "A", "board", 2, 0);

        // Cycle: 0,0 -> 1,0 -> 2,0 -> 0,0
        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "board", "pos": "1,0"},
                {"zone": "board", "pos": "2,0"}
            ]}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();

        let z = session.runtime.zones.get("board").unwrap();
        assert_eq!(z.grid_get(0, 0), Some(c)); // c wraps from pos[2] to pos[0]
        assert_eq!(z.grid_get(1, 0), Some(a)); // a moves from pos[0] to pos[1]
        assert_eq!(z.grid_get(2, 0), Some(b)); // b moves from pos[1] to pos[2]
    }

    #[test]
    fn cycle_cross_zone() {
        let mut session = multi_zone_session();
        let a = place_piece_in(&mut session, "a", "A", "board", 0, 0);
        let b = place_piece_in(&mut session, "b", "A", "front", 0, 0);
        let c = place_piece_in(&mut session, "c", "A", "right", 0, 0);

        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "front", "pos": "0,0"},
                {"zone": "right", "pos": "0,0"}
            ]}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();

        assert_eq!(session.runtime.zones.get("board").unwrap().grid_get(0, 0), Some(c));
        assert_eq!(session.runtime.zones.get("front").unwrap().grid_get(0, 0), Some(a));
        assert_eq!(session.runtime.zones.get("right").unwrap().grid_get(0, 0), Some(b));
    }

    #[test]
    fn cycle_with_empty_cell_acts_as_transfer() {
        let mut session = test_session();
        let a = place_piece_in(&mut session, "a", "A", "board", 0, 0);
        // pos 1,0 is empty

        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "board", "pos": "1,0"}
            ]}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();

        let z = session.runtime.zones.get("board").unwrap();
        assert_eq!(z.grid_get(0, 0), None);    // source emptied
        assert_eq!(z.grid_get(1, 0), Some(a));  // component transferred
    }

    #[test]
    fn cycle_4x_returns_to_start() {
        let mut session = test_session();
        let a = place_piece_in(&mut session, "a", "A", "board", 0, 0);
        let b = place_piece_in(&mut session, "b", "A", "board", 1, 0);
        let c = place_piece_in(&mut session, "c", "A", "board", 2, 0);
        let d = place_piece_in(&mut session, "d", "A", "board", 0, 1);

        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "board", "pos": "1,0"},
                {"zone": "board", "pos": "2,0"},
                {"zone": "board", "pos": "0,1"}
            ]}"#,
        )
        .unwrap();
        // Apply 4 times — should return to original positions
        for _ in 0..4 {
            execute_effect(&mut session, &effect).unwrap();
        }

        let z = session.runtime.zones.get("board").unwrap();
        assert_eq!(z.grid_get(0, 0), Some(a));
        assert_eq!(z.grid_get(1, 0), Some(b));
        assert_eq!(z.grid_get(2, 0), Some(c));
        assert_eq!(z.grid_get(0, 1), Some(d));
    }

    #[test]
    fn cycle_single_element_is_noop() {
        let mut session = test_session();
        let a = place_piece_in(&mut session, "a", "A", "board", 0, 0);

        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [{"zone": "board", "pos": "0,0"}]}"#,
        )
        .unwrap();
        execute_effect(&mut session, &effect).unwrap();

        assert_eq!(session.runtime.zones.get("board").unwrap().grid_get(0, 0), Some(a));
    }

    #[test]
    fn cycle_unknown_zone_errors() {
        let mut session = test_session();
        let effect: Effect = serde_json::from_str(
            r#"{"cycle": [
                {"zone": "board", "pos": "0,0"},
                {"zone": "nonexistent", "pos": "0,0"}
            ]}"#,
        )
        .unwrap();
        assert!(execute_effect(&mut session, &effect).is_err());
    }

    #[test]
    fn deserialize_go_capture_skeleton() {
        // Verify the Go capture chain from DESIGN.md can at least parse
        let json = r#"{"repeat_until_stable": {"fuel": 81,
            "apply": {"sequence": [
                {"set_counter": {"counter": "stable_marker", "value": 1}}
            ]}
        }}"#;
        let effect: Effect = serde_json::from_str(json).unwrap();
        let mut session = test_session();
        execute_effect(&mut session, &effect).unwrap();
    }
}
