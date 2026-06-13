use indexmap::IndexMap;

use crate::action::{Action, ActionType, Position};
use crate::definition::{TriggerDef, Visibility, VisibilityTier};
use crate::end_conditions::check_end_conditions;
use crate::error::{BaizeError, Result};
use crate::runtime::{
    ClaimWindow, ComponentData, ComponentId, GameSession, RuntimeZone, MAX_EVENTS_PER_GAME,
    MAX_STATE_SIZE_BYTES, STATE_SIZE_CHECK_INTERVAL,
};
use crate::state::GameStatus;

/// An event emitted by a state transition, for JSONL event logging.
#[derive(Debug, Clone, serde::Serialize)]
pub struct GameEvent {
    pub sequence: u64,
    pub event_type: EventType,
    pub player: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub component_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub captured: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    pub state_hash: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prev_hash: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    MovePiece,
    Place,
    Capture,
    Draw,
    PlayCard,
    Discard,
    Flip,
    Promote,
    Swap,
    Remove,
    Pass,
    Resign,
    Fire,
    Hit,
    Miss,
    Sunk,
    Commit,
    Reveal,
    ActionSubmitted,
    TurnAdvance,
    GameEnd,
    VisibilityChange,
    TriggerActivated,
    ClaimSubmitted,
    ClaimResolved,
    /// Shuffle step completed by a player.
    ShuffleComplete,
    /// A card has been dealt (decryption shares collected).
    CardDealt,
    /// Player revealed their encryption key for verification.
    KeyRevealed,
    /// Mental poker verification completed (pass or fail).
    VerificationComplete,
}

/// Return the current Phase definition, or None if no phases are defined.
fn current_phase(session: &GameSession) -> Option<&crate::definition::Phase> {
    session
        .definition
        .phases
        .get(session.runtime.phase_index)
}

/// Apply an action to the game session, mutating state and returning events.
///
/// For non-simultaneous phases this works exactly as before. For simultaneous
/// phases it buffers the action under the current player; use
/// [`apply_action_for_player`] when the caller knows the acting player's
/// identity (e.g. the server knows which WebSocket submitted the move).
pub fn apply_action(session: &mut GameSession, action: &Action) -> Result<Vec<GameEvent>> {
    apply_action_for_player(session, action, None)
}

/// Apply an action with an explicit acting player.
///
/// When `acting_player` is `Some`, that player is used instead of the
/// current-turn player. This is required for simultaneous phases where
/// multiple players submit moves independently.
pub fn apply_action_for_player(
    session: &mut GameSession,
    action: &Action,
    acting_player: Option<&str>,
) -> Result<Vec<GameEvent>> {
    if session.runtime.status == GameStatus::Finished {
        return Err(BaizeError::IllegalAction("game is finished".into()));
    }

    // If a claim window is active, only claims are accepted
    if session.runtime.claim_window.is_some() {
        return Err(BaizeError::IllegalAction(
            "claim window is active — use apply_claim instead".into(),
        ));
    }

    if session.runtime.status == GameStatus::Setup {
        session.runtime.status = GameStatus::InProgress;
    }

    // Check if we're in a simultaneous phase
    let is_simultaneous = current_phase(session)
        .and_then(|p| p.simultaneous)
        .unwrap_or(false);

    if is_simultaneous {
        return apply_simultaneous(session, action, acting_player);
    }

    let player = acting_player
        .map(String::from)
        .or_else(|| session.current_player().map(String::from))
        .ok_or_else(|| BaizeError::IllegalAction("no current player".into()))?;

    debug_assert!(
        session.runtime.players.contains_key(&player),
        "current player {:?} not in players map",
        player
    );

    let prev_hash = session.runtime.history_hashes.last().cloned();
    let events = execute_action(session, &player, action, &prev_hash)?;
    finalize_turn(session, events, prev_hash, Some(action))
}

/// Buffer an action for a simultaneous phase; resolve when all players submit.
fn apply_simultaneous(
    session: &mut GameSession,
    action: &Action,
    acting_player: Option<&str>,
) -> Result<Vec<GameEvent>> {
    let player = acting_player
        .map(String::from)
        .or_else(|| session.current_player().map(String::from))
        .ok_or_else(|| {
            BaizeError::IllegalAction("no player specified for simultaneous action".into())
        })?;

    if !session.runtime.players.contains_key(&player) {
        return Err(BaizeError::IllegalAction(format!(
            "unknown player: {player}"
        )));
    }
    if session.runtime.simultaneous_actions.contains_key(&player) {
        return Err(BaizeError::IllegalAction(format!(
            "player {player} has already submitted for this phase"
        )));
    }

    let prev_hash = session.runtime.history_hashes.last().cloned();

    // Buffer the action as a JSON value
    let action_value = serde_json::to_value(action)
        .map_err(|e| BaizeError::IllegalAction(format!("failed to serialize action: {e}")))?;
    session
        .runtime
        .simultaneous_actions
        .insert(player.clone(), action_value);

    let mut events = vec![make_event(
        session.runtime.sequence,
        EventType::ActionSubmitted,
        &player,
        None,
        None,
        None,
        "",
        &prev_hash,
    )];

    // Check if all players have submitted
    let all_players: Vec<String> = session.runtime.players.keys().cloned().collect();
    let all_submitted = all_players
        .iter()
        .all(|p| session.runtime.simultaneous_actions.contains_key(p));

    if all_submitted {
        // Drain the buffer (take ownership before mutating session)
        let buffered: IndexMap<String, serde_json::Value> =
            std::mem::take(&mut session.runtime.simultaneous_actions);

        // Resolve: apply each action in player-definition order
        for p in &all_players {
            let act_value = buffered
                .get(p)
                .expect("all_submitted guarantees presence");
            let act: Action = serde_json::from_value(act_value.clone()).map_err(|e| {
                BaizeError::IllegalAction(format!(
                    "failed to deserialize buffered action for {p}: {e}"
                ))
            })?;
            let resolve_events = execute_action(session, p, &act, &prev_hash)?;
            events.extend(resolve_events);
        }

        // Check end conditions after all actions resolved
        events = finalize_turn(session, events, prev_hash, None)?;
    }

    Ok(events)
}

