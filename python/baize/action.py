"""Dataclasses matching move-action.schema.json.

Covers player actions (client -> server) and server responses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Union


# ---------------------------------------------------------------------------
# Enums as Literals
# ---------------------------------------------------------------------------

ClientMessageTypeLiteral = Literal[
    "submit_move", "request_random", "acknowledge_state",
]

ServerMessageTypeLiteral = Literal[
    "move_confirmed", "move_rejected", "random_result", "reveal", "state_sync",
]

ActionTypeLiteral = Literal[
    "move_piece", "place", "draw", "play_card", "discard",
    "roll_dice", "flip", "promote", "swap", "remove",
    "pass", "resign", "offer_draw", "accept_draw", "decline_draw",
    "fold", "check", "call", "raise", "all_in",
    "place_ship", "fire",
    "castle", "en_passant",
    "declare_action",
    "commit", "reveal",
    "claim_action",
    "custom",
]

AuthorityLiteral = Literal["client_verifiable", "server_only"]

OrientationLiteral = Literal["horizontal", "vertical"]

CastleSideLiteral = Literal["kingside", "queenside"]

RandomTypeLiteral = Literal["roll", "draw", "shuffle"]

PreviousVisibilityLiteral = Literal["hidden", "private"]
NewVisibilityLiteral = Literal["public", "private"]


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

Position = Union[str, dict[str, Any]]


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

@dataclass
class Action:
    action_type: ActionTypeLiteral
    authority: AuthorityLiteral | None = None
    component_id: str | None = None
    component_type: str | None = None
    from_pos: Position | None = None
    to_pos: Position | None = None
    zone: str | None = None
    count: int | None = None
    promote_to: str | None = None
    orientation: OrientationLiteral | None = None
    rotation: int | None = None
    amount: int | float | None = None
    side: CastleSideLiteral | None = None
    dice_count: int | None = None
    dice_type: str | None = None
    swap_with: str | None = None
    declaration: str | None = None
    commitment: str | None = None
    custom_data: dict[str, Any] | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Action:
        if "action_type" not in d:
            raise ValueError("action dict missing required 'action_type' key")
        return Action(
            action_type=d["action_type"],
            authority=d.get("authority"),
            component_id=d.get("component_id"),
            component_type=d.get("component_type"),
            from_pos=d.get("from"),
            to_pos=d.get("to"),
            zone=d.get("zone"),
            count=d.get("count"),
            promote_to=d.get("promote_to"),
            orientation=d.get("orientation"),
            rotation=d.get("rotation"),
            amount=d.get("amount"),
            side=d.get("side"),
            dice_count=d.get("dice_count"),
            dice_type=d.get("dice_type"),
            swap_with=d.get("swap_with"),
            declaration=d.get("declaration"),
            commitment=d.get("commitment"),
            custom_data=d.get("custom_data"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"action_type": self.action_type}
        if self.authority is not None:
            out["authority"] = self.authority
        if self.component_id is not None:
            out["component_id"] = self.component_id
        if self.component_type is not None:
            out["component_type"] = self.component_type
        if self.from_pos is not None:
            out["from"] = self.from_pos
        if self.to_pos is not None:
            out["to"] = self.to_pos
        if self.zone is not None:
            out["zone"] = self.zone
        if self.count is not None:
            out["count"] = self.count
        if self.promote_to is not None:
            out["promote_to"] = self.promote_to
        if self.orientation is not None:
            out["orientation"] = self.orientation
        if self.rotation is not None:
            out["rotation"] = self.rotation
        if self.amount is not None:
            out["amount"] = self.amount
        if self.side is not None:
            out["side"] = self.side
        if self.dice_count is not None:
            out["dice_count"] = self.dice_count
        if self.dice_type is not None:
            out["dice_type"] = self.dice_type
        if self.swap_with is not None:
            out["swap_with"] = self.swap_with
        if self.declaration is not None:
            out["declaration"] = self.declaration
        if self.commitment is not None:
            out["commitment"] = self.commitment
        if self.custom_data is not None:
            out["custom_data"] = self.custom_data
        return out


# ---------------------------------------------------------------------------
# RandomRequest
# ---------------------------------------------------------------------------

@dataclass
class RandomRequest:
    random_type: RandomTypeLiteral
    dice_type: str | None = None
    dice_count: int | None = None
    draw_from: str | None = None
    draw_count: int | None = None
    shuffle_zone: str | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> RandomRequest:
        if "random_type" not in d:
            raise ValueError("random request dict missing required 'random_type' key")
        return RandomRequest(
            random_type=d["random_type"],
            dice_type=d.get("dice_type"),
            dice_count=d.get("dice_count"),
            draw_from=d.get("draw_from"),
            draw_count=d.get("draw_count"),
            shuffle_zone=d.get("shuffle_zone"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"random_type": self.random_type}
        if self.dice_type is not None:
            out["dice_type"] = self.dice_type
        if self.dice_count is not None:
            out["dice_count"] = self.dice_count
        if self.draw_from is not None:
            out["draw_from"] = self.draw_from
        if self.draw_count is not None:
            out["draw_count"] = self.draw_count
        if self.shuffle_zone is not None:
            out["shuffle_zone"] = self.shuffle_zone
        return out


# ---------------------------------------------------------------------------
# Fact  (for reveal messages)
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    fact_type: str
    component_id: str | None = None
    zone: str | None = None
    position: Position | None = None
    properties: dict[str, Any] | None = None
    previous_visibility: PreviousVisibilityLiteral | None = None
    new_visibility: NewVisibilityLiteral | None = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Fact:
        if "fact_type" not in d:
            raise ValueError("fact dict missing required 'fact_type' key")
        return Fact(
            fact_type=d["fact_type"],
            component_id=d.get("component_id"),
            zone=d.get("zone"),
            position=d.get("position"),
            properties=d.get("properties"),
            previous_visibility=d.get("previous_visibility"),
            new_visibility=d.get("new_visibility"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"fact_type": self.fact_type}
        if self.component_id is not None:
            out["component_id"] = self.component_id
        if self.zone is not None:
            out["zone"] = self.zone
        if self.position is not None:
            out["position"] = self.position
        if self.properties is not None:
            out["properties"] = self.properties
        if self.previous_visibility is not None:
            out["previous_visibility"] = self.previous_visibility
        if self.new_visibility is not None:
            out["new_visibility"] = self.new_visibility
        return out


# ---------------------------------------------------------------------------
# ClientMessage
# ---------------------------------------------------------------------------

@dataclass
class ClientMessage:
    message_type: ClientMessageTypeLiteral
    game_id: str
    player: str
    sequence: int | None = None
    action: Action | None = None
    random_request: RandomRequest | None = None
    state_hash: str | None = None

    @classmethod
    def from_json(cls, json_str: str) -> ClientMessage:
        """Parse a ClientMessage from a JSON string."""
        from baize.error import ParseError

        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ParseError(str(exc)) from exc
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ClientMessage:
        from baize.error import ParseError

        try:
            for required in ("message_type", "game_id", "player"):
                if required not in d:
                    raise KeyError(f"client message missing required key: {required!r}")
            action_raw = d.get("action")
            action = Action.from_dict(action_raw) if action_raw is not None else None
            rr_raw = d.get("random_request")
            random_request = RandomRequest.from_dict(rr_raw) if rr_raw is not None else None
            return cls(
                message_type=d["message_type"],
                game_id=d["game_id"],
                player=d["player"],
                sequence=d.get("sequence"),
                action=action,
                random_request=random_request,
                state_hash=d.get("state_hash"),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(str(exc)) from exc

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "message_type": self.message_type,
            "game_id": self.game_id,
            "player": self.player,
        }
        if self.sequence is not None:
            out["sequence"] = self.sequence
        if self.action is not None:
            out["action"] = self.action.to_dict()
        if self.random_request is not None:
            out["random_request"] = self.random_request.to_dict()
        if self.state_hash is not None:
            out["state_hash"] = self.state_hash
        return out


# ---------------------------------------------------------------------------
# ServerMessage
# ---------------------------------------------------------------------------

@dataclass
class ServerMessage:
    message_type: ServerMessageTypeLiteral
    game_id: str
    sequence: int | None = None
    action: Action | None = None
    result_state: dict[str, Any] | None = None
    reason: str | None = None
    random_type: str | None = None
    random_value: int | str | list[Any] | dict[str, Any] | None = None
    reveal_to: str | None = None
    facts: list[Fact] = field(default_factory=list)
    full_state: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, json_str: str) -> ServerMessage:
        """Parse a ServerMessage from a JSON string."""
        from baize.error import ParseError

        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ParseError(str(exc)) from exc
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> ServerMessage:
        from baize.error import ParseError

        try:
            for required in ("message_type", "game_id"):
                if required not in d:
                    raise KeyError(f"server message missing required key: {required!r}")
            action_raw = d.get("action")
            action = Action.from_dict(action_raw) if action_raw is not None else None
            facts = [Fact.from_dict(f) for f in d.get("facts", [])]
            return cls(
                message_type=d["message_type"],
                game_id=d["game_id"],
                sequence=d.get("sequence"),
                action=action,
                result_state=d.get("result_state"),
                reason=d.get("reason"),
                random_type=d.get("random_type"),
                random_value=d.get("random_value"),
                reveal_to=d.get("reveal_to"),
                facts=facts,
                full_state=d.get("full_state"),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ParseError(str(exc)) from exc

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "message_type": self.message_type,
            "game_id": self.game_id,
        }
        if self.sequence is not None:
            out["sequence"] = self.sequence
        if self.action is not None:
            out["action"] = self.action.to_dict()
        if self.result_state is not None:
            out["result_state"] = self.result_state
        if self.reason is not None:
            out["reason"] = self.reason
        if self.random_type is not None:
            out["random_type"] = self.random_type
        if self.random_value is not None:
            out["random_value"] = self.random_value
        if self.reveal_to is not None:
            out["reveal_to"] = self.reveal_to
        if self.facts:
            out["facts"] = [f.to_dict() for f in self.facts]
        if self.full_state is not None:
            out["full_state"] = self.full_state
        return out
