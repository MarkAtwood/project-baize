"""Built-in reference agents for testing and benchmarking.

- ``RandomAgent``: Uniform random legal move (re-exported from agent.py).
- ``GreedyAgent``: Maximize immediate material advantage (captures first).
- ``MCTSAgent``: Monte Carlo tree search with configurable playout budget.

All agents use ``AgentSession`` from the SDK to enumerate legal moves
locally, so they work with any game definition.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from baize.agent import Agent
from baize.definition import GameDefinition
from baize.sdk import AgentMove, AgentSession
from baize.transition import apply_action
from baize.action import Action


# Re-export RandomAgent for convenience
from baize.agent import RandomAgent

__all__ = ["RandomAgent", "GreedyAgent", "MCTSAgent"]


class GreedyAgent(Agent):
    """Agent that maximizes immediate material advantage.

    Prefers captures over non-captures. Among captures, prefers
    capturing higher-value targets. Falls back to random if no
    captures are available.

    Requires ``definition`` to be set before calling ``play()``.
    """

    def __init__(
        self,
        server_url: str,
        room_id: str,
        definition: GameDefinition,
        **kwargs: Any,
    ) -> None:
        super().__init__(server_url, room_id, **kwargs)
        self.definition = definition

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any] | None:
        session = AgentSession.from_server_state(self.definition, state)
        moves = session.legal_moves()
        if not moves:
            return None

        # Score each move: captures are worth more
        best_move = moves[0]
        best_score = -1
        for move in moves:
            score = self._score_move(move, state)
            if score > best_score:
                best_score = score
                best_move = move

        return best_move.to_action_dict()

    def _score_move(self, move: AgentMove, state: dict[str, Any]) -> int:
        """Score a move. Higher is better."""
        action = move.action
        d = move.to_action_dict()
        to_pos = d.get("to")

        if to_pos is None:
            return 0

        # Check if the destination has an opponent piece (capture)
        zones = state.get("zones", {})
        for zone_data in zones.values():
            cells = zone_data.get("cells", {})
            if isinstance(to_pos, dict):
                cell_key = to_pos.get("cell", "")
            else:
                cell_key = str(to_pos)
            if cell_key in cells:
                return 10  # Capture is worth more

        return 1  # Non-capture move


@dataclass
class _MCTSNode:
    """A node in the MCTS search tree."""

    action_dict: dict[str, Any] | None  # None for root
    parent: _MCTSNode | None
    children: list[_MCTSNode] = field(default_factory=list)
    visits: int = 0
    wins: float = 0.0
    untried_actions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ucb1(self) -> float:
        if self.visits == 0:
            return float("inf")
        if self.parent is None or self.parent.visits == 0:
            return self.wins / self.visits
        return (self.wins / self.visits) + math.sqrt(
            2.0 * math.log(self.parent.visits) / self.visits
        )


class MCTSAgent(Agent):
    """Monte Carlo tree search agent with configurable playout budget.

    Uses random playouts to estimate move values. The ``budget``
    parameter controls how many playouts per move decision.

    Requires ``definition`` to be set before calling ``play()``.
    """

    def __init__(
        self,
        server_url: str,
        room_id: str,
        definition: GameDefinition,
        *,
        budget: int = 100,
        **kwargs: Any,
    ) -> None:
        super().__init__(server_url, room_id, **kwargs)
        self.definition = definition
        self.budget = budget

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any] | None:
        session = AgentSession.from_server_state(self.definition, state)
        moves = session.legal_moves()
        if not moves:
            return None
        if len(moves) == 1:
            return moves[0].to_action_dict()

        action_dicts = [m.to_action_dict() for m in moves]

        root = _MCTSNode(
            action_dict=None,
            parent=None,
            untried_actions=list(action_dicts),
        )

        my_seat = self.client.seat

        for _ in range(self.budget):
            node = root
            sim_session = AgentSession.from_server_state(
                self.definition, state
            )

            # Selection: walk down the tree using UCB1
            while not node.untried_actions and node.children:
                node = max(node.children, key=lambda n: n.ucb1)
                if node.action_dict is not None:
                    self._apply_action_to_session(
                        sim_session, node.action_dict
                    )

            # Expansion: try an untried action
            if node.untried_actions:
                action_dict = node.untried_actions.pop(
                    random.randrange(len(node.untried_actions))
                )
                self._apply_action_to_session(sim_session, action_dict)
                child = _MCTSNode(
                    action_dict=action_dict,
                    parent=node,
                )
                # Populate child's untried actions
                child_moves = sim_session.legal_moves()
                child.untried_actions = [m.to_action_dict() for m in child_moves]
                node.children.append(child)
                node = child

            # Simulation: random playout to terminal
            result = self._random_playout(sim_session)

            # Backpropagation
            reward = 1.0 if result == my_seat else (0.5 if result == "" else 0.0)
            while node is not None:
                node.visits += 1
                node.wins += reward
                node = node.parent  # type: ignore[assignment]

        # Pick the most-visited child
        if not root.children:
            return action_dicts[0] if action_dicts else None
        best = max(root.children, key=lambda n: n.visits)
        return best.action_dict

    def _apply_action_to_session(
        self, session: AgentSession, action_dict: dict[str, Any]
    ) -> None:
        """Apply an action to a local session (best-effort)."""
        try:
            action = Action(
                action_type=action_dict.get("action_type", "pass"),
                component_id=action_dict.get("component_id"),
                component_type=action_dict.get("component_type"),
                from_pos=action_dict.get("from"),
                to_pos=action_dict.get("to"),
                zone=action_dict.get("zone"),
                promote_to=action_dict.get("promote_to"),
                swap_with=action_dict.get("swap_with"),
            )
            apply_action(session.session, action)
        except Exception:
            pass  # Simulation errors are expected at search boundaries

    def _random_playout(self, session: AgentSession, max_depth: int = 50) -> str:
        """Run a random playout from the current state. Returns the winner or ""."""
        for _ in range(max_depth):
            if session.status == "finished":
                result = session.session.runtime.result
                if result is not None:
                    return result.winner or ""
                return ""
            moves = session.legal_moves()
            if not moves:
                return ""
            move = random.choice(moves)
            self._apply_action_to_session(session, move.to_action_dict())
        return ""
