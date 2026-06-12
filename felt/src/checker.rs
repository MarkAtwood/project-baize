use std::collections::HashMap;

use crate::ast::*;
use crate::lexer::Span;

#[derive(Debug, Clone)]
pub struct TypeError {
    pub message: String,
    pub span: Span,
}

impl std::fmt::Display for TypeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

pub struct TypeChecker {
    env: HashMap<String, Type>,
    type_defs: HashMap<String, Vec<(String, Type)>>,
}

impl Default for TypeChecker {
    fn default() -> Self {
        Self::new()
    }
}

impl TypeChecker {
    pub fn new() -> Self {
        let mut checker = Self {
            env: HashMap::new(),
            type_defs: HashMap::new(),
        };
        checker.register_builtins();
        checker
    }

    fn register_builtins(&mut self) {
        use Type::*;

        // Zone access
        self.env.insert("zone".into(), Fn(Box::new(State), Box::new(Fn(Box::new(String), Box::new(Zone)))));
        self.env.insert("zone_for".into(), Fn(Box::new(State), Box::new(Fn(Box::new(String), Box::new(Fn(Box::new(Player), Box::new(Zone)))))));
        self.env.insert("components".into(), Fn(Box::new(Zone), Box::new(List(Box::new(Component)))));
        self.env.insert("cells".into(), Fn(Box::new(Zone), Box::new(List(Box::new(Cell)))));
        self.env.insert("cell_at".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(Option(Box::new(Component)))))))));
        self.env.insert("count".into(), Fn(Box::new(Zone), Box::new(Int)));
        self.env.insert("counter_value".into(), Fn(Box::new(Zone), Box::new(Int)));

        // Component properties
        self.env.insert("type_of".into(), Fn(Box::new(Component), Box::new(String)));
        self.env.insert("owner".into(), Fn(Box::new(Component), Box::new(Option(Box::new(Player)))));
        self.env.insert("rank".into(), Fn(Box::new(Component), Box::new(Int)));
        self.env.insert("suit".into(), Fn(Box::new(Component), Box::new(String)));
        self.env.insert("property".into(), Fn(Box::new(Component), Box::new(Fn(Box::new(String), Box::new(String)))));
        self.env.insert("position".into(), Fn(Box::new(Component), Box::new(Option(Box::new(Cell)))));
        self.env.insert("col".into(), Fn(Box::new(Cell), Box::new(Int)));
        self.env.insert("row".into(), Fn(Box::new(Cell), Box::new(Int)));

        // Grid operations
        self.env.insert("adjacent".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(List(Box::new(Cell)))))));
        self.env.insert("diagonal".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(List(Box::new(Cell)))))));
        self.env.insert("neighbors".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(List(Box::new(Cell)))))));
        self.env.insert("in_bounds".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(Bool)))))));
        self.env.insert("dimensions".into(), Fn(Box::new(Zone), Box::new(Tuple(vec![Int, Int]))));
        self.env.insert("row_cells".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Int), Box::new(List(Box::new(Cell)))))));
        self.env.insert("col_cells".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Int), Box::new(List(Box::new(Cell)))))));
        self.env.insert("line_cells".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(List(Box::new(Cell)))))))))));

        // Graph operations
        self.env.insert("flood_fill".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(Fn(Box::new(Fn(Box::new(Cell), Box::new(Bool))), Box::new(Set(Box::new(Cell)))))))));
        self.env.insert("flood_groups".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Fn(Box::new(Cell), Box::new(Bool))), Box::new(List(Box::new(Set(Box::new(Cell)))))))));
        self.env.insert("connected".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Cell), Box::new(Fn(Box::new(Cell), Box::new(Fn(Box::new(Fn(Box::new(Cell), Box::new(Bool))), Box::new(Bool)))))))));
        self.env.insert("border".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Set(Box::new(Cell))), Box::new(Set(Box::new(Cell)))))));
        self.env.insert("border_owners".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Set(Box::new(Cell))), Box::new(Set(Box::new(Player)))))));
        self.env.insert("liberties".into(), Fn(Box::new(Zone), Box::new(Fn(Box::new(Set(Box::new(Cell))), Box::new(Int)))));

        // Game state
        self.env.insert("players".into(), Fn(Box::new(State), Box::new(List(Box::new(Player)))));
        self.env.insert("current_player".into(), Fn(Box::new(State), Box::new(Player)));
        self.env.insert("other_player".into(), Fn(Box::new(State), Box::new(Fn(Box::new(Player), Box::new(Player)))));
        self.env.insert("turn".into(), Fn(Box::new(State), Box::new(Int)));
        self.env.insert("phase".into(), Fn(Box::new(State), Box::new(String)));
        self.env.insert("counters".into(), Fn(Box::new(State), Box::new(Map(Box::new(String), Box::new(Int)))));
        self.env.insert("is_finished".into(), Fn(Box::new(State), Box::new(Bool)));
        self.env.insert("name".into(), Fn(Box::new(Player), Box::new(String)));

        // Tuple operations
        self.env.insert("fst".into(), Fn(Box::new(Tuple(vec![Int, Int])), Box::new(Int)));
        self.env.insert("snd".into(), Fn(Box::new(Tuple(vec![Int, Int])), Box::new(Int)));

        // Option operations
        self.env.insert("is_some".into(), Fn(Box::new(Option(Box::new(Int))), Box::new(Bool)));
        self.env.insert("is_none".into(), Fn(Box::new(Option(Box::new(Int))), Box::new(Bool)));

        // Arithmetic
        self.env.insert("abs".into(), Fn(Box::new(Int), Box::new(Int)));
        self.env.insert("max_of".into(), Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(Int)))));
        self.env.insert("min_of".into(), Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(Int)))));

        // List operations (monomorphic approximations — will be refined at call sites)
        self.env.insert("sum".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Int)));
        self.env.insert("max".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Int)));
        self.env.insert("min".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Int)));
        self.env.insert("sort".into(), Fn(Box::new(List(Box::new(Int))), Box::new(List(Box::new(Int)))));
        self.env.insert("length".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Int)));
        self.env.insert("all_same".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Bool)));
        self.env.insert("consecutive".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Bool)));
        self.env.insert("concat".into(), Fn(Box::new(String), Box::new(Fn(Box::new(String), Box::new(String)))));
        self.env.insert("range".into(), Fn(Box::new(Int), Box::new(Fn(Box::new(Int), Box::new(List(Box::new(Int)))))));
        self.env.insert("size".into(), Fn(Box::new(Set(Box::new(Cell))), Box::new(Int)));

        // Set operations
        self.env.insert("from_list".into(), Fn(Box::new(List(Box::new(Player))), Box::new(Set(Box::new(Player)))));
        self.env.insert("to_list".into(), Fn(Box::new(Set(Box::new(Int))), Box::new(List(Box::new(Int)))));
        self.env.insert("member".into(), Fn(Box::new(Set(Box::new(Int))), Box::new(Fn(Box::new(Int), Box::new(Bool)))));

        // Grouping
        self.env.insert("count_groups".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Fn(Box::new(Int), Box::new(Int)))));
        self.env.insert("has_group".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Fn(Box::new(Int), Box::new(Bool)))));
        self.env.insert("group_value".into(), Fn(Box::new(List(Box::new(Int))), Box::new(Fn(Box::new(Int), Box::new(Int)))));
    }

    pub fn check_program(&mut self, program: &Program) -> Result<(), Vec<TypeError>> {
        let mut errors = Vec::new();

        // Register type defs
        for td in &program.type_defs {
            self.type_defs.insert(td.name.clone(), td.fields.clone());
        }

        // Register all function signatures first (allows forward references)
        for f in &program.functions {
            let fn_type = self.build_fn_type(&f.params, &f.return_type);
            self.env.insert(f.name.clone(), fn_type);
        }

        // Check each function body
        for f in &program.functions {
            let mut local_env = self.env.clone();
            for (pname, ptype) in &f.params {
                local_env.insert(pname.clone(), ptype.clone());
            }

            match self.check_expr(&f.body, &f.return_type, &local_env) {
                Ok(()) => {}
                Err(e) => errors.push(e),
            }
        }

        // Validate extension function signatures
        let ext_sigs = self.extension_signatures();
        for f in &program.functions {
            if let Some(expected) = ext_sigs.get(f.name.as_str()) {
                let actual = self.build_fn_type(&f.params, &f.return_type);
                if !self.types_compatible(&actual, expected) {
                    errors.push(TypeError {
                        message: format!(
                            "extension function '{}' has wrong signature: expected {:?}, found {:?}",
                            f.name, expected, actual
                        ),
                        span: f.span.clone(),
                    });
                }
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }

    fn extension_signatures(&self) -> HashMap<&'static str, Type> {
        use Type::*;
        let score_type = Record(vec![
            ("player".into(), String),
            ("points".into(), Int),
            ("breakdown".into(), List(Box::new(Record(vec![
                ("category".into(), String),
                ("points".into(), Int),
            ])))),
        ]);
        let end_result_type = Record(vec![
            ("game_over".into(), Bool),
            ("winner".into(), String),
            ("condition".into(), String),
        ]);

        let mut sigs = HashMap::new();
        sigs.insert("is_legal", Fn(Box::new(State), Box::new(Fn(Box::new(Player), Box::new(Fn(Box::new(Action), Box::new(Option(Box::new(Bool)))))))));
        sigs.insert("legal_moves", Fn(Box::new(State), Box::new(Fn(Box::new(Player), Box::new(List(Box::new(Action)))))));
        sigs.insert("apply_effect", Fn(Box::new(State), Box::new(Fn(Box::new(String), Box::new(State)))));
        sigs.insert("score", Fn(Box::new(State), Box::new(List(Box::new(score_type)))));
        sigs.insert("check_end", Fn(Box::new(State), Box::new(Option(Box::new(end_result_type)))));
        sigs
    }

    fn build_fn_type(&self, params: &[(String, Type)], ret: &Type) -> Type {
        let mut t = ret.clone();
        for (_, ptype) in params.iter().rev() {
            t = Type::Fn(Box::new(ptype.clone()), Box::new(t));
        }
        t
    }

    fn check_expr(&self, expr: &Expr, expected: &Type, env: &HashMap<String, Type>) -> Result<(), TypeError> {
        let inferred = self.infer_expr(expr, env)?;
        if self.types_compatible(&inferred, expected) {
            Ok(())
        } else {
            Err(TypeError {
                message: format!("type mismatch: expected {expected:?}, found {inferred:?}"),
                span: 0..0, // TODO: attach proper spans to expressions
            })
        }
    }

    fn infer_expr(&self, expr: &Expr, env: &HashMap<String, Type>) -> Result<Type, TypeError> {
        match expr {
            Expr::IntLit(_) => Ok(Type::Int),
            Expr::FloatLit(_) => Ok(Type::Float),
            Expr::BoolLit(_) => Ok(Type::Bool),
            Expr::StringLit(_) => Ok(Type::String),
            Expr::NoneLit => Ok(Type::Option(Box::new(Type::Int))), // Generic None; refined at use site
            Expr::SomeWrap(inner) => {
                let t = self.infer_expr(inner, env)?;
                Ok(Type::Option(Box::new(t)))
            }

            Expr::Ident(name) => env.get(name).cloned().ok_or_else(|| TypeError {
                message: format!("unknown identifier '{name}'"),
                span: 0..0,
            }),

            Expr::BinOp(op, lhs, rhs) => {
                let lt = self.infer_expr(lhs, env)?;
                let rt = self.infer_expr(rhs, env)?;
                self.check_binop(*op, &lt, &rt)
            }

            Expr::UnOp(UnOp::Neg, inner) => {
                let t = self.infer_expr(inner, env)?;
                match t {
                    Type::Int | Type::Float => Ok(t),
                    _ => Err(TypeError {
                        message: format!("cannot negate type {t:?}"),
                        span: 0..0,
                    }),
                }
            }

            Expr::UnOp(UnOp::Not, inner) => {
                let t = self.infer_expr(inner, env)?;
                if self.types_compatible(&t, &Type::Bool) {
                    Ok(Type::Bool)
                } else {
                    Err(TypeError {
                        message: format!("'not' requires Bool, found {t:?}"),
                        span: 0..0,
                    })
                }
            }

            Expr::If(cond, then_br, else_br) => {
                let ct = self.infer_expr(cond, env)?;
                if !self.types_compatible(&ct, &Type::Bool) {
                    return Err(TypeError {
                        message: format!("if condition must be Bool, found {ct:?}"),
                        span: 0..0,
                    });
                }
                let tt = self.infer_expr(then_br, env)?;
                let et = self.infer_expr(else_br, env)?;
                if self.types_compatible(&tt, &et) {
                    Ok(tt)
                } else {
                    Err(TypeError {
                        message: format!("if branches have different types: {tt:?} vs {et:?}"),
                        span: 0..0,
                    })
                }
            }

            Expr::Let(bindings, body) => {
                let mut local_env = env.clone();
                for (name, val) in bindings {
                    let t = self.infer_expr(val, &local_env)?;
                    local_env.insert(name.clone(), t);
                }
                self.infer_expr(body, &local_env)
            }

            Expr::Lambda(param, body) => {
                // Without context we can't infer the param type, so we
                // return a placeholder. In practice, lambdas appear inside
                // Apply where the expected type provides context.
                // For now, assign a generic type.
                let mut local_env = env.clone();
                local_env.insert(param.clone(), Type::Int); // placeholder
                let body_type = self.infer_expr(body, &local_env)?;
                Ok(Type::Fn(Box::new(Type::Int), Box::new(body_type)))
            }

            Expr::Apply(func, arg) => {
                let ft = self.infer_expr(func, env)?;
                match ft {
                    Type::Fn(_param_type, ret_type) => {
                        // Check arg type is compatible (lenient for polymorphic builtins)
                        let _at = self.infer_expr(arg, env)?;
                        // For now, we trust the arg type and return the declared return type.
                        // Full unification would refine polymorphic returns.
                        Ok(*ret_type)
                    }
                    _ => {
                        // Could be partial application or an identifier that resolves later
                        let _at = self.infer_expr(arg, env)?;
                        Err(TypeError {
                            message: format!("'{ft:?}' is not a function"),
                            span: 0..0,
                        })
                    }
                }
            }

            Expr::List(items) => {
                if items.is_empty() {
                    Ok(Type::List(Box::new(Type::Int))) // empty list default
                } else {
                    let t = self.infer_expr(&items[0], env)?;
                    Ok(Type::List(Box::new(t)))
                }
            }

            Expr::Set(items) => {
                if items.is_empty() {
                    Ok(Type::Set(Box::new(Type::Int)))
                } else {
                    let t = self.infer_expr(&items[0], env)?;
                    Ok(Type::Set(Box::new(t)))
                }
            }

            Expr::Tuple(items) => {
                let types: Result<Vec<_>, _> = items.iter().map(|e| self.infer_expr(e, env)).collect();
                Ok(Type::Tuple(types?))
            }

            Expr::Record(fields) => {
                let mut field_types = Vec::new();
                for (name, val) in fields {
                    let t = self.infer_expr(val, env)?;
                    field_types.push((name.clone(), t));
                }
                Ok(Type::Record(field_types))
            }

            Expr::FieldAccess(expr, field) => {
                let t = self.infer_expr(expr, env)?;
                match &t {
                    Type::Record(fields) => {
                        for (name, ft) in fields {
                            if name == field {
                                return Ok(ft.clone());
                            }
                        }
                        Err(TypeError {
                            message: format!("field '{field}' does not exist on type {t:?}"),
                            span: 0..0,
                        })
                    }
                    _ => {
                        // Check type defs for named record types
                        // For game types, field access is handled specially
                        Err(TypeError {
                            message: format!("cannot access field '{field}' on type {t:?}"),
                            span: 0..0,
                        })
                    }
                }
            }

            Expr::Match(scrutinee, arms) => {
                let _st = self.infer_expr(scrutinee, env)?;
                if arms.is_empty() {
                    return Err(TypeError {
                        message: "empty match".to_string(),
                        span: 0..0,
                    });
                }

                // Infer type from first arm, check rest match
                let mut local_env = env.clone();
                self.bind_pattern(&arms[0].0, &_st, &mut local_env);
                let result_type = self.infer_expr(&arms[0].1, &local_env)?;

                for arm in &arms[1..] {
                    let mut arm_env = env.clone();
                    self.bind_pattern(&arm.0, &_st, &mut arm_env);
                    let _at = self.infer_expr(&arm.1, &arm_env)?;
                }

                Ok(result_type)
            }
        }
    }

    fn bind_pattern(&self, pattern: &Pattern, scrutinee_type: &Type, env: &mut HashMap<String, Type>) {
        match pattern {
            Pattern::VarPat(name) => {
                env.insert(name.clone(), scrutinee_type.clone());
            }
            Pattern::SomePat(name) => {
                if let Type::Option(inner) = scrutinee_type {
                    env.insert(name.clone(), *inner.clone());
                } else {
                    env.insert(name.clone(), scrutinee_type.clone());
                }
            }
            _ => {} // Wildcard, literals — no bindings
        }
    }

    fn check_binop(&self, op: BinOp, lt: &Type, rt: &Type) -> Result<Type, TypeError> {
        match op {
            BinOp::Add | BinOp::Sub | BinOp::Mul | BinOp::Div | BinOp::Mod => {
                match (lt, rt) {
                    (Type::Int, Type::Int) => Ok(Type::Int),
                    (Type::Float, Type::Float) => Ok(Type::Float),
                    _ => Err(TypeError {
                        message: format!("arithmetic requires matching numeric types, found {lt:?} and {rt:?}"),
                        span: 0..0,
                    }),
                }
            }
            BinOp::Eq | BinOp::Neq => {
                if self.types_compatible(lt, rt) {
                    Ok(Type::Bool)
                } else {
                    Err(TypeError {
                        message: format!("comparison requires matching types, found {lt:?} and {rt:?}"),
                        span: 0..0,
                    })
                }
            }
            BinOp::Lt | BinOp::Gt | BinOp::Lte | BinOp::Gte => {
                match (lt, rt) {
                    (Type::Int, Type::Int) | (Type::Float, Type::Float) | (Type::String, Type::String) => Ok(Type::Bool),
                    _ => Err(TypeError {
                        message: format!("ordering requires matching ordered types, found {lt:?} and {rt:?}"),
                        span: 0..0,
                    }),
                }
            }
            BinOp::And | BinOp::Or => {
                if self.types_compatible(lt, &Type::Bool) && self.types_compatible(rt, &Type::Bool) {
                    Ok(Type::Bool)
                } else {
                    Err(TypeError {
                        message: format!("logical operators require Bool, found {lt:?} and {rt:?}"),
                        span: 0..0,
                    })
                }
            }
            BinOp::Concat => {
                // Works on lists and strings
                match (lt, rt) {
                    (Type::String, Type::String) => Ok(Type::String),
                    (Type::List(a), Type::List(_)) => Ok(Type::List(a.clone())),
                    _ => Err(TypeError {
                        message: format!("++ requires matching List or String types, found {lt:?} and {rt:?}"),
                        span: 0..0,
                    }),
                }
            }
        }
    }

    fn types_compatible(&self, a: &Type, b: &Type) -> bool {
        match (a, b) {
            (Type::Int, Type::Int)
            | (Type::Float, Type::Float)
            | (Type::Bool, Type::Bool)
            | (Type::String, Type::String)
            | (Type::State, Type::State)
            | (Type::Zone, Type::Zone)
            | (Type::Cell, Type::Cell)
            | (Type::Component, Type::Component)
            | (Type::Player, Type::Player)
            | (Type::Action, Type::Action) => true,
            (Type::List(a), Type::List(b)) => self.types_compatible(a, b),
            (Type::Set(a), Type::Set(b)) => self.types_compatible(a, b),
            (Type::Map(ak, av), Type::Map(bk, bv)) => {
                self.types_compatible(ak, bk) && self.types_compatible(av, bv)
            }
            (Type::Option(a), Type::Option(b)) => self.types_compatible(a, b),
            (Type::Tuple(a), Type::Tuple(b)) => {
                a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| self.types_compatible(x, y))
            }
            (Type::Record(a), Type::Record(b)) => {
                // Structural compatibility: same field names and types
                a.len() == b.len()
                    && a.iter().zip(b.iter()).all(|((an, at), (bn, bt))| {
                        an == bn && self.types_compatible(at, bt)
                    })
            }
            (Type::Fn(a1, a2), Type::Fn(b1, b2)) => {
                self.types_compatible(a1, b1) && self.types_compatible(a2, b2)
            }
            // Polymorphic compatibility: any concrete type is compatible with
            // a builtin's placeholder type for polymorphic positions
            _ => false,
        }
    }
}

