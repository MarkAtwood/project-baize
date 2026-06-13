use indexmap::IndexMap;

use crate::definition::{GameDefinition, Visibility, VisibilityTier};
use crate::state::{GameState, ZoneState};

/// Resolve effective visibility for a zone, checking runtime overrides first.
fn effective_visibility<'a>(
    zone_name: &str,
    override_key: &str,
    definition: &'a GameDefinition,
    overrides: &'a IndexMap<String, Visibility>,
) -> Option<&'a Visibility> {
    // Runtime override takes precedence
    if let Some(vis) = overrides.get(override_key) {
        return Some(vis);
    }
    // Fall back to definition
    definition.zones.get(zone_name).map(|z| &z.visibility)
}

/// Produce a filtered view of the game state for a specific viewer.
///
/// Visibility rules:
/// - public zones: all components included
/// - hidden zones: components stripped, only count retained
/// - private zones: owner sees contents, others see only count
/// - server (`"__server__"`) sees everything
///
/// Runtime overrides in `full_state.visibility_overrides` take precedence
/// over the definition's static visibility. For per-player zones, the
/// override key format is `"zone_name[player_name]"`.
pub fn filter_for_viewer(
    full_state: &GameState,
    viewer: &str,
    definition: &GameDefinition,
) -> GameState {
    if viewer == "__server__" {
        return full_state.clone();
    }

    let mut filtered = full_state.clone();

    // Filter shared zones
    for (zone_name, zone_state) in &full_state.zones {
        let vis = effective_visibility(
            zone_name,
            zone_name,
            definition,
            &full_state.visibility_overrides,
        );
        match vis {
            Some(Visibility::Tier(VisibilityTier::Public)) | None => {}
            Some(Visibility::Tier(VisibilityTier::Hidden)) => {
                let count = zone_component_count(zone_state);
                filtered
                    .zones
                    .insert(zone_name.clone(), redacted_zone(zone_state, count));
            }
            Some(Visibility::Private { .. }) => {
                // Shared zone marked private: treat as hidden for all players
                let count = zone_component_count(zone_state);
                filtered
                    .zones
                    .insert(zone_name.clone(), redacted_zone(zone_state, count));
            }
        }
    }

    // Filter per-player zones
    for (player_name, player_state) in &full_state.players {
        let Some(filtered_player) = filtered.players.get_mut(player_name) else {
            continue;
        };

        for (zone_name, zone_state) in &player_state.zones {
            let override_key = format!("{zone_name}[{player_name}]");
            let vis = effective_visibility(
                zone_name,
                &override_key,
                definition,
                &full_state.visibility_overrides,
            );
            match vis {
                Some(Visibility::Tier(VisibilityTier::Public)) | None => {}
                Some(Visibility::Tier(VisibilityTier::Hidden)) => {
                    let count = zone_component_count(zone_state);
                    filtered_player
                        .zones
                        .insert(zone_name.clone(), redacted_zone(zone_state, count));
                }
                Some(Visibility::Private { private }) => {
                    let is_owner = private == "owner" && player_name == viewer;
                    if !is_owner {
                        let count = zone_component_count(zone_state);
                        filtered_player
                            .zones
                            .insert(zone_name.clone(), redacted_zone(zone_state, count));
                    }
                }
            }
        }
    }

    filtered
}

/// Count the number of components in a wire zone state.
fn zone_component_count(zone: &ZoneState) -> u32 {
    match zone {
        ZoneState::Grid { cells, .. } => cells.len() as u32,
        ZoneState::OrderedStack { components, .. } => components.len() as u32,
        ZoneState::Set { components, .. } => components.len() as u32,
        ZoneState::SingleSlot { component } => u32::from(component.is_some()),
        ZoneState::Counter { .. } => 0,
        ZoneState::Track { positions } => positions.values().map(|v| v.len() as u32).sum(),
    }
}

/// Return a redacted zone: same type, empty components, but count preserved.
fn redacted_zone(zone: &ZoneState, count: u32) -> ZoneState {
    match zone {
        ZoneState::OrderedStack { .. } => ZoneState::OrderedStack {
            components: Vec::new(),
            count: Some(count),
        },
        ZoneState::Set { .. } => ZoneState::Set {
            components: Vec::new(),
            count: Some(count),
        },
        ZoneState::Grid { .. } => ZoneState::Grid {
            cells: IndexMap::new(),
            cell_properties: None,
        },
        ZoneState::SingleSlot { .. } => ZoneState::SingleSlot { component: None },
        ZoneState::Counter { value } => ZoneState::Counter {
            value: value.clone(),
        },
        ZoneState::Track { .. } => ZoneState::Track {
            positions: IndexMap::new(),
        },
    }
}
