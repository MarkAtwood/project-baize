# Baize — Prior Art Survey

Comprehensive assessment of existing systems, what they got right, and why
none of them solve the specific problem we're addressing.

## The Problem Nobody Solved

A declarative game description designed around the client/server trust
boundary: what can the client validate locally, what requires a server
round-trip, and how does the schema communicate this split?

## Systems Evaluated

### GDL (Game Description Language)

- **Origin**: Stanford, 2005. Michael Genesereth. General Game Playing competition.
- **Language**: Datalog (Prolog-like logic programming)
- **Universality**: Proven universal for finite deterministic games (GDL-I), extended to stochastic and imperfect-information games (GDL-II, GDL-III).
- **Game coverage**: Any finite game can be expressed. Practically: ~150 games in the GGP repository.

**What they got right:**
- State as ground facts in a relational model
- `legal(Player, Move)` as a declarative predicate — the right abstraction
- `next(Fact)` for state transitions — pure functional
- GDL-II's `sees(Player, Percept)` — exactly the visibility model we need
- Formal semantics: every game has unambiguous interpretation

**Why it's not enough:**
- Designed for AI reasoning, not human authoring or client/server architectures
- Datalog syntax is hostile to game designers
- No concept of "compile to client-side validator"
- No networking model, no transport, no real-time
- Evaluation is expensive (model checking) — not suitable for real-time client validation
- No component ontology — everything is raw predicates

**References:**
- http://logic.stanford.edu/ggp/notes/gdl.html
- https://en.wikipedia.org/wiki/Game_Description_Language

---

### Ludii (Ludemic General Game System)

- **Origin**: Maastricht University, 2019-present. Cameron Browne et al.
- **Language**: Domain-specific ludeme language (S-expression-like)
- **Game coverage**: 1400+ games implemented. Primarily abstract strategy, but expanding to card games and dice games.
- **Universality**: Proven universal (2022 paper).

**What they got right:**
- Composable movement primitives (ludemes) — `(move Slide Orthogonal)` is vastly more readable than GDL predicates for the same concept
- Rich component library (board shapes, piece types, dice, cards)
- Game concepts as metadata (branching factor, draw rate, decisiveness)
- Equipment ontology is well-thought-out
- Actually playable — has a GUI, real games work

**Why it's not enough:**
- Monolithic evaluator — the Ludii runtime is a single-process Java app
- No client/server concept at all
- No visibility model for imperfect information (recent additions, still limited)
- Bespoke runtime — can't ship ludeme trees to arbitrary clients
- Language is complex (~2000 keywords) and hard to learn
- No WASM compilation target
- Academic focus: optimized for AI research, not production game platforms

**References:**
- https://ludii.games/
- https://arxiv.org/abs/2205.00451 (universality proof)

---

### Ludax (GPU-Accelerated DSL for Board Games)

- **Origin**: 2025. Graham Todd. Builds on Ludii concepts.
- **Language**: Ludii-inspired, compiles to JAX (GPU-accelerated Python)
- **Game coverage**: Narrow — 2-player, perfect-information, placement games only (Connect Four, Hex, Pente, etc.)

**What they got right:**
- Proves declarative game descriptions CAN compile to efficient execution
- Shows the path from "description" to "runnable validator"
- Clean separation of game definition from execution engine
- Web interface for interactive play (proof of concept)

**Why it's not enough:**
- GPU/RL-specific — designed for training AI agents at scale
- Extremely narrow game class (placement games only)
- No networking, no client/server, no visibility model
- JAX dependency — not portable to browsers or general clients
- No card games, no hidden information, no dice

**References:**
- https://arxiv.org/abs/2506.22609
- https://github.com/gdrtodd/ludax

---

### TAG (Tabletop Games Framework)

- **Origin**: Queen Mary University of London, 2020. GAIG Research group.
- **Language**: Java framework (imperative, not declarative)
- **Game coverage**: ~20 games implemented (Catan, Pandemic, Uno, Dominion, etc.)

**What they got right:**
- Best component taxonomy in the literature:
  - Containers: grid board, graph board, area, deck, hand, discard
  - Components: token, card, die, counter, tile
  - Properties: owner, visibility, position, value
- Turn order as a first-class concept (round-robin, alternating, reactive)
- Game analytics (branching factor, hidden info ratio, game length)
- JSON import for configuration data (card definitions, board layouts)
- Covers modern hobby games (deck-builders, area control), not just abstracts

**Why it's not enough:**
- Rules are imperative Java code (`ForwardModel` class per game)
- Not declarative — adding a game means writing Java
- No client/server split — single-process simulation
- No real-time, no networking
- "JSON import" is just data files (card text, board images), not rules

**References:**
- https://tabletopgames.ai/
- https://github.com/GAIGResearch/TabletopGames
- https://arxiv.org/pdf/2009.12065

---

### Partake

- **Origin**: Academic, recent. Formal language for board games.
- **Language**: Two intertwined languages — declarative relational + procedural episodes.

**What they got right:**
- Compositional: build complex games from simpler building blocks
- Zones with typed slots and capacity constraints
- Transitions as "move component from zone A to zone B if predicate"
- Clean separation of state (relational) from procedure (episode)
- Conciseness: game descriptions approach natural language length

**Why it's not enough:**
- Pure formalism — no implementation, no runtime
- No client/server concept
- No WASM, no compilation target
- Limited game coverage in examples
- Academic paper, not a usable system

