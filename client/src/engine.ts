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
    this.requireEngine().loadDefinition(JSON.stringify(definition));
  }

  /** Get all legal moves for the current player. */
  legalMoves(): readonly Action[] {
    const json = this.requireEngine().legalMoves();
    return JSON.parse(json) as Action[];
  }

  /** Apply a player action. Returns JSONL event strings. */
  applyAction(action: Action): readonly string[] {
    const jsonl = this.requireEngine().applyAction(JSON.stringify(action));
    if (jsonl.length === 0) return [];
    return jsonl.split("\n");
  }

  /** Get the current game state. */
  getState(): GameState {
    const json = this.requireEngine().getState();
    return JSON.parse(json) as GameState;
  }

  /** Get the current player's seat identifier. */
  currentPlayer(): string {
    return this.requireEngine().currentPlayer();
  }

  /** Compute a BLAKE3 hash of the current state. */
  stateHash(): string {
    return this.requireEngine().stateHash();
  }

  /** Release WASM resources. */
  dispose(): void {
    this.inner?.free();
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
}
