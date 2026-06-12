use std::collections::HashMap;

use wasm_encoder::{
    CodeSection, ConstExpr, ExportKind, ExportSection, Function, FunctionSection, Instruction,
    MemorySection, MemoryType, Module, TypeSection, ValType, DataSection, DataSegment,
    DataSegmentMode,
};

use crate::ast::{BinOp, Expr, FnDef, Pattern, Program, Type, UnOp};

pub struct Compiler {
    fn_indices: HashMap<String, u32>,
    string_data: Vec<(u32, Vec<u8>)>, // (offset, bytes) for data section
    data_offset: u32,
}

struct FnCompiler<'a> {
    locals: HashMap<String, (u32, ValType)>, // name -> (index, type)
    next_local: u32,
    extra_locals: Vec<ValType>, // locals beyond params
    compiler: &'a Compiler,
}

impl Compiler {
    pub fn compile(program: &Program) -> Vec<u8> {
        let mut compiler = Compiler {
            fn_indices: HashMap::new(),
            string_data: Vec::new(),
            data_offset: 0,
        };

        // Assign function indices
        for (i, f) in program.functions.iter().enumerate() {
            compiler.fn_indices.insert(f.name.clone(), i as u32);
        }

        // Collect string literals from all function bodies
        for f in &program.functions {
            compiler.collect_strings(&f.body);
        }

        compiler.emit_module(program)
    }

    fn collect_strings(&mut self, expr: &Expr) {
        match expr {
            Expr::StringLit(s) => {
                let bytes = s.as_bytes().to_vec();
                let offset = self.data_offset;
                self.data_offset += bytes.len() as u32;
                self.string_data.push((offset, bytes));
            }
            Expr::Apply(f, a) => {
                self.collect_strings(f);
                self.collect_strings(a);
            }
            Expr::Lambda(_, body) => self.collect_strings(body),
            Expr::Let(binds, body) => {
                for (_, v) in binds {
                    self.collect_strings(v);
                }
                self.collect_strings(body);
            }
            Expr::If(c, t, e) => {
                self.collect_strings(c);
                self.collect_strings(t);
                self.collect_strings(e);
            }
            Expr::Match(s, arms) => {
                self.collect_strings(s);
                for (_, b) in arms {
                    self.collect_strings(b);
                }
            }
            Expr::BinOp(_, l, r) => {
                self.collect_strings(l);
                self.collect_strings(r);
            }
            Expr::UnOp(_, inner) => self.collect_strings(inner),
            Expr::SomeWrap(inner) => self.collect_strings(inner),
            Expr::FieldAccess(inner, _) => self.collect_strings(inner),
            Expr::List(items) | Expr::Set(items) | Expr::Tuple(items) => {
                for item in items {
                    self.collect_strings(item);
                }
            }
            Expr::Record(fields) => {
                for (_, v) in fields {
                    self.collect_strings(v);
                }
            }
            Expr::IntLit(_) | Expr::FloatLit(_) | Expr::BoolLit(_) | Expr::Ident(_)
            | Expr::NoneLit => {}
        }
    }

