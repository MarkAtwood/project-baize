# Felt Language Specification

**Felt** is a pure, expression-oriented language for writing board game
logic that compiles to WebAssembly. It targets game designers who need
more power than CEL predicates but don't want to write Rust.

Felt is the computational complement to CEL (read-only predicates) and
the perturber (bounded mutations). Felt handles scoring, validation,
move generation, and end-condition detection — the things that push
games into WASM.

## Design Principles

1. **Pure.** Every function takes values in and returns values out. No
   mutation, no I/O, no side effects.

2. **Total.** Every Felt program terminates. No recursion. No loops.
   All iteration is through built-in higher-order functions (map,
   filter, fold) operating on finite collections from game state.

3. **Board-native.** Built-in types and functions for zones, cells,
   components, adjacency, flood-fill, and connected components.

4. **Readable.** ML-inspired syntax with pipe operators. Code reads
   left-to-right, top-to-bottom.

5. **Small.** The entire language fits in this document. No modules, no
   classes, no generics, no macros, no operator overloading, no
   recursion, no user-defined sum types.

## Not In The Language

These features are deliberately excluded. If you need them, write your
extension in Rust.

- **Recursion.** Functions cannot call themselves, directly or through
  cycles. All iteration uses built-in higher-order functions.
- **Loops.** No `while`, `for`, `loop`. Not keywords. Not syntax.
- **Mutation.** No variables, no assignment, no mutable state.
- **User-defined sum types.** `Option` and `Result` are built-in.
  You cannot define new sum types.
- **Modules or imports.** One file = one extension. No multi-file.
- **Generics.** Built-in functions are polymorphic. User functions
  are monomorphic (concrete types only).
- **String interpolation.** Use `concat` for string building.
- **Exceptions.** Errors are `Option`/`Result` values.
- **Closures capturing mutable state.** Lambdas can capture
  immutable bindings from enclosing scope (see Lambdas section).

---

## Formal Grammar (EBNF)

```ebnf
program     = { fn_def } ;

fn_def      = "fn" IDENT "(" [ param_list ] ")" "->" type "="
              expr [ where_clause ] ;

param_list  = param { "," param } ;
param       = IDENT ":" type ;

where_clause = "where" { where_bind } ;
where_bind   = IDENT { IDENT } "=" expr ;

type        = "Int" | "Float" | "Bool" | "String"
            | "State" | "Zone" | "Cell" | "Component" | "Player"
            | "Action"
            | "List" type
            | "Set" type
            | "Map" type type
            | "Option" type
            | "(" type { "," type } ")"
            | "{" field_type { "," field_type } "}"
            | type "->" type ;

field_type  = IDENT ":" type ;

expr        = pipe_expr ;

pipe_expr   = or_expr { "|>" or_expr } ;

or_expr     = and_expr { "or" and_expr } ;

and_expr    = cmp_expr { "and" cmp_expr } ;

cmp_expr    = concat_expr [ cmp_op concat_expr ] ;
cmp_op      = "==" | "!=" | "<" | ">" | "<=" | ">=" ;

concat_expr = add_expr { "++" add_expr } ;

add_expr    = mul_expr { ("+" | "-") mul_expr } ;

mul_expr    = unary_expr { ("*" | "/" | "%") unary_expr } ;

unary_expr  = [ "not" | "-" ] apply_expr ;

apply_expr  = atom_expr { atom_expr } ;

atom_expr   = INT_LIT | FLOAT_LIT | STRING_LIT
            | "true" | "false"
            | IDENT
            | "(" expr { "," expr } ")"
            | "[" [ expr { "," expr } ] "]"
            | "[" expr "|" generator { "," generator } "]"
            | "{" [ expr { "," expr } ] "}"
            | "{" field_val { "," field_val } "}"
            | "." IDENT
            | lambda
            | let_expr
            | if_expr
            | match_expr ;

generator   = IDENT "<-" expr [ "," expr ] ;

lambda      = "\\" IDENT { IDENT } "->" expr ;

let_expr    = "let" let_bind { let_bind } "in" expr ;
let_bind    = IDENT "=" expr ;

if_expr     = "if" expr "then" expr "else" expr ;

match_expr  = "match" expr "with" { "|" pattern "->" expr } ;

pattern     = "_"
            | INT_LIT
            | STRING_LIT
            | "true" | "false"
            | "None"
            | "Some" IDENT
            | IDENT ;

field_val   = IDENT "=" expr ;

INT_LIT     = digit { digit } ;
FLOAT_LIT   = digit { digit } "." digit { digit } ;
STRING_LIT  = '"' { any_char } '"' ;
IDENT       = letter { letter | digit | "_" } ;

(* Line comments start with -- and extend to end of line *)
```

### Operator Precedence (lowest to highest)

| Level | Operators | Associativity |
|-------|-----------|---------------|
| 1 | `\|>` (pipe) | Left |
| 2 | `or` | Left |
| 3 | `and` | Left |
| 4 | `==` `!=` `<` `>` `<=` `>=` | None (no chaining) |
| 5 | `++` (list/string concat) | Right |
| 6 | `+` `-` | Left |
| 7 | `*` `/` `%` | Left |
| 8 | `not` `-` (unary) | Prefix |
| 9 | Function application | Left |
| 10 | `.field` (record access) | Postfix |

### Reserved Keywords

```
fn let in if then else match with where
true false not and or
type None Some
```

No other identifiers are reserved. Built-in function names (`map`,
`filter`, `zone`, etc.) can be shadowed by local bindings, though
this is not recommended.

---

## Types

### Primitive Types

| Type | WASM GC repr | Description |
|------|-------------|-------------|
| `Int` | `i64` | 64-bit signed integer (WASM scalar) |
| `Float` | `f64` | 64-bit IEEE 754 (WASM scalar) |
| `Bool` | `i32` | 0 = false, 1 = true (WASM scalar) |
| `String` | `ref (array i8)` | GC-managed immutable byte array (UTF-8) |

