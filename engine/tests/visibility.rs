//! Visibility model test runner for Baize (baize-562.4).
//!
//! Loads test vectors from tests/vectors/visibility.json, builds the game
//! state described therein, then applies visibility filtering for each viewer
//! and asserts the expected visible/hidden invariants.
//!
//! Run: cargo test --test visibility  (from the engine/ directory)

use baize_engine::definition::GameDefinition;
use baize_engine::runtime::*;
use baize_engine::state::*;
use baize_engine::visibility::filter_for_viewer;
use indexmap::IndexMap;
use serde_json::Value;
use std::collections::HashSet;

// ---------------------------------------------------------------------------
// Helpers: load the shared test fixture
// ---------------------------------------------------------------------------

fn load_vectors() -> Value {
    let raw = include_str!("../../tests/vectors/visibility.json");
    serde_json::from_str(raw).expect("visibility.json must parse")
}

fn build_game_definition(vectors: &Value) -> GameDefinition {
    let def_value = vectors["game_definition"].clone();
    serde_json::from_value(def_value).expect("game_definition must parse into GameDefinition")
}

/// Build a GameSession and populate it with the components from `setup`.
fn build_session(vectors: &Value) -> GameSession {
    let def = build_game_definition(vectors);
    let mut session = GameSession::new(def).expect("session init");
    session.runtime.status = GameStatus::InProgress;

    let setup = &vectors["setup"];
    let components = setup["components"].as_array().expect("components array");

    for comp in components {
        let id_str = comp["id"].as_str().unwrap().to_string();
        let comp_type = comp["component_type"].as_str().unwrap().to_string();
        let zone_name = comp["zone"].as_str().unwrap().to_string();
        let owner = comp["owner"].as_str().map(|s| s.to_string());

        let mut properties = IndexMap::new();
        if let Some(props) = comp.get("properties").and_then(|p| p.as_object()) {
            for (k, v) in props {
                properties.insert(k.clone(), v.clone());
            }
        }

        let cid = session.runtime.components.insert(ComponentData {
            id: ComponentId(0),
            string_id: id_str,
            component_type: comp_type,
            owner: owner.clone(),
            facing: None,
            state: None,
            properties,
        }).unwrap();

        // Place into the correct zone.
        // Per-player zones live under player.zones; shared zones under session.runtime.zones.
        if let Some(ref owner_name) = owner {
            if let Some(player) = session.runtime.players.get_mut(owner_name) {
                if let Some(zone) = player.zones.get_mut(&zone_name) {
                    zone.set_add(cid);
                    continue;
                }
            }
        }
        // Shared zone
        if let Some(zone) = session.runtime.zones.get_mut(&zone_name) {
            match zone {
                RuntimeZone::OrderedStack { components } => components.push(cid),
                RuntimeZone::Set { components } => components.push(cid),
                _ => panic!("unexpected zone type for {zone_name}"),
            }
        } else {
            panic!("zone {zone_name} not found");
        }
    }

    session
}

/// Collect all component IDs from a wire zone state.
fn zone_component_ids(zone: &ZoneState) -> Vec<String> {
    match zone {
        ZoneState::OrderedStack { components, .. } | ZoneState::Set { components, .. } => {
            components.iter().map(|c| c.id.clone()).collect()
        }
        ZoneState::Grid { cells } => {
            let mut ids = Vec::new();
            for contents in cells.values() {
                match contents {
                    CellContents::Single(c) => ids.push(c.id.clone()),
                    CellContents::Multiple(cs) => {
                        for c in cs {
                            ids.push(c.id.clone());
                        }
                    }
                    CellContents::Empty => {}
                }
            }
            ids
        }
        ZoneState::SingleSlot { component } => {
            component.iter().map(|c| c.id.clone()).collect()
        }
        ZoneState::Counter { .. } => Vec::new(),
        ZoneState::Track { positions } => positions
            .values()
            .flat_map(|v| v.iter().map(|c| c.id.clone()))
            .collect(),
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn public_zone_visible_to_all() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    // Both alice and bob see community cards
    for viewer in &["alice", "bob"] {
        let view = filter_for_viewer(&full_state, viewer, &def);
        let community = view.zones.get("community").expect("community zone");
        let ids: HashSet<String> = zone_component_ids(community).into_iter().collect();
        assert!(ids.contains("card-AH"), "{viewer} must see card-AH");
        assert!(ids.contains("card-KH"), "{viewer} must see card-KH");
        assert!(ids.contains("card-QS"), "{viewer} must see card-QS");
        assert_eq!(ids.len(), 3, "{viewer} should see exactly 3 community cards");
    }
}

#[test]
fn hidden_zone_invisible_to_players() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    for viewer in &["alice", "bob"] {
        let view = filter_for_viewer(&full_state, viewer, &def);

        // Deck: hidden zone — no component IDs visible
        let deck = view.zones.get("deck").expect("deck zone");
        let deck_ids = zone_component_ids(deck);
        assert!(
            deck_ids.is_empty(),
            "{viewer} must NOT see deck contents, found: {deck_ids:?}"
        );

        // Discard: also hidden
        let discard = view.zones.get("discard").expect("discard zone");
        let discard_ids = zone_component_ids(discard);
        assert!(
            discard_ids.is_empty(),
            "{viewer} must NOT see discard contents, found: {discard_ids:?}"
        );
    }
}

