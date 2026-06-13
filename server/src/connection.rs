use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket};
use axum::extract::{ConnectInfo, Json, Path, State, WebSocketUpgrade};
use axum::response::IntoResponse;
use rand::Rng;
use tokio::sync::Mutex;

use baize_engine::action::{Hello, PROTOCOL_VERSION};
use baize_engine::transition::apply_claim;
use baize_engine::visibility::filter_for_viewer_with_fog;

use crate::config;
use crate::protocol::{self, HandleResult};
use crate::room::{self, Room, RoomRegistry};

use baize_server::rate_limiter::RateLimiter;

/// Validate a room ID: must be 1-64 chars, alphanumeric plus hyphens and underscores.
fn validate_room_id(room_id: &str) -> Result<(), String> {
    if room_id.is_empty() {
        return Err("room ID must not be empty".to_string());
    }
    if room_id.len() > config::MAX_ROOM_ID_LENGTH {
        return Err(format!(
            "room ID too long ({len} chars, max {max})",
            len = room_id.len(),
            max = config::MAX_ROOM_ID_LENGTH
        ));
    }
    if !room_id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("room ID must be alphanumeric (plus hyphens and underscores)".to_string());
    }
    Ok(())
}

/// Build a JSON error string for protocol-level errors sent to the client.
fn ws_error_json(code: &str, detail: &str) -> String {
    serde_json::json!({
        "message_type": "error",
        "error_code": code,
        "detail": detail,
    })
    .to_string()
}

/// Axum handler: upgrade HTTP to WebSocket for a given room.
pub async fn ws_handler(
    ws: WebSocketUpgrade,
    Path(room_id): Path<String>,
    State(registry): State<Arc<RoomRegistry>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
) -> impl IntoResponse {
    // Validate room ID before doing anything else
    if let Err(e) = validate_room_id(&room_id) {
        eprintln!(
            "[security] rejected invalid room ID '{room_id}' from {addr}: {e}"
        );
        return (
            axum::http::StatusCode::BAD_REQUEST,
            format!("invalid room ID: {e}"),
        )
            .into_response();
    }

    // Enforce per-IP connection limit
    let ip = addr.ip();
    let ip_guard = match registry.acquire_ip_slot(ip).await {
        Ok(guard) => guard,
        Err(e) => {
            eprintln!("[security] IP connection limit reached for {addr}: {e}");
            return (axum::http::StatusCode::TOO_MANY_REQUESTS, e).into_response();
        }
    };

    // Look up existing room (rooms must be created via POST /rooms first)
    let room = match registry.get_room(&room_id).await {
        Some(r) => r,
        None => {
            drop(ip_guard);
            return (
                axum::http::StatusCode::NOT_FOUND,
                format!("room '{room_id}' does not exist — create it via POST /rooms first"),
            )
                .into_response();
        }
    };

    // Configure WebSocket with message size limit
    ws.max_message_size(config::MAX_MESSAGE_SIZE)
        .on_upgrade(move |socket| handle_socket(socket, room, room_id, ip_guard))
        .into_response()
}

