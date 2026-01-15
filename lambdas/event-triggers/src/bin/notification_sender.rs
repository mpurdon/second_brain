//! Notification Sender Lambda - Delivers notifications via various channels.
//!
//! This Lambda is triggered by SNS and:
//! 1. Receives notification ID from SNS message
//! 2. Fetches notification details from database
//! 3. Sends via appropriate channel (push, email, discord)
//! 4. Updates notification status in database

use aws_sdk_ses::types::{Body, Content, Destination, Message};
use chrono::Utc;
use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// SNS Event wrapper
#[derive(Debug, Deserialize)]
struct SnsEvent {
    #[serde(rename = "Records")]
    records: Vec<SnsRecord>,
}

#[derive(Debug, Deserialize)]
struct SnsRecord {
    #[serde(rename = "Sns")]
    sns: SnsMessage,
}

#[derive(Debug, Deserialize)]
struct SnsMessage {
    #[serde(rename = "Message")]
    message: String,
}

/// Notification message from SNS
#[derive(Debug, Deserialize)]
struct NotificationMessage {
    notification_id: String,
    #[serde(default)]
    r#type: String,
    #[serde(default)]
    title: String,
}

#[derive(Debug, Serialize)]
struct SenderResponse {
    notifications_sent: u32,
    errors: u32,
}

/// Notification from database
#[derive(Debug, sqlx::FromRow)]
struct NotificationRow {
    id: Uuid,
    user_id: Uuid,
    notification_type: String,
    title: String,
    body: String,
    channel: String,
    reminder_id: Option<Uuid>,
}

/// User contact info
#[derive(Debug, sqlx::FromRow)]
struct UserContact {
    email: Option<String>,
    discord_user_id: Option<String>,
    push_token: Option<String>,
}

struct AppState {
    db_pool: PgPool,
    ses_client: aws_sdk_ses::Client,
    discord_webhook_url: Option<String>,
    from_email: String,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let secrets_client = aws_sdk_secretsmanager::Client::new(&config);
        let ses_client = aws_sdk_ses::Client::new(&config);

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

        let discord_webhook_url = std::env::var("DISCORD_WEBHOOK_URL").ok();
        let from_email = std::env::var("FROM_EMAIL")
            .unwrap_or_else(|_| "noreply@secondbrain.app".to_string());

        Ok(Self {
            db_pool,
            ses_client,
            discord_webhook_url,
            from_email,
        })
    }
}

async fn get_notification(pool: &PgPool, notification_id: Uuid) -> Result<Option<NotificationRow>, Error> {
    let notification: Option<NotificationRow> = sqlx::query_as(
        r#"
        SELECT
            id, user_id, notification_type::text,
            title, body, channel::text, reminder_id
        FROM notifications
        WHERE id = $1 AND status = 'pending'
        "#,
    )
    .bind(notification_id)
    .fetch_optional(pool)
    .await
    .map_err(|e| format!("Failed to fetch notification: {}", e))?;

    Ok(notification)
}

async fn get_user_contact(pool: &PgPool, user_id: Uuid) -> Result<Option<UserContact>, Error> {
    let contact: Option<UserContact> = sqlx::query_as(
        r#"
        SELECT
            u.email,
            up.discord_user_id,
            up.push_token
        FROM users u
        LEFT JOIN user_profiles up ON up.user_id = u.id
        WHERE u.id = $1
        "#,
    )
    .bind(user_id)
    .fetch_optional(pool)
    .await
    .map_err(|e| format!("Failed to fetch user contact: {}", e))?;

    Ok(contact)
}