### Collection Types

| Type | WASM GC repr | Description |
|------|-------------|-------------|
| `List a` | `ref (array (ref $a))` | GC-managed immutable array of element refs |
| `Set a` | `ref (array (ref $a))` | Same as List but sorted, no duplicates |
| `Map k v` | `ref (array (ref $entry))` | Sorted array of (key, value) struct refs |

Collections are immutable. Operations like `filter` and `map` return
new GC-allocated arrays. The engine's GC reclaims unreachable old
copies. No manual memory management.

### Game Types (GC Struct References)

These are GC-managed struct refs populated during JSON deserialization.
You cannot construct them — you receive them from the game state.

| Type | WASM GC repr | What it is |
|------|-------------|------------|
| `State` | `ref $State` | GC struct: zones array, players array, counters, phase, turn |
| `Zone` | `ref $Zone` | GC struct: zone_type, cells array, components array, dimensions |
| `Cell` | `ref $Cell` | GC struct: col, row, component (nullable ref) |
| `Component` | `ref $Component` | GC struct: type_name, owner, rank, suit, properties |
| `Player` | `ref $Player` | GC struct: name, index |
| `Action` | `ref $Action` | GC struct: action_type, component_id, from, to, etc. |

### Tuple Types

```
(Int, Int)           -- pair
(String, Int, Bool)  -- triple
```

WASM GC repr: `ref (struct i64 i64)` for pairs, etc. Accessed by
position: `fst`, `snd`, or destructuring. GC-managed.

### Record Types

```
type Score = { player: String, points: Int, breakdown: List Entry }
type Entry = { category: String, points: Int }
type EndResult = { game_over: Bool, winner: String, condition: String }
```

These are the only three user-definable record types. They correspond
to the `GameExtension` return types. WASM GC repr: `ref (struct ...)`
with named field accessors via `struct.get`. Accessed with `.field`
syntax: `s.player`, `s.points`.

Record types are declared at the top of a `.felt` file. They are
product types only — no inheritance, no methods.

### Option Type (Built-in)

```
Option a = Some a | None
```

WASM GC repr: nullable reference. `Option Component` = `(ref null $Component)`.
`None` = `ref.null`. `Some x` = the ref itself.

For `Option Int` (boxing a scalar): `ref null (struct i64)`.

Pattern match to extract:
```
match cell_at board 3 4 with
| Some c -> type_of c
| None   -> "empty"
```

Compiles to `ref.is_null` + `br_if`.

### Convenience Functions for Option

```
unwrap_or : Option a -> a -> a      -- extract or use default
is_some   : Option a -> Bool
is_none   : Option a -> Bool
```

---

## Syntax Details

### Let Bindings

```
let x = 42
let name = "poker"
let cards = zone state "hand" player |> components
```

Multiple `let` bindings use `let ... in` for scoping:

```
let ranks = cards |> map rank |> sort
    suits = cards |> map suit
in if all_same suits then "flush" else "not flush"
```

Each binding's right-hand side can reference all previous bindings
in the same `let` block. Bindings are immutable.

### Functions

All functions are top-level. No nested `fn` definitions.

```
fn score_hand(cards: List Component) -> Int =
  let ranks = cards |> map rank |> sort |> reverse
      suits = cards |> map suit
  in
    if all_same suits and consecutive ranks then 800 + max ranks
    else 0
```

Functions cannot call themselves (no recursion). The compiler rejects
any cycle in the call graph. Functions CAN call other top-level
functions — the call graph must be a DAG.

### Where Clauses

Sugar for `let ... in` at the end of a function body:

```
fn territory(state: State, player: Player) -> Int =
  empty_cells board
  |> flood_groups board
  |> filter (surrounded_by player)
  |> map size
  |> sum
  where
    board = zone state "board"
    surrounded_by p group = border_owners board group |> all (== p)
```

Where bindings desugar to:
```
let board = zone state "board"
    surrounded_by = \p -> \group -> border_owners board group |> all (== p)
in empty_cells board |> ...
```

### Lambdas

Anonymous functions with `\param -> body` syntax:

```
cards |> filter (\c -> rank c > 10)
cards |> map (\c -> (rank c, suit c))
```

Lambdas capture immutable bindings from their enclosing scope.

**Compilation:** closure conversion. Captured variables become extra
parameters. The compiler rewrites:

```
let threshold = 10
in cards |> filter (\c -> rank c > threshold)
```

to:

```
let threshold = 10
in cards |> filter (__lambda_1 threshold)

fn __lambda_1(threshold: Int, c: Component) -> Bool =
  rank c > threshold
```

The caller passes captured values at the call site. The lambda becomes
a plain function with extra parameters. No heap-allocated closures,
no function pointers, no GC.

**Multi-parameter lambdas:** `\x y -> x + y` is sugar for
`\x -> \y -> x + y`.

### Pipe Operator

`a |> f` desugars to `f a` (f applied to a as its LAST argument).

```
cards |> filter (\c -> rank c > 10) |> map rank |> sum
-- desugars to:
sum (map rank (filter (\c -> rank c > 10) cards))
```

The pipe is purely syntactic sugar. It is eliminated during parsing
(before type checking). The desugared form is all the compiler sees.

### Partial Application

`(== player)` is sugar for `\x -> x == player`.
`(+ 1)` is sugar for `\x -> x + 1`.
`(f a)` where `f` takes 2+ arguments returns a function waiting for
the remaining arguments.

Implementation: the compiler desugars partial application into
explicit lambdas during parsing.

### Pattern Matching

Match on values. Every match must be exhaustive (have a wildcard `_`
or cover all cases).

```
match expr with
| pattern_1 -> result_1
| pattern_2 -> result_2
| _         -> default_result
```

Patterns can match:
- Integer literals: `| 42 -> ...`
- String literals: `| "king" -> ...`
- Booleans: `| true -> ...`
- Option: `| Some x -> ...` and `| None -> ...`
- Wildcard: `| _ -> ...`
- Variable binding: `| x -> ...` (binds the matched value to x)

