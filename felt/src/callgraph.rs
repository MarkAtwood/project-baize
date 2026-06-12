use std::collections::{HashMap, HashSet};

use crate::ast::{Expr, Program};

#[derive(Debug, Clone)]
pub struct CycleError {
    pub cycle: Vec<String>,
}

impl std::fmt::Display for CycleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "recursive call: {}", self.cycle.join(" -> "))
    }
}

pub fn check_no_cycles(program: &Program) -> Result<(), CycleError> {
    let fn_names: HashSet<&str> = program.functions.iter().map(|f| f.name.as_str()).collect();

    // Build adjacency list: caller -> callees
    let mut graph: HashMap<&str, Vec<&str>> = HashMap::new();
    for f in &program.functions {
        let mut callees = Vec::new();
        collect_calls(&f.body, &fn_names, &mut callees);
        graph.insert(f.name.as_str(), callees);
    }

    // DFS cycle detection
    let mut visited = HashSet::new();
    let mut in_stack = HashSet::new();
    let mut path = Vec::new();

    for f in &program.functions {
        if !visited.contains(f.name.as_str()) {
            if let Some(cycle) = dfs(
                f.name.as_str(),
                &graph,
                &mut visited,
                &mut in_stack,
                &mut path,
            ) {
                return Err(CycleError { cycle });
            }
        }
    }

    Ok(())
}

fn dfs<'a>(
    node: &'a str,
    graph: &HashMap<&'a str, Vec<&'a str>>,
    visited: &mut HashSet<&'a str>,
    in_stack: &mut HashSet<&'a str>,
    path: &mut Vec<&'a str>,
) -> Option<Vec<String>> {
    visited.insert(node);
    in_stack.insert(node);
    path.push(node);

    if let Some(neighbors) = graph.get(node) {
        for &next in neighbors {
            if !visited.contains(next) {
                if let Some(cycle) = dfs(next, graph, visited, in_stack, path) {
                    return Some(cycle);
                }
            } else if in_stack.contains(next) {
                // Found cycle — extract it from path
                let start = path.iter().position(|&n| n == next).unwrap();
                let mut cycle: Vec<String> =
                    path[start..].iter().map(|s| s.to_string()).collect();
                cycle.push(next.to_string());
                return Some(cycle);
            }
        }
    }

    path.pop();
    in_stack.remove(node);
    None
}

fn collect_calls<'a>(expr: &'a Expr, fn_names: &HashSet<&str>, callees: &mut Vec<&'a str>) {
    match expr {
        Expr::Ident(name) => {
            if fn_names.contains(name.as_str()) {
                callees.push(name.as_str());
            }
        }
        Expr::Apply(f, arg) => {
            collect_calls(f, fn_names, callees);
            collect_calls(arg, fn_names, callees);
        }
        Expr::Lambda(_, body) => collect_calls(body, fn_names, callees),
        Expr::Let(bindings, body) => {
            for (_, val) in bindings {
                collect_calls(val, fn_names, callees);
            }
            collect_calls(body, fn_names, callees);
        }
        Expr::If(c, t, e) => {
            collect_calls(c, fn_names, callees);
            collect_calls(t, fn_names, callees);
            collect_calls(e, fn_names, callees);
        }
        Expr::Match(scrutinee, arms) => {
            collect_calls(scrutinee, fn_names, callees);
            for (_, body) in arms {
                collect_calls(body, fn_names, callees);
            }
        }
        Expr::BinOp(_, lhs, rhs) => {
            collect_calls(lhs, fn_names, callees);
            collect_calls(rhs, fn_names, callees);
        }
        Expr::UnOp(_, inner) => collect_calls(inner, fn_names, callees),
        Expr::List(items) | Expr::Set(items) | Expr::Tuple(items) => {
            for item in items {
                collect_calls(item, fn_names, callees);
            }
        }
        Expr::Record(fields) => {
            for (_, val) in fields {
                collect_calls(val, fn_names, callees);
            }
        }
        Expr::FieldAccess(expr, _) => collect_calls(expr, fn_names, callees),
        Expr::SomeWrap(inner) => collect_calls(inner, fn_names, callees),
        Expr::IntLit(_) | Expr::FloatLit(_) | Expr::BoolLit(_) | Expr::StringLit(_)
        | Expr::NoneLit => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexer;
    use crate::parser;

    fn check(input: &str) -> Result<(), CycleError> {
        let tokens = lexer::lex(input).expect("lex error");
        let program = parser::parse(tokens).expect("parse error");
        check_no_cycles(&program)
    }

    #[test]
    fn test_dag_accepted() {
        check("fn f(x: Int) -> Int = g x\nfn g(x: Int) -> Int = x + 1").unwrap();
    }

    #[test]
    fn test_direct_recursion_rejected() {
        let err = check("fn f(x: Int) -> Int = f x").unwrap_err();
        assert!(err.cycle.contains(&"f".to_string()));
    }

    #[test]
    fn test_mutual_recursion_rejected() {
        let err =
            check("fn f(x: Int) -> Int = g x\nfn g(x: Int) -> Int = f x").unwrap_err();
        assert!(err.cycle.len() >= 2);
    }

    #[test]
    fn test_deep_acyclic() {
        check(
            "fn a(x: Int) -> Int = b x\nfn b(x: Int) -> Int = c x\nfn c(x: Int) -> Int = x",
        )
        .unwrap();
    }

    #[test]
    fn test_no_functions() {
        check("").unwrap();
    }

    #[test]
    fn test_single_function_no_self_call() {
        check("fn f(x: Int) -> Int = x + 1").unwrap();
    }

    #[test]
    fn test_cycle_reports_path() {
        let err =
            check("fn a(x: Int) -> Int = b x\nfn b(x: Int) -> Int = c x\nfn c(x: Int) -> Int = a x")
                .unwrap_err();
        // Cycle should include a, b, c
        let msg = err.to_string();
        assert!(msg.contains("a"));
        assert!(msg.contains("b"));
        assert!(msg.contains("c"));
    }
}
