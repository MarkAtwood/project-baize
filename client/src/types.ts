// TypeScript types derived from Baize JSON schemas:
//   schema/game-definition.schema.json
//   schema/game-state.schema.json
//   schema/move-action.schema.json

// ---------------------------------------------------------------------------
// Game Definition (Tier 1 — declarative, parsed not executed)
// ---------------------------------------------------------------------------

export interface GameDefinition {
  readonly game: GameMetadata;
  readonly zones: Record<string, Zone>;
  readonly components: Record<string, Component>;
  readonly turn_order: TurnOrder;
  readonly phases?: readonly Phase[];
  readonly rules?: Record<string, Rule>;
  readonly library?: Record<string, LibraryEntry>;
  readonly end_conditions: readonly EndCondition[];
  readonly authority: Authority;
  readonly wasm_module?: string;
  readonly notation?: NotationSpec;
  readonly hand_rankings?: readonly string[];
  readonly betting_round?: BettingRound;
}

export interface GameMetadata {
  readonly name: string;
  readonly players: readonly string[] | PlayerRange;
  readonly information?: "perfect" | "imperfect";
}

export interface PlayerRange {
  readonly min: number;
  readonly max: number;
}

export interface LibraryEntry {
  readonly expression?: string;
  readonly effect?: Effect;
  readonly description?: string;
}

export interface NotationSpec {
  readonly piece_symbols?: Record<string, string>;
  readonly capture_marker?: string;
  readonly disambiguation?: string;
}

export type Visibility = "public" | "hidden" | { readonly private: string };

export type ZoneType =
  | "grid"
  | "hex_grid"
  | "graph"
  | "ordered_stack"
  | "set"
  | "queue"
  | "single_slot"
  | "track"
  | "counter";

export interface Zone {
  readonly zone_type: ZoneType;
  readonly visibility: Visibility;
  readonly per_player?: boolean;
  readonly capacity?: number | "unlimited";
  readonly dimensions?: readonly [number, number] | number;
  readonly intersections?: boolean;
  readonly labels?: {
    readonly files?: readonly string[];
    readonly ranks?: readonly (string | number)[];
  };
  readonly coloring?: string;
  readonly adjacency?: "orthogonal_4" | "orthogonal_8" | "hex_6";
  readonly star_points?: ReadonlyArray<readonly [number, number]>;
  readonly draw_visibility?: Visibility;
  readonly dynamic?: boolean;
  readonly length?: number;
  readonly lanes?: string;
  readonly points?: number;
  readonly connectivity?: number;
  readonly edge_ownership?: Record<string, unknown>;
  readonly cell_type?: string;
  readonly direction?: string;
  readonly valid_cells?: ReadonlyArray<readonly [number, number]>;
  readonly stacking_limit?: number;
  readonly storage?: "dense" | "sparse";
  readonly nodes?: readonly string[];
  readonly edges?: ReadonlyArray<readonly [string, string]>;
  readonly node_properties?: Record<string, Record<string, unknown>>;
  readonly cell_properties?: Record<string, Record<string, unknown>>;
  readonly note?: string;
}

export type MovementPrimitive =
  | "step"
  | "slide"
  | "hop"
  | "leap"
  | "place"
  | "draw"
  | "move_to"
  | "swap"
  | "remove"
  | "promote"
  | "flip"
  | "castle";

export type Direction =
  | "orthogonal"
  | "diagonal"
  | "adjacent"
  | "forward"
  | "forward_diagonal"
  | "backward"
  | "backward_diagonal"
  | readonly ("orthogonal" | "diagonal")[]
  | string;

export interface Movement {
  readonly primitive: MovementPrimitive;
  readonly direction?: Direction;
  readonly distance?: number;
  readonly dx?: number;
  readonly dy?: number;
  readonly target_zone?: string;
  readonly condition?: string;
  readonly repeat?: number | { readonly min: number; readonly max: number } | "unlimited";
  readonly after?: readonly string[];
  readonly side?: "kingside" | "queenside";
  readonly over?: number;
}

