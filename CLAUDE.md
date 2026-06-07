# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
# Rust engine (28 tests)
cd engine && cargo test

# Rust server (builds, no tests yet)
cd server && cargo build

# Python (30 tests)
cd python && python3 -m pytest tests/ -v

# TypeScript client (type-check only, no runtime tests)
cd client && npx tsc --noEmit
```

## Architecture Overview

Baize is a declarative board game engine with a three-tier trust architecture:

- **Tier 1 — Declarative Schema**: JSON game definitions (`games/*.json`) validated against JSON Schema (`schema/*.json`). Covers zones, components, movement, turn order, phases, end conditions, authority.
- **Tier 2 — WASM Extensions**: Optional game-specific logic via `GameExtension` trait for complex scoring, chain reactions, custom validation. Compiled to WASM, runs on both client and server.
- **Tier 3 — Server Authority**: Hidden state vault, cryptographic randomness (ChaCha20Rng), move sequencing. The server's irreducible responsibility.

Key directories:
- `schema/` — JSON Schema definitions (draft 2020-12)
- `games/` — Reference game definitions (tic-tac-toe, chess, poker, etc.)
- `registry/` — Reusable component definitions (cards, dice, pieces, boards)
- `engine/` — Rust core engine (compiles to native + WASM via wasm-bindgen)
- `python/` — Python reference implementation (3.12+, strict mypy)
- `server/` — Axum WebSocket game server
- `client/` — TypeScript Web Components (`<baize-game>`, `<baize-board>`, etc.)
- `tests/vectors/` — Cross-implementation test vectors (JSON)

## Conventions & Patterns

- **Deterministic engine**: Pure function `(state, action) → (state, events)`. No side effects. Seeded PRNG.
- **Event logging**: JSONL with BLAKE3 hash chaining for tournament integrity.
- **Component IDs**: Arena-based `ComponentId(usize)` in both Rust and Python.
- **Grid indexing**: Flat `Vec<Option<ComponentId>>` indexed by `row * width + col`.
- **Serde patterns**: `#[serde(tag = "...")]` for discriminated unions, `#[serde(untagged)]` for polymorphic types.
- **Python style**: Dataclasses, no inheritance trees, `from_dict()`/`to_dict()` for serialization.
- **Schema `oneOf` rule**: Never combine `{const: "foo"}` with `{type: "string"}` in a `oneOf` — use a single `{type: "string"}` with descriptive text instead.
