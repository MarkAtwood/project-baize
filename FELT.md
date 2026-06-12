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
   mutation, no I/O, no side effects. A Felt function called twice with
   the same game state returns the same answer.

2. **Total.** Every Felt program terminates. Recursion is structural
   only (you can recurse on sub-lists and sub-trees, not on computed
   values). No unbounded loops.

3. **Board-native.** Built-in types and functions for zones, cells,
   components, adjacency, flood-fill, and connected components. You
   don't implement graph traversal — you call `flood_fill`.

4. **Readable.** ML-inspired syntax with pipe operators. Code reads
   left-to-right, top-to-bottom. No parenthesis soup.

5. **Small.** The entire language fits in this document. No modules, no
   classes, no generics, no macros, no operator overloading.

---

## Types

### Primitive Types

```
Int         -- 64-bit signed integer
Float       -- 64-bit IEEE 754
Bool        -- true, false
String      -- UTF-8 text
```

### Collection Types

```
List a      -- ordered sequence: [1, 2, 3]
Set a       -- unordered unique elements: {1, 2, 3}
Map k v     -- key-value pairs: {"a": 1, "b": 2}
```

### Game Types

These are provided by the runtime. You can't construct them — you
receive them from the game state.

```
State       -- the full game state (opaque, query it with functions)
Zone        -- a named zone (grid, stack, set, counter, track, graph)
Cell        -- a position in a zone (col, row for grids; node name for graphs)
Component   -- a game piece/card/token on the board
Player      -- a player identity
```

### Product Types

```
type Score = { player: String, points: Int, breakdown: List Entry }
type Entry = { category: String, points: Int }
type EndResult = { game_over: Bool, winner: String, condition: String }
```

### Sum Types

```
type Option a = Some a | None
type Result a = Ok a | Error String
```

---

## Syntax

### Literals

```
42                     -- Int
3.14                   -- Float
true                   -- Bool
"hello"                -- String
[1, 2, 3]             -- List Int
{1, 2, 3}             -- Set Int
{"a": 1, "b": 2}      -- Map String Int
```

### Let Bindings

```
let x = 42
let name = "poker"
let cards = zone state "hand" player |> components
```

All bindings are immutable. There is no assignment operator.

### Functions

```
-- Named function
fn score_hand(cards: List Component) -> Int =
  let ranks = cards |> map rank |> sort |> reverse
  let suits = cards |> map suit
  if all_same suits and consecutive ranks then 800 + max ranks
  else if has_group ranks 4 then 700 + group_value ranks 4
  else if has_group ranks 3 and has_group ranks 2 then 600
  else 0

-- Anonymous function (lambda)
cards |> filter (\c -> rank c > 10)

-- Multi-line with where clause
fn territory(state: State, player: Player) -> Int =
  empty_cells board
  |> flood_groups board
  |> filter (surrounded_by player)
  |> map size
  |> sum
  where
    board = zone state "board"
    surrounded_by p group = border_owners group |> all (== p)
```

### Pipe Operator

The pipe `|>` passes the result of the left side as the last argument
to the right side. Chains read left-to-right.

```
-- These are equivalent:
sum (map size (filter f groups))
groups |> filter f |> map size |> sum
```

### Pattern Matching

```
fn describe_hand(hand_type: Int) -> String =
  match hand_type with
  | 800 -> "straight flush"
  | 700 -> "four of a kind"
  | 600 -> "full house"
  | 500 -> "flush"
  | 400 -> "straight"
  | _   -> "other"

fn component_value(c: Component) -> Int =
  match type_of c with
  | "king"   -> 10
  | "queen"  -> 9
  | "rook"   -> 5
  | "bishop" -> 3
  | "knight" -> 3
  | "pawn"   -> 1
  | _        -> 0
```

### Conditionals

```
if x > 0 then x else -x

if is_flush and is_straight then "straight flush"
else if is_flush then "flush"
else if is_straight then "straight"
else "high card"
```

Every `if` must have an `else`. There are no statements — `if` is an
expression that returns a value.

### List Comprehensions

```
-- All pieces owned by player on the board
[c | c <- components board, owner c == player]

-- Scores for each player
[{ player = p, points = count_territory state p } | p <- players state]
```

---

## Board Query Functions

These are built-in. They operate on the game types provided by the
runtime. You don't implement graph algorithms — you call these.

### Zone Access

```
zone : State -> String -> Zone
  -- Get a zone by name.

zone_for : State -> String -> Player -> Zone
  -- Get a per-player zone instance.

components : Zone -> List Component
  -- All components in a zone.

cells : Zone -> List Cell
  -- All cells in a zone (grid: all positions; graph: all nodes).

cell_at : Zone -> Int -> Int -> Option Component
  -- What's at (col, row) in a grid zone? None if empty.

count : Zone -> Int
  -- Number of components in a zone.

counter_value : Zone -> Int
  -- Value of a counter zone.
```

