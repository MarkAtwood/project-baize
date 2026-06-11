"""Tests for built-in reference agents."""

import json
from typing import Any

from baize.agents import GreedyAgent, MCTSAgent, RandomAgent
from baize.definition import GameDefinition
from baize.sdk import AgentSession


def _chess_definition() -> GameDefinition:
    raw = {
        "game": {"name": "Chess", "players": ["white", "black"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [8, 8], "visibility": "public"},
        },
        "components": {
            "king": {
                "owner": "per_player", "count": 1,
                "movement": [{"primitive": "step", "direction": "adjacent"}],
            },
            "pawn": {
                "owner": "per_player", "count": 8,
                "movement": [
                    {"primitive": "step", "direction": "forward", "distance": 1, "condition": "empty"},
                ],
            },
        },
        "turn_order": {
            "type": "alternating", "players": ["white", "black"],
            "actions_per_turn": 1, "mandatory": True,
        },
        "end_conditions": [
            {"result": "draw", "condition": "all_cells_occupied"},
        ],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    return GameDefinition.from_json(json.dumps(raw))


def _state_with_king_and_enemy() -> dict[str, Any]:
    """White king at 4,4 with black pawn at 5,5 (capturable)."""
    return {
        "status": "in_progress",
        "turn": "white",
        "sequence": 0,
        "zones": {
            "board": {
                "cells": {
                    "4,4": {"id": "king-w-0", "component_type": "king", "owner": "white"},
                    "5,5": {"id": "pawn-b-0", "component_type": "pawn", "owner": "black"},
                }
            }
        },
    }


def _state_with_king_only() -> dict[str, Any]:
    """White king at 0,0 on an empty board."""
    return {
        "status": "in_progress",
        "turn": "white",
        "sequence": 0,
        "zones": {
            "board": {
                "cells": {
                    "0,0": {"id": "king-w-0", "component_type": "king", "owner": "white"},
                }
            }
        },
    }


class TestGreedyAgent:
    def test_prefers_capture(self) -> None:
        defn = _chess_definition()
        agent = GreedyAgent("ws://localhost:8080", "test", defn)
        agent.client.seat = "white"
        state = _state_with_king_and_enemy()
        action = agent.choose_action(state)
        assert action is not None
        # Should pick capture at 5,5
        to_pos = action.get("to")
        assert to_pos is not None
        if isinstance(to_pos, dict):
            assert to_pos.get("cell") == "5,5"

    def test_returns_move_when_no_captures(self) -> None:
        defn = _chess_definition()
        agent = GreedyAgent("ws://localhost:8080", "test", defn)
        agent.client.seat = "white"
        state = _state_with_king_only()
        action = agent.choose_action(state)
        assert action is not None
        assert action["action_type"] == "move_piece"


class TestMCTSAgent:
    def test_returns_valid_action(self) -> None:
        defn = _chess_definition()
        agent = MCTSAgent("ws://localhost:8080", "test", defn, budget=10)
        agent.client.seat = "white"
        state = _state_with_king_only()
        action = agent.choose_action(state)
        assert action is not None
        assert action["action_type"] == "move_piece"

    def test_single_move_returns_immediately(self) -> None:
        """When only one move exists, MCTS should return it without search."""
        defn = _chess_definition()
        agent = MCTSAgent("ws://localhost:8080", "test", defn, budget=10)
        agent.client.seat = "white"
        # King in corner: only 3 moves
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "white",
            "sequence": 0,
            "zones": {
                "board": {
                    "cells": {
                        "0,0": {"id": "king-w-0", "component_type": "king", "owner": "white"},
                    }
                }
            },
        }
        action = agent.choose_action(state)
        assert action is not None

    def test_empty_moves_returns_none(self) -> None:
        defn = _chess_definition()
        agent = MCTSAgent("ws://localhost:8080", "test", defn, budget=5)
        agent.client.seat = "white"
        # No pieces on board
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "white",
            "sequence": 0,
            "zones": {"board": {"cells": {}}},
        }
        action = agent.choose_action(state)
        assert action is None


class TestRandomAgentReexport:
    def test_random_agent_importable_from_agents(self) -> None:
        """RandomAgent should be re-exported from agents module."""
        assert RandomAgent is not None
        agent = RandomAgent("ws://localhost:8080", "test")
        assert agent.client.client_type == "bot"
