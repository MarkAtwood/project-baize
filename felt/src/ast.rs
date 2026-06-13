use crate::lexer::Span;

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    IntLit(i64),
    FloatLit(f64),
    BoolLit(bool),
    StringLit(String),
    Ident(String),
    Apply(Box<Expr>, Box<Expr>),
    Lambda(String, Box<Expr>),
    Let(Vec<(String, Expr)>, Box<Expr>),
    If(Box<Expr>, Box<Expr>, Box<Expr>),
    Match(Box<Expr>, Vec<(Pattern, Expr)>),
    BinOp(BinOp, Box<Expr>, Box<Expr>),
    UnOp(UnOp, Box<Expr>),
    List(Vec<Expr>),
    Set(Vec<Expr>),
    Record(Vec<(String, Expr)>),
    FieldAccess(Box<Expr>, String),
    Tuple(Vec<Expr>),
    NoneLit,
    SomeWrap(Box<Expr>),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Pattern {
    Wildcard,
    IntPat(i64),
    StringPat(String),
    BoolPat(bool),
    NonePat,
    SomePat(String),
    VarPat(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Eq,
    Neq,
    Lt,
    Gt,
    Lte,
    Gte,
    And,
    Or,
    Concat,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnOp {
    Neg,
    Not,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Type {
    Int,
    Float,
    Bool,
    String,
    State,
    Zone,
    Cell,
    Component,
    Player,
    Action,
    List(Box<Type>),
    Set(Box<Type>),
    Map(Box<Type>, Box<Type>),
    Option(Box<Type>),
    Tuple(Vec<Type>),
    Record(Vec<(String, Type)>),
    Fn(Box<Type>, Box<Type>),
    /// Type variable used internally by the checker for polymorphic builtins.
    /// Not parsed from user source — only created in register_builtins.
    Var(u8),
}

#[derive(Debug, Clone, PartialEq)]
pub struct TypeDef {
    pub name: String,
    pub fields: Vec<(String, Type)>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FnDef {
    pub name: String,
    pub params: Vec<(String, Type)>,
    pub return_type: Type,
    pub body: Expr,
    pub span: Span,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Program {
    pub type_defs: Vec<TypeDef>,
    pub functions: Vec<FnDef>,
}
