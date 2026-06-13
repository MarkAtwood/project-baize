# Baize

A declarative language for turn-based card and board games that separates
game topology, components, and constraints from the minimal authoritative
game server. Designed so that most operations run locally on the client,
reducing the server to a sequencer and hidden-state oracle.

**Baize** is the green felt cloth used to cover card tables, billiard tables,
and gaming surfaces. It's the surface everything plays out on — present in
every game, belonging to none of them.

## Why doesn't this exist already?

Four communities independently solved their slice of this problem, then
stopped:

**The AI researchers** (Stanford, Maastricht) built declarative game
languages — GDL (2005), Ludii (2019, 1,400+ games). They proved you can
describe game rules formally enough for machine reasoning. But they assumed
a single trusted evaluator. No client/server split, no hidden state model,
no network protocol. GDL is Datalog. Ludii is a monolithic Java runtime.
Neither can run in a browser or talk to a game server.

**The platform operators** (Board Game Arena, 500+ games) built game servers
with full rules enforcement. But every game is an imperative PHP module
written against their proprietary framework. The rules live in server code,
not in a portable description. The client is dumb — it renders what the
server tells it. You can't validate a move locally, highlight legal targets,
or play offline. And you can't take your game to another platform.

**The tabletop simulators** (Vassal, Tabletop Simulator, Screentop.gg) built
shared digital surfaces. Vassal has been battle-tested since 2003 with
sophisticated component models (counters, cards, maps, overlays). Tabletop
Simulator lets you flip tables in VR. But none of them enforce rules. They're
shared whiteboards where players self-police. You can't run a rated
tournament on a system that can't detect an illegal move.

**The component catalogers** (The Game Crafter, Tabletopia) built exhaustive
taxonomies of physical game pieces — 2,967 components, 92 meeple shapes,
dimensions in millimeters. Tabletopia added 3D rendering with real-world
scale. But they describe *things*, not *rules*. A catalog entry for a chess
pawn tells you it's 34mm tall. It doesn't tell you it moves forward one
square, captures diagonally, promotes on the eighth rank, and can be taken
en passant.

The gap is in the middle. Nobody combined declarative game rules + an
explicit client/server trust boundary + a visibility model (public/private/
hidden) + a component ontology + a network protocol into a single system.
Each camp had part of the answer. The AI researchers had the right formalism
but the wrong deployment target. The platform operators had the right
deployment target but locked the rules in server code. The tabletop
simulators had the right UX intuition but no enforcement. The catalogers had
the right component model but no game logic.

Baize synthesizes these: GDL's relational state model and GDL-II's
visibility tiers. Ludii's composable movement primitives. TAG's component
taxonomy. BGA's static-material/dynamic-state separation. Screentop's
instantiation hierarchy. And then adds the piece none of them had: an
**authority declaration** that tells clients what they can validate locally
and tells servers what they must enforce. That's the novel contribution.

The idea is older than any of these systems. In 1991, the creator played
RoboRally — a board game where players secretly program robot movements,
then the board resolves them simultaneously — and immediately tried to write
an internet multiplayer version that could run itself. The game had
declarative movement (programmed cards), hidden simultaneous actions (sealed
orders), and deterministic resolution (conveyor belts, lasers, pits). It was
begging for a server that understood the rules. The technology wasn't there.
TCP/IP was exotic, browsers didn't exist yet, and "run the same logic on
client and server" meant shipping C source code. Thirty-five years later,
every missing piece — WebSocket, WASM, JSON Schema, Web Components — is a
baseline platform feature, and the four communities that each solved a
quarter of the problem have published enough prior art to steal from. The
platform is finally ready.

## Architecture: Three Tiers

