use baize_engine::action::{ClientMessage, RandomType, ServerMessage};
use baize_engine::state::GameStatus;
use baize_engine::transition::apply_action;

use crate::room::Room;
use crate::vault;

/// Handle an incoming client message (JSON text) and return server responses.
/// In the full implementation, some responses go only to the acting player
/// (e.g., move_rejected) while others broadcast (move_confirmed).
/// For the skeleton, we return a Vec and let the caller broadcast all of them.
pub fn handle_client_message(room: &mut Room, seat: &str, raw: &str) -> Vec<ServerMessage> {
    let msg: ClientMessage = match serde_json::from_str(raw) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("invalid client message from {seat}: {e}");
            return Vec::new();
        }
    };

    match msg {
        ClientMessage::SubmitMove {
            game_id: _,
            player,
            sequence: _,
            action,
        } => handle_submit_move(room, seat, &player, action),

        ClientMessage::RequestRandom {
            game_id: _,
            player,
            random_request,
        } => handle_request_random(room, seat, &player, random_request),

        ClientMessage::AcknowledgeState {
            game_id: _,
            player,
            state_hash,
        } => handle_acknowledge_state(room, seat, &player, &state_hash),
    }
}

/// Process a submit_move message:
/// 1. Verify it is this player's turn
/// 2. Apply the action through the engine
/// 3. Return move_confirmed or move_rejected
fn handle_submit_move(
    room: &mut Room,
    _seat: &str,
    player: &str,
    action: baize_engine::action::Action,
) -> Vec<ServerMessage> {
    let game_id = room.id.clone();

    // Check game is in progress or setup
    if room.session.runtime.status == GameStatus::Finished {
        return vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: "game is finished".to_string(),
        }];
    }

    // Check it is this player's turn
    let current = room
        .session
        .current_player()
        .unwrap_or("")
        .to_string();
    if current != player {
        return vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: format!("not your turn (current: {current})"),
        }];
    }

    // Apply through the engine
    match apply_action(&mut room.session, &action) {
        Ok(_events) => {
            let wire_state = room.session.to_wire_state();
            let sequence = wire_state.sequence;
            let result_state = serde_json::to_value(&wire_state).ok();

            vec![ServerMessage::MoveConfirmed {
                game_id,
                sequence,
                action,
                result_state,
            }]
        }
        Err(e) => vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: e.to_string(),
        }],
    }
}

/// Process a request_random message:
/// Delegate to the vault for dice rolls, card draws, and shuffles.
fn handle_request_random(
    room: &mut Room,
    _seat: &str,
    _player: &str,
    request: baize_engine::action::RandomRequest,
) -> Vec<ServerMessage> {
    let game_id = room.id.clone();

    match request.random_type {
        RandomType::Roll => {
            let dice_count = request.dice_count.unwrap_or(1);
            let dice_type = request.dice_type.as_deref().unwrap_or("d6");
            let faces: u32 = dice_type
                .strip_prefix('d')
                .and_then(|s| s.parse().ok())
                .unwrap_or(6);

            let results = vault::roll_dice(&mut room.vault, dice_count, faces);
            let random_value = serde_json::to_value(&results).unwrap_or_default();

            vec![ServerMessage::RandomResult {
                game_id,
                random_type: "roll".to_string(),
                random_value,
            }]
        }
        RandomType::Draw => {
            let draw_count = request.draw_count.unwrap_or(1);
            let zone = request.draw_from.as_deref().unwrap_or("deck");

            let drawn = vault::draw_cards(&mut room.vault, zone, draw_count);
            let random_value = serde_json::to_value(&drawn).unwrap_or_default();

            vec![ServerMessage::RandomResult {
                game_id,
                random_type: "draw".to_string(),
                random_value,
            }]
        }
        RandomType::Shuffle => {
            let zone = request.shuffle_zone.as_deref().unwrap_or("deck");
            vault::shuffle_zone(&mut room.vault, zone);

            vec![ServerMessage::RandomResult {
                game_id,
                random_type: "shuffle".to_string(),
                random_value: serde_json::Value::Null,
            }]
        }
    }
}

/// Process an acknowledge_state message:
/// Compare the client's hash with the server's hash. If they diverge,
/// send a state_sync with the full authoritative state.
fn handle_acknowledge_state(
    room: &mut Room,
    _seat: &str,
    _player: &str,
    client_hash: &str,
) -> Vec<ServerMessage> {
    let game_id = room.id.clone();
    let server_hash = room.session.compute_state_hash();

    if client_hash == server_hash {
        // Hashes match — no response needed
        Vec::new()
    } else {
        // Desync detected — send full state
        eprintln!(
            "state desync in room {game_id}: client={client_hash}, server={server_hash}"
        );
        let wire_state = room.session.to_wire_state();
        let sequence = wire_state.sequence;
        let full_state = serde_json::to_value(&wire_state).unwrap_or_default();

        vec![ServerMessage::StateSync {
            game_id,
            sequence,
            full_state,
        }]
    }
}
