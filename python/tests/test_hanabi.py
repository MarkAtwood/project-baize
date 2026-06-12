"""Tests for Hanabi: cooperative card game with inverted visibility.

Hanabi is a cooperative game for 2-4 players (tested with 2). Players hold
cards that they CANNOT see — but every other player CAN see them. Players
give clues, play cards to build firework stacks (1-5 per color), or discard
to reclaim clue tokens.

50 cards in 5 colors (red, yellow, green, blue, white):
  - Three 1s, two 2s, two 3s, two 4s, one 5 per color.

Resources: 8 clue tokens (spend to give clue, regain on discard),
3 fuse tokens (lose one on misplay, game over at 0).

Win: complete all 5 firework stacks (score 25).
Lose: 3 fuses blown or deck runs out with incomplete stacks.

Key mechanic: inverted hand visibility — you see others' hands, not your own.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from baize.definition import GameDefinition, PrivateVisibility
from baize.runtime import (
    ComponentData,
    ComponentId,
    CounterZone,
    GameSession,
    SetZone,
    StackZone,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "hanabi.json"

COLORS = ["red", "yellow", "green", "blue", "white"]
# Card distribution per color: number -> count
DISTRIBUTION = {1: 3, 2: 2, 3: 2, 4: 2, 5: 1}
CARDS_PER_COLOR = sum(DISTRIBUTION.values())  # 10
TOTAL_CARDS = CARDS_PER_COLOR * len(COLORS)  # 50

MAX_CLUE_TOKENS = 8
MAX_FUSE_TOKENS = 3
HAND_SIZE = 5
PERFECT_SCORE = 25

FIREWORK_ZONES = {
    "red": "fireworks_red",
    "yellow": "fireworks_yellow",
    "green": "fireworks_green",
    "blue": "fireworks_blue",
    "white": "fireworks_white",
}


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# Clue data structure
# ---------------------------------------------------------------------------

@dataclass
class Clue:
    """A clue given to a player: all cards matching attribute=value."""
    target: str
    attribute: str  # "color" or "number"
    value: str | int
    matching_indices: list[int]  # indices in target's hand


# ---------------------------------------------------------------------------
# HanabiGame driver
# ---------------------------------------------------------------------------

class HanabiGame:
    """Hanabi game driver simulating server-authority card management."""

    def __init__(self, seed: int = 42) -> None:
        self.defn = _load_game()
        self.session = GameSession(self.defn)
        self.session.runtime.status = "in_progress"
        self.players = ["P1", "P2"]
        self.clue_tokens = MAX_CLUE_TOKENS
        self.fuse_tokens = MAX_FUSE_TOKENS
        self.fireworks: dict[str, list[int]] = {c: [] for c in COLORS}
        self.discard: list[tuple[str, int]] = []  # (color, number)
        self.deck: list[ComponentId] = []
        self.hands: dict[str, list[ComponentId]] = {p: [] for p in self.players}
        self.finished = False
        self.won = False
        self.score = 0
        self.clue_log: list[Clue] = []
        self.final_turns_remaining: int | None = None
        self._build_and_shuffle(seed)
        self._deal()

    def _build_and_shuffle(self, seed: int) -> None:
        """Build the 50-card deck and shuffle deterministically."""
        deck_zone = self.session.runtime.zones.get("deck")
        assert isinstance(deck_zone, StackZone)
        for color in COLORS:
            for number, count in DISTRIBUTION.items():
                for copy in range(count):
                    comp = ComponentData(
                        id=ComponentId(0),
                        string_id=f"card-{color}-{number}-{copy}",
                        component_type="card",
                        owner=None,
                        properties={"color": color, "number": number},
                    )
                    cid = self.session.runtime.components.insert(comp)
                    deck_zone.components.append(cid)
        self.deck = list(deck_zone.components)
        rng = random.Random(seed)
        rng.shuffle(self.deck)
        deck_zone.components = list(self.deck)

    def _deal(self) -> None:
        """Deal HAND_SIZE cards to each player."""
        for _ in range(HAND_SIZE):
            for player in self.players:
                self._draw_to_hand(player)

    def _draw_to_hand(self, player: str) -> ComponentId | None:
        """Draw a card from deck into player's hand. Returns None if deck empty."""
        deck_zone = self.session.runtime.zones["deck"]
        assert isinstance(deck_zone, StackZone)
        if not deck_zone.components:
            return None
        cid = deck_zone.components.pop()
        self.deck = list(deck_zone.components)

        # Add to player's hand zone
        player_hand = self.session.runtime.players[player].zones["hand"]
        assert isinstance(player_hand, SetZone)
        player_hand.set_add(cid)
        self.hands[player].append(cid)

        comp = self.session.runtime.components.get(cid)
        assert comp is not None
        comp.owner = player
        return cid

    def _card(self, cid: ComponentId) -> ComponentData:
        comp = self.session.runtime.components.get(cid)
        assert comp is not None
        return comp

    def _firework_top(self, color: str) -> int:
        """Top number of a firework stack, 0 if empty."""
        return self.fireworks[color][-1] if self.fireworks[color] else 0

    def _check_finished(self) -> None:
        """Check win/loss conditions."""
        if self.fuse_tokens <= 0:
            self.finished = True
            self.won = False
            return
        if all(len(stack) == 5 for stack in self.fireworks.values()):
            self.finished = True
            self.won = True
            self.score = PERFECT_SCORE
            return
        if self.final_turns_remaining is not None:
            if self.final_turns_remaining <= 0:
                self.finished = True
                self.won = False
                self.score = sum(len(s) for s in self.fireworks.values())
                return

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def deck_size(self) -> int:
        deck_zone = self.session.runtime.zones["deck"]
        assert isinstance(deck_zone, StackZone)
        return len(deck_zone.components)

    def hand_cards(self, player: str) -> list[tuple[str, int]]:
        """Return (color, number) for each card in player's hand."""
        return [
            (self._card(cid).properties["color"], self._card(cid).properties["number"])
            for cid in self.hands[player]
        ]

    def give_clue(self, attribute: str, value: str | int) -> Clue:
        """Give a clue to the other player about their hand.

        The current player tells the other player which of their cards
        match the given attribute (color or number).
        """
        if self.finished:
            raise ValueError("game is finished")
        if self.clue_tokens <= 0:
            raise ValueError("no clue tokens available")
        if attribute not in ("color", "number"):
            raise ValueError(f"attribute must be 'color' or 'number', got {attribute!r}")

        giver = self.current_player()
        target = "P2" if giver == "P1" else "P1"

        # Find all matching cards in target's hand
        matching = []
        for i, cid in enumerate(self.hands[target]):
            card = self._card(cid)
            if card.properties[attribute] == value:
                matching.append(i)

        if not matching:
            raise ValueError(
                f"clue must match at least one card; "
                f"no cards with {attribute}={value} in {target}'s hand"
            )

        self.clue_tokens -= 1
        clue = Clue(
            target=target,
            attribute=attribute,
            value=value,
            matching_indices=matching,
        )
        self.clue_log.append(clue)
        self.session.advance_turn()
        self._advance_final_turns()
        self._check_finished()
        return clue

    def play_card(self, card_index: int) -> dict:
        """Play a card from the current player's hand.

        If the card is the next number in its color's firework stack,
        it's placed successfully. Otherwise a fuse token is lost.
        """
        if self.finished:
            raise ValueError("game is finished")
        player = self.current_player()
        if card_index < 0 or card_index >= len(self.hands[player]):
            raise ValueError(
                f"card_index {card_index} out of range for hand of size {len(self.hands[player])}"
            )

        cid = self.hands[player].pop(card_index)
        card = self._card(cid)
        color = card.properties["color"]
        number = card.properties["number"]

        # Remove from runtime hand zone
        player_hand = self.session.runtime.players[player].zones["hand"]
        assert isinstance(player_hand, SetZone)
        player_hand.set_remove(cid)

        expected_next = self._firework_top(color) + 1
        success = number == expected_next

        if success:
            self.fireworks[color].append(number)
            fw_zone = self.session.runtime.zones[FIREWORK_ZONES[color]]
            assert isinstance(fw_zone, StackZone)
            fw_zone.components.append(cid)
            # Playing a 5 successfully regains 1 clue token
            if number == 5 and self.clue_tokens < MAX_CLUE_TOKENS:
                self.clue_tokens += 1
        else:
            self.fuse_tokens -= 1
            self.discard.append((color, number))
            discard_zone = self.session.runtime.zones["discard_pile"]
            assert isinstance(discard_zone, StackZone)
            discard_zone.components.append(cid)

        # Draw replacement
        self._draw_to_hand(player)
        # Check if deck just emptied
        if self.deck_size() == 0 and self.final_turns_remaining is None:
            self.final_turns_remaining = len(self.players)

        self.session.advance_turn()
        self._advance_final_turns()
        self._check_finished()

        return {
            "player": player,
            "color": color,
            "number": number,
            "success": success,
            "firework_height": len(self.fireworks[color]),
            "fuse_tokens": self.fuse_tokens,
        }

    def discard_card(self, card_index: int) -> dict:
        """Discard a card from the current player's hand, regaining a clue token."""
        if self.finished:
            raise ValueError("game is finished")
        if self.clue_tokens >= MAX_CLUE_TOKENS:
            raise ValueError("cannot discard: clue tokens already at maximum")

        player = self.current_player()
        if card_index < 0 or card_index >= len(self.hands[player]):
            raise ValueError(
                f"card_index {card_index} out of range for hand of size {len(self.hands[player])}"
            )

        cid = self.hands[player].pop(card_index)
        card = self._card(cid)
        color = card.properties["color"]
        number = card.properties["number"]

        # Remove from runtime hand zone
        player_hand = self.session.runtime.players[player].zones["hand"]
        assert isinstance(player_hand, SetZone)
        player_hand.set_remove(cid)

        # Add to discard pile
        self.discard.append((color, number))
        discard_zone = self.session.runtime.zones["discard_pile"]
        assert isinstance(discard_zone, StackZone)
        discard_zone.components.append(cid)

        # Regain 1 clue token
        self.clue_tokens = min(self.clue_tokens + 1, MAX_CLUE_TOKENS)

        # Draw replacement
        self._draw_to_hand(player)
        if self.deck_size() == 0 and self.final_turns_remaining is None:
            self.final_turns_remaining = len(self.players)

        self.session.advance_turn()
        self._advance_final_turns()
        self._check_finished()

        return {
            "player": player,
            "color": color,
            "number": number,
            "clue_tokens": self.clue_tokens,
        }

    def _advance_final_turns(self) -> None:
        """Decrement final turns counter if active."""
        if self.final_turns_remaining is not None and self.final_turns_remaining > 0:
            self.final_turns_remaining -= 1

    def total_score(self) -> int:
        """Current score: sum of top values across all firework stacks."""
        return sum(len(s) for s in self.fireworks.values())


