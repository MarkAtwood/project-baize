use logos::Logos;

#[derive(Logos, Debug, Clone, PartialEq)]
#[logos(skip(r"--[^\n]*", allow_greedy = true))]
#[logos(skip r"[ \t\n\r]+")]
pub enum Token {
    // Keywords
    #[token("fn")]
    Fn,
    #[token("let")]
    Let,
    #[token("in")]
    In,
    #[token("if")]
    If,
    #[token("then")]
    Then,
    #[token("else")]
    Else,
    #[token("match")]
    Match,
    #[token("with")]
    With,
    #[token("where")]
    Where,
    #[token("true")]
    True,
    #[token("false")]
    False,
    #[token("not")]
    Not,
    #[token("and")]
    And,
    #[token("or")]
    Or,
    #[token("type")]
    Type,
    #[token("None")]
    None_,
    #[token("Some")]
    Some_,

    // Multi-char operators (must come before single-char variants)
    #[token("|>")]
    Pipe,
    #[token("->")]
    Arrow,
    #[token("<-")]
    LeftArrow,
    #[token("==")]
    Eq,
    #[token("!=")]
    Neq,
    #[token(">=")]
    Gte,
    #[token("<=")]
    Lte,
    #[token("++")]
    PlusPlus,

    // Single-char operators
    #[token(">")]
    Gt,
    #[token("<")]
    Lt,
    #[token("+")]
    Plus,
    #[token("-")]
    Minus,
    #[token("*")]
    Star,
    #[token("/")]
    Slash,
    #[token("%")]
    Percent,
    #[token("\\")]
    Backslash,
    #[token("|")]
    Bar,
    #[token("=")]
    Assign,
    #[token(".")]
    Dot,

    // Punctuation
    #[token("(")]
    LParen,
    #[token(")")]
    RParen,
    #[token("[")]
    LBracket,
    #[token("]")]
    RBracket,
    #[token("{")]
    LBrace,
    #[token("}")]
    RBrace,
    #[token(",")]
    Comma,
    #[token(":")]
    Colon,
    #[token("_")]
    Underscore,

    // Literals — float before int so "3.14" matches float, not "3" + ".14"
    #[regex(r"[0-9]+\.[0-9]+", |lex| lex.slice().parse::<f64>().ok())]
    FloatLit(f64),
    #[regex(r"[0-9]+", |lex| lex.slice().parse::<i64>().ok())]
    IntLit(i64),
    #[regex(r#""[^"]*""#, |lex| {
        let s = lex.slice();
        Some(s[1..s.len()-1].to_string())
    })]
    StringLit(String),

    // Identifiers — logos gives priority to #[token] over #[regex] for same-length matches,
    // so keywords like "fn" won't be captured here.
    #[regex(r"[a-zA-Z][a-zA-Z0-9_]*", |lex| Some(lex.slice().to_string()))]
    Ident(String),
}

pub type Span = std::ops::Range<usize>;

#[derive(Debug, Clone)]
pub struct Spanned {
    pub token: Token,
    pub span: Span,
}

pub fn lex(source: &str) -> Result<Vec<Spanned>, Vec<LexError>> {
    let mut tokens = Vec::new();
    let mut errors = Vec::new();
    let lexer = Token::lexer(source);

    for (result, span) in lexer.spanned() {
        match result {
            Ok(token) => tokens.push(Spanned {
                token,
                span: span.clone(),
            }),
            Err(()) => errors.push(LexError {
                span: span.clone(),
                message: format!(
                    "unexpected character '{}'",
                    &source[span.start..span.end]
                ),
            }),
        }
    }

    if errors.is_empty() {
        Ok(tokens)
    } else {
        Err(errors)
    }
}

#[derive(Debug, Clone)]
pub struct LexError {
    pub span: Span,
    pub message: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tok(input: &str) -> Vec<Token> {
        lex(input).expect("lexer error").into_iter().map(|s| s.token).collect()
    }

    #[test]
    fn test_fn_definition() {
        assert_eq!(
            tok("fn f(x: Int) -> Int = x + 1"),
            vec![
                Token::Fn,
                Token::Ident("f".into()),
                Token::LParen,
                Token::Ident("x".into()),
                Token::Colon,
                Token::Ident("Int".into()),
                Token::RParen,
                Token::Arrow,
                Token::Ident("Int".into()),
                Token::Assign,
                Token::Ident("x".into()),
                Token::Plus,
                Token::IntLit(1),
            ]
        );
    }

    #[test]
    fn test_pipe() {
        assert_eq!(
            tok("x |> map f"),
            vec![
                Token::Ident("x".into()),
                Token::Pipe,
                Token::Ident("map".into()),
                Token::Ident("f".into()),
            ]
        );
    }

    #[test]
    fn test_lambda() {
        assert_eq!(
            tok(r"\x -> x + 1"),
            vec![
                Token::Backslash,
                Token::Ident("x".into()),
                Token::Arrow,
                Token::Ident("x".into()),
                Token::Plus,
                Token::IntLit(1),
            ]
        );
    }

    #[test]
    fn test_comment() {
        assert_eq!(tok("-- comment\n42"), vec![Token::IntLit(42)]);
    }