Patterns CANNOT match:
- List destructuring (`x :: rest` — not supported, use `head`/`tail`)
- Nested patterns (`Some (Some x)` — not supported)
- Guards (`| x if x > 0` — not supported, use `if` in the body)

**WASM compilation:** cascade of `if`/`else` blocks.

```
match x with
| 1 -> "one"
| 2 -> "two"
| _ -> "other"
```

compiles to:

```wasm
local.get $x
i64.const 1
i64.eq
if (result (ref $String))
  array.new_data $String $data_one 3      ;; "one"
else
  local.get $x
  i64.const 2
  i64.eq
  if (result (ref $String))
    array.new_data $String $data_two 3    ;; "two"
  else
    array.new_data $String $data_other 5  ;; "other"
  end
end
```

### List Comprehensions

```
[expr | var <- collection]
[expr | var <- collection, predicate]
```

Desugar to `map` and `filter`:

```
[rank c | c <- cards, owner c == player]
-- desugars to:
cards |> filter (\c -> owner c == player) |> map (\c -> rank c)
```

Comprehensions are syntactic sugar only — eliminated during parsing.

### Record Construction and Access

```
-- Construction
{ player = "X", points = 42, breakdown = [] }

-- Field access
score.player     -- "X"
score.points     -- 42
```

Field access compiles to `struct.get` (GC-managed, type-safe).

---

## Built-in Functions (Complete)

Every built-in has a fixed type signature. The compiler knows these
types without any declaration.

### Zone Access

| Signature | Description |
|-----------|-------------|
| `zone : State -> String -> Zone` | Get zone by name |
| `zone_for : State -> String -> Player -> Zone` | Get per-player zone |
| `components : Zone -> List Component` | All components in zone |
| `cells : Zone -> List Cell` | All cells in zone |
| `cell_at : Zone -> Int -> Int -> Option Component` | Component at (col, row) |
| `count : Zone -> Int` | Component count |
| `counter_value : Zone -> Int` | Counter zone value |

### Component Properties

| Signature | Description |
|-----------|-------------|
| `type_of : Component -> String` | Type name |
| `owner : Component -> Option Player` | Owning player |
| `rank : Component -> Int` | Numeric rank |
| `suit : Component -> String` | Suit/color group |
| `property : Component -> String -> String` | Named property |
| `position : Component -> Option Cell` | Board position |
| `col : Cell -> Int` | Cell column |
| `row : Cell -> Int` | Cell row |

### Grid Operations

| Signature | Description |
|-----------|-------------|
| `adjacent : Zone -> Cell -> List Cell` | 4 orthogonal neighbors |
| `diagonal : Zone -> Cell -> List Cell` | 4 diagonal neighbors |
| `neighbors : Zone -> Cell -> List Cell` | All 8 neighbors |
| `in_bounds : Zone -> Int -> Int -> Bool` | Bounds check |
| `dimensions : Zone -> (Int, Int)` | (width, height) |
| `row_cells : Zone -> Int -> List Cell` | All cells in row |
| `col_cells : Zone -> Int -> List Cell` | All cells in column |
| `line_cells : Zone -> Cell -> Int -> Int -> List Cell` | Cells along (dx,dy) direction |

### Graph Operations

| Signature | Description |
|-----------|-------------|
| `flood_fill : Zone -> Cell -> (Cell -> Bool) -> Set Cell` | BFS from cell through matching cells |
| `flood_groups : Zone -> (Cell -> Bool) -> List (Set Cell)` | All connected components matching predicate |
| `connected : Zone -> Cell -> Cell -> (Cell -> Bool) -> Bool` | Reachability test |
| `border : Zone -> Set Cell -> Set Cell` | Cells adjacent to group but not in it |
| `border_owners : Zone -> Set Cell -> Set Player` | Owners on border cells |
| `liberties : Zone -> Set Cell -> Int` | Empty cells adjacent to group |

### List Operations

| Signature | Description |
|-----------|-------------|
| `map : (a -> b) -> List a -> List b` | Transform each element |
| `filter : (a -> Bool) -> List a -> List a` | Keep matching elements |
| `fold : (b -> a -> b) -> b -> List a -> b` | Left fold with accumulator |
| `flat_map : (a -> List b) -> List a -> List b` | Map then flatten |
| `sum : List Int -> Int` | Sum of integers |
| `max : List Int -> Int` | Maximum (0 if empty) |
| `min : List Int -> Int` | Minimum (0 if empty) |
| `sort : List Int -> List Int` | Ascending sort |
| `sort_by : (a -> Int) -> List a -> List a` | Sort by key function |
| `reverse : List a -> List a` | Reverse order |
| `length : List a -> Int` | Element count |
| `head : List a -> Option a` | First element |
| `tail : List a -> List a` | All but first (empty if empty) |
| `zip : List a -> List b -> List (a, b)` | Pair elements |
| `flatten : List (List a) -> List a` | Concatenate nested lists |
| `unique : List a -> Set a` | Deduplicate into set |
| `contains : List a -> a -> Bool` | Membership test |
| `all : (a -> Bool) -> List a -> Bool` | Every element matches |
| `any : (a -> Bool) -> List a -> Bool` | At least one matches |
| `all_same : List a -> Bool` | All elements equal |
| `consecutive : List Int -> Bool` | Sequential integers (e.g., [3,4,5,6]) |
| `combinations : List a -> Int -> List (List a)` | All k-combinations |
| `concat : String -> String -> String` | String concatenation |
| `range : Int -> Int -> List Int` | Integer range [lo, hi) |
| `enumerate : List a -> List (Int, a)` | Pair with index |

### Set Operations

