"""Serialization round-trip integrity tests.

Verify: parse -> serialize -> parse -> serialize produces identical output
for all game definitions in games/*.json.

The first parse may normalize the data (e.g. dropping defaults). The invariant
is that the second round-trip is identical to the first — i.e. the
from_dict/to_dict cycle is idempotent once the data has passed through the
typed model.
"""

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition

GAMES_DIR = Path(__file__).resolve().parent.parent.parent / "games"

GAME_FILES = sorted(GAMES_DIR.glob("*.json"))


@pytest.fixture(params=GAME_FILES, ids=[f.stem for f in GAME_FILES])
def game_json(request: pytest.FixtureRequest) -> tuple[str, str]:
    """Return (game_name, raw_json_string) for each game file."""
    path: Path = request.param
    return path.stem, path.read_text(encoding="utf-8")


def test_game_files_found() -> None:
    """Sanity check: we found at least one game JSON file."""
    assert len(GAME_FILES) > 0, f"no game JSON files found in {GAMES_DIR}"


def test_definition_dict_roundtrip(game_json: tuple[str, str]) -> None:
    """parse -> to_dict -> parse -> to_dict produces identical dicts."""
    name, raw_json = game_json

    # First pass: raw JSON -> GameDefinition -> dict
    def1 = GameDefinition.from_json(raw_json, validate_schema=False)
    dict1 = def1._to_dict()

    # Second pass: dict -> GameDefinition -> dict
    def2 = GameDefinition._from_dict(dict1)
    dict2 = def2._to_dict()

    assert dict1 == dict2, (
        f"[{name}] dict round-trip not identical.\n"
        f"Keys only in first: {set(dict1) - set(dict2)}\n"
        f"Keys only in second: {set(dict2) - set(dict1)}"
    )


def test_definition_json_string_roundtrip(game_json: tuple[str, str]) -> None:
    """parse -> to_dict -> JSON string -> parse -> to_dict -> JSON string is identical."""
    name, raw_json = game_json

    # First pass
    def1 = GameDefinition.from_json(raw_json, validate_schema=False)
    dict1 = def1._to_dict()
    json1 = json.dumps(dict1, sort_keys=True, ensure_ascii=False)

    # Second pass
    reparsed = json.loads(json1)
    def2 = GameDefinition._from_dict(reparsed)
    dict2 = def2._to_dict()
    json2 = json.dumps(dict2, sort_keys=True, ensure_ascii=False)

    assert json1 == json2, (
        f"[{name}] JSON string round-trip not bitwise identical.\n"
        f"len(json1)={len(json1)}, len(json2)={len(json2)}"
    )


def test_definition_to_json_method_roundtrip(game_json: tuple[str, str]) -> None:
    """to_json() -> from_json() -> to_json() produces identical output."""
    name, raw_json = game_json

    # First pass
    def1 = GameDefinition.from_json(raw_json, validate_schema=False)
    serialized1 = def1.to_json(indent=None)

    # Second pass
    def2 = GameDefinition.from_json(serialized1, validate_schema=False)
    serialized2 = def2.to_json(indent=None)

    assert serialized1 == serialized2, (
        f"[{name}] to_json() round-trip not identical"
    )