**Tier 1 — Declarative Schema + CEL + Perturbers** (~90% of games). JSON
game definitions validated against JSON Schema (draft 2020-12). Describes
zones, components, movement primitives, visibility, win conditions.
[CEL](https://github.com/google/cel-spec) expressions evaluate end
conditions and movement constraints. Structured perturber effects handle
state mutations (captures, chain reactions, puzzle moves) with guaranteed
termination. Game definitions can declare a `library` of named CEL
expressions and perturber sequences.

**Tier 2 — WASM Extensions** (~10%). For logic too complex for Tier 1:
complex scoring (tile-placement field scoring, Go territory), graph
algorithms (connection games, supply lines), chain reactions requiring
flood fill (Go captures). Same WASM binary runs on client and server.
Deterministic, sandboxed, no I/O.

**Tier 3 — Trust Services** (irreducible minimum — but the provider is
replaceable). Hidden state, randomness, move sequencing, conflict
resolution. For perfect-information games the server is just a notary.

For imperfect-information games, the default is a trusted server. But
the authority declaration is a transport-independent interface — it
describes *what trust is needed*, not *who provides it*. Every
`server_only` operation has a known cryptographic replacement:
commit-reveal for dice rolls (2 rounds), mental poker for card shuffling
(SRA 1979, Barnett & Smart 2003), commit-reveal for simultaneous moves.
The schema doesn't change between a trusted server and a peer-to-peer
cryptographic protocol. Commit-reveal for randomness ships in the
earliest releases to hold the protocol space open in every client
implementation, even before full mental poker support.

## Status

Core engine complete. 333 of 358 issues closed. Sixty-one games
defined, twenty-one fully playable end-to-end. Texas Hold'em poker
now playable with full betting, hand evaluation, and showdown.
The engine parses and validates game definitions, manages runtime
state, generates legal moves, evaluates CEL expressions for
win/constraint conditions, applies state transitions with a
structured perturber language, and produces BLAKE3 hash-chained
event logs. Commit-reveal protocol (SHA-256) and simultaneous move
collection implemented in both engines. Cross-implementation test
vectors ensure the Rust and Python engines produce identical results.
Comprehensive defensive hardening: constant-time crypto, input
validation, fuel limits, WASM sandboxing, resource budgets, and
fuzzing infrastructure. Felt compiler complete — a pure, total,
board-native DSL for game extensions, compiles to WASM GC (127 tests,
35 builtins wired as host imports).
Grid storage supports both dense (Vec) and sparse (HashMap) backends
with auto-selection. Grid cell stacking with configurable limits.
Partnership declarations with team win propagation. Dynamic visibility
transitions triggered by phase changes. Fog of war with per-cell
per-player visibility (unexplored/visible/fogged), vision range
computation, and cell-level state filtering. Action triggers with
claim windows for reactive turns (Mahjong chi/pon/ron, Uno jump-in,
auction raise-or-pass).

Wargame primitives implemented: terrain movement costs, combat
resolution tables, and zones of control as Felt extensions with a
new `cell_property` builtin. Polymorphic type variables in the Felt
type checker. Resource system for external data: game definitions
declare named resources (word lists, lookup tables), engine loads
them at game start, `word_valid` Felt builtin for dictionary
validation (Scrabble). Mental poker protocol implemented: SRA
commutative encryption (RFC 3526 2048-bit MODP), N-player encrypted
shuffle with BLAKE3 hash chain, selective decryption deal, showdown
key reveal with tamper detection, authority-aware trust mode dispatch.

| Component | Tests | What works |
|-----------|-------|-----------|
| Schema (5 JSON Schemas) | — | Game definitions, state, actions, events, component registry |
| Rust engine | 329 | Parse, validate, state machine, move gen, transitions, CEL end conditions, perturber effects (cycle, remove, flip, promote, counters, invoke), commit-reveal, simultaneous phases, action triggers with claim windows, mental poker (SRA commutative encryption, N-player shuffle, selective deal, showdown verification), hash-chained events, tamper detection, visibility filtering, dynamic visibility transitions, fog of war (per-cell per-player), valid_cells grid mask, graph zone, sparse/dense grid storage, cell stacking with limits, partnerships with team win propagation, hostile input rejection, invariant guards, fuel limits, resource budgets, serialization round-trips, cross-engine determinism |
| Python engine | 3,690 | Feature-parallel with Rust, plus game analysis, Jupyter notebook, terminal CLI, interactive REPL, agent framework (Random/Greedy/MCTS), notation adapter, adversarial input tests, error leak audit, hypothesis fuzzing, cross-engine determinism, poker (hand evaluator, betting FSM, showdown), sparse/dense grid storage, cell stacking, partnerships, dynamic visibility, fog of war, action triggers with claim windows, 58 game definitions with gameplay tests |
| Server | 130 | Room management, WebSocket protocol, hidden-state vault (ChaCha20Rng), per-player visibility, rate limiting, token auth, spectator isolation, persistence, WASM sandboxing (fuel + memory caps), abuse resistance, protocol hardening, claim window timeouts, cell_property host import, debug redaction, graceful shutdown, Felt host imports |
| Felt compiler | 127 | Lexer (logos), parser (chumsky), type checker with polymorphic type variables, call graph checker, WASM GC codegen (wasm-encoder), 37 builtins wired as host imports, CLI (compile/check), host import API, example extensions (poker, chess, go, wargame terrain/CRT/ZOC), word_valid for dictionary resources |
| Client (TypeScript) | 86 | Full type definitions for all schemas (game state, actions, events, registry, effects); Web Components (`<baize-game>`, `<baize-board>`, `<baize-hand>`, `<baize-clock>`, `<baize-score>`); WASM engine wrapper; WebSocket connection with auto-reconnect; server message validation with prototype-pollution defense; drag-and-drop board interaction; Go-style intersection rendering; stacking visualization |

### Tools

```bash
python -m baize.repl [game.json]             # interactive engine REPL
python -m baize.cli <server_url> <room_id>   # terminal game client
```

The REPL loads game definitions locally — step through moves, inspect
state, test CEL expressions, run perturber effects, undo. No server
required. The CLI connects to a running server via WebSocket.

### Non-goals

Out-of-band player communication (chat, voice, emoji) is out of scope.
Baize handles game state, rules, and trust. Player communication belongs
in external tools.

## Game Catalog

Sixty-one reference game definitions spanning the complexity spectrum.
Game rules are not subject to intellectual property protection. All
trademarked names are used here in their descriptive sense to identify
the games whose rules are implemented. Games marked ✓ are fully
playable end-to-end with tests. Games marked `def` have a JSON
definition that parses and validates. Planned games have beads issues
tracking their implementation.

### Playable

| Game | Information | Notable features |
|------|------------|-----------------|
| Tic-Tac-Toe | Perfect | Simplest definition; library CEL expressions; zero server authority |
| Connect Four™ | Perfect | 7×6 grid, gravity drop placement, CEL `lines_4` window detection |
| Pig | Perfect + random | Push-your-luck dice, multi-action turns, counter-based scoring |
| Battleship™ | Imperfect | Hidden ship placement, multi-cell spans, hit/miss/sunk tracking |
| Rock Paper Scissors | Imperfect | Simultaneous phases, commit-reveal (SHA-256), best-of-3 |
| High Card | Imperfect | Deck shuffle/deal pipeline, private hands, rank comparison |
| Go | Perfect | 9×9/19×19, flood-fill captures, ko rule, suicide, territory scoring |
| Othello™ / Reversi | Perfect | 8-direction bracket flipping, legal move detection, disc count scoring |
| Checkers | Perfect | Hop captures, multi-jump chains, mandatory captures, king promotion |
| Snakes & Ladders | Perfect + random | TrackZone, d6 dice, snake/ladder triggered effects, bounce-back |
| Yahtzee™ | Perfect + random | 5d6, keep/re-roll, 13 scoring categories, upper bonus |
| Liar's Dice | Imperfect | Hidden per-player dice, escalating bids, challenge/reveal, elimination |
| Backgammon | Perfect + random | 24-point track, hitting/bar, re-entry, bearing off, doubles |
| Chess | Perfect | All pieces, castling, en passant, promotion, check/checkmate/stalemate, repetition, 50-move, insufficient material |
| Hex | Perfect | Hex grid, 6-neighbor adjacency, BFS edge-to-edge connectivity win |
| Chinese Checkers | Perfect | 121-position hexagram via valid_cells mask, hex_6 adjacency, step/hop, multi-hop chains |
| Blokus™ | Perfect | 20×20 grid, 21 polyomino shapes, rotation/flip, corner-only adjacency |
| Polyiamond Placement | Perfect | 486-cell hex triangular grid, D6 symmetry, 22 polyiamond pieces |
| Ogre™ | Perfect | 22×15 hex wargame, Ogre Mk III subsystem targeting, CRT combat, GEV hit-and-run, overrun |
| Rubik's Cube™ | Perfect | Single-player puzzle, 6-zone cycle perturbers, solved-state CEL |

### Definition exists (parse + validate, with gameplay tests)

| Game | Information | Notable features |
|------|------------|-----------------|
| Texas Hold'em | Imperfect | Betting FSM, hand evaluator (7-card best-of-21), server deal/burn/reveal phases, showdown with pot distribution |
| Risk™ | Imperfect | 12 territories, 3 continents, dice combat, reinforcement/fortification phases |
| Pandemic™ | Imperfect | Cooperative, 12 cities, disease cubes, outbreaks, cure mechanics |
| Ticket to Ride™ | Imperfect | 10-city route network, train card deck, route claiming/scoring |
| Carcassonne™ | Imperfect | 30 tiles with edge matching, meeple placement, city/road/monastery scoring |
| Clue™ | Imperfect | 9 rooms + hallways graph, hidden envelope, deduction, secret passages |
| Scotland Yard™ | Imperfect | 20-location transit network, hidden Mr. X movement, reveal turns |
| Diplomacy™ | Imperfect | 12 territories, simultaneous secret orders, support/strength resolution |
| Settlers of Catan™ | Imperfect | 7-hex resource map, graph settlement placement, dice production, bank trading |
| Colossal Cave Adventure | Perfect | 17-room graph text adventure, obstacles, treasures, single player |
| Colossal Cave Adventure (350) | Perfect | 46-room expanded version, lamp battery, darkness, 10 treasures, 350 points |
| Shogi | Perfect | 9×9, piece drops (captured pieces return to play), directional movement, promotion |
| Xiangqi | Perfect | 9×10, river/palace constraints, cannon jump-capture, flying general |
| Mancala | Perfect | 14 pits, seed-sowing distribution, captures, extra turns |
| Mahjong™ | Imperfect | 4-player, 136 tiles, interrupt claiming (chi/pon/ron), yaku scoring |
| Dominoes | Imperfect | 28 tiles (double-six), chain topology, end matching |
| Bridge | Imperfect | 4-player partnership, auction bidding, dummy hand exposure, trick-taking |
| Stratego™ | Imperfect | 10×10, hidden piece ranks, simultaneous placement, combat reveal |
| Mastermind™ | Imperfect | Code-breaking, structured feedback (black/white pegs), information-theoretic deduction |
| Hanabi™ | Imperfect | Cooperative, reverse hidden info (see others not yourself), constrained clues |
| Nine Men's Morris | Perfect | 24 intersections, phase transition (place → slide), mill captures, flying |
| Quarto™ | Perfect | 4×4, opponent chooses your piece, 4-in-a-row by shared property |
| Dots and Boxes | Perfect | Dot grid, edges as playable positions, box completion, chain reactions |
| Abalone™ | Perfect | 61-cell hex, push chains of marbles off the edge |
| Hive™ | Perfect | Boardless — pieces form the board, insect movement, one-hive rule |
| Scrabble™ | Imperfect | 15×15 premium grid, dictionary validation, cross-word formation |
| Azul™ | Imperfect | Factory tile drafting, pattern building, adjacency scoring |
| Cribbage | Imperfect | Pegging phase (running total to 31), combinatorial hand scoring, pegboard |
| Hearts | Imperfect | 4-player trick avoidance, shoot-the-moon gambit, card passing |
| Gin Rummy | Imperfect | Deadwood optimization, knocking, undercut, layoff |
| Uno™ | Imperfect | 108-card color-matching, Skip/Reverse/Draw Two/Wild effects, direction reversal, 2-10 players |
| Skip-Bo™ | Imperfect | 162-card sequential building piles, stockpile race, wild cards, 4 personal discard stacks, 2-6 players |
| Nim | Perfect | Multiple heaps, Sprague-Grundy theory, mathematically solved |
| Infinite Go | Perfect | Unbounded sparse board, superko rule, capture-only scoring |
| Power Grid™ | Imperfect | City network graph, auction economy, resource market, Dijkstra path costs |
| Fury of Dracula™ | Imperfect | Hidden movement on European map, asymmetric teams, trail mechanic, day/night cycle |
| Triangle Dominoes | Imperfect | Triangular tiles on sparse hex grid, edge matching, region scoring |
| Chickenfoot Dominoes | Imperfect | Dynamic graph branching layout, double-nine set, chickenfoot fork rule |
| Hex Wargame | Perfect | 20×15 hex grid, mixed terrain (cell_properties), CRT combat, ZOC, IGOUGO phases, Felt wargame extensions |
| Global Thermonuclear War | Imperfect | 40 cities (20/side), ICBM/SLBM/bomber allocation, ABM defense, simultaneous sealed orders, commit-reveal launch, mutual destruction. A strange game. |

™ marks identify trademarks of their respective owners. Used here
descriptively to identify the game rules implemented, not to imply
endorsement or affiliation.

## Component Registry

49 reusable component definitions in `registry/`:

- **Cards** (12): French 52/54/32/36, German 36, Swiss-German 36, Spanish 40/48, Italian 40, Tarot 78, Hanafuda 48, Mamluk 52
- **Dice** (11): d2 (coin), d4, d6, d8, d10, d12, d20, d100, Fudge/FATE, direction, color
- **Pieces** (7): Chess, Go stones, Xiangqi, Shogi, Janggi, Checkers, Backgammon
- **Boards** (9): Chess 8x8, Go 19/13/9, Backgammon, Xiangqi, Hex 11, Cribbage, Checkers
- **Tiles** (6): Dominoes (double-six/nine/twelve), Mahjong 144/136, English letter tiles
- **Tokens** (4): Poker chips, Meeples, Resource cubes, Victory points

## Quick Start

```bash
# Rust engine
cd engine && cargo test

# Python engine
cd python && python3 -m pytest tests/ -v

# Server
cd server && cargo build
cargo run  # listens on 0.0.0.0:8080

# TypeScript client (86 tests)
cd client && npm test
```

## Key Documents

- `DESIGN.md` — Architecture, trust boundaries, prior art analysis, decided and open questions
- `EXAMPLES.md` — Full schema examples (chess, poker, Tile Kingdoms, Naval Battle, tic-tac-toe)
- `COMPONENTS.md` — Standard component registry specification
- `PRIOR-ART.md` — Survey of 12 existing systems and what Baize borrows from each
- `BINDING-SCENE.md` — Optional binding to JMAP Scene
- `PRFAQ.md` — Product vision and aspirational roadmap

## Project Layout

```
schema/          JSON Schema definitions (draft 2020-12)
games/           Reference game definitions
registry/        Reusable component definitions (cards, dice, pieces, boards)
engine/          Rust core engine (native + WASM via wasm-bindgen)
python/          Python reference implementation (3.12+, strict mypy)
server/          Axum WebSocket game server
client/          TypeScript Web Components
tests/vectors/   Cross-implementation test vectors
```

## License

Three-tier license structure:

| What | License | Share source? |
|------|---------|--------------|
| Game schema / JSON definitions | CC-BY-SA 4.0 | Attribution + share-alike |
| Engine embedded in your game client | MIT | No |
| Engine embedded in your mobile app | MIT | No |
| WASM module loaded in browser | MIT | No |
| Reference server code and all derivatives | AGPL-3.0 | Yes |

The AGPL applies to the reference server (`server/`) and any work
derived from it. If you build a game server using this code — whether
you fork it, wrap it, or deploy it as a service — you must share your
server source code. This is intentional: the server holds hidden state
and enforces trust, so players deserve to verify it.

The engine and client libraries are MIT — embed them anywhere, no
strings attached.

**Your game definitions** (the JSON files describing your game) are yours to
license however you want. We recommend CC-BY-SA or something similarly
permissive — a client needs to fetch and parse your schema to play your game.
