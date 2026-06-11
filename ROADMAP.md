# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Critical Path: First Playable Game

The immediate goal is a playable tic-tac-toe: browser client connects
to server, two players place marks, someone wins. This requires three
server features landing before the client can be built:

```
baize-f1l  Evaluate end conditions ──────┐
baize-8ct  Visibility filtering ─────────┼──→ baize-j7a  Minimal playable client
baize-f9t  Game definition loading ──────┘
```

After tic-tac-toe, the path to chess requires the CEL constraint
language and remaining movement primitives. The path to Go requires
the structured perturber language for capture chains:

```
baize-1ye  CEL constraint language ──→ baize-olc  Remaining primitives ──→ baize-3a3  Perturber language
```

## Open Work

### Ready (no blockers)

**baize-f1l** (P1, feature) — **Evaluate end conditions at runtime**

End conditions in game definitions are currently decorative strings
that are never evaluated. Implement end condition checking after each
state transition. Start with tic-tac-toe (three-in-a-row, board-full).
Pre-CEL: hardcoded condition evaluators matching existing game
definitions. Post-CEL: replace with CEL expression evaluation. Both
Rust and Python engines.

**baize-8ct** (P1, feature) — **Visibility filtering on state sync**

Server currently sends full game state to all players including hidden
and private information. Implement per-player state filtering based on
zone visibility declarations (public/private/hidden). Private zones
only visible to owner. Hidden zones omitted from all client responses
(count only). Must filter in both state_sync and move_confirmed
messages.

**baize-f9t** (P1, feature) — **Game definition loading from room creation API**

Server currently auto-creates rooms with a hardcoded placeholder
definition. Add an HTTP endpoint or WebSocket message to create a room
with a specific game definition (JSON body or URI reference). Validate
definition before creating room. Remove the auto-create fallback.

**baize-o8y** (P1, bug) — **Upgrade wasmtime from v29 to fix 14 CVEs**

All 14 Dependabot alerts trace to wasmtime v29.0.1, which is 16 major
versions behind. Two critical sandbox escapes (CVSS 9.0). Feature is
behind an optional flag but needs upgrade before any WASM hosting work.

**baize-1ye** (P2, feature) — **Spec CEL constraint language integration**

Replace free-form constraint strings with CEL (Common Expression
Language) expressions. Define the standard function library for
game-specific predicates (adjacent, in_check, path_clear, liberties,
group, connected, history_contains, etc.). The function library is
the primary extension point for the project — new game mechanics get
supported by adding well-defined CEL functions, not by changing the
schema or language. Needs Rust (cel-rust) and Python (cel-python)
evaluator integration.

Blocks: baize-olc, baize-3a3.

**baize-z6r** (P2, feature) — **Server persistence layer**

Server state is in-memory only; restart loses all games. Add a
persistence layer so game state and event logs survive restart.
The specific database is an implementation detail. Interface should be
abstract (trait/protocol) so the backing store can be swapped. Must
persist: room state, game state, event log. Should support: replay
from event log for recovery.

Blocks: baize-e3s.

**baize-fk5** (P2, task) — **CI pipeline**

No CI/CD pipeline exists. Set up GitHub Actions: cargo test (engine),
cargo clippy (engine), cargo build (server), python pytest, python
mypy, npx tsc --noEmit (client). Fail on any error.

### Blocked

**baize-j7a** (P1, feature) — **Minimal playable client**

Build the minimum viable Web Components client that can play
tic-tac-toe. Needs: `<baize-game>` element that connects to WebSocket,
`<baize-board>` element that renders a grid zone as SVG, click-to-place
interaction, turn indicator, game result display. No drag/drop, no hand
rendering, no clock. Just enough to demo one game end-to-end.

Blocked by: baize-f1l, baize-8ct, baize-f9t.

**baize-olc** (P2, feature) — **Implement remaining movement primitives**

Only step/slide/leap/hop are implemented. Implement: draw, move_to/
transfer, swap, remove, promote, castle, flip (as movement trigger).
Also implement hand plays (currently a no-op stub). Both Rust and
Python engines.

Blocked by: baize-1ye (CEL needed for movement conditions).

**baize-3a3** (P2, feature) — **Spec structured perturber language**

Structured effect/mutation language composing movement primitives with
control flow (sequence, if/then/else, for_each, choose, repeat,
repeat_until_stable). Bounded fixpoint iteration with fuel budget for
chain reactions. Termination guaranteed by construction. Design target:
Go runs entirely in Tier 1 without WASM.

Blocked by: baize-1ye, baize-olc.

**baize-e3s** (P2, feature) — **Authentication and player identity**

Token-based auth (JWT or similar) on WebSocket upgrade. Stable player
identity across reconnections. Spectators remain anonymous.

Blocked by: baize-z6r (persistence needed for session state).

## Completed Work (50 issues)

### Epics

**baize-0a0** — JSON Schema definitions (4 tasks)
Game definition, component registry, game state, move/action schemas.

**baize-ah1** — Rust core engine (5 tasks)
Definition parser, state representation, legal move generator, state
transition engine, WASM bindings.

**baize-aca** — Game server (4 tasks)
WebSocket framework, hidden state vault, cryptographic randomness,
move sequencing and validation.

**baize-562** — Cross-implementation test suite (4 tasks)
Legal move vectors, state transition vectors, visibility model tests,
structured event log format.

**baize-7vp** — TypeScript Web Components client (4 tasks)
Type definitions for `<baize-game>`, `<baize-board>`, drag/drop
interaction layer, WebSocket connection manager.

### Game Definitions (6)

Tic-Tac-Toe, Chess, Texas Hold'em, Carcassonne, Go, Backgammon.

### Security and Hardening (11)

Three P0 fixes (hidden state leak, RequestRandom auth bypass, DoS
vectors), plus input validation, spectator isolation, protocol
hardening, bounded channels, defensive audits of both engines.

### Testing and Quality (7)

Vault unit tests, schema validation on load, hash collision resistance,
fuzz testing, tamper detection, mypy and clippy CI tasks.

## Summary

| Status | Count |
|--------|-------|
| Ready | 7 |
| Blocked | 4 |
| Closed | 50 |
| **Total** | **61** |

---

*Last updated 2026-06-11. Run `bd list` for live state, `bd show <id>`
for details, `bd ready` for unblocked work.*