/// Main per-connection loop.
///
/// Handles:
/// - Rate limiting (sliding window)
/// - Idle timeout (5 min)
/// - Sequence number tracking
/// - Graceful error handling (never panics on malformed input)
async fn handle_socket(
    mut socket: WebSocket,
    room: Arc<Mutex<Room>>,
    room_id: String,
    _ip_guard: room::IpConnectionGuard,
) {
    let idle_timeout = Duration::from_secs(config::IDLE_TIMEOUT_SECS);
    let mut rate_limiter = RateLimiter::new(config::MAX_MESSAGES_PER_SECOND);
    let mut expected_seq: u64 = 0;

    // --- Handshake: wait for Hello ---
    let hello = match tokio::time::timeout(Duration::from_secs(5), socket.recv()).await {
        Ok(Some(Ok(Message::Text(text)))) => {
            match serde_json::from_str::<serde_json::Value>(&text) {
                Ok(v) if v.get("message_type").and_then(|t| t.as_str()) == Some("hello") => {
                    match serde_json::from_value::<Hello>(v) {
                        Ok(h) => h,
                        Err(e) => {
                            let err = ws_error_json("invalid_hello", &format!("bad hello: {e}"));
                            let _ = socket.send(Message::Text(err.into())).await;
                            return;
                        }
                    }
                }
                _ => {
                    let err = ws_error_json(
                        "handshake_required",
                        "first message must be {\"message_type\": \"hello\", \"protocol_version\": 1}",
                    );
                    let _ = socket.send(Message::Text(err.into())).await;
                    return;
                }
            }
        }
        Ok(Some(Ok(Message::Close(_)))) | Ok(None) => return,
        Ok(Some(Err(e))) => {
            eprintln!("websocket error during handshake in room '{room_id}': {e}");
            return;
        }
        Err(_) => {
            let err = ws_error_json("handshake_timeout", "hello not received within 5 seconds");
            let _ = socket.send(Message::Text(err.into())).await;
            return;
        }
        _ => return,
    };

    // Validate protocol version
    if hello.protocol_version != PROTOCOL_VERSION {
        let err = ws_error_json(
            "version_mismatch",
            &format!(
                "server speaks protocol v{PROTOCOL_VERSION}, client sent v{}",
                hello.protocol_version
            ),
        );
        let _ = socket.send(Message::Text(err.into())).await;
        return;
    }

    // --- Seat assignment (token-aware) ---
    let join_result = {
        let mut room_guard = room.lock().await;

        // Check for reconnection via token
        let (seat, token) = if let Some(ref client_token) = hello.token {
            if let Some(existing_seat) = room::seat_for_token(&room_guard, client_token) {
                // Reconnection: reclaim the seat, reuse token
                eprintln!(
                    "player '{existing_seat}' reconnecting to room '{room_id}'"
                );
                (existing_seat, client_token.clone())
            } else {
                // Unknown token — treat as new connection
                if !room::room_has_capacity(&room_guard) {
                    let err = ws_error_json("room_full", "this room is at player capacity");
                    let _ = socket.send(Message::Text(err.into())).await;
                    return;
                }
                let seat = pick_seat(&room_guard);
                let token = room::register_token(&mut room_guard, &seat);
                (seat, token)
            }
        } else {
            // No token — new connection
            if !room::room_has_capacity(&room_guard) {
                eprintln!(
                    "[security] room '{room_id}' is full ({max} players)",
                    max = room_guard.max_players
                );
                let err = ws_error_json("room_full", "this room is at player capacity");
                let _ = socket.send(Message::Text(err.into())).await;
                return;
            }
            let seat = pick_seat(&room_guard);
            let token = room::register_token(&mut room_guard, &seat);
            (seat, token)
        };

        let rx = room::join_room(&mut room_guard, seat.clone());
        eprintln!(
            "player '{seat}' ({:?}) joined room '{room_id}' [proto v{}]",
            hello.client_type, hello.protocol_version
        );

        // Send Welcome with auth token
        let welcome = serde_json::json!({
            "message_type": "welcome",
            "protocol_version": PROTOCOL_VERSION,
            "server_version": env!("CARGO_PKG_VERSION"),
            "seat": seat,
            "game_id": room_guard.id,
            "token": token,
        });
        room::send_to_player(&room_guard, &seat, &welcome.to_string());

        // Send initial state sync (filtered for this player)
        let state = room_guard.session.to_wire_state();
        let filtered = filter_for_viewer_with_fog(
            &state,
            &seat,
            &room_guard.session.definition,
            Some(&room_guard.session.runtime.zones),
        );
        let sync_msg = serde_json::json!({
            "message_type": "state_sync",
            "game_id": room_guard.id,
            "sequence": state.sequence,
            "full_state": serde_json::to_value(&filtered)
                .expect("filtered state should serialize to JSON"),
        });
        room::send_to_player(&room_guard, &seat, &sync_msg.to_string());

        (seat, rx)
    };

    let (seat, mut outbound_rx) = join_result;

    // Local mirror of the room's claim deadline so we can drive
    // the select! branch without locking the room every iteration.
    let mut local_claim_deadline: Option<tokio::time::Instant> = None;

    // Main select loop with idle timeout
    loop {
        // Build a future that fires at the claim deadline (or never).
        let claim_sleep = async {
            match local_claim_deadline {
                Some(deadline) => tokio::time::sleep_until(deadline).await,
                None => std::future::pending().await,
            }
        };

        tokio::select! {
            // Outbound: forward queued messages to the WebSocket
            Some(msg) = outbound_rx.recv() => {
                if socket.send(Message::Text(msg.into())).await.is_err() {
                    break;
                }
            }

            // Claim window timeout: auto-submit defaults for non-respondents
            () = claim_sleep => {
                local_claim_deadline = None;
                let mut room_guard = room.lock().await;

                // Another connection may have already resolved the window
                if room_guard.claim_deadline.is_some()
                    && room_guard.session.runtime.claim_window.is_some()
                {
                    handle_claim_timeout(&mut room_guard);
                }
                room_guard.claim_deadline = None;
            }

            // Inbound: read from the WebSocket with idle timeout
            result = async {
                tokio::time::timeout(idle_timeout, socket.recv()).await
            } => {
                match result {
                    // Timeout: no message within the idle window
                    Err(_elapsed) => {
                        eprintln!(
                            "idle timeout for player '{seat}' in room '{room_id}' \
                             (no message for {secs}s)",
                            secs = config::IDLE_TIMEOUT_SECS
                        );
                        let err = ws_error_json(
                            "idle_timeout",
                            &format!(
                                "disconnected after {}s of inactivity",
                                config::IDLE_TIMEOUT_SECS
                            ),
                        );
                        let _ = socket.send(Message::Text(err.into())).await;
                        break;
                    }

                    // Got a message (or connection event)
                    Ok(Some(Ok(Message::Text(text)))) => {
                        // Rate limit check
                        if !rate_limiter.check() {
                            eprintln!(
                                "[security] rate limit exceeded for player '{seat}' \
                                 in room '{room_id}'"
                            );
                            let err = ws_error_json(
                                "rate_limited",
                                &format!(
                                    "too many messages (max {}/s)",
                                    config::MAX_MESSAGES_PER_SECOND
                                ),
                            );
                            if socket.send(Message::Text(err.into())).await.is_err() {
                                break;
                            }
                            continue;
                        }

                        let mut room_guard = room.lock().await;
                        match protocol::handle_client_message(
                            &mut room_guard,
                            &seat,
                            &text,
                            &mut expected_seq,
                        ) {
                            HandleResult::Broadcast(responses) => {
                                for response in responses {
                                    let json = serde_json::to_string(&response)
                                        .expect("ServerMessage should serialize to JSON");
                                    room::broadcast(&room_guard, &json);
                                }
                            }
                            HandleResult::FilteredBroadcast { per_player } => {
                                for (target_seat, msg) in per_player {
                                    let json = serde_json::to_string(&msg)
                                        .expect("ServerMessage should serialize to JSON");
                                    room::send_to_player(
                                        &room_guard,
                                        &target_seat,
                                        &json,
                                    );
                                }
                            }
                            HandleResult::Reply(responses) => {
                                for response in responses {
                                    let json = serde_json::to_string(&response)
                                        .expect("ServerMessage should serialize to JSON");
                                    room::send_to_player(&room_guard, &seat, &json);
                                }
                            }
                            HandleResult::Error(err_json) => {
                                room::send_to_player(&room_guard, &seat, &err_json);
                            }
                        }

                        // After processing, check if a claim window was opened
                        // and set deadline if not already set
                        if room_guard.session.runtime.claim_window.is_some()
                            && room_guard.claim_deadline.is_none()
                        {
                            let timeout_secs = claim_timeout_secs(&room_guard);
                            let deadline = tokio::time::Instant::now()
                                + Duration::from_secs(timeout_secs);
                            room_guard.claim_deadline = Some(deadline);
                            local_claim_deadline = Some(deadline);
                        } else if room_guard.session.runtime.claim_window.is_none() {
                            // Window was resolved (possibly by this claim)
                            room_guard.claim_deadline = None;
                            local_claim_deadline = None;
                        } else {
                            // Sync local deadline with room (another conn may have set it)
                            local_claim_deadline = room_guard.claim_deadline;
                        }
                    }

                    Ok(Some(Ok(Message::Close(_)))) | Ok(None) => break,
                    Ok(Some(Err(e))) => {
                        eprintln!(
                            "websocket error for player '{seat}' in room '{room_id}': {e}"
                        );
                        break;
                    }
                    // Ping/Pong/Binary -- ignore (do NOT reset idle timer
                    // for binary frames to prevent keep-alive abuse)
                    _ => {}
                }
            }
        }
    }

    // Clean up: remove player from room
    {
        let mut room_guard = room.lock().await;
        let had_player = room_guard.players.remove(&seat).is_some();
        debug_assert!(
            had_player,
            "connection: player '{seat}' was not in room '{room_id}' at disconnect"
        );
        // Postcondition: player count must not exceed max_players after removal
        debug_assert!(
            room_guard.players.len() <= room_guard.max_players + config::MAX_CONNECTIONS_PER_IP,
            "connection: postcondition failed — player count {} exceeds bounds after removal",
            room_guard.players.len()
        );
        eprintln!("player '{seat}' left room '{room_id}'");
    }
    // _ip_guard drops here, releasing the per-IP connection slot
}

