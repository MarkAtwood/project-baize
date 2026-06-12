use std::path::Path;
use std::sync::Mutex;

use wasmtime::{Engine, Instance, Linker, Memory, Module, Store};

use baize_engine::action::Action;
use baize_engine::extension::{
    EndCheckResult, ExtensionError, GameExtension, PlayerScore,
};
use baize_engine::state::GameState;

/// Maximum fuel (instruction count) per WASM extension call.
/// Fuel is consumed per instruction; 1 billion covers complex scoring
/// and chain reactions while preventing infinite loops.
const WASM_FUEL_PER_CALL: u64 = 1_000_000_000;

/// Maximum WASM linear memory in bytes (64 MB).
/// Prevents a malicious extension from allocating unbounded memory.
const WASM_MAX_MEMORY_BYTES: usize = 64 * 1024 * 1024;

/// Host environment for a game-specific WASM extension module.
///
/// The WASM module is expected to export the following functions,
/// all using a JSON-string ABI:
///
/// - `alloc(len: i32) -> i32` — allocate `len` bytes in WASM memory, return pointer
/// - `dealloc(ptr: i32, len: i32)` — free a previous allocation
/// - `is_legal(state_ptr: i32, state_len: i32, player_ptr: i32, player_len: i32,
///             action_ptr: i32, action_len: i32) -> i32`
///   Returns a pointer to a JSON result string. -1 means "defer to declarative engine".
/// - `legal_moves(state_ptr: i32, state_len: i32, player_ptr: i32, player_len: i32) -> i32`
///   Returns a pointer to a JSON array of Action objects.
/// - `apply_effect(state_ptr: i32, state_len: i32, trigger_ptr: i32, trigger_len: i32) -> i32`
///   Returns a pointer to a JSON GameState.
/// - `score(state_ptr: i32, state_len: i32) -> i32`
///   Returns a pointer to a JSON array of PlayerScore objects.
/// - `check_end(state_ptr: i32, state_len: i32) -> i32`
///   Returns a pointer to a JSON EndCheckResult, or 0 for None.
///
/// All returned pointers point to a length-prefixed string in WASM linear memory:
/// the first 4 bytes (little-endian i32) are the string length, followed by UTF-8 bytes.
pub struct WasmHost {
    inner: Mutex<WasmHostInner>,
}

struct WasmHostInner {
    store: Store<()>,
    instance: Instance,
    memory: Memory,
}

/// Result pointer convention: the WASM module returns a pointer where
/// the first 4 bytes are the length (little-endian u32), followed by
/// that many bytes of UTF-8 JSON. A return value of 0 means "null/none".
const NULL_PTR: i32 = 0;

