use crate::definition::EndResult;
use crate::runtime::{ComponentId, GameSession, RuntimeZone};
use crate::state::{GameOutcome, GameResult};

/// Check all end conditions against the current game state.
///
/// Must be called BEFORE advance_turn() so "current" refers to
/// the player who just moved.
pub fn check_end_conditions(session: &GameSession) -> Option<GameResult> {
    let current_player = session.current_player()?;

    for ec in &session.definition.end_conditions {
        if !eval_condition(session, &ec.condition, current_player) {
            continue;
        }

        let (outcome, winner) = match ec.result {
            EndResult::Win => {
                let player_ref = ec.player.as_deref().unwrap_or("current");
                let w = if player_ref == "current" {
                    current_player.to_string()
                } else {
                    player_ref.to_string()
                };
                (GameOutcome::Win, Some(w))
            }
            EndResult::Draw => (GameOutcome::Draw, None),
            EndResult::Loss => {
                let opponent = session
                    .runtime
                    .players
                    .keys()
                    .find(|p| p.as_str() != current_player)
                    .cloned();
                (GameOutcome::Win, opponent)
            }
        };

        return Some(GameResult {
            outcome,
            winner,
            condition: ec.name.clone(),
            final_scores: None,
        });
    }

    None
}

/// Evaluate a condition string: resolve library references, try CEL, then legacy dispatch.
fn eval_condition(session: &GameSession, condition: &str, current_player: &str) -> bool {
    // Check if condition matches a library expression
    let resolved = session
        .definition
        .library
        .get(condition)
        .and_then(|entry| match entry {
            crate::definition::LibraryEntry::Expression(expr) => Some(expr.as_str()),
            _ => None,
        })
        .unwrap_or(condition);

    // Try CEL evaluation first
    if let Some(result) = crate::cel::try_eval_end_condition(session, resolved, current_player) {
        return result;
    }
    // Legacy string dispatch for non-CEL condition strings
    let base = resolved.split('(').next().unwrap_or(resolved).trim();
    match base {
        "three_in_line" => check_line_win(session, current_player),
        "all_cells_occupied" | "board_is_full" => check_all_cells_occupied(session, condition),
        _ => false,
    }
}

/// Check if the given player owns a complete row, column, or diagonal
/// on any grid zone.
pub(crate) fn check_line_win(session: &GameSession, player: &str) -> bool {
    for zone in session.runtime.zones.values() {
        if let RuntimeZone::Grid {
            width,
            height,
            cells,
        } = zone
        {
            if has_complete_line(session, cells, *width, *height, player) {
                return true;
            }
        }
    }
    false
}

fn has_complete_line(
    session: &GameSession,
    cells: &[Option<ComponentId>],
    width: u32,
    height: u32,
    player: &str,
) -> bool {
    let w = width as usize;
    let h = height as usize;

    // Check rows
    for row in 0..h {
        if w > 0 && (0..w).all(|col| cell_owned_by(session, cells, row * w + col, player)) {
            return true;
        }
    }

    // Check columns
    for col in 0..w {
        if h > 0 && (0..h).all(|row| cell_owned_by(session, cells, row * w + col, player)) {
            return true;
        }
    }

    // Check diagonals (square grids only)
    if w == h && w > 0 {
        if (0..w).all(|i| cell_owned_by(session, cells, i * w + i, player)) {
            return true;
        }
        if (0..w).all(|i| cell_owned_by(session, cells, i * w + (w - 1 - i), player)) {
            return true;
        }
    }

    false
}

fn cell_owned_by(
    session: &GameSession,
    cells: &[Option<ComponentId>],
    idx: usize,
    player: &str,
) -> bool {
    cells
        .get(idx)
        .and_then(|c| *c)
        .and_then(|cid| session.runtime.components.get(cid))
        .is_some_and(|comp| comp.owner.as_deref() == Some(player))
}

/// Check if all cells in the target grid zone are occupied.
fn check_all_cells_occupied(session: &GameSession, condition: &str) -> bool {
    let zone_name = extract_paren_arg(condition).unwrap_or("board");
    if let Some(RuntimeZone::Grid { cells, .. }) = session.runtime.zones.get(zone_name) {
        return !cells.is_empty() && cells.iter().all(|c| c.is_some());
    }
    false
}

fn extract_paren_arg(s: &str) -> Option<&str> {
    let open = s.find('(')?;
    let close = s.find(')')?;
    if close > open + 1 {
        Some(s[open + 1..close].trim())
    } else {
        None
    }
}
