"""Jupyter notebook integration for Baize.

Provides visual board display (SVG), interactive game widgets, and
ASCII art formatting for terminal use. All IPython/Jupyter imports are
guarded so this module works without Jupyter installed.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from baize.definition import GameDefinition
from baize.moves import LegalMove, legal_moves
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    GridZone,
    RuntimeZone,
    SetZone,
    SlotZone,
    StackZone,
    TrackZone,
)
from baize.state import (
    ComponentInstance,
    CounterState,
    GridState,
    SetState,
    SlotState,
    StackState,
    TrackState,
    ZoneState,
)


# ---------------------------------------------------------------------------
# SVG rendering helpers
# ---------------------------------------------------------------------------

_CELL_SIZE = 48
_FONT_SIZE = 18
_HEADER_SIZE = 14
_MARGIN = 24  # space for labels
_COLORS = {
    "light": "#f0d9b5",
    "dark": "#b58863",
    "stroke": "#333333",
    "text": "#1a1a1a",
    "text_light": "#ffffff",
}


def _escape_xml(text: str) -> str:
    """Escape text for safe embedding in XML/SVG."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _component_glyph(comp: ComponentData) -> str:
    """Derive a short display glyph from a component."""
    # Use first letter of component_type, uppercased for one player,
    # lowercased for the other to distinguish sides.
    letter = comp.component_type[0].upper() if comp.component_type else "?"
    return letter


def _render_grid_svg(
    zone: GridZone,
    session: GameSession,
    zone_name: str,
) -> str:
    """Render a GridZone as an SVG string."""
    w = zone.width
    h = zone.height
    cell = _CELL_SIZE
    margin = _MARGIN

    # Look up labels from the definition
    zone_def = session.definition.zones.get(zone_name)
    has_labels = zone_def is not None and zone_def.labels is not None
    file_labels: list[str] | None = None
    rank_labels: list[str | int] | None = None
    if has_labels and zone_def is not None and zone_def.labels is not None:
        file_labels = zone_def.labels.files
        rank_labels = zone_def.labels.ranks

    svg_w = w * cell + margin * 2
    svg_h = h * cell + margin * 2

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}" '
        f'viewBox="0 0 {svg_w} {svg_h}">'
    )
    parts.append(
        f'<rect x="0" y="0" width="{svg_w}" height="{svg_h}" '
        f'fill="#fafafa" />'
    )

    # Determine coloring scheme
    use_checker = zone_def is not None and zone_def.coloring == "checkered"

    # Draw cells
    for row in range(h):
        for col in range(w):
            x = margin + col * cell
            y = margin + row * cell

            if use_checker:
                fill = (
                    _COLORS["light"]
                    if (row + col) % 2 == 0
                    else _COLORS["dark"]
                )
            else:
                fill = "#ffffff"

            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                f'fill="{fill}" stroke="{_COLORS["stroke"]}" '
                f'stroke-width="1" />'
            )

            # Draw component if present
            cid = zone.cells[row * w + col]
            if cid is not None:
                comp = session.runtime.components.get(cid)
                if comp is not None:
                    glyph = _component_glyph(comp)
                    # Use different text color on dark squares
                    text_color = (
                        _COLORS["text_light"]
                        if use_checker and (row + col) % 2 != 0
                        else _COLORS["text"]
                    )
                    tx = x + cell // 2
                    ty = y + cell // 2 + _FONT_SIZE // 3
                    parts.append(
                        f'<text x="{tx}" y="{ty}" '
                        f'font-family="monospace" font-size="{_FONT_SIZE}" '
                        f'fill="{text_color}" '
                        f'text-anchor="middle">'
                        f'{_escape_xml(glyph)}</text>'
                    )

    # Draw file labels (column headers)
    if file_labels:
        for col, label in enumerate(file_labels[:w]):
            tx = margin + col * cell + cell // 2
            # Top
            parts.append(
                f'<text x="{tx}" y="{margin - 6}" '
                f'font-family="sans-serif" font-size="{_HEADER_SIZE}" '
                f'fill="{_COLORS["text"]}" '
                f'text-anchor="middle">{_escape_xml(str(label))}</text>'
            )

    # Draw rank labels (row headers)
    if rank_labels:
        for row, label in enumerate(rank_labels[:h]):
            ty = margin + row * cell + cell // 2 + _HEADER_SIZE // 3
            # Left
            parts.append(
                f'<text x="{margin - 6}" y="{ty}" '
                f'font-family="sans-serif" font-size="{_HEADER_SIZE}" '
                f'fill="{_COLORS["text"]}" '
                f'text-anchor="end">{_escape_xml(str(label))}</text>'
            )

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# format_state  (ASCII art)
# ---------------------------------------------------------------------------