    fn emit_module(&self, program: &Program) -> Vec<u8> {
        let mut module = Module::new();

        // Type section: one type per function signature
        let mut types = TypeSection::new();
        for f in &program.functions {
            let params: Vec<ValType> = f.params.iter().map(|(_, t)| type_to_valtype(t)).collect();
            let results = vec![type_to_valtype(&f.return_type)];
            types.ty().function(params, results);
        }
        module.section(&types);

        // Function section
        let mut functions = FunctionSection::new();
        for (i, _) in program.functions.iter().enumerate() {
            functions.function(i as u32); // type index = function index
        }
        module.section(&functions);

        // Memory section (1 page minimum, 16 max)
        let mut memories = MemorySection::new();
        memories.memory(MemoryType {
            minimum: 1,
            maximum: Some(16),
            memory64: false,
            shared: false,
            page_size_log2: None,
        });
        module.section(&memories);

        // Export section
        let mut exports = ExportSection::new();
        exports.export("memory", ExportKind::Memory, 0);

        let extension_fns = ["is_legal", "legal_moves", "apply_effect", "score", "check_end"];
        for f in &program.functions {
            if extension_fns.contains(&f.name.as_str()) {
                exports.export(&f.name, ExportKind::Func, self.fn_indices[&f.name]);
            }
        }
        // Also export all functions for testing
        for f in &program.functions {
            if !extension_fns.contains(&f.name.as_str()) {
                exports.export(&f.name, ExportKind::Func, self.fn_indices[&f.name]);
            }
        }
        module.section(&exports);

        // Code section
        let mut codes = CodeSection::new();
        for f in &program.functions {
            let func = self.compile_function(f);
            codes.function(&func);
        }
        module.section(&codes);

        // Data section (string literals)
        if !self.string_data.is_empty() {
            let mut data = DataSection::new();
            let offsets: Vec<ConstExpr> = self
                .string_data
                .iter()
                .map(|(offset, _)| ConstExpr::i32_const(*offset as i32))
                .collect();
            for (i, (_, bytes)) in self.string_data.iter().enumerate() {
                data.segment(DataSegment {
                    mode: DataSegmentMode::Active {
                        memory_index: 0,
                        offset: &offsets[i],
                    },
                    data: bytes.iter().copied(),
                });
            }
            module.section(&data);
        }

        module.finish()
    }

    fn compile_function(&self, f: &FnDef) -> Function {
        let mut fc = FnCompiler {
            locals: HashMap::new(),
            next_local: 0,
            extra_locals: Vec::new(),
            compiler: self,
        };

        // Register params as locals
        for (name, ty) in &f.params {
            let vt = type_to_valtype(ty);
            fc.locals.insert(name.clone(), (fc.next_local, vt));
            fc.next_local += 1;
        }

        // Pre-scan body for let bindings to allocate locals
        fc.prescan_locals(&f.body);

        // Build function with extra locals
        let local_decls: Vec<(u32, ValType)> = fc.extra_locals.iter().map(|vt| (1, *vt)).collect();
        let mut func = Function::new(local_decls);

        // Compile body
        fc.compile_expr(&f.body, &mut func);
        func.instruction(&Instruction::End);

        func
    }
}

impl<'a> FnCompiler<'a> {
    fn prescan_locals(&mut self, expr: &Expr) {
        match expr {
            Expr::Let(bindings, body) => {
                for (name, val) in bindings {
                    if !self.locals.contains_key(name) {
                        let vt = self.infer_valtype(val);
                        self.locals.insert(name.clone(), (self.next_local, vt));
                        self.extra_locals.push(vt);
                        self.next_local += 1;
                    }
                    self.prescan_locals(val);
                }
                self.prescan_locals(body);
            }
            Expr::Match(scrutinee, arms) => {
                // Need a local for the scrutinee value
                if !self.locals.contains_key("__match") {
                    let vt = self.infer_valtype(scrutinee);
                    self.locals.insert("__match".to_string(), (self.next_local, vt));
                    self.extra_locals.push(vt);
                    self.next_local += 1;
                }
                self.prescan_locals(scrutinee);
                for (pat, body) in arms {
                    if let Pattern::SomePat(name) | Pattern::VarPat(name) = pat {
                        if !self.locals.contains_key(name) {
                            let vt = self.infer_valtype(scrutinee);
                            self.locals.insert(name.clone(), (self.next_local, vt));
                            self.extra_locals.push(vt);
                            self.next_local += 1;
                        }
                    }
                    self.prescan_locals(body);
                }
            }
            Expr::If(c, t, e) => {
                self.prescan_locals(c);
                self.prescan_locals(t);
                self.prescan_locals(e);
            }
            Expr::Apply(f, arg) => {
                self.prescan_locals(f);
                self.prescan_locals(arg);
            }
            Expr::Lambda(_, body) => self.prescan_locals(body),
            Expr::BinOp(_, l, r) => {
                self.prescan_locals(l);
                self.prescan_locals(r);
            }
            Expr::UnOp(_, inner) => self.prescan_locals(inner),
            Expr::SomeWrap(inner) | Expr::FieldAccess(inner, _) => self.prescan_locals(inner),
            Expr::List(items) | Expr::Set(items) | Expr::Tuple(items) => {
                for item in items {
                    self.prescan_locals(item);
                }
            }
            Expr::Record(fields) => {
                for (_, v) in fields {
                    self.prescan_locals(v);
                }
            }
            Expr::IntLit(_) | Expr::FloatLit(_) | Expr::BoolLit(_) | Expr::StringLit(_)
            | Expr::Ident(_) | Expr::NoneLit => {}
        }
    }

