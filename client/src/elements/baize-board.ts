/**
 * <baize-board> — Renders the game board as inline SVG in Shadow DOM.
 *
 * Listens for "baize-state-update" from its parent <baize-game> element
 * and re-renders the board grid with zone contents and legal move highlights.
 *
 * Supports grid zones with configurable dimensions, labels, and coloring.
 */

import type {
  ComponentInstance,
  GameDefinition,
  GameState,
  GridState,
  Zone,
} from "../types.js";

interface StateUpdateDetail {
  readonly state: GameState | null;
  readonly definition: GameDefinition | null;
}

const CELL_SIZE = 60;
const LABEL_OFFSET = 20;
const COLORS = {
  lightCell: "#f0d9b5",
  darkCell: "#b58863",
  highlight: "rgba(255, 255, 0, 0.4)",
  gridLine: "#333",
  text: "#333",
  pieceLight: "#fff",
  pieceDark: "#333",
} as const;

export class BaizeBoardElement extends HTMLElement {
  private definition: GameDefinition | null = null;
  private state: GameState | null = null;
  private legalMoveTargets: ReadonlySet<string> = new Set();

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

  /** Highlight a set of cell coordinates as legal move targets. */
  setLegalMoves(targets: ReadonlySet<string>): void {
    this.legalMoveTargets = targets;
    this.renderBoard();
  }

  /** Clear legal move highlights. */
  clearLegalMoves(): void {
    this.legalMoveTargets = new Set();
    this.renderBoard();
  }

  private handleStateUpdate = (event: Event): void => {
    const detail = (event as CustomEvent<StateUpdateDetail>).detail;
    this.definition = detail.definition;
    this.state = detail.state;
    this.renderBoard();
  };

  private renderPlaceholder(): void {
    if (this.shadowRoot === null) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          max-width: 100%;
          overflow: auto;
        }
        .placeholder {
          width: 200px;
          height: 200px;
          background: #f5f5f5;
          border: 1px dashed #ccc;
          display: flex;
          align-items: center;
          justify-content: center;
          font-family: system-ui, sans-serif;
          font-size: 0.875rem;
          color: #999;
        }
      </style>
      <div class="placeholder">Board</div>
    `;
  }

  private renderBoard(): void {
    if (this.shadowRoot === null) return;
    if (this.definition === null || this.state === null) return;

    // Find the first grid-type zone to render.
    const boardEntry = this.findBoardZone();
    if (boardEntry === null) {
      this.renderPlaceholder();
      return;
    }

    const [zoneName, zoneDef] = boardEntry;
    const zoneState = this.state.zones[zoneName];

    const dims = this.getGridDimensions(zoneDef);
    if (dims === null) return;
    const [cols, rows] = dims;

    const hasLabels = zoneDef.labels !== undefined;
    const ox = hasLabels ? LABEL_OFFSET : 0;
    const oy = hasLabels ? LABEL_OFFSET : 0;
    const svgWidth = cols * CELL_SIZE + ox;
    const svgHeight = rows * CELL_SIZE + oy;

    const cells: string[] = [];

    // Grid cells
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = c * CELL_SIZE + ox;
        const y = r * CELL_SIZE + oy;
        const coord = this.cellCoord(c, r, zoneDef);

        const isDark =
          zoneDef.coloring === "alternating" ? (c + r) % 2 === 1 : false;
        const fill = isDark ? COLORS.darkCell : COLORS.lightCell;
        const isHighlighted = this.legalMoveTargets.has(coord);

        cells.push(
          `<rect x="${x}" y="${y}" width="${CELL_SIZE}" height="${CELL_SIZE}" ` +
            `fill="${fill}" stroke="${COLORS.gridLine}" stroke-width="0.5" ` +
            `data-cell="${coord}" />`,
        );

        if (isHighlighted) {
          cells.push(
            `<rect x="${x}" y="${y}" width="${CELL_SIZE}" height="${CELL_SIZE}" ` +
              `fill="${COLORS.highlight}" data-highlight="${coord}" />`,
          );
        }

        // Render component if present
        if (zoneState !== undefined && zoneState.zone_type === "grid") {
          const component = this.getComponentAt(zoneState, coord);
          if (component !== null) {
            cells.push(this.renderPiece(component, x, y));
          }
        }
      }
    }

    // Axis labels
    const labels: string[] = [];
    if (zoneDef.labels !== undefined) {
      const { files, ranks } = zoneDef.labels;
      if (files !== undefined) {
        for (let c = 0; c < Math.min(cols, files.length); c++) {
          const x = c * CELL_SIZE + ox + CELL_SIZE / 2;
          labels.push(
            `<text x="${x}" y="${svgHeight + 16}" text-anchor="middle" ` +
              `font-size="12" fill="${COLORS.text}">${files[c]}</text>`,
          );
        }
      }
      if (ranks !== undefined) {
        for (let r = 0; r < Math.min(rows, ranks.length); r++) {
          const y = r * CELL_SIZE + oy + CELL_SIZE / 2 + 4;
          const rankIdx = ranks.length - 1 - r;
          const label = ranks[rankIdx];
          labels.push(
            `<text x="${ox - 6}" y="${y}" text-anchor="end" ` +
              `font-size="12" fill="${COLORS.text}">${label ?? ""}</text>`,
          );
        }
      }
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          max-width: 100%;
          overflow: auto;
        }
        svg {
          display: block;
        }
        rect[data-cell] {
          cursor: pointer;
        }
        rect[data-cell]:hover {
          opacity: 0.8;
        }
      </style>
      <svg xmlns="http://www.w3.org/2000/svg"
           viewBox="0 0 ${svgWidth} ${svgHeight + (hasLabels ? 20 : 0)}"
           width="${svgWidth}" height="${svgHeight + (hasLabels ? 20 : 0)}">
        ${cells.join("\n        ")}
        ${labels.join("\n        ")}
      </svg>
    `;

