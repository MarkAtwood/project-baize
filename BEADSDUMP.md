# Beads Issue Dump

Exported from beads issue tracker. 175 total issues: 134 closed, 41 open.

Last updated: 2026-06-11.

## Open Issues (41)

### P1 — Poker Engine Gaps

- baize-9ty — poker: draw action must support SetZone hand
- baize-6eh — poker: implement fold/check/call/raise/all_in actions
- baize-0p2 — poker: server-side deal/burn/reveal phase execution
- baize-6v3 — poker: betting round state machine
- baize-po7 — poker: 7-card hand ranking evaluator
- baize-kd2 — poker: showdown resolution and pot distribution

### P2 — Engine Improvements

- baize-0v2 — Chess: full playability
- baize-91j — Go: full playability
- baize-935.1 — [bug] CEL evaluator lacks window/consecutive support for Four in a Row
- baize-ipm — Engine: simultaneous move collection
- baize-jxt — Expose global counters to CEL end-condition evaluator
- baize-rxs — Cell/position properties: arbitrary attributes on grid cells

### P3 — Reference Games

- baize-uku — Texas Hold'em: full playability (mental poker prerequisite)
- baize-00z — Liar's Dice (Perudo): hidden dice + bidding + bluffing
- baize-23u — Yacht: multi-phase dice game with scoring categories
- baize-3xm — Snakes & Ladders: track + dice + triggered effects
- baize-5o2 — Backgammon: full playability
- baize-7df — Rubik's Cube as a single-player game definition
- baize-7h1 — Hex: connection game on graph/hex grid
- baize-8dy — Tile Kingdoms: full playability
- baize-ccb — Reversi: chain-reaction flipping
- baize-q8j — Chinese Checkers: star-shaped triangular lattice
- baize-rto — Checkers: hop captures + multi-jump chains
- baize-xat — Polyomino Placement: grid territory game
- baize-777 — Ogre: hex wargame reference game

### P3 — Infrastructure

- baize-uei — Game notation adapter: human-readable move input/output
- baize-tix — Game definition generator: Ludii/BGG pipeline
- baize-ty6 — Hex wargaming: stacking, terrain costs, CRT combat

### P3 — Notation Specs (blocked on baize-uei)

- baize-0af — Notation spec: Backgammon point notation
- baize-akb — Notation spec: Chess algebraic (SAN)
- baize-ebp — Notation spec: Go board coordinates
- baize-vt3 — Notation spec: Tile Kingdoms tile placement
- baize-wt9 — Cube: Singmaster notation (U R F D L B)
- baize-xkr — Notation spec: Tic-Tac-Toe grid labels

### P3 — Wargaming (blocked on baize-ty6)

- baize-0d6 — Terrain movement costs (WASM)
- baize-1w4 — Combat resolution tables (WASM)
- baize-el1 — Zones of control
- baize-042 — Native mobile client (iOS/Android)

### P4 — Future

- baize-bqi — Triangle Dominoes: triangular tile matching
- baize-hfe — Polyiamond Placement: triangle-tiled territory game
- baize-rkf — Desktop standalone client

---

## Closed Issues (134)

### Epics

- baize-0a0 — JSON Schema definitions [P1, epic, 4 sub-issues]
- baize-ah1 — Rust core engine (WASM) [P1, epic, 5 sub-issues]
- baize-562 — Cross-implementation test suite [P1, epic, 6 sub-issues]
- baize-7vp — TypeScript Web Components client [P1, epic, 8 sub-issues]
- baize-aca — Game server [P1, epic, 6 sub-issues]
- baize-ep0 — Python library [P2, epic, 5 sub-issues]
- baize-rhd — Standard component library [P2, epic, 7 sub-issues]
- baize-xhp — Reference game definitions [P2, epic, 6 sub-issues]

### Game Definitions (parse + validate)

- baize-xhp.1 — Tic-Tac-Toe game definition [P1]
- baize-xhp.2 — Chess game definition [P1]
- baize-xhp.3 — Poker: Texas Hold'em game definition [P1]
- baize-xhp.4 — Tile Kingdoms game definition [P2]
- baize-xhp.5 — Go game definition [P2]
- baize-xhp.6 — Backgammon game definition [P2]
- baize-qg5 — Naval Battle game definition [P3]

### Games — Full Playability

- baize-8ph — Naval Battle: full playability [P2, 7 tests]
- baize-oq9 — Pig: push-your-luck dice game [P3, 43 tests]
- baize-935 — Four in a Row: gravity placement + line detection [P3, 6 tests]
- baize-dri — Rock Paper Scissors: simultaneous moves [P3, 29 tests]
- baize-i9s — Interactive engine REPL [P3]

