use crate::action::{Action, ActionType, Position};
use crate::definition::{Adjacency, Component, DirectionName, MovementPrimitive, PrimitiveType};
use crate::runtime::{ComponentId, GameSession, RuntimeZone};

/// Maximum number of legal moves to generate before stopping.
/// Prevents combinatorial explosion on huge boards with many pieces.
const MAX_LEGAL_MOVES: usize = 10_000;

/// A legal move that a player can make.
#[derive(Debug, Clone)]
pub struct LegalMove {
    pub component_id: ComponentId,
    pub action: Action,
}

/// Generate all legal moves for the current player.
pub fn legal_moves(session: &GameSession) -> Vec<LegalMove> {
    let player = match session.current_player() {
        Some(p) => p.to_string(),
        None => return Vec::new(),
    };

    let mut moves = Vec::new();

    // For each component owned by the current player on the board, generate moves
    for (zone_name, zone) in &session.runtime.zones {
        if moves.len() >= MAX_LEGAL_MOVES {
            break;
        }
        let zone_def = match session.definition.zones.get(zone_name) {
            Some(z) => z,
            None => continue,
        };

        match zone {
            RuntimeZone::Grid { storage, .. } => {
                // Track seen components to avoid duplicate processing of multi-cell spans
                let mut seen = std::collections::HashSet::new();
                let occupied = storage.occupied_cells();
                for (col, row, cid) in occupied {
                    if moves.len() >= MAX_LEGAL_MOVES {
                        break;
                    }
                    if col < 0 || row < 0 {
                        continue; // skip negative coords for move generation
                    }
                    if !seen.insert(cid) {
                        continue; // Already processed this spanning component
                    }
                    if let Some(comp_data) = session.runtime.components.get(cid) {
                        if comp_data.owner.as_deref() != Some(&player) {
                            continue;
                        }
                        if let Some(comp_def) =
                            session.definition.components.get(&comp_data.component_type)
                        {
                            generate_grid_moves(
                                session,
                                zone_name,
                                cid,
                                comp_def,
                                col as u32,
                                row as u32,
                                zone_def.adjacency,
                                &mut moves,
                            );
                        }
                    }
                }
            }
            _ => {
                // Non-grid zones: generate placement moves for components in supply
                generate_placement_moves(session, &player, zone_name, zone_def, zone, &mut moves);
            }
        }
    }

    // Also check per-player zones
    if moves.len() < MAX_LEGAL_MOVES {
        if let Some(player_state) = session.runtime.players.get(&player) {
            for (zone_name, zone) in &player_state.zones {
                if moves.len() >= MAX_LEGAL_MOVES {
                    break;
                }
                generate_hand_plays(session, &player, zone_name, zone, &mut moves);
            }
        }
    }

    moves
}

