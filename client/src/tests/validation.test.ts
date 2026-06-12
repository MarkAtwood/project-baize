import { describe, it } from "node:test";
import { strict as assert } from "node:assert";
import { validateServerMessage } from "../validation.js";

describe("validateServerMessage", () => {
  // -------------------------------------------------------------------
  // Basic rejection
  // -------------------------------------------------------------------

  it("rejects non-objects", () => {
    assert.equal(validateServerMessage(null), null);
    assert.equal(validateServerMessage(undefined), null);
    assert.equal(validateServerMessage("string"), null);
    assert.equal(validateServerMessage(42), null);
    assert.equal(validateServerMessage([]), null);
  });

  it("rejects missing message_type", () => {
    assert.equal(validateServerMessage({ game_id: "g1" }), null);
  });

  it("rejects unknown message_type", () => {
    assert.equal(
      validateServerMessage({ message_type: "unknown", game_id: "g1" }),
      null,
    );
  });

  it("rejects missing game_id", () => {
    assert.equal(
      validateServerMessage({ message_type: "move_confirmed" }),
      null,
    );
  });

  it("rejects oversized game_id", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "g".repeat(11_000),
      }),
      null,
    );
  });

  it("rejects oversized strings", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_rejected",
        game_id: "game-1",
        reason: "x".repeat(11_000),
      }),
      null,
    );
  });

  it("rejects non-finite sequence (Infinity)", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        sequence: Infinity,
      }),
      null,
    );
  });

  it("rejects non-finite sequence (NaN)", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        sequence: NaN,
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // Prototype pollution
  // -------------------------------------------------------------------

  it("rejects prototype pollution via __proto__", () => {
    const malicious = Object.create(null) as Record<string, unknown>;
    malicious["__proto__"] = { admin: true };
    malicious["message_type"] = "welcome";
    malicious["game_id"] = "g1";
    assert.equal(validateServerMessage(malicious), null);
  });

  it("strips unknown fields from message", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      malicious_field: "evil",
    });
    assert.notEqual(msg, null);
    assert.equal(
      "malicious_field" in (msg as unknown as Record<string, unknown>),
      false,
    );
  });

  // -------------------------------------------------------------------
  // Message types
  // -------------------------------------------------------------------

  it("accepts minimal valid messages for each type", () => {
    for (const msgType of [
      "welcome",
      "move_confirmed",
      "move_rejected",
      "random_result",
      "reveal",
    ]) {
      const msg = validateServerMessage({
        message_type: msgType,
        game_id: "g1",
      });
      assert.notEqual(msg, null, `${msgType} should be accepted`);
      assert.equal(msg!.message_type, msgType);
    }
  });

  it("accepts valid move_confirmed", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 5,
      action: { action_type: "move_piece", from: "e2", to: "e4" },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.message_type, "move_confirmed");
    assert.equal(msg!.sequence, 5);
  });

  it("accepts valid move_rejected", () => {
    const msg = validateServerMessage({
      message_type: "move_rejected",
      game_id: "game-1",
      reason: "Not your turn",
      action: { action_type: "place", to: "0,0" },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.reason, "Not your turn");
  });

  // -------------------------------------------------------------------
  // Welcome message fields
  // -------------------------------------------------------------------

  it("accepts welcome with token, seat, server_version, protocol_version", () => {
    const msg = validateServerMessage({
      message_type: "welcome",
      game_id: "game-1",
      token: "abc123",
      seat: "player1",
      server_version: "0.1.0",
      protocol_version: 1,
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.token, "abc123");
    assert.equal(msg!.seat, "player1");
    assert.equal(msg!.server_version, "0.1.0");
    assert.equal(msg!.protocol_version, 1);
  });

  it("rejects welcome with non-string token", () => {
    assert.equal(
      validateServerMessage({
        message_type: "welcome",
        game_id: "game-1",
        token: 42,
      }),
      null,
    );
  });

  it("rejects welcome with non-finite protocol_version", () => {
    assert.equal(
      validateServerMessage({
        message_type: "welcome",
        game_id: "game-1",
        protocol_version: NaN,
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // Action validation
  // -------------------------------------------------------------------

  it("accepts action with string fields", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: {
        action_type: "castle",
        side: "kingside",
        component_id: "king_1",
      },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.action!.action_type, "castle");
  });

  it("accepts action with commitment field", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: {
        action_type: "commit",
        commitment: "sha256:abc123",
      },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.action!.commitment, "sha256:abc123");
  });

  it("accepts action with numeric fields", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: { action_type: "raise", amount: 50, count: 2 },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.action!.amount, 50);
  });

  it("rejects action with missing action_type", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        action: { from: "e2", to: "e4" },
      }),
      null,
    );
  });

  it("rejects action with non-string action_type", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        action: { action_type: 42 },
      }),
      null,
    );
  });

  it("strips unknown fields from action", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: {
        action_type: "move_piece",
        from: "e2",
        to: "e4",
        hack_field: "evil",
      },
    });
    assert.notEqual(msg, null);
    assert.equal(
      "hack_field" in (msg!.action as unknown as Record<string, unknown>),
      false,
    );
  });

  it("accepts action with custom_data object", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: {
        action_type: "custom",
        custom_data: { nonce: "xyz", value: 42 },
      },
    });
    assert.notEqual(msg, null);
    assert.deepEqual(msg!.action!.custom_data, { nonce: "xyz", value: 42 });
  });

  it("rejects action with non-object custom_data", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        action: { action_type: "custom", custom_data: "not-an-object" },
      }),
      null,
    );
  });

  it("accepts action with object-form position", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "game-1",
      sequence: 1,
      action: {
        action_type: "move_piece",
        from: { zone: "board", cell: "0,0" },
        to: { zone: "board", cell: "1,1" },
      },
    });
    assert.notEqual(msg, null);
  });

  it("rejects action with non-string/non-object position", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        action: { action_type: "move_piece", from: 42, to: "e4" },
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // Reveal / facts
  // -------------------------------------------------------------------

  it("accepts valid reveal", () => {
    const msg = validateServerMessage({
      message_type: "reveal",
      game_id: "game-1",
      reveal_to: "player1",
      facts: [
        {
          fact_type: "component_identity",
          component_id: "card_3",
          properties: { suit: "hearts", rank: "ace" },
          previous_visibility: "hidden",
          new_visibility: "public",
        },
      ],
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.facts!.length, 1);
  });

  it("rejects facts with missing fact_type", () => {
    assert.equal(
      validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: [{ component_id: "c1" }],
      }),
      null,
    );
  });

  it("rejects facts with non-object entries", () => {
    assert.equal(
      validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: ["not-an-object"],
      }),
      null,
    );
  });

  it("rejects non-array facts", () => {
    assert.equal(
      validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: "not-an-array",
      }),
      null,
    );
  });

  it("accepts facts with position as string or object", () => {
    for (const position of ["0,0", { zone: "board", cell: "1,1" }]) {
      const msg = validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: [{ fact_type: "component_position", position }],
      });
      assert.notEqual(msg, null);
    }
  });

  it("rejects facts with non-string/non-object position", () => {
    assert.equal(
      validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: [{ fact_type: "component_position", position: 42 }],
      }),
      null,
    );
  });

  it("rejects facts with non-object properties", () => {
    assert.equal(
      validateServerMessage({
        message_type: "reveal",
        game_id: "game-1",
        facts: [{ fact_type: "id", properties: "not-an-object" }],
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // Random result
  // -------------------------------------------------------------------

  it("accepts random_value as number, string, array, or object", () => {
    for (const random_value of [6, "ace_of_spades", [3, 5], { order: [1, 2] }]) {
      const msg = validateServerMessage({
        message_type: "random_result",
        game_id: "game-1",
        random_type: "roll",
        random_value,
      });
      assert.notEqual(msg, null);
    }
  });

  it("rejects random_value as boolean", () => {
    assert.equal(
      validateServerMessage({
        message_type: "random_result",
        game_id: "game-1",
        random_type: "roll",
        random_value: true,
      }),
      null,
    );
  });

  it("rejects non-finite random_value number", () => {
    assert.equal(
      validateServerMessage({
        message_type: "random_result",
        game_id: "game-1",
        random_type: "roll",
        random_value: Infinity,
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // State sync / GameState validation
  // -------------------------------------------------------------------

  it("accepts valid state_sync", () => {
    const msg = validateServerMessage({
      message_type: "state_sync",
      game_id: "game-1",
      sequence: 3,
      full_state: {
        game_id: "game-1",
        schema_ref: "tic-tac-toe",
        sequence: 3,
        status: "in_progress",
        turn: "X",
        phase: "play",
        zones: {},
        players: {},
      },
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.message_type, "state_sync");
  });

  it("rejects full_state with invalid status", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: {
          game_id: "g1",
          schema_ref: "t",
          sequence: 1,
          status: "invalid_status",
          turn: "p1",
          phase: "main",
          zones: {},
          players: {},
        },
      }),
      null,
    );
  });

  it("rejects full_state with non-object zones", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: {
          game_id: "g1",
          schema_ref: "t",
          sequence: 1,
          status: "in_progress",
          turn: "p1",
          phase: "main",
          zones: "not-an-object",
          players: {},
        },
      }),
      null,
    );
  });

  it("rejects full_state with missing required fields", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: { game_id: "g1", schema_ref: "t" },
      }),
      null,
    );
  });

  it("accepts full_state with optional numeric fields", () => {
    const msg = validateServerMessage({
      message_type: "state_sync",
      game_id: "game-1",
      full_state: {
        game_id: "game-1",
        schema_ref: "chess",
        sequence: 10,
        status: "in_progress",
        turn: "white",
        phase: "main",
        zones: {},
        players: {},
        move_count: 5,
        halfmove_clock: 3,
      },
    });
    assert.notEqual(msg, null);
    const state = msg!.full_state as unknown as Record<string, unknown>;
    assert.equal(state["move_count"], 5);
    assert.equal(state["halfmove_clock"], 3);
  });

  it("rejects full_state with non-finite numeric fields", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: {
          game_id: "g1",
          schema_ref: "t",
          sequence: 1,
          status: "in_progress",
          turn: "p1",
          phase: "main",
          zones: {},
          players: {},
          move_count: NaN,
        },
      }),
      null,
    );
  });

  // -------------------------------------------------------------------
  // State: counters, pending_actions, pending_commits, simultaneous
  // -------------------------------------------------------------------

  it("accepts state with counters", () => {
    const msg = validateServerMessage({
      message_type: "state_sync",
      game_id: "game-1",
      full_state: {
        game_id: "game-1",
        schema_ref: "poker",
        sequence: 10,
        status: "in_progress",
        turn: "player1",
        phase: "betting",
        zones: {},
        players: {},
        counters: { pot: 100, round: 2 },
      },
    });
    assert.notEqual(msg, null);
    const state = msg!.full_state as unknown as Record<string, unknown>;
    const counters = state["counters"] as Record<string, number>;
    assert.equal(counters["pot"], 100);
  });

  it("rejects state with non-object counters", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: {
          game_id: "g1",
          schema_ref: "t",
          sequence: 1,
          status: "in_progress",
          turn: "p1",
          phase: "main",
          zones: {},
          players: {},
          counters: "not-an-object",
        },
      }),
      null,
    );
  });

  it("accepts state with valid pending_actions", () => {
    const msg = validateServerMessage({
      message_type: "state_sync",
      game_id: "game-1",
      full_state: {
        game_id: "game-1",
        schema_ref: "poker",
        sequence: 5,
        status: "in_progress",
        turn: "p1",
        phase: "betting",
        zones: {},
        players: {},
        pending_actions: [
          { player: "p2", action_type: "call" },
        ],
      },
    });
    assert.notEqual(msg, null);
  });

  it("rejects state with invalid pending_actions entries", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: {
          game_id: "g1",
          schema_ref: "t",
          sequence: 1,
          status: "in_progress",
          turn: "p1",
          phase: "main",
          zones: {},
          players: {},
          pending_actions: [{ invalid: true }],
        },
      }),
      null,
    );
  });

  it("accepts state with pending_commits and simultaneous_actions", () => {
    const msg = validateServerMessage({
      message_type: "state_sync",
      game_id: "game-1",
      full_state: {
        game_id: "game-1",
        schema_ref: "rps",
        sequence: 1,
        status: "in_progress",
        turn: "",
        phase: "choose",
        zones: {},
        players: {},
        pending_commits: { p1: "sha256:abc", p2: "sha256:def" },
        simultaneous_actions: { p1: { action_type: "commit" } },
      },
    });
    assert.notEqual(msg, null);
  });

  // -------------------------------------------------------------------
  // Edge cases
  // -------------------------------------------------------------------

  it("accepts empty game_id string", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "",
    });
    assert.notEqual(msg, null);
  });

  it("accepts sequence of zero", () => {
    const msg = validateServerMessage({
      message_type: "move_confirmed",
      game_id: "g1",
      sequence: 0,
    });
    assert.notEqual(msg, null);
    assert.equal(msg!.sequence, 0);
  });

  it("rejects non-string reason", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_rejected",
        game_id: "game-1",
        reason: 42,
      }),
      null,
    );
  });

  it("rejects non-object result_state", () => {
    assert.equal(
      validateServerMessage({
        message_type: "move_confirmed",
        game_id: "game-1",
        result_state: "not-an-object",
      }),
      null,
    );
  });

  it("rejects non-object full_state", () => {
    assert.equal(
      validateServerMessage({
        message_type: "state_sync",
        game_id: "game-1",
        full_state: "not-an-object",
      }),
      null,
    );
  });
});
