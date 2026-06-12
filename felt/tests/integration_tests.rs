use wasmtime::*;

fn compile_and_validate(source: &str) -> Vec<u8> {
    let tokens = felt::lexer::lex(source).expect("lex error");
    let program = felt::parser::parse(tokens).expect("parse error");
    felt::checker::check(&program).expect("type error");
    felt::callgraph::check_no_cycles(&program).expect("cycle error");
    felt::codegen::compile(&program)
}

fn call_i64(source: &str, func_name: &str, args: &[Val]) -> i64 {
    let wasm = compile_and_validate(source);
    let engine = Engine::default();
    let module = Module::new(&engine, &wasm).expect("invalid wasm module");
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[]).expect("instantiation failed");
    let func = instance
        .get_func(&mut store, func_name)
        .unwrap_or_else(|| panic!("function '{func_name}' not exported"));
    let mut results = [Val::I64(0)];
    func.call(&mut store, args, &mut results)
        .unwrap_or_else(|e| panic!("call to '{func_name}' failed: {e}"));
    match results[0] {
        Val::I64(v) => v,
        _ => panic!("expected i64 result"),
    }
}

fn call_i32(source: &str, func_name: &str, args: &[Val]) -> i32 {
    let wasm = compile_and_validate(source);
    let engine = Engine::default();
    let module = Module::new(&engine, &wasm).expect("invalid wasm module");
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[]).expect("instantiation failed");
    let func = instance
        .get_func(&mut store, func_name)
        .unwrap_or_else(|| panic!("function '{func_name}' not exported"));
    let mut results = [Val::I32(0)];
    func.call(&mut store, args, &mut results)
        .unwrap_or_else(|e| panic!("call to '{func_name}' failed: {e}"));
    match results[0] {
        Val::I32(v) => v,
        _ => panic!("expected i32 result"),
    }
}

#[test]
fn test_add_one() {
    let result = call_i64("fn add1(x: Int) -> Int = x + 1", "add1", &[Val::I64(41)]);
    assert_eq!(result, 42);
}

#[test]
fn test_arithmetic() {
    let result = call_i64(
        "fn calc(a: Int, b: Int) -> Int = a * b + a",
        "calc",
        &[Val::I64(3), Val::I64(4)],
    );
    assert_eq!(result, 15); // 3*4 + 3
}

#[test]
fn test_if_then_else() {
    let source = "fn maxval(a: Int, b: Int) -> Int = if a > b then a else b";
    assert_eq!(call_i64(source, "maxval", &[Val::I64(10), Val::I64(5)]), 10);
    assert_eq!(call_i64(source, "maxval", &[Val::I64(3), Val::I64(7)]), 7);
}

#[test]
fn test_let_binding() {
    let result = call_i64(
        "fn f(x: Int) -> Int = let y = x + 1 in y * y",
        "f",
        &[Val::I64(4)],
    );
    assert_eq!(result, 25); // (4+1)^2
}

#[test]
fn test_function_call() {
    let source = "fn double(x: Int) -> Int = x * 2\nfn quad(x: Int) -> Int = double (double x)";
    assert_eq!(call_i64(source, "quad", &[Val::I64(3)]), 12);
}

#[test]
fn test_bool_and() {
    let source = "fn f(a: Bool, b: Bool) -> Bool = a and b";
    assert_eq!(call_i32(source, "f", &[Val::I32(1), Val::I32(1)]), 1);
    assert_eq!(call_i32(source, "f", &[Val::I32(1), Val::I32(0)]), 0);
    assert_eq!(call_i32(source, "f", &[Val::I32(0), Val::I32(1)]), 0);
}

#[test]
fn test_bool_or() {
    let source = "fn f(a: Bool, b: Bool) -> Bool = a or b";
    assert_eq!(call_i32(source, "f", &[Val::I32(0), Val::I32(0)]), 0);
    assert_eq!(call_i32(source, "f", &[Val::I32(1), Val::I32(0)]), 1);
}

#[test]
fn test_not() {
    let source = "fn f(a: Bool) -> Bool = not a";
    assert_eq!(call_i32(source, "f", &[Val::I32(1)]), 0);
    assert_eq!(call_i32(source, "f", &[Val::I32(0)]), 1);
}

#[test]
fn test_negation() {
    assert_eq!(
        call_i64("fn neg(x: Int) -> Int = -x", "neg", &[Val::I64(42)]),
        -42,
    );
}

#[test]
fn test_comparison() {
    let source = "fn gt(a: Int, b: Int) -> Bool = a > b";
    assert_eq!(call_i32(source, "gt", &[Val::I64(5), Val::I64(3)]), 1);
    assert_eq!(call_i32(source, "gt", &[Val::I64(3), Val::I64(5)]), 0);
}

#[test]
fn test_modulo() {
    assert_eq!(
        call_i64(
            "fn f(a: Int, b: Int) -> Int = a % b",
            "f",
            &[Val::I64(17), Val::I64(5)],
        ),
        2,
    );
}

#[test]
fn test_match_int() {
    let source = "fn f(x: Int) -> Int = match x with | 1 -> 100 | 2 -> 200 | _ -> 0";
    assert_eq!(call_i64(source, "f", &[Val::I64(1)]), 100);
    assert_eq!(call_i64(source, "f", &[Val::I64(2)]), 200);
    assert_eq!(call_i64(source, "f", &[Val::I64(99)]), 0);
}

#[test]
fn test_nested_if() {
    let source =
        "fn classify(x: Int) -> Int = if x > 0 then 1 else if x == 0 then 0 else -1";
    assert_eq!(call_i64(source, "classify", &[Val::I64(5)]), 1);
    assert_eq!(call_i64(source, "classify", &[Val::I64(0)]), 0);
    assert_eq!(call_i64(source, "classify", &[Val::I64(-3)]), -1);
}

#[test]
fn test_multiple_let_bindings() {
    let source = "fn f(x: Int) -> Int = let a = x + 1 in let b = a * 2 in b + a";
    assert_eq!(call_i64(source, "f", &[Val::I64(3)]), 12); // a=4, b=8, 8+4=12
}

#[test]
fn test_three_functions() {
    let source = "\
        fn inc(x: Int) -> Int = x + 1\n\
        fn dbl(x: Int) -> Int = x * 2\n\
        fn f(x: Int) -> Int = dbl (inc x)";
    assert_eq!(call_i64(source, "f", &[Val::I64(3)]), 8); // (3+1)*2
}

#[test]
fn test_fibonacci_iterative_style() {
    // Since we can't use recursion, test with explicit computation
    let source = "\
        fn fib5() -> Int = \
          let a = 1 in \
          let b = 1 in \
          let c = a + b in \
          let d = b + c in \
          let e = c + d in \
          e";
    assert_eq!(call_i64(source, "fib5", &[]), 5);
}

#[test]
fn test_where_clause() {
    let source = "fn f(x: Int) -> Int = y * 2 where y = x + 1";
    assert_eq!(call_i64(source, "f", &[Val::I64(4)]), 10); // (4+1)*2
}

#[test]
fn test_wasm_module_size() {
    let wasm = compile_and_validate("fn f(x: Int) -> Int = x + 1");
    // Should be small — under 200 bytes for a trivial function
    assert!(wasm.len() < 200, "trivial function produced {} bytes", wasm.len());
}