/// Generate moves for a piece on a grid using its movement primitives.
#[allow(clippy::too_many_arguments)]
fn generate_grid_moves(
    session: &GameSession,
    zone_name: &str,
    cid: ComponentId,
    comp_def: &Component,
    col: u32,
    row: u32,
    adjacency: Option<Adjacency>,
    moves: &mut Vec<LegalMove>,
) {
    let zone = match session.runtime.zones.get(zone_name) {
        Some(z) => z,
        None => return,
    };
    let player = session
        .runtime
        .components
        .get(cid)
        .and_then(|c| c.owner.as_deref())
        .unwrap_or("");

    for mp in &comp_def.movement {
        if moves.len() >= MAX_LEGAL_MOVES {
            return;
        }
        match mp.primitive {
            PrimitiveType::Step => {
                let dirs = resolve_directions(mp, player, adjacency);
                let dist = mp.distance.unwrap_or(1);
                for (dx, dy) in &dirs {
                    let nx = col as i32 + dx * dist as i32;
                    let ny = row as i32 + dy * dist as i32;
                    if nx < 0 || ny < 0 || !zone.grid_cell_valid(nx as u32, ny as u32) {
                        continue;
                    }
                    if check_cell_condition(zone, session, nx as u32, ny as u32, mp, player) {
                        moves.push(LegalMove {
                            component_id: cid,
                            action: make_move_action(zone_name, col, row, nx as u32, ny as u32),
                        });
                    }
                }
            }
            PrimitiveType::Slide => {
                let dirs = resolve_directions(mp, player, adjacency);
                for (dx, dy) in &dirs {
                    let mut nx = col as i32 + dx;
                    let mut ny = row as i32 + dy;
                    while nx >= 0 && ny >= 0 && zone.grid_cell_valid(nx as u32, ny as u32)
                        && moves.len() < MAX_LEGAL_MOVES
                    {
                        let target = zone.grid_get(nx as u32, ny as u32);
                        if let Some(tid) = target {
                            if is_enemy(session, tid, player) {
                                moves.push(LegalMove {
                                    component_id: cid,
                                    action: make_move_action(
                                        zone_name, col, row, nx as u32, ny as u32,
                                    ),
                                });
                            }
                            break;
                        }
                        moves.push(LegalMove {
                            component_id: cid,
                            action: make_move_action(zone_name, col, row, nx as u32, ny as u32),
                        });
                        nx += dx;
                        ny += dy;
                    }
                }
            }
            PrimitiveType::Leap => {
                if let (Some(dx), Some(dy)) = (mp.dx, mp.dy) {
                    for (sx, sy) in &[(1, 1), (1, -1), (-1, 1), (-1, -1)] {
                        for (ldx, ldy) in &[(dx, dy), (dy, dx)] {
                            let nx = col as i32 + ldx * sx;
                            let ny = row as i32 + ldy * sy;
                            if nx < 0 || ny < 0 || !zone.grid_cell_valid(nx as u32, ny as u32) {
                                continue;
                            }
                            let target = zone.grid_get(nx as u32, ny as u32);
                            match target {
                                None => {
                                    moves.push(LegalMove {
                                        component_id: cid,
                                        action: make_move_action(
                                            zone_name, col, row, nx as u32, ny as u32,
                                        ),
                                    });
                                }
                                Some(tid) if is_enemy(session, tid, player) => {
                                    moves.push(LegalMove {
                                        component_id: cid,
                                        action: make_move_action(
                                            zone_name, col, row, nx as u32, ny as u32,
                                        ),
                                    });
                                }
                                _ => {}
                            }
                        }
                    }
                }
            }
            PrimitiveType::Hop => {
                let dirs = resolve_directions(mp, player, adjacency);
                for (dx, dy) in &dirs {
                    let mid_x = col as i32 + dx;
                    let mid_y = row as i32 + dy;
                    let land_x = col as i32 + dx * 2;
                    let land_y = row as i32 + dy * 2;
                    if mid_x < 0
                        || mid_y < 0
                        || land_x < 0
                        || land_y < 0
                        || !zone.grid_cell_valid(mid_x as u32, mid_y as u32)
                        || !zone.grid_cell_valid(land_x as u32, land_y as u32)
                    {
                        continue;
                    }
                    // Middle cell must be occupied
                    if zone.grid_get(mid_x as u32, mid_y as u32).is_none() {
                        continue;
                    }
                    // Landing cell must be empty
                    if zone.grid_get(land_x as u32, land_y as u32).is_none() {
                        moves.push(LegalMove {
                            component_id: cid,
                            action: make_move_action(
                                zone_name, col, row, land_x as u32, land_y as u32,
                            ),
                        });
                    }
                }
            }
            PrimitiveType::Place => {
                // Placement from supply onto empty cells — handled elsewhere
            }
            PrimitiveType::Flip => {
                let comp_name = session
                    .runtime
                    .components
                    .get(cid)
                    .map(|c| c.string_id.clone())
                    .unwrap_or_default();
                moves.push(LegalMove {
                    component_id: cid,
                    action: Action {
                        action_type: ActionType::Flip,
                        component_id: Some(comp_name),
                        ..default_action()
                    },
                });
            }
            PrimitiveType::Remove => {
                let comp_name = session
                    .runtime
                    .components
                    .get(cid)
                    .map(|c| c.string_id.clone())
                    .unwrap_or_default();
                moves.push(LegalMove {
                    component_id: cid,
                    action: Action {
                        action_type: ActionType::Remove,
                        component_id: Some(comp_name),
                        ..default_action()
                    },
                });
            }
            PrimitiveType::Swap => {
                let dirs = resolve_directions(mp, player, adjacency);
                let dist = mp.distance.unwrap_or(1);
                for (dx, dy) in &dirs {
                    let nx = col as i32 + dx * dist as i32;
                    let ny = row as i32 + dy * dist as i32;
                    if nx < 0 || ny < 0 || !zone.grid_cell_valid(nx as u32, ny as u32) {
                        continue;
                    }
                    if let Some(target_id) = zone.grid_get(nx as u32, ny as u32) {
                        let comp_name = session
                            .runtime
                            .components
                            .get(cid)
                            .map(|c| c.string_id.clone())
                            .unwrap_or_default();
                        let target_name = session
                            .runtime
                            .components
                            .get(target_id)
                            .map(|c| c.string_id.clone())
                            .unwrap_or_default();
                        moves.push(LegalMove {
                            component_id: cid,
                            action: Action {
                                action_type: ActionType::Swap,
                                component_id: Some(comp_name),
                                swap_with: Some(target_name),
                                ..default_action()
                            },
                        });
                    }
                }
            }
            _ => {
                // Remaining primitives (draw, move_to, castle, promote)
                // require cross-zone or multi-piece coordination
            }
        }
    }
}

/// Generate placement moves (e.g. Go stone placement, tic-tac-toe marks).
fn generate_placement_moves(
    _session: &GameSession,
    _player: &str,
    _zone_name: &str,
    _zone_def: &crate::definition::Zone,
    _zone: &RuntimeZone,
    _moves: &mut Vec<LegalMove>,
) {
    // Placement from supply is game-specific; will be expanded
}

