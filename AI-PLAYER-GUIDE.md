# Baize AI Player Guide

How to read a game definition, connect to a server, and play a game from scratch.

## Quick Start

```python
from baize.agent import Agent

class MyAgent(Agent):
    def choose_action(self, state: dict) -> dict | None:
        moves = state.get("legal_moves", [])
        return moves[0] if moves else None

agent = MyAgent("ws://localhost:8080", "room-id")
agent.play()
```

That's a complete bot. The rest of this document explains what's happening
underneath so you can play well, not just play.

---

## Part 1: Reading a Game Definition

Game definitions are JSON files in `games/`. Here's the smallest complete game
(tic-tac-toe):

```json
{
  "game": {
    "name": "Tic-Tac-Toe",
    "players": ["X", "O"],
    "information": "perfect"
  },
  "zones": {
    "board": {
      "zone_type": "grid",
      "dimensions": [3, 3],
      "visibility": "public"
    }
  },
  "components": {
    "mark": {
      "owner": "per_player",
      "count": "unlimited"
    }
  },
  "turn_order": {
    "type": "alternating",
    "players": ["X", "O"],
    "actions_per_turn": 1,
    "mandatory": true
  },
  "end_conditions": [
    {"result": "win",  "player": "current", "condition": "three_in_a_row"},
    {"result": "draw", "condition": "board_full"}
  ],
  "authority": {
    "server_only": [],
    "client_verifiable": ["place(mark, board/cell)"]
  }
}
```

### The Six Required Sections

Every game definition has these:

**1. `game`** — Who's playing, what kind of game.
- `players`: Array of player names (these are your seat identifiers).
- `information`: `"perfect"` (everyone sees everything) or `"imperfect"` (hidden state exists).

**2. `zones`** — The spaces where components live.

| Zone Type | What It Is | Example |
|-----------|-----------|---------|
| `grid` | 2D cell array, indexed by `col,row` | Chess board, tic-tac-toe |
| `hex_grid` | Hexagonal grid | Go, hex strategy |
| `graph` | Named nodes with edges | Risk territories |
| `ordered_stack` | LIFO stack (deck of cards) | Draw pile |
| `set` | Unordered collection | Hand of cards, discard pile |
| `counter` | Integer value | Score, chip count |
| `track` | Linear sequence of positions | Backgammon points |
| `single_slot` | Holds exactly one component | Display slot |

Zone visibility controls what you can see:
- `"public"` — everyone sees it.
- `"hidden"` — only the server sees it (e.g., deck order).
- `{"private": "owner"}` — only the owning player sees it (e.g., your hand).

`per_player: true` means each player gets their own instance of the zone.

**3. `components`** — The pieces, cards, tokens.
- `owner`: `"per_player"`, `"neutral"`, `"shared"`, or a specific player name.
- `count`: Integer or `"unlimited"`.
- `types`: Subtypes with different properties (e.g., rock/paper/scissors, ship sizes).
- `movement`: Array of movement primitives (step, slide, leap, hop, place, draw).
- `span`: Number of cells a component occupies (e.g., battleship = 5).

**4. `turn_order`** — Who acts when.
- `alternating`: Players take turns in sequence.
- `round_robin`: All players act each round.
- `simultaneous`: All players act at once (server buffers until all submit).

**5. `end_conditions`** — When and how the game ends.
- Each entry has `result` (win/draw), `condition` (a predicate), and optionally `player` (who wins).
- `"current"` means the player who just moved. `"opponent_of_current"` means the other player.

**6. `authority`** — Trust boundaries.
- `server_only`: Operations requiring hidden state or randomness.
- `client_verifiable`: Operations you can validate locally.
- `wasm_required`: Complex logic needing game-specific WASM.

This tells you what the server controls. If shuffle/deal/reveal are `server_only`,
you'll get cards via `random_result` messages, not by looking at the deck.

### Optional Sections

- **`phases`**: Multi-step game flow (e.g., deal → preflop → flop → turn → river → showdown).
  Each phase can have `server_action` (deal cards, reveal community), `action` (what players do),
  `simultaneous` (buffered), and `ends_when` / `then` for transitions.
- **`rules`**: Named constraints on actions (e.g., "cell must be empty", "cannot move into check").
- **`library`**: Reusable named expressions referenced by end_conditions and rules.
- **`notation`**: Human-readable move format (piece symbols, capture markers).
- **`hand_rankings`** / **`betting_round`**: Poker-specific.

### Reading Strategy

When you encounter a new game definition:

