#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Feed random bytes to GameState::from_json().
    // Must never panic -- all invalid input should produce Err.
    if let Ok(s) = std::str::from_utf8(data) {
        if let Ok(state) = baize_engine::GameState::from_json(s) {
            // If parsing succeeds, compute_hash must also not panic.
            let _ = state.compute_hash();
        }
    }

    // Also try serde_json::from_slice directly.
    let _ = serde_json::from_slice::<baize_engine::state::GameState>(data);
});
