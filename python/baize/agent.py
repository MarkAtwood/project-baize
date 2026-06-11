"""AI player agent framework.

Provides a base class for writing game-playing agents. Agents connect
to the server via the BaizeClient, receive game state, and submit moves.
At the protocol level, agents are indistinguishable from human players.

Usage::

    class MyAgent(Agent):
        def choose_action(self, state: dict) -> dict | None:
            # Return an action dict, or None to pass
            moves = state.get("legal_moves", [])
            return moves[0] if moves else None

    agent = MyAgent("ws://localhost:8080", "room-id")
    agent.play()  # blocks until game ends
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any

from baize.client import BaizeClient


class Agent(ABC):
    """Base class for game-playing agents.

    Subclasses implement ``choose_action`` to decide what move to make
    given the current game state. The agent loop handles connecting,
    receiving state, and submitting moves.
    """

    def __init__(
        self,
        server_url: str,
        room_id: str,
        *,
        token: str | None = None,
        poll_interval: float = 0.1,
    ) -> None:
        self.client = BaizeClient(
            server_url=server_url,
            room_id=room_id,
            client_type="bot",
            token=token,
        )
        self.poll_interval = poll_interval
        self._running = False

    @abstractmethod
    def choose_action(self, state: dict[str, Any]) -> dict[str, Any] | None:
        """Choose an action given the current game state.

        Args:
            state: The full game state dict from state_sync.

        Returns:
            An action dict to submit, or None to pass.
        """

    def on_game_start(self, state: dict[str, Any]) -> None:
        """Called once when the agent receives its first state."""

    def on_game_end(self, state: dict[str, Any]) -> None:
        """Called when the game ends."""

    def play(self, timeout: float = 300.0) -> dict[str, Any]:
        """Connect and play until the game ends or timeout.

        Returns the final game state.
        """
        self.client.connect()
        self._running = True
        deadline = time.monotonic() + timeout
        first_state = True

        try:
            while self._running and time.monotonic() < deadline:
                state = self.client.state
                if not state:
                    time.sleep(self.poll_interval)
                    continue

                status = state.get("status", "")
                if status == "finished":
                    self.on_game_end(state)
                    break

                if first_state:
                    self.on_game_start(state)
                    first_state = False

                # Only act on our turn
                if state.get("turn") != self.client.seat:
                    time.sleep(self.poll_interval)
                    continue

                action = self.choose_action(state)
                if action is None:
                    self.client.pass_turn()
                else:
                    self.client.submit_move(action)

                # Wait for state update after our move
                time.sleep(self.poll_interval)

        finally:
            self._running = False
            self.client.disconnect()

        return dict(self.client.state)

    def stop(self) -> None:
        """Signal the agent to stop playing."""
        self._running = False


class RandomAgent(Agent):
    """Agent that picks a random legal move each turn.

    Proof-of-concept agent. If ``legal_moves`` is present in the state,
    picks uniformly at random. Otherwise passes.
    """

    def choose_action(self, state: dict[str, Any]) -> dict[str, Any] | None:
        moves = state.get("legal_moves", [])
        if not moves:
            return None
        return dict(random.choice(moves))
