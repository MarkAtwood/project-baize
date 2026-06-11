"""Terminal client for Baize game server.

Connects to a running server, renders the board as ASCII art, and
accepts moves via text commands. Useful for dev/testing, SSH play,
and accessibility.

Usage::

    python -m baize.cli ws://localhost:8080 room-id
    python -m baize.cli ws://localhost:8080 room-id --token abc123
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from baize.client import BaizeClient


def render_grid(state: dict[str, Any]) -> str:
    """Render a grid zone as ASCII art."""
    zones = state.get("zones", {})
    for zone_name, zone_data in zones.items():
        cells = zone_data.get("cells", {})
        if not isinstance(cells, dict):
            continue
        # Determine grid dimensions from cell coordinates
        max_col = 0
        max_row = 0
        for coord in cells:
            parts = coord.split(",")
            if len(parts) == 2:
                c, r = int(parts[0]), int(parts[1])
                max_col = max(max_col, c)
                max_row = max(max_row, r)

        # Infer dimensions from state or default
        width = max_col + 1 if cells else 3
        height = max_row + 1 if cells else 3

        lines = []
        # Column headers
        header = "   " + "  ".join(str(c) for c in range(width))
        lines.append(header)
        lines.append("  " + "---" * width + "-")

        for row in range(height):
            row_cells = []
            for col in range(width):
                coord = f"{col},{row}"
                cell = cells.get(coord)
                if cell is None:
                    row_cells.append(" . ")
                elif isinstance(cell, dict):
                    owner = cell.get("owner", "?")
                    comp_type = cell.get("component_type", "?")
                    label = _piece_label(comp_type, owner)
                    row_cells.append(f" {label} ")
                else:
                    row_cells.append(" ? ")
            lines.append(f"{row} |{'|'.join(row_cells)}|")
            lines.append("  " + "---" * width + "-")

        return f"[{zone_name}]\n" + "\n".join(lines)

    return "(no grid zones)"


def _piece_label(comp_type: str, owner: str) -> str:
    """Short label for a piece."""
    # For tic-tac-toe style: show owner letter
    if comp_type == "mark":
        return owner[0] if owner else "?"
    # For chess style: show piece type initial
    piece_chars = {
        "king": "K", "queen": "Q", "rook": "R",
        "bishop": "B", "knight": "N", "pawn": "P",
    }
    ch = piece_chars.get(comp_type, comp_type[0].upper() if comp_type else "?")
    # Lowercase for black
    if owner and owner[0].lower() == "b":
        ch = ch.lower()
    return ch


def render_status(state: dict[str, Any], seat: str) -> str:
    """Render game status line."""
    status = state.get("status", "unknown")
    turn = state.get("turn", "?")
    seq = state.get("sequence", 0)
    result = state.get("result")

    if status == "finished" and result:
        outcome = result.get("outcome", "")
        winner = result.get("winner", "")
        condition = result.get("condition", "")
        return f"GAME OVER: {outcome} — {winner} wins ({condition})"

    marker = " <-- your turn" if turn == seat else ""
    return f"Turn: {turn}{marker}  |  Seq: {seq}  |  You: {seat}"


def parse_move(text: str) -> dict[str, Any] | None:
    """Parse a text command into an action dict.

    Supported formats:
        place mark 1,1       — place a component
        move 0,0 1,1         — move piece from→to
        pass                 — pass turn
        resign               — resign game
        flip comp-id         — flip a component
        remove comp-id       — remove a component
    """
    parts = text.strip().split()
    if not parts:
        return None

    cmd = parts[0].lower()

    if cmd == "pass":
        return {"action_type": "pass"}
    if cmd == "resign":
        return {"action_type": "resign"}
    if cmd == "place" and len(parts) >= 3:
        return {
            "action_type": "place",
            "component_type": parts[1],
            "to": {"zone": "board", "cell": parts[2]},
        }
    if cmd == "move" and len(parts) >= 3:
        return {
            "action_type": "move_piece",
            "from": {"zone": "board", "cell": parts[1]},
            "to": {"zone": "board", "cell": parts[2]},
        }
    if cmd == "flip" and len(parts) >= 2:
        return {"action_type": "flip", "component_id": parts[1]}
    if cmd == "remove" and len(parts) >= 2:
        return {"action_type": "remove", "component_id": parts[1]}

    return None


HELP_TEXT = """Commands:
  place <type> <col,row>   Place a component (e.g. place mark 1,1)
  move <from> <to>         Move piece (e.g. move 0,0 1,1)
  pass                     Pass your turn
  resign                   Resign the game
  flip <id>                Flip a component
  remove <id>              Remove a component
  board                    Redraw the board
  help                     Show this help
  quit                     Disconnect and exit
"""


def run_cli(server_url: str, room_id: str, token: str | None = None) -> None:
    """Main CLI loop."""
    client = BaizeClient(
        server_url=server_url,
        room_id=room_id,
        client_type="browser",
        token=token,
    )

    print(f"Connecting to {server_url}/ws/{room_id}...")
    try:
        client.connect(timeout=10.0)
    except Exception as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Connected as: {client.seat}")
    if client.token:
        print(f"Token (save for reconnect): {client.token}")
    print(HELP_TEXT)

    # Wait for initial state
    time.sleep(0.5)
    if client.state:
        print(render_grid(client.state))
        print(render_status(client.state, client.seat))

    try:
        while True:
            try:
                line = input(f"[{client.seat}]> ")
            except EOFError:
                break

            line = line.strip()
            if not line:
                continue

            if line.lower() in ("quit", "exit", "q"):
                break
            if line.lower() in ("help", "h", "?"):
                print(HELP_TEXT)
                continue
            if line.lower() in ("board", "b"):
                if client.state:
                    print(render_grid(client.state))
                    print(render_status(client.state, client.seat))
                else:
                    print("(no state received yet)")
                continue

            action = parse_move(line)
            if action is None:
                print(f"Unknown command: {line}  (type 'help' for commands)")
                continue

            client.submit_move(action)
            time.sleep(0.3)  # Wait for server response

            if client.state:
                print(render_grid(client.state))
                print(render_status(client.state, client.seat))

    except KeyboardInterrupt:
        print("\nDisconnecting...")
    finally:
        client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baize terminal game client",
        usage="python -m baize.cli SERVER_URL ROOM_ID [--token TOKEN]",
    )
    parser.add_argument("server_url", help="WebSocket server URL (e.g. ws://localhost:8080)")
    parser.add_argument("room_id", help="Room ID to join")
    parser.add_argument("--token", help="Auth token for reconnection")
    args = parser.parse_args()
    run_cli(args.server_url, args.room_id, args.token)


if __name__ == "__main__":
    main()
