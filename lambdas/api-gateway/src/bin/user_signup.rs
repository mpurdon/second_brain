//! User Signup Lambda - Cognito Post-Confirmation Trigger
//!
//! This Lambda is triggered after a user confirms their account in Cognito.
//! It creates the user record in the database with default settings.

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Cognito trigger event
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CognitoTriggerEvent {
    version: String,
    trigger_source: String,
    region: String,
    user_pool_id: String,
    user_name: String,
    request: CognitoRequest,
    response: CognitoResponse,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct CognitoRequest {
    user_attributes: UserAttributes,
}

#[derive(Debug, Deserialize, Serialize)]
struct UserAttributes {
    sub: String,
    email: String,
    email_verified: Option<String>,
    #[serde(default)]
    name: Option<String>,
    #[serde(rename = "custom:display_name")]
    display_name: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Default)]
struct CognitoResponse {}

/// Response must match input structure for Cognito triggers
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CognitoTriggerResponse {
    version: String,
    trigger_source: String,
    region: String,
    user_pool_id: String,
    user_name: String,
    request: serde_json::Value,
    response: CognitoResponse,
}

/// Application state
struct AppState {
    db_pool: PgPool,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let secrets_client = aws_sdk_secretsmanager::Client::new(&config);

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

        Ok(Self { db_pool })
    }
}

async fn handler(
    state: Arc<AppState>,
    event: LambdaEvent<CognitoTriggerEvent>,
) -> Result<CognitoTriggerResponse, Error> {
    let trigger = event.payload;

    info!(
        "Processing {} trigger for user {}",
        trigger.trigger_source, trigger.user_name
    );

    // Only process PostConfirmation triggers
    if !trigger.trigger_source.starts_with("PostConfirmation") {
        info!("Skipping non-PostConfirmation trigger");
        return Ok(CognitoTriggerResponse {
            version: trigger.version,
            trigger_source: trigger.trigger_source,
            region: trigger.region,
            user_pool_id: trigger.user_pool_id,
            user_name: trigger.user_name,
            request: serde_json::to_value(&trigger.request)?,
            response: CognitoResponse {},
        });
    }

    let user_attrs = &trigger.request.user_attributes;
    let user_id = Uuid::parse_str(&user_attrs.sub)
        .map_err(|e| format!("Invalid user sub: {}", e))?;

    let display_name = user_attrs.display_name
        .clone()
        .or_else(|| user_attrs.name.clone())
        .unwrap_or_else(|| user_attrs.email.split('@').next().unwrap_or("User").to_string());

    // Create user record
    let result = sqlx::query(
        r#"
        INSERT INTO users (id, email, display_name, cognito_sub, settings)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            display_name = COALESCE(NULLIF(users.display_name, ''), EXCLUDED.display_name),
            updated_at = NOW()
        "#,
    )
    .bind(user_id)
    .bind(&user_attrs.email)
    .bind(&display_name)
    .bind(&user_attrs.sub)
    .bind(serde_json::json!({
        "timezone": "America/New_York",
        "notifications_enabled": true,
        "briefing_time": "07:00",
        "voice_enabled": true,
        "default_visibility_tier": 3,
    }))
    .execute(&state.db_pool)
    .await;

    match result {
        Ok(_) => {
            info!("Created/updated user {} ({})", user_id, user_attrs.email);

            // Initialize self-access in cache
            let _ = sqlx::query(
                r#"
                INSERT INTO user_access_cache (viewer_user_id, target_user_id, access_tier, relationship_path, hop_count)
                VALUES ($1, $1, 1, ARRAY[]::uuid[], 0)
                ON CONFLICT (viewer_user_id, target_user_id) DO NOTHING
                "#,
            )
            .bind(user_id)
            .execute(&state.db_pool)
            .await;
        }
        Err(e) => {
            error!("Failed to create user {}: {}", user_id, e);
            // Don't fail the Cognito flow - user can still sign in
        }
    }

    // Return the event back to Cognito (required format)
    Ok(CognitoTriggerResponse {
        version: trigger.version,
        trigger_source: trigger.trigger_source,
        region: trigger.region,
        user_pool_id: trigger.user_pool_id,
        user_name: trigger.user_name,
        request: serde_json::to_value(&trigger.request)?,
        response: CognitoResponse {},
    })
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
