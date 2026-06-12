# Baize — Example Game Definitions

These examples show the declarative schema applied to real games of
increasing complexity. Each demonstrates different aspects of the
language. Examples use YAML pseudocode for readability; actual game
definitions are JSON files in `games/` validated against
`schema/game-definition.schema.json`.

## Chess (perfect information, movement-heavy)

```yaml
game:
  name: Chess
  players: [white, black]
  information: perfect

zones:
  board:
    type: grid(8, 8)
    visibility: public
    labels:
      files: [a, b, c, d, e, f, g, h]
      ranks: [1, 2, 3, 4, 5, 6, 7, 8]

components:
  pawn:
    owner: per_player
    count: 8
    movement:
      - step(forward, 1, if: empty)
      - step(forward, 2, if: empty AND first_move)
      - step(forward_diagonal, 1, if: enemy)     # capture
      - step(forward_diagonal, 1, if: en_passant) # en passant
    promotion:
      trigger: reaches_rank(8, owner:white) OR reaches_rank(1, owner:black)
      choices: [queen, rook, bishop, knight]

  rook:
    owner: per_player
    count: 2
    movement:
      - slide(orthogonal)
    special: castling_participant

  knight:
    owner: per_player
    count: 2
    movement:
      - leap(1, 2)  # L-shape, ignores intervening pieces
      - leap(2, 1)

  bishop:
    owner: per_player
    count: 2
    movement:
      - slide(diagonal)

  queen:
    owner: per_player
    count: 1
    movement:
      - slide(orthogonal)
      - slide(diagonal)

  king:
    owner: per_player
    count: 1
    movement:
      - step(adjacent)
      - castle(kingside)   # special composite move
      - castle(queenside)
    constraints:
      - cannot_move_into_check

turn_order:
  type: alternating
  players: [white, black]
  actions_per_turn: 1
  mandatory: true  # must move or it's stalemate/checkmate

rules:
  check:
    definition: king is attacked by opponent piece
    constraint: player in check MUST resolve check this turn

  en_passant:
    trigger: opponent pawn advances 2 from start
    window: next_turn_only
    effect: capture as if pawn advanced 1

  castling:
    requires:
      - king has not moved
      - participating rook has not moved
      - no pieces between king and rook
      - king not in check
      - king does not pass through check
      - king does not land in check

end_conditions:
  - type: win
    for: opponent(current)
    when: in_check(current) AND no_legal_moves(current)
    name: checkmate

  - type: draw
    when: NOT in_check(current) AND no_legal_moves(current)
    name: stalemate

  - type: draw
    when: repetition(position, 3)
    name: threefold_repetition

  - type: draw
    when: halfmove_clock >= 100
    name: fifty_move_rule

  - type: draw
    when: insufficient_material
    name: insufficient_material

authority:
  server_only: []  # nothing! pure sequencer for chess
  client_verifiable:
    - all moves (perfect information game)
```

## Poker: Texas Hold'em (hidden information, betting)

```yaml
game:
  name: Texas Hold'em
  players: { min: 2, max: 10 }
  information: imperfect

zones:
  deck:
    type: ordered_stack(52)
    visibility: hidden
    note: only server knows order

  community:
    type: set
    capacity: 5
    visibility: public

  hand:
    type: set
    per_player: true
    capacity: 2
    visibility: private(owner)

  pot:
    type: counter
    visibility: public

  player_chips:
    type: counter
    per_player: true
    visibility: public

  discard:
    type: set
    visibility: hidden
    note: burn cards go here, nobody sees them

components:
  card:
    properties:
      suit: [hearts, diamonds, clubs, spades]
      rank: [2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A]
    facing: face_down (default), face_up (when in community)
    count: 52

phases:
  - name: deal
    server_action: deal(deck, hand, count:2, to:each_player)

  - name: preflop
    type: betting_round
    starts_with: player_after(big_blind)

  - name: flop
    server_action:
      - burn(deck, discard, count:1)
      - reveal(deck, community, count:3)
    then: betting_round(starts_with: first_active_after(dealer))

  - name: turn
    server_action:
      - burn(deck, discard, count:1)
      - reveal(deck, community, count:1)
    then: betting_round(starts_with: first_active_after(dealer))

  - name: river
    server_action:
      - burn(deck, discard, count:1)
      - reveal(deck, community, count:1)
    then: betting_round(starts_with: first_active_after(dealer))

  - name: showdown
    action: reveal(hand, to:all) for remaining players
    resolve: best_hand(hand + community) wins pot

betting_round:
  actions:
    - fold: remove self from hand
    - check: pass (if no bet to match)
    - call: match current bet
    - raise(amount): increase bet (min: previous raise or big blind)
    - all_in: bet remaining chips
  ends_when: all active players have acted and bets are equal

hand_rankings:  # declarative, client can evaluate these locally
  - royal_flush
  - straight_flush
  - four_of_a_kind
  - full_house
  - flush
  - straight
  - three_of_a_kind
  - two_pair
  - one_pair
  - high_card

authority:
  server_only:
    - shuffle(deck)
    - deal(deck, hand)
    - burn(deck, discard)
    - reveal(deck, community)
    - resolve_side_pots  # complex split pot calculation

  client_verifiable:
    - fold()              # always legal
    - check()            # legal if no outstanding bet
    - call()             # legal if outstanding bet and chips >= amount
    - raise(amount)      # legal if chips >= amount and amount >= min_raise
    - hand_comparison()  # given visible cards, client knows rankings
```

