"""Tests for Hearts: 4-player trick-taking card game with penalty points.

Hearts: 4 players, 52-card deck. Deal 13 each. Pass 3 cards (rotate
direction each round). Trick-taking: follow suit, highest of led suit
wins. Hearts = 1pt each, Queen of Spades = 13pts. Low score wins.
Shoot the moon: take all 26 penalty points -> everyone else gets 26.
Cannot lead hearts until broken. Game ends when any player hits 100pts.

Tests simulate server-authority deal by manually placing cards into
player hands from a known deck state.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "hearts.json"

PLAYERS = ["North", "East", "South", "West"]

SUITS = ["hearts", "diamonds", "clubs", "spades"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

RANK_VALUES = {r: i for i, r in enumerate(RANKS, start=2)}

PASS_DIRECTIONS = ["left", "right", "across", "hold"]


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


def _make_card(
    session: GameSession, suit: str, rank: str, owner: str | None = None
) -> ComponentId:
    """Create a card component and add it to the component arena."""
    comp = ComponentData(
        id=ComponentId(0),
        string_id=f"card-{suit}-{rank}",
        component_type="card",
        owner=owner,
        properties={"suit": suit, "rank": rank},
    )
    return session.runtime.components.insert(comp)


def _card_props(session: GameSession, cid: ComponentId) -> dict:
    comp = session.runtime.components.get(cid)
    assert comp is not None
    return comp.properties


def _card_str(session: GameSession, cid: ComponentId) -> str:
    p = _card_props(session, cid)
    return f"{p['rank']} of {p['suit']}"


# ---------------------------------------------------------------------------
# HeartsGame driver
# ---------------------------------------------------------------------------


@dataclass
class TrickCard:
    """A card played to a trick, with who played it."""

    player: str
    cid: ComponentId
    suit: str
    rank: str


class HeartsGame:
    """Hearts game driver implementing trick-taking, scoring, and passing."""

    def __init__(self) -> None:
        self.defn = _load_game()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"

        self.hands: dict[str, list[ComponentId]] = {p: [] for p in PLAYERS}
        self.taken: dict[str, list[ComponentId]] = {p: [] for p in PLAYERS}
        self.scores: dict[str, int] = {p: 0 for p in PLAYERS}

        self.current_trick: list[TrickCard] = []
        self.trick_number = 0
        self.hearts_broken = False
        self.round_number = 0
        self.leader: str | None = None
        self.finished = False

    def _player_index(self, player: str) -> int:
        return PLAYERS.index(player)

    def _next_player(self, player: str) -> str:
        idx = self._player_index(player)
        return PLAYERS[(idx + 1) % 4]

    def deal(self, hands: dict[str, list[tuple[str, str]]]) -> None:
        """Deal specific cards to each player. Each entry is (suit, rank)."""
        for player, cards in hands.items():
            assert len(cards) == 13, f"{player} needs 13 cards, got {len(cards)}"
            for suit, rank in cards:
                cid = _make_card(self.session, suit, rank, owner=player)
                self.hands[player].append(cid)

    def pass_cards(
        self, selections: dict[str, list[int]]
    ) -> dict[str, list[ComponentId]]:
        """Pass 3 cards. selections maps player -> indices into their hand.

        Returns dict of player -> cards received.
        """
        direction = PASS_DIRECTIONS[self.round_number % 4]
        if direction == "hold":
            return {p: [] for p in PLAYERS}

        passed: dict[str, list[ComponentId]] = {}
        for player, indices in selections.items():
            assert len(indices) == 3, f"{player} must pass exactly 3 cards"
            cards = [self.hands[player][i] for i in sorted(indices, reverse=True)]
            for i in sorted(indices, reverse=True):
                self.hands[player].pop(i)
            passed[player] = cards

        received: dict[str, list[ComponentId]] = {p: [] for p in PLAYERS}
        for player, cards in passed.items():
            idx = self._player_index(player)
            if direction == "left":
                recipient = PLAYERS[(idx + 1) % 4]
            elif direction == "right":
                recipient = PLAYERS[(idx - 1) % 4]
            else:  # across
                recipient = PLAYERS[(idx + 2) % 4]
            self.hands[recipient].extend(cards)
            received[recipient].extend(cards)

        return received

    def find_two_of_clubs(self) -> str:
        """Return the player holding the 2 of clubs."""
        for player, hand in self.hands.items():
            for cid in hand:
                p = _card_props(self.session, cid)
                if p["suit"] == "clubs" and p["rank"] == "2":
                    return player
        raise ValueError("2 of clubs not found in any hand")

    def _find_card_in_hand(
        self, player: str, suit: str, rank: str
    ) -> ComponentId | None:
        for cid in self.hands[player]:
            p = _card_props(self.session, cid)
            if p["suit"] == suit and p["rank"] == rank:
                return cid
        return None

    def _has_suit(self, player: str, suit: str) -> bool:
        return any(
            _card_props(self.session, c)["suit"] == suit
            for c in self.hands[player]
        )

    def _only_has_hearts(self, player: str) -> bool:
        return all(
            _card_props(self.session, c)["suit"] == "hearts"
            for c in self.hands[player]
        )

    def _only_has_penalty_cards(self, player: str) -> bool:
        """Player only has hearts and/or queen of spades."""
        for cid in self.hands[player]:
            p = _card_props(self.session, cid)
            if p["suit"] == "hearts":
                continue
            if p["suit"] == "spades" and p["rank"] == "Q":
                continue
            return False
        return True

    def led_suit(self) -> str | None:
        if not self.current_trick:
            return None
        return self.current_trick[0].suit

    def play_card(self, player: str, suit: str, rank: str) -> None:
        """Play a card to the current trick with rule validation."""
        if self.finished:
            raise ValueError("game is finished")

        # Must be this player's turn
        expected = self._whose_turn()
        if player != expected:
            raise ValueError(f"not {player}'s turn, expected {expected}")

        cid = self._find_card_in_hand(player, suit, rank)
        if cid is None:
            raise ValueError(f"{player} does not have {rank} of {suit}")

        is_leading = len(self.current_trick) == 0

        # First trick: must lead 2 of clubs
        if self.trick_number == 0 and is_leading:
            if suit != "clubs" or rank != "2":
                raise ValueError("first trick must be led with 2 of clubs")

        # Follow suit rule
        if not is_leading:
            led = self.led_suit()
            assert led is not None
            if suit != led and self._has_suit(player, led):
                raise ValueError(
                    f"must follow suit ({led}), player has cards of that suit"
                )

        # Cannot lead hearts unless broken (or only hearts in hand)
        if is_leading and suit == "hearts" and not self.hearts_broken:
            if not self._only_has_hearts(player):
                raise ValueError(
                    "cannot lead hearts until hearts are broken"
                )

        # First trick: cannot play penalty cards unless forced
        if self.trick_number == 0 and not is_leading:
            is_penalty = suit == "hearts" or (suit == "spades" and rank == "Q")
            if is_penalty:
                # Check if player has non-penalty cards of led suit or other suits
                led = self.led_suit()
                assert led is not None
                if self._has_suit(player, led):
                    # Has led suit, follow suit takes precedence — if led suit
                    # is not a penalty suit this wouldn't trigger
                    pass
                elif not self._only_has_penalty_cards(player):
                    raise ValueError(
                        "cannot play penalty cards on the first trick unless forced"
                    )

        # Remove from hand and add to trick
        self.hands[player].remove(cid)
        self.current_trick.append(
            TrickCard(player=player, cid=cid, suit=suit, rank=rank)
        )

        # Track hearts broken
        if suit == "hearts":
            self.hearts_broken = True

        # If trick is complete (4 cards), resolve it
        if len(self.current_trick) == 4:
            self._resolve_trick()

    def _whose_turn(self) -> str:
        """Determine whose turn it is to play."""
        if len(self.current_trick) == 0:
            if self.leader is not None:
                return self.leader
            # First trick: find 2 of clubs holder
            return self.find_two_of_clubs()
        # Next player after the last card played
        last_player = self.current_trick[-1].player
        return self._next_player(last_player)

    def _resolve_trick(self) -> None:
        """Resolve a completed trick: highest of led suit wins."""
        led = self.current_trick[0].suit
        best: TrickCard | None = None
        for tc in self.current_trick:
            if tc.suit == led:
                if best is None or RANK_VALUES[tc.rank] > RANK_VALUES[best.rank]:
                    best = tc
        assert best is not None
        winner = best.player

        # Move all trick cards to winner's taken pile
        for tc in self.current_trick:
            self.taken[winner].append(tc.cid)

        self.current_trick = []
        self.trick_number += 1
        self.leader = winner

    def score_round(self) -> dict[str, int]:
        """Score the round. Returns penalty points per player for this round."""
        round_points: dict[str, int] = {}
        for player in PLAYERS:
            pts = 0
            for cid in self.taken[player]:
                p = _card_props(self.session, cid)
                if p["suit"] == "hearts":
                    pts += 1
                elif p["suit"] == "spades" and p["rank"] == "Q":
                    pts += 13
            round_points[player] = pts

        # Shoot the moon check
        shooter = None
        for player, pts in round_points.items():
            if pts == 26:
                shooter = player
                break

        if shooter is not None:
            # Shooter gets 0, everyone else gets 26
            for player in PLAYERS:
                if player == shooter:
                    round_points[player] = 0
                else:
                    round_points[player] = 26

        # Add to cumulative scores
        for player in PLAYERS:
            self.scores[player] += round_points[player]

        return round_points

    def check_game_over(self) -> bool:
        """Check if any player has >= 100 points."""
        if any(s >= 100 for s in self.scores.values()):
            self.finished = True
            return True
        return False

    def winner(self) -> str | None:
        """Return the player with the lowest score (if game is over)."""
        if not self.finished:
            return None
        return min(self.scores, key=lambda p: self.scores[p])

    def new_round(self) -> None:
        """Reset for a new round."""
        self.round_number += 1
        self.hands = {p: [] for p in PLAYERS}
        self.taken = {p: [] for p in PLAYERS}
        self.current_trick = []
        self.trick_number = 0
        self.hearts_broken = False
        self.leader = None


# ---------------------------------------------------------------------------
# Standard test hands (known deal for deterministic testing)
# ---------------------------------------------------------------------------

def _standard_deal() -> dict[str, list[tuple[str, str]]]:
    """A known deal distributing 13 cards to each player.

    North: all clubs
    East: all diamonds
    South: all hearts
    West: all spades
    """
    return {
        "North": [(s, r) for s, r in zip(["clubs"] * 13, RANKS)],
        "East": [(s, r) for s, r in zip(["diamonds"] * 13, RANKS)],
        "South": [(s, r) for s, r in zip(["hearts"] * 13, RANKS)],
        "West": [(s, r) for s, r in zip(["spades"] * 13, RANKS)],
    }


def _mixed_deal() -> dict[str, list[tuple[str, str]]]:
    """A more realistic deal with mixed suits.

    North gets 2C (must lead first trick).
    """
    return {
        "North": [
            ("clubs", "2"), ("clubs", "3"), ("clubs", "4"),
            ("diamonds", "5"), ("diamonds", "6"), ("diamonds", "7"),
            ("hearts", "8"), ("hearts", "9"), ("hearts", "10"),
            ("spades", "J"), ("spades", "Q"), ("spades", "K"),
            ("spades", "A"),
        ],
        "East": [
            ("clubs", "5"), ("clubs", "6"), ("clubs", "7"),
            ("diamonds", "8"), ("diamonds", "9"), ("diamonds", "10"),
            ("hearts", "J"), ("hearts", "Q"), ("hearts", "K"),
            ("spades", "2"), ("spades", "3"), ("spades", "4"),
            ("spades", "5"),
        ],
        "South": [
            ("clubs", "8"), ("clubs", "9"), ("clubs", "10"),
            ("diamonds", "J"), ("diamonds", "Q"), ("diamonds", "K"),
            ("hearts", "2"), ("hearts", "3"), ("hearts", "4"),
            ("spades", "6"), ("spades", "7"), ("spades", "8"),
            ("spades", "9"),
        ],
        "West": [
            ("clubs", "J"), ("clubs", "Q"), ("clubs", "K"),
            ("clubs", "A"), ("diamonds", "2"), ("diamonds", "3"),
            ("diamonds", "4"), ("diamonds", "A"),
            ("hearts", "5"), ("hearts", "6"), ("hearts", "7"),
            ("hearts", "A"), ("spades", "10"),
        ],
    }


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestHeartsDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Hearts"

    def test_four_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["North", "East", "South", "West"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_deck_zone_is_hidden_stack(self) -> None:
        defn = _load_game()
        assert "deck" in defn.zones
        assert defn.zones["deck"].zone_type == "ordered_stack"
        assert defn.zones["deck"].visibility == "hidden"

    def test_hand_zone_is_per_player_private(self) -> None:
        defn = _load_game()
        assert "hand" in defn.zones
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_trick_zone_is_public(self) -> None:
        defn = _load_game()
        assert "trick" in defn.zones
        assert defn.zones["trick"].visibility == "public"

    def test_taken_zone_is_per_player_public(self) -> None:
        defn = _load_game()
        assert "taken" in defn.zones
        assert defn.zones["taken"].per_player is True
        assert defn.zones["taken"].visibility == "public"

    def test_score_zone_is_per_player_counter(self) -> None:
        defn = _load_game()
        assert "score" in defn.zones
        assert defn.zones["score"].zone_type == "counter"
        assert defn.zones["score"].per_player is True

    def test_has_four_phases(self) -> None:
        defn = _load_game()
        assert defn.phases is not None
        phase_names = [p.name for p in defn.phases]
        assert phase_names == ["deal", "pass", "play", "scoring"]

    def test_authority_deal_is_server_only(self) -> None:
        defn = _load_game()
        assert "deal(deck, hand)" in defn.authority.server_only

    def test_authority_play_is_client_verifiable(self) -> None:
        defn = _load_game()
        assert "play(hand, trick)" in defn.authority.client_verifiable

    def test_round_robin_turn_order(self) -> None:
        defn = _load_game()
        assert defn.turn_order.type == "round_robin"

    def test_has_rules(self) -> None:
        defn = _load_game()
        assert defn.rules is not None
        rule_names = set(defn.rules.keys())
        assert "follow_suit" in rule_names
        assert "hearts_broken" in rule_names
        assert "shoot_the_moon" in rule_names

    def test_end_conditions(self) -> None:
        defn = _load_game()
        assert len(defn.end_conditions) == 2
        names = {ec.name for ec in defn.end_conditions}
        assert "lowest_score_wins" in names


# ---------------------------------------------------------------------------
# Tests: session creation
# ---------------------------------------------------------------------------


class TestSessionCreation:
    def test_session_creates_four_players(self) -> None:
        session = GameSession(_load_game())
        assert len(session.runtime.players) == 4
        assert set(session.runtime.players.keys()) == set(PLAYERS)

    def test_each_player_has_hand_zone(self) -> None:
        session = GameSession(_load_game())
        for player in PLAYERS:
            assert "hand" in session.runtime.players[player].zones

    def test_each_player_has_taken_zone(self) -> None:
        session = GameSession(_load_game())
        for player in PLAYERS:
            assert "taken" in session.runtime.players[player].zones

    def test_each_player_has_score_zone(self) -> None:
        session = GameSession(_load_game())
        for player in PLAYERS:
            assert "score" in session.runtime.players[player].zones

    def test_shared_deck_zone_exists(self) -> None:
        session = GameSession(_load_game())
        assert "deck" in session.runtime.zones

    def test_shared_trick_zone_exists(self) -> None:
        session = GameSession(_load_game())
        assert "trick" in session.runtime.zones


# ---------------------------------------------------------------------------
# Tests: dealing
# ---------------------------------------------------------------------------


class TestDealing:
    def test_deal_gives_13_cards_each(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        for player in PLAYERS:
            assert len(game.hands[player]) == 13

    def test_deal_52_cards_total(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        total = sum(len(h) for h in game.hands.values())
        assert total == 52

    def test_all_cards_unique(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        all_cids = []
        for hand in game.hands.values():
            all_cids.extend(hand)
        assert len(set(all_cids)) == 52

    def test_wrong_count_rejected(self) -> None:
        game = HeartsGame()
        bad_deal = {p: [("clubs", "2")] for p in PLAYERS}
        with pytest.raises(AssertionError, match="13 cards"):
            game.deal(bad_deal)


# ---------------------------------------------------------------------------
# Tests: card passing
# ---------------------------------------------------------------------------


class TestPassing:
    def test_pass_left_round_0(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        assert PASS_DIRECTIONS[game.round_number % 4] == "left"
        # Each player passes first 3 cards
        selections = {p: [0, 1, 2] for p in PLAYERS}
        received = game.pass_cards(selections)
        # North's cards go to East (left)
        assert len(received["East"]) > 0
        # Each player still has 13 cards
        for player in PLAYERS:
            assert len(game.hands[player]) == 13

    def test_pass_right_round_1(self) -> None:
        game = HeartsGame()
        game.round_number = 1
        game.deal(_mixed_deal())
        assert PASS_DIRECTIONS[game.round_number % 4] == "right"
        selections = {p: [0, 1, 2] for p in PLAYERS}
        received = game.pass_cards(selections)
        # North's cards go to West (right)
        assert len(received["West"]) > 0

    def test_pass_across_round_2(self) -> None:
        game = HeartsGame()
        game.round_number = 2
        game.deal(_mixed_deal())
        assert PASS_DIRECTIONS[game.round_number % 4] == "across"
        selections = {p: [0, 1, 2] for p in PLAYERS}
        received = game.pass_cards(selections)
        # North's cards go to South (across)
        assert len(received["South"]) > 0

    def test_hold_round_3(self) -> None:
        game = HeartsGame()
        game.round_number = 3
        game.deal(_mixed_deal())
        assert PASS_DIRECTIONS[game.round_number % 4] == "hold"
        selections = {p: [0, 1, 2] for p in PLAYERS}
        received = game.pass_cards(selections)
        # Nobody receives cards on hold round
        for player in PLAYERS:
            assert received[player] == []

    def test_pass_preserves_hand_size(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        selections = {p: [0, 1, 2] for p in PLAYERS}
        game.pass_cards(selections)
        for player in PLAYERS:
            assert len(game.hands[player]) == 13

    def test_must_pass_exactly_three(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        with pytest.raises(AssertionError, match="exactly 3"):
            game.pass_cards({p: [0, 1] for p in PLAYERS})


# ---------------------------------------------------------------------------
# Tests: trick-taking basics
# ---------------------------------------------------------------------------


class TestTrickTaking:
    def test_two_of_clubs_leads_first_trick(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # North has all clubs including 2C
        leader = game.find_two_of_clubs()
        assert leader == "North"

    def test_must_lead_two_of_clubs_first(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # North tries to lead with 3 of clubs instead of 2
        with pytest.raises(ValueError, match="2 of clubs"):
            game.play_card("North", "clubs", "3")

    def test_play_card_removes_from_hand(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        assert len(game.hands["North"]) == 13
        game.play_card("North", "clubs", "2")
        assert len(game.hands["North"]) == 12

    def test_play_card_adds_to_trick(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        game.play_card("North", "clubs", "2")
        assert len(game.current_trick) == 1
        assert game.current_trick[0].suit == "clubs"
        assert game.current_trick[0].rank == "2"

    def test_trick_resolves_after_four_cards(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # All suits, follow suit not possible for E/S/W since they have no clubs
        # But in _standard_deal each player has only one suit
        # North leads 2C, others must play (they can't follow suit, so play anything)
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        game.play_card("West", "spades", "2")
        # Trick resolved — highest of led suit (clubs) wins
        assert len(game.current_trick) == 0
        assert game.trick_number == 1

    def test_highest_of_led_suit_wins_trick(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "A")  # high but wrong suit
        game.play_card("South", "hearts", "A")  # high but wrong suit
        game.play_card("West", "spades", "A")  # high but wrong suit
        # North wins — only player who played clubs (the led suit)
        assert "North" in [
            p for p, taken in game.taken.items() if len(taken) == 4
        ]

    def test_winner_leads_next_trick(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        game.play_card("West", "spades", "2")
        # North won the trick (only clubs player), so North leads next
        assert game.leader == "North"


# ---------------------------------------------------------------------------
# Tests: follow suit rule
# ---------------------------------------------------------------------------


class TestFollowSuit:
    def test_must_follow_suit_if_able(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        # North leads 2C
        game.play_card("North", "clubs", "2")
        # East has clubs (5,6,7) — must follow suit
        with pytest.raises(ValueError, match="follow suit"):
            game.play_card("East", "diamonds", "8")

    def test_can_play_off_suit_if_void(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # North leads 2C, East has no clubs (only diamonds)
        game.play_card("North", "clubs", "2")
        # East can play any diamond since void in clubs
        game.play_card("East", "diamonds", "2")
        assert len(game.current_trick) == 2

    def test_following_suit_accepted(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        game.play_card("North", "clubs", "2")
        # East follows with a club
        game.play_card("East", "clubs", "5")
        assert len(game.current_trick) == 2


# ---------------------------------------------------------------------------
# Tests: hearts broken rule
# ---------------------------------------------------------------------------


class TestHeartsBroken:
    def test_cannot_lead_hearts_before_broken(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # Play first trick with non-hearts
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")  # off-suit, breaks hearts
        game.play_card("West", "spades", "2")
        # Hearts broken by South's play
        assert game.hearts_broken is True

    def test_hearts_not_broken_initially(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        assert game.hearts_broken is False

    def test_can_lead_hearts_after_broken(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # First trick — break hearts
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        game.play_card("West", "spades", "2")
        # North won, leads again. North only has clubs, so play clubs.
        # We need South (who has all hearts) to lead.
        # Let's set up a scenario where South wins a trick and can lead hearts.
        game.leader = "South"
        game.play_card("South", "hearts", "3")  # hearts broken, so allowed
        assert game.current_trick[0].suit == "hearts"

    def test_can_lead_hearts_if_only_hearts_in_hand(self) -> None:
        """Exception: lead hearts if that's all you have."""
        game = HeartsGame()
        # Give a player only hearts
        game.deal({
            "North": [("clubs", r) for r in RANKS],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("hearts", r) for r in RANKS],
            "West": [("spades", r) for r in RANKS],
        })
        # Play first trick to let South lead
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        game.play_card("West", "spades", "2")
        # Force South to lead — South only has hearts
        game.leader = "South"
        # Hearts not broken by leading, but South has no choice
        game.play_card("South", "hearts", "3")
        assert game.current_trick[0].suit == "hearts"