| Signature | Description |
|-----------|-------------|
| `union : Set a -> Set a -> Set a` | Set union |
| `intersect : Set a -> Set a -> Set a` | Set intersection |
| `difference : Set a -> Set a -> Set a` | Set difference |
| `size : Set a -> Int` | Cardinality |
| `member : Set a -> a -> Bool` | Membership test |
| `to_list : Set a -> List a` | Convert to sorted list |
| `from_list : List a -> Set a` | Convert from list (dedup+sort) |

### Map Operations

| Signature | Description |
|-----------|-------------|
| `lookup : Map k v -> k -> Option v` | Key lookup |
| `keys : Map k v -> List k` | All keys |
| `values : Map k v -> List v` | All values |
| `entries : Map k v -> List (k, v)` | All key-value pairs |
| `insert : Map k v -> k -> v -> Map k v` | Insert/replace (returns new map) |

### Grouping (Card Games)

| Signature | Description |
|-----------|-------------|
| `group_by : (a -> k) -> List a -> Map k (List a)` | Group by key function |
| `count_groups : List Int -> Int -> Int` | How many groups of exactly size N |
| `has_group : List Int -> Int -> Bool` | Is there a group of size >= N |
| `group_value : List Int -> Int -> Int` | Value of largest group of size N |

### Game State

| Signature | Description |
|-----------|-------------|
| `players : State -> List Player` | All players |
| `current_player : State -> Player` | Whose turn |
| `other_player : State -> Player -> Player` | Opponent (2-player games) |
| `turn : State -> Int` | Turn number |
| `phase : State -> String` | Current phase name |
| `counters : State -> Map String Int` | Global counters |
| `is_finished : State -> Bool` | Game over? |

### Tuple Operations

| Signature | Description |
|-----------|-------------|
| `fst : (a, b) -> a` | First element |
| `snd : (a, b) -> b` | Second element |

### Option Operations

| Signature | Description |
|-----------|-------------|
| `unwrap_or : Option a -> a -> a` | Extract or default |
| `is_some : Option a -> Bool` | Has value |
| `is_none : Option a -> Bool` | No value |
| `map_opt : (a -> b) -> Option a -> Option b` | Transform inner value |

### Arithmetic

| Signature | Description |
|-----------|-------------|
| `abs : Int -> Int` | Absolute value |
| `max_of : Int -> Int -> Int` | Maximum of two |
| `min_of : Int -> Int -> Int` | Minimum of two |

---

## Extension Interface

A Felt file implements one or more of five standard functions. Each
corresponds to a method on the `GameExtension` trait.

```
fn is_legal(state: State, player: Player, action: Action) -> Option Bool
fn legal_moves(state: State, player: Player) -> List Action
fn apply_effect(state: State, trigger: String) -> State
fn score(state: State) -> List Score
fn check_end(state: State) -> Option EndResult
```

Implement only the ones your game needs. The compiler emits WASM
exports only for functions that are defined.

These five names are special. The compiler recognizes them and
generates the JSON marshaling code (deserialize arguments from JSON,
call the function, serialize results to JSON).

All other top-level `fn` definitions become internal WASM functions
(not exported). They are helper functions.

---

## Termination

Felt guarantees termination trivially:

1. **No recursion.** The compiler builds a call graph of all `fn`
   definitions. Any cycle is a compile error. Functions can call
   other functions, but the call graph must be a DAG.

2. **No loops.** There is no `while`, `for`, or `loop` keyword.

3. **All iteration is through builtins.** `map`, `filter`, `fold`,
   `flood_fill`, `combinations`, etc. iterate over finite collections
   from game state. These are implemented in the runtime, not in Felt.
   They always terminate because game state is finite.

This means the termination check is trivial: detect cycles in the
call graph. No structural recursion analysis needed, no fuel
budgets, no dependent types.

### WASM Fuel (Runtime Backstop)

The Baize server's wasmtime runtime enforces a fuel limit on all
WASM modules (1 billion instructions per call). This catches Felt
programs that terminate but are slow (e.g., `combinations cards 7`
on a 52-card deck). Game designers never see this — it's a server
safety net.

```
Felt (.felt)  →  termination guaranteed (compile-time, no recursion)
                 + WASM fuel limit (runtime backstop)

Rust (.rs)    →  no termination guarantee
                 + WASM fuel limit (runtime, only defense)
```

---

## WASM GC Memory Model

### No Manual Memory Management

Felt targets WASM GC (WebAssembly 3.0, standardized September 2025).
All heap allocations — strings, lists, records, game state structs —
are GC-managed by the WASM runtime (wasmtime or browser engine).

**No arena allocator.** No bump pointer. No `alloc`/`dealloc` exports.
No manual memory layout. The runtime handles everything.

This is possible because:
- Felt is pure — no mutation, no aliasing concerns.
- Extension calls are short-lived — allocate during the call, GC
  reclaims afterward.
- Wasmtime's "null" GC (bump-allocate, no cycle collection) is
  perfect for this: Felt can't create cycles (immutable data, no
  mutation), so bump-and-forget is correct.

### WASM GC Type Definitions

The Felt compiler emits these GC type definitions in the WASM module:

