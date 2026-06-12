use std::collections::HashMap;
use std::fmt;

use rand::Rng;
use rand::SeedableRng;
use rand_chacha::ChaCha20Rng;

/// Hidden state vault.
///
/// Stores server-only state that clients must not see:
/// - Deck orders (shuffled sequences of component IDs)
/// - Hidden zone contents
/// - Per-player filtered state views
///
/// Uses ChaCha20 for cryptographically fair randomness.
///
/// **Security**: Debug output is redacted to prevent secret leakage
/// through panic backtraces or log messages.
pub struct Vault {
    rng: ChaCha20Rng,
    /// Hidden deck orders, keyed by zone name.
    /// Each entry is an ordered list of component IDs (top of deck = last element).
    decks: HashMap<String, Vec<String>>,
    /// Per-player hidden facts that have not yet been revealed.
    hidden_facts: HashMap<String, Vec<HiddenFact>>,
}

impl fmt::Debug for Vault {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Vault")
            .field("decks", &format_args!("<{} zones redacted>", self.decks.len()))
            .field(
                "hidden_facts",
                &format_args!("<{} players redacted>", self.hidden_facts.len()),
            )
            .field("rng", &"<redacted>")
            .finish()
    }
}

/// A fact stored in the vault that is hidden from one or more players.
#[derive(Debug, Clone)]
pub struct HiddenFact {
    pub zone: String,
    pub component_id: String,
    pub properties: serde_json::Value,
}

impl Default for Vault {
    fn default() -> Self {
        Self::new()
    }
}

impl Vault {
    pub fn new() -> Self {
        Self {
            rng: ChaCha20Rng::from_os_rng(),
            decks: HashMap::new(),
            hidden_facts: HashMap::new(),
        }
    }

    /// Seed the RNG with a specific value (for reproducible tests).
    pub fn with_seed(seed: u64) -> Self {
        Self {
            rng: ChaCha20Rng::seed_from_u64(seed),
            decks: HashMap::new(),
            hidden_facts: HashMap::new(),
        }
    }

    /// Register a deck's initial contents (component IDs).
    ///
    /// Preconditions:
    /// - zone name must not be empty
    /// - component IDs must not contain empty strings
    pub fn register_deck(&mut self, zone: &str, component_ids: Vec<String>) {
        debug_assert!(!zone.is_empty(), "vault: deck zone name must not be empty");
        debug_assert!(
            component_ids.iter().all(|id| !id.is_empty()),
            "vault: register_deck component_ids must not contain empty strings"
        );
        self.decks.insert(zone.to_string(), component_ids);
    }

    /// Returns true if a deck with the given zone name exists.
    pub fn deck_exists(&self, zone: &str) -> bool {
        self.decks.contains_key(zone)
    }

    /// Returns the number of cards remaining in the given deck, or 0 if the deck
    /// does not exist.
    pub fn deck_size(&self, zone: &str) -> usize {
        self.decks.get(zone).map_or(0, |d| d.len())
    }

    /// Store a hidden fact.
    ///
    /// Precondition: player name must not be empty.
    pub fn add_hidden_fact(&mut self, player: &str, fact: HiddenFact) {
        debug_assert!(!player.is_empty(), "vault: add_hidden_fact player must not be empty");
        self.hidden_facts
            .entry(player.to_string())
            .or_default()
            .push(fact);
    }

    /// Retrieve and clear hidden facts for a player (on revelation).
    pub fn take_hidden_facts(&mut self, player: &str) -> Vec<HiddenFact> {
        self.hidden_facts.remove(player).unwrap_or_default()
    }
}

/// Roll N dice with the given number of faces. Returns a vec of results.
///
/// Preconditions:
/// - `faces` must be >= 1 (a zero-faced die is nonsensical and panics in random_range)
/// - `count` must be >= 1 (rolling zero dice is a no-op; caller should not request it)
///
/// Postcondition: every result is in [1, faces].
pub fn roll_dice(vault: &mut Vault, count: u32, faces: u32) -> Vec<u32> {
    assert!(faces >= 1, "vault: dice faces must be >= 1, got {faces}");
    assert!(count >= 1, "vault: dice count must be >= 1, got {count}");

    let results: Vec<u32> = (0..count)
        .map(|_| vault.rng.random_range(1..=faces))
        .collect();

    debug_assert!(
        results.iter().all(|&r| r >= 1 && r <= faces),
        "vault: postcondition failed — roll result out of [1, {faces}]"
    );
    debug_assert_eq!(
        results.len(),
        count as usize,
        "vault: postcondition failed — expected {count} results, got {}",
        results.len()
    );

    results
}

/// Draw N cards from the top of a named deck zone.
///
/// Returns `Ok(drawn_cards)` on success. If the deck has fewer than `count`
/// cards, draws as many as available.
///
/// Returns `Err` if the deck zone does not exist (caller should check first).
///
/// Postcondition: deck size decreases by exactly the number of cards returned.
pub fn draw_cards(vault: &mut Vault, zone: &str, count: u32) -> Result<Vec<String>, String> {
    let deck = match vault.decks.get_mut(zone) {
        Some(d) => d,
        None => return Err(format!("vault: deck zone '{zone}' does not exist")),
    };

    let size_before = deck.len();
    let n = (count as usize).min(deck.len());
    let start = deck.len() - n;
    let drawn = deck.split_off(start);

    debug_assert_eq!(
        deck.len(),
        size_before - drawn.len(),
        "vault: postcondition failed — deck size mismatch after draw"
    );

    Ok(drawn)
}

/// Shuffle a deck zone in place using the vault's RNG.
///
/// Returns `Err` if the deck zone does not exist (caller should check first).
///
/// Postcondition: deck size is unchanged after shuffle (permutation, not lossy).
pub fn shuffle_zone(vault: &mut Vault, zone: &str) -> Result<(), String> {
    let deck = match vault.decks.get_mut(zone) {
        Some(d) => d,
        None => return Err(format!("vault: deck zone '{zone}' does not exist")),
    };

    let size_before = deck.len();
    shuffle(deck, &mut vault.rng);

    debug_assert_eq!(
        deck.len(),
        size_before,
        "vault: postcondition failed — deck size changed after shuffle"
    );

    Ok(())
}

/// Fisher-Yates shuffle.
fn shuffle<T>(slice: &mut [T], rng: &mut ChaCha20Rng) {
    let len = slice.len();
    for i in (1..len).rev() {
        let j = rng.random_range(0..=i);
        slice.swap(i, j);
    }
}
