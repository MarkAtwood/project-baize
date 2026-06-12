"""End-to-end test for a complete Naval Battle game.

Plays two complete games from ship placement through firing to the last ship
being sunk, verifying the winner's ships_remaining counter reaches zero and
all expected sunk events are emitted.
"""

from __future__ import annotations

from baize.action import Action
from baize.definition import GameDefinition
from baize.runtime import GameSession, GridZone
from baize.transition import apply_action


# Minimal Naval Battle definition with two ship types (carrier and destroyer)
# so tests complete quickly.  Two ships per player → ships_remaining starts at 2.
NAVAL_BATTLE_JSON = """{
    "game": { "name": "Naval Battle", "players": ["player_1", "player_2"], "information": "imperfect" },
    "zones": {
        "ocean": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
        "target": { "zone_type": "grid", "dimensions": [10, 10], "per_player": true, "visibility": { "private": "owner" } },
        "ships_remaining": { "zone_type": "counter", "per_player": true, "visibility": "public" }
    },
    "components": {
        "ship": {
            "owner": "per_player",
            "types": {
                "carrier": { "span": 5 },
                "destroyer": { "span": 2 }
            }
        },
        "peg": { "owner": "per_player", "count": "unlimited" }
    },
    "turn_order": { "type": "alternating", "players": ["player_1", "player_2"] },
    "end_conditions": [{ "result": "win", "condition": "false" }],
    "authority": { "server_only": [], "client_verifiable": ["all"] }
}"""


def _make_session() -> GameSession:
    """Create a Naval Battle session with ships_remaining initialised to 2."""
    definition = GameDefinition.from_json(NAVAL_BATTLE_JSON)
    session = GameSession(definition)
    for player in session.runtime.players.values():
        player.counters["ships_remaining"] = 2
    return session


def _place_ship(
    comp_type: str, col: int, row: int, orientation: str
) -> Action:
    return Action(
        action_type="place_ship",
        component_type=comp_type,
        to_pos={"zone": "ocean", "cell": f"{col},{row}"},
        orientation=orientation,
    )


def _fire(col: int, row: int) -> Action:
    return Action(
        action_type="fire",
        to_pos={"zone": "ocean", "cell": f"{col},{row}"},
        zone="target",
    )


def _place_all_ships(session: GameSession) -> None:
    """Place both players' ships so they don't overlap.

    player_1 placement:
      carrier   (span 5) horizontal at (0,0)  → cols 0-4, row 0
      destroyer (span 2) horizontal at (0,1)  → cols 0-1, row 1

    player_2 placement:
      carrier   (span 5) horizontal at (0,2)  → cols 0-4, row 2
      destroyer (span 2) horizontal at (0,3)  → cols 0-1, row 3
    """
    # player_1 places (turn_index 0)
    session.runtime.turn_index = 0
    apply_action(session, _place_ship("carrier", 0, 0, "horizontal"))
    session.runtime.turn_index = 0
    apply_action(session, _place_ship("destroyer", 0, 1, "horizontal"))

    # player_2 places (turn_index 1)
    session.runtime.turn_index = 1
    apply_action(session, _place_ship("carrier", 0, 2, "horizontal"))
    session.runtime.turn_index = 1
    apply_action(session, _place_ship("destroyer", 0, 3, "horizontal"))

    # Reset to player_1's turn for the combat phase.
    session.runtime.turn_index = 0
    session.runtime.status = "in_progress"


def test_full_game_placement() -> None:
    """Both players' ships are placed and recorded on their ocean grids."""
    session = _make_session()
    _place_all_ships(session)

    p1_ocean = session.runtime.players["player_1"].zones["ocean"]
    assert isinstance(p1_ocean, GridZone)
    # carrier occupies cols 0-4, row 0
    for col in range(5):
        assert p1_ocean.grid_get(col, 0) is not None, f"carrier missing at col {col}"
    # destroyer occupies cols 0-1, row 1
    assert p1_ocean.grid_get(0, 1) is not None
    assert p1_ocean.grid_get(1, 1) is not None

    p2_ocean = session.runtime.players["player_2"].zones["ocean"]
    assert isinstance(p2_ocean, GridZone)
    for col in range(5):
        assert p2_ocean.grid_get(col, 2) is not None, f"P2 carrier missing at col {col}"
    assert p2_ocean.grid_get(0, 3) is not None
    assert p2_ocean.grid_get(1, 3) is not None


