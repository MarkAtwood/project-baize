"""Tests for Snakes and Ladders: track movement, dice, triggered effects.

First game to exercise TrackZone. Players roll a d6 and advance along a
100-position track. Landing on a snake head slides to the tail; landing on
a ladder bottom climbs to the top. First to position 100 wins.

Dice rolls are server authority — tests supply deterministic values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    TrackZone,
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "snakes-and-ladders.json"

# Snakes: head → tail (0-indexed: position N in JSON = index N-1)
SNAKES = {
    16: 6, 47: 26, 49: 11, 56: 53, 62: 19,
    64: 60, 87: 24, 93: 73, 95: 75, 98: 78,
}

# Ladders: bottom → top
LADDERS = {
    1: 38, 4: 14, 9: 31, 21: 42, 28: 84,
    36: 44, 51: 67, 71: 91, 80: 100,
}


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# SnakesGame helper
# ---------------------------------------------------------------------------


class SnakesGame:
    """Snakes and Ladders driver with dice roll simulation."""

    def __init__(self) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None

        # Place tokens off-board (position tracking via dict)
        self.positions: dict[str, int] = {"P1": 0, "P2": 0}
        # Position 0 = not yet on board; positions 1-100 are track indices 0-99

        # Create token components
        self.tokens: dict[str, ComponentId] = {}
        for player in ["P1", "P2"]:
            cid = self.session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"token-{player}",
                    component_type="token",
                    owner=player,
                )
            )
            self.tokens[player] = cid

    @property
    def track(self) -> TrackZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, TrackZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _move_token(self, player: str, new_pos: int) -> None:
        """Move player's token to new_pos (1-100). 0 = off board."""
        cid = self.tokens[player]
        old_pos = self.positions[player]

        # Remove from old position
        if old_pos > 0:
            idx = old_pos - 1
            pos_list = self.track.positions[idx]
            if cid in pos_list:
                pos_list.remove(cid)

        # Place at new position
        if new_pos > 0 and new_pos <= 100:
            idx = new_pos - 1
            self.track.positions[idx].append(cid)

        self.positions[player] = new_pos

    def _apply_snakes_and_ladders(self, pos: int) -> int:
        """Check for snake or ladder at position, return final position."""
        if pos in SNAKES:
            return SNAKES[pos]
        if pos in LADDERS:
            return LADDERS[pos]
        return pos

    def roll(self, die_value: int) -> dict:
        """Roll the die (deterministic value) and move the current player.

        Returns {player, rolled, landed, final, snake, ladder, won}.
        """
        if self.finished:
            raise ValueError("game is finished")
        if die_value < 1 or die_value > 6:
            raise ValueError(f"invalid die value: {die_value}")

        player = self.current_player()
        old_pos = self.positions[player]
        new_pos = old_pos + die_value

        # Must land exactly on 100 — overshoot bounces back
        if new_pos > 100:
            new_pos = 100 - (new_pos - 100)

        result = {
            "player": player,
            "rolled": die_value,
            "landed": new_pos,
            "final": new_pos,
            "snake": False,
            "ladder": False,
            "won": False,
        }

        # Apply snake/ladder
        final = self._apply_snakes_and_ladders(new_pos)
        if final != new_pos:
            if final < new_pos:
                result["snake"] = True
            else:
                result["ladder"] = True
            result["final"] = final

        self._move_token(player, final)

        # Win check
        if final == 100:
            self.finished = True
            self.winner = player
            result["won"] = True
        else:
            self.session.advance_turn()

        return result

    def player_position(self, player: str) -> int:
        return self.positions[player]


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Snakes and Ladders"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["P1", "P2"]

    def test_track_zone(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].zone_type == "track"
        assert defn.zones["board"].length == 100


# ---------------------------------------------------------------------------
# Tests: basic movement
# ---------------------------------------------------------------------------


class TestMovement:
    def test_first_roll_moves_from_start(self) -> None:
        game = SnakesGame()
        result = game.roll(3)
        assert result["player"] == "P1"
        assert result["rolled"] == 3
        assert game.player_position("P1") == 3

    def test_alternating_players(self) -> None:
        game = SnakesGame()
        game.roll(1)  # P1
        assert game.current_player() == "P2"
        game.roll(2)  # P2
        assert game.current_player() == "P1"

    def test_positions_accumulate(self) -> None:
        game = SnakesGame()
        game.roll(4)  # P1 -> 4... but 4 is a ladder to 14!
        game.roll(1)  # P2 -> 1... but 1 is a ladder to 38!
        game.roll(3)  # P1 at 14 -> 17
        assert game.player_position("P1") == 17

    def test_overshoot_bounces_back(self) -> None:
        """Rolling past 100 bounces back."""
        game = SnakesGame()
        game.positions["P1"] = 98
        game._move_token("P1", 98)
        result = game.roll(5)  # 98 + 5 = 103 -> bounce to 97
        assert result["landed"] == 97

    def test_exact_landing_on_100_wins(self) -> None:
        game = SnakesGame()
        game.positions["P1"] = 96
        game._move_token("P1", 96)
        result = game.roll(4)  # 96 + 4 = 100
        assert result["final"] == 100
        assert result["won"] is True
        assert game.finished


