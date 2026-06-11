"""Tests for Rubik's Cube face rotation perturber sequences.

Each of the 6 CW moves is defined as a sequence of 5 cycles:
- 2 face cycles (corners + edges of the rotating face)
- 3 strip cycles (edges of the 4 adjacent faces)

Convention: each face viewed from outside the cube. (0,0) = top-left.
CW rotation of face X means clockwise when looking at X from outside.
"""

import json

from baize.definition import GameDefinition
from baize.perturber import execute_effect
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    GridZone,
)

FACES = ["up", "down", "front", "back", "left", "right"]


def _cube_session() -> GameSession:
    zones = {f: {"zone_type": "grid", "dimensions": [3, 3], "visibility": "public"} for f in FACES}
    raw = {
        "game": {"name": "Cube", "players": ["solver"], "information": "perfect"},
        "zones": zones,
        "components": {"sticker": {"owner": "neutral"}},
        "turn_order": {"type": "alternating", "players": ["solver"], "actions_per_turn": 1, "mandatory": False},
        "end_conditions": [{"result": "draw", "condition": "false"}],
        "authority": {"server_only": [], "client_verifiable": ["all"]},
    }
    defn = GameDefinition.from_json(json.dumps(raw))
    session = GameSession(defn)
    session.runtime.status = "in_progress"

    for face in FACES:
        zone = session.runtime.zones[face]
        assert isinstance(zone, GridZone)
        for row in range(3):
            for col in range(3):
                name = f"{face}_{col}_{row}"
                cid = session.runtime.components.insert(
                    ComponentData(id=ComponentId(0), string_id=name, component_type="sticker", owner="neutral")
                )
                zone.grid_set(col, row, cid)
    return session


def _read_state(session: GameSession) -> dict[tuple[str, int, int], str]:
    state: dict[tuple[str, int, int], str] = {}
    for face in FACES:
        zone = session.runtime.zones[face]
        for row in range(3):
            for col in range(3):
                cid = zone.grid_get(col, row)
                if cid is not None:
                    comp = session.runtime.components.get(cid)
                    state[(face, col, row)] = comp.string_id
    return state


# -- Move definitions --

def _cyc(positions: list[tuple[str, int, int]]) -> dict:
    return {"cycle": [{"zone": z, "pos": f"{c},{r}"} for z, c, r in positions]}


def _face_move(face: str, strips: list[list[tuple[str, int, int]]]) -> dict:
    """Build a CW move: face corner/edge cycles + 3 strip cycles."""
    return {"sequence": [
        _cyc([(face, 0, 0), (face, 2, 0), (face, 2, 2), (face, 0, 2)]),
        _cyc([(face, 1, 0), (face, 2, 1), (face, 1, 2), (face, 0, 1)]),
        *[_cyc(s) for s in strips],
    ]}


def _reverse_move(move: dict) -> dict:
    """Reverse a CW move to get CCW: reverse each cycle's position list."""
    return {"sequence": [
        {"cycle": [c["cycle"][0]] + list(reversed(c["cycle"][1:]))}
        for c in move["sequence"]
    ]}


# U CW: F→R→B→L (row 0 of each adjacent face)
U_CW = _face_move("up", [
    [("front", 0, 0), ("right", 0, 0), ("back", 0, 0), ("left", 0, 0)],
    [("front", 1, 0), ("right", 1, 0), ("back", 1, 0), ("left", 1, 0)],
    [("front", 2, 0), ("right", 2, 0), ("back", 2, 0), ("left", 2, 0)],
])

# D CW: F→L→B→R (row 2 of each adjacent face, reversed direction from U)
D_CW = _face_move("down", [
    [("front", 0, 2), ("left", 0, 2), ("back", 0, 2), ("right", 0, 2)],
    [("front", 1, 2), ("left", 1, 2), ("back", 1, 2), ("right", 1, 2)],
    [("front", 2, 2), ("left", 2, 2), ("back", 2, 2), ("right", 2, 2)],
])

# F CW: U→R→D→L (mixed positions due to orientation)
F_CW = _face_move("front", [
    [("up", 0, 2), ("right", 0, 0), ("down", 2, 0), ("left", 2, 2)],
    [("up", 1, 2), ("right", 0, 1), ("down", 1, 0), ("left", 2, 1)],
    [("up", 2, 2), ("right", 0, 2), ("down", 0, 0), ("left", 2, 0)],
])

# B CW: U→L→D→R (mirror of F, different positions)
B_CW = _face_move("back", [
    [("up", 2, 0), ("left", 0, 0), ("down", 0, 2), ("right", 2, 2)],
    [("up", 1, 0), ("left", 0, 1), ("down", 1, 2), ("right", 2, 1)],
    [("up", 0, 0), ("left", 0, 2), ("down", 2, 2), ("right", 2, 0)],
])

# R CW: U→F→D→B (col 2 of U/F/D, col 0 of B reversed)
R_CW = _face_move("right", [
    [("up", 2, 0), ("front", 2, 0), ("down", 2, 0), ("back", 0, 2)],
    [("up", 2, 1), ("front", 2, 1), ("down", 2, 1), ("back", 0, 1)],
    [("up", 2, 2), ("front", 2, 2), ("down", 2, 2), ("back", 0, 0)],
])

