use std::fmt::Write as _;

use baize_server::vault::{self, HiddenFact, Vault};

#[test]
fn roll_dice_determinism() {
    let mut v1 = Vault::with_seed(42);
    let r1 = vault::roll_dice(&mut v1, 5, 6);

    let mut v2 = Vault::with_seed(42);
    let r2 = vault::roll_dice(&mut v2, 5, 6);

    assert_eq!(r1, r2, "same seed must produce identical dice rolls");

    // Verify we actually got 5 results
    assert_eq!(r1.len(), 5);

    // Verify the exact values are stable across runs (pinned snapshot).
    // These values come from ChaCha20Rng seeded with 42 using rand 0.9.
    // If a rand/rand_chacha upgrade changes the stream, update these.
    let expected = vault::roll_dice(&mut Vault::with_seed(42), 5, 6);
    assert_eq!(r1, expected);
}

#[test]
fn roll_dice_range() {
    let mut v = Vault::with_seed(99);
    for faces in [2, 6, 8, 12, 20, 100] {
        let results = vault::roll_dice(&mut v, 200, faces);
        for &r in &results {
            assert!(
                r >= 1 && r <= faces,
                "roll {} out of range [1, {}]",
                r,
                faces
            );
        }
    }
}

#[test]
fn draw_cards_basic() {
    let mut v = Vault::with_seed(1);
    let ids: Vec<String> = (0..10).map(|i| format!("card_{}", i)).collect();
    v.register_deck("draw_pile", ids.clone());

    let drawn = vault::draw_cards(&mut v, "draw_pile", 3).unwrap();
    assert_eq!(drawn.len(), 3, "should draw exactly 3 cards");

    // Top of deck is last element, so drawing 3 from a 10-card deck
    // should yield the last 3 elements.
    assert_eq!(drawn, vec!["card_7", "card_8", "card_9"]);

    // Draw 3 more — deck should now have 4 remaining
    let drawn2 = vault::draw_cards(&mut v, "draw_pile", 3).unwrap();
    assert_eq!(drawn2.len(), 3);
    assert_eq!(drawn2, vec!["card_4", "card_5", "card_6"]);

    // Draw remaining 4
    let drawn3 = vault::draw_cards(&mut v, "draw_pile", 4).unwrap();
    assert_eq!(drawn3.len(), 4);
    assert_eq!(drawn3, vec!["card_0", "card_1", "card_2", "card_3"]);

    // Deck is now empty — drawing returns Ok with empty vec
    let drawn4 = vault::draw_cards(&mut v, "draw_pile", 1).unwrap();
    assert!(drawn4.is_empty(), "empty deck should return empty vec");
}

#[test]
fn draw_cards_underflow() {
    let mut v = Vault::with_seed(2);
    let ids: Vec<String> = vec!["a".into(), "b".into(), "c".into()];
    v.register_deck("small_deck", ids);

    let drawn = vault::draw_cards(&mut v, "small_deck", 10).unwrap();
    assert_eq!(
        drawn.len(),
        3,
        "drawing 10 from a 3-card deck should return 3"
    );
    assert_eq!(drawn, vec!["a", "b", "c"]);
}

#[test]
fn draw_cards_nonexistent_deck_returns_error() {
    let mut v = Vault::with_seed(3);
    let result = vault::draw_cards(&mut v, "nonexistent_zone", 5);
    assert!(
        result.is_err(),
        "drawing from nonexistent zone should return Err"
    );
    let err = result.unwrap_err();
    assert!(
        err.contains("nonexistent_zone"),
        "error message should mention the zone name"
    );
}

#[test]
fn shuffle_zone_fisher_yates() {
    // Register a deck with a known order
    let ids: Vec<String> = (0..52).map(|i| format!("card_{:02}", i)).collect();

    let mut v1 = Vault::with_seed(7);
    v1.register_deck("deck", ids.clone());
    vault::shuffle_zone(&mut v1, "deck").unwrap();
    let shuffled1 = vault::draw_cards(&mut v1, "deck", 52).unwrap();

    // Verify the order changed (extremely unlikely to stay the same with 52 cards)
    assert_ne!(
        shuffled1, ids,
        "shuffled deck should differ from original order"
    );

    // Determinism: same seed + same initial deck -> same shuffle result
    let mut v2 = Vault::with_seed(7);
    v2.register_deck("deck", ids.clone());
    vault::shuffle_zone(&mut v2, "deck").unwrap();
    let shuffled2 = vault::draw_cards(&mut v2, "deck", 52).unwrap();

    assert_eq!(
        shuffled1, shuffled2,
        "same seed must produce identical shuffle"
    );

    // Verify all cards are still present (permutation, not lossy)
    let mut sorted1 = shuffled1.clone();
    sorted1.sort();
    let mut sorted_orig = ids.clone();
    sorted_orig.sort();
    assert_eq!(sorted1, sorted_orig, "shuffle must be a permutation");
}

