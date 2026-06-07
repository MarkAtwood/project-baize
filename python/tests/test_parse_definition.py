"""Port of engine/tests/parse_definition.rs test fixtures.

Tests tic-tac-toe, chess minimal, and poker game definitions.
Each fixture tests parse, field assertions, and round-trip (parse -> serialize -> re-parse).
"""

from baize.definition import (
    GameDefinition,
    PlayerRange,
    PrivateVisibility,
)

# ---------------------------------------------------------------------------
# Fixtures  (exact JSON from engine/tests/parse_definition.rs)
# ---------------------------------------------------------------------------

TIC_TAC_TOE = """{
    "game": {
        "name": "Tic-Tac-Toe",
        "players": ["X", "O"],
        "information": "perfect"
    },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [3, 3],
            "visibility": "public"
        }
    },
    "components": {
        "mark": {
            "owner": "per_player",
            "count": "unlimited"
        }
    },
    "turn_order": {
        "type": "alternating",
        "players": ["X", "O"],
        "actions_per_turn": 1,
        "mandatory": true
    },
    "end_conditions": [
        {
            "result": "win",
            "player": "current",
            "condition": "three_in_line(current.marks, row OR column OR diagonal)"
        },
        {
            "result": "draw",
            "condition": "board_is_full"
        }
    ],
    "authority": {
        "server_only": [],
        "client_verifiable": ["all"]
    }
}"""

CHESS_MINIMAL = """{
    "game": {
        "name": "Chess",
        "players": ["white", "black"],
        "information": "perfect"
    },
    "zones": {
        "board": {
            "zone_type": "grid",
            "dimensions": [8, 8],
            "visibility": "public",
            "coloring": "alternating",
            "labels": {
                "files": ["a","b","c","d","e","f","g","h"],
                "ranks": [1,2,3,4,5,6,7,8]
            }
        }
    },
    "components": {
        "king": {
            "owner": "per_player",
            "count": 1,
            "movement": [
                { "primitive": "step", "direction": "adjacent" }
            ],
            "constraints": ["cannot_move_into_check"]
        },
        "rook": {
            "owner": "per_player",
            "count": 2,
            "movement": [
                { "primitive": "slide", "direction": "orthogonal" }
            ],
            "special": "castling_participant"
        },
        "pawn": {
            "owner": "per_player",
            "count": 8,
            "movement": [
                { "primitive": "step", "direction": "forward", "distance": 1, "condition": "empty" },
                { "primitive": "step", "direction": "forward", "distance": 2, "condition": "empty AND first_move" },
                { "primitive": "step", "direction": "forward_diagonal", "distance": 1, "condition": "enemy" }
            ],
            "promotion": {
                "trigger": "reaches_last_rank",
                "choices": ["queen", "rook", "bishop", "knight"]
            }
        }
    },
    "turn_order": {
        "type": "alternating",
        "players": ["white", "black"],
        "actions_per_turn": 1,
        "mandatory": true
    },
    "rules": {
        "check": {
            "definition": "king is attacked by opponent piece",
            "constraint": "player in check MUST resolve check this turn"
        },
        "castling": {
            "requires": [
                "king has not moved",
                "participating rook has not moved",
                "no pieces between king and rook",
                "king not in check"
            ]
        }
    },
    "end_conditions": [
        {
            "result": "win",
            "player": "opponent_of_current",
            "condition": "in_check(current) AND no_legal_moves(current)",
            "name": "checkmate"
        },
        {
            "result": "draw",
            "condition": "NOT in_check(current) AND no_legal_moves(current)",
            "name": "stalemate"
        }
    ],
    "authority": {
        "server_only": [],
        "client_verifiable": ["all"]
    }
}"""

