"""Headless WebSocket client for Baize game server.

Connects to a running server, performs the hello/welcome handshake,
receives game state, and submits moves programmatically. Designed
for bots, automated testing, and AI research.

Usage::

    client = BaizeClient("ws://localhost:8080", "room-id")
    client.connect()
    state = client.state          # latest game state
    client.submit_move({"action_type": "place", "component_type": "mark",
                        "to": {"zone": "board", "cell": "1,1"}})
    client.disconnect()
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

PROTOCOL_VERSION = 1


@dataclass
class BaizeClient:
    """Headless game client that connects via WebSocket."""

    server_url: str
    room_id: str
    client_type: str = "bot"
    token: str | None = None

    # Populated after connect
    seat: str = ""
    game_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    connected: bool = False

    # Callbacks
    on_state: Callable[[dict[str, Any]], None] | None = None
    on_move_confirmed: Callable[[dict[str, Any]], None] | None = None
    on_move_rejected: Callable[[dict[str, Any]], None] | None = None
    on_error: Callable[[str], None] | None = None

    _ws: Any = field(default=None, repr=False)
    _recv_thread: threading.Thread | None = field(default=None, repr=False)
    _messages: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _welcome_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    _sequence: int = field(default=0, repr=False)

    def connect(self, timeout: float = 10.0) -> None:
        """Connect to the server and complete the handshake."""
        import websocket  # type: ignore[import-untyped]

        ws_url = f"{self.server_url}/ws/{self.room_id}"
        self._welcome_event.clear()
        self._ws = websocket.WebSocket()
        self._ws.settimeout(timeout)
        self._ws.connect(ws_url)

        # Send hello
        hello: dict[str, Any] = {
            "message_type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "client_type": self.client_type,
        }
        if self.token is not None:
            hello["token"] = self.token
        self._ws.send(json.dumps(hello))

        # Start receive thread
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True
        )
        self._recv_thread.start()

        # Wait for welcome
        if not self._welcome_event.wait(timeout=timeout):
            self._ws.close()
            raise TimeoutError("did not receive welcome within timeout")

        self.connected = True

    def disconnect(self) -> None:
        """Close the connection."""
        self.connected = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def submit_move(self, action: dict[str, Any]) -> None:
        """Submit a move action to the server."""
        msg = {
            "message_type": "submit_move",
            "game_id": self.game_id,
            "player": self.seat,
            "sequence": self._sequence,
            "action": action,
        }
        self._send(msg)

    def request_random(
        self,
        random_type: str,
        **kwargs: Any,
    ) -> None:
        """Request server-side randomness."""
        msg = {
            "message_type": "request_random",
            "game_id": self.game_id,
            "player": self.seat,
            "random_request": {"random_type": random_type, **kwargs},
        }
        self._send(msg)

    def pass_turn(self) -> None:
        """Pass the current turn."""
        self.submit_move({"action_type": "pass"})

    def resign(self) -> None:
        """Resign the game."""
        self.submit_move({"action_type": "resign"})

    def wait_for_state(self, timeout: float = 5.0) -> dict[str, Any]:
        """Block until a state_sync is received, then return it."""
        deadline = time.monotonic() + timeout
        initial_state = dict(self.state)
        while time.monotonic() < deadline:
            if self.state != initial_state:
                return dict(self.state)
            time.sleep(0.05)
        return dict(self.state)

    def _send(self, msg: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("not connected")
        self._ws.send(json.dumps(msg))

    def _recv_loop(self) -> None:
        while self._ws is not None:
            try:
                raw = self._ws.recv()
                if not raw:
                    break
                data = json.loads(raw)
                self._handle_message(data)
            except Exception:
                break
        self.connected = False

    def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("message_type", "")
        self._messages.append(msg)

        if msg_type == "welcome":
            self.seat = msg.get("seat", "")
            self.game_id = msg.get("game_id", "")
            self.token = msg.get("token", self.token)
            self._welcome_event.set()

        elif msg_type == "state_sync":
            self.state = msg.get("full_state", {})
            self._sequence = msg.get("sequence", self._sequence)
            if self.on_state is not None:
                self.on_state(self.state)

        elif msg_type == "move_confirmed":
            self._sequence = msg.get("sequence", self._sequence)
            if self.on_move_confirmed is not None:
                self.on_move_confirmed(msg)

        elif msg_type == "move_rejected":
            if self.on_move_rejected is not None:
                self.on_move_rejected(msg)

        elif msg_type == "error":
            if self.on_error is not None:
                self.on_error(msg.get("detail", str(msg)))