# ---------------------------------------------------------------------------
# Tests: definition loading
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Hanabi"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["P1", "P2"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_deck_is_hidden_stack(self) -> None:
        defn = _load_game()
        assert defn.zones["deck"].zone_type == "ordered_stack"
        assert defn.zones["deck"].visibility == "hidden"

    def test_hand_is_per_player_set(self) -> None:
        defn = _load_game()
        hand = defn.zones["hand"]
        assert hand.zone_type == "set"
        assert hand.per_player is True
        assert hand.capacity == 5

    def test_hand_has_inverted_visibility(self) -> None:
        """Hanabi's key feature: hand visible to others, NOT to owner."""
        defn = _load_game()
        hand = defn.zones["hand"]
        assert isinstance(hand.visibility, PrivateVisibility)
        assert hand.visibility.private == "others"

    def test_firework_zones_exist(self) -> None:
        defn = _load_game()
        for color in COLORS:
            zone_name = f"fireworks_{color}"
            assert zone_name in defn.zones, f"missing firework zone: {zone_name}"
            assert defn.zones[zone_name].zone_type == "ordered_stack"
            assert defn.zones[zone_name].visibility == "public"

    def test_clue_tokens_counter(self) -> None:
        defn = _load_game()
        assert "clue_tokens" in defn.zones
        assert defn.zones["clue_tokens"].zone_type == "counter"

    def test_fuse_tokens_counter(self) -> None:
        defn = _load_game()
        assert "fuse_tokens" in defn.zones
        assert defn.zones["fuse_tokens"].zone_type == "counter"

    def test_discard_pile_is_public_stack(self) -> None:
        defn = _load_game()
        assert defn.zones["discard_pile"].zone_type == "ordered_stack"
        assert defn.zones["discard_pile"].visibility == "public"

    def test_card_component(self) -> None:
        defn = _load_game()
        assert "card" in defn.components
        assert defn.components["card"].count == 50

    def test_round_robin_turn_order(self) -> None:
        defn = _load_game()
        assert defn.turn_order.type == "round_robin"

    def test_has_end_conditions(self) -> None:
        defn = _load_game()
        results = [ec.result for ec in defn.end_conditions]
        assert "win" in results
        assert "loss" in results

    def test_win_condition_is_perfect_fireworks(self) -> None:
        defn = _load_game()
        win_conds = [ec for ec in defn.end_conditions if ec.result == "win"]
        assert len(win_conds) == 1
        assert win_conds[0].name == "perfect_fireworks"

    def test_loss_conditions(self) -> None:
        defn = _load_game()
        loss_names = {ec.name for ec in defn.end_conditions if ec.result == "loss"}
        assert "explosion" in loss_names
        assert "out_of_cards" in loss_names


