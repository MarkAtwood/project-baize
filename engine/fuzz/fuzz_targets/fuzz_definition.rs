#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Feed random bytes as UTF-8 to GameDefinition::from_json().
    // Must never panic -- all invalid input should produce Err.
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = baize_engine::GameDefinition::from_json(s);
    }

    // Also try from_value with arbitrary JSON.
    if let Ok(value) = serde_json::from_slice::<serde_json::Value>(data) {
        let _ = baize_engine::definition::GameDefinition::from_value(value);
    }
});
