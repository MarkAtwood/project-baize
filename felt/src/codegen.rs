use std::collections::{HashMap, HashSet};

use wasm_encoder::{
    CodeSection, ConstExpr, EntityType, ExportKind, ExportSection, Function, FunctionSection,
    GlobalSection, GlobalType, ImportSection, Instruction, MemorySection, MemoryType, Module,
    TypeSection, ValType, DataSection, DataSegment, DataSegmentMode,
};

use crate::ast::{BinOp, Expr, FnDef, Pattern, Program, Type, UnOp};

/// How a single Felt-level argument maps to WASM-level parameters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FeltArg {
    /// A handle/int/bool value: one WASM i32 or i64 param.
    Handle(ValType),
    /// A string input: expands to (ptr: i32, len: i32) — two WASM params.
    StringIn,
    /// A string output via buffer: adds a buf: i32 param, return is len: i32.
    StringOut,
}

/// Describes a builtin's WASM import signature.
struct BuiltinImport {
    /// Felt-level builtin name (e.g., "zone", "rank").
    felt_name: &'static str,
    /// WASM import function name (e.g., "zone_by_name", "comp_rank").
    wasm_name: &'static str,
    /// Felt-level argument descriptors, in curried application order.
    felt_args: &'static [FeltArg],
    /// WASM-level result type.
    result: ValType,
}

impl BuiltinImport {
    /// Compute the flat WASM parameter types from the Felt arg descriptors.
    fn wasm_params(&self) -> Vec<ValType> {
        let mut params = Vec::new();
        for arg in self.felt_args {
            match arg {
                FeltArg::Handle(vt) => params.push(*vt),
                FeltArg::StringIn => {
                    params.push(ValType::I32); // ptr
                    params.push(ValType::I32); // len
                }
                FeltArg::StringOut => {
                    params.push(ValType::I32); // buf ptr
                }
            }
        }
        params
    }

}

