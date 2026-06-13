//! Mental poker: serverless cryptographic card shuffling via SRA commutative encryption.
//!
//! Uses a well-known 2048-bit MODP group (RFC 3526 Group 14) for modular exponentiation.
//! Backend can be swapped to WASI-Crypto when it stabilizes.
//!
//! Protocol:
//! 1. Each player generates an SRA keypair (e, d) where e*d ≡ 1 mod (p-1)
//! 2. Cards are encoded as group elements
//! 3. Players take turns encrypting all cards and shuffling
//! 4. To deal: other players send decryption shares, recipient decrypts last
//! 5. At showdown: players reveal keys for full verification

use num_bigint::{BigInt, BigUint};
use num_integer::Integer;
use num_traits::One;
use rand::Rng;
use std::collections::HashMap;

use crate::error::{BaizeError, Result};

/// RFC 3526 Group 14: 2048-bit MODP group.
/// Using a well-known group avoids safe-prime generation entirely.
fn modp_2048_prime() -> BigUint {
    BigUint::from_bytes_be(&hex_to_bytes(
        "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1\
         29024E088A67CC74020BBEA63B139B22514A08798E3404DD\
         EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245\
         E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED\
         EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D\
         C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F\
         83655D23DCA3AD961C62F356208552BB9ED529077096966D\
         670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B\
         E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9\
         DE2BCBF6955817183995497CEA956AE515D2261898FA0510\
         15728E5A8AACAA68FFFFFFFFFFFFFFFF",
    ))
}

fn hex_to_bytes(hex: &str) -> Vec<u8> {
    let clean: String = hex.chars().filter(|c| c.is_ascii_hexdigit()).collect();
    (0..clean.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&clean[i..i + 2], 16).unwrap())
        .collect()
}

/// Generate a random BigUint in [low, high).
///
/// Uses rejection sampling with top-byte masking to avoid bias.
fn gen_biguint_range<R: Rng>(rng: &mut R, low: &BigUint, high: &BigUint) -> BigUint {
    assert!(high > low, "high must be > low");
    let range = high - low;
    let bit_len = range.bits() as usize;
    let byte_len = (bit_len + 7) / 8;
    if byte_len == 0 {
        return low.clone();
    }
    let top_bits = (bit_len % 8) as u8;
    loop {
        let mut bytes = vec![0u8; byte_len];
        rng.fill(&mut bytes[..]);
        // Mask top byte to reduce rejection rate
        if top_bits > 0 {
            bytes[0] &= (1u8 << top_bits) - 1;
        }
        let val = BigUint::from_bytes_be(&bytes);
        if val < range {
            return low + val;
        }
    }
}

// ---------------------------------------------------------------------------
// Layer 1: SRA Commutative Encryption
// ---------------------------------------------------------------------------

/// Maximum key generation attempts before giving up.
const MAX_KEYGEN_ATTEMPTS: usize = 1000;

/// An SRA keypair: encrypt with e, decrypt with d. e*d ≡ 1 mod (p-1).
#[derive(Debug, Clone)]
pub struct SraKeypair {
    pub encrypt_key: BigUint,
    pub decrypt_key: BigUint,
}

/// Generate an SRA keypair for the given prime p.
///
/// Picks a random e coprime to (p-1), computes d = e^(-1) mod (p-1).
pub fn generate_keypair<R: Rng>(rng: &mut R, p: &BigUint) -> Result<SraKeypair> {
    let p_minus_1 = p - BigUint::one();
    // p_minus_1 must be > 2 for meaningful encryption
    assert!(p_minus_1 > BigUint::from(2u32), "prime too small");

    let low = BigUint::from(2u32);

    for _ in 0..MAX_KEYGEN_ATTEMPTS {
        // Random e in [2, p-2]
        let e = gen_biguint_range(rng, &low, &p_minus_1);

        // e must be coprime to p-1
        if e.gcd(&p_minus_1) != BigUint::one() {
            continue;
        }

        // d = e^(-1) mod (p-1) using extended GCD
        let d = mod_inverse(&e, &p_minus_1)
            .ok_or_else(|| BaizeError::IllegalAction("modular inverse failed".into()))?;

        // Verify: e * d ≡ 1 mod (p-1)
        debug_assert!(
            (&e * &d) % &p_minus_1 == BigUint::one(),
            "keypair verification failed: e*d mod (p-1) != 1"
        );

        return Ok(SraKeypair {
            encrypt_key: e,
            decrypt_key: d,
        });
    }

    Err(BaizeError::IllegalAction(format!(
        "failed to generate SRA keypair after {MAX_KEYGEN_ATTEMPTS} attempts"
    )))
}