def test_full_game_player1_wins() -> None:
    """player_1 sinks all player_2 ships; ships_remaining drops to 0.

    player_1 fires precisely at player_2's ships.
    player_2 fires into empty water on every turn.
    Ship positions: player_2 carrier at (0-4, 2), destroyer at (0-1, 3).
    """
    session = _make_session()
    _place_all_ships(session)

    # All of player_2's ship cells that player_1 must hit.
    # carrier: (0,2),(1,2),(2,2),(3,2),(4,2) — 5 hits
    # destroyer: (0,3),(1,3)                 — 2 hits
    player1_shots: list[tuple[int, int]] = [
        (0, 2), (1, 2), (2, 2), (3, 2), (4, 2),  # carrier
        (0, 3), (1, 3),                            # destroyer
    ]

    # player_2 fires into empty water (row 9, guaranteed no ships there).
    player2_misses: list[tuple[int, int]] = [
        (col, 9) for col in range(len(player1_shots) - 1)
    ]

    sunk_events: list[str] = []

    shot_index = 0
    for p1_col, p1_row in player1_shots:
        # player_1's turn
        assert session.current_player() == "player_1"
        events = apply_action(session, _fire(p1_col, p1_row))
        event_types = [e.event_type for e in events]
        assert "fire" in event_types
        assert "hit" in event_types, (
            f"Expected hit at ({p1_col},{p1_row}), got {event_types}"
        )
        for e in events:
            if e.event_type == "sunk":
                sunk_events.append(e.component_id or "")

        # player_2's turn (fire into empty water, if there are remaining turns)
        if shot_index < len(player2_misses):
            assert session.current_player() == "player_2"
            p2_col, p2_row = player2_misses[shot_index]
            miss_events = apply_action(session, _fire(p2_col, p2_row))
            miss_types = [e.event_type for e in miss_events]
            assert "miss" in miss_types

        shot_index += 1

    # All of player_2's ships are sunk.
    assert session.runtime.players["player_2"].counters["ships_remaining"] == 0, (
        "player_2 should have 0 ships remaining after all ships are sunk"
    )

    # Both ship types were sunk exactly once.
    assert "carrier" in sunk_events, "carrier sunk event missing"
    assert "destroyer" in sunk_events, "destroyer sunk event missing"
    assert len(sunk_events) == 2, f"Expected 2 sunk events, got {sunk_events}"

    # player_1 still has both ships intact.
    assert session.runtime.players["player_1"].counters["ships_remaining"] == 2


def test_full_game_player2_wins() -> None:
    """player_2 sinks all player_1 ships; ships_remaining drops to 0.

    player_1 fires misses first; then player_2 fires hits.
    Ship positions: player_1 carrier at (0-4, 0), destroyer at (0-1, 1).
    """
    session = _make_session()
    _place_all_ships(session)

    # player_2 must hit: carrier (0-4, 0), destroyer (0-1, 1)
    player2_shots: list[tuple[int, int]] = [
        (0, 0), (1, 0), (2, 0), (3, 0), (4, 0),  # carrier
        (0, 1), (1, 1),                            # destroyer
    ]

    # player_1 fires into empty water (row 9).
    player1_misses: list[tuple[int, int]] = [
        (col, 9) for col in range(len(player2_shots))
    ]

    sunk_events: list[str] = []

    for i, (p2_col, p2_row) in enumerate(player2_shots):
        # player_1 fires a miss first on each round.
        assert session.current_player() == "player_1"
        p1_col, p1_row = player1_misses[i]
        miss_events = apply_action(session, _fire(p1_col, p1_row))
        assert "miss" in [e.event_type for e in miss_events]

        # player_2 fires a hit.
        assert session.current_player() == "player_2"
        events = apply_action(session, _fire(p2_col, p2_row))
        event_types = [e.event_type for e in events]
        assert "hit" in event_types, (
            f"Expected hit at ({p2_col},{p2_row}), got {event_types}"
        )
        for e in events:
            if e.event_type == "sunk":
                sunk_events.append(e.component_id or "")

    # All of player_1's ships are sunk.
    assert session.runtime.players["player_1"].counters["ships_remaining"] == 0, (
        "player_1 should have 0 ships remaining after all ships are sunk"
    )

    assert "carrier" in sunk_events
    assert "destroyer" in sunk_events
    assert len(sunk_events) == 2

    # player_2 still has both ships intact.
    assert session.runtime.players["player_2"].counters["ships_remaining"] == 2


