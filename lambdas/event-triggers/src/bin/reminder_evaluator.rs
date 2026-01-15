//! Reminder Evaluator Lambda - Evaluates pending reminders and queues notifications.
//!
//! This Lambda runs every few minutes via EventBridge and:
//! 1. Queries reminders whose trigger time has passed
//! 2. Evaluates trigger conditions
//! 3. Queues notifications for delivery
//! 4. Updates reminder status (triggered or reschedules recurring)

use aws_sdk_sns::Client as SnsClient;
use chrono::Utc;
use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    #[serde(default)]
    detail_type: String,
}

#[derive(Debug, Serialize)]
struct EvaluatorResponse {
    reminders_evaluated: u32,
    notifications_queued: u32,
    reminders_rescheduled: u32,
    errors: u32,
}

struct AppState {
    db_pool: PgPool,
    sns_client: SnsClient,
    notification_topic_arn: Option<String>,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let secrets_client = aws_sdk_secretsmanager::Client::new(&config);
        let sns_client = SnsClient::new(&config);

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

        let notification_topic_arn = std::env::var("NOTIFICATION_TOPIC_ARN").ok();

        Ok(Self {
            db_pool,
            sns_client,
            notification_topic_arn,
        })
    }
}

/// Pending reminder from database
#[derive(Debug, sqlx::FromRow)]
struct PendingReminder {
    id: Uuid,
    user_id: Uuid,
    title: String,
    description: Option<String>,
    trigger_type: String,
    priority: i16,
}

/// User notification preferences
#[derive(Debug, sqlx::FromRow)]
struct UserPreferences {
    push_enabled: bool,
    email_enabled: bool,
    discord_enabled: bool,
    quiet_hours_enabled: bool,
    quiet_hours_start: Option<chrono::NaiveTime>,
    quiet_hours_end: Option<chrono::NaiveTime>,
    timezone: String,
}

async fn get_pending_reminders(pool: &PgPool, limit: i32) -> Result<Vec<PendingReminder>, Error> {
    let reminders: Vec<PendingReminder> = sqlx::query_as(
        r#"
        SELECT
            r.id,
            r.user_id,
            r.title,
            r.description,
            r.trigger_type::text as trigger_type,
            r.priority
        FROM reminders r
        WHERE r.status = 'active'
        AND r.next_trigger_at <= NOW()
        AND (r.snooze_until IS NULL OR r.snooze_until <= NOW())
        ORDER BY r.priority DESC, r.next_trigger_at ASC
        LIMIT $1
        "#,
    )
    .bind(limit)
    .fetch_all(pool)
    .await
    .map_err(|e| format!("Failed to query reminders: {}", e))?;

    Ok(reminders)
}

async fn get_user_preferences(
    pool: &PgPool,
    user_id: Uuid,
) -> Result<Option<UserPreferences>, Error> {
    let prefs: Option<UserPreferences> = sqlx::query_as(
        r#"
        SELECT
            push_enabled,
            email_enabled,
            discord_enabled,
            quiet_hours_enabled,
            quiet_hours_start,
            quiet_hours_end,
            timezone
        FROM user_notification_preferences
        WHERE user_id = $1
        "#,
    )
    .bind(user_id)
    .fetch_optional(pool)
    .await
    .map_err(|e| format!("Failed to query preferences: {}", e))?;

    Ok(prefs)
}

fn is_in_quiet_hours(prefs: &UserPreferences) -> bool {
    if !prefs.quiet_hours_enabled {
        return false;
    }

    let (start, end) = match (prefs.quiet_hours_start, prefs.quiet_hours_end) {
        (Some(s), Some(e)) => (s, e),
        _ => return false,
    };

    let now = Utc::now().time();

    if start <= end {
        now >= start && now < end
    } else {
        // Wrapping range (e.g., 22:00 - 07:00)
        now >= start || now < end
    }
}

fn get_preferred_channel(prefs: &UserPreferences) -> &str {
    if prefs.discord_enabled {
        "discord"
    } else if prefs.push_enabled {
        "push"
    } else if prefs.email_enabled {
        "email"
    } else {
        "push"
    }
}

