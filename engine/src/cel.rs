use cel_interpreter::{Context, Program, Value};
use crate::runtime::{GameSession, RuntimeZone};

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

    // Precomputed game predicates — evaluated eagerly so CEL expressions
    // can reference them as simple boolean variables.
    ctx.add_variable_from_value(
        "three_in_line",
        crate::end_conditions::check_line_win(session, current_player),
    );
    ctx.add_variable_from_value("all_cells_occupied", check_any_grid_full(session));
    ctx.add_variable_from_value("board_is_full", check_any_grid_full(session));

    ctx
}

/// Check whether any grid zone has all cells occupied.
fn check_any_grid_full(session: &GameSession) -> bool {
    for zone in session.runtime.zones.values() {
        if let RuntimeZone::Grid { cells, .. } = zone {
            if !cells.is_empty() && cells.iter().all(|c| c.is_some()) {
                return true;
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
    fn invalid_cel_returns_none() {
        let result = try_eval_move_condition(true, false, "three_in_line(current.marks, row OR column)");
        assert_eq!(result, None);
    }
}
