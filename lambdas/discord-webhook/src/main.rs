//! Discord Webhook Lambda - Handles Discord bot interactions.
//!
//! This Lambda handles incoming Discord interaction webhooks, verifies signatures,
//! processes slash commands, and invokes the agent system.
//!
//! Uses deferred responses to handle Discord's 3-second timeout requirement.

use aws_sdk_lambda::primitives::Blob;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use lambda_runtime::{service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use shared::AgentClient;
use std::sync::Arc;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;

/// Discord interaction types
const INTERACTION_PING: u8 = 1;
const INTERACTION_APPLICATION_COMMAND: u8 = 2;

/// Discord response types
const RESPONSE_PONG: u8 = 1;
const RESPONSE_CHANNEL_MESSAGE: u8 = 4;
const RESPONSE_DEFERRED_CHANNEL_MESSAGE: u8 = 5;

/// Discord interaction request
#[derive(Debug, Deserialize, Clone)]
struct DiscordInteraction {
    #[serde(rename = "type")]
    interaction_type: u8,
    token: Option<String>,
    data: Option<InteractionData>,
    member: Option<GuildMember>,
    user: Option<DiscordUser>,
    application_id: Option<String>,
}

/// Discord interaction data (for slash commands)
#[derive(Debug, Deserialize, Clone)]
struct InteractionData {
    name: String,
    options: Option<Vec<CommandOption>>,
}

/// Discord command option
#[derive(Debug, Deserialize, Clone)]
struct CommandOption {
    name: String,
    value: serde_json::Value,
}

/// Discord guild member
#[derive(Debug, Deserialize, Clone)]
struct GuildMember {
    user: DiscordUser,
}

/// Discord user
#[derive(Debug, Deserialize, Clone)]
struct DiscordUser {
    id: String,
    username: String,
}

/// Discord interaction response
#[derive(Debug, Serialize)]
struct DiscordResponse {
    #[serde(rename = "type")]
    response_type: u8,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: Option<ResponseData>,
}

/// Discord response data
#[derive(Debug, Serialize)]
struct ResponseData {
    content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    flags: Option<u32>,
}

/// Payload for async follow-up processing
#[derive(Debug, Serialize, Deserialize)]
struct FollowUpPayload {
    follow_up: bool,
    application_id: String,
    interaction_token: String,
    command_name: String,
    message: String,
    user_id: String,
    username: String,
}

/// API Gateway proxy request (simplified)
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ApiGatewayRequest {
    headers: Option<std::collections::HashMap<String, String>>,
    body: Option<String>,
    is_base64_encoded: Option<bool>,
}

/// API Gateway proxy response
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ApiGatewayResponse {
    status_code: u16,
    headers: std::collections::HashMap<String, String>,
    body: String,
    is_base64_encoded: bool,
}

impl ApiGatewayResponse {
    fn new(status_code: u16, body: &str, content_type: &str) -> Self {
        let mut headers = std::collections::HashMap::new();
        headers.insert("content-type".to_string(), content_type.to_string());
        Self {
            status_code,
            headers,
            body: body.to_string(),
            is_base64_encoded: false,
        }
    }

    fn json<T: Serialize>(status_code: u16, data: &T) -> Result<Self, Error> {
        let body = serde_json::to_string(data)?;
        Ok(Self::new(status_code, &body, "application/json"))
    }
}

/// Application state
struct AppState {
    agent_client: AgentClient,
    lambda_client: aws_sdk_lambda::Client,
    http_client: reqwest::Client,
    discord_public_key: VerifyingKey,
    function_name: String,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let lambda_client = aws_sdk_lambda::Client::new(&config);

        let agent_function = std::env::var("AGENT_FUNCTION_NAME")
            .unwrap_or_else(|_| "second-brain-agents".to_string());

        let function_name = std::env::var("AWS_LAMBDA_FUNCTION_NAME")
            .unwrap_or_else(|_| "second-brain-discord-webhook".to_string());

        let public_key_hex = std::env::var("DISCORD_PUBLIC_KEY")
            .map_err(|_| "DISCORD_PUBLIC_KEY not set")?;

        let public_key_bytes = hex::decode(&public_key_hex)
            .map_err(|e| format!("Invalid public key hex: {}", e))?;

        let public_key: [u8; 32] = public_key_bytes
            .try_into()
            .map_err(|_| "Public key must be 32 bytes")?;

        let verifying_key = VerifyingKey::from_bytes(&public_key)
            .map_err(|e| format!("Invalid public key: {}", e))?;

        Ok(Self {
            agent_client: AgentClient::new(lambda_client.clone(), agent_function),
            lambda_client,
            http_client: reqwest::Client::new(),
            discord_public_key: verifying_key,
            function_name,
        })
    }

    /// Send follow-up message to Discord via webhook
    async fn send_follow_up(
        &self,
        application_id: &str,
        interaction_token: &str,
        content: &str,
    ) -> Result<(), Error> {
        let url = format!(
            "https://discord.com/api/v10/webhooks/{}/{}/messages/@original",
            application_id, interaction_token
        );

        let payload = serde_json::json!({
            "content": content
        });

        let response = self
            .http_client
            .patch(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("Failed to send follow-up: {}", e))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            error!("Discord webhook failed: {} - {}", status, body);
            return Err(format!("Discord webhook failed: {}", status).into());
        }

        info!("Follow-up message sent successfully");
        Ok(())
    }

    /// Invoke self asynchronously for follow-up processing
    async fn invoke_follow_up(&self, payload: &FollowUpPayload) -> Result<(), Error> {
        let payload_json = serde_json::to_vec(payload)?;

        self.lambda_client
            .invoke()
            .function_name(&self.function_name)
            .invocation_type(aws_sdk_lambda::types::InvocationType::Event)
            .payload(Blob::new(payload_json))
            .send()
            .await
            .map_err(|e| format!("Failed to invoke follow-up: {}", e))?;

        info!("Follow-up invocation triggered");
        Ok(())
    }
}

