use wasmtime::{Caller, Linker};

use baize_engine::extension::ExtensionError;
use baize_engine::state::{CellContents, ComponentInstance, GameState, GameStatus, ZoneState};

pub struct HostState {
    pub zones: Vec<ZoneHandle>,
    pub components: Vec<CompHandle>,
    pub players: Vec<PlayerHandle>,
    pub zone_names: Vec<String>,
    pub current_player_idx: i32,
    pub turn_number: i32,
    pub phase_name: String,
    pub is_finished: bool,
    pub counters: Vec<(String, i64)>,
}

pub struct ZoneHandle {
    pub name: String,
    pub zone_type: i32, // 0=grid, 1=stack, 2=set, 3=slot, 4=counter
    pub width: i32,
    pub height: i32,
    pub cell_count: i32,
    pub comp_count: i32,
    pub counter_val: i64,
    pub cells: Vec<i32>,       // flat grid cells: component handle or -1
    pub comp_indices: Vec<i32>, // indices into components array
    pub cell_properties: Vec<((i32, i32), Vec<(String, String)>)>,
}

pub struct CompHandle {
    pub type_name: String,
    pub owner: i32, // player handle or -1
    pub rank: i64,
    pub suit: String,
    pub string_id: String,
    pub properties: Vec<(String, String)>,
}

pub struct PlayerHandle {
    pub name: String,
}

impl HostState {
    pub fn from_game_state(state: &GameState) -> Self {
        let mut host = HostState {
            zones: Vec::new(),
            components: Vec::new(),
            players: Vec::new(),
            zone_names: Vec::new(),
            current_player_idx: -1,
            turn_number: state.move_count.unwrap_or(0) as i32,
            phase_name: state.phase.clone(),
            is_finished: state.status == GameStatus::Finished,
            counters: Vec::new(),
        };

        // Build player handles
        for (name, _) in &state.players {
            host.players.push(PlayerHandle { name: name.clone() });
        }

        // Set current player
        for (i, p) in host.players.iter().enumerate() {
            if p.name == state.turn {
                host.current_player_idx = i as i32;
                break;
            }
        }

        // Build counters
        for (name, val) in &state.counters {
            let v = val.as_i64().unwrap_or_else(|| val.as_f64().map(|f| f as i64).unwrap_or(0));
            host.counters.push((name.clone(), v));
        }

        // Build zones and components
        for (zone_name, zone_state) in &state.zones {
            host.zone_names.push(zone_name.clone());
            let zone_handle =
                Self::build_zone_handle(zone_name, zone_state, &mut host.components, &host.players);
            host.zones.push(zone_handle);
        }

        // Also process per-player zones
        for (player_name, player_state) in &state.players {
            for (zone_name, zone_state) in &player_state.zones {
                let full_name = format!("{player_name}:{zone_name}");
                host.zone_names.push(full_name.clone());
                let zone_handle = Self::build_zone_handle(
                    &full_name,
                    zone_state,
                    &mut host.components,
                    &host.players,
                );
                host.zones.push(zone_handle);
            }
        }

        host
    }