### Component Properties

```
type_of : Component -> String
  -- Component type name ("pawn", "king", "ace_spades").

owner : Component -> Option Player
  -- Who owns this component.

rank : Component -> Int
  -- Numeric rank (cards: 1-13, pieces: defined by game).

suit : Component -> String
  -- Suit or color group.

property : Component -> String -> String
  -- Arbitrary named property from the game definition.

position : Component -> Option Cell
  -- Where is this component on the board?
```

### Grid Operations

```
adjacent : Zone -> Cell -> List Cell
  -- Orthogonally adjacent cells.

diagonal : Zone -> Cell -> List Cell
  -- Diagonally adjacent cells.

neighbors : Zone -> Cell -> List Cell
  -- All 8 neighbors (adjacent + diagonal).

in_bounds : Zone -> Int -> Int -> Bool
  -- Is (col, row) within the grid?

dimensions : Zone -> (Int, Int)
  -- (width, height) of a grid zone.

row_cells : Zone -> Int -> List Cell
  -- All cells in a row.

col_cells : Zone -> Int -> List Cell
  -- All cells in a column.

line_cells : Zone -> Cell -> (Int, Int) -> List Cell
  -- Cells along a direction (dx, dy) from a starting cell.
```

### Graph Operations

```
flood_fill : Zone -> Cell -> (Cell -> Bool) -> Set Cell
  -- Starting from a cell, expand to all connected cells
  -- satisfying the predicate. Adjacency-based.

flood_groups : Zone -> (Cell -> Bool) -> List (Set Cell)
  -- Partition all cells matching the predicate into connected
  -- groups. Each group is a maximal connected component.

connected : Zone -> Cell -> Cell -> (Cell -> Bool) -> Bool
  -- Can you reach cell B from cell A through cells satisfying
  -- the predicate?

path_exists : Zone -> Cell -> Cell -> (Cell -> Bool) -> Bool
  -- Alias for connected.

border : Zone -> Set Cell -> Set Cell
  -- Cells adjacent to the group but not in the group.

border_owners : Zone -> Set Cell -> Set Player
  -- Distinct owners of components on border cells.

liberties : Zone -> Set Cell -> Int
  -- Count of empty cells adjacent to the group.
  -- (Go-specific but generally useful.)
```

### Set and List Operations

```
map : (a -> b) -> List a -> List b
filter : (a -> Bool) -> List a -> List a
fold : (b -> a -> b) -> b -> List a -> b
sum : List Int -> Int
max : List Int -> Int
min : List Int -> Int
sort : List Int -> List Int
reverse : List a -> List a
length : List a -> Int
head : List a -> Option a
tail : List a -> List a
zip : List a -> List b -> List (a, b)
flatten : List (List a) -> List a
unique : List a -> Set a
contains : List a -> a -> Bool
all : (a -> Bool) -> List a -> Bool
any : (a -> Bool) -> List a -> Bool
all_same : List a -> Bool
consecutive : List Int -> Bool

-- Set operations
union : Set a -> Set a -> Set a
intersect : Set a -> Set a -> Set a
difference : Set a -> Set a -> Set a
size : Set a -> Int
member : Set a -> a -> Bool

-- Map operations
lookup : Map k v -> k -> Option v
keys : Map k v -> List k
values : Map k v -> List v
```

### Grouping (for card games)

```
group_by : (a -> k) -> List a -> Map k (List a)
  -- Group elements by a key function.
  -- Example: group_by rank cards -> {10: [10h, 10s], 7: [7d]}

count_groups : List Int -> Int -> Int
  -- How many groups of exactly size N exist?
  -- count_groups [10, 10, 10, 7, 7] 3 -> 1  (one triple)

has_group : List Int -> Int -> Bool
  -- Is there a group of size >= N?

group_value : List Int -> Int -> Int
  -- Value of the largest group of size N.
  -- group_value [10, 10, 10, 7, 7] 3 -> 10
```

### Game State

```
players : State -> List Player
current_player : State -> Player
turn : State -> Int
phase : State -> String
counters : State -> Map String Int
is_finished : State -> Bool
```

---

## Extension Interface

A Felt file implements one or more of five standard functions. Each
corresponds to a method on the `GameExtension` trait:

```
-- Optional: custom move legality check
fn is_legal(state: State, player: Player, action: Action) -> Option Bool =
  ...

-- Optional: additional legal moves
fn legal_moves(state: State, player: Player) -> List Action =
  ...

-- Optional: post-move effects (chain reactions)
fn apply_effect(state: State, trigger: String) -> State =
  ...

-- Optional: compute scores for all players
fn score(state: State) -> List Score =
  ...

-- Optional: check if the game has ended
fn check_end(state: State) -> Option EndResult =
  ...
```