def test_game_end_condition_ships_remaining_zero() -> None:
    """End condition: ships_remaining == 0 is the correct terminal state.

    This test verifies the game-end condition defined in battleship.json:
      'opponent ships_remaining == 0'

    We play until all opponent ships are sunk, then assert:
    - ships_remaining counter is 0 (the condition is satisfied)
    - the last sunk event carries the correct ship type
    - player_1 fired exactly enough shots to sink all player_2 ships

    Note: automatic game_end event detection requires the CEL evaluator to
    expose per-player counter variables ('opponent ships_remaining').  That
    wiring is not yet implemented; this test verifies the underlying state
    that the condition checks.
    """
    session = _make_session()
    _place_all_ships(session)

    # carrier cells
    carrier_cells = [(col, 2) for col in range(5)]
    # destroyer cells
    destroyer_cells = [(0, 3), (1, 3)]
    all_target_cells = carrier_cells + destroyer_cells

    total_hits = 0
    last_sunk_ship_type: str | None = None
    miss_col = 0  # monotonically advancing column for player_2 misses

    for col, row in all_target_cells:
        # player_1 fires
        assert session.current_player() == "player_1"
        events = apply_action(session, _fire(col, row))
        total_hits += 1

        sunk = [e for e in events if e.event_type == "sunk"]
        if sunk:
            last_sunk_ship_type = sunk[0].component_id

        # Consume player_2's turn with a miss (row 9 is empty, unique columns)
        assert session.current_player() == "player_2"
        apply_action(session, _fire(miss_col, 9))
        miss_col += 1

    # The end condition 'opponent ships_remaining == 0' is now satisfied.
    opponent_remaining = session.runtime.players["player_2"].counters["ships_remaining"]
    assert opponent_remaining == 0, (
        f"End condition 'opponent ships_remaining == 0' not met: "
        f"ships_remaining={opponent_remaining}"
    )

    # The last ship sunk is the destroyer (last in the target list).
    assert last_sunk_ship_type == "destroyer"

    # player_1 fired exactly 7 shots (5 + 2) to sink all ships.
    assert total_hits == 7


def test_sunk_events_emitted_in_order() -> None:
    """sunk events appear after the final hit on each ship, in ship order."""
    session = _make_session()
    _place_all_ships(session)

    sunk_sequence: list[tuple[int, str]] = []  # (sequence, ship_type)

    # Sink the carrier first (5 hits), then the destroyer (2 hits).
    # player_2 fires misses in between using unique columns on row 9.
    carrier_cells = [(col, 2) for col in range(5)]
    destroyer_cells = [(0, 3), (1, 3)]
    miss_col = 0  # monotonically advancing column for player_2 misses

    for col, row in carrier_cells + destroyer_cells:
        assert session.current_player() == "player_1"
        events = apply_action(session, _fire(col, row))
        for e in events:
            if e.event_type == "sunk":
                sunk_sequence.append((e.sequence, e.component_id or ""))

        assert session.current_player() == "player_2"
        apply_action(session, _fire(miss_col, 9))  # miss
        miss_col += 1

    assert len(sunk_sequence) == 2
    # carrier sunk first, then destroyer
    assert sunk_sequence[0][1] == "carrier"
    assert sunk_sequence[1][1] == "destroyer"
    # sequences are non-decreasing
    assert sunk_sequence[0][0] <= sunk_sequence[1][0]


def test_no_friendly_fire() -> None:
    """Firing at an opponent cell that is empty (row 9) always produces a miss."""
    session = _make_session()
    _place_all_ships(session)

    # player_1 fires at row 9 — no ships there for either player.
    events = apply_action(session, _fire(0, 9))
    event_types = [e.event_type for e in events]
    assert "miss" in event_types
    assert "hit" not in event_types
    assert "sunk" not in event_types


def test_hit_count_accumulates_before_sunk() -> None:
    """hit_count on the carrier increments with each hit before sunk fires."""
    session = _make_session()
    _place_all_ships(session)

    # player_2's carrier is at cols 0-4, row 2.  Find its ComponentId.
    p2_ocean = session.runtime.players["player_2"].zones["ocean"]
    assert isinstance(p2_ocean, GridZone)
    carrier_cid = p2_ocean.grid_get(0, 2)
    assert carrier_cid is not None

    for i in range(5):
        # player_1 fires at carrier cell i
        assert session.current_player() == "player_1"
        apply_action(session, _fire(i, 2))

        comp = session.runtime.components.get(carrier_cid)
        assert comp is not None
        expected_hits = i + 1
        actual_hits = comp.properties.get("hit_count", 0)
        assert actual_hits == expected_hits, (
            f"After {expected_hits} hits: expected hit_count={expected_hits}, "
            f"got {actual_hits}"
        )

        if i < 4:
            # Carrier not yet sunk; player_2 takes a miss turn.
            assert session.current_player() == "player_2"
            apply_action(session, _fire(i, 9))
