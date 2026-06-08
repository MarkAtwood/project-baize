//! Integration tests that validate all game definitions in games/ parse
//! successfully through the Rust engine's GameDefinition::from_json.

use std::fs;
use std::path::PathBuf;

use baize_engine::GameDefinition;

fn games_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("games")
}

#[test]
fn all_game_definitions_parse() {
    let dir = games_dir();
    let mut count = 0;

    for entry in fs::read_dir(&dir).expect("games/ directory should exist") {
        let entry = entry.unwrap();
        let path = entry.path();

        if path.extension().is_some_and(|ext| ext == "json") {
            let name = path.file_name().unwrap().to_string_lossy().to_string();
            let content = fs::read_to_string(&path)
                .unwrap_or_else(|e| panic!("failed to read {name}: {e}"));

            let def = GameDefinition::from_json(&content)
                .unwrap_or_else(|e| panic!("{name} failed to parse: {e}"));

            assert!(
                !def.game.name.is_empty(),
                "{name} has empty game name"
            );
            assert!(
                !def.end_conditions.is_empty(),
                "{name} has no end conditions"
            );

            count += 1;
        }
    }

    assert!(count >= 6, "expected at least 6 game definitions, found {count}");
}
