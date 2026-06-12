# Baize — Standard Component Registry

The component registry defines reusable, well-known game pieces that any
game can reference by identifier. Clients cache these once and render any
game that uses them. Implemented registry entries are JSON files in
`registry/` validated against `schema/component-registry.schema.json`.
The examples below use YAML pseudocode for readability.

## Design Principle: Primitives, Not Products

We define generic components (colored pawns, lettered tiles, numbered cards)
rather than trademarked products. "A 20×20 grid with letter tiles and point
values" is a game mechanism, not intellectual property.

## Instantiation Hierarchy

Borrowed from Screentop.gg's data model and BGA's architecture:

```
Registry (standard:french-52)
  └─ Template: "poker card" — SVG layout, 63×88mm, rounded corners
       └─ Type: "Ace of Spades" — rank=A, suit=spades, color=black
            └─ Instance: card #37 in this shuffled deck
                 └─ Placement: in Alice's hand, face-down, position 3
```

- **Registry + Template** = static, cached by client, shared across all games
- **Type** = defined per game (or inherited from registry), immutable during play
- **Instance** = created at game setup (server shuffles deck, deals), has identity
- **Placement** = mutable game state (position, facing, owner changes per move)

A game schema defines Types and references Templates. The server creates
Instances at setup. Placements are the dynamic state that changes every turn.

## Physical Form Factors (from The Game Crafter catalog)

Every component MAY declare physical manufacturing metadata. This enables
print-and-play export, TGC/Panda manufacturing specs, and AR rendering
at real-world scale.

```yaml
physical_forms:
  poker_card:    { size_mm: [63, 88],  thickness_mm: 0.32, material: cardstock }
  bridge_card:   { size_mm: [57, 89],  thickness_mm: 0.32, material: cardstock }
  tarot_card:    { size_mm: [70, 120], thickness_mm: 0.32, material: cardstock }
  mini_card:     { size_mm: [44, 63],  thickness_mm: 0.32, material: cardstock }
  square_tile:   { size_mm: [50, 50],  thickness_mm: 2.0,  material: chipboard }
  hex_tile:      { size_mm: [50, 43],  thickness_mm: 2.0,  material: chipboard }
  large_tile:    { size_mm: [75, 75],  thickness_mm: 2.0,  material: chipboard }
  meeple:        { size_mm: [16, 16],  thickness_mm: 10.0, material: wood }
  disc_small:    { size_mm: [15, 15],  thickness_mm: 4.0,  material: wood }
  disc_large:    { size_mm: [25, 25],  thickness_mm: 6.0,  material: wood }
  cube_8mm:      { size_mm: [8, 8],    thickness_mm: 8.0,  material: wood }
  cube_10mm:     { size_mm: [10, 10],  thickness_mm: 10.0, material: wood }
  pawn_cone:     { size_mm: [12, 12],  thickness_mm: 24.0, material: wood }
  standee_small: { size_mm: [25, 32],  thickness_mm: 3.0,  material: chipboard }
  standee_large: { size_mm: [38, 50],  thickness_mm: 3.0,  material: chipboard }
  d6_standard:   { size_mm: [16, 16],  thickness_mm: 16.0, material: plastic }
  d6_large:      { size_mm: [20, 20],  thickness_mm: 20.0, material: plastic }
  token_round:   { size_mm: [20, 20],  thickness_mm: 2.0,  material: chipboard }
  coin_metal:    { size_mm: [25, 25],  thickness_mm: 2.5,  material: metal }
```

Games reference these by name: `physical_form: poker_card`. Clients use
dimensions for layout; manufacturing tools use them for print specs.
This is optional metadata — games work fine without it.

## The Universal Primitive: Glyph Tile

The most general component is a shape + color + glyph:

```yaml
# Any game piece is reducible to:
primitive:
  shape: circle | square | rounded_rect | hexagon | meeple | disc | custom_svg
  fill: <color>
  stroke: <color> | none
  glyph: <unicode_codepoint> | <svg_symbol_ref> | none
  glyph_color: <color>
  label: <text>  # optional secondary text (point value, cost)
  size: <relative_scale>
```

