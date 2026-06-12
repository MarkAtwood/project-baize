/**
 * Baize Client — Entry point.
 *
 * Registers all custom elements and re-exports public API.
 *
 * Usage:
 *   <script src="baize.js"></script>
 *   <baize-game src="chess.json" server="wss://play.example.com/game/42">
 *     <baize-board></baize-board>
 *     <baize-hand player="white"></baize-hand>
 *     <baize-score></baize-score>
 *   </baize-game>
 */

import { BaizeBoardElement } from "./elements/baize-board.js";
import { BaizeGameElement } from "./elements/baize-game.js";
import { BaizeHandElement } from "./elements/baize-hand.js";
import { BaizeClockElement } from "./elements/baize-clock.js";
import { BaizeScoreElement } from "./elements/baize-score.js";

export { BaizeEngine } from "./engine.js";
export { BaizeConnection } from "./connection.js";
export { validateServerMessage } from "./validation.js";
export { BaizeGameElement } from "./elements/baize-game.js";
export { BaizeBoardElement } from "./elements/baize-board.js";
export { BaizeHandElement } from "./elements/baize-hand.js";
export { BaizeClockElement } from "./elements/baize-clock.js";
export { BaizeScoreElement } from "./elements/baize-score.js";
export type {
  Action,
  ActionType,
  Authority,
  BettingRound,
  ClientMessage,
  ClockState,
  Component,
  ComponentInstance,
  ComponentType,
  CounterState,
  Direction,
  Effect,
  EndCondition,
  EventPayload,
  EventType,
  Fact,
  ForEachSpec,
  GameDefinition,
  GameEvent,
  GameMetadata,
  GameResult,
  GameState,
  GraphState,
  GridState,
  LibraryEntry,
  Movement,
  MovementPrimitive,
  NotationSpec,
  PendingAction,
  Phase,
  PhysicalForm,
  PieceDefinition,
  PlayerRange,
  PlayerState,
  Position,
  Promotion,
  RandomRequest,
  RegistryEntry,
  Rule,
  ServerMessage,
  SetState,
  SlotState,
  StackState,
  TargetSpec,
  TileDistribution,
  TrackState,
  TurnActionSlot,
  TurnOrder,
  Variant,
  Visibility,
  Zone,
  ZoneState,
  ZoneType,
} from "./types.js";

function registerElements(): void {
  const elements: ReadonlyArray<readonly [string, CustomElementConstructor]> = [
    ["baize-game", BaizeGameElement],
    ["baize-board", BaizeBoardElement],
    ["baize-clock", BaizeClockElement],
    ["baize-hand", BaizeHandElement],
    ["baize-score", BaizeScoreElement],
  ];

  for (const [tag, constructor] of elements) {
    if (customElements.get(tag) === undefined) {
      customElements.define(tag, constructor);
    }
  }
}

registerElements();