```wasm
;; Primitives that need boxing (for Option, List elements, etc.)
(type $BoxedInt (struct (field $val i64)))
(type $BoxedFloat (struct (field $val f64)))

;; Strings
(type $String (array i8))    ;; UTF-8 bytes, length via array.len

;; Generic array (for List/Set)
(type $Array_i64 (array i64))
(type $Array_ref (array (ref null any)))  ;; array of any GC ref

;; Game types
(type $State (struct
  (field $zones    (ref $Array_ref))     ;; array of Zone refs
  (field $players  (ref $Array_ref))     ;; array of Player refs
  (field $counters (ref $Array_ref))     ;; array of (name, value) pairs
  (field $phase    (ref $String))
  (field $turn     i32)
  (field $finished i32)))

(type $Zone (struct
  (field $name       (ref $String))
  (field $zone_type  i32)              ;; 0=grid, 1=stack, 2=set, etc.
  (field $width      i32)
  (field $height     i32)
  (field $cells      (ref $Array_ref))   ;; array of Cell refs
  (field $components (ref $Array_ref)))) ;; array of Component refs

(type $Cell (struct
  (field $col       i32)
  (field $row       i32)
  (field $occupant  (ref null $Component))))

(type $Component (struct
  (field $type_name  (ref $String))
  (field $owner      (ref null $Player))
  (field $rank       i64)
  (field $suit       (ref $String))
  (field $id         (ref $String))
  (field $properties (ref $Array_ref)))) ;; array of (key, value) pairs

(type $Player (struct
  (field $name  (ref $String))
  (field $index i32)))

;; User-defined records
(type $Score (struct
  (field $player    (ref $String))
  (field $points    i64)
  (field $breakdown (ref $Array_ref))))   ;; array of Entry refs

(type $Entry (struct
  (field $category (ref $String))
  (field $points   i64)))

(type $EndResult (struct
  (field $game_over i32)
  (field $winner    (ref $String))
  (field $condition (ref $String))))

;; Tuples
(type $Pair_i64_i64 (struct (field $fst i64) (field $snd i64)))
;; (other tuple types generated as needed by the compiler)
```

### Value Representation Summary

| Felt type | WASM GC instruction | Notes |
|-----------|--------------------|----|
| `Int` | `i64` on stack | No boxing unless inside a collection |
| `Float` | `f64` on stack | No boxing unless inside a collection |
| `Bool` | `i32` on stack | 0 or 1 |
| `String` | `array.new $String` | Immutable byte array |
| `List a` | `array.new $Array_*` | Immutable element array |
| `(a, b)` | `struct.new $Pair` | GC struct |
| `{ f: T }` | `struct.new $Record` | GC struct |
| `Some x` | The ref itself | Non-null ref |
| `None` | `ref.null` | Null ref |
| Game types | `struct.new $State/$Zone/...` | GC struct |

### JSON Serde Runtime

The compiled WASM binary includes a small runtime that:

1. **Deserializes** JSON game state into GC struct/array instances
   using `struct.new` and `array.new` instructions.
2. **Serializes** Felt result values back to JSON by walking GC
   structs with `struct.get` and arrays with `array.get`.

The runtime is pre-compiled WASM (written in Rust, compiled to
`wasm32-unknown-unknown` with GC target features). The Felt compiler
links it into every output binary.

**Deserialization strategy:** The JSON arrives as a byte array in
linear memory (the one piece of linear memory we still use — for
the JSON input/output buffer). The runtime parses it and builds
GC structs:

```
JSON bytes (linear memory) → parse → struct.new $State
  → struct.new $Zone (for each zone)
    → struct.new $Cell (for each cell)
      → struct.new $Component (for each component)
```

**Serialization strategy:** Walk the result's GC structs, emit JSON
bytes into the linear memory output buffer:
- `List Score` → `[{"player":...,"points":...}, ...]`
- `Option EndResult` → `{...}` or `null`
- `Option Bool` → `true`/`false`/`null`

**Linear memory is used ONLY for the JSON I/O buffers** — the
input string from the host and the output string to the host. All
game data structures live in the GC heap.

### Why WASM GC?

| Without GC (WASM 2.0) | With GC (WASM 3.0) |
|----------------------|---------------------|
| Ship an allocator in every binary | Runtime manages memory |
| Manual layout: `(len, elements...)` in raw bytes | `array.new`, `array.get`, `array.len` |
| Pointer math for struct fields | `struct.new`, `struct.get` — type-safe |
| Option = `(tag, value)` packed in memory | Nullable ref: `ref.null` / `ref.is_null` |
| ~5KB allocator overhead | 0 bytes overhead |
| Out-of-bounds = silent corruption | Out-of-bounds = runtime trap |

WASM GC is a W3C standard (WebAssembly 3.0, September 2025).
Supported in Chrome (since late 2023), Firefox, and wasmtime 27+
(Bytecode Alliance). Felt targets WASM GC as a hard requirement.

---

## Compilation Details

```
felt compile poker.felt -o poker.wasm
felt check poker.felt                    -- type-check only
felt run poker.felt --state game.json    -- interpret locally
```

### Pipeline

```
Source (.felt)
  → Lexer (logos)          → Token stream with spans
  → Parser (chumsky)       → AST (with source locations)
  → Desugar                → Core AST (pipes, comprehensions, partials eliminated)
  → Type Checker           → Typed AST (every node annotated with type)
  → Call Graph Check       → Verified AST (no cycles)
  → WASM Codegen           → .wasm binary
    (wasm-encoder)
```

### Stage 1: Lexer (logos)

```rust
#[derive(Logos, Debug, Clone, PartialEq)]
enum Token {
    // Keywords
    #[token("fn")]     Fn,
    #[token("let")]    Let,
    #[token("in")]     In,
    #[token("if")]     If,
    #[token("then")]   Then,
    #[token("else")]   Else,
    #[token("match")]  Match,
    #[token("with")]   With,
    #[token("where")]  Where,
    #[token("true")]   True,
    #[token("false")]  False,
    #[token("not")]    Not,
    #[token("and")]    And,
    #[token("or")]     Or,
    #[token("type")]   Type,
    #[token("None")]   None_,
    #[token("Some")]   Some_,

    // Operators
    #[token("|>")]     Pipe,
    #[token("->")]     Arrow,
    #[token("==")]     Eq,
    #[token("!=")]     Neq,
    #[token(">=")]     Gte,
    #[token("<=")]     Lte,
    #[token(">")]      Gt,
    #[token("<")]      Lt,
    #[token("+")]      Plus,
    #[token("-")]      Minus,
    #[token("*")]      Star,
    #[token("/")]      Slash,
    #[token("%")]      Percent,
    #[token("++")]     PlusPlus,
    #[token("\\")]     Backslash,
    #[token("|")]      Bar,
    #[token("=")]      Assign,
    #[token(".")]      Dot,

    // Punctuation
    #[token("(")]      LParen,
    #[token(")")]      RParen,
    #[token("[")]      LBracket,
    #[token("]")]      RBracket,
    #[token("{")]      LBrace,
    #[token("}")]      RBrace,
    #[token(",")]      Comma,
    #[token(":")]      Colon,
    #[token("_")]      Underscore,
    #[token("<-")]     LeftArrow,

    // Literals
    #[regex(r"[0-9]+\.[0-9]+", |lex| lex.slice().parse::<f64>().ok())]
    FloatLit(f64),
    #[regex(r"[0-9]+", |lex| lex.slice().parse::<i64>().ok())]
    IntLit(i64),
    #[regex(r#""[^"]*""#, |lex| Some(lex.slice()[1..lex.slice().len()-1].to_string()))]
    StringLit(String),

    // Identifiers
    #[regex(r"[a-zA-Z_][a-zA-Z0-9_]*", |lex| Some(lex.slice().to_string()))]
    Ident(String),

    // Skip
    #[regex(r"--[^\n]*", logos::skip)]    // line comments
    #[regex(r"[ \t\n\r]+", logos::skip)]  // whitespace
}
```

