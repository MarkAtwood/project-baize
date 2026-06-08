use baize_engine::action::{ClientMessage, RandomRequest, RandomType, ServerMessage};
use baize_engine::state::GameStatus;
use baize_engine::transition::apply_action;

use crate::config;
use crate::room::Room;
use crate::vault;

/// Structured error sent to the client for protocol violations.
fn error_response(game_id: &str, code: &str, detail: &str) -> String {
    serde_json::json!({
        "message_type": "error",
        "game_id": game_id,
        "error_code": code,
        "detail": detail,
    })
    .to_string()
}

/// Outcome of handling a client message.
pub enum HandleResult {
    /// Broadcast these server messages to all players.
    Broadcast(Vec<ServerMessage>),
    /// Send a reply only to the originating player (not broadcast).
    Reply(Vec<ServerMessage>),
    /// Send an error only to the originating player.
    Error(String),
}

/// Handle an incoming client message (JSON text) and return server responses.
///
/// Validates:
/// - JSON parse
/// - Player name matches the connection's assigned seat
/// - Sequence number is monotonically increasing (if present)
///
/// `expected_seq` is the next expected sequence number for this connection.
/// Updated in-place on success.
pub fn handle_client_message(
    room: &mut Room,
    seat: &str,
    raw: &str,
    expected_seq: &mut u64,
) -> HandleResult {
    let game_id = room.id.clone();

    // Parse JSON
    let msg: ClientMessage = match serde_json::from_str(raw) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("[security] malformed JSON from seat '{seat}' in room '{game_id}': {e}");
            return HandleResult::Error(error_response(
                &game_id,
                "invalid_message",
                &format!("malformed JSON: {e}"),
            ));
        }
    };

    // Extract common fields for validation
    let (msg_player, msg_game_id, msg_seq) = match &msg {
        ClientMessage::SubmitMove {
            game_id,
            player,
            sequence,
            ..
        } => (player.as_str(), game_id.as_str(), *sequence),
        ClientMessage::RequestRandom {
            game_id, player, ..
        } => (player.as_str(), game_id.as_str(), None),
        ClientMessage::AcknowledgeState {
            game_id, player, ..
        } => (player.as_str(), game_id.as_str(), None),
    };

    // Validate player name matches seat
    if msg_player != seat {
        eprintln!(
            "[security] seat mismatch in room '{game_id}': seat='{seat}', \
             claimed player='{msg_player}'"
        );
        return HandleResult::Error(error_response(
            &game_id,
            "seat_mismatch",
            &format!(
                "you are seated as '{seat}' but claimed to be '{msg_player}'"
            ),
        ));
    }

    // Validate game_id matches the room
    if msg_game_id != game_id {
        eprintln!(
            "[security] game_id mismatch from seat '{seat}': \
             room='{game_id}', message='{msg_game_id}'"
        );
        return HandleResult::Error(error_response(
            &game_id,
            "game_id_mismatch",
            &format!(
                "this room is '{game_id}' but message targets '{msg_game_id}'"
            ),
        ));
    }

    // Validate sequence number (if present): must be monotonically increasing
    if let Some(seq) = msg_seq {
        if seq < *expected_seq {
            eprintln!(
                "[security] replayed/out-of-order sequence from seat '{seat}' \
                 in room '{game_id}': got {seq}, expected >= {expected_seq}"
            );
            return HandleResult::Error(error_response(
                &game_id,
                "sequence_error",
                &format!(
                    "sequence {seq} is out of order (expected >= {expected_seq})"
                ),
            ));
        }
        *expected_seq = seq + 1;
    }

    // Reject game-altering messages from spectators
    let is_spectator = seat.starts_with("spectator_");

    // Dispatch to handlers
    match msg {
        ClientMessage::SubmitMove {
            action, player, ..
        } => {
            if is_spectator {
                return HandleResult::Error(error_response(
                    &game_id,
                    "spectator_not_allowed",
                    "spectators cannot submit moves",
                ));
            }
            // Validate action fields
            if let Err(e) = validate_action(&action) {
                eprintln!(
                    "[security] invalid action from seat '{seat}' in room '{game_id}': {e}"
                );
                return HandleResult::Error(error_response(
                    &game_id,
                    "invalid_action",
                    &e,
                ));
            }
            handle_submit_move(room, seat, &player, action)
        }

        ClientMessage::RequestRandom {
            random_request,
            player,
            ..
        } => {
            if is_spectator {
                return HandleResult::Error(error_response(
                    &game_id,
                    "spectator_not_allowed",
                    "spectators cannot request random values",
                ));
            }
            // Turn check: only the current player may request random values
            let current = room
                .session
                .current_player()
                .unwrap_or("")
                .to_string();
            if current != player {
                return HandleResult::Error(error_response(
                    &game_id,
                    "not_your_turn",
                    &format!(
                        "not your turn to request random (current: {current})"
                    ),
                ));
            }
            if let Err(e) = validate_random_request(&random_request) {
                eprintln!(
                    "[security] invalid random request from seat '{seat}' \
                     in room '{game_id}': {e}"
                );
                return HandleResult::Error(error_response(
                    &game_id,
                    "invalid_random_request",
                    &e,
                ));
            }
            HandleResult::Broadcast(handle_request_random(
                room,
                seat,
                &player,
                random_request,
            ))
        }

        ClientMessage::AcknowledgeState {
            state_hash,
            player,
            ..
        } => {
            // BLAKE3 hex digest is exactly 64 chars
            if state_hash.len() != 64
                || !state_hash.chars().all(|c| c.is_ascii_hexdigit())
            {
                return HandleResult::Error(error_response(
                    &game_id,
                    "invalid_state_hash",
                    "state_hash must be a 64-character hex string",
                ));
            }
            // StateSync is sent only to the requesting player to prevent
            // leaking hidden/private zone contents to other players.
            HandleResult::Reply(handle_acknowledge_state(
                room,
                seat,
                &player,
                &state_hash,
            ))
        }
    }
}

