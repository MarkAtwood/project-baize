"""Game analysis tools for the Baize engine.

Provides functions for analyzing game complexity, replaying games,
and searching for shortest games via random playouts.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from baize.action import Action
from baize.definition import GameDefinition, PrivateVisibility
from baize.moves import LegalMove, legal_moves
from baize.runtime import GameSession, GridZone
from baize.state import GameState
from baize.transition import apply_action


def _generate_placement_moves(session: GameSession) -> list[Action]:
    """Generate placement actions for games that use place-on-empty-cell rules.

    This supplements legal_moves() which only handles grid movement primitives.
    For games like tic-tac-toe, the legal actions are placing a component on any
    empty cell of a grid zone.
    """
    player = session.current_player()
    if player is None:
        return []

    actions: list[Action] = []
    for zone_name, zone in session.runtime.zones.items():
        if not isinstance(zone, GridZone):
            continue
        zone_def = session.definition.zones.get(zone_name)
        if zone_def is None:
            continue

        # Find component types that can be placed (unlimited or count > current)
        for comp_type, comp_def in session.definition.components.items():
            if not comp_def.movement:
                # No movement primitives means this is a placeable component
                for row in range(zone.height):
                    for col in range(zone.width):
                        if zone.grid_get(col, row) is None:
                            actions.append(
                                Action(
                                    action_type="place",
                                    component_type=comp_type,
                                    to_pos={
                                        "zone": zone_name,
                                        "cell": f"{col},{row}",
                                    },
                                )
                            )
    return actions


def _all_legal_actions(session: GameSession) -> list[Action]:
    """Get all legal actions: movement moves plus placement moves."""
    actions: list[Action] = []

    # Movement-based moves from legal_moves()
    moves = legal_moves(session)
    for m in moves:
        actions.append(m.action)

    # Placement moves for games with placeable components
    actions.extend(_generate_placement_moves(session))

    return actions


def branching_factor(session: GameSession) -> int:
    """Return the number of legal moves in the current state."""
    return len(_all_legal_actions(session))


def game_tree_depth(
    session: GameSession, max_depth: int = 100, n_samples: int = 10
) -> int:
    """Estimate average game length by playing random games.

    Plays n_samples random games from the current state and returns the
    average number of moves before the game ends or max_depth is reached.
    """
    total_depth = 0
    for _ in range(n_samples):
        sess = copy.deepcopy(session)
        depth = 0
        while depth < max_depth and sess.runtime.status != "finished":
            actions = _all_legal_actions(sess)
            if not actions:
                break
            action = random.choice(actions)
            try:
                apply_action(sess, action)
            except Exception:
                break
            depth += 1
        total_depth += depth
    return total_depth // n_samples


def complexity_profile(
    session: GameSession, n_games: int = 100
) -> dict[str, Any]:
    """Run n random games and report complexity statistics.

    Returns a dict with:
        - min_length: shortest game observed
        - max_length: longest game observed
        - avg_length: average game length
        - avg_branching_factor: average branching factor per turn
        - win_rates: dict mapping player name to win fraction
    """
    lengths: list[int] = []
    total_branching: list[float] = []
    wins: dict[str, int] = {}

    player_names: list[str] = list(session.runtime.players.keys())
    for name in player_names:
        wins[name] = 0

    for _ in range(n_games):
        sess = copy.deepcopy(session)
        depth = 0
        turn_branching: list[int] = []

        while depth < 1000 and sess.runtime.status != "finished":
            actions = _all_legal_actions(sess)
            if not actions:
                break
            turn_branching.append(len(actions))
            action = random.choice(actions)
            try:
                apply_action(sess, action)
            except Exception:
                break
            depth += 1

        lengths.append(depth)
        if turn_branching:
            total_branching.append(sum(turn_branching) / len(turn_branching))

        # Determine winner: the last player to move before game ended,
        # or check if a resign happened
        if sess.runtime.status == "finished" and depth > 0:
            # In many games, the player who made the last move won
            last_player_idx = (sess.runtime.turn_index - 1) % len(player_names)
            if last_player_idx < len(player_names):
                winner = player_names[last_player_idx]
                wins[winner] = wins.get(winner, 0) + 1

    avg_length = sum(lengths) / len(lengths) if lengths else 0.0
    avg_bf = sum(total_branching) / len(total_branching) if total_branching else 0.0

    win_rates: dict[str, float] = {}
    for name in player_names:
        win_rates[name] = wins[name] / n_games if n_games > 0 else 0.0

    return {
        "min_length": min(lengths) if lengths else 0,
        "max_length": max(lengths) if lengths else 0,
        "avg_length": avg_length,
        "avg_branching_factor": avg_bf,
        "win_rates": win_rates,
    }


def hidden_info_ratio(definition: GameDefinition) -> float:
    """Ratio of hidden/private zones to total zones.

    Returns 0.0 for perfect information games (all zones public),
    and up to 1.0 when all zones are hidden or private.
    """
    total = len(definition.zones)
    if total == 0:
        return 0.0

    hidden_count = 0
    for zone in definition.zones.values():
        vis = zone.visibility
        if vis == "hidden" or isinstance(vis, PrivateVisibility):
            hidden_count += 1

    return hidden_count / total


def replay_game(
    session: GameSession, actions: list[Action]
) -> list[GameState]:
    """Apply a sequence of actions and return all intermediate states.

    Returns a list of GameState snapshots, one after each action is applied.
    The list length equals the number of actions.
    """
    sess = copy.deepcopy(session)
    states: list[GameState] = []
    for action in actions:
        apply_action(sess, action)
        states.append(sess.to_wire_state())
    return states


def find_shortest_game(
    session: GameSession, max_attempts: int = 10000
) -> list[Action]:
    """Brute-force search for the shortest possible game via random playouts.

    Plays up to max_attempts random games and returns the action sequence
    of the shortest one found. Returns an empty list if no game terminates.
    """
    best: list[Action] | None = None

    for _ in range(max_attempts):
        sess = copy.deepcopy(session)
        moves_taken: list[Action] = []
        depth = 0
        max_depth = len(best) - 1 if best is not None else 1000
        game_ended = False

        while depth < max_depth:
            if sess.runtime.status == "finished":
                game_ended = True
                break
            actions = _all_legal_actions(sess)
            if not actions:
                # No legal actions remaining counts as game over
                game_ended = True
                break
            action = random.choice(actions)
            try:
                apply_action(sess, action)
            except Exception:
                break
            moves_taken.append(action)
            depth += 1

        if not game_ended and sess.runtime.status == "finished":
            game_ended = True

        if game_ended and moves_taken:
            if best is None or len(moves_taken) < len(best):
                best = moves_taken

    return best if best is not None else []