1. Read `game.players` and `game.information` — how many players, is there hidden state?
2. Read `zones` — map the topology. What's public, what's hidden, what's per-player?
3. Read `components` — what pieces exist, how do they move?
4. Read `turn_order` — alternating? simultaneous? how many actions per turn?
5. Read `phases` (if present) — what's the flow? what does the server do automatically?
6. Read `end_conditions` — what are you trying to achieve?
7. Read `authority` — what can you verify locally vs. what does the server control?

---

## Part 2: The WebSocket Protocol

### Connection Lifecycle

```
You                             Server
 |                                |
 |--- POST /rooms {"definition":..} -->|  Create a game room
 |<-- 201 {"room_id":"abc"} --------|
 |                                |
 |--- WebSocket /ws/abc ----------->|  Upgrade to WebSocket
 |                                |
 |--- hello ---------------------->|  Handshake
 |<-- welcome --------------------|  You get a seat and auth token
 |<-- state_sync -----------------|  Initial game state (filtered for you)
 |                                |
 |--- submit_move --------------->|  Your turn: send an action
 |<-- move_confirmed -------------|  Broadcast to all (filtered per player)
 |     or                         |
 |<-- move_rejected --------------|  Only to you, with reason
 |                                |
 |--- request_random ------------->|  Ask for dice roll / card draw
 |<-- random_result ---------------|  Broadcast to all
 |                                |
 |--- acknowledge_state ---------->|  Optional: desync check
 |<-- state_sync (if mismatch) ---|
 |                                |
 |--- close ---------------------->|  Disconnect
```

### Message Reference

#### Client to Server

**hello** (must be first message, within 5 seconds):
```json
{
  "message_type": "hello",
  "protocol_version": 1,
  "client_type": "bot",
  "capabilities": [],
  "token": null
}
```
Set `token` to your previously received token to reclaim your seat on reconnect.

**submit_move** (your turn action):
```json
{
  "message_type": "submit_move",
  "game_id": "abc",
  "player": "X",
  "sequence": 0,
  "action": {
    "action_type": "place",
    "component_type": "mark",
    "to": {"zone": "board", "cell": "1,1"}
  }
}
```

The `action` object fields depend on the game. Common fields:

| Field | When Used |
|-------|-----------|
| `action_type` | Always. `"place"`, `"move_piece"`, `"draw"`, `"play_card"`, `"pass"`, `"resign"`, `"fold"`, `"check"`, `"call"`, `"raise"`, `"commit"`, `"reveal"` |
| `component_type` | Placing or moving a piece type |
| `component_id` | Moving a specific piece |
| `from` | Source position (`"col,row"` or `{"zone":"name","cell":"coord"}`) |
| `to` | Destination position (same format) |
| `zone` | Target zone name |
| `amount` | Bet amount (poker) |
| `promote_to` | Promotion choice (chess pawn) |
| `declaration` | Commit-reveal: the hash (commit) or the value (reveal) |
| `commitment` | Commit-reveal: the nonce (reveal phase) |
| `count` | Number of cards to draw |
| `dice_count` / `dice_type` | Dice roll parameters |

**request_random** (ask server for randomness):
```json
{
  "message_type": "request_random",
  "game_id": "abc",
  "player": "X",
  "random_request": {
    "random_type": "roll",
    "dice_type": "d6",
    "dice_count": 2
  }
}
```
`random_type`: `"roll"`, `"draw"`, or `"shuffle"`.

**acknowledge_state** (optional desync check):
```json
{
  "message_type": "acknowledge_state",
  "game_id": "abc",
  "player": "X",
  "sequence": 1,
  "state_hash": "blake3_hex_64_chars"
}
```

#### Server to Client

**welcome**:
```json
{
  "message_type": "welcome",
  "protocol_version": 1,
  "server_version": "0.1.0",
  "seat": "X",
  "game_id": "abc",
  "token": "128bit_hex_auth_token"
}
```
Save `seat` (your player name) and `token` (for reconnection).

**state_sync** (full state, filtered for your visibility):
```json
{
  "message_type": "state_sync",
  "game_id": "abc",
  "sequence": 0,
  "full_state": { ... }
}
```
See "Game State Format" below.

**move_confirmed** (broadcast after a valid move):
```json
{
  "message_type": "move_confirmed",
  "game_id": "abc",
  "sequence": 1,
  "action": { ... },
  "result_state": { ... }
}
```

**move_rejected** (sent only to you):
```json
{
  "message_type": "move_rejected",
  "game_id": "abc",
  "action": { ... },
  "reason": "not your turn (current: O)"
}
```

**random_result** (broadcast):
```json
{
  "message_type": "random_result",
  "game_id": "abc",
  "random_type": "roll",
  "random_value": [3, 5]
}
```

**error**:
```json
{
  "message_type": "error",
  "error_code": "rate_limited",
  "detail": "exceeded 10 messages per second"
}
```