/// Execute action mechanics: mutate state and return events.
///
/// Does NOT advance turn or check end conditions — the caller handles that.
fn execute_action(
    session: &mut GameSession,
    player: &str,
    action: &Action,
    prev_hash: &Option<String>,
) -> Result<Vec<GameEvent>> {
    let mut events = Vec::new();

    match action.action_type {
        ActionType::MovePiece => {
            let (from_col, from_row) = parse_position(action.from.as_ref())?;
            let (to_col, to_row) = parse_position(action.to.as_ref())?;

            let zone_name = position_zone(action.from.as_ref()).unwrap_or("board".to_string());
            let zone = session
                .runtime
                .zones
                .get_mut(&zone_name)
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;

            let cid = zone
                .grid_get(from_col, from_row)
                .ok_or_else(|| BaizeError::IllegalAction("no piece at source".into()))?;

            let limit = zone.grid_stacking_limit();
            let dest_occupied = zone.grid_get(to_col, to_row).is_some();

            if dest_occupied && limit != 1 {
                // Stacking enabled — push onto destination stack instead of capturing
                // Remove from source (pop reveals piece below if stacked)
                zone.grid_pop(from_col, from_row);
                zone.grid_push(to_col, to_row, cid)?;
            } else {
                // Classic behavior: capture if occupied (stacking_limit == 1)
                if let Some(cap_id) = zone.grid_get(to_col, to_row) {
                    let cap_name = session
                        .runtime
                        .components
                        .get(cap_id)
                        .map(|c| c.string_id.clone())
                        .unwrap_or_default();
                    events.push(make_event(
                        session.runtime.sequence,
                        EventType::Capture,
                        player,
                        Some(&cap_name),
                        None,
                        Some(&format!("{},{}", to_col, to_row)),
                        "",
                        prev_hash,
                    ));
                }
                // Remove from source (pop reveals piece below if stacked)
                zone.grid_pop(from_col, from_row);
                zone.grid_set(to_col, to_row, Some(cid));
            }

            let comp_name = session
                .runtime
                .components
                .get(cid)
                .map(|c| c.string_id.clone())
                .unwrap_or_default();

            events.push(make_event(
                session.runtime.sequence,
                EventType::MovePiece,
                player,
                Some(&comp_name),
                Some(&format!("{},{}", from_col, from_row)),
                Some(&format!("{},{}", to_col, to_row)),
                "",
                prev_hash,
            ));
        }
        ActionType::Place => {
            let (to_col, to_row) = parse_position(action.to.as_ref())?;
            let zone_name = position_zone(action.to.as_ref()).unwrap_or("board".to_string());
            let comp_type = action
                .component_type
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("place requires component_type".into()))?;

            // Create a new component instance
            let instance_id = format!(
                "{}-{}-{}",
                comp_type,
                player,
                session.runtime.components.len()
            );
            let cid = session.runtime.components.insert(ComponentData {
                id: ComponentId(0),
                string_id: instance_id.clone(),
                component_type: comp_type.to_string(),
                owner: Some(player.to_string()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
                span_cells: Vec::new(),
                orientation: None,
            })?;

            // Try player zone first, then shared zones
            let zone = session
                .runtime
                .players
                .get_mut(player)
                .and_then(|p| p.zones.get_mut(&zone_name))
                .or_else(|| session.runtime.zones.get_mut(&zone_name))
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;

            let limit = zone.grid_stacking_limit();
            if zone.grid_get(to_col, to_row).is_some() {
                if limit == 1 {
                    return Err(BaizeError::IllegalAction(format!(
                        "cell ({to_col},{to_row}) is already occupied"
                    )));
                }
                // Stacking enabled — push onto stack
                zone.grid_push(to_col, to_row, cid)?;
            } else {
                zone.grid_set(to_col, to_row, Some(cid));
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Place,
                player,
                Some(&instance_id),
                None,
                Some(&format!("{},{}", to_col, to_row)),
                "",
                prev_hash,
            ));
        }
        ActionType::Pass => {
            events.push(make_event(
                session.runtime.sequence,
                EventType::Pass,
                player,
                None,
                None,
                None,
                "",
                prev_hash,
            ));
        }
        ActionType::Resign => {
            events.push(make_event(
                session.runtime.sequence,
                EventType::Resign,
                player,
                None,
                None,
                None,
                "",
                prev_hash,
            ));
            session.runtime.status = GameStatus::Finished;
        }
        ActionType::Flip => {
            if let Some(ref comp_id_str) = action.component_id {
                let cid = session
                    .runtime
                    .components
                    .iter()
                    .find(|c| c.string_id == *comp_id_str)
                    .map(|c| c.id);
                if let Some(cid) = cid {
                    if let Some(comp_mut) = session.runtime.components.get_mut(cid) {
                        comp_mut.facing = match comp_mut.facing {
                            Some(crate::state::Facing::FaceUp) => {
                                Some(crate::state::Facing::FaceDown)
                            }
                            Some(crate::state::Facing::FaceDown) | None => {
                                Some(crate::state::Facing::FaceUp)
                            }
                        };
                    }
                    events.push(make_event(
                        session.runtime.sequence,
                        EventType::Flip,
                        player,
                        Some(comp_id_str),
                        None,
                        None,
                        "",
                        prev_hash,
                    ));
                }
            }
        }
        ActionType::Remove => {
            let comp_id_str = action
                .component_id
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("remove requires component_id".into()))?;
            let (cid, zone_name, col, row) =
                find_component_on_grid(session, comp_id_str)?;

            // Check if this is a spanning component
            let span_cells = session
                .runtime
                .components
                .get(cid)
                .map(|c| c.span_cells.clone())
                .unwrap_or_default();

            let zone = session
                .runtime
                .zones
                .get_mut(&zone_name)
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;

            if span_cells.is_empty() {
                zone.grid_set(col, row, None);
            } else {
                zone.grid_remove_span(&span_cells);
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Remove,
                player,
                Some(comp_id_str),
                Some(&format!("{col},{row}")),
                None,
                "",
                prev_hash,
            ));
        }
        ActionType::Swap => {
            let comp_id_str = action
                .component_id
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("swap requires component_id".into()))?;
            let swap_with_str = action
                .swap_with
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("swap requires swap_with".into()))?;

            let (_cid_a, zone_a, col_a, row_a) =
                find_component_on_grid(session, comp_id_str)?;
            let (_cid_b, zone_b, col_b, row_b) =
                find_component_on_grid(session, swap_with_str)?;

            if zone_a != zone_b {
                return Err(BaizeError::IllegalAction(
                    "swap requires both components in the same zone".into(),
                ));
            }

            let zone = session
                .runtime
                .zones
                .get_mut(&zone_a)
                .ok_or_else(|| BaizeError::UnknownZone(zone_a.clone()))?;
            let a = zone.grid_get(col_a, row_a);
            let b = zone.grid_get(col_b, row_b);
            zone.grid_set(col_a, row_a, b);
            zone.grid_set(col_b, row_b, a);

            events.push(make_event(
                session.runtime.sequence,
                EventType::Swap,
                player,
                Some(comp_id_str),
                Some(&format!("{col_a},{row_a}")),
                Some(&format!("{col_b},{row_b}")),
                "",
                prev_hash,
            ));
        }
        ActionType::Promote => {
            let comp_id_str = action
                .component_id
                .as_deref()
                .ok_or_else(|| {
                    BaizeError::IllegalAction("promote requires component_id".into())
                })?;
            let promote_to = action
                .promote_to
                .as_deref()
                .ok_or_else(|| {
                    BaizeError::IllegalAction("promote requires promote_to".into())
                })?;

            let cid = session
                .runtime
                .components
                .iter()
                .find(|c| c.string_id == *comp_id_str)
                .map(|c| c.id)
                .ok_or_else(|| {
                    BaizeError::IllegalAction(format!("component {comp_id_str:?} not found"))
                })?;

            if let Some(comp) = session.runtime.components.get_mut(cid) {
                comp.component_type = promote_to.to_string();
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Promote,
                player,
                Some(comp_id_str),
                None,
                None,
                "",
                prev_hash,
            ));
        }
        ActionType::Draw => {
            let source_zone = action
                .zone
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("draw requires zone".into()))?;

            let zone = session
                .runtime
                .zones
                .get_mut(source_zone)
                .ok_or_else(|| BaizeError::UnknownZone(source_zone.into()))?;

            let cid = zone
                .stack_pop()
                .ok_or_else(|| BaizeError::IllegalAction("source zone is empty".into()))?;

            let comp_name = session
                .runtime
                .components
                .get(cid)
                .map(|c| c.string_id.clone())
                .unwrap_or_default();

            // Add to the player's first per-player zone (hand)
            if let Some(player_state) = session.runtime.players.get_mut(player) {
                if let Some(hand) = player_state.zones.values_mut().next() {
                    match hand {
                        RuntimeZone::OrderedStack { .. } => hand.stack_push(cid),
                        RuntimeZone::Set { .. } => hand.set_add(cid),
                        _ => {}
                    }
                }
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Draw,
                player,
                Some(&comp_name),
                None,
                None,
                "",
                prev_hash,
            ));
        }
        ActionType::PlaceShip => {
            let (to_col, to_row) = parse_position(action.to.as_ref())?;
            let zone_name = position_zone(action.to.as_ref()).unwrap_or("board".to_string());
            let comp_type = action
                .component_type
                .as_deref()
                .ok_or_else(|| {
                    BaizeError::IllegalAction("place_ship requires component_type".into())
                })?;

            let horizontal = match action.orientation {
                Some(crate::action::Orientation::Horizontal) => true,
                Some(crate::action::Orientation::Vertical) => false,
                None => {
                    return Err(BaizeError::IllegalAction(
                        "place_ship requires orientation".into(),
                    ))
                }
            };

            // Look up span from definition: check types[comp_type].span, then component.span
            let span = lookup_span(&session.definition, comp_type)?;

            let instance_id = format!(
                "{}-{}-{}",
                comp_type,
                player,
                session.runtime.components.len()
            );
            let cid = session.runtime.components.insert(ComponentData {
                id: ComponentId(0),
                string_id: instance_id.clone(),
                component_type: comp_type.to_string(),
                owner: Some(player.to_string()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
                span_cells: Vec::new(),
                orientation: None,
            })?;

            // Try player zone first, then shared zones
            let zone = session
                .runtime
                .players
                .get_mut(player)
                .and_then(|p| p.zones.get_mut(&zone_name))
                .or_else(|| session.runtime.zones.get_mut(&zone_name))
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;

            let span_cells = zone.grid_place_span(to_col, to_row, horizontal, span, cid)?;

            // Store span cells on the component
            if let Some(comp) = session.runtime.components.get_mut(cid) {
                comp.span_cells = span_cells;
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Place,
                player,
                Some(&instance_id),
                None,
                Some(&format!("{},{}", to_col, to_row)),
                "",
                prev_hash,
            ));
        }
        ActionType::Fire => {
            let (target_col, target_row) = parse_position(action.to.as_ref())?;
            let target_zone_name = position_zone(action.to.as_ref()).unwrap_or("ocean".to_string());
            let peg_zone_name = action
                .zone
                .as_deref()
                .unwrap_or("target");

            // Find the opponent
            let opponent = session
                .runtime
                .players
                .keys()
                .find(|p| p.as_str() != player)
                .cloned()
                .ok_or_else(|| BaizeError::IllegalAction("no opponent found".into()))?;

            // Check if attacker already fired at this cell (check own target grid for peg)
            {
                let attacker_target = session
                    .runtime
                    .players
                    .get(player)
                    .and_then(|p| p.zones.get(peg_zone_name));
                if let Some(tz) = attacker_target {
                    if tz.grid_get(target_col, target_row).is_some() {
                        return Err(BaizeError::IllegalAction(format!(
                            "already fired at ({target_col},{target_row})"
                        )));
                    }
                }
            }

            // Check opponent's ocean grid at the target cell
            let hit_cid = {
                let opp_ocean = session
                    .runtime
                    .players
                    .get(&opponent)
                    .and_then(|p| p.zones.get(&target_zone_name));
                match opp_ocean {
                    Some(zone) => zone.grid_get(target_col, target_row),
                    None => None,
                }
            };

            let is_hit = hit_cid.is_some();

            // Create a peg (hit or miss) on the attacker's target grid
            let peg_type = if is_hit { "hit" } else { "miss" };
            let peg_id = format!("{}-{}-{}", peg_type, player, session.runtime.components.len());
            let peg_cid = session.runtime.components.insert(ComponentData {
                id: ComponentId(0),
                string_id: peg_id.clone(),
                component_type: peg_type.to_string(),
                owner: Some(player.to_string()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
                span_cells: Vec::new(),
                orientation: None,
            })?;

            // Place peg on attacker's target grid
            if let Some(attacker) = session.runtime.players.get_mut(player) {
                if let Some(target_zone) = attacker.zones.get_mut(peg_zone_name) {
                    target_zone.grid_set(target_col, target_row, Some(peg_cid));
                }
            }

            // Fire event
            events.push(make_event(
                session.runtime.sequence,
                EventType::Fire,
                player,
                None,
                None,
                Some(&format!("{target_col},{target_row}")),
                "",
                prev_hash,
            ));

            if is_hit {
                let hit_comp_id = hit_cid.expect("verified is_hit above");

                // Increment hit_count on the ship component
                let (ship_type, hit_count, span_len) = {
                    let comp = session.runtime.components.get_mut(hit_comp_id)
                        .ok_or_else(|| BaizeError::IllegalAction("hit component not found".into()))?;
                    let prev = comp.properties
                        .get("hit_count")
                        .and_then(|v| v.as_u64())
                        .unwrap_or(0);
                    let new_count = prev + 1;
                    comp.properties.insert(
                        "hit_count".to_string(),
                        serde_json::Value::Number(serde_json::Number::from(new_count)),
                    );
                    (comp.component_type.clone(), new_count, comp.span_cells.len() as u64)
                };

                events.push(make_event(
                    session.runtime.sequence,
                    EventType::Hit,
                    player,
                    Some(&peg_id),
                    None,
                    Some(&format!("{target_col},{target_row}")),
                    "",
                    prev_hash,
                ));

                // Check if ship is sunk (hit_count == span length)
                if span_len > 0 && hit_count >= span_len {
                    events.push(GameEvent {
                        sequence: session.runtime.sequence,
                        event_type: EventType::Sunk,
                        player: player.to_string(),
                        component_id: Some(ship_type),
                        from: None,
                        to: None,
                        captured: None,
                        detail: None,
                        state_hash: String::new(),
                        prev_hash: prev_hash.clone(),
                    });

                    // Decrement opponent's ships_remaining counter
                    if let Some(opp) = session.runtime.players.get_mut(&opponent) {
                        if let Some(counter) = opp.counters.get_mut("ships_remaining") {
                            *counter = counter.saturating_sub(1);
                        }
                    }
                }
            } else {
                events.push(make_event(
                    session.runtime.sequence,
                    EventType::Miss,
                    player,
                    Some(&peg_id),
                    None,
                    Some(&format!("{target_col},{target_row}")),
                    "",
                    prev_hash,
                ));
            }
        }
        ActionType::Commit => {
            let hash = action.declaration.as_deref().ok_or_else(|| {
                BaizeError::IllegalAction("commit action requires declaration (hash)".into())
            })?;
            if session.runtime.pending_commits.contains_key(player) {
                return Err(BaizeError::IllegalAction(
                    format!("player {player} already has a pending commitment"),
                ));
            }
            session
                .runtime
                .pending_commits
                .insert(player.to_string(), hash.to_string());
            events.push(make_event(
                session.runtime.sequence,
                EventType::Commit,
                player,
                None,
                None,
                None,
                "",
                prev_hash,
            ));
        }
        ActionType::Reveal => {
            use sha2::{Digest, Sha256};
            use subtle::ConstantTimeEq;

            let stored = session
                .runtime
                .pending_commits
                .get(player)
                .cloned()
                .ok_or_else(|| {
                    BaizeError::IllegalAction(format!(
                        "player {player} has no pending commitment to reveal"
                    ))
                })?;
            let value = action.declaration.as_deref().ok_or_else(|| {
                BaizeError::IllegalAction("reveal action requires declaration (value)".into())
            })?;
            let nonce = action.commitment.as_deref().ok_or_else(|| {
                BaizeError::IllegalAction("reveal action requires commitment (nonce)".into())
            })?;
            let preimage = format!("{value}|{nonce}");
            let actual = format!("{:x}", Sha256::digest(preimage.as_bytes()));
            // Constant-time comparison to prevent timing side-channel attacks
            if actual.as_bytes().ct_eq(stored.as_bytes()).unwrap_u8() != 1 {
                return Err(BaizeError::IllegalAction(format!(
                    "commitment verification failed: SHA-256({value}|<nonce>) != stored hash"
                )));
            }
            session.runtime.pending_commits.swap_remove(player);

            // Place the revealed component if component_type and position are provided
            if let (Some(comp_type), Some(to_pos)) =
                (&action.component_type, &action.to)
            {
                let (to_col, to_row) = parse_position(Some(to_pos))?;
                let zone_name =
                    position_zone(Some(to_pos)).unwrap_or("board".to_string());

                let instance_id = format!(
                    "{}-{}-{}",
                    comp_type,
                    player,
                    session.runtime.components.len()
                );
                let cid = session.runtime.components.insert(ComponentData {
                    id: ComponentId(0),
                    string_id: instance_id,
                    component_type: comp_type.clone(),
                    owner: Some(player.to_string()),
                    facing: None,
                    state: None,
                    properties: IndexMap::new(),
                    span_cells: Vec::new(),
                    orientation: None,
                })?;

                // Try global zones first, then player zones
                let zone = session
                    .runtime
                    .zones
                    .get_mut(&zone_name)
                    .or_else(|| {
                        session
                            .runtime
                            .players
                            .get_mut(player)
                            .and_then(|p| p.zones.get_mut(&zone_name))
                    });
                if let Some(zone) = zone {
                    zone.grid_set(to_col, to_row, Some(cid));
                }
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Reveal,
                player,
                None,
                None,
                None,
                "",
                prev_hash,
            ));
        }
        _ => {
            return Err(BaizeError::IllegalAction(format!(
                "action type {:?} not yet implemented",
                action.action_type
            )));
        }
    }

    // Recompute fog of war for the acting player on any fog-enabled zones
    if matches!(action.action_type, ActionType::MovePiece | ActionType::Place) {
        recompute_player_fog(session, player);
    }

    Ok(events)
}

