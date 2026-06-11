# Baize PRFAQ

## Press Release

**Seattle, WA** — Baize, the open declarative game language, today announced
general availability of its 1.0 specification and reference implementations.
For the first time, board game designers can describe a complete game — its
topology, components, movement rules, visibility model, and win conditions —
in a single JSON file, and have it playable in any browser with one script
tag.

Game designers have long faced a choice: build on a closed platform like
Board Game Arena (and accept its PHP framework, revenue split, and approval
process), use a rules-free sandbox like Tabletop Simulator (and lose all
enforcement), or code everything from scratch. Academic game languages like
GDL and Ludii proved that declarative game descriptions work, but they were
built for AI researchers, not for networked multiplayer play. No existing
system answers the question that matters for online games: *what can the
client compute locally, and what requires a server round-trip?*

Baize answers that question with an explicit authority declaration in every
game definition. The schema tells clients which actions they can validate
locally (piece movement, card plays, placement rules) and which require
server authority (deck shuffling, dice rolls, hidden-state reveals). This
lets clients highlight legal moves, reject illegal actions, and animate
transitions instantly — without waiting for a round-trip — while the server
remains authoritative over hidden state and randomness.

"I wanted to prototype a card game and test it with friends over the
weekend," said a game designer during early access testing. "With Board Game
Arena, that means learning PHP, writing a game module, and waiting for
approval. With Baize, I wrote a JSON file, pointed a `<baize-game>` tag at
it, and we were playing in an hour. When I needed custom scoring logic, I
wrote a small Rust function, compiled it to WASM, and both the client and
server ran the same code."

The Baize architecture is built on three tiers. Tier 1 is the declarative
JSON schema, which covers approximately 90% of game logic: zones (grids, hex
grids, stacks, sets, tracks), components (pieces, cards, dice, tiles,
tokens), composable movement primitives (step, slide, hop, leap, place,
draw), turn structure, and win conditions. Tier 2 is an optional WASM module
for complex logic that exceeds declarative predicates — scoring algorithms,
chain reactions, custom validation — running deterministically on both client
and server. Tier 3 is trust services: hidden state, randomness, move sequencing, and
conflict resolution. The default provider is a trusted server, but every
Tier 3 operation has a known cryptographic replacement — commit-reveal for
dice and simultaneous moves, mental poker for card shuffling — so the
server role is architecturally replaceable by peer-to-peer protocols.

A standard component registry ships with the specification, providing
reusable definitions for common game components: French card decks, standard
dice, chess and Go piece sets, board layouts, domino tiles, and poker chips.
Game designers reference registry entries rather than redefining standard
components, and the registry carries optional physical metadata (dimensions,
material, weight) enabling print-and-play PDF export and manufacturing
integration.

Every state transition produces a BLAKE3 hash-chained event log entry,
creating a tamper-evident record suitable for tournament play. Both the Rust
and Python engines produce identical hashes for the same state, verified by
cross-implementation test vectors. Competitive events can verify game
integrity after the fact without trusting any single server.

The client embedding model requires no framework:

```html
<script src="https://cdn.example.com/baize.js"></script>
<baize-game src="chess.json" server="wss://play.example.com/game/42">
  <baize-board></baize-board>
  <baize-hand player="1"></baize-hand>
  <baize-clock></baize-clock>
</baize-game>
```

One script tag registers Web Components and bundles the WASM engine. Shadow
DOM isolates game styles from the host page. It works in React, WordPress,
raw HTML, or anything that renders DOM. Game designers rearrange child
elements to customize layout without touching game logic.

The specification is licensed CC-BY-SA 4.0. The embeddable engine is MIT,
so game clients — including proprietary and commercial ones — can ship it
without license encumbrance. Servers and standalone clients are AGPL-3.0,
ensuring that anyone running a Baize game server shares their modifications.

Baize is available at github.com/MarkAtwood/baize. The specification,
reference implementations in Rust and Python, a WebSocket game server, and a
TypeScript client are all included.

---

## External FAQ

### What games can Baize describe?