You implement only the functions your game needs. Unimplemented
functions defer to the declarative engine.

---

## Worked Examples

### Poker Hand Scoring

```
fn score(state: State) -> List Score =
  players state |> map (\p ->
    let hand = zone_for state "hand" p |> components
        community = zone state "community" |> components
        all_cards = hand ++ community
        best = best_five all_cards
    in { player = p
       , points = hand_rank best
       , breakdown = [{ category = hand_name best, points = hand_rank best }]
       })

fn best_five(cards: List Component) -> List Component =
  combinations cards 5
  |> map (\combo -> (hand_rank combo, combo))
  |> sort_by fst
  |> reverse
  |> head
  |> map snd
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
fn score(state: State) -> List Score =
  let board = zone state "board"
  in players state |> map (\p ->
    let territory = count_territory board p
        captures = counter_value (zone_for state "captures" p)
    in { player = p
       , points = territory + captures
       , breakdown = [ { category = "territory", points = territory }
                     , { category = "captures", points = captures }
                     ]
       })

fn count_territory(board: Zone, player: Player) -> Int =
  empty_cells board
  |> flood_groups board
  |> filter (\group -> is_controlled_by board group player)
  |> map size
  |> sum

fn empty_cells(board: Zone) -> List Cell =
  cells board |> filter (\c -> cell_at board (col c) (row c) == None)

fn is_controlled_by(board: Zone, group: Set Cell, player: Player) -> Bool =
  border_owners board group == {player}
```

### Carcassonne City Scoring

```
fn score(state: State) -> List Score =
  let board = zone state "board"
      cities = flood_groups board is_city_tile
  in players state |> map (\p ->
    let city_points = cities
          |> filter (has_meeple p)
          |> map (\city -> score_city board city)
          |> sum
    in { player = p
       , points = city_points
       , breakdown = [{ category = "cities", points = city_points }]
       })

fn is_city_tile(cell: Cell) -> Bool =
  match cell_at board (col cell) (row cell) with
  | Some c -> property c "terrain" == "city"
  | None   -> false

fn score_city(board: Zone, city: Set Cell) -> Int =
  let tile_count = size city
      has_pennant = city |> any (\c ->
        match cell_at board (col c) (row c) with
        | Some comp -> property comp "pennant" == "true"
        | None -> false)
      pennant_bonus = if has_pennant then 2 else 0
      complete = border board city |> all (\c ->
        cell_at board (col c) (row c) != None)
      multiplier = if complete then 2 else 1
  in (tile_count + pennant_bonus) * multiplier

fn has_meeple(player: Player, group: Set Cell) -> Bool =
  group |> any (\c ->
    match cell_at board (col c) (row c) with
    | Some comp -> type_of comp == "meeple" and owner comp == Some player
    | None -> false)
```

### Checkmate Detection

```
fn check_end(state: State) -> Option EndResult =
  let board = zone state "board"
      current = current_player state
      opponent = other_player state current
  in
    if in_check board current and no_legal_escape board current then
      Some { game_over = true
           , winner = opponent
           , condition = "checkmate"
           }
    else if not (in_check board current) and no_legal_moves board current then
      Some { game_over = true
           , winner = ""
           , condition = "stalemate"
           }
    else
      None

fn in_check(board: Zone, player: Player) -> Bool =
  let king_cell = find_king board player
  in opponent_pieces board player
     |> any (\piece -> can_attack board piece king_cell)

fn no_legal_escape(board: Zone, player: Player) -> Bool =
  own_pieces board player
  |> flat_map (\piece -> legal_destinations board piece)
  |> all (\move -> still_in_check board player move)

fn find_king(board: Zone, player: Player) -> Cell =
  components board
  |> filter (\c -> type_of c == "king" and owner c == Some player)
  |> head
  |> map position
  |> flatten
  |> unwrap_or (0, 0)
```

---

## Termination

Felt guarantees termination through two restrictions:

1. **No general recursion.** Functions can only recurse on structural
   sub-parts of their arguments (a sub-list, a subset, a smaller
   collection). The compiler rejects recursion on computed values.

2. **No unbounded iteration.** `map`, `filter`, `fold`, and list
   comprehensions iterate over finite collections received from the
   game state. There is no `while` or `loop`.

The compiler performs a termination check during compilation and
rejects programs that cannot be proven total.

### What You Can Do

```
-- OK: structural recursion on a sub-list
fn sum_list(xs: List Int) -> Int =
  match xs with
  | [] -> 0
  | x :: rest -> x + sum_list rest    -- rest is strictly smaller

-- OK: iterate over a finite collection from game state
components board |> map rank |> sum
```

### What You Cannot Do