/// Encrypt: c = m^e mod p
pub fn sra_encrypt(message: &BigUint, key: &BigUint, p: &BigUint) -> BigUint {
    message.modpow(key, p)
}

/// Decrypt: m = c^d mod p
pub fn sra_decrypt(ciphertext: &BigUint, key: &BigUint, p: &BigUint) -> BigUint {
    ciphertext.modpow(key, p)
}

/// Modular multiplicative inverse using extended Euclidean algorithm.
fn mod_inverse(a: &BigUint, m: &BigUint) -> Option<BigUint> {
    let a_signed = BigInt::from(a.clone());
    let m_signed = BigInt::from(m.clone());

    let gcd_result = a_signed.extended_gcd(&m_signed);

    if gcd_result.gcd != BigInt::one() {
        return None; // not coprime
    }

    // Normalize to positive
    let inv = ((gcd_result.x % &m_signed) + &m_signed) % &m_signed;
    Some(inv.to_biguint().expect("modular inverse should be non-negative"))
}

// ---------------------------------------------------------------------------
// Layer 2: Card Encoding
// ---------------------------------------------------------------------------

/// Maximum supported deck size.
const MAX_DECK_SIZE: usize = 256;

/// Encode card indices as group elements.
///
/// Uses sequential assignment: card i -> (i + 2) as a BigUint.
/// Values 0 and 1 are reserved (0 = identity, 1 = trivial).
/// This is deterministic and reversible.
pub fn encode_card(card_index: usize) -> Result<BigUint> {
    if card_index >= MAX_DECK_SIZE {
        return Err(BaizeError::IllegalAction(format!(
            "card index {card_index} exceeds max deck size {MAX_DECK_SIZE}"
        )));
    }
    Ok(BigUint::from(card_index + 2))
}

/// Decode a group element back to a card index.
pub fn decode_card(element: &BigUint) -> Result<usize> {
    // to_u64_digits returns little-endian u64 limbs; empty vec means zero.
    let digits = element.to_u64_digits();
    if digits.len() > 1 {
        return Err(BaizeError::IllegalAction(
            "card element too large to decode".into(),
        ));
    }
    let val = digits.first().copied().unwrap_or(0) as usize;

    if val < 2 {
        return Err(BaizeError::IllegalAction(
            "invalid card encoding: value < 2".into(),
        ));
    }
    let index = val - 2;
    if index >= MAX_DECK_SIZE {
        return Err(BaizeError::IllegalAction(format!(
            "decoded card index {index} exceeds max deck size {MAX_DECK_SIZE}"
        )));
    }
    Ok(index)
}

/// Build a plaintext deck of encoded cards for a given deck size.
pub fn build_deck(deck_size: usize) -> Result<Vec<BigUint>> {
    if deck_size == 0 {
        return Err(BaizeError::IllegalAction("deck size must be > 0".into()));
    }
    if deck_size > MAX_DECK_SIZE {
        return Err(BaizeError::IllegalAction(format!(
            "deck size {deck_size} exceeds max {MAX_DECK_SIZE}"
        )));
    }
    (0..deck_size).map(encode_card).collect()
}