def _format_grid_ascii(
    zone: GridZone,
    session: GameSession,
    zone_name: str,
) -> str:
    """Render a GridZone as ASCII art."""
    w = zone.width
    h = zone.height

    zone_def = session.definition.zones.get(zone_name)
    file_labels: list[str] | None = None
    rank_labels: list[str | int] | None = None
    if zone_def is not None and zone_def.labels is not None:
        file_labels = zone_def.labels.files
        rank_labels = zone_def.labels.ranks

    # Build cell contents: 3-char wide per cell
    cell_width = 3
    lines: list[str] = []

    # Column header
    if file_labels:
        header = "   " + "".join(str(f).center(cell_width + 1) for f in file_labels[:w])
        lines.append(header)

    sep = "   " + ("+" + "-" * cell_width) * w + "+"

    for row in range(h):
        lines.append(sep)
        row_cells: list[str] = []
        for col in range(w):
            cid = zone.cells[row * w + col]
            if cid is not None:
                comp = session.runtime.components.get(cid)
                if comp is not None:
                    # Show owner initial + type initial, e.g. "wK" for white King
                    owner_ch = comp.owner[0] if comp.owner else " "
                    type_ch = comp.component_type[0].upper() if comp.component_type else "?"
                    cell_str = f"{owner_ch}{type_ch}"
                else:
                    cell_str = "??"
            else:
                cell_str = "  "
            row_cells.append(cell_str.center(cell_width))

        rank_label = ""
        if rank_labels and row < len(rank_labels):
            rank_label = str(rank_labels[row]).rjust(2) + " "
        else:
            rank_label = str(row).rjust(2) + " "

        lines.append(rank_label + "|" + "|".join(row_cells) + "|")

    lines.append(sep)
    return "\n".join(lines)


def _format_stack_ascii(
    zone: StackZone,
    session: GameSession,
) -> str:
    """Render a StackZone as ASCII."""
    if not zone.components:
        return "  (empty)"
    items: list[str] = []
    for cid in zone.components:
        comp = session.runtime.components.get(cid)
        if comp is not None:
            items.append(f"  {comp.string_id} ({comp.component_type})")
        else:
            items.append("  ???")
    return "\n".join(["  [top]"] + list(reversed(items)) + ["  [bottom]"])


def _format_set_ascii(
    zone: SetZone,
    session: GameSession,
) -> str:
    """Render a SetZone as ASCII."""
    if not zone.components:
        return "  (empty)"
    items: list[str] = []
    for cid in zone.components:
        comp = session.runtime.components.get(cid)
        if comp is not None:
            items.append(f"  {comp.string_id} ({comp.component_type})")
        else:
            items.append("  ???")
    return "\n".join(items)


def _format_slot_ascii(
    zone: SlotZone,
    session: GameSession,
) -> str:
    """Render a SlotZone as ASCII."""
    if zone.component is None:
        return "  (empty)"
    comp = session.runtime.components.get(zone.component)
    if comp is not None:
        return f"  {comp.string_id} ({comp.component_type})"
    return "  ???"


def _format_counter_ascii(zone: CounterZone) -> str:
    """Render a CounterZone as ASCII."""
    return f"  value: {zone.value}"


def _format_track_ascii(
    zone: TrackZone,
    session: GameSession,
) -> str:
    """Render a TrackZone as ASCII."""
    parts: list[str] = []
    for i, pos in enumerate(zone.positions):
        if pos:
            names = []
            for cid in pos:
                comp = session.runtime.components.get(cid)
                if comp is not None:
                    names.append(comp.string_id)
                else:
                    names.append("???")
            parts.append(f"  [{i}]: {', '.join(names)}")
        else:
            parts.append(f"  [{i}]: ---")
    return "\n".join(parts) if parts else "  (empty track)"


