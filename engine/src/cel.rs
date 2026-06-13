use std::sync::Arc;

use cel_interpreter::{Context, Program, Value};
use crate::runtime::{GameSession, RuntimeZone};

/// Maximum CEL expression length (bytes). Prevents ReDoS-style attacks
/// on the CEL compiler.
const MAX_CEL_LENGTH: usize = 4096;

/// Maximum grid cells before skipping CEL grid context population.
const MAX_CEL_GRID_CELLS: usize = 10_000;

/// Maximum nesting depth (parentheses) allowed in CEL expressions.
/// Prevents stack overflow from deeply nested expressions.
const MAX_CEL_NESTING: usize = 32;

/// Check that a CEL expression does not exceed nesting limits.
/// Returns false if the expression is too deeply nested.
fn check_cel_nesting(expr: &str) -> bool {
    let mut depth: usize = 0;
    for ch in expr.chars() {
        if ch == '(' {
            depth += 1;
            if depth > MAX_CEL_NESTING {
                return false;
            }
        } else if ch == ')' {
            depth = depth.saturating_sub(1);
        }
    }
    true
}

/// Try to evaluate a condition string as a CEL expression for end-condition checking.
///
/// Returns `Some(result)` if the string is valid CEL and evaluates successfully.
/// Returns `None` if the expression fails to parse, allowing the caller to fall
/// back to legacy string dispatch.
pub fn try_eval_end_condition(
    session: &GameSession,
    condition: &str,
    current_player: &str,
) -> Option<bool> {
    if condition.len() > MAX_CEL_LENGTH || !check_cel_nesting(condition) {
        return None;
    }
    let program = Program::compile(condition).ok()?;
    let ctx = build_end_condition_context(session, current_player);
    match program.execute(&ctx) {
        Ok(Value::Bool(b)) => Some(b),
        Ok(_) => Some(false),
        Err(_) => None,
    }
}

/// Try to evaluate a movement condition as a CEL expression.
///
/// Cell occupancy state is injected as boolean variables (`empty`, `enemy`).
/// Returns `None` if the expression fails to parse.
pub fn try_eval_move_condition(
    is_empty: bool,
    is_enemy: bool,
    condition: &str,
) -> Option<bool> {
    if condition.len() > MAX_CEL_LENGTH || !check_cel_nesting(condition) {
        return None;
    }
    let program = Program::compile(condition).ok()?;
    let mut ctx = Context::default();
    ctx.add_variable_from_value("empty", is_empty);
    ctx.add_variable_from_value("enemy", is_enemy);
    ctx.add_variable_from_value("empty_or_enemy", is_empty || is_enemy);
    // first_move tracking requires per-component history, not yet implemented
    ctx.add_variable_from_value("first_move", false);
    match program.execute(&ctx) {
        Ok(Value::Bool(b)) => Some(b),
        Ok(_) => Some(false),
        Err(_) => None,
    }
}

fn build_end_condition_context(session: &GameSession, current_player: &str) -> Context<'static> {
    let mut ctx = Context::default();

    // Standard game state variables
    ctx.add_variable_from_value("current_player", current_player.to_string());
    ctx.add_variable_from_value("move_count", session.runtime.move_count as i64);
    ctx.add_variable_from_value("halfmove_clock", session.runtime.halfmove_clock as i64);

    // Inject all runtime counters into CEL context
    for (name, value) in &session.runtime.counters {
        ctx.add_variable_from_value(name.clone(), *value);
    }

    // Grid structure: serialize all lines (rows, columns, diagonals) as
    // lists of owner strings so CEL expressions can query them composably.
    // e.g. lines.exists(line, line.all(cell, cell == current_player))
    populate_grid_lines(&mut ctx, session);

    // Legacy boolean variables (backward compat)
    ctx.add_variable_from_value(
        "three_in_line",
        crate::end_conditions::check_line_win(session, current_player),
    );
    ctx.add_variable_from_value("all_cells_occupied", check_any_grid_full(session));
    ctx.add_variable_from_value("board_is_full", check_any_grid_full(session));

    ctx
}

