use crate::ast::*;
use crate::lexer::{Span, Spanned, Token};

pub struct Parser {
    tokens: Vec<Spanned>,
    pos: usize,
}

#[derive(Debug, Clone)]
pub struct ParseError {
    pub message: String,
    pub span: Span,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl Parser {
    pub fn new(tokens: Vec<Spanned>) -> Self {
        Self { tokens, pos: 0 }
    }

    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.pos).map(|s| &s.token)
    }

    fn peek_span(&self) -> Span {
        self.tokens
            .get(self.pos)
            .map(|s| s.span.clone())
            .unwrap_or_else(|| {
                let end = self.tokens.last().map(|s| s.span.end).unwrap_or(0);
                end..end
            })
    }

    fn advance(&mut self) -> &Spanned {
        let s = &self.tokens[self.pos];
        self.pos += 1;
        s
    }

    fn expect(&mut self, expected: &Token) -> Result<Span, ParseError> {
        match self.peek() {
            Some(t) if t == expected => {
                let span = self.tokens[self.pos].span.clone();
                self.pos += 1;
                Ok(span)
            }
            Some(t) => Err(ParseError {
                message: format!("expected {expected:?}, found {t:?}"),
                span: self.peek_span(),
            }),
            None => Err(ParseError {
                message: format!("expected {expected:?}, found end of input"),
                span: self.peek_span(),
            }),
        }
    }

    fn expect_ident(&mut self) -> Result<(String, Span), ParseError> {
        match self.peek() {
            Some(Token::Ident(_)) => {
                let s = self.advance();
                if let Token::Ident(name) = &s.token {
                    Ok((name.clone(), s.span.clone()))
                } else {
                    unreachable!()
                }
            }
            other => Err(ParseError {
                message: format!("expected identifier, found {other:?}"),
                span: self.peek_span(),
            }),
        }
    }

    pub fn parse_program(&mut self) -> Result<Program, ParseError> {
        let mut type_defs = Vec::new();
        let mut functions = Vec::new();

        while self.pos < self.tokens.len() {
            match self.peek() {
                Some(Token::Type) => type_defs.push(self.parse_type_def()?),
                Some(Token::Fn) => functions.push(self.parse_fn_def()?),
                _ => {
                    return Err(ParseError {
                        message: format!(
                            "expected 'fn' or 'type', found {:?}",
                            self.peek()
                        ),
                        span: self.peek_span(),
                    });
                }
            }
        }

        Ok(Program {
            type_defs,
            functions,
        })
    }

    fn parse_type_def(&mut self) -> Result<TypeDef, ParseError> {
        self.expect(&Token::Type)?;
        let (name, _) = self.expect_ident()?;
        self.expect(&Token::Assign)?;
        self.expect(&Token::LBrace)?;

        let mut fields = Vec::new();
        loop {
            if matches!(self.peek(), Some(Token::RBrace)) {
                break;
            }
            let (fname, _) = self.expect_ident()?;
            self.expect(&Token::Colon)?;
            let ftype = self.parse_type()?;
            fields.push((fname, ftype));
            if !matches!(self.peek(), Some(Token::Comma)) {
                break;
            }
            self.advance(); // consume comma
        }
        self.expect(&Token::RBrace)?;
        Ok(TypeDef { name, fields })
    }

    fn parse_fn_def(&mut self) -> Result<FnDef, ParseError> {
        let start = self.expect(&Token::Fn)?;
        let (name, _) = self.expect_ident()?;
        self.expect(&Token::LParen)?;

        let mut params = Vec::new();
        while !matches!(self.peek(), Some(Token::RParen)) {
            let (pname, _) = self.expect_ident()?;
            self.expect(&Token::Colon)?;
            let ptype = self.parse_type()?;
            params.push((pname, ptype));
            if !matches!(self.peek(), Some(Token::Comma)) {
                break;
            }
            self.advance(); // consume comma
        }
        self.expect(&Token::RParen)?;
        self.expect(&Token::Arrow)?;
        let return_type = self.parse_type()?;
        self.expect(&Token::Assign)?;

        let body = self.parse_expr()?;

        // Handle where clause
        let body = if matches!(self.peek(), Some(Token::Where)) {
            self.advance();
            let mut bindings = Vec::new();
            while matches!(self.peek(), Some(Token::Ident(_))) {
                // Check if this is a new fn/type or another where binding
                let save = self.pos;
                let (bname, _) = self.expect_ident()?;

                // where binding can have params: `name p1 p2 = expr`
                // These become lambdas: `name = \p1 -> \p2 -> expr`
                let mut lambda_params = Vec::new();
                while matches!(self.peek(), Some(Token::Ident(_))) {
                    let (p, _) = self.expect_ident()?;
                    lambda_params.push(p);
                }

                if !matches!(self.peek(), Some(Token::Assign)) {
                    // Not a where binding, rewind
                    self.pos = save;
                    break;
                }
                self.advance(); // consume =
                let mut val = self.parse_expr()?;

                // Wrap in lambdas for parameters (right to left)
                for p in lambda_params.into_iter().rev() {
                    val = Expr::Lambda(p, Box::new(val));
                }

                bindings.push((bname, val));
            }
            Expr::Let(bindings, Box::new(body))
        } else {
            body
        };

        let span = start.start..self.peek_span().start;
        Ok(FnDef {
            name,
            params,
            return_type,
            body,
            span,
        })
    }

    fn parse_type(&mut self) -> Result<Type, ParseError> {
        let base = self.parse_type_atom()?;
        // Check for function type: T -> T
        if matches!(self.peek(), Some(Token::Arrow)) {
            self.advance();
            let ret = self.parse_type()?;
            Ok(Type::Fn(Box::new(base), Box::new(ret)))
        } else {
            Ok(base)
        }
    }

    fn parse_type_atom(&mut self) -> Result<Type, ParseError> {
        match self.peek() {
            Some(Token::Ident(name)) => {
                let name = name.clone();
                self.advance();
                match name.as_str() {
                    "Int" => Ok(Type::Int),
                    "Float" => Ok(Type::Float),
                    "Bool" => Ok(Type::Bool),
                    "String" => Ok(Type::String),
                    "State" => Ok(Type::State),
                    "Zone" => Ok(Type::Zone),
                    "Cell" => Ok(Type::Cell),
                    "Component" => Ok(Type::Component),
                    "Player" => Ok(Type::Player),
                    "Action" => Ok(Type::Action),
                    "List" => {
                        let inner = self.parse_type_atom()?;
                        Ok(Type::List(Box::new(inner)))
                    }
                    "Set" => {
                        let inner = self.parse_type_atom()?;
                        Ok(Type::Set(Box::new(inner)))
                    }
                    "Map" => {
                        let k = self.parse_type_atom()?;
                        let v = self.parse_type_atom()?;
                        Ok(Type::Map(Box::new(k), Box::new(v)))
                    }
                    "Option" => {
                        let inner = self.parse_type_atom()?;
                        Ok(Type::Option(Box::new(inner)))
                    }
                    other => Ok(Type::Record(vec![(other.to_string(), Type::Int)])), // user-defined type ref
                }
            }
            Some(Token::LParen) => {
                self.advance();
                let first = self.parse_type()?;
                if matches!(self.peek(), Some(Token::Comma)) {
                    // Tuple type
                    let mut types = vec![first];
                    while matches!(self.peek(), Some(Token::Comma)) {
                        self.advance();
                        types.push(self.parse_type()?);
                    }
                    self.expect(&Token::RParen)?;
                    Ok(Type::Tuple(types))
                } else {
                    // Parenthesized type
                    self.expect(&Token::RParen)?;
                    Ok(first)
                }
            }
            Some(Token::LBrace) => {
                // Record type
                self.advance();
                let mut fields = Vec::new();
                loop {
                    if matches!(self.peek(), Some(Token::RBrace)) {
                        break;
                    }
                    let (fname, _) = self.expect_ident()?;
                    self.expect(&Token::Colon)?;
                    let ftype = self.parse_type()?;
                    fields.push((fname, ftype));
                    if !matches!(self.peek(), Some(Token::Comma)) {
                        break;
                    }
                    self.advance();
                }
                self.expect(&Token::RBrace)?;
                Ok(Type::Record(fields))
            }
            _ => Err(ParseError {
                message: format!("expected type, found {:?}", self.peek()),
                span: self.peek_span(),
            }),
        }
    }

    pub fn parse_expr(&mut self) -> Result<Expr, ParseError> {
        self.parse_pipe()
    }

    // Level 1: pipe (left-assoc) — desugars to Apply
    fn parse_pipe(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_or()?;
        while matches!(self.peek(), Some(Token::Pipe)) {
            self.advance();
            let func = self.parse_or()?;
            expr = Expr::Apply(Box::new(func), Box::new(expr));
        }
        Ok(expr)
    }

    // Level 2: or (left-assoc)
    fn parse_or(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_and()?;
        while matches!(self.peek(), Some(Token::Or)) {
            self.advance();
            let rhs = self.parse_and()?;
            expr = Expr::BinOp(BinOp::Or, Box::new(expr), Box::new(rhs));
        }
        Ok(expr)
    }

    // Level 3: and (left-assoc)
    fn parse_and(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_comparison()?;
        while matches!(self.peek(), Some(Token::And)) {
            self.advance();
            let rhs = self.parse_comparison()?;
            expr = Expr::BinOp(BinOp::And, Box::new(expr), Box::new(rhs));
        }
        Ok(expr)
    }

    // Level 4: comparison (non-associative)
    fn parse_comparison(&mut self) -> Result<Expr, ParseError> {
        let expr = self.parse_concat()?;
        let op = match self.peek() {
            Some(Token::Eq) => Some(BinOp::Eq),
            Some(Token::Neq) => Some(BinOp::Neq),
            Some(Token::Lt) => Some(BinOp::Lt),
            Some(Token::Gt) => Some(BinOp::Gt),
            Some(Token::Lte) => Some(BinOp::Lte),
            Some(Token::Gte) => Some(BinOp::Gte),
            _ => None,
        };
        if let Some(op) = op {
            self.advance();
            let rhs = self.parse_concat()?;
            Ok(Expr::BinOp(op, Box::new(expr), Box::new(rhs)))
        } else {
            Ok(expr)
        }
    }

    // Level 5: concat (right-assoc)
    fn parse_concat(&mut self) -> Result<Expr, ParseError> {
        let expr = self.parse_add()?;
        if matches!(self.peek(), Some(Token::PlusPlus)) {
            self.advance();
            let rhs = self.parse_concat()?; // right-recursive for right-assoc
            Ok(Expr::BinOp(BinOp::Concat, Box::new(expr), Box::new(rhs)))
        } else {
            Ok(expr)
        }
    }

    // Level 6: add/sub (left-assoc)
    fn parse_add(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_mul()?;
        loop {
            let op = match self.peek() {
                Some(Token::Plus) => Some(BinOp::Add),
                Some(Token::Minus) => Some(BinOp::Sub),
                _ => None,
            };
            if let Some(op) = op {
                self.advance();
                let rhs = self.parse_mul()?;
                expr = Expr::BinOp(op, Box::new(expr), Box::new(rhs));
            } else {
                break;
            }
        }
        Ok(expr)
    }

    // Level 7: mul/div/mod (left-assoc)
    fn parse_mul(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_unary()?;
        loop {
            let op = match self.peek() {
                Some(Token::Star) => Some(BinOp::Mul),
                Some(Token::Slash) => Some(BinOp::Div),
                Some(Token::Percent) => Some(BinOp::Mod),
                _ => None,
            };
            if let Some(op) = op {
                self.advance();
                let rhs = self.parse_unary()?;
                expr = Expr::BinOp(op, Box::new(expr), Box::new(rhs));
            } else {
                break;
            }
        }
        Ok(expr)
    }

    // Level 8: unary prefix (not, -)
    fn parse_unary(&mut self) -> Result<Expr, ParseError> {
        match self.peek() {
            Some(Token::Not) => {
                self.advance();
                let expr = self.parse_unary()?;
                Ok(Expr::UnOp(UnOp::Not, Box::new(expr)))
            }
            Some(Token::Minus) => {
                // Check if this is unary minus or binary minus
                // Unary if at start of expression or after operator/open paren
                self.advance();
                let expr = self.parse_unary()?;
                Ok(Expr::UnOp(UnOp::Neg, Box::new(expr)))
            }
            _ => self.parse_apply(),
        }
    }

    // Level 9: function application (left-assoc, juxtaposition)
    fn parse_apply(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_postfix()?;

        // Application: f a b c = ((f a) b) c
        // Only consume atoms that can start an argument
        while self.is_atom_start() {
            let arg = self.parse_postfix()?;
            expr = Expr::Apply(Box::new(expr), Box::new(arg));
        }
        Ok(expr)
    }

    fn is_atom_start(&self) -> bool {
        matches!(
            self.peek(),
            Some(
                Token::IntLit(_)
                    | Token::FloatLit(_)
                    | Token::StringLit(_)
                    | Token::Ident(_)
                    | Token::True
                    | Token::False
                    | Token::None_
                    | Token::Some_
                    | Token::LParen
                    | Token::LBracket
                    | Token::LBrace
                    | Token::Backslash
            )
        )
    }

    // Level 10: postfix field access (.field)
    fn parse_postfix(&mut self) -> Result<Expr, ParseError> {
        let mut expr = self.parse_atom()?;
        while matches!(self.peek(), Some(Token::Dot)) {
            self.advance();
            let (field, _) = self.expect_ident()?;
            expr = Expr::FieldAccess(Box::new(expr), field);
        }
        Ok(expr)
    }

    fn parse_atom(&mut self) -> Result<Expr, ParseError> {
        match self.peek() {
            Some(Token::IntLit(_)) => {
                let s = self.advance();
                if let Token::IntLit(n) = &s.token {
                    Ok(Expr::IntLit(*n))
                } else {
                    unreachable!()
                }
            }
            Some(Token::FloatLit(_)) => {
                let s = self.advance();
                if let Token::FloatLit(f) = &s.token {
                    Ok(Expr::FloatLit(*f))
                } else {
                    unreachable!()
                }
            }
            Some(Token::StringLit(_)) => {
                let s = self.advance();
                if let Token::StringLit(v) = &s.token {
                    Ok(Expr::StringLit(v.clone()))
                } else {
                    unreachable!()
                }
            }
            Some(Token::True) => {
                self.advance();
                Ok(Expr::BoolLit(true))
            }
            Some(Token::False) => {
                self.advance();
                Ok(Expr::BoolLit(false))
            }
            Some(Token::None_) => {
                self.advance();
                Ok(Expr::NoneLit)
            }
            Some(Token::Some_) => {
                self.advance();
                let inner = self.parse_postfix()?;
                Ok(Expr::SomeWrap(Box::new(inner)))
            }
            Some(Token::Ident(_)) => {
                let s = self.advance();
                if let Token::Ident(name) = &s.token {
                    Ok(Expr::Ident(name.clone()))
                } else {
                    unreachable!()
                }
            }
            Some(Token::LParen) => self.parse_paren_expr(),
            Some(Token::LBracket) => self.parse_list_or_comprehension(),
            Some(Token::LBrace) => self.parse_brace_expr(),
            Some(Token::Backslash) => self.parse_lambda(),
            Some(Token::Let) => self.parse_let(),
            Some(Token::If) => self.parse_if(),
            Some(Token::Match) => self.parse_match(),
            _ => Err(ParseError {
                message: format!("expected expression, found {:?}", self.peek()),
                span: self.peek_span(),
            }),
        }
    }

    fn parse_paren_expr(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume (

        // Check for partial application: (== val), (+ 1), etc.
        if let Some(op) = self.peek_binop_for_partial() {
            self.advance();
            let rhs = self.parse_expr()?;
            self.expect(&Token::RParen)?;
            return Ok(Expr::Lambda(
                "__x".to_string(),
                Box::new(Expr::BinOp(
                    op,
                    Box::new(Expr::Ident("__x".to_string())),
                    Box::new(rhs),
                )),
            ));
        }

        // Empty parens — unit/empty tuple
        if matches!(self.peek(), Some(Token::RParen)) {
            self.advance();
            return Ok(Expr::Tuple(vec![]));
        }

        let first = self.parse_expr()?;

        if matches!(self.peek(), Some(Token::Comma)) {
            // Tuple
            let mut items = vec![first];
            while matches!(self.peek(), Some(Token::Comma)) {
                self.advance();
                items.push(self.parse_expr()?);
            }
            self.expect(&Token::RParen)?;
            Ok(Expr::Tuple(items))
        } else {
            // Parenthesized expression
            self.expect(&Token::RParen)?;
            Ok(first)
        }
    }

    fn peek_binop_for_partial(&self) -> Option<BinOp> {
        match self.peek() {
            Some(Token::Eq) => Some(BinOp::Eq),
            Some(Token::Neq) => Some(BinOp::Neq),
            Some(Token::Lt) => Some(BinOp::Lt),
            Some(Token::Gt) => Some(BinOp::Gt),
            Some(Token::Lte) => Some(BinOp::Lte),
            Some(Token::Gte) => Some(BinOp::Gte),
            Some(Token::Plus) => Some(BinOp::Add),
            Some(Token::Minus) => Some(BinOp::Sub),
            Some(Token::Star) => Some(BinOp::Mul),
            Some(Token::Slash) => Some(BinOp::Div),
            Some(Token::Percent) => Some(BinOp::Mod),
            Some(Token::PlusPlus) => Some(BinOp::Concat),
            _ => None,
        }
    }

    fn parse_list_or_comprehension(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume [

        // Empty list
        if matches!(self.peek(), Some(Token::RBracket)) {
            self.advance();
            return Ok(Expr::List(vec![]));
        }

        let first = self.parse_expr()?;

        // Check for comprehension: [expr | var <- collection]
        if matches!(self.peek(), Some(Token::Bar)) {
            self.advance();
            return self.parse_comprehension_rest(first);
        }

        // Regular list
        let mut items = vec![first];
        while matches!(self.peek(), Some(Token::Comma)) {
            self.advance();
            items.push(self.parse_expr()?);
        }
        self.expect(&Token::RBracket)?;
        Ok(Expr::List(items))
    }

    fn parse_comprehension_rest(&mut self, map_expr: Expr) -> Result<Expr, ParseError> {
        // [map_expr | var <- collection, predicate]
        let (var, _) = self.expect_ident()?;
        self.expect(&Token::LeftArrow)?;
        let collection = self.parse_expr()?;

        let result = if matches!(self.peek(), Some(Token::Comma)) {
            self.advance();
            let predicate = self.parse_expr()?;
            // Desugar: collection |> filter (\var -> predicate) |> map (\var -> map_expr)
            let filtered = Expr::Apply(
                Box::new(Expr::Apply(
                    Box::new(Expr::Ident("filter".to_string())),
                    Box::new(Expr::Lambda(var.clone(), Box::new(predicate))),
                )),
                Box::new(collection),
            );
            Expr::Apply(
                Box::new(Expr::Apply(
                    Box::new(Expr::Ident("map".to_string())),
                    Box::new(Expr::Lambda(var, Box::new(map_expr))),
                )),
                Box::new(filtered),
            )
        } else {
            // No predicate, just map
            Expr::Apply(
                Box::new(Expr::Apply(
                    Box::new(Expr::Ident("map".to_string())),
                    Box::new(Expr::Lambda(var, Box::new(map_expr))),
                )),
                Box::new(collection),
            )
        };
        self.expect(&Token::RBracket)?;
        Ok(result)
    }

    fn parse_brace_expr(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume {

        // Empty set/record
        if matches!(self.peek(), Some(Token::RBrace)) {
            self.advance();
            return Ok(Expr::Set(vec![]));
        }

        // Peek ahead: if we see "ident =", it's a record. Otherwise, a set.
        if self.is_record_start() {
            self.parse_record_fields()
        } else {
            self.parse_set_elements()
        }
    }

    fn is_record_start(&self) -> bool {
        // Look at current and next: Ident followed by =
        if self.pos + 1 < self.tokens.len() {
            matches!(self.tokens[self.pos].token, Token::Ident(_))
                && matches!(self.tokens[self.pos + 1].token, Token::Assign)
        } else {
            false
        }
    }

    fn parse_record_fields(&mut self) -> Result<Expr, ParseError> {
        let mut fields = Vec::new();
        loop {
            if matches!(self.peek(), Some(Token::RBrace)) {
                break;
            }
            let (name, _) = self.expect_ident()?;
            self.expect(&Token::Assign)?;
            let val = self.parse_expr()?;
            fields.push((name, val));
            if !matches!(self.peek(), Some(Token::Comma)) {
                break;
            }
            self.advance();
        }
        self.expect(&Token::RBrace)?;
        Ok(Expr::Record(fields))
    }

    fn parse_set_elements(&mut self) -> Result<Expr, ParseError> {
        let mut items = Vec::new();
        loop {
            if matches!(self.peek(), Some(Token::RBrace)) {
                break;
            }
            items.push(self.parse_expr()?);
            if !matches!(self.peek(), Some(Token::Comma)) {
                break;
            }
            self.advance();
        }
        self.expect(&Token::RBrace)?;
        Ok(Expr::Set(items))
    }

    fn parse_lambda(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume backslash
        let mut params = Vec::new();
        while matches!(self.peek(), Some(Token::Ident(_))) {
            let (name, _) = self.expect_ident()?;
            params.push(name);
        }
        if params.is_empty() {
            return Err(ParseError {
                message: "expected parameter in lambda".to_string(),
                span: self.peek_span(),
            });
        }
        self.expect(&Token::Arrow)?;
        let body = self.parse_expr()?;

        // Desugar multi-param: \x y -> e  becomes  \x -> \y -> e
        let mut result = body;
        for param in params.into_iter().rev() {
            result = Expr::Lambda(param, Box::new(result));
        }
        Ok(result)
    }

    fn parse_let(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume let
        let mut bindings = Vec::new();

        loop {
            let (name, _) = self.expect_ident()?;
            self.expect(&Token::Assign)?;
            let val = self.parse_expr()?;
            bindings.push((name, val));

            // Check for more bindings (indented on next line, or same line)
            if !matches!(self.peek(), Some(Token::Ident(_)))
                || matches!(self.peek(), Some(Token::In))
            {
                break;
            }

            // Peek ahead to see if it's "name = expr" pattern
            if self.pos + 1 < self.tokens.len()
                && !matches!(self.tokens[self.pos + 1].token, Token::Assign)
            {
                break;
            }
        }

        self.expect(&Token::In)?;
        let body = self.parse_expr()?;
        Ok(Expr::Let(bindings, Box::new(body)))
    }

    fn parse_if(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume if
        let cond = self.parse_expr()?;
        self.expect(&Token::Then)?;
        let then_branch = self.parse_expr()?;
        self.expect(&Token::Else)?;
        let else_branch = self.parse_expr()?;
        Ok(Expr::If(
            Box::new(cond),
            Box::new(then_branch),
            Box::new(else_branch),
        ))
    }

    fn parse_match(&mut self) -> Result<Expr, ParseError> {
        self.advance(); // consume match
        let scrutinee = self.parse_expr()?;
        self.expect(&Token::With)?;

        let mut arms = Vec::new();
        while matches!(self.peek(), Some(Token::Bar)) {
            self.advance(); // consume |
            let pattern = self.parse_pattern()?;
            self.expect(&Token::Arrow)?;
            let body = self.parse_expr()?;
            arms.push((pattern, body));
        }

        if arms.is_empty() {
            return Err(ParseError {
                message: "expected at least one match arm".to_string(),
                span: self.peek_span(),
            });
        }

        Ok(Expr::Match(Box::new(scrutinee), arms))
    }

    fn parse_pattern(&mut self) -> Result<Pattern, ParseError> {
        match self.peek() {
            Some(Token::Underscore) => {
                self.advance();
                Ok(Pattern::Wildcard)
            }
            Some(Token::IntLit(_)) => {
                let s = self.advance();
                if let Token::IntLit(n) = &s.token {
                    Ok(Pattern::IntPat(*n))
                } else {
                    unreachable!()
                }
            }
            Some(Token::StringLit(_)) => {
                let s = self.advance();
                if let Token::StringLit(v) = &s.token {
                    Ok(Pattern::StringPat(v.clone()))
                } else {
                    unreachable!()
                }
            }
            Some(Token::True) => {
                self.advance();
                Ok(Pattern::BoolPat(true))
            }
            Some(Token::False) => {
                self.advance();
                Ok(Pattern::BoolPat(false))
            }
            Some(Token::None_) => {
                self.advance();
                Ok(Pattern::NonePat)
            }
            Some(Token::Some_) => {
                self.advance();
                let (name, _) = self.expect_ident()?;
                Ok(Pattern::SomePat(name))
            }
            Some(Token::Ident(_)) => {
                let (name, _) = self.expect_ident()?;
                Ok(Pattern::VarPat(name))
            }
            _ => Err(ParseError {
                message: format!("expected pattern, found {:?}", self.peek()),
                span: self.peek_span(),
            }),
        }
    }
}

pub fn parse(tokens: Vec<Spanned>) -> Result<Program, ParseError> {
    let mut parser = Parser::new(tokens);
    parser.parse_program()
}

pub fn parse_expr(tokens: Vec<Spanned>) -> Result<Expr, ParseError> {
    let mut parser = Parser::new(tokens);
    parser.parse_expr()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexer;

    fn expr(input: &str) -> Expr {
        let tokens = lexer::lex(input).expect("lex error");
        parse_expr(tokens).expect("parse error")
    }

    fn program(input: &str) -> Program {
        let tokens = lexer::lex(input).expect("lex error");
        parse(tokens).expect("parse error")
    }

    #[test]
    fn test_int_lit() {
        assert_eq!(expr("42"), Expr::IntLit(42));
    }

    #[test]
    fn test_float_lit() {
        assert_eq!(expr("3.14"), Expr::FloatLit(3.14));
    }

    #[test]
    fn test_bool_lit() {
        assert_eq!(expr("true"), Expr::BoolLit(true));
        assert_eq!(expr("false"), Expr::BoolLit(false));
    }

    #[test]
    fn test_string_lit() {
        assert_eq!(expr(r#""hello""#), Expr::StringLit("hello".into()));
    }

    #[test]
    fn test_ident() {
        assert_eq!(expr("x"), Expr::Ident("x".into()));
    }

    #[test]
    fn test_binop_precedence() {
        // x + y * z  should be  Add(x, Mul(y, z))
        assert_eq!(
            expr("x + y * z"),
            Expr::BinOp(
                BinOp::Add,
                Box::new(Expr::Ident("x".into())),
                Box::new(Expr::BinOp(
                    BinOp::Mul,
                    Box::new(Expr::Ident("y".into())),
                    Box::new(Expr::Ident("z".into())),
                )),
            )
        );
    }

    #[test]
    fn test_application() {
        // f a b  should be  Apply(Apply(f, a), b)
        assert_eq!(
            expr("f a b"),
            Expr::Apply(
                Box::new(Expr::Apply(
                    Box::new(Expr::Ident("f".into())),
                    Box::new(Expr::Ident("a".into())),
                )),
                Box::new(Expr::Ident("b".into())),
            )
        );
    }

    #[test]
    fn test_pipe_desugar() {
        // x |> f |> g  desugars to  Apply(g, Apply(f, x))
        assert_eq!(
            expr("x |> f |> g"),
            Expr::Apply(
                Box::new(Expr::Ident("g".into())),
                Box::new(Expr::Apply(
                    Box::new(Expr::Ident("f".into())),
                    Box::new(Expr::Ident("x".into())),
                )),
            )
        );
    }

    #[test]
    fn test_if_expr() {
        assert_eq!(
            expr("if true then 1 else 2"),
            Expr::If(
                Box::new(Expr::BoolLit(true)),
                Box::new(Expr::IntLit(1)),
                Box::new(Expr::IntLit(2)),
            )
        );
    }

    #[test]
    fn test_lambda() {
        // \x -> x + 1
        assert_eq!(
            expr(r"\x -> x + 1"),
            Expr::Lambda(
                "x".into(),
                Box::new(Expr::BinOp(
                    BinOp::Add,
                    Box::new(Expr::Ident("x".into())),
                    Box::new(Expr::IntLit(1)),
                )),
            )
        );
    }

    #[test]
    fn test_multi_param_lambda() {
        // \x y -> x + y  desugars to \x -> \y -> x + y
        assert_eq!(
            expr(r"\x y -> x + y"),
            Expr::Lambda(
                "x".into(),
                Box::new(Expr::Lambda(
                    "y".into(),
                    Box::new(Expr::BinOp(
                        BinOp::Add,
                        Box::new(Expr::Ident("x".into())),
                        Box::new(Expr::Ident("y".into())),
                    )),
                )),
            )
        );
    }

    #[test]
    fn test_let_expr() {
        assert_eq!(
            expr("let x = 1 in x"),
            Expr::Let(
                vec![("x".into(), Expr::IntLit(1))],
                Box::new(Expr::Ident("x".into())),
            )
        );
    }

    #[test]
    fn test_list_literal() {
        assert_eq!(
            expr("[1, 2, 3]"),
            Expr::List(vec![Expr::IntLit(1), Expr::IntLit(2), Expr::IntLit(3)]),
        );
    }

    #[test]
    fn test_empty_list() {
        assert_eq!(expr("[]"), Expr::List(vec![]));
    }

    #[test]
    fn test_set_literal() {
        assert_eq!(
            expr("{1, 2, 3}"),
            Expr::Set(vec![Expr::IntLit(1), Expr::IntLit(2), Expr::IntLit(3)]),
        );
    }

    #[test]
    fn test_record_literal() {
        assert_eq!(
            expr("{ x = 1, y = 2 }"),
            Expr::Record(vec![
                ("x".into(), Expr::IntLit(1)),
                ("y".into(), Expr::IntLit(2)),
            ]),
        );
    }

    #[test]
    fn test_field_access() {
        assert_eq!(
            expr("score.points"),
            Expr::FieldAccess(
                Box::new(Expr::Ident("score".into())),
                "points".into(),
            )
        );
    }

    #[test]
    fn test_tuple() {
        assert_eq!(
            expr("(1, 2)"),
            Expr::Tuple(vec![Expr::IntLit(1), Expr::IntLit(2)]),
        );
    }

    #[test]
    fn test_none_some() {
        assert_eq!(expr("None"), Expr::NoneLit);
        assert_eq!(
            expr("Some 42"),
            Expr::SomeWrap(Box::new(Expr::IntLit(42))),
        );
    }

    #[test]
    fn test_match_expr() {
        let result = expr(
            r#"match x with
            | 1 -> "one"
            | 2 -> "two"
            | _ -> "other""#,
        );
        assert_eq!(
            result,
            Expr::Match(
                Box::new(Expr::Ident("x".into())),
                vec![
                    (Pattern::IntPat(1), Expr::StringLit("one".into())),
                    (Pattern::IntPat(2), Expr::StringLit("two".into())),
                    (Pattern::Wildcard, Expr::StringLit("other".into())),
                ],
            )
        );
    }

    #[test]
    fn test_option_match() {
        let result = expr(
            r#"match cell_at board 3 4 with
            | Some c -> c
            | None -> x"#,
        );
        if let Expr::Match(_, arms) = result {
            assert_eq!(arms.len(), 2);
            assert_eq!(arms[0].0, Pattern::SomePat("c".into()));
            assert_eq!(arms[1].0, Pattern::NonePat);
        } else {
            panic!("expected match");
        }
    }

    #[test]
    fn test_partial_application() {
        // (== player) desugars to \__x -> __x == player
        assert_eq!(
            expr("(== player)"),
            Expr::Lambda(
                "__x".into(),
                Box::new(Expr::BinOp(
                    BinOp::Eq,
                    Box::new(Expr::Ident("__x".into())),
                    Box::new(Expr::Ident("player".into())),
                )),
            )
        );
    }

    #[test]
    fn test_partial_add() {
        // (+ 1) desugars to \__x -> __x + 1
        assert_eq!(
            expr("(+ 1)"),
            Expr::Lambda(
                "__x".into(),
                Box::new(Expr::BinOp(
                    BinOp::Add,
                    Box::new(Expr::Ident("__x".into())),
                    Box::new(Expr::IntLit(1)),
                )),
            )
        );
    }

    #[test]
    fn test_unary_not() {
        assert_eq!(
            expr("not true"),
            Expr::UnOp(UnOp::Not, Box::new(Expr::BoolLit(true))),
        );
    }

    #[test]
    fn test_unary_neg() {
        assert_eq!(
            expr("-42"),
            Expr::UnOp(UnOp::Neg, Box::new(Expr::IntLit(42))),
        );
    }

    #[test]
    fn test_list_comprehension() {
        // [rank c | c <- cards]  desugars to  map (\c -> rank c) cards
        let result = expr("[rank c | c <- cards]");
        match &result {
            Expr::Apply(f, collection) => {
                // outer: Apply(Apply(map, \c -> rank c), cards)
                if let Expr::Apply(map_fn, lambda) = f.as_ref() {
                    assert_eq!(**map_fn, Expr::Ident("map".into()));
                    assert!(matches!(lambda.as_ref(), Expr::Lambda(..)));
                } else {
                    panic!("expected Apply(map, lambda), got {f:?}");
                }
                assert_eq!(**collection, Expr::Ident("cards".into()));
            }
            _ => panic!("expected apply, got {result:?}"),
        }
    }

    #[test]
    fn test_comprehension_with_filter() {
        // [rank c | c <- cards, owner c == player]
        let result = expr("[rank c | c <- cards, owner c == player]");
        // Should be: map (\c -> rank c) (filter (\c -> owner c == player) cards)
        match &result {
            Expr::Apply(_, _) => {} // Just check it parses
            _ => panic!("expected apply, got {result:?}"),
        }
    }

    #[test]
    fn test_fn_def() {
        let prog = program("fn double(x: Int) -> Int = x * 2");
        assert_eq!(prog.functions.len(), 1);
        assert_eq!(prog.functions[0].name, "double");
        assert_eq!(prog.functions[0].params, vec![("x".into(), Type::Int)]);
        assert_eq!(prog.functions[0].return_type, Type::Int);
    }

    #[test]
    fn test_type_def() {
        let prog = program("type Score = { player: String, points: Int }");
        assert_eq!(prog.type_defs.len(), 1);
        assert_eq!(prog.type_defs[0].name, "Score");
        assert_eq!(prog.type_defs[0].fields.len(), 2);
    }

    #[test]
    fn test_complex_type() {
        let prog = program("fn f(xs: List Int, m: Map String Int) -> Option Bool = None");
        let f = &prog.functions[0];
        assert_eq!(f.params[0].1, Type::List(Box::new(Type::Int)));
        assert_eq!(
            f.params[1].1,
            Type::Map(Box::new(Type::String), Box::new(Type::Int))
        );
        assert_eq!(f.return_type, Type::Option(Box::new(Type::Bool)));
    }

    #[test]
    fn test_nested_if() {
        let result = expr("if x then if y then 1 else 2 else 3");
        match result {
            Expr::If(_, then_branch, _) => {
                assert!(matches!(*then_branch, Expr::If(..)));
            }
            _ => panic!("expected if"),
        }
    }

    #[test]
    fn test_concat_right_assoc() {
        // a ++ b ++ c  should be  Concat(a, Concat(b, c))
        assert_eq!(
            expr("a ++ b ++ c"),
            Expr::BinOp(
                BinOp::Concat,
                Box::new(Expr::Ident("a".into())),
                Box::new(Expr::BinOp(
                    BinOp::Concat,
                    Box::new(Expr::Ident("b".into())),
                    Box::new(Expr::Ident("c".into())),
                )),
            )
        );
    }

    #[test]
    fn test_where_clause() {
        let prog = program(
            "fn f(s: State) -> Int = x + 1 where x = 42",
        );
        let f = &prog.functions[0];
        match &f.body {
            Expr::Let(binds, body) => {
                assert_eq!(binds.len(), 1);
                assert_eq!(binds[0].0, "x");
                assert!(matches!(**body, Expr::BinOp(BinOp::Add, ..)));
            }
            _ => panic!("expected let from where desugar"),
        }
    }

    #[test]
    fn test_where_with_params() {
        let prog = program(
            "fn f(s: State) -> Int = g 1 where g x = x + 1",
        );
        let f = &prog.functions[0];
        match &f.body {
            Expr::Let(binds, _) => {
                assert_eq!(binds[0].0, "g");
                assert!(matches!(binds[0].1, Expr::Lambda(..)));
            }
            _ => panic!("expected let from where desugar"),
        }
    }

    #[test]
    fn test_pipe_with_lambda() {
        // cards |> filter (\c -> rank c > 10)
        let result = expr(r"cards |> filter (\c -> rank c > 10)");
        // Should be: Apply(Apply(filter, \c -> rank c > 10), cards)
        match &result {
            Expr::Apply(f, arg) => {
                assert_eq!(**arg, Expr::Ident("cards".into()));
                match f.as_ref() {
                    Expr::Apply(filter, _lambda) => {
                        assert_eq!(**filter, Expr::Ident("filter".into()));
                    }
                    _ => panic!("expected apply"),
                }
            }
            _ => panic!("expected apply"),
        }
    }

    #[test]
    fn test_and_or_precedence() {
        // a or b and c  should be  Or(a, And(b, c))
        assert_eq!(
            expr("a or b and c"),
            Expr::BinOp(
                BinOp::Or,
                Box::new(Expr::Ident("a".into())),
                Box::new(Expr::BinOp(
                    BinOp::And,
                    Box::new(Expr::Ident("b".into())),
                    Box::new(Expr::Ident("c".into())),
                )),
            )
        );
    }

    #[test]
    fn test_chained_field_access() {
        assert_eq!(
            expr("a.b.c"),
            Expr::FieldAccess(
                Box::new(Expr::FieldAccess(
                    Box::new(Expr::Ident("a".into())),
                    "b".into(),
                )),
                "c".into(),
            )
        );
    }

    #[test]
    fn test_function_type() {
        let prog = program("fn f(g: Int -> Bool) -> Bool = g 0");
        assert_eq!(
            prog.functions[0].params[0].1,
            Type::Fn(Box::new(Type::Int), Box::new(Type::Bool))
        );
    }

    #[test]
    fn test_tuple_type() {
        let prog = program("fn f(p: (Int, Int)) -> Int = fst p");
        assert_eq!(
            prog.functions[0].params[0].1,
            Type::Tuple(vec![Type::Int, Type::Int])
        );
    }

    #[test]
    fn test_multiple_fn_defs() {
        let prog = program(
            "fn f(x: Int) -> Int = x + 1\nfn g(x: Int) -> Int = x * 2",
        );
        assert_eq!(prog.functions.len(), 2);
        assert_eq!(prog.functions[0].name, "f");
        assert_eq!(prog.functions[1].name, "g");
    }
}