/// Request body for POST /rooms.
#[derive(serde::Deserialize)]
pub struct CreateRoomRequest {
    /// Optional room ID. Auto-generated if not provided.
    pub room_id: Option<String>,
    /// Full game definition JSON.
    pub definition: serde_json::Value,
}

/// Response body for POST /rooms.
#[derive(serde::Serialize)]
pub struct CreateRoomResponse {
    pub room_id: String,
    pub game_name: String,
    pub max_players: usize,
}

/// Room summary for GET /rooms.
#[derive(serde::Serialize)]
pub struct RoomSummary {
    pub room_id: String,
    pub game_name: String,
    pub players_connected: usize,
    pub max_players: usize,
}

/// Generate a random room ID: 8 lowercase hex characters.
fn generate_room_id() -> String {
    let mut rng = rand::rng();
    let val: u32 = rng.random();
    format!("{val:08x}")
}

/// Axum handler: create a new room with a game definition.
pub async fn create_room_handler(
    State(registry): State<Arc<RoomRegistry>>,
    Json(body): Json<CreateRoomRequest>,
) -> impl IntoResponse {
    let room_id = body.room_id.unwrap_or_else(generate_room_id);

    if let Err(e) = validate_room_id(&room_id) {
        return (
            axum::http::StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": format!("invalid room_id: {e}") })),
        )
            .into_response();
    }

    let definition_json = body.definition.to_string();

    // Validate by parsing the definition through the engine
    let definition = match baize_engine::GameDefinition::from_json(&definition_json) {
        Ok(d) => d,
        Err(e) => {
            return (
                axum::http::StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": format!("invalid game definition: {e}") })),
            )
                .into_response();
        }
    };

    let game_name = definition.game.name.clone();
    let max_players = match &definition.game.players {
        baize_engine::definition::Players::Named(names) => names.len(),
        baize_engine::definition::Players::Range { max, .. } => *max as usize,
    };

    match registry.create_room(room_id.clone(), &definition_json).await {
        Ok(_) => (
            axum::http::StatusCode::CREATED,
            Json(serde_json::json!(CreateRoomResponse {
                room_id,
                game_name,
                max_players,
            })),
        )
            .into_response(),
        Err(e) => (
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            Json(serde_json::json!({ "error": e })),
        )
            .into_response(),
    }
}