export interface Component {
  readonly registry?: string;
  readonly extends?: string;
  readonly owner?: "per_player" | "neutral" | "shared" | string;
  readonly count?: number | "unlimited";
  readonly movement?: readonly Movement[];
  readonly properties?: Record<string, readonly (string | number)[] | string | boolean>;
  readonly facing?: string;
  readonly promotion?: Promotion;
  readonly constraints?: readonly string[];
  readonly special?: string;
  readonly types?: Record<string, Record<string, unknown>>;
  readonly one_of_each?: boolean;
  readonly span?: number;
  readonly supply?: number | "unlimited" | "configurable";
  readonly adds?: Record<string, unknown>;
  readonly note?: string;
}

export interface Promotion {
  readonly trigger: string;
  readonly choices: readonly string[];
}

export interface TurnOrder {
  readonly type: "alternating" | "round_robin" | "simultaneous" | "reactive";
  readonly players?: readonly string[];
  readonly actions_per_turn?: number | readonly TurnActionSlot[];
  readonly mandatory?: boolean;
}

export type TurnActionSlot = Record<string, number | string>;

export interface Phase {
  readonly name: string;
  readonly type?: string;
  readonly simultaneous?: boolean;
  readonly server_action?: string | readonly string[];
  readonly action?: string;
  readonly actions_per_turn?: number;
  readonly starts_with?: string;
  readonly trigger?: string;
  readonly choices?: readonly string[];
  readonly ends_when?: string;
  readonly then?: string;
  readonly resolve?: string;
}

export interface Rule {
  readonly definition?: string;
  readonly action?: string;
  readonly constraint?: string;
  readonly constraints?: readonly string[];
  readonly trigger?: string;
  readonly window?: string;
  readonly effect?: string;
  readonly requires?: readonly string[];
  readonly server_resolves?: string;
}

export interface EndCondition {
  readonly result: "win" | "loss" | "draw";
  readonly player?: string;
  readonly condition: string;
  readonly name?: string;
}

export interface Authority {
  readonly server_only: readonly string[];
  readonly client_verifiable: readonly string[];
  readonly wasm_required?: readonly string[];
}

export interface BettingRound {
  readonly actions?: readonly string[];
  readonly ends_when?: string;
}

// ---------------------------------------------------------------------------
// Game State (runtime — flows between client and server)
// ---------------------------------------------------------------------------

export interface GameState {
  readonly game_id: string;
  readonly schema_ref: string;
  readonly sequence: number;
  readonly state_hash?: string;
  readonly status: "setup" | "in_progress" | "finished";
  readonly result?: GameResult;
  readonly turn: string;
  readonly phase: string;
  readonly move_count?: number;
  readonly halfmove_clock?: number;
  readonly zones: Record<string, ZoneState>;
  readonly players: Record<string, PlayerState>;
  readonly counters?: Record<string, number>;
  readonly pending_actions?: readonly PendingAction[];
  readonly pending_commits?: Record<string, string>;
  readonly simultaneous_actions?: Record<string, unknown>;
  readonly history_hash?: string;
  readonly timestamp?: string;
}

export type ZoneState =
  | GridState
  | StackState
  | SetState
  | SlotState
  | CounterState
  | TrackState
  | GraphState;

export interface GridState {
  readonly zone_type: "grid";
  readonly cells: Record<string, ComponentInstance | readonly ComponentInstance[] | null>;
  readonly cell_properties?: Record<string, Record<string, unknown>>;
}

export interface StackState {
  readonly zone_type: "ordered_stack";
  readonly components: readonly ComponentInstance[];
  readonly count?: number;
}

export interface SetState {
  readonly zone_type: "set";
  readonly components: readonly ComponentInstance[];
  readonly count?: number;
}

export interface SlotState {
  readonly zone_type: "single_slot";
  readonly component?: ComponentInstance | null;
}

export interface CounterState {
  readonly zone_type: "counter";
  readonly value: number;
}

export interface TrackState {
  readonly zone_type: "track";
  readonly positions: Record<string, readonly ComponentInstance[]>;
}

export interface GraphState {
  readonly zone_type: "graph";
  readonly occupants: Record<string, readonly ComponentInstance[]>;
  readonly node_properties?: Record<string, Record<string, unknown>>;
}

export interface ComponentInstance {
  readonly id: string;
  readonly component_type: string;
  readonly owner?: string;
  readonly facing?: "face_up" | "face_down";
  readonly state?: string;
  readonly properties?: Record<string, unknown>;
}