Any turn-based card or board game with discrete state. The six reference
games — Tic-Tac-Toe, Chess, Go, Backgammon, Texas Hold'em, and Carcassonne
— span the spectrum from trivial perfect-information placement games to
complex imperfect-information games with randomness, hidden state, dynamic
boards, and custom scoring. Games with real-time physics (foosball) or
continuous state (flight simulators) are out of scope.

### How is this different from Board Game Arena?

Board Game Arena is a closed platform: you write a PHP game module conforming
to their framework, submit it for approval, and it runs on their servers.
Your game logic is imperative code. Baize is an open specification: you write
a declarative JSON file, host it anywhere, and any compliant client or server
can run it. The engine is embeddable (MIT-licensed) in any application. You
keep full control of hosting, distribution, and monetization.

### How is this different from Tabletop Simulator?

Tabletop Simulator provides a physics sandbox with no rules enforcement. It's
a shared whiteboard where players must self-enforce rules. Baize enforces
rules declaratively — illegal moves are rejected by the client before they
reach the server. This enables competitive play, rating systems, and
tournament integrity verification.

### How is this different from GDL or Ludii?

GDL and Ludii are academic game description languages designed for AI
research. They assume a single trusted evaluator and have no concept of
client/server trust boundaries, network transport, hidden state management,
or browser embedding. Baize borrows their best ideas (relational state from
GDL, movement primitives from Ludii) and wraps them in a practical
architecture for networked multiplayer play.

### Do I need to write code to create a game?

For most games, no. The declarative schema covers zones, components, movement
rules, turn structure, visibility, and win conditions. You write a JSON file
and you're done. For games that need complex logic (custom scoring, chain
reactions, non-trivial win conditions like checkmate), you write a small WASM
module — typically a single Rust function — that runs on both client and
server.

### What about mobile apps?

The Rust engine compiles to native code for iOS and Android via standard
toolchains, and to WASM for browser-based mobile play. The MIT license
permits embedding in proprietary apps without restriction.

### Can I use this for competitive/tournament play?

Yes. Every state transition produces a BLAKE3 hash-chained event log.
Tournament organizers can verify game integrity after the fact by replaying
the event log and checking the hash chain. The server uses ChaCha20Rng for
cryptographically fair randomness. Time controls are enforced server-side
with configurable Fischer increment.

### What about cheating?

