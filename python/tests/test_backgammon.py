"""Tests for Backgammon: track movement, hitting, bar re-entry, bearing off.

24-point track, 15 checkers per player. Roll 2d6, move checkers forward
by die values. Hit lone opponents to the bar. Re-enter from bar before
other moves. Bear off when all checkers are in home board. Doubles give
4 moves instead of 2.

Dice rolls are server authority — tests supply deterministic values.
White moves from high points to low (24→1). Black moves low to high (1→24).
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
    SetZone,
    TrackZone,
)


# ---------------------------------------------------------------------------
# Game data
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "backgammon.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# BackgammonGame helper
# ---------------------------------------------------------------------------


class BackgammonGame:
    """Backgammon game driver with movement, hitting, bar, and bearing off."""

    # White home = points 1-6 (indices 0-5), moves 24→1 (high index to low)
    # Black home = points 19-24 (indices 18-23), moves 1→24 (low index to high)
    HOME_RANGE = {"White": range(0, 6), "Black": range(18, 24)}
    DIRECTION = {"White": -1, "Black": 1}  # step direction on track

    # Standard starting position: (point_index_0based, count)
    INITIAL = {
        "White": [(0, 2), (11, 5), (16, 3), (18, 5)],
        "Black": [(23, 2), (12, 5), (7, 3), (5, 5)],
    }

    def __init__(self) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.finished = False
        self.winner: str | None = None
        self._setup_initial_position()
        self.dice_remaining: list[int] = []

    @property
    def track(self) -> TrackZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, TrackZone)
        return zone

    def _bar(self, player: str) -> SetZone:
        zone = self.session.runtime.players[player].zones["bar"]
        assert isinstance(zone, SetZone)
        return zone

    def _borne_off(self, player: str) -> SetZone:
        zone = self.session.runtime.players[player].zones["bearing_off"]
        assert isinstance(zone, SetZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _make_checker(self, owner: str) -> ComponentId:
        n = len(self.session.runtime.components)
        return self.session.runtime.components.insert(
            ComponentData(
                id=ComponentId(0),
                string_id=f"checker-{owner}-{n}",
                component_type="checker",
                owner=owner,
            )
        )

    def _setup_initial_position(self) -> None:
        for player, positions in self.INITIAL.items():
            for point_idx, count in positions:
                for _ in range(count):
                    cid = self._make_checker(player)
                    self.track.positions[point_idx].append(cid)

    def _owner_at(self, point_idx: int) -> str | None:
        """Return the owner of checkers at a point, or None if empty."""
        if not self.track.positions[point_idx]:
            return None
        cid = self.track.positions[point_idx][0]
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def _count_at(self, point_idx: int) -> int:
        return len(self.track.positions[point_idx])

    def _count_on_bar(self, player: str) -> int:
        return len(self._bar(player).components)

    def _count_borne_off(self, player: str) -> int:
        return len(self._borne_off(player).components)

    def _total_checkers(self, player: str) -> int:
        """Count all checkers for a player (track + bar + borne off)."""
        count = self._count_on_bar(player) + self._count_borne_off(player)
        for idx in range(24):
            if self._owner_at(idx) == player:
                count += self._count_at(idx)
        return count

    def _all_in_home(self, player: str) -> bool:
        """Check if all of player's checkers are in their home board."""
        if self._count_on_bar(player) > 0:
            return False
        home = self.HOME_RANGE[player]
        for idx in range(24):
            if idx not in home and self._owner_at(idx) == player:
                return False
        return True

    def roll(self, d1: int, d2: int) -> list[int]:
        """Roll dice. Doubles give 4 uses."""
        if d1 == d2:
            self.dice_remaining = [d1] * 4
        else:
            self.dice_remaining = sorted([d1, d2], reverse=True)
        return list(self.dice_remaining)

    def _use_die(self, value: int) -> None:
        if value not in self.dice_remaining:
            raise ValueError(f"no die showing {value} remaining")
        self.dice_remaining.remove(value)

    def move(self, from_point: int, die_value: int) -> str:
        """Move a checker from from_point (0-based) by die_value.

        Returns 'ok', 'hit', or 'bear_off'.
        """
        if self.finished:
            raise ValueError("game is finished")
        player = self.current_player()
        direction = self.DIRECTION[player]

        # Must re-enter from bar first
        if self._count_on_bar(player) > 0 and from_point != -1:
            raise ValueError("must re-enter from bar first")

        if from_point == -1:
            # Bar re-entry
            return self._enter_from_bar(player, die_value)

        # Validate source
        if self._owner_at(from_point) != player:
            raise ValueError(f"no {player} checker at point {from_point}")

        to_point = from_point + direction * die_value

        # Bearing off
        if player == "White" and to_point < 0:
            return self._bear_off(player, from_point, die_value)
        if player == "Black" and to_point > 23:
            return self._bear_off(player, from_point, die_value)

        if to_point < 0 or to_point > 23:
            raise ValueError(f"destination {to_point} out of bounds")

        return self._move_to(player, from_point, to_point, die_value)

    def _move_to(self, player: str, from_point: int, to_point: int, die_value: int) -> str:
        opponent = "Black" if player == "White" else "White"
        dest_owner = self._owner_at(to_point)
        dest_count = self._count_at(to_point)

        if dest_owner == opponent and dest_count >= 2:
            raise ValueError(f"point {to_point} is blocked ({dest_count} opponent checkers)")

        self._use_die(die_value)
        hit = False

        # Hit lone opponent
        if dest_owner == opponent and dest_count == 1:
            opp_cid = self.track.positions[to_point].pop()
            self._bar(opponent).components.append(opp_cid)
            hit = True

        # Move checker
        cid = self.track.positions[from_point].pop()
        self.track.positions[to_point].append(cid)

        return "hit" if hit else "ok"

    def _enter_from_bar(self, player: str, die_value: int) -> str:
        """Re-enter a checker from the bar."""
        if player == "White":
            entry_point = 24 - die_value  # White enters at 24-die (high end)
        else:
            entry_point = die_value - 1  # Black enters at die-1 (low end)

        opponent = "Black" if player == "White" else "White"
        dest_owner = self._owner_at(entry_point)
        dest_count = self._count_at(entry_point)

        if dest_owner == opponent and dest_count >= 2:
            raise ValueError(f"entry point {entry_point} is blocked")

        self._use_die(die_value)
        hit = False

        if dest_owner == opponent and dest_count == 1:
            opp_cid = self.track.positions[entry_point].pop()
            self._bar(opponent).components.append(opp_cid)
            hit = True

        bar = self._bar(player)
        cid = bar.components.pop()
        self.track.positions[entry_point].append(cid)

        return "hit" if hit else "ok"

    def _bear_off(self, player: str, from_point: int, die_value: int) -> str:
        if not self._all_in_home(player):
            raise ValueError("cannot bear off: not all checkers in home board")

        self._use_die(die_value)
        cid = self.track.positions[from_point].pop()
        self._borne_off(player).components.append(cid)

        if self._count_borne_off(player) == 15:
            self.finished = True
            self.winner = player

        return "bear_off"

    def end_turn(self) -> None:
        self.dice_remaining.clear()
        self.session.advance_turn()


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Backgammon"

    def test_two_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["White", "Black"]

    def test_track_24_points(self) -> None:
        defn = _load_game()
        assert defn.zones["board"].zone_type == "track"
        assert defn.zones["board"].points == 24

    def test_per_player_bar(self) -> None:
        defn = _load_game()
        assert defn.zones["bar"].per_player is True


