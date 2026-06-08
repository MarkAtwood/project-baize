use baize_engine::{BaizeError, GameDefinition};

const TIC_TAC_TOE: &str = r#"{
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
}"#;

#[test]
fn parse_tic_tac_toe() {
    let def = GameDefinition::from_json(TIC_TAC_TOE).expect("parse failed");
    assert_eq!(def.game.name, "Tic-Tac-Toe");
    assert_eq!(def.zones.len(), 1);
    assert!(def.zones.contains_key("board"));
    assert_eq!(def.components.len(), 1);
    assert_eq!(def.end_conditions.len(), 2);
    assert!(def.authority.server_only.is_empty());
    assert_eq!(def.authority.client_verifiable, vec!["all"]);
    assert!(def.wasm_module.is_none());
}

#[test]
fn round_trip_tic_tac_toe() {
    let def = GameDefinition::from_json(TIC_TAC_TOE).expect("parse failed");
    let json = serde_json::to_string_pretty(&def).expect("serialize failed");
    let def2 = GameDefinition::from_json(&json).expect("re-parse failed");
    assert_eq!(def2.game.name, def.game.name);
    assert_eq!(def2.zones.len(), def.zones.len());
    assert_eq!(def2.end_conditions.len(), def.end_conditions.len());
}

const CHESS_MINIMAL: &str = r#"{
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
}"#;

#[test]
fn parse_chess_minimal() {
    let def = GameDefinition::from_json(CHESS_MINIMAL).expect("parse failed");
    assert_eq!(def.game.name, "Chess");
    assert_eq!(def.components.len(), 3);

    let pawn = &def.components["pawn"];
    assert_eq!(pawn.movement.len(), 3);
    assert!(pawn.promotion.is_some());

    let rook = &def.components["rook"];
    assert_eq!(rook.special.as_deref(), Some("castling_participant"));

    assert_eq!(def.rules.len(), 2);
    assert!(def.rules.contains_key("check"));
    assert!(def.rules.contains_key("castling"));
}

const POKER_IMPERFECT: &str = r#"{
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
}"#;

#[test]
fn parse_poker_imperfect_info() {
    let def = GameDefinition::from_json(POKER_IMPERFECT).expect("parse failed");
    assert_eq!(def.game.name, "Texas Hold'em");

    // Variable player count
    match &def.game.players {
        baize_engine::definition::Players::Range { min, max } => {
            assert_eq!(*min, 2);
            assert_eq!(*max, 10);
        }
        _ => panic!("expected Range players"),
    }

    // Private visibility
    let hand = &def.zones["hand"];
    match &hand.visibility {
        baize_engine::definition::Visibility::Private { private } => {
            assert_eq!(private, "owner");
        }
        _ => panic!("expected private visibility"),
    }

    assert_eq!(def.phases.len(), 3);
    assert_eq!(def.authority.server_only.len(), 4);
}

// --- Validation rejection tests ---

#[test]
fn reject_empty_players() {
    let json = r#"{
        "game": { "name": "Bad", "players": [] },
        "zones": {},
        "components": {},
        "turn_order": { "type": "alternating" },
        "end_conditions": [{"result": "draw", "condition": "never"}],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    let err = GameDefinition::from_json(json).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_empty_game_name() {
    let json = r#"{
        "game": { "name": "  ", "players": ["A"] },
        "zones": {},
        "components": {},
        "turn_order": { "type": "alternating" },
        "end_conditions": [{"result": "draw", "condition": "x"}],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    let err = GameDefinition::from_json(json).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_no_end_conditions() {
    let json = r#"{
        "game": { "name": "Bad", "players": ["A"] },
        "zones": {},
        "components": {},
        "turn_order": { "type": "alternating" },
        "end_conditions": [],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    let err = GameDefinition::from_json(json).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_grid_without_dimensions() {
    let json = r#"{
        "game": { "name": "Bad", "players": ["A"] },
        "zones": {
            "board": { "zone_type": "grid", "visibility": "public" }
        },
        "components": {},
        "turn_order": { "type": "alternating" },
        "end_conditions": [{"result": "draw", "condition": "x"}],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    let err = GameDefinition::from_json(json).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn reject_unknown_turn_player() {
    let json = r#"{
        "game": { "name": "Bad", "players": ["A", "B"] },
        "zones": {},
        "components": {},
        "turn_order": { "type": "alternating", "players": ["A", "C"] },
        "end_conditions": [{"result": "draw", "condition": "x"}],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    let err = GameDefinition::from_json(json).unwrap_err();
    assert!(matches!(err, BaizeError::Validation(_)));
}

#[test]
fn accept_valid_minimal_definition() {
    let json = r#"{
        "game": { "name": "Minimal", "players": ["A"] },
        "zones": {},
        "components": {},
        "turn_order": { "type": "alternating" },
        "end_conditions": [{"result": "draw", "condition": "always"}],
        "authority": { "server_only": [], "client_verifiable": [] }
    }"#;
    GameDefinition::from_json(json).expect("valid minimal definition should parse");
}
