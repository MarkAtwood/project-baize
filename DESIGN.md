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

### Tier 3: Server Authority (irreducible minimum)

Only what cannot be computed locally:

- Hidden state storage and revelation
- Randomness generation (cryptographically fair)
- Move sequencing and timestamps
- Conflict resolution requiring hidden state

For perfect-information games (chess, Go, checkers), Tier 3 is just a
sequencer — a message bus that stamps move order. For imperfect-information
games (poker, Battleship), Tier 3 holds the hidden state and reveals it
according to the schema's visibility rules.

## Authority Declaration

The schema explicitly declares which operations require server authority:

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

Each primitive composes with:
- **Direction generators**: orthogonal, diagonal, adjacent, forward, specific
- **Conditions**: if_empty, if_enemy, if_friendly, if_nth_move
- **Repetition**: exactly(N), range(min, max), unlimited
- **Effects**: after_move(capture, promote, score, end_turn)

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

Declarative predicates over state:

```
end_conditions:
  - type: win
    player: opponent(current)
    when: no_legal_moves(current) AND in_check(current)  # checkmate

  - type: draw
    when: no_legal_moves(current) AND NOT in_check(current)  # stalemate

  - type: draw
    when: repetition_count(state) >= 3  # threefold repetition

  - type: win
    player: owner(component) WHERE component.position == zone(goal)
    when: exists(component, type:king, position:opponent_goal)
```

## WASM Interface

When declarative predicates aren't enough, the WASM module provides:

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
uses. The WASM module is a superset — it can do anything the declarative
predicates can do, plus arbitrary computation.

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

## Open Questions

1. ~~**Syntax**~~ — **Decided: JSON.** Zero-dependency parsing in all three
   implementation languages, no ambiguity, JSON Schema for validation.

2. **WASM ABI**: What's the exact serialization format for passing game state
   to/from WASM? Flatbuffers? JSON? Custom binary? (JSON is the default
   candidate given the schema format decision.)

3. **Randomness commitment**: For competitive play, the server should commit
   to random values before they're needed (commit-reveal). How does the
   schema express this?

4. **Simultaneous moves**: Some games have simultaneous action selection
   (Rock-Paper-Scissors, Diplomacy). The schema needs to express "both
   players submit secretly, then reveal." This is a server-authority
   operation that the visibility model handles, but the turn structure
   needs to express it.

5. **Infinite/unbounded games**: The schema assumes finite state. How do we
   handle games with unbounded state (deck-builders that add cards during
   play, procedurally generated maps)?

6. **Spectator mode**: Spectators see public state. But some games have
   delayed revelation for spectators (poker tournament broadcast delay).
   Does the schema express this?

7. **Undo/takeback**: Should the schema declare whether undo is permitted?
   This affects the server protocol (can a confirmed move be rescinded?).

8. **Time controls**: Chess clocks, shot clocks, turn timers. Are these part
   of the schema or a transport concern?

9. **Rating/matchmaking**: Out of scope, but the schema's complexity
   metadata (branching factor, average game length, hidden information
   ratio) could feed rating systems. TAG already computes these metrics.

10. **Mod support**: Can a WASM module extend the declarative schema (add new
    movement primitives, new component types)? Or is the schema fixed and
    WASM is only for validation logic?
