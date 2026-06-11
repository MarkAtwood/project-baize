# Baize — Design Document

## Problem Statement

No existing system provides a declarative game description that is designed
around the client/server trust boundary. Academic systems (GDL, Ludii) assume
a single evaluator. Practical systems (Vassal, Tabletop Simulator) provide
no rules enforcement. There is no language that tells a client "here is what
you can validate locally" while telling a server "here is the minimum you
must enforce."

## Core Insight

Most turn-based game operations are deterministic functions of visible state.
A client that knows the rules can:

- Highlight legal moves before the player acts
- Reject illegal moves without a round-trip
- Animate state transitions immediately (optimistic execution)
- Detect cheating by peers in P2P scenarios

The server's irreducible role is:

- Maintaining hidden state (shuffled deck order, fog-of-war truth)
- Providing randomness (dice rolls, card draws)
- Sequencing moves (who moved first in simultaneous games)
- Resolving conflicts that depend on hidden state

Everything else can run on the client.

## Platform Requirements

Baize clients require a user agent that supports WebAssembly, WebSocket
(RFC 6455), inline SVG, and Web Components (Custom Elements v1, Shadow
DOM). These are baseline web platform features available in all major
browsers since 2020. No polyfills are provided or supported.

The intended embedding model is a set of custom elements:

```html
<script src="https://cdn.example.com/baize.js"></script>
<baize-game src="chess.json" server="wss://play.example.com/game/42">
  <baize-board></baize-board>
  <baize-hand player="1"></baize-hand>
  <baize-score></baize-score>
  <baize-clock></baize-clock>
</baize-game>
```

One script tag registers the custom elements and bundles the WASM engine.
Shadow DOM isolates game styles from the host page. No framework dependency
— works in React, WordPress, raw HTML, or anything that renders DOM. Game
designers can rearrange child elements to customize layout without touching
game logic.

## Architecture: Three Tiers

### Tier 1: Declarative Schema (parsed, not executed)

Covers ~90% of games. Describes:

- Topology (zones, slots, adjacency, capacity)
- Components (pieces, cards, dice, tokens)
- Movement primitives (slide, hop, step, leap, place, draw)
- Static constraints (max per zone, valid placements, turn structure)
- Visibility rules (public, private-to-owner, hidden)
- Win/loss/draw conditions (when expressible as predicates over visible state)

The schema is data. The client parses it and uses it to compute legal moves,
render valid targets, and validate actions locally.

### Tier 2: WASM Module (executed deterministically)

Covers the remaining ~10%: logic too complex for declarative predicates.

- Complex scoring (Carcassonne field scoring, Go territory)
- Chain reactions (Othello flips, Candy Crush cascades)
- Custom phase logic (Magic: The Gathering stack resolution)
- Non-trivial win conditions (checkmate detection)

The same WASM binary runs on both client and server. Deterministic execution
guarantees identical results. Sandboxed — no I/O, no escape.

The WASM module receives game state as input and returns:
- Legal moves for a given player
- Next state given a move
- Game-over conditions

### Tier 3: Server Authority (irreducible minimum — or is it?)

Only what cannot be computed locally:

- Hidden state storage and revelation
- Randomness generation (cryptographically fair)
- Move sequencing and timestamps
- Conflict resolution requiring hidden state

For perfect-information games (chess, Go, checkers), Tier 3 is just a
sequencer — a message bus that stamps move order. For imperfect-information
games (poker, Battleship), Tier 3 holds the hidden state and reveals it
according to the schema's visibility rules.

But none of these operations *inherently* require a trusted third party.
Every `server_only` operation has a known cryptographic protocol that
replaces the server with peer-to-peer computation (see "Serverless Play"
below). The authority declaration is designed as a transport-independent
interface: the schema says *what* needs to happen, not *who* does it.

## Authority Declaration

The schema explicitly declares which operations require server authority.
In practice these are JSON arrays of action strings (see `games/*.json`);
the pseudocode below is for readability:

```
authority:
  server_only:
    - draw_from(deck)        # deck order is hidden
    - roll(dice)             # randomness
    - reveal(card, player)   # hidden → visible transition
    - resolve_simultaneous() # ordering when moves are concurrent

  client_verifiable:
    - move(piece, from, to)  # movement rules are public
    - play_card(card)        # hand contents known to owner
    - place(token, zone)     # zone capacity is public
    - declare_action(type)   # action legality is visible-state
```