# ---------------------------------------------------------------------------
# Tests: initial position
# ---------------------------------------------------------------------------


class TestInitialPosition:
    def test_15_checkers_per_player(self) -> None:
        game = BackgammonGame()
        assert game._total_checkers("White") == 15
        assert game._total_checkers("Black") == 15

    def test_white_starting_positions(self) -> None:
        game = BackgammonGame()
        assert game._count_at(0) == 2   # point 1
        assert game._owner_at(0) == "White"
        assert game._count_at(11) == 5  # point 12
        assert game._count_at(16) == 3  # point 17
        assert game._count_at(18) == 5  # point 19

    def test_black_starting_positions(self) -> None:
        game = BackgammonGame()
        assert game._count_at(23) == 2  # point 24
        assert game._owner_at(23) == "Black"
        assert game._count_at(12) == 5  # point 13
        assert game._count_at(7) == 3   # point 8
        assert game._count_at(5) == 5   # point 6

    def test_white_moves_first(self) -> None:
        game = BackgammonGame()
        assert game.current_player() == "White"


# ---------------------------------------------------------------------------
# Tests: basic movement
# ---------------------------------------------------------------------------


class TestMovement:
    def test_white_moves_toward_lower_points(self) -> None:
        game = BackgammonGame()
        game.roll(5, 3)
        # White moves from point 12 (idx 11) by 5 → point 7 (idx 6)
        game.move(11, 5)
        assert game._owner_at(6) == "White"

    def test_move_uses_die(self) -> None:
        game = BackgammonGame()
        game.roll(4, 2)
        assert len(game.dice_remaining) == 2
        game.move(18, 4)  # White: point 19 (idx 18) → point 15 (idx 14)
        assert len(game.dice_remaining) == 1

    def test_doubles_give_four_moves(self) -> None:
        game = BackgammonGame()
        dice = game.roll(3, 3)
        assert dice == [3, 3, 3, 3]

    def test_blocked_point_rejected(self) -> None:
        game = BackgammonGame()
        game.roll(6, 5)
        # White from point 19 (idx 18) by 6 → point 13 (idx 12) — 5 Black checkers
        with pytest.raises(ValueError, match="blocked"):
            game.move(18, 6)

    def test_wrong_player_checker_rejected(self) -> None:
        game = BackgammonGame()
        game.roll(3, 1)
        with pytest.raises(ValueError, match="no White"):
            game.move(23, 3)  # Black's checker


# ---------------------------------------------------------------------------
# Tests: hitting
# ---------------------------------------------------------------------------


