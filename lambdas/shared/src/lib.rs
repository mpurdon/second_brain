//! Shared library for Second Brain Lambda functions.
//!
//! This crate provides common utilities, types, and clients used across all Lambda functions.

pub mod agents;
pub mod auth;
pub mod config;
pub mod db;
pub mod error;
pub mod models;
pub mod secrets;
pub mod tts;

pub use agents::{AgentClient, AgentRequest, AgentResponse};
pub use auth::{validate_token, extract_user_from_context, AuthenticatedUser, CognitoClaims};
pub use config::Config;
pub use error::{Error, Result};
pub use models::{ApiResponse, QueryRequest, QueryResponse, IngestRequest, IngestResponse, UserContext};
pub use secrets::{get_secret, get_database_credentials, DatabaseCredentials};
pub use tts::{TtsService, TtsError};
