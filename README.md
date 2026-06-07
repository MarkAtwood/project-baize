# Baize

A declarative language for turn-based card and board games that separates
game topology, components, and constraints from the minimal authoritative
game server. Designed so that most operations run locally on the client,
reducing the server to a sequencer and hidden-state oracle.

**Baize** is the green felt cloth used to cover card tables, billiard tables,
and gaming surfaces. It's the surface everything plays out on — present in
every game, belonging to none of them.

## Why doesn't this exist already?

Declarative game languages exist (GDL, Ludii). Game servers exist (Board
Game Arena). Digital tabletops exist (Vassal, Tabletop Simulator). Component
catalogs exist (The Game Crafter). But none of them talk to each other, and
none of them answer the question: *what can the client compute locally, and
what requires a server round-trip?*

The game AI community builds languages for reasoning about games. The game
platform community builds servers for playing games. The tabletop community
builds shared whiteboards with no rules enforcement. Each solved their slice
and stopped.

Baize treats game definitions as a protocol design problem — capabilities,
trust boundaries, visibility models, optional extensions — rather than as a
game engine or an academic formalism. The schema doesn't run your game; it
tells clients and servers what each of them is responsible for.

The timing also matters. The three-tier architecture (declarative schema
for the common case, WASM modules for complex logic, thin server for hidden
state) only works now that WASM, WebSocket, and SVG are baseline web
platform features.

## Status

Design phase. No implementation yet.

## Key Documents

- `DESIGN.md` — Architecture, design rationale, prior art analysis
- `SCHEMA.md` — Schema language specification (draft)
- `EXAMPLES.md` — Example game definitions (chess, poker, Carcassonne)
- `COMPONENTS.md` — Standard component registry (cards, dice, tiles, tokens)
- `PRIOR-ART.md` — Survey of existing systems and what we stole from each
- `BINDING-SCENE.md` — Optional binding to JMAP Scene

## Implementations

Three reference implementations, same schema, same test vectors:

- `rust/` — Core engine, compiles to WASM, CLI tool
- `ts/` — Browser client, Node server
- `python/` — AI research, game analysis, Jupyter notebooks

## Relationship to Other Projects

Baize is a standalone specification. It does not depend on JMAP, JMAP Scene,
or any specific transport. Optional bindings can map game concepts to
specific platforms (JMAP Scene, WebSocket servers, peer-to-peer, etc.).

## License

Baize uses a three-tier license structure:

- **Specification and schema definitions** — [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  The game schema format, standard component registry, and all documentation.

- **Client-embeddable engine** (code that runs INSIDE a user agent) —
  [MIT](https://opensource.org/licenses/MIT). The core engine library
  (parser, legal move generator, state transitions) is MIT-licensed so it
  can be embedded in any application — proprietary game clients, mobile apps,
  commercial platforms — without license encumbrance.

- **Servers and standalone user agents** —
  [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html). The reference
  server, CLI tools, and standalone client applications. If you run a Baize
  server or distribute a standalone Baize client, you must share your
  modifications.

In practice:

| What you're building | License applies | You must share source? |
|---------------------|----------------|----------------------|
| Game schema / JSON definitions | CC-BY-SA | Attribution + share-alike |
| Engine embedded in your game client | MIT | No |
| Engine embedded in your mobile app | MIT | No |
| WASM module loaded in browser | MIT | No |
| Your game server using Baize | AGPL-3.0 | Yes |
| Your standalone desktop client | AGPL-3.0 | Yes |
| Your fork of the reference server | AGPL-3.0 | Yes |

**Your game definitions** (the JSON files describing your game) are yours
to license however you want. But consider: a client needs to fetch, parse,
and cache your game schema to play it. A server needs to read it to host it.
If your license prohibits that, nobody can play your game. We recommend
CC-BY-SA or something similarly permissive for game definitions.