/// Axum handler: list active rooms.
pub async fn list_rooms_handler(
    State(registry): State<Arc<RoomRegistry>>,
) -> impl IntoResponse {
    let room_ids = registry.list_rooms().await;
    let mut rooms = Vec::new();

    for room_id in room_ids {
        if let Some(room_arc) = registry.get_room(&room_id).await {
            let room_guard = room_arc.lock().await;
            rooms.push(RoomSummary {
                room_id: room_id.clone(),
                game_name: room_guard.session.definition.game.name.clone(),
                players_connected: room_guard.players.len(),
                max_players: room_guard.max_players,
            });
        }
    }

    Json(rooms)
}

/// Compute the claim timeout for a room, checking the game definition's
/// trigger-specific timeout first, then falling back to the server default.
fn claim_timeout_secs(room: &Room) -> u64 {
    if let Some(ref window) = room.session.runtime.claim_window {
        if let Some(trigger_def) = room.session.definition.triggers.get(&window.trigger_name) {
            if let Some(timeout) = trigger_def.claim_window.timeout {
                return timeout as u64;
            }
        }
    }
    config::DEFAULT_CLAIM_TIMEOUT_SECS
}

/// Handle claim window timeout: submit default claims for all non-respondent
/// eligible players, then broadcast the resolved state.
///
/// Precondition: caller must hold the room lock and verify that
/// `claim_window` is `Some` before calling.
fn handle_claim_timeout(room: &mut Room) {
    let game_id = room.id.clone();

    // Collect non-respondent players and the default claim
    let (pending_players, default_claim) = {
        // claim_window verified present by caller
        let window = room.session.runtime.claim_window.as_ref()
            .expect("handle_claim_timeout called without active claim window");
        let pending: Vec<String> = window
            .eligible_players
            .iter()
            .filter(|p| !window.submitted_claims.contains_key(p.as_str()))
            .cloned()
            .collect();
        (pending, window.default_claim.clone())
    };

    if pending_players.is_empty() {
        return;
    }

    eprintln!(
        "claim window timeout in room '{game_id}': auto-submitting '{default_claim}' \
         for {} non-respondent player(s)",
        pending_players.len()
    );

    // Submit default claims for each non-respondent
    for player in &pending_players {
        match apply_claim(&mut room.session, player, &default_claim) {
            Ok(_events) => {}
            Err(e) => {
                // Should not happen: default claim is always valid
                eprintln!(
                    "[error] failed to auto-submit default claim for \
                     player '{player}' in room '{game_id}': {e}"
                );
                break;
            }
        }
    }

    // Broadcast resolved state to all connected players
    if room.session.runtime.claim_window.is_none() {
        let wire_state = room.session.to_wire_state();
        let definition = &room.session.definition;

        for (seat_name, conn) in &room.players {
            let filtered = filter_for_viewer_with_fog(
                &wire_state,
                seat_name,
                definition,
                Some(&room.session.runtime.zones),
            );
            let sync_msg = serde_json::json!({
                "message_type": "state_sync",
                "game_id": game_id,
                "sequence": wire_state.sequence,
                "full_state": serde_json::to_value(&filtered)
                    .expect("filtered state should serialize to JSON"),
            });
            if conn.tx.try_send(sync_msg.to_string()).is_err() {
                eprintln!(
                    "[warning] outbound queue full for player '{seat_name}' \
                     during claim timeout broadcast"
                );
            }
        }
    }
}

/// Pick the next available seat for a connecting player.
///
/// Precondition: room must have at least one defined player in the game definition.
/// Postcondition: returned seat name is never empty.
fn pick_seat(room: &Room) -> String {
    let defined_players: Vec<String> = room
        .session
        .runtime
        .players
        .keys()
        .cloned()
        .collect();

    debug_assert!(
        !defined_players.is_empty(),
        "connection: pick_seat called on room with no defined players"
    );

    for name in &defined_players {
        if !room.players.contains_key(name) {
            debug_assert!(
                !name.is_empty(),
                "connection: defined player name must not be empty"
            );
            return name.clone();
        }
    }

    // All seats taken -- assign as spectator with a numbered seat
    let seat = format!("spectator_{}", room.players.len());
    debug_assert!(
        !seat.is_empty(),
        "connection: pick_seat produced empty seat name"
    );
    seat
}