#[test]
fn hidden_zone_count_preserved() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    let view = filter_for_viewer(&full_state, "alice", &def);

    // Deck should report count=3 even though contents are hidden
    if let ZoneState::OrderedStack { count, .. } = view.zones.get("deck").unwrap() {
        assert_eq!(*count, Some(3), "deck count should be 3");
    } else {
        panic!("deck should be OrderedStack");
    }

    // Discard should report count=1
    if let ZoneState::Set { count, .. } = view.zones.get("discard").unwrap() {
        assert_eq!(*count, Some(1), "discard count should be 1");
    } else {
        panic!("discard should be Set");
    }
}

#[test]
fn private_zone_visible_to_owner() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    // Alice sees her own hand
    let alice_view = filter_for_viewer(&full_state, "alice", &def);
    let alice_hand = alice_view
        .players
        .get("alice")
        .and_then(|p| p.zones.get("hand"))
        .expect("alice should have hand zone");
    let alice_hand_ids: HashSet<String> = zone_component_ids(alice_hand).into_iter().collect();
    assert!(
        alice_hand_ids.contains("card-JD"),
        "alice must see her card-JD"
    );
    assert!(
        alice_hand_ids.contains("card-10S"),
        "alice must see her card-10S"
    );
    assert_eq!(alice_hand_ids.len(), 2, "alice should see exactly 2 cards");

    // Bob sees his own hand
    let bob_view = filter_for_viewer(&full_state, "bob", &def);
    let bob_hand = bob_view
        .players
        .get("bob")
        .and_then(|p| p.zones.get("hand"))
        .expect("bob should have hand zone");
    let bob_hand_ids: HashSet<String> = zone_component_ids(bob_hand).into_iter().collect();
    assert!(bob_hand_ids.contains("card-5C"), "bob must see his card-5C");
    assert!(bob_hand_ids.contains("card-9H"), "bob must see his card-9H");
    assert!(
        bob_hand_ids.contains("card-KD"),
        "bob must see his card-KD"
    );
    assert_eq!(bob_hand_ids.len(), 3, "bob should see exactly 3 cards");
}

#[test]
fn private_zone_hidden_from_non_owner() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    // Alice must NOT see Bob's hand contents
    let alice_view = filter_for_viewer(&full_state, "alice", &def);
    let bob_hand_from_alice = alice_view
        .players
        .get("bob")
        .and_then(|p| p.zones.get("hand"))
        .expect("bob's hand zone should still exist in alice's view");
    let leaked_ids = zone_component_ids(bob_hand_from_alice);
    assert!(
        leaked_ids.is_empty(),
        "SECURITY: alice must NOT see bob's hand, but found: {leaked_ids:?}"
    );

    // Bob must NOT see Alice's hand contents
    let bob_view = filter_for_viewer(&full_state, "bob", &def);
    let alice_hand_from_bob = bob_view
        .players
        .get("alice")
        .and_then(|p| p.zones.get("hand"))
        .expect("alice's hand zone should still exist in bob's view");
    let leaked_ids = zone_component_ids(alice_hand_from_bob);
    assert!(
        leaked_ids.is_empty(),
        "SECURITY: bob must NOT see alice's hand, but found: {leaked_ids:?}"
    );
}

#[test]
fn private_zone_count_visible_to_non_owner() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    // Alice can see that bob has 3 cards (count), even if she can't see them
    let alice_view = filter_for_viewer(&full_state, "alice", &def);
    let bob_hand_from_alice = alice_view
        .players
        .get("bob")
        .and_then(|p| p.zones.get("hand"))
        .expect("bob's hand zone");

    if let ZoneState::Set { count, .. } = bob_hand_from_alice {
        assert_eq!(*count, Some(3), "alice should see bob has 3 cards");
    } else {
        panic!("bob's hand should be a Set");
    }

    // Bob can see that alice has 2 cards
    let bob_view = filter_for_viewer(&full_state, "bob", &def);
    let alice_hand_from_bob = bob_view
        .players
        .get("alice")
        .and_then(|p| p.zones.get("hand"))
        .expect("alice's hand zone");

    if let ZoneState::Set { count, .. } = alice_hand_from_bob {
        assert_eq!(*count, Some(2), "bob should see alice has 2 cards");
    } else {
        panic!("alice's hand should be a Set");
    }
}

