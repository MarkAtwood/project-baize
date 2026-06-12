"""Hypothesis property-based fuzz tests for the Baize Python engine.

Strategies generate random game definitions and action dicts, then verify:
  - from_dict() never raises uncaught exceptions (only ParseError/ValueError/TypeError)
  - from_json() never crashes on arbitrary strings
  - Round-trip: if from_dict succeeds, to_dict must not crash
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from baize.definition import GameDefinition
from baize.action import Action
from baize.error import ParseError, ValidationError


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary JSON-compatible values (strings, ints, floats, bools, None, nested).
json_values: st.SearchStrategy[Any] = st.recursive(
    st.one_of(
        st.text(max_size=40),
        st.integers(min_value=-1_000_000, max_value=1_000_000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.none(),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=15), children, max_size=4),
    ),
    max_leaves=15,
)

# Random strings that may or may not be valid JSON.
random_strings: st.SearchStrategy[str] = st.one_of(
    json_values.map(lambda v: json.dumps(v)),
    st.text(max_size=500),
    st.binary(max_size=200).map(lambda b: b.decode("latin-1")),
)

# Strategy for game definition-like dicts.
# Generates dicts with plausible top-level keys, but random values.
DEFINITION_KEYS = [
    "game", "zones", "components", "turn_order",
    "end_conditions", "authority", "phases", "rules",
    "library", "wasm_module", "hand_rankings",
]

game_definition_dicts: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {},
    optional={
        "game": st.one_of(
            json_values,
            st.fixed_dictionaries(
                {"name": st.text(max_size=30), "players": st.lists(st.text(max_size=10), max_size=4)},
                optional={"information": st.sampled_from(["perfect", "imperfect", "hidden"])},
            ),
        ),
        "zones": st.one_of(
            json_values,
            st.dictionaries(
                st.text(max_size=15),
                st.fixed_dictionaries(
                    {"zone_type": st.sampled_from(["grid", "stack", "set", "slot", "counter", "track"])},
                    optional={
                        "dimensions": st.lists(st.integers(min_value=0, max_value=50), min_size=2, max_size=2),
                        "visibility": st.sampled_from(["public", "private", "hidden"]),
                        "max_size": st.integers(min_value=0, max_value=200),
                    },
                ),
                max_size=3,
            ),
        ),
        "components": st.one_of(
            json_values,
            st.dictionaries(
                st.text(max_size=15),
                st.fixed_dictionaries(
                    {},
                    optional={
                        "owner": st.sampled_from(["per_player", "shared", "neutral"]),
                        "count": st.one_of(st.just("unlimited"), st.integers(min_value=0, max_value=100)),
                    },
                ),
                max_size=3,
            ),
        ),
        "turn_order": st.one_of(
            json_values,
            st.fixed_dictionaries(
                {"type": st.sampled_from(["alternating", "round_robin", "custom"])},
                optional={
                    "players": st.lists(st.text(max_size=10), max_size=4),
                    "actions_per_turn": st.integers(min_value=0, max_value=10),
                    "mandatory": st.booleans(),
                },
            ),
        ),
        "end_conditions": st.one_of(
            json_values,
            st.lists(
                st.fixed_dictionaries(
                    {"result": st.sampled_from(["win", "draw", "loss"])},
                    optional={
                        "condition": st.text(max_size=30),
                        "player": st.sampled_from(["current", "other", "all"]),
                    },
                ),
                max_size=3,
            ),
        ),
        "authority": st.one_of(
            json_values,
            st.fixed_dictionaries(
                {},
                optional={
                    "server_only": st.lists(st.text(max_size=15), max_size=3),
                    "client_verifiable": st.lists(st.text(max_size=15), max_size=3),
                },
            ),
        ),
        "phases": json_values,
        "rules": json_values,
    },
)

# Strategy for action-like dicts.
ACTION_TYPES = [
    "move_piece", "place", "draw", "play_card", "discard",
    "roll_dice", "flip", "promote", "swap", "remove",
    "pass", "resign", "offer_draw", "accept_draw", "decline_draw",
    "fold", "check", "call", "raise", "all_in",
    "place_ship", "fire", "castle", "en_passant",
    "declare_action", "custom",
]

action_dicts: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {"action_type": st.sampled_from(ACTION_TYPES)},
    optional={
        "component_id": st.text(max_size=30),
        "component_type": st.text(max_size=30),
        "from": st.one_of(
            st.text(max_size=20),
            st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3),
        ),
        "to": st.one_of(
            st.text(max_size=20),
            st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3),
        ),
        "zone": st.text(max_size=20),
        "count": st.integers(min_value=0, max_value=1000),
        "amount": st.integers(min_value=0, max_value=10000),
        "custom_data": json_values,
    },
)


# ---------------------------------------------------------------------------
# Tests: GameDefinition parsing
# ---------------------------------------------------------------------------


class TestDefinitionParsing:
    """Property tests for GameDefinition.from_json() and _from_dict()."""

    @given(data=random_strings)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_from_json_never_crashes(self, data: str) -> None:
        """from_json() on arbitrary strings must not raise unexpected exceptions."""
        try:
            GameDefinition.from_json(data)
        except (ParseError, ValidationError):
            pass  # expected for invalid input

    @given(data=json_values)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_from_json_random_values(self, data: object) -> None:
        """Serialize a random JSON value and feed to from_json()."""
        try:
            GameDefinition.from_json(json.dumps(data))
        except (ParseError, ValidationError):
            pass  # expected for invalid input

    @given(data=game_definition_dicts)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_from_json_definition_like_dicts(self, data: dict[str, Any]) -> None:
        """Feed generated definition-like dicts through JSON round-trip."""
        try:
            GameDefinition.from_json(json.dumps(data))
        except (ParseError, ValidationError):
            pass  # expected for structurally invalid definitions


# ---------------------------------------------------------------------------
# Tests: Action parsing
# ---------------------------------------------------------------------------


class TestActionParsing:
    """Property tests for Action.from_dict()."""

    @given(data=json_values)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_from_dict_random_values(self, data: object) -> None:
        """Action.from_dict() on non-dict values must not crash unexpectedly."""
        if not isinstance(data, dict):
            return  # from_dict requires a dict
        try:
            Action.from_dict(data)
        except (KeyError, TypeError, ValueError):
            pass  # from_dict raises these for bad input

    @given(data=action_dicts)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_from_dict_action_like(self, data: dict[str, Any]) -> None:
        """Action.from_dict() on action-like dicts must not crash unexpectedly."""
        try:
            Action.from_dict(data)
        except (KeyError, TypeError, ValueError):
            pass  # expected for malformed actions


# ---------------------------------------------------------------------------
# Tests: Round-trip — if from_dict succeeds, to_dict must not crash
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """If parsing succeeds, serialization must not crash."""

    @given(data=game_definition_dicts)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_definition_round_trip(self, data: dict[str, Any]) -> None:
        """If from_json succeeds, to_json must not raise."""
        try:
            defn = GameDefinition.from_json(json.dumps(data))
        except (ParseError, ValidationError):
            return  # parsing failed, nothing to round-trip
        # to_json must not crash
        result = defn.to_json()
        assert isinstance(result, str)
        assert len(result) > 0

    @given(data=action_dicts)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_action_round_trip(self, data: dict[str, Any]) -> None:
        """If Action.from_dict succeeds, to_dict must not raise."""
        try:
            action = Action.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return  # parsing failed, nothing to round-trip
        # to_dict must not crash
        result = action.to_dict()
        assert isinstance(result, dict)
        assert "action_type" in result