// ---------------------------------------------------------------------------
// Layer 3: Shuffle Protocol
// ---------------------------------------------------------------------------

/// A player's contribution to the shuffle: encrypted + shuffled deck.
#[derive(Debug, Clone)]
pub struct ShuffleStep {
    /// Player who performed this step.
    pub player: String,
    /// The deck after this player encrypted and shuffled.
    pub deck: Vec<BigUint>,
    /// BLAKE3 hash of the deck before this step (chain integrity).
    pub prev_hash: String,
    /// BLAKE3 hash of the deck after this step.
    pub step_hash: String,
}

/// Hash a deck for chain integrity.
fn hash_deck(deck: &[BigUint]) -> String {
    let mut hasher = blake3::Hasher::new();
    for card in deck {
        hasher.update(&card.to_bytes_be());
        hasher.update(b"|"); // separator
    }
    hasher.finalize().to_hex().to_string()
}

/// Encrypt all cards in a deck with the given key and shuffle.
pub fn encrypt_and_shuffle<R: Rng>(
    rng: &mut R,
    deck: &[BigUint],
    encrypt_key: &BigUint,
    p: &BigUint,
    player: &str,
) -> Result<ShuffleStep> {
    if deck.is_empty() {
        return Err(BaizeError::IllegalAction("cannot shuffle empty deck".into()));
    }
    if deck.len() > MAX_DECK_SIZE {
        return Err(BaizeError::IllegalAction(format!(
            "deck too large: {} > {MAX_DECK_SIZE}",
            deck.len()
        )));
    }

    let prev_hash = hash_deck(deck);

    // Encrypt each card
    let mut encrypted: Vec<BigUint> = deck
        .iter()
        .map(|card| sra_encrypt(card, encrypt_key, p))
        .collect();

    // Fisher-Yates shuffle
    for i in (1..encrypted.len()).rev() {
        let j = rng.random_range(0..=i);
        encrypted.swap(i, j);
    }

    let step_hash = hash_deck(&encrypted);

    Ok(ShuffleStep {
        player: player.to_string(),
        deck: encrypted,
        prev_hash,
        step_hash,
    })
}

/// Full N-player shuffle protocol.
///
/// Each player encrypts and shuffles in sequence.
/// Returns the final encrypted deck and the shuffle history.
pub fn full_shuffle<R: Rng>(
    rng: &mut R,
    deck_size: usize,
    players: &[(&str, &SraKeypair)],
    p: &BigUint,
) -> Result<(Vec<BigUint>, Vec<ShuffleStep>)> {
    if players.is_empty() {
        return Err(BaizeError::IllegalAction("no players for shuffle".into()));
    }

    let mut current_deck = build_deck(deck_size)?;
    let mut history = Vec::new();

    for (player_name, keypair) in players {
        let step = encrypt_and_shuffle(
            rng,
            &current_deck,
            &keypair.encrypt_key,
            p,
            player_name,
        )?;
        current_deck = step.deck.clone();
        history.push(step);
    }

    Ok((current_deck, history))
}

// ---------------------------------------------------------------------------
// Layer 4: Deal and Reveal
// ---------------------------------------------------------------------------

/// Deal a card using decrypt keys directly.
///
/// Applies each key's decryption in sequence, then the recipient's.
/// Order doesn't matter (SRA commutativity) but we apply in given order.
pub fn deal_card_with_keys(
    encrypted_card: &BigUint,
    other_decrypt_keys: &[&BigUint],
    recipient_decrypt_key: &BigUint,
    p: &BigUint,
) -> BigUint {
    let mut current = encrypted_card.clone();
    for key in other_decrypt_keys {
        current = sra_decrypt(&current, key, p);
    }
    sra_decrypt(&current, recipient_decrypt_key, p)
}

