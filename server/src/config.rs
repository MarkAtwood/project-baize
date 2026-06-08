/// Server-wide security configuration with sensible defaults.

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
