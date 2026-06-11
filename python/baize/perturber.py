"""Structured perturber language: composable effects with bounded control flow.

Perturbers describe state mutations as a structured AST. Unlike CEL (pure
queries), perturbers mutate game state. Unlike WASM (arbitrary code),
perturbers are guaranteed to terminate.

Control flow: sequence, if/then/else, for_each, repeat(n), repeat_until_stable.
No while, no recursion, no computed gotos.
"""

from __future__ import annotations

from typing import Any

from baize.action import Action
from baize.cel import try_eval_end_condition
from baize.runtime import GameSession
from baize.transition import apply_action

MAX_FUEL = 10_000
MAX_REPEAT = 10_000
MAX_FOREACH_ITEMS = 10_000
MAX_COUNTER_VALUE = 1_000_000_000


def execute_effect(session: GameSession, effect: dict[str, Any]) -> None:
    """Execute a perturber effect against a game session."""
    if "sequence" in effect:
        for e in effect["sequence"]:
            execute_effect(session, e)

    elif "if" in effect:
        condition = effect["if"]
        player = session.current_player() or ""
        variables = _build_variables(session, player)
        result = try_eval_end_condition(variables, condition)
        if result is True:
            execute_effect(session, effect["then"])
        elif "else" in effect:
            execute_effect(session, effect["else"])

    elif "for_each" in effect:
        spec = effect["for_each"]
        items: list[str] = spec.get("in", [])
        if len(items) > MAX_FOREACH_ITEMS:
            raise ValueError(
                f"for_each collection size {len(items)} exceeds maximum {MAX_FOREACH_ITEMS}"
            )
        filter_expr = spec.get("filter")
        body = effect["do"]

        if filter_expr is not None:
            player = session.current_player() or ""
            var_name = spec.get("var", "item")
            filtered = []
            for item in items:
                variables = _build_variables(session, player)
                expr = filter_expr.replace(f"${var_name}", item)
                if try_eval_end_condition(variables, expr) is True:
                    filtered.append(item)
            items = filtered

        for _item in items:
            execute_effect(session, body)

    elif "repeat" in effect:
        count = min(int(effect["repeat"]), MAX_REPEAT)
        if count < 0:
            return
        body = effect["body"]
        for _ in range(count):
            execute_effect(session, body)

    elif "repeat_until_stable" in effect:
        spec = effect["repeat_until_stable"]
        fuel = min(int(spec.get("fuel", 100)), MAX_FUEL)
        body = spec["apply"]
        for _ in range(fuel):
            hash_before = session.compute_state_hash()
            execute_effect(session, body)
            hash_after = session.compute_state_hash()
            if hash_before == hash_after:
                break

    elif "remove" in effect:
        target = effect["remove"]["target"]
        action = Action(action_type="remove", component_id=target)
        apply_action(session, action)

    elif "flip" in effect:
        target = effect["flip"]["target"]
        action = Action(action_type="flip", component_id=target)
        apply_action(session, action)

    elif "promote" in effect:
        spec = effect["promote"]
        action = Action(
            action_type="promote",
            component_id=spec["target"],
            promote_to=spec["to_type"],
        )
        apply_action(session, action)

    elif "add_counter" in effect:
        spec = effect["add_counter"]
        counter = spec["counter"]
        value = int(spec.get("value", 0))
        if abs(value) > MAX_COUNTER_VALUE:
            raise ValueError(
                f"counter value {value} exceeds maximum {MAX_COUNTER_VALUE}"
            )
        current = session.runtime.counters.get(counter, 0)
        new_value = current + value
        if abs(new_value) > MAX_COUNTER_VALUE * 10:
            raise OverflowError("counter addition overflow")
        session.runtime.counters[counter] = new_value

    elif "set_counter" in effect:
        spec = effect["set_counter"]
        value = int(spec.get("value", 0))
        if abs(value) > MAX_COUNTER_VALUE:
            raise ValueError(
                f"counter value {value} exceeds maximum {MAX_COUNTER_VALUE}"
            )
        session.runtime.counters[spec["counter"]] = value


def _build_variables(session: GameSession, player: str) -> dict[str, Any]:
    """Build CEL variables for condition evaluation within perturbers."""
    return {
        "current_player": player,
        "move_count": int(session.runtime.move_count),
        "halfmove_clock": int(session.runtime.halfmove_clock),
    }