# ---------------------------------------------------------------------------
# Tests: deck construction and dealing
# ---------------------------------------------------------------------------


class TestDeckAndDealing:
    def test_deck_has_50_cards(self) -> None:
        game = HanabiGame()
        # 50 total - 10 dealt (5 per player) = 40 in deck
        assert game.deck_size() == 40

    def test_each_player_has_5_cards(self) -> None:
        game = HanabiGame()
        assert len(game.hands["P1"]) == HAND_SIZE
        assert len(game.hands["P2"]) == HAND_SIZE

    def test_card_distribution_correct(self) -> None:
        """Verify 50 cards with correct per-color distribution."""
        game = HanabiGame()
        all_cards = []
        for player in game.players:
            all_cards.extend(game.hand_cards(player))
        # Also check deck
        deck_zone = game.session.runtime.zones["deck"]
        assert isinstance(deck_zone, StackZone)
        for cid in deck_zone.components:
            card = game._card(cid)
            all_cards.append((card.properties["color"], card.properties["number"]))

        assert len(all_cards) == TOTAL_CARDS

        # Verify distribution per color
        for color in COLORS:
            color_cards = [n for c, n in all_cards if c == color]
            assert len(color_cards) == CARDS_PER_COLOR
            for number, expected_count in DISTRIBUTION.items():
                actual = sum(1 for n in color_cards if n == number)
                assert actual == expected_count, (
                    f"{color} {number}: expected {expected_count}, got {actual}"
                )

    def test_deterministic_shuffle(self) -> None:
        """Same seed produces same hands."""
        g1 = HanabiGame(seed=99)
        g2 = HanabiGame(seed=99)
        assert g1.hand_cards("P1") == g2.hand_cards("P1")
        assert g1.hand_cards("P2") == g2.hand_cards("P2")

    def test_different_seeds_differ(self) -> None:
        g1 = HanabiGame(seed=1)
        g2 = HanabiGame(seed=2)
        # Extremely unlikely to be identical
        assert g1.hand_cards("P1") != g2.hand_cards("P1")