/// Generate moves for playing from a hand zone.
fn generate_hand_plays(
    _session: &GameSession,
    _player: &str,
    _zone_name: &str,
    _zone: &RuntimeZone,
    _moves: &mut Vec<LegalMove>,
) {
    // Hand plays are game-specific; will be expanded
}

// --- Helpers ---

/// Resolve direction names to (dx, dy) vectors, respecting zone adjacency.
fn resolve_directions(
    mp: &MovementPrimitive,
    _player: &str,
    adjacency: Option<Adjacency>,
) -> Vec<(i32, i32)> {
    use crate::definition::Direction;

    let dir = match &mp.direction {
        Some(d) => d,
        None => return adjacent_directions(adjacency),
    };

    match dir {
        Direction::Single(name) => direction_vectors(name, adjacency),
        Direction::Multiple(names) => {
            names.iter().flat_map(|n| direction_vectors(n, adjacency)).collect()
        }
        Direction::Custom(_) => adjacent_directions(adjacency),
    }
}

fn direction_vectors(name: &DirectionName, adjacency: Option<Adjacency>) -> Vec<(i32, i32)> {
    match name {
        DirectionName::Orthogonal => vec![(1, 0), (-1, 0), (0, 1), (0, -1)],
        DirectionName::Diagonal => {
            if adjacency == Some(Adjacency::Hex6) {
                // Hex grids have no separate diagonal; return the non-orthogonal hex neighbors
                vec![(-1, 1), (1, -1)]
            } else {
                vec![(1, 1), (1, -1), (-1, 1), (-1, -1)]
            }
        }
        DirectionName::Adjacent => adjacent_directions(adjacency),
        DirectionName::Forward => vec![(0, 1)],
        DirectionName::ForwardDiagonal => vec![(1, 1), (-1, 1)],
        DirectionName::Backward => vec![(0, -1)],
        DirectionName::BackwardDiagonal => vec![(1, -1), (-1, -1)],
    }
}

fn hex_directions() -> Vec<(i32, i32)> {
    vec![(-1, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, -1)]
}

fn adjacent_directions(adjacency: Option<Adjacency>) -> Vec<(i32, i32)> {
    match adjacency {
        Some(Adjacency::Hex6) => hex_directions(),
        Some(Adjacency::Orthogonal4) => vec![(1, 0), (-1, 0), (0, 1), (0, -1)],
        _ => {
            vec![
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
                (1, 1),
                (1, -1),
                (-1, 1),
                (-1, -1),
            ]
        }
    }
}

fn is_enemy(session: &GameSession, target_id: ComponentId, player: &str) -> bool {
    session
        .runtime
        .components
        .get(target_id)
        .and_then(|c| c.owner.as_deref())
        .is_some_and(|owner| owner != player)
}

fn check_cell_condition(
    zone: &RuntimeZone,
    session: &GameSession,
    col: u32,
    row: u32,
    mp: &MovementPrimitive,
    player: &str,
) -> bool {
    let occupant = zone.grid_get(col, row);
    let condition = mp.condition.as_deref().unwrap_or("empty_or_enemy");

    match condition {
        "empty" => occupant.is_none(),
        "enemy" => occupant.is_some_and(|id| is_enemy(session, id, player)),
        "empty_or_enemy" => {
            occupant.is_none()
                || occupant.is_some_and(|id| is_enemy(session, id, player))
        }
        other => {
            let cell_empty = occupant.is_none();
            let cell_enemy = occupant.is_some_and(|id| is_enemy(session, id, player));
            // Try CEL evaluation for complex conditions
            if let Some(result) = crate::cel::try_eval_move_condition(cell_empty, cell_enemy, other)
            {
                return result;
            }
            // Legacy fallback: allow if empty or enemy
            cell_empty || cell_enemy
        }
    }
}

fn default_action() -> Action {
    Action {
        action_type: ActionType::Pass, // overridden by caller
        authority: None,
        component_id: None,
        component_type: None,
        from: None,
        to: None,
        zone: None,
        count: None,
        promote_to: None,
        orientation: None,
        rotation: None,
        amount: None,
        side: None,
        dice_count: None,
        dice_type: None,
        swap_with: None,
        declaration: None,
        commitment: None,
        custom_data: None,
    }
}

fn make_move_action(zone: &str, from_col: u32, from_row: u32, to_col: u32, to_row: u32) -> Action {
    Action {
        action_type: ActionType::MovePiece,
        authority: None,
        component_id: None,
        component_type: None,
        from: Some(Position::Structured {
            zone: Some(zone.to_string()),
            cell: Some(format!("{},{}", from_col, from_row)),
            index: None,
        }),
        to: Some(Position::Structured {
            zone: Some(zone.to_string()),
            cell: Some(format!("{},{}", to_col, to_row)),
            index: None,
        }),
        zone: None,
        count: None,
        promote_to: None,
        orientation: None,
        rotation: None,
        amount: None,
        side: None,
        dice_count: None,
        dice_type: None,
        swap_with: None,
        declaration: None,
        commitment: None,
        custom_data: None,
    }
}