/// Apply visibility transition rules that match the given phase.
///
/// Checks all `definition.visibility_transitions` and applies those whose
/// `phase` field matches `new_phase`. Emits a `VisibilityChange` event for
/// each applied transition.
fn apply_visibility_transitions(
    session: &mut GameSession,
    new_phase: &str,
    prev_hash: &Option<String>,
) -> Vec<GameEvent> {
    let mut events = Vec::new();

    let transitions: Vec<_> = session
        .definition
        .visibility_transitions
        .iter()
        .filter(|vt| vt.phase.as_deref() == Some(new_phase))
        .cloned()
        .collect();

    for vt in &transitions {
        let new_vis = match vt.new_visibility.as_str() {
            "public" => Visibility::Tier(VisibilityTier::Public),
            "hidden" => Visibility::Tier(VisibilityTier::Hidden),
            _ => continue, // validated at parse time, but be defensive
        };

        let zone_key = match &vt.player {
            Some(player) => format!("{}[{}]", vt.zone, player),
            None => vt.zone.clone(),
        };

        let _prev = session.runtime.change_visibility(&zone_key, new_vis);

        events.push(GameEvent {
            sequence: session.runtime.sequence,
            event_type: EventType::VisibilityChange,
            player: vt.player.clone().unwrap_or_default(),
            component_id: None,
            from: None,
            to: Some(zone_key),
            captured: None,
            detail: Some(vt.new_visibility.clone()),
            state_hash: String::new(),
            prev_hash: prev_hash.clone(),
        });
    }

    events
}

