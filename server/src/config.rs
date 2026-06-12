//! Server-wide security configuration with sensible defaults.

/// Maximum WebSocket message size in bytes (64 KB).
pub const MAX_MESSAGE_SIZE: usize = 64 * 1024;

/// Maximum messages per second per connection (sliding window).
pub const MAX_MESSAGES_PER_SECOND: usize = 30;

/// Idle connection timeout (5 minutes).
pub const IDLE_TIMEOUT_SECS: u64 = 300;

/// Maximum rooms per server.
pub const MAX_ROOMS: usize = 100;

/// Maximum connections per IP address.
pub const MAX_CONNECTIONS_PER_IP: usize = 10;

/// Maximum room ID length.
pub const MAX_ROOM_ID_LENGTH: usize = 64;

/// Maximum dice per single roll request.
pub const MAX_DICE_COUNT: u32 = 100;

/// Maximum dice faces (prevents absurdly large ranges).
pub const MAX_DICE_FACES: u32 = 1000;

/// Maximum cards per single draw request.
pub const MAX_DRAW_COUNT: u32 = 1000;

/// Maximum zone name length for random requests.
pub const MAX_ZONE_NAME_LENGTH: usize = 128;

/// Maximum outbound message queue depth per player connection.
/// If a player's queue is full, the connection is dropped.
pub const MAX_OUTBOUND_QUEUE: usize = 256;

/// Maximum moves per game before auto-finish (DoS prevention).
pub const MAX_MOVES_PER_GAME: u64 = 10_000;

/// Maximum length for action string fields (component_id, zone, etc.).
pub const MAX_ACTION_FIELD_LENGTH: usize = 256;

/// Maximum total WebSocket connections across all IPs.
pub const MAX_TOTAL_CONNECTIONS: usize = 500;

/// Maximum events per game before rejecting further moves (DoS prevention).
pub const MAX_EVENTS_PER_GAME: u64 = 100_000;

/// Maximum serialized state size in bytes (10 MB).
/// Engine checks this periodically; server reserves the constant for future use.
#[allow(dead_code)]
pub const MAX_STATE_SIZE: usize = 10 * 1024 * 1024;
