# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Milestone: First Playable Game ✓

Tic-tac-toe is playable end-to-end: browser client connects to server,
two players place marks, someone wins. All P0/P1 issues are closed.

## Milestone: CEL + Server + Agent Stack ✓

Full declarative game logic via CEL expressions, server persistence
and auth, headless bot client, agent framework with reference agents
(random, greedy, MCTS), and a terminal client for dev/testing.

## Critical Path: Go

The remaining critical-path item is the structured perturber language
for chain reactions (Go captures, Carcassonne scoring). Everything
else needed for chess-level games is complete:

```
✓ CEL constraints ──→ ✓ Movement primitives ──→ ○ baize-3a3  Perturber language
                            │
                            └──→ ✓ Composable CEL predicates
```

## Open Work (4 issues)

**baize-3a3** (P2, feature) — **Spec structured perturber language**

Structured effect/mutation language composing movement primitives with
control flow (sequence, if/then/else, for_each, choose, repeat,
repeat_until_stable). Bounded fixpoint iteration with fuel budget for
chain reactions. Design target: Go runs entirely in Tier 1 without WASM.

**baize-7a2** (P2, decision) — **CEL predicates are state queries only**

Design decision: CEL functions are restricted to pure queries over
current observable state — O(board_size), guaranteed termination.
Hypotheticals (move simulation, checkmate) belong in Tier 2 WASM
extensions. Three tiers: CEL = what's true now, WASM = what happens
if, Agent/AI = is there a winning strategy.

**baize-042** (P3, feature) — **Native mobile client (iOS/Android)**

**baize-rkf** (P4, feature) — **Desktop standalone client**

## Completed Work (104 issues)

### Milestones

**First Playable Game** — Tic-tac-toe end-to-end: browser client,
WebSocket server, game logic, win/draw detection.

**CEL Integration** (baize-1ye) — CEL expression evaluation for game
conditions in both Rust (cel-interpreter) and Python (built-in
evaluator with .exists/.all/.filter/.size support). Game definitions
use composable CEL syntax: `lines.exists(line, line.all(cell, cell ==
current_player))`.

**Composable CEL Predicates** (baize-82w) — Grid serialized as
lines/rows/cols/diags of owner strings + type_rows/type_cols of
component types. Hardcoded three_in_line replaced with composable
CEL expression. Region-query variables for placement constraints.

**Movement Primitives** (baize-olc) — Remove, swap, promote, draw
transitions + flip/remove/swap move generation in both engines.

**Server Infrastructure** — Persistence layer with abstract Store
trait + FileStore (baize-z6r). Token-based player auth with
reconnection (baize-e3s). WebSocket hello/welcome capability
handshake with protocol versioning (baize-7ce). CI pipeline with
Rust clippy/test, Python mypy/pytest, TypeScript tsc (baize-fk5).

**Agent Stack** — Headless Python bot client (baize-5vf). Agent
abstract base class with play() loop (baize-a9j). Agent SDK bridging
server state to local engine for move enumeration (baize-a0o).
Reference agents: RandomAgent, GreedyAgent, MCTSAgent (baize-9wj).

**Terminal Client** (baize-1yb) — ASCII board rendering, text command
parsing, token reconnection. `python -m baize.cli`.

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
| Open | 4 |
| Blocked | 0 |
| Closed | 104 |
| **Total** | **108** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
