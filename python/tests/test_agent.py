"""Tests for the AI agent framework."""

from typing import Any

from baize.agent import Agent, RandomAgent


class AlwaysPlaceCenter(Agent):
    """Test agent that always places at center."""

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "action_type": "place",
            "component_type": "mark",
            "to": {"zone": "board", "cell": "1,1"},
        }


class TestAgentBase:
    def test_agent_is_abstract(self) -> None:
        """Cannot instantiate Agent directly."""
        import pytest
        with pytest.raises(TypeError):
            Agent("ws://localhost:8080", "test")  # type: ignore[abstract]

    def test_subclass_choose_action(self) -> None:
        agent = AlwaysPlaceCenter("ws://localhost:8080", "test")
        action = agent.choose_action({"turn": "X", "status": "in_progress"})
        assert action is not None
        assert action["action_type"] == "place"

    def test_client_type_is_bot(self) -> None:
        agent = AlwaysPlaceCenter("ws://localhost:8080", "test")
        assert agent.client.client_type == "bot"

    def test_token_passed_to_client(self) -> None:
        agent = AlwaysPlaceCenter(
            "ws://localhost:8080", "test", token="my-token"
        )
        assert agent.client.token == "my-token"

    def test_stop_sets_running_false(self) -> None:
        agent = AlwaysPlaceCenter("ws://localhost:8080", "test")
        agent._running = True
        agent.stop()
        assert agent._running is False


class TestRandomAgent:
    def test_random_agent_picks_from_legal_moves(self) -> None:
        agent = RandomAgent("ws://localhost:8080", "test")
        state = {
            "legal_moves": [
                {"action_type": "place", "to": {"cell": "0,0"}},
                {"action_type": "place", "to": {"cell": "1,1"}},
            ]
        }
        action = agent.choose_action(state)
        assert action is not None
        assert action["action_type"] == "place"

    def test_random_agent_passes_when_no_moves(self) -> None:
        agent = RandomAgent("ws://localhost:8080", "test")
        action = agent.choose_action({"legal_moves": []})
        assert action is None

    def test_random_agent_passes_when_no_legal_moves_key(self) -> None:
        agent = RandomAgent("ws://localhost:8080", "test")
        action = agent.choose_action({"status": "in_progress"})
        assert action is None
