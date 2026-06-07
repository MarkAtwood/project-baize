/**
 * WebSocket connection manager for the Baize game server.
 *
 * Handles the client<->server protocol defined in move-action.schema.json:
 *   Client -> Server: submit_move, request_random, acknowledge_state
 *   Server -> Client: move_confirmed, move_rejected, random_result, reveal, state_sync
 *
 * Provides auto-reconnect with state_sync on reconnection.
 */

import type {
  Action,
  ClientMessage,
  RandomRequest,
  ServerMessage,
  ServerMessageType,
} from "./types.js";

export type ConnectionStatus = "disconnected" | "connecting" | "connected";

export type ServerMessageHandler = (message: ServerMessage) => void;
export type StatusChangeHandler = (status: ConnectionStatus) => void;

export interface ConnectionOptions {
  /** Maximum reconnect attempts before giving up (0 = unlimited). */
  readonly maxReconnectAttempts?: number;
  /** Base delay in ms between reconnect attempts (doubles each attempt). */
  readonly reconnectBaseDelay?: number;
  /** Maximum delay in ms between reconnect attempts. */
  readonly reconnectMaxDelay?: number;
}

const DEFAULT_OPTIONS: Required<ConnectionOptions> = {
  maxReconnectAttempts: 0,
  reconnectBaseDelay: 1000,
  reconnectMaxDelay: 30000,
};

export class BaizeConnection {
  private ws: WebSocket | null = null;
  private serverUrl: string;
  private gameId: string;
  private player: string;
  private currentSequence = 0;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private readonly options: Required<ConnectionOptions>;

  private readonly messageHandlers = new Map<
    ServerMessageType,
    Set<ServerMessageHandler>
  >();
  private readonly statusHandlers = new Set<StatusChangeHandler>();

  private _status: ConnectionStatus = "disconnected";

  constructor(
    serverUrl: string,
    gameId: string,
    player: string,
    options?: ConnectionOptions,
  ) {
    this.serverUrl = serverUrl;
    this.gameId = gameId;
    this.player = player;
    this.options = { ...DEFAULT_OPTIONS, ...options };
  }

  get status(): ConnectionStatus {
    return this._status;
  }

  /** Subscribe to a specific server message type. */
  on(type: ServerMessageType, handler: ServerMessageHandler): void {
    let handlers = this.messageHandlers.get(type);
    if (handlers === undefined) {
      handlers = new Set();
      this.messageHandlers.set(type, handlers);
    }
    handlers.add(handler);
  }

  /** Unsubscribe from a server message type. */
  off(type: ServerMessageType, handler: ServerMessageHandler): void {
    this.messageHandlers.get(type)?.delete(handler);
  }

  /** Subscribe to connection status changes. */
  onStatusChange(handler: StatusChangeHandler): void {
    this.statusHandlers.add(handler);
  }

  /** Unsubscribe from status changes. */
  offStatusChange(handler: StatusChangeHandler): void {
    this.statusHandlers.delete(handler);
  }

  /** Open the WebSocket connection. */
  connect(): void {
    if (this.ws !== null) return;
    this.intentionalClose = false;
    this.setStatus("connecting");

    this.ws = new WebSocket(this.serverUrl);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus("connected");
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    this.ws.onclose = () => {
      this.ws = null;
      this.setStatus("disconnected");
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onerror is always followed by onclose; just let onclose handle it.
    };
  }

  /** Gracefully close the connection. */
  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.setStatus("disconnected");
  }

  /** Submit a move action to the server. */
  submitMove(action: Action): void {
    const msg: ClientMessage = {
      message_type: "submit_move",
      game_id: this.gameId,
      player: this.player,
      sequence: this.currentSequence,
      action,
    };
    this.send(msg);
  }

  /** Request server-side randomness (dice roll, card draw, shuffle). */
  requestRandom(request: RandomRequest): void {
    const msg: ClientMessage = {
      message_type: "request_random",
      game_id: this.gameId,
      player: this.player,
      random_request: request,
    };
    this.send(msg);
  }

  /** Acknowledge current state with a hash for desync detection. */
  acknowledgeState(stateHash: string): void {
    const msg: ClientMessage = {
      message_type: "acknowledge_state",
      game_id: this.gameId,
      player: this.player,
      sequence: this.currentSequence,
      state_hash: stateHash,
    };
    this.send(msg);
  }

  /** Update the tracked sequence number (called when state changes). */
  updateSequence(sequence: number): void {
    this.currentSequence = sequence;
  }

  private send(msg: ClientMessage): void {
    if (this.ws === null || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("BaizeConnection: not connected");
    }
    this.ws.send(JSON.stringify(msg));
  }

  private handleMessage(event: MessageEvent): void {
    const data = event.data;
    if (typeof data !== "string") return;

    let msg: ServerMessage;
    try {
      msg = JSON.parse(data) as ServerMessage;
    } catch {
      return;
    }

    if (msg.sequence !== undefined) {
      this.currentSequence = msg.sequence;
    }

    const handlers = this.messageHandlers.get(msg.message_type);
    if (handlers !== undefined) {
      for (const handler of handlers) {
        handler(msg);
      }
    }
  }

  private setStatus(status: ConnectionStatus): void {
    if (this._status === status) return;
    this._status = status;
    for (const handler of this.statusHandlers) {
      handler(status);
    }
  }

  private scheduleReconnect(): void {
    const { maxReconnectAttempts, reconnectBaseDelay, reconnectMaxDelay } =
      this.options;

    if (maxReconnectAttempts > 0 && this.reconnectAttempts >= maxReconnectAttempts) {
      return;
    }

    const delay = Math.min(
      reconnectBaseDelay * 2 ** this.reconnectAttempts,
      reconnectMaxDelay,
    );
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}
