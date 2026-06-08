"""Property-based fuzz tests using Hypothesis.

These tests feed random / adversarial inputs to the Baize parsers and
runtime, checking that:
  - ParseError is raised for invalid JSON (never TypeError, KeyError, etc.)
  - Runtime operations never raise unexpected exceptions
  - legal_moves() always returns a list
"""

from __future__ import annotations

import json

import hypothesis
from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from baize.definition import GameDefinition
from baize.action import Action, ClientMessage
from baize.error import BaizeError, ParseError
from baize.runtime import GameSession
from baize.moves import legal_moves
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary JSON values (strings, ints, floats, bools, None, lists, dicts).
json_values = st.recursive(
    st.one_of(
        st.text(max_size=50),
        st.integers(min_value=-1_000_000, max_value=1_000_000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.none(),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)

# Random JSON strings (may or may not be valid JSON).
random_json_strings = st.one_of(
    # Valid JSON from random values
    json_values.map(lambda v: json.dumps(v)),
    # Completely random text (likely invalid JSON)
    st.text(max_size=500),
    # Random bytes decoded as latin-1 (produces valid str, possibly invalid JSON)
    st.binary(max_size=200).map(lambda b: b.decode("latin-1")),
)

# Valid action types for generating plausible-ish action dicts.
ACTION_TYPES = [
    "move_piece", "place", "draw", "play_card", "discard",
    "roll_dice", "flip", "promote", "swap", "remove",
    "pass", "resign", "offer_draw", "accept_draw", "decline_draw",
    "fold", "check", "call", "raise", "all_in",
    "place_ship", "fire", "castle", "en_passant",
    "declare_action", "custom",
]

# Strategy that produces dicts that look somewhat like actions.
action_like_dicts = st.fixed_dictionaries(
    {"action_type": st.sampled_from(ACTION_TYPES)},
    optional={
        "component_id": st.text(max_size=30),
        "component_type": st.text(max_size=30),
        "from": st.one_of(st.text(max_size=20), st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3)),
        "to": st.one_of(st.text(max_size=20), st.dictionaries(st.text(max_size=10), st.text(max_size=10), max_size=3)),
        "zone": st.text(max_size=20),
        "count": st.integers(min_value=0, max_value=1000),
        "amount": st.integers(min_value=0, max_value=10000),
        "custom_data": json_values,
    },
)


# ---------------------------------------------------------------------------
# Minimal valid game definition for creating sessions
# ---------------------------------------------------------------------------

TTT_JSON = """{
    "game": {
        "name": "Tic-Tac-Toe",
        "players": ["X", "O"],
        "information": "perfect"
    },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [3, 3],
            "visibility": "public"
        }
    },
    "components": {
        "mark": {
            "owner": "per_player",
            "count": "unlimited"
        }
    },
    "turn_order": {
        "type": "alternating",
        "players": ["X", "O"],
        "actions_per_turn": 1,
        "mandatory": true
    },
    "end_conditions": [
        {
            "result": "win",
            "player": "current",
            "condition": "three_in_line"
        },
        {
            "result": "draw",
            "condition": "board_is_full"
        }
    ],
    "authority": {
        "server_only": [],
        "client_verifiable": ["all"]
    }
}"""


def _make_session() -> GameSession:
    """Create a fresh tic-tac-toe session."""
    defn = GameDefinition.from_json(TTT_JSON)
    return GameSession(defn)


# ---------------------------------------------------------------------------
# Test: random JSON to definition parser
# ---------------------------------------------------------------------------


class TestFuzzDefinitionParser:
    """Random JSON strings fed to GameDefinition.from_json().

    Must not raise unexpected exceptions -- ParseError is fine,
    TypeError/KeyError/AttributeError is not.
    """

    @given(data=random_json_strings)
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_random_json_to_definition(self, data: str) -> None:
        try:
            GameDefinition.from_json(data)
        except ParseError:
            pass  # Expected for invalid input

    @given(data=json_values)
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_random_values_to_definition(self, data: object) -> None:
        """Serialize a random JSON value and try to parse it."""
        json_str = json.dumps(data)
        try:
            GameDefinition.from_json(json_str)
        except ParseError:
            pass  # Expected for invalid input


# ---------------------------------------------------------------------------
# Test: random JSON to ClientMessage / Action parser
# ---------------------------------------------------------------------------


class TestFuzzActionParser:
    """Random JSON fed to ClientMessage.from_json() and Action.from_dict()."""

    @given(data=random_json_strings)
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_random_json_to_client_message(self, data: str) -> None:
        try:
            ClientMessage.from_json(data)
        except ParseError:
            pass  # Expected for invalid input

    @given(data=json_values)
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_random_values_to_action(self, data: object) -> None:
        """Try to create an Action from a random dict-like value."""
        if not isinstance(data, dict):
            return  # Action.from_dict requires a dict
        try:
            Action.from_dict(data)
        except (KeyError, TypeError, ValueError):
            pass  # Action.from_dict doesn't wrap these in ParseError


# ---------------------------------------------------------------------------
# Test: random actions applied to a valid session
# ---------------------------------------------------------------------------


class TestFuzzApplyAction:
    """Feed random action dicts to apply_action on a valid session.

    Must not raise unexpected exceptions -- BaizeError subclasses are fine.
    """

    @given(action_dict=action_like_dicts)
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_random_action_on_session(self, action_dict: dict) -> None:
        session = _make_session()
        action = Action.from_dict(action_dict)
        try:
            apply_action(session, action)
        except BaizeError:
            pass  # Expected for illegal / unimplemented actions

    @given(
        placements=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=2),
                st.integers(min_value=0, max_value=2),
            ),
            max_size=9,
        ),
        extra_action=action_like_dicts,
    )
    @settings(
        max_examples=300,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_actions_after_placements(
        self,
        placements: list[tuple[int, int]],
        extra_action: dict,
    ) -> None:
        """Place marks randomly, then try an arbitrary action."""
        session = _make_session()
        for col, row in placements:
            place = Action(
                action_type="place",
                component_type="mark",
                to_pos={"zone": "board", "cell": f"{col},{row}"},
            )
            try:
                apply_action(session, place)
            except BaizeError:
                pass

        action = Action.from_dict(extra_action)
        try:
            apply_action(session, action)
        except BaizeError:
            pass


# ---------------------------------------------------------------------------
# Test: legal_moves always returns a list
# ---------------------------------------------------------------------------


class TestFuzzLegalMoves:
    """Property: legal_moves() always returns a list, never crashes."""

    def test_empty_session(self) -> None:
        session = _make_session()
        result = legal_moves(session)
        assert isinstance(result, list)

    @given(
        placements=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=2),
                st.integers(min_value=0, max_value=2),
            ),
            max_size=9,
        ),
    )
    @settings(
        max_examples=500,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_legal_moves_after_random_placements(
        self,
        placements: list[tuple[int, int]],
    ) -> None:
        """Place marks randomly, then verify legal_moves returns a list."""
        session = _make_session()
        for col, row in placements:
            place = Action(
                action_type="place",
                component_type="mark",
                to_pos={"zone": "board", "cell": f"{col},{row}"},
            )
            try:
                apply_action(session, place)
            except BaizeError:
                pass

        result = legal_moves(session)
        assert isinstance(result, list)
