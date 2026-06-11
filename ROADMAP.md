# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Milestone: First Playable Game ✓

Tic-tac-toe is playable end-to-end: browser client connects to server,
two players place marks, someone wins. All P0/P1 issues are closed.

## Critical Path: Chess and Go

CEL constraint language is integrated (baize-1ye ✓). The path to chess
requires the remaining movement primitives. The path to Go additionally
requires the structured perturber language for capture chains:

```
✓ baize-1ye  CEL constraints ──→ ○ baize-olc  Movement primitives ──→ ○ baize-3a3  Perturber language
                                       │
                                       └──→ ○ baize-82w  Composable CEL predicates
```

## Dependency Graph

```
                          ┌─────────────────────────────────┐
                          │         CEL LAYER                │
                          │                                  │
                          │  ○ baize-wf3  Region-query fns   │
                          │  ○ baize-7a2  Design decision    │
                          └─────────────────────────────────┘
                                         ↕ related

○ baize-olc  Movement primitives ──→ ○ baize-82w  Composable CEL predicates
       │
       └──→ ○ baize-3a3  Perturber language

○ baize-z6r  Server persistence ──→ ○ baize-e3s  Auth & player identity

○ baize-7ce  WS capability negotiation ──→ ○ baize-a9j  AI agent framework ──┐
       │                                                                      │
       ├──→ ○ baize-5vf  Bot/headless harness ──→ ○ baize-a0o  Agent SDK ──→ ○ baize-9wj  Reference agents
       │
       ├──→ ○ baize-042  Native mobile client
       └──→ ○ baize-rkf  Desktop client

○ baize-fk5  CI pipeline                     (no blockers)
○ baize-1yb  CLI/terminal client             (no blockers)
```

## Open Work

### Ready (no blockers)

**baize-olc** (P2, feature) — **Implement remaining movement primitives**

Only step/slide/leap/hop are implemented. Implement: draw, move_to/
transfer, swap, remove, promote, castle, flip (as movement trigger).
Also implement hand plays (currently a no-op stub). Both Rust and
Python engines.

Blocks: baize-3a3, baize-82w.

**baize-wf3** (P2, feature) — **CEL region-query functions for placement constraints**

CEL functions for checking uniqueness/exclusion constraints over defined
regions of a grid zone. Enables Sudoku-level validation: "is this a
valid play given what's on the board?" Functions: cells_in(), region_of(),
values_in(), count(). All pure state queries per decision baize-7a2.

**baize-7a2** (P2, decision) — **CEL predicates are state queries only**

CEL functions are restricted to pure queries over current observable
state — O(board_size), guaranteed termination. Hypotheticals (move
simulation, checkmate) belong in Tier 2 WASM extensions.

**baize-z6r** (P2, feature) — **Server persistence layer**

Server state is in-memory only; restart loses all games. Add a
persistence layer so game state and event logs survive restart.
Abstract trait/protocol so the backing store can be swapped.

Blocks: baize-e3s.

**baize-7ce** (P2, feature) — **WebSocket client capability negotiation**

Protocol version, client type (browser/mobile/desktop/bot), supported
features in the handshake. Prerequisite for safely evolving the protocol
across heterogeneous clients.

Blocks: baize-042, baize-5vf, baize-a9j, baize-rkf.

**baize-fk5** (P2, task) — **CI pipeline**

GitHub Actions: cargo test, cargo clippy, cargo build, python pytest,
python mypy, npx tsc --noEmit. Fail on any error.

**baize-1yb** (P4, feature) — **CLI/terminal client**

### Blocked

**baize-82w** (P2, task) — **Replace hardcoded three_in_line with composable CEL functions**

Decompose game-specific predicates (three_in_line, all_cells_occupied)
into composable CEL primitives from the standard function library.

Blocked by: baize-olc.

**baize-3a3** (P2, feature) — **Spec structured perturber language**

Structured effect/mutation language composing movement primitives with
control flow. Bounded fixpoint iteration with fuel budget for chain
reactions. Design target: Go runs entirely in Tier 1 without WASM.

Blocked by: baize-olc.

**baize-e3s** (P2, feature) — **Authentication and player identity**

Token-based auth on WebSocket upgrade. Stable player identity across
reconnections.

Blocked by: baize-z6r.

**baize-a9j** (P3, feature) — **AI player agent framework**

Blocked by: baize-7ce.

**baize-5vf** (P3, feature) — **Bot/headless client harness**

Blocked by: baize-7ce.

**baize-042** (P3, feature) — **Native mobile client (iOS/Android)**

Blocked by: baize-7ce.

**baize-a0o** (P3, feature) — **Agent SDK (Rust + Python)**

Blocked by: baize-5vf, baize-a9j.

**baize-9wj** (P4, feature) — **Built-in reference agents (random, greedy, MCTS)**

Blocked by: baize-a0o.

**baize-rkf** (P4, feature) — **Desktop standalone client**

Blocked by: baize-7ce.

## Completed Work (92 issues)

### Milestones

**First Playable Game** — Tic-tac-toe end-to-end: browser client,
WebSocket server, game logic, win/draw detection.

**CEL Integration** (baize-1ye) — CEL expression evaluation for game
conditions in both Rust (cel-interpreter) and Python (built-in
evaluator). Game definitions use valid CEL syntax. Precomputed game
state variables with legacy fallback.

### Epics

**baize-0a0** — JSON Schema definitions (4 tasks)
**baize-ah1** — Rust core engine (5 tasks)
**baize-aca** — Game server (4 tasks)
**baize-562** — Cross-implementation test suite (4 tasks)
**baize-7vp** — TypeScript Web Components client (4 tasks)

### Game Definitions (6)

Tic-Tac-Toe, Chess, Texas Hold'em, Carcassonne, Go, Backgammon.

### Security and Hardening (11)

Three P0 fixes (hidden state leak, RequestRandom auth bypass, DoS
vectors), plus input validation, spectator isolation, protocol
hardening, bounded channels, defensive audits of both engines.

### Testing and Quality (8)

Vault unit tests, schema validation on load, hash collision resistance,
fuzz testing, tamper detection, mypy and clippy CI tasks, wasmtime
upgrade (14 CVEs resolved).

## Summary

| Status | Count |
|--------|-------|
| Ready | 7 |
| Blocked | 9 |
| Closed | 92 |
| **Total** | **108** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
