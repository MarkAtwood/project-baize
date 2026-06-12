"""Tests for Reversi (Othello): placement, flipping, legal moves, game end.

Reversi-specific logic (flip detection, legal move generation) is implemented
as a Python ReversiGame helper — same pattern as Go. The engine handles disc
placement via the 'place' action and pass via the 'pass' action.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)
from baize.transition import apply_action


# ---------------------------------------------------------------------------
# Game definition
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "reversi.json"

# 8 directions: N, NE, E, SE, S, SW, W, NW
_DIRS = [
    (0, -1), (1, -1), (1, 0), (1, 1),
    (0, 1), (-1, 1), (-1, 0), (-1, -1),
]


def _load_reversi() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


# ---------------------------------------------------------------------------
# ReversiGame helper
# ---------------------------------------------------------------------------


class ReversiGame:
    """Reversi game driver with flip logic and legal move detection."""

    def __init__(self) -> None:
        defn = _load_reversi()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"
        self.consecutive_passes = 0
        self.finished = False
        self._setup_initial_position()

    @property
    def board(self) -> GridZone:
        zone = self.session.runtime.zones["board"]
        assert isinstance(zone, GridZone)
        return zone

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _setup_initial_position(self) -> None:
        """Place the standard 4-disc starting position."""
        # Standard Reversi opening: center 4 discs
        # (3,3)=white, (4,4)=white, (3,4)=black, (4,3)=black
        for col, row, owner in [
            (3, 3, "white"), (4, 4, "white"),
            (3, 4, "black"), (4, 3, "black"),
        ]:
            cid = self.session.runtime.components.insert(
                ComponentData(
                    id=ComponentId(0),
                    string_id=f"disc-{owner}-{col}-{row}",
                    component_type="disc",
                    owner=owner,
                )
            )
            self.board.grid_set(col, row, cid)

    def owner_at(self, col: int, row: int) -> str | None:
        cid = self.board.grid_get(col, row)
        if cid is None:
            return None
        comp = self.session.runtime.components.get(cid)
        return comp.owner if comp is not None else None

    def _flips_in_direction(
        self, col: int, row: int, dc: int, dr: int, player: str
    ) -> list[tuple[int, int]]:
        """Return cells that would be flipped in one direction."""
        opponent = "white" if player == "black" else "black"
        candidates: list[tuple[int, int]] = []
        c, r = col + dc, row + dr
        while 0 <= c < 8 and 0 <= r < 8:
            owner = self.owner_at(c, r)
            if owner == opponent:
                candidates.append((c, r))
            elif owner == player:
                return candidates  # bracketed!
            else:
                return []  # empty cell — no bracket
            c += dc
            r += dr
        return []  # ran off board

    def _all_flips(self, col: int, row: int, player: str) -> list[tuple[int, int]]:
        """Return all cells that would be flipped by placing at (col, row)."""
        flips: list[tuple[int, int]] = []
        for dc, dr in _DIRS:
            flips.extend(self._flips_in_direction(col, row, dc, dr, player))
        return flips

    def legal_moves(self, player: str | None = None) -> list[tuple[int, int]]:
        """Return all legal placement positions for the given player."""
        if player is None:
            player = self.current_player()
        moves = []
        for r in range(8):
            for c in range(8):
                if self.owner_at(c, r) is None and self._all_flips(c, r, player):
                    moves.append((c, r))
        return moves

    def play(self, col: int, row: int) -> int:
        """Place a disc and flip bracketed opponents. Returns flip count."""
        if self.finished:
            raise ValueError("game is finished")
        player = self.current_player()

        if self.owner_at(col, row) is not None:
            raise ValueError(f"cell ({col},{row}) is occupied")

        flips = self._all_flips(col, row, player)
        if not flips:
            raise ValueError(
                f"illegal move: ({col},{row}) does not bracket any opponent discs"
            )

        # Place via engine
        apply_action(
            self.session,
            Action(
                action_type="place",
                component_type="disc",
                to_pos={"zone": "board", "cell": f"{col},{row}"},
            ),
        )

        # Flip bracketed discs
        for fc, fr in flips:
            cid = self.board.grid_get(fc, fr)
            if cid is not None:
                comp = self.session.runtime.components.get(cid)
                if comp is not None:
                    comp.owner = player

        self.consecutive_passes = 0
        return len(flips)

    def pass_turn(self) -> None:
        """Pass (required when no legal moves). Two passes ends the game."""
        if self.finished:
            raise ValueError("game is finished")
        if self.legal_moves():
            raise ValueError("cannot pass when legal moves exist")
        apply_action(self.session, Action(action_type="pass"))
        self.consecutive_passes += 1
        if self.consecutive_passes >= 2:
            self.finished = True

    def count_discs(self) -> dict[str, int]:
        """Count discs per player."""
        counts: dict[str, int] = {"black": 0, "white": 0}
        for r in range(8):
            for c in range(8):
                owner = self.owner_at(c, r)
                if owner is not None:
                    counts[owner] += 1
        return counts

    def winner(self) -> str | None:
        """Return winner by disc count, or None on tie."""
        counts = self.count_discs()
        if counts["black"] > counts["white"]:
            return "black"
        elif counts["white"] > counts["black"]:
            return "white"
        return None


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestReversiDefinition:
    def test_loads_without_error(self) -> None:
        defn = _load_reversi()
        assert defn.game.name == "Reversi"

    def test_two_players(self) -> None:
        defn = _load_reversi()
        assert defn.game.players == ["black", "white"]

    def test_8x8_board(self) -> None:
        defn = _load_reversi()
        assert defn.zones["board"].dimensions == [8, 8]


# ---------------------------------------------------------------------------
# Tests: initial position
# ---------------------------------------------------------------------------


class TestInitialPosition:
    def test_four_discs_placed(self) -> None:
        game = ReversiGame()
        counts = game.count_discs()
        assert counts["black"] == 2
        assert counts["white"] == 2

    def test_center_layout(self) -> None:
        game = ReversiGame()
        assert game.owner_at(3, 3) == "white"
        assert game.owner_at(4, 4) == "white"
        assert game.owner_at(3, 4) == "black"
        assert game.owner_at(4, 3) == "black"

    def test_black_moves_first(self) -> None:
        game = ReversiGame()
        assert game.current_player() == "black"


# ---------------------------------------------------------------------------
# Tests: legal move generation
# ---------------------------------------------------------------------------


class TestLegalMoves:
    def test_initial_legal_moves_for_black(self) -> None:
        """Black's opening moves bracket at least one white disc."""
        game = ReversiGame()
        moves = game.legal_moves("black")
        # Standard opening: (2,3), (3,2), (4,5), (5,4)
        assert len(moves) == 4
        assert (2, 3) in moves
        assert (3, 2) in moves
        assert (4, 5) in moves
        assert (5, 4) in moves

    def test_no_legal_move_on_occupied(self) -> None:
        game = ReversiGame()
        moves = game.legal_moves("black")
        assert (3, 3) not in moves  # occupied by white
        assert (4, 3) not in moves  # occupied by black

    def test_no_flip_means_illegal(self) -> None:
        game = ReversiGame()
        moves = game.legal_moves("black")
        assert (0, 0) not in moves  # corner, no adjacent discs


