use crate::lexer::Span;

#[derive(Debug, Clone)]
pub struct FeltError {
    pub code: &'static str,
    pub message: String,
    pub span: Span,
}

impl std::fmt::Display for FeltError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for FeltError {}