# ---------------------------------------------------------------------------
# Tests: clue giving
# ---------------------------------------------------------------------------


class TestClueGiving:
    def test_give_color_clue(self) -> None:
        game = HanabiGame(seed=42)
        # Find a color present in P2's hand
        p2_cards = game.hand_cards("P2")
        target_color = p2_cards[0][0]

        clue = game.give_clue("color", target_color)
        assert clue.target == "P2"
        assert clue.attribute == "color"
        assert clue.value == target_color
        assert len(clue.matching_indices) >= 1

    def test_give_number_clue(self) -> None:
        game = HanabiGame(seed=42)
        p2_cards = game.hand_cards("P2")
        target_number = p2_cards[0][1]

        clue = game.give_clue("number", target_number)
        assert clue.target == "P2"
        assert clue.attribute == "number"
        assert len(clue.matching_indices) >= 1

    def test_clue_spends_token(self) -> None:
        game = HanabiGame(seed=42)
        assert game.clue_tokens == MAX_CLUE_TOKENS
        p2_cards = game.hand_cards("P2")
        game.give_clue("color", p2_cards[0][0])
        assert game.clue_tokens == MAX_CLUE_TOKENS - 1

    def test_clue_advances_turn(self) -> None:
        game = HanabiGame(seed=42)
        assert game.current_player() == "P1"
        p2_cards = game.hand_cards("P2")
        game.give_clue("color", p2_cards[0][0])
        assert game.current_player() == "P2"

    def test_clue_matches_all_cards_of_attribute(self) -> None:
        """Clue must point to ALL matching cards."""
        game = HanabiGame(seed=42)
        p2_cards = game.hand_cards("P2")
        target_color = p2_cards[0][0]

        # Count how many of that color P2 has
        expected_matches = sum(1 for c, _ in p2_cards if c == target_color)

        clue = game.give_clue("color", target_color)
        assert len(clue.matching_indices) == expected_matches

    def test_no_clue_tokens_rejected(self) -> None:
        """Cannot give clue with 0 tokens."""
        game = HanabiGame(seed=42)
        game.clue_tokens = 0
        p2_cards = game.hand_cards("P2")
        with pytest.raises(ValueError, match="no clue tokens"):
            game.give_clue("color", p2_cards[0][0])

    def test_clue_with_no_matching_cards_rejected(self) -> None:
        """Clue must match at least one card in target's hand."""
        game = HanabiGame(seed=42)
        p2_cards = game.hand_cards("P2")
        p2_colors = {c for c, _ in p2_cards}

        # Find a color NOT in P2's hand
        missing_color = None
        for c in COLORS:
            if c not in p2_colors:
                missing_color = c
                break

        if missing_color is not None:
            with pytest.raises(ValueError, match="must match at least one"):
                game.give_clue("color", missing_color)

    def test_invalid_attribute_rejected(self) -> None:
        with pytest.raises(ValueError, match="attribute must be"):
            game = HanabiGame(seed=42)
            game.give_clue("suit", "red")

    def test_clue_logged(self) -> None:
        game = HanabiGame(seed=42)
        p2_cards = game.hand_cards("P2")
        game.give_clue("color", p2_cards[0][0])
        assert len(game.clue_log) == 1