This is the key novel contribution. No existing system provides this
metadata.

## State Model

Game state is a set of typed facts (relational model, stolen from GDL):

```
# Zones
zone(board, grid, 8x8)
zone(white_hand, set, capacity:unlimited)
zone(black_hand, set, capacity:unlimited)

# Components
component(wp1, pawn, owner:white, position:board/a2)
component(wp2, pawn, owner:white, position:board/b2)
component(bk, king, owner:black, position:board/e8)

# Game state
turn(white)
phase(main)
move_count(0)
```

State transitions are the result of applying a legal move to the current
state. Both client and server can compute the transition independently.

## Visibility Model (from GDL-II)

Three tiers of fact visibility:

| Tier | Who sees it | Examples |
|------|-------------|----------|
| Public | All players + spectators | Board position, captured pieces, scores |
| Private | Owner only | Cards in hand, face-down tiles you placed |
| Hidden | Server only | Deck order, unrevealed map tiles, sealed bids |

The schema declares visibility per zone and per component property:

```
zone deck:
  type: ordered_stack
  visibility: hidden        # nobody sees order
  draw_visibility: private  # drawn card visible only to drawer

zone board:
  type: grid(8, 8)
  visibility: public        # everyone sees all board positions

zone hand:
  type: set
  visibility: private(owner) # only owner sees contents
  capacity: unlimited
```

A client receiving the game state gets: all public facts + their own private
facts. They can compute legal moves over this subset. The server sees
everything and validates against the full state.

## Instantiation Model (from Screentop.gg, BGA)

A game piece goes through four levels from definition to play:

```
Template        →  Type           →  Instance       →  Placement
(registry SVG)    (game schema)     (specific piece)  (in-play state)
```

| Level | What it is | Example | Who defines it |
|-------|-----------|---------|---------------|
| **Template** | Visual + shape definition | "A poker-sized card face" | Component registry |
| **Type** | A specific kind of piece with properties | "Ace of Spades" | Game schema |
| **Instance** | A particular copy in this game session | "The Ace of Spades in this deck" | Runtime (server creates) |
| **Placement** | Where it is right now | "In Alice's hand, face-down" | Game state (mutable) |

This mirrors Screentop.gg's Asset → Component → Variant → Object hierarchy,
and BGA's material.inc.php (static definitions) vs. database (dynamic state).

**Why this matters for the trust boundary:** Templates and Types are static —
shipped once, cached forever. Instances are created at game start (or during
play for deck-builders). Placements change every turn. The client needs
Templates + Types to render and validate; it needs Placements to show current
state. The server is authoritative over Instance creation (shuffling) and
Placement changes (move confirmation).

## Static vs. Dynamic Separation (from BGA)

Borrowed from Board Game Arena's architecture:

- **Static material** (schema): component types, rules, zones, constraints.
  Defined once per game. Never changes during play. Equivalent to BGA's
  `material.inc.php`.

- **Dynamic state** (runtime): which instances exist, where they are, whose
  turn it is, score counters. Changes every move. Equivalent to BGA's
  database tables.

The schema language defines the static material. The server protocol operates
over dynamic state. A client caches the static material and subscribes to
state changes.

## Component Ontology (from TAG, TGC, Tabletopia)

Primitives that every game is built from:

### Containers (zones)

- **Grid** — 2D array of cells (chess, Go, Tic-tac-toe)
- **Hex grid** — hexagonal tessellation (Catan, Hive)
- **Graph** — arbitrary node/edge topology (network games)
- **Stack** — ordered, access from top (draw pile, discard)
- **Set** — unordered collection (hand of cards, bag of tiles)
- **Queue** — ordered, FIFO (turn order track)
- **Single slot** — holds exactly one component (throne, target cell)
- **Track** — linear sequence of positions (backgammon points, scoring track)
- **Counter** — numeric value, no components (score, pot, hit points)

### Components