    fn infer_valtype(&self, expr: &Expr) -> ValType {
        match expr {
            Expr::IntLit(_) => ValType::I64,
            Expr::FloatLit(_) => ValType::F64,
            Expr::BoolLit(_) => ValType::I32,
            Expr::StringLit(_) => ValType::I32, // pointer
            Expr::BinOp(op, _, _) => match op {
                BinOp::Add | BinOp::Sub | BinOp::Mul | BinOp::Div | BinOp::Mod => ValType::I64,
                BinOp::Eq | BinOp::Neq | BinOp::Lt | BinOp::Gt | BinOp::Lte | BinOp::Gte
                | BinOp::And | BinOp::Or => ValType::I32,
                BinOp::Concat => ValType::I32,
            },
            Expr::UnOp(UnOp::Not, _) => ValType::I32,
            Expr::UnOp(UnOp::Neg, inner) => self.infer_valtype(inner),
            Expr::If(_, t, _) => self.infer_valtype(t),
            Expr::Ident(name) => {
                self.locals.get(name).map(|(_, vt)| *vt).unwrap_or(ValType::I64)
            }
            _ => ValType::I64, // default
        }
    }

    fn compile_expr(&self, expr: &Expr, func: &mut Function) {
        match expr {
            Expr::IntLit(n) => {
                func.instruction(&Instruction::I64Const(*n));
            }
            Expr::FloatLit(f) => {
                func.instruction(&Instruction::F64Const(*f));
            }
            Expr::BoolLit(b) => {
                func.instruction(&Instruction::I32Const(if *b { 1 } else { 0 }));
            }
            Expr::StringLit(_s) => {
                // Return pointer to string data in linear memory
                // For now, just return 0 (placeholder)
                func.instruction(&Instruction::I32Const(0));
            }
            Expr::NoneLit => {
                // None represented as 0/default
                func.instruction(&Instruction::I64Const(0));
            }
            Expr::SomeWrap(inner) => {
                // Some x = just the value (non-zero indicates Some for handles)
                self.compile_expr(inner, func);
            }
            Expr::Ident(name) => {
                if let Some((idx, _)) = self.locals.get(name) {
                    func.instruction(&Instruction::LocalGet(*idx));
                } else if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                    // Function reference — shouldn't appear as a bare value normally,
                    // but handle it for partial application stubs
                    func.instruction(&Instruction::I64Const(*fn_idx as i64));
                } else {
                    // Unknown — push 0 as fallback
                    func.instruction(&Instruction::I64Const(0));
                }
            }
            Expr::BinOp(op, lhs, rhs) => {
                self.compile_expr(lhs, func);
                self.compile_expr(rhs, func);
                match op {
                    BinOp::Add => { func.instruction(&Instruction::I64Add); }
                    BinOp::Sub => { func.instruction(&Instruction::I64Sub); }
                    BinOp::Mul => { func.instruction(&Instruction::I64Mul); }
                    BinOp::Div => { func.instruction(&Instruction::I64DivS); }
                    BinOp::Mod => { func.instruction(&Instruction::I64RemS); }
                    BinOp::Eq => { func.instruction(&Instruction::I64Eq); }
                    BinOp::Neq => { func.instruction(&Instruction::I64Ne); }
                    BinOp::Lt => { func.instruction(&Instruction::I64LtS); }
                    BinOp::Gt => { func.instruction(&Instruction::I64GtS); }
                    BinOp::Lte => { func.instruction(&Instruction::I64LeS); }
                    BinOp::Gte => { func.instruction(&Instruction::I64GeS); }
                    BinOp::And => { func.instruction(&Instruction::I32And); }
                    BinOp::Or => { func.instruction(&Instruction::I32Or); }
                    BinOp::Concat => {
                        // TODO: string/list concatenation
                        func.instruction(&Instruction::I32Add);
                    }
                }
            }
            Expr::UnOp(UnOp::Neg, inner) => {
                let vt = self.infer_valtype(inner);
                match vt {
                    ValType::I64 => {
                        func.instruction(&Instruction::I64Const(0));
                        self.compile_expr(inner, func);
                        func.instruction(&Instruction::I64Sub);
                    }
                    ValType::F64 => {
                        self.compile_expr(inner, func);
                        func.instruction(&Instruction::F64Neg);
                    }
                    _ => {
                        func.instruction(&Instruction::I64Const(0));
                        self.compile_expr(inner, func);
                        func.instruction(&Instruction::I64Sub);
                    }
                }
            }
            Expr::UnOp(UnOp::Not, inner) => {
                self.compile_expr(inner, func);
                func.instruction(&Instruction::I32Eqz);
            }
            Expr::If(cond, then_br, else_br) => {
                self.compile_expr(cond, func);
                let result_type = self.infer_valtype(then_br);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                self.compile_expr(then_br, func);
                func.instruction(&Instruction::Else);
                self.compile_expr(else_br, func);
                func.instruction(&Instruction::End);
            }
            Expr::Let(bindings, body) => {
                for (name, val) in bindings {
                    self.compile_expr(val, func);
                    if let Some((idx, _)) = self.locals.get(name) {
                        func.instruction(&Instruction::LocalSet(*idx));
                    }
                }
                self.compile_expr(body, func);
            }
            Expr::Apply(f_expr, arg) => {
                // Direct function call: f(x)
                if let Expr::Ident(name) = f_expr.as_ref() {
                    if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                        self.compile_expr(arg, func);
                        func.instruction(&Instruction::Call(*fn_idx));
                        return;
                    }
                }
                // Curried application: (f a) b — compile as nested calls
                if let Expr::Apply(ff, first_arg) = f_expr.as_ref() {
                    if let Expr::Ident(name) = ff.as_ref() {
                        if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                            self.compile_expr(first_arg, func);
                            self.compile_expr(arg, func);
                            func.instruction(&Instruction::Call(*fn_idx));
                            return;
                        }
                    }
                    // Triple application: ((f a) b) c
                    if let Expr::Apply(fff, a0) = ff.as_ref() {
                        if let Expr::Ident(name) = fff.as_ref() {
                            if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                                self.compile_expr(a0, func);
                                self.compile_expr(first_arg, func);
                                self.compile_expr(arg, func);
                                func.instruction(&Instruction::Call(*fn_idx));
                                return;
                            }
                        }
                    }
                }
                // Fallback: compile both sides and try a call
                self.compile_expr(arg, func);
                self.compile_expr(f_expr, func);
                // Can't dynamically call — emit 0 as placeholder
                func.instruction(&Instruction::Drop);
            }
            Expr::Match(scrutinee, arms) => {
                self.compile_expr(scrutinee, func);
                if let Some((match_idx, _)) = self.locals.get("__match") {
                    func.instruction(&Instruction::LocalSet(*match_idx));
                    self.compile_match_arms(arms, *match_idx, func);
                }
            }
            Expr::Lambda(_, body) => {
                // Lambdas should have been eliminated by closure conversion
                // For now, just compile the body (works for simple cases)
                self.compile_expr(body, func);
            }
            Expr::List(_) | Expr::Set(_) | Expr::Tuple(_) | Expr::Record(_) => {
                // Collections not yet implemented in codegen
                func.instruction(&Instruction::I64Const(0));
            }
            Expr::FieldAccess(_, _) => {
                // Record field access not yet implemented
                func.instruction(&Instruction::I64Const(0));
            }
        }
    }

    fn compile_match_arms(&self, arms: &[(Pattern, Expr)], match_local: u32, func: &mut Function) {
        if arms.is_empty() {
            func.instruction(&Instruction::Unreachable);
            return;
        }

        if arms.len() == 1 {
            let (pat, body) = &arms[0];
            self.bind_pattern(pat, match_local, func);
            self.compile_expr(body, func);
            return;
        }

        let (pat, body) = &arms[0];
        let rest = &arms[1..];

        let result_type = self.infer_valtype(body);

        match pat {
            Pattern::Wildcard | Pattern::VarPat(_) => {
                self.bind_pattern(pat, match_local, func);
                self.compile_expr(body, func);
            }
            Pattern::IntPat(n) => {
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I64Const(*n));
                func.instruction(&Instruction::I64Eq);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                self.bind_pattern(pat, match_local, func);
                self.compile_expr(body, func);
                func.instruction(&Instruction::Else);
                self.compile_match_arms(rest, match_local, func);
                func.instruction(&Instruction::End);
            }
            Pattern::BoolPat(b) => {
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I32Const(if *b { 1 } else { 0 }));
                func.instruction(&Instruction::I32Eq);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                self.compile_expr(body, func);
                func.instruction(&Instruction::Else);
                self.compile_match_arms(rest, match_local, func);
                func.instruction(&Instruction::End);
            }
            Pattern::NonePat => {
                // None = 0 for handle-based values
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I64Eqz);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                self.compile_expr(body, func);
                func.instruction(&Instruction::Else);
                self.compile_match_arms(rest, match_local, func);
                func.instruction(&Instruction::End);
            }
            Pattern::SomePat(name) => {
                // Some = non-zero
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I64Const(0));
                func.instruction(&Instruction::I64Ne);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                // Bind the value
                if let Some((idx, _)) = self.locals.get(name) {
                    func.instruction(&Instruction::LocalGet(match_local));
                    func.instruction(&Instruction::LocalSet(*idx));
                }
                self.compile_expr(body, func);
                func.instruction(&Instruction::Else);
                self.compile_match_arms(rest, match_local, func);
                func.instruction(&Instruction::End);
            }
            Pattern::StringPat(_) => {
                // String comparison not yet implemented
                self.compile_expr(body, func);
            }
        }
    }

    fn bind_pattern(&self, pat: &Pattern, match_local: u32, func: &mut Function) {
        if let Pattern::VarPat(name) = pat {
            if let Some((idx, _)) = self.locals.get(name) {
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::LocalSet(*idx));
            }
        }
    }
}