This covers:
- Go stone = `{shape: circle, fill: black, glyph: none}`
- Mahjong tile = `{shape: rounded_rect, fill: ivory, glyph: "🀄"}`
- Chess king = `{shape: circle, fill: white, glyph: "♔"}`
- Scrabble tile = `{shape: square, fill: "#D2B48C", glyph: "A", label: "1"}`
- Generic pawn = `{shape: meeple, fill: player_color, glyph: none}`

Everything below is sugar over this primitive.

---

## Stones and Counters

### Go Stones
```yaml
standard:go-stones:
  type: stone
  variants:
    black: { shape: circle, fill: "#1a1a1a", stroke: none }
    white: { shape: circle, fill: "#f5f5f5", stroke: "#ccc" }
  supply: unlimited
  properties: [position]
```

### Colored Stones (generic)
```yaml
standard:stones-colored:
  type: stone
  parameterized_by: color
  shape: circle
  available_colors:
    - black, white, red, blue, green, yellow, orange, purple, pink, brown
  supply: configurable
  # Used by: Mancala seeds, Chinese Checkers, Pente, abstract games
```

### Glass Beads
```yaml
standard:glass-beads:
  type: stone
  shape: circle
  style: gradient  # shiny/translucent appearance
  available_colors: [red, blue, green, amber, clear, cobalt]
  # Used by: Mancala, marble games, point trackers
```

### Flat Discs (Othello/Reversi, Checkers, Backgammon)
```yaml
standard:discs-reversible:
  type: disc
  shape: disc  # flat cylinder
  sides:
    face: { fill: <color_a> }
    back: { fill: <color_b> }
  flip: true  # can be flipped (Othello)
  # Othello: black/white
  # Checkers: red/black (with optional "kinged" crown glyph)

standard:discs-solid:
  type: disc
  shape: disc
  parameterized_by: color
  available_colors: [white, black, red, blue, green, yellow]
  # Backgammon, Ludo, generic counters
```

---

## Pawns and Figures

### Generic Meeples (tile-placement-style)
```yaml
standard:meeples:
  type: pawn
  shape: meeple  # the iconic silhouette
  parameterized_by: color
  available_colors: [red, blue, green, yellow, black, white, orange, purple, pink]
  # Used by: worker placement games, area control, generic player markers
```

### Generic Pawns (cone-shaped)
```yaml
standard:pawns-cone:
  type: pawn
  shape: cone
  parameterized_by: color
  available_colors: [red, blue, green, yellow, white, black]
  # Used by: Sorry-likes, Parcheesi-likes, roll-and-move games
```

### Generic Cylinders
```yaml
standard:cylinders:
  type: token
  shape: cylinder
  parameterized_by: color
  available_colors: [red, blue, green, yellow, white, black, natural_wood]
  # Used by: resource markers, action spots, Eurogames
```

### Houses and Hotels (property games)
```yaml
standard:buildings:
  variants:
    house: { shape: house, fill: green, size: small }
    hotel: { shape: house, fill: red, size: large }
  # Generic property improvement tokens
```

---

## Dice

### Standard Numbered Dice
```yaml
standard:d4:  { type: die, faces: 4, values: [1,2,3,4] }
standard:d6:  { type: die, faces: 6, values: [1,2,3,4,5,6] }
standard:d8:  { type: die, faces: 8, values: [1,2,3,4,5,6,7,8] }
standard:d10: { type: die, faces: 10, values: [0,1,2,3,4,5,6,7,8,9] }
standard:d12: { type: die, faces: 12, values: [1..12] }
standard:d20: { type: die, faces: 20, values: [1..20] }
standard:d100: { type: die, faces: 100, values: [1..100], note: "percentile" }
```

