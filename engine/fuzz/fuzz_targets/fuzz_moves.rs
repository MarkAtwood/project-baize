#![no_main]

use libfuzzer_sys::fuzz_target;

/// Minimal tic-tac-toe definition for bootstrapping a game session.
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
    // Create a valid game session with random component placements,
    // then call legal_moves(). Must never panic.
    let definition = match baize_engine::GameDefinition::from_json(TTT_JSON) {
        Ok(d) => d,
        Err(_) => return,
    };
    let mut session = match baize_engine::GameSession::new(definition) {
        Ok(s) => s,
        Err(_) => return,
    };

    // Use the fuzz data to drive random placements onto the board.
    // Each 2 bytes encode a placement: (col % 3, row % 3).
    let chunks = data.chunks_exact(2);
    for chunk in chunks {
        let col = (chunk[0] % 3) as u32;
        let row = (chunk[1] % 3) as u32;
        let _player = session.current_player().unwrap_or("X").to_string();
        let action = baize_engine::action::Action {
            action_type: baize_engine::action::ActionType::Place,
            authority: None,
            component_id: None,
            component_type: Some("mark".to_string()),
            from: None,
            to: Some(baize_engine::action::Position::Structured {
                zone: Some("board".to_string()),
                cell: Some(format!("{col},{row}")),
                index: None,
            }),
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
        };
        let _ = baize_engine::transition::apply_action(&mut session, &action);
    }

    // After random placements, call legal_moves. Must not panic.
    let _ = baize_engine::moves::legal_moves(&session);

    // Also try: parse fuzz data as a game definition, create session, call legal_moves.
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(def) = baize_engine::GameDefinition::from_json(s) {
            if let Ok(session2) = baize_engine::GameSession::new(def) {
                let _ = baize_engine::moves::legal_moves(&session2);
            }
        }
    }
});
