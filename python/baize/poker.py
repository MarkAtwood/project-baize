"""Poker hand ranking evaluator.

Evaluates 5-card poker hands and selects the best 5-card hand from 7 cards
(2 hole + 5 community) for Texas Hold'em showdown resolution.

Cards are represented as (rank, suit) tuples where:
  - rank: int 2-14 (14 = Ace)
  - suit: str, one of "hearts", "diamonds", "clubs", "spades"
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum


class HandRank(IntEnum):
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8
    ROYAL_FLUSH = 9


@dataclass(frozen=True, order=True)
class HandValue:
    """Comparable hand evaluation result.

    Ordering is determined first by rank (HandRank IntEnum), then by
    tiebreakers tuple (kickers in descending significance order).
    """

    rank: HandRank
    tiebreakers: tuple[int, ...]


def evaluate_hand(cards: list[tuple[int, str]]) -> HandValue:
    """Evaluate a 5-card poker hand.

    Args:
        cards: Exactly 5 cards as (rank, suit) tuples.
            rank is 2-14 (14=Ace), suit is one of
            "hearts", "diamonds", "clubs", "spades".

    Returns:
        HandValue with rank and tiebreakers for comparison.

    Raises:
        ValueError: If not exactly 5 cards.
    """
    if len(cards) != 5:
        raise ValueError(f"Expected 5 cards, got {len(cards)}")

    ranks = sorted((r for r, _s in cards), reverse=True)
    suits = [s for _r, s in cards]

    is_flush = len(set(suits)) == 1

    # Check for straight: 5 consecutive ranks, or ace-low (A-2-3-4-5)
    unique_ranks = sorted(set(ranks), reverse=True)
    is_straight = False
    straight_high = 0

    if len(unique_ranks) == 5:
        if unique_ranks[0] - unique_ranks[4] == 4:
            is_straight = True
            straight_high = unique_ranks[0]
        elif unique_ranks == [14, 5, 4, 3, 2]:
            # Ace-low straight (wheel): A-2-3-4-5, high card is 5
            is_straight = True
            straight_high = 5

    # Count rank groups
    rank_counts = Counter(ranks)
    # Sort groups by (count descending, rank descending)
    groups = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    group_counts = [count for _rank, count in groups]

    if is_straight and is_flush:
        if straight_high == 14:
            return HandValue(HandRank.ROYAL_FLUSH, ())
        return HandValue(HandRank.STRAIGHT_FLUSH, (straight_high,))

    if group_counts == [4, 1]:
        quad_rank = groups[0][0]
        kicker = groups[1][0]
        return HandValue(HandRank.FOUR_OF_A_KIND, (quad_rank, kicker))

    if group_counts == [3, 2]:
        triple_rank = groups[0][0]
        pair_rank = groups[1][0]
        return HandValue(HandRank.FULL_HOUSE, (triple_rank, pair_rank))

    if is_flush:
        return HandValue(HandRank.FLUSH, tuple(ranks))

    if is_straight:
        return HandValue(HandRank.STRAIGHT, (straight_high,))

    if group_counts == [3, 1, 1]:
        triple_rank = groups[0][0]
        kickers = sorted((groups[1][0], groups[2][0]), reverse=True)
        return HandValue(HandRank.THREE_OF_A_KIND, (triple_rank, *kickers))

    if group_counts == [2, 2, 1]:
        high_pair = max(groups[0][0], groups[1][0])
        low_pair = min(groups[0][0], groups[1][0])
        kicker = groups[2][0]
        return HandValue(HandRank.TWO_PAIR, (high_pair, low_pair, kicker))

    if group_counts == [2, 1, 1, 1]:
        pair_rank = groups[0][0]
        kickers = sorted((groups[1][0], groups[2][0], groups[3][0]), reverse=True)
        return HandValue(HandRank.ONE_PAIR, (pair_rank, *kickers))

    # High card
    return HandValue(HandRank.HIGH_CARD, tuple(ranks))


def best_hand(cards: list[tuple[int, str]]) -> HandValue:
    """Find the best 5-card hand from 7 cards.

    Evaluates all C(7,5) = 21 combinations and returns the best.

    Args:
        cards: Exactly 7 cards as (rank, suit) tuples.

    Returns:
        The highest-ranking HandValue among all 21 combinations.

    Raises:
        ValueError: If not exactly 7 cards.
    """
    if len(cards) != 7:
        raise ValueError(f"Expected 7 cards, got {len(cards)}")

    return max(evaluate_hand(list(combo)) for combo in itertools.combinations(cards, 5))
