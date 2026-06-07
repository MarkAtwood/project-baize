use std::collections::HashMap;

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
pub struct Vault {
    rng: ChaCha20Rng,
    /// Hidden deck orders, keyed by zone name.
    /// Each entry is an ordered list of component IDs (top of deck = last element).
    decks: HashMap<String, Vec<String>>,
    /// Per-player hidden facts that have not yet been revealed.
    hidden_facts: HashMap<String, Vec<HiddenFact>>,
}

/// A fact stored in the vault that is hidden from one or more players.
#[derive(Debug, Clone)]
pub struct HiddenFact {
    pub zone: String,
    pub component_id: String,
    pub properties: serde_json::Value,
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
    pub fn register_deck(&mut self, zone: &str, component_ids: Vec<String>) {
        self.decks.insert(zone.to_string(), component_ids);
    }

    /// Store a hidden fact.
    pub fn add_hidden_fact(&mut self, player: &str, fact: HiddenFact) {
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
pub fn roll_dice(vault: &mut Vault, count: u32, faces: u32) -> Vec<u32> {
    (0..count)
        .map(|_| vault.rng.random_range(1..=faces))
        .collect()
}

/// Draw N cards from the top of a named deck zone.
/// Returns the drawn component IDs. If the deck has fewer than N cards,
/// returns as many as available.
pub fn draw_cards(vault: &mut Vault, zone: &str, count: u32) -> Vec<String> {
    let deck = match vault.decks.get_mut(zone) {
        Some(d) => d,
        None => return Vec::new(),
    };

    let n = (count as usize).min(deck.len());
    let start = deck.len() - n;
    deck.split_off(start)
}

/// Shuffle a deck zone in place using the vault's RNG.
pub fn shuffle_zone(vault: &mut Vault, zone: &str) {
    if let Some(deck) = vault.decks.get_mut(zone) {
        shuffle(deck, &mut vault.rng);
    }
}

/// Fisher-Yates shuffle.
fn shuffle<T>(slice: &mut [T], rng: &mut ChaCha20Rng) {
    let len = slice.len();
    for i in (1..len).rev() {
        let j = rng.random_range(0..=i);
        slice.swap(i, j);
    }
}
