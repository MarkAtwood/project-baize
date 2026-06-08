/**
 * <baize-game> — Root custom element.
 *
 * Attributes:
 *   src     — URL to a game definition JSON file
 *   server  — WebSocket URL for the game server
 *   player  — Seat identifier for the local player
 *
 * Responsibilities:
 *   - Fetches and parses the game definition
 *   - Initializes the WASM engine
 *   - Opens the WebSocket connection
 *   - Distributes state to child elements (<baize-board>, <baize-hand>, <baize-score>)
 */

import { BaizeConnection } from "../connection.js";
import { BaizeEngine } from "../engine.js";
import type { Action, GameDefinition, GameState, ServerMessage } from "../types.js";

const WASM_URL_ATTR = "wasm";
const DEFAULT_WASM_PATH = "baize_engine_bg.wasm";

/** Protocols that must never be loaded as resource URLs. */
const BLOCKED_PROTOCOLS: ReadonlySet<string> = new Set([
  "javascript:",
  "data:",
  "vbscript:",
]);

export class BaizeGameElement extends HTMLElement {
  static readonly observedAttributes = ["src", "server", "player"] as const;

  private engine: BaizeEngine | null = null;
  private connection: BaizeConnection | null = null;
  private definition: GameDefinition | null = null;
  private state: GameState | null = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.render();
  }

  connectedCallback(): void {
    void this.initialize();
  }

  disconnectedCallback(): void {
    this.connection?.disconnect();
    this.engine?.dispose();
  }

  attributeChangedCallback(
    name: string,
    _oldValue: string | null,
    _newValue: string | null,
  ): void {
    if (name === "src" || name === "server" || name === "player") {
      void this.initialize();
    }
  }

  /** Current game definition (read-only for child elements). */
  getDefinition(): GameDefinition | null {
    return this.definition;
  }

  /** Current game state (read-only for child elements). */
  getState(): GameState | null {
    return this.state;
  }

  /** Current engine instance (for legal move computation). */
  getEngine(): BaizeEngine | null {
    return this.engine;
  }

  /** Submit a move through the connection. */
  submitMove(action: Action): void {
    if (this.connection === null) {
      throw new Error("<baize-game>: no active connection");
    }
    this.connection.submitMove(action);
  }

  private async initialize(): Promise<void> {
    const src = this.getAttribute("src");
    const server = this.getAttribute("server");
    const player = this.getAttribute("player") ?? "player1";

    if (src === null) return;

    try {
      if (!BaizeGameElement.isSafeResourceUrl(src)) {
        throw new Error(`Blocked unsafe src URL: ${src}`);
      }
      await this.loadDefinition(src);
      await this.initEngine();
      if (server !== null) {
        this.initConnection(server, player);
      }
      this.updateStatus("ready");
    } catch (err) {
      this.updateStatus("error", err instanceof Error ? err.message : String(err));
    }
  }

  private async loadDefinition(url: string): Promise<void> {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to load game definition: ${response.status} ${response.statusText}`);
    }
    this.definition = (await response.json()) as GameDefinition;
  }

  private async initEngine(): Promise<void> {
    if (this.definition === null) return;

    this.engine?.dispose();
    this.engine = new BaizeEngine();

    const wasmUrl = this.getAttribute(WASM_URL_ATTR) ?? DEFAULT_WASM_PATH;

    if (!BaizeGameElement.isSafeResourceUrl(wasmUrl)) {
      // Unsafe WASM URL — skip loading, same as WASM-unavailable path.
      return;
    }

    try {
      await this.engine.init(wasmUrl);
      this.engine.loadDefinition(this.definition);
      this.state = this.engine.getState();
      this.distributeState();
    } catch {
      // WASM not available — engine stays in unloaded state.
      // The client can still render from server-provided state.
    }
  }

  private initConnection(serverUrl: string, player: string): void {
    this.connection?.disconnect();

    const gameId = this.extractGameId(serverUrl);
    this.connection = new BaizeConnection(serverUrl, gameId, player);

    this.connection.on("move_confirmed", (msg) => this.handleMoveConfirmed(msg));
    this.connection.on("move_rejected", (msg) => this.handleMoveRejected(msg));
    this.connection.on("state_sync", (msg) => this.handleStateSync(msg));
    this.connection.on("reveal", (msg) => this.handleReveal(msg));
    this.connection.on("random_result", (msg) => this.handleRandomResult(msg));

    this.connection.onStatusChange((status) => {
      this.dispatchEvent(
        new CustomEvent("baize-connection", { detail: { status }, bubbles: true }),
      );
    });

    this.connection.connect();
  }

  private handleMoveConfirmed(msg: ServerMessage): void {
    if (msg.full_state !== undefined) {
      this.state = msg.full_state;
    } else if (msg.sequence !== undefined) {
      this.connection?.updateSequence(msg.sequence);
    }
    this.distributeState();
    this.dispatchEvent(
      new CustomEvent("baize-move-confirmed", { detail: msg, bubbles: true }),
    );
  }

  private handleMoveRejected(msg: ServerMessage): void {
    this.dispatchEvent(
      new CustomEvent("baize-move-rejected", {
        detail: { reason: msg.reason },
        bubbles: true,
      }),
    );
  }

  private handleStateSync(msg: ServerMessage): void {
    if (msg.full_state !== undefined) {
      this.state = msg.full_state;
      this.distributeState();
    }
  }

  private handleReveal(msg: ServerMessage): void {
    this.dispatchEvent(
      new CustomEvent("baize-reveal", { detail: msg, bubbles: true }),
    );
  }

  private handleRandomResult(msg: ServerMessage): void {
    this.dispatchEvent(
      new CustomEvent("baize-random", { detail: msg, bubbles: true }),
    );
  }

  /** Push current state to all child baize-* elements. */
  private distributeState(): void {
    this.dispatchEvent(
      new CustomEvent("baize-state-update", {
        detail: { state: this.state, definition: this.definition },
        bubbles: false,
      }),
    );
  }

  /**
   * Check whether a URL is safe to load as a resource (fetch / import).
   * Blocks javascript:, data:, and vbscript: protocols.
   * Relative URLs are always allowed.
   */
  private static isSafeResourceUrl(url: string): boolean {
    // Relative URLs are safe (no protocol to abuse)
    try {
      const parsed = new URL(url, "https://dummy.invalid/");
      // If the URL string itself contains a blocked protocol prefix
      // (not just when resolved against the dummy base), reject it.
      const colonIdx = url.indexOf(":");
      if (colonIdx > 0) {
        const protocol = url.slice(0, colonIdx + 1).toLowerCase();
        if (BLOCKED_PROTOCOLS.has(protocol)) return false;
      }
      if (BLOCKED_PROTOCOLS.has(parsed.protocol)) return false;
    } catch {
      return false;
    }
    return true;
  }

  private extractGameId(url: string): string {
    // Best-effort: take the last path segment as the game ID.
    try {
      const parsed = new URL(url);
      const segments = parsed.pathname.split("/").filter((s) => s.length > 0);
      return segments[segments.length - 1] ?? "unknown";
    } catch {
      return "unknown";
    }
  }

  private updateStatus(status: string, error?: string): void {
    const statusEl = this.shadowRoot?.getElementById("status");
    if (statusEl !== null && statusEl !== undefined) {
      statusEl.textContent = error !== undefined ? `Error: ${error}` : status;
      statusEl.className = error !== undefined ? "error" : status;
    }
  }

  private render(): void {
    if (this.shadowRoot === null) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          position: relative;
          contain: layout;
        }
        #status {
          font-family: system-ui, sans-serif;
          font-size: 0.75rem;
          padding: 0.25rem 0.5rem;
          color: #666;
        }
        #status.error {
          color: #c00;
        }
        #status.ready {
          display: none;
        }
        ::slotted(*) {
          display: block;
        }
      </style>
      <div id="status">Loading...</div>
      <slot></slot>
    `;
  }
}