/// Advance the game to a new phase by index and apply visibility transitions.
///
/// Returns events for any visibility changes triggered by the new phase.
pub fn advance_phase(
    session: &mut GameSession,
    new_phase_index: usize,
    prev_hash: &Option<String>,
) -> Vec<GameEvent> {
    session.runtime.phase_index = new_phase_index;
    let phase_name = session
        .definition
        .phases
        .get(new_phase_index)
        .map(|p| p.name.clone())
        .unwrap_or_else(|| "main".to_string());
    apply_visibility_transitions(session, &phase_name, prev_hash)
}

/// Check end conditions, advance turn, compute hash, and stamp all events.
fn finalize_turn(
    session: &mut GameSession,
    mut events: Vec<GameEvent>,
    prev_hash: Option<String>,
    action: Option<&Action>,
) -> Result<Vec<GameEvent>> {
    // Enforce event budget (+1 for the turn_advance or game_end event added below)
    let projected = session
        .runtime
        .event_count
        .saturating_add(events.len() as u64 + 1);
    if projected > MAX_EVENTS_PER_GAME as u64 {
        return Err(BaizeError::ResourceBudget(format!(
            "event count ({projected}) would exceed limit ({MAX_EVENTS_PER_GAME})"
        )));
    }

    // Periodic state size check (amortized)
    if session.runtime.move_count % STATE_SIZE_CHECK_INTERVAL == 0
        && session.runtime.move_count > 0
    {
        let wire = session.to_wire_state();
        let size = serde_json::to_string(&wire)
            .map(|s| s.len())
            .unwrap_or(0);
        if size > MAX_STATE_SIZE_BYTES {
            return Err(BaizeError::ResourceBudget(format!(
                "serialized state size ({size} bytes) exceeds limit ({MAX_STATE_SIZE_BYTES} bytes)"
            )));
        }
    }

    // Check end conditions before advancing turn ("current" = player who just moved)
    if session.runtime.status != GameStatus::Finished {
        if let Some(result) = check_end_conditions(session) {
            session.runtime.status = GameStatus::Finished;
            session.runtime.result = Some(result.clone());

            let new_hash = session.compute_state_hash();
            session.runtime.history_hashes.push(new_hash.clone());

            for event in &mut events {
                event.state_hash = new_hash.clone();
            }

            events.push(GameEvent {
                sequence: session.runtime.sequence,
                event_type: EventType::GameEnd,
                player: result.winner.unwrap_or_default(),
                component_id: None,
                from: None,
                to: None,
                captured: None,
                detail: result.condition,
                state_hash: new_hash,
                prev_hash,
            });

            session.runtime.event_count += events.len() as u64;
            return Ok(events);
        }
    }

    // Check if any trigger matches the action that was just applied
    if let Some(action) = action {
        if session.runtime.claim_window.is_none() {
            if let Some((trigger_name, trigger_def)) =
                find_matching_trigger(session, action)
            {
                let eligible = compute_eligible_players(
                    session,
                    &trigger_def.claim_window.eligible,
                )?;

                if !eligible.is_empty() {
                    let triggering_player = session
                        .current_player()
                        .unwrap_or("")
                        .to_string();

                    session.runtime.claim_window = Some(ClaimWindow {
                        trigger_name: trigger_name.clone(),
                        triggering_action: action.clone(),
                        triggering_player: triggering_player.clone(),
                        eligible_players: eligible.clone(),
                        submitted_claims: IndexMap::new(),
                        priority: trigger_def.claim_window.priority.clone(),
                        default_claim: trigger_def.claim_window.default.clone(),
                    });

                    events.push(GameEvent {
                        sequence: session.runtime.sequence,
                        event_type: EventType::TriggerActivated,
                        player: triggering_player,
                        component_id: None,
                        from: None,
                        to: None,
                        captured: None,
                        detail: Some(trigger_name),
                        state_hash: String::new(),
                        prev_hash: prev_hash.clone(),
                    });

                    // Compute hash but do NOT advance turn
                    let new_hash = session.compute_state_hash();
                    session.runtime.history_hashes.push(new_hash.clone());
                    for event in &mut events {
                        event.state_hash = new_hash.clone();
                    }
                    session.runtime.event_count += events.len() as u64;
                    return Ok(events);
                }
            }
        }
    }

    // Advance turn
    session.advance_turn();
    let new_hash = session.compute_state_hash();
    session
        .runtime
        .history_hashes
        .push(new_hash.clone());

    // Update hashes on all events
    for event in &mut events {
        event.state_hash = new_hash.clone();
    }

    events.push(GameEvent {
        sequence: session.runtime.sequence,
        event_type: EventType::TurnAdvance,
        player: session.current_player().unwrap_or("").to_string(),
        component_id: None,
        from: None,
        to: None,
        captured: None,
        detail: None,
        state_hash: new_hash,
        prev_hash,
    });

    session.runtime.event_count += events.len() as u64;
    Ok(events)
}