/// All builtins that have matching host imports in felt_host.rs.
fn builtin_imports() -> Vec<BuiltinImport> {
    use FeltArg::*;
    use ValType::{I32, I64};
    vec![
        // Zone access
        BuiltinImport { felt_name: "zone", wasm_name: "zone_by_name", felt_args: &[Handle(I32), StringIn], result: I32 },
        BuiltinImport { felt_name: "zone_for", wasm_name: "zone_for_player", felt_args: &[Handle(I32), StringIn, Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "count", wasm_name: "zone_comp_count", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "counter_value", wasm_name: "zone_counter_val", felt_args: &[Handle(I32)], result: I64 },
        // Cell access
        BuiltinImport { felt_name: "cell_at", wasm_name: "cell_at", felt_args: &[Handle(I32), Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "col", wasm_name: "cell_col", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "row", wasm_name: "cell_row", felt_args: &[Handle(I32)], result: I32 },
        // Component access
        BuiltinImport { felt_name: "type_of", wasm_name: "comp_type", felt_args: &[Handle(I32), StringOut], result: I32 },
        BuiltinImport { felt_name: "owner", wasm_name: "comp_owner", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "rank", wasm_name: "comp_rank", felt_args: &[Handle(I32)], result: I64 },
        BuiltinImport { felt_name: "suit", wasm_name: "comp_suit", felt_args: &[Handle(I32), StringOut], result: I32 },
        BuiltinImport { felt_name: "property", wasm_name: "comp_property", felt_args: &[Handle(I32), StringIn, StringOut], result: I32 },
        // Player access
        BuiltinImport { felt_name: "current_player", wasm_name: "current_player", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "turn", wasm_name: "turn_number", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "phase", wasm_name: "phase_name", felt_args: &[Handle(I32), StringOut], result: I32 },
        BuiltinImport { felt_name: "is_finished", wasm_name: "is_finished", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "name", wasm_name: "player_name", felt_args: &[Handle(I32), StringOut], result: I32 },
        // Zone info
        BuiltinImport { felt_name: "zone_count", wasm_name: "zone_count", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "zone_type", wasm_name: "zone_type", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "zone_width", wasm_name: "zone_width", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "zone_height", wasm_name: "zone_height", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "zone_cell_count", wasm_name: "zone_cell_count", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "zone_comp_count", wasm_name: "zone_comp_count", felt_args: &[Handle(I32)], result: I32 },
        // Grid adjacency
        BuiltinImport { felt_name: "adjacent_count", wasm_name: "adjacent_count", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "adjacent_at", wasm_name: "adjacent_at", felt_args: &[Handle(I32), Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "in_bounds", wasm_name: "in_bounds", felt_args: &[Handle(I32), Handle(I32), Handle(I32)], result: I32 },
        // Player enumeration
        BuiltinImport { felt_name: "player_count", wasm_name: "player_count", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "player_by_index", wasm_name: "player_by_index", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        // Cell/component by index
        BuiltinImport { felt_name: "cell_by_index", wasm_name: "cell_by_index", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "comp_by_index", wasm_name: "comp_by_index", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "cell_occupant", wasm_name: "cell_occupant", felt_args: &[Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "comp_id", wasm_name: "comp_id", felt_args: &[Handle(I32), StringOut], result: I32 },
        BuiltinImport { felt_name: "zone_by_index", wasm_name: "zone_by_index", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        // Diagonal adjacency
        BuiltinImport { felt_name: "diagonal_count", wasm_name: "diagonal_count", felt_args: &[Handle(I32), Handle(I32)], result: I32 },
        BuiltinImport { felt_name: "diagonal_at", wasm_name: "diagonal_at", felt_args: &[Handle(I32), Handle(I32), Handle(I32)], result: I32 },
        // Counter by name (state-level)
        BuiltinImport { felt_name: "counter_by_name", wasm_name: "counter_value", felt_args: &[Handle(I32), StringIn], result: I64 },
    ]
}

/// Bump allocator offset within linear memory. String data occupies low
/// addresses; the allocator starts above that. We reserve 4 bytes at offset 0
/// for the global heap pointer if no string data is present, but typically
/// string data lives at offset 0.. and the heap starts after.
const HEAP_BASE_DEFAULT: u32 = 4096;
const STRING_BUF_SIZE: i32 = 256;

pub struct Compiler {
    fn_indices: HashMap<String, u32>,
    builtin_indices: HashMap<String, u32>,
    builtin_info: HashMap<String, BuiltinImportInfo>,
    import_count: u32,
    alloc_fn_idx: u32,
    string_data: Vec<(u32, Vec<u8>)>,
    data_offset: u32,
    /// Heap base address: starts after string data, rounded up.
    heap_base: u32,
}

/// Runtime info for a builtin import stored in the compiler.
#[derive(Clone)]
struct BuiltinImportInfo {
    felt_args: Vec<FeltArg>,
    result: ValType,
    wasm_fn_idx: u32,
}

struct FnCompiler<'a> {
    locals: HashMap<String, (u32, ValType)>,
    next_local: u32,
    extra_locals: Vec<ValType>,
    compiler: &'a Compiler,
}

/// Flatten a curried application chain into the root function name and
/// argument list, in application order. For `((f a) b) c` returns
/// `Some(("f", [a, b, c]))`.
fn flatten_apply(expr: &Expr) -> Option<(&str, Vec<&Expr>)> {
    fn go<'a>(e: &'a Expr, args: &mut Vec<&'a Expr>) -> Option<&'a str> {
        match e {
            Expr::Ident(name) => Some(name.as_str()),
            Expr::Apply(f, arg) => {
                let name = go(f, args)?;
                args.push(arg);
                Some(name)
            }
            _ => None,
        }
    }
    let mut args = Vec::new();
    let name = go(expr, &mut args)?;
    Some((name, args))
}

impl Compiler {
    pub fn compile(program: &Program) -> Vec<u8> {
        let mut compiler = Compiler {
            fn_indices: HashMap::new(),
            builtin_indices: HashMap::new(),
            builtin_info: HashMap::new(),
            import_count: 0,
            alloc_fn_idx: 0,
            string_data: Vec::new(),
            data_offset: 0,
            heap_base: HEAP_BASE_DEFAULT,
        };

        // Collect string literals first to know data_offset
        for f in &program.functions {
            compiler.collect_strings(&f.body);
        }

        // Set heap base above string data, aligned to 16 bytes
        compiler.heap_base = ((compiler.data_offset + 15) / 16) * 16;
        if compiler.heap_base < HEAP_BASE_DEFAULT {
            compiler.heap_base = HEAP_BASE_DEFAULT;
        }

        // Determine which builtins are actually used
        let all_builtins = builtin_imports();
        let used_names = compiler.collect_used_builtins(program);
        let mut import_idx: u32 = 0;

        for bi in &all_builtins {
            if used_names.contains(bi.felt_name) {
                compiler.builtin_indices.insert(bi.felt_name.to_string(), import_idx);
                compiler.builtin_info.insert(bi.felt_name.to_string(), BuiltinImportInfo {
                    felt_args: bi.felt_args.to_vec(),
                    result: bi.result,
                    wasm_fn_idx: import_idx,
                });
                import_idx += 1;
            }
        }
        compiler.import_count = import_idx;

        // alloc and dealloc are internal functions, placed right after imports
        // but before user functions. We'll add them as the first two user functions.
        let has_string_builtins = compiler.builtin_info.values().any(|bi| {
            bi.felt_args.iter().any(|a| matches!(a, FeltArg::StringIn | FeltArg::StringOut))
        });

        let internal_fn_count = if has_string_builtins || !compiler.string_data.is_empty() { 2 } else { 0 }; // alloc + dealloc
        let user_fn_base = compiler.import_count + internal_fn_count as u32;

        if internal_fn_count > 0 {
            compiler.alloc_fn_idx = compiler.import_count; // alloc is first internal function
        }

        // Assign function indices for user-defined functions
        for (i, f) in program.functions.iter().enumerate() {
            compiler.fn_indices.insert(f.name.clone(), user_fn_base + i as u32);
        }

        compiler.emit_module(program, has_string_builtins || !compiler.string_data.is_empty())
    }

    /// Scan the AST to find all builtin names that appear in function positions
    /// of Apply expressions.
    fn collect_used_builtins(&self, program: &Program) -> HashSet<String> {
        let all_builtin_names: HashSet<&str> = builtin_imports().iter().map(|b| b.felt_name).collect();
        let user_fn_names: HashSet<&str> = program.functions.iter().map(|f| f.name.as_str()).collect();
        let mut used = HashSet::new();
        for f in &program.functions {
            self.scan_builtins(&f.body, &all_builtin_names, &user_fn_names, &mut used);
        }
        used
    }

    fn scan_builtins(
        &self,
        expr: &Expr,
        builtin_names: &HashSet<&str>,
        user_fn_names: &HashSet<&str>,
        used: &mut HashSet<String>,
    ) {
        match expr {
            Expr::Ident(name) => {
                if builtin_names.contains(name.as_str()) && !user_fn_names.contains(name.as_str()) {
                    used.insert(name.clone());
                }
            }
            Expr::Apply(f, a) => {
                // Check if root of application chain is a builtin
                if let Some((name, _)) = flatten_apply(expr) {
                    if builtin_names.contains(name) && !user_fn_names.contains(name) {
                        used.insert(name.to_string());
                    }
                }
                self.scan_builtins(f, builtin_names, user_fn_names, used);
                self.scan_builtins(a, builtin_names, user_fn_names, used);
            }
            Expr::Lambda(_, body) => self.scan_builtins(body, builtin_names, user_fn_names, used),
            Expr::Let(binds, body) => {
                for (_, v) in binds {
                    self.scan_builtins(v, builtin_names, user_fn_names, used);
                }
                self.scan_builtins(body, builtin_names, user_fn_names, used);
            }
            Expr::If(c, t, e) => {
                self.scan_builtins(c, builtin_names, user_fn_names, used);
                self.scan_builtins(t, builtin_names, user_fn_names, used);
                self.scan_builtins(e, builtin_names, user_fn_names, used);
            }
            Expr::Match(s, arms) => {
                self.scan_builtins(s, builtin_names, user_fn_names, used);
                for (_, b) in arms {
                    self.scan_builtins(b, builtin_names, user_fn_names, used);
                }
            }
            Expr::BinOp(_, l, r) => {
                self.scan_builtins(l, builtin_names, user_fn_names, used);
                self.scan_builtins(r, builtin_names, user_fn_names, used);
            }
            Expr::UnOp(_, inner) | Expr::SomeWrap(inner) | Expr::FieldAccess(inner, _) => {
                self.scan_builtins(inner, builtin_names, user_fn_names, used);
            }
            Expr::List(items) | Expr::Set(items) | Expr::Tuple(items) => {
                for item in items {
                    self.scan_builtins(item, builtin_names, user_fn_names, used);
                }
            }
            Expr::Record(fields) => {
                for (_, v) in fields {
                    self.scan_builtins(v, builtin_names, user_fn_names, used);
                }
            }
            Expr::IntLit(_) | Expr::FloatLit(_) | Expr::BoolLit(_) | Expr::StringLit(_)
            | Expr::NoneLit => {}
        }
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

    fn emit_module(&self, program: &Program, emit_alloc: bool) -> Vec<u8> {
        let mut module = Module::new();

        // ---- Type section ----
        // Types for: imports, internal fns (alloc/dealloc), then user functions
        let mut types = TypeSection::new();

        // Import function types
        let all_builtins = builtin_imports();
        let mut type_idx: u32 = 0;
        for bi in &all_builtins {
            if self.builtin_indices.contains_key(bi.felt_name) {
                let params = bi.wasm_params();
                let results = vec![bi.result];
                types.ty().function(params, results);
                type_idx += 1;
            }
        }

        // Internal function types (alloc, dealloc) if needed
        let alloc_type_idx = type_idx;
        let dealloc_type_idx = type_idx + 1;
        if emit_alloc {
            // alloc: (size: i32) -> i32
            types.ty().function(vec![ValType::I32], vec![ValType::I32]);
            type_idx += 1;
            // dealloc: (ptr: i32, size: i32) -> ()
            types.ty().function(vec![ValType::I32, ValType::I32], vec![]);
            type_idx += 1;
        }

        // User function types
        let user_type_base = type_idx;
        for f in &program.functions {
            let params: Vec<ValType> = f.params.iter().map(|(_, t)| type_to_valtype(t)).collect();
            let results = vec![type_to_valtype(&f.return_type)];
            types.ty().function(params, results);
        }
        module.section(&types);

        // ---- Import section ----
        if self.import_count > 0 {
            let mut imports = ImportSection::new();
            let mut import_type_idx: u32 = 0;
            for bi in &all_builtins {
                if self.builtin_indices.contains_key(bi.felt_name) {
                    imports.import("baize", bi.wasm_name, EntityType::Function(import_type_idx));
                    import_type_idx += 1;
                }
            }
            module.section(&imports);
        }

        // ---- Function section ----
        let mut functions = FunctionSection::new();
        if emit_alloc {
            functions.function(alloc_type_idx);
            functions.function(dealloc_type_idx);
        }
        for (i, _) in program.functions.iter().enumerate() {
            functions.function(user_type_base + i as u32);
        }
        module.section(&functions);

        // ---- Memory section ----
        let mut memories = MemorySection::new();
        memories.memory(MemoryType {
            minimum: 1,
            maximum: Some(16),
            memory64: false,
            shared: false,
            page_size_log2: None,
        });
        module.section(&memories);

        // ---- Global section ----
        // Global 0: heap pointer (mutable i32), initialized to heap_base
        let mut globals = GlobalSection::new();
        globals.global(
            GlobalType {
                val_type: ValType::I32,
                mutable: true,
                shared: false,
            },
            &ConstExpr::i32_const(self.heap_base as i32),
        );
        module.section(&globals);

        // ---- Export section ----
        let mut exports = ExportSection::new();
        exports.export("memory", ExportKind::Memory, 0);

        if emit_alloc {
            exports.export("alloc", ExportKind::Func, self.alloc_fn_idx);
            exports.export("dealloc", ExportKind::Func, self.alloc_fn_idx + 1);
        }

        let extension_fns = ["is_legal", "legal_moves", "apply_effect", "score", "check_end"];
        for f in &program.functions {
            if extension_fns.contains(&f.name.as_str()) {
                exports.export(&f.name, ExportKind::Func, self.fn_indices[&f.name]);
            }
        }
        for f in &program.functions {
            if !extension_fns.contains(&f.name.as_str()) {
                exports.export(&f.name, ExportKind::Func, self.fn_indices[&f.name]);
            }
        }
        module.section(&exports);

        // ---- Code section ----
        let mut codes = CodeSection::new();

        // Alloc and dealloc implementations
        if emit_alloc {
            codes.function(&self.emit_alloc_fn());
            codes.function(&Self::emit_dealloc_fn());
        }

        for f in &program.functions {
            let func = self.compile_function(f);
            codes.function(&func);
        }
        module.section(&codes);

        // ---- Data section ----
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

    /// Emit a simple bump allocator: reads global 0 (heap ptr), advances it
    /// by the requested size (aligned to 8), returns the old value.
    fn emit_alloc_fn(&self) -> Function {
        let mut func = Function::new(vec![]);
        // local 0 = size param
        // result = old heap ptr
        func.instruction(&Instruction::GlobalGet(0));        // [old_ptr]
        func.instruction(&Instruction::GlobalGet(0));        // [old_ptr, old_ptr]
        func.instruction(&Instruction::LocalGet(0));         // [old_ptr, old_ptr, size]
        // Align size up to 8 bytes: (size + 7) & ~7
        func.instruction(&Instruction::I32Const(7));         // [old_ptr, old_ptr, size, 7]
        func.instruction(&Instruction::I32Add);              // [old_ptr, old_ptr, size+7]
        func.instruction(&Instruction::I32Const(-8));        // [old_ptr, old_ptr, size+7, ~7]
        func.instruction(&Instruction::I32And);              // [old_ptr, old_ptr, aligned_size]
        func.instruction(&Instruction::I32Add);              // [old_ptr, new_ptr]
        func.instruction(&Instruction::GlobalSet(0));        // [old_ptr]  (global updated)
        func.instruction(&Instruction::End);
        func
    }

    /// Emit a no-op deallocator (arena allocation — freed in bulk).
    fn emit_dealloc_fn() -> Function {
        let mut func = Function::new(vec![]);
        // params: ptr (local 0), size (local 1) — both ignored
        func.instruction(&Instruction::End);
        func
    }

    fn compile_function(&self, f: &FnDef) -> Function {
        let mut fc = FnCompiler {
            locals: HashMap::new(),
            next_local: 0,
            extra_locals: Vec::new(),
            compiler: self,
        };

        for (name, ty) in &f.params {
            let vt = type_to_valtype(ty);
            fc.locals.insert(name.clone(), (fc.next_local, vt));
            fc.next_local += 1;
        }

        fc.prescan_locals(&f.body);

        let local_decls: Vec<(u32, ValType)> = fc.extra_locals.iter().map(|vt| (1, *vt)).collect();
        let mut func = Function::new(local_decls);

        fc.compile_expr(&f.body, &mut func);
        func.instruction(&Instruction::End);

        func
    }

    /// Look up a string literal's offset and length in the data section.
    fn string_literal_info(&self, s: &str) -> Option<(u32, u32)> {
        let bytes = s.as_bytes();
        for (offset, data) in &self.string_data {
            if data == bytes {
                return Some((*offset, data.len() as u32));
            }
        }
        None
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
            Expr::StringLit(_) => ValType::I32,
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
                if let Some((_, vt)) = self.locals.get(name) {
                    return *vt;
                }
                // Check if it's a builtin with a known return type
                if let Some(bi) = self.compiler.builtin_info.get(name) {
                    return bi.result;
                }
                ValType::I64
            }
            Expr::Apply(f_expr, _) => {
                // If it's a builtin call, use the builtin's result type
                if let Some((name, _)) = flatten_apply(expr) {
                    if let Some(bi) = self.compiler.builtin_info.get(name) {
                        return bi.result;
                    }
                }
                // Otherwise recurse on function
                match f_expr.as_ref() {
                    Expr::Ident(name) => {
                        if let Some(bi) = self.compiler.builtin_info.get(name.as_str()) {
                            return bi.result;
                        }
                    }
                    _ => {}
                }
                ValType::I64
            }
            _ => ValType::I64,
        }
    }

    /// Try to compile a builtin call. Returns true if this expression was
    /// handled as a builtin call, false if it should fall through to normal
    /// Apply handling.
    fn try_compile_builtin_call(&self, expr: &Expr, func: &mut Function) -> bool {
        let (name, args) = match flatten_apply(expr) {
            Some(pair) => pair,
            None => return false,
        };

        let bi = match self.compiler.builtin_info.get(name) {
            Some(bi) => bi.clone(),
            None => return false,
        };

        let felt_arity = bi.felt_args.len();

        if args.len() < felt_arity {
            // Partial application of a builtin — can't emit a direct call.
            // Fall through to normal handling.
            return false;
        }

        if args.len() > felt_arity {
            // More args than the builtin expects. This shouldn't normally
            // happen for well-typed programs, but emit a trap.
            func.instruction(&Instruction::Unreachable);
            return true;
        }

        // Emit arguments in order, expanding strings as needed
        for (i, felt_arg) in bi.felt_args.iter().enumerate() {
            match felt_arg {
                FeltArg::Handle(_) => {
                    self.compile_expr(args[i], func);
                    // If the Felt type was i64 but the host expects i32, wrap
                    let inferred = self.infer_valtype(args[i]);
                    if inferred == ValType::I64 {
                        func.instruction(&Instruction::I32WrapI64);
                    }
                }
                FeltArg::StringIn => {
                    // String argument: push (ptr, len)
                    self.compile_string_arg(args[i], func);
                }
                FeltArg::StringOut => {
                    // Allocate a buffer for the output string. Push buf ptr.
                    func.instruction(&Instruction::I32Const(STRING_BUF_SIZE));
                    func.instruction(&Instruction::Call(self.compiler.alloc_fn_idx));
                }
            }
        }

        func.instruction(&Instruction::Call(bi.wasm_fn_idx));
        true
    }

    /// Compile a Felt string expression into (ptr: i32, len: i32) on the stack.
    fn compile_string_arg(&self, expr: &Expr, func: &mut Function) {
        match expr {
            Expr::StringLit(s) => {
                if let Some((offset, len)) = self.compiler.string_literal_info(s) {
                    func.instruction(&Instruction::I32Const(offset as i32));
                    func.instruction(&Instruction::I32Const(len as i32));
                } else {
                    // String not in data section (shouldn't happen)
                    func.instruction(&Instruction::I32Const(0));
                    func.instruction(&Instruction::I32Const(0));
                }
            }
            _ => {
                // Runtime string value — for now, treat as a pointer with
                // unknown length. This handles the case where a string comes
                // from a previous builtin call (which returns a ptr).
                // We push ptr=value, len=0 as a placeholder.
                self.compile_expr(expr, func);
                func.instruction(&Instruction::I32Const(0));
            }
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
            Expr::StringLit(s) => {
                if let Some((offset, _)) = self.compiler.string_literal_info(s) {
                    func.instruction(&Instruction::I32Const(offset as i32));
                } else {
                    func.instruction(&Instruction::I32Const(0));
                }
            }
            Expr::NoneLit => {
                func.instruction(&Instruction::I64Const(0));
            }
            Expr::SomeWrap(inner) => {
                self.compile_expr(inner, func);
            }
            Expr::Ident(name) => {
                if let Some((idx, _)) = self.locals.get(name) {
                    func.instruction(&Instruction::LocalGet(*idx));
                } else if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                    func.instruction(&Instruction::I64Const(*fn_idx as i64));
                } else if self.compiler.builtin_info.contains_key(name) {
                    // Bare builtin reference without application — can't call
                    // without args. Emit a trap since this is a code path that
                    // requires partial application support.
                    func.instruction(&Instruction::Unreachable);
                } else {
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
            Expr::Apply(_, _) => {
                // Try builtin call first
                if self.try_compile_builtin_call(expr, func) {
                    return;
                }

                // Not a builtin — handle user function calls
                if let Expr::Apply(f_expr, arg) = expr {
                    // Direct function call: f(x)
                    if let Expr::Ident(name) = f_expr.as_ref() {
                        if let Some(fn_idx) = self.compiler.fn_indices.get(name) {
                            self.compile_expr(arg, func);
                            func.instruction(&Instruction::Call(*fn_idx));
                            return;
                        }
                    }
                    // Curried application: (f a) b
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
                    // Fallback: compile both sides
                    self.compile_expr(arg, func);
                    self.compile_expr(f_expr, func);
                    func.instruction(&Instruction::Drop);
                }
            }
            Expr::Match(scrutinee, arms) => {
                self.compile_expr(scrutinee, func);
                if let Some((match_idx, _)) = self.locals.get("__match") {
                    func.instruction(&Instruction::LocalSet(*match_idx));
                    self.compile_match_arms(arms, *match_idx, func);
                }
            }
            Expr::Lambda(_, body) => {
                self.compile_expr(body, func);
            }
            Expr::List(_) | Expr::Set(_) | Expr::Tuple(_) | Expr::Record(_) => {
                func.instruction(&Instruction::I64Const(0));
            }
            Expr::FieldAccess(_, _) => {
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
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I64Eqz);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
                self.compile_expr(body, func);
                func.instruction(&Instruction::Else);
                self.compile_match_arms(rest, match_local, func);
                func.instruction(&Instruction::End);
            }
            Pattern::SomePat(name) => {
                func.instruction(&Instruction::LocalGet(match_local));
                func.instruction(&Instruction::I64Const(0));
                func.instruction(&Instruction::I64Ne);
                func.instruction(&Instruction::If(wasm_encoder::BlockType::Result(result_type)));
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
        Type::String => ValType::I32,
        _ => ValType::I64,
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
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
        assert!(wasm.len() > 8);
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

    #[test]
    fn test_compile_builtin_import_emitted() {
        // A program that uses a builtin should produce WASM with an import section
        let wasm = compile_to_wasm("fn f(c: Component) -> Int = rank c");
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
        // The WASM should contain "baize" as the import module name
        let wasm_str = String::from_utf8_lossy(&wasm);
        assert!(wasm_str.contains("baize"), "WASM should contain 'baize' import module");
    }

    #[test]
    fn test_compile_no_imports_when_no_builtins() {
        // A program with no builtins should not have "baize" in the binary
        let wasm = compile_to_wasm("fn f(x: Int) -> Int = x + 1");
        // Check that "baize" does NOT appear as a raw string in the WASM
        let has_baize = wasm.windows(5).any(|w| w == b"baize");
        assert!(!has_baize, "WASM without builtins should not contain 'baize'");
    }

    #[test]
    fn test_compile_string_builtin() {
        // zone requires string argument — should produce imports
        let wasm = compile_to_wasm(r#"fn f(s: State) -> Zone = zone s "board""#);
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
        let has_baize = wasm.windows(5).any(|w| w == b"baize");
        assert!(has_baize, "zone builtin should produce 'baize' import");
    }

    #[test]
    fn test_compile_multiple_builtins() {
        let wasm = compile_to_wasm(
            "fn f(s: State) -> Int = turn s\nfn g(c: Component) -> Int = rank c",
        );
        assert!(wasm.starts_with(&[0x00, 0x61, 0x73, 0x6d]));
    }
}