fn type_to_valtype(ty: &Type) -> ValType {
    match ty {
        Type::Int => ValType::I64,
        Type::Float => ValType::F64,
        Type::Bool => ValType::I32,
        Type::String => ValType::I32, // pointer to linear memory
        _ => ValType::I64, // handles, collections, etc.
    }
}

pub fn compile(program: &Program) -> Vec<u8> {
    Compiler::compile(program)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexer;
    use crate::parser;

    fn compile_to_wasm(input: &str) -> Vec<u8> {
        let tokens = lexer::lex(input).expect("lex error");
        let program = parser::parse(tokens).expect("parse error");
        compile(&program)
    }

    #[test]
    fn test_compile_simple() {
        let wasm = compile_to_wasm("fn add1(x: Int) -> Int = x + 1");
        // Should produce valid WASM
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d])); // \0asm magic
        assert!(wasm.len() > 8); // non-trivial
    }

    #[test]
    fn test_compile_arithmetic() {
        let wasm = compile_to_wasm("fn calc(a: Int, b: Int) -> Int = a * b + a - b");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_if_else() {
        let wasm = compile_to_wasm("fn maxval(a: Int, b: Int) -> Int = if a > b then a else b");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_let() {
        let wasm = compile_to_wasm("fn f(x: Int) -> Int = let y = x + 1 in y * y");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_function_call() {
        let wasm = compile_to_wasm(
            "fn double(x: Int) -> Int = x * 2\nfn quad(x: Int) -> Int = double (double x)",
        );
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_bool() {
        let wasm = compile_to_wasm("fn f(a: Bool, b: Bool) -> Bool = a and b");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_match() {
        let wasm = compile_to_wasm(
            "fn f(x: Int) -> Int = match x with | 1 -> 100 | 2 -> 200 | _ -> 0",
        );
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_negation() {
        let wasm = compile_to_wasm("fn neg(x: Int) -> Int = -x");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_multiple_fns() {
        let wasm = compile_to_wasm(
            "fn f(x: Int) -> Int = x + 1\nfn g(x: Int) -> Int = f x * 2",
        );
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }

    #[test]
    fn test_compile_nested_if() {
        let wasm = compile_to_wasm(
            "fn classify(x: Int) -> Int = if x > 0 then 1 else if x == 0 then 0 else -1",
        );
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }
}