// --- Helpers ---

fn parse_position(pos: Option<&Position>) -> Result<(u32, u32)> {
    match pos {
        Some(Position::Coordinate(s)) => parse_coord_str(s),
        Some(Position::Structured { cell, .. }) => {
            parse_coord_str(cell.as_deref().unwrap_or("0,0"))
        }
        None => Err(BaizeError::IllegalAction("missing position".into())),
    }
}

fn parse_coord_str(s: &str) -> Result<(u32, u32)> {
    let parts: Vec<&str> = s.split(',').collect();
    if parts.len() == 2 {
        let col = parts[0]
            .trim()
            .parse::<u32>()
            .map_err(|_| BaizeError::IllegalAction(format!("invalid coordinate: {s}")))?;
        let row = parts[1]
            .trim()
            .parse::<u32>()
            .map_err(|_| BaizeError::IllegalAction(format!("invalid coordinate: {s}")))?;
        Ok((col, row))
    } else {
        Err(BaizeError::IllegalAction(format!(
            "invalid coordinate format: {s}"
        )))
    }
}

/// Find a component by its string ID on any grid zone. Returns (ComponentId, zone_name, col, row).
fn find_component_on_grid(
    session: &GameSession,
    comp_id_str: &str,
) -> Result<(ComponentId, String, u32, u32)> {
    let cid = session
        .runtime
        .components
        .iter()
        .find(|c| c.string_id == *comp_id_str)
        .map(|c| c.id)
        .ok_or_else(|| {
            BaizeError::IllegalAction(format!("component {comp_id_str:?} not found"))
        })?;

    for (zone_name, zone) in &session.runtime.zones {
        if let crate::runtime::RuntimeZone::Grid { storage, .. } = zone {
            for (col, row, cell_cid) in storage.occupied_cells() {
                if cell_cid == cid {
                    if col < 0 || row < 0 {
                        continue;
                    }
                    return Ok((cid, zone_name.clone(), col as u32, row as u32));
                }
            }
        }
    }

    Err(BaizeError::IllegalAction(format!(
        "component {comp_id_str:?} not found on any grid"
    )))
}