### Special Dice
```yaml
standard:d6-pips:
  type: die
  faces: 6
  display: pip_pattern  # visual dots, not numerals
  # Matters for games like Liar's Dice where pip display is gameplay

standard:fudge:
  type: die
  faces: 6
  values: [-, -, blank, blank, +, +]
  # FATE/Fudge RPG system

standard:d6-direction:
  type: die
  faces: 6
  values: [N, S, E, W, NE, NW]
  # Used by wargames, some exploration games

standard:d6-colors:
  type: die
  faces: 6
  values: [red, blue, green, yellow, white, black]
  # Color die for various family games
```

---

## Card Decks

### European/Western

```yaml
standard:french-52:
  name: French/International Playing Cards
  type: card_deck
  suits: [spades, hearts, diamonds, clubs]
  suit_symbols: ["♠", "♥", "♦", "♣"]
  suit_colors: { spades: black, hearts: red, diamonds: red, clubs: black }
  ranks: ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
  rank_values: { A: [1,14], "2": 2, ..., "10": 10, J: 11, Q: 12, K: 13 }
  count: 52
  facing: face_up | face_down

standard:french-54:
  extends: standard:french-52
  extra: [{ rank: "Joker", suit: red }, { rank: "Joker", suit: black }]
  count: 54

standard:french-32:
  name: Piquet Deck (Skat, Belote)
  subset_of: standard:french-52
  ranks: ["7", "8", "9", "10", "J", "Q", "K", "A"]
  count: 32

standard:french-36:
  name: Russian/Swiss-French Deck
  subset_of: standard:french-52
  ranks: ["6", "7", "8", "9", "10", "J", "Q", "K", "A"]
  count: 36
```

### Germanic

```yaml
standard:german-36:
  name: German-Suited Cards (Skat)
  suits: [acorns, leaves, hearts, bells]
  suit_symbols: ["🌰", "🍃", "♥", "🔔"]
  ranks: ["6", "7", "8", "9", "10", "U", "O", "K", "A"]
  # U=Unter(Jack), O=Ober(Queen equivalent), K=König, A=Ass
  count: 36

standard:swiss-german-36:
  name: Swiss-German Cards (Jass)
  suits: [acorns, shields, roses, bells]
  suit_symbols: ["🌰", "🛡", "🌹", "🔔"]
  ranks: ["6", "7", "8", "9", "10", "U", "O", "K", "A"]
  count: 36
```

### Iberian

```yaml
standard:spanish-40:
  name: Spanish Suited Cards
  suits: [coins, cups, swords, clubs]
  suit_symbols: ["🪙", "🏆", "⚔", "🏏"]
  ranks: ["1", "2", "3", "4", "5", "6", "7", "10", "11", "12"]
  # 8 and 9 omitted in standard 40-card deck
  count: 40

standard:spanish-48:
  name: Spanish Full Deck
  suits: [coins, cups, swords, clubs]
  ranks: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
  count: 48

standard:italian-40:
  name: Italian Suited Cards (regional variations exist)
  suits: [coins, cups, swords, batons]
  suit_symbols: ["🪙", "🏆", "⚔", "🪵"]
  ranks: ["A", "2", "3", "4", "5", "6", "7", "J", "Q", "K"]
  count: 40
```

### Tarot

```yaml
standard:tarot-78:
  name: Tarot Deck (Tarot de Marseille / Rider-Waite structure)
  composition:
    major_arcana:
      count: 22
      ranks: ["0:Fool", "I:Magician", "II:High Priestess", ..., "XXI:World"]
      suit: major
    minor_arcana:
      suits: [wands, cups, swords, pentacles]
      ranks: ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Page", "Knight", "Queen", "King"]
      count: 56
  total: 78
  # Used for: Tarot card games (Tarock, French Tarot), divination decks

standard:tarock-54:
  name: Austrian Tarock (Industrie und Glück)
  # Reduced tarot deck for the actual card game
  composition:
    trumps: 22  # major arcana
    suits: [hearts, diamonds, spades, clubs]
    ranks: ["7", "8", "9", "10", "J", "Q", "K", "A"]  # 8 per suit
  count: 54
```

### East Asian