/// Verify the entire shuffle-deal sequence after showdown.
///
/// Given all players' keypairs and the shuffle history, re-derive every card
/// and verify consistency.
pub fn verify_game(
    deck_size: usize,
    players: &[(&str, &SraKeypair)],
    shuffle_history: &[ShuffleStep],
    dealt_cards: &HashMap<usize, (String, BigUint)>, // card_index -> (recipient, plaintext)
    p: &BigUint,
) -> Result<bool> {
    // Rebuild the deck
    let original_deck = build_deck(deck_size)?;

    // Verify shuffle chain hashes
    let mut current_deck = original_deck;
    for (step_idx, step) in shuffle_history.iter().enumerate() {
        let expected_prev_hash = hash_deck(&current_deck);
        if step.prev_hash != expected_prev_hash {
            return Err(BaizeError::IllegalAction(format!(
                "shuffle step {step_idx} ({}) prev_hash mismatch: expected {expected_prev_hash}, got {}",
                step.player, step.prev_hash
            )));
        }
        // We can't verify the shuffle order without the RNG seed,
        // but we can verify the hashes chain correctly.
        current_deck = step.deck.clone();
    }

    // Verify each dealt card: decrypt with all keys, should match plaintext
    let final_deck = &shuffle_history
        .last()
        .map(|s| &s.deck)
        .unwrap_or(&current_deck);

    for (card_idx, (_recipient, expected_plaintext)) in dealt_cards {
        if *card_idx >= final_deck.len() {
            return Err(BaizeError::IllegalAction(format!(
                "dealt card index {card_idx} out of range (deck size {})",
                final_deck.len()
            )));
        }

        let encrypted = &final_deck[*card_idx];
        let all_keys: Vec<&BigUint> = players.iter().map(|(_, kp)| &kp.decrypt_key).collect();

        let mut decrypted = encrypted.clone();
        for key in &all_keys {
            decrypted = sra_decrypt(&decrypted, key, p);
        }

        if &decrypted != expected_plaintext {
            return Err(BaizeError::IllegalAction(format!(
                "card {card_idx} verification failed: decrypted to {decrypted}, expected {expected_plaintext}"
            )));
        }
    }

    Ok(true)
}

// ---------------------------------------------------------------------------
// Convenience: MentalPokerSession
// ---------------------------------------------------------------------------

/// Maximum players for a mental poker session.
const MAX_PLAYERS: usize = 10;

/// A mental poker session managing the full protocol lifecycle.
#[derive(Debug, Clone)]
pub struct MentalPokerSession {
    /// The prime modulus (RFC 3526 Group 14).
    pub prime: BigUint,
    /// Number of cards in the deck.
    pub deck_size: usize,
    /// Player names in order.
    pub player_names: Vec<String>,
    /// Current state of the deck (encrypted).
    pub deck: Vec<BigUint>,
    /// Shuffle history for verification.
    pub shuffle_history: Vec<ShuffleStep>,
    /// Cards that have been dealt: deck_index -> (recipient, plaintext_card_index).
    pub dealt_cards: HashMap<usize, (String, usize)>,
    /// Protocol phase.
    pub phase: MentalPokerPhase,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MentalPokerPhase {
    /// Waiting for players to join and generate keys.
    Setup,
    /// Players are encrypting and shuffling in sequence.
    Shuffling { next_player_index: usize },
    /// Deck is shuffled; cards can be dealt.
    Ready,
    /// Game is over; keys revealed for verification.
    Revealed,
}

impl MentalPokerSession {
    /// Create a new session.
    pub fn new(deck_size: usize, player_names: Vec<String>) -> Result<Self> {
        if deck_size == 0 || deck_size > MAX_DECK_SIZE {
            return Err(BaizeError::IllegalAction(format!(
                "deck size must be 1..={MAX_DECK_SIZE}, got {deck_size}"
            )));
        }
        if player_names.is_empty() || player_names.len() > MAX_PLAYERS {
            return Err(BaizeError::IllegalAction(format!(
                "player count must be 1..={MAX_PLAYERS}, got {}",
                player_names.len()
            )));
        }

        let deck = build_deck(deck_size)?;

        Ok(Self {
            prime: modp_2048_prime(),
            deck_size,
            player_names,
            deck,
            shuffle_history: Vec::new(),
            dealt_cards: HashMap::new(),
            phase: MentalPokerPhase::Setup,
        })
    }