Baize's trust model is defense-in-depth. The client validates moves locally
using the declarative schema, providing instant feedback and catching casual
errors. The server independently validates every move against the full state
(including hidden information the client doesn't have). Hidden state never
leaves the server until the schema's visibility rules permit revelation. Rate
limiting, per-IP connection limits, bounded message queues, and move count
caps protect against abuse.

### Can spectators watch games?

Yes. Spectators receive public state only — board positions, scores, move
history. They cannot see private information (players' hands) or submit
moves. Broadcast delay for competitive events is a server transport concern,
not a schema concern.

### Do games require a central server?

Not always. For perfect-information games (chess, Go, checkers), the server
is just a move sequencer — any message ordering mechanism works, including
peer-to-peer WebRTC. For imperfect-information games (poker, Battleship),
the default is a trusted server, but every server-only operation has a known
cryptographic replacement: commit-reveal for dice rolls and simultaneous
moves (2 extra rounds), mental poker for card shuffling and dealing (SRA
1979, Barnett & Smart 2003). The game definition doesn't change between a
trusted server and a peer-to-peer protocol — the authority declaration
describes what trust is needed, not who provides it. Commit-reveal for
randomness ships in the earliest releases to ensure every client has the
protocol space open from day one.

### What browsers are supported?

Any browser with WebAssembly, WebSocket (RFC 6455), inline SVG, and Web
Components (Custom Elements v1, Shadow DOM). This is every major browser
since 2020. No polyfills are provided or supported.

---

## Internal FAQ

### Why JSON and not a custom DSL?

Zero-dependency parsing in every target language. No ambiguity. JSON Schema
provides machine-checkable validation without a custom parser. Every
developer tool already supports JSON (syntax highlighting, linting,
formatting, diffing). The cost is verbosity, which is acceptable for a
machine-read specification.

### Why three licenses instead of one?

The three-tier license (CC-BY-SA / MIT / AGPL) serves three different
constituencies. Game designers need permissive terms for their definitions
(CC-BY-SA). App developers need to embed the engine without copyleft
obligations (MIT) or they won't adopt it. Server operators who benefit from
the community's work should contribute back (AGPL). A single license cannot
serve all three.

### Why WASM for extensions instead of a scripting language?

Determinism. The same WASM binary produces identical results on client and
server — no floating-point divergence, no platform-specific behavior. WASM
also provides sandboxing (no I/O, no network, no filesystem) without a
custom sandbox implementation. And it's a compilation target, not a
language — game developers can write extensions in Rust, C, Go, or
AssemblyScript.

### What's the competitive moat?

The authority declaration — the explicit separation of client-verifiable vs.
server-only operations — is the novel contribution that no existing system
provides. Once game definitions carry this metadata, clients can optimize
aggressively (local validation, optimistic execution, offline play for
perfect-information games) and servers can be minimal. This creates a network
effect: more games described in Baize means more clients and servers
implement the spec, which makes Baize the natural format for new games.

### What are the biggest technical risks?

1. **Schema expressiveness ceiling.** Some game mechanics may resist
   declarative description, requiring WASM for games we expected to be
   Tier 1. Mitigation: the six reference games exercise a wide range of
   mechanics, and the WASM escape hatch is always available.

2. **Cross-implementation consistency.** Two implementations must produce
   identical state hashes for the same inputs. Mitigation: cross-
   implementation test vectors checked in CI, canonical serialization
   order documented and enforced.

3. **Adoption chicken-and-egg.** No games without clients, no clients
   without games. Mitigation: ship reference games (chess, poker) that
   people already want to play, and make the embedding model (`<baize-game>`)
   so simple that integration cost approaches zero.

### What does the server cost to run?

Minimal. For perfect-information games (chess, Go, checkers), the server is
a WebSocket relay that stamps move order — no game logic, no state
computation. For imperfect-information games, the server holds hidden state
and generates randomness, but the computational cost is trivial (a few
hash operations and RNG calls per move). A single commodity server can host
thousands of concurrent games.

### What's the path to 1.0?

1. Stabilize the JSON Schema definitions (game-definition, game-state,
   move-action, event-log, component-registry).
2. Complete movement primitive evaluation in the Rust engine (all 12
   primitives, with constraint expressions).
3. Implement WASM extension hosting (Tier 2) using wasmtime on the server
   and native WASM in the browser.
4. Build the Web Components client (`<baize-game>`, `<baize-board>`,
   `<baize-hand>`, `<baize-clock>`, `<baize-score>`).
5. Ship playable chess and poker as proof points.
6. Write the specification as a standalone document (not just JSON Schema +
   code comments).

### Why does commit-reveal ship before mental poker?

Architectural forcing function. Every client must implement the commit-reveal
message flow (commit hash, acknowledge, reveal, verify) from the first
release. This ensures the protocol space for serverless cryptography exists
in every client from day one. Adding mental poker later is a compatible
extension on top of commit-reveal. Adding commit-reveal later would require
breaking protocol changes in every deployed client.

### Why now?

The three-tier architecture — declarative schema parsed on the client, WASM
modules running deterministically on both sides, thin WebSocket server —
only works because WASM, WebSocket, and Web Components are all baseline
web platform features. Five years ago, WASM support was experimental and Web
Components required polyfills. Today, the platform is ready.

---

> **What is a PRFAQ?** A PRFAQ (Press Release / FAQ) is an Amazon-originated
> product planning technique. It starts with a fictional press release
> written as if the product has already launched successfully, forcing clarity
> on customer benefit and desired outcome. The FAQ section then anticipates
> hard internal and external questions. Writing the press release first
> ensures the team aligns on what success looks like before committing to
> implementation.
