/**
 * BaizeEngine — TypeScript wrapper around the WASM FFI.
 *
 * The Rust engine (engine/src/wasm.rs) exposes a BaizeEngine class via
 * wasm-bindgen with JSON-string-based data crossing.  This module handles
 * loading the .wasm binary and provides typed wrappers over the raw FFI.
 */

import type { Action, GameDefinition, GameState } from "./types.js";

/** Shape of the wasm-bindgen JS glue module. */
interface BaizeWasmModule {
  default: (input?: RequestInfo | URL | BufferSource) => Promise<void>;
  BaizeEngine: BaizeWasmEngineConstructor;
}

interface BaizeWasmEngineConstructor {
  new (): BaizeWasmEngine;
}

/** Raw wasm-bindgen class — all methods take/return JSON strings. */
interface BaizeWasmEngine {
  loadDefinition(json: string): void;
  legalMoves(): string;
  applyAction(actionJson: string): string;
  getState(): string;
  currentPlayer(): string;
  stateHash(): string;
  free(): void;
}

/** Default timeout for WASM calls that might be computationally expensive. */
const WASM_CALL_TIMEOUT_MS = 5_000;

export class BaizeEngine {
  private inner: BaizeWasmEngine | null = null;

  /** Load the WASM binary from a URL and instantiate the module. */
  async init(wasmUrl: string): Promise<void> {
    const module = await import(/* webpackIgnore: true */ wasmUrl) as BaizeWasmModule;
    await module.default();
    this.inner = new module.BaizeEngine();
  }

  /** Load a game definition into the engine. */
  loadDefinition(definition: GameDefinition): void {
    this.callWasm(() => {
      this.requireEngine().loadDefinition(JSON.stringify(definition));
    });
  }

  /** Get all legal moves for the current player. */
  legalMoves(): readonly Action[] {
    const json = this.callWasm(() => this.requireEngine().legalMoves());
    if (typeof json !== "string" || json.length === 0) return [];
    const parsed: unknown = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed as Action[];
  }

  /** Apply a player action. Returns JSONL event strings. */
  applyAction(action: Action): readonly string[] {
    const jsonl = this.callWasm(() =>
      this.requireEngine().applyAction(JSON.stringify(action)),
    );
    if (typeof jsonl !== "string" || jsonl.length === 0) return [];
    return jsonl.split("\n");
  }

  /** Get the current game state. */
  getState(): GameState {
    const json = this.callWasm(() => this.requireEngine().getState());
    if (typeof json !== "string") {
      throw new Error("BaizeEngine: getState() returned non-string");
    }
    const parsed: unknown = JSON.parse(json);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("BaizeEngine: getState() returned invalid state");
    }
    return parsed as GameState;
  }

  /** Get the current player's seat identifier. */
  currentPlayer(): string {
    const result = this.callWasm(() => this.requireEngine().currentPlayer());
    if (typeof result !== "string") {
      throw new Error("BaizeEngine: currentPlayer() returned non-string");
    }
    return result;
  }

  /** Compute a BLAKE3 hash of the current state. */
  stateHash(): string {
    const result = this.callWasm(() => this.requireEngine().stateHash());
    if (typeof result !== "string") {
      throw new Error("BaizeEngine: stateHash() returned non-string");
    }
    return result;
  }

  /** Release WASM resources. */
  dispose(): void {
    try {
      this.inner?.free();
    } catch {
      // Ignore errors during cleanup — engine may already be in a bad state
    }
    this.inner = null;
  }

  get isLoaded(): boolean {
    return this.inner !== null;
  }

  private requireEngine(): BaizeWasmEngine {
    if (this.inner === null) {
      throw new Error("BaizeEngine: WASM not loaded. Call init() first.");
    }
    return this.inner;
  }

  /**
   * Execute a WASM call with trap handling and timeout protection.
   *
   * WASM traps surface as RuntimeError in JS. This wrapper catches them
   * and re-throws with a descriptive message. For calls that might be
   * computationally expensive, a timeout aborts after WASM_CALL_TIMEOUT_MS
   * (note: this uses a synchronous deadline check, since WASM execution
   * is synchronous and cannot be interrupted — the timeout is checked
   * after the call returns, protecting against unexpectedly long but
   * finite computations in future async variants).
   */
  private callWasm<T>(fn: () => T): T {
    const start = performance.now();
    try {
      const result = fn();
      const elapsed = performance.now() - start;
      if (elapsed > WASM_CALL_TIMEOUT_MS) {
        throw new Error(
          `BaizeEngine: WASM call took ${Math.round(elapsed)}ms (limit: ${WASM_CALL_TIMEOUT_MS}ms)`,
        );
      }
      return result;
    } catch (err) {
      if (err instanceof WebAssembly.RuntimeError) {
        // WASM trap — engine is likely in an unrecoverable state
        this.inner = null;
        throw new Error(`BaizeEngine: WASM trap: ${err.message}`);
      }
      throw err;
    }
  }
}
