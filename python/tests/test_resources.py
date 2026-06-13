import pytest
from pathlib import Path

from baize.definition import GameDefinition, ResourceDef
from baize.resource_store import ResourceStore

REGISTRY_DIR = Path(__file__).parent.parent.parent  # project root

class TestResourceDef:
    def test_from_dict(self):
        d = {"type": "word_list", "name": "twl06"}
        r = ResourceDef.from_dict(d)
        assert r.resource_type == "word_list"
        assert r.name == "twl06"
        assert r.note is None

    def test_from_dict_with_note(self):
        d = {"type": "word_list", "name": "twl06", "note": "Official tournament list"}
        r = ResourceDef.from_dict(d)
        assert r.note == "Official tournament list"

    def test_to_dict_roundtrip(self):
        d = {"type": "word_list", "name": "twl06"}
        r = ResourceDef.from_dict(d)
        assert r.to_dict() == d

    def test_game_def_with_resources(self):
        """Game definition with resources section parses correctly."""
        json_str = open(REGISTRY_DIR / "games" / "scrabble.json").read()
        defn = GameDefinition.from_json(json_str)
        assert "dictionary" in defn.resources
        assert defn.resources["dictionary"].resource_type == "word_list"

    def test_game_def_without_resources(self):
        """Game definition without resources section still works."""
        json_str = open(REGISTRY_DIR / "games" / "tic-tac-toe.json").read()
        defn = GameDefinition.from_json(json_str)
        assert defn.resources == {}

class TestResourceStore:
    def test_load_word_list(self):
        resources = {"dict": ResourceDef("word_list", "test-wordlist")}
        store = ResourceStore.load(resources, REGISTRY_DIR)
        assert store.word_valid("dict", "CAT")
        assert store.word_valid("dict", "cat")  # case insensitive
        assert store.word_valid("dict", "Dog")
        assert not store.word_valid("dict", "XYZZY")

    def test_word_valid_unknown_resource(self):
        store = ResourceStore.empty()
        with pytest.raises(Exception, match="not loaded"):
            store.word_valid("nonexistent", "CAT")

    def test_missing_file(self):
        resources = {"dict": ResourceDef("word_list", "nonexistent-file")}
        with pytest.raises(Exception, match="not found"):
            ResourceStore.load(resources, REGISTRY_DIR)

    def test_unknown_resource_type(self):
        resources = {"x": ResourceDef("unknown_type", "foo")}
        with pytest.raises(Exception, match="unknown resource type"):
            ResourceStore.load(resources, REGISTRY_DIR)

    def test_empty_store(self):
        store = ResourceStore.empty()
        assert isinstance(store, ResourceStore)

    def test_word_list_has_expected_count(self):
        resources = {"dict": ResourceDef("word_list", "test-wordlist")}
        store = ResourceStore.load(resources, REGISTRY_DIR)
        # Should have ~100 words
        assert store.word_valid("dict", "ABOUT")
        assert store.word_valid("dict", "WRITE")
        assert not store.word_valid("dict", "")

class TestSchemaValidation:
    def test_scrabble_with_resources_validates(self):
        import json
        from jsonschema import validate
        schema = json.load(open(REGISTRY_DIR / "schema" / "game-definition.schema.json"))
        game = json.load(open(REGISTRY_DIR / "games" / "scrabble.json"))
        validate(game, schema)  # Should not raise
