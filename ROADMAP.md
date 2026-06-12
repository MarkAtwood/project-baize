# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Status: Core Engine Complete

All engine, server, protocol, agent, and testing infrastructure is
done. 123 of 135 issues closed. Remaining work is notation adapters,
platform-specific clients, and the Rubik's Cube game definition.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1 — Declarative (JSON game definitions)              │
│  CEL predicates · Movement primitives · Perturber language  │
├─────────────────────────────────────────────────────────────┤
│  Tier 2 — WASM Extensions (optional complex logic)         │
├─────────────────────────────────────────────────────────────┤
│  Tier 3 — Trust Services (server: hidden state, RNG, auth) │
└─────────────────────────────────────────────────────────────┘
```

## Open Work

### Ready (no blockers)

- **baize-7df** (P3) — **Rubik's Cube game definition** — 5 of 6
  sub-issues closed (cycle primitive, face rotations, single-player,
  solved-state CEL, scramble). Blocked only on notation (baize-wt9).
- **baize-uei** (P3) — **Game notation adapter** — Human-readable move
  input/output (chess algebraic, Go coordinates, Singmaster). Declarative
  JSON spec + WASM escape hatch. Blocks 6 game-specific notation issues.
- **baize-i9s** (P3) — **Interactive engine REPL** — Python REPL for
  local game exploration. Load definitions, step through moves, test CEL
  expressions, run perturber effects. `python -m baize.repl`
- **baize-bu6** (P2) — **Named compound perturber effects** — Schema
  support for game definitions to declare libraries of named perturber
  sequences (e.g., Rubik's Cube moves as reusable named effects).
- **baize-042** (P3) — **Native mobile client** (iOS/Android)
- **baize-rkf** (P4) — **Desktop standalone client**

### Blocked

- **baize-wt9** (P3) — Singmaster notation — blocked on baize-uei
- 5 other notation issues — blocked on baize-uei

## Completed Work (123 issues)

### Engine (Rust + Python)

- **JSON Schema** (baize-0a0) — Game definition, component registry,
  game state, move/action schemas (4 tasks)
- **Rust core engine** (baize-ah1) — Parser, state, moves, transitions,
  WASM bindings (5 tasks). 153 tests.
- **Python reference engine** — Strict mypy, dataclasses, mirrors Rust.
  259 tests.
- **CEL integration** (baize-1ye, baize-82w, baize-wf3) — Rust
  cel-interpreter + Python built-in evaluator (.exists/.all/.filter/
  .size). Grid serialized as composable lines/rows/cols/diags +
  type_rows/type_cols + zone_uniform_<name> booleans. Win conditions:
  `lines.exists(line, line.all(cell, cell == current_player))`.
  Per-zone uniform-type checks for puzzle games (Rubik's Cube).
- **Movement primitives** (baize-olc) — Step, slide, leap, hop,
  remove, swap, promote, draw, flip.
- **Perturber language** (baize-3a3) — Structured effect AST:
  sequence, if/then/else, for_each, repeat(n), repeat_until_stable
  with fuel budget. Termination guaranteed by construction.
  Primitives: remove, flip, promote, cycle, add_counter, set_counter.
- **Cycle perturber** (baize-57v) — Cross-zone position rotation.
  Subsumes transfer and swap. Foundation for Rubik's Cube face rotations
  (5 cycles per move × 18 moves, all verified with identity tests).
- **Single-player support** (baize-0b1) — Engine handles 1-player games
  (advance_turn with modular arithmetic, no opponent assumptions).
- **7 game definitions** — Tic-Tac-Toe, Chess, Texas Hold'em,
  Tile Kingdoms, Go, Backgammon, Naval Battle.
- **Naval Battle** — Multi-cell ship spans, per-player hidden grids,
  hit/miss/sunk tracking via perturber effects.
- **Rubik's Cube subsystems** — Cycle primitive, face rotations (all 18
  moves), solved-state CEL end condition, scramble generation.
- **Cross-implementation test suite** (baize-562) — Legal moves, state
  transitions, visibility, round-trip, primitives parity.

### Server

- **Axum WebSocket server** (baize-aca) — Hidden state vault,
  ChaCha20Rng randomness, move sequencing/validation.
- **Persistence** (baize-z6r) — Abstract Store trait + FileStore.
- **Auth** (baize-e3s) — Token-based player identity with reconnection.
- **Protocol** (baize-7ce) — Hello/welcome handshake with protocol
  versioning and client type declaration.
- **CI** (baize-fk5) — GitHub Actions: Rust clippy/test, Python
  mypy/pytest, TypeScript tsc. All green.

### Clients

- **TypeScript Web Components** (baize-7vp) — `<baize-game>`,
  `<baize-board>`, drag/drop, WebSocket manager.
- **Terminal client** (baize-1yb) — ASCII board, text commands.
  `python -m baize.cli`
- **Headless bot client** (baize-5vf) — Python WebSocket client.

### Agent Stack

- **Agent framework** (baize-a9j) — Agent ABC with play() loop.
- **Agent SDK** (baize-a0o) — AgentSession: local move enumeration.
- **Reference agents** (baize-9wj) — RandomAgent, GreedyAgent
  (capture-first), MCTSAgent (UCB1 + random playout).

### Security and Hardening (16 issues)

- Three P0 fixes (hidden state leak, RequestRandom auth bypass,
  DoS vectors)
- Input validation, spectator isolation, protocol hardening,
  bounded channels, defensive audits, wasmtime upgrade (14 CVEs)
- **Defensive programming pass**: perturber bounds (MAX_REPEAT,
  MAX_FOREACH_ITEMS, MAX_CYCLE_LEN, checked counter arithmetic),
  CEL complexity limits (MAX_CEL_LENGTH, grid context cap), protocol
  validation (zone/component/promote_to against definition), unwrap
  elimination, client message field validation

### Design Decisions

- **CEL predicate boundary** (baize-7a2) — Pure state queries only.
  Hypotheticals → WASM. Three tiers: CEL = what's true now, WASM =
  what happens if, Agent = is there a winning strategy.

### Testing

- **Full-game integration tests** — Complete tic-tac-toe games
  (win/draw/resign) through both engines
- **Rubik's Cube rotation tests** — All 6 CW moves verified with
  4× identity, CW+CCW identity, 20-sticker count, sexy move
  (R U R' U')⁶ = identity, solved-state detection
- **Server smoke test** — End-to-end: create room, two bots play,
  verify winner, test token reconnection
- **443 automated tests** across Rust engine (153), Rust server (31),
  Python engine (259)

## Summary

| Status | Count |
|--------|-------|
| Open | 12 |
| Closed | 123 |
| **Total** | **135** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
