import { describe, it } from "node:test";
import { strict as assert } from "node:assert";
import type {
  Action,
  ActionType,
  ClientMessage,
  ComponentInstance,
  CounterState,
  EndCondition,
  Fact,
  GameDefinition,
  GameEvent,
  GameResult,
  GraphState,
  GameState,
  GridState,
  Movement,
  PendingAction,
  PlayerState,
  RegistryEntry,
  RandomRequest,
  ServerMessage,
  SetState,
  SlotState,
  StackState,
  TrackState,
  Zone,
  ZoneState,
} from "../types.js";

/**
 * Type-level tests: these verify that the TypeScript types accept
 * values shaped like what the engine actually produces.
 * If these compile and run, the types are compatible.
 */

describe("Type compatibility", () => {
  it("GameState accepts engine-shaped data", () => {
    const state: GameState = {
      game_id: "test-1",
      schema_ref: "tic-tac-toe.json",
      sequence: 0,
      status: "in_progress",
      turn: "X",
      phase: "play",
      zones: {
        board: {
          zone_type: "grid",
          cells: {
            "0,0": { id: "x_0", component_type: "X_piece", facing: "face_up" },
            "1,1": null,
          },
        } satisfies GridState,
      },
      players: {
        X: { seat: "X", active: true, score: 0 },
        O: { seat: "O", active: true, score: 0 },
      },
    };
    assert.equal(state.status, "in_progress");
  });

  it("GameState accepts optional fields", () => {
    const state: GameState = {
      game_id: "chess-1",
      schema_ref: "chess.json",
      sequence: 20,
      status: "in_progress",
      turn: "white",
      phase: "main",
      zones: {},
      players: {},
      state_hash: "abc123",
      move_count: 10,
      halfmove_clock: 4,
      history_hash: "def456",
      timestamp: "2026-01-01T00:00:00Z",
      counters: { pot: 100, round: 2 },
      pending_actions: [
        { player: "player2", action_type: "call" },
      ],
    };
    assert.equal(state.move_count, 10);
    assert.equal(state.counters!["pot"], 100);
  });

  it("GameState accepts finished status with result", () => {
    const result: GameResult = {
      outcome: "win",
      winner: "X",
      condition: "three_in_row",
      final_scores: { X: 1, O: 0 },
    };
    const state: GameState = {
      game_id: "done-1",
      schema_ref: "tic-tac-toe.json",
      sequence: 5,
      status: "finished",
      result,
      turn: "",
      phase: "end",
      zones: {},
      players: {},
    };
    assert.equal(state.result!.outcome, "win");
    assert.equal(state.result!.winner, "X");
  });

  it("ZoneState discriminated union works", () => {
    const grid: ZoneState = { zone_type: "grid", cells: {} };
    const stack: ZoneState = { zone_type: "ordered_stack", components: [] };
    const set: ZoneState = { zone_type: "set", components: [] };
    const slot: ZoneState = { zone_type: "single_slot" };
    const counter: ZoneState = { zone_type: "counter", value: 42 };
    const track: ZoneState = { zone_type: "track", positions: {} };

    assert.equal(grid.zone_type, "grid");
    assert.equal(stack.zone_type, "ordered_stack");
    assert.equal(set.zone_type, "set");
    assert.equal(slot.zone_type, "single_slot");
    assert.equal(counter.zone_type, "counter");
    assert.equal(track.zone_type, "track");
  });

  it("GridState accepts component arrays in cells", () => {
    const grid: GridState = {
      zone_type: "grid",
      cells: {
        "0,0": { id: "piece_1", component_type: "pawn" },
        "0,1": [
          { id: "chip_1", component_type: "chip" },
          { id: "chip_2", component_type: "chip" },
        ],
        "0,2": null,
      },
    };
    assert.equal(grid.zone_type, "grid");
  });

  it("StackState accepts optional count", () => {
    const stack: StackState = {
      zone_type: "ordered_stack",
      components: [
        { id: "card_1", component_type: "card", facing: "face_down" },
      ],
      count: 52,
    };
    assert.equal(stack.count, 52);
  });

  it("SetState accepts components", () => {
    const set: SetState = {
      zone_type: "set",
      components: [
        { id: "tile_1", component_type: "tile" },
        { id: "tile_2", component_type: "tile" },
      ],
    };
    assert.equal(set.components.length, 2);
  });

  it("SlotState accepts optional component", () => {
    const empty: SlotState = { zone_type: "single_slot" };
    const filled: SlotState = {
      zone_type: "single_slot",
      component: { id: "king_1", component_type: "king" },
    };
    const cleared: SlotState = {
      zone_type: "single_slot",
      component: null,
    };
    assert.equal(empty.component, undefined);
    assert.notEqual(filled.component, null);
    assert.equal(cleared.component, null);
  });

  it("TrackState accepts positions map", () => {
    const track: TrackState = {
      zone_type: "track",
      positions: {
        "0": [{ id: "token_1", component_type: "token" }],
        "5": [
          { id: "token_2", component_type: "token" },
          { id: "token_3", component_type: "token" },
        ],
      },
    };
    assert.equal(track.positions["0"]!.length, 1);
  });

  it("CounterState stores a value", () => {
    const counter: CounterState = {
      zone_type: "counter",
      value: 42,
    };
    assert.equal(counter.value, 42);
  });

  it("Action accepts movement actions", () => {
    const actions: Action[] = [
      { action_type: "move_piece", from: "e2", to: "e4", component_id: "pawn_1" },
      { action_type: "place", to: "0,0", component_type: "X_piece" },
      { action_type: "castle", side: "kingside" },
      { action_type: "fold" },
      { action_type: "raise", amount: 50 },
      { action_type: "place_ship", orientation: "horizontal", to: "A1" },
      { action_type: "fire", to: "B3" },
      { action_type: "draw", zone: "deck", count: 2 },
      { action_type: "pass" },
      { action_type: "resign" },
    ];
    assert.equal(actions.length, 10);
  });

  it("Action accepts object-form positions", () => {
    const action: Action = {
      action_type: "move_piece",
      from: { zone: "board", cell: "0,0", index: 0 },
      to: { zone: "board", cell: "1,1" },
    };
    assert.equal(action.action_type, "move_piece");
  });

  it("Action accepts custom action with custom_data", () => {
    const action: Action = {
      action_type: "custom",
      custom_data: { nonce: "xyz", value: 42 },
    };
    assert.equal(action.action_type, "custom");
    assert.equal(action.custom_data!["nonce"], "xyz");
  });

  it("ComponentInstance accepts all fields", () => {
    const card: ComponentInstance = {
      id: "card_14",
      component_type: "card",
      owner: "player1",
      facing: "face_up",
      state: "tapped",
      properties: { suit: "hearts", rank: "ace" },
    };
    assert.equal(card.properties!["suit"], "hearts");
    assert.equal(card.state, "tapped");
  });

  it("PlayerState accepts all optional fields", () => {
    const player: PlayerState = {
      user_id: "user-123",
      seat: "north",
      active: true,
      connected: true,
      score: 42,
      counters: { coins: 10, lives: 3 },
      zones: {
        hand: { zone_type: "set", components: [] },
      },
      clock: {
        remaining_ms: 300000,
        increment_ms: 5000,
        running: true,
      },
    };
    assert.equal(player.score, 42);
    assert.equal(player.clock!.remaining_ms, 300000);
    assert.equal(player.counters!["coins"], 10);
  });

  it("PendingAction has required fields", () => {
    const pa: PendingAction = {
      player: "player1",
      action_type: "bet",
      submitted: true,
    };
    assert.equal(pa.player, "player1");
    assert.equal(pa.submitted, true);
  });

  it("ClientMessage includes all fields", () => {
    const msg: ClientMessage = {
      message_type: "submit_move",
      game_id: "game-1",
      player: "player1",
      sequence: 5,
      action: { action_type: "place", to: "0,0" },
      state_hash: "abc123",
    };
    assert.equal(msg.message_type, "submit_move");
    assert.equal(msg.player, "player1");
  });

  it("ClientMessage with random_request", () => {
    const req: RandomRequest = {
      random_type: "roll",
      dice_type: "d6",
      dice_count: 2,
    };
    const msg: ClientMessage = {
      message_type: "request_random",
      game_id: "game-1",
      player: "player1",
      random_request: req,
    };
    assert.equal(msg.random_request!.random_type, "roll");
  });

  it("RandomRequest accepts all variants", () => {
    const roll: RandomRequest = { random_type: "roll", dice_type: "d20", dice_count: 1 };
    const draw: RandomRequest = { random_type: "draw", draw_from: "deck", draw_count: 5 };
    const shuffle: RandomRequest = { random_type: "shuffle", shuffle_zone: "deck" };
    assert.equal(roll.random_type, "roll");
    assert.equal(draw.draw_from, "deck");
    assert.equal(shuffle.shuffle_zone, "deck");
  });

  it("ServerMessage accepts all message types", () => {
    const welcome: ServerMessage = {
      message_type: "welcome",
      game_id: "g1",
      token: "tok_123",
      seat: "player1",
      server_version: "0.1.0",
      protocol_version: 1,
    };
    const confirmed: ServerMessage = {
      message_type: "move_confirmed",
      game_id: "g1",
      sequence: 5,
      action: { action_type: "place", to: "0,0" },
    };
    const rejected: ServerMessage = {
      message_type: "move_rejected",
      game_id: "g1",
      reason: "Not your turn",
    };
    assert.equal(welcome.message_type, "welcome");
    assert.equal(confirmed.sequence, 5);
    assert.equal(rejected.reason, "Not your turn");
  });

  it("Fact accepts all optional fields", () => {
    const fact: Fact = {
      fact_type: "component_identity",
      component_id: "card_3",
      zone: "hand",
      position: "0",
      properties: { suit: "hearts" },
      previous_visibility: "hidden",
      new_visibility: "public",
    };
    assert.equal(fact.fact_type, "component_identity");
    assert.equal(fact.previous_visibility, "hidden");
  });

  it("GameDefinition accepts required fields", () => {
    const def: GameDefinition = {
      game: { name: "Tic-Tac-Toe", players: ["X", "O"] },
      zones: {
        board: {
          zone_type: "grid",
          visibility: "public",
          dimensions: [3, 3],
        },
      },
      components: {
        X_piece: { owner: "per_player", count: 5 },
      },
      turn_order: { type: "alternating" },
      end_conditions: [
        { result: "win", condition: "three_in_row" },
        { result: "draw", condition: "board_full" },
      ],
      authority: {
        server_only: ["random"],
        client_verifiable: ["move_validation"],
      },
    };
    assert.equal(def.game.name, "Tic-Tac-Toe");
    assert.equal(def.end_conditions.length, 2);
  });

  it("GameDefinition accepts optional fields", () => {
    const def: GameDefinition = {
      game: { name: "Poker", players: { min: 2, max: 10 }, information: "imperfect" },
      zones: {},
      components: {},
      turn_order: { type: "round_robin", players: ["p1", "p2"] },
      phases: [{ name: "deal" }, { name: "betting", simultaneous: false }],
      rules: {
        fold_rule: { action: "fold", constraint: "player_has_cards" },
      },
      end_conditions: [],
      authority: { server_only: [], client_verifiable: [] },
      wasm_module: "poker.wasm",
      hand_rankings: ["royal_flush", "straight_flush", "four_of_a_kind"],
      betting_round: { actions: ["fold", "call", "raise"], ends_when: "all_called" },
    };
    assert.equal(def.game.information, "imperfect");
    assert.equal(def.wasm_module, "poker.wasm");
  });

  it("Zone accepts all optional fields", () => {
    const zone: Zone = {
      zone_type: "grid",
      visibility: "public",
      per_player: false,
      capacity: "unlimited",
      dimensions: [8, 8],
      labels: {
        files: ["a", "b", "c", "d", "e", "f", "g", "h"],
        ranks: [1, 2, 3, 4, 5, 6, 7, 8],
      },
      coloring: "checkerboard",
      adjacency: "orthogonal_8",
    };
    assert.equal(zone.zone_type, "grid");
    assert.equal(zone.labels!.files!.length, 8);
  });

  it("Movement accepts all fields", () => {
    const move: Movement = {
      primitive: "slide",
      direction: "diagonal",
      distance: 7,
      dx: 1,
      dy: 1,
      target_zone: "board",
      condition: "path_clear",
      repeat: { min: 1, max: 7 },
      after: ["capture"],
      side: "kingside",
      over: 1,
    };
    assert.equal(move.primitive, "slide");
    assert.equal(move.direction, "diagonal");
  });

  it("EndCondition accepts all fields", () => {
    const ec: EndCondition = {
      result: "win",
      player: "current",
      condition: "checkmate",
      name: "Checkmate",
    };
    assert.equal(ec.result, "win");
    assert.equal(ec.name, "Checkmate");
  });

  it("ActionType union covers all variants including commit/reveal", () => {
    const types: ActionType[] = [
      "move_piece", "place", "draw", "play_card", "discard",
      "roll_dice", "flip", "promote", "swap", "remove",
      "pass", "resign", "offer_draw", "accept_draw", "decline_draw",
      "fold", "check", "call", "raise", "all_in",
      "place_ship", "fire", "castle", "en_passant",
      "declare_action", "commit", "reveal", "custom",
    ];
    assert.equal(types.length, 28);
  });

  it("Action accepts commit/reveal with commitment field", () => {
    const commit: Action = {
      action_type: "commit",
      commitment: "sha256:abc123",
    };
    const reveal: Action = {
      action_type: "reveal",
      commitment: "rock",
      custom_data: { nonce: "xyz" },
    };
    assert.equal(commit.commitment, "sha256:abc123");
    assert.equal(reveal.action_type, "reveal");
  });

  it("GraphState accepts occupants and node_properties", () => {
    const graph: GraphState = {
      zone_type: "graph",
      occupants: {
        node_a: [{ id: "piece_1", component_type: "token" }],
        node_b: [],
      },
      node_properties: {
        node_a: { terrain: "mountain", elevation: 3 },
      },
    };
    assert.equal(graph.zone_type, "graph");
    assert.equal(graph.occupants["node_a"]!.length, 1);
  });

  it("GameState accepts pending_commits and simultaneous_actions", () => {
    const state: GameState = {
      game_id: "rps-1",
      schema_ref: "rock-paper-scissors.json",
      sequence: 1,
      status: "in_progress",
      turn: "",
      phase: "choose",
      zones: {},
      players: {},
      pending_commits: { player1: "sha256:abc", player2: "sha256:def" },
      simultaneous_actions: { player1: { action_type: "commit" } },
    };
    assert.equal(state.pending_commits!["player1"], "sha256:abc");
  });

  it("GridState accepts cell_properties", () => {
    const grid: GridState = {
      zone_type: "grid",
      cells: {},
      cell_properties: {
        "0,0": { terrain: "mountain", elevation: 3 },
      },
    };
    assert.equal(grid.cell_properties!["0,0"]!["terrain"], "mountain");
  });

  it("GameEvent has required hash chain fields", () => {
    const event: GameEvent = {
      game_id: "game-1",
      sequence: 0,
      event_type: "move_applied",
      player: "X",
      state_hash: "a".repeat(64),
      prev_hash: "0".repeat(64),
      event_hash: "b".repeat(64),
      payload: {
        action: "place",
        to: "0,0",
        component_id: "x_0",
      },
    };
    assert.equal(event.sequence, 0);
    assert.equal(event.prev_hash.length, 64);
  });

  it("RegistryEntry accepts card deck shape", () => {
    const deck: RegistryEntry = {
      id: "standard:french-52",
      component_type: "card_deck",
      name: "Standard 52-card deck",
      suits: ["hearts", "diamonds", "clubs", "spades"],
      suit_symbols: ["\u2665", "\u2666", "\u2663", "\u2660"],
      suit_colors: { hearts: "red", diamonds: "red", clubs: "black", spades: "black" },
      ranks: ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"],
      rank_values: { A: [1, 14], J: 11, Q: 12, K: 13 },
    };
    assert.equal(deck.suits!.length, 4);
    assert.equal(deck.ranks!.length, 13);
  });

  it("GameDefinition accepts library and notation", () => {
    const def: GameDefinition = {
      game: { name: "Test", players: ["p1", "p2"] },
      zones: {},
      components: {},
      turn_order: { type: "alternating" },
      end_conditions: [],
      authority: { server_only: [], client_verifiable: [] },
      library: {
        three_in_line: { expression: "check_line(board, 3)" },
      },
      notation: {
        piece_symbols: { king: "K", queen: "Q" },
        capture_marker: "x",
      },
    };
    assert.equal(def.library!["three_in_line"]!.expression, "check_line(board, 3)");
  });
});
