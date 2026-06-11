#![allow(dead_code)]

use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use tokio::sync::{Mutex, RwLock};

use baize_engine::GameDefinition;
use baize_engine::GameSession;

use crate::config;
use crate::store::Store;
use crate::vault::Vault;

/// A single game room: one game session with connected players.
pub struct Room {
    pub id: String,
    pub session: GameSession,
    pub vault: Vault,
    /// Map of player seat name to connected sender.
    pub players: HashMap<String, PlayerConnection>,
    /// Maximum number of players allowed (from game definition).
    pub max_players: usize,
    /// Map of auth token to seat name for reconnection.
    pub player_tokens: HashMap<String, String>,
}

/// Tracks a connected player's WebSocket sender.
pub struct PlayerConnection {
    pub seat: String,
    pub tx: tokio::sync::mpsc::Sender<String>,
}

/// Registry of all active rooms, with per-IP connection tracking.
pub struct RoomRegistry {
    rooms: RwLock<HashMap<String, Arc<Mutex<Room>>>>,
    /// Per-IP active connection count.
    ip_connections: RwLock<HashMap<IpAddr, Arc<AtomicUsize>>>,
    /// Optional persistence layer.
    store: Option<Arc<dyn Store>>,
}

impl Default for RoomRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl RoomRegistry {
    pub fn new() -> Self {
        Self {
            rooms: RwLock::new(HashMap::new()),
            ip_connections: RwLock::new(HashMap::new()),
            store: None,
        }
    }

    pub fn with_store(store: Arc<dyn Store>) -> Self {
        Self {
            rooms: RwLock::new(HashMap::new()),
            ip_connections: RwLock::new(HashMap::new()),
            store: Some(store),
        }
    }

    /// Restore rooms from the persistence store. Call once at startup.
    pub async fn restore_from_store(&self) -> Result<usize, String> {
        let store = match &self.store {
            Some(s) => s,
            None => return Ok(0),
        };
        let room_ids = store.list_rooms().map_err(|e| e.to_string())?;
        let mut restored = 0;
        for room_id in &room_ids {
            match store.load_room(room_id) {
                Ok(Some(data)) => {
                    if let Err(e) = self.create_room(room_id.clone(), &data.definition_json).await {
                        eprintln!("[store] failed to restore room {room_id}: {e}");
                    } else {
                        restored += 1;
                    }
                }
                Ok(None) => {}
                Err(e) => {
                    eprintln!("[store] error loading room {room_id}: {e}");
                }
            }
        }
        Ok(restored)
    }

    /// Try to acquire a connection slot for the given IP.
    /// Returns Ok(guard) if under the limit, Err(message) if at capacity.
    pub async fn acquire_ip_slot(&self, ip: IpAddr) -> Result<IpConnectionGuard, String> {
        let counter = {
            let mut map = self.ip_connections.write().await;
            // Lazy pruning: remove stale entries (counter == 0) to prevent
            // unbounded HashMap growth from unique IPs that have disconnected.
            map.retain(|_, c| c.load(Ordering::SeqCst) > 0);
            map.entry(ip)
                .or_insert_with(|| Arc::new(AtomicUsize::new(0)))
                .clone()
        };

        let current = counter.fetch_add(1, Ordering::SeqCst);
        if current >= config::MAX_CONNECTIONS_PER_IP {
            counter.fetch_sub(1, Ordering::SeqCst);
            return Err(format!(
                "too many connections from {ip} (max {max})",
                max = config::MAX_CONNECTIONS_PER_IP
            ));
        }

        Ok(IpConnectionGuard {
            ip,
            counter,
            released: false,
        })
    }

    /// Create a new room from a game definition JSON string.
    /// Returns the room ID.
    pub async fn create_room(
        &self,
        room_id: String,
        definition_json: &str,
    ) -> Result<String, String> {
        {
            let rooms = self.rooms.read().await;
            if rooms.len() >= config::MAX_ROOMS {
                return Err(format!(
                    "server at room capacity (max {max})",
                    max = config::MAX_ROOMS
                ));
            }
        }

        let definition =
            GameDefinition::from_json(definition_json).map_err(|e| e.to_string())?;
        let max_players = match &definition.game.players {
            baize_engine::definition::Players::Named(names) => names.len(),
            baize_engine::definition::Players::Range { max, .. } => *max as usize,
        };
        let session = GameSession::new(definition).map_err(|e| e.to_string())?;
        let vault = Vault::new();

        let room = Room {
            id: room_id.clone(),
            session,
            vault,
            players: HashMap::new(),
            max_players,
            player_tokens: HashMap::new(),
        };

        // Persist to store if available
        if let Some(ref store) = self.store {
            let state_json = serde_json::to_string(&room.session.to_wire_state())
                .unwrap_or_default();
            if let Err(e) = store.save_room(&room_id, definition_json, &state_json) {
                eprintln!("[store] failed to persist room {room_id}: {e}");
            }
        }

        let mut rooms = self.rooms.write().await;
        rooms.insert(room_id.clone(), Arc::new(Mutex::new(room)));
        Ok(room_id)
    }