# ---------------------------------------------------------------------------
# Tests: snakes
# ---------------------------------------------------------------------------


class TestSnakes:
    def test_landing_on_snake_slides_down(self) -> None:
        game = SnakesGame()
        game.positions["P1"] = 44
        game._move_token("P1", 44)
        result = game.roll(3)  # 44 + 3 = 47 (snake -> 26)
        assert result["landed"] == 47
        assert result["final"] == 26
        assert result["snake"] is True
        assert game.player_position("P1") == 26

    def test_snake_98_to_78(self) -> None:
        game = SnakesGame()
        game.positions["P1"] = 95
        game._move_token("P1", 95)
        result = game.roll(3)  # 95 + 3 = 98 (snake -> 78)
        assert result["final"] == 78
        assert result["snake"] is True

    def test_all_snakes_go_down(self) -> None:
        for head, tail in SNAKES.items():
            assert tail < head, f"snake {head}->{tail} doesn't go down"


# ---------------------------------------------------------------------------
# Tests: ladders
# ---------------------------------------------------------------------------


class TestLadders:
    def test_landing_on_ladder_climbs_up(self) -> None:
        game = SnakesGame()
        # Position 1 is a ladder to 38
        result = game.roll(1)  # P1: 0 + 1 = 1 (ladder -> 38)
        assert result["landed"] == 1
        assert result["final"] == 38
        assert result["ladder"] is True
        assert game.player_position("P1") == 38

    def test_ladder_80_to_100_wins(self) -> None:
        game = SnakesGame()
        game.positions["P1"] = 77
        game._move_token("P1", 77)
        result = game.roll(3)  # 77 + 3 = 80 (ladder -> 100)
        assert result["final"] == 100
        assert result["won"] is True
        assert result["ladder"] is True

    def test_all_ladders_go_up(self) -> None:
        for bottom, top in LADDERS.items():
            assert top > bottom, f"ladder {bottom}->{top} doesn't go up"


# ---------------------------------------------------------------------------
# Tests: track zone usage
# ---------------------------------------------------------------------------


class TestTrackZone:
    def test_token_on_track(self) -> None:
        game = SnakesGame()
        game.roll(5)  # P1 lands on 5 (no snake/ladder at 5)
        # Verify token is at position 5 (index 4) on the track
        track = game.track
        assert game.tokens["P1"] in track.positions[4]

    def test_token_removed_from_old_position(self) -> None:
        game = SnakesGame()
        game.roll(5)  # P1 -> 5
        game.roll(2)  # P2 -> 2
        game.roll(3)  # P1: 5 + 3 = 8
        track = game.track
        assert game.tokens["P1"] not in track.positions[4]  # no longer at 5
        assert game.tokens["P1"] in track.positions[7]  # now at 8

    def test_multiple_tokens_same_position(self) -> None:
        """Two tokens can occupy the same track position."""
        game = SnakesGame()
        game.roll(5)  # P1 -> 5
        game.roll(5)  # P2 -> 5
        track = game.track
        assert game.tokens["P1"] in track.positions[4]
        assert game.tokens["P2"] in track.positions[4]


# ---------------------------------------------------------------------------
# Tests: full game
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_deterministic_game(self) -> None:
        """Play a scripted game to verify end-to-end flow."""
        game = SnakesGame()
        rolls = [
            # (die, expected_player)
            (6, "P1"), (6, "P2"), (6, "P1"), (6, "P2"),
            (6, "P1"), (6, "P2"), (6, "P1"), (6, "P2"),
        ]
        for die_val, expected_player in rolls:
            if game.finished:
                break
            assert game.current_player() == expected_player
            game.roll(die_val)

        # Just verify no crashes and positions advanced
        assert game.player_position("P1") > 0
        assert game.player_position("P2") > 0

    def test_cannot_roll_after_win(self) -> None:
        game = SnakesGame()
        game.positions["P1"] = 94
        game._move_token("P1", 94)
        game.roll(6)  # P1: 94 + 6 = 100, wins
        with pytest.raises(ValueError, match="finished"):
            game.roll(1)