    /// Apply a player's shuffle step.
    pub fn apply_shuffle_step(&mut self, step: ShuffleStep) -> Result<()> {
        match &self.phase {
            MentalPokerPhase::Setup => {
                self.phase = MentalPokerPhase::Shuffling {
                    next_player_index: 0,
                };
                self.apply_shuffle_step(step)
            }
            MentalPokerPhase::Shuffling { next_player_index } => {
                let expected_player = &self.player_names[*next_player_index];
                if step.player != *expected_player {
                    return Err(BaizeError::IllegalAction(format!(
                        "expected shuffle from {expected_player}, got {}",
                        step.player
                    )));
                }

                // Verify prev_hash chains
                let current_hash = hash_deck(&self.deck);
                if step.prev_hash != current_hash {
                    return Err(BaizeError::IllegalAction(format!(
                        "shuffle step prev_hash mismatch for {}: expected {current_hash}, got {}",
                        step.player, step.prev_hash
                    )));
                }

                // Verify deck size unchanged
                if step.deck.len() != self.deck_size {
                    return Err(BaizeError::IllegalAction(format!(
                        "shuffle step changed deck size: {} -> {}",
                        self.deck_size,
                        step.deck.len()
                    )));
                }

                self.deck = step.deck.clone();
                self.shuffle_history.push(step);

                let next = next_player_index + 1;
                if next >= self.player_names.len() {
                    self.phase = MentalPokerPhase::Ready;
                } else {
                    self.phase = MentalPokerPhase::Shuffling {
                        next_player_index: next,
                    };
                }

                Ok(())
            }
            other => Err(BaizeError::IllegalAction(format!(
                "cannot shuffle in phase {other:?}"
            ))),
        }
    }

    /// Record a dealt card.
    pub fn record_deal(
        &mut self,
        deck_index: usize,
        recipient: &str,
        plaintext_card_index: usize,
    ) -> Result<()> {
        if self.phase != MentalPokerPhase::Ready {
            return Err(BaizeError::IllegalAction(
                "can only deal in Ready phase".into(),
            ));
        }
        if deck_index >= self.deck_size {
            return Err(BaizeError::IllegalAction(format!(
                "deck index {deck_index} out of range (deck size {})",
                self.deck_size
            )));
        }
        if self.dealt_cards.contains_key(&deck_index) {
            return Err(BaizeError::IllegalAction(format!(
                "card at deck position {deck_index} already dealt"
            )));
        }
        if !self.player_names.contains(&recipient.to_string()) {
            return Err(BaizeError::IllegalAction(format!(
                "unknown recipient: {recipient}"
            )));
        }

        self.dealt_cards
            .insert(deck_index, (recipient.to_string(), plaintext_card_index));
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::StdRng;
    use rand::SeedableRng;

    fn test_rng() -> StdRng {
        StdRng::seed_from_u64(42)
    }

    #[test]
    fn test_keypair_generation() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp = generate_keypair(&mut rng, &p).unwrap();
        let p_minus_1 = &p - BigUint::one();
        assert_eq!(
            (&kp.encrypt_key * &kp.decrypt_key) % &p_minus_1,
            BigUint::one()
        );
    }

    #[test]
    fn test_encrypt_decrypt_roundtrip() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp = generate_keypair(&mut rng, &p).unwrap();
        let message = BigUint::from(42u32);
        let encrypted = sra_encrypt(&message, &kp.encrypt_key, &p);
        let decrypted = sra_decrypt(&encrypted, &kp.decrypt_key, &p);
        assert_eq!(decrypted, message);
    }

    #[test]
    fn test_commutativity() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();
        let message = BigUint::from(99u32);

