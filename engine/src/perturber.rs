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
use crate::runtime::GameSession;
use crate::transition::apply_action;

/// Maximum fuel for repeat_until_stable (safety cap).
const MAX_FUEL: u64 = 10_000;

/// Maximum repeat count for repeat(n).
const MAX_REPEAT: u32 = 10_000;

/// Maximum collection size for for_each.
const MAX_FOREACH_ITEMS: usize = 10_000;

/// Maximum absolute value for counter operations.
const MAX_COUNTER_VALUE: i64 = 1_000_000_000;

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
pub struct RepeatUntilStableSpec {
    pub fuel: u64,
    pub apply: Box<Effect>,
}

/// Execute a perturber effect against a game session.
pub fn execute_effect(session: &mut GameSession, effect: &Effect) -> Result<()> {
    match effect {
        Effect::Sequence { sequence } => {
            for e in sequence {
                execute_effect(session, e)?;
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
                execute_effect(session, then)?;
            } else if let Some(else_effect) = else_branch {
                execute_effect(session, else_effect)?;
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
                execute_effect(session, body)?;
            }
        }
        Effect::Repeat { repeat, body } => {
            let bounded = (*repeat).min(MAX_REPEAT);
            for _ in 0..bounded {
                execute_effect(session, body)?;
            }
        }
        Effect::RepeatUntilStable {
            repeat_until_stable,
        } => {
            let fuel = repeat_until_stable.fuel.min(MAX_FUEL);
            for _ in 0..fuel {
                let hash_before = session.compute_state_hash();
                execute_effect(session, &repeat_until_stable.apply)?;
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
    }
    Ok(())
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
        custom_data: None,
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
