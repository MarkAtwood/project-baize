# Baize — Optional Binding: JMAP Scene

This document describes how game schema concepts map to JMAP Scene objects
when the `urn:ietf:params:jmap:scene` capability is present. This binding
is optional — the game schema is transport-independent.

It tracks these documents (jmap-chat-spec repository, revision `3445973`);
section names and line numbers below refer to that revision:

- `draft-atwood-jmap-scene-00` — the Scene data model and methods ("Scene").
- `draft-atwood-jmap-scene-wss-00` — ephemeral Scene events over the JMAP
  WebSocket ("Scene WSS").
- `jmap-scene-board-games-guide.md`, `jmap-scene-2d-guide.md`,
  `jmap-scene-simulation-guide.md` — non-normative implementer guides.

Where a guide and a draft differ, the draft wins.

## Concept Mapping

| Game Schema | JMAP Scene | Notes |
|-------------|-----------|-------|
| Game instance | SceneRegion | One region per game table, created by the game server's account |
| Zone (board) | SceneRegion.bounds | One cell = one meter; cell (col, row) at `[col, 0, row]` |
| Zone (hand, deck) | Container SceneObject | Members name it in `parentId` and are positioned relative to it |
| Component (piece, card) | SceneObject | `interactable: true`, `physicsMode: "none"` |
| Component properties | SceneObject.worldState | owner (seat), state, facing; public values only |
| Player | SceneAvatar | Created by the player's own client; seat lives in region `worldState` |
| Game state (turn, phase) | SceneRegion.worldState | Shared game metadata |
| Game server endpoint | SceneRegion.simulationUri | The Baize WebSocket server for this table |
| Player action | Baize `submit_move` over `simulationUri`, or `SceneObject/interact` | See "Player Actions" |
| WASM module | SceneRegion.worldState (`wasmModule`) | Scene has no module field; see "WASM Module" |

### Units and coordinates

Scene positions are right-handed, Y-up, in meters, region-local (Scene
§Coordinate System, lines 244–271). Following the 2D guide's tile mapping
(`jmap-scene-2d-guide.md` §3, lines 220–245), a Baize grid cell
`"col,row"` maps to `position: [col, 0, row]`, and an 8×8 board is a region
with `bounds` `{ "min": [0, 0, 0], "max": [8, 1, 8] }`. A container's
members are positioned relative to the container, and the container must be
in the same region (Scene lines 608–609, 1659). Hex and graph zones need a
deployment-chosen layout; their coordinates are not defined here.

### Ids and userIds

`id` on every Scene record is server-set (a ULID; Scene lines 394–395,
602–603, 689–690). The examples below show `id` values as the server would
return them; a client never chooses them. Ids use the RFC 8620 §1.2
charset (`A-Za-z0-9-_`).

A "userId" is the authenticated identity string from the transport layer,
not a JMAP Id (Scene line 232), so values such as
`"user:alice@example.com"` are valid in `ownerId`, `userId`,
`invitedUserIds`, and in Baize's own `worldState.players`.

## SceneRegion as Game Table

The game server creates the region (`SceneRegion/set` create; only `name`
and `bounds` are required, Scene lines 1130–1136), which makes it the
region owner (`ownerId`). Only the region owner (or an administrator) may
update the region (Scene line 1240), so the game server must own the region
to keep `worldState` current.

For `accessPolicy: "invite"`, the players' userIds must be listed in
`invitedUserIds`; with the default `[]` only the owner and administrators
can enter (Scene lines 526–530, §Region Access lines 2680–2695). Spectators
need either an invitation or a `"public"` region.

```json
{
  "id": "01J5REG0000000000000000001",
  "name": "Chess: Alice vs Bob",
  "bounds": { "min": [0, 0, 0], "max": [8, 1, 8] },
  "viewHint": "2d-topdown",
  "simulationUri": "wss://games.example.com/rooms/chess-001",
  "accessPolicy": "invite",
  "invitedUserIds": ["user:alice@example.com", "user:bob@example.com"],
  "worldState": {
    "gameSchema": "urn:game:chess:standard",
    "gameSchemaVersion": "1.0",
    "wasmModule": null,
    "turn": "white",
    "phase": "main",
    "moveCount": 12,
    "players": {
      "white": "user:alice@example.com",
      "black": "user:bob@example.com"
    }
  }
}
```

Fields omitted above take their defaults or are server-set (`ownerId`,
`accountId`, `activeAvatarCount`, `createdAt`, `updatedAt`).
`invitedUserIds` is returned only to callers who may update the region;
everyone else sees `[]` (Scene line 530), so clients read seats from
`worldState.players`, not from `invitedUserIds`.