```yaml
standard:hanafuda-48:
  name: Hanafuda (Japanese Flower Cards)
  months: [pine, plum, cherry, wisteria, iris, peony,
           bush_clover, pampas, chrysanthemum, maple, willow, paulownia]
  cards_per_month: 4
  card_types: [plain, ribbon, animal, bright]
  count: 48
  # Scoring combinations (yaku) are game-specific

standard:hwatu-48:
  name: Hwatu (Korean Flower Cards)
  note: Korean adaptation of Hanafuda
  extends: standard:hanafuda-48
  visual_style: plastic  # traditionally brighter colors than Japanese

standard:karuta-100:
  name: Hyakunin Isshu (Japanese Poetry Cards)
  composition:
    reading_cards: 100  # torifuda - cards to grab
    reciting_cards: 100  # yomifuda - cards read aloud
  # Competitive karuta is a real sport
  count: 200
```

### Chinese

```yaml
standard:chinese-money-cards-120:
  name: Chinese Money-Suited Cards
  suits: [coins, strings, myriads, tens_of_myriads]
  ranks: ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
  extra: [red_flower, white_flower, old_thousand]
  count: ~120 (varies by regional variant)

standard:four-color-cards-112:
  name: Sì Sè Pái (Four Color Cards)
  # Chess-piece based card game
  colors: [red, yellow, green, white]
  pieces_per_color: [general, advisor, elephant, chariot, horse, cannon, soldier]
  duplicates: 2 per piece per color (except generals)
  count: 112
```

---

## Tile Sets

### Dominoes

```yaml
standard:dominoes-double-six:
  name: Double-Six Dominoes
  type: tile
  shape: rectangle(2:1)  # 2:1 aspect ratio
  halves: 2
  pip_range: [0, 6]
  count: 28  # all combinations of 0-6 on each half, including doubles
  facing: face_up | face_down
  properties: [half_a, half_b]

standard:dominoes-double-nine:
  extends: standard:dominoes-double-six
  pip_range: [0, 9]
  count: 55

standard:dominoes-double-twelve:
  extends: standard:dominoes-double-six
  pip_range: [0, 12]
  count: 91

standard:dominoes-double-fifteen:
  extends: standard:dominoes-double-six
  pip_range: [0, 15]
  count: 136
```

### Mahjong Tiles

```yaml
standard:mahjong-144:
  name: Mahjong Tile Set
  type: tile
  shape: rounded_rect
  composition:
    suits:
      - name: characters  # 萬子
        glyphs: ["🀇", "🀈", "🀉", "🀊", "🀋", "🀌", "🀍", "🀎", "🀏"]
        ranks: [1, 2, 3, 4, 5, 6, 7, 8, 9]
        copies: 4
      - name: bamboo  # 索子
        glyphs: ["🀐", "🀑", "🀒", "🀓", "🀔", "🀕", "🀖", "🀗", "🀘"]
        ranks: [1, 2, 3, 4, 5, 6, 7, 8, 9]
        copies: 4
      - name: dots  # 筒子
        glyphs: ["🀙", "🀚", "🀛", "🀜", "🀝", "🀞", "🀟", "🀠", "🀡"]
        ranks: [1, 2, 3, 4, 5, 6, 7, 8, 9]
        copies: 4
    winds:
      glyphs: ["🀀", "🀁", "🀂", "🀃"]
      names: [east, south, west, north]
      copies: 4
    dragons:
      glyphs: ["🀄", "🀅", "🀆"]
      names: [red, green, white]
      copies: 4
    flowers:
      glyphs: ["🀢", "🀣", "🀤", "🀥"]
      copies: 1
    seasons:
      glyphs: ["🀦", "🀧", "🀨", "🀩"]
      copies: 1
  total: 144
  facing: face_up | face_down

standard:mahjong-136:
  name: Japanese Mahjong (Riichi)
  extends: standard:mahjong-144
  removes: [flowers, seasons]
  adds:
    red_fives: 3  # one per suit, replace a regular 5
  total: 136
```

### Generic Glyph Tiles

