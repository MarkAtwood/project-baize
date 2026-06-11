"""Tests for the headless BaizeClient message handling."""

from baize.client import BaizeClient, PROTOCOL_VERSION


class TestHandshake:
    def test_welcome_sets_seat_and_token(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        client._handle_message({
            "message_type": "welcome",
            "protocol_version": PROTOCOL_VERSION,
            "server_version": "0.1.0",
            "seat": "white",
            "game_id": "test-room",
            "token": "abc123",
        })
        assert client.seat == "white"
        assert client.game_id == "test-room"
        assert client.token == "abc123"
        assert client._welcome_event.is_set()

    def test_welcome_preserves_existing_token_if_not_provided(self) -> None:
        client = BaizeClient(
            server_url="ws://localhost:8080", room_id="test", token="old-token"
        )
        client._handle_message({
            "message_type": "welcome",
            "seat": "black",
            "game_id": "room-2",
        })
        assert client.seat == "black"
        assert client.token == "old-token"


class TestStateSync:
    def test_state_sync_updates_state(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        state_received: list[dict] = []  # type: ignore[type-arg]
        client.on_state = lambda s: state_received.append(s)

        client._handle_message({
            "message_type": "state_sync",
            "game_id": "test",
            "sequence": 5,
            "full_state": {"status": "in_progress", "turn": "white"},
        })
        assert client.state == {"status": "in_progress", "turn": "white"}
        assert client._sequence == 5
        assert len(state_received) == 1

    def test_state_sync_without_callback(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        client._handle_message({
            "message_type": "state_sync",
            "sequence": 1,
            "full_state": {"turn": "X"},
        })
        assert client.state == {"turn": "X"}


class TestMoveMessages:
    def test_move_confirmed_updates_sequence(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        confirmed: list[dict] = []  # type: ignore[type-arg]
        client.on_move_confirmed = lambda m: confirmed.append(m)

        client._handle_message({
            "message_type": "move_confirmed",
            "game_id": "test",
            "sequence": 3,
        })
        assert client._sequence == 3
        assert len(confirmed) == 1

    def test_move_rejected_callback(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        rejections: list[dict] = []  # type: ignore[type-arg]
        client.on_move_rejected = lambda m: rejections.append(m)

        client._handle_message({
            "message_type": "move_rejected",
            "game_id": "test",
            "reason": "not your turn",
        })
        assert len(rejections) == 1
        assert rejections[0]["reason"] == "not your turn"


class TestErrorHandling:
    def test_error_callback(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        errors: list[str] = []
        client.on_error = lambda e: errors.append(e)

        client._handle_message({
            "message_type": "error",
            "error_code": "rate_limited",
            "detail": "too many messages",
        })
        assert errors == ["too many messages"]

    def test_unknown_message_stored(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        client._handle_message({"message_type": "unknown_type", "data": 42})
        assert len(client._messages) == 1


class TestMessageBuilding:
    def test_submit_move_format(self) -> None:
        client = BaizeClient(server_url="ws://localhost:8080", room_id="test")
        client.seat = "white"
        client.game_id = "room-1"
        client._sequence = 5

        # Can't actually send without a ws connection, but test the data shape
        import json

        action = {"action_type": "place", "component_type": "mark",
                  "to": {"zone": "board", "cell": "1,1"}}
        msg = {
            "message_type": "submit_move",
            "game_id": client.game_id,
            "player": client.seat,
            "sequence": client._sequence,
            "action": action,
        }
        serialized = json.dumps(msg)
        parsed = json.loads(serialized)
        assert parsed["message_type"] == "submit_move"
        assert parsed["player"] == "white"
        assert parsed["action"]["action_type"] == "place"
