# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Milestone: First Playable Game ✓

Tic-tac-toe is playable end-to-end: browser client connects to server,
two players place marks, someone wins.

## Milestone: Declarative Game Engine ✓

All core engine infrastructure is complete:

- **CEL constraint language** with composable predicates (lines, rows,
  cols, diags, type queries), .exists/.all/.filter/.size support
- **Movement primitives**: step, slide, leap, hop, remove, swap,
  promote, draw, flip
- **Structured perturber language**: sequence, if/then/else, for_each,
  repeat(n), repeat_until_stable with fuel budget. Termination
  guaranteed by construction. Enables Go captures, checkers multi-jump,
  match-3 cascades in Tier 1 without WASM.

## Milestone: Server + Agent Stack ✓

- **Server persistence** (Store trait + FileStore)
- **Token-based player auth** with reconnection
- **WebSocket hello/welcome** capability handshake
- **CI pipeline** (Rust clippy/test, Python mypy/pytest, TypeScript tsc)
- **Headless bot client** + **Agent framework** (Agent ABC, play loop)
- **Agent SDK** (local move enumeration via AgentSession)
- **Reference agents**: RandomAgent, GreedyAgent, MCTSAgent
- **Terminal client** (`python -m baize.cli`)

## Open Work (2 issues)

**baize-042** (P3, feature) — **Native mobile client (iOS/Android)**

**baize-rkf** (P4, feature) — **Desktop standalone client**

Both are platform-specific UI projects (Swift/Kotlin, Electron/Tauri)
independent of the core engine.

## Completed Work (106 issues)

### Engine

**JSON Schema** (baize-0a0) — Game definition, component registry,
game state, move/action schemas.

**Rust Core Engine** (baize-ah1) — Definition parser, state
representation, legal move generator, state transition engine, WASM
bindings. 106 tests.

**Python Reference Implementation** — Strict mypy, dataclasses,
mirrors Rust engine. 206 tests.

**CEL Integration** (baize-1ye, baize-82w, baize-wf3) — cel-interpreter
in Rust, built-in evaluator in Python (.exists/.all/.filter/.size).
Grid serialized as composable lines/rows/cols/diags + type_rows/
type_cols. Tic-tac-toe win condition:
`lines.exists(line, line.all(cell, cell == current_player))`.

**Movement Primitives** (baize-olc) — Remove, swap, promote, draw
transitions + flip/remove/swap move generation.

**Perturber Language** (baize-3a3) — Structured effect AST with
bounded control flow. sequence, if/then/else (CEL predicate),
for_each, repeat(n), repeat_until_stable (fuel budget, fixpoint via
state hash). No while, no recursion.

### Server

**Game Server** (baize-aca) — Axum WebSocket, hidden state vault,
ChaCha20Rng randomness, move sequencing/validation.

**Persistence** (baize-z6r) — Abstract Store trait + FileStore.
Rooms persisted on creation, restored on startup.

**Auth** (baize-e3s) — Token-based player identity with reconnection.

**Protocol** (baize-7ce) — Hello/welcome handshake with protocol
versioning and client type declaration.

**CI** (baize-fk5) — GitHub Actions: 3 parallel jobs, all green.

### Clients

**TypeScript Web Components** (baize-7vp) — `<baize-game>`,
`<baize-board>`, drag/drop, WebSocket connection manager.

**Terminal Client** (baize-1yb) — ASCII board rendering, text commands.

**Bot Client** (baize-5vf) — Headless Python WebSocket client.

### Agent Stack

**Agent Framework** (baize-a9j) — Agent ABC with play() loop.

**Agent SDK** (baize-a0o) — AgentSession bridges server state to
local engine for move enumeration.

**Reference Agents** (baize-9wj) — RandomAgent, GreedyAgent
(capture-first), MCTSAgent (UCB1 + random playout).

### Game Definitions (6)

Tic-Tac-Toe, Chess, Texas Hold'em, Carcassonne, Go, Backgammon.

### Security and Hardening (11)

Three P0 fixes, input validation, spectator isolation, protocol
hardening, bounded channels, defensive audits, wasmtime upgrade.

### Design Decisions

**CEL predicate boundary** (baize-7a2) — CEL functions are pure state
queries only. Hypotheticals belong in WASM extensions.

## Summary

| Status | Count |
|--------|-------|
| Open | 2 |
| Closed | 106 |
| **Total** | **108** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
