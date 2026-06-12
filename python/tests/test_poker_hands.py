"""Tests for poker hand ranking evaluator.

Covers all 10 hand ranks, tiebreakers within each rank, edge cases
(ace-low/ace-high straights), and best_hand selection from 7 cards.

Run with: cd /home/mark/PROJECT/baize/python && python3 -m pytest tests/test_poker_hands.py -v
"""

from __future__ import annotations

import pytest

from baize.poker import HandRank, HandValue, best_hand, evaluate_hand

# Shorthand suits
H = "hearts"
D = "diamonds"
C = "clubs"
S = "spades"


# =========================================================================
# HIGH CARD
# =========================================================================


class TestHighCard:
    def test_high_card_ace_high(self) -> None:
        hand = [(14, H), (10, D), (7, C), (4, S), (2, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.HIGH_CARD
        assert result.tiebreakers == (14, 10, 7, 4, 2)

    def test_high_card_king_high(self) -> None:
        hand = [(13, H), (11, D), (9, C), (5, S), (3, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.HIGH_CARD
        assert result.tiebreakers == (13, 11, 9, 5, 3)

    def test_high_card_comparison_first_kicker(self) -> None:
        higher = evaluate_hand([(14, H), (10, D), (7, C), (4, S), (2, H)])
        lower = evaluate_hand([(13, H), (10, D), (7, C), (4, S), (2, D)])
        assert higher > lower

    def test_high_card_comparison_second_kicker(self) -> None:
        higher = evaluate_hand([(14, H), (13, D), (7, C), (4, S), (2, H)])
        lower = evaluate_hand([(14, D), (12, D), (7, S), (4, C), (2, D)])
        assert higher > lower


# =========================================================================
# ONE PAIR
# =========================================================================


class TestOnePair:
    def test_pair_of_aces(self) -> None:
        hand = [(14, H), (14, D), (10, C), (7, S), (3, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.ONE_PAIR
        assert result.tiebreakers == (14, 10, 7, 3)

    def test_pair_of_twos(self) -> None:
        hand = [(2, H), (2, D), (14, C), (13, S), (12, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.ONE_PAIR
        assert result.tiebreakers == (2, 14, 13, 12)

    def test_pair_comparison_higher_pair_wins(self) -> None:
        aces = evaluate_hand([(14, H), (14, D), (5, C), (4, S), (3, H)])
        kings = evaluate_hand([(13, H), (13, D), (12, C), (11, S), (10, H)])
        assert aces > kings

    def test_pair_comparison_kicker_decides(self) -> None:
        higher = evaluate_hand([(10, H), (10, D), (14, C), (7, S), (3, H)])
        lower = evaluate_hand([(10, C), (10, S), (13, C), (7, H), (3, D)])
        assert higher > lower


# =========================================================================
# TWO PAIR
# =========================================================================


class TestTwoPair:
    def test_aces_and_kings(self) -> None:
        hand = [(14, H), (14, D), (13, C), (13, S), (7, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.TWO_PAIR
        assert result.tiebreakers == (14, 13, 7)

    def test_tens_and_fives(self) -> None:
        hand = [(10, H), (10, D), (5, C), (5, S), (14, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.TWO_PAIR
        assert result.tiebreakers == (10, 5, 14)

    def test_two_pair_higher_high_pair_wins(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (3, C), (3, S), (2, H)])
        lower = evaluate_hand([(13, H), (13, D), (12, C), (12, S), (14, H)])
        assert higher > lower

    def test_two_pair_same_high_pair_low_pair_decides(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (13, C), (13, S), (2, H)])
        lower = evaluate_hand([(14, C), (14, S), (12, C), (12, S), (13, H)])
        assert higher > lower

    def test_two_pair_same_pairs_kicker_decides(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (13, C), (13, S), (10, H)])
        lower = evaluate_hand([(14, C), (14, S), (13, H), (13, D), (9, H)])
        assert higher > lower


# =========================================================================
# THREE OF A KIND
# =========================================================================


class TestThreeOfAKind:
    def test_trip_aces(self) -> None:
        hand = [(14, H), (14, D), (14, C), (7, S), (3, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.THREE_OF_A_KIND
        assert result.tiebreakers == (14, 7, 3)

    def test_trip_fives(self) -> None:
        hand = [(5, H), (5, D), (5, C), (14, S), (13, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.THREE_OF_A_KIND
        assert result.tiebreakers == (5, 14, 13)

    def test_trips_comparison_higher_triple_wins(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (14, C), (3, S), (2, H)])
        lower = evaluate_hand([(13, H), (13, D), (13, C), (14, S), (12, H)])
        assert higher > lower


# =========================================================================
# STRAIGHT
# =========================================================================


class TestStraight:
    def test_ace_high_straight(self) -> None:
        hand = [(14, H), (13, D), (12, C), (11, S), (10, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT
        assert result.tiebreakers == (14,)

    def test_ace_low_straight_wheel(self) -> None:
        hand = [(14, H), (2, D), (3, C), (4, S), (5, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT
        assert result.tiebreakers == (5,)

    def test_middle_straight(self) -> None:
        hand = [(8, H), (7, D), (6, C), (5, S), (4, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT
        assert result.tiebreakers == (8,)

    def test_straight_comparison_higher_wins(self) -> None:
        higher = evaluate_hand([(14, H), (13, D), (12, C), (11, S), (10, H)])
        lower = evaluate_hand([(13, H), (12, D), (11, C), (10, S), (9, D)])
        assert higher > lower

    def test_ace_low_straight_loses_to_six_high(self) -> None:
        wheel = evaluate_hand([(14, H), (2, D), (3, C), (4, S), (5, H)])
        six_high = evaluate_hand([(6, H), (5, D), (4, C), (3, S), (2, D)])
        assert six_high > wheel

    def test_straight_not_flush(self) -> None:
        """Mixed suits should be straight, not flush."""
        hand = [(10, H), (9, D), (8, C), (7, S), (6, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT


# =========================================================================
# FLUSH
# =========================================================================


class TestFlush:
    def test_flush_hearts(self) -> None:
        hand = [(14, H), (10, H), (7, H), (4, H), (2, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FLUSH
        assert result.tiebreakers == (14, 10, 7, 4, 2)

    def test_flush_spades(self) -> None:
        hand = [(13, S), (11, S), (9, S), (5, S), (3, S)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FLUSH
        assert result.tiebreakers == (13, 11, 9, 5, 3)

    def test_flush_comparison_first_card(self) -> None:
        higher = evaluate_hand([(14, H), (10, H), (7, H), (4, H), (2, H)])
        lower = evaluate_hand([(13, S), (12, S), (11, S), (10, S), (8, S)])
        assert higher > lower

    def test_flush_comparison_kicker_decides(self) -> None:
        higher = evaluate_hand([(14, H), (13, H), (12, H), (11, H), (9, H)])
        lower = evaluate_hand([(14, D), (13, D), (12, D), (11, D), (8, D)])
        assert higher > lower


# =========================================================================
# FULL HOUSE
# =========================================================================


class TestFullHouse:
    def test_aces_full_of_kings(self) -> None:
        hand = [(14, H), (14, D), (14, C), (13, S), (13, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FULL_HOUSE
        assert result.tiebreakers == (14, 13)

    def test_twos_full_of_threes(self) -> None:
        hand = [(2, H), (2, D), (2, C), (3, S), (3, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FULL_HOUSE
        assert result.tiebreakers == (2, 3)

    def test_full_house_higher_triple_wins(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (14, C), (2, S), (2, H)])
        lower = evaluate_hand([(13, H), (13, D), (13, C), (14, S), (14, D)])
        assert higher > lower

    def test_full_house_same_triple_higher_pair_wins(self) -> None:
        higher = evaluate_hand([(10, H), (10, D), (10, C), (9, S), (9, H)])
        lower = evaluate_hand([(10, S), (10, C), (10, H), (8, S), (8, D)])
        assert higher > lower


# =========================================================================
# FOUR OF A KIND
# =========================================================================


class TestFourOfAKind:
    def test_quad_aces(self) -> None:
        hand = [(14, H), (14, D), (14, C), (14, S), (13, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FOUR_OF_A_KIND
        assert result.tiebreakers == (14, 13)

    def test_quad_twos(self) -> None:
        hand = [(2, H), (2, D), (2, C), (2, S), (14, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.FOUR_OF_A_KIND
        assert result.tiebreakers == (2, 14)

    def test_quads_comparison_higher_quad_wins(self) -> None:
        higher = evaluate_hand([(14, H), (14, D), (14, C), (14, S), (2, H)])
        lower = evaluate_hand([(13, H), (13, D), (13, C), (13, S), (14, H)])
        assert higher > lower

    def test_quads_same_rank_kicker_decides(self) -> None:
        higher = evaluate_hand([(10, H), (10, D), (10, C), (10, S), (14, H)])
        lower = evaluate_hand([(10, H), (10, D), (10, C), (10, S), (13, D)])
        assert higher > lower


# =========================================================================
# STRAIGHT FLUSH
# =========================================================================


class TestStraightFlush:
    def test_nine_high_straight_flush(self) -> None:
        hand = [(9, H), (8, H), (7, H), (6, H), (5, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT_FLUSH
        assert result.tiebreakers == (9,)

    def test_five_high_straight_flush_wheel(self) -> None:
        hand = [(14, D), (2, D), (3, D), (4, D), (5, D)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT_FLUSH
        assert result.tiebreakers == (5,)

    def test_straight_flush_comparison(self) -> None:
        higher = evaluate_hand([(13, S), (12, S), (11, S), (10, S), (9, S)])
        lower = evaluate_hand([(9, H), (8, H), (7, H), (6, H), (5, H)])
        assert higher > lower


# =========================================================================
# ROYAL FLUSH
# =========================================================================


class TestRoyalFlush:
    def test_royal_flush_hearts(self) -> None:
        hand = [(14, H), (13, H), (12, H), (11, H), (10, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.ROYAL_FLUSH
        assert result.tiebreakers == ()

    def test_royal_flush_spades(self) -> None:
        hand = [(14, S), (13, S), (12, S), (11, S), (10, S)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.ROYAL_FLUSH

    def test_royal_flush_beats_straight_flush(self) -> None:
        royal = evaluate_hand([(14, H), (13, H), (12, H), (11, H), (10, H)])
        sf = evaluate_hand([(13, S), (12, S), (11, S), (10, S), (9, S)])
        assert royal > sf

    def test_royal_flushes_are_equal(self) -> None:
        hearts = evaluate_hand([(14, H), (13, H), (12, H), (11, H), (10, H)])
        spades = evaluate_hand([(14, S), (13, S), (12, S), (11, S), (10, S)])
        assert hearts == spades


# =========================================================================
# CROSS-RANK COMPARISONS
# =========================================================================


class TestCrossRankOrdering:
    """Verify the strict ordering between all adjacent hand ranks."""

    def test_pair_beats_high_card(self) -> None:
        pair = evaluate_hand([(2, H), (2, D), (3, C), (4, S), (5, H)])
        high = evaluate_hand([(14, H), (13, D), (12, C), (11, S), (9, H)])
        assert pair > high

    def test_two_pair_beats_pair(self) -> None:
        two_pair = evaluate_hand([(2, H), (2, D), (3, C), (3, S), (4, H)])
        pair = evaluate_hand([(14, H), (14, D), (13, C), (12, S), (11, H)])
        assert two_pair > pair

    def test_trips_beats_two_pair(self) -> None:
        trips = evaluate_hand([(2, H), (2, D), (2, C), (3, S), (4, H)])
        two_pair = evaluate_hand([(14, H), (14, D), (13, C), (13, S), (12, H)])
        assert trips > two_pair

    def test_straight_beats_trips(self) -> None:
        straight = evaluate_hand([(5, H), (4, D), (3, C), (2, S), (14, H)])
        trips = evaluate_hand([(14, D), (14, C), (14, S), (13, H), (12, D)])
        assert straight > trips

    def test_flush_beats_straight(self) -> None:
        flush = evaluate_hand([(2, H), (4, H), (6, H), (8, H), (10, H)])
        straight = evaluate_hand([(14, H), (13, D), (12, C), (11, S), (10, D)])
        assert flush > straight

    def test_full_house_beats_flush(self) -> None:
        fh = evaluate_hand([(2, H), (2, D), (2, C), (3, S), (3, H)])
        flush = evaluate_hand([(14, H), (13, H), (12, H), (11, H), (9, H)])
        assert fh > flush

    def test_quads_beats_full_house(self) -> None:
        quads = evaluate_hand([(2, H), (2, D), (2, C), (2, S), (3, H)])
        fh = evaluate_hand([(14, H), (14, D), (14, C), (13, S), (13, H)])
        assert quads > fh

    def test_straight_flush_beats_quads(self) -> None:
        sf = evaluate_hand([(5, H), (4, H), (3, H), (2, H), (14, H)])
        quads = evaluate_hand([(14, D), (14, C), (14, S), (14, H), (13, D)])
        assert sf > quads

    def test_royal_flush_beats_quads(self) -> None:
        royal = evaluate_hand([(14, H), (13, H), (12, H), (11, H), (10, H)])
        quads = evaluate_hand([(14, D), (14, C), (14, S), (14, H), (13, D)])
        assert royal > quads


# =========================================================================
# BEST HAND (7-CARD SELECTION)
# =========================================================================


class TestBestHand:
    def test_selects_flush_over_pair(self) -> None:
        """7 cards contain a flush and a pair; flush should win."""
        cards = [
            (14, H), (10, H), (7, H), (4, H), (2, H),  # flush
            (14, D),  # makes pair of aces, but flush is better
            (3, C),
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.FLUSH

    def test_selects_straight_from_seven(self) -> None:
        cards = [
            (10, H), (9, D), (8, C), (7, S), (6, H),  # straight
            (2, D), (3, C),
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.STRAIGHT
        assert result.tiebreakers == (10,)

    def test_selects_full_house_from_seven(self) -> None:
        cards = [
            (14, H), (14, D), (14, C),  # trip aces
            (13, S), (13, H),           # pair of kings
            (7, D), (2, C),
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.FULL_HOUSE
        assert result.tiebreakers == (14, 13)

    def test_selects_best_two_pair(self) -> None:
        """From 3 pairs in 7 cards, picks the best two pair + kicker."""
        cards = [
            (14, H), (14, D),  # pair of aces
            (13, C), (13, S),  # pair of kings
            (5, H), (5, D),   # pair of fives
            (10, C),           # kicker
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.TWO_PAIR
        # Best is aces and kings with 10 kicker
        assert result.tiebreakers == (14, 13, 10)

    def test_selects_royal_flush_from_seven(self) -> None:
        cards = [
            (14, S), (13, S), (12, S), (11, S), (10, S),  # royal flush
            (2, H), (3, D),
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.ROYAL_FLUSH

    def test_hole_cards_improve_community(self) -> None:
        """Hole cards complete a straight that community alone doesn't have."""
        # Community: 8, 9, 10, K, 2
        # Hole: J, Q -> best straight is 9-10-J-Q-K (king high)
        cards = [
            (11, H), (12, D),          # hole cards
            (8, C), (9, S), (10, H),   # community part of straight
            (13, D), (2, C),           # community noise
        ]
        result = best_hand(cards)
        assert result.rank == HandRank.STRAIGHT
        assert result.tiebreakers == (13,)


# =========================================================================
# EDGE CASES AND VALIDATION
# =========================================================================


class TestEdgeCases:
    def test_evaluate_rejects_four_cards(self) -> None:
        with pytest.raises(ValueError, match="Expected 5 cards"):
            evaluate_hand([(14, H), (13, H), (12, H), (11, H)])

    def test_evaluate_rejects_six_cards(self) -> None:
        with pytest.raises(ValueError, match="Expected 5 cards"):
            evaluate_hand([(14, H), (13, H), (12, H), (11, H), (10, H), (9, H)])

    def test_best_hand_rejects_six_cards(self) -> None:
        with pytest.raises(ValueError, match="Expected 7 cards"):
            best_hand([(14, H), (13, H), (12, H), (11, H), (10, H), (9, H)])

    def test_best_hand_rejects_eight_cards(self) -> None:
        with pytest.raises(ValueError, match="Expected 7 cards"):
            best_hand([(14, H), (13, H), (12, H), (11, H), (10, H), (9, H), (8, H), (7, H)])

    def test_equal_hands_are_equal(self) -> None:
        a = evaluate_hand([(14, H), (13, D), (12, C), (11, S), (9, H)])
        b = evaluate_hand([(14, S), (13, C), (12, D), (11, H), (9, D)])
        assert a == b

    def test_ace_low_straight_flush(self) -> None:
        """A-2-3-4-5 all same suit is a straight flush, not a royal flush."""
        hand = [(14, C), (2, C), (3, C), (4, C), (5, C)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.STRAIGHT_FLUSH
        assert result.tiebreakers == (5,)

    def test_near_straight_not_straight(self) -> None:
        """Four consecutive ranks plus a gap is not a straight."""
        hand = [(10, H), (9, D), (8, C), (7, S), (5, H)]
        result = evaluate_hand(hand)
        assert result.rank == HandRank.HIGH_CARD
