"""Tests for per-session resource budgets: component limits, event limits."""

from __future__ import annotations

import json

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.error import ResourceBudgetError
from baize.runtime import (
    ComponentData,
    ComponentId,
    ComponentTable,
    GameSession,
    MAX_COMPONENTS_PER_GAME,
    MAX_EVENTS_PER_GAME,
    MAX_STATE_SIZE_BYTES,
)
from baize.transition import apply_action


def _ttt_json() -> str:
    return json.dumps({
        "game": {
            "name": "Tic-Tac-Toe",
            "players": ["X", "O"],
            "information": "perfect",
        },
        "zones": {
            "board": {
                "zone_type": "grid",
                "dimensions": [3, 3],
                "visibility": "public",
            }
        },
        "components": {
            "piece": {"owner": "per_player", "count": "unlimited"}
        },
        "turn_order": {"type": "alternating", "players": ["X", "O"]},
        "end_conditions": [{"result": "draw", "condition": "board_is_full"}],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    })


# ===================================================================
# Component Limits
# ===================================================================


class TestComponentLimits:
    """ComponentTable enforces MAX_COMPONENTS_PER_GAME."""

    def test_insert_within_limit(self) -> None:
        table = ComponentTable()
        for i in range(100):
            cid = table.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"test-{i}",
                    component_type="piece",
                )
            )
            assert cid.value == i

    def test_insert_at_limit_fails(self) -> None:
        table = ComponentTable()
        for i in range(MAX_COMPONENTS_PER_GAME):
            table.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"fill-{i}",
                    component_type="piece",
                )
            )
        with pytest.raises(ResourceBudgetError) as exc_info:
            table.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id="overflow",
                    component_type="piece",
                )
            )
        assert "components" in str(exc_info.value)
        assert str(MAX_COMPONENTS_PER_GAME) in str(exc_info.value)

    def test_place_action_fails_at_component_limit(self) -> None:
        defn = GameDefinition.from_json(_ttt_json())
        session = GameSession(defn)
        # Fill to limit
        for i in range(MAX_COMPONENTS_PER_GAME):
            session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"pre-{i}",
                    component_type="piece",
                )
            )
        action = Action(
            action_type="place",
            to_pos="0,0",
            component_type="piece",
        )
        with pytest.raises(ResourceBudgetError):
            apply_action(session, action)


# ===================================================================
# Event Count Tracking
# ===================================================================


class TestEventCountTracking:
    """Events are counted and enforced per session."""

    def test_event_count_starts_at_zero(self) -> None:
        defn = GameDefinition.from_json(_ttt_json())
        session = GameSession(defn)
        assert session.runtime.event_count == 0

    def test_event_count_increments(self) -> None:
        defn = GameDefinition.from_json(_ttt_json())
        session = GameSession(defn)
        action = Action(
            action_type="place",
            to_pos="0,0",
            component_type="piece",
        )
        events = apply_action(session, action)
        assert len(events) > 0
        assert session.runtime.event_count == len(events)

    def test_event_count_accumulates(self) -> None:
        defn = GameDefinition.from_json(_ttt_json())
        session = GameSession(defn)
        coords = ["0,0", "1,0", "0,1", "1,1"]
        total = 0
        for coord in coords:
            action = Action(
                action_type="place",
                to_pos=coord,
                component_type="piece",
            )
            events = apply_action(session, action)
            total += len(events)
        assert session.runtime.event_count == total


# ===================================================================
# Constants Are Reasonable
# ===================================================================


class TestConstants:
    """Resource budget defaults are generous enough for real games."""

    def test_component_limit_at_least_10k(self) -> None:
        assert MAX_COMPONENTS_PER_GAME >= 10_000

    def test_event_limit_at_least_100k(self) -> None:
        assert MAX_EVENTS_PER_GAME >= 100_000

    def test_state_size_at_least_10mb(self) -> None:
        assert MAX_STATE_SIZE_BYTES >= 10 * 1024 * 1024


# ===================================================================
# Reference Games Within Budgets
# ===================================================================


class TestReferenceGames:
    """All reference games initialize without exceeding budgets."""

    def test_all_reference_games_within_budgets(self) -> None:
        from pathlib import Path

        games_dir = Path(__file__).resolve().parent.parent.parent / "games"
        if not games_dir.exists():
            pytest.skip("games directory not found")
        game_files = sorted(games_dir.glob("*.json"))
        assert len(game_files) >= 20, f"Expected 20+ games, found {len(game_files)}"
        for game_file in game_files:
            defn = GameDefinition.from_json(game_file.read_text())
            session = GameSession(defn)
            assert session.runtime.event_count == 0
            assert len(session.runtime.components) < MAX_COMPONENTS_PER_GAME
