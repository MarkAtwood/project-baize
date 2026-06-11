"""Interactive engine REPL for local game exploration.

Load a game definition, step through moves, inspect state, test CEL
expressions, and run perturber effects — no server required.

Usage::

    python -m baize.repl
    python -m baize.repl games/tic-tac-toe.json
"""

from __future__ import annotations

import argparse
import cmd
import copy
import json
import sys
from pathlib import Path
from typing import Any

from baize.action import Action
from baize.definition import GameDefinition
from baize.end_conditions import check_end_conditions, _build_end_condition_variables
from baize.moves import legal_moves
from baize.perturber import execute_effect
from baize.runtime import (
    ComponentId,
    GameSession,
    GridZone,
    StackZone,
    SetZone,
)
from baize.transition import apply_action


def _render_grid(session: GameSession, zone_name: str, zone: GridZone) -> str:
    """Render a grid zone as ASCII art."""
    w, h = zone.width, zone.height
    lines = []
    header = "   " + "  ".join(f"{c:>2}" for c in range(w))
    lines.append(header)
    lines.append("  " + "----" * w + "-")

    for row in range(h):
        cells = []
        for col in range(w):
            cid = zone.grid_get(col, row)
            if cid is None:
                cells.append("  . ")
            else:
                comp = session.runtime.components.get(cid)
                if comp is None:
                    cells.append("  ? ")
                else:
                    label = comp.component_type[:3]
                    cells.append(f" {label:>3}")
        lines.append(f"{row:>2} |{'|'.join(cells)}|")
        lines.append("  " + "----" * w + "-")

    return f"[{zone_name}]\n" + "\n".join(lines)


def _format_action(action: Action) -> str:
    """Format an action for display."""
    parts = [action.action_type]
    if action.component_type:
        parts.append(action.component_type)
    if action.component_id:
        parts.append(action.component_id)
    if action.from_pos:
        parts.append(f"from={action.from_pos}")
    if action.to_pos:
        parts.append(f"to={action.to_pos}")
    if action.zone:
        parts.append(f"zone={action.zone}")
    if action.promote_to:
        parts.append(f"promote_to={action.promote_to}")
    if action.swap_with:
        parts.append(f"swap_with={action.swap_with}")
    return " ".join(str(p) for p in parts)