- **Token/Piece** — has owner, type, position. May have state (promoted/not).
- **Card** — has suit, rank, face-up/down. Lives in stacks or sets.
- **Die/Dice** — N-sided, produces random value on roll.
- **Counter** — numeric value (score, hit points, mana).
- **Tile** — placed onto grid/board, may have edges/sides (Carcassonne).
- **Marker** — stateless position indicator (last-move dot, legal-move highlight).

### Properties

- `owner` — which player (or neutral/shared)
- `position` — which zone and where within it
- `facing` — face-up, face-down, or edge-specific (tile games)
- `state` — type-specific state (promoted pawn, tapped card, exhausted action)

### Physical Form Factor (optional, from TGC/Tabletopia)

Components MAY carry physical metadata for manufacturing compatibility
or real-world prototyping:

```yaml
physical:
  size_mm: [63, 88]          # poker card: 63×88mm
  thickness_mm: 0.32         # standard card stock
  material: cardstock_300gsm # or: wood, plastic, acrylic, metal
  shape: rectangle           # or: circle, hexagon, meeple, custom
  weight_g: 1.8              # per unit
```

This is informational — it enables "export to print-and-play PDF" or
"generate manufacturing spec" workflows. Games work without it.
The Game Crafter's catalog of 2,967 physical pieces validates that
these form factors cover real-world games.

## Movement Primitives (from Ludii)

Composable atoms describing how pieces move:

| Primitive | Meaning | Example |
|-----------|---------|---------|
| `step(dir)` | Move one cell in direction | King (chess) |
| `slide(dir)` | Move any distance in direction until blocked | Rook, Bishop |
| `hop(dir)` | Jump over exactly one piece | Checkers capture |
| `leap(dx, dy)` | Jump to offset regardless of path | Knight |
| `place(zone)` | Put new component into zone | Go stone placement |
| `draw(zone)` | Take top of stack | Draw a card |
| `move_to(zone)` | Transfer component between zones | Play card from hand |
| `swap(a, b)` | Exchange positions of two components | Some abstract games |
| `remove(component)` | Destroy/capture | Chess capture |
| `promote(type)` | Change component type | Pawn promotion |
| `flip()` | Toggle face-up/down | Memory game |
| `castle(side)` | Composite king+rook move | Chess castling |

Each primitive composes with:
- **Direction generators**: orthogonal, diagonal, adjacent, forward, specific
- **Conditions**: CEL expressions (see Constraint Language below)
- **Repetition**: exactly(N), range(min, max), unlimited
- **Effects**: Perturber sequences (see Effect Language below)

## Constraint Language (CEL)

