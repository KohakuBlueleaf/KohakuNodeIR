//! Errors raised by the KIR toolchain.

use std::fmt;

use crate::check::Diagnostic;

#[derive(Clone, Debug)]
pub enum KirError {
    Syntax {
        message: String,
        line: Option<usize>,
        column: Option<usize>,
    },
    /// A program failed the checker; holds every finding.
    Check(Vec<Diagnostic>),
    /// A signature file or `@use` library could not be loaded.
    Signature(String),
    /// A graph view (.kirgraph) is malformed.
    Graph(String),
    /// A value with no KIR literal or no JSON form.
    Value(String),
}

pub type Result<T> = std::result::Result<T, KirError>;

impl KirError {
    pub fn syntax(message: impl Into<String>, line: Option<usize>, column: Option<usize>) -> KirError {
        KirError::Syntax { message: message.into(), line, column }
    }

    /// The error class name of the Python reference.
    pub fn kind(&self) -> &'static str {
        match self {
            KirError::Syntax { .. } => "KirSyntaxError",
            KirError::Check(_) => "KirCheckError",
            KirError::Signature(_) => "KirSignatureError",
            KirError::Graph(_) => "KirGraphError",
            KirError::Value(_) => "ValueError",
        }
    }
}

impl fmt::Display for KirError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            KirError::Syntax { message, line: Some(line), column } => {
                let column = column.map_or("None".to_string(), |c| c.to_string());
                write!(f, "{message} (line {line}, column {column})")
            }
            KirError::Syntax { message, .. } => write!(f, "{message}"),
            KirError::Check(diags) => {
                let errors: Vec<String> = diags.iter().filter(|d| d.is_error()).map(|d| d.to_string()).collect();
                write!(f, "{}", errors.join("\n"))
            }
            KirError::Signature(m) | KirError::Graph(m) | KirError::Value(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for KirError {}