def _format_zone_ascii(
    zone: RuntimeZone,
    session: GameSession,
    zone_name: str,
) -> str:
    """Render any RuntimeZone as ASCII."""
    if isinstance(zone, GridZone):
        return _format_grid_ascii(zone, session, zone_name)
    if isinstance(zone, StackZone):
        return _format_stack_ascii(zone, session)
    if isinstance(zone, SetZone):
        return _format_set_ascii(zone, session)
    if isinstance(zone, SlotZone):
        return _format_slot_ascii(zone, session)
    if isinstance(zone, CounterZone):
        return _format_counter_ascii(zone)
    if isinstance(zone, TrackZone):
        return _format_track_ascii(zone, session)
    return "  (unknown zone type)"


def format_state(session: GameSession) -> str:
    """Render the current game state as ASCII art.

    Works in any terminal -- no Jupyter dependency. Shows all zones,
    player info, current turn, and game status.
    """
    parts: list[str] = []
    game_name = session.definition.game.name
    status = session.runtime.status
    current = session.current_player() or "(none)"
    move_num = session.runtime.move_count

    parts.append(f"=== {game_name} ===")
    parts.append(f"Status: {status}  |  Turn: {current}  |  Move: {move_num}")
    parts.append("")

    # Global zones
    for name, zone in session.runtime.zones.items():
        parts.append(f"[{name}]")
        parts.append(_format_zone_ascii(zone, session, name))
        parts.append("")

    # Player zones and info
    for pname, player in session.runtime.players.items():
        active = "active" if player.active else "inactive"
        parts.append(f"Player: {pname} ({active}, score: {player.score})")
        if player.counters:
            counters_str = ", ".join(
                f"{k}={v}" for k, v in player.counters.items()
            )
            parts.append(f"  Counters: {counters_str}")
        for zname, zone in player.zones.items():
            parts.append(f"  [{zname}]")
            zone_text = _format_zone_ascii(zone, session, zname)
            # Indent the zone text further
            indented = "\n".join(
                "  " + line for line in zone_text.split("\n")
            )
            parts.append(indented)
        parts.append("")

    return "\n".join(parts).rstrip()


# ---------------------------------------------------------------------------
# display_board  (SVG)
# ---------------------------------------------------------------------------


class BoardSVG:
    """Wrapper that holds SVG markup and implements the Jupyter display protocol."""

    def __init__(self, svg: str) -> None:
        self._svg = svg

    def _repr_svg_(self) -> str:
        return self._svg

    def __str__(self) -> str:
        return self._svg

    def __repr__(self) -> str:
        return f"BoardSVG({len(self._svg)} bytes)"


def display_board(session: GameSession) -> BoardSVG:
    """Render the current board state as inline SVG for Jupyter display.

    For grid zones, draws an SVG with cells and piece glyphs. Returns a
    ``BoardSVG`` object that implements ``_repr_svg_()`` for automatic
    Jupyter rendering.

    If no grid zones exist, renders a text summary as SVG.
    """
    # Find all grid zones and render them
    svg_parts: list[str] = []

    for name, zone in session.runtime.zones.items():
        if isinstance(zone, GridZone):
            svg_parts.append(_render_grid_svg(zone, session, name))

    # Also check player zones for grids
    for _pname, player in session.runtime.players.items():
        for zname, zone in player.zones.items():
            if isinstance(zone, GridZone):
                svg_parts.append(_render_grid_svg(zone, session, zname))

    if svg_parts:
        # If multiple grids, combine them (use the first for now)
        svg = svg_parts[0]
    else:
        # Fallback: render a text summary as SVG
        text = format_state(session)
        lines = text.split("\n")
        line_h = 18
        svg_h = len(lines) * line_h + 20
        svg_w = max((len(line) for line in lines), default=40) * 8 + 20
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{svg_w}" height="{svg_h}" '
            f'viewBox="0 0 {svg_w} {svg_h}">',
        ]
        for i, line in enumerate(lines):
            y = 16 + i * line_h
            parts.append(
                f'<text x="10" y="{y}" '
                f'font-family="monospace" font-size="14" '
                f'fill="#333333">{_escape_xml(line)}</text>'
            )
        parts.append("</svg>")
        svg = "\n".join(parts)

    return BoardSVG(svg)


