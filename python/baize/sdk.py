"""Agent SDK — ergonomic API for writing game-playing agents.

Bridges the headless client (network) with the game engine (logic) so
agents can enumerate legal moves locally before choosing one.

Usage::

    from baize.sdk import AgentSession

    class SmartAgent(Agent):
        def choose_action(self, state: dict) -> dict | None:
            session = AgentSession.from_server_state(self.definition, state)
            moves = session.legal_moves()
            if not moves:
                return None
            # Pick the best move using your strategy
            return moves[0].to_action_dict()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baize.action import Action
from baize.definition import GameDefinition
from baize.moves import LegalMove, legal_moves
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
    RuntimePlayer,
    RuntimeState,
)


@dataclass
class AgentSession:
    """Local game session for agent-side move enumeration.

    Reconstructs a minimal GameSession from the server's state_sync
    payload so agents can call ``legal_moves()`` without the server.
    """

    session: GameSession

    @staticmethod
    def from_server_state(
        definition: GameDefinition,
        server_state: dict[str, Any],
    ) -> AgentSession:
        """Build a local session from a game definition and server state.

        Args:
            definition: The game definition (load once, reuse).
            server_state: The ``full_state`` dict from a ``state_sync`` message.
        """
        session = GameSession(definition)
        session.runtime.status = server_state.get("status", "in_progress")

        # Restore turn index from player name
        turn = server_state.get("turn", "")
        player_names = list(session.runtime.players.keys())
        for i, name in enumerate(player_names):
            if name == turn:
                session.runtime.turn_index = i
                break

        session.runtime.sequence = server_state.get("sequence", 0)
        session.runtime.move_count = server_state.get("move_count", 0)
        session.runtime.halfmove_clock = server_state.get("halfmove_clock", 0)

        # Restore grid zones from server state
        zones = server_state.get("zones", {})
        for zone_name, zone_data in zones.items():
            zone = session.runtime.zones.get(zone_name)
            if zone is None or not isinstance(zone, GridZone):
                continue
            cells = zone_data.get("cells", {})
            for coord, cell_data in cells.items():
                col, row = _parse_coord(coord)
                comp = _extract_component(cell_data)
                if comp is not None:
                    cid = session.runtime.components.insert(comp)
                    zone.grid_set(col, row, cid)

        return AgentSession(session=session)

    def legal_moves(self) -> list[AgentMove]:
        """Enumerate all legal moves for the current player."""
        raw_moves = legal_moves(self.session)
        return [AgentMove(m) for m in raw_moves]

    @property
    def current_player(self) -> str | None:
        """The player whose turn it is."""
        return self.session.current_player()

    @property
    def status(self) -> str:
        """Game status: setup, in_progress, or finished."""
        return str(self.session.runtime.status)


@dataclass
class AgentMove:
    """A legal move with a convenience method to convert to action dict."""

    _move: LegalMove

    @property
    def action(self) -> Action:
        return self._move.action

    def to_action_dict(self) -> dict[str, Any]:
        """Convert to the dict format expected by BaizeClient.submit_move()."""
        a = self._move.action
        d: dict[str, Any] = {"action_type": a.action_type}
        if a.component_id is not None:
            d["component_id"] = a.component_id
        if a.component_type is not None:
            d["component_type"] = a.component_type
        if a.from_pos is not None:
            d["from"] = a.from_pos
        if a.to_pos is not None:
            d["to"] = a.to_pos
        if a.zone is not None:
            d["zone"] = a.zone
        if a.promote_to is not None:
            d["promote_to"] = a.promote_to
        if a.swap_with is not None:
            d["swap_with"] = a.swap_with
        return d


def _parse_coord(coord: str) -> tuple[int, int]:
    parts = coord.split(",")
    return int(parts[0]), int(parts[1])


def _extract_component(cell_data: Any) -> ComponentData | None:
    """Extract a ComponentData from a cell's wire format."""
    if isinstance(cell_data, dict):
        # Single component: {"id": "...", "component_type": "...", "owner": "..."}
        comp_id = cell_data.get("id", "")
        comp_type = cell_data.get("component_type", "")
        owner = cell_data.get("owner")
        if comp_type:
            return ComponentData(
                id=ComponentId(0),
                string_id=comp_id,
                component_type=comp_type,
                owner=owner,
            )
    return None