## SceneObject as Game Piece

`regionId` and `position` are required on create (Scene lines 1627–1631).
`interactable` defaults to `false` and `physicsMode` to `"static"` (Scene
lines 632–637); a piece the player acts on through Scene needs
`interactable: true`, because `SceneObject/interact` rejects interactions
with non-interactable objects (Scene line 2137). The board-games guide uses
`physicsMode: "none"` for pieces (guide lines 84–91).

```json
{
  "id": "01J5OBJ0000000000000000004",
  "regionId": "01J5REG0000000000000000001",
  "name": "White Queen",
  "position": [3, 0, 0],
  "visualRef": "blob-chess-queen-white",
  "visualType": "model/gltf-binary",
  "physicsMode": "none",
  "interactable": true,
  "worldState": {
    "gameComponent": "queen",
    "owner": "white",
    "zone": "board",
    "cell": "3,0",
    "hasMoved": true
  }
}
```

`visualType` must be in the account's `supportedVisualTypes` (Scene lines
291–292, 1659); `"model/gltf-binary"` always is, and 2D deployments often
add `"image/svg+xml"` (guide lines 103–109).

The seat that controls a piece goes in `worldState.owner`. Scene's
`ownerId` is server-set to the creating user, here the game server, and
cannot be reassigned (Scene line 641; guide lines 167–171), so it cannot
express which player owns a piece or who holds a card.

## Player Actions

Players act in one of two ways.

**Recommended: the Baize protocol over `simulationUri`.** The client
connects to the region's `simulationUri` (after explicit user action —
the URI is untrusted, Scene lines 2715–2719) and sends Baize
`submit_move` messages. The game server validates the move, then writes
the result to Scene with `SceneObject/set` and `SceneRegion/set`. Scene
clients that are not Baize-aware see the board change through ordinary
`StateChange` pushes. This matches the simulation guide's model for
board games: no tick loop, state changes only on player actions
(`jmap-scene-simulation-guide.md` line 704).

**Scene-native: `SceneObject/interact`.** A client may instead submit the
Baize action as a Scene interaction, carrying the Baize action object in
`data`. `SceneObject/interact` (Scene §SceneObject/interact, lines
2100–2195) returns `accepted` or a SetError per interaction; a
`SceneInteractionEvent` frame sent on the WebSocket (Scene WSS lines
396–428) gets no response at all. Either way the caller must have an active
SceneAvatar in the region and the target object must be `interactable`
(Scene line 2137). Actions without a natural target object (pass, resign,
offer draw) need an interactable target, such as an invisible
(`visible: false`, `interactable: true`) game-state object.

```json
["SceneObject/interact", {
  "accountId": "acct-game-server",
  "interactions": {
    "i0": {
      "regionId": "01J5REG0000000000000000001",
      "objectId": "01J5OBJ0000000000000000004",
      "action": "io.github.markatwood.baize.action",
      "data": {
        "action_type": "move_piece",
        "from": { "zone": "board", "cell": "3,0" },
        "to": { "zone": "board", "cell": "3,4" }
      }
    }
  }
}, "c0"]
```

Scene defines only the short actions `"click"`, `"grab"`, `"release"`, and
`"activate"`; deployment-specific actions SHOULD use reverse-domain
notation (Scene WSS lines 302–308), so Baize uses one action name,
`io.github.markatwood.baize.action`, for every Baize action, with the
action type inside `data`.

Each accepted interaction is delivered to the region's WebSocket
subscribers as a `SceneInteractionEvent`. The server fills in `accountId`
(the hosting account, required on every event, Scene WSS lines 181–190)
and `userId` (from the authenticated user; a `userId` in a client frame is
ignored, Scene WSS lines 411–413):

```json
{
  "@type": "SceneInteractionEvent",
  "accountId": "acct-game-server",
  "regionId": "01J5REG0000000000000000001",
  "objectId": "01J5OBJ0000000000000000004",
  "userId": "user:alice@example.com",
  "action": "io.github.markatwood.baize.action",
  "data": {
    "action_type": "move_piece",
    "from": { "zone": "board", "cell": "3,0" },
    "to": { "zone": "board", "cell": "3,4" }
  }
}
```

To receive these events, the game server must:

1. Find `urn:ietf:params:jmap:scene:websocket` in the Session capabilities
   (Scene WSS lines 133–153); that capability, not the account-level Scene
   capability, is what makes `SceneStreamEnable` available.