#[test]
fn server_sees_everything() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    let server_view = filter_for_viewer(&full_state, "__server__", &def);

    // Server sees deck
    let deck = server_view.zones.get("deck").expect("deck zone");
    let deck_ids: HashSet<String> = zone_component_ids(deck).into_iter().collect();
    assert_eq!(deck_ids.len(), 3, "server sees all 3 deck cards");
    assert!(deck_ids.contains("card-2D"));
    assert!(deck_ids.contains("card-3D"));
    assert!(deck_ids.contains("card-4C"));

    // Server sees discard
    let discard = server_view.zones.get("discard").expect("discard zone");
    let discard_ids = zone_component_ids(discard);
    assert_eq!(discard_ids.len(), 1);
    assert_eq!(discard_ids[0], "card-7H");

    // Server sees community
    let community = server_view.zones.get("community").expect("community zone");
    let comm_ids: HashSet<String> = zone_component_ids(community).into_iter().collect();
    assert_eq!(comm_ids.len(), 3);

    // Server sees both hands
    let alice_hand = server_view
        .players
        .get("alice")
        .and_then(|p| p.zones.get("hand"))
        .expect("alice hand");
    let alice_ids: HashSet<String> = zone_component_ids(alice_hand).into_iter().collect();
    assert_eq!(alice_ids.len(), 2);
    assert!(alice_ids.contains("card-JD"));
    assert!(alice_ids.contains("card-10S"));

    let bob_hand = server_view
        .players
        .get("bob")
        .and_then(|p| p.zones.get("hand"))
        .expect("bob hand");
    let bob_ids: HashSet<String> = zone_component_ids(bob_hand).into_iter().collect();
    assert_eq!(bob_ids.len(), 3);
    assert!(bob_ids.contains("card-5C"));
    assert!(bob_ids.contains("card-9H"));
    assert!(bob_ids.contains("card-KD"));
}

#[test]
fn public_counter_visible_to_all() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    // Public per-player counters (score) should be visible to both players
    for viewer in &["alice", "bob"] {
        let view = filter_for_viewer(&full_state, viewer, &def);

        for player_name in &["alice", "bob"] {
            let score_zone = view
                .players
                .get(*player_name)
                .and_then(|p| p.zones.get("score"))
                .expect(&format!("{player_name}'s score zone"));

            // Counter zones are always visible when public — they hold a value, not components
            if let ZoneState::Counter { .. } = score_zone {
                // Expected: counter is present and unredacted
            } else {
                panic!("{player_name}'s score should be a Counter zone");
            }
        }
    }
}

#[test]
fn filtered_view_never_leaks_hidden_component_properties() {
    let vectors = load_vectors();
    let session = build_session(&vectors);
    let def = build_game_definition(&vectors);
    let full_state = session.to_wire_state();

    let alice_view = filter_for_viewer(&full_state, "alice", &def);

    // Serialize alice's view to JSON and search for hidden component IDs
    let json = serde_json::to_string(&alice_view).unwrap();

    // These are in the deck (hidden zone) — must not appear anywhere in alice's view
    assert!(
        !json.contains("card-2D"),
        "SECURITY: card-2D (hidden deck) leaked into alice's view"
    );
    assert!(
        !json.contains("card-3D"),
        "SECURITY: card-3D (hidden deck) leaked into alice's view"
    );
    assert!(
        !json.contains("card-4C"),
        "SECURITY: card-4C (hidden deck) leaked into alice's view"
    );
    assert!(
        !json.contains("card-7H"),
        "SECURITY: card-7H (hidden discard) leaked into alice's view"
    );

    // Bob's hand cards must not appear in alice's view
    assert!(
        !json.contains("card-5C"),
        "SECURITY: card-5C (bob's hand) leaked into alice's view"
    );
    assert!(
        !json.contains("card-9H"),
        "SECURITY: card-9H (bob's hand) leaked into alice's view"
    );
    assert!(
        !json.contains("card-KD"),
        "SECURITY: card-KD (bob's hand) leaked into alice's view"
    );

    // Alice's own cards and public cards SHOULD appear
    assert!(json.contains("card-JD"), "alice should see her own card-JD");
    assert!(
        json.contains("card-10S"),
        "alice should see her own card-10S"
    );
    assert!(
        json.contains("card-AH"),
        "alice should see public card-AH"
    );
}