export interface PlayerState {
  readonly user_id?: string;
  readonly seat?: string;
  readonly active?: boolean;
  readonly connected?: boolean;
  readonly score?: number;
  readonly counters?: Record<string, number>;
  readonly zones?: Record<string, ZoneState>;
  readonly clock?: ClockState;
}

export interface ClockState {
  readonly remaining_ms?: number;
  readonly increment_ms?: number;
  readonly running?: boolean;
}

export interface PendingAction {
  readonly player: string;
  readonly action_type: string;
  readonly submitted?: boolean;
}

export interface GameResult {
  readonly outcome: "win" | "draw" | "abandoned";
  readonly winner?: string;
  readonly condition?: string;
  readonly final_scores?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Move / Action (client <-> server protocol messages)
// ---------------------------------------------------------------------------

export type ActionType =
  | "move_piece"
  | "place"
  | "draw"
  | "play_card"
  | "discard"
  | "roll_dice"
  | "flip"
  | "promote"
  | "swap"
  | "remove"
  | "pass"
  | "resign"
  | "offer_draw"
  | "accept_draw"
  | "decline_draw"
  | "fold"
  | "check"
  | "call"
  | "raise"
  | "all_in"
  | "place_ship"
  | "fire"
  | "castle"
  | "en_passant"
  | "declare_action"
  | "commit"
  | "reveal"
  | "custom";

export type Position =
  | string
  | { readonly zone?: string; readonly cell?: string; readonly index?: number };

export interface Action {
  readonly action_type: ActionType;
  readonly authority?: "client_verifiable" | "server_only";
  readonly component_id?: string;
  readonly component_type?: string;
  readonly from?: Position;
  readonly to?: Position;
  readonly zone?: string;
  readonly count?: number;
  readonly promote_to?: string;
  readonly orientation?: "horizontal" | "vertical";
  readonly rotation?: 0 | 90 | 180 | 270;
  readonly amount?: number;
  readonly side?: "kingside" | "queenside";
  readonly dice_count?: number;
  readonly dice_type?: string;
  readonly swap_with?: string;
  readonly declaration?: string;
  readonly commitment?: string;
  readonly custom_data?: Record<string, unknown>;
}

export type ClientMessageType = "submit_move" | "request_random" | "acknowledge_state";

export interface ClientMessage {
  readonly message_type: ClientMessageType;
  readonly game_id: string;
  readonly player: string;
  readonly sequence?: number;
  readonly action?: Action;
  readonly random_request?: RandomRequest;
  readonly state_hash?: string;
}

export type ServerMessageType =
  | "welcome"
  | "move_confirmed"
  | "move_rejected"
  | "random_result"
  | "reveal"
  | "state_sync";

export interface ServerMessage {
  readonly message_type: ServerMessageType;
  readonly game_id: string;
  readonly sequence?: number;
  readonly action?: Action;
  readonly result_state?: Record<string, unknown>;
  readonly reason?: string;
  readonly random_type?: string;
  readonly random_value?: number | string | readonly unknown[] | Record<string, unknown>;
  readonly reveal_to?: string;
  readonly facts?: readonly Fact[];
  readonly full_state?: GameState;
  readonly token?: string;
  readonly seat?: string;
  readonly server_version?: string;
  readonly protocol_version?: number;
}

export interface RandomRequest {
  readonly random_type: "roll" | "draw" | "shuffle";
  readonly dice_type?: string;
  readonly dice_count?: number;
  readonly draw_from?: string;
  readonly draw_count?: number;
  readonly shuffle_zone?: string;
}

export interface Fact {
  readonly fact_type: string;
  readonly component_id?: string;
  readonly zone?: string;
  readonly position?: Position;
  readonly properties?: Record<string, unknown>;
  readonly previous_visibility?: "hidden" | "private";
  readonly new_visibility?: "public" | "private";
}

// ---------------------------------------------------------------------------
// Event Log (hash-chained JSONL for tournament integrity)
// ---------------------------------------------------------------------------

export type EventType =
  | "move_applied"
  | "state_transition"
  | "game_over"
  | "random_value"
  | "visibility_change";

export interface GameEvent {
  readonly game_id: string;
  readonly sequence: number;
  readonly event_type: EventType;
  readonly player: string;
  readonly state_hash: string;
  readonly prev_hash: string;
  readonly event_hash: string;
  readonly payload: EventPayload;
}

export interface EventPayload {
  readonly action?: string;
  readonly component_id?: string;
  readonly from?: string;
  readonly to?: string;
  readonly captured?: string;
  readonly detail?: string;
  readonly transition?: string;
  readonly next_player?: string;
  readonly outcome?: "win" | "draw" | "abandoned";
  readonly winner?: string;
  readonly condition?: string;
  readonly random_type?: string;
  readonly random_result?: unknown;
  readonly zone?: string;
  readonly visibility?: string;
  readonly revealed_to?: string;
  readonly final_scores?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Component Registry (reusable component definitions)
// ---------------------------------------------------------------------------

export type ComponentType =
  | "stone"
  | "disc"
  | "pawn"
  | "token"
  | "die"
  | "card_deck"
  | "tile"
  | "piece_set"
  | "counter"
  | "card"
  | "tile_set";

export interface RegistryEntry {
  readonly id: string;
  readonly component_type: ComponentType;
  readonly name?: string;
  readonly extends?: string;
  readonly subset_of?: string;
  readonly shape?: string;
  readonly available_colors?: readonly string[];
  readonly supply?: number | "unlimited" | "configurable";
  readonly count?: number;
  readonly total?: number;
  readonly facing?: string;
  readonly flip?: boolean;
  readonly variants?: Record<string, Variant> | readonly Variant[];
  readonly properties?: readonly string[];
  readonly sides?: Record<string, unknown>;
  readonly suits?: readonly string[];
  readonly suit_symbols?: readonly string[];
  readonly suit_colors?: Record<string, string>;
  readonly ranks?: readonly (string | number)[];
  readonly rank_values?: Record<string, number | readonly number[]>;
  readonly faces?: number;
  readonly values?: readonly (string | number)[];
  readonly pieces?: Record<string, PieceDefinition>;
  readonly movement?: Record<string, string>;
  readonly distribution?: Record<string, TileDistribution>;
  readonly physical?: PhysicalForm;
  readonly visibility?: Visibility;
  readonly glyphs?: Record<string, Record<string, string>>;
  readonly note?: string;
}

export interface Variant {
  readonly shape?: string;
  readonly fill?: string;
  readonly stroke?: string;
  readonly glyph?: string;
  readonly glyph_color?: string;
  readonly label?: string;
  readonly size?: string;
  readonly color?: string;
  readonly pattern?: string;
}

export interface PieceDefinition {
  readonly glyph?: string;
  readonly promoted?: string;
  readonly count?: number;
  readonly movement?: string;
}

export interface TileDistribution {
  readonly count: number;
  readonly points: number;
}

export interface PhysicalForm {
  readonly size_mm?: readonly number[];
  readonly thickness_mm?: number;
  readonly material?: string;
  readonly weight_g?: number;
}

// ---------------------------------------------------------------------------
// Effects (used by library entries)
// ---------------------------------------------------------------------------

export type Effect =
  | { readonly sequence: readonly Effect[] }
  | { readonly if: string; readonly then: Effect; readonly else?: Effect }
  | { readonly for_each: ForEachSpec; readonly do: Effect }
  | { readonly repeat: number; readonly body: Effect }
  | { readonly remove: TargetSpec }
  | { readonly flip: TargetSpec }
  | { readonly promote: PromoteSpec }
  | { readonly add_counter: CounterSpec }
  | { readonly set_counter: CounterSpec }
  | { readonly invoke: string }
  | { readonly set_cell_property: CellPropertySpec };

export interface ForEachSpec {
  readonly collection: string;
  readonly variable: string;
}

export interface TargetSpec {
  readonly zone?: string;
  readonly position?: string;
  readonly condition?: string;
}

export interface PromoteSpec {
  readonly target: TargetSpec;
  readonly to: string;
}

export interface CounterSpec {
  readonly counter: string;
  readonly value: number | string;
  readonly player?: string;
}

export interface CellPropertySpec {
  readonly zone: string;
  readonly position: string;
  readonly property: string;
  readonly value: unknown;
}
