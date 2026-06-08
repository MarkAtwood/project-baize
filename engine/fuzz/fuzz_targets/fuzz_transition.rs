#![no_main]

use libfuzzer_sys::fuzz_target;

/// Minimal tic-tac-toe definition used to bootstrap a valid game session.
const TTT_JSON: &str = r#"{
    "game": {
        "name": "Tic-Tac-Toe",
        "players": ["X", "O"],
        "information": "perfect"
    },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [3, 3],
            "visibility": "public"
        }
    },
    "components": {
        "mark": {
            "owner": "per_player",
            "count": "unlimited"
        }
    },
    "turn_order": {
        "type": "alternating",
        "players": ["X", "O"],
        "actions_per_turn": 1,
        "mandatory": true
    },
    "end_conditions": [
        {
            "result": "win",
            "player": "current",
            "condition": "three_in_line"
        },
        {
            "result": "draw",
            "condition": "board_is_full"
        }
    ],
    "authority": {
        "server_only": [],
        "client_verifiable": ["all"]
    }
}"#;

fuzz_target!(|data: &[u8]| {
    // Create a valid game session, then feed random action JSON to apply_action.
    // Must never panic -- illegal actions should produce Err.
    let definition = match baize_engine::GameDefinition::from_json(TTT_JSON) {
        Ok(d) => d,
        Err(_) => return,
    };
    let mut session = match baize_engine::GameSession::new(definition) {
        Ok(s) => s,
        Err(_) => return,
    };

    // Try to parse the fuzz data as an Action and apply it.
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(action) = serde_json::from_str::<baize_engine::action::Action>(s) {
            let _ = baize_engine::transition::apply_action(&mut session, &action);
        }
    }

    // Also try: parse as a sequence of actions (JSON array) and apply each.
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(actions) = serde_json::from_str::<Vec<baize_engine::action::Action>>(s) {
            // Re-create session for the sequence test.
            let def2 = baize_engine::GameDefinition::from_json(TTT_JSON).unwrap();
            let mut session2 = baize_engine::GameSession::new(def2).unwrap();
            for action in &actions {
                let _ = baize_engine::transition::apply_action(&mut session2, action);
            }
        }
    }
});