# ---------------------------------------------------------------------------
# GameWidget
# ---------------------------------------------------------------------------


class GameWidget:
    """Simple interactive game player for Jupyter notebooks.

    Loads a game definition, creates a session, and provides methods for
    display, move execution, and undo.
    """

    def __init__(self, definition_path: str) -> None:
        """Load a game definition from a JSON file and create a session.

        Args:
            definition_path: Path to a game definition JSON file.
        """
        with open(definition_path) as f:
            json_str = f.read()
        self._definition = GameDefinition.from_json(json_str)
        self._session = GameSession(self._definition)
        self._session.runtime.status = "in_progress"
        self._history: list[GameSession] = []

    @property
    def session(self) -> GameSession:
        """The underlying GameSession."""
        return self._session

    def show(self) -> BoardSVG:
        """Display the board with SVG.

        Returns a ``BoardSVG`` that auto-renders in Jupyter.
        """
        return display_board(self._session)

    def move(self, action_dict: dict[str, Any]) -> None:
        """Apply an action and redisplay.

        The action_dict should contain at minimum the fields needed to
        identify and execute a move. For grid-based games, a typical
        action_dict looks like::

            {"component": "piece_id", "from": [col, row], "to": [col, row]}

        This saves the current state to the history stack before applying.

        Args:
            action_dict: Dictionary describing the action to apply.
        """
        # Save state for undo
        self._history.append(copy.deepcopy(self._session))

        # Interpret the action
        comp_id_str = action_dict.get("component")
        from_pos = action_dict.get("from")
        to_pos = action_dict.get("to")

        if from_pos is not None and to_pos is not None:
            # Grid move: find the component and move it
            for _zname, zone in self._session.runtime.zones.items():
                if isinstance(zone, GridZone):
                    from_col, from_row = from_pos[0], from_pos[1]
                    to_col, to_row = to_pos[0], to_pos[1]

                    cid = zone.grid_get(from_col, from_row)
                    if cid is not None:
                        comp = self._session.runtime.components.get(cid)
                        if comp is not None:
                            if comp_id_str is None or comp.string_id == comp_id_str:
                                zone.grid_set(from_col, from_row, None)
                                zone.grid_set(to_col, to_row, cid)
                                self._session.advance_turn()
                                return

        # Place action: place a new component
        place_pos = action_dict.get("place")
        comp_type = action_dict.get("type", "mark")
        if place_pos is not None:
            owner = self._session.current_player() or ""
            comp_count = len(self._session.runtime.components)
            cid = self._session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"{comp_type}-{owner}-{comp_count}",
                    component_type=comp_type,
                    owner=owner,
                )
            )
            for _zname, zone in self._session.runtime.zones.items():
                if isinstance(zone, GridZone):
                    zone.grid_set(place_pos[0], place_pos[1], cid)
                    self._session.advance_turn()
                    return

    def legal_moves(self) -> list[LegalMove]:
        """Show legal moves for the current player.

        Returns:
            List of ``LegalMove`` objects.
        """
        return legal_moves(self._session)

    def undo(self) -> None:
        """Go back one state using the history stack.

        Raises:
            IndexError: If there is no history to undo.
        """
        if not self._history:
            raise IndexError("no history to undo")
        self._session = self._history.pop()

    def _repr_html_(self) -> str:
        """Auto-display in Jupyter as HTML containing the board SVG."""
        svg = display_board(self._session)
        game_name = _escape_xml(self._session.definition.game.name)
        current = _escape_xml(self._session.current_player() or "(none)")
        status = _escape_xml(self._session.runtime.status)
        move_count = self._session.runtime.move_count

        return (
            f'<div style="font-family: sans-serif; padding: 8px;">'
            f'<h3 style="margin: 0 0 8px 0;">{game_name}</h3>'
            f'<p style="margin: 0 0 8px 0; color: #666;">'
            f'Status: {status} | Turn: {current} | Move: {move_count}</p>'
            f'{svg._repr_svg_()}'
            f'</div>'
        )