**Test vectors for lexer:**

| Input | Expected tokens |
|-------|----------------|
| `fn f(x: Int) -> Int = x + 1` | `Fn Ident("f") LParen Ident("x") Colon Ident("Int") RParen Arrow Ident("Int") Assign Ident("x") Plus IntLit(1)` |
| `x \|> map f` | `Ident("x") Pipe Ident("map") Ident("f")` |
| `\x -> x + 1` | `Backslash Ident("x") Arrow Ident("x") Plus IntLit(1)` |
| `-- comment\n42` | `IntLit(42)` |
| `"hello"` | `StringLit("hello")` |
| `3.14` | `FloatLit(3.14)` |
| `true and false` | `True And False` |
| `match x with \| 1 -> "a"` | `Match Ident("x") With Bar IntLit(1) Arrow StringLit("a")` |

### Stage 2: Parser (chumsky)

Produces this AST:

```rust
enum Expr {
    IntLit(i64),
    FloatLit(f64),
    BoolLit(bool),
    StringLit(String),
    Ident(String),
    Apply(Box<Expr>, Box<Expr>),           // f(x)
    Lambda(String, Box<Expr>),             // \x -> body
    Let(Vec<(String, Expr)>, Box<Expr>),   // let x = e in body
    If(Box<Expr>, Box<Expr>, Box<Expr>),   // if c then t else f
    Match(Box<Expr>, Vec<(Pattern, Expr)>),
    BinOp(BinOp, Box<Expr>, Box<Expr>),
    UnOp(UnOp, Box<Expr>),
    List(Vec<Expr>),
    Set(Vec<Expr>),
    Record(Vec<(String, Expr)>),           // { field = value }
    FieldAccess(Box<Expr>, String),        // expr.field
    Tuple(Vec<Expr>),                      // (a, b)
    NoneLit,
    SomeWrap(Box<Expr>),                   // Some x
}

enum Pattern {
    Wildcard,
    IntPat(i64),
    StringPat(String),
    BoolPat(bool),
    NonePat,
    SomePat(String),     // Some x — binds x
    VarPat(String),      // x — binds x
}

enum BinOp { Add, Sub, Mul, Div, Mod, Eq, Neq, Lt, Gt, Lte, Gte,
             And, Or, Concat }
enum UnOp { Neg, Not }

struct FnDef {
    name: String,
    params: Vec<(String, Type)>,
    return_type: Type,
    body: Expr,
}

struct Program {
    type_defs: Vec<TypeDef>,
    functions: Vec<FnDef>,
}
```

**Desugaring (done during parsing, before type checking):**
- `a |> f` → `Apply(f, a)`
- `[e | x <- xs, p]` → `Apply(map, Lambda(x, e), Apply(filter, Lambda(x, p), xs))`
- `where x = e` → `Let([(x, e)], body)`
- `(== val)` → `Lambda(__x, BinOp(Eq, Ident(__x), val))`
- `(+ 1)` → `Lambda(__x, BinOp(Add, Ident(__x), IntLit(1)))`
- `\x y -> e` → `Lambda(x, Lambda(y, e))`

**Test vectors for parser:**

| Input | Expected AST (simplified) |
|-------|--------------------------|
| `42` | `IntLit(42)` |
| `x + y * z` | `BinOp(Add, x, BinOp(Mul, y, z))` |
| `f a b` | `Apply(Apply(f, a), b)` |
| `x \|> f \|> g` | `Apply(g, Apply(f, x))` |
| `if true then 1 else 2` | `If(BoolLit(true), IntLit(1), IntLit(2))` |
| `\x -> x + 1` | `Lambda("x", BinOp(Add, Ident("x"), IntLit(1)))` |

### Stage 3: Type Checker

Bidirectional type checking (not full Hindley-Milner — simpler, since
no user-defined polymorphism). Every function has an explicit type
signature. The checker:

1. Populates the type environment with all built-in function signatures.
2. Adds all user `fn` definitions to the environment.
3. Checks each function body against its declared return type.
4. Infers types for `let` bindings, lambda parameters (from context),
   and subexpressions.
5. Resolves polymorphic builtins (`map`, `filter`, etc.) by
   unification at each call site.

**Type errors reported with source spans via ariadne.**

**Checked invariants:**
- Every `if` has matching `then`/`else` types.
- Every `match` arm has the same result type.
- Every `match` has a wildcard or covers all patterns.
- Binary operators have matching operand types.
- Function arguments match parameter types.
- Record field access is valid (field exists in record type).
- The five extension functions (if defined) have the correct signatures.

### Stage 4: Call Graph Check