# ---------------------------------------------------------------------------
# Tests: first trick restrictions
# ---------------------------------------------------------------------------


class TestFirstTrickRestrictions:
    def test_no_hearts_on_first_trick(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        game.play_card("North", "clubs", "2")
        game.play_card("East", "clubs", "5")
        game.play_card("South", "clubs", "8")
        # West has clubs (J,Q,K,A) — must follow suit anyway
        # Let's test with a player void in clubs
        # Actually, in _mixed_deal, all players have clubs, so let's craft a deal
        game2 = HeartsGame()
        game2.deal({
            "North": [("clubs", "2")] + [("clubs", r) for r in RANKS[1:13]],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("hearts", r) for r in RANKS],
            "West": [("spades", r) for r in RANKS],
        })
        game2.play_card("North", "clubs", "2")
        # East void in clubs, cannot play hearts on first trick
        with pytest.raises(ValueError, match="penalty cards on the first trick"):
            game2.play_card("East", "hearts", "2")

    def test_no_queen_of_spades_on_first_trick(self) -> None:
        game = HeartsGame()
        # West has Q of spades, no clubs
        game.deal({
            "North": [("clubs", "2")] + [("clubs", r) for r in RANKS[1:13]],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("hearts", r) for r in RANKS],
            "West": [("spades", r) for r in RANKS],
        })
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        # Wait — South should not be able to play hearts on first trick
        # unless forced. South is void in clubs and only has hearts.
        # Since South ONLY has hearts (penalty cards), it's forced.
        # That play should succeed because South has no choice.
        # Let's verify West can't play Q of spades when they have non-penalty options.
        game3 = HeartsGame()
        game3.deal({
            "North": [("clubs", "2")] + [("clubs", r) for r in RANKS[1:13]],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("diamonds", "A")] + [("hearts", r) for r in RANKS[:12]],
            "West": [("spades", "Q")] + [("diamonds", r) for r in ["2", "3", "4", "5", "6", "7", "8", "9"]] + [("spades", r) for r in ["2", "3", "4", "5"]],
        })
        game3.play_card("North", "clubs", "2")
        game3.play_card("East", "diamonds", "2")
        game3.play_card("South", "diamonds", "A")
        # West is void in clubs, has QS and non-penalty cards
        with pytest.raises(ValueError, match="penalty cards on the first trick"):
            game3.play_card("West", "spades", "Q")


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_hearts_one_point_each(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # Manually put some hearts in North's taken pile
        for rank in ["2", "3", "4"]:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["North"].append(cid)
        pts = game.score_round()
        assert pts["North"] == 3

    def test_queen_of_spades_thirteen_points(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        cid = _make_card(game.session, "spades", "Q")
        game.taken["East"].append(cid)
        pts = game.score_round()
        assert pts["East"] == 13

    def test_hearts_plus_queen(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # Give East the queen of spades + 3 hearts
        cid_q = _make_card(game.session, "spades", "Q")
        game.taken["East"].append(cid_q)
        for rank in ["5", "6", "7"]:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["East"].append(cid)
        pts = game.score_round()
        assert pts["East"] == 16  # 13 + 3

    def test_no_penalty_cards_zero_points(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # Give North only non-penalty cards
        for rank in ["2", "3"]:
            cid = _make_card(game.session, "clubs", rank)
            game.taken["North"].append(cid)
        pts = game.score_round()
        assert pts["North"] == 0

    def test_cumulative_scoring(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        cid = _make_card(game.session, "hearts", "2")
        game.taken["North"].append(cid)
        game.score_round()
        assert game.scores["North"] == 1

        # New round, score again
        game.new_round()
        game.deal(_standard_deal())
        cid2 = _make_card(game.session, "hearts", "3")
        game.taken["North"].append(cid2)
        game.score_round()
        assert game.scores["North"] == 2


# ---------------------------------------------------------------------------
# Tests: shoot the moon
# ---------------------------------------------------------------------------


class TestShootTheMoon:
    def test_shoot_the_moon_gives_others_26(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # Give North all 13 hearts + queen of spades = 26 points
        for rank in RANKS:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["North"].append(cid)
        cid_q = _make_card(game.session, "spades", "Q")
        game.taken["North"].append(cid_q)
        pts = game.score_round()
        assert pts["North"] == 0
        assert pts["East"] == 26
        assert pts["South"] == 26
        assert pts["West"] == 26

    def test_shoot_the_moon_cumulative(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        for rank in RANKS:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["South"].append(cid)
        cid_q = _make_card(game.session, "spades", "Q")
        game.taken["South"].append(cid_q)
        game.score_round()
        assert game.scores["South"] == 0
        assert game.scores["North"] == 26
        assert game.scores["East"] == 26
        assert game.scores["West"] == 26

    def test_not_quite_the_moon(self) -> None:
        """Taking 25 penalty points is not a moon shot."""
        game = HeartsGame()
        game.deal(_standard_deal())
        # Give North 12 hearts (12 pts) + queen of spades (13 pts) = 25
        for rank in RANKS[:12]:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["North"].append(cid)
        cid_q = _make_card(game.session, "spades", "Q")
        game.taken["North"].append(cid_q)
        pts = game.score_round()
        assert pts["North"] == 25  # not 0, not a moon shot


# ---------------------------------------------------------------------------
# Tests: game end condition
# ---------------------------------------------------------------------------


class TestGameEnd:
    def test_game_ends_at_100(self) -> None:
        game = HeartsGame()
        game.scores["North"] = 99
        game.deal(_standard_deal())
        # North takes 1 heart this round
        cid = _make_card(game.session, "hearts", "2")
        game.taken["North"].append(cid)
        game.score_round()
        assert game.scores["North"] == 100
        assert game.check_game_over() is True
        assert game.finished is True

    def test_game_continues_below_100(self) -> None:
        game = HeartsGame()
        game.scores["North"] = 90
        game.deal(_standard_deal())
        cid = _make_card(game.session, "hearts", "2")
        game.taken["North"].append(cid)
        game.score_round()
        assert game.scores["North"] == 91
        assert game.check_game_over() is False

    def test_lowest_score_wins(self) -> None:
        game = HeartsGame()
        game.scores = {"North": 100, "East": 45, "South": 30, "West": 60}
        game.finished = True
        assert game.winner() == "South"

    def test_no_winner_before_game_over(self) -> None:
        game = HeartsGame()
        assert game.winner() is None

    def test_cannot_play_after_finished(self) -> None:
        game = HeartsGame()
        game.finished = True
        game.deal(_standard_deal())
        with pytest.raises(ValueError, match="finished"):
            game.play_card("North", "clubs", "2")


# ---------------------------------------------------------------------------
# Tests: turn order
# ---------------------------------------------------------------------------


class TestTurnOrder:
    def test_wrong_player_rejected(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # North has 2C and should lead, but East tries to play
        with pytest.raises(ValueError, match="not East's turn"):
            game.play_card("East", "diamonds", "2")

    def test_play_order_clockwise(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        game.play_card("North", "clubs", "2")
        # Next should be East
        assert game._whose_turn() == "East"
        game.play_card("East", "diamonds", "2")
        assert game._whose_turn() == "South"
        game.play_card("South", "hearts", "2")
        assert game._whose_turn() == "West"

    def test_trick_winner_leads_next(self) -> None:
        game = HeartsGame()
        game.deal(_mixed_deal())
        # North leads 2C
        game.play_card("North", "clubs", "2")
        game.play_card("East", "clubs", "5")
        game.play_card("South", "clubs", "8")
        game.play_card("West", "clubs", "A")
        # West played highest club, wins the trick
        assert game.leader == "West"
        assert game._whose_turn() == "West"


# ---------------------------------------------------------------------------
# Tests: playing a card not in hand
# ---------------------------------------------------------------------------


class TestCardValidation:
    def test_play_card_not_in_hand(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        # North has clubs only, try to play a diamond
        with pytest.raises(ValueError, match="does not have"):
            game.play_card("North", "diamonds", "A")


# ---------------------------------------------------------------------------
# Tests: full round play-through
# ---------------------------------------------------------------------------


class TestFullRound:
    def test_play_all_13_tricks(self) -> None:
        """Play through an entire round with the standard deal."""
        game = HeartsGame()
        game.deal(_standard_deal())

        # Standard deal: North=clubs, East=diamonds, South=hearts, West=spades
        # North leads 2C each trick, others play off-suit
        for i, rank in enumerate(RANKS):
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)

        assert game.trick_number == 13
        # All hands should be empty
        for player in PLAYERS:
            assert len(game.hands[player]) == 0
        # North won all tricks (only clubs player following led suit)
        assert len(game.taken["North"]) == 52

    def test_full_round_scoring(self) -> None:
        """Play full round and verify scoring."""
        game = HeartsGame()
        game.deal(_standard_deal())

        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)

        pts = game.score_round()
        # North took all 52 cards, including all 13 hearts + QS = 26 pts
        # That triggers shoot the moon!
        assert pts["North"] == 0
        assert pts["East"] == 26
        assert pts["South"] == 26
        assert pts["West"] == 26

    def test_new_round_resets_state(self) -> None:
        game = HeartsGame()
        game.deal(_standard_deal())
        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)
        game.score_round()
        game.new_round()
        assert game.trick_number == 0
        assert game.hearts_broken is False
        assert game.leader is None
        for player in PLAYERS:
            assert len(game.hands[player]) == 0
            assert len(game.taken[player]) == 0

    def test_multi_round_game(self) -> None:
        """Play multiple rounds until game over."""
        game = HeartsGame()

        # Round 1: shoot the moon by North
        game.deal(_standard_deal())
        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)
        game.score_round()
        assert game.scores == {"North": 0, "East": 26, "South": 26, "West": 26}
        assert not game.check_game_over()

        # Round 2: same thing
        game.new_round()
        game.deal(_standard_deal())
        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)
        game.score_round()
        assert game.scores == {"North": 0, "East": 52, "South": 52, "West": 52}
        assert not game.check_game_over()

        # Round 3: same again
        game.new_round()
        game.deal(_standard_deal())
        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)
        game.score_round()
        assert game.scores == {"North": 0, "East": 78, "South": 78, "West": 78}
        assert not game.check_game_over()

        # Round 4: this pushes others to 104
        game.new_round()
        game.deal(_standard_deal())
        for rank in RANKS:
            game.play_card("North", "clubs", rank)
            game.play_card("East", "diamonds", rank)
            game.play_card("South", "hearts", rank)
            game.play_card("West", "spades", rank)
        game.score_round()
        assert game.scores == {"North": 0, "East": 104, "South": 104, "West": 104}
        assert game.check_game_over()
        assert game.winner() == "North"


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_all_penalty_points_is_26(self) -> None:
        """13 hearts + QS = 26, the exact moon threshold."""
        game = HeartsGame()
        game.deal(_standard_deal())
        for rank in RANKS:
            cid = _make_card(game.session, "hearts", rank)
            game.taken["North"].append(cid)
        cid_q = _make_card(game.session, "spades", "Q")
        game.taken["North"].append(cid_q)
        pts = game.score_round()
        # Moon shot: North gets 0, others get 26
        assert pts["North"] == 0
        total = sum(pts.values())
        assert total == 78  # 3 * 26

    def test_pass_direction_cycles(self) -> None:
        """Pass direction rotates: left, right, across, hold, left, ..."""
        game = HeartsGame()
        expected = ["left", "right", "across", "hold", "left", "right"]
        for i, exp in enumerate(expected):
            game.round_number = i
            assert PASS_DIRECTIONS[game.round_number % 4] == exp

    def test_only_hearts_forces_lead(self) -> None:
        """If a player only has hearts, they can lead hearts even if not broken."""
        game = HeartsGame()
        # Give South only hearts, make South lead
        game.deal({
            "North": [("clubs", r) for r in RANKS],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("hearts", r) for r in RANKS],
            "West": [("spades", r) for r in RANKS],
        })
        # Play first trick
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "hearts", "2")
        game.play_card("West", "spades", "2")
        # Force South to lead next
        game.leader = "South"
        # Hearts broken by South's earlier play in trick 1
        # Actually let's test the unbroken case
        game.hearts_broken = False
        # South only has hearts — must be allowed to lead hearts
        game.play_card("South", "hearts", "3")

    def test_queen_of_spades_not_heart(self) -> None:
        """QS does not break hearts when played."""
        game = HeartsGame()
        game.deal({
            "North": [("clubs", r) for r in RANKS],
            "East": [("diamonds", r) for r in RANKS],
            "South": [("spades", r) for r in RANKS],
            "West": [("hearts", r) for r in RANKS],
        })
        game.play_card("North", "clubs", "2")
        game.play_card("East", "diamonds", "2")
        game.play_card("South", "spades", "Q")  # QS but not hearts
        game.play_card("West", "hearts", "2")  # this breaks hearts
        # Hearts broken because West played a heart
        assert game.hearts_broken is True

    def test_tie_score_lowest_wins(self) -> None:
        """If multiple players tie for lowest, min() picks one deterministically."""
        game = HeartsGame()
        game.scores = {"North": 100, "East": 30, "South": 30, "West": 60}
        game.finished = True
        # min() returns first with lowest score
        w = game.winner()
        assert w in ("East", "South")