/// Verify Discord signature
fn verify_signature(
    public_key: &VerifyingKey,
    signature_hex: &str,
    timestamp: &str,
    body: &str,
) -> bool {
    let signature_bytes = match hex::decode(signature_hex) {
        Ok(bytes) => bytes,
        Err(_) => return false,
    };

    let signature: [u8; 64] = match signature_bytes.try_into() {
        Ok(sig) => sig,
        Err(_) => return false,
    };

    let signature = Signature::from_bytes(&signature);

    let message = format!("{}{}", timestamp, body);
    public_key.verify(message.as_bytes(), &signature).is_ok()
}

async fn handler(state: Arc<AppState>, event: LambdaEvent<Value>) -> Result<Value, Error> {
    let (payload, _context) = event.into_parts();

    // Check if this is a direct follow-up invocation (not from API Gateway)
    if let Ok(follow_up) = serde_json::from_value::<FollowUpPayload>(payload.clone()) {
        if follow_up.follow_up {
            info!(
                "Processing follow-up for command '{}' from user {}",
                follow_up.command_name, follow_up.username
            );
            return handle_follow_up(state, follow_up).await;
        }
    }

    // This is an API Gateway request
    let api_request: ApiGatewayRequest = serde_json::from_value(payload)?;

    // Get the body
    let body_str = api_request.body.unwrap_or_default();

    // Get signature headers (case-insensitive)
    let headers = api_request.headers.unwrap_or_default();
    let signature = headers
        .iter()
        .find(|(k, _)| k.to_lowercase() == "x-signature-ed25519")
        .map(|(_, v)| v.as_str())
        .unwrap_or("");
    let timestamp = headers
        .iter()
        .find(|(k, _)| k.to_lowercase() == "x-signature-timestamp")
        .map(|(_, v)| v.as_str())
        .unwrap_or("");

    // Verify signature
    if !verify_signature(&state.discord_public_key, signature, timestamp, &body_str) {
        warn!("Invalid Discord signature");
        return Ok(serde_json::to_value(ApiGatewayResponse::new(
            401,
            "Invalid signature",
            "text/plain",
        ))?);
    }

    // Parse interaction
    let interaction: DiscordInteraction = match serde_json::from_str(&body_str) {
        Ok(i) => i,
        Err(e) => {
            error!("Failed to parse interaction: {}", e);
            return Ok(serde_json::to_value(ApiGatewayResponse::new(
                400,
                "Invalid request",
                "text/plain",
            ))?);
        }
    };

    // Handle ping (verification)
    if interaction.interaction_type == INTERACTION_PING {
        info!("Responding to Discord PING");
        return Ok(serde_json::to_value(ApiGatewayResponse::json(
            200,
            &DiscordResponse {
                response_type: RESPONSE_PONG,
                data: None,
            },
        )?)?);
    }

    // Handle application commands
    if interaction.interaction_type == INTERACTION_APPLICATION_COMMAND {
        let data = match &interaction.data {
            Some(d) => d,
            None => {
                return Ok(serde_json::to_value(ApiGatewayResponse::json(
                    200,
                    &DiscordResponse {
                        response_type: RESPONSE_CHANNEL_MESSAGE,
                        data: Some(ResponseData {
                            content: "Invalid command".to_string(),
                            flags: Some(64),
                        }),
                    },
                )?)?);
            }
        };

        // Get user info
        let user = interaction
            .member
            .as_ref()
            .map(|m| &m.user)
            .or(interaction.user.as_ref())
            .cloned()
            .unwrap_or(DiscordUser {
                id: "unknown".to_string(),
                username: "unknown".to_string(),
            });

        info!(
            "Processing command '{}' from user {}",
            data.name, user.username
        );

        // Extract command arguments
        let message = data
            .options
            .as_ref()
            .and_then(|opts| {
                opts.iter()
                    .find(|o| o.name == "message" || o.name == "question" || o.name == "fact")
                    .and_then(|o| o.value.as_str().map(String::from))
            })
            .unwrap_or_default();

        // Get application ID and token for follow-up
        let application_id = interaction
            .application_id
            .clone()
            .unwrap_or_else(|| std::env::var("DISCORD_APPLICATION_ID").unwrap_or_default());
        let interaction_token = interaction.token.clone().unwrap_or_default();

        if application_id.is_empty() || interaction_token.is_empty() {
            error!("Missing application_id or interaction_token");
            return Ok(serde_json::to_value(ApiGatewayResponse::json(
                200,
                &DiscordResponse {
                    response_type: RESPONSE_CHANNEL_MESSAGE,
                    data: Some(ResponseData {
                        content: "Configuration error. Please try again later.".to_string(),
                        flags: Some(64),
                    }),
                },
            )?)?);
        }

        // Create follow-up payload and invoke asynchronously
        let follow_up_payload = FollowUpPayload {
            follow_up: true,
            application_id,
            interaction_token,
            command_name: data.name.clone(),
            message,
            user_id: user.id,
            username: user.username,
        };

        if let Err(e) = state.invoke_follow_up(&follow_up_payload).await {
            error!("Failed to invoke follow-up: {}", e);
            return Ok(serde_json::to_value(ApiGatewayResponse::json(
                200,
                &DiscordResponse {
                    response_type: RESPONSE_CHANNEL_MESSAGE,
                    data: Some(ResponseData {
                        content: "Sorry, something went wrong. Please try again.".to_string(),
                        flags: Some(64),
                    }),
                },
            )?)?);
        }

        // Return deferred response immediately
        return Ok(serde_json::to_value(ApiGatewayResponse::json(
            200,
            &DiscordResponse {
                response_type: RESPONSE_DEFERRED_CHANNEL_MESSAGE,
                data: None,
            },
        )?)?);
    }

    // Unknown interaction type
    Ok(serde_json::to_value(ApiGatewayResponse::new(
        400,
        "Unknown interaction type",
        "text/plain",
    ))?)
}

