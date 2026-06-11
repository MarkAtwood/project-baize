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
    TurnAdvance,
    GameEnd,
}

/// Apply an action to the game session, mutating state and returning events.
pub fn apply_action(session: &mut GameSession, action: &Action) -> Result<Vec<GameEvent>> {
    let player = session
        .current_player()
        .ok_or_else(|| BaizeError::IllegalAction("no current player".into()))?
        .to_string();

    if session.runtime.status == GameStatus::Finished {
        return Err(BaizeError::IllegalAction("game is finished".into()));
    }

    if session.runtime.status == GameStatus::Setup {
        session.runtime.status = GameStatus::InProgress;
    }

    let prev_hash = session.runtime.history_hashes.last().cloned();
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
                    &player,
                    Some(&cap_name),
                    None,
                    Some(&format!("{},{}", to_col, to_row)),
                    "",
                    &prev_hash,
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
                &player,
                Some(&comp_name),
                Some(&format!("{},{}", from_col, from_row)),
                Some(&format!("{},{}", to_col, to_row)),
                "",
                &prev_hash,
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
                owner: Some(player.clone()),
                facing: None,
                state: None,
                properties: IndexMap::new(),
            })?;

            let zone = session
                .runtime
                .zones
                .get_mut(&zone_name)
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;
            zone.grid_set(to_col, to_row, Some(cid));

            events.push(make_event(
                session.runtime.sequence,
                EventType::Place,
                &player,
                Some(&instance_id),
                None,
                Some(&format!("{},{}", to_col, to_row)),
                "",
                &prev_hash,
            ));
        }
        ActionType::Pass => {
            events.push(make_event(
                session.runtime.sequence,
                EventType::Pass,
                &player,
                None,
                None,
                None,
                "",
                &prev_hash,
            ));
        }
        ActionType::Resign => {
            events.push(make_event(
                session.runtime.sequence,
                EventType::Resign,
                &player,
                None,
                None,
                None,
                "",
                &prev_hash,
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
                        &player,
                        Some(comp_id_str),
                        None,
                        None,
                        "",
                        &prev_hash,
                    ));
                }
            }
        }
        ActionType::Remove => {
            let comp_id_str = action
                .component_id
                .as_deref()
                .ok_or_else(|| BaizeError::IllegalAction("remove requires component_id".into()))?;
            let (_cid, zone_name, col, row) =
                find_component_on_grid(session, comp_id_str)?;

            let zone = session
                .runtime
                .zones
                .get_mut(&zone_name)
                .ok_or_else(|| BaizeError::UnknownZone(zone_name.clone()))?;
            zone.grid_set(col, row, None);

            events.push(make_event(
                session.runtime.sequence,
                EventType::Remove,
                &player,
                Some(comp_id_str),
                Some(&format!("{col},{row}")),
                None,
                "",
                &prev_hash,
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
                &player,
                Some(comp_id_str),
                Some(&format!("{col_a},{row_a}")),
                Some(&format!("{col_b},{row_b}")),
                "",
                &prev_hash,
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
                &player,
                Some(comp_id_str),
                None,
                None,
                "",
                &prev_hash,
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
            if let Some(player_state) = session.runtime.players.get_mut(&player) {
                if let Some(hand) = player_state.zones.values_mut().next() {
                    hand.stack_push(cid);
                }
            }

            events.push(make_event(
                session.runtime.sequence,
                EventType::Draw,
                &player,
                Some(&comp_name),
                None,
                None,
                "",
                &prev_hash,
            ));
        }
        _ => {
            return Err(BaizeError::IllegalAction(format!(
                "action type {:?} not yet implemented",
                action.action_type
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
        if let crate::runtime::RuntimeZone::Grid {
            width,
            height,
            cells,
        } = zone
        {
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
