//! Shared data models.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// User context extracted from JWT.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserContext {
    pub user_id: Uuid,
    pub email: String,
    pub family_ids: Vec<Uuid>,
}

/// Standard API response wrapper.
#[derive(Debug, Serialize)]
pub struct ApiResponse<T> {
    pub success: bool,
    pub data: Option<T>,
    pub error: Option<String>,
}

impl<T> ApiResponse<T> {
    pub fn success(data: T) -> Self {
        Self {
            success: true,
            data: Some(data),
            error: None,
        }
    }

    pub fn error(message: impl Into<String>) -> Self {
        Self {
            success: false,
            data: None,
            error: Some(message.into()),
        }
    }
}

/// Query request payload.
#[derive(Debug, Deserialize)]
pub struct QueryRequest {
    pub query: String,
    pub session_id: Option<String>,
}

/// Query response payload.
#[derive(Debug, Serialize)]
pub struct QueryResponse {
    pub response: String,
    pub session_id: String,
    pub agents_used: Vec<String>,
}

/// Ingest request payload.
#[derive(Debug, Deserialize)]
pub struct IngestRequest {
    pub content: String,
    pub visibility_tier: Option<i16>,
}

/// Ingest response payload.
#[derive(Debug, Serialize)]
pub struct IngestResponse {
    pub fact_id: Uuid,
    pub message: String,
    pub entities_created: Vec<String>,
}