    fn build_zone_handle(
        name: &str,
        zone_state: &ZoneState,
        components: &mut Vec<CompHandle>,
        players: &[PlayerHandle],
    ) -> ZoneHandle {
        match zone_state {
            ZoneState::Grid { cells, cell_properties, .. } => {
                let mut zone_cells = Vec::new();
                let mut zone_comps = Vec::new();
                let mut max_col = 0i32;
                let mut max_row = 0i32;

                for (key, cell) in cells {
                    // Parse cell key (e.g., "0,0")
                    let parts: Vec<&str> = key.split(',').collect();
                    if parts.len() == 2 {
                        if let (Ok(c), Ok(r)) = (parts[0].parse::<i32>(), parts[1].parse::<i32>())
                        {
                            max_col = max_col.max(c + 1);
                            max_row = max_row.max(r + 1);
                        }
                    }

                    let cell_comps = cell_to_components(cell);
                    if let Some(comp) = cell_comps.first() {
                        let comp_idx = components.len() as i32;
                        push_component(components, comp, players);
                        zone_comps.push(comp_idx);
                        zone_cells.push(comp_idx);
                        // Push additional components from multi-occupancy cells
                        for extra in cell_comps.iter().skip(1) {
                            let idx = components.len() as i32;
                            push_component(components, extra, players);
                            zone_comps.push(idx);
                        }
                    } else {
                        zone_cells.push(-1);
                    }
                }

                // Extract cell properties
                let mut cell_props = Vec::new();
                if let Some(cp) = cell_properties {
                    for (coord_key, props) in cp {
                        let parts: Vec<&str> = coord_key.split(',').collect();
                        if parts.len() == 2 {
                            if let (Ok(c), Ok(r)) = (parts[0].parse::<i32>(), parts[1].parse::<i32>()) {
                                let kvs: Vec<(String, String)> = props
                                    .iter()
                                    .map(|(k, v)| {
                                        let s = match v {
                                            serde_json::Value::String(s) => s.clone(),
                                            other => other.to_string(),
                                        };
                                        (k.clone(), s)
                                    })
                                    .collect();
                                cell_props.push(((c, r), kvs));
                            }
                        }
                    }
                }

                ZoneHandle {
                    name: name.to_string(),
                    zone_type: 0,
                    width: max_col,
                    height: max_row,
                    cell_count: zone_cells.len() as i32,
                    comp_count: zone_comps.len() as i32,
                    counter_val: 0,
                    cells: zone_cells,
                    comp_indices: zone_comps,
                    cell_properties: cell_props,
                }
            }
            ZoneState::OrderedStack { components: comps, .. }
            | ZoneState::Set { components: comps, .. } => {
                let mut zone_comps = Vec::new();
                for comp in comps {
                    let comp_idx = components.len() as i32;
                    push_component(components, comp, players);
                    zone_comps.push(comp_idx);
                }

                let is_set = matches!(zone_state, ZoneState::Set { .. });
                ZoneHandle {
                    name: name.to_string(),
                    zone_type: if is_set { 2 } else { 1 },
                    width: 0,
                    height: 0,
                    cell_count: 0,
                    comp_count: zone_comps.len() as i32,
                    counter_val: 0,
                    cells: Vec::new(),
                    comp_indices: zone_comps,
                    cell_properties: Vec::new(),
                }
            }
            ZoneState::Counter { value, .. } => {
                let v = value
                    .as_i64()
                    .unwrap_or_else(|| value.as_f64().map(|f| f as i64).unwrap_or(0));
                ZoneHandle {
                    name: name.to_string(),
                    zone_type: 4,
                    width: 0,
                    height: 0,
                    cell_count: 0,
                    comp_count: 0,
                    counter_val: v,
                    cells: Vec::new(),
                    comp_indices: Vec::new(),
                    cell_properties: Vec::new(),
                }
            }
            _ => ZoneHandle {
                name: name.to_string(),
                zone_type: -1,
                width: 0,
                height: 0,
                cell_count: 0,
                comp_count: 0,
                counter_val: 0,
                cells: Vec::new(),
                comp_indices: Vec::new(),
                cell_properties: Vec::new(),
            },
        }
    }
}

fn cell_to_components(cell: &CellContents) -> Vec<&ComponentInstance> {
    match cell {
        CellContents::Single(c) => vec![c],
        CellContents::Multiple(cs) => cs.iter().collect(),
        CellContents::Empty => vec![],
    }
}