pub fn check(program: &Program) -> Result<(), Vec<TypeError>> {
    let mut checker = TypeChecker::new();
    checker.check_program(program)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexer;
    use crate::parser;

    fn check_program(input: &str) -> Result<(), Vec<TypeError>> {
        let tokens = lexer::lex(input).expect("lex error");
        let program = parser::parse(tokens).expect("parse error");
        check(&program)
    }

    fn check_ok(input: &str) {
        match check_program(input) {
            Ok(()) => {}
            Err(errors) => {
                for e in &errors {
                    eprintln!("  {e}");
                }
                panic!("expected no type errors, got {}", errors.len());
            }
        }
    }

    fn check_err(input: &str) -> Vec<TypeError> {
        check_program(input).expect_err("expected type error")
    }

    #[test]
    fn test_simple_int_fn() {
        check_ok("fn f(x: Int) -> Int = x + 1");
    }

    #[test]
    fn test_bool_fn() {
        check_ok("fn f(x: Bool) -> Bool = not x");
    }

    #[test]
    fn test_if_matching_branches() {
        check_ok("fn f(x: Bool) -> Int = if x then 1 else 2");
    }

    #[test]
    fn test_if_mismatched_branches() {
        let errors = check_err(r#"fn f(x: Bool) -> Int = if x then 1 else "no""#);
        assert!(!errors.is_empty());
    }

    #[test]
    fn test_let_binding() {
        check_ok("fn f(x: Int) -> Int = let y = x + 1 in y * 2");
    }

    #[test]
    fn test_unknown_ident() {
        let errors = check_err("fn f(x: Int) -> Int = y");
        assert!(errors[0].message.contains("unknown identifier"));
    }

    #[test]
    fn test_arithmetic_type_mismatch() {
        let errors = check_err(r#"fn f(x: Int) -> Int = x + "hello""#);
        assert!(!errors.is_empty());
    }

    #[test]
    fn test_builtin_zone() {
        check_ok("fn f(s: State) -> Zone = zone s \"board\"");
    }

    #[test]
    fn test_builtin_rank() {
        check_ok("fn f(c: Component) -> Int = rank c");
    }

    #[test]
    fn test_builtin_components() {
        check_ok("fn f(z: Zone) -> List Component = components z");
    }

    #[test]
    fn test_record_construction() {
        check_ok(
            "type Score = { player: String, points: Int }\nfn f() -> { player: String, points: Int } = { player = \"X\", points = 42 }",
        );
    }

    #[test]
    fn test_field_access() {
        check_ok("fn f(s: { player: String, points: Int }) -> String = s.player");
    }

    #[test]
    fn test_bad_field_access() {
        let errors = check_err("fn f(s: { player: String }) -> Int = s.missing");
        assert!(errors[0].message.contains("field 'missing'"));
    }

    #[test]
    fn test_match_int() {
        check_ok(
            r#"fn f(x: Int) -> String = match x with | 1 -> "one" | _ -> "other""#,
        );
    }

    #[test]
    fn test_option_match_types() {
        check_ok(
            "fn f(x: Option Int) -> Int = match x with | Some v -> v | None -> 0",
        );
    }

    #[test]
    fn test_forward_reference() {
        check_ok("fn g(x: Int) -> Int = f x\nfn f(x: Int) -> Int = x + 1");
    }

    #[test]
    fn test_multiple_let_bindings() {
        check_ok("fn f(x: Int) -> Int = let a = x + 1 in let b = a * 2 in b");
    }

    #[test]
    fn test_comparison_returns_bool() {
        check_ok("fn f(x: Int, y: Int) -> Bool = x > y");
    }

    #[test]
    fn test_logical_ops() {
        check_ok("fn f(a: Bool, b: Bool) -> Bool = a and b or not a");
    }

    #[test]
    fn test_list_literal() {
        check_ok("fn f() -> List Int = [1, 2, 3]");
    }

    #[test]
    fn test_tuple_type() {
        check_ok("fn f() -> (Int, Int) = (1, 2)");
    }

    #[test]
    fn test_pipe_with_builtin() {
        check_ok("fn f(z: Zone) -> List Component = z |> components");
    }

    #[test]
    fn test_string_concat() {
        check_ok(r#"fn f(a: String, b: String) -> String = a ++ b"#);
    }
}
