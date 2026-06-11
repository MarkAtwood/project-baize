# Baize — Roadmap and Task Tracker

This file is a human-readable snapshot of the project's issue tracker
([beads](https://github.com/MarkAtwood/beads)). It exists because
reviewers and contributors won't have beads installed. The canonical
source of truth is the beads database in `.beads/`; this file is
regenerated periodically.

## Open Work

### P1 — High Priority

**baize-o8y** (bug) — **Upgrade wasmtime from v29 to fix 14 CVEs**

All 14 Dependabot alerts trace to wasmtime v29.0.1, which is 16 major
versions behind. Two critical sandbox escapes (CVSS 9.0). The feature
is behind an optional flag (`wasm-host`) but needs upgrade before any
WASM hosting work proceeds.

### P2 — Medium Priority

**baize-1ye** (feature) — **Spec CEL constraint language integration**

Replace free-form constraint strings with
[CEL (Common Expression Language)](https://github.com/google/cel-spec)
expressions. Define the standard function library for game-specific
predicates (adjacent, in_check, path_clear, liberties, group, connected,
history_contains, etc.). Predicates are CEL; effects remain structural.
Document grammar subset, function signatures, and how CEL expressions
appear in `game-definition.schema.json`. Needs Rust (cel-rust) and
Python (cel-python) evaluator integration.

Blocks: baize-3a3.

**baize-3a3** (feature) — **Spec structured perturber language**

Design a structured effect/mutation language for game state transitions.
Composes movement primitives (move, place, remove, flip, promote, swap,
draw, shuffle, transfer, reveal) with control flow (sequence,
if/then/else, for_each, choose, repeat, repeat_until_stable). CEL
expressions for predicates and filters. `repeat_until_stable` provides
bounded fixpoint iteration with a fuel budget for chain reactions (Go
captures, checkers multi-jump, match-3 cascades). Fuel is a CEL
expression evaluated once against initial state. No `while`, no
recursion, no computed gotos. Termination guaranteed by construction.

Depends on: baize-1ye (CEL must be specced first).

Design target: Go (placement, capture chains, ko/superko, territory
scoring) should run entirely in Tier 1 without WASM.

## Completed Work

### Epics

**baize-0a0** (P1) — **JSON Schema definitions**
- baize-0a0.1 — Game definition schema
- baize-0a0.2 — Component registry schema
- baize-0a0.3 — Game state schema
- baize-0a0.4 — Move/action schema

**baize-ah1** (P1) — **Rust core engine**
- baize-ah1.1 — Game definition parser
- baize-ah1.2 — State representation
- baize-ah1.3 — Legal move generator
- baize-ah1.4 — State transition engine
- baize-ah1.5 — WASM bindings (wasm-bindgen)

**baize-aca** (P1) — **Game server**
- baize-aca.1 — WebSocket server framework (Axum)
- baize-aca.2 — Hidden state vault
- baize-aca.3 — Cryptographic randomness (ChaCha20Rng)
- baize-aca.4 — Move sequencing and validation

**baize-562** (P1) — **Cross-implementation test suite**
- baize-562.1 — Legal move test vectors
- baize-562.2 — State transition test vectors
- baize-562.4 — Visibility model tests
- baize-562.6 — Structured event log format

**baize-7vp** (P1) — **TypeScript Web Components client**
- baize-7vp.1 — `<baize-game>` root element
- baize-7vp.2 — `<baize-board>` SVG renderer
- baize-7vp.6 — Drag/drop interaction layer
- baize-7vp.7 — WebSocket connection manager

### Game Definitions

- baize-xhp.1 — Tic-Tac-Toe
- baize-xhp.2 — Chess
- baize-xhp.3 — Texas Hold'em
- baize-xhp.4 — Carcassonne
- baize-xhp.5 — Go
- baize-xhp.6 — Backgammon

### Security and Hardening

- baize-l4x (P0) — Fix StateSync broadcasting hidden state to all players
- baize-rss (P0) — Add turn/auth check to RequestRandom handler
- baize-rt8 (P0) — Fix unbounded dice/draw DoS vectors in server
- baize-08a (P1) — Replace unbounded outbound channel with bounded
- baize-7nh (P1) — Reject moves from spectator seats
- baize-5yr (P1) — Input validation at all system boundaries
- baize-894 (P1) — Client-side message sanitization
- baize-l54 (P1) — Server protocol hardening
- baize-x74 (P1) — Rust engine defensive programming audit
- baize-gaw (P1) — Python engine defensive programming audit
- baize-1g0 (P2) — Add max move count per game

### Testing and Quality

- baize-ass (P1) — Server vault unit tests
- baize-g8g (P1) — Schema validation on game definition load
- baize-cxn (P2) — State hash collision resistance
- baize-gdl (P2) — Fuzz testing for parsers and protocol
- baize-k1f (P2) — Event log tamper detection
- baize-33c (P2) — Add Python mypy to CI
- baize-4y7 (P2) — Add Rust clippy to CI

## Summary

| Status | Count |
|--------|-------|
| Open | 3 |
| In progress | 0 |
| Closed | 50 |
| **Total** | **53** |

---

*This file was last updated 2026-06-11. Run `bd list` for the live
state, or `bd show <id>` for details on any issue.*