# ---------------------------------------------------------------------------
# Tests: playing cards
# ---------------------------------------------------------------------------


class TestPlayCard:
    def _game_with_known_hand(self) -> HanabiGame:
        """Create a game and manually set P1's hand for predictable testing."""
        game = HanabiGame(seed=42)
        # Clear P1's hand and set up known cards
        p1_hand_zone = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(p1_hand_zone, SetZone)
        p1_hand_zone.components.clear()
        game.hands["P1"].clear()

        known_cards = [
            ("red", 1, "test-r1"),
            ("blue", 1, "test-b1"),
            ("green", 3, "test-g3"),
            ("yellow", 2, "test-y2"),
            ("white", 5, "test-w5"),
        ]
        for color, number, sid in known_cards:
            comp = ComponentData(
                id=ComponentId(0),
                string_id=sid,
                component_type="card",
                owner="P1",
                properties={"color": color, "number": number},
            )
            cid = game.session.runtime.components.insert(comp)
            p1_hand_zone.set_add(cid)
            game.hands["P1"].append(cid)

        return game

    def test_successful_play_on_empty_stack(self) -> None:
        """Playing a 1 on an empty firework stack succeeds."""
        game = self._game_with_known_hand()
        # P1's index 0 is red 1 — fireworks_red is empty
        result = game.play_card(0)
        assert result["success"] is True
        assert result["color"] == "red"
        assert result["number"] == 1
        assert result["firework_height"] == 1
        assert game.fireworks["red"] == [1]

    def test_failed_play_loses_fuse(self) -> None:
        """Playing wrong card loses a fuse token."""
        game = self._game_with_known_hand()
        # P1's index 2 is green 3 — green stack is empty, needs 1
        result = game.play_card(2)
        assert result["success"] is False
        assert result["fuse_tokens"] == MAX_FUSE_TOKENS - 1
        assert game.fuse_tokens == MAX_FUSE_TOKENS - 1

    def test_failed_play_discards_card(self) -> None:
        """Failed play puts card in discard pile."""
        game = self._game_with_known_hand()
        result = game.play_card(2)  # green 3 on empty stack
        assert ("green", 3) in game.discard

    def test_play_draws_replacement(self) -> None:
        """After playing, a replacement card is drawn from deck."""
        game = self._game_with_known_hand()
        deck_before = game.deck_size()
        hand_before = len(game.hands["P1"])
        game.play_card(0)
        # Hand size stays the same (one removed, one drawn)
        assert len(game.hands["P1"]) == hand_before
        assert game.deck_size() == deck_before - 1

    def test_sequential_firework_build(self) -> None:
        """Build a firework stack 1-2 in sequence."""
        game = self._game_with_known_hand()
        # Play red 1
        game.play_card(0)
        assert game.fireworks["red"] == [1]

        # Now it's P2's turn; give a clue to pass
        p1_cards = game.hand_cards("P1")
        game.give_clue("color", p1_cards[0][0])

        # Now put a red 2 in P1's hand
        p1_hand_zone = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(p1_hand_zone, SetZone)
        comp = ComponentData(
            id=ComponentId(0),
            string_id="test-r2",
            component_type="card",
            owner="P1",
            properties={"color": "red", "number": 2},
        )
        cid = game.session.runtime.components.insert(comp)
        p1_hand_zone.set_add(cid)
        game.hands["P1"].append(cid)

        # Play the red 2 (last card in hand)
        idx = len(game.hands["P1"]) - 1
        result = game.play_card(idx)
        assert result["success"] is True
        assert game.fireworks["red"] == [1, 2]

    def test_playing_5_regains_clue_token(self) -> None:
        """Successfully playing a 5 regains 1 clue token."""
        game = self._game_with_known_hand()
        game.clue_tokens = 5
        # Set up white firework to 4 so white 5 is playable
        game.fireworks["white"] = [1, 2, 3, 4]

        # Find white 5 in hand (index 4)
        result = game.play_card(4)
        assert result["success"] is True
        assert result["number"] == 5
        assert game.clue_tokens == 6  # was 5, gained 1

    def test_playing_5_does_not_exceed_max_clue_tokens(self) -> None:
        """Playing a 5 with max tokens doesn't go over 8."""
        game = self._game_with_known_hand()
        game.clue_tokens = MAX_CLUE_TOKENS
        game.fireworks["white"] = [1, 2, 3, 4]
        game.play_card(4)
        assert game.clue_tokens == MAX_CLUE_TOKENS

    def test_play_advances_turn(self) -> None:
        game = self._game_with_known_hand()
        assert game.current_player() == "P1"
        game.play_card(0)
        assert game.current_player() == "P2"

    def test_invalid_card_index_rejected(self) -> None:
        game = HanabiGame(seed=42)
        with pytest.raises(ValueError, match="out of range"):
            game.play_card(99)


