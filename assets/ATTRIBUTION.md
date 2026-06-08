# Asset Attribution and Licensing

This file documents all graphical assets used in the Baize project,
their sources, authors, and licenses.

---

## Playing Cards

### SVG-cards (Full Deck)

- **Location:** `svg/card/svg-cards/svg-cards.svg`
- **Description:** Complete set of 52 playing cards plus jokers and card backs,
  rendered as named SVG symbols in a single file. French-style face cards.
- **Author:** David Bellot (original), Huub de Beer (SVG-cards 4.x maintainer)
- **Source:** <https://github.com/htdebeer/SVG-cards>
- **Original project:** <https://svg-cards.sourceforge.net/>
- **License:** LGPL-2.1-or-later (`LGPL-2.1-or-later`)
- **License file:** `svg/card/svg-cards/LICENSE`
- **Modifications:** None. Downloaded as-is from the htdebeer fork (version 4.x).

### Card placeholders (face and back templates)

- **Location:** `svg/card/card-face.svg`, `svg/card/card-back.svg`
- **Description:** Minimal card templates using CSS custom properties for
  theming. These are structural placeholders, not based on any external source.
- **Author:** Baize project
- **License:** Project license (generated -- no external source)

---

## Dice

### Wikimedia Commons dice faces (d6, pips)

- **Location:** `svg/dice/wikimedia/dice-1.svg` through `svg/dice/wikimedia/dice-6.svg`
- **Description:** Six standard d6 die faces with red pips on a white rounded-square body.
- **Author:** Antonsusi (Wikimedia Commons user, noted as "complete repaint")
- **Source URLs:**
  - <https://commons.wikimedia.org/wiki/File:Dice-1.svg>
  - <https://commons.wikimedia.org/wiki/File:Dice-2.svg>
  - <https://commons.wikimedia.org/wiki/File:Dice-3.svg>
  - <https://commons.wikimedia.org/wiki/File:Dice-4.svg>
  - <https://commons.wikimedia.org/wiki/File:Dice-5.svg>
  - <https://commons.wikimedia.org/wiki/File:Dice-6.svg>
- **License:** Public domain (PD-shape -- simple geometry ineligible for copyright)
- **Modifications:** Renamed from `Dice-N.svg` to `dice-N.svg`.

### Dice placeholders (themed)

- **Location:** `svg/dice/d6-1.svg` through `svg/dice/d6-6.svg`
- **Description:** Minimal die-face SVGs using CSS custom properties for theming.
  Not based on any external source.
- **Author:** Baize project
- **License:** Project license (generated -- no external source)

---

## Go Stones

### Wikimedia Commons Go stones

- **Location:** `svg/go/wikimedia/go-black.svg`, `svg/go/wikimedia/go-white.svg`
- **Description:** Individual black and white Go stones with radial gradients
  on a wood-colored background square.
- **Author:** Manslay (Wikimedia Commons user)
- **Source URLs:**
  - <https://commons.wikimedia.org/wiki/File:Go_b.svg>
  - <https://commons.wikimedia.org/wiki/File:Go_w.svg>
- **License:** CC-BY-SA-3.0 (`CC-BY-SA-3.0`)
- **Modifications:** Renamed from `Go_b.svg`/`Go_w.svg` to `go-black.svg`/`go-white.svg`.

### Go stone placeholder (themed)

- **Location:** `svg/go/stone.svg`
- **Description:** Minimal Go stone SVG using CSS custom properties and radial
  gradient for theming. Not based on any external source.
- **Author:** Baize project
- **License:** Project license (generated -- no external source)

---

## Poker Chips / Tokens

### OpenGameArt poker chips

- **Location:** `svg/common/opengameart/poker-chips.svg`
- **Description:** Multi-color poker chip set (Inkscape SVG, ~195 KB).
  Contains multiple chip designs in a single file.
- **Author:** looneybits
- **Source:** <https://opengameart.org/content/poker-chips-0>
- **License:** CC0-1.0 (public domain dedication)
- **Modifications:** None. Downloaded as-is.

### Token placeholder (themed)

- **Location:** `svg/common/token.svg`
- **Description:** Generic circular token with dashed edge detail and radial
  gradient highlight. Uses CSS custom properties for theming. Not based on
  any external source.
- **Author:** Baize project
- **License:** Project license (generated -- no external source)

---

## Chess Pieces

See `svg/chess/ATTRIBUTION.md` for chess piece attribution (cburnett set,
GPLv2+ / BSD / GFDL).

---

## Other

### Tile placeholder

- **Location:** `svg/common/tile.svg`
- **Description:** Generic tile shape for tile-based games. Not based on any
  external source.
- **Author:** Baize project
- **License:** Project license (generated -- no external source)

---

## License Summary

| Asset | License (SPDX) | Attribution required |
|---|---|---|
| SVG-cards (playing cards) | `LGPL-2.1-or-later` | Yes (provide source + license) |
| Wikimedia dice faces | Public domain (PD-shape) | No |
| Wikimedia Go stones | `CC-BY-SA-3.0` | Yes |
| OpenGameArt poker chips | `CC0-1.0` | No |
| Chess pieces (cburnett) | `GPL-2.0-or-later` / `BSD-3-Clause` / `GFDL-1.2-or-later` | Yes (under GPL/GFDL) |
| All placeholder/themed SVGs | Project license | No (generated) |
