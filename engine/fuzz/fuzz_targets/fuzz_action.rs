#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Feed random bytes to ClientMessage and Action deserialization.
    // Must never panic -- all invalid input should produce Err.
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = serde_json::from_str::<baize_engine::action::ClientMessage>(s);
        let _ = serde_json::from_str::<baize_engine::action::ServerMessage>(s);
        let _ = serde_json::from_str::<baize_engine::action::Action>(s);
    }

    // Try from raw bytes as well.
    let _ = serde_json::from_slice::<baize_engine::action::ClientMessage>(data);
    let _ = serde_json::from_slice::<baize_engine::action::Action>(data);
});