Error codes: `invalid_message`, `handshake_required`, `handshake_timeout`,
`version_mismatch`, `room_full`, `idle_timeout`, `rate_limited`,
`seat_mismatch`, `game_id_mismatch`, `sequence_error`,
`spectator_not_allowed`, `invalid_action`, `not_your_turn`.

### Game State Format

The `full_state` in `state_sync` and `result_state` in `move_confirmed`:

```json
{
  "status": "in_progress",
  "turn": "X",
  "phase": "main",
  "sequence": 5,
  "move_count": 5,
  "zones": {
    "board": {
      "cells": {
        "0,0": {"id": "mark-X-0", "component_type": "mark", "owner": "X"},
        "1,1": {"id": "mark-X-2", "component_type": "mark", "owner": "X"},
        "1,0": {"id": "mark-O-1", "component_type": "mark", "owner": "O"},
        "0,1": null,
        "2,2": null
      }
    }
  },
  "players": {
    "X": {"seat": "X", "active": true, "connected": true},
    "O": {"seat": "O", "active": true, "connected": true}
  },
  "legal_moves": [
    {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "0,1"}},
    {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "2,0"}}
  ],
  "result": null
}
```

Key fields:
- `status`: `"setup"`, `"in_progress"`, or `"finished"`.
- `turn`: Whose turn it is (matches a player name from the game definition).
- `legal_moves`: Array of valid actions you can submit right now. **This is your menu.**
- `zones`: Current board/card/counter state, filtered by your visibility.
- `result`: Non-null when game is over: `{"outcome": "win", "winner": "X", "condition": "three_in_a_row"}`.

### Visibility Filtering

You only see what you're allowed to see:
- Public zones: full contents.
- Your private zones: full contents.
- Other players' private zones: `{"count": N}` (you know how many, not what).
- Hidden zones (e.g., deck): `{"count": N}` only.

The server holds the complete truth. You see your slice.

### Sequence Numbers