/// Serialize grid zones into CEL structures for composable queries.
///
/// Owner-based (for win conditions):
/// - `lines`, `rows`, `cols`, `diags`: lists of owner strings
///
/// Type-based (for placement constraints):
/// - `type_rows`, `type_cols`: lists of component_type strings
///
/// Dimensions:
/// - `board_width`, `board_height`, `cell_count`, `occupied_count`
fn populate_grid_lines(ctx: &mut Context<'_>, session: &GameSession) {
    for zone in session.runtime.zones.values() {
        if let RuntimeZone::Grid { storage, .. } = zone
        {
            let (w, h) = match storage.dimensions() {
                Some((w, h)) => (w as usize, h as usize),
                None => break, // sparse with no dimensions: skip CEL grid context
            };

            // Skip CEL grid context for very large grids to prevent memory exhaustion
            if w * h > MAX_CEL_GRID_CELLS {
                ctx.add_variable_from_value("board_width", w as i64);
                ctx.add_variable_from_value("board_height", h as i64);
                ctx.add_variable_from_value("cell_count", (w * h) as i64);
                ctx.add_variable_from_value(
                    "occupied_count",
                    storage.occupied_count() as i64,
                );
                break;
            }

            ctx.add_variable_from_value("board_width", w as i64);
            ctx.add_variable_from_value("board_height", h as i64);
            ctx.add_variable_from_value("cell_count", (w * h) as i64);
            ctx.add_variable_from_value(
                "occupied_count",
                storage.occupied_count() as i64,
            );

            // Closure used by both full lines and windowed sub-lines below.
            let owner_at = |col: usize, row: usize| -> Value {
                storage
                    .get(col as i32, row as i32)
                    .and_then(|cid| session.runtime.components.get(cid))
                    .and_then(|comp| comp.owner.as_deref())
                    .map(|s| Value::String(Arc::new(s.to_string())))
                    .unwrap_or(Value::String(Arc::new(String::new())))
            };

            // Rows
            let mut rows = Vec::with_capacity(h);
            for row in 0..h {
                let line: Vec<Value> = (0..w).map(|col| owner_at(col, row)).collect();
                rows.push(Value::List(Arc::new(line)));
            }

            // Columns
            let mut cols = Vec::with_capacity(w);
            for col in 0..w {
                let line: Vec<Value> = (0..h).map(|row| owner_at(col, row)).collect();
                cols.push(Value::List(Arc::new(line)));
            }

            // Diagonals (square grids only)
            let mut diags = Vec::new();
            if w == h && w > 0 {
                let main: Vec<Value> = (0..w).map(|i| owner_at(i, i)).collect();
                let anti: Vec<Value> = (0..w).map(|i| owner_at(w - 1 - i, i)).collect();
                diags.push(Value::List(Arc::new(main)));
                diags.push(Value::List(Arc::new(anti)));
            }

            ctx.add_variable_from_value("rows", Value::List(Arc::new(rows.clone())));
            ctx.add_variable_from_value("cols", Value::List(Arc::new(cols.clone())));
            ctx.add_variable_from_value("diags", Value::List(Arc::new(diags.clone())));

            // Combined: all lines in one list
            let mut all_lines = rows;
            all_lines.extend(cols);
            all_lines.extend(diags);
            ctx.add_variable_from_value("lines", Value::List(Arc::new(all_lines)));

            // Windowed sub-lines: lines_N for N-length consecutive windows
            // in every direction (horizontal, vertical, both diagonals).
            // e.g. lines_4.exists(line, line.all(cell, cell == current_player))
            let max_dim = w.max(h);
            for n in 3..=max_dim {
                let mut windows: Vec<Value> = Vec::new();
                if n <= w {
                    for row in 0..h {
                        for sc in 0..=(w - n) {
                            let win: Vec<Value> =
                                (0..n).map(|i| owner_at(sc + i, row)).collect();
                            windows.push(Value::List(Arc::new(win)));
                        }
                    }
                }
                if n <= h {
                    for col in 0..w {
                        for sr in 0..=(h - n) {
                            let win: Vec<Value> =
                                (0..n).map(|i| owner_at(col, sr + i)).collect();
                            windows.push(Value::List(Arc::new(win)));
                        }
                    }
                }
                if n <= w && n <= h {
                    for sc in 0..=(w - n) {
                        for sr in 0..=(h - n) {
                            let win: Vec<Value> =
                                (0..n).map(|i| owner_at(sc + i, sr + i)).collect();
                            windows.push(Value::List(Arc::new(win)));
                        }
                    }
                    for sc in (n - 1)..w {
                        for sr in 0..=(h - n) {
                            let win: Vec<Value> =
                                (0..n).map(|i| owner_at(sc - i, sr + i)).collect();
                            windows.push(Value::List(Arc::new(win)));
                        }
                    }
                }
                if !windows.is_empty() {
                    ctx.add_variable_from_value(
                        format!("lines_{n}"),
                        Value::List(Arc::new(windows)),
                    );
                }
            }

            // Component-type-based rows/cols (for placement constraints)
            let type_at = |col: usize, row: usize| -> Value {
                storage
                    .get(col as i32, row as i32)
                    .and_then(|cid| session.runtime.components.get(cid))
                    .map(|comp| Value::String(Arc::new(comp.component_type.clone())))
                    .unwrap_or(Value::String(Arc::new(String::new())))
            };

            let type_rows: Vec<Value> = (0..h)
                .map(|row| {
                    let line: Vec<Value> = (0..w).map(|col| type_at(col, row)).collect();
                    Value::List(Arc::new(line))
                })
                .collect();
            let type_cols: Vec<Value> = (0..w)
                .map(|col| {
                    let line: Vec<Value> = (0..h).map(|row| type_at(col, row)).collect();
                    Value::List(Arc::new(line))
                })
                .collect();

            ctx.add_variable_from_value("type_rows", Value::List(Arc::new(type_rows)));
            ctx.add_variable_from_value("type_cols", Value::List(Arc::new(type_cols)));

            // Cell properties: expose prop_{key} as 2D arrays (rows format).
            if let RuntimeZone::Grid { cell_properties, .. } = zone {
                let mut all_keys = std::collections::BTreeSet::new();
                for props in cell_properties.values() {
                    for key in props.keys() {
                        all_keys.insert(key.clone());
                    }
                }
                for key in &all_keys {
                    let prop_rows: Vec<Value> = (0..h)
                        .map(|row| {
                            let line: Vec<Value> = (0..w)
                                .map(|col| {
                                    let coord = (col as i32, row as i32);
                                    let val = cell_properties
                                        .get(&coord)
                                        .and_then(|p| p.get(key.as_str()))
                                        .map(|v| match v {
                                            serde_json::Value::String(s) => s.clone(),
                                            serde_json::Value::Number(n) => n.to_string(),
                                            serde_json::Value::Bool(b) => b.to_string(),
                                            _ => String::new(),
                                        })
                                        .unwrap_or_default();
                                    Value::String(Arc::new(val))
                                })
                                .collect();
                            Value::List(Arc::new(line))
                        })
                        .collect();
                    ctx.add_variable_from_value(
                        format!("prop_{key}"),
                        Value::List(Arc::new(prop_rows)),
                    );
                }
            }

            break; // Use the first grid zone
        }
    }

    // Per-zone uniform-type booleans: zone_uniform_<name> is true when all
    // cells in the named grid zone are occupied and have the same component type.
    for (name, zone) in &session.runtime.zones {
        if let RuntimeZone::Grid { storage, .. } = zone {
            if let Some((w, h)) = storage.dimensions() {
                let total = (w as usize).checked_mul(h as usize).unwrap_or(0);
                let occupied = storage.occupied_count();
                let uniform = total > 0 && occupied == total && {
                    let cells = storage.occupied_cells();
                    let first_type = cells
                        .first()
                        .and_then(|&(_, _, cid)| session.runtime.components.get(cid))
                        .map(|c| c.component_type.clone());
                    first_type.is_some()
                        && cells.iter().skip(1).all(|&(_, _, cid)| {
                            session
                                .runtime
                                .components
                                .get(cid)
                                .map(|comp| comp.component_type.as_str())
                                == first_type.as_deref()
                        })
                };
                ctx.add_variable_from_value(format!("zone_uniform_{name}"), uniform);
            }
        }
    }
}

