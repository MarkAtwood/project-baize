use std::collections::HashMap;
use std::sync::Arc;

use tokio::sync::{Mutex, RwLock};

use baize_engine::GameDefinition;
use baize_engine::GameSession;

use crate::vault::Vault;

/// A single game room: one game session with connected players.
pub struct Room {
    pub id: String,
    pub session: GameSession,
    pub vault: Vault,
    /// Map of player seat name to connected sender.
    pub players: HashMap<String, PlayerConnection>,
}

/// Tracks a connected player's WebSocket sender.
pub struct PlayerConnection {
    pub seat: String,
    pub tx: tokio::sync::mpsc::UnboundedSender<String>,
}

/// Registry of all active rooms.
pub struct RoomRegistry {
    rooms: RwLock<HashMap<String, Arc<Mutex<Room>>>>,
}

impl RoomRegistry {
    pub fn new() -> Self {
        Self {
            rooms: RwLock::new(HashMap::new()),
        }
    }

    /// Create a new room from a game definition JSON string.
    /// Returns the room ID.
    pub async fn create_room(
        &self,
        room_id: String,
        definition_json: &str,
    ) -> Result<String, String> {
        let definition =
            GameDefinition::from_json(definition_json).map_err(|e| e.to_string())?;
        let session = GameSession::new(definition).map_err(|e| e.to_string())?;
        let vault = Vault::new();

        let room = Room {
            id: room_id.clone(),
            session,
            vault,
            players: HashMap::new(),
        };

        let mut rooms = self.rooms.write().await;
        rooms.insert(room_id.clone(), Arc::new(Mutex::new(room)));
        Ok(room_id)
    }

    /// Get a room by ID, creating it with a default placeholder definition if
    /// it does not exist yet. In production, rooms would be created explicitly
    /// via an API; this fallback keeps the skeleton functional.
    pub async fn get_or_create_room(&self, room_id: &str) -> Arc<Mutex<Room>> {
        // Fast path: room exists
        {
            let rooms = self.rooms.read().await;
            if let Some(room) = rooms.get(room_id) {
                return Arc::clone(room);
            }
        }

        // Slow path: create with a minimal placeholder definition
        let definition_json = default_definition();
        // Ignore create errors for the skeleton — just log
        if let Err(e) = self.create_room(room_id.to_string(), &definition_json).await {
            eprintln!("failed to auto-create room {room_id}: {e}");
        }

        let rooms = self.rooms.read().await;
        rooms
            .get(room_id)
            .expect("room should exist after creation")
            .clone()
    }

    /// List all room IDs.
    pub async fn list_rooms(&self) -> Vec<String> {
        let rooms = self.rooms.read().await;
        rooms.keys().cloned().collect()
    }
}

/// Join a room as a player. Returns an unbounded receiver for outbound messages.
pub fn join_room(
    room: &mut Room,
    seat: String,
) -> tokio::sync::mpsc::UnboundedReceiver<String> {
    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    room.players.insert(
        seat.clone(),
        PlayerConnection {
            seat,
            tx,
        },
    );
    rx
}

/// Broadcast a JSON message to all connected players in a room.
pub fn broadcast(room: &Room, message: &str) {
    for conn in room.players.values() {
        let _ = conn.tx.send(message.to_string());
    }
}

/// Send a JSON message to a specific player.
pub fn send_to_player(room: &Room, seat: &str, message: &str) {
    if let Some(conn) = room.players.get(seat) {
        let _ = conn.tx.send(message.to_string());
    }
}

/// A minimal game definition used when auto-creating rooms for the skeleton.
/// Describes a 2-player perfect-information game with an 8x8 board.
fn default_definition() -> String {
    serde_json::json!({
        "game": {
            "name": "placeholder",
            "players": ["white", "black"],
            "information": "perfect"
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "visibility": "public",
                "dimensions": [8, 8]
            }
        },
        "components": {},
        "turn_order": {
            "type": "alternating",
            "players": ["white", "black"]
        },
        "phases": [],
        "rules": {},
        "end_conditions": [
            {
                "result": "draw",
                "condition": "no_legal_moves"
            }
        ],
        "authority": {
            "server_only": [],
            "client_verifiable": ["move_piece", "place", "pass", "resign"]
        }
    })
    .to_string()
}
