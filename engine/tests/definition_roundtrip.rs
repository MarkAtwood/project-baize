use baize_engine::GameDefinition;

/// Collect all game JSON files from the games/ directory.
fn game_files() -> Vec<(String, String)> {
    let games_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../games");
    let mut files: Vec<(String, String)> = std::fs::read_dir(games_dir)
        .unwrap_or_else(|e| panic!("failed to read games dir {games_dir}: {e}"))
        .filter_map(|entry| {
            let entry = entry.ok()?;
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("json") {
                let name = path
                    .file_stem()
                    .unwrap()
                    .to_string_lossy()
                    .into_owned();
                let content = std::fs::read_to_string(&path)
                    .unwrap_or_else(|e| panic!("failed to read {}: {e}", path.display()));
                Some((name, content))
            } else {
                None
            }
        })
        .collect();
    files.sort_by(|a, b| a.0.cmp(&b.0));
    files
}

/// Serialize -> deserialize -> serialize must produce identical output.
///
/// The first deserialization may drop unknown fields (e.g. "notation" which
/// the Rust model does not yet represent). The invariant tested here is that
/// the second round-trip is bitwise identical to the first — i.e. the
/// serialize/deserialize cycle is idempotent once the data has passed through
/// the typed model.
#[test]
fn definition_roundtrip_all_games() {
    let files = game_files();
    assert!(!files.is_empty(), "no game JSON files found");

    for (name, raw_json) in &files {
        // First pass: raw JSON -> GameDefinition -> JSON string
        let def1: GameDefinition = GameDefinition::from_json(raw_json)
            .unwrap_or_else(|e| panic!("[{name}] first parse failed: {e}"));
        let json1 = serde_json::to_string(&def1)
            .unwrap_or_else(|e| panic!("[{name}] first serialize failed: {e}"));

        // Second pass: JSON string -> GameDefinition -> JSON string
        let def2: GameDefinition = GameDefinition::from_json(&json1)
            .unwrap_or_else(|e| panic!("[{name}] second parse failed: {e}"));
        let json2 = serde_json::to_string(&def2)
            .unwrap_or_else(|e| panic!("[{name}] second serialize failed: {e}"));

        // Byte-identical comparison
        assert_eq!(
            json1, json2,
            "[{name}] serialize-deserialize-serialize not bitwise identical"
        );
    }
}

/// Same test but via serde_json::Value to catch key-ordering issues.
///
/// IndexMap preserves insertion order, so serialization order should be
/// deterministic. This test round-trips through Value to verify that the
/// structural representation is also stable.
#[test]
fn definition_roundtrip_via_value_all_games() {
    let files = game_files();
    assert!(!files.is_empty(), "no game JSON files found");

    for (name, raw_json) in &files {
        // Parse raw JSON to Value first
        let raw_value: serde_json::Value = serde_json::from_str(raw_json)
            .unwrap_or_else(|e| panic!("[{name}] raw JSON parse to Value failed: {e}"));

        // Value -> GameDefinition -> Value
        let def1: GameDefinition = serde_json::from_value(raw_value.clone())
            .unwrap_or_else(|e| panic!("[{name}] first Value->Definition parse failed: {e}"));
        let val1: serde_json::Value = serde_json::to_value(&def1)
            .unwrap_or_else(|e| panic!("[{name}] first Definition->Value serialize failed: {e}"));

        // Value -> GameDefinition -> Value (second pass)
        let def2: GameDefinition = serde_json::from_value(val1.clone())
            .unwrap_or_else(|e| panic!("[{name}] second Value->Definition parse failed: {e}"));
        let val2: serde_json::Value = serde_json::to_value(&def2)
            .unwrap_or_else(|e| {
                panic!("[{name}] second Definition->Value serialize failed: {e}")
            });

        // Structural equality (Value implements PartialEq)
        assert_eq!(
            val1, val2,
            "[{name}] Value round-trip not structurally identical"
        );

        // Also check that the serialized JSON strings match (catches key ordering)
        let str1 = serde_json::to_string(&val1)
            .unwrap_or_else(|e| panic!("[{name}] Value->String 1 failed: {e}"));
        let str2 = serde_json::to_string(&val2)
            .unwrap_or_else(|e| panic!("[{name}] Value->String 2 failed: {e}"));
        assert_eq!(
            str1, str2,
            "[{name}] Value->String round-trip not bitwise identical"
        );
    }
}