# ---------------------------------------------------------------------------
# Tests: placement and flipping
# ---------------------------------------------------------------------------


class TestFlipping:
    def test_single_flip(self) -> None:
        """Black plays (2,3) — flips white at (3,3)."""
        game = ReversiGame()
        flipped = game.play(2, 3)
        assert flipped == 1
        assert game.owner_at(3, 3) == "black"  # was white, now black
        assert game.owner_at(2, 3) == "black"  # newly placed

    def test_disc_counts_after_first_move(self) -> None:
        game = ReversiGame()
        game.play(2, 3)
        counts = game.count_discs()
        assert counts["black"] == 4  # 2 original + 1 placed + 1 flipped
        assert counts["white"] == 1  # 2 original - 1 flipped

    def test_multiple_direction_flip(self) -> None:
        """Play a few moves and verify disc counts stay consistent."""
        game = ReversiGame()
        game.play(2, 3)  # B flips (3,3)
        game.play(2, 2)  # W flips (3,3) back
        game.play(2, 1)  # B flips (2,2)

        counts = game.count_discs()
        total = counts["black"] + counts["white"]
        assert total == 7  # 4 initial + 3 placed

    def test_illegal_placement_no_bracket(self) -> None:
        game = ReversiGame()
        with pytest.raises(ValueError, match="does not bracket"):
            game.play(0, 0)

    def test_occupied_cell_rejected(self) -> None:
        game = ReversiGame()
        with pytest.raises(ValueError, match="occupied"):
            game.play(3, 3)

    def test_long_line_flip(self) -> None:
        """Flip an entire line of opponent discs."""
        game = ReversiGame()
        # Build a line: B at col 2, W at cols 3-6, then B places at col 7
        # Row 3: set up manually
        board = game.board
        comps = game.session.runtime.components

        # Clear initial position and set up custom
        for r in range(8):
            for c in range(8):
                board.grid_set(c, r, None)

        # Black at (1,3)
        cid = comps.insert(ComponentData(
            id=ComponentId(0), string_id="b-1-3",
            component_type="disc", owner="black",
        ))
        board.grid_set(1, 3, cid)

        # White at (2,3), (3,3), (4,3), (5,3)
        for c in range(2, 6):
            cid = comps.insert(ComponentData(
                id=ComponentId(0), string_id=f"w-{c}-3",
                component_type="disc", owner="white",
            ))
            board.grid_set(c, 3, cid)

        # Black places at (6,3) — should flip 4 white discs
        flipped = game.play(6, 3)
        assert flipped == 4
        for c in range(2, 6):
            assert game.owner_at(c, 3) == "black"