fn push_component(
    components: &mut Vec<CompHandle>,
    comp: &ComponentInstance,
    players: &[PlayerHandle],
) {
    let owner_idx = comp
        .owner
        .as_ref()
        .map(|o| {
            players
                .iter()
                .position(|p| p.name == *o)
                .map(|i| i as i32)
                .unwrap_or(-1)
        })
        .unwrap_or(-1);

    let rank = comp
        .properties
        .as_ref()
        .and_then(|p| p.get("rank"))
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    let suit = comp
        .properties
        .as_ref()
        .and_then(|p| p.get("suit"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let properties = comp
        .properties
        .as_ref()
        .map(|p| p.iter().map(|(k, v)| (k.clone(), v.to_string())).collect())
        .unwrap_or_default();

    components.push(CompHandle {
        type_name: comp.component_type.clone(),
        owner: owner_idx,
        rank,
        suit,
        string_id: comp.id.clone(),
        properties,
    });
}

pub fn register_felt_imports(linker: &mut Linker<HostState>) -> Result<(), ExtensionError> {
    // Zone access
    linker
        .func_wrap(
            "baize",
            "zone_count",
            |caller: Caller<'_, HostState>, _state: i32| -> i32 {
                caller.data().zones.len() as i32
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_by_index",
            |caller: Caller<'_, HostState>, _state: i32, idx: i32| -> i32 {
                if idx >= 0 && (idx as usize) < caller.data().zones.len() {
                    idx
                } else {
                    -1
                }
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_by_name",
            |mut caller: Caller<'_, HostState>,
             _state: i32,
             name_ptr: i32,
             name_len: i32|
             -> i32 {
                let name = read_string_from_memory(&mut caller, name_ptr, name_len);
                match name {
                    Some(n) => caller
                        .data()
                        .zones
                        .iter()
                        .position(|z| z.name == n)
                        .map(|i| i as i32)
                        .unwrap_or(-1),
                    None => -1,
                }
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_for_player",
            |mut caller: Caller<'_, HostState>,
             _state: i32,
             name_ptr: i32,
             name_len: i32,
             player: i32|
             -> i32 {
                let zone_name = read_string_from_memory(&mut caller, name_ptr, name_len);
                let player_name = caller
                    .data()
                    .players
                    .get(player as usize)
                    .map(|p| p.name.clone());
                match (zone_name, player_name) {
                    (Some(zn), Some(pn)) => {
                        let full = format!("{pn}:{zn}");
                        caller
                            .data()
                            .zones
                            .iter()
                            .position(|z| z.name == full)
                            .map(|i| i as i32)
                            .unwrap_or(-1)
                    }
                    _ => -1,
                }
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_type",
            |caller: Caller<'_, HostState>, zone: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.zone_type)
                    .unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_width",
            |caller: Caller<'_, HostState>, zone: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.width)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_height",
            |caller: Caller<'_, HostState>, zone: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.height)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_cell_count",
            |caller: Caller<'_, HostState>, zone: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.cell_count)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_comp_count",
            |caller: Caller<'_, HostState>, zone: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.comp_count)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "zone_counter_val",
            |caller: Caller<'_, HostState>, zone: i32| -> i64 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .map(|z| z.counter_val)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    // Cell access
    linker
        .func_wrap(
            "baize",
            "cell_by_index",
            |caller: Caller<'_, HostState>, zone: i32, idx: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .and_then(|z| z.cells.get(idx as usize))
                    .copied()
                    .unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "cell_at",
            |caller: Caller<'_, HostState>, zone: i32, col: i32, row: i32| -> i32 {
                let z = match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 && z.width > 0 => z,
                    _ => return -1,
                };
                let idx = (row * z.width + col) as usize;
                z.cells.get(idx).copied().unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "cell_col",
            |_caller: Caller<'_, HostState>, cell: i32| -> i32 {
                // Cell handle = flat index. col = cell % width.
                // Without zone context, we use a placeholder.
                cell % 8
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "cell_row",
            |_caller: Caller<'_, HostState>, cell: i32| -> i32 { cell / 8 },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "cell_occupant",
            |_caller: Caller<'_, HostState>, cell: i32| -> i32 {
                // cell handle IS the component handle for occupied cells
                if cell >= 0 { cell } else { -1 }
            },
        )
        .map_err(wrap_err)?;

    // Component access
    linker
        .func_wrap(
            "baize",
            "comp_by_index",
            |caller: Caller<'_, HostState>, zone: i32, idx: i32| -> i32 {
                caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .and_then(|z| z.comp_indices.get(idx as usize))
                    .copied()
                    .unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_type",
            |mut caller: Caller<'_, HostState>, comp: i32, buf: i32| -> i32 {
                let s = caller
                    .data()
                    .components
                    .get(comp as usize)
                    .map(|c| c.type_name.clone())
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &s)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_owner",
            |caller: Caller<'_, HostState>, comp: i32| -> i32 {
                caller
                    .data()
                    .components
                    .get(comp as usize)
                    .map(|c| c.owner)
                    .unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_rank",
            |caller: Caller<'_, HostState>, comp: i32| -> i64 {
                caller
                    .data()
                    .components
                    .get(comp as usize)
                    .map(|c| c.rank)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_suit",
            |mut caller: Caller<'_, HostState>, comp: i32, buf: i32| -> i32 {
                let s = caller
                    .data()
                    .components
                    .get(comp as usize)
                    .map(|c| c.suit.clone())
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &s)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_id",
            |mut caller: Caller<'_, HostState>, comp: i32, buf: i32| -> i32 {
                let s = caller
                    .data()
                    .components
                    .get(comp as usize)
                    .map(|c| c.string_id.clone())
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &s)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "comp_property",
            |mut caller: Caller<'_, HostState>,
             comp: i32,
             key_ptr: i32,
             key_len: i32,
             buf: i32|
             -> i32 {
                let key =
                    read_string_from_memory(&mut caller, key_ptr, key_len).unwrap_or_default();
                let val = caller
                    .data()
                    .components
                    .get(comp as usize)
                    .and_then(|c| c.properties.iter().find(|(k, _)| k == &key).map(|(_, v)| v.clone()))
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &val)
            },
        )
        .map_err(wrap_err)?;

    // Player access
    linker
        .func_wrap(
            "baize",
            "player_count",
            |caller: Caller<'_, HostState>, _state: i32| -> i32 {
                caller.data().players.len() as i32
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "player_by_index",
            |caller: Caller<'_, HostState>, _state: i32, idx: i32| -> i32 {
                if idx >= 0 && (idx as usize) < caller.data().players.len() {
                    idx
                } else {
                    -1
                }
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "player_name",
            |mut caller: Caller<'_, HostState>, player: i32, buf: i32| -> i32 {
                let s = caller
                    .data()
                    .players
                    .get(player as usize)
                    .map(|p| p.name.clone())
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &s)
            },
        )
        .map_err(wrap_err)?;

    // Game state
    linker
        .func_wrap(
            "baize",
            "current_player",
            |caller: Caller<'_, HostState>, _state: i32| -> i32 {
                caller.data().current_player_idx
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "turn_number",
            |caller: Caller<'_, HostState>, _state: i32| -> i32 {
                caller.data().turn_number
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "phase_name",
            |mut caller: Caller<'_, HostState>, _state: i32, buf: i32| -> i32 {
                let s = caller.data().phase_name.clone();
                write_string_to_memory(&mut caller, buf, &s)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "is_finished",
            |caller: Caller<'_, HostState>, _state: i32| -> i32 {
                if caller.data().is_finished { 1 } else { 0 }
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "counter_value",
            |mut caller: Caller<'_, HostState>,
             _state: i32,
             name_ptr: i32,
             name_len: i32|
             -> i64 {
                let name =
                    read_string_from_memory(&mut caller, name_ptr, name_len).unwrap_or_default();
                caller
                    .data()
                    .counters
                    .iter()
                    .find(|(k, _)| k == &name)
                    .map(|(_, v)| *v)
                    .unwrap_or(0)
            },
        )
        .map_err(wrap_err)?;

    // Grid adjacency
    linker
        .func_wrap(
            "baize",
            "adjacent_count",
            |caller: Caller<'_, HostState>, zone: i32, cell: i32| -> i32 {
                let z = match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 => z,
                    _ => return 0,
                };
                let col = cell % z.width;
                let row = cell / z.width;
                let mut count = 0;
                if col > 0 {
                    count += 1;
                }
                if col < z.width - 1 {
                    count += 1;
                }
                if row > 0 {
                    count += 1;
                }
                if row < z.height - 1 {
                    count += 1;
                }
                count
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "adjacent_at",
            |caller: Caller<'_, HostState>, zone: i32, cell: i32, idx: i32| -> i32 {
                let z = match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 => z,
                    _ => return -1,
                };
                let col = cell % z.width;
                let row = cell / z.width;
                let mut neighbors = Vec::new();
                if col > 0 {
                    neighbors.push(row * z.width + (col - 1));
                }
                if col < z.width - 1 {
                    neighbors.push(row * z.width + (col + 1));
                }
                if row > 0 {
                    neighbors.push((row - 1) * z.width + col);
                }
                if row < z.height - 1 {
                    neighbors.push((row + 1) * z.width + col);
                }
                neighbors.get(idx as usize).copied().unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "diagonal_count",
            |caller: Caller<'_, HostState>, zone: i32, cell: i32| -> i32 {
                let z = match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 => z,
                    _ => return 0,
                };
                let col = cell % z.width;
                let row = cell / z.width;
                let mut count = 0;
                if col > 0 && row > 0 {
                    count += 1;
                }
                if col < z.width - 1 && row > 0 {
                    count += 1;
                }
                if col > 0 && row < z.height - 1 {
                    count += 1;
                }
                if col < z.width - 1 && row < z.height - 1 {
                    count += 1;
                }
                count
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "diagonal_at",
            |caller: Caller<'_, HostState>, zone: i32, cell: i32, idx: i32| -> i32 {
                let z = match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 => z,
                    _ => return -1,
                };
                let col = cell % z.width;
                let row = cell / z.width;
                let mut diags = Vec::new();
                if col > 0 && row > 0 {
                    diags.push((row - 1) * z.width + (col - 1));
                }
                if col < z.width - 1 && row > 0 {
                    diags.push((row - 1) * z.width + (col + 1));
                }
                if col > 0 && row < z.height - 1 {
                    diags.push((row + 1) * z.width + (col - 1));
                }
                if col < z.width - 1 && row < z.height - 1 {
                    diags.push((row + 1) * z.width + (col + 1));
                }
                diags.get(idx as usize).copied().unwrap_or(-1)
            },
        )
        .map_err(wrap_err)?;

    linker
        .func_wrap(
            "baize",
            "in_bounds",
            |caller: Caller<'_, HostState>, zone: i32, col: i32, row: i32| -> i32 {
                match caller.data().zones.get(zone as usize) {
                    Some(z) if z.zone_type == 0 => {
                        if col >= 0 && col < z.width && row >= 0 && row < z.height {
                            1
                        } else {
                            0
                        }
                    }
                    _ => 0,
                }
            },
        )
        .map_err(wrap_err)?;

    // Cell properties
    linker
        .func_wrap(
            "baize",
            "cell_property",
            |mut caller: Caller<'_, HostState>,
             zone: i32,
             col: i32,
             row: i32,
             key_ptr: i32,
             key_len: i32,
             buf: i32|
             -> i32 {
                let key = match read_string_from_memory(&mut caller, key_ptr, key_len) {
                    Some(k) => k,
                    None => return 0,
                };
                let value = caller
                    .data()
                    .zones
                    .get(zone as usize)
                    .and_then(|z| {
                        z.cell_properties
                            .iter()
                            .find(|((c, r), _)| *c == col && *r == row)
                            .and_then(|(_, props)| {
                                props.iter().find(|(k, _)| k == &key).map(|(_, v)| v.clone())
                            })
                    })
                    .unwrap_or_default();
                write_string_to_memory(&mut caller, buf, &value)
            },
        )
        .map_err(wrap_err)?;

    Ok(())
}

fn read_string_from_memory(
    caller: &mut Caller<'_, HostState>,
    ptr: i32,
    len: i32,
) -> Option<String> {
    let memory = caller.get_export("memory")?.into_memory()?;
    let data = memory.data(&caller);
    let start = ptr as usize;
    let end = start + len as usize;
    if end > data.len() {
        return None;
    }
    String::from_utf8(data[start..end].to_vec()).ok()
}

fn write_string_to_memory(caller: &mut Caller<'_, HostState>, buf: i32, s: &str) -> i32 {
    let bytes = s.as_bytes();
    let len = bytes.len();
    if let Some(memory) = caller.get_export("memory").and_then(|e| e.into_memory()) {
        let data = memory.data_mut(caller);
        let start = buf as usize;
        if start + len <= data.len() {
            data[start..start + len].copy_from_slice(bytes);
        }
    }
    len as i32
}

fn wrap_err(e: impl std::fmt::Display) -> ExtensionError {
    ExtensionError::ComputationFailed(format!("failed to register host import: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasmtime::Engine;

    #[test]
    fn test_register_imports() {
        let engine = Engine::default();
        let mut linker = Linker::new(&engine);
        register_felt_imports(&mut linker).expect("failed to register imports");
    }
}