/// Check whether any grid zone has all cells occupied.
fn check_any_grid_full(session: &GameSession) -> bool {
    for zone in session.runtime.zones.values() {
        if let RuntimeZone::Grid { storage, .. } = zone {
            if let Some((w, h)) = storage.dimensions() {
                let total = (w as usize).checked_mul(h as usize).unwrap_or(0);
                if total > 0 && storage.occupied_count() == total {
                    return true;
                }
            }
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simple_bool_expression() {
        let program = Program::compile("true && !false").unwrap();
        let ctx = Context::default();
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn variable_lookup() {
        let program = Program::compile("three_in_line").unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("three_in_line", true);
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn boolean_composition() {
        let program = Program::compile("in_check && !has_legal_moves").unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("in_check", true);
        ctx.add_variable_from_value("has_legal_moves", false);
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn comparison_expression() {
        let program = Program::compile("halfmove_clock >= 100").unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("halfmove_clock", 101i64);
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn move_condition_empty_and_first_move() {
        let result = try_eval_move_condition(true, false, "empty");
        assert_eq!(result, Some(true));

        let result = try_eval_move_condition(false, true, "enemy");
        assert_eq!(result, Some(true));

        let result = try_eval_move_condition(true, false, "empty || enemy");
        assert_eq!(result, Some(true));
    }

    #[test]
    fn legacy_string_returns_none() {
        // Old-style conditions with AND/OR should fail to parse as CEL
        let result = try_eval_move_condition(true, false, "empty AND first_move");
        assert_eq!(result, None);
    }

    #[test]
    fn lines_exist_composable_win() {
        // Simulate the composable win condition used by tic-tac-toe
        let program = Program::compile(
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        .unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("current_player", "X".to_string());
        // A winning board: X owns the entire first row
        let row0 = Value::List(Arc::new(vec![
            Value::String(Arc::new("X".into())),
            Value::String(Arc::new("X".into())),
            Value::String(Arc::new("X".into())),
        ]));
        let row1 = Value::List(Arc::new(vec![
            Value::String(Arc::new("O".into())),
            Value::String(Arc::new(String::new())),
            Value::String(Arc::new(String::new())),
        ]));
        ctx.add_variable_from_value("lines", Value::List(Arc::new(vec![row0, row1])));
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn lines_no_win() {
        let program = Program::compile(
            "lines.exists(line, line.all(cell, cell == current_player))",
        )
        .unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("current_player", "X".to_string());
        let row0 = Value::List(Arc::new(vec![
            Value::String(Arc::new("X".into())),
            Value::String(Arc::new("O".into())),
            Value::String(Arc::new("X".into())),
        ]));
        ctx.add_variable_from_value("lines", Value::List(Arc::new(vec![row0])));
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(false)));
    }

    #[test]
    fn occupied_count_board_full() {
        let program = Program::compile("occupied_count == cell_count").unwrap();
        let mut ctx = Context::default();
        ctx.add_variable_from_value("occupied_count", 9i64);
        ctx.add_variable_from_value("cell_count", 9i64);
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn type_rows_filter_size() {
        // Test that filter+size works for uniqueness checking
        let program = Program::compile(
            "type_rows[0].filter(v, v == target).size() == 1",
        )
        .unwrap();
        let mut ctx = Context::default();
        let row0 = Value::List(Arc::new(vec![
            Value::String(Arc::new("pawn".into())),
            Value::String(Arc::new("rook".into())),
            Value::String(Arc::new("pawn".into())),
        ]));
        ctx.add_variable_from_value("type_rows", Value::List(Arc::new(vec![row0])));
        ctx.add_variable_from_value("target", "rook".to_string());
        assert_eq!(program.execute(&ctx), Ok(Value::Bool(true)));
    }

    #[test]
    fn invalid_cel_returns_none() {
        let result = try_eval_move_condition(true, false, "three_in_line(current.marks, row OR column)");
        assert_eq!(result, None);
    }

    #[test]
    fn deeply_nested_expression_rejected() {
        // 33 levels of nesting exceeds MAX_CEL_NESTING (32)
        let expr = "(".repeat(33) + "true" + &")".repeat(33);
        let result = try_eval_move_condition(true, false, &expr);
        assert_eq!(result, None);
    }

    #[test]
    fn acceptable_nesting_works() {
        // 5 levels of nesting is fine
        let expr = "(((((!false)))))";
        let result = try_eval_move_condition(true, false, expr);
        assert_eq!(result, Some(true));
    }

    #[test]
    fn oversized_expression_rejected() {
        let expr = "a".repeat(MAX_CEL_LENGTH + 1);
        let result = try_eval_move_condition(true, false, &expr);
        assert_eq!(result, None);
    }
}