async fn update_notification_status(
    pool: &PgPool,
    notification_id: Uuid,
    status: &str,
    delivery_info: Option<&str>,
) -> Result<(), Error> {
    let sent_at = if status == "sent" {
        Some(Utc::now())
    } else {
        None
    };

    sqlx::query(
        r#"
        UPDATE notifications
        SET status = $2::notification_status,
            sent_at = COALESCE($3, sent_at),
            delivery_info = COALESCE($4, delivery_info),
            updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(notification_id)
    .bind(status)
    .bind(sent_at)
    .bind(delivery_info)
    .execute(pool)
    .await
    .map_err(|e| format!("Failed to update notification status: {}", e))?;

    Ok(())
}

async fn send_email(
    state: &AppState,
    to_email: &str,
    title: &str,
    body: &str,
) -> Result<String, Error> {
    let subject = Content::builder()
        .data(title)
        .charset("UTF-8")
        .build()
        .map_err(|e| format!("Failed to build subject: {}", e))?;

    let html_body = format!(
        r#"
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: sans-serif; padding: 20px;">
            <h2>{}</h2>
            <p>{}</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Sent by Second Brain
            </p>
        </body>
        </html>
        "#,
        title,
        body.replace('\n', "<br>")
    );

    let html_content = Content::builder()
        .data(html_body)
        .charset("UTF-8")
        .build()
        .map_err(|e| format!("Failed to build body: {}", e))?;

    let text_content = Content::builder()
        .data(body)
        .charset("UTF-8")
        .build()
        .map_err(|e| format!("Failed to build text body: {}", e))?;

    let body_content = Body::builder()
        .html(html_content)
        .text(text_content)
        .build();

    let message = Message::builder()
        .subject(subject)
        .body(body_content)
        .build();

    let destination = Destination::builder()
        .to_addresses(to_email)
        .build();

    let result = state
        .ses_client
        .send_email()
        .source(&state.from_email)
        .destination(destination)
        .message(message)
        .send()
        .await
        .map_err(|e| format!("Failed to send email: {}", e))?;

    Ok(result.message_id().to_string())
}

async fn send_discord(
    state: &AppState,
    discord_user_id: &str,
    title: &str,
    body: &str,
) -> Result<String, Error> {
    let webhook_url = state
        .discord_webhook_url
        .as_ref()
        .ok_or("Discord webhook URL not configured")?;

    let payload = serde_json::json!({
        "content": format!("<@{}> **{}**\n{}", discord_user_id, title, body),
        "allowed_mentions": {
            "users": [discord_user_id]
        }
    });

    let client = reqwest::Client::new();
    let response = client
        .post(webhook_url)
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Failed to send Discord message: {}", e))?;

    if response.status().is_success() {
        Ok("discord_sent".to_string())
    } else {
        Err(format!("Discord webhook failed: {}", response.status()).into())
    }
}

async fn send_push(_push_token: &str, _title: &str, _body: &str) -> Result<String, Error> {
    // Push notifications would typically use Firebase Cloud Messaging or similar
    // For now, we log and return success
    warn!("Push notifications not implemented - would send to token");
    Ok("push_pending".to_string())
}

async fn send_notification(
    state: &AppState,
    notification: &NotificationRow,
    contact: &UserContact,
) -> Result<String, Error> {
    match notification.channel.as_str() {
        "email" => {
            let email = contact
                .email
                .as_ref()
                .ok_or("User has no email address")?;
            send_email(state, email, &notification.title, &notification.body).await
        }
        "discord" => {
            let discord_id = contact
                .discord_user_id
                .as_ref()
                .ok_or("User has no Discord ID")?;
            send_discord(state, discord_id, &notification.title, &notification.body).await
        }
        "push" => {
            let push_token = contact
                .push_token
                .as_ref()
                .ok_or("User has no push token")?;
            send_push(push_token, &notification.title, &notification.body).await
        }
        _ => Err(format!("Unknown channel: {}", notification.channel).into()),
    }
}

async fn handler(
    state: Arc<AppState>,
    event: LambdaEvent<SnsEvent>,
) -> Result<SenderResponse, Error> {
    info!("Processing notification sender event");

    let mut notifications_sent = 0u32;
    let mut errors = 0u32;

    for record in &event.payload.records {
        let message: NotificationMessage = match serde_json::from_str(&record.sns.message) {
            Ok(m) => m,
            Err(e) => {
                error!(error = %e, "Failed to parse SNS message");
                errors += 1;
                continue;
            }
        };

        let notification_id = match Uuid::parse_str(&message.notification_id) {
            Ok(id) => id,
            Err(e) => {
                error!(error = %e, "Invalid notification ID");
                errors += 1;
                continue;
            }
        };

        info!(notification_id = %notification_id, "Processing notification");

        // Fetch notification from database
        let notification = match get_notification(&state.db_pool, notification_id).await {
            Ok(Some(n)) => n,
            Ok(None) => {
                warn!(notification_id = %notification_id, "Notification not found or already sent");
                continue;
            }
            Err(e) => {
                error!(notification_id = %notification_id, error = %e, "Failed to fetch notification");
                errors += 1;
                continue;
            }
        };

        // Fetch user contact info
        let contact = match get_user_contact(&state.db_pool, notification.user_id).await {
            Ok(Some(c)) => c,
            Ok(None) => {
                error!(user_id = %notification.user_id, "User not found");
                update_notification_status(
                    &state.db_pool,
                    notification_id,
                    "failed",
                    Some("User not found"),
                )
                .await
                .ok();
                errors += 1;
                continue;
            }
            Err(e) => {
                error!(error = %e, "Failed to fetch user contact");
                errors += 1;
                continue;
            }
        };

        // Send notification
        match send_notification(&state, &notification, &contact).await {
            Ok(delivery_id) => {
                info!(
                    notification_id = %notification_id,
                    channel = %notification.channel,
                    "Notification sent successfully"
                );
                update_notification_status(
                    &state.db_pool,
                    notification_id,
                    "sent",
                    Some(&delivery_id),
                )
                .await
                .ok();
                notifications_sent += 1;
            }
            Err(e) => {
                error!(
                    notification_id = %notification_id,
                    channel = %notification.channel,
                    error = %e,
                    "Failed to send notification"
                );
                update_notification_status(
                    &state.db_pool,
                    notification_id,
                    "failed",
                    Some(&e.to_string()),
                )
                .await
                .ok();
                errors += 1;
            }
        }
    }

    let response = SenderResponse {
        notifications_sent,
        errors,
    };

    info!(
        sent = response.notifications_sent,
        errors = response.errors,
        "Notification sender complete"
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