class BaizeRepl(cmd.Cmd):
    """Interactive Baize engine REPL."""

    prompt = "baize> "
    intro = "Baize interactive REPL. Type 'help' for commands, 'load <path>' to load a game."

    def __init__(self) -> None:
        super().__init__()
        self.session: GameSession | None = None
        self.definition: GameDefinition | None = None
        self.definition_path: str | None = None
        self.history: list[Action] = []
        self.snapshots: list[GameSession] = []

    def _require_session(self) -> GameSession | None:
        if self.session is None:
            print("No game loaded. Use 'load <path>' first.")
            return None
        return self.session

    def _snapshot(self) -> None:
        if self.session is not None:
            self.snapshots.append(copy.deepcopy(self.session))

    # -- Session management --

    def do_load(self, arg: str) -> None:
        """Load a game definition: load <path.json>"""
        path = arg.strip()
        if not path:
            print("Usage: load <path.json>")
            return
        try:
            text = Path(path).read_text()
            self.definition = GameDefinition.from_json(text)
            self.session = GameSession(self.definition)
            self.session.runtime.status = "in_progress"
            self.definition_path = path
            self.history = []
            self.snapshots = []
            print(f"Loaded: {self.definition.game.name}")
            players = self.definition.game.players
            if isinstance(players, list):
                print(f"Players: {', '.join(players)}")
            print(f"Zones: {', '.join(self.definition.zones.keys())}")
        except FileNotFoundError:
            print(f"File not found: {path}")
        except Exception as e:
            print(f"Error loading: {e}")

    def do_reset(self, arg: str) -> None:
        """Reset to initial state."""
        if self.definition is None:
            print("No game loaded.")
            return
        self.session = GameSession(self.definition)
        self.session.runtime.status = "in_progress"
        self.history = []
        self.snapshots = []
        print("Reset to initial state.")

    def do_status(self, arg: str) -> None:
        """Show game status."""
        session = self._require_session()
        if session is None:
            return
        player = session.current_player() or "(none)"
        print(f"Status:  {session.runtime.status}")
        print(f"Player:  {player}")
        print(f"Move:    {session.runtime.move_count}")
        print(f"Seq:     {session.runtime.sequence}")

        result = check_end_conditions(session)
        if result is not None:
            print(f"Result:  {result.outcome} — {result.winner or ''} {result.condition or ''}")

    def do_history(self, arg: str) -> None:
        """Show move history."""
        if not self.history:
            print("(no moves)")
            return
        for i, action in enumerate(self.history):
            print(f"  {i+1}. {_format_action(action)}")

    # -- Board and state --

    def do_board(self, arg: str) -> None:
        """Render current board as ASCII art."""
        session = self._require_session()
        if session is None:
            return
        rendered = False
        for name, zone in session.runtime.zones.items():
            if isinstance(zone, GridZone):
                print(_render_grid(session, name, zone))
                rendered = True
        for pname, player in session.runtime.players.items():
            for zname, zone in player.zones.items():
                if isinstance(zone, GridZone):
                    print(_render_grid(session, f"{pname}/{zname}", zone))
                    rendered = True
        if not rendered:
            print("(no grid zones)")

    def do_state(self, arg: str) -> None:
        """Dump full state as formatted JSON."""
        session = self._require_session()
        if session is None:
            return
        wire = session.to_wire_state()
        print(json.dumps(wire._to_dict(), indent=2))

    def do_zones(self, arg: str) -> None:
        """List all zones with types and component counts."""
        session = self._require_session()
        if session is None:
            return
        for name, zone in session.runtime.zones.items():
            if isinstance(zone, GridZone):
                occupied = sum(1 for c in zone.cells if c is not None)
                print(f"  {name}: grid {zone.width}x{zone.height} ({occupied}/{zone.width*zone.height} occupied)")
            elif isinstance(zone, StackZone):
                print(f"  {name}: stack ({len(zone.components)} items)")
            elif isinstance(zone, SetZone):
                print(f"  {name}: set ({len(zone.components)} items)")
            else:
                print(f"  {name}: {type(zone).__name__}")
        for pname, player in session.runtime.players.items():
            for zname, zone in player.zones.items():
                if isinstance(zone, GridZone):
                    occupied = sum(1 for c in zone.cells if c is not None)
                    print(f"  {pname}/{zname}: grid {zone.width}x{zone.height} ({occupied}/{zone.width*zone.height} occupied)")

    def do_zone(self, arg: str) -> None:
        """Show contents of a specific zone: zone <name>"""
        session = self._require_session()
        if session is None:
            return
        name = arg.strip()
        if not name:
            print("Usage: zone <name>")
            return
        zone = session.runtime.zones.get(name)
        if zone is None:
            print(f"Unknown zone: {name}")
            return
        if isinstance(zone, GridZone):
            print(_render_grid(session, name, zone))
        else:
            print(f"  {name}: {type(zone).__name__}")

    def do_components(self, arg: str) -> None:
        """List all component instances with positions."""
        session = self._require_session()
        if session is None:
            return
        for cid_val in range(len(session.runtime.components._entries)):
            cid = ComponentId(cid_val)
            comp = session.runtime.components.get(cid)
            if comp is None:
                continue
            pos = _find_component_position(session, cid)
            pos_str = f" at {pos}" if pos else ""
            owner_str = f" ({comp.owner})" if comp.owner else ""
            print(f"  {comp.string_id}: {comp.component_type}{owner_str}{pos_str}")

    def do_counters(self, arg: str) -> None:
        """Show all counter values."""
        session = self._require_session()
        if session is None:
            return
        if not session.runtime.counters:
            print("(no counters)")
            return
        for name, value in session.runtime.counters.items():
            print(f"  {name}: {value}")

    def do_players(self, arg: str) -> None:
        """Show player states."""
        session = self._require_session()
        if session is None:
            return
        current = session.current_player()
        for name in session.runtime.players:
            marker = " <-- current" if name == current else ""
            print(f"  {name}{marker}")

    # -- Moves --

    def do_place(self, arg: str) -> None:
        """Place a component: place <type> <col,row> [zone]"""
        self._do_action_from_parts("place", arg)

    def do_move(self, arg: str) -> None:
        """Move a piece: move <from> <to> [zone]"""
        self._do_action_from_parts("move_piece", arg)

    def do_pass(self, arg: str) -> None:
        """Pass turn."""
        self._apply_action(Action(action_type="pass"))

    def do_resign(self, arg: str) -> None:
        """Resign the game."""
        self._apply_action(Action(action_type="resign"))

    def do_flip(self, arg: str) -> None:
        """Flip a component: flip <id>"""
        cid = arg.strip()
        if not cid:
            print("Usage: flip <component_id>")
            return
        self._apply_action(Action(action_type="flip", component_id=cid))

    def do_remove(self, arg: str) -> None:
        """Remove a component: remove <id>"""
        cid = arg.strip()
        if not cid:
            print("Usage: remove <component_id>")
            return
        self._apply_action(Action(action_type="remove", component_id=cid))

    def do_swap(self, arg: str) -> None:
        """Swap two components: swap <id1> <id2>"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: swap <id1> <id2>")
            return
        self._apply_action(Action(action_type="swap", component_id=parts[0], swap_with=parts[1]))

    def do_promote(self, arg: str) -> None:
        """Promote a component: promote <id> <type>"""
        parts = arg.strip().split()
        if len(parts) < 2:
            print("Usage: promote <id> <type>")
            return
        self._apply_action(Action(action_type="promote", component_id=parts[0], promote_to=parts[1]))

    def do_legal(self, arg: str) -> None:
        """List all legal moves for current player."""
        session = self._require_session()
        if session is None:
            return
        moves = legal_moves(session)
        if not moves:
            print("(no legal moves)")
            return
        for i, m in enumerate(moves):
            print(f"  {i+1}. {_format_action(m.action)}")

    def do_undo(self, arg: str) -> None:
        """Undo last move."""
        if not self.snapshots:
            print("Nothing to undo.")
            return
        self.session = self.snapshots.pop()
        if self.history:
            self.history.pop()
        print("Undone.")

    def _do_action_from_parts(self, action_type: str, arg: str) -> None:
        parts = arg.strip().split()
        if action_type == "place":
            if len(parts) < 2:
                print("Usage: place <type> <col,row> [zone]")
                return
            zone = parts[2] if len(parts) > 2 else "board"
            self._apply_action(Action(
                action_type="place",
                component_type=parts[0],
                to_pos={"zone": zone, "cell": parts[1]},
                zone=zone,
            ))
        elif action_type == "move_piece":
            if len(parts) < 2:
                print("Usage: move <from> <to> [zone]")
                return
            zone = parts[2] if len(parts) > 2 else "board"
            self._apply_action(Action(
                action_type="move_piece",
                from_pos={"zone": zone, "cell": parts[0]},
                to_pos={"zone": zone, "cell": parts[1]},
            ))

    def _apply_action(self, action: Action) -> None:
        session = self._require_session()
        if session is None:
            return
        self._snapshot()
        try:
            events = apply_action(session, action)
            self.history.append(action)
            for ev in events:
                detail = ev.detail or ""
                print(f"  -> {ev.event_type} {detail}".rstrip())
                if ev.event_type == "game_end":
                    session.runtime.status = "finished"
        except Exception as e:
            self.session = self.snapshots.pop()
            print(f"Error: {e}")

    # -- CEL testing --

    def do_cel(self, arg: str) -> None:
        """Evaluate a CEL expression: cel <expression>"""
        session = self._require_session()
        if session is None:
            return
        expr = arg.strip()
        if not expr:
            print("Usage: cel <expression>")
            return
        from baize.cel import try_eval_end_condition
        player = session.current_player() or ""
        variables = _build_end_condition_variables(session, player)
        result = try_eval_end_condition(variables, expr)
        if result is None:
            print(f"  (could not evaluate: {expr})")
        else:
            print(f"  = {result}")

    def do_celctx(self, arg: str) -> None:
        """Show all CEL context variables."""
        session = self._require_session()
        if session is None:
            return
        player = session.current_player() or ""
        variables = _build_end_condition_variables(session, player)
        for k, v in sorted(variables.items()):
            val_str = repr(v)
            if len(val_str) > 120:
                val_str = val_str[:117] + "..."
            print(f"  {k}: {val_str}")

    # -- Perturber testing --

    def do_effect(self, arg: str) -> None:
        """Execute a perturber effect: effect <json>"""
        session = self._require_session()
        if session is None:
            return
        raw = arg.strip()
        if not raw:
            print("Usage: effect <json>")
            return
        try:
            effect = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}")
            return
        self._snapshot()
        try:
            execute_effect(session, effect)
            print("  Effect applied.")
        except Exception as e:
            self.session = self.snapshots.pop()
            print(f"Error: {e}")

    def do_effect_file(self, arg: str) -> None:
        """Load and execute a perturber effect from a file: effect-file <path>"""
        session = self._require_session()
        if session is None:
            return
        path = arg.strip()
        if not path:
            print("Usage: effect-file <path>")
            return
        try:
            effect = json.loads(Path(path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error: {e}")
            return
        self._snapshot()
        try:
            execute_effect(session, effect)
            print("  Effect applied.")
        except Exception as e:
            self.session = self.snapshots.pop()
            print(f"Error: {e}")

    # -- Analysis --

    def do_hash(self, arg: str) -> None:
        """Show current state hash."""
        session = self._require_session()
        if session is None:
            return
        print(f"  {session.compute_state_hash()}")

    def do_hashes(self, arg: str) -> None:
        """Show history hash chain."""
        if not self.snapshots:
            print("(no history)")
            return
        for i, snap in enumerate(self.snapshots):
            print(f"  {i}: {snap.compute_state_hash()}")
        if self.session:
            print(f"  {len(self.snapshots)}: {self.session.compute_state_hash()} (current)")

    def do_moves_for(self, arg: str) -> None:
        """Legal moves for a specific player: moves-for <player>"""
        session = self._require_session()
        if session is None:
            return
        player = arg.strip()
        if not player:
            print("Usage: moves-for <player>")
            return
        saved_idx = session.runtime.turn_index
        players = session.definition.game.players
        if isinstance(players, list) and player in players:
            session.runtime.turn_index = players.index(player)
        moves = legal_moves(session)
        session.runtime.turn_index = saved_idx
        if not moves:
            print(f"(no legal moves for {player})")
            return
        for i, m in enumerate(moves):
            print(f"  {i+1}. {_format_action(m.action)}")

    # -- Scripting --

    def do_run(self, arg: str) -> None:
        """Execute a script of REPL commands: run <path>"""
        path = arg.strip()
        if not path:
            print("Usage: run <path>")
            return
        try:
            lines = Path(path).read_text().splitlines()
        except FileNotFoundError:
            print(f"File not found: {path}")
            return
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            print(f">>> {line}")
            self.onecmd(line)

    def do_save(self, arg: str) -> None:
        """Save current state as JSON: save <path>"""
        session = self._require_session()
        if session is None:
            return
        path = arg.strip()
        if not path:
            print("Usage: save <path>")
            return
        wire = session.to_wire_state()
        Path(path).write_text(json.dumps(wire._to_dict(), indent=2))
        print(f"Saved to {path}")

    # -- Lifecycle --

    def do_quit(self, arg: str) -> bool:
        """Exit the REPL."""
        return True

    do_exit = do_quit
    do_EOF = do_quit

    def emptyline(self) -> None:
        pass

    def default(self, line: str) -> None:
        print(f"Unknown command: {line}  (type 'help' for commands)")


def _find_component_position(
    session: GameSession, target: ComponentId
) -> str | None:
    """Find which zone and position a component is at."""
    for name, zone in session.runtime.zones.items():
        if isinstance(zone, GridZone):
            for row in range(zone.height):
                for col in range(zone.width):
                    if zone.grid_get(col, row) == target:
                        return f"{name}:{col},{row}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baize interactive engine REPL",
        usage="python -m baize.repl [game.json]",
    )
    parser.add_argument("game", nargs="?", help="Game definition JSON file to load on startup")
    args = parser.parse_args()

    repl = BaizeRepl()
    if args.game:
        repl.do_load(args.game)
    repl.cmdloop()


if __name__ == "__main__":
    main()