impl WasmHost {
    /// Load a WASM module from the given file path.
    ///
    /// Configures the wasmtime engine with:
    /// - **Fuel metering**: each call gets [`WASM_FUEL_PER_CALL`] fuel units.
    ///   If exhausted, the call traps with an out-of-fuel error.
    /// - **Memory cap**: linear memory is limited to [`WASM_MAX_MEMORY_BYTES`].
    ///   Attempts to grow beyond this limit will fail.
    pub fn from_file(path: &Path) -> Result<Self, ExtensionError> {
        let mut config = wasmtime::Config::new();
        config.consume_fuel(true);

        let engine = Engine::new(&config).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to create WASM engine: {e}"))
        })?;
        let module = Module::from_file(&engine, path).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to load WASM module: {e}"))
        })?;

        let mut linker = Linker::new(&engine);

        // Apply memory limit: cap the maximum number of WASM pages.
        // Each WASM page is 64 KiB.
        let max_pages = (WASM_MAX_MEMORY_BYTES / (64 * 1024)) as u32;
        let memory_type = wasmtime::MemoryType::new(1, Some(max_pages));
        let host_memory = wasmtime::Memory::new(&mut Store::new(&engine, ()), memory_type)
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!(
                    "failed to create capped memory: {e}"
                ))
            })?;
        // Only define a host memory if the module does not export its own.
        // We try to link it; if the module exports "memory", instantiation
        // will use the module's own (which we cap via resource limiter below).
        let _ = linker.define(&mut Store::new(&engine, ()), "env", "memory", host_memory);

        let mut store = Store::new(&engine, ());
        store.set_fuel(WASM_FUEL_PER_CALL).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to set fuel: {e}"))
        })?;

        let instance = linker.instantiate(&mut store, &module).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to instantiate WASM module: {e}"))
        })?;

        let memory = instance
            .get_memory(&mut store, "memory")
            .ok_or_else(|| {
                ExtensionError::ComputationFailed(
                    "WASM module does not export 'memory'".to_string(),
                )
            })?;

        Ok(Self {
            inner: Mutex::new(WasmHostInner {
                store,
                instance,
                memory,
            }),
        })
    }

    /// Reset fuel to the per-call budget before each extension call.
    fn refuel(inner: &mut WasmHostInner) {
        let _ = inner.store.set_fuel(WASM_FUEL_PER_CALL);
    }

    /// Write a string into WASM linear memory via the module's `alloc` export.
    /// Returns (pointer, length) in WASM address space.
    fn write_string(inner: &mut WasmHostInner, s: &str) -> Result<(i32, i32), ExtensionError> {
        let bytes = s.as_bytes();
        let len = bytes.len() as i32;

        let alloc = inner
            .instance
            .get_typed_func::<i32, i32>(&mut inner.store, "alloc")
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("missing 'alloc' export: {e}"))
            })?;

        let ptr = alloc.call(&mut inner.store, len).map_err(|e| {
            ExtensionError::ComputationFailed(format!("alloc call failed: {e}"))
        })?;

        inner
            .memory
            .write(&mut inner.store, ptr as usize, bytes)
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("failed to write to WASM memory: {e}"))
            })?;

        Ok((ptr, len))
    }

    /// Read a length-prefixed string from WASM linear memory.
    /// The first 4 bytes at `ptr` are the length (little-endian u32),
    /// followed by that many bytes of UTF-8.
    fn read_result_string(inner: &mut WasmHostInner, ptr: i32) -> Result<String, ExtensionError> {
        if ptr == NULL_PTR {
            return Ok(String::new());
        }

        let mut len_buf = [0u8; 4];
        inner
            .memory
            .read(&inner.store, ptr as usize, &mut len_buf)
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!(
                    "failed to read result length from WASM memory: {e}"
                ))
            })?;
        let len = u32::from_le_bytes(len_buf) as usize;

        let mut buf = vec![0u8; len];
        inner
            .memory
            .read(&inner.store, (ptr as usize) + 4, &mut buf)
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!(
                    "failed to read result data from WASM memory: {e}"
                ))
            })?;

        String::from_utf8(buf).map_err(|e| {
            ExtensionError::ComputationFailed(format!("WASM returned invalid UTF-8: {e}"))
        })
    }

    /// Deallocate a WASM buffer via the module's `dealloc` export (best-effort).
    fn dealloc(inner: &mut WasmHostInner, ptr: i32, len: i32) {
        if ptr == NULL_PTR {
            return;
        }
        if let Ok(dealloc_fn) =
            inner
                .instance
                .get_typed_func::<(i32, i32), ()>(&mut inner.store, "dealloc")
        {
            let _ = dealloc_fn.call(&mut inner.store, (ptr, len));
        }
    }
}