2. Have an active SceneAvatar in the region, because a stream only carries
   events for regions where the subscriber is present (Scene WSS lines
   532–549).
3. Send `SceneStreamEnable`, optionally with
   `"eventTypes": ["SceneInteractionEvent"]` (Scene WSS lines 432–465).

An interaction event says only that a user asked; the game server still
validates the action against the game state and the user's seat
(`worldState.players`). The `data` payload is visible to every subscriber
of the region (Scene WSS lines 1214–1219), so it must not carry hidden
information.

## Players, Avatars, and Leaving

Each player's client enters by creating its own SceneAvatar
(`SceneAvatar/set` create with `regionId`, Scene lines 2213–2224); the
server sets `userId` from the caller, so the game server cannot create
avatars on players' behalf (Scene lines 2476–2481). A user has at most one
SceneAvatar per region. A second create, even after leaving, fails with
`alreadyExists` and `existingId` (Scene line 2317); the client re-enters by
updating that record's `leftAt` to `null` (Scene lines 2448–2460).

A player leaves by setting `leftAt`; the server stores its own time and
echoes the stored value in `updated` (Scene lines 2385–2446). The region
owner (the game server) can eject a player the same way, patching only
`leftAt` (Scene §Avatar Permissions, lines 2707–2711). Changing
`invitedUserIds` does not remove avatars already present (Scene line 2695).

Leaving the Scene region does not resign the game seat; seat state belongs
to the game server.

## WASM Module

Scene has no field for a rules module. `simulationUri` is a live
"real-time simulation layer endpoint" (Scene lines 415–416), so it names
the game server, not a module to download. Baize carries the module
reference in region `worldState`, which Scene leaves to the deployment
(Scene lines 538–539):

```json
"wasmModule": {
  "uri": "https://games.example.com/modules/chess-ext-1.0.wasm",
  "sha256": "<lowercase hex>"
}
```

`null` (as in the region example) means the game needs no Tier 2 module.
The module is untrusted code: a client verifies the digest before use and
runs it only in the Tier 2 sandbox.

## Hidden Information Handling

The Scene draft does not filter `worldState`: it is opaque and the server
"stores and relays this object without interpretation" (Scene lines
538–539, 650–651). The only filtering the draft defines is per object: a
server MAY leave objects out of `/get` and `/query` for a user (Scene
§Visibility Contract, lines 2662–2676). The board-games and 2D guides
describe servers that swap `visualRef` and redact `worldState` per
recipient (board-games guide lines 161–172; 2D guide line 744). A Scene
server is not required to do this, so Baize does not depend on it:

- **Never write a hidden value into Scene.** Face-down cards and private
  hands are SceneObjects whose `worldState` holds only public facts (zone,
  owner seat, face-down) and whose `visualRef` shows the card back. Rank
  and suit stay in the game server's vault; each player learns their own
  cards through the Baize protocol, which already filters per seat.
- **`visible` is not access control.** It tells clients whether to render
  the object (Scene line 638); every user who can read the object still
  receives all its properties.
- **Leaving an object out is visible in other ways.** `/changes` reports
  changes for the whole account (Scene line 2674), so a hidden object's id
  can still show up; ids and names must not encode hidden facts.
- When a card is revealed, the game server writes the face values with
  `SceneObject/set`.

| Visibility tier | Scene behavior |
|-----------------|---------------|
| Public | Object and all its properties written to Scene |
| Private(owner) | Object written with public properties only; owner gets the face via the Baize protocol |
| Hidden | Not written to Scene; server-only |

## Limitations of the Scene Binding

The Scene binding provides:
- Spatial rendering of game state
- Real-time event delivery (`SceneInteractionEvent`, Scene WSS)
- Multi-user presence (SceneAvatar)
- Access control (`accessPolicy`, `invitedUserIds`)

The Scene binding does NOT provide:
- Rules enforcement (that's the game schema + optional WASM)
- Turn management (that's the game server interpreting the schema)
- Hidden state management (that's the game server)

The Scene layer is the **view**. The game schema is the **model**. The game
server (or WASM module) is the **controller**.

## Discovery

A client discovering a Scene region can detect it's a game table by checking
for `worldState.gameSchema`. If present, the client:

1. Fetches/caches the game schema definition (by URI)
2. Optionally fetches the WASM module named by `worldState.wasmModule`
   and checks its digest
3. Uses the schema to render game-specific UI (legal move highlights,
   turn indicators, score displays)
4. Connects to `simulationUri` only when the user chooses to play
5. Falls back to generic Scene rendering if the schema is unrecognized
