"""Poker showdown resolution: reveal hands, rank them, award pot.

After the final betting round, determines the winner(s) by evaluating
each active player's best 5-card hand from their 2 hole cards plus
5 community cards. Awards the pot to the winner, splitting on ties.

Side pots are NOT in scope for P1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baize.betting import BettingRoundState
from baize.poker import HandRank, HandValue, best_hand
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
)


# Map card rank strings to integer values for the evaluator
_RANK_MAP: dict[str, int] = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}


@dataclass(frozen=True)
class ShowdownResult:
    """Result of a showdown resolution.

    Attributes:
        winners: List of player names who won (multiple on tie).
        hand_rank: The winning HandRank (None if won by last-standing).
        hand_name: Human-readable name of the winning hand.
        hand_values: Per-player HandValue for each active player evaluated.
        pot_awarded: Total pot amount distributed.
        awards: Per-player chip amounts awarded.
    """

    winners: list[str]
    hand_rank: HandRank | None
    hand_name: str
    hand_values: dict[str, HandValue]
    pot_awarded: int
    awards: dict[str, int]


def _card_to_tuple(comp: ComponentData) -> tuple[int, str]:
    """Convert a ComponentData card to (rank_int, suit_str) for the evaluator."""
    rank_str = comp.properties.get("rank", "")
    suit = comp.properties.get("suit", "")
    rank_int = _RANK_MAP.get(str(rank_str), 0)
    return (rank_int, suit)


def _get_hand_cards(
    session: GameSession, player: str
) -> list[tuple[int, str]]:
    """Get a player's hole cards as (rank, suit) tuples."""
    pstate = session.runtime.players.get(player)
    if pstate is None:
        return []
    hand_zone = pstate.zones.get("hand")
    if not isinstance(hand_zone, SetZone):
        return []
    cards: list[tuple[int, str]] = []
    for cid in hand_zone.components:
        comp = session.runtime.components.get(cid)
        if comp is not None:
            cards.append(_card_to_tuple(comp))
    return cards


def _get_community_cards(session: GameSession) -> list[tuple[int, str]]:
    """Get community cards as (rank, suit) tuples."""
    community = session.runtime.zones.get("community")
    if not isinstance(community, SetZone):
        return []
    cards: list[tuple[int, str]] = []
    for cid in community.components:
        comp = session.runtime.components.get(cid)
        if comp is not None:
            cards.append(_card_to_tuple(comp))
    return cards


def _get_active_players(session: GameSession) -> list[str]:
    """Get the list of active (non-folded) players.

    Uses the betting state if available; otherwise returns all players.
    """
    bs = session.runtime.betting_state
    if bs is not None and bs.active_players:
        return list(bs.active_players)
    return list(session.runtime.players.keys())


def _hand_rank_name(rank: HandRank) -> str:
    """Human-readable name for a HandRank."""
    names = {
        HandRank.HIGH_CARD: "high card",
        HandRank.ONE_PAIR: "one pair",
        HandRank.TWO_PAIR: "two pair",
        HandRank.THREE_OF_A_KIND: "three of a kind",
        HandRank.STRAIGHT: "straight",
        HandRank.FLUSH: "flush",
        HandRank.FULL_HOUSE: "full house",
        HandRank.FOUR_OF_A_KIND: "four of a kind",
        HandRank.STRAIGHT_FLUSH: "straight flush",
        HandRank.ROYAL_FLUSH: "royal flush",
    }
    return names.get(rank, "unknown")


def resolve_showdown(session: GameSession) -> ShowdownResult:
    """Resolve the showdown phase: evaluate hands, find winner(s), award pot.

    Handles three cases:
      1. All but one folded: last player wins pot without showing cards.
      2. Single winner: best hand wins entire pot.
      3. Tie: pot split evenly, remainder to first winner in turn order.

    Returns a ShowdownResult with winner info and chip awards.
    """
    active = _get_active_players(session)

    # Get pot amount
    pot_zone = session.runtime.zones.get("pot")
    pot_amount = pot_zone.value if isinstance(pot_zone, CounterZone) else 0

    # All players in turn order (for tiebreaker remainder assignment)
    all_players = list(session.runtime.players.keys())

    # Case 1: only one player remaining (all others folded)
    if len(active) == 1:
        winner = active[0]
        _award_chips(session, winner, pot_amount)
        _zero_pot(session)
        return ShowdownResult(
            winners=[winner],
            hand_rank=None,
            hand_name="last player standing",
            hand_values={},
            pot_awarded=pot_amount,
            awards={winner: pot_amount},
        )

    # Case 2+3: evaluate hands for all active players
    community = _get_community_cards(session)
    hand_values: dict[str, HandValue] = {}

    for player in active:
        hole = _get_hand_cards(session, player)
        all_cards = hole + community
        if len(all_cards) == 7:
            hand_values[player] = best_hand(all_cards)
        elif len(all_cards) == 5:
            # Edge case: no community cards dealt yet (unlikely but handle it)
            from baize.poker import evaluate_hand
            hand_values[player] = evaluate_hand(all_cards)

    if not hand_values:
        # No hands could be evaluated — award pot to first active player
        winner = active[0]
        _award_chips(session, winner, pot_amount)
        _zero_pot(session)
        return ShowdownResult(
            winners=[winner],
            hand_rank=None,
            hand_name="no hands evaluated",
            hand_values={},
            pot_awarded=pot_amount,
            awards={winner: pot_amount},
        )

    # Find the best hand value
    best_val = max(hand_values.values())

    # Find all players with the best hand (ties)
    winners = [p for p in active if hand_values.get(p) == best_val]

    # Order winners by turn order for remainder assignment
    winners_ordered = [p for p in all_players if p in winners]

    # Distribute pot
    awards: dict[str, int] = {}
    if len(winners_ordered) == 1:
        awards[winners_ordered[0]] = pot_amount
        _award_chips(session, winners_ordered[0], pot_amount)
    else:
        # Split evenly, remainder goes to first winner in turn order
        share = pot_amount // len(winners_ordered)
        remainder = pot_amount % len(winners_ordered)
        for i, winner in enumerate(winners_ordered):
            amount = share + (1 if i < remainder else 0)
            awards[winner] = amount
            _award_chips(session, winner, amount)

    _zero_pot(session)

    return ShowdownResult(
        winners=winners_ordered,
        hand_rank=best_val.rank,
        hand_name=_hand_rank_name(best_val.rank),
        hand_values=hand_values,
        pot_awarded=pot_amount,
        awards=awards,
    )


def _award_chips(session: GameSession, player: str, amount: int) -> None:
    """Add chips to a player's chip counter."""
    pstate = session.runtime.players.get(player)
    if pstate is None:
        return
    chip_zone = pstate.zones.get("player_chips")
    if isinstance(chip_zone, CounterZone):
        chip_zone.value += amount


def _zero_pot(session: GameSession) -> None:
    """Reset the pot counter to zero."""
    pot = session.runtime.zones.get("pot")
    if isinstance(pot, CounterZone):
        pot.value = 0
