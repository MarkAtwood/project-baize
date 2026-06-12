"""Dataclasses matching game-definition.schema.json.

Mirrors the Rust structs in engine/src/definition.rs as closely as possible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Union

# ---------------------------------------------------------------------------
# JSON Schema validation (lazy-loaded)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, Any] | None = None


def _load_schema() -> dict[str, Any]:
    """Load the game-definition JSON Schema, caching after first read."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    schema_path = Path(__file__).resolve().parent.parent.parent / "schema" / "game-definition.schema.json"
    if not schema_path.exists():
        return {}  # Schema file not found — skip validation gracefully
    _SCHEMA_CACHE = json.loads(schema_path.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def _validate_against_schema(data: Any) -> None:
    """Validate a parsed dict against the game-definition JSON Schema.

    Raises ParseError with all validation errors if validation fails.
    Silently succeeds if the jsonschema package is not installed or
    the schema file is not found.
    """
    from baize.error import ParseError

    schema = _load_schema()
    if not schema:
        return

    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        return  # jsonschema not installed — skip validation

    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))

    if errors:
        messages = []
        for err in errors[:10]:  # Cap at 10 errors to avoid flooding
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            messages.append(f"  {path}: {err.message}")
        raise ParseError(
            f"Game definition failed schema validation ({len(errors)} error(s)):\n"
            + "\n".join(messages)
        )


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

VisibilityTier = Literal["public", "hidden"]


@dataclass
class PrivateVisibility:
    """Visible only to the named role (typically 'owner')."""

    private: str


Visibility = Union[VisibilityTier, PrivateVisibility]


def _visibility_from_raw(raw: object) -> Visibility:
    if isinstance(raw, str):
        if raw not in ("public", "hidden"):
            raise ValueError(f"invalid visibility tier: {raw!r}")
        return raw  # type: ignore[return-value]
    if isinstance(raw, dict):
        if "private" not in raw:
            raise ValueError(
                f"visibility dict must contain 'private' key, got {raw!r}"
            )
        return PrivateVisibility(private=raw["private"])
    raise ValueError(f"invalid visibility value: {raw!r}")


def _visibility_to_raw(v: Visibility) -> object:
    if isinstance(v, str):
        return v
    return {"private": v.private}


# ---------------------------------------------------------------------------
# Enums as Literals
# ---------------------------------------------------------------------------

ZoneTypeName = Literal[
    "grid", "hex_grid", "graph", "ordered_stack",
    "set", "queue", "single_slot", "track", "counter",
]

PrimitiveTypeName = Literal[
    "step", "slide", "hop", "leap", "place", "draw",
    "move_to", "swap", "remove", "promote", "flip", "castle",
]

DirectionNameLiteral = Literal[
    "orthogonal", "diagonal", "adjacent", "forward",
    "forward_diagonal", "backward", "backward_diagonal",
]

Direction = Union[DirectionNameLiteral, list[DirectionNameLiteral], str]

CastleSideLiteral = Literal["kingside", "queenside"]

AdjacencyLiteral = Literal["orthogonal_4", "orthogonal_8", "hex_6"]

InformationTypeLiteral = Literal["perfect", "imperfect"]

TurnOrderTypeLiteral = Literal["alternating", "round_robin", "simultaneous", "reactive"]

EndResultLiteral = Literal["win", "loss", "draw"]

# Capacity: either an int or the string "unlimited"
Capacity = Union[int, Literal["unlimited"]]

# Dimensions: either [width, height] or a single int
Dimensions = Union[list[int], int]

# ComponentCount: either an int or "unlimited"
ComponentCount = Union[int, Literal["unlimited"]]


# ---------------------------------------------------------------------------
# GridLabels
# ---------------------------------------------------------------------------