Build a directed graph: edge from `f` to `g` if `f`'s body calls `g`.
Check for cycles (topological sort — if it fails, there's a cycle).
Report the cycle in the error message.

This is ~50 lines. It replaces the structural recursion termination
checker from the earlier spec.

### Stage 5: WASM Codegen (wasm-encoder)

**Function compilation:** Each `fn` becomes a WASM function. Local
variables are WASM locals. The body is compiled as a single
expression that leaves its result on the stack.

**Compilation rules (WASM GC):**

| Felt construct | WASM GC output |
|---------------|----------------|
| `IntLit(n)` | `i64.const n` |
| `FloatLit(f)` | `f64.const f` |
| `BoolLit(b)` | `i32.const 0\|1` |
| `StringLit(s)` | `array.new_data $String $data_offset $len` (from data section) |
| `Ident(x)` | `local.get $x` |
| `BinOp(Add, a, b)` | `[compile a] [compile b] i64.add` |
| `BinOp(Eq, a, b)` | `[compile a] [compile b] i64.eq` |
| `Apply(f, x)` | `[compile x] call $f` |
| `Let(binds, body)` | For each: `[compile val] local.set $var`. Then `[compile body]` |
| `If(c, t, f)` | `[compile c] if (result ...) [compile t] else [compile f] end` |
| `Match(e, arms)` | `[compile e] local.set $match_val` then cascade of if/else |
| `Lambda(...)` | After closure conversion: `call $__lambda_N` with captured vars |
| `[a, b, c]` | `array.new_fixed $Array_T 3` then `array.set` for each element |
| `{ f = v }` | `[compile each field] struct.new $RecordType` |
| `.field` | `struct.get $RecordType $field_index` |
| `None` | `ref.null $T` |
| `Some x` | `[compile x]` (the non-null ref IS the Some) |
| `is_none x` | `ref.is_null [compile x]` |
| `match ... Some` | `ref.is_null br_if $none_branch` then `ref.as_non_null` |

**Built-in functions** are compiled as WASM function bodies in the
runtime module. They use GC instructions internally (e.g., `map`
creates a new `array.new` and fills it with `array.set`). Each
built-in has a known function index.

**WASM module structure (WASM 3.0 + GC):**

```
TypeSection:       GC struct/array type definitions + function signatures
ImportSection:     (none — self-contained)
FunctionSection:   function indices
MemorySection:     1 memory, min 1 page (for JSON I/O buffers only)
ExportSection:     "memory", "alloc", "dealloc", + extension functions
DataSection:       string literals (for array.new_data)
CodeSection:       function bodies (user + runtime)
```

Note: `alloc`/`dealloc` are still exported for the JSON I/O buffer
in linear memory (the WasmHost ABI passes JSON strings through
linear memory). All game data structures use the GC heap instead.

---

## Error Catalog

### Lexer Errors

| Code | Message | Cause |
|------|---------|-------|
| E001 | `unexpected character '{c}'` | Character not part of any token |
| E002 | `unterminated string literal` | String missing closing `"` |

### Parser Errors

| Code | Message | Cause |
|------|---------|-------|
| E100 | `expected {token}, found {actual}` | Syntax error |
| E101 | `expected expression` | Missing expression after operator |
| E102 | `expected '->' in lambda` | Lambda missing arrow |
| E103 | `expected 'then' after 'if' condition` | If missing then |
| E104 | `expected 'else' branch` | If without else |
| E105 | `expected '\|' pattern` | Match without arms |
| E106 | `expected type annotation after ':'` | Missing type |
| E107 | `expected '=' after function signature` | Fn missing body |

### Type Errors

| Code | Message | Cause |
|------|---------|-------|
| E200 | `type mismatch: expected {t1}, found {t2}` | Expression has wrong type |
| E201 | `unknown identifier '{name}'` | Undefined variable/function |
| E202 | `'{name}' is not a function` | Applying non-function |
| E203 | `wrong number of arguments: {name} takes {n}, got {m}` | Arity mismatch |
| E204 | `field '{f}' does not exist on type {t}` | Bad field access |
| E205 | `non-exhaustive match: missing {patterns}` | Match doesn't cover all cases |
| E206 | `if branches have different types: {t1} vs {t2}` | Branch type mismatch |
| E207 | `extension function '{name}' has wrong signature` | Extension fn type mismatch |

### Call Graph Errors

| Code | Message | Cause |
|------|---------|-------|
| E300 | `recursive call: {f} -> {g} -> ... -> {f}` | Cycle in call graph |

---

## Edge Cases and Defined Behavior

| Situation | Behavior |
|-----------|----------|
| Division by zero (Int) | Returns 0 |
| Division by zero (Float) | Returns `Infinity` or `NaN` (IEEE 754) |
| Integer overflow | Wraps (two's complement, same as WASM `i64`) |
| `max []` / `min []` | Returns 0 |
| `head []` | Returns `None` |
| `tail []` | Returns `[]` |
| `sum []` | Returns 0 |
| `all_same []` | Returns `true` (vacuous truth) |
| `consecutive []` | Returns `true` |
| `combinations xs k` where k > length xs | Returns `[]` |
| `combinations xs k` where k < 0 | Returns `[]` |
| `cell_at` out of bounds | Returns `None` |
| `zone` with unknown name | Returns empty zone (0 cells, 0 components) |
| `zone_for` with unknown player | Returns empty zone |
| `counter_value` on non-counter zone | Returns 0 |
| `property` with unknown key | Returns `""` |
| `rank` on component without rank | Returns 0 |
| `suit` on component without suit | Returns `""` |
| `unwrap_or None default` | Returns `default` |
| `unwrap_or (Some x) default` | Returns `x` |
| Record field type mismatch in JSON | Deserialization returns zero/empty |
| String comparison | Lexicographic (UTF-8 byte order) |
| Set ordering | Sorted by natural order (Int < String < handle) |

---

## Worked Examples

### Poker Hand Scoring

```
type Score = { player: String, points: Int, breakdown: List Entry }
type Entry = { category: String, points: Int }

fn score(state: State) -> List Score =
  players state |> map (\p ->
    let hand = zone_for state "hand" p |> components
        community = zone state "community" |> components
        all_cards = hand ++ community
        best = best_five all_cards
    in { player = name p
       , points = hand_rank best
       , breakdown = [{ category = hand_name best, points = hand_rank best }]
       })

fn best_five(cards: List Component) -> List Component =
  combinations cards 5
  |> sort_by (\combo -> hand_rank combo)
  |> reverse
  |> head
  |> unwrap_or []

fn hand_rank(cards: List Component) -> Int =
  let ranks = cards |> map rank |> sort |> reverse
      suits = cards |> map suit
      is_flush = all_same suits
      is_straight = consecutive ranks
  in
    if is_flush and is_straight then 800 + max ranks
    else if has_group ranks 4 then 700 + group_value ranks 4
    else if has_group ranks 3 and has_group ranks 2 then
      600 + group_value ranks 3 * 10 + group_value ranks 2
    else if is_flush then 500 + max ranks
    else if is_straight then 400 + max ranks
    else if has_group ranks 3 then 300 + group_value ranks 3
    else if count_groups ranks 2 >= 2 then 200 + max ranks
    else if has_group ranks 2 then 100 + group_value ranks 2
    else max ranks

fn hand_name(cards: List Component) -> String =
  let r = hand_rank cards
  in if r >= 800 then "straight flush"
     else if r >= 700 then "four of a kind"
     else if r >= 600 then "full house"
     else if r >= 500 then "flush"
     else if r >= 400 then "straight"
     else if r >= 300 then "three of a kind"
     else if r >= 200 then "two pair"
     else if r >= 100 then "one pair"
     else "high card"
```

### Go Territory Scoring

```
type Score = { player: String, points: Int, breakdown: List Entry }
type Entry = { category: String, points: Int }

fn score(state: State) -> List Score =
  let board = zone state "board"
  in players state |> map (\p ->
    let territory = count_territory board p
        captures = counter_value (zone_for state "captures" p)
    in { player = name p
       , points = territory + captures
       , breakdown = [ { category = "territory", points = territory }
                     , { category = "captures", points = captures }
                     ]
       })

fn count_territory(board: Zone, player: Player) -> Int =
  cells board
  |> filter (\c -> is_none (cell_at board (col c) (row c)))
  |> flood_groups board
  |> filter (\group -> is_controlled_by board group player)
  |> map size
  |> sum

fn is_controlled_by(board: Zone, group: Set Cell, player: Player) -> Bool =
  border_owners board group == from_list [player]
```

### Checkmate Detection

```
type EndResult = { game_over: Bool, winner: String, condition: String }

fn check_end(state: State) -> Option EndResult =
  let board = zone state "board"
      current = current_player state
      opponent = other_player state current
  in
    if in_check board current and no_legal_escape state board current then
      Some { game_over = true
           , winner = name opponent
           , condition = "checkmate"
           }
    else if not (in_check board current) and no_legal_moves state board current then
      Some { game_over = true
           , winner = ""
           , condition = "stalemate"
           }
    else None

fn in_check(board: Zone, player: Player) -> Bool =
  let king_pos = find_king board player
  in opponent_pieces board player
     |> any (\piece -> attacks board piece king_pos)

fn find_king(board: Zone, player: Player) -> Cell =
  components board
  |> filter (\c -> type_of c == "king" and owner c == Some player)
  |> head
  |> map_opt position
  |> flatten
  |> unwrap_or (cell_at board 0 0 |> unwrap_or_default)

fn opponent_pieces(board: Zone, player: Player) -> List Component =
  components board
  |> filter (\c -> owner c != Some player and is_some (owner c))

fn no_legal_escape(state: State, board: Zone, player: Player) -> Bool =
  -- delegates to the declarative engine's legal_moves
  -- then checks each one still results in check
  legal_moves_for state player |> all (\m -> still_in_check board player m)

fn no_legal_moves(state: State, board: Zone, player: Player) -> Bool =
  legal_moves_for state player |> length == 0
```

---

## Implementation Toolchain

| Stage | Crate | Custom code |
|-------|-------|-------------|
| Lexer | `logos` | Token enum (~50 lines) |
| Parser | `chumsky` | Grammar combinators (~400 lines) |
| Desugar | — | Pipe/comprehension/partial elimination (~100 lines) |
| Type checker | — | Bidirectional checking (~500 lines) |
| Call graph check | — | Topological sort (~50 lines) |
| WASM GC codegen | `wasm-encoder` | Expression compiler with GC types (~600 lines) |
| JSON runtime | Pre-compiled WASM | State deserializer, result serializer (~300 lines Rust) |
| Error reporting | `ariadne` | Diagnostic formatting (~100 lines) |
| CLI | `clap` | Three subcommands (~50 lines) |

**Total estimated custom code: ~2,200 lines of Rust.** (GC eliminates
~200 lines of manual memory management from the codegen.)

---

## Relationship to Other Baize Languages

```
Game Definition (JSON)
  ├── CEL expressions      → read-only predicates (end conditions, filters)
  ├── Perturber effects    → bounded mutations (captures, chain reactions)
  └── Felt extensions      → pure computation (scoring, validation, move gen)
       └── compiles to → WASM module loaded by WasmHost
```

CEL and the perturber live inside the game definition JSON. Felt lives
in separate `.felt` files, compiled to `.wasm` binaries, referenced
by the game definition's `wasm_module` field.

If your game logic fits in CEL + perturber, you don't need Felt.
Felt is for when you need algorithms: hand ranking, territory
counting, connected component analysis, complex spatial queries.

If Felt isn't enough, write your extension in Rust.

---

## File Extension

`.felt`

## Name

**Felt** — the woven fabric covering gaming tables. Same family as
baize. Felt is what the game logic is woven from; baize is the
surface it plays on.