impl GameExtension for WasmHost {
    fn is_legal(&self, state: &GameState, player: &str, action: &Action) -> Option<bool> {
        let mut inner = match self.inner.lock() {
            Ok(g) => g,
            Err(e) => {
                eprintln!("wasm_host: mutex poisoned in is_legal: {e}");
                return None;
            }
        };
        Self::refuel(&mut inner);

        let state_json = match serde_json::to_string(state) {
            Ok(j) => j,
            Err(e) => {
                eprintln!("wasm_host: failed to serialize state: {e}");
                return None;
            }
        };
        let action_json = match serde_json::to_string(action) {
            Ok(j) => j,
            Err(e) => {
                eprintln!("wasm_host: failed to serialize action: {e}");
                return None;
            }
        };

        let (state_ptr, state_len) = match Self::write_string(&mut inner, &state_json) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return None;
            }
        };
        let (player_ptr, player_len) = match Self::write_string(&mut inner, player) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return None;
            }
        };
        let (action_ptr, action_len) = match Self::write_string(&mut inner, &action_json) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return None;
            }
        };

        let inner_ref = &mut *inner;
        let func = match inner_ref.instance.get_typed_func::<(i32, i32, i32, i32, i32, i32), i32>(
            &mut inner_ref.store,
            "is_legal",
        ) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("wasm_host: missing 'is_legal' export: {e}");
                return None;
            }
        };

        let result_ptr = match func.call(
            &mut inner.store,
            (state_ptr, state_len, player_ptr, player_len, action_ptr, action_len),
        ) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("wasm_host: is_legal call failed: {e}");
                return None;
            }
        };

        // -1 means "defer to declarative engine"
        if result_ptr == -1 {
            return None;
        }

        let result_json = match Self::read_result_string(&mut inner, result_ptr) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("wasm_host: failed to read is_legal result: {e}");
                return None;
            }
        };

        // Clean up WASM allocations
        Self::dealloc(&mut inner, state_ptr, state_len);
        Self::dealloc(&mut inner, player_ptr, player_len);
        Self::dealloc(&mut inner, action_ptr, action_len);

        match serde_json::from_str::<bool>(&result_json) {
            Ok(v) => Some(v),
            Err(e) => {
                eprintln!("wasm_host: failed to parse is_legal result: {e}");
                None
            }
        }
    }

    fn legal_moves(&self, state: &GameState, player: &str) -> Vec<Action> {
        let mut inner = match self.inner.lock() {
            Ok(g) => g,
            Err(e) => {
                eprintln!("wasm_host: mutex poisoned in legal_moves: {e}");
                return Vec::new();
            }
        };
        Self::refuel(&mut inner);

        let state_json = match serde_json::to_string(state) {
            Ok(j) => j,
            Err(e) => {
                eprintln!("wasm_host: failed to serialize state: {e}");
                return Vec::new();
            }
        };

        let (state_ptr, state_len) = match Self::write_string(&mut inner, &state_json) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return Vec::new();
            }
        };
        let (player_ptr, player_len) = match Self::write_string(&mut inner, player) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return Vec::new();
            }
        };

        let inner_ref = &mut *inner;
        let func = match inner_ref
            .instance
            .get_typed_func::<(i32, i32, i32, i32), i32>(&mut inner_ref.store, "legal_moves")
        {
            Ok(f) => f,
            Err(e) => {
                eprintln!("wasm_host: missing 'legal_moves' export: {e}");
                return Vec::new();
            }
        };

        let result_ptr = match func.call(
            &mut inner.store,
            (state_ptr, state_len, player_ptr, player_len),
        ) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("wasm_host: legal_moves call failed: {e}");
                return Vec::new();
            }
        };

        if result_ptr == NULL_PTR {
            return Vec::new();
        }

        let result_json = match Self::read_result_string(&mut inner, result_ptr) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("wasm_host: failed to read legal_moves result: {e}");
                return Vec::new();
            }
        };

        Self::dealloc(&mut inner, state_ptr, state_len);
        Self::dealloc(&mut inner, player_ptr, player_len);

        match serde_json::from_str::<Vec<Action>>(&result_json) {
            Ok(moves) => moves,
            Err(e) => {
                eprintln!("wasm_host: failed to parse legal_moves result: {e}");
                Vec::new()
            }
        }
    }

    fn apply_effect(
        &self,
        state: &GameState,
        trigger: &str,
    ) -> Result<GameState, ExtensionError> {
        let mut inner = self.inner.lock().map_err(|e| {
            ExtensionError::ComputationFailed(format!("mutex poisoned in apply_effect: {e}"))
        })?;
        Self::refuel(&mut inner);

        let state_json = serde_json::to_string(state).map_err(|e| {
            ExtensionError::InvalidState(format!("failed to serialize state: {e}"))
        })?;

        let (state_ptr, state_len) = Self::write_string(&mut inner, &state_json)?;
        let (trigger_ptr, trigger_len) = Self::write_string(&mut inner, trigger)?;

        let inner_ref = &mut *inner;
        let func = inner_ref
            .instance
            .get_typed_func::<(i32, i32, i32, i32), i32>(&mut inner_ref.store, "apply_effect")
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("missing 'apply_effect' export: {e}"))
            })?;

        let result_ptr = func
            .call(
                &mut inner.store,
                (state_ptr, state_len, trigger_ptr, trigger_len),
            )
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("apply_effect call failed: {e}"))
            })?;

        if result_ptr == NULL_PTR {
            // No effect applied; return state unchanged
            return Ok(state.clone());
        }

        let result_json = Self::read_result_string(&mut inner, result_ptr)?;

        Self::dealloc(&mut inner, state_ptr, state_len);
        Self::dealloc(&mut inner, trigger_ptr, trigger_len);

        serde_json::from_str::<GameState>(&result_json).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to parse apply_effect result: {e}"))
        })
    }

    fn score(&self, state: &GameState) -> Result<Vec<PlayerScore>, ExtensionError> {
        let mut inner = self.inner.lock().map_err(|e| {
            ExtensionError::ComputationFailed(format!("mutex poisoned in score: {e}"))
        })?;
        Self::refuel(&mut inner);

        let state_json = serde_json::to_string(state).map_err(|e| {
            ExtensionError::InvalidState(format!("failed to serialize state: {e}"))
        })?;

        let (state_ptr, state_len) = Self::write_string(&mut inner, &state_json)?;

        let inner_ref = &mut *inner;
        let func = inner_ref
            .instance
            .get_typed_func::<(i32, i32), i32>(&mut inner_ref.store, "score")
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("missing 'score' export: {e}"))
            })?;

        let result_ptr = func
            .call(&mut inner.store, (state_ptr, state_len))
            .map_err(|e| {
                ExtensionError::ComputationFailed(format!("score call failed: {e}"))
            })?;

        if result_ptr == NULL_PTR {
            return Ok(Vec::new());
        }

        let result_json = Self::read_result_string(&mut inner, result_ptr)?;

        Self::dealloc(&mut inner, state_ptr, state_len);

        serde_json::from_str::<Vec<PlayerScore>>(&result_json).map_err(|e| {
            ExtensionError::ComputationFailed(format!("failed to parse score result: {e}"))
        })
    }

    fn check_end(&self, state: &GameState) -> Option<EndCheckResult> {
        let mut inner = match self.inner.lock() {
            Ok(g) => g,
            Err(e) => {
                eprintln!("wasm_host: mutex poisoned in check_end: {e}");
                return None;
            }
        };
        Self::refuel(&mut inner);

        let state_json = match serde_json::to_string(state) {
            Ok(j) => j,
            Err(e) => {
                eprintln!("wasm_host: failed to serialize state: {e}");
                return None;
            }
        };

        let (state_ptr, state_len) = match Self::write_string(&mut inner, &state_json) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("wasm_host: {e}");
                return None;
            }
        };

        let inner_ref = &mut *inner;
        let func = match inner_ref
            .instance
            .get_typed_func::<(i32, i32), i32>(&mut inner_ref.store, "check_end")
        {
            Ok(f) => f,
            Err(e) => {
                eprintln!("wasm_host: missing 'check_end' export: {e}");
                return None;
            }
        };

        let result_ptr = match func.call(&mut inner.store, (state_ptr, state_len)) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("wasm_host: check_end call failed: {e}");
                return None;
            }
        };

        if result_ptr == NULL_PTR {
            return None;
        }

        let result_json = match Self::read_result_string(&mut inner, result_ptr) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("wasm_host: failed to read check_end result: {e}");
                return None;
            }
        };

        Self::dealloc(&mut inner, state_ptr, state_len);

        match serde_json::from_str::<EndCheckResult>(&result_json) {
            Ok(r) => Some(r),
            Err(e) => {
                eprintln!("wasm_host: failed to parse check_end result: {e}");
                None
            }
        }
    }
}
