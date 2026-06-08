//! Integration tests for event log tamper detection.

use std::io::BufReader;
use std::path::PathBuf;

use baize_engine::verify::verify_event_log;

/// Path to the test vectors JSONL file.
fn vectors_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("tests")
        .join("vectors")
        .join("event-log-examples.jsonl")
}

/// Canonical hash fields per the schema (sorted).
const CANONICAL_KEYS: &[&str] = &[
    "event_type",
    "game_id",
    "payload",
    "player",
    "prev_hash",
    "sequence",
    "state_hash",
];

/// Recompute event_hash from canonical fields.
fn recompute_hash(event: &serde_json::Value) -> String {
    let obj = event.as_object().unwrap();
    let mut canonical = serde_json::Map::new();
    for &key in CANONICAL_KEYS {
        if let Some(val) = obj.get(key) {
            canonical.insert(key.to_string(), val.clone());
        }
    }
    let payload =
        serde_json::to_string(&serde_json::Value::Object(canonical)).unwrap();
    blake3::hash(payload.as_bytes()).to_hex().to_string()
}

/// Load all events from the JSONL file.
fn load_events() -> Vec<serde_json::Value> {
    let content = std::fs::read_to_string(vectors_path()).unwrap();
    content
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}

/// Write events to a JSONL string.
fn events_to_jsonl(events: &[serde_json::Value]) -> String {
    events
        .iter()
        .map(|e| serde_json::to_string(e).unwrap())
        .collect::<Vec<_>>()
        .join("\n")
        + "\n"
}

#[test]
fn test_valid_log_passes() {
    let file = std::fs::File::open(vectors_path()).unwrap();
    let reader = BufReader::new(file);
    let result = verify_event_log(reader).unwrap();
    assert!(result.valid);
    assert_eq!(result.events_checked, 10);
    assert!(result.error.is_none());
    assert!(result.divergence_index.is_none());
}

#[test]
fn test_modifying_payload_breaks_chain() {
    let mut events = load_events();
    // Tamper with event 3's payload
    events[3]
        .as_object_mut()
        .unwrap()
        .get_mut("payload")
        .unwrap()
        .as_object_mut()
        .unwrap()
        .insert("next_player".to_string(), serde_json::json!("Z"));

    let jsonl = events_to_jsonl(&events);
    let reader = BufReader::new(jsonl.as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(!result.valid);
    assert_eq!(result.divergence_index, Some(3));
    assert!(result.error.as_ref().unwrap().contains("event_hash mismatch"));
}

#[test]
fn test_inserting_event_breaks_chain() {
    let mut events = load_events();
    // Duplicate event 2 and insert at position 3
    let mut inserted = events[2].clone();
    inserted
        .as_object_mut()
        .unwrap()
        .insert("sequence".to_string(), serde_json::json!(3));
    events.insert(3, inserted);

    let jsonl = events_to_jsonl(&events);
    let reader = BufReader::new(jsonl.as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(!result.valid);
    assert!(result.divergence_index.is_some());
}

#[test]
fn test_deleting_event_breaks_chain() {
    let mut events = load_events();
    // Delete event at index 4
    events.remove(4);

    let jsonl = events_to_jsonl(&events);
    let reader = BufReader::new(jsonl.as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(!result.valid);
    assert!(result.divergence_index.is_some());
}

#[test]
fn test_wrong_genesis_hash_detected() {
    let mut events = load_events();
    // Set a non-zero genesis prev_hash
    events[0]
        .as_object_mut()
        .unwrap()
        .insert(
            "prev_hash".to_string(),
            serde_json::json!("ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
        );
    // Recompute event_hash so only the genesis check catches it
    let new_hash = recompute_hash(&events[0]);
    events[0]
        .as_object_mut()
        .unwrap()
        .insert("event_hash".to_string(), serde_json::json!(new_hash));

    let jsonl = events_to_jsonl(&events);
    let reader = BufReader::new(jsonl.as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(!result.valid);
    assert_eq!(result.divergence_index, Some(0));
    let err = result.error.as_ref().unwrap().to_lowercase();
    assert!(err.contains("genesis") || err.contains("prev_hash"));
}

#[test]
fn test_duplicate_sequence_number_detected() {
    let mut events = load_events();
    // Give event 5 the same sequence as event 4
    let seq4 = events[4]["sequence"].clone();
    events[5]
        .as_object_mut()
        .unwrap()
        .insert("sequence".to_string(), seq4);
    // Recompute event_hash to avoid hash mismatch catching it first
    let new_hash = recompute_hash(&events[5]);
    events[5]
        .as_object_mut()
        .unwrap()
        .insert("event_hash".to_string(), serde_json::json!(new_hash));

    let jsonl = events_to_jsonl(&events);
    let reader = BufReader::new(jsonl.as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(!result.valid);
    assert!(result.divergence_index.is_some());
    let err = result.error.as_ref().unwrap().to_lowercase();
    assert!(err.contains("sequence") || err.contains("duplicate"));
}

#[test]
fn test_empty_log_is_valid() {
    let reader = BufReader::new("".as_bytes());
    let result = verify_event_log(reader).unwrap();
    assert!(result.valid);
    assert_eq!(result.events_checked, 0);
}
