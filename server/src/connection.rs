use std::collections::VecDeque;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::extract::ws::{Message, WebSocket};
use axum::extract::{ConnectInfo, Path, State, WebSocketUpgrade};
use axum::response::IntoResponse;
use tokio::sync::Mutex;

use crate::config;
use crate::protocol::{self, HandleResult};
use crate::room::{self, Room, RoomRegistry};

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

    // Check room capacity and get/create the room
    let room = match registry.get_or_create_room(&room_id).await {
        Ok(r) => r,
        Err(e) => {
            eprintln!("[error] failed to get/create room '{room_id}': {e}");
            drop(ip_guard);
            return (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                format!("room unavailable: {e}"),
            )
                .into_response();
        }
    };

    // Configure WebSocket with message size limit
    ws.max_message_size(config::MAX_MESSAGE_SIZE)
        .on_upgrade(move |socket| handle_socket(socket, room, room_id, ip_guard))
        .into_response()
}

/// Per-connection rate limiter using a sliding window of message timestamps.
struct RateLimiter {
    /// Timestamps of recent messages within the current window.
    timestamps: VecDeque<Instant>,
    /// Maximum allowed messages per second.
    max_per_second: usize,
}

impl RateLimiter {
    fn new(max_per_second: usize) -> Self {
        Self {
            timestamps: VecDeque::with_capacity(max_per_second + 1),
            max_per_second,
        }
    }

    /// Record a message arrival. Returns `true` if the message is allowed,
    /// `false` if the rate limit is exceeded.
    fn check(&mut self) -> bool {
        let now = Instant::now();
        let window_start = now - Duration::from_secs(1);

        // Drop timestamps older than the 1-second window
        while self
            .timestamps
            .front()
            .is_some_and(|&t| t < window_start)
        {
            self.timestamps.pop_front();
        }

        if self.timestamps.len() >= self.max_per_second {
            return false;
        }

        self.timestamps.push_back(now);
        true
    }
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

    // Assign a seat and get the outbound receiver
    let join_result = {
        let mut room_guard = room.lock().await;

        // Check room capacity
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
        let rx = room::join_room(&mut room_guard, seat.clone());
        eprintln!("player '{seat}' joined room '{room_id}'");

        // Send initial state sync
        let state = room_guard.session.to_wire_state();
        let sync_msg = serde_json::json!({
            "message_type": "state_sync",
            "game_id": room_guard.id,
            "sequence": state.sequence,
            "full_state": serde_json::to_value(&state).unwrap_or_default(),
        });
        room::send_to_player(&room_guard, &seat, &sync_msg.to_string());

        (seat, rx)
    };

    let (seat, mut outbound_rx) = join_result;

    // Main select loop with idle timeout
    loop {
        tokio::select! {
            // Outbound: forward queued messages to the WebSocket
            Some(msg) = outbound_rx.recv() => {
                if socket.send(Message::Text(msg.into())).await.is_err() {
                    break;
                }
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
                                    let json =
                                        serde_json::to_string(&response).unwrap_or_default();
                                    room::broadcast(&room_guard, &json);
                                }
                            }
                            HandleResult::Reply(responses) => {
                                for response in responses {
                                    let json =
                                        serde_json::to_string(&response).unwrap_or_default();
                                    room::send_to_player(&room_guard, &seat, &json);
                                }
                            }
                            HandleResult::Error(err_json) => {
                                room::send_to_player(&room_guard, &seat, &err_json);
                            }
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
        room_guard.players.remove(&seat);
        eprintln!("player '{seat}' left room '{room_id}'");
    }
    // _ip_guard drops here, releasing the per-IP connection slot
}

/// Pick the next available seat for a connecting player.
fn pick_seat(room: &Room) -> String {
    let defined_players: Vec<String> = room
        .session
        .runtime
        .players
        .keys()
        .cloned()
        .collect();

    for name in &defined_players {
        if !room.players.contains_key(name) {
            return name.clone();
        }
    }

    // All seats taken -- assign as spectator with a numbered seat
    format!("spectator_{}", room.players.len())
}