    #[test]
    fn test_string_lit() {
        assert_eq!(tok(r#""hello""#), vec![Token::StringLit("hello".into())]);
    }

    #[test]
    fn test_float_lit() {
        assert_eq!(tok("3.14"), vec![Token::FloatLit(3.14)]);
    }

    #[test]
    fn test_bool_and_or() {
        assert_eq!(
            tok("true and false"),
            vec![Token::True, Token::And, Token::False]
        );
    }

    #[test]
    fn test_match() {
        assert_eq!(
            tok(r#"match x with | 1 -> "a""#),
            vec![
                Token::Match,
                Token::Ident("x".into()),
                Token::With,
                Token::Bar,
                Token::IntLit(1),
                Token::Arrow,
                Token::StringLit("a".into()),
            ]
        );
    }

    #[test]
    fn test_empty_input() {
        assert_eq!(tok(""), Vec::<Token>::new());
    }

    #[test]
    fn test_only_comments() {
        assert_eq!(tok("-- just a comment\n-- another"), Vec::<Token>::new());
    }

    #[test]
    fn test_adjacent_pipes() {
        assert_eq!(
            tok("|>|>"),
            vec![Token::Pipe, Token::Pipe]
        );
    }

    #[test]
    fn test_keywords_not_identifiers() {
        assert_eq!(tok("fn"), vec![Token::Fn]);
        assert_eq!(tok("let"), vec![Token::Let]);
        assert_eq!(tok("None"), vec![Token::None_]);
        assert_eq!(tok("Some"), vec![Token::Some_]);
        assert_eq!(tok("type"), vec![Token::Type]);
    }

    #[test]
    fn test_identifier_with_keyword_prefix() {
        // "fns" should be an identifier, not Fn + "s"
        assert_eq!(tok("fns"), vec![Token::Ident("fns".into())]);
        assert_eq!(tok("letter"), vec![Token::Ident("letter".into())]);
        assert_eq!(tok("matching"), vec![Token::Ident("matching".into())]);
    }

    #[test]
    fn test_all_comparison_ops() {
        assert_eq!(
            tok("== != < > <= >="),
            vec![Token::Eq, Token::Neq, Token::Lt, Token::Gt, Token::Lte, Token::Gte]
        );
    }

    #[test]
    fn test_concat_op() {
        assert_eq!(tok("++"), vec![Token::PlusPlus]);
    }

    #[test]
    fn test_left_arrow() {
        assert_eq!(
            tok("x <- xs"),
            vec![Token::Ident("x".into()), Token::LeftArrow, Token::Ident("xs".into())]
        );
    }

    #[test]
    fn test_record_syntax() {
        assert_eq!(
            tok("{ x = 1, y = 2 }"),
            vec![
                Token::LBrace,
                Token::Ident("x".into()),
                Token::Assign,
                Token::IntLit(1),
                Token::Comma,
                Token::Ident("y".into()),
                Token::Assign,
                Token::IntLit(2),
                Token::RBrace,
            ]
        );
    }

    #[test]
    fn test_underscore() {
        assert_eq!(tok("_"), vec![Token::Underscore]);
    }

    #[test]
    fn test_set_literal() {
        assert_eq!(
            tok("{1, 2, 3}"),
            vec![
                Token::LBrace,
                Token::IntLit(1),
                Token::Comma,
                Token::IntLit(2),
                Token::Comma,
                Token::IntLit(3),
                Token::RBrace,
            ]
        );
    }

    #[test]
    fn test_list_comprehension() {
        assert_eq!(
            tok("[x | x <- xs]"),
            vec![
                Token::LBracket,
                Token::Ident("x".into()),
                Token::Bar,
                Token::Ident("x".into()),
                Token::LeftArrow,
                Token::Ident("xs".into()),
                Token::RBracket,
            ]
        );
    }

    #[test]
    fn test_where_clause() {
        assert_eq!(
            tok("where x = 1"),
            vec![
                Token::Where,
                Token::Ident("x".into()),
                Token::Assign,
                Token::IntLit(1),
            ]
        );
    }

    #[test]
    fn test_dot_access() {
        assert_eq!(
            tok("score.points"),
            vec![
                Token::Ident("score".into()),
                Token::Dot,
                Token::Ident("points".into()),
            ]
        );
    }

    #[test]
    fn test_negative_number() {
        // Minus is a separate token; parser handles negation
        assert_eq!(
            tok("-42"),
            vec![Token::Minus, Token::IntLit(42)]
        );
    }

    #[test]
    fn test_complex_expression() {
        assert_eq!(
            tok("if x > 0 then x else -x"),
            vec![
                Token::If,
                Token::Ident("x".into()),
                Token::Gt,
                Token::IntLit(0),
                Token::Then,
                Token::Ident("x".into()),
                Token::Else,
                Token::Minus,
                Token::Ident("x".into()),
            ]
        );
    }

    #[test]
    fn test_spans() {
        let tokens = lex("fn f").unwrap();
        assert_eq!(tokens[0].span, 0..2);
        assert_eq!(tokens[1].span, 3..4);
    }
}