/// Look up span for a component type from the game definition.
///
/// Checks (in order):
/// 1. Component types[comp_type].span (per-type span)
/// 2. Component-level span (uniform span)
/// 3. Default: 1
fn lookup_span(
    definition: &crate::definition::GameDefinition,
    comp_type: &str,
) -> Result<u32> {
    for comp_def in definition.components.values() {
        // Check per-type span
        if let Some(ref types) = comp_def.types {
            if let Some(type_def) = types.get(comp_type) {
                if let Some(span) = type_def.get("span").and_then(|v| v.as_u64()) {
                    return Ok(span as u32);
                }
            }
        }
        // Check component-level span
        if let Some(span) = comp_def.span {
            return Ok(span);
        }
    }
    Ok(1)
}

fn position_zone(pos: Option<&Position>) -> Option<String> {
    match pos {
        Some(Position::Structured { zone, .. }) => zone.clone(),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
fn make_event(
    sequence: u64,
    event_type: EventType,
    player: &str,
    component_id: Option<&str>,
    from: Option<&str>,
    to: Option<&str>,
    _detail: &str,
    prev_hash: &Option<String>,
) -> GameEvent {
    GameEvent {
        sequence,
        event_type,
        player: player.to_string(),
        component_id: component_id.map(String::from),
        from: from.map(String::from),
        to: to.map(String::from),
        captured: None,
        detail: None,
        state_hash: String::new(), // filled in after state mutation
        prev_hash: prev_hash.clone(),
    }
}

/// Recompute fog of war for a player on all fog-enabled shared zones.
///
/// Finds all units owned by the player on each fog-enabled zone and calls
/// `recompute_fog` with their positions and the zone's vision_range.
fn recompute_player_fog(session: &mut GameSession, player: &str) {
    // Collect zone names and vision_range for fog-enabled zones
    let fog_zones: Vec<(String, u32)> = session
        .runtime
        .zones
        .iter()
        .filter_map(|(name, zone)| {
            zone.fog_config()
                .map(|config| (name.clone(), config.vision_range))
        })
        .collect();

    for (zone_name, vision_range) in fog_zones {
        if vision_range == 0 {
            continue;
        }

        // Find all units owned by the player on this zone
        let unit_positions: Vec<(i32, i32)> = {
            let zone = &session.runtime.zones[&zone_name];
            if let RuntimeZone::Grid { storage, .. } = zone {
                storage
                    .occupied_cells()
                    .iter()
                    .filter_map(|&(col, row, cid)| {
                        session
                            .runtime
                            .components
                            .get(cid)
                            .and_then(|comp| {
                                if comp.owner.as_deref() == Some(player) {
                                    Some((col, row))
                                } else {
                                    None
                                }
                            })
                    })
                    .collect()
            } else {
                continue;
            }
        };

        if let Some(zone) = session.runtime.zones.get_mut(&zone_name) {
            zone.recompute_fog(player, &unit_positions, vision_range);
        }
    }
}

// --- Trigger / claim window ---

/// Find a trigger whose `on_action` matches the action just performed.
///
/// Returns the trigger name and definition if found. The trigger's `on_action`
/// is matched against the action_type's snake_case serialization.
fn find_matching_trigger<'a>(
    session: &'a GameSession,
    action: &Action,
) -> Option<(String, &'a TriggerDef)> {
    if session.definition.triggers.is_empty() {
        return None;
    }

    // Serialize the action_type to its snake_case form for matching
    let action_type_str = serde_json::to_value(&action.action_type)
        .ok()
        .and_then(|v| v.as_str().map(String::from))?;

    for (name, trigger) in &session.definition.triggers {
        if trigger.on_action == action_type_str {
            // TODO: evaluate CEL condition when condition support is added
            return Some((name.clone(), trigger));
        }
    }
    None
}

/// Compute which players are eligible for a claim window.
fn compute_eligible_players(
    session: &GameSession,
    eligible_rule: &str,
) -> Result<Vec<String>> {
    let current = session.current_player().unwrap_or("").to_string();
    let all_players: Vec<String> = session.runtime.players.keys().cloned().collect();

    match eligible_rule {
        "all_except_current" => {
            Ok(all_players.into_iter().filter(|p| p != &current).collect())
        }
        "next_in_order" => {
            let player_count = all_players.len();
            if player_count == 0 {
                return Ok(vec![]);
            }
            let next_index = (session.runtime.turn_index + 1) % player_count;
            Ok(vec![all_players[next_index].clone()])
        }
        other => Err(BaizeError::IllegalAction(
            format!("unknown eligible rule: {other:?}"),
        )),
    }
}

/// Submit a claim during an active claim window.
///
/// When all eligible players have responded, resolves the window:
/// the highest-priority claim wins, that player becomes active,
/// and normal turn flow resumes.
pub fn apply_claim(
    session: &mut GameSession,
    player: &str,
    claim: &str,
) -> Result<Vec<GameEvent>> {
    let window = session
        .runtime
        .claim_window
        .as_mut()
        .ok_or_else(|| BaizeError::IllegalAction("no active claim window".into()))?;

    // Defensive: player must be eligible
    if !window.eligible_players.contains(&player.to_string()) {
        return Err(BaizeError::IllegalAction(format!(
            "player {player} is not eligible for this claim window"
        )));
    }

    // Defensive: no double-submission
    if window.submitted_claims.contains_key(player) {
        return Err(BaizeError::IllegalAction(format!(
            "player {player} has already submitted a claim"
        )));
    }

    // Defensive: claim must be valid (in actions list or the default)
    let trigger_def = session
        .definition
        .triggers
        .get(&window.trigger_name)
        .ok_or_else(|| {
            BaizeError::IllegalAction("trigger definition not found".into())
        })?;
    let valid_claims: Vec<&str> = trigger_def
        .claim_window
        .actions
        .iter()
        .map(|s| s.as_str())
        .chain(std::iter::once(trigger_def.claim_window.default.as_str()))
        .collect();
    if !valid_claims.contains(&claim) {
        return Err(BaizeError::IllegalAction(format!(
            "invalid claim {claim:?} — valid: {valid_claims:?}"
        )));
    }

    // Re-borrow mutably after the immutable borrow of definition
    let window = session
        .runtime
        .claim_window
        .as_mut()
        .expect("claim_window verified present above");
    window
        .submitted_claims
        .insert(player.to_string(), claim.to_string());

    let prev_hash = session.runtime.history_hashes.last().cloned();
    let mut events = vec![GameEvent {
        sequence: session.runtime.sequence,
        event_type: EventType::ClaimSubmitted,
        player: player.to_string(),
        component_id: None,
        from: None,
        to: None,
        captured: None,
        detail: Some(claim.to_string()),
        state_hash: String::new(),
        prev_hash: prev_hash.clone(),
    }];

    // Check if all eligible players have submitted
    let all_submitted = {
        let window = session
            .runtime
            .claim_window
            .as_ref()
            .expect("claim_window verified present above");
        window
            .eligible_players
            .iter()
            .all(|p| window.submitted_claims.contains_key(p))
    };

    if all_submitted {
        events.extend(resolve_claim_window(session, prev_hash.clone())?);
    } else {
        // Just hash and return
        let new_hash = session.compute_state_hash();
        session.runtime.history_hashes.push(new_hash.clone());
        for event in &mut events {
            event.state_hash = new_hash.clone();
        }
        session.runtime.event_count += events.len() as u64;
    }

    Ok(events)
}

/// Resolve a completed claim window: pick the winning claim and advance the game.
fn resolve_claim_window(
    session: &mut GameSession,
    prev_hash: Option<String>,
) -> Result<Vec<GameEvent>> {
    let window = session
        .runtime
        .claim_window
        .take()
        .expect("resolve_claim_window called without active window");

    // Find the highest-priority claim that isn't the default (pass)
    let mut winning_claim: Option<(String, String)> = None; // (player, claim)
    for priority_action in &window.priority {
        for (player, claim) in &window.submitted_claims {
            if claim == priority_action && claim != &window.default_claim {
                winning_claim = Some((player.clone(), claim.clone()));
                break; // first player at this priority level wins
            }
        }
        if winning_claim.is_some() {
            break;
        }
    }

    let mut events = Vec::new();

    if let Some((ref winner, ref claim)) = winning_claim {
        // Winner becomes the active player
        let player_names: Vec<String> = session.runtime.players.keys().cloned().collect();
        let winner_index = player_names
            .iter()
            .position(|p| p == winner)
            .ok_or_else(|| {
                BaizeError::IllegalAction(format!(
                    "winning claimant {winner} not in player list"
                ))
            })?;
        session.runtime.turn_index = winner_index;

        events.push(GameEvent {
            sequence: session.runtime.sequence,
            event_type: EventType::ClaimResolved,
            player: winner.clone(),
            component_id: None,
            from: None,
            to: None,
            captured: None,
            detail: Some(claim.clone()),
            state_hash: String::new(),
            prev_hash: prev_hash.clone(),
        });
    } else {
        // All passed — advance turn normally
        session.advance_turn();
        events.push(GameEvent {
            sequence: session.runtime.sequence,
            event_type: EventType::ClaimResolved,
            player: String::new(),
            component_id: None,
            from: None,
            to: None,
            captured: None,
            detail: Some("all_passed".to_string()),
            state_hash: String::new(),
            prev_hash: prev_hash.clone(),
        });
    }

    let new_hash = session.compute_state_hash();
    session.runtime.history_hashes.push(new_hash.clone());
    for event in &mut events {
        event.state_hash = new_hash.clone();
    }

    // Add turn_advance event
    events.push(GameEvent {
        sequence: session.runtime.sequence,
        event_type: EventType::TurnAdvance,
        player: session.current_player().unwrap_or("").to_string(),
        component_id: None,
        from: None,
        to: None,
        captured: None,
        detail: None,
        state_hash: new_hash,
        prev_hash,
    });

    session.runtime.event_count += events.len() as u64;
    Ok(events)
}
