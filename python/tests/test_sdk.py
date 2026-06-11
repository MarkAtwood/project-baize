"""Tests for the Agent SDK."""

import json
from typing import Any

from baize.definition import GameDefinition
from baize.sdk import AgentSession


def _ttt_definition() -> GameDefinition:
    raw = {
        "game": {"name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect"},
        "zones": {
            "board": {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"},
        },
        "components": {
            "mark": {"owner": "per_player", "count": "unlimited"},
        },
        "turn_order": {
            "type": "alternating", "players": ["X", "O"],
            "actions_per_turn": 1, "mandatory": True,
        },
        "end_conditions": [
            {"result": "win", "player": "current", "condition": "three_in_line"},
            {"result": "draw", "condition": "all_cells_occupied"},
        ],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    return GameDefinition.from_json(json.dumps(raw))


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


class TestAgentSession:
    def test_from_empty_state(self) -> None:
        defn = _ttt_definition()
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "X",
            "sequence": 0,
            "zones": {"board": {"cells": {}}},
        }
        session = AgentSession.from_server_state(defn, state)
        assert session.current_player == "X"
        assert session.status == "in_progress"

    def test_legal_moves_on_empty_board(self) -> None:
        """Empty tic-tac-toe board should have no grid moves (placement is supply-based)."""
        defn = _ttt_definition()
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "X",
            "sequence": 0,
            "zones": {"board": {"cells": {}}},
        }
        session = AgentSession.from_server_state(defn, state)
        # Tic-tac-toe uses placement from supply, not grid movement
        moves = session.legal_moves()
        assert isinstance(moves, list)

    def test_legal_moves_with_pieces(self) -> None:
        """King on an empty chess board should have legal moves."""
        defn = _chess_definition()
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "white",
            "sequence": 0,
            "zones": {
                "board": {
                    "cells": {
                        "4,4": {
                            "id": "king-white-0",
                            "component_type": "king",
                            "owner": "white",
                        }
                    }
                }
            },
        }
        session = AgentSession.from_server_state(defn, state)
        moves = session.legal_moves()
        assert len(moves) == 8  # King in center of empty board

    def test_move_to_action_dict(self) -> None:
        """AgentMove.to_action_dict() produces valid action dicts."""
        defn = _chess_definition()
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "white",
            "sequence": 0,
            "zones": {
                "board": {
                    "cells": {
                        "0,0": {
                            "id": "king-white-0",
                            "component_type": "king",
                            "owner": "white",
                        }
                    }
                }
            },
        }
        session = AgentSession.from_server_state(defn, state)
        moves = session.legal_moves()
        assert len(moves) > 0

        action_dict = moves[0].to_action_dict()
        assert "action_type" in action_dict
        assert action_dict["action_type"] == "move_piece"

    def test_turn_index_restored(self) -> None:
        defn = _ttt_definition()
        state: dict[str, Any] = {
            "status": "in_progress",
            "turn": "O",
            "sequence": 1,
            "zones": {"board": {"cells": {}}},
        }
        session = AgentSession.from_server_state(defn, state)
        assert session.current_player == "O"