```
-- REJECTED: recursion on a computed value
fn collatz(n: Int) -> Int =
  if n == 1 then 0
  else if n % 2 == 0 then 1 + collatz (n / 2)    -- not structural
  else 1 + collatz (3 * n + 1)                    -- not structural

-- REJECTED: no loop construct exists
while not_done do ...    -- syntax error: 'while' is not a keyword
```

### No Gas — Termination + WASM Fuel Instead

Felt does **not** have a gas or fuel mechanism. Two layers provide
safety without burdening game designers:

1. **Compile-time termination.** The Felt compiler proves every
   program terminates before emitting WASM. This is a stronger
   property than gas — gas says "we'll kill it if it runs too long,"
   termination says "it's impossible for it to run too long." Game
   designers never see a gas budget or hit a gas error.

2. **WASM fuel (runtime backstop).** The Baize server's wasmtime
   runtime enforces an instruction-level fuel limit on all WASM
   modules (1 billion instructions per call). This catches Felt
   programs that terminate but are slow (e.g., combinatorial
   explosion on large game states), and also protects against
   hand-crafted WASM that bypasses Felt entirely.

```
Felt (.felt)  →  termination guaranteed (compile-time)
                 + WASM fuel limit (runtime backstop)

Rust (.rs)    →  no termination guarantee
                 + WASM fuel limit (runtime, only defense)
```

This is defense-in-depth at different layers. Felt is the compile-time
guarantee for game designers. WASM fuel is the runtime guarantee for
everyone, including Rust power users writing extensions directly.

---

## Compilation

```
felt compile poker.felt -o poker.wasm
felt check poker.felt              # type-check and termination-check only
felt run poker.felt --state game.json   # interpret locally (for debugging)
```

### Pipeline

```
Source (.felt)
  → Lexer (logos)        → Tokens
  → Parser (chumsky)     → AST
  → Type Checker         → Typed AST
  → Termination Checker  → Verified AST
  → WASM Codegen         → .wasm binary
    (wasm-encoder)
```

### Implementation: Off-the-Shelf Rust

The compiler uses established Rust crates wherever possible. Custom
code is limited to the two game-specific passes (type checking with
game types, termination checking).

| Stage | Crate | Role |
|-------|-------|------|
| Lexer | `logos` | Derive-macro lexer. Define tokens as an enum, logos generates a zero-copy DFA. |
| Parser | `chumsky` | Parser combinator with error recovery and source spans. Integrates with logos via zero-copy adapter. |
| Type checker | Hand-rolled | ~500 lines. Hindley-Milner inference with game-specific base types (State, Zone, Cell, Component, Player). |
| Termination checker | Hand-rolled | ~200 lines. Verify recursion is structural (argument is strict sub-part of input). |
| WASM codegen | `wasm-encoder` | Bytecode Alliance crate. Direct WASM binary emission — build type, function, export, and code sections, then serialize. No intermediate representation. |
| Error reporting | `ariadne` | Beautiful terminal diagnostics with source spans and colored annotations. Pairs with chumsky's error types. |
| CLI | `clap` | Standard Rust CLI argument parsing. |

**Why `wasm-encoder` and not Cranelift?** Cranelift compiles *from*
WASM to native. We compile *to* WASM. `wasm-encoder` is the right
tool: you emit WASM stack-machine bytecodes directly. For a language
this simple (no closures, no GC, no exceptions, no mutation), codegen
is straightforward — each Felt expression maps to a short sequence of
WASM instructions.

**WASM codegen strategy:** Felt is expression-oriented and pure, which
maps naturally to WASM's stack machine:
- Literals push values onto the stack.
- Binary operators pop two values, push one result.
- Function calls use WASM `call` instructions.
- `if/else` uses WASM `if/else/end` blocks.
- `let` bindings become WASM `local.set`/`local.get`.
- Pattern matching compiles to cascading `if` blocks with `br_table`
  for integer dispatch.
- List operations (map, filter, fold) compile to linear memory
  iteration with bounds-checked indexing.
- The pipe operator `|>` is just syntactic sugar — desugared to
  function application before codegen.

**Target output:** typical Felt extensions (poker scoring, Go
territory) should produce WASM binaries under 50KB, including the
embedded JSON deserialization runtime.

The WASM binary exports the standard `alloc`, `dealloc`, and whichever
of the five extension functions (`is_legal`, `legal_moves`,
`apply_effect`, `score`, `check_end`) the source file defines.

The JSON-string ABI matches the existing `WasmHost` in the Baize
server: game state is passed as serialized JSON, results are returned
as serialized JSON. The Felt runtime (compiled into the WASM binary)
handles deserialization into Felt's native types.

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

---

## File Extension

`.felt`

## MIME Type

`application/x-felt`

## Name

**Felt** — the woven fabric covering gaming tables. Same family as
baize. Felt is what the game logic is woven from; baize is the
surface it plays on.