The universal tile: any Unicode character on a colored background.

```yaml
standard:glyph-tile:
  name: Unicode Glyph Tile (parameterized)
  type: tile
  shape: rounded_rect | square | hexagon
  parameters:
    glyph: <any_unicode_codepoint_or_string>
    fill: <background_color>
    glyph_color: <foreground_color>
    size: small | medium | large
  # This is the escape hatch — any symbol on any colored tile

# Example uses:
# Letter tiles (word games):
#   glyph_tile(glyph: "A", fill: tan, label: "1")
#   glyph_tile(glyph: "Z", fill: tan, label: "10")
#
# Emoji tiles (Azul-like pattern games):
#   glyph_tile(glyph: "⬟", fill: blue)
#   glyph_tile(glyph: "✦", fill: red)
#
# Rune tiles:
#   glyph_tile(glyph: "ᚠ", fill: stone_gray)
#
# Chinese chess (Xiangqi) pieces:
#   glyph_tile(glyph: "將", fill: red)
#   glyph_tile(glyph: "帥", fill: black)
#
# Korean chess (Janggi) pieces:
#   glyph_tile(glyph: "漢", fill: red, shape: octagon)
#
# Shogi pieces (Japanese chess):
#   glyph_tile(glyph: "王", fill: wood, shape: pentagon)
```

### Letter Tiles (word games)

```yaml
standard:letter-tiles-english:
  name: English Letter Tiles
  type: tile
  shape: square
  fill: "#D2B48C"  # tan/wood
  glyph_color: black
  distribution:  # count and point value per letter
    A: { count: 9,  points: 1 }
    B: { count: 2,  points: 3 }
    C: { count: 2,  points: 3 }
    D: { count: 4,  points: 2 }
    E: { count: 12, points: 1 }
    F: { count: 2,  points: 4 }
    G: { count: 3,  points: 2 }
    H: { count: 2,  points: 4 }
    I: { count: 9,  points: 1 }
    J: { count: 1,  points: 8 }
    K: { count: 1,  points: 5 }
    L: { count: 4,  points: 1 }
    M: { count: 2,  points: 3 }
    N: { count: 6,  points: 1 }
    O: { count: 8,  points: 1 }
    P: { count: 2,  points: 3 }
    Q: { count: 1,  points: 10 }
    R: { count: 6,  points: 1 }
    S: { count: 4,  points: 1 }
    T: { count: 6,  points: 1 }
    U: { count: 4,  points: 1 }
    V: { count: 2,  points: 4 }
    W: { count: 2,  points: 4 }
    X: { count: 1,  points: 8 }
    Y: { count: 2,  points: 4 }
    Z: { count: 1,  points: 10 }
    blank: { count: 2, points: 0, wildcard: true }
  total: 100

# Other languages follow same pattern:
standard:letter-tiles-french:
  # ...distribution differs (more E, accented letters)
standard:letter-tiles-german:
  # ...includes Ä, Ö, Ü
standard:letter-tiles-spanish:
  # ...includes Ñ, LL, RR, CH
standard:letter-tiles-arabic:
  # ...right-to-left glyphs
standard:letter-tiles-hebrew:
  # ...22 letters + finals
```

---

## Chess-Family Piece Sets

### International Chess
```yaml
standard:chess-pieces:
  type: piece_set
  glyphs:
    white: { king: "♔", queen: "♕", rook: "♖", bishop: "♗", knight: "♘", pawn: "♙" }
    black: { king: "♚", queen: "♛", rook: "♜", bishop: "♝", knight: "♞", pawn: "♟" }
  movement:  # rules included — a game can reference this and get chess movement free
    king: step(adjacent, 1)
    queen: slide(orthogonal | diagonal)
    rook: slide(orthogonal)
    bishop: slide(diagonal)
    knight: leap(1,2) | leap(2,1)
    pawn: step(forward, 1, if:empty) | step(forward, 2, if:first_move AND empty) | step(forward_diagonal, 1, if:enemy)
```