/// Validate action fields for sanity.
fn validate_action(action: &baize_engine::action::Action) -> Result<(), String> {
    // Validate string fields: non-empty and bounded length
    let string_fields: &[(&str, &Option<String>)] = &[
        ("component_id", &action.component_id),
        ("component_type", &action.component_type),
        ("zone", &action.zone),
        ("promote_to", &action.promote_to),
        ("swap_with", &action.swap_with),
        ("declaration", &action.declaration),
        ("dice_type", &action.dice_type),
    ];
    for (name, field) in string_fields {
        if let Some(v) = field {
            if v.is_empty() {
                return Err(format!("{name} must not be empty"));
            }
            if v.len() > config::MAX_ACTION_FIELD_LENGTH {
                return Err(format!(
                    "{name} too long ({} chars, max {})",
                    v.len(),
                    config::MAX_ACTION_FIELD_LENGTH
                ));
            }
        }
    }

    // rotation, if present, must be a valid value (0-359 degrees)
    if let Some(rot) = action.rotation {
        if rot >= 360 {
            return Err(format!("rotation {rot} out of range (0-359)"));
        }
    }

    // dice_count on an action must be bounded
    if let Some(dc) = action.dice_count {
        if dc > config::MAX_DICE_COUNT {
            return Err(format!(
                "dice_count {dc} exceeds maximum ({})",
                config::MAX_DICE_COUNT
            ));
        }
    }

    Ok(())
}

/// Validate a random request for sanity and DoS prevention.
fn validate_random_request(request: &RandomRequest) -> Result<(), String> {
    match request.random_type {
        RandomType::Roll => {
            if let Some(count) = request.dice_count {
                if count == 0 {
                    return Err("dice_count must be at least 1".to_string());
                }
                if count > config::MAX_DICE_COUNT {
                    return Err(format!(
                        "dice_count {count} exceeds maximum ({})",
                        config::MAX_DICE_COUNT
                    ));
                }
            }
            if let Some(ref dt) = request.dice_type {
                if dt.len() > 16 {
                    return Err("dice_type too long".to_string());
                }
                let faces: Option<u32> = dt.strip_prefix('d').and_then(|s| s.parse().ok());
                if let Some(f) = faces {
                    if f == 0 {
                        return Err("dice faces must be at least 1".to_string());
                    }
                    if f > config::MAX_DICE_FACES {
                        return Err(format!(
                            "dice faces {f} exceeds maximum ({})",
                            config::MAX_DICE_FACES
                        ));
                    }
                }
            }
        }
        RandomType::Draw => {
            if let Some(count) = request.draw_count {
                if count == 0 {
                    return Err("draw_count must be at least 1".to_string());
                }
                if count > config::MAX_DRAW_COUNT {
                    return Err(format!(
                        "draw_count {count} exceeds maximum ({})",
                        config::MAX_DRAW_COUNT
                    ));
                }
            }
            if let Some(ref zone) = request.draw_from {
                if zone.len() > config::MAX_ZONE_NAME_LENGTH {
                    return Err("draw_from zone name too long".to_string());
                }
            }
        }
        RandomType::Shuffle => {
            if let Some(ref zone) = request.shuffle_zone {
                if zone.len() > config::MAX_ZONE_NAME_LENGTH {
                    return Err("shuffle_zone name too long".to_string());
                }
            }
        }
    }
    Ok(())
}

/// Process a submit_move message:
/// 1. Verify it is this player's turn
/// 2. Apply the action through the engine
/// 3. Broadcast move_confirmed to all, or reply move_rejected to sender only
fn handle_submit_move(
    room: &mut Room,
    _seat: &str,
    player: &str,
    action: baize_engine::action::Action,
) -> HandleResult {
    let game_id = room.id.clone();

    // Check game is in progress or setup
    if room.session.runtime.status == GameStatus::Finished {
        return HandleResult::Reply(vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: "game is finished".to_string(),
        }]);
    }

    // Enforce max moves per game to prevent indefinite resource consumption
    if room.session.runtime.sequence >= config::MAX_MOVES_PER_GAME {
        eprintln!(
            "[security] game in room '{game_id}' exceeded max move count ({})",
            config::MAX_MOVES_PER_GAME
        );
        return HandleResult::Reply(vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: format!(
                "game exceeded maximum move count ({})",
                config::MAX_MOVES_PER_GAME
            ),
        }]);
    }

    // Check it is this player's turn
    let current = room
        .session
        .current_player()
        .unwrap_or("")
        .to_string();
    if current != player {
        return HandleResult::Reply(vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: format!("not your turn (current: {current})"),
        }]);
    }

    // Apply through the engine
    match apply_action(&mut room.session, &action) {
        Ok(_events) => {
            let wire_state = room.session.to_wire_state();
            let sequence = wire_state.sequence;
            let result_state = serde_json::to_value(&wire_state).ok();

            HandleResult::Broadcast(vec![ServerMessage::MoveConfirmed {
                game_id,
                sequence,
                action,
                result_state,
            }])
        }
        Err(e) => HandleResult::Reply(vec![ServerMessage::MoveRejected {
            game_id,
            action,
            reason: e.to_string(),
        }]),
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
        // Hashes match -- no response needed
        Vec::new()
    } else {
        // Desync detected -- send full state
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