class TestHitting:
    def test_hit_lone_opponent(self) -> None:
        """Land on a point with exactly 1 opponent checker → hit to bar."""
        game = BackgammonGame()
        # Clear a point and place a lone Black checker
        game.track.positions[9] = []
        cid = game._make_checker("Black")
        game.track.positions[9].append(cid)

        game.roll(2, 1)
        result = game.move(11, 2)  # White from 12→10 (idx 11→9)
        assert result == "hit"
        assert game._owner_at(9) == "White"
        assert game._count_on_bar("Black") == 1

    def test_hit_sends_to_bar(self) -> None:
        game = BackgammonGame()
        game.track.positions[14] = []
        cid = game._make_checker("Black")
        game.track.positions[14].append(cid)

        game.roll(4, 1)
        game.move(18, 4)  # White 19→15 (idx 18→14), hits
        assert game._count_on_bar("Black") == 1


# ---------------------------------------------------------------------------
# Tests: bar re-entry
# ---------------------------------------------------------------------------


class TestBar:
    def test_must_enter_from_bar_first(self) -> None:
        game = BackgammonGame()
        # Put a White checker on the bar
        cid = game._make_checker("White")
        game._bar("White").components.append(cid)

        game.roll(3, 1)
        with pytest.raises(ValueError, match="bar first"):
            game.move(11, 3)  # can't move from track while on bar

    def test_white_enters_from_bar(self) -> None:
        """White enters at 24-die (high points, opponent's home)."""
        game = BackgammonGame()
        # Clear Black's home point 22 (idx 21)
        game.track.positions[21] = []
        cid = game._make_checker("White")
        game._bar("White").components.append(cid)

        game.roll(3, 1)
        game.move(-1, 3)  # enter at point 22 (idx 21)
        assert game._owner_at(21) == "White"
        assert game._count_on_bar("White") == 0

    def test_blocked_entry_rejected(self) -> None:
        game = BackgammonGame()
        cid = game._make_checker("White")
        game._bar("White").components.append(cid)

        game.roll(1, 2)
        # Point 24 (idx 23) has 2 Black checkers → blocked
        with pytest.raises(ValueError, match="blocked"):
            game.move(-1, 1)


# ---------------------------------------------------------------------------
# Tests: bearing off
# ---------------------------------------------------------------------------


class TestBearingOff:
    def _setup_home_only(self, game: BackgammonGame, player: str) -> None:
        """Clear board and place all 15 checkers in home board."""
        for idx in range(24):
            game.track.positions[idx] = []
        game._bar(player).components.clear()
        game._borne_off(player).components.clear()

        home_start = 0 if player == "White" else 18
        for i in range(15):
            cid = game._make_checker(player)
            point = home_start + (i % 6)
            game.track.positions[point].append(cid)

    def test_bear_off_exact(self) -> None:
        game = BackgammonGame()
        self._setup_home_only(game, "White")
        game.roll(1, 2)
        result = game.move(0, 1)  # point 1 (idx 0) bear off with die 1
        assert result == "bear_off"
        assert game._count_borne_off("White") == 1

    def test_cannot_bear_off_with_checker_outside_home(self) -> None:
        game = BackgammonGame()
        game.roll(1, 2)
        with pytest.raises(ValueError, match="not all checkers"):
            game.move(0, 1)

    def test_all_borne_off_wins(self) -> None:
        game = BackgammonGame()
        # Place exactly 1 White checker at point 1 (idx 0), rest borne off
        for idx in range(24):
            game.track.positions[idx] = []
        game._bar("White").components.clear()

        # 14 already borne off
        for _ in range(14):
            cid = game._make_checker("White")
            game._borne_off("White").components.append(cid)
        # 1 on point 1
        cid = game._make_checker("White")
        game.track.positions[0].append(cid)

        game.roll(1, 2)
        game.move(0, 1)  # bear off the last one
        assert game.finished
        assert game.winner == "White"


# ---------------------------------------------------------------------------
# Tests: full game scenario
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_opening_moves(self) -> None:
        game = BackgammonGame()
        game.roll(3, 1)
        game.move(16, 3)  # White: point 17 (idx 16) → point 14 (idx 13)
        game.move(16, 1)  # White: point 17 (idx 16) → point 16 (idx 15)
        game.end_turn()
        assert game.current_player() == "Black"

    def test_simple_opening(self) -> None:
        game = BackgammonGame()
        game.roll(3, 1)
        # White from point 17 (idx 16) by 3 → point 14 (idx 13) — empty
        game.move(16, 3)
        # White from point 19 (idx 18) by 1 → point 18 (idx 17) — empty
        game.move(18, 1)
        assert game._count_at(13) == 1
        assert game._count_at(17) == 1

    def test_alternating_turns(self) -> None:
        game = BackgammonGame()
        assert game.current_player() == "White"
        game.roll(3, 1)
        game.move(11, 3)
        game.move(11, 1)
        game.end_turn()
        assert game.current_player() == "Black"

    def test_checker_count_preserved(self) -> None:
        game = BackgammonGame()
        game.roll(5, 3)
        game.move(11, 5)
        game.move(11, 3)
        assert game._total_checkers("White") == 15
        assert game._total_checkers("Black") == 15
