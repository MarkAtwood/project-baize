#!/usr/bin/env python3
"""End-to-end server smoke test.

Starts the server, creates a room, connects two bot clients,
plays a full tic-tac-toe game, and verifies the result.

Usage:
    # With server already running:
    python tests/smoke_test_server.py

    # Auto-start server (requires cargo build):
    python tests/smoke_test_server.py --start-server

Exit code 0 = success, 1 = failure.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add python/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from baize.client import BaizeClient


SERVER_URL = os.environ.get("BAIZE_SERVER_URL", "ws://localhost:8080")
GAMES_DIR = Path(__file__).parent.parent / "games"


def create_room(server_url: str, room_id: str, definition_path: Path) -> dict:
    """Create a room via HTTP POST."""
    import urllib.request

    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    definition = json.loads(definition_path.read_text())
    body = json.dumps({"room_id": room_id, "definition": definition}).encode()
    req = urllib.request.Request(
        f"{http_url}/rooms",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def play_tic_tac_toe(server_url: str, room_id: str) -> dict:
    """Connect two clients and play a full game."""
    # X's moves: top row (0,0), (1,0), (2,0)
    # O's moves: second row (0,1), (1,1)
    x_moves = [
        {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "0,0"}},
        {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "1,0"}},
        {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "2,0"}},
    ]
    o_moves = [
        {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "0,1"}},
        {"action_type": "place", "component_type": "mark", "to": {"zone": "board", "cell": "1,1"}},
    ]

    # Connect both players
    client_x = BaizeClient(server_url=server_url, room_id=room_id, client_type="bot")
    client_o = BaizeClient(server_url=server_url, room_id=room_id, client_type="bot")

    client_x.connect(timeout=5)
    time.sleep(0.3)
    client_o.connect(timeout=5)
    time.sleep(0.3)

    print(f"  X is '{client_x.seat}', O is '{client_o.seat}'")

    # Play alternating moves
    move_idx_x = 0
    move_idx_o = 0
    for turn in range(5):
        time.sleep(0.2)
        if turn % 2 == 0:
            # X's turn
            client_x.submit_move(x_moves[move_idx_x])
            move_idx_x += 1
        else:
            # O's turn
            client_o.submit_move(o_moves[move_idx_o])
            move_idx_o += 1
        time.sleep(0.3)

    # Wait for final state
    time.sleep(0.5)
    final_state = client_x.state

    client_x.disconnect()
    client_o.disconnect()

    return final_state


def verify_result(state: dict) -> bool:
    """Verify the game ended correctly."""
    status = state.get("status", "")
    result = state.get("result", {})
    outcome = result.get("outcome", "")
    winner = result.get("winner", "")
    condition = result.get("condition", "")

    print(f"  Status: {status}")
    print(f"  Outcome: {outcome}")
    print(f"  Winner: {winner}")
    print(f"  Condition: {condition}")

    if status != "finished":
        print("  FAIL: game did not finish")
        return False
    if outcome != "win":
        print("  FAIL: expected win")
        return False
    if condition != "three_in_a_row":
        print(f"  FAIL: expected condition 'three_in_a_row', got '{condition}'")
        return False

    print("  PASS")
    return True


def test_reconnection(server_url: str, room_id: str) -> bool:
    """Test that a client can reconnect with a token and get the same seat."""
    print("\n--- Test: Token Reconnection ---")

    client = BaizeClient(server_url=server_url, room_id=room_id, client_type="bot")
    client.connect(timeout=5)
    time.sleep(0.3)

    original_seat = client.seat
    token = client.token
    print(f"  First connect: seat={original_seat}, token={token}")

    client.disconnect()
    time.sleep(0.3)

    # Reconnect with token
    client2 = BaizeClient(server_url=server_url, room_id=room_id, client_type="bot", token=token)
    client2.connect(timeout=5)
    time.sleep(0.3)

    reconnect_seat = client2.seat
    print(f"  Reconnect: seat={reconnect_seat}")
    client2.disconnect()

    if original_seat == reconnect_seat:
        print("  PASS")
        return True
    else:
        print(f"  FAIL: seats differ ({original_seat} vs {reconnect_seat})")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Server smoke test")
    parser.add_argument("--start-server", action="store_true", help="Auto-start the server")
    parser.add_argument("--server-url", default=SERVER_URL, help="Server URL")
    args = parser.parse_args()

    server_proc = None
    if args.start_server:
        print("Starting server...")
        server_proc = subprocess.Popen(
            ["cargo", "run"],
            cwd=str(Path(__file__).parent.parent / "server"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(3)  # Wait for server startup

    try:
        # Test 1: Create room and play game
        print("--- Test: Full Tic-Tac-Toe Game ---")
        room_id = f"smoke-test-{int(time.time())}"
        print(f"  Creating room '{room_id}'...")
        create_room(args.server_url, room_id, GAMES_DIR / "tic-tac-toe.json")
        print("  Playing game...")
        state = play_tic_tac_toe(args.server_url, room_id)
        game_ok = verify_result(state)

        # Test 2: Reconnection
        room_id2 = f"smoke-reconnect-{int(time.time())}"
        create_room(args.server_url, room_id2, GAMES_DIR / "tic-tac-toe.json")
        reconnect_ok = test_reconnection(args.server_url, room_id2)

        # Summary
        print(f"\n{'='*40}")
        all_ok = game_ok and reconnect_ok
        if all_ok:
            print("ALL TESTS PASSED")
        else:
            print("SOME TESTS FAILED")
            sys.exit(1)

    finally:
        if server_proc is not None:
            server_proc.terminate()
            server_proc.wait(timeout=5)


if __name__ == "__main__":
    main()