# ---------------------------------------------------------------------------
# Tests: discarding
# ---------------------------------------------------------------------------


class TestDiscard:
    def test_discard_regains_clue_token(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = 5
        result = game.discard_card(0)
        assert result["clue_tokens"] == 6
        assert game.clue_tokens == 6

    def test_discard_max_tokens_rejected(self) -> None:
        """Cannot discard when clue tokens are at maximum."""
        game = HanabiGame(seed=42)
        assert game.clue_tokens == MAX_CLUE_TOKENS
        with pytest.raises(ValueError, match="clue tokens already at maximum"):
            game.discard_card(0)

    def test_discard_removes_from_hand(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = 5
        hand_before = len(game.hands["P1"])
        game.discard_card(0)
        # Hand stays same size (draw replacement)
        assert len(game.hands["P1"]) == hand_before

    def test_discard_goes_to_discard_pile(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = 5
        p1_card = game.hand_cards("P1")[0]
        game.discard_card(0)
        assert p1_card in game.discard

    def test_discard_draws_replacement(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = 5
        deck_before = game.deck_size()
        game.discard_card(0)
        assert game.deck_size() == deck_before - 1

    def test_discard_advances_turn(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = 5
        assert game.current_player() == "P1"
        game.discard_card(0)
        assert game.current_player() == "P2"

    def test_discard_does_not_exceed_max_tokens(self) -> None:
        game = HanabiGame(seed=42)
        game.clue_tokens = MAX_CLUE_TOKENS - 1
        game.discard_card(0)
        assert game.clue_tokens == MAX_CLUE_TOKENS


# ---------------------------------------------------------------------------
# Tests: win condition (perfect fireworks)
# ---------------------------------------------------------------------------


class TestWinCondition:
    def test_perfect_score_wins(self) -> None:
        """Completing all 5 firework stacks wins the game."""
        game = HanabiGame(seed=42)
        # Manually complete all fireworks
        for color in COLORS:
            game.fireworks[color] = [1, 2, 3, 4, 5]
        game._check_finished()
        assert game.finished is True
        assert game.won is True
        assert game.score == PERFECT_SCORE

    def test_incomplete_fireworks_not_won(self) -> None:
        game = HanabiGame(seed=42)
        game.fireworks["red"] = [1, 2, 3, 4, 5]
        game.fireworks["blue"] = [1, 2, 3, 4]
        game._check_finished()
        assert game.finished is False


# ---------------------------------------------------------------------------
# Tests: loss conditions
# ---------------------------------------------------------------------------


class TestLossConditions:
    def test_three_fuses_blown_loses(self) -> None:
        """Losing all 3 fuse tokens ends the game in a loss."""
        game = HanabiGame(seed=42)
        game.fuse_tokens = 0
        game._check_finished()
        assert game.finished is True
        assert game.won is False

    def test_one_fuse_not_lost(self) -> None:
        game = HanabiGame(seed=42)
        game.fuse_tokens = 1
        game._check_finished()
        assert game.finished is False

    def test_deck_empty_triggers_final_turns(self) -> None:
        """When deck empties, each player gets one final turn."""
        game = HanabiGame(seed=42)
        # Empty the deck
        deck_zone = game.session.runtime.zones["deck"]
        assert isinstance(deck_zone, StackZone)
        deck_zone.components.clear()
        game.deck = []
        game.clue_tokens = 5

        # Discard triggers final turn countdown
        game.discard_card(0)
        assert game.final_turns_remaining is not None

    def test_game_ends_after_final_turns(self) -> None:
        """Game ends after each player takes their final turn."""
        game = HanabiGame(seed=42)
        game.final_turns_remaining = 1
        game.clue_tokens = 5
        game.discard_card(0)  # P1's final action
        assert game.final_turns_remaining == 0
        assert game.finished is True
        assert game.won is False

    def test_cannot_play_after_finished(self) -> None:
        game = HanabiGame(seed=42)
        game.finished = True
        with pytest.raises(ValueError, match="finished"):
            game.play_card(0)

    def test_cannot_give_clue_after_finished(self) -> None:
        game = HanabiGame(seed=42)
        game.finished = True
        with pytest.raises(ValueError, match="finished"):
            game.give_clue("color", "red")

    def test_cannot_discard_after_finished(self) -> None:
        game = HanabiGame(seed=42)
        game.finished = True
        with pytest.raises(ValueError, match="finished"):
            game.discard_card(0)


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_score_zero_at_start(self) -> None:
        game = HanabiGame(seed=42)
        assert game.total_score() == 0

    def test_score_after_successful_plays(self) -> None:
        game = HanabiGame(seed=42)
        game.fireworks["red"] = [1, 2, 3]
        game.fireworks["blue"] = [1]
        assert game.total_score() == 4

    def test_perfect_score_is_25(self) -> None:
        game = HanabiGame(seed=42)
        for color in COLORS:
            game.fireworks[color] = [1, 2, 3, 4, 5]
        assert game.total_score() == PERFECT_SCORE


# ---------------------------------------------------------------------------
# Tests: inverted visibility model
# ---------------------------------------------------------------------------


class TestInvertedVisibility:
    """Tests that Hanabi's core mechanic — reverse hidden information — is
    correctly modeled. You see everyone else's hand but not your own."""

    def test_visibility_is_private_others(self) -> None:
        """Hand zone declares visibility as private to 'others'."""
        defn = _load_game()
        hand = defn.zones["hand"]
        assert isinstance(hand.visibility, PrivateVisibility)
        assert hand.visibility.private == "others"

    def test_hand_zone_per_player(self) -> None:
        """Each player has their own hand zone instance."""
        game = HanabiGame(seed=42)
        p1_hand = game.session.runtime.players["P1"].zones["hand"]
        p2_hand = game.session.runtime.players["P2"].zones["hand"]
        assert isinstance(p1_hand, SetZone)
        assert isinstance(p2_hand, SetZone)
        assert p1_hand is not p2_hand

    def test_other_player_can_see_hand(self) -> None:
        """Verify a player can describe the OTHER player's hand (for clue giving)."""
        game = HanabiGame(seed=42)
        # P1 can see P2's hand
        p2_cards = game.hand_cards("P2")
        assert len(p2_cards) == HAND_SIZE
        # Each card has valid color and number
        for color, number in p2_cards:
            assert color in COLORS
            assert number in [1, 2, 3, 4, 5]

    def test_clue_requires_visible_hand(self) -> None:
        """Giving a clue exercises inverted visibility: giver sees target's hand."""
        game = HanabiGame(seed=42)
        p2_cards = game.hand_cards("P2")
        target_color = p2_cards[0][0]

        clue = game.give_clue("color", target_color)
        # Clue correctly identifies which cards match
        for idx in clue.matching_indices:
            assert p2_cards[idx][0] == target_color

    def test_deck_is_hidden(self) -> None:
        """Deck is hidden from all players."""
        defn = _load_game()
        assert defn.zones["deck"].visibility == "hidden"

    def test_fireworks_are_public(self) -> None:
        """Firework stacks are visible to everyone."""
        defn = _load_game()
        for color in COLORS:
            assert defn.zones[f"fireworks_{color}"].visibility == "public"

    def test_discard_is_public(self) -> None:
        """Discard pile is visible to everyone."""
        defn = _load_game()
        assert defn.zones["discard_pile"].visibility == "public"


# ---------------------------------------------------------------------------
# Tests: full game simulation
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_play_several_turns(self) -> None:
        """Play a few turns exercising all three actions."""
        game = HanabiGame(seed=42)

        # Turn 1: P1 gives a clue to P2
        p2_cards = game.hand_cards("P2")
        game.give_clue("color", p2_cards[0][0])
        assert game.clue_tokens == 7

        # Turn 2: P2 gives a clue to P1
        p1_cards = game.hand_cards("P1")
        game.give_clue("number", p1_cards[0][1])
        assert game.clue_tokens == 6

        # Turn 3: P1 discards to get a token back
        game.discard_card(0)
        assert game.clue_tokens == 7

        # Turn 4: P2 plays a card
        result = game.play_card(0)
        # Whether it succeeds depends on the seed, but the game should continue
        assert result["player"] == "P2"
        assert not game.finished

    def test_fuse_loss_game(self) -> None:
        """Game ends when 3 fuses are blown by misplays."""
        game = HanabiGame(seed=42)
        misplays = 0
        # Keep playing cards until 3 fuses are blown
        while not game.finished and misplays < 10:
            player = game.current_player()
            # Try playing card index 0; most will fail on empty stacks
            result = game.play_card(0)
            if not result["success"]:
                misplays += 1
            if game.finished:
                break

        assert game.fuse_tokens <= 0
        assert game.finished is True
        assert game.won is False

    def test_wire_state_includes_hands(self) -> None:
        """Wire state includes per-player hand zones."""
        game = HanabiGame(seed=42)
        wire = game.session.to_wire_state()
        assert "P1" in wire.players
        assert "P2" in wire.players
        assert wire.players["P1"].zones is not None
        assert "hand" in wire.players["P1"].zones

    def test_wire_state_includes_firework_zones(self) -> None:
        """Wire state includes firework stack zones."""
        game = HanabiGame(seed=42)
        wire = game.session.to_wire_state()
        for color in COLORS:
            assert f"fireworks_{color}" in wire.zones


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_card_color_is_five(self) -> None:
        """Each color has exactly one 5 — verify via distribution constant."""
        assert DISTRIBUTION[5] == 1

    def test_three_ones_per_color(self) -> None:
        """Each color has exactly three 1s."""
        assert DISTRIBUTION[1] == 3

    def test_total_cards_is_50(self) -> None:
        assert TOTAL_CARDS == 50

    def test_firework_top_empty(self) -> None:
        game = HanabiGame(seed=42)
        assert game._firework_top("red") == 0

    def test_firework_top_with_cards(self) -> None:
        game = HanabiGame(seed=42)
        game.fireworks["red"] = [1, 2, 3]
        assert game._firework_top("red") == 3

    def test_play_on_completed_stack_fails(self) -> None:
        """Playing a card on a completed (1-5) stack always fails."""
        game = HanabiGame(seed=42)
        game.fireworks["red"] = [1, 2, 3, 4, 5]

        # Manually place a red card (any number) in P1's hand
        p1_hand_zone = game.session.runtime.players["P1"].zones["hand"]
        assert isinstance(p1_hand_zone, SetZone)
        comp = ComponentData(
            id=ComponentId(0),
            string_id="test-extra-red",
            component_type="card",
            owner="P1",
            properties={"color": "red", "number": 1},
        )
        cid = game.session.runtime.components.insert(comp)
        p1_hand_zone.set_add(cid)
        game.hands["P1"].append(cid)

        idx = len(game.hands["P1"]) - 1
        result = game.play_card(idx)
        assert result["success"] is False

    def test_multiple_clues_deplete_tokens(self) -> None:
        """Giving 8 clues depletes all tokens."""
        game = HanabiGame(seed=42)
        for i in range(8):
            player = game.current_player()
            target = "P2" if player == "P1" else "P1"
            target_cards = game.hand_cards(target)
            game.give_clue("color", target_cards[0][0])

        assert game.clue_tokens == 0

    def test_discard_then_clue_token_cycle(self) -> None:
        """Discard restores a token, then spend it on clue."""
        game = HanabiGame(seed=42)
        # Spend all tokens
        for i in range(8):
            target = "P2" if game.current_player() == "P1" else "P1"
            target_cards = game.hand_cards(target)
            game.give_clue("color", target_cards[0][0])

        assert game.clue_tokens == 0
        # Now discard to get one back
        game.discard_card(0)
        assert game.clue_tokens == 1

        # Spend it on a clue
        target = "P2" if game.current_player() == "P1" else "P1"
        target_cards = game.hand_cards(target)
        game.give_clue("color", target_cards[0][0])
        assert game.clue_tokens == 0