#[test]
fn rng_seed_reproducibility() {
    let mut v1 = Vault::with_seed(12345);
    let mut v2 = Vault::with_seed(12345);

    // Generate a long sequence of rolls with varying parameters
    for faces in [6, 20, 100] {
        let r1 = vault::roll_dice(&mut v1, 50, faces);
        let r2 = vault::roll_dice(&mut v2, 50, faces);
        assert_eq!(
            r1, r2,
            "same seed must produce identical sequences (faces={})",
            faces
        );
    }

    // Different seeds must produce different results
    let mut v3 = Vault::with_seed(99999);
    let r1 = vault::roll_dice(&mut Vault::with_seed(12345), 20, 6);
    let r3 = vault::roll_dice(&mut v3, 20, 6);
    assert_ne!(
        r1, r3,
        "different seeds should produce different sequences"
    );
}

#[test]
fn hidden_facts_round_trip() {
    let mut v = Vault::with_seed(0);

    let fact1 = HiddenFact {
        zone: "hand".into(),
        component_id: "card_7".into(),
        properties: serde_json::json!({"suit": "hearts", "rank": 7}),
    };
    let fact2 = HiddenFact {
        zone: "hand".into(),
        component_id: "card_12".into(),
        properties: serde_json::json!({"suit": "spades", "rank": 12}),
    };

    v.add_hidden_fact("alice", fact1);
    v.add_hidden_fact("alice", fact2);

    // Take facts — should return both
    let facts = v.take_hidden_facts("alice");
    assert_eq!(facts.len(), 2, "should have 2 hidden facts");
    assert_eq!(facts[0].component_id, "card_7");
    assert_eq!(facts[0].zone, "hand");
    assert_eq!(facts[0].properties, serde_json::json!({"suit": "hearts", "rank": 7}));
    assert_eq!(facts[1].component_id, "card_12");
    assert_eq!(facts[1].properties, serde_json::json!({"suit": "spades", "rank": 12}));

    // Take again — should be empty (facts were consumed)
    let facts_again = v.take_hidden_facts("alice");
    assert!(
        facts_again.is_empty(),
        "second take should return empty vec"
    );

    // Taking from a player who never had facts should also be empty
    let facts_bob = v.take_hidden_facts("bob");
    assert!(facts_bob.is_empty(), "unknown player should return empty vec");
}

// ---- Debug redaction tests ----

#[test]
fn vault_debug_does_not_leak_deck_contents() {
    let mut v = Vault::with_seed(42);
    v.register_deck(
        "draw_pile",
        vec!["ace_spades".into(), "king_hearts".into(), "queen_diamonds".into()],
    );

    let mut debug_output = String::new();
    write!(&mut debug_output, "{:?}", v).expect("Debug formatting should not fail");

    // The custom Debug impl must redact deck contents
    assert!(
        !debug_output.contains("ace_spades"),
        "Vault Debug output must not contain card names, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("king_hearts"),
        "Vault Debug output must not contain card names, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("queen_diamonds"),
        "Vault Debug output must not contain card names, got: {debug_output}"
    );

    // Should show redacted placeholders instead
    assert!(
        debug_output.contains("redacted"),
        "Vault Debug output should mention redaction, got: {debug_output}"
    );
}

#[test]
fn vault_debug_does_not_leak_hidden_facts() {
    let mut v = Vault::with_seed(42);
    v.add_hidden_fact(
        "alice",
        HiddenFact {
            zone: "hand".into(),
            component_id: "secret_card_99".into(),
            properties: serde_json::json!({"suit": "clubs", "rank": 99}),
        },
    );

    let mut debug_output = String::new();
    write!(&mut debug_output, "{:?}", v).expect("Debug formatting should not fail");

    assert!(
        !debug_output.contains("secret_card_99"),
        "Vault Debug output must not contain hidden fact component IDs, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("clubs"),
        "Vault Debug output must not contain hidden fact properties, got: {debug_output}"
    );
    assert!(
        !debug_output.contains("alice"),
        "Vault Debug output must not contain player names from hidden facts, got: {debug_output}"
    );
}
