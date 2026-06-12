# Build the Felt Compiler

You are an autonomous agent building the Felt compiler for the Baize
project. You are running unattended. Work through the beads, commit
often, push when milestones are reached.

## Context

- **Project:** /home/mark/PROJECT/baize — a declarative board game engine
- **Spec:** FELT.md — the complete Felt language specification (read this first)
- **Epic:** baize-le7a — Felt compiler epic with sub-issues
- **Tracker:** `bd` (beads) — use it for all task tracking

## First Steps

1. Run `bd prime` to load the beads workflow context.
2. Run `bd show baize-le7a` to see the epic and all sub-issues.
3. Read `FELT.md` completely — it contains the formal grammar, type
   system, compilation rules, WASM GC types, host import API, stdlib
   design, error catalog, edge cases, and test vectors.
4. Read `engine/src/extension.rs` and `server/src/wasm_host.rs` to
   understand the existing WASM extension interface.
5. Run `bd ready` to see what's unblocked and ready to work.

## Work Strategy

### Use subagents aggressively

Each compiler stage is independent enough for parallel work:
- Lexer and parser can be developed in a subagent
- Type checker can start once parser AST types are defined
- Host imports (server-side) are independent of the compiler
- Stdlib (Rust → WASM) is independent of the compiler

Use `isolation: "worktree"` for subagents that write code, so they
don't conflict with each other. Merge results back to main.

### Beads workflow

For each sub-issue:
1. `bd update <id> --claim` — claim it
2. Do the work (write code, write tests, run tests)
3. `git add <files> && git commit -m "..."` — commit
4. `bd close <id>` — mark done
5. Move to the next unblocked issue

### Commit discipline

- Commit after each sub-issue is complete and tests pass
- Conventional commits: `feat: felt lexer`, `feat: felt parser`, etc.
- Push to remote after each major milestone (lexer done, parser done, etc.)
- Never commit broken code. Run tests before every commit.

## Build Plan

### Phase 1: Crate Setup

Create the `felt/` directory as a Rust crate:

```
felt/
  Cargo.toml          # binary + lib crate
  src/
    lib.rs            # re-export modules
    main.rs           # CLI entry point (clap)
    lexer.rs          # logos token definitions
    parser.rs         # chumsky grammar
    ast.rs            # AST types (Expr, Pattern, FnDef, Program)
    types.rs          # Type enum, type environment
    checker.rs        # type checker
    callgraph.rs      # cycle detection (termination)
    codegen.rs        # wasm-encoder code generation
    builtins.rs       # built-in function signatures
    desugar.rs        # pipe, comprehension, partial app elimination
    error.rs          # error types and ariadne formatting
  tests/
    lexer_tests.rs
    parser_tests.rs
    checker_tests.rs
    codegen_tests.rs
    integration_tests.rs
```

Cargo.toml dependencies:
```toml
[dependencies]
logos = "0.15"
chumsky = "0.10"
wasm-encoder = "0.225"
ariadne = "0.5"
clap = { version = "4", features = ["derive"] }
```

Check latest crate versions before pinning.

### Phase 2: Lexer (baize-le7a.1)

Implement the token enum from FELT.md "Stage 1: Lexer" section.
The spec includes the exact `#[derive(Logos)]` enum and test vectors.

Tests: verify every test vector from the spec. Add edge cases:
- Empty input
- Only comments
- Unterminated strings
- Unicode identifiers
- Adjacent operators (`|>|>`)

### Phase 3: Parser (baize-le7a.2)

Implement the chumsky parser producing the AST from FELT.md
"Stage 2: Parser" section. The spec includes the exact AST types
and desugaring rules.

Implement desugaring in a separate pass:
- `a |> f` → `Apply(f, a)`
- `[e | x <- xs, p]` → filter then map
- `where` → `let ... in`
- `(== val)` → lambda
- `\x y -> e` → nested lambdas