@dataclass
class GridLabels:
    files: list[str] | None = None
    ranks: list[str | int] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> GridLabels:
        return GridLabels(
            files=d.get("files"),
            ranks=d.get("ranks"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.files is not None:
            out["files"] = self.files
        if self.ranks is not None:
            out["ranks"] = self.ranks
        return out


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

@dataclass
class Promotion:
    trigger: str
    choices: list[str]

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Promotion:
        if "trigger" not in d:
            raise ValueError("promotion dict missing required 'trigger' key")
        if "choices" not in d:
            raise ValueError("promotion dict missing required 'choices' key")
        return Promotion(trigger=d["trigger"], choices=d["choices"])

    def to_dict(self) -> dict[str, Any]:
        return {"trigger": self.trigger, "choices": self.choices}


# ---------------------------------------------------------------------------
# MovementPrimitive
# ---------------------------------------------------------------------------

@dataclass
class MovementPrimitive:
    primitive: PrimitiveTypeName
    direction: Direction | None = None
    distance: int | None = None
    dx: int | None = None
    dy: int | None = None
    target_zone: str | None = None
    condition: str | None = None
    repeat: Any | None = None
    after: list[str] = field(default_factory=list)
    side: CastleSideLiteral | None = None
    over: int | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> MovementPrimitive:
        if "primitive" not in d:
            raise ValueError("movement dict missing required 'primitive' key")
        return MovementPrimitive(
            primitive=d["primitive"],
            direction=d.get("direction"),
            distance=d.get("distance"),
            dx=d.get("dx"),
            dy=d.get("dy"),
            target_zone=d.get("target_zone"),
            condition=d.get("condition"),
            repeat=d.get("repeat"),
            after=d.get("after", []),
            side=d.get("side"),
            over=d.get("over"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"primitive": self.primitive}
        if self.direction is not None:
            out["direction"] = self.direction
        if self.distance is not None:
            out["distance"] = self.distance
        if self.dx is not None:
            out["dx"] = self.dx
        if self.dy is not None:
            out["dy"] = self.dy
        if self.target_zone is not None:
            out["target_zone"] = self.target_zone
        if self.condition is not None:
            out["condition"] = self.condition
        if self.repeat is not None:
            out["repeat"] = self.repeat
        if self.after:
            out["after"] = self.after
        if self.side is not None:
            out["side"] = self.side
        if self.over is not None:
            out["over"] = self.over
        return out


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------

@dataclass
class Zone:
    zone_type: ZoneTypeName
    visibility: Visibility
    per_player: bool | None = None
    capacity: Capacity | None = None
    dimensions: Dimensions | None = None
    intersections: bool | None = None
    labels: GridLabels | None = None
    coloring: str | None = None
    adjacency: AdjacencyLiteral | None = None
    valid_cells: list[list[int]] | None = None
    star_points: list[list[int]] | None = None
    draw_visibility: Visibility | None = None
    dynamic: bool | None = None
    length: int | None = None
    lanes: str | None = None
    points: int | None = None
    connectivity: int | None = None
    edge_ownership: Any | None = None
    cell_type: str | None = None
    direction: str | None = None
    nodes: list[str] | None = None
    edges: list[list[str]] | None = None
    node_properties: dict[str, dict[str, str | int | bool]] | None = None
    note: str | None = None
    cell_properties: dict[str, dict[str, str | int | bool]] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Zone:
        if "zone_type" not in d:
            raise ValueError("zone dict missing required 'zone_type' key")
        if "visibility" not in d:
            raise ValueError("zone dict missing required 'visibility' key")
        labels_raw = d.get("labels")
        labels = GridLabels.from_dict(labels_raw) if labels_raw is not None else None
        draw_vis_raw = d.get("draw_visibility")
        draw_vis = _visibility_from_raw(draw_vis_raw) if draw_vis_raw is not None else None
        return Zone(
            zone_type=d["zone_type"],
            visibility=_visibility_from_raw(d["visibility"]),
            per_player=d.get("per_player"),
            capacity=d.get("capacity"),
            dimensions=d.get("dimensions"),
            intersections=d.get("intersections"),
            labels=labels,
            coloring=d.get("coloring"),
            adjacency=d.get("adjacency"),
            valid_cells=d.get("valid_cells"),
            star_points=d.get("star_points"),
            draw_visibility=draw_vis,
            dynamic=d.get("dynamic"),
            length=d.get("length"),
            lanes=d.get("lanes"),
            points=d.get("points"),
            connectivity=d.get("connectivity"),
            edge_ownership=d.get("edge_ownership"),
            cell_type=d.get("cell_type"),
            direction=d.get("direction"),
            nodes=d.get("nodes"),
            edges=d.get("edges"),
            node_properties=d.get("node_properties"),
            note=d.get("note"),
            cell_properties=d.get("cell_properties"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "zone_type": self.zone_type,
            "visibility": _visibility_to_raw(self.visibility),
        }
        if self.per_player is not None:
            out["per_player"] = self.per_player
        if self.capacity is not None:
            out["capacity"] = self.capacity
        if self.dimensions is not None:
            out["dimensions"] = self.dimensions
        if self.intersections is not None:
            out["intersections"] = self.intersections
        if self.labels is not None:
            out["labels"] = self.labels.to_dict()
        if self.coloring is not None:
            out["coloring"] = self.coloring
        if self.adjacency is not None:
            out["adjacency"] = self.adjacency
        if self.valid_cells is not None:
            out["valid_cells"] = self.valid_cells
        if self.star_points is not None:
            out["star_points"] = self.star_points
        if self.draw_visibility is not None:
            out["draw_visibility"] = _visibility_to_raw(self.draw_visibility)
        if self.dynamic is not None:
            out["dynamic"] = self.dynamic
        if self.length is not None:
            out["length"] = self.length
        if self.lanes is not None:
            out["lanes"] = self.lanes
        if self.points is not None:
            out["points"] = self.points
        if self.connectivity is not None:
            out["connectivity"] = self.connectivity
        if self.edge_ownership is not None:
            out["edge_ownership"] = self.edge_ownership
        if self.cell_type is not None:
            out["cell_type"] = self.cell_type
        if self.direction is not None:
            out["direction"] = self.direction
        if self.nodes is not None:
            out["nodes"] = self.nodes
        if self.edges is not None:
            out["edges"] = self.edges
        if self.node_properties is not None:
            out["node_properties"] = self.node_properties
        if self.note is not None:
            out["note"] = self.note
        if self.cell_properties is not None:
            out["cell_properties"] = self.cell_properties
        return out


# ---------------------------------------------------------------------------
# Owner  (Rust: enum Owner { PerPlayer, Named(String) })
# ---------------------------------------------------------------------------

Owner = str  # "per_player", "neutral", "shared", or a player name


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

@dataclass
class Component:
    registry: str | None = None
    extends: str | None = None
    owner: Owner | None = None
    count: ComponentCount | None = None
    movement: list[MovementPrimitive] = field(default_factory=list)
    properties: dict[str, Any] | None = None
    facing: str | None = None
    promotion: Promotion | None = None
    constraints: list[str] = field(default_factory=list)
    special: str | None = None
    types: dict[str, Any] | None = None
    one_of_each: bool | None = None
    span: int | None = None
    supply: Any | None = None
    adds: Any | None = None
    note: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Component:
        movement_raw = d.get("movement", [])
        movement = [MovementPrimitive.from_dict(m) for m in movement_raw]
        promo_raw = d.get("promotion")
        promotion = Promotion.from_dict(promo_raw) if promo_raw is not None else None
        return Component(
            registry=d.get("registry"),
            extends=d.get("extends"),
            owner=d.get("owner"),
            count=d.get("count"),
            movement=movement,
            properties=d.get("properties"),
            facing=d.get("facing"),
            promotion=promotion,
            constraints=d.get("constraints", []),
            special=d.get("special"),
            types=d.get("types"),
            one_of_each=d.get("one_of_each"),
            span=d.get("span"),
            supply=d.get("supply"),
            adds=d.get("adds"),
            note=d.get("note"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.registry is not None:
            out["registry"] = self.registry
        if self.extends is not None:
            out["extends"] = self.extends
        if self.owner is not None:
            out["owner"] = self.owner
        if self.count is not None:
            out["count"] = self.count
        if self.movement:
            out["movement"] = [m.to_dict() for m in self.movement]
        if self.properties is not None:
            out["properties"] = self.properties
        if self.facing is not None:
            out["facing"] = self.facing
        if self.promotion is not None:
            out["promotion"] = self.promotion.to_dict()
        if self.constraints:
            out["constraints"] = self.constraints
        if self.special is not None:
            out["special"] = self.special
        if self.types is not None:
            out["types"] = self.types
        if self.one_of_each is not None:
            out["one_of_each"] = self.one_of_each
        if self.span is not None:
            out["span"] = self.span
        if self.supply is not None:
            out["supply"] = self.supply
        if self.adds is not None:
            out["adds"] = self.adds
        if self.note is not None:
            out["note"] = self.note
        return out


# ---------------------------------------------------------------------------
# TurnOrder
# ---------------------------------------------------------------------------

# ActionsPerTurn: either an int or a list of structured action slots
ActionsPerTurn = Union[int, list[dict[str, Any]]]


@dataclass
class TurnOrder:
    type: TurnOrderTypeLiteral
    players: list[str] | None = None
    actions_per_turn: ActionsPerTurn | None = None
    mandatory: bool | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TurnOrder:
        if "type" not in d:
            raise ValueError("turn_order dict missing required 'type' key")
        return TurnOrder(
            type=d["type"],
            players=d.get("players"),
            actions_per_turn=d.get("actions_per_turn"),
            mandatory=d.get("mandatory"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.players is not None:
            out["players"] = self.players
        if self.actions_per_turn is not None:
            out["actions_per_turn"] = self.actions_per_turn
        if self.mandatory is not None:
            out["mandatory"] = self.mandatory
        return out


# ---------------------------------------------------------------------------
# ServerAction  (Rust: enum { Single(String), Multiple(Vec<String>) })
# ---------------------------------------------------------------------------

ServerAction = Union[str, list[str]]


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------

@dataclass
class Phase:
    name: str
    type: str | None = None
    simultaneous: bool | None = None
    server_action: ServerAction | None = None
    action: str | None = None
    actions_per_turn: int | None = None
    starts_with: str | None = None
    trigger: str | None = None
    choices: list[str] = field(default_factory=list)
    ends_when: str | None = None
    then: str | None = None
    resolve: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Phase:
        return Phase(
            name=d["name"],
            type=d.get("type"),
            simultaneous=d.get("simultaneous"),
            server_action=d.get("server_action"),
            action=d.get("action"),
            actions_per_turn=d.get("actions_per_turn"),
            starts_with=d.get("starts_with"),
            trigger=d.get("trigger"),
            choices=d.get("choices", []),
            ends_when=d.get("ends_when"),
            then=d.get("then"),
            resolve=d.get("resolve"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name}
        if self.type is not None:
            out["type"] = self.type
        if self.simultaneous is not None:
            out["simultaneous"] = self.simultaneous
        if self.server_action is not None:
            out["server_action"] = self.server_action
        if self.action is not None:
            out["action"] = self.action
        if self.actions_per_turn is not None:
            out["actions_per_turn"] = self.actions_per_turn
        if self.starts_with is not None:
            out["starts_with"] = self.starts_with
        if self.trigger is not None:
            out["trigger"] = self.trigger
        if self.choices:
            out["choices"] = self.choices
        if self.ends_when is not None:
            out["ends_when"] = self.ends_when
        if self.then is not None:
            out["then"] = self.then
        if self.resolve is not None:
            out["resolve"] = self.resolve
        return out


# ---------------------------------------------------------------------------
# Rule
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    definition: str | None = None
    action: str | None = None
    constraint: str | None = None
    constraints: list[str] = field(default_factory=list)
    trigger: str | None = None
    window: str | None = None
    effect: str | None = None
    requires: list[str] = field(default_factory=list)
    server_resolves: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Rule:
        return Rule(
            definition=d.get("definition"),
            action=d.get("action"),
            constraint=d.get("constraint"),
            constraints=d.get("constraints", []),
            trigger=d.get("trigger"),
            window=d.get("window"),
            effect=d.get("effect"),
            requires=d.get("requires", []),
            server_resolves=d.get("server_resolves"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.definition is not None:
            out["definition"] = self.definition
        if self.action is not None:
            out["action"] = self.action
        if self.constraint is not None:
            out["constraint"] = self.constraint
        if self.constraints:
            out["constraints"] = self.constraints
        if self.trigger is not None:
            out["trigger"] = self.trigger
        if self.window is not None:
            out["window"] = self.window
        if self.effect is not None:
            out["effect"] = self.effect
        if self.requires:
            out["requires"] = self.requires
        if self.server_resolves is not None:
            out["server_resolves"] = self.server_resolves
        return out


# ---------------------------------------------------------------------------
# EndCondition
# ---------------------------------------------------------------------------

@dataclass
class EndCondition:
    result: EndResultLiteral
    condition: str
    player: str | None = None
    name: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> EndCondition:
        if "result" not in d:
            raise ValueError("end_condition dict missing required 'result' key")
        if "condition" not in d:
            raise ValueError("end_condition dict missing required 'condition' key")
        return EndCondition(
            result=d["result"],
            condition=d["condition"],
            player=d.get("player"),
            name=d.get("name"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "result": self.result,
            "condition": self.condition,
        }
        if self.player is not None:
            out["player"] = self.player
        if self.name is not None:
            out["name"] = self.name
        return out


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

@dataclass
class Authority:
    server_only: list[str]
    client_verifiable: list[str]
    wasm_required: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Authority:
        if "server_only" not in d:
            raise ValueError("authority dict missing required 'server_only' key")
        if "client_verifiable" not in d:
            raise ValueError("authority dict missing required 'client_verifiable' key")
        return Authority(
            server_only=d["server_only"],
            client_verifiable=d["client_verifiable"],
            wasm_required=d.get("wasm_required", []),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "server_only": self.server_only,
            "client_verifiable": self.client_verifiable,
        }
        if self.wasm_required:
            out["wasm_required"] = self.wasm_required
        return out


# ---------------------------------------------------------------------------
# BettingRound
# ---------------------------------------------------------------------------

@dataclass
class BettingRound:
    actions: list[str] = field(default_factory=list)
    ends_when: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> BettingRound:
        return BettingRound(
            actions=d.get("actions", []),
            ends_when=d.get("ends_when"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.actions:
            out["actions"] = self.actions
        if self.ends_when is not None:
            out["ends_when"] = self.ends_when
        return out


# ---------------------------------------------------------------------------
# Players  (Rust: enum { Named(Vec<String>), Range { min, max } })
# ---------------------------------------------------------------------------

@dataclass
class PlayerRange:
    min: int
    max: int


Players = Union[list[str], PlayerRange]


def _players_from_raw(raw: object) -> Players:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if "min" not in raw or "max" not in raw:
            raise ValueError(
                f"player range dict must contain 'min' and 'max' keys, got {raw!r}"
            )
        p_min = raw["min"]
        p_max = raw["max"]
        if not isinstance(p_min, int) or not isinstance(p_max, int):
            raise ValueError(
                f"player range min/max must be integers, got min={p_min!r}, max={p_max!r}"
            )
        if p_min < 1 or p_max < 1:
            raise ValueError(
                f"player range values must be at least 1, got min={p_min}, max={p_max}"
            )
        if p_min > p_max:
            raise ValueError(
                f"player range min ({p_min}) must not exceed max ({p_max})"
            )
        return PlayerRange(min=p_min, max=p_max)
    raise ValueError(f"invalid players value: {raw!r}")


def _players_to_raw(p: Players) -> object:
    if isinstance(p, list):
        return p
    return {"min": p.min, "max": p.max}


# ---------------------------------------------------------------------------
# GameMetadata
# ---------------------------------------------------------------------------

@dataclass
class GameMetadata:
    name: str
    players: Players
    information: InformationTypeLiteral | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> GameMetadata:
        if "name" not in d:
            raise ValueError("game metadata dict missing required 'name' key")
        if "players" not in d:
            raise ValueError("game metadata dict missing required 'players' key")
        return GameMetadata(
            name=d["name"],
            players=_players_from_raw(d["players"]),
            information=d.get("information"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "players": _players_to_raw(self.players),
        }
        if self.information is not None:
            out["information"] = self.information
        return out


# ---------------------------------------------------------------------------
# GameDefinition  (top-level)
# ---------------------------------------------------------------------------

@dataclass
class GameDefinition:
    game: GameMetadata
    zones: dict[str, Zone]
    components: dict[str, Component]
    turn_order: TurnOrder
    end_conditions: list[EndCondition]
    authority: Authority
    phases: list[Phase] = field(default_factory=list)
    rules: dict[str, Rule] = field(default_factory=dict)
    library: dict[str, str | dict] = field(default_factory=dict)
    wasm_module: str | None = None
    hand_rankings: list[str] = field(default_factory=list)
    betting_round: BettingRound | None = None
    notation: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, json_str: str, *, validate_schema: bool = True) -> GameDefinition:
        """Parse a GameDefinition from a JSON string.

        Args:
            json_str: JSON string to parse.
            validate_schema: If True (default), validate against the JSON Schema
                before parsing into dataclasses.
        """
        from baize.error import ParseError

        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ParseError(str(exc)) from exc

        if validate_schema:
            _validate_against_schema(raw)

        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> GameDefinition:
        from baize.error import ParseError

        try:
            for required in ("game", "zones", "components", "turn_order",
                             "end_conditions", "authority"):
                if required not in d:
                    raise KeyError(f"game definition missing required key: {required!r}")
            zones = {k: Zone.from_dict(v) for k, v in d["zones"].items()}
            components = {k: Component.from_dict(v) for k, v in d["components"].items()}
            phases = [Phase.from_dict(p) for p in d.get("phases", [])]
            rules = {k: Rule.from_dict(v) for k, v in d.get("rules", {}).items()}
            end_conds = [EndCondition.from_dict(e) for e in d["end_conditions"]]
            br_raw = d.get("betting_round")
            betting_round = BettingRound.from_dict(br_raw) if br_raw is not None else None

            defn = cls(
                game=GameMetadata.from_dict(d["game"]),
                zones=zones,
                components=components,
                turn_order=TurnOrder.from_dict(d["turn_order"]),
                end_conditions=end_conds,
                authority=Authority.from_dict(d["authority"]),
                phases=phases,
                rules=rules,
                library=d.get("library", {}),
                wasm_module=d.get("wasm_module"),
                hand_rankings=d.get("hand_rankings", []),
                betting_round=betting_round,
                notation=d.get("notation"),
            )
            defn.validate()
            return defn
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(str(exc)) from exc

    def validate(self) -> None:
        """Semantic validation: resource limits to prevent computational DoS."""
        from baize.error import ValidationError

        # Player count limits (max 100)
        if isinstance(self.game.players, list):
            if len(self.game.players) > 100:
                raise ValidationError(
                    f"too many players: {len(self.game.players)} exceeds maximum (100)"
                )
        elif isinstance(self.game.players, PlayerRange):
            if self.game.players.max > 100:
                raise ValidationError(
                    f"max players {self.game.players.max} exceeds maximum (100)"
                )

        # Grid dimension limits (max 1000 per axis)
        for name, zone in self.zones.items():
            if zone.zone_type in ("grid", "hex_grid") and zone.dimensions is not None:
                if isinstance(zone.dimensions, list):
                    dims = zone.dimensions
                elif isinstance(zone.dimensions, int):
                    dims = [zone.dimensions, zone.dimensions]
                else:
                    dims = []
                for i, d in enumerate(dims):
                    if isinstance(d, (int, float)) and d > 1000:
                        raise ValidationError(
                            f"zone {name!r} dimension[{i}] = {d} exceeds maximum (1000)"
                        )

        # Total component count (max 10,000)
        if isinstance(self.game.players, list):
            player_count = max(len(self.game.players), 1)
        elif isinstance(self.game.players, PlayerRange):
            player_count = max(self.game.players.max, 1)
        else:
            player_count = 1
        total = 0
        for comp in self.components.values():
            if comp.count is None:
                base = 1
            elif comp.count == "unlimited":
                base = 1
            elif isinstance(comp.count, int) and comp.count > 0:
                base = comp.count
            else:
                base = 1
            multiplier = player_count if comp.owner == "per_player" else 1
            total += base * multiplier
        if total > 10_000:
            raise ValidationError(
                f"total component count {total} exceeds maximum (10000)"
            )

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "game": self.game.to_dict(),
            "zones": {k: v.to_dict() for k, v in self.zones.items()},
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "turn_order": self.turn_order.to_dict(),
            "end_conditions": [e.to_dict() for e in self.end_conditions],
            "authority": self.authority.to_dict(),
        }
        if self.phases:
            out["phases"] = [p.to_dict() for p in self.phases]
        if self.rules:
            out["rules"] = {k: v.to_dict() for k, v in self.rules.items()}
        if self.wasm_module is not None:
            out["wasm_module"] = self.wasm_module
        if self.hand_rankings:
            out["hand_rankings"] = self.hand_rankings
        if self.betting_round is not None:
            out["betting_round"] = self.betting_round.to_dict()
        if self.notation is not None:
            out["notation"] = self.notation
        return out