**References:**
- https://cutfree.net/games/

---

### Regular Games (Automata-Based)

- **Origin**: 2024. Extends GDL concepts with automata theory.
- **Approach**: Games as finite automata over moves.

**What they got right:**
- Automata-based validation is computationally efficient (O(1) per transition)
- Universal for finite turn-based games including imperfect information
- Rational probability support for stochastic games
- Formal information set modeling

**Why it's not enough:**
- Purely theoretical — no implementation
- Automata get exponentially large for complex games
- No component ontology, no game design ergonomics
- No networking model

**References:**
- https://arxiv.org/pdf/2511.10593

---

### Vassal Engine

- **Origin**: 2003-present. Open source. Large community.
- **Approach**: Shared virtual tabletop — pieces you can move, no rules.

**What they got right:**
- Battle-tested component model (counters, cards, dice, hex maps, boards)
- Proven at scale: thousands of game modules
- Shows that designers WANT a generic game platform
- Module format is well-understood (ZIP with XML + images)
- Network play works (peer-to-peer state sync)

**Why it's not enough:**
- Zero rules enforcement — humans must enforce rules themselves
- State sync is "last writer wins" — no conflict resolution
- No validation, no cheating prevention
- Legacy codebase (Java Swing era)
- Module format is presentation-focused, not rules-focused

**References:**
- https://vassalengine.org/

---

### Tabletop Simulator (Steam)

- **Origin**: 2015. Berserk Games. Commercial.
- **Approach**: Physics sandbox — literally simulate a table with objects.

**What they got right:**
- Proves massive demand for generic tabletop platform
- Lua scripting for automation (closest to "programmable rules")
- Workshop ecosystem (thousands of community game mods)
- Network multiplayer works

**Why it's not enough:**
- Physics engine is the wrong abstraction for turn-based games
- Lua scripts are imperative, per-game, not declarative or reusable
- No rules enforcement beyond what scripts manually implement
- Proprietary, closed platform
- Performance limited by physics simulation overhead

---

### BoardGameArena

- **Origin**: 2010. Commercial web platform. 500+ games.
- **Approach**: PHP/JS per-game implementation, centralized server.

**What they got right:**
- Proves the model works commercially
- Server-authoritative (no cheating)
- Turn management, ELO ratings, matchmaking all handled
- Real-time and asynchronous play

**Why it's not enough:**
- Every game is a bespoke PHP implementation — no reusable language
- Adding a game requires a full development project
- Closed ecosystem (must be accepted by BGA team)
- No declarative layer — it's just a web app framework for games
- No client-side validation — every action round-trips to server

---

## Summary Matrix

| System | Declarative | Client/Server | Vis. Model | Components | Movement | Practical | WASM |
|--------|:-----------:|:-------------:|:----------:|:----------:|:--------:|:---------:|:----:|
| GDL | Yes | No | Yes (GDL-II) | No | No | No | No |
| Ludii | Yes | No | Partial | Yes | Yes | Somewhat | No |
| Ludax | Yes | No | No | Minimal | Minimal | No | No |
| TAG | No | No | No | Yes | No | Research | No |
| Partake | Yes | No | No | Partial | Partial | No | No |
| Regular Games | Yes | No | Yes | No | No | No | No |
| Vassal | No | P2P | No | Yes | No | Yes | No |
| TTS | No | Client/Server | No | Physics | No | Yes | No |
| BGA | No | Server-auth | Implicit | Bespoke | Bespoke | Yes | No |
| Screentop.gg | No | Client/Server | No | Yes | No | Yes | No |
| The Game Crafter | No | No | No | Yes (2967) | No | Mfg only | No |
| Tabletopia | No | Client/Server | No | Yes | No | Yes | No |
| **Ours** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Goal** | **Yes** |

## What We Steal

| Source | Concept | Adaptation |
|--------|---------|-----------|
| GDL | Relational state model | Use it, but with readable syntax (YAML/JSON, not Datalog) |
| GDL-II | `sees(player, percept)` visibility tiers | Public/Private/Hidden zone classification |
| Ludii | Movement primitive library | Steal vocabulary: slide, hop, step, leap, place, draw |
| Ludii | Ludeme composability | Direction + condition + effect composition |
| TAG | Component ontology | Token, card, die, counter, tile, board types |
| TAG | Turn order taxonomy | Alternating, round-robin, simultaneous, reactive |
| Partake | Zone model with capacity | Typed zones with constraints |
| Partake | Compositional game definition | Build complex from simple |
| Regular Games | Efficient automata validation | Compile movement rules to fast validators |
| Vassal | Proven component vocabulary | Hex grids, counters, card decks, maps |
| BGA | Server-authoritative model | But declarative, not bespoke PHP |
| BGA | Static material / dynamic state separation | Schema (cached) vs state (live) |
| BGA | Deck, Stock, Zone framework primitives | Our zone types map 1:1 |
| Ludax | Declarative → compiled execution | But target WASM, not GPU |
| Screentop.gg | Asset→Component→Variant→Object hierarchy | Template→Type→Instance→Placement |
| The Game Crafter | Physical form-factor catalog (2,967 pieces) | Optional `physical` metadata per component |
| Tabletopia | Real-world dimensions, 3D mesh support | Physical size for AR/manufacturing export |