Tests: verify every test vector. Add:
- Operator precedence (all 10 levels)
- Nested if/else
- Match with multiple arms
- Record construction and access
- List/set literals
- Lambda inside pipe chains
- Error recovery (missing else, missing arrow)

### Phase 4: Type Checker (baize-le7a.3)

Bidirectional type checking per the spec. Populate the type
environment with all built-in function signatures from the
"Built-in Functions (Complete)" table in FELT.md.

Tests:
- Every built-in resolves to its declared type
- Type mismatch errors with source spans
- Lambda parameter inference from context
- Record field access type checking
- Option pattern matching type checking
- Extension function signature validation

### Phase 5: Call Graph Check (baize-le7a.4)

Topological sort. Reject cycles. ~50 lines.

Tests:
- DAG of functions: accepted
- Direct recursion: rejected with error naming the function
- Mutual recursion (A → B → A): rejected with cycle path
- Deeply nested but acyclic: accepted

### Phase 6: WASM Codegen (baize-le7a.5)

Emit WASM GC binary using wasm-encoder. Follow the compilation
rules table in FELT.md exactly. Emit host imports from the
"Layer 1: Host Imports" section. Emit GC type definitions from
the "WASM GC Type Definitions" section.

This is the hardest phase. Break it into sub-steps:
1. Module skeleton (types, imports, memory, exports)
2. Simple expressions (literals, binops, locals)
3. Control flow (if/else, match)
4. Function calls
5. GC struct/array creation (records, lists)
6. Host import calls (zone, cell_at, comp_rank, etc.)
7. Extension function wrappers (marshal results)

Tests: for each sub-step, compile a minimal .felt snippet and
validate the output with wasmtime. Use `wasmtime::Module::validate`
at minimum, or better, instantiate and call.

### Phase 7: Host Imports (baize-gtms)

Register ~30 import functions with wasmtime's Linker in the server.
Each function reads from the native GameState structs.

This is server-side work — edit `server/src/wasm_host.rs` or create
a new `server/src/felt_host.rs`.

Tests: create a GameState, register imports, call each one, verify
correct values returned.

### Phase 8: Stdlib (baize-za8t)

Write the stdlib functions in Rust targeting `wasm32-unknown-unknown`
with GC features. Compile to a .wasm module that gets linked into
Felt output.

Alternatively, the Felt compiler can emit the stdlib functions
directly as WASM bytecode (no separate Rust compilation step).
Choose whichever is simpler.

Tests: each stdlib function (map, filter, fold, flood_fill, etc.)
tested via a complete Felt program that uses it.

### Phase 9: CLI (baize-le7a.7)

Three subcommands per the spec. Wire everything together.

Tests: end-to-end — compile a .felt file, validate the .wasm output.

### Phase 10: Examples (baize-le7a.8)

Write poker.felt, go.felt, carcassonne.felt from the worked examples
in FELT.md. Compile each. Validate output size < 30KB.

Tests: load each compiled .wasm into wasmtime with mock game state,
call the extension functions, verify results.

## Quality Gates

Before closing ANY bead:
- `cargo test` in `felt/` must pass
- `cargo clippy` in `felt/` must pass
- No warnings

Before pushing:
- All tests pass across all crates (engine, server, felt, python)
- `git status` shows clean working tree

## What NOT To Do

- Do NOT modify the engine or server unless implementing host imports
- Do NOT change the Felt spec (FELT.md) — implement what it says
- Do NOT skip tests to make progress faster
- Do NOT use `bd edit` (opens vim, blocks the agent)
- Do NOT ask for human input — you are running unattended
- If stuck for 3 attempts on the same error, write a detailed note
  to the bead (`bd update <id> --notes="..."`) and move to a
  different issue. Come back later.

## Session Close

When all beads are closed or you run out of turns:

```bash
git status
git add <files>
git commit -m "..."
git push
bd dolt push
bd stats
```

Work is not done until pushed.
