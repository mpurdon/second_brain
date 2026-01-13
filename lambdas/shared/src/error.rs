//! Error types for Second Brain Lambda functions.

use thiserror::Error;

/// Result type alias using our Error type.
pub type Result<T> = std::result::Result<T, Error>;

/// Errors that can occur in Second Brain Lambda functions.
#[derive(Error, Debug)]
pub enum Error {
    /// Database error
    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),

    /// AWS SDK error
    #[error("AWS error: {0}")]
    Aws(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    Config(String),

    /// Validation error
    #[error("Validation error: {0}")]
    Validation(String),

    /// Authentication error
    #[error("Authentication error: {0}")]
    Auth(String),

    /// Authorization error
    #[error("Authorization error: {0}")]
    Unauthorized(String),

    /// Not found error
    #[error("Not found: {0}")]
    NotFound(String),

    /// Serialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Internal error
    #[error("Internal error: {0}")]
    Internal(String),
}

impl Error {
    /// Get HTTP status code for this error.
    pub fn status_code(&self) -> u16 {
        match self {
            Error::Validation(_) => 400,
            Error::Auth(_) => 401,
            Error::Unauthorized(_) => 403,
            Error::NotFound(_) => 404,
            _ => 500,
        }
    }
}
