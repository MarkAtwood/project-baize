"""Human-readable move notation adapter.

Parses text like "e4", "Nf3", "O-O" into Action objects
and formats Action objects back into human-readable text.

Two layers:
  Layer 1: Grid label coordinate mapping (automatic from game definition labels)
  Layer 2: Declarative notation spec (piece symbols, disambiguation, special moves)
"""

from __future__ import annotations

from typing import Any

from baize.action import Action
from baize.definition import GameDefinition, GridLabels


def coords_to_label(col: int, row: int, labels: GridLabels | None) -> str:
    """Convert (col, row) to label string like 'e4'."""
    if labels is None:
        return f"{col},{row}"
    file_str = labels.files[col] if labels.files and col < len(labels.files) else str(col)
    rank_val = labels.ranks[row] if labels.ranks and row < len(labels.ranks) else str(row)
    return f"{file_str}{rank_val}"


def label_to_coords(text: str, labels: GridLabels | None) -> tuple[int, int] | None:
    """Parse a label string like 'e4' to (col, row). Returns None if invalid."""
    if labels is None:
        parts = text.split(",")
        if len(parts) == 2:
            try:
                return (int(parts[0]), int(parts[1]))
            except ValueError:
                return None
        return None

    if labels.files:
        for col, file_name in enumerate(labels.files):
            if text.startswith(file_name):
                rank_part = text[len(file_name):]
                if labels.ranks:
                    for row, rank_val in enumerate(labels.ranks):
                        if str(rank_val) == rank_part:
                            return (col, row)
    return None


def parse_special_move(
    text: str, notation: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Check if text matches a special move. Returns action dict or None."""
    if notation is None:
        return None
    specials = notation.get("special_moves", {})
    return specials.get(text)


def parse_move(
    text: str, definition: GameDefinition, zone_name: str = "board"
) -> Action | None:
    """Parse human-readable notation into an Action.

    Tries in order:
    1. Special moves (O-O, pass, resign, U, R', etc.)
    2. Piece-symbol notation (Nf3, Bxe5, e4)
    3. Plain coordinate (e4, a1, D4)
    """
    text = text.strip()
    notation = definition.notation

    # 1. Special moves
    special = parse_special_move(text, notation)
    if special is not None:
        return Action(**special)

    # Get labels from zone
    zone_def = definition.zones.get(zone_name)
    labels = zone_def.labels if zone_def else None

    # Strip check/checkmate markers for parsing
    clean = text
    if notation:
        for marker_key in ("checkmate_marker", "check_marker"):
            marker = notation.get(marker_key, "")
            if marker and clean.endswith(marker):
                clean = clean[: -len(marker)]

    # 2. Piece-symbol notation
    if notation and "piece_symbols" in notation:
        result = _parse_piece_notation(clean, notation, labels)
        if result is not None:
            return result

    # 3. Plain coordinate (placement)
    coords = label_to_coords(clean, labels)
    if coords is not None:
        col, row = coords
        return Action(
            action_type="place",
            zone=zone_name,
            to_pos={"col": col, "row": row},
        )

    return None


def _parse_piece_notation(
    text: str, notation: dict[str, Any], labels: GridLabels | None
) -> Action | None:
    """Parse piece-symbol notation like Nf3, Bxe5, exd5, e8=Q."""
    symbols = notation.get("piece_symbols", {})
    capture_marker = notation.get("capture_marker", "x")
    promotion_marker = notation.get("promotion_marker", "=")

    # Reverse map: symbol -> piece_type
    symbol_to_type = {v: k for k, v in symbols.items()}

    remaining = text
    piece_type = None

    # Check for piece symbol prefix (uppercase letter in symbol map)
    if remaining and remaining[0].isupper() and remaining[0] in symbol_to_type:
        piece_type = symbol_to_type[remaining[0]]
        remaining = remaining[1:]
    else:
        # Might be a pawn (empty symbol)
        if "" in symbol_to_type:
            piece_type = symbol_to_type[""]

    # Handle promotion suffix (e.g., =Q)
    promote_to = None
    if promotion_marker and promotion_marker in remaining:
        idx = remaining.index(promotion_marker)
        promo_str = remaining[idx + len(promotion_marker) :]
        if promo_str in symbol_to_type:
            promote_to = symbol_to_type[promo_str]
        remaining = remaining[:idx]

    # Remove capture marker
    is_capture = False
    if capture_marker and capture_marker in remaining:
        is_capture = True
        remaining = remaining.replace(capture_marker, "", 1)

    # Parse destination: find longest suffix that is a valid coordinate
    dest = None
    disambig = ""
    if labels and labels.files:
        for i in range(len(remaining)):
            candidate = remaining[i:]
            coords = label_to_coords(candidate, labels)
            if coords is not None:
                dest = coords
                disambig = remaining[:i]
                break

    if dest is None:
        return None

    col, row = dest
    custom: dict[str, Any] = {}
    if disambig:
        custom["disambiguation"] = disambig
    if is_capture:
        custom["capture"] = True

    return Action(
        action_type="move_piece",
        zone="board",
        to_pos={"col": col, "row": row},
        component_type=piece_type,
        promote_to=promote_to,
        custom_data=custom if custom else None,
    )


def format_move(
    action: Action, definition: GameDefinition, zone_name: str = "board"
) -> str:
    """Format an Action into human-readable notation."""
    notation = definition.notation

    # Check special moves (reverse lookup)
    if notation:
        specials = notation.get("special_moves", {})
        for text, action_dict in specials.items():
            if _action_matches_special(action, action_dict):
                return text

    zone_def = definition.zones.get(zone_name)
    labels = zone_def.labels if zone_def else None

    pos = action.to_pos
    if pos is None:
        return str(action)

    dest = coords_to_label(pos.get("col", 0), pos.get("row", 0), labels)

    if notation and "piece_symbols" in notation:
        symbols = notation.get("piece_symbols", {})
        capture_marker = notation.get("capture_marker", "")
        promotion_marker = notation.get("promotion_marker", "")

        parts: list[str] = []
        piece_sym = symbols.get(action.component_type or "", "")
        parts.append(piece_sym)

        cd = action.custom_data or {}
        if cd.get("disambiguation"):
            parts.append(cd["disambiguation"])
        if cd.get("capture") and capture_marker:
            parts.append(capture_marker)
        parts.append(dest)
        if action.promote_to and promotion_marker:
            parts.append(promotion_marker)
            parts.append(symbols.get(action.promote_to, action.promote_to))
        return "".join(parts)

    return dest


def _action_matches_special(action: Action, action_dict: dict[str, Any]) -> bool:
    """Check if an action matches a special move dict."""
    for key, val in action_dict.items():
        if getattr(action, key, None) != val:
            return False
    return True
