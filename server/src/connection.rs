use std::sync::Arc;

use axum::extract::ws::{Message, WebSocket};
use axum::extract::{Path, State, WebSocketUpgrade};
use axum::response::IntoResponse;
use tokio::sync::Mutex;

use crate::protocol;
use crate::room::{self, Room, RoomRegistry};

/// Axum handler: upgrade HTTP to WebSocket for a given room.
pub async fn ws_handler(
    ws: WebSocketUpgrade,
    Path(room_id): Path<String>,
    State(registry): State<Arc<RoomRegistry>>,
) -> impl IntoResponse {
    let room = registry.get_or_create_room(&room_id).await;
    ws.on_upgrade(move |socket| handle_socket(socket, room))
}

/// Main per-connection loop.
///
/// Axum 0.8's WebSocket provides `recv()` and `send()` on a single
/// mutable reference, so we split the socket into two halves by
/// extracting the outbound channel: a tokio mpsc channel receives
/// protocol responses and a dedicated task forwards them to the socket.
async fn handle_socket(mut socket: WebSocket, room: Arc<Mutex<Room>>) {
    // Assign a seat and get the outbound receiver
    let (seat, mut outbound_rx) = {
        let mut room_guard = room.lock().await;
        let seat = pick_seat(&room_guard);
        let rx = room::join_room(&mut room_guard, seat.clone());
        eprintln!("player '{seat}' joined room '{}'", room_guard.id);

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

    // We need to handle both directions concurrently. Since axum's
    // WebSocket does not support split(), we use a channel-based
    // approach: outbound messages are collected and sent whenever
    // the socket is free.
    loop {
        tokio::select! {
            // Outbound: forward queued messages to the WebSocket
            Some(msg) = outbound_rx.recv() => {
                if socket.send(Message::text(msg)).await.is_err() {
                    break;
                }
            }

            // Inbound: read from the WebSocket
            result = socket.recv() => {
                match result {
                    Some(Ok(Message::Text(text))) => {
                        let mut room_guard = room.lock().await;
                        let responses =
                            protocol::handle_client_message(&mut room_guard, &seat, &text);
                        for response in responses {
                            let json = serde_json::to_string(&response).unwrap_or_default();
                            room::broadcast(&room_guard, &json);
                        }
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Err(_)) => break,
                    _ => {} // Ping/Pong/Binary — ignore
                }
            }
        }
    }

    // Clean up: remove player from room
    {
        let mut room_guard = room.lock().await;
        room_guard.players.remove(&seat);
        eprintln!("player '{seat}' left room '{}'", room_guard.id);
    }
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

    // All seats taken — assign as spectator with a numbered seat
    format!("spectator_{}", room.players.len())
}