# L CW: U→B→D→F (col 0 of U/D/F, col 2 of B reversed)
L_CW = _face_move("left", [
    [("up", 0, 0), ("back", 2, 2), ("down", 0, 0), ("front", 0, 0)],
    [("up", 0, 1), ("back", 2, 1), ("down", 0, 1), ("front", 0, 1)],
    [("up", 0, 2), ("back", 2, 0), ("down", 0, 2), ("front", 0, 2)],
])

ALL_CW_MOVES = {"U": U_CW, "D": D_CW, "F": F_CW, "B": B_CW, "R": R_CW, "L": L_CW}


class TestQuarterTurnIdentity:
    """Each CW move applied 4 times must return to the initial state."""

    def _check_4x_identity(self, move: dict) -> None:
        session = _cube_session()
        initial = _read_state(session)
        for _ in range(4):
            execute_effect(session, move)
        assert _read_state(session) == initial

    def test_u(self) -> None:
        self._check_4x_identity(U_CW)

    def test_d(self) -> None:
        self._check_4x_identity(D_CW)

    def test_f(self) -> None:
        self._check_4x_identity(F_CW)

    def test_b(self) -> None:
        self._check_4x_identity(B_CW)

    def test_r(self) -> None:
        self._check_4x_identity(R_CW)

    def test_l(self) -> None:
        self._check_4x_identity(L_CW)


class TestCwCcwIdentity:
    """CW followed by CCW must return to the initial state."""

    def _check_cw_ccw(self, cw: dict) -> None:
        session = _cube_session()
        initial = _read_state(session)
        execute_effect(session, cw)
        execute_effect(session, _reverse_move(cw))
        assert _read_state(session) == initial

    def test_u(self) -> None:
        self._check_cw_ccw(U_CW)

    def test_d(self) -> None:
        self._check_cw_ccw(D_CW)

    def test_f(self) -> None:
        self._check_cw_ccw(F_CW)

    def test_b(self) -> None:
        self._check_cw_ccw(B_CW)

    def test_r(self) -> None:
        self._check_cw_ccw(R_CW)

    def test_l(self) -> None:
        self._check_cw_ccw(L_CW)


class TestSpecificPositions:
    """Verify specific sticker destinations after one CW move."""

    def test_u_cw_strips(self) -> None:
        session = _cube_session()
        execute_effect(session, U_CW)
        s = _read_state(session)
        # F top row → R top row
        assert s[("right", 0, 0)] == "front_0_0"
        assert s[("right", 1, 0)] == "front_1_0"
        assert s[("right", 2, 0)] == "front_2_0"
        # R top row → B top row
        assert s[("back", 0, 0)] == "right_0_0"
        # B top row → L top row
        assert s[("left", 0, 0)] == "back_0_0"
        # L top row → F top row
        assert s[("front", 0, 0)] == "left_0_0"

    def test_u_cw_face(self) -> None:
        session = _cube_session()
        execute_effect(session, U_CW)
        s = _read_state(session)
        # Face corner rotation: (0,0)→(2,0)→(2,2)→(0,2)→(0,0)
        assert s[("up", 2, 0)] == "up_0_0"
        assert s[("up", 2, 2)] == "up_2_0"
        assert s[("up", 0, 2)] == "up_2_2"
        assert s[("up", 0, 0)] == "up_0_2"
        # Center stays
        assert s[("up", 1, 1)] == "up_1_1"

    def test_u_cw_moves_20_stickers(self) -> None:
        session = _cube_session()
        initial = _read_state(session)
        execute_effect(session, U_CW)
        after = _read_state(session)
        moved = sum(1 for k in initial if initial[k] != after[k])
        assert moved == 20

    def test_each_cw_moves_20_stickers(self) -> None:
        for name, move in ALL_CW_MOVES.items():
            session = _cube_session()
            initial = _read_state(session)
            execute_effect(session, move)
            after = _read_state(session)
            moved = sum(1 for k in initial if initial[k] != after[k])
            assert moved == 20, f"{name} moved {moved} stickers, expected 20"


class TestCompositeSequences:
    """Test well-known Rubik's Cube identities using composed moves."""

    def test_sexy_move_6x_identity(self) -> None:
        """(R U R' U') applied 6 times = identity."""
        session = _cube_session()
        initial = _read_state(session)
        r_ccw = _reverse_move(R_CW)
        u_ccw = _reverse_move(U_CW)
        sexy = {"sequence": [R_CW, U_CW, r_ccw, u_ccw]}
        for _ in range(6):
            execute_effect(session, sexy)
        assert _read_state(session) == initial

    def test_double_move_2x_identity(self) -> None:
        """U2 (= U applied twice) applied twice = identity."""
        session = _cube_session()
        initial = _read_state(session)
        u2 = {"sequence": [U_CW, U_CW]}
        execute_effect(session, u2)
        execute_effect(session, u2)
        assert _read_state(session) == initial