Every `submit_move` includes a `sequence` number. It must be monotonically
increasing (>= the server's expected value). This prevents replay attacks and
detects out-of-order messages. The server rejects stale sequences with
`sequence_error`.

### Reconnection

1. Save the `token` from the `welcome` message.
2. Reconnect to the same WebSocket URL.
3. Send `hello` with the saved `token`.
4. Server recognizes you, reassigns your seat, sends fresh `state_sync`.

---

## Part 3: Playing the Game

### The Decision Loop

Every turn, you receive a game state with `legal_moves`. Your job:

1. Check `state.status` — if `"finished"`, stop.
2. Check `state.turn` — if it's not your seat, wait.
3. Read `state.legal_moves` — this is your complete set of valid actions.
4. Pick one. Submit it.

That's the whole loop. The server validates everything. If you submit an
illegal move, you get `move_rejected` and can try again.

### Using the Agent Framework

```python
from baize.agent import Agent

class MyAgent(Agent):
    def choose_action(self, state: dict) -> dict | None:
        # state["legal_moves"] is your menu
        moves = state.get("legal_moves", [])
        if not moves:
            return None  # will pass
        # Your strategy goes here
        return best_move(moves)

agent = MyAgent("ws://localhost:8080", "room-id")
final_state = agent.play(timeout=300)
```

The `Agent` base class handles:
- Connecting and handshaking
- Waiting for your turn
- Calling `choose_action` when it's your turn
- Submitting the returned action
- Detecting game end

You implement `choose_action`. Optionally override `on_game_start` and
`on_game_end` for setup/teardown.

### Using the SDK for Local Move Enumeration

If `legal_moves` isn't in the server state (some configurations), or you want
to do deeper analysis, use `AgentSession` to enumerate moves locally:

```python
from baize.sdk import AgentSession
from baize.definition import GameDefinition

definition = GameDefinition.from_file("games/tic-tac-toe.json")

class SmartAgent(Agent):
    def choose_action(self, state: dict) -> dict | None:
        session = AgentSession.from_server_state(definition, state)
        moves = session.legal_moves()
        if not moves:
            return None
        # Each move has .action with typed fields
        # .to_action_dict() converts to the wire format
        return moves[0].to_action_dict()
```

### Reference Agents

Three built-in agents in `baize.agents`:

- **`RandomAgent`** — Picks uniformly from `legal_moves`. Baseline.
- **`GreedyAgent`** — Maximizes immediate material advantage (prefers captures).
- **`MCTSAgent`** — Monte Carlo tree search with configurable playout budget (default 100).

### Commit-Reveal Games

For simultaneous/hidden-choice games (e.g., rock-paper-scissors), the protocol
uses commit-reveal:

1. **Commit**: Submit `action_type: "commit"` with `declaration` set to
   `SHA-256(your_choice|random_nonce)`.
2. **Wait**: Server collects commits from all players.
3. **Reveal**: Submit `action_type: "reveal"` with `declaration` set to
   your choice and `commitment` set to your nonce.
4. Server verifies `SHA-256(declaration|commitment)` matches your commit.
   If it does, your choice is locked in. If not, you're caught cheating.

This prevents anyone from changing their choice after seeing the opponent's.

---

## Part 4: Imperfect Information Games

When `game.information` is `"imperfect"`:

- Some zones are hidden or private. You won't see their contents.
- The server handles shuffle, deal, and reveal via `server_only` authority.
- Cards arrive via `random_result` or phase transitions, not by peeking at the deck.
- Your `legal_moves` only includes actions valid given what you know.

### What You Can Infer

- Zone counts are always visible (`{"count": 45}` for a hidden deck).
- Public zones show full contents (community cards in poker).
- Your private zones show your cards (your hand).
- Opponent private zones show only count.

### What You Cannot See

- Deck order.
- Opponent hands.
- Server PRNG state.
- Any zone marked `"hidden"` or `{"private": "owner"}` where you're not the owner.

Error messages from the server are also scrubbed — they never leak hidden state.

---

## Part 5: Event Log and Integrity

Every game produces a BLAKE3 hash-chained event log (JSONL). Each event
includes `prev_hash` (the previous event's hash), forming a tamper-evident
chain. Genesis event has `prev_hash` of all zeros.

```json
{"game_id":"ttt-001","sequence":0,"event_type":"move_applied","player":"X",
 "state_hash":"0b46...","prev_hash":"0000...0000","event_hash":"fe36...",
 "payload":{"action":"place","component_id":"mark-X-0","to":"0,0"}}
```

You don't need to interact with the event log to play. It exists for
tournament integrity and post-game analysis.

---

## Appendix: Worked Example — Tic-Tac-Toe

**1. Create room:**
```
POST /rooms
{"definition": <contents of games/tic-tac-toe.json>}
→ {"room_id": "ttt-001", "game_name": "Tic-Tac-Toe", "max_players": 2}
```

**2. Connect:** `ws://localhost:8080/ws/ttt-001`

**3. Handshake:**
```json
→ {"message_type":"hello","protocol_version":1,"client_type":"bot"}
← {"message_type":"welcome","seat":"X","game_id":"ttt-001","token":"a1b2..."}
← {"message_type":"state_sync","sequence":0,"full_state":{
     "status":"in_progress","turn":"X",
     "zones":{"board":{"cells":{"0,0":null,"0,1":null,"0,2":null,
       "1,0":null,"1,1":null,"1,2":null,"2,0":null,"2,1":null,"2,2":null}}},
     "legal_moves":[
       {"action_type":"place","component_type":"mark","to":{"zone":"board","cell":"0,0"}},
       {"action_type":"place","component_type":"mark","to":{"zone":"board","cell":"0,1"}},
       ...9 moves total...
     ]
   }}
```

**4. Play center:**
```json
→ {"message_type":"submit_move","game_id":"ttt-001","player":"X","sequence":0,
   "action":{"action_type":"place","component_type":"mark",
             "to":{"zone":"board","cell":"1,1"}}}
← {"message_type":"move_confirmed","sequence":1,
   "result_state":{"status":"in_progress","turn":"O",
     "zones":{"board":{"cells":{
       "1,1":{"id":"mark-X-0","component_type":"mark","owner":"X"},
       ...rest null...
     }}}}}
```

**5. Wait for opponent, repeat until:**
```json
← {"message_type":"move_confirmed","sequence":8,
   "result_state":{"status":"finished",
     "result":{"outcome":"win","winner":"X","condition":"three_in_a_row"}}}
```

---

## Appendix: Server Limits

| Limit | Value |
|-------|-------|
| Connections per IP | 10 |
| Messages per second | 10 |
| Max message size | 1 MB |
| Idle timeout | 5 minutes |
| Handshake timeout | 5 seconds |
| Max moves per game | 100,000 |
| Action field length | 255 chars |
| Dice count per roll | 1–1,000 |

## Appendix: File Locations

| What | Where |
|------|-------|
| Game definitions | `games/*.json` |
| JSON Schema specs | `schema/game-definition.schema.json` (and 4 others) |
| Reusable components | `registry/` (47 standard boards, cards, dice, pieces, tiles, tokens) |
| Python agent framework | `python/baize/agent.py` |
| Reference agents | `python/baize/agents.py` |
| Agent SDK | `python/baize/sdk.py` |
| Python client | `python/baize/client.py` |
| TypeScript client | `client/src/connection.ts` |
| Cross-impl test vectors | `tests/vectors/` |
