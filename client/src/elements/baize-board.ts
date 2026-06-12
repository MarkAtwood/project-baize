/**
 * <baize-board> — Renders the game board as inline SVG in Shadow DOM.
 *
 * Listens for "baize-state-update" from its parent <baize-game> element
 * and re-renders the board grid with zone contents and legal move highlights.
 *
 * Supports grid zones with configurable dimensions, labels, and coloring.
 *
 * Interaction modes:
 *   - Click-to-select: click a cell to emit "baize-cell-click" (original)
 *   - Drag-and-drop: mousedown/touchstart on a piece starts a drag,
 *     highlights legal targets, and emits "baize-move" on valid drop.
 */

import type {
  Action,
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

interface CellPosition {
  readonly row: number;
  readonly col: number;
}

interface DragState {
  /** The zone name being dragged within. */
  zoneName: string;
  /** Grid coordinate string of the origin cell (e.g. "e2"). */
  fromCoord: string;
  /** Row/col of the origin cell. */
  from: CellPosition;
  /** The component being dragged. */
  component: ComponentInstance;
  /** Set of coordinate strings that are legal drop targets. */
  legalTargets: ReadonlySet<string>;
  /** Current pointer position in SVG user-space. */
  pointerX: number;
  pointerY: number;
  /** Whether the pointer has moved enough to count as a drag (vs click). */
  hasMoved: boolean;
}

const CELL_SIZE = 60;
const LABEL_OFFSET = 20;
const DRAG_THRESHOLD = 5; // px before mousedown is treated as drag
const GHOST_OPACITY = 0.7;
const DIMMED_OPACITY = 0.4;
const COLORS = {
  lightCell: "#f0d9b5",
  darkCell: "#b58863",
  highlight: "rgba(255, 255, 0, 0.4)",
  dropTarget: "rgba(0, 200, 80, 0.45)",
  gridLine: "#333",
  text: "#333",
  pieceLight: "#fff",
  pieceDark: "#333",
} as const;

export class BaizeBoardElement extends HTMLElement {
  private definition: GameDefinition | null = null;
  private state: GameState | null = null;
  private legalMoveTargets: ReadonlySet<string> = new Set();

  // Drag state
  private drag: DragState | null = null;
  private ghostGroup: SVGGElement | null = null;
  private startPointerX = 0;
  private startPointerY = 0;

  // Cached geometry for coordinate lookups during drag
  private cachedOx = 0;
  private cachedOy = 0;
  private cachedCols = 0;
  private cachedRows = 0;
  private cachedZoneDef: Zone | null = null;

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.renderPlaceholder();
  }

  connectedCallback(): void {
    const parent = this.closest("baize-game");
    parent?.addEventListener("baize-state-update", this.handleStateUpdate);
    document.addEventListener("keydown", this.handleKeyDown);
  }

  disconnectedCallback(): void {
    const parent = this.closest("baize-game");
    parent?.removeEventListener("baize-state-update", this.handleStateUpdate);
    document.removeEventListener("keydown", this.handleKeyDown);
    this.cancelDrag();
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

  // ---------------------------------------------------------------------------
  // State update from parent
  // ---------------------------------------------------------------------------

  private handleStateUpdate = (event: Event): void => {
    const detail = (event as CustomEvent<StateUpdateDetail>).detail;
    this.definition = detail.definition;
    this.state = detail.state;
    this.cancelDrag();
    this.renderBoard();
  };

  // ---------------------------------------------------------------------------
  // Legal moves query
  // ---------------------------------------------------------------------------

  /**
   * Query the parent <baize-game> engine for legal moves originating from
   * `fromCoord`, and return the set of target coordinate strings.
   */
  private computeLegalTargets(fromCoord: string): ReadonlySet<string> {
    const gameEl = this.closest("baize-game") as
      | (HTMLElement & { getEngine?(): { isLoaded: boolean; legalMoves(): readonly Action[] } | null })
      | null;

    if (gameEl === null || gameEl === undefined) return new Set();

    const engine = gameEl.getEngine?.() ?? null;
    if (engine === null || !engine.isLoaded) return new Set();

    try {
      const moves = engine.legalMoves();
      const targets = new Set<string>();
      for (const move of moves) {
        const moveFrom = typeof move.from === "string" ? move.from : move.from?.cell;
        const moveTo = typeof move.to === "string" ? move.to : move.to?.cell;
        if (moveFrom === fromCoord && moveTo !== undefined) {
          targets.add(moveTo);
        }
      }
      return targets;
    } catch {
      return new Set();
    }
  }

  // ---------------------------------------------------------------------------
  // Coordinate helpers
  // ---------------------------------------------------------------------------

  /** Convert a pointer event's client coordinates to SVG user-space. */
  private clientToSvg(clientX: number, clientY: number): { x: number; y: number } | null {
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (ctm === null) return null;
    const transformed = pt.matrixTransform(ctm.inverse());
    return { x: transformed.x, y: transformed.y };
  }

  /** Convert SVG coordinates to grid col/row (may be out of bounds). */
  private svgToCell(svgX: number, svgY: number): CellPosition | null {
    const col = Math.floor((svgX - this.cachedOx) / CELL_SIZE);
    const row = Math.floor((svgY - this.cachedOy) / CELL_SIZE);
    if (col < 0 || col >= this.cachedCols || row < 0 || row >= this.cachedRows) {
      return null;
    }
    return { col, row };
  }

  /** Build a reverse map from coord string to {row, col}. */
  private coordToPosition(coord: string): CellPosition | null {
    if (this.cachedZoneDef === null) return null;
    for (let r = 0; r < this.cachedRows; r++) {
      for (let c = 0; c < this.cachedCols; c++) {
        if (this.cellCoord(c, r, this.cachedZoneDef) === coord) {
          return { row: r, col: c };
        }
      }
    }
    return null;
  }

  // ---------------------------------------------------------------------------
  // Drag lifecycle
  // ---------------------------------------------------------------------------

  private handlePointerDown = (event: MouseEvent | TouchEvent): void => {
    // Only handle primary button (left click) for mouse
    if (event instanceof MouseEvent && event.button !== 0) return;

    const clientPos = this.extractClientPos(event);
    if (clientPos === null) return;

    const svgPos = this.clientToSvg(clientPos.x, clientPos.y);
    if (svgPos === null) return;

    const cell = this.svgToCell(svgPos.x, svgPos.y);
    if (cell === null) return;

    if (this.cachedZoneDef === null) return;
    const coord = this.cellCoord(cell.col, cell.row, this.cachedZoneDef);

    // Find the board zone entry
    const boardEntry = this.findBoardZone();
    if (boardEntry === null) return;
    const [zoneName] = boardEntry;

    const zoneState = this.state?.zones[zoneName];
    if (zoneState === undefined || zoneState.zone_type !== "grid") return;

    const component = this.getComponentAt(zoneState, coord);
    if (component === null) return;

    // Record starting position (to distinguish click from drag)
    this.startPointerX = svgPos.x;
    this.startPointerY = svgPos.y;

    // Compute legal targets for this piece
    const legalTargets = this.computeLegalTargets(coord);

    this.drag = {
      zoneName,
      fromCoord: coord,
      from: cell,
      component,
      legalTargets,
      pointerX: svgPos.x,
      pointerY: svgPos.y,
      hasMoved: false,
    };

    // Bind move/up listeners at the document level so drag continues
    // even if pointer leaves the SVG
    document.addEventListener("mousemove", this.handlePointerMove);
    document.addEventListener("mouseup", this.handlePointerUp);
    document.addEventListener("touchmove", this.handlePointerMove, { passive: false });
    document.addEventListener("touchend", this.handlePointerUp);
    document.addEventListener("touchcancel", this.handlePointerCancel);

    // Prevent text selection and default touch behavior during drag
    event.preventDefault();
  };

  private handlePointerMove = (event: MouseEvent | TouchEvent): void => {
    if (this.drag === null) return;

    const clientPos = this.extractClientPos(event);
    if (clientPos === null) return;

    const svgPos = this.clientToSvg(clientPos.x, clientPos.y);
    if (svgPos === null) return;

    // Check drag threshold
    if (!this.drag.hasMoved) {
      const dx = svgPos.x - this.startPointerX;
      const dy = svgPos.y - this.startPointerY;
      if (Math.sqrt(dx * dx + dy * dy) < DRAG_THRESHOLD) return;
      this.drag.hasMoved = true;
      this.onDragStart();
    }

    this.drag.pointerX = svgPos.x;
    this.drag.pointerY = svgPos.y;
    this.updateGhostPosition();

    // Prevent scrolling on touch
    event.preventDefault();
  };

  private handlePointerUp = (event: MouseEvent | TouchEvent): void => {
    this.removeDocumentListeners();

    if (this.drag === null) return;

    if (!this.drag.hasMoved) {
      // Pointer never moved past threshold: treat as a click
      const coord = this.drag.fromCoord;
      const zoneName = this.drag.zoneName;
      const { col, row } = this.drag.from;
      this.drag = null;
      this.dispatchEvent(
        new CustomEvent("baize-cell-click", {
          detail: { cell: coord, zone: zoneName, col, row },
          bubbles: true,
          composed: true,
        }),
      );
      return;
    }

    // Determine drop target
    const clientPos = this.extractClientPos(event);
    if (clientPos !== null) {
      const svgPos = this.clientToSvg(clientPos.x, clientPos.y);
      if (svgPos !== null) {
        const dropCell = this.svgToCell(svgPos.x, svgPos.y);
        if (dropCell !== null && this.cachedZoneDef !== null) {
          const dropCoord = this.cellCoord(dropCell.col, dropCell.row, this.cachedZoneDef);
          if (this.drag.legalTargets.has(dropCoord)) {
            this.completeDrag(dropCell, dropCoord);
            return;
          }
        }
      }
    }

    // Invalid drop — cancel
    this.cancelDrag();
  };

  private handlePointerCancel = (_event: TouchEvent): void => {
    this.cancelDrag();
  };

  private handleKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape" && this.drag !== null) {
      this.cancelDrag();
    }
  };

  /** Called once the pointer has moved past the drag threshold. */
  private onDragStart(): void {
    if (this.drag === null) return;

    // Show legal target highlights and dim the board
    this.showDragOverlays();

    // Create ghost piece that follows the pointer
    this.createGhost();
  }

  /** Complete a valid drag-drop move. */
  private completeDrag(toCell: CellPosition, _toCoord: string): void {
    if (this.drag === null) return;

    const from = this.drag.from;
    const componentId = this.drag.component.id;

    this.removeDragOverlays();
    this.removeGhost();
    this.drag = null;

    this.dispatchEvent(
      new CustomEvent("baize-move", {
        detail: {
          from: { row: from.row, col: from.col },
          to: { row: toCell.row, col: toCell.col },
          component_id: componentId,
        },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Cancel an in-progress drag. */
  private cancelDrag(): void {
    this.removeDocumentListeners();
    this.removeDragOverlays();
    this.removeGhost();
    this.drag = null;
  }

  // ---------------------------------------------------------------------------
  // Ghost piece (follows pointer during drag)
  // ---------------------------------------------------------------------------

  private createGhost(): void {
    if (this.drag === null) return;
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return;

    const ns = "http://www.w3.org/2000/svg";
    const g = document.createElementNS(ns, "g");
    g.setAttribute("class", "drag-ghost");
    g.setAttribute("pointer-events", "none");
    g.style.opacity = String(GHOST_OPACITY);

    const r = CELL_SIZE * 0.35;
    const fill =
      this.drag.component.owner === "white" || this.drag.component.owner === "player1"
        ? COLORS.pieceLight
        : COLORS.pieceDark;
    const stroke = fill === COLORS.pieceLight ? COLORS.pieceDark : COLORS.pieceLight;
    const label = this.drag.component.component_type.charAt(0).toUpperCase();

    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("r", String(r));
    circle.setAttribute("fill", fill);
    circle.setAttribute("stroke", stroke);
    circle.setAttribute("stroke-width", "2");

    const text = document.createElementNS(ns, "text");
    text.setAttribute("y", "5");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("font-size", "14");
    text.setAttribute("font-weight", "bold");
    text.setAttribute("fill", stroke);
    text.textContent = label;

    g.appendChild(circle);
    g.appendChild(text);
    svg.appendChild(g);
    this.ghostGroup = g;

    // Hide the original piece
    this.hideSourcePiece();

    this.updateGhostPosition();
  }

  private updateGhostPosition(): void {
    if (this.ghostGroup === null || this.drag === null) return;
    this.ghostGroup.setAttribute(
      "transform",
      `translate(${this.drag.pointerX}, ${this.drag.pointerY})`,
    );
  }

  private removeGhost(): void {
    if (this.ghostGroup !== null) {
      this.ghostGroup.remove();
      this.ghostGroup = null;
    }
    this.showSourcePiece();
  }

  private hideSourcePiece(): void {
    if (this.drag === null) return;
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return;
    const pieces = svg.querySelectorAll(`[data-piece="${this.drag.fromCoord}"]`);
    pieces.forEach((el) => {
      (el as SVGElement).style.visibility = "hidden";
    });
  }

  private showSourcePiece(): void {
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return;
    const pieces = svg.querySelectorAll("[data-piece]");
    pieces.forEach((el) => {
      (el as SVGElement).style.visibility = "";
    });
  }

  // ---------------------------------------------------------------------------
  // Drag overlays (legal target highlights, dimming)
  // ---------------------------------------------------------------------------

  private showDragOverlays(): void {
    if (this.drag === null) return;
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return;
    const ns = "http://www.w3.org/2000/svg";

    // Dim cells that are NOT legal targets
    const allCells = svg.querySelectorAll("rect[data-cell]");
    allCells.forEach((rect) => {
      const coord = rect.getAttribute("data-cell");
      if (coord !== null && !this.drag!.legalTargets.has(coord) && coord !== this.drag!.fromCoord) {
        (rect as SVGElement).style.opacity = String(DIMMED_OPACITY);
      }
    });

    // Add bright overlay on legal targets
    for (const targetCoord of this.drag.legalTargets) {
      const pos = this.coordToPosition(targetCoord);
      if (pos === null) continue;
      const x = pos.col * CELL_SIZE + this.cachedOx;
      const y = pos.row * CELL_SIZE + this.cachedOy;

      const overlay = document.createElementNS(ns, "rect");
      overlay.setAttribute("x", String(x));
      overlay.setAttribute("y", String(y));
      overlay.setAttribute("width", String(CELL_SIZE));
      overlay.setAttribute("height", String(CELL_SIZE));
      overlay.setAttribute("fill", COLORS.dropTarget);
      overlay.setAttribute("class", "drag-target-overlay");
      overlay.setAttribute("pointer-events", "none");
      svg.appendChild(overlay);
    }
  }

  private removeDragOverlays(): void {
    const svg = this.shadowRoot?.querySelector("svg");
    if (svg === null || svg === undefined) return;

    // Remove target overlays
    svg.querySelectorAll(".drag-target-overlay").forEach((el) => el.remove());

    // Restore opacity on all cells
    svg.querySelectorAll("rect[data-cell]").forEach((rect) => {
      (rect as SVGElement).style.opacity = "";
    });
  }

  // ---------------------------------------------------------------------------
  // Document-level listener management
  // ---------------------------------------------------------------------------

  private removeDocumentListeners(): void {
    document.removeEventListener("mousemove", this.handlePointerMove);
    document.removeEventListener("mouseup", this.handlePointerUp);
    document.removeEventListener("touchmove", this.handlePointerMove);
    document.removeEventListener("touchend", this.handlePointerUp);
    document.removeEventListener("touchcancel", this.handlePointerCancel);
  }

  // ---------------------------------------------------------------------------
  // Client position extraction
  // ---------------------------------------------------------------------------

  private extractClientPos(event: MouseEvent | TouchEvent): { x: number; y: number } | null {
    if (event instanceof MouseEvent) {
      return { x: event.clientX, y: event.clientY };
    }
    const touch = event.changedTouches[0];
    if (touch === undefined) return null;
    return { x: touch.clientX, y: touch.clientY };
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

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

    // Cache geometry for drag coordinate lookups
    const hasLabels = zoneDef.labels !== undefined;
    const ox = hasLabels ? LABEL_OFFSET : 0;
    const oy = hasLabels ? LABEL_OFFSET : 0;
    this.cachedOx = ox;
    this.cachedOy = oy;
    this.cachedCols = cols;
    this.cachedRows = rows;
    this.cachedZoneDef = zoneDef;

    const svgWidth = cols * CELL_SIZE + ox;
    const svgHeight = rows * CELL_SIZE + oy;

    const cells: string[] = [];

    // Intersection mode (Go-style) vs regular grid
    if (zoneDef.intersections === true && zoneState !== undefined && zoneState.zone_type === "grid") {
      cells.push(...this.renderIntersectionGrid(cols, rows, ox, oy, zoneDef, zoneState, zoneName));
    } else {
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

          const safeCoord = BaizeBoardElement.escapeSvgAttr(coord);
          cells.push(
            `<rect x="${x}" y="${y}" width="${CELL_SIZE}" height="${CELL_SIZE}" ` +
              `fill="${fill}" stroke="${COLORS.gridLine}" stroke-width="0.5" ` +
              `data-cell="${safeCoord}" data-col="${c}" data-row="${r}" />`,
          );

          if (isHighlighted) {
            cells.push(
              `<rect x="${x}" y="${y}" width="${CELL_SIZE}" height="${CELL_SIZE}" ` +
                `fill="${COLORS.highlight}" data-highlight="${safeCoord}" pointer-events="none" />`,
            );
          }

          // Render component if present (engine uses "col,row" coords)
          if (zoneState !== undefined && zoneState.zone_type === "grid") {
            const engineCoord = `${c},${r}`;
            const component = this.getComponentAt(zoneState, engineCoord);
            if (component !== null) {
              cells.push(this.renderPiece(component, x, y, coord));
              const depth = this.getStackDepth(zoneState, engineCoord);
              if (depth > 1) {
                cells.push(this.renderStackBadge(x, y, depth));
              }
            }

            // Render cell property indicator if present
            if (zoneState.cell_properties !== undefined) {
              const cellProps = zoneState.cell_properties[engineCoord];
              if (cellProps !== undefined) {
                const propText = Object.entries(cellProps)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(" ");
                if (propText.length > 0) {
                  const safeText = BaizeBoardElement.escapeSvg(propText.slice(0, 8));
                  cells.push(
                    `<text x="${x + 3}" y="${y + CELL_SIZE - 4}" font-size="8" fill="#666" ` +
                    `pointer-events="none">${safeText}</text>`
                  );
                }
              }
            }
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
          const safeLabel = BaizeBoardElement.escapeSvg(String(files[c] ?? ""));
          labels.push(
            `<text x="${x}" y="${svgHeight + 16}" text-anchor="middle" ` +
              `font-size="12" fill="${COLORS.text}">${safeLabel}</text>`,
          );
        }
      }
      if (ranks !== undefined) {
        for (let r = 0; r < Math.min(rows, ranks.length); r++) {
          const y = r * CELL_SIZE + oy + CELL_SIZE / 2 + 4;
          const rankIdx = ranks.length - 1 - r;
          const label = ranks[rankIdx];
          const safeLabel = BaizeBoardElement.escapeSvg(String(label ?? ""));
          labels.push(
            `<text x="${ox - 6}" y="${y}" text-anchor="end" ` +
              `font-size="12" fill="${COLORS.text}">${safeLabel}</text>`,
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
          touch-action: none;
          user-select: none;
          -webkit-user-select: none;
        }
        rect[data-cell] {
          cursor: pointer;
          transition: opacity 0.15s ease;
        }
        rect[data-cell]:hover {
          opacity: 0.8;
        }
        .drag-ghost {
          pointer-events: none;
        }
        .drag-target-overlay {
          pointer-events: none;
        }
      </style>
      <svg xmlns="http://www.w3.org/2000/svg"
           viewBox="0 0 ${svgWidth} ${svgHeight + (hasLabels ? 20 : 0)}"
           width="${svgWidth}" height="${svgHeight + (hasLabels ? 20 : 0)}">
        ${cells.join("\n        ")}
        ${labels.join("\n        ")}
      </svg>
    `;

    // Attach click handler for cell selection (fallback when not dragging)
    this.shadowRoot.querySelectorAll("rect[data-cell]").forEach((rect) => {
      rect.addEventListener("click", () => {
        // If a drag just completed, the drag handlers already consumed the
        // interaction — skip the click.
        if (this.drag !== null) return;
        const cell = rect.getAttribute("data-cell");
        const col = Number(rect.getAttribute("data-col"));
        const row = Number(rect.getAttribute("data-row"));
        if (cell !== null) {
          this.dispatchEvent(
            new CustomEvent("baize-cell-click", {
              detail: { cell, zone: zoneName, col, row },
              bubbles: true,
              composed: true,
            }),
          );
        }
      });
    });

    // Attach drag start handlers (mouse + touch)
    const svg = this.shadowRoot.querySelector("svg");
    if (svg !== null) {
      svg.addEventListener("mousedown", this.handlePointerDown);
      svg.addEventListener("touchstart", this.handlePointerDown, { passive: false });
    }
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
      // Stacking: return top component (last in array = top of stack)
      return cell.length > 0 ? (cell[cell.length - 1] as ComponentInstance) : null;
    }
    return cell as ComponentInstance;
  }

  private getStackDepth(gridState: GridState, coord: string): number {
    const cell = gridState.cells[coord];
    if (cell === null || cell === undefined) return 0;
    if (Array.isArray(cell)) return cell.length;
    return 1;
  }

  private renderPiece(
    component: ComponentInstance,
    x: number,
    y: number,
    coord: string,
  ): string {
    const cx = x + CELL_SIZE / 2;
    const cy = y + CELL_SIZE / 2;
    const r = CELL_SIZE * 0.35;
    const fill =
      component.owner === "white" || component.owner === "player1"
        ? COLORS.pieceLight
        : COLORS.pieceDark;
    const stroke =
      fill === COLORS.pieceLight ? COLORS.pieceDark : COLORS.pieceLight;

    const label = BaizeBoardElement.escapeSvg(
      component.component_type.charAt(0).toUpperCase(),
    );
    const safeCoord = BaizeBoardElement.escapeSvgAttr(coord);

    return (
      `<g data-piece="${safeCoord}">` +
      `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2" />` +
      `<text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="14" ` +
      `font-weight="bold" fill="${stroke}">${label}</text>` +
      `</g>`
    );
  }

  private renderStackBadge(x: number, y: number, depth: number): string {
    const bx = x + CELL_SIZE - 10;
    const by = y + 10;
    return (
      `<g pointer-events="none">` +
      `<circle cx="${bx}" cy="${by}" r="7" fill="#e74c3c" />` +
      `<text x="${bx}" y="${by + 4}" text-anchor="middle" font-size="9" ` +
      `font-weight="bold" fill="#fff">${depth}</text>` +
      `</g>`
    );
  }

  private renderIntersectionGrid(
    cols: number,
    rows: number,
    ox: number,
    oy: number,
    zoneDef: Zone,
    zoneState: GridState,
    _zoneName: string,
  ): string[] {
    const lines: string[] = [];
    const half = CELL_SIZE / 2;

    // Draw grid lines
    for (let r = 0; r < rows; r++) {
      const y = oy + r * CELL_SIZE + half;
      lines.push(
        `<line x1="${ox + half}" y1="${y}" x2="${ox + (cols - 1) * CELL_SIZE + half}" y2="${y}" ` +
        `stroke="${COLORS.gridLine}" stroke-width="1" />`
      );
    }
    for (let c = 0; c < cols; c++) {
      const x = ox + c * CELL_SIZE + half;
      lines.push(
        `<line x1="${x}" y1="${oy + half}" x2="${x}" y2="${oy + (rows - 1) * CELL_SIZE + half}" ` +
        `stroke="${COLORS.gridLine}" stroke-width="1" />`
      );
    }

    // Draw star points
    if (zoneDef.star_points !== undefined) {
      for (const [sc, sr] of zoneDef.star_points) {
        const sx = ox + sc * CELL_SIZE + half;
        const sy = oy + sr * CELL_SIZE + half;
        lines.push(
          `<circle cx="${sx}" cy="${sy}" r="3" fill="${COLORS.gridLine}" />`
        );
      }
    }

    // Draw click targets (invisible rects for interaction)
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = c * CELL_SIZE + ox;
        const y = r * CELL_SIZE + oy;
        const coord = this.cellCoord(c, r, zoneDef);
        const safeCoord = BaizeBoardElement.escapeSvgAttr(coord);
        lines.push(
          `<rect x="${x}" y="${y}" width="${CELL_SIZE}" height="${CELL_SIZE}" ` +
          `fill="transparent" data-cell="${safeCoord}" data-col="${c}" data-row="${r}" />`
        );

        // Render piece at intersection
        const engineCoord = `${c},${r}`;
        const component = this.getComponentAt(zoneState, engineCoord);
        if (component !== null) {
          lines.push(this.renderPiece(component, x, y, coord));
          const depth = this.getStackDepth(zoneState, engineCoord);
          if (depth > 1) {
            lines.push(this.renderStackBadge(x, y, depth));
          }
        }
      }
    }

    return lines;
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
