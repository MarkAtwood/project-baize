# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Status: Core Engine Complete

All engine, server, protocol, agent, and testing infrastructure is
done. 111 of 113 issues closed. Only platform-specific client ports
remain.

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

## Open Work (2 issues)

**baize-042** (P3) — **Native mobile client (iOS/Android)**

**baize-rkf** (P4) — **Desktop standalone client**

Both are platform-specific UI projects independent of the core engine.

## Completed Work (111 issues)

### Engine (Rust + Python)

- **JSON Schema** (baize-0a0) — Game definition, component registry,
  game state, move/action schemas (4 tasks)
- **Rust core engine** (baize-ah1) — Parser, state, moves, transitions,
  WASM bindings (5 tasks). 109 tests.
- **Python reference engine** — Strict mypy, dataclasses, mirrors Rust.
  213 tests.
- **CEL integration** (baize-1ye, baize-82w, baize-wf3) — Rust
  cel-interpreter + Python built-in evaluator (.exists/.all/.filter/
  .size). Grid serialized as composable lines/rows/cols/diags +
  type_rows/type_cols. Win condition:
  `lines.exists(line, line.all(cell, cell == current_player))`.
- **Movement primitives** (baize-olc) — Step, slide, leap, hop,
  remove, swap, promote, draw, flip.
- **Perturber language** (baize-3a3) — Structured effect AST:
  sequence, if/then/else, for_each, repeat(n), repeat_until_stable
  with fuel budget. Termination guaranteed by construction.
- **6 game definitions** — Tic-Tac-Toe, Chess, Texas Hold'em,
  Carcassonne, Go, Backgammon.
- **Cross-implementation test suite** (baize-562) — Legal moves, state
  transitions, visibility, round-trip, primitives parity (43 tests).

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
  MAX_FOREACH_ITEMS, checked counter arithmetic), CEL complexity
  limits (MAX_CEL_LENGTH, grid context cap), protocol validation
  (zone/component/promote_to against definition), unwrap elimination,
  client message field validation

### Design Decisions

- **CEL predicate boundary** (baize-7a2) — Pure state queries only.
  Hypotheticals → WASM. Three tiers: CEL = what's true now, WASM =
  what happens if, Agent = is there a winning strategy.

### Testing

- **Full-game integration tests** — Complete tic-tac-toe games
  (win/draw/resign) through both engines
- **Server smoke test** — End-to-end: create room, two bots play,
  verify winner, test token reconnection
- **365 automated tests** across Rust engine (109), Python engine
  (213), and cross-implementation parity (43)

## Summary

| Status | Count |
|--------|-------|
| Open | 2 |
| Closed | 111 |
| **Total** | **113** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
