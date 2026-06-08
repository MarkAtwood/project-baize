# Beads Issue Dump

Exported from beads issue tracker. 87 total issues: 1 open, 86 closed.

## Open Issues

### baize-o8y — Upgrade wasmtime from v29 to fix 14 CVEs
- **Status:** open
- **Priority:** P1
- **Type:** bug
- **Owner:** Mark Atwood
- **Description:** All 14 Dependabot alerts trace to wasmtime v29.0.1 which is 16 major versions behind. Two critical sandbox escapes (CVSS 9.0). Feature is behind optional flag but needs upgrade.

---

## Closed Issues

### Epics

#### baize-0a0 — JSON Schema definitions [P1, epic]
Sub-issues:
- baize-0a0.1 — Game definition schema [P1, task]
- baize-0a0.2 — Component registry schema [P1, task]
- baize-0a0.3 — Game state schema [P1, task]
- baize-0a0.4 — Move/action schema [P1, task]

#### baize-ah1 — Rust core engine (WASM) [P1, epic]
Sub-issues:
- baize-ah1.1 — Game definition parser [P1, task]
- baize-ah1.2 — State representation [P1, task]
- baize-ah1.3 — Legal move generator [P1, task]
- baize-ah1.4 — State transition engine [P1, task]
- baize-ah1.5 — WASM bindings (wasm-bindgen) [P1, task]

#### baize-562 — Cross-implementation test suite [P1, epic]
Sub-issues:
- baize-562.1 — Legal move test vectors [P1, task]
- baize-562.2 — State transition test vectors [P1, task]
- baize-562.3 — Round-trip serialization tests [P2, task]
- baize-562.4 — Visibility model tests [P1, task]
- baize-562.5 — Cross-implementation CI [P2, task]
- baize-562.6 — Structured event log format [P1, task]

#### baize-7vp — TypeScript Web Components client [P1, epic]
Sub-issues:
- baize-7vp.1 — `<baize-game>` root element [P1, task]
- baize-7vp.2 — `<baize-board>` SVG renderer [P1, task]
- baize-7vp.6 — Drag/drop interaction layer [P1, task]
- baize-7vp.7 — WebSocket connection manager [P1, task]

#### baize-aca — Game server [P1, epic]
Sub-issues:
- baize-aca.1 — WebSocket server framework [P1, task]
- baize-aca.2 — Hidden state vault [P1, task]
- baize-aca.3 — Cryptographic randomness [P1, task]
- baize-aca.4 — Move sequencing and validation [P1, task]

### Game Definitions

- baize-xhp.1 — Tic-Tac-Toe game definition [P1, task]
- baize-xhp.2 — Chess game definition [P1, task]
- baize-xhp.3 — Poker: Texas Hold'em game definition [P1, task]
- baize-xhp.4 — Carcassonne game definition [P2, task]
- baize-xhp.5 — Go game definition [P2, task]
- baize-xhp.6 — Backgammon game definition [P2, task]

### Security & Hardening (P0)

- baize-l4x — Fix StateSync broadcasting hidden state to all players [P0, bug]
- baize-rss — Add turn/auth check to RequestRandom handler [P0, bug]
- baize-rt8 — Fix unbounded dice/draw DoS vectors in server [P0, bug]

### Security & Hardening (P1)

- baize-08a — Replace unbounded outbound channel with bounded [P1, bug]
- baize-5yr — Input validation at all system boundaries [P1, task]
- baize-7nh — Reject moves from spectator seats [P1, bug]
- baize-894 — Client-side message sanitization [P1, task]
- baize-ass — Add server vault unit tests [P1, task]
- baize-g8g — Schema validation on game definition load [P1, task]
- baize-gaw — Python engine defensive programming audit [P1, task]
- baize-l54 — Server protocol hardening [P1, task]
- baize-x74 — Rust engine defensive programming audit [P1, task]

### Infrastructure & CI (P2)

- baize-1g0 — Add max move count per game [P2, bug]
- baize-33c — Add Python mypy to CI [P2, task]
- baize-4y7 — Add Rust clippy to CI [P2, task]
- baize-cxn — State hash collision resistance [P2, task]
- baize-gdl — Fuzz testing for parsers and protocol [P2, task]
- baize-k1f — Event log tamper detection [P2, task]

### Design Decisions (P2-P4)

- baize-4gv — WASM mod extensibility: new primitives or validation only? [P2, task]
- baize-aob — Simultaneous move semantics [P2, task]
- baize-99b — Infinite/unbounded game state [P3, task]
- baize-dtt — WASM ABI: serialization format for game state [P3, task]
- baize-mms — Randomness commitment scheme for competitive play [P3, task]
- baize-ppq — Time controls: schema or transport? [P3, task]
- baize-zbu — Undo/takeback: schema or server concern? [P4, task]
- baize-zmi — Spectator mode: delayed revelation [P4, task]

### Bug Fixes (P3-P4)

- baize-46t — Prune stale IP connection counters [P3, bug]
- baize-7wn — Fix TOCTOU race in room creation [P3, bug]
- baize-29h — Bound client-side array lengths in validation [P4, bug]

### Testing

- baize-r54 — Add protocol.rs dispatch tests [P3, task]
