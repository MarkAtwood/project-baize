/**
 * Server message validation — defense-in-depth for untrusted server data.
 *
 * Validates structure, types, and value ranges of incoming ServerMessage
 * payloads before they are used by the rest of the client. Returns null
 * for any message that fails validation (never throws on bad input).
 */

import type { ServerMessage, ServerMessageType } from "./types.js";

/** Maximum allowed length for any single string field. */
const MAX_STRING_LENGTH = 10_240; // 10 KB

/** Known server message types. */
const KNOWN_MESSAGE_TYPES: ReadonlySet<string> = new Set<ServerMessageType>([
  "move_confirmed",
  "move_rejected",
  "random_result",
  "reveal",
  "state_sync",
]);

/**
 * Validate and sanitize a raw parsed JSON value as a ServerMessage.
 *
 * Returns a cleaned ServerMessage with only known fields, or null if
 * the data is structurally invalid. Never throws on bad input.
 */
export function validateServerMessage(data: unknown): ServerMessage | null {
  try {
    if (!isPlainObject(data)) return null;

    // message_type: required, must be a known type
    const messageType = data["message_type"];
    if (typeof messageType !== "string") return null;
    if (!KNOWN_MESSAGE_TYPES.has(messageType)) return null;

    // game_id: required string
    const gameId = data["game_id"];
    if (typeof gameId !== "string") return null;
    if (!isReasonableString(gameId)) return null;

    // Build a clean message with only known fields
    const msg: Record<string, unknown> = {
      message_type: messageType as ServerMessageType,
      game_id: gameId,
    };

    // sequence: optional finite number
    if ("sequence" in data && data["sequence"] !== undefined) {
      if (!isFiniteNumber(data["sequence"])) return null;
      msg["sequence"] = data["sequence"];
    }

    // reason: optional bounded string
    if ("reason" in data && data["reason"] !== undefined) {
      if (typeof data["reason"] !== "string") return null;
      if (!isReasonableString(data["reason"])) return null;
      msg["reason"] = data["reason"];
    }

    // random_type: optional bounded string
    if ("random_type" in data && data["random_type"] !== undefined) {
      if (typeof data["random_type"] !== "string") return null;
      if (!isReasonableString(data["random_type"])) return null;
      msg["random_type"] = data["random_type"];
    }

    // random_value: optional (number | string | array | object)
    if ("random_value" in data && data["random_value"] !== undefined) {
      const rv = data["random_value"];
      if (typeof rv === "number") {
        if (!isFiniteNumber(rv)) return null;
        msg["random_value"] = rv;
      } else if (typeof rv === "string") {
        if (!isReasonableString(rv)) return null;
        msg["random_value"] = rv;
      } else if (Array.isArray(rv)) {
        msg["random_value"] = rv;
      } else if (isPlainObject(rv)) {
        msg["random_value"] = rv;
      } else {
        return null;
      }
    }

    // reveal_to: optional bounded string
    if ("reveal_to" in data && data["reveal_to"] !== undefined) {
      if (typeof data["reveal_to"] !== "string") return null;
      if (!isReasonableString(data["reveal_to"])) return null;
      msg["reveal_to"] = data["reveal_to"];
    }

    // action: optional object (validated as plain object only)
    if ("action" in data && data["action"] !== undefined) {
      if (!isPlainObject(data["action"])) return null;
      const validatedAction = validateAction(data["action"]);
      if (validatedAction === null) return null;
      msg["action"] = validatedAction;
    }

    // result_state: optional plain object
    if ("result_state" in data && data["result_state"] !== undefined) {
      if (!isPlainObject(data["result_state"])) return null;
      msg["result_state"] = data["result_state"];
    }

    // facts: optional array of objects
    if ("facts" in data && data["facts"] !== undefined) {
      if (!Array.isArray(data["facts"])) return null;
      const validatedFacts = validateFacts(data["facts"]);
      if (validatedFacts === null) return null;
      msg["facts"] = validatedFacts;
    }

    // full_state: optional plain object (GameState)
    if ("full_state" in data && data["full_state"] !== undefined) {
      if (!isPlainObject(data["full_state"])) return null;
      const validatedState = validateGameState(data["full_state"]);
      if (validatedState === null) return null;
      msg["full_state"] = validatedState;
    }

    // Return as ServerMessage — only known fields were copied above,
    // so any unknown/extra fields from the wire are stripped.
    return msg as unknown as ServerMessage;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Internal validators
// ---------------------------------------------------------------------------

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || value === undefined) return false;
  if (typeof value !== "object") return false;
  if (Array.isArray(value)) return false;
  // Defense against prototype pollution: reject objects with __proto__ or
  // constructor properties that could tamper with the prototype chain.
  const obj = value as Record<string, unknown>;
  if ("__proto__" in obj) return false;
  if ("constructor" in obj && obj["constructor"] !== Object) return false;
  return true;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isReasonableString(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_STRING_LENGTH;
}

function validateAction(
  data: Record<string, unknown>,
): Record<string, unknown> | null {
  // action_type is required
  if (typeof data["action_type"] !== "string") return null;
  if (!isReasonableString(data["action_type"])) return null;

  // Build a clean action object with only known fields
  const action: Record<string, unknown> = {
    action_type: data["action_type"],
  };

  const optionalStrings = [
    "authority",
    "component_id",
    "component_type",
    "zone",
    "promote_to",
    "orientation",
    "dice_type",
    "swap_with",
    "declaration",
    "side",
  ] as const;

  for (const field of optionalStrings) {
    if (field in data && data[field] !== undefined) {
      if (typeof data[field] !== "string") return null;
      if (!isReasonableString(data[field])) return null;
      action[field] = data[field];
    }
  }

  const optionalNumbers = [
    "count",
    "amount",
    "rotation",
    "dice_count",
  ] as const;

  for (const field of optionalNumbers) {
    if (field in data && data[field] !== undefined) {
      if (!isFiniteNumber(data[field])) return null;
      action[field] = data[field];
    }
  }

  // from/to: string or object
  for (const field of ["from", "to"] as const) {
    if (field in data && data[field] !== undefined) {
      const pos = data[field];
      if (typeof pos === "string") {
        if (!isReasonableString(pos)) return null;
        action[field] = pos;
      } else if (isPlainObject(pos)) {
        action[field] = pos;
      } else {
        return null;
      }
    }
  }

  // custom_data: optional plain object
  if ("custom_data" in data && data["custom_data"] !== undefined) {
    if (!isPlainObject(data["custom_data"])) return null;
    action["custom_data"] = data["custom_data"];
  }

  return action;
}

function validateFacts(data: readonly unknown[]): readonly unknown[] | null {
  const result: unknown[] = [];
  for (const item of data) {
    if (!isPlainObject(item)) return null;
    if (typeof item["fact_type"] !== "string") return null;
    if (!isReasonableString(item["fact_type"])) return null;
    // Copy only known fact fields
    const fact: Record<string, unknown> = {
      fact_type: item["fact_type"],
    };
    const optionalStrings = [
      "component_id",
      "zone",
      "previous_visibility",
      "new_visibility",
    ] as const;
    for (const field of optionalStrings) {
      if (field in item && item[field] !== undefined) {
        if (typeof item[field] !== "string") return null;
        if (!isReasonableString(item[field])) return null;
        fact[field] = item[field];
      }
    }
    if ("position" in item && item["position"] !== undefined) {
      const pos = item["position"];
      if (typeof pos === "string") {
        if (!isReasonableString(pos)) return null;
        fact["position"] = pos;
      } else if (isPlainObject(pos)) {
        fact["position"] = pos;
      } else {
        return null;
      }
    }
    if ("properties" in item && item["properties"] !== undefined) {
      if (!isPlainObject(item["properties"])) return null;
      fact["properties"] = item["properties"];
    }
    result.push(fact);
  }
  return result;
}

function validateGameState(
  data: Record<string, unknown>,
): Record<string, unknown> | null {
  // Required fields
  if (typeof data["game_id"] !== "string") return null;
  if (!isReasonableString(data["game_id"])) return null;

  if (typeof data["schema_ref"] !== "string") return null;
  if (!isReasonableString(data["schema_ref"])) return null;

  if (!isFiniteNumber(data["sequence"])) return null;

  const validStatuses = new Set(["setup", "in_progress", "finished"]);
  if (typeof data["status"] !== "string") return null;
  if (!validStatuses.has(data["status"])) return null;

  if (typeof data["turn"] !== "string") return null;
  if (!isReasonableString(data["turn"])) return null;

  if (typeof data["phase"] !== "string") return null;
  if (!isReasonableString(data["phase"])) return null;

  if (!isPlainObject(data["zones"])) return null;
  if (!isPlainObject(data["players"])) return null;

  // Validate optional numeric fields
  for (const field of ["move_count", "halfmove_clock"] as const) {
    if (field in data && data[field] !== undefined) {
      if (!isFiniteNumber(data[field])) return null;
    }
  }

  // Validate optional string fields
  for (const field of ["state_hash", "history_hash", "timestamp"] as const) {
    if (field in data && data[field] !== undefined) {
      if (typeof data[field] !== "string") return null;
      if (!isReasonableString(data[field])) return null;
    }
  }

  // Build a clean copy with only known fields — strip unknown properties.
  const state: Record<string, unknown> = {
    game_id: data["game_id"],
    schema_ref: data["schema_ref"],
    sequence: data["sequence"],
    status: data["status"],
    turn: data["turn"],
    phase: data["phase"],
    zones: data["zones"],
    players: data["players"],
  };

  for (const field of ["move_count", "halfmove_clock"] as const) {
    if (field in data && data[field] !== undefined) {
      state[field] = data[field];
    }
  }

  for (const field of [
    "state_hash",
    "history_hash",
    "timestamp",
    "result",
  ] as const) {
    if (field in data && data[field] !== undefined) {
      state[field] = data[field];
    }
  }

  return state;
}
