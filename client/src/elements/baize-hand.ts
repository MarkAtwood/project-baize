/**
 * <baize-hand> — Renders a player's hand (cards, tiles, or held components).
 *
 * Attributes:
 *   player — Seat identifier of the player whose hand to display
 *
 * Looks for per-player zones of type "set" with private visibility
 * in the game state's player.zones or the top-level zones marked per_player.
 */

import type {
  ComponentInstance,
  GameDefinition,
  GameState,
  SetState,
  StackState,
  ZoneState,
} from "../types.js";

interface StateUpdateDetail {
  readonly state: GameState | null;
  readonly definition: GameDefinition | null;
}

const CARD_WIDTH = 60;
const CARD_HEIGHT = 84;
const CARD_GAP = 8;

export class BaizeHandElement extends HTMLElement {
  static readonly observedAttributes = ["player"] as const;

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

  attributeChangedCallback(
    _name: string,
    _oldValue: string | null,
    _newValue: string | null,
  ): void {
    this.renderHand();
  }

  private handleStateUpdate = (event: Event): void => {
    const detail = (event as CustomEvent<StateUpdateDetail>).detail;
    this.state = detail.state;
    this.renderHand();
  };

  private get player(): string {
    return this.getAttribute("player") ?? "";
  }

  private renderPlaceholder(): void {
    if (this.shadowRoot === null) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        .placeholder {
          min-height: ${CARD_HEIGHT + 16}px;
          padding: 8px;
          background: #f9f9f9;
          border: 1px dashed #ccc;
          border-radius: 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: system-ui, sans-serif;
          font-size: 0.875rem;
          color: #999;
        }
      </style>
      <div class="placeholder">Hand (${this.player || "no player"})</div>
    `;
  }

  private renderHand(): void {
    if (this.shadowRoot === null) return;
    if (this.state === null || this.player === "") {
      this.renderPlaceholder();
      return;
    }

    const components = this.getHandComponents();
    if (components.length === 0) {
      this.renderPlaceholder();
      return;
    }

    const svgWidth = components.length * (CARD_WIDTH + CARD_GAP) - CARD_GAP + 16;
    const svgHeight = CARD_HEIGHT + 16;

    const cards = components.map((component, i) => {
      const x = 8 + i * (CARD_WIDTH + CARD_GAP);
      const y = 8;
      return this.renderCard(component, x, y, i);
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          overflow-x: auto;
        }
        svg {
          display: block;
        }
        .card {
          cursor: pointer;
        }
        .card:hover rect {
          stroke: #007bff;
          stroke-width: 2;
        }
      </style>
      <svg xmlns="http://www.w3.org/2000/svg"
           viewBox="0 0 ${svgWidth} ${svgHeight}"
           width="${svgWidth}" height="${svgHeight}">
        ${cards.join("\n        ")}
      </svg>
    `;

    // Click handler for card selection
    this.shadowRoot.querySelectorAll(".card").forEach((card) => {
      card.addEventListener("click", () => {
        const componentId = card.getAttribute("data-component-id");
        if (componentId !== null) {
          this.dispatchEvent(
            new CustomEvent("baize-card-click", {
              detail: { componentId, player: this.player },
              bubbles: true,
              composed: true,
            }),
          );
        }
      });
    });
  }

  private getHandComponents(): readonly ComponentInstance[] {
    if (this.state === null) return [];

    // Check player-specific zones first.
    const playerState = this.state.players[this.player];
    if (playerState?.zones !== undefined) {
      for (const zone of Object.values(playerState.zones)) {
        const components = this.extractComponents(zone);
        if (components.length > 0) return components;
      }
    }

    // Fall back to top-level zones that might be per-player hands.
    for (const [name, zone] of Object.entries(this.state.zones)) {
      if (!name.includes("hand")) continue;
      const components = this.extractComponents(zone);
      if (components.length > 0) {
        return components.filter(
          (c) => c.owner === this.player || c.owner === undefined,
        );
      }
    }

    return [];
  }

  private extractComponents(zone: ZoneState): readonly ComponentInstance[] {
    if (zone.zone_type === "set") {
      return (zone as SetState).components;
    }
    if (zone.zone_type === "ordered_stack") {
      return (zone as StackState).components;
    }
    return [];
  }

  private renderCard(
    component: ComponentInstance,
    x: number,
    y: number,
    _index: number,
  ): string {
    const isFaceDown = component.facing === "face_down";
    const fill = isFaceDown ? "#336699" : "#fff";
    const textFill = isFaceDown ? "#fff" : "#333";

    const label = isFaceDown
      ? "?"
      : BaizeHandElement.escapeSvg(
          component.properties?.["rank"] !== undefined
            ? String(component.properties["rank"])
            : component.component_type.charAt(0).toUpperCase(),
        );

    const safeId = BaizeHandElement.escapeSvgAttr(component.id);

    // Show properties like suit/rank if available
    let subtitle = "";
    if (!isFaceDown && component.properties !== undefined) {
      const props = component.properties;
      const rank = props["rank"] ?? props["value"];
      const suit = props["suit"];
      if (rank !== undefined || suit !== undefined) {
        const propText = [rank, suit].filter(v => v !== undefined).join(" ");
        subtitle = `<text x="${x + CARD_WIDTH / 2}" y="${y + CARD_HEIGHT / 2 + 14}" ` +
          `text-anchor="middle" font-size="9" fill="#999">` +
          `${BaizeHandElement.escapeSvg(String(propText))}</text>`;
      } else {
        subtitle = `<text x="${x + CARD_WIDTH / 2}" y="${y + CARD_HEIGHT / 2 + 14}" ` +
          `text-anchor="middle" font-size="9" fill="#999">` +
          `${BaizeHandElement.escapeSvg(component.component_type)}</text>`;
      }
    }

    return (
      `<g class="card" data-component-id="${safeId}">` +
      `<rect x="${x}" y="${y}" width="${CARD_WIDTH}" height="${CARD_HEIGHT}" ` +
      `rx="4" ry="4" fill="${fill}" stroke="#999" stroke-width="1" />` +
      `<text x="${x + CARD_WIDTH / 2}" y="${y + CARD_HEIGHT / 2 + 5}" ` +
      `text-anchor="middle" font-size="18" font-weight="bold" ` +
      `fill="${textFill}">${label}</text>` +
      subtitle +
      `</g>`
    );
  }

  /** Escape text content for safe SVG/XML embedding. */
  private static escapeSvg(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /** Escape a value for safe use inside an SVG/HTML attribute. */
  private static escapeSvgAttr(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}