    /// Get an existing room by ID. Returns None if the room does not exist.
    pub async fn get_room(&self, room_id: &str) -> Option<Arc<Mutex<Room>>> {
        let rooms = self.rooms.read().await;
        rooms.get(room_id).cloned()
    }

    /// List all room IDs.
    pub async fn list_rooms(&self) -> Vec<String> {
        let rooms = self.rooms.read().await;
        rooms.keys().cloned().collect()
    }

    /// Persist state and events for a room after a mutation.
    pub fn persist_state(&self, room: &Room, event_lines: &[String]) {
        if let Some(ref store) = self.store {
            let state_json =
                serde_json::to_string(&room.session.to_wire_state()).unwrap_or_default();
            if let Err(e) = store.update_state(&room.id, &state_json) {
                eprintln!("[store] failed to update state for {}: {e}", room.id);
            }
            if !event_lines.is_empty() {
                if let Err(e) = store.append_events(&room.id, event_lines) {
                    eprintln!("[store] failed to append events for {}: {e}", room.id);
                }
            }
        }
    }

    /// Return the current number of rooms.
    pub async fn room_count(&self) -> usize {
        let rooms = self.rooms.read().await;
        rooms.len()
    }
}

/// RAII guard that decrements the per-IP connection counter on drop.
pub struct IpConnectionGuard {
    ip: IpAddr,
    counter: Arc<AtomicUsize>,
    released: bool,
}

impl IpConnectionGuard {
    /// Explicitly release the slot (also happens on drop).
    pub fn release(&mut self) {
        if !self.released {
            self.counter.fetch_sub(1, Ordering::SeqCst);
            self.released = true;
        }
    }
}

impl Drop for IpConnectionGuard {
    fn drop(&mut self) {
        if !self.released {
            self.counter.fetch_sub(1, Ordering::SeqCst);
            eprintln!("ip connection slot released for {}", self.ip);
        }
    }
}

/// Generate a random 128-bit hex token for player authentication.
pub fn generate_player_token() -> String {
    use rand::Rng;
    let mut rng = rand::rng();
    let a: u64 = rng.random();
    let b: u64 = rng.random();
    format!("{a:016x}{b:016x}")
}

/// Look up a seat by auth token. Returns None if token is unknown.
pub fn seat_for_token(room: &Room, token: &str) -> Option<String> {
    room.player_tokens.get(token).cloned()
}

/// Register a token for a seat. Returns the token.
pub fn register_token(room: &mut Room, seat: &str) -> String {
    let token = generate_player_token();
    room.player_tokens.insert(token.clone(), seat.to_string());
    token
}

/// Check if the room has capacity for another player.
pub fn room_has_capacity(room: &Room) -> bool {
    room.players.len() < room.max_players
}

/// Join a room as a player. Returns a bounded receiver for outbound messages.
/// The channel has MAX_OUTBOUND_QUEUE capacity; if a client falls behind,
/// the send will fail and the connection should be dropped.
pub fn join_room(
    room: &mut Room,
    seat: String,
) -> tokio::sync::mpsc::Receiver<String> {
    let (tx, rx) = tokio::sync::mpsc::channel(config::MAX_OUTBOUND_QUEUE);
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
/// Uses try_send to avoid blocking; if a player's queue is full,
/// the message is dropped and a warning is logged (the connection
/// handler will detect the closed channel and disconnect).
pub fn broadcast(room: &Room, message: &str) {
    for conn in room.players.values() {
        if conn.tx.try_send(message.to_string()).is_err() {
            eprintln!(
                "[warning] outbound queue full for player '{}', message dropped",
                conn.seat
            );
        }
    }
}

/// Send a JSON message to a specific player.
pub fn send_to_player(room: &Room, seat: &str, message: &str) {
    if let Some(conn) = room.players.get(seat) {
        if conn.tx.try_send(message.to_string()).is_err() {
            eprintln!(
                "[warning] outbound queue full for player '{seat}', message dropped"
            );
        }
    }
}

