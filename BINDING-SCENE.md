# Baize — Optional Binding: JMAP Scene

This document describes how game schema concepts map to JMAP Scene objects
when the `urn:ietf:params:jmap:scene` capability is present. This binding
is optional — the game schema is transport-independent.

## Concept Mapping

| Game Schema | JMAP Scene | Notes |
|-------------|-----------|-------|
| Game instance | SceneRegion | One region per game table |
| Zone (board) | SceneRegion.bounds | Grid mapped to spatial coordinates |
| Zone (hand, deck) | SceneObject with children | Container objects |
| Component (piece, card) | SceneObject | Position = board coordinates |
| Component properties | SceneObject.customProperties | owner, state, facing |
| Player avatar | SceneAvatar | Seated at the table |
| Game state (turn, phase) | SceneRegion.customProperties | Shared game metadata |
| Player action | SceneInteractionEvent | Via JMAP Scene WSS |
| WASM module | SceneRegion.simulationUri (or new field) | Rules engine endpoint |

## SceneRegion as Game Table

```json
{
  "id": "region-chess-001",
  "name": "Chess: Alice vs Bob",
  "bounds": { "min": [0, 0, 0], "max": [8, 1, 8] },
  "viewHint": "2d-topdown",
  "accessPolicy": "invite",
  "customProperties": {
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

## SceneObject as Game Piece

```json
{
  "id": "obj-white-queen",
  "regionId": "region-chess-001",
  "name": "White Queen",
  "position": [3, 0, 0],
  "visualRef": "blob-chess-queen-white",
  "visualType": "model/gltf-binary",
  "customProperties": {
    "gameComponent": "queen",
    "owner": "white",
    "zone": "board",
    "cell": "d1",
    "hasMoved": true
  }
}
```

## SceneInteractionEvent as Game Action

```json
{
  "@type": "SceneInteractionEvent",
  "regionId": "region-chess-001",
  "objectId": "obj-white-queen",
  "userId": "user:alice@example.com",
  "action": "move",
  "data": {
    "from": "d1",
    "to": "d5"
  }
}
```

## Hidden Information Handling

JMAP Scene's `visible` property on SceneObject handles the display layer:

- Face-down cards: `visible: true` (object exists) but `visualRef` shows
  card back. The `customProperties.rank` and `customProperties.suit` are
  omitted from /get responses for non-owners (server filters).
- Opponent's grid in Naval Battle: objects exist but are not included in
  query results for the opponent (access control).

The game schema's visibility model drives Scene's per-user object filtering:

| Visibility tier | Scene behavior |
|-----------------|---------------|
| Public | Object included in all /get responses |
| Private(owner) | Object included only for owner; others see placeholder or nothing |
| Hidden | Object not included in any client response; server-only |

## Limitations of the Scene Binding

The Scene binding provides:
- Spatial rendering of game state
- Real-time event delivery (SceneInteractionEvent)
- Multi-user presence (SceneAvatar)
- Access control

The Scene binding does NOT provide:
- Rules enforcement (that's the game schema + optional WASM)
- Turn management (that's the game server interpreting the schema)
- Hidden state management (that's the game server)

The Scene layer is the **view**. The game schema is the **model**. The game
server (or WASM module) is the **controller**.

## Discovery

A client discovering a Scene region can detect it's a game table by checking
for `customProperties.gameSchema`. If present, the client:

1. Fetches/caches the game schema definition (by URI)
2. Optionally fetches the WASM module if specified
3. Uses the schema to render game-specific UI (legal move highlights,
   turn indicators, score displays)
4. Falls back to generic Scene rendering if the schema is unrecognized
