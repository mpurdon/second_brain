//! HTTP helpers for Lambda functions.

use lambda_http::{Body, Response};
use serde::de::DeserializeOwned;
use serde::Serialize;

/// Standard API response wrapper.
#[derive(Debug, Serialize)]
pub struct ApiResponse<T> {
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
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

    pub fn error(message: impl Into<String>) -> ApiResponse<()> {
        ApiResponse {
            success: false,
            data: None,
            error: Some(message.into()),
        }
    }
}

/// Create a JSON response with the given status code and data.
pub fn json_response<T: Serialize>(status: u16, data: &T) -> Result<Response<Body>, lambda_http::Error> {
    Ok(Response::builder()
        .status(status)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_string(data)?))
        .expect("Failed to build response"))
}

/// Create an error response with the given status code and message.
pub fn error_response(status: u16, message: impl Into<String>) -> Result<Response<Body>, lambda_http::Error> {
    json_response(status, &ApiResponse::<()>::error(message))
}

/// Parse request body as JSON, returning a 400 response on failure.
///
/// Returns `Ok(Ok(T))` on successful parse, `Ok(Err(Response))` on parse error (400),
/// or `Err(lambda_http::Error)` on serialization failure.
pub fn parse_json_body<T: DeserializeOwned>(body: &Body) -> Result<Result<T, Response<Body>>, lambda_http::Error> {
    match serde_json::from_slice(body.as_ref()) {
        Ok(parsed) => Ok(Ok(parsed)),
        Err(e) => {
            let response = error_response(400, format!("Invalid request body: {}", e))?;
            Ok(Err(response))
        }
    }
}

/// Macro to parse request body, returning early with 400 on parse error.
///
/// Usage:
/// ```ignore
/// let request: MyRequest = parse_body!(event.body());
/// ```
#[macro_export]
macro_rules! parse_body {
    ($body:expr) => {
        match shared::http::parse_json_body($body)? {
            Ok(parsed) => parsed,
            Err(response) => return Ok(response),
        }
    };
}
