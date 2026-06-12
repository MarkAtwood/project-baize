//! Per-connection rate limiter using a sliding window of message timestamps.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

/// Per-connection rate limiter using a sliding window of message timestamps.
pub struct RateLimiter {
    /// Timestamps of recent messages within the current window.
    timestamps: VecDeque<Instant>,
    /// Maximum allowed messages per second.
    max_per_second: usize,
}

impl RateLimiter {
    /// Create a new rate limiter allowing `max_per_second` messages per 1-second window.
    pub fn new(max_per_second: usize) -> Self {
        Self {
            timestamps: VecDeque::with_capacity(max_per_second + 1),
            max_per_second,
        }
    }

    /// Record a message arrival. Returns `true` if the message is allowed,
    /// `false` if the rate limit is exceeded.
    pub fn check(&mut self) -> bool {
        self.check_at(Instant::now())
    }

    /// Record a message arrival at a specific instant (for testing).
    /// Returns `true` if the message is allowed, `false` if the rate limit is exceeded.
    pub fn check_at(&mut self, now: Instant) -> bool {
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

    /// Return the number of messages recorded in the current window.
    pub fn window_count(&self) -> usize {
        self.timestamps.len()
    }
}