Constraints and predicates throughout the schema use
[CEL (Common Expression Language)](https://github.com/google/cel-spec),
Google's expression language for policy evaluation. CEL is:

- **Guaranteed to terminate** — no loops, no recursion, no mutation
- **Formally specified** — unambiguous grammar and semantics
- **Multi-implementation** — Rust (cel-rust), Python (cel-python), WASM-compilable

CEL expressions evaluate over game state and return booleans. They appear
in movement conditions, end conditions, rule triggers, and perturber
control flow. Examples:

```cel
// Movement condition: pawn can move forward if cell is empty
target.component == null

// Movement condition: pawn captures diagonally if enemy present
target.component != null && target.component.owner != current_player

// End condition: checkmate
in_check(current_player) && legal_moves(current_player).size() == 0

// End condition: board full (tic-tac-toe draw)
zone("board").cells.all(c, c.component != null)

// Rule trigger: pawn reaches promotion rank
component.position.rank == promote_rank(component.owner)

// Carcassonne: tile edges must match neighbors
adjacent_cells(target).all(neighbor,
    neighbor.component == null ||
    edge_matches(component, target.rotation, neighbor.component, neighbor.direction))
```

### Standard Function Library

CEL's custom function mechanism provides game-specific predicates. The
engine registers these; the spec defines their signatures and semantics:

| Function | Signature | Description |
|----------|-----------|-------------|
| `zone(name)` | `string → ZoneState` | Access a zone by name |
| `adjacent(pos)` | `Position → list<Position>` | All adjacent positions |
| `adjacent_cells(pos)` | `Position → list<Cell>` | Adjacent cells with contents |
| `distance(a, b)` | `Position, Position → int` | Grid distance between positions |
| `path_clear(from, to, dir)` | `Position, Position, Direction → bool` | No pieces between two positions |
| `in_line(positions)` | `list<Position> → bool` | All positions are collinear |
| `connected(pos, pred)` | `Position, Predicate → list<Position>` | Flood-fill from position matching predicate |
| `group(pos)` | `Position → list<Position>` | Connected same-owner group containing position |
| `liberties(group)` | `list<Position> → int` | Empty cells adjacent to group |
| `in_check(player)` | `string → bool` | Player's king is attacked |
| `legal_moves(player)` | `string → list<Move>` | All legal moves for player |
| `attacked_by(pos, player)` | `Position, string → bool` | Position is attacked by player's pieces |
| `edge_matches(a, b, dir)` | `Component, Component, Direction → bool` | Tile edges match at boundary |
| `promote_rank(player)` | `string → int` | Promotion rank for player |
| `count(zone, filter)` | `string, Predicate → int` | Count components matching filter |
| `has_moved(component)` | `Component → bool` | Component has moved from initial position |
| `owner_of(component)` | `Component → string` | Owner of a component |
| `history_contains(hash)` | `string → bool` | Board state hash appears in game history (for superko) |
| `group_size(group)` | `list<Position> → int` | Number of positions in a group |

Functions that require search (`in_check`, `legal_moves`) are evaluated
by the engine, not expanded inline. Their cost is bounded by board size.

### Extension Model

The CEL function library is the primary extension point for the project.
The schema language, perturber primitives, and control flow constructs
are intentionally closed — they change rarely if ever. New game mechanics
get supported by adding well-defined CEL functions with clear signatures,
semantics, and termination bounds. This is where the project accepts
contributions: a new function like `territory_score(zone, player)` or
`longest_road(zone, player)` extends what Tier 1 can express without
touching the language itself.

Function contributions must specify:
- **Signature**: input types and return type
- **Semantics**: unambiguous description of behavior
- **Termination bound**: worst-case cost in terms of board state size
- **Test vectors**: at least two non-trivial test cases with expected outputs

## Effect Language (Structured Perturbers)

State mutations are described by a structured effect language that composes
movement primitives with control flow. Unlike CEL (which is pure), perturbers
mutate game state. Unlike WASM (which is arbitrary code), perturbers are
guaranteed to terminate.

### Effect Primitives

| Primitive | Fields | Description |
|-----------|--------|-------------|
| `move` | `component`, `to` | Relocate component to position |
| `place` | `component_type`, `at`, `owner` | Create and place new component |
| `remove` | `target` | Destroy/capture a component |
| `flip` | `target` | Toggle face-up/face-down |
| `promote` | `target`, `to_type` | Change component type |
| `swap` | `a`, `b` | Exchange two components' positions |
| `draw` | `from_zone`, `to_zone` | Take top of stack |
| `shuffle` | `zone` | Randomize stack order (server authority) |
| `transfer` | `component`, `from_zone`, `to_zone` | Move between zones |
| `reveal` | `component`, `to` | Change visibility (hidden → public) |
| `set_counter` | `counter`, `value` | Set counter to value |
| `add_counter` | `counter`, `value` | Increment/decrement counter |
| `set_state` | `target`, `state` | Change component state (tapped, exhausted) |
| `end_turn` | | Advance turn to next player |

### Control Flow

| Construct | Semantics | Termination guarantee |
|-----------|-----------|----------------------|
| `sequence` | Run effects in order | Finite list |
| `if` / `then` / `else` | CEL predicate, one branch taken | Single evaluation |
| `for_each` + `filter` | CEL filter over collection, run body per match | Bounded by set size |
| `choose` | Player selects from finite options | Blocks for input; finite choices |
| `repeat(n)` | Run body n times | Literal count |
| `repeat_until_stable` | Run body, check for state change, repeat | Fuel budget (see below) |

**No `while`. No recursion. No computed gotos.**

### Chain Reactions: `repeat_until_stable`

Many games have chain reactions: Go captures, checkers multi-jumps,
match-3 cascades, Othello flips. These are fixpoint computations — apply
rules until the board is stable. `repeat_until_stable` handles this with
a **fuel budget**: a CEL expression evaluated once against initial state
that sets the hard upper bound on iterations.

```
// Go capture chains
{
  "on": "place",
  "then": {
    "repeat_until_stable": {
      "fuel": "zone('board').cells.size()",
      "apply": [{
        "for_each": {
          "in": "groups(zone('board'))",
          "filter": "liberties($item) == 0 && $item[0].owner != current_player"
        },
        "do": {
          "sequence": [
            { "add_counter": { "counter": "captures", "player": "current",
                               "value": "group_size($item)" } },
            { "for_each": { "in": "$item",
                            "do": { "remove": { "target": "$item" } } } }
          ]
        }
      }]
    }
  }
}
```

The engine evaluates `fuel` once (here: number of board cells). Each
iteration applies the body and diffs the state. If nothing changed, the
chain is stable — stop. If fuel exhausts before fixpoint, that's a game
definition error reported at validation time or runtime.

Real-world chain reactions always terminate because each step consumes
a finite resource:

| Game | Chain mechanism | What decreases per step |
|------|----------------|------------------------|
| Go | Capture no-liberty groups | Stones on board |
| Checkers | Multi-jump captures | Opponent pieces |
| Match-3 / Candy Crush | Remove matches, gravity fill, re-match | Pieces on board |
| Othello | Flip sandwiched lines | N/A (one pass, not cascading) |
| Carcassonne | Complete feature → return meeples | Meeples on features |
| MTG/Dominion | Card triggers card | Actions/mana remaining |

### Tier Boundary Redefined

With CEL constraints and structured perturbers, the three tiers become:

- **Tier 1**: CEL predicates + structural effects + `repeat_until_stable`.
  Covers placement, movement, capture, scoring, chain reactions, phase
  transitions, and most end conditions. Guaranteed to terminate.

- **Tier 2 (WASM)**: Needed only for logic that exceeds Tier 1:
  - Computed scoring with complex tiebreakers (Carcassonne field majority)
  - Predicates requiring game-tree search (checkmate detection via
    move enumeration — though `in_check()` as a library function may
    suffice for most cases)
  - Exotic mechanics with no natural fuel bound

- **Tier 3 (Server)**: Unchanged — hidden state, randomness, sequencing.

## Turn Structure

```
turn_order:
  type: alternating          # or: round_robin, simultaneous, reactive
  players: [white, black]

phases:
  - name: main
    actions_per_turn: 1
    mandatory: true          # must make a legal move or lose

  - name: promotion
    trigger: pawn_reaches_rank_8
    actions_per_turn: 1
    choices: [queen, rook, bishop, knight]
```

## Win/Loss/Draw Conditions

Declarative predicates over state, using CEL expressions:

```
end_conditions:
  - result: win
    player: opponent(current)
    condition: "legal_moves(current_player).size() == 0 && in_check(current_player)"
    name: checkmate

  - result: draw
    condition: "legal_moves(current_player).size() == 0 && !in_check(current_player)"
    name: stalemate

  - result: draw
    condition: "state.halfmove_clock >= 100"
    name: fifty_move_rule

  - result: win
    player: current
    condition: "lines.exists(line, line.all(cell, cell.owner == current_player))"
    name: three_in_a_row
```

## WASM Interface

When declarative predicates aren't enough, the WASM module provides
these four entry points. State and actions are serialized as JSON strings
passed via `alloc`/`dealloc` in WASM linear memory (length-prefixed,
4 bytes LE + UTF-8). Server-side hosting uses wasmtime (optional feature
in `server/Cargo.toml`); client-side uses native browser WASM.

```rust
// The WASM module exports these functions:

/// Returns list of legal moves for the given player in the given state.
#[export]
fn legal_moves(state: &GameState, player: PlayerId) -> Vec<Move>;

/// Applies a move to state, returns new state + events.
#[export]
fn apply_move(state: &GameState, action: Move) -> (GameState, Vec<Event>);

/// Checks if the game is over and who won.
#[export]
fn check_end(state: &GameState) -> Option<GameResult>;

/// Validates a proposed move (for server confirmation).
#[export]
fn validate_move(state: &GameState, player: PlayerId, action: Move) -> bool;
```

The state is serialized as the same relational facts the declarative schema
uses. The WASM module is a superset — it can do anything CEL predicates
and structured perturbers can do, plus arbitrary computation. With the
Tier 1 constraint and effect languages, WASM is needed for fewer games
than initially expected — the design target is that Go (capture chains,
ko detection, territory scoring) runs entirely in Tier 1 without WASM.

## Server Protocol (Minimal)

The server's API surface:

```
# Client → Server
submit_move(game_id, player, action)
request_random(game_id, type, params)   # "roll 2d6", "draw 1"
acknowledge_state(game_id, state_hash)

# Server → Client
move_confirmed(game_id, sequence, action, result_state)
move_rejected(game_id, action, reason)
random_result(game_id, type, value)
reveal(game_id, player, facts)          # hidden → private/public
state_sync(game_id, full_state)         # on reconnect or desync
```

For perfect-information games, `submit_move` → `move_confirmed` is the
entire protocol. The server is a notary.

## Prior Art Assessment

| System | What we steal | What we reject |
|--------|--------------|----------------|
| **GDL** | Relational state model, `legal` predicates | Datalog syntax, AI-only focus, no client/server concept |
| **GDL-II** | `sees(player, percept)` visibility model | Still Datalog, still no practical transport |
| **Ludii** | Composable movement primitives (ludemes), component library | Monolithic evaluator, bespoke runtime, no networking |
| **TAG** | Component taxonomy (token/card/die/counter), zone model, turn orders | Imperative Java ForwardModel, no declarative rules |
| **Partake** | Compositional zone/transition model, relational concepts | Academic formalism, no implementation |
| **Regular Games** | Automata-based validation (efficient) | Too theoretical, narrow game class |
| **Ludax** | Compiles declarative → executable (GPU), proves the concept | GPU/RL-specific, narrow game class (placement only) |
| **Vassal** | Battle-tested component model (counters, cards, maps) | No rules enforcement at all |
| **Tabletop Simulator** | Shows demand for generic tabletop platform | Proprietary, no rules, physics-based (wrong abstraction) |
| **Screentop.gg** | Asset→Component→Variant→Object instantiation hierarchy | No rules enforcement, JSON model is visual-only |
| **The Game Crafter** | Physical form-factor taxonomy (2,967 pieces, 92 meeple shapes) | Manufacturing API, no game logic, no digital play |
| **Board Game Arena** | Static material / dynamic state separation; Deck/Stock/Zone framework | Rules are imperative PHP, closed ecosystem |
| **Tabletopia** | Real-world dimensions as component metadata; .OBJ 3D models | No rules, shared-whiteboard model |

## Event Logging

Every state transition produces a structured JSONL event with BLAKE3 hash
chaining. Each event's hash includes the previous event's hash, forming a
tamper-evident log suitable for tournament integrity verification.

```
{"game_id":"g1","sequence":0,"event_type":"move","player":"white",
 "state_hash":"ab12...","prev_hash":"0000...","event_hash":"cd34...",
 "payload":{...}}
```

Both Rust and Python implementations produce identical hashes for the same
state (verified by cross-implementation test vectors).

## Server Security Model

The server enforces defense-in-depth:

- **Rate limiting**: 30 messages/second per connection (sliding window)
- **Message size**: 64 KB maximum WebSocket message
- **Per-IP limits**: 10 connections per IP address
- **Idle timeout**: 5 minutes of inactivity disconnects
- **Room capacity**: 100 rooms maximum, player count per game definition
- **Move limits**: 10,000 moves per game maximum
- **Bounded channels**: 256-message outbound queue per player; slow clients dropped
- **Input validation**: All action fields bounded (256 chars), dice/draw counts capped
- **Spectator isolation**: Spectators cannot submit moves or request random values
- **Private replies**: MoveRejected and StateSync sent only to the requesting player,
  preventing information leaks in imperfect-information games
- **Turn enforcement**: RequestRandom requires it to be the requesting player's turn

## Serverless Play: Cryptographic Protocols

The server's secret-keeping role is architecturally replaceable. The
authority declaration identifies exactly which operations require trust;
cryptographic protocols can provide that trust without a central server.

### Every server_only operation has a crypto replacement

| Server operation | Cryptographic protocol | Latency cost |
|-----------------|----------------------|-------------|
| `shuffle(deck)` | Mental poker — commutative encryption shuffle (SRA 1979, Barnett & Smart 2003) | O(n²) rounds for n cards |
| `deal(card)` | Threshold decryption — all parties must cooperate to reveal | 1 round per card |
| `roll(dice)` | Commit-reveal — each party commits `hash(nonce)`, reveal, XOR for result | 2 rounds |
| `reveal(card)` | Owner removes their encryption layer | 1 round |
| `resolve_simultaneous()` | Commit-reveal — commit `hash(action)`, then reveal | 2 rounds |
| Move sequencing | Consensus protocol or designated-verifier ordering | Varies |

For perfect-information games, the server is already just a sequencer
and can be replaced by any message ordering mechanism (turn-based
WebRTC, blockchain, or even email).

For imperfect-information games (poker, Battleship), the full mental
poker protocol replaces the server as card dealer. The 1979 SRA protocol
uses commutative encryption: each player encrypts every card with their
own key, they shuffle in encrypted form, and a card is revealed only
when all players agree to decrypt their layer. Modern variants (Barnett
& Smart 2003, Geometry of Shuffling) reduce this to efficient elliptic
curve operations.

### How the schema supports this

The schema is already transport-independent. The authority declaration
is the interface:

1. A **trusted server** transport reads `server_only` and implements
   those operations centrally. Fastest, simplest, current default.

2. A **commit-reveal** transport implements `roll(dice)` and
   `resolve_simultaneous()` as peer-to-peer commit-reveal. Covers
   randomness and simultaneous moves with minimal overhead (2 extra
   rounds). This is the practical near-term extension.

3. A **mental poker** transport implements `shuffle`, `deal`, and
   `reveal` using commutative encryption. Covers all card games
   without any trusted party. Higher latency but provably fair.

The game definition does not change between transports. A poker game
that declares `server_only: [shuffle(deck), deal(deck, hand)]` works
identically whether those operations are performed by a trusted server
or by a mental poker protocol between peers. The schema describes the
*trust requirements*; the transport binding satisfies them.

### Commit-reveal for randomness

The simplest and most immediately useful crypto extension. For any
`server_only` operation that generates randomness:

```
1. Server commits: broadcasts hash(random_value || nonce)
2. Players acknowledge the commitment
3. Server reveals: broadcasts random_value and nonce
4. Clients verify: hash(random_value || nonce) == commitment
```

This prevents the server from choosing random values after seeing player
actions. It's a one-way upgrade: existing clients that ignore commitments
still work; clients that verify commitments get stronger guarantees.

**Commit-reveal for randomness ships in the earliest releases.** This is
a deliberate architectural forcing function: every client implementation
must have the protocol space for serverless cryptography from day one,
even before full mental poker support. Adding commit-reveal later would
require breaking protocol changes in every client. Adding mental poker
later, on top of an existing commit-reveal flow, is a compatible
extension.

For full serverless randomness (no trusted server at all), each player
contributes a committed nonce and the final random value is XOR of all
nonces — no single party controls the outcome.

### What this means for the architecture

The three tiers are not about *who* performs computation. They're about
*what kind* of computation is needed:

- **Tier 1**: Deterministic, visible-state predicates and effects
- **Tier 2**: Deterministic, complex computation (WASM)
- **Tier 3**: Operations requiring *trust* — which can be provided by a
  server, by cryptographic protocols, or by a combination

The authority declaration is the interface between game logic and trust
provision. This is what makes it the key novel contribution: it doesn't
just tell clients what to validate locally. It tells *any trust provider*
— server, peer-to-peer protocol, blockchain, or future mechanism —
exactly what trust services the game requires.

## Decided Questions

1. ~~**Syntax**~~ — **JSON.** Zero-dependency parsing in all three
   implementation languages, no ambiguity, JSON Schema for validation.

2. ~~**WASM ABI**~~ — **JSON strings.** State and actions serialized as JSON,
   passed via `alloc`/`dealloc` in WASM linear memory. Length-prefixed
   (4 bytes LE + UTF-8). Deterministic across client and server.

3. ~~**Simultaneous moves**~~ — **Compose from existing primitives.** Phase
   with `simultaneous: true` + visibility model + server submission gate.
   No new turn_order type. Phase collects private actions, server waits
   for all players, then reveals. Covers RPS, Diplomacy, sealed bids.

4. ~~**Infinite/unbounded games**~~ — **Dynamic zones.** Zones with
   `dynamic: true` can grow at runtime (deck-builders, procedural maps).
   Grid zones require explicit dimensions; dynamic zones do not.

5. ~~**Spectator mode**~~ — **Public state only.** Spectators receive public
   zone contents and scores. Delayed revelation (broadcast delay) is a
   server transport concern, not a schema concern.

6. ~~**Undo/takeback**~~ — **Schema-declared.** The schema can declare
   `undo: permitted | forbidden`. Server enforces. Undo replays from
   the event log.

7. ~~**Constraint language**~~ — **CEL (Common Expression Language).**
   Google's policy expression language. Guaranteed to terminate, formally
   specified, multi-implementation (Rust, Python, WASM). Predicates are
   CEL; effects are a structured perturber language composing movement
   primitives with control flow (`sequence`, `if/then/else`, `for_each`,
   `repeat_until_stable`). Chain reactions use bounded fixpoint iteration
   with a fuel budget. No `while`, no recursion. WASM tier is now only
   needed for computed scoring and search-dependent predicates.

8. ~~**Randomness commitment**~~ — **Commit-reveal, transport-level.**
   The server commits `hash(value || nonce)` before players act, then
   reveals. Verification is optional for clients (backwards compatible).
   For serverless play, all parties contribute committed nonces; final
   value is XOR. The schema declares what randomness is needed
   (`server_only: roll, shuffle`); the transport binding decides whether
   a trusted server or commit-reveal protocol provides it.

9. ~~**Time controls**~~ — **Split responsibility.** Schema declares
   `time_control` type and `timeout_result` (loss/draw/none — the game
   rule). Server overrides `seconds` and `increment` at room creation.
   Server owns clock state and enforcement. Client displays
   server-provided clock.

## Implementation Status

Three reference implementations share the same schema and cross-validate
via test vectors in `tests/vectors/`:

| Component | Language | Tests | Key capabilities |
|-----------|----------|-------|-----------------|
| `engine/` | Rust (serde, blake3, indexmap) | 77 | Parse/validate definitions, runtime state machine, legal move generation (step/slide/leap/hop), state transitions, BLAKE3 hash-chained event logs, tamper detection |
| `python/` | Python 3.12 (dataclasses, strict mypy) | 121 | Feature-parallel with Rust engine, plus game analysis (branching factor, complexity profile, shortest game search) and Jupyter notebook integration (SVG board rendering, interactive `GameWidget`) |
| `server/` | Rust (Axum, tokio, WebSocket) | Builds | Room management, WebSocket protocol dispatch, hidden-state vault (ChaCha20Rng), rate limiting, per-IP connection limits, spectator isolation |
| `client/` | TypeScript | Types only | Full type definitions for all five JSON schemas; Web Components rendering not yet implemented |

Five JSON Schema definitions (draft 2020-12) in `schema/`:

- `game-definition.schema.json` — Declarative game definitions
- `game-state.schema.json` — Runtime game state
- `move-action.schema.json` — Client/server protocol messages
- `event-log.schema.json` — BLAKE3 hash-chained event log format
- `component-registry.schema.json` — Reusable component definitions

Six reference game definitions in `games/`: Tic-Tac-Toe, Chess, Go,
Backgammon, Texas Hold'em, Carcassonne. Ten reusable component definitions
in `registry/` (card decks, dice, piece sets, boards, tiles, tokens).

Cross-implementation test vectors in `tests/vectors/` verify that Rust and
Python produce identical state hashes, legal move lists, and event logs for
the same inputs.

## Open Questions

1. **Rating/matchmaking**: Out of scope, but the schema's complexity
   metadata (branching factor, average game length, hidden information
   ratio) could feed rating systems. TAG already computes these metrics.
   The Python `analysis` module already computes branching factor,
   complexity profiles, and hidden information ratio.

2. **Mod support**: Can a WASM module extend the declarative schema (add new
   movement primitives, new component types)? Or is the schema fixed and
   WASM is only for validation logic?
