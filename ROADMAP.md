# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Status: Production-Ready

340 of 368 issues closed. Core engine, server, and web client are
complete. 64 game definitions. Remaining work is the demo-ready
deployment (container, served web client, playable lobby UI), Flutter
native clients, tooling, and experimental bridges.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1 — Declarative (JSON game definitions)              │
│  CEL predicates · Movement primitives · Perturber language  │
├─────────────────────────────────────────────────────────────┤
│  Tier 2 — WASM Extensions (optional complex logic)         │
│  Felt compiler (127 tests, 38 host imports)                │
├─────────────────────────────────────────────────────────────┤
│  Tier 3 — Trust Services (server: hidden state, RNG, auth) │
│  Mental poker (SRA) · Commit-reveal · Fog of war           │
└─────────────────────────────────────────────────────────────┘
```

## Open Work (28 issues)

- **P2** — **Demo-ready epic** (7 issues) — Docker multi-stage server
  build, container image on ghcr.io, server serving the static web
  client, `GET /rooms/{id}`, playable lobby and game UI from the
  existing Web Components, end-to-end smoke test.
- **P3** — **Flutter native clients epic** (16 issues) — one codebase
  for iOS, Android, and desktop: scaffold and WebSocket connection,
  state model, board/hand/track/graph widgets, auto-layout, drag-and-drop
  input, lobby, reference game screens, Rust engine FFI for offline
  play, CI builds. Supersedes the separate native mobile and desktop
  client issues.
- **P3** — **Game definition generator** — Ludii/BGG pipeline for
  automated game definition authoring.
- **P4** — **Adopt WASI-Crypto when stable** — Swap mental poker
  backend from custom SRA to standardized WASI-Crypto host calls.
- **P4** — **Text adventure parser** — WASM extension for IF-style
  natural language command parsing.
- **P4** — **Interactive Fiction bridges** (3 issues) — Z-machine
  interpreter, ZIL translator, Inform 7 bridge.

## Completed Work (340 issues)

### Engine (Rust + Python)

- **JSON Schema** — Game definition, component registry, game state,
  move/action schemas. Draft 2020-12.
- **Rust core engine** — Parser, state, moves, transitions, WASM
  bindings. 331 tests.
- **Python reference engine** — Strict mypy, dataclasses, mirrors
  Rust. 3,709 tests.
- **CEL integration** — Rust cel-interpreter + Python built-in
  evaluator. Grid context (lines/rows/cols/diags), zone predicates,
  per-zone uniform-type checks. Complexity limits enforced.
- **Movement primitives** — Step, slide, leap, hop, remove, swap,
  promote, draw, flip.
- **Perturber language** — Structured effect AST: sequence,
  if/then/else, for_each, repeat(n), repeat_until_stable with fuel
  budget. Termination guaranteed by construction.
- **Triggers and claim windows** — Event-driven effect chains with
  player response windows.
- **Resources and dictionaries** — First-class resource tracking and
  key-value storage in game state.
- **Grid systems** — Dense and sparse grids, stacking, hex support.
- **Fog of war** — Dynamic per-player visibility with authority-
  controlled information hiding.
- **Partnerships** — Team-based play with shared visibility and
  coordinated win conditions.
- **Wargame primitives** — Terrain effects, combat results tables
  (CRT), zones of control (ZOC).
- **64 game definitions** — including
  Tic-Tac-Toe, Chess, Go, Infinite Go, Texas Hold'em, Backgammon,
  Naval Battle, and others.
- **Cross-implementation test suite** — Legal moves, state
  transitions, visibility, round-trip, primitives parity.

### Felt Compiler

- **Felt language** — Domain-specific language compiling to WASM
  extensions. 127 tests, 38 host imports. Covers scoring, chain
  reactions, custom validation, and complex game logic.

### Server

- **Axum WebSocket server** — Hidden state vault, ChaCha20Rng
  randomness, move sequencing/validation.
- **WASM sandboxing** — Wasmtime-based extension host with fuel and
  memory limits, behind the optional `wasm-host` feature. Not yet
  called from room code.
- **Rate limiting** — Per-connection and per-room throttling.
- **Persistence** — Abstract Store trait + FileStore.
- **Auth** — Token-based player identity with reconnection.
- **Protocol** — Hello/welcome handshake with protocol versioning
  and client type declaration.
- **Lobby** — `GET /games`, seat selection, ready-up protocol.
- **Mental poker (SRA)** — Commutative encryption for trustless card
  games. Commit-reveal for hidden state without trusted server.
- **CI** — GitHub Actions: Rust fmt/clippy/test for engine, felt and
  server, wasm32 engine build, fuzz target check, MSRV 1.85 check,
  Python mypy/pytest, TypeScript tsc/test/build.

### Clients

- **TypeScript Web Components** — `<baize-game>`, `<baize-board>`,
  drag/drop, WebSocket manager.
- **Terminal client** — ASCII board, text commands.
  `python -m baize.cli`
- **Headless bot client** — Python WebSocket client.

### Agent Stack

- **Agent framework** — Agent ABC with play() loop.
- **Agent SDK** — AgentSession: local move enumeration.
- **Reference agents** — RandomAgent, GreedyAgent (capture-first),
  MCTSAgent (UCB1 + random playout).

### Security and Hardening

- P0 fixes (hidden state leak, RequestRandom auth bypass, DoS
  vectors). Input validation, spectator isolation, protocol
  hardening, bounded channels, defensive audits.
- Perturber bounds, CEL complexity limits, protocol validation,
  unwrap elimination, client message field validation.

## Summary

| Status | Count |
|--------|-------|
| Open | 28 |
| Closed | 340 |
| **Total** | **368** |

---

*Last updated 2026-11-20. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
