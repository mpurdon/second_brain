//! Briefing Dispatcher Lambda - Triggers morning/evening briefings based on timezone.
//!
//! This Lambda runs hourly via EventBridge and:
//! 1. Queries users whose briefing time matches the current hour in their timezone
//! 2. Invokes the agent system to generate briefings for each user
//! 3. Queues notifications for delivery

use aws_sdk_lambda::primitives::Blob;
use chrono::{Timelike, Utc};
use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    #[serde(default)]
    detail_type: String,
    // Briefing type can be passed in the event
    #[serde(default)]
    briefing_type: Option<String>,
}

#[derive(Debug, Serialize)]
struct DispatcherResponse {
    users_processed: u32,
    briefings_triggered: u32,
    errors: u32,
}

#[derive(Debug, Serialize)]
struct AgentRequest {
    message: String,
    user_id: String,
    family_ids: Vec<String>,
    intent: String,
    source: String,
}

struct AppState {
    db_pool: PgPool,
    lambda_client: aws_sdk_lambda::Client,
    agent_function_name: String,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let secrets_client = aws_sdk_secretsmanager::Client::new(&config);
        let lambda_client = aws_sdk_lambda::Client::new(&config);

        let db_secret_arn =
            std::env::var("DB_SECRET_ARN").map_err(|_| "DB_SECRET_ARN not set")?;

        let db_secret = secrets_client
            .get_secret_value()
            .secret_id(&db_secret_arn)
            .send()
            .await
            .map_err(|e| format!("Failed to get DB secret: {}", e))?;

        let db_creds: serde_json::Value =
            serde_json::from_str(db_secret.secret_string().unwrap_or("{}"))?;

        let db_host = std::env::var("DB_HOST").map_err(|_| "DB_HOST not set")?;
        let db_name = std::env::var("DB_NAME").unwrap_or_else(|_| "second_brain".to_string());
        let db_user = db_creds["username"].as_str().unwrap_or("sbadmin");
        let db_pass = db_creds["password"].as_str().unwrap_or("");

        let database_url = format!(
            "postgres://{}:{}@{}:5432/{}",
            db_user, db_pass, db_host, db_name
        );

        let db_pool = PgPoolOptions::new()
            .max_connections(5)
            .connect(&database_url)
            .await
            .map_err(|e| format!("Failed to connect to database: {}", e))?;

        let agent_function_name = std::env::var("AGENT_FUNCTION_NAME")
            .unwrap_or_else(|_| "second-brain-agents".to_string());

        Ok(Self {
            db_pool,
            lambda_client,
            agent_function_name,
        })
    }
}

/// User eligible for briefing
#[derive(Debug, sqlx::FromRow)]
struct BriefingUser {
    user_id: Uuid,
    email: Option<String>,
    timezone: String,
    preferred_channel: String,
}

async fn get_users_for_briefing(
    pool: &PgPool,
    briefing_type: &str,
    current_hour_utc: u32,
) -> Result<Vec<BriefingUser>, Error> {
    // Get users whose local briefing time matches current UTC hour
    // This is a simplified version - production would need proper timezone handling
    let users: Vec<BriefingUser> = sqlx::query_as(
        r#"
        SELECT
            u.id as user_id,
            u.email,
            COALESCE(unp.timezone, 'America/New_York') as timezone,
            CASE
                WHEN unp.discord_enabled THEN 'discord'
                WHEN unp.push_enabled THEN 'push'
                WHEN unp.email_enabled THEN 'email'
                ELSE 'push'
            END as preferred_channel
        FROM users u
        LEFT JOIN user_notification_preferences unp ON unp.user_id = u.id
        WHERE
            CASE $1
                WHEN 'morning' THEN
                    COALESCE(unp.morning_briefing_enabled, true)
                    AND EXTRACT(HOUR FROM COALESCE(unp.morning_briefing_time, '07:00'::time)) =
                        ($2 + EXTRACT(TIMEZONE_HOUR FROM NOW() AT TIME ZONE COALESCE(unp.timezone, 'America/New_York')))::integer % 24
                WHEN 'evening' THEN
                    COALESCE(unp.evening_briefing_enabled, false)
                    AND EXTRACT(HOUR FROM COALESCE(unp.evening_briefing_time, '18:00'::time)) =
                        ($2 + EXTRACT(TIMEZONE_HOUR FROM NOW() AT TIME ZONE COALESCE(unp.timezone, 'America/New_York')))::integer % 24
                ELSE false
            END
        LIMIT 100
        "#,
    )
    .bind(briefing_type)
    .bind(current_hour_utc as i32)
    .fetch_all(pool)
    .await
    .map_err(|e| format!("Failed to query users: {}", e))?;

    Ok(users)
}

async fn trigger_briefing(
    state: &AppState,
    user: &BriefingUser,
    briefing_type: &str,
) -> Result<(), Error> {
    let message = match briefing_type {
        "morning" => "Generate my morning briefing".to_string(),
        "evening" => "Generate my evening summary".to_string(),
        _ => format!("Generate my {} briefing", briefing_type),
    };

    let request = AgentRequest {
        message,
        user_id: user.user_id.to_string(),
        family_ids: vec![], // Would fetch from DB in production
        intent: "briefing".to_string(),
        source: "scheduler".to_string(),
    };

    let payload = serde_json::to_vec(&request)
        .map_err(|e| format!("Failed to serialize request: {}", e))?;

    // Invoke agent asynchronously (don't wait for response)
    state
        .lambda_client
        .invoke()
        .function_name(&state.agent_function_name)
        .invocation_type(aws_sdk_lambda::types::InvocationType::Event) // Async
        .payload(Blob::new(payload))
        .send()
        .await
        .map_err(|e| format!("Failed to invoke agent: {}", e))?;

    info!(
        user_id = %user.user_id,
        briefing_type = briefing_type,
        "Triggered briefing generation"
    );

    Ok(())
}

async fn handler(
    state: Arc<AppState>,
    event: LambdaEvent<ScheduledEvent>,
) -> Result<DispatcherResponse, Error> {
    let briefing_type = event
        .payload
        .briefing_type
        .unwrap_or_else(|| "morning".to_string());

    let current_hour = Utc::now().hour();

    info!(
        briefing_type = %briefing_type,
        current_hour_utc = current_hour,
        "Starting briefing dispatch"
    );

    // Get users eligible for briefing at this hour
    let users = get_users_for_briefing(&state.db_pool, &briefing_type, current_hour).await?;

    info!(users_found = users.len(), "Found users for briefing");

    let mut briefings_triggered = 0u32;
    let mut errors = 0u32;

    // Trigger briefings for each user
    for user in &users {
        match trigger_briefing(&state, user, &briefing_type).await {
            Ok(_) => briefings_triggered += 1,
            Err(e) => {
                error!(
                    user_id = %user.user_id,
                    error = %e,
                    "Failed to trigger briefing"
                );
                errors += 1;
            }
        }
    }

    let response = DispatcherResponse {
        users_processed: users.len() as u32,
        briefings_triggered,
        errors,
    };

    info!(
        users_processed = response.users_processed,
        briefings_triggered = response.briefings_triggered,
        errors = response.errors,
        "Briefing dispatch complete"
    );

    Ok(response)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    let state = Arc::new(AppState::new().await?);
    let state_clone = state.clone();

    run(service_fn(move |event| {
        let state = state_clone.clone();
        async move { handler(state, event).await }
    }))
    .await
}