async fn queue_notification(
    pool: &PgPool,
    user_id: Uuid,
    reminder: &PendingReminder,
    channel: &str,
) -> Result<Uuid, Error> {
    let body = reminder
        .description
        .clone()
        .unwrap_or_else(|| reminder.title.clone());

    let notification_id: Uuid = sqlx::query_scalar(
        r#"
        INSERT INTO notifications (
            user_id, notification_type, title, body, channel, reminder_id
        ) VALUES ($1, 'reminder', $2, $3, $4::notification_channel, $5)
        RETURNING id
        "#,
    )
    .bind(user_id)
    .bind(&reminder.title)
    .bind(&body)
    .bind(channel)
    .bind(reminder.id)
    .fetch_one(pool)
    .await
    .map_err(|e| format!("Failed to queue notification: {}", e))?;

    Ok(notification_id)
}

async fn update_reminder_status(
    pool: &PgPool,
    reminder_id: Uuid,
    trigger_type: &str,
) -> Result<bool, Error> {
    let is_recurring = trigger_type == "recurring";

    if is_recurring {
        sqlx::query(
            r#"
            UPDATE reminders
            SET last_triggered_at = NOW(),
                next_trigger_at = calculate_next_trigger(trigger_type, trigger_config, NOW()),
                updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(reminder_id)
        .execute(pool)
        .await
        .map_err(|e| format!("Failed to reschedule reminder: {}", e))?;
    } else {
        sqlx::query(
            r#"
            UPDATE reminders
            SET status = 'triggered',
                last_triggered_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(reminder_id)
        .execute(pool)
        .await
        .map_err(|e| format!("Failed to update reminder status: {}", e))?;
    }

    Ok(is_recurring)
}

async fn publish_to_sns(state: &AppState, notification_id: Uuid, title: &str) -> Result<(), Error> {
    if let Some(topic_arn) = &state.notification_topic_arn {
        let message = serde_json::json!({
            "notification_id": notification_id.to_string(),
            "type": "reminder",
            "title": title,
        });

        state
            .sns_client
            .publish()
            .topic_arn(topic_arn)
            .message(serde_json::to_string(&message).unwrap_or_default())
            .send()
            .await
            .map_err(|e| format!("Failed to publish to SNS: {}", e))?;
    }

    Ok(())
}

async fn handler(
    state: Arc<AppState>,
    _event: LambdaEvent<ScheduledEvent>,
) -> Result<EvaluatorResponse, Error> {
    info!("Starting reminder evaluation");

    let reminders = get_pending_reminders(&state.db_pool, 100).await?;

    info!(reminders_found = reminders.len(), "Found pending reminders");

    let mut notifications_queued = 0u32;
    let mut reminders_rescheduled = 0u32;
    let mut errors = 0u32;

    for reminder in &reminders {
        let prefs = match get_user_preferences(&state.db_pool, reminder.user_id).await {
            Ok(Some(p)) => p,
            Ok(None) => UserPreferences {
                push_enabled: true,
                email_enabled: true,
                discord_enabled: false,
                quiet_hours_enabled: false,
                quiet_hours_start: None,
                quiet_hours_end: None,
                timezone: "America/New_York".to_string(),
            },
            Err(e) => {
                error!(reminder_id = %reminder.id, error = %e, "Failed to get user preferences");
                errors += 1;
                continue;
            }
        };

        if is_in_quiet_hours(&prefs) {
            info!(reminder_id = %reminder.id, "Skipping notification during quiet hours");
            continue;
        }

        let channel = get_preferred_channel(&prefs);
        match queue_notification(&state.db_pool, reminder.user_id, reminder, channel).await {
            Ok(notification_id) => {
                notifications_queued += 1;
                if let Err(e) = publish_to_sns(&state, notification_id, &reminder.title).await {
                    warn!(notification_id = %notification_id, error = %e, "Failed to publish to SNS");
                }
            }
            Err(e) => {
                error!(reminder_id = %reminder.id, error = %e, "Failed to queue notification");
                errors += 1;
                continue;
            }
        }

        match update_reminder_status(&state.db_pool, reminder.id, &reminder.trigger_type).await {
            Ok(was_rescheduled) => {
                if was_rescheduled {
                    reminders_rescheduled += 1;
                }
            }
            Err(e) => {
                error!(reminder_id = %reminder.id, error = %e, "Failed to update reminder status");
                errors += 1;
            }
        }
    }

    let response = EvaluatorResponse {
        reminders_evaluated: reminders.len() as u32,
        notifications_queued,
        reminders_rescheduled,
        errors,
    };

    info!(
        reminders_evaluated = response.reminders_evaluated,
        notifications_queued = response.notifications_queued,
        "Reminder evaluation complete"
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