    // Attach click handler for cell selection
    this.shadowRoot.querySelectorAll("rect[data-cell]").forEach((rect) => {
      rect.addEventListener("click", () => {
        const cell = rect.getAttribute("data-cell");
        if (cell !== null) {
          this.dispatchEvent(
            new CustomEvent("baize-cell-click", {
              detail: { cell, zone: zoneName },
              bubbles: true,
              composed: true,
            }),
          );
        }
      });
    });
  }

  private findBoardZone(): [string, Zone] | null {
    if (this.definition === null) return null;
    for (const [name, zone] of Object.entries(this.definition.zones)) {
      if (zone.zone_type === "grid" || zone.zone_type === "hex_grid") {
        return [name, zone];
      }
    }
    return null;
  }

  private getGridDimensions(zone: Zone): [number, number] | null {
    const dims = zone.dimensions;
    if (dims === undefined) return null;
    if (typeof dims === "number") return [dims, dims];
    return [dims[0], dims[1]];
  }

  private cellCoord(col: number, row: number, zone: Zone): string {
    if (zone.labels?.files !== undefined) {
      const file = zone.labels.files[col] ?? String(col);
      const ranks = zone.labels.ranks;
      if (ranks !== undefined) {
        const rankIdx = ranks.length - 1 - row;
        const rank = ranks[rankIdx];
        return `${file}${rank ?? row + 1}`;
      }
      return `${file}${row + 1}`;
    }
    return `${col},${row}`;
  }

  private getComponentAt(
    gridState: GridState,
    coord: string,
  ): ComponentInstance | null {
    const cell = gridState.cells[coord];
    if (cell === null || cell === undefined) return null;
    if (Array.isArray(cell)) {
      return cell.length > 0 ? (cell[0] as ComponentInstance) : null;
    }
    return cell as ComponentInstance;
  }

  private renderPiece(component: ComponentInstance, x: number, y: number): string {
    const cx = x + CELL_SIZE / 2;
    const cy = y + CELL_SIZE / 2;
    const r = CELL_SIZE * 0.35;
    const fill =
      component.owner === "white" || component.owner === "player1"
        ? COLORS.pieceLight
        : COLORS.pieceDark;
    const stroke =
      fill === COLORS.pieceLight ? COLORS.pieceDark : COLORS.pieceLight;

    const label = component.component_type.charAt(0).toUpperCase();

    return (
      `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2" />` +
      `<text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="14" ` +
      `font-weight="bold" fill="${stroke}">${label}</text>`
    );
  }
}