/// Handle follow-up processing (async invocation)
async fn handle_follow_up(state: Arc<AppState>, payload: FollowUpPayload) -> Result<Value, Error> {
    let response_text = match payload.command_name.as_str() {
        "remember" | "save" => {
            match state
                .agent_client
                .ingest(&payload.message, &payload.user_id, vec![], "discord")
                .await
            {
                Ok(resp) => resp.response,
                Err(e) => {
                    error!("Agent error: {}", e);
                    "Sorry, I couldn't save that. Please try again.".to_string()
                }
            }
        }
        "ask" | "query" => {
            match state
                .agent_client
                .query(&payload.message, &payload.user_id, vec![], None, "discord")
                .await
            {
                Ok(resp) => resp.response,
                Err(e) => {
                    error!("Agent error: {}", e);
                    "Sorry, I couldn't process that query. Please try again.".to_string()
                }
            }
        }
        "briefing" => {
            match state
                .agent_client
                .query(
                    "Give me my morning briefing",
                    &payload.user_id,
                    vec![],
                    None,
                    "discord",
                )
                .await
            {
                Ok(resp) => resp.response,
                Err(e) => {
                    error!("Agent error: {}", e);
                    "Sorry, I couldn't generate your briefing. Please try again.".to_string()
                }
            }
        }
        "edit" => {
            // Route edit requests through query with clear intent
            let edit_message = format!("Please edit this fact: {}", payload.message);
            match state
                .agent_client
                .query(&edit_message, &payload.user_id, vec![], None, "discord")
                .await
            {
                Ok(resp) => resp.response,
                Err(e) => {
                    error!("Agent error: {}", e);
                    "Sorry, I couldn't edit that fact. Please try again.".to_string()
                }
            }
        }
        "forget" => {
            // Route forget/delete requests through query with clear intent
            let forget_message = format!("Please delete/forget this fact: {}", payload.message);
            match state
                .agent_client
                .query(&forget_message, &payload.user_id, vec![], None, "discord")
                .await
            {
                Ok(resp) => resp.response,
                Err(e) => {
                    error!("Agent error: {}", e);
                    "Sorry, I couldn't forget that. Please try again.".to_string()
                }
            }
        }
        _ => format!("Unknown command: {}", payload.command_name),
    };

    // Send the follow-up message to Discord
    if let Err(e) = state
        .send_follow_up(
            &payload.application_id,
            &payload.interaction_token,
            &response_text,
        )
        .await
    {
        error!("Failed to send follow-up message: {}", e);
    }

    // Return success for async invocation
    Ok(serde_json::json!({"status": "ok"}))
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    let state = Arc::new(AppState::new().await?);

    lambda_runtime::run(service_fn(move |event| {
        let state = Arc::clone(&state);
        async move { handler(state, event).await }
    }))
    .await
}