        // E_a(E_b(m)) should equal E_b(E_a(m))
        let ab = sra_encrypt(
            &sra_encrypt(&message, &kp_a.encrypt_key, &p),
            &kp_b.encrypt_key,
            &p,
        );
        let ba = sra_encrypt(
            &sra_encrypt(&message, &kp_b.encrypt_key, &p),
            &kp_a.encrypt_key,
            &p,
        );
        assert_eq!(ab, ba);

        // Decrypt in either order should recover m
        let dec_ab = sra_decrypt(
            &sra_decrypt(&ab, &kp_a.decrypt_key, &p),
            &kp_b.decrypt_key,
            &p,
        );
        let dec_ba = sra_decrypt(
            &sra_decrypt(&ab, &kp_b.decrypt_key, &p),
            &kp_a.decrypt_key,
            &p,
        );
        assert_eq!(dec_ab, message);
        assert_eq!(dec_ba, message);
    }

    #[test]
    fn test_card_encoding_roundtrip() {
        for i in 0..52 {
            let encoded = encode_card(i).unwrap();
            let decoded = decode_card(&encoded).unwrap();
            assert_eq!(decoded, i);
        }
    }

    #[test]
    fn test_card_encoding_bounds() {
        assert!(encode_card(MAX_DECK_SIZE).is_err());
        assert!(encode_card(0).is_ok());
        assert!(encode_card(255).is_ok());
    }

    #[test]
    fn test_build_deck() {
        let deck = build_deck(52).unwrap();
        assert_eq!(deck.len(), 52);
        assert!(build_deck(0).is_err());
        assert!(build_deck(MAX_DECK_SIZE + 1).is_err());
    }

    #[test]
    fn test_full_shuffle_2_players() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();

        let players = vec![("Alice", &kp_a), ("Bob", &kp_b)];
        let (final_deck, history) = full_shuffle(&mut rng, 5, &players, &p).unwrap();

        assert_eq!(final_deck.len(), 5);
        assert_eq!(history.len(), 2);
        assert_eq!(history[0].player, "Alice");
        assert_eq!(history[1].player, "Bob");

        // Verify hash chain
        assert_eq!(history[1].prev_hash, history[0].step_hash);
    }

    #[test]
    fn test_deal_card_with_keys() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();

        let message = encode_card(7).unwrap();

        // Encrypt with both keys
        let encrypted = sra_encrypt(
            &sra_encrypt(&message, &kp_a.encrypt_key, &p),
            &kp_b.encrypt_key,
            &p,
        );

        // Deal to player A: B decrypts first, then A
        let plaintext = deal_card_with_keys(
            &encrypted,
            &[&kp_b.decrypt_key],
            &kp_a.decrypt_key,
            &p,
        );

        assert_eq!(decode_card(&plaintext).unwrap(), 7);
    }

    #[test]
    fn test_full_shuffle_deal_verify() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();

        let players = vec![("Alice", &kp_a), ("Bob", &kp_b)];
        let (final_deck, history) = full_shuffle(&mut rng, 5, &players, &p).unwrap();

        // Deal card 0 to Alice: Bob decrypts, then Alice
        let card_0_plaintext = deal_card_with_keys(
            &final_deck[0],
            &[&kp_b.decrypt_key],
            &kp_a.decrypt_key,
            &p,
        );
        let card_0_index = decode_card(&card_0_plaintext).unwrap();
        assert!(card_0_index < 5);

        // Deal card 1 to Bob: Alice decrypts, then Bob
        let card_1_plaintext = deal_card_with_keys(
            &final_deck[1],
            &[&kp_a.decrypt_key],
            &kp_b.decrypt_key,
            &p,
        );
        let card_1_index = decode_card(&card_1_plaintext).unwrap();
        assert!(card_1_index < 5);

        // Verify the game
        let mut dealt = HashMap::new();
        dealt.insert(0, ("Alice".to_string(), card_0_plaintext));
        dealt.insert(1, ("Bob".to_string(), card_1_plaintext));

        let verify_result = verify_game(5, &players, &history, &dealt, &p);
        assert!(verify_result.is_ok());
        assert!(verify_result.unwrap());
    }

    #[test]
    fn test_session_lifecycle() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();

        let mut session =
            MentalPokerSession::new(5, vec!["Alice".into(), "Bob".into()]).unwrap();

        assert_eq!(session.phase, MentalPokerPhase::Setup);

        // Alice shuffles
        let step_a = encrypt_and_shuffle(
            &mut rng,
            &session.deck,
            &kp_a.encrypt_key,
            &session.prime,
            "Alice",
        )
        .unwrap();
        session.apply_shuffle_step(step_a).unwrap();

        assert!(matches!(
            session.phase,
            MentalPokerPhase::Shuffling {
                next_player_index: 1
            }
        ));

        // Bob shuffles
        let step_b = encrypt_and_shuffle(
            &mut rng,
            &session.deck,
            &kp_b.encrypt_key,
            &session.prime,
            "Bob",
        )
        .unwrap();
        session.apply_shuffle_step(step_b).unwrap();

        assert_eq!(session.phase, MentalPokerPhase::Ready);

        // Record deals
        session.record_deal(0, "Alice", 3).unwrap();
        session.record_deal(1, "Bob", 1).unwrap();

        // Double-deal rejected
        assert!(session.record_deal(0, "Bob", 2).is_err());

        // Unknown player rejected
        assert!(session.record_deal(2, "Charlie", 0).is_err());
    }

    #[test]
    fn test_3_player_commutativity() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();
        let kp_c = generate_keypair(&mut rng, &p).unwrap();

        let message = encode_card(0).unwrap();

        // Triple encrypt
        let encrypted = sra_encrypt(
            &sra_encrypt(
                &sra_encrypt(&message, &kp_a.encrypt_key, &p),
                &kp_b.encrypt_key,
                &p,
            ),
            &kp_c.encrypt_key,
            &p,
        );

        // Decrypt in all 6 possible orders - all should give same result
        let orders: Vec<Vec<&BigUint>> = vec![
            vec![&kp_a.decrypt_key, &kp_b.decrypt_key, &kp_c.decrypt_key],
            vec![&kp_a.decrypt_key, &kp_c.decrypt_key, &kp_b.decrypt_key],
            vec![&kp_b.decrypt_key, &kp_a.decrypt_key, &kp_c.decrypt_key],
            vec![&kp_b.decrypt_key, &kp_c.decrypt_key, &kp_a.decrypt_key],
            vec![&kp_c.decrypt_key, &kp_a.decrypt_key, &kp_b.decrypt_key],
            vec![&kp_c.decrypt_key, &kp_b.decrypt_key, &kp_a.decrypt_key],
        ];

        for (idx, order) in orders.iter().enumerate() {
            let mut val = encrypted.clone();
            for key in order {
                val = sra_decrypt(&val, key, &p);
            }
            assert_eq!(val, message, "commutativity failed for order {idx}");
        }
    }

    #[test]
    fn test_tampered_card_detected() {
        let p = modp_2048_prime();
        let mut rng = test_rng();
        let kp_a = generate_keypair(&mut rng, &p).unwrap();
        let kp_b = generate_keypair(&mut rng, &p).unwrap();

        let players = vec![("Alice", &kp_a), ("Bob", &kp_b)];
        let (_final_deck, history) = full_shuffle(&mut rng, 5, &players, &p).unwrap();

        // Tamper: claim card 0 decrypted to a different value
        let mut dealt = HashMap::new();
        let fake_plaintext = encode_card(99).unwrap(); // wrong card
        dealt.insert(0, ("Alice".to_string(), fake_plaintext));

        let result = verify_game(5, &players, &history, &dealt, &p);
        assert!(result.is_err() || !result.unwrap());
    }
}