## Tile Kingdoms (tile placement, complex scoring needs WASM)

```yaml
game:
  name: Tile Kingdoms
  players: { min: 2, max: 5 }
  information: imperfect  # tile draw is hidden
  wasm_module: tile_kingdoms_scoring.wasm  # field scoring is too complex

zones:
  draw_pile:
    type: ordered_stack(71)
    visibility: hidden
    note: remaining tiles, only server knows order

  current_tile:
    type: single_slot
    visibility: public
    note: the tile just drawn, visible to all before placement

  board:
    type: grid(dynamic)  # grows as tiles are placed
    visibility: public
    cell_type: tile_slot
    adjacency: orthogonal_4

  meeple_supply:
    type: set
    per_player: true
    capacity: 7
    visibility: public  # everyone can see how many meeples you have

components:
  tile:
    count: 71  # base game
    properties:
      edges: [north, east, south, west]  # each is: road, city, field
      center: road | city | monastery | field
      has_pennant: boolean
    facing: face_down (in draw_pile), face_up (when drawn/placed)

  meeple:
    owner: per_player
    count: 7
    properties:
      role: null | knight | thief | monk | farmer
      placed_on: null | feature_id

turn_order:
  type: round_robin
  actions_per_turn:
    - draw_tile: 1 (mandatory, server action)
    - place_tile: 1 (mandatory)
    - place_meeple: 0 or 1 (optional)

rules:
  tile_placement:
    constraints:
      - must be adjacent to existing tile (orthogonal)
      - all touching edges must match (road-road, city-city, field-field)
      - at least one valid placement must exist (if not, discard and redraw)

  meeple_placement:
    constraints:
      - must place on the tile just placed
      - must place on an unoccupied feature
        (feature = connected road/city/field segment; no other meeple
         on any tile in the same connected feature)
      - must have meeple in supply

  scoring:
    # These are the SIMPLE cases declarable in the schema:
    completed_road: tiles_in_road * 1
    completed_city: tiles_in_city * 2 (+ pennants * 2)
    completed_monastery: 9 (monastery + 8 surrounding tiles)

    # This requires WASM because field scoring needs flood-fill
    # over the entire board at game end:
    field_scoring: wasm(score_fields)

authority:
  server_only:
    - shuffle(draw_pile)
    - draw_tile(draw_pile, current_tile)

  client_verifiable:
    - place_tile(position, rotation)
      # client knows: edge matching, adjacency
    - place_meeple(feature)
      # client knows: which features on current tile, feature connectivity
    - score_completed_feature()
      # client can trace connected tiles for roads/cities/monasteries

  wasm_required:
    - score_fields()
      # end-game field scoring: flood-fill from each farmer meeple,
      # determine which completed cities the field touches,
      # resolve majority ownership. Too complex for predicates.
```

## Tic-Tac-Toe (minimal example)

The simplest possible game definition, useful as a reference:

```yaml
game:
  name: Tic-Tac-Toe
  players: [X, O]
  information: perfect

zones:
  board:
    type: grid(3, 3)
    visibility: public

components:
  mark:
    owner: per_player
    count: unlimited  # players never run out

turn_order:
  type: alternating
  players: [X, O]
  actions_per_turn: 1
  mandatory: true

rules:
  placement:
    action: place(mark, board/cell)
    constraint: cell is empty

end_conditions:
  - type: win
    for: current
    when: three_in_line(current.marks, row OR column OR diagonal)

  - type: draw
    when: board is full

authority:
  server_only: []
  client_verifiable: [all]
```

## Naval Battle (hidden information, spatial)

```yaml
game:
  name: Naval Battle
  players: [A, B]
  information: imperfect

zones:
  own_grid:
    type: grid(10, 10)
    per_player: true
    visibility: private(owner)
    note: your ship placements, opponent cannot see

  target_grid:
    type: grid(10, 10)
    per_player: true
    visibility: private(owner)
    note: your record of hits/misses on opponent

phases:
  - name: placement
    simultaneous: true
    action: place_ships(own_grid)
    ends_when: all players have placed all ships

  - name: combat
    turn_order: alternating
    actions_per_turn: 1
    action: fire(opponent_grid, cell)

components:
  ship:
    types:
      carrier: { size: 5 }
      battleship: { size: 4 }
      cruiser: { size: 3 }
      submarine: { size: 3 }
      destroyer: { size: 2 }
    properties:
      orientation: horizontal | vertical
      hits: set(cell_indices)  # which cells have been hit
    one_of_each: true

  peg:
    types:
      hit: { color: red }
      miss: { color: white }

rules:
  placement_constraints:
    - ships cannot overlap
    - ships must be fully within grid
    - ships are horizontal or vertical (no diagonal)

  fire:
    action: choose cell on opponent grid
    server_resolves:
      if ship_at(opponent.own_grid, cell):
        reveal: hit
        mark: hit_peg on target_grid
        check: is_ship_sunk(ship)
        if sunk: reveal ship identity and position
      else:
        reveal: miss
        mark: miss_peg on target_grid

end_conditions:
  - type: win
    for: current
    when: all opponent ships sunk

authority:
  server_only:
    - resolve_fire(cell)     # server checks opponent's hidden grid
    - reveal_sunk_ship()     # hidden → public transition
    - validate_placement()   # confirm ships don't overlap (simultaneous phase)

  client_verifiable:
    - fire(cell)             # legal if cell not already fired upon
    - place_ship(ship, pos, orient)  # legal if fits in grid, no overlap with own ships
```
