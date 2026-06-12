//! Event log tamper detection.
//!
//! Reads a JSONL event log (in the schema format defined by
//! `event-log.schema.json`) and verifies the blake3 hash chain.

use std::io::BufRead;

use subtle::ConstantTimeEq;

use crate::error::BaizeError;

/// The genesis hash: 64 hex zero characters.
const GENESIS_HASH: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

/// Canonical field names included in the event hash, per the schema.
const CANONICAL_KEYS: &[&str] = &[
    "event_type",
    "game_id",
    "payload",
    "player",
    "prev_hash",
    "sequence",
    "state_hash",
];

/// Result of verifying an event log's hash chain.
#[derive(Debug, Clone)]
pub struct VerifyResult {
    /// Whether the entire log passed verification.
    pub valid: bool,
    /// Number of events checked before verification stopped or completed.
    pub events_checked: usize,
    /// Human-readable error message if verification failed.
    pub error: Option<String>,
    /// Zero-based index of the first event where verification failed.
    pub divergence_index: Option<usize>,
}

/// Recompute the event_hash from the canonical fields of a schema-format event.
fn compute_event_hash(event: &serde_json::Value) -> Result<String, BaizeError> {
    let obj = event.as_object().ok_or_else(|| {
        BaizeError::Validation("event must be a JSON object".into())
    })?;
    // Build a sorted map of only the canonical keys.
    let mut canonical = serde_json::Map::new();
    for &key in CANONICAL_KEYS {
        if let Some(val) = obj.get(key) {
            canonical.insert(key.to_string(), val.clone());
        }
    }
    // Safe: serializing a serde_json::Value::Object is infallible.
    let payload = serde_json::to_string(&serde_json::Value::Object(canonical)).unwrap();
    let hash = blake3::hash(payload.as_bytes());
    Ok(hash.to_hex().to_string())
}

/// Verify a JSONL event log read from `reader`.
///
/// Checks performed:
/// - Genesis event has `prev_hash` of all zeros
/// - `prev_hash` of event N+1 matches `event_hash` of event N
/// - Sequence numbers are consecutive starting from 0
/// - No duplicate sequence numbers
/// - Each `event_hash` matches recomputation from canonical fields
pub fn verify_event_log(reader: impl BufRead) -> Result<VerifyResult, BaizeError> {
    let mut events: Vec<serde_json::Value> = Vec::new();

    for line_result in reader.lines() {
        let line =
            line_result.map_err(|e| BaizeError::Validation(format!("IO error: {e}")))?;
        let trimmed = line.trim().to_string();
        if trimmed.is_empty() {
            continue;
        }
        let event: serde_json::Value = serde_json::from_str(&trimmed)?;
        events.push(event);
    }

    if events.is_empty() {
        return Ok(VerifyResult {
            valid: true,
            events_checked: 0,
            error: None,
            divergence_index: None,
        });
    }

    let mut seen_sequences = std::collections::HashSet::new();

    for (i, event) in events.iter().enumerate() {
        let seq = event
            .get("sequence")
            .and_then(|v| v.as_u64())
            .ok_or_else(|| BaizeError::Validation("missing or invalid sequence".into()))?
            as usize;

        // Check for duplicate sequence number
        if !seen_sequences.insert(seq) {
            return Ok(VerifyResult {
                valid: false,
                events_checked: i,
                error: Some(format!("duplicate sequence number {seq}")),
                divergence_index: Some(i),
            });
        }

        // Check sequence numbers are consecutive starting from 0
        if seq != i {
            return Ok(VerifyResult {
                valid: false,
                events_checked: i,
                error: Some(format!("expected sequence {i}, got {seq}")),
                divergence_index: Some(i),
            });
        }

        let prev_hash = event
            .get("prev_hash")
            .and_then(|v| v.as_str())
            .unwrap_or("");

        // Check genesis prev_hash (constant-time to prevent timing side-channels)
        if i == 0 {
            if prev_hash.as_bytes().ct_eq(GENESIS_HASH.as_bytes()).unwrap_u8() != 1 {
                return Ok(VerifyResult {
                    valid: false,
                    events_checked: 0,
                    error: Some("genesis event prev_hash is not all zeros".into()),
                    divergence_index: Some(0),
                });
            }
        } else {
            // Check chain linkage
            let expected_prev = events[i - 1]
                .get("event_hash")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if prev_hash.as_bytes().ct_eq(expected_prev.as_bytes()).unwrap_u8() != 1 {
                return Ok(VerifyResult {
                    valid: false,
                    events_checked: i,
                    error: Some(format!(
                        "prev_hash mismatch at sequence {seq}: expected {expected_prev}, got {prev_hash}"
                    )),
                    divergence_index: Some(i),
                });
            }
        }

        // Check event_hash recomputation
        let expected_hash = compute_event_hash(event)?;
        let actual_hash = event
            .get("event_hash")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if actual_hash.as_bytes().ct_eq(expected_hash.as_bytes()).unwrap_u8() != 1 {
            return Ok(VerifyResult {
                valid: false,
                events_checked: i,
                error: Some(format!(
                    "event_hash mismatch at sequence {seq}: expected {expected_hash}, got {actual_hash}"
                )),
                divergence_index: Some(i),
            });
        }
    }

    Ok(VerifyResult {
        valid: true,
        events_checked: events.len(),
        error: None,
        divergence_index: None,
    })
}
