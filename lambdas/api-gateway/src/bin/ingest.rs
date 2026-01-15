//! Ingest Lambda - Handles /v1/ingest endpoint.
//!
//! This Lambda processes fact ingestion requests from API Gateway, validates the user's
//! JWT token, and invokes the Python agent system to store the fact.

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, RequestPayloadExt, Response};
use shared::{
    extract_user_from_context, AgentClient, ApiResponse, IngestRequest, IngestResponse,
};
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Application state shared across requests.
struct AppState {
    agent_client: AgentClient,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let lambda_client = aws_sdk_lambda::Client::new(&config);

        let agent_function = std::env::var("AGENT_FUNCTION_NAME")
            .unwrap_or_else(|_| "second-brain-agents".to_string());

        Ok(Self {
            agent_client: AgentClient::new(lambda_client, agent_function),
        })
    }
}

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    // Extract user from request context (set by Cognito authorizer)
    let user = match event.request_context_ref() {
        Some(ctx) => {
            if let Some(authorizer) = ctx.authorizer() {
                let claims = authorizer.fields.get("claims");
                if let Some(claims) = claims {
                    match extract_user_from_context(claims) {
                        Ok(user) => user,
                        Err(e) => {
                            error!("Failed to extract user: {}", e);
                            return Ok(error_response(401, "Authentication required"));
                        }
                    }
                } else {
                    return Ok(error_response(401, "Authentication required"));
                }
            } else {
                return Ok(error_response(401, "Authentication required"));
            }
        }
        None => return Ok(error_response(401, "Authentication required")),
    };

    info!("Processing ingestion for user: {}", user.user_id);

    // Parse request body
    let request: IngestRequest = match event.payload() {
        Ok(Some(req)) => req,
        Ok(None) => return Ok(error_response(400, "Missing request body")),
        Err(e) => return Ok(error_response(400, &format!("Invalid request: {}", e))),
    };

    // Validate content
    if request.content.trim().is_empty() {
        return Ok(error_response(400, "Content cannot be empty"));
    }

    // Build the message for the agent
    // Include visibility tier if specified
    let message = if let Some(tier) = request.visibility_tier {
        format!(
            "Remember this (visibility tier {}): {}",
            tier, request.content
        )
    } else {
        format!("Remember this: {}", request.content)
    };

    // Invoke agent system for ingestion
    let agent_response = match state
        .agent_client
        .ingest(&message, &user.user_id, user.family_ids.clone(), "api")
        .await
    {
        Ok(resp) => resp,
        Err(e) => {
            error!("Agent invocation failed: {}", e);
            return Ok(error_response(500, "Failed to store fact"));
        }
    };

    // Build response
    // In a real implementation, we'd parse the agent response to extract fact_id and entities
    let response_body = ApiResponse::success(IngestResponse {
        fact_id: Uuid::new_v4(), // TODO: Extract from agent response
        message: agent_response.response,
        entities_created: vec![], // TODO: Extract from agent response
    });

    let body = serde_json::to_string(&response_body)?;

    Ok(Response::builder()
        .status(201)
        .header("content-type", "application/json")
        .body(Body::from(body))
        .expect("Failed to build response"))
}

fn error_response(status: u16, message: &str) -> Response<Body> {
    let body = serde_json::to_string(&ApiResponse::<()>::error(message))
        .unwrap_or_else(|_| r#"{"success":false,"error":"Internal error"}"#.to_string());

    Response::builder()
        .status(status)
        .header("content-type", "application/json")
        .body(Body::from(body))
        .expect("Failed to build error response")
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    let state = Arc::new(AppState::new().await?);

    run(service_fn(move |event| {
        let state = Arc::clone(&state);
        async move { handler(state, event).await }
    }))
    .await
}
