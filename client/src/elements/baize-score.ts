/**
 * <baize-score> — Displays player scores and game status.
 *
 * Reads score data from the GameState.players map and renders a simple
 * scoreboard in Shadow DOM.
 */

import type { GameDefinition, GameState, PlayerState } from "../types.js";

interface StateUpdateDetail {
  readonly state: GameState | null;
  readonly definition: GameDefinition | null;
}

export class BaizeScoreElement extends HTMLElement {
  private state: GameState | null = null;

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
  }

  private handleStateUpdate = (event: Event): void => {
    const detail = (event as CustomEvent<StateUpdateDetail>).detail;
    this.state = detail.state;
    this.renderScoreboard();
  };

  private renderPlaceholder(): void {
    if (this.shadowRoot === null) return;
    this.shadowRoot.innerHTML = `
      <style>
        ${BaizeScoreElement.styles}
      </style>
      <div class="scoreboard placeholder">
        <span>Scores</span>
      </div>
    `;
  }

  private renderScoreboard(): void {
    if (this.shadowRoot === null) return;
    if (this.state === null) {
      this.renderPlaceholder();
      return;
    }

    const players = Object.entries(this.state.players);
    const rows = players
      .map(([name, ps]) => this.renderPlayerRow(name, ps, this.state!))
      .join("");

    const statusLine = this.renderStatus(this.state);

    this.shadowRoot.innerHTML = `
      <style>
        ${BaizeScoreElement.styles}
      </style>
      <div class="scoreboard">
        <table>
          <thead>
            <tr>
              <th>Player</th>
              <th>Score</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
          </tbody>
        </table>
        ${statusLine}
      </div>
    `;
  }

  private renderPlayerRow(
    name: string,
    playerState: PlayerState,
    gameState: GameState,
  ): string {
    const isActive = gameState.turn === name;
    const score = playerState.score ?? 0;
    const connected = playerState.connected !== false;
    const statusIcon = connected ? "" : " (disconnected)";
    const activeClass = isActive ? ' class="active"' : "";

    return (
      `<tr${activeClass}>` +
      `<td>${this.escapeHtml(name)}${statusIcon}</td>` +
      `<td>${score}</td>` +
      `<td>${isActive ? "Current turn" : ""}</td>` +
      `</tr>`
    );
  }

  private renderStatus(state: GameState): string {
    if (state.status === "finished" && state.result !== undefined) {
      const { outcome, winner, condition } = state.result;
      const safeCondition = condition !== undefined ? this.escapeHtml(condition) : undefined;
      if (outcome === "draw") {
        return `<div class="game-result draw">Draw${safeCondition !== undefined ? ` (${safeCondition})` : ""}</div>`;
      }
      if (outcome === "win" && winner !== undefined) {
        return `<div class="game-result win">${this.escapeHtml(winner)} wins${safeCondition !== undefined ? ` (${safeCondition})` : ""}!</div>`;
      }
      return `<div class="game-result">Game over: ${this.escapeHtml(outcome)}</div>`;
    }
    if (state.status === "setup") {
      return `<div class="game-status">Setting up...</div>`;
    }
    return "";
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  private static readonly styles = `
    :host {
      display: block;
      font-family: system-ui, sans-serif;
    }
    .scoreboard {
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
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
    }
    th {
      text-align: left;
      padding: 0.25rem 0.5rem;
      border-bottom: 2px solid #ddd;
      font-weight: 600;
    }
    td {
      padding: 0.25rem 0.5rem;
      border-bottom: 1px solid #eee;
    }
    tr.active td {
      background: #e8f4fd;
      font-weight: 600;
    }
    .game-result {
      margin-top: 0.5rem;
      padding: 0.5rem;
      text-align: center;
      font-weight: 700;
      border-radius: 4px;
    }
    .game-result.win {
      background: #d4edda;
      color: #155724;
    }
    .game-result.draw {
      background: #fff3cd;
      color: #856404;
    }
    .game-status {
      margin-top: 0.5rem;
      text-align: center;
      color: #666;
      font-size: 0.75rem;
    }
  `;
}
