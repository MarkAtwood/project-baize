"""Tests for JSON Schema validation of game definitions."""

from __future__ import annotations

import pytest

from baize.definition import GameDefinition
from baize.error import ParseError


TIC_TAC_TOE_JSON = """{
    "game": { "name": "Tic-Tac-Toe", "players": ["X", "O"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
    "end_conditions": [
        { "result": "win", "player": "current", "condition": "three_in_line" },
        { "result": "draw", "condition": "board_is_full" }
    ],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def test_valid_definition_passes_schema():
    """A well-formed game definition passes schema validation."""
    defn = GameDefinition.from_json(TIC_TAC_TOE_JSON)
    assert defn.game.name == "Tic-Tac-Toe"


def test_missing_required_field_fails_schema():
    """A definition missing a required field is rejected by schema validation."""
    bad_json = '{"game": {"name": "X", "players": ["A"]}, "zones": {}}'
    with pytest.raises(ParseError, match="schema validation"):
        GameDefinition.from_json(bad_json)


def test_invalid_zone_type_fails_schema():
    """An unknown zone_type is rejected by schema validation."""
    import json

    raw = json.loads(TIC_TAC_TOE_JSON)
    raw["zones"]["board"]["zone_type"] = "wormhole"
    with pytest.raises(ParseError, match="schema validation"):
        GameDefinition.from_json(json.dumps(raw))


def test_extra_top_level_key_fails_schema():
    """additionalProperties: false rejects unknown top-level keys."""
    import json

    raw = json.loads(TIC_TAC_TOE_JSON)
    raw["hacks"] = True
    with pytest.raises(ParseError, match="schema validation"):
        GameDefinition.from_json(json.dumps(raw))


def test_skip_schema_validation():
    """validate_schema=False skips schema checks."""
    bad_json = '{"game": {"name": "X", "players": ["A"]}, "zones": {}}'
    with pytest.raises(ParseError):
        # This should fail in _from_dict, not schema validation
        GameDefinition.from_json(bad_json, validate_schema=False)
