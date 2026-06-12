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

Core engine complete. 134 of 175 issues closed. Six games are fully
playable end-to-end. The engine parses and validates game definitions,
manages runtime state, generates legal moves, evaluates CEL expressions
for win/constraint conditions, applies state transitions with a structured
perturber language, and produces BLAKE3 hash-chained event logs.
Cross-implementation test vectors ensure the Rust and Python engines
produce identical results.

| Component | Tests | What works |
|-----------|-------|-----------|
| Schema (5 JSON Schemas) | — | Game definitions, state, actions, events, component registry |
| Rust engine | 153 | Parse, validate, state machine, move gen, transitions, CEL end conditions, perturber effects (cycle, remove, flip, promote, counters, invoke), hash-chained events, tamper detection, visibility filtering |
| Python engine | 391 | Feature-parallel with Rust, plus game analysis, Jupyter notebook, terminal CLI, interactive REPL, agent framework (Random/Greedy/MCTS) |
| Server | 31 | Room management, WebSocket protocol, hidden-state vault (ChaCha20Rng), per-player visibility, rate limiting, token auth, spectator isolation, persistence |
| Client (TypeScript) | — | Full type definitions for all schemas; Web Components (`<baize-game>`, `<baize-board>`) |

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

Twenty reference games spanning the complexity spectrum. Games marked ✓
are fully playable end-to-end with tests. Games marked `def` have a JSON
definition that parses and validates. Planned games have beads issues
tracking their implementation.

### Playable

| Game | Information | Notable features |
|------|------------|-----------------|
| Tic-Tac-Toe | Perfect | Simplest definition; library CEL expressions; zero server authority |
| Four in a Row | Perfect | 7×6 grid, gravity drop placement, 4-in-a-line detection |
| Pig | Perfect + random | Push-your-luck dice, multi-action turns, counter-based scoring |
| Naval Battle | Imperfect | Hidden ship placement, multi-cell spans, hit/miss/sunk tracking |
| Rock Paper Scissors | Imperfect | Simultaneous moves, best-of-3 |
| Rubik's Cube | Perfect | Single-player puzzle, 6-zone cycle perturbers, solved-state CEL |

### Definition exists (parse + validate, not yet fully playable)

| Game | Information | Notable features |
|------|------------|-----------------|
| Chess | Perfect | 6 piece types, step/slide/leap/castle primitives, promotion |
| Go | Perfect | Intersection play; WASM required for captures/scoring |
| Backgammon | Perfect + random | Dice-driven track movement, bar, bearing off |
| Texas Hold'em | Imperfect | Deck/deal/shuffle work; betting/phases/hand ranking in progress |
| Tile Kingdoms | Imperfect | Dynamic grid, 71-tile draw pile; WASM for field scoring |

### Planned (beads filed)

| Game | What it proves |
|------|---------------|
| Checkers | Hop captures, multi-jump chains, repeat_until_stable |
| Reversi | Chain-reaction flipping (the canonical perturber example) |
| Yacht | Multi-phase dice turns, scoring categories |
| Snakes & Ladders | Track zones, dice, triggered position effects |
| Liar's Dice | Hidden dice, bidding, player elimination |
| Hex | Hex grid, graph connectivity win condition |
| Chinese Checkers | Star-shaped triangular lattice, multi-hop |
| Polyomino Placement | 2D multi-cell spans, corner-only adjacency |
| Ogre | Hex wargame — stacking, CRT combat, asymmetric forces |

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

# TypeScript client (type-check only)
cd client && npx tsc --noEmit
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
