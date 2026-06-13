"""Tests for the trigger / claim-window system.

When a game action matches a trigger's on_action field, the engine opens a
"claim window" -- a mini-simultaneous collection phase where eligible players
submit claims. When all respond, the highest-priority non-default claim wins
and that player becomes active. If all pass, normal turn order resumes.

Uses an inline 3-player game definition with a trigger on "place" actions.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession
from baize.transition import apply_action, apply_claim


# ---------------------------------------------------------------------------
# Game definition JSON -- 3-player game with a trigger on "place"
# ---------------------------------------------------------------------------

TRIGGER_GAME_JSON = """{
    "game": { "name": "Trigger Test Game", "players": ["Alice", "Bob", "Carol"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "round_robin", "players": ["Alice", "Bob", "Carol"], "actions_per_turn": 1 },
    "end_conditions": [
        { "result": "draw", "condition": "board_is_full" }
    ],
    "triggers": {
        "on_place": {
            "on_action": "place",
            "claim_window": {
                "eligible": "all_except_current",
                "actions": ["claim", "challenge"],
                "priority": ["challenge", "claim"],
                "timeout": 10,
                "default": "pass"
            }
        }
    },
    "authority": { "server_only": [], "client_verifiable": ["place"] }
}"""

NEXT_IN_ORDER_GAME_JSON = """{
    "game": { "name": "Next-In-Order Trigger", "players": ["Alice", "Bob", "Carol"], "information": "perfect" },
    "zones": {
        "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
    },
    "components": {
        "mark": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "round_robin", "players": ["Alice", "Bob", "Carol"], "actions_per_turn": 1 },
    "end_conditions": [
        { "result": "draw", "condition": "board_is_full" }
    ],
    "triggers": {
        "on_place": {
            "on_action": "place",
            "claim_window": {
                "eligible": "next_in_order",
                "actions": ["claim"],
                "priority": ["claim"],
                "timeout": 5,
                "default": "pass"
            }
        }
    },
    "authority": { "server_only": [], "client_verifiable": ["place"] }
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trigger_session() -> GameSession:
    defn = GameDefinition.from_json(TRIGGER_GAME_JSON)
    return GameSession(defn)


def _next_in_order_session() -> GameSession:
    defn = GameDefinition.from_json(NEXT_IN_ORDER_GAME_JSON)
    return GameSession(defn)


def _place_mark(col: int, row: int) -> Action:
    return Action(
        action_type="place",
        component_type="mark",
        to_pos={"zone": "board", "cell": f"{col},{row}"},
    )


# ---------------------------------------------------------------------------
# 1. Trigger fires on matching action
# ---------------------------------------------------------------------------


class TestTriggerFires:

    def test_trigger_fires_on_matching_action(self) -> None:
        session = _trigger_session()
        assert session.current_player() == "Alice"

        events = apply_action(session, _place_mark(1, 1), acting_player="Alice")

        # Must contain trigger_activated event with detail "on_place"
        trigger_events = [e for e in events if e.event_type == "trigger_activated"]
        assert len(trigger_events) == 1, "expected exactly one trigger_activated event"
        assert trigger_events[0].player == "Alice"
        assert trigger_events[0].detail == "on_place"

        # Claim window must be active
        assert session.runtime.claim_window is not None
        cw = session.runtime.claim_window
        assert cw.trigger_name == "on_place"
        assert cw.triggering_player == "Alice"
        assert cw.eligible_players == ["Bob", "Carol"]
        assert cw.submitted_claims == {}

        # Turn should NOT have advanced
        turn_advances = [e for e in events if e.event_type == "turn_advance"]
        assert len(turn_advances) == 0, "turn should not advance when claim window opens"


# ---------------------------------------------------------------------------
# 2. Claim window blocks normal actions
# ---------------------------------------------------------------------------


class TestClaimWindowBlocks:

    def test_claim_window_blocks_normal_actions(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(1, 1), acting_player="Alice")

        assert session.runtime.claim_window is not None

        with pytest.raises(Exception, match="claim window"):
            apply_action(session, _place_mark(0, 0), acting_player="Bob")


# ---------------------------------------------------------------------------
# 3. Valid claim submission
# ---------------------------------------------------------------------------


class TestClaimSubmit:

    def test_claim_submit_valid(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(1, 1), acting_player="Alice")

        events = apply_claim(session, "Bob", "claim")

        submitted_events = [e for e in events if e.event_type == "claim_submitted"]
        assert len(submitted_events) == 1
        assert submitted_events[0].player == "Bob"
        assert submitted_events[0].detail == "claim"

        # Window still active (Carol hasn't responded)
        assert session.runtime.claim_window is not None
        assert session.runtime.claim_window.submitted_claims.get("Bob") == "claim"


# ---------------------------------------------------------------------------
# 4. Non-eligible player rejected
# ---------------------------------------------------------------------------


class TestClaimNonEligible:

    def test_claim_submit_non_eligible_rejected(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(1, 1), acting_player="Alice")

        with pytest.raises(Exception, match="not eligible"):
            apply_claim(session, "Alice", "claim")


# ---------------------------------------------------------------------------
# 5. Duplicate claim rejected
# ---------------------------------------------------------------------------


class TestClaimDuplicate:

    def test_claim_submit_duplicate_rejected(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(1, 1), acting_player="Alice")

        apply_claim(session, "Bob", "pass")
        with pytest.raises(Exception, match="already submitted"):
            apply_claim(session, "Bob", "claim")


# ---------------------------------------------------------------------------
# 6. Invalid claim action rejected
# ---------------------------------------------------------------------------


class TestClaimInvalidAction:

    def test_claim_submit_invalid_action_rejected(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(1, 1), acting_player="Alice")

        with pytest.raises(Exception, match="invalid claim"):
            apply_claim(session, "Bob", "steal")


# ---------------------------------------------------------------------------
# 7. All pass advances turn normally
# ---------------------------------------------------------------------------


class TestAllPass:

    def test_all_pass_advances_turn(self) -> None:
        session = _trigger_session()
        assert session.current_player() == "Alice"

        apply_action(session, _place_mark(1, 1), acting_player="Alice")
        apply_claim(session, "Bob", "pass")
        events = apply_claim(session, "Carol", "pass")

        # Claim window should be cleared
        assert session.runtime.claim_window is None

        # claim_resolved with "all_passed"
        resolved = [e for e in events if e.event_type == "claim_resolved"]
        assert len(resolved) == 1
        assert resolved[0].detail == "all_passed"

        # Turn advances to Bob (next after Alice in round_robin)
        turn_advances = [e for e in events if e.event_type == "turn_advance"]
        assert len(turn_advances) == 1
        assert turn_advances[0].player == "Bob"
        assert session.current_player() == "Bob"


# ---------------------------------------------------------------------------
# 8. Priority resolution -- challenge beats claim
# ---------------------------------------------------------------------------


class TestPriorityResolution:

    def test_priority_resolution(self) -> None:
        session = _trigger_session()
        apply_action(session, _place_mark(0, 0), acting_player="Alice")

        apply_claim(session, "Bob", "claim")
        events = apply_claim(session, "Carol", "challenge")

        resolved = [e for e in events if e.event_type == "claim_resolved"]
        assert len(resolved) == 1
        assert resolved[0].player == "Carol"
        assert resolved[0].detail == "challenge"


# ---------------------------------------------------------------------------
# 9. Winner becomes active player
# ---------------------------------------------------------------------------


class TestWinnerBecomesActive:

    def test_winner_becomes_active_player(self) -> None:
        session = _trigger_session()
        assert session.current_player() == "Alice"

        apply_action(session, _place_mark(0, 0), acting_player="Alice")

        apply_claim(session, "Bob", "pass")
        events = apply_claim(session, "Carol", "challenge")

        assert session.runtime.claim_window is None

        # Carol should now be the active player
        assert session.current_player() == "Carol"

        turn_advances = [e for e in events if e.event_type == "turn_advance"]
        assert len(turn_advances) == 1
        assert turn_advances[0].player == "Carol"


# ---------------------------------------------------------------------------
# 10. No trigger without match
# ---------------------------------------------------------------------------


class TestNoTriggerWithoutMatch:

    def test_no_trigger_without_match(self) -> None:
        no_trigger_json = """{
            "game": { "name": "No Triggers", "players": ["X", "O"], "information": "perfect" },
            "zones": {
                "board": { "zone_type": "grid", "dimensions": [3, 3], "visibility": "public" }
            },
            "components": {
                "mark": { "owner": "per_player", "count": "unlimited" }
            },
            "turn_order": { "type": "alternating", "players": ["X", "O"], "actions_per_turn": 1, "mandatory": true },
            "end_conditions": [
                { "result": "draw", "condition": "board_is_full" }
            ],
            "authority": { "server_only": [], "client_verifiable": ["all"] }
        }"""
        defn = GameDefinition.from_json(no_trigger_json)
        session = GameSession(defn)

        events = apply_action(
            session,
            Action(
                action_type="place",
                component_type="mark",
                to_pos={"zone": "board", "cell": "1,1"},
            ),
        )

        trigger_events = [e for e in events if e.event_type == "trigger_activated"]
        assert len(trigger_events) == 0, "no trigger_activated event expected"

        assert session.runtime.claim_window is None

        turn_advances = [e for e in events if e.event_type == "turn_advance"]
        assert len(turn_advances) == 1, "turn should advance normally"


# ---------------------------------------------------------------------------
# 11. Trigger definition roundtrip
# ---------------------------------------------------------------------------


class TestTriggerRoundtrip:

    def test_trigger_definition_roundtrip(self) -> None:
        defn1 = GameDefinition.from_json(TRIGGER_GAME_JSON)

        # Must have parsed the trigger
        assert "on_place" in defn1.triggers
        trigger = defn1.triggers["on_place"]
        assert trigger.on_action == "place"
        assert trigger.claim_window.eligible == "all_except_current"
        assert trigger.claim_window.actions == ["claim", "challenge"]
        assert trigger.claim_window.priority == ["challenge", "claim"]
        assert trigger.claim_window.default == "pass"
        assert trigger.claim_window.timeout == 10

        # Serialize to JSON and back
        json1 = defn1.to_json(indent=None)

        defn2 = GameDefinition.from_json(json1)
        json2 = defn2.to_json(indent=None)

        assert json1 == json2, "trigger definition roundtrip not identical"


# ---------------------------------------------------------------------------
# 12. next_in_order eligible rule
# ---------------------------------------------------------------------------


class TestNextInOrderEligible:

    def test_next_in_order_eligible(self) -> None:
        session = _next_in_order_session()
        assert session.current_player() == "Alice"

        events = apply_action(session, _place_mark(1, 1), acting_player="Alice")

        trigger_events = [e for e in events if e.event_type == "trigger_activated"]
        assert len(trigger_events) == 1, "trigger should fire"

        cw = session.runtime.claim_window
        assert cw is not None
        assert cw.eligible_players == ["Bob"], \
            "only next-in-order player (Bob) should be eligible"

        # Bob claims -- single eligible player, resolves immediately
        events = apply_claim(session, "Bob", "claim")

        resolved = [e for e in events if e.event_type == "claim_resolved"]
        assert len(resolved) == 1
        assert resolved[0].player == "Bob"
        assert resolved[0].detail == "claim"

        assert session.current_player() == "Bob"
        assert session.runtime.claim_window is None


# ---------------------------------------------------------------------------
# Cross-implementation test vector runner
# ---------------------------------------------------------------------------


VECTORS_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "vectors"
    / "triggers.json"
)


class TestTriggerVectors:

    def test_run_trigger_test_vectors(self) -> None:
        raw = VECTORS_PATH.read_text(encoding="utf-8")
        vectors = json.loads(raw)

        game_def_json = json.dumps(vectors["game_definition"])
        test_cases = vectors["test_cases"]

        for tc in test_cases:
            name = tc["name"]
            steps = tc["steps"]

            # Fresh session for each test case
            defn = GameDefinition.from_json(game_def_json)
            session = GameSession(defn)

            for step_idx, step in enumerate(steps):
                step_type = step["type"]
                expected = step["expected"]

                if step_type == "action":
                    player = step["player"]
                    action_val = step["action"]
                    action = Action(
                        action_type=action_val["action_type"],
                        component_type=action_val.get("component_type"),
                        to_pos=action_val.get("to"),
                    )
                    events = apply_action(
                        session, action, acting_player=player
                    )
                    _verify_step_expected(
                        session, events, expected, name, step_idx
                    )

                elif step_type == "claim":
                    player = step["player"]
                    claim = step["claim"]
                    events = apply_claim(session, player, claim)
                    _verify_step_expected(
                        session, events, expected, name, step_idx
                    )

                else:
                    raise ValueError(
                        f"[{name}] unknown step type: {step_type}"
                    )


def _verify_step_expected(
    session: GameSession,
    events: list[Any],
    expected: dict[str, Any],
    test_name: str,
    step: int,
) -> None:
    # Check claim_window_active
    if "claim_window_active" in expected:
        active = expected["claim_window_active"]
        actual = session.runtime.claim_window is not None
        assert actual == active, (
            f"[{test_name}] step {step}: claim_window_active: "
            f"expected {active}, got {actual}"
        )

    # Check current_player
    if "current_player" in expected:
        assert session.current_player() == expected["current_player"], (
            f"[{test_name}] step {step}: current_player mismatch"
        )

    # Check events_contain
    if "events_contain" in expected:
        for exp_ev in expected["events_contain"]:
            exp_type = exp_ev["event_type"]
            match = None
            for e in events:
                if e.event_type != exp_type:
                    continue
                if "player" in exp_ev and e.player != exp_ev["player"]:
                    continue
                if "detail" in exp_ev and e.detail != exp_ev["detail"]:
                    continue
                match = e
                break
            assert match is not None, (
                f"[{test_name}] step {step}: expected event {exp_ev} "
                f"not found in {[(e.event_type, e.player, e.detail) for e in events]}"
            )

    # Check events_must_not_contain
    if "events_must_not_contain" in expected:
        for excl_type in expected["events_must_not_contain"]:
            found = any(e.event_type == excl_type for e in events)
            assert not found, (
                f"[{test_name}] step {step}: event type {excl_type} "
                f"should not be present"
            )

    # Check claim_window details
    if "claim_window" in expected:
        exp_cw = expected["claim_window"]
        cw = session.runtime.claim_window
        assert cw is not None, (
            f"[{test_name}] step {step}: claim_window expected to be active"
        )
        if "trigger_name" in exp_cw:
            assert cw.trigger_name == exp_cw["trigger_name"]
        if "triggering_player" in exp_cw:
            assert cw.triggering_player == exp_cw["triggering_player"]
        if "eligible_players" in exp_cw:
            assert cw.eligible_players == exp_cw["eligible_players"]