### Xiangqi (Chinese Chess)
```yaml
standard:xiangqi-pieces:
  type: piece_set
  shape: disc
  sides:
    red:
      general: { glyph: "帥" }
      advisor: { glyph: "仕" }
      elephant: { glyph: "相" }
      chariot: { glyph: "俥" }
      horse: { glyph: "傌" }
      cannon: { glyph: "炮" }
      soldier: { glyph: "兵" }
    black:
      general: { glyph: "將" }
      advisor: { glyph: "士" }
      elephant: { glyph: "象" }
      chariot: { glyph: "車" }
      horse: { glyph: "馬" }
      cannon: { glyph: "砲" }
      soldier: { glyph: "卒" }
  board_constraints:
    palace: grid(3, 3)  # generals and advisors confined
    river: divides board  # elephants cannot cross
```

### Shogi (Japanese Chess)
```yaml
standard:shogi-pieces:
  type: piece_set
  shape: pentagon  # pointed toward opponent
  owner_indicated_by: direction  # piece faces opponent's side
  pieces:
    king:     { glyph: "王", promoted: null }
    rook:     { glyph: "飛", promoted: { glyph: "龍", gains: step(diagonal,1) } }
    bishop:   { glyph: "角", promoted: { glyph: "馬", gains: step(orthogonal,1) } }
    gold:     { glyph: "金", promoted: null }
    silver:   { glyph: "銀", promoted: { glyph: "全", moves_as: gold } }
    knight:   { glyph: "桂", promoted: { glyph: "圭", moves_as: gold } }
    lance:    { glyph: "香", promoted: { glyph: "杏", moves_as: gold } }
    pawn:     { glyph: "歩", promoted: { glyph: "と", moves_as: gold } }
  special_rules:
    drops: true  # captured pieces can be replayed
    promotion_zone: last_3_ranks
```

### Janggi (Korean Chess)
```yaml
standard:janggi-pieces:
  type: piece_set
  shape: octagon
  sides:
    cho: { color: red, general: "楚" }   # Chu
    han: { color: blue, general: "漢" }  # Han
  # Similar to Xiangqi but octagonal, different movement for elephant/horse
```

---

## Board Topologies (Standard)

```yaml
standard:board-chess:
  type: grid
  size: [8, 8]
  coloring: alternating(light, dark)
  labels: { files: [a,b,c,d,e,f,g,h], ranks: [1,2,3,4,5,6,7,8] }

standard:board-go-19:
  type: grid
  size: [19, 19]
  intersections: true  # pieces on intersections, not cells
  star_points: [[4,4],[4,10],[4,16],[10,4],[10,10],[10,16],[16,4],[16,10],[16,16]]

standard:board-go-13:
  type: grid
  size: [13, 13]
  intersections: true
  star_points: [[4,4],[4,10],[7,7],[10,4],[10,10]]

standard:board-go-9:
  type: grid
  size: [9, 9]
  intersections: true
  star_points: [[3,3],[3,7],[5,5],[7,3],[7,7]]

standard:board-backgammon:
  type: track
  points: 24
  layout: [12, 12]  # two rows of 12
  bar: 1  # center holding zone
  home: per_player  # off-board scoring zone
  direction: per_player(clockwise, counterclockwise)

standard:board-cribbage:
  type: track
  length: 121
  lanes: per_player
  # Scoring track, not a playing surface

standard:board-xiangqi:
  type: grid
  size: [9, 10]
  intersections: true
  river: between_ranks(5, 6)
  palace: [[4,1],[6,3]] AND [[4,8],[6,10]]  # 3x3 zones

standard:board-hex:
  type: hex_grid
  size: 11  # 11x11 is standard Hex
  connectivity: 6  # each hex has 6 neighbors
  edge_ownership: { top_bottom: player_a, left_right: player_b }
```

---

## Currency and Scoring Tokens

