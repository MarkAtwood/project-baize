use indexmap::IndexMap;

use crate::action::{Action, ActionType, Position};
use crate::end_conditions::check_end_conditions;
use crate::error::{BaizeError, Result};
use crate::runtime::{ComponentData, ComponentId, GameSession};
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
    finalize_turn(session, events, prev_hash)
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
        events = finalize_turn(session, events, prev_hash)?;
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

            // Check for capture
            let captured = zone.grid_get(to_col, to_row);
            if let Some(cap_id) = captured {
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

            // Move the piece
            zone.grid_set(from_col, from_row, None);
            zone.grid_set(to_col, to_row, Some(cid));

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
            zone.grid_set(to_col, to_row, Some(cid));

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
                    hand.stack_push(cid);
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

    Ok(events)
}

/// Check end conditions, advance turn, compute hash, and stamp all events.
fn finalize_turn(
    session: &mut GameSession,
    mut events: Vec<GameEvent>,
    prev_hash: Option<String>,
) -> Result<Vec<GameEvent>> {
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

            return Ok(events);
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
        if let crate::runtime::RuntimeZone::Grid { width, height, cells, .. } = zone
        {
            debug_assert_eq!(
                cells.len(),
                (*width as usize) * (*height as usize),
                "grid cells length {} != width*height {}x{} in zone {}",
                cells.len(),
                width,
                height,
                zone_name
            );
            for row in 0..*height {
                for col in 0..*width {
                    let idx = row as usize * *width as usize + col as usize;
                    if cells.get(idx).copied().flatten() == Some(cid) {
                        return Ok((cid, zone_name.clone(), col, row));
                    }
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
