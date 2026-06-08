/**
 * <baize-clock> — Displays per-player countdown timers.
 *
 * Reads clock data from GameState.players[*].clock and renders a timer
 * display for each player in Shadow DOM. Uses requestAnimationFrame for
 * smooth client-side interpolation between server state updates.
 *
 * Visual warnings:
 *   < 30s remaining — yellow
 *   < 10s remaining — red
 *   <  5s remaining — red + pulse animation
 */

import type { GameDefinition, GameState, PlayerState } from "../types.js";

interface StateUpdateDetail {
  readonly state: GameState | null;
  readonly definition: GameDefinition | null;
}

/** Snapshot of a single player's clock at a known wall-clock instant. */
interface ClockSnapshot {
  remainingMs: number;
  running: boolean;
  incrementMs: number;
}

const WARN_THRESHOLD_MS = 30_000;
const DANGER_THRESHOLD_MS = 10_000;
const CRITICAL_THRESHOLD_MS = 5_000;

export class BaizeClockElement extends HTMLElement {
  private state: GameState | null = null;

  /** Per-player clock snapshots taken at the last server update. */
  private snapshots = new Map<string, ClockSnapshot>();

  /** Wall-clock timestamp (performance.now) of the last server update. */
  private lastUpdateTime = 0;

  /** Active requestAnimationFrame handle, or 0 when idle. */
  private rafHandle = 0;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.renderPlaceholder();
  }

  connectedCallback(): void {
    const parent = this.closest("baize-game");
    parent?.addEventListener("baize-state-update", this.handleStateUpdate);
  }

  disconnectedCallback(): void {
    const parent = this.closest("baize-game");
    parent?.removeEventListener("baize-state-update", this.handleStateUpdate);
    this.stopTicking();
  }

  private handleStateUpdate = (event: Event): void => {
    const detail = (event as CustomEvent<StateUpdateDetail>).detail;
    this.state = detail.state;
    this.syncSnapshots();
    this.renderClocks();
    this.ensureTicking();
  };

  // ---------------------------------------------------------------------------
  // Snapshot management
  // ---------------------------------------------------------------------------

  /** Rebuild snapshots from server-authoritative state. */
  private syncSnapshots(): void {
    this.snapshots.clear();
    this.lastUpdateTime = performance.now();

    if (this.state === null) return;

    for (const [name, ps] of Object.entries(this.state.players)) {
      const clock = ps.clock;
      if (clock === undefined) continue;
      this.snapshots.set(name, {
        remainingMs: clock.remaining_ms ?? 0,
        running: clock.running === true,
        incrementMs: clock.increment_ms ?? 0,
      });
    }
  }

  /** Compute the interpolated remaining time for a player right now. */
  private interpolatedMs(name: string, now: number): number {
    const snap = this.snapshots.get(name);
    if (snap === undefined) return 0;

    if (!snap.running || this.state?.status !== "in_progress") {
      return snap.remainingMs;
    }

    const elapsed = now - this.lastUpdateTime;
    return Math.max(0, snap.remainingMs - elapsed);
  }

  // ---------------------------------------------------------------------------
  // Animation loop
  // ---------------------------------------------------------------------------

  private ensureTicking(): void {
    const anyRunning = this.isAnyClockRunning();
    if (anyRunning && this.rafHandle === 0) {
      this.rafHandle = requestAnimationFrame(this.tick);
    } else if (!anyRunning && this.rafHandle !== 0) {
      this.stopTicking();
    }
  }

  private stopTicking(): void {
    if (this.rafHandle !== 0) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = 0;
    }
  }

  private isAnyClockRunning(): boolean {
    if (this.state?.status !== "in_progress") return false;
    for (const snap of this.snapshots.values()) {
      if (snap.running) return true;
    }
    return false;
  }

  private tick = (): void => {
    this.rafHandle = 0;
    this.renderClocks();
    if (this.isAnyClockRunning()) {
      this.rafHandle = requestAnimationFrame(this.tick);
    }
  };

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  private renderPlaceholder(): void {
    if (this.shadowRoot === null) return;
    this.shadowRoot.innerHTML = `
      <style>
        ${BaizeClockElement.styles}
      </style>
      <div class="clock-container placeholder">
        <span>Clock</span>
      </div>
    `;
  }

  private renderClocks(): void {
    if (this.shadowRoot === null) return;
    if (this.state === null || this.snapshots.size === 0) {
      this.renderPlaceholder();
      return;
    }

    const now = performance.now();
    const players = Object.entries(this.state.players);

    const rows = players
      .map(([name, ps]) => this.renderPlayerClock(name, ps, now))
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        ${BaizeClockElement.styles}
      </style>
      <div class="clock-container">
        ${rows}
      </div>
    `;
  }

  private renderPlayerClock(
    name: string,
    playerState: PlayerState,
    now: number,
  ): string {
    const clock = playerState.clock;
    if (clock === undefined) return "";

    const remainingMs = this.interpolatedMs(name, now);
    const isActive = this.state?.turn === name;
    const running = clock.running === true && this.state?.status === "in_progress";

    const timeStr = BaizeClockElement.formatTime(remainingMs);
    const urgencyClass = BaizeClockElement.urgencyClass(remainingMs);
    const activeClass = isActive ? " active" : "";
    const runningClass = running ? " running" : " paused";

    const incrementInfo =
      clock.increment_ms !== undefined && clock.increment_ms > 0
        ? `<span class="increment">+${BaizeClockElement.formatSeconds(clock.increment_ms)}</span>`
        : "";

    return `
      <div class="player-clock${activeClass}${runningClass}${urgencyClass}">
        <span class="player-name">${this.escapeHtml(name)}</span>
        <span class="time">${timeStr}</span>
        ${incrementInfo}
      </div>
    `;
  }

  // ---------------------------------------------------------------------------
  // Formatting helpers
  // ---------------------------------------------------------------------------

  /** Format milliseconds as M:SS or H:MM:SS. */
  private static formatTime(ms: number): string {
    const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const mm = String(minutes).padStart(hours > 0 ? 2 : 1, "0");
    const ss = String(seconds).padStart(2, "0");

    if (hours > 0) {
      return `${hours}:${mm}:${ss}`;
    }
    return `${mm}:${ss}`;
  }

  /** Format increment milliseconds as a human-readable seconds string. */
  private static formatSeconds(ms: number): string {
    const s = ms / 1000;
    if (Number.isInteger(s)) return `${s}s`;
    return `${s.toFixed(1)}s`;
  }

  /** Return a CSS class suffix for the urgency level. */
  private static urgencyClass(remainingMs: number): string {
    if (remainingMs <= CRITICAL_THRESHOLD_MS) return " critical";
    if (remainingMs <= DANGER_THRESHOLD_MS) return " danger";
    if (remainingMs <= WARN_THRESHOLD_MS) return " warn";
    return "";
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ---------------------------------------------------------------------------
  // Styles
  // ---------------------------------------------------------------------------

  private static readonly styles = `
    :host {
      display: block;
      font-family: system-ui, sans-serif;
    }
    .clock-container {
      display: flex;
      gap: 0.5rem;
      padding: 0.5rem;
      border: 1px solid #e0e0e0;
      border-radius: 4px;
      background: #fafafa;
    }
    .placeholder {
      color: #999;
      font-size: 0.875rem;
      text-align: center;
      padding: 1rem;
      justify-content: center;
    }
    .player-clock {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.375rem 0.75rem;
      border-radius: 4px;
      background: #f0f0f0;
      flex: 1;
      min-width: 0;
    }
    .player-clock.active {
      background: #e8f4fd;
      border: 2px solid #2196f3;
      padding: calc(0.375rem - 2px) calc(0.75rem - 2px);
    }
    .player-clock.paused .time {
      opacity: 0.6;
    }
    .player-name {
      font-size: 0.75rem;
      font-weight: 600;
      color: #555;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
    .time {
      font-size: 1.25rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.025em;
      margin-left: auto;
      white-space: nowrap;
    }
    .increment {
      font-size: 0.625rem;
      color: #888;
      white-space: nowrap;
    }

    /* Warning: < 30s */
    .player-clock.warn .time {
      color: #b8860b;
    }

    /* Danger: < 10s */
    .player-clock.danger .time {
      color: #c00;
    }

    /* Critical: < 5s — red + pulse */
    .player-clock.critical .time {
      color: #c00;
      animation: pulse 0.5s ease-in-out infinite alternate;
    }
    @keyframes pulse {
      from { opacity: 1; }
      to { opacity: 0.4; }
    }
  `;
}
