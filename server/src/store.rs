use std::fmt;
use std::fs;
use std::path::PathBuf;

/// Errors from store operations.
#[derive(Debug)]
pub enum StoreError {
    Io(std::io::Error),
    SerdeJson(serde_json::Error),
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::Io(e) => write!(f, "store I/O error: {e}"),
            StoreError::SerdeJson(e) => write!(f, "store serialization error: {e}"),
        }
    }
}

impl From<std::io::Error> for StoreError {
    fn from(e: std::io::Error) -> Self {
        StoreError::Io(e)
    }
}

impl From<serde_json::Error> for StoreError {
    fn from(e: serde_json::Error) -> Self {
        StoreError::SerdeJson(e)
    }
}

/// Abstract persistence interface. Implementations can back to files, SQLite, etc.
pub trait Store: Send + Sync {
    /// Persist a newly created room (definition + initial state).
    fn save_room(
        &self,
        room_id: &str,
        definition_json: &str,
        state_json: &str,
    ) -> Result<(), StoreError>;

    /// Update the persisted state for an existing room.
    fn update_state(&self, room_id: &str, state_json: &str) -> Result<(), StoreError>;

    /// Append event log lines (JSONL) for a room.
    fn append_events(&self, room_id: &str, events: &[String]) -> Result<(), StoreError>;

    /// Load a room's definition and latest state. Returns None if not found.
    fn load_room(&self, room_id: &str) -> Result<Option<RoomData>, StoreError>;

    /// List all persisted room IDs.
    fn list_rooms(&self) -> Result<Vec<String>, StoreError>;

    /// Delete a room's persisted data.
    #[allow(dead_code)]
    fn delete_room(&self, room_id: &str) -> Result<(), StoreError>;
}

/// Data loaded from storage for a single room.
#[allow(dead_code)]
pub struct RoomData {
    pub definition_json: String,
    pub state_json: String,
}

/// File-system-based store. Each room gets a directory under `base_dir`:
///
/// ```text
/// base_dir/
///   <room_id>/
///     definition.json
///     state.json
///     events.jsonl
/// ```
pub struct FileStore {
    base_dir: PathBuf,
}

impl FileStore {
    pub fn new(base_dir: impl Into<PathBuf>) -> Result<Self, StoreError> {
        let base_dir = base_dir.into();
        fs::create_dir_all(&base_dir)?;
        Ok(Self { base_dir })
    }

    fn room_dir(&self, room_id: &str) -> PathBuf {
        self.base_dir.join(room_id)
    }
}

impl Store for FileStore {
    fn save_room(
        &self,
        room_id: &str,
        definition_json: &str,
        state_json: &str,
    ) -> Result<(), StoreError> {
        let dir = self.room_dir(room_id);
        fs::create_dir_all(&dir)?;
        fs::write(dir.join("definition.json"), definition_json)?;
        fs::write(dir.join("state.json"), state_json)?;
        Ok(())
    }

    fn update_state(&self, room_id: &str, state_json: &str) -> Result<(), StoreError> {
        let dir = self.room_dir(room_id);
        if !dir.exists() {
            return Err(StoreError::Io(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("room {room_id} not found in store"),
            )));
        }
        fs::write(dir.join("state.json"), state_json)?;
        Ok(())
    }

    fn append_events(&self, room_id: &str, events: &[String]) -> Result<(), StoreError> {
        use std::io::Write;
        let dir = self.room_dir(room_id);
        let path = dir.join("events.jsonl");
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)?;
        for event in events {
            writeln!(file, "{event}")?;
        }
        Ok(())
    }

    fn load_room(&self, room_id: &str) -> Result<Option<RoomData>, StoreError> {
        let dir = self.room_dir(room_id);
        let def_path = dir.join("definition.json");
        let state_path = dir.join("state.json");

        if !def_path.exists() {
            return Ok(None);
        }

        let definition_json = fs::read_to_string(def_path)?;
        let state_json = if state_path.exists() {
            fs::read_to_string(state_path)?
        } else {
            String::new()
        };

        Ok(Some(RoomData {
            definition_json,
            state_json,
        }))
    }

    fn list_rooms(&self) -> Result<Vec<String>, StoreError> {
        let mut rooms = Vec::new();
        if !self.base_dir.exists() {
            return Ok(rooms);
        }
        for entry in fs::read_dir(&self.base_dir)? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                if let Some(name) = entry.file_name().to_str() {
                    let def_path = entry.path().join("definition.json");
                    if def_path.exists() {
                        rooms.push(name.to_string());
                    }
                }
            }
        }
        Ok(rooms)
    }

    fn delete_room(&self, room_id: &str) -> Result<(), StoreError> {
        let dir = self.room_dir(room_id);
        if dir.exists() {
            fs::remove_dir_all(dir)?;
        }
        Ok(())
    }
}

/// In-memory store for testing. No disk I/O.
pub struct MemoryStore {
    rooms: std::sync::Mutex<std::collections::HashMap<String, MemoryRoom>>,
}

struct MemoryRoom {
    definition_json: String,
    state_json: String,
    events: Vec<String>,
}