```yaml
standard:poker-chips:
  type: counter
  shape: disc
  denominations:
    white:  1
    red:    5
    blue:   10
    green:  25
    black:  100
    purple: 500
    orange: 1000

standard:play-money:
  name: Paper Play Money (Monopoly-style)
  type: card  # bills are card-shaped rectangles
  physical_form: mini_card  # ~44×88mm or similar
  facing: face_up  # always visible, no hidden side
  denominations:
    1:    { color: "#F5F5DC", glyph: "1" }
    2:    { color: "#FFD1DC", glyph: "2" }
    5:    { color: "#FFFACD", glyph: "5" }
    10:   { color: "#98FB98", glyph: "10" }
    20:   { color: "#87CEEB", glyph: "20" }
    50:   { color: "#DDA0DD", glyph: "50" }
    100:  { color: "#FFE4B5", glyph: "100" }
    200:  { color: "#B0E0E6", glyph: "200" }
    500:  { color: "#FFD700", glyph: "500" }
  supply: unlimited  # bank never runs out (per most rulesets)
  visibility: public  # everyone can see how much you have
  # User agents are free to render play money to resemble real
  # currency (locale-appropriate bills, coins, or fantasy designs).
  # The schema defines denomination and color hint; presentation is
  # a client concern.
  # Override denominations for different games:
  #   Monopoly-style: [1, 5, 10, 20, 50, 100, 500]
  #   Life-style: [1000, 5000, 10000, 50000, 100000]

standard:play-money-coins:
  name: Coin Tokens (cardboard or metal)
  type: token
  shape: circle
  physical_form: token_round  # 20mm chipboard disc
  facing: face_up
  denominations:
    1:   { color: "#B87333", glyph: "1" }   # copper
    2:   { color: "#B87333", glyph: "2" }   # copper
    5:   { color: "#C0C0C0", glyph: "5" }   # silver
    10:  { color: "#C0C0C0", glyph: "10" }  # silver
    20:  { color: "#C0C0C0", glyph: "20" }  # silver
    50:  { color: "#FFD700", glyph: "50" }   # gold
    100: { color: "#FFD700", glyph: "100" }  # gold
    200: { color: "#FFD700", glyph: "200" }  # gold
    500: { color: "#FFD700", glyph: "500" }  # gold
  supply: unlimited
  visibility: public
  # For games that use coins instead of bills (many Eurogames)

standard:victory-points:
  type: counter
  shape: star | shield | laurel
  values: [1, 3, 5]
  # Generic VP tokens for Eurogames

standard:resource-cubes:
  type: token
  shape: cube
  parameterized_by: color
  meaning_is_game_defined: true
  # wood=brown, stone=gray, wheat=yellow, brick=red, ore=dark_gray
  # (meanings are per-game, colors are standard)
```

---

## Pattern Tiles (abstract placement games)

```yaml
standard:pattern-tiles:
  name: Colored Pattern Tiles (Azul-like)
  type: tile
  shape: square
  variants:
    - { fill: "#1E3A5F", pattern: "snowflake" }
    - { fill: "#D4A017", pattern: "sun" }
    - { fill: "#8B0000", pattern: "flower" }
    - { fill: "#2E8B57", pattern: "leaf" }
    - { fill: "#4B0082", pattern: "star" }
  count_per_variant: configurable (default: 20)

standard:abstract-shapes:
  name: Geometric Shape Tokens
  shapes: [circle, triangle, square, diamond, star, hexagon]
  colors: [red, orange, yellow, green, blue, purple]
  # 6 shapes × 6 colors = 36 unique combinations
  # Used by: Qwirkle-like pattern matching games
```

---

## Historical and Rare Decks

