"""Dataclasses matching component-registry.schema.json.

Mirrors the Rust structs in engine/src/registry.rs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Union

from baize.definition import Visibility, _visibility_from_raw, _visibility_to_raw


# ---------------------------------------------------------------------------
# Enums as Literals
# ---------------------------------------------------------------------------

ComponentTypeName = Literal[
    "stone", "disc", "pawn", "token", "die", "card_deck",
    "tile", "piece_set", "counter", "card", "tile_set",
]

ShapeName = str  # Too many shapes to enumerate; kept as str


# ---------------------------------------------------------------------------
# Variant
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    shape: str | None = None
    fill: str | None = None
    stroke: str | None = None
    glyph: str | None = None
    glyph_color: str | None = None
    label: str | None = None
    size: str | None = None
    color: str | None = None
    pattern: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Variant:
        return Variant(
            shape=d.get("shape"),
            fill=d.get("fill"),
            stroke=d.get("stroke"),
            glyph=d.get("glyph"),
            glyph_color=d.get("glyph_color"),
            label=d.get("label"),
            size=d.get("size"),
            color=d.get("color"),
            pattern=d.get("pattern"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for attr in (
            "shape", "fill", "stroke", "glyph", "glyph_color",
            "label", "size", "color", "pattern",
        ):
            val = getattr(self, attr)
            if val is not None:
                out[attr] = val
        return out


# Variants: either a dict of named variants or a list
Variants = Union[dict[str, Variant], list[Variant]]


def _variants_from_raw(raw: object) -> Variants:
    if isinstance(raw, dict):
        return {k: Variant.from_dict(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return [Variant.from_dict(v) for v in raw]
    raise ValueError(f"invalid variants value: {raw!r}")


def _variants_to_raw(v: Variants) -> object:
    if isinstance(v, dict):
        return {k: val.to_dict() for k, val in v.items()}
    return [val.to_dict() for val in v]


# ---------------------------------------------------------------------------
# PieceDefinition
# ---------------------------------------------------------------------------

@dataclass
class PromotedForm:
    glyph: str | None = None
    moves_as: str | None = None
    gains: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PromotedForm:
        return PromotedForm(
            glyph=d.get("glyph"),
            moves_as=d.get("moves_as"),
            gains=d.get("gains"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.glyph is not None:
            out["glyph"] = self.glyph
        if self.moves_as is not None:
            out["moves_as"] = self.moves_as
        if self.gains is not None:
            out["gains"] = self.gains
        return out


@dataclass
class PieceDefinition:
    glyph: str | None = None
    promoted: PromotedForm | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PieceDefinition:
        promo_raw = d.get("promoted")
        promoted: PromotedForm | None = None
        if promo_raw is not None:
            promoted = PromotedForm.from_dict(promo_raw)
        return PieceDefinition(glyph=d.get("glyph"), promoted=promoted)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.glyph is not None:
            out["glyph"] = self.glyph
        if self.promoted is not None:
            out["promoted"] = self.promoted.to_dict()
        return out


# ---------------------------------------------------------------------------
# TileDistribution
# ---------------------------------------------------------------------------

@dataclass
class TileDistribution:
    count: int
    points: int
    wildcard: bool | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TileDistribution:
        return TileDistribution(
            count=d["count"],
            points=d["points"],
            wildcard=d.get("wildcard"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"count": self.count, "points": self.points}
        if self.wildcard is not None:
            out["wildcard"] = self.wildcard
        return out


# ---------------------------------------------------------------------------
# PhysicalForm
# ---------------------------------------------------------------------------

@dataclass
class PhysicalForm:
    size_mm: list[float] | None = None
    thickness_mm: float | None = None
    material: str | None = None
    shape: str | None = None
    weight_g: float | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> PhysicalForm:
        return PhysicalForm(
            size_mm=d.get("size_mm"),
            thickness_mm=d.get("thickness_mm"),
            material=d.get("material"),
            shape=d.get("shape"),
            weight_g=d.get("weight_g"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.size_mm is not None:
            out["size_mm"] = self.size_mm
        if self.thickness_mm is not None:
            out["thickness_mm"] = self.thickness_mm
        if self.material is not None:
            out["material"] = self.material
        if self.shape is not None:
            out["shape"] = self.shape
        if self.weight_g is not None:
            out["weight_g"] = self.weight_g
        return out


# ---------------------------------------------------------------------------
# RegistryEntry  (top-level)
# ---------------------------------------------------------------------------

@dataclass
class RegistryEntry:
    id: str
    component_type: ComponentTypeName
    name: str | None = None
    extends: str | None = None
    subset_of: str | None = None
    shape: str | None = None
    parameterized_by: str | None = None
    available_colors: list[str] = field(default_factory=list)
    supply: Any | None = None
    count: int | None = None
    total: int | None = None
    facing: str | None = None
    flip: bool | None = None
    variants: Variants | None = None
    properties: list[str] = field(default_factory=list)
    sides: dict[str, Any] | None = None
    suits: list[str] = field(default_factory=list)
    suit_symbols: list[str] = field(default_factory=list)
    suit_colors: dict[str, str] | None = None
    ranks: list[str | int] = field(default_factory=list)
    rank_values: dict[str, Any] | None = None
    extra: list[Any] = field(default_factory=list)
    composition: Any | None = None
    faces: int | None = None
    values: list[str | int] = field(default_factory=list)
    display: str | None = None
    glyphs: Any | None = None
    pieces: dict[str, PieceDefinition] | None = None
    movement: dict[str, str] | None = None
    owner_indicated_by: str | None = None
    special_rules: Any | None = None
    board_constraints: Any | None = None
    distribution: dict[str, TileDistribution] | None = None
    denominations: dict[str, Any] | None = None
    physical_form: str | None = None
    physical: PhysicalForm | None = None
    visibility: Visibility | None = None
    note: str | None = None

    @classmethod
    def from_json(cls, json_str: str) -> RegistryEntry:
        """Parse a RegistryEntry from a JSON string."""
        from baize.error import ParseError

        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ParseError(str(exc)) from exc
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> RegistryEntry:
        from baize.error import ParseError

        try:
            variants_raw = d.get("variants")
            variants = _variants_from_raw(variants_raw) if variants_raw is not None else None

            pieces_raw = d.get("pieces")
            pieces = (
                {k: PieceDefinition.from_dict(v) for k, v in pieces_raw.items()}
                if pieces_raw is not None
                else None
            )

            dist_raw = d.get("distribution")
            distribution = (
                {k: TileDistribution.from_dict(v) for k, v in dist_raw.items()}
                if dist_raw is not None
                else None
            )

            phys_raw = d.get("physical")
            physical = PhysicalForm.from_dict(phys_raw) if phys_raw is not None else None

            vis_raw = d.get("visibility")
            visibility = _visibility_from_raw(vis_raw) if vis_raw is not None else None

            return cls(
                id=d["id"],
                component_type=d["component_type"],
                name=d.get("name"),
                extends=d.get("extends"),
                subset_of=d.get("subset_of"),
                shape=d.get("shape"),
                parameterized_by=d.get("parameterized_by"),
                available_colors=d.get("available_colors", []),
                supply=d.get("supply"),
                count=d.get("count"),
                total=d.get("total"),
                facing=d.get("facing"),
                flip=d.get("flip"),
                variants=variants,
                properties=d.get("properties", []),
                sides=d.get("sides"),
                suits=d.get("suits", []),
                suit_symbols=d.get("suit_symbols", []),
                suit_colors=d.get("suit_colors"),
                ranks=d.get("ranks", []),
                rank_values=d.get("rank_values"),
                extra=d.get("extra", []),
                composition=d.get("composition"),
                faces=d.get("faces"),
                values=d.get("values", []),
                display=d.get("display"),
                glyphs=d.get("glyphs"),
                pieces=pieces,
                movement=d.get("movement"),
                owner_indicated_by=d.get("owner_indicated_by"),
                special_rules=d.get("special_rules"),
                board_constraints=d.get("board_constraints"),
                distribution=distribution,
                denominations=d.get("denominations"),
                physical_form=d.get("physical_form"),
                physical=physical,
                visibility=visibility,
                note=d.get("note"),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(str(exc)) from exc

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "component_type": self.component_type,
        }
        if self.name is not None:
            out["name"] = self.name
        if self.extends is not None:
            out["extends"] = self.extends
        if self.subset_of is not None:
            out["subset_of"] = self.subset_of
        if self.shape is not None:
            out["shape"] = self.shape
        if self.parameterized_by is not None:
            out["parameterized_by"] = self.parameterized_by
        if self.available_colors:
            out["available_colors"] = self.available_colors
        if self.supply is not None:
            out["supply"] = self.supply
        if self.count is not None:
            out["count"] = self.count
        if self.total is not None:
            out["total"] = self.total
        if self.facing is not None:
            out["facing"] = self.facing
        if self.flip is not None:
            out["flip"] = self.flip
        if self.variants is not None:
            out["variants"] = _variants_to_raw(self.variants)
        if self.properties:
            out["properties"] = self.properties
        if self.sides is not None:
            out["sides"] = self.sides
        if self.suits:
            out["suits"] = self.suits
        if self.suit_symbols:
            out["suit_symbols"] = self.suit_symbols
        if self.suit_colors is not None:
            out["suit_colors"] = self.suit_colors
        if self.ranks:
            out["ranks"] = self.ranks
        if self.rank_values is not None:
            out["rank_values"] = self.rank_values
        if self.extra:
            out["extra"] = self.extra
        if self.composition is not None:
            out["composition"] = self.composition
        if self.faces is not None:
            out["faces"] = self.faces
        if self.values:
            out["values"] = self.values
        if self.display is not None:
            out["display"] = self.display
        if self.glyphs is not None:
            out["glyphs"] = self.glyphs
        if self.pieces is not None:
            out["pieces"] = {k: v.to_dict() for k, v in self.pieces.items()}
        if self.movement is not None:
            out["movement"] = self.movement
        if self.owner_indicated_by is not None:
            out["owner_indicated_by"] = self.owner_indicated_by
        if self.special_rules is not None:
            out["special_rules"] = self.special_rules
        if self.board_constraints is not None:
            out["board_constraints"] = self.board_constraints
        if self.distribution is not None:
            out["distribution"] = {k: v.to_dict() for k, v in self.distribution.items()}
        if self.denominations is not None:
            out["denominations"] = self.denominations
        if self.physical_form is not None:
            out["physical_form"] = self.physical_form
        if self.physical is not None:
            out["physical"] = self.physical.to_dict()
        if self.visibility is not None:
            out["visibility"] = _visibility_to_raw(self.visibility)
        if self.note is not None:
            out["note"] = self.note
        return out
