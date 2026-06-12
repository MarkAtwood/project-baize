# The Perturber Language

A structured effect language for board game state mutations with
guaranteed termination.

## Why This Exists

Board game engines need three kinds of logic:

1. **Predicates** — "Is the game over?" "Can this piece move here?"
   Pure read-only queries. Baize uses CEL for these.

2. **Mutations** — "Remove captured stones." "Promote pawn to queen."
   "Chain-react until the board stabilizes." State changes that happen
   as consequences of player actions.

3. **Complex algorithms** — "Score a Carcassonne field." "Evaluate a
   poker hand." Arbitrary computation. Baize uses WASM for these.

The perturber language fills gap #2. CEL can't do it (pure, no side
effects). WASM can but is Turing-complete — you can't prove a WASM
module terminates without running it. The perturber is deliberately
not Turing-complete: every program terminates, provably, by
construction.

**Design constraints:**
- Must mutate game state (CEL can't)
- Must guarantee termination (WASM can't)
- Must be JSON-serializable (lives inside game definitions)
- Must be deterministic (same inputs, same outputs, always)
- Must be auditable (every mutation appears in the event log)

## Quick Example

Capture a piece and award a point:

```json
{"sequence": [
  {"remove": {"target": "captured-piece"}},
  {"add_counter": {"counter": "captures", "value": 1}}
]}
```

Go-style chain reaction — remove dead groups until the board
stabilizes:

```json
{"repeat_until_stable": {
  "fuel": 81,
  "apply": {
    "for_each": {
      "var": "group",
      "in": ["group_1", "group_2", "group_3"],
      "filter": "liberties($group) == 0",
      "do": {"sequence": [
        {"remove": {"target": "$group"}},
        {"add_counter": {"counter": "captured_stones", "value": 1}}
      ]}
    }
  }
}}
```

## Primitives

Eight atomic effects. Each maps to a single game state mutation.

### remove

Destroy a component (capture, kill, discard).

```json
{"remove": {"target": "piece-id"}}
```

The component is removed from whatever zone it occupies. The cell
becomes empty.

### flip

Toggle a component's facing (face-up / face-down).

```json
{"flip": {"target": "card-id"}}
```

### promote

Change a component's type. Used for pawn promotion, king-making in
checkers, upgrading units.

```json
{"promote": {"target": "pawn-3", "to_type": "queen"}}
```

### set_counter

Set a named counter to an exact value. Counters are global integers
attached to the game session (scores, round numbers, resource pools).

```json
{"set_counter": {"counter": "score", "value": 10}}
```

### add_counter

Increment or decrement a counter by a value.

```json
{"add_counter": {"counter": "score", "value": 5}}
{"add_counter": {"counter": "health", "value": -1}}
```

Counter values are capped at +/- 1,000,000,000.

### cycle

Rotate components through a sequence of positions. Each position
receives the component from the previous position; the first position
receives from the last (circular shift). Positions can span multiple
zones.

```json
{"cycle": [
  {"zone": "board", "pos": "0,0"},
  {"zone": "board", "pos": "1,0"},
  {"zone": "board", "pos": "2,0"}
]}
```

After execution: what was at `0,0` is now at `1,0`, what was at `1,0`
is now at `2,0`, what was at `2,0` is now at `0,0`.

Empty cells participate — a cycle with one piece and one empty cell
is a transfer. Applying the same cycle N times (where N = number of
positions) returns everything to the starting arrangement.

Cross-zone cycles work — useful for Rubik's Cube face rotations:

```json
{"cycle": [
  {"zone": "front", "pos": "0,0"},
  {"zone": "right", "pos": "0,0"},
  {"zone": "back",  "pos": "0,0"},
  {"zone": "left",  "pos": "0,0"}
]}
```

Maximum cycle length: 1,000 positions.

### set_cell_property

Set a key-value property on a grid cell. Used for terrain, coloring,
annotations, fog-of-war markers.

```json
{"set_cell_property": {
  "zone": "board",
  "col": 3,
  "row": 4,
  "key": "terrain",
  "value": "forest"
}}
```

Values can be any JSON type (string, number, boolean, object, array).

### invoke

Call a named effect from the game definition's library section. This
is how you reuse effects — define once, reference by name.

```json
{"invoke": "capture_chain"}
```

The library entry must be an effect (object), not a CEL expression
(string). Maximum nesting depth: 16 levels.

## Control Flow

Six control structures. All are bounded — it is impossible to write
a non-terminating perturber program.

### sequence

Run effects in order.

```json
{"sequence": [
  {"set_counter": {"counter": "round", "value": 1}},
  {"add_counter": {"counter": "total_rounds", "value": 1}},
  {"invoke": "deal_cards"}
]}
```

### if / then / else

Conditional execution. The condition is a CEL expression (evaluated
against current game state). The `else` branch is optional.

```json
{"if": "captured_count > 3",
 "then": {"set_counter": {"counter": "bonus", "value": 1}},
 "else": {"set_counter": {"counter": "bonus", "value": 0}}}
```

### for_each

Iterate over a collection with an optional CEL filter. The loop
variable is substituted into the body and filter as `$var`.

```json
{"for_each": {
   "var": "stone",
   "in": ["stone_1", "stone_2", "stone_3", "stone_4"],
   "filter": "is_captured($stone)"
 },
 "do": {"remove": {"target": "$stone"}}
}
```

The collection is a literal list of strings (not computed). The filter
is a CEL expression. Maximum collection size: 10,000 items.

### repeat

Run an effect exactly N times.

```json
{"repeat": 3,
 "body": {"add_counter": {"counter": "ticks", "value": 1}}}
```

Maximum repeat count: 10,000.

### repeat_until_stable

Run an effect repeatedly until the game state stops changing. After
each iteration, the engine computes a state hash. If the hash is
identical to the previous iteration, the board is stable and the
loop exits.

```json
{"repeat_until_stable": {
  "fuel": 81,
  "apply": {"invoke": "remove_dead_groups"}
}}
```

The `fuel` parameter is the maximum number of iterations. It is
capped at 10,000 regardless of what the definition specifies. This
is the only loop construct that can run a variable number of times,
and its termination is guaranteed by the fuel budget.

Use this for chain reactions: captures that expose new captures (Go),
gravity that causes new matches (Bejeweled), cascading tile collapses.

## Termination Guarantee

The perturber language is **not Turing-complete** by design. Every
program terminates because:

- **No `while` loops.** The only loops are `repeat` (fixed count)
  and `repeat_until_stable` (fuel-bounded).
- **No recursion.** `invoke` tracks depth and stops at 16 levels.
- **No computed collections.** `for_each` iterates over a literal
  list, not a dynamically generated one.
- **No computed positions.** Grid coordinates are literal strings,
  not expressions.
- **No variables.** There is no general-purpose variable binding.
  The only "variable" is the `for_each` loop variable, which
  iterates over a fixed list.

The engine can prove any perturber program terminates before running
it, by inspecting the AST and summing fuel budgets.

### Limits

| Resource | Maximum | Enforced by |
|----------|---------|-------------|
| `repeat` count | 10,000 | `MAX_REPEAT` |
| `repeat_until_stable` fuel | 10,000 | `MAX_FUEL` |
| `for_each` collection size | 10,000 | `MAX_FOREACH_ITEMS` |
| `invoke` nesting depth | 16 | `MAX_INVOKE_DEPTH` |
| `cycle` positions | 1,000 | `MAX_CYCLE_LEN` |
| Counter absolute value | 1,000,000,000 | `MAX_COUNTER_VALUE` |

## Where Perturbers Live

Effects are defined in the `library` section of a game definition
and referenced by name via `invoke`:

```json
{
  "library": {
    "board_full": "occupied_count == cell_count",
    "capture_chain": {
      "repeat_until_stable": {
        "fuel": 81,
        "apply": {"invoke": "remove_dead_groups"}
      }
    },
    "remove_dead_groups": {
      "for_each": {
        "var": "g",
        "in": ["g1", "g2", "g3"],
        "filter": "liberties($g) == 0"
      },
      "do": {"remove": {"target": "$g"}}
    }
  }
}
```

String values in the library are CEL expressions (predicates).
Object values are perturber effects (mutations). The engine
distinguishes them by type.

## How It Relates to CEL and WASM

| | CEL | Perturber | WASM |
|---|---|---|---|
| **Purpose** | Predicates | Mutations | Complex algorithms |
| **Side effects** | None | State mutation | Anything |
| **Termination** | Guaranteed (expression) | Guaranteed (structural) | Not guaranteed |
| **Expressiveness** | Read-only queries | Bounded state changes | Turing-complete |
| **Where used** | End conditions, move constraints, filters | Post-action effects, chain reactions | Scoring, pathfinding, custom logic |

CEL and the perturber work together: `if` conditions and `for_each`
filters are CEL expressions. The perturber provides the mutation
shell; CEL provides the decision logic inside it.

## JSON Grammar

Every effect is a JSON object. The top-level key determines the type.

```
Effect ::=
  | {"sequence": [Effect, ...]}
  | {"if": CelExpr, "then": Effect}
  | {"if": CelExpr, "then": Effect, "else": Effect}
  | {"for_each": ForEachSpec, "do": Effect}
  | {"repeat": N, "body": Effect}
  | {"repeat_until_stable": {"fuel": N, "apply": Effect}}
  | {"remove": {"target": ComponentId}}
  | {"flip": {"target": ComponentId}}
  | {"promote": {"target": ComponentId, "to_type": TypeName}}
  | {"set_counter": {"counter": Name, "value": Integer}}
  | {"add_counter": {"counter": Name, "value": Integer}}
  | {"cycle": [{"zone": Name, "pos": "col,row"}, ...]}
  | {"set_cell_property": {"zone": Name, "col": N, "row": N, "key": Name, "value": Any}}
  | {"invoke": LibraryName}

ForEachSpec ::=
  {"var": Name, "in": [String, ...]}
  | {"var": Name, "in": [String, ...], "filter": CelExpr}

CelExpr ::= String  (evaluated as CEL against current game state)
ComponentId ::= String  (references a component by string_id)
Name ::= String
N ::= Non-negative integer
Integer ::= Signed integer (-1,000,000,000 to 1,000,000,000)
Any ::= Any JSON value
```

## Implementation

Both engines implement the full language:

- **Rust:** `engine/src/perturber.rs` (724 lines, 18 tests)
- **Python:** `python/baize/perturber.py` (206 lines)

The implementations are structurally identical — a recursive
`execute_effect` function that pattern-matches on the effect type
and dispatches to the appropriate handler.