impl MemoryStore {
    pub fn new() -> Self {
        Self {
            rooms: std::sync::Mutex::new(std::collections::HashMap::new()),
        }
    }
}

impl Default for MemoryStore {
    fn default() -> Self {
        Self::new()
    }
}

impl Store for MemoryStore {
    fn save_room(
        &self,
        room_id: &str,
        definition_json: &str,
        state_json: &str,
    ) -> Result<(), StoreError> {
        let mut rooms = self.rooms.lock().unwrap();
        rooms.insert(
            room_id.to_string(),
            MemoryRoom {
                definition_json: definition_json.to_string(),
                state_json: state_json.to_string(),
                events: Vec::new(),
            },
        );
        Ok(())
    }

    fn update_state(&self, room_id: &str, state_json: &str) -> Result<(), StoreError> {
        let mut rooms = self.rooms.lock().unwrap();
        match rooms.get_mut(room_id) {
            Some(room) => {
                room.state_json = state_json.to_string();
                Ok(())
            }
            None => Err(StoreError::Io(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("room {room_id} not found"),
            ))),
        }
    }

    fn append_events(&self, room_id: &str, events: &[String]) -> Result<(), StoreError> {
        let mut rooms = self.rooms.lock().unwrap();
        if let Some(room) = rooms.get_mut(room_id) {
            room.events.extend(events.iter().cloned());
        }
        Ok(())
    }

    fn load_room(&self, room_id: &str) -> Result<Option<RoomData>, StoreError> {
        let rooms = self.rooms.lock().unwrap();
        Ok(rooms.get(room_id).map(|r| RoomData {
            definition_json: r.definition_json.clone(),
            state_json: r.state_json.clone(),
        }))
    }

    fn list_rooms(&self) -> Result<Vec<String>, StoreError> {
        let rooms = self.rooms.lock().unwrap();
        Ok(rooms.keys().cloned().collect())
    }

    fn delete_room(&self, room_id: &str) -> Result<(), StoreError> {
        let mut rooms = self.rooms.lock().unwrap();
        rooms.remove(room_id);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn memory_store_round_trip() {
        let store = MemoryStore::new();
        store
            .save_room("test-1", r#"{"game":{}}"#, r#"{"status":"setup"}"#)
            .unwrap();

        let data = store.load_room("test-1").unwrap().unwrap();
        assert_eq!(data.definition_json, r#"{"game":{}}"#);
        assert_eq!(data.state_json, r#"{"status":"setup"}"#);

        store.update_state("test-1", r#"{"status":"in_progress"}"#).unwrap();
        let data = store.load_room("test-1").unwrap().unwrap();
        assert_eq!(data.state_json, r#"{"status":"in_progress"}"#);
    }

    #[test]
    fn memory_store_list_rooms() {
        let store = MemoryStore::new();
        store.save_room("a", "{}", "{}").unwrap();
        store.save_room("b", "{}", "{}").unwrap();
        let mut rooms = store.list_rooms().unwrap();
        rooms.sort();
        assert_eq!(rooms, vec!["a", "b"]);
    }

    #[test]
    fn memory_store_delete() {
        let store = MemoryStore::new();
        store.save_room("del", "{}", "{}").unwrap();
        assert!(store.load_room("del").unwrap().is_some());
        store.delete_room("del").unwrap();
        assert!(store.load_room("del").unwrap().is_none());
    }

    #[test]
    fn memory_store_append_events() {
        let store = MemoryStore::new();
        store.save_room("ev", "{}", "{}").unwrap();
        store
            .append_events("ev", &["event1".into(), "event2".into()])
            .unwrap();
        let rooms = store.rooms.lock().unwrap();
        assert_eq!(rooms["ev"].events, vec!["event1", "event2"]);
    }

    #[test]
    fn file_store_round_trip() {
        let dir = std::env::temp_dir().join("baize-test-store");
        let _ = fs::remove_dir_all(&dir);

        let store = FileStore::new(&dir).unwrap();
        store
            .save_room("room-1", r#"{"name":"test"}"#, r#"{"seq":0}"#)
            .unwrap();

        let rooms = store.list_rooms().unwrap();
        assert_eq!(rooms, vec!["room-1"]);

        let data = store.load_room("room-1").unwrap().unwrap();
        assert_eq!(data.definition_json, r#"{"name":"test"}"#);

        store.update_state("room-1", r#"{"seq":1}"#).unwrap();
        let data = store.load_room("room-1").unwrap().unwrap();
        assert_eq!(data.state_json, r#"{"seq":1}"#);

        store
            .append_events("room-1", &[r#"{"e":1}"#.into()])
            .unwrap();
        let events_path = dir.join("room-1").join("events.jsonl");
        let events = fs::read_to_string(events_path).unwrap();
        assert_eq!(events.trim(), r#"{"e":1}"#);

        store.delete_room("room-1").unwrap();
        assert!(store.load_room("room-1").unwrap().is_none());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn file_store_missing_room() {
        let dir = std::env::temp_dir().join("baize-test-store-miss");
        let _ = fs::remove_dir_all(&dir);

        let store = FileStore::new(&dir).unwrap();
        assert!(store.load_room("nonexistent").unwrap().is_none());

        let _ = fs::remove_dir_all(&dir);
    }
}