POKER_IMPERFECT = """{
    "game": {
        "name": "Texas Hold'em",
        "players": { "min": 2, "max": 10 },
        "information": "imperfect"
    },
    "zones": {
        "deck": {
            "zone_type": "ordered_stack",
            "capacity": 52,
            "visibility": "hidden"
        },
        "community": {
            "zone_type": "set",
            "capacity": 5,
            "visibility": "public"
        },
        "hand": {
            "zone_type": "set",
            "per_player": true,
            "capacity": 2,
            "visibility": { "private": "owner" }
        },
        "pot": {
            "zone_type": "counter",
            "visibility": "public"
        }
    },
    "components": {
        "card": {
            "properties": {
                "suit": ["hearts", "diamonds", "clubs", "spades"],
                "rank": ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
            },
            "facing": "face_down",
            "count": 52
        }
    },
    "turn_order": {
        "type": "round_robin"
    },
    "phases": [
        { "name": "deal", "server_action": "deal(deck, hand, count:2, to:each_player)" },
        { "name": "preflop", "type": "betting_round", "starts_with": "player_after(big_blind)" },
        { "name": "flop", "server_action": ["burn(deck, discard, count:1)", "reveal(deck, community, count:3)"] }
    ],
    "end_conditions": [
        {
            "result": "win",
            "condition": "best_hand(hand + community) after showdown"
        }
    ],
    "authority": {
        "server_only": ["shuffle(deck)", "deal(deck, hand)", "burn(deck, discard)", "reveal(deck, community)"],
        "client_verifiable": ["fold()", "check()", "call()", "raise(amount)", "hand_comparison()"]
    }
}"""


# ---------------------------------------------------------------------------
# Tests mirroring engine/tests/parse_definition.rs
# ---------------------------------------------------------------------------


class TestParseTicTacToe:
    def test_parse(self) -> None:
        defn = GameDefinition.from_json(TIC_TAC_TOE)
        assert defn.game.name == "Tic-Tac-Toe"
        assert len(defn.zones) == 1
        assert "board" in defn.zones
        assert len(defn.components) == 1
        assert len(defn.end_conditions) == 2
        assert defn.authority.server_only == []
        assert defn.authority.client_verifiable == ["all"]
        assert defn.wasm_module is None

    def test_round_trip(self) -> None:
        defn = GameDefinition.from_json(TIC_TAC_TOE)
        json_str = defn.to_json()
        defn2 = GameDefinition.from_json(json_str)
        assert defn2.game.name == defn.game.name
        assert len(defn2.zones) == len(defn.zones)
        assert len(defn2.end_conditions) == len(defn.end_conditions)


class TestParseChessMinimal:
    def test_parse(self) -> None:
        defn = GameDefinition.from_json(CHESS_MINIMAL)
        assert defn.game.name == "Chess"
        assert len(defn.components) == 3

        pawn = defn.components["pawn"]
        assert len(pawn.movement) == 3
        assert pawn.promotion is not None

        rook = defn.components["rook"]
        assert rook.special == "castling_participant"

        assert len(defn.rules) == 2
        assert "check" in defn.rules
        assert "castling" in defn.rules

    def test_round_trip(self) -> None:
        defn = GameDefinition.from_json(CHESS_MINIMAL)
        json_str = defn.to_json()
        defn2 = GameDefinition.from_json(json_str)
        assert defn2.game.name == defn.game.name
        assert len(defn2.components) == len(defn.components)
        assert len(defn2.rules) == len(defn.rules)


class TestParsePokerImperfectInfo:
    def test_parse(self) -> None:
        defn = GameDefinition.from_json(POKER_IMPERFECT)
        assert defn.game.name == "Texas Hold'em"

        # Variable player count
        players = defn.game.players
        assert isinstance(players, PlayerRange)
        assert players.min == 2
        assert players.max == 10

        # Private visibility
        hand = defn.zones["hand"]
        assert isinstance(hand.visibility, PrivateVisibility)
        assert hand.visibility.private == "owner"

        assert len(defn.phases) == 3
        assert len(defn.authority.server_only) == 4

    def test_round_trip(self) -> None:
        defn = GameDefinition.from_json(POKER_IMPERFECT)
        json_str = defn.to_json()
        defn2 = GameDefinition.from_json(json_str)
        assert defn2.game.name == defn.game.name
        assert isinstance(defn2.game.players, PlayerRange)
        assert defn2.game.players.min == 2
        assert defn2.game.players.max == 10
        hand2 = defn2.zones["hand"]
        assert isinstance(hand2.visibility, PrivateVisibility)
        assert hand2.visibility.private == "owner"
        assert len(defn2.phases) == len(defn.phases)
        assert len(defn2.authority.server_only) == len(defn.authority.server_only)
