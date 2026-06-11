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

**Tier 1 — Declarative Schema** (~90% of games). JSON game definitions
validated against JSON Schema (draft 2020-12). Describes zones, components,
movement primitives, visibility, win conditions. Data only — parsed, not
executed.

**Tier 2 — WASM Extensions** (~10%). For logic too complex for declarative
predicates: scoring (Carcassonne fields), chain reactions (Othello flips),
custom validation (checkmate). Same WASM binary runs on client and server.
Deterministic, sandboxed, no I/O.

**Tier 3 — Server Authority** (irreducible minimum). Hidden state (deck
order), cryptographic randomness (ChaCha20Rng), move sequencing, conflict
resolution. For perfect-information games the server is just a notary.

## Status

Active development. The engine parses and validates game definitions, manages
runtime state, generates legal moves (step/slide/leap/hop primitives),
applies state transitions, and produces BLAKE3 hash-chained event logs.
Cross-implementation test vectors ensure the Rust and Python engines produce
identical results.

| Component | What works | What's next |
|-----------|-----------|-------------|
| Schema (5 JSON Schemas) | Game definitions, state, actions, events, registry | Formalize constraint expressions |
| Rust engine (77 tests) | Parse, validate, state machine, move gen, transitions, hash-chained events, tamper detection | Full movement evaluation, WASM extension hosting |
| Python engine (121 tests) | Feature-parallel with Rust: parse, validate, state, moves, transitions, events, game analysis, Jupyter notebook integration | Visibility filtering, game tree search |
| Server (Axum/WebSocket) | Room management, protocol dispatch, hidden-state vault, rate limiting, per-IP connection limits | Authentication, matchmaking, spectator delay |
| Client (TypeScript) | Full type definitions for all schemas | Web Components rendering (`<baize-game>`) |

## Game Definitions

Six reference games spanning the complexity spectrum:

| Game | Information | Zones | Notable features |
|------|------------|-------|-----------------|
| Tic-Tac-Toe | Perfect | 3x3 grid | Simplest possible definition; zero server authority needed |
| Chess | Perfect | 8x8 grid | 6 piece types, step/slide/leap/castle primitives, promotion, 5 end conditions |
| Go | Perfect | 19x19 grid | Intersection play, star points; WASM required for ko/scoring |
| Backgammon | Perfect + random | 24-point track | Dice-driven movement, bar, bearing off |
| Texas Hold'em | Imperfect | Deck + hands + community | 6 phases, betting rounds, server-only shuffle/deal/reveal |
| Carcassonne | Imperfect | Dynamic grid | Growing board, 71-tile draw pile, meeple placement; WASM for field scoring |

## Component Registry

Reusable component definitions in `registry/`:

- **Cards**: French 52-card deck, French 54-card deck (with jokers)
- **Dice**: d6, d20
- **Pieces**: Chess set, Go stones
- **Boards**: Chess 8x8, Go 19x19
- **Tiles**: Double-six dominoes
- **Tokens**: Poker chips

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
- `EXAMPLES.md` — Full schema examples (chess, poker, Carcassonne, Battleship, tic-tac-toe)
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

| What you're building | License | Share source? |
|---------------------|---------|--------------|
| Game schema / JSON definitions | CC-BY-SA 4.0 | Attribution + share-alike |
| Engine embedded in your game client | MIT | No |
| Engine embedded in your mobile app | MIT | No |
| WASM module loaded in browser | MIT | No |
| Your game server using Baize | AGPL-3.0 | Yes |
| Your standalone desktop client | AGPL-3.0 | Yes |
| Your fork of the reference server | AGPL-3.0 | Yes |

**Your game definitions** (the JSON files describing your game) are yours to
license however you want. We recommend CC-BY-SA or something similarly
permissive — a client needs to fetch and parse your schema to play your game.
