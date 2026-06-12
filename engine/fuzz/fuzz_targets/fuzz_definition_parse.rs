#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Feed random bytes as UTF-8 to GameDefinition JSON parsing.
    // Key invariant: parsing arbitrary input must NEVER panic — always Ok or Err.
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = serde_json::from_str::<baize_engine::GameDefinition>(s);
    }
});