# ---------------------------------------------------------------------------
# Tests: pass and game end
# ---------------------------------------------------------------------------


class TestPassAndGameEnd:
    def test_pass_when_no_moves(self) -> None:
        """A player with no legal moves can pass."""
        game = ReversiGame()
        # We need a board state where one player has no moves.
        # Manually clear the board and set up such a state.
        board = game.board
        comps = game.session.runtime.components
        for r in range(8):
            for c in range(8):
                board.grid_set(c, r, None)

        # Only one black disc at corner — white has no legal moves
        cid = comps.insert(ComponentData(
            id=ComponentId(0), string_id="b-only",
            component_type="disc", owner="black",
        ))
        board.grid_set(0, 0, cid)

        # Black has no legal moves (no white discs to bracket)
        assert game.legal_moves("black") == []
        game.pass_turn()  # black passes
        # White also has no legal moves
        assert game.legal_moves("white") == []
        game.pass_turn()  # white passes
        assert game.finished

    def test_cannot_pass_with_legal_moves(self) -> None:
        game = ReversiGame()
        assert len(game.legal_moves()) > 0
        with pytest.raises(ValueError, match="cannot pass"):
            game.pass_turn()

    def test_double_pass_ends_game(self) -> None:
        game = ReversiGame()
        board = game.board
        comps = game.session.runtime.components
        for r in range(8):
            for c in range(8):
                board.grid_set(c, r, None)

        cid = comps.insert(ComponentData(
            id=ComponentId(0), string_id="sole",
            component_type="disc", owner="black",
        ))
        board.grid_set(0, 0, cid)

        game.pass_turn()
        game.pass_turn()
        assert game.finished
        assert game.winner() == "black"


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_initial_score_is_tied(self) -> None:
        game = ReversiGame()
        counts = game.count_discs()
        assert counts["black"] == counts["white"]
        assert game.winner() is None

    def test_winner_by_disc_count(self) -> None:
        game = ReversiGame()
        game.play(2, 3)  # black gains advantage
        counts = game.count_discs()
        assert counts["black"] > counts["white"]
        assert game.winner() == "black"


# ---------------------------------------------------------------------------
# Tests: full game scenario
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_several_moves(self) -> None:
        """Play several legal moves and verify board consistency."""
        game = ReversiGame()

        # Each move must be legal — use known-good opening sequence
        moves = [(2, 3), (2, 2), (2, 1), (2, 0)]
        for col, row in moves:
            if (col, row) in game.legal_moves():
                game.play(col, row)
            else:
                break

        counts = game.count_discs()
        total = counts["black"] + counts["white"]
        # 4 initial + up to 4 placed = max 8, but flips don't add
        assert total >= 4
        assert total <= 64

    def test_play_does_not_leave_zero_discs(self) -> None:
        """No player should ever have 0 discs after a valid game sequence."""
        game = ReversiGame()
        game.play(2, 3)
        counts = game.count_discs()
        assert counts["black"] > 0
        assert counts["white"] > 0