```yaml
standard:mamluk-52:
  name: Mamluk Cards (ancestor of European cards, ~13th century)
  suits: [coins, cups, swords, polo_sticks]
  ranks: ["1"..."10", "deputy", "second_deputy", "king"]
  count: 52
  note: Oldest known card deck structure; basis for all European decks

standard:ganjifa-96:
  name: Ganjifa (Indian/Persian round cards)
  shape: circle  # round cards!
  suits: 8  # varies: Mughal=8, Dashavatara=10
  ranks_per_suit: 12
  count: 96
  note: Round cards, hand-painted, highly decorative

standard:minchiate-97:
  name: Minchiate (Florentine expanded tarot, 16th century)
  composition:
    standard_tarot: 78
    extra_trumps: 19  # zodiac signs, four elements, four virtues
  count: 97
  note: Largest historical European deck

standard:ceki-60:
  name: Ceki / Cherki (Southeast Asian cards, Chinese-derived)
  shape: narrow_rectangle  # very narrow cards
  suits: [coins, strings, myriads]
  count: 60
  note: Played in Malaysia, Indonesia, Thailand

standard:tujeon-80:
  name: Tujeon (Korean arrow cards)
  shape: narrow_rectangle  # 8:1 aspect ratio
  suits: [man, fish, crow, pheasant, antelope, star, rabbit, horse]
  ranks_per_suit: 10
  count: 80
```

---

## How Games Reference Components

```yaml
# A poker game:
game:
  name: Texas Hold'em
  components:
    deck: standard:french-52
    chips: standard:poker-chips
    # done — no need to redefine 52 cards and chip denominations

# A Mahjong game:
game:
  name: Riichi Mahjong
  components:
    tiles: standard:mahjong-136
    scoring_sticks:
      - { value: 100, count: 40 }
      - { value: 1000, count: 20 }
      - { value: 5000, count: 8 }
      - { value: 10000, count: 4 }

# A custom card game with unique cards:
game:
  name: My Custom Game
  components:
    base_deck: standard:french-52
    custom_cards:
      type: card
      template: glyph_tile(shape: rounded_rect, fill: purple)
      cards:
        - { glyph: "⚡", name: "Lightning Strike", cost: 3 }
        - { glyph: "🛡", name: "Shield Wall", cost: 2 }
        - { glyph: "🌀", name: "Vortex", cost: 5 }

# A chess variant:
game:
  name: Capablanca Chess
  components:
    pieces:
      extends: standard:chess-pieces
      adds:
        archbishop: { glyph: "⛪", movement: [leap(1,2), slide(diagonal)] }
        chancellor: { glyph: "♜♞", movement: [leap(1,2), slide(orthogonal)] }
  zones:
    board:
      extends: standard:board-chess
      size: [10, 8]  # wider board

# A word game in Turkish:
game:
  name: Kelime Oyunu
  components:
    tiles: standard:letter-tiles-turkish
    # If not in registry yet, define inline:
    tiles:
      type: glyph_tile
      shape: square
      fill: "#D2B48C"
      distribution:
        A: { count: 12, points: 1 }
        B: { count: 2, points: 3 }
        C: { count: 2, points: 4 }
        Ç: { count: 2, points: 4 }
        # ... Turkish-specific letter distribution
        Ş: { count: 2, points: 4 }
        Ü: { count: 3, points: 3 }
```

---

## Registry Extensibility

The standard registry is a well-known namespace. Games can:

1. **Reference** a standard set: `standard:french-52`
2. **Extend** a standard set: `extends: standard:chess-pieces` + additions
3. **Subset** a standard set: `standard:french-52, exclude: [rank:2..6]`
4. **Define inline**: full custom component definitions for unique games
5. **Publish** to a community registry: `community:mycardgame/deck-v2`

The registry grows independently of the schema language. Adding a new
historical deck or regional tile set requires no schema changes — just
a new entry in the catalog.

---

## SVG Asset Mapping

Each registry entry maps to SVG templates:

```
standard:french-52/
  template.svg       # parameterized card face
  back.svg           # card back
  suits.svg          # ♠♥♦♣ symbol definitions
  params.json        # 52 entries with rank/suit/color values

standard:mahjong-144/
  template.svg       # parameterized tile face
  back.svg           # tile back (bamboo pattern)
  params.json        # 144 entries with suit/rank/glyph

standard:chess-pieces/
  *.svg              # one SVG per piece type, parameterized by color
```

Clients fetch and cache the SVG bundle for any standard set they encounter.
Custom games ship their own SVG bundle in the same format.