### Rubik's Cube

- baize-57v — Cycle perturber primitive (cross-zone) [P3]
- baize-wx3 — Face rotation as perturber sequence [P3]
- baize-0b1 — Single-player game support [P3]
- baize-0zh — Solved-state end condition in CEL [P3]
- baize-7y3 — Scramble generation and initial state [P3]

### Naval Battle (Battleship) Subsystems

- baize-56g — Multi-cell ship placement [P3]
- baize-frg — Simultaneous placement phase [P3]
- baize-sb1 — Sunk detection and end condition [P3]
- baize-v2j — Server-authority attack resolution [P3]

### Engine Features

- baize-1ye — CEL constraint language integration [P1]
- baize-82w — Composable CEL functions replacing hardcoded checks [P2]
- baize-wf3 — CEL region-query functions [P2]
- baize-3a3 — Structured perturber language [P2]
- baize-olc — Movement primitives (step/slide/leap/hop/etc.) [P2]
- baize-bu6 — Named compound perturber effects (library) [P2]
- baize-nr9 — Grid stacking: multiple components per cell [P2]
- baize-fgt — Component orientation/facing [P2]
- baize-jae — Multi-cell span support [P1]
- baize-f1l — End condition evaluation at runtime [P1]
- baize-8ct — Visibility filtering on state sync [P1]
- baize-f9t — Game definition loading from room creation API [P1]

### Server

- baize-e3s — Authentication and player identity [P2]
- baize-7ce — WebSocket client capability negotiation [P2]
- baize-z6r — Server persistence layer [P2]

### Documentation & Naming

- baize-ecm — Update project documentation [P2]
- baize-th4 — Rename Battleship to Naval Battle [P2]
- baize-xzo — Rename Carcassonne to Tile Kingdoms [P2]

### Security & Hardening

- baize-l4x — Fix StateSync broadcasting hidden state [P0]
- baize-rss — Add turn/auth check to RequestRandom [P0]
- baize-rt8 — Fix unbounded dice/draw DoS vectors [P0]
- baize-4xq — Perturber bounds enforcement [P0]
- baize-08a — Bounded outbound channels [P1]
- baize-5yr — Input validation at system boundaries [P1]
- baize-7nh — Reject spectator moves [P1]
- baize-894 — Client-side message sanitization [P1]
- baize-89u — CEL expression complexity limits [P1]
- baize-lc2 — Server protocol validation hardening [P1]
- baize-o8y — Upgrade wasmtime (14 CVEs) [P1]
- baize-z6k — Eliminate unwrap anti-patterns [P2]
- baize-e7q — Python client/agent message validation [P2]
- baize-1g0 — Max move count per game [P2]

### Infrastructure & CI

- baize-fk5 — CI pipeline [P2]
- baize-33c — Python mypy in CI [P2]
- baize-4y7 — Rust clippy in CI [P2]
- baize-cxn — State hash collision resistance [P2]
- baize-gdl — Fuzz testing [P2]
- baize-k1f — Event log tamper detection [P2]

### Design Decisions

- baize-7a2 — CEL predicate boundary (pure queries, no hypotheticals) [P2]
- baize-4gv — WASM extensibility model [P2]
- baize-aob — Simultaneous move semantics [P2]
- baize-99b — Infinite/unbounded game state [P3]
- baize-dtt — WASM ABI serialization format [P3]
- baize-mms — Randomness commitment scheme [P3]
- baize-ppq — Time controls [P3]
- baize-zbu — Undo/takeback [P4]
- baize-zmi — Spectator delayed revelation [P4]

### Agents

- baize-a9j — Agent framework [P3]
- baize-a0o — Agent SDK [P3]
- baize-9wj — Reference agents (random/greedy/MCTS) [P4]

### Clients

- baize-j7a — Minimal playable client [P1]
- baize-1yb — CLI/terminal client [P4]
- baize-5vf — Bot/headless client harness [P3]

### Testing & Bug Fixes

- baize-ass — Server vault unit tests [P1]
- baize-g8g — Schema validation on load [P1]
- baize-gaw — Python defensive audit [P1]
- baize-l54 — Server protocol hardening [P1]
- baize-x74 — Rust defensive audit [P1]
- baize-r54 — Protocol dispatch tests [P3]
- baize-46t — Prune stale IP counters [P3]
- baize-7wn — Fix TOCTOU in room creation [P3]
- baize-29h — Bound client array lengths [P4]

---

## Summary

| Status | Count |
|--------|-------|
| Open | 41 |
| Closed | 134 |
| **Total** | **175** |

*Run `bd list` for live state, `bd show <id>` for details, `bd ready` for unblocked work.*
