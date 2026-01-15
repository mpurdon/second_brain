//! Discord Webhook Lambda - Handles Discord bot interactions.
//!
//! This Lambda handles incoming Discord interaction webhooks, verifies signatures,
//! processes slash commands, and invokes the agent system.

use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use shared::{AgentClient, ApiResponse};
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
#[derive(Debug, Deserialize)]
struct DiscordInteraction {
    #[serde(rename = "type")]
    interaction_type: u8,
    token: Option<String>,
    data: Option<InteractionData>,
    member: Option<GuildMember>,
    user: Option<DiscordUser>,
}

/// Discord interaction data (for slash commands)
#[derive(Debug, Deserialize)]
struct InteractionData {
    name: String,
    options: Option<Vec<CommandOption>>,
}

/// Discord command option
#[derive(Debug, Deserialize)]
struct CommandOption {
    name: String,
    value: serde_json::Value,
}

/// Discord guild member
#[derive(Debug, Deserialize)]
struct GuildMember {
    user: DiscordUser,
}

/// Discord user
#[derive(Debug, Deserialize)]
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

/// Application state
struct AppState {
    agent_client: AgentClient,
    discord_public_key: VerifyingKey,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let lambda_client = aws_sdk_lambda::Client::new(&config);

        let agent_function = std::env::var("AGENT_FUNCTION_NAME")
            .unwrap_or_else(|_| "second-brain-agents".to_string());

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
            agent_client: AgentClient::new(lambda_client, agent_function),
            discord_public_key: verifying_key,
        })
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

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    // Get signature headers
    let signature = event
        .headers()
        .get("x-signature-ed25519")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let timestamp = event
        .headers()
        .get("x-signature-timestamp")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    // Get body as string
    let body_bytes = event.body().to_vec();
    let body_str = String::from_utf8_lossy(&body_bytes);

    // Verify signature
    if !verify_signature(&state.discord_public_key, signature, timestamp, &body_str) {
        warn!("Invalid Discord signature");
        return Ok(Response::builder()
            .status(401)
            .body(Body::from("Invalid signature"))
            .expect("Failed to build response"));
    }

    // Parse interaction
    let interaction: DiscordInteraction = match serde_json::from_slice(&body_bytes) {
        Ok(i) => i,
        Err(e) => {
            error!("Failed to parse interaction: {}", e);
            return Ok(Response::builder()
                .status(400)
                .body(Body::from("Invalid request"))
                .expect("Failed to build response"));
        }
    };

    // Handle ping (verification)
    if interaction.interaction_type == INTERACTION_PING {
        info!("Responding to Discord PING");
        return json_response(&DiscordResponse {
            response_type: RESPONSE_PONG,
            data: None,
        });
    }

    // Handle application commands
    if interaction.interaction_type == INTERACTION_APPLICATION_COMMAND {
        let data = match interaction.data {
            Some(d) => d,
            None => {
                return json_response(&DiscordResponse {
                    response_type: RESPONSE_CHANNEL_MESSAGE,
                    data: Some(ResponseData {
                        content: "Invalid command".to_string(),
                        flags: Some(64), // Ephemeral
                    }),
                });
            }
        };

        // Get user info
        let user = interaction
            .member
            .map(|m| m.user)
            .or(interaction.user)
            .unwrap_or(DiscordUser {
                id: "unknown".to_string(),
                username: "unknown".to_string(),
            });

        info!("Processing command '{}' from user {}", data.name, user.username);

        // Extract command arguments
        let message = data
            .options
            .and_then(|opts| {
                opts.into_iter()
                    .find(|o| o.name == "message" || o.name == "query" || o.name == "fact")
                    .and_then(|o| o.value.as_str().map(String::from))
            })
            .unwrap_or_default();

        // Process based on command name
        let response_text = match data.name.as_str() {
            "remember" | "save" => {
                // Ingestion command
                match state
                    .agent_client
                    .ingest(&message, &user.id, vec![], "discord")
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
                // Query command
                match state
                    .agent_client
                    .query(&message, &user.id, vec![], None, "discord")
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
                // Morning briefing command
                match state
                    .agent_client
                    .query("Give me my morning briefing", &user.id, vec![], None, "discord")
                    .await
                {
                    Ok(resp) => resp.response,
                    Err(e) => {
                        error!("Agent error: {}", e);
                        "Sorry, I couldn't generate your briefing. Please try again.".to_string()
                    }
                }
            }
            _ => format!("Unknown command: {}", data.name),
        };

        return json_response(&DiscordResponse {
            response_type: RESPONSE_CHANNEL_MESSAGE,
            data: Some(ResponseData {
                content: response_text,
                flags: None,
            }),
        });
    }

    // Unknown interaction type
    Ok(Response::builder()
        .status(400)
        .body(Body::from("Unknown interaction type"))
        .expect("Failed to build response"))
}

fn json_response<T: Serialize>(data: &T) -> Result<Response<Body>, Error> {
    let body = serde_json::to_string(data)?;
    Ok(Response::builder()
        .status(200)
        .header("content-type", "application/json")
        .body(Body::from(body))
        .expect("Failed to build response"))
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
