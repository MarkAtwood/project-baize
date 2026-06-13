use indexmap::IndexMap;

use crate::definition::{GameDefinition, Visibility, VisibilityTier};
use crate::runtime::{FogState, RuntimeZone};
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
    filter_for_viewer_with_fog(full_state, viewer, definition, None)
}

/// Like `filter_for_viewer`, but with optional runtime zone data for fog of war.
///
/// When `runtime_zones` is provided, fog-enabled zones have cell-level filtering:
/// - Unexplored cells: components hidden, cell_properties hidden
/// - Visible cells: full visibility
/// - Fogged cells: components hidden, cell_properties visible if remember_terrain
pub fn filter_for_viewer_with_fog(
    full_state: &GameState,
    viewer: &str,
    definition: &GameDefinition,
    runtime_zones: Option<&IndexMap<String, RuntimeZone>>,
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
            Some(Visibility::Tier(VisibilityTier::Public)) | None => {
                // Apply fog-of-war cell-level filtering if configured
                if let Some(rt_zones) = runtime_zones {
                    if let Some(rt_zone) = rt_zones.get(zone_name) {
                        if rt_zone.fog_config().is_some() {
                            let fog_filtered = apply_fog_filter(zone_state, rt_zone, viewer);
                            filtered.zones.insert(zone_name.clone(), fog_filtered);
                        }
                    }
                }
            }
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

/// Apply fog-of-war filtering to a grid zone for a specific viewer.
///
/// Returns a new ZoneState::Grid with:
/// - Unexplored cells: components removed, cell_properties removed
/// - Visible cells: everything kept
/// - Fogged cells: components removed, cell_properties kept if remember_terrain
/// - cell_fog populated with the viewer's fog data
fn apply_fog_filter(
    zone_state: &ZoneState,
    rt_zone: &RuntimeZone,
    viewer: &str,
) -> ZoneState {
    let ZoneState::Grid { cells, cell_properties, .. } = zone_state else {
        return zone_state.clone();
    };

    let remember_terrain = rt_zone
        .fog_config()
        .map(|c| c.remember_terrain)
        .unwrap_or(true);

    let mut filtered_cells = IndexMap::new();
    let mut filtered_props: Option<IndexMap<String, IndexMap<String, serde_json::Value>>> = None;
    let mut wire_fog = IndexMap::new();

    // Process each cell in the wire format
    // Collect all cell coordinates from both cells and cell_properties
    let mut all_coords: IndexMap<String, (i32, i32)> = IndexMap::new();
    for coord_str in cells.keys() {
        if let Some(parsed) = parse_coord(coord_str) {
            all_coords.insert(coord_str.clone(), parsed);
        }
    }
    if let Some(props) = cell_properties {
        for coord_str in props.keys() {
            if let Some(parsed) = parse_coord(coord_str) {
                all_coords.entry(coord_str.clone()).or_insert(parsed);
            }
        }
    }

    // Also include all fog entries for this viewer to populate wire_fog
    if let Some(fog_map) = rt_zone.cell_fog() {
        for (&(col, row), player_fog) in fog_map {
            if let Some(state) = player_fog.get(viewer) {
                let coord_str = format!("{},{}", col, row);
                let state_str = match state {
                    FogState::Unexplored => "unexplored",
                    FogState::Visible => "visible",
                    FogState::Fogged => "fogged",
                };
                wire_fog.insert(coord_str.clone(), state_str.to_string());
                all_coords.entry(coord_str).or_insert((col, row));
            }
        }
    }

    for (coord_str, (col, row)) in &all_coords {
        let fog_state = rt_zone.cell_fog_state(*col, *row, viewer);

        match fog_state {
            FogState::Visible => {
                // Keep everything
                if let Some(cell) = cells.get(coord_str) {
                    filtered_cells.insert(coord_str.clone(), cell.clone());
                }
                if let Some(props) = cell_properties {
                    if let Some(prop) = props.get(coord_str) {
                        filtered_props
                            .get_or_insert_with(IndexMap::new)
                            .insert(coord_str.clone(), prop.clone());
                    }
                }
            }
            FogState::Fogged => {
                // Remove components, keep terrain if remember_terrain
                if remember_terrain {
                    if let Some(props) = cell_properties {
                        if let Some(prop) = props.get(coord_str) {
                            filtered_props
                                .get_or_insert_with(IndexMap::new)
                                .insert(coord_str.clone(), prop.clone());
                        }
                    }
                }
                // Components are not included (hidden in fog)
            }
            FogState::Unexplored => {
                // Remove everything — components and cell_properties hidden
            }
        }

        // Add fog state to wire format
        let state_str = match fog_state {
            FogState::Unexplored => "unexplored",
            FogState::Visible => "visible",
            FogState::Fogged => "fogged",
        };
        wire_fog.insert(coord_str.clone(), state_str.to_string());
    }

    // Also include fog entries for cells that weren't in cells/cell_properties
    // (already handled above via the fog_map loop)

    ZoneState::Grid {
        cells: filtered_cells,
        cell_properties: filtered_props,
        cell_fog: if wire_fog.is_empty() { None } else { Some(wire_fog) },
    }
}

/// Parse "col,row" coordinate string into (col, row) integers.
fn parse_coord(s: &str) -> Option<(i32, i32)> {
    let parts: Vec<&str> = s.split(',').collect();
    if parts.len() == 2 {
        let col = parts[0].trim().parse::<i32>().ok()?;
        let row = parts[1].trim().parse::<i32>().ok()?;
        Some((col, row))
    } else {
        None
    }
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
            cell_fog: None,
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
