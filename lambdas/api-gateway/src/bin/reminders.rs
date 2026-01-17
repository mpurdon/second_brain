//! Reminders API Lambda - CRUD operations for reminders.
//!
//! Endpoints:
//! - POST /reminders - Create a reminder
//! - GET /reminders - List reminders
//! - GET /reminders/{id} - Get a single reminder
//! - PUT /reminders/{id} - Update a reminder
//! - POST /reminders/{id}/snooze - Snooze a reminder
//! - DELETE /reminders/{id} - Delete a reminder

use chrono::{DateTime, NaiveTime, Utc};
use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Create reminder request
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CreateReminderRequest {
    title: String,
    description: Option<String>,
    trigger_type: String, // time, location, event, recurring
    trigger_config: serde_json::Value,
    priority: Option<i16>,
    related_entity_id: Option<String>,
    related_fact_id: Option<String>,
}

/// Update reminder request
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UpdateReminderRequest {
    title: Option<String>,
    description: Option<String>,
    trigger_config: Option<serde_json::Value>,
    priority: Option<i16>,
    status: Option<String>,
}

/// Snooze reminder request
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SnoozeReminderRequest {
    snooze_until: String, // ISO 8601 datetime
}

/// Reminder response from database
#[derive(Debug, sqlx::FromRow)]
struct ReminderRow {
    id: Uuid,
    user_id: Uuid,
    title: String,
    description: Option<String>,
    trigger_type: String,
    trigger_config: serde_json::Value,
    priority: i16,
    status: String,
    next_trigger_at: Option<DateTime<Utc>>,
    last_triggered_at: Option<DateTime<Utc>>,
    snooze_until: Option<DateTime<Utc>>,
    related_entity_id: Option<Uuid>,
    related_fact_id: Option<Uuid>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

/// Reminder API response
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReminderResponse {
    id: String,
    title: String,
    description: Option<String>,
    trigger_type: String,
    trigger_config: serde_json::Value,
    priority: i16,
    status: String,
    next_trigger_at: Option<String>,
    last_triggered_at: Option<String>,
    snooze_until: Option<String>,
    related_entity_id: Option<String>,
    related_fact_id: Option<String>,
    created_at: String,
    updated_at: String,
}

impl From<ReminderRow> for ReminderResponse {
    fn from(row: ReminderRow) -> Self {
        Self {
            id: row.id.to_string(),
            title: row.title,
            description: row.description,
            trigger_type: row.trigger_type,
            trigger_config: row.trigger_config,
            priority: row.priority,
            status: row.status,
            next_trigger_at: row.next_trigger_at.map(|dt| dt.to_rfc3339()),
            last_triggered_at: row.last_triggered_at.map(|dt| dt.to_rfc3339()),
            snooze_until: row.snooze_until.map(|dt| dt.to_rfc3339()),
            related_entity_id: row.related_entity_id.map(|u| u.to_string()),
            related_fact_id: row.related_fact_id.map(|u| u.to_string()),
            created_at: row.created_at.to_rfc3339(),
            updated_at: row.updated_at.to_rfc3339(),
        }
    }
}

/// API response wrapper
#[derive(Debug, Serialize)]
struct ApiResponse<T> {
    success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
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

/// Extract user_id from Cognito claims
fn extract_user_id(event: &Request) -> Result<Uuid, Error> {
    let context = event
        .request_context_ref()
        .ok_or("Missing request context")?;

    let claims = context
        .authorizer()
        .and_then(|a| a.fields.get("claims"))
        .ok_or("Missing claims")?;

    let sub = claims
        .as_object()
        .and_then(|c| c.get("sub"))
        .and_then(|s| s.as_str())
        .ok_or("Missing sub claim")?;

    Uuid::parse_str(sub).map_err(|_| "Invalid user ID".into())
}

/// Calculate next trigger time based on trigger type and config
fn calculate_next_trigger(
    trigger_type: &str,
    trigger_config: &serde_json::Value,
) -> Option<DateTime<Utc>> {
    match trigger_type {
        "time" => {
            // Direct datetime trigger - support multiple field names for compatibility
            trigger_config
                .get("scheduledAt")
                .or_else(|| trigger_config.get("triggerAt"))
                .or_else(|| trigger_config.get("at"))
                .and_then(|v| v.as_str())
                .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                .map(|dt| dt.with_timezone(&Utc))
        }
        "recurring" => {
            // For recurring, calculate next occurrence based on pattern
            // This is a simplified version - the DB function handles full logic
            let time_str = trigger_config
                .get("time")
                .and_then(|v| v.as_str())
                .unwrap_or("09:00");

            let time = NaiveTime::parse_from_str(time_str, "%H:%M").ok()?;
            let today = Utc::now().date_naive();
            let datetime = today.and_time(time);
            Some(DateTime::from_naive_utc_and_offset(datetime, Utc))
        }
        "event" => {
            // Event-based triggers are evaluated by the reminder evaluator
            // Set a far-future placeholder
            trigger_config
                .get("checkAfter")
                .and_then(|v| v.as_str())
                .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                .map(|dt| dt.with_timezone(&Utc))
        }
        "location" => {
            // Location triggers are evaluated continuously
            // No specific next_trigger_at
            None
        }
        _ => None,
    }
}

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    let method = event.method().as_str();
    let raw_path = event.uri().path();
    // Strip /api stage prefix if present (API Gateway REST API includes stage in path)
    let path = raw_path.strip_prefix("/api").unwrap_or(raw_path);

    info!("Reminders request: {} {}", method, path);

    // Extract user
    let cognito_sub = match extract_user_id(&event) {
        Ok(id) => id,
        Err(e) => {
            return Ok(json_response(
                401,
                &ApiResponse::<()> {
                    success: false,
                    data: None,
                    error: Some(e.to_string()),
                },
            )?)
        }
    };

    // Look up database user_id from Cognito sub
    let user_id: Uuid = match sqlx::query_scalar::<_, Uuid>(
        "SELECT id FROM users WHERE cognito_sub = $1::text"
    )
    .bind(cognito_sub)
    .fetch_optional(&state.db_pool)
    .await
    .map_err(|e| format!("Failed to lookup user: {}", e))? {
        Some(id) => id,
        None => {
            return Ok(json_response(
                401,
                &ApiResponse::<()> {
                    success: false,
                    data: None,
                    error: Some("User not registered".to_string()),
                },
            )?)
        }
    };

    match (method, path) {
        // Create reminder
        ("POST", "/reminders") => {
            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: CreateReminderRequest =
                serde_json::from_str(body_str).map_err(|e| format!("Invalid request: {}", e))?;

            // Validate trigger type
            let valid_types = ["time", "location", "event", "recurring"];
            if !valid_types.contains(&request.trigger_type.as_str()) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some(format!(
                            "Invalid trigger_type. Must be one of: {}",
                            valid_types.join(", ")
                        )),
                    },
                )?);
            }

            let related_entity_id = request
                .related_entity_id
                .as_ref()
                .and_then(|id| Uuid::parse_str(id).ok());

            let related_fact_id = request
                .related_fact_id
                .as_ref()
                .and_then(|id| Uuid::parse_str(id).ok());

            let next_trigger_at = calculate_next_trigger(&request.trigger_type, &request.trigger_config);
            let priority = request.priority.unwrap_or(2); // Default medium priority

            let reminder: ReminderRow = sqlx::query_as(
                r#"
                INSERT INTO reminders (
                    user_id, title, description, trigger_type,
                    trigger_config, priority, next_trigger_at,
                    related_entity_id, related_fact_id
                ) VALUES (
                    $1, $2, $3, $4::reminder_trigger_type,
                    $5, $6, $7,
                    $8, $9
                )
                RETURNING
                    id, user_id, title, description,
                    trigger_type::text, trigger_config, priority,
                    status::text, next_trigger_at, last_triggered_at,
                    snooze_until, related_entity_id, related_fact_id,
                    created_at, updated_at
                "#,
            )
            .bind(user_id)
            .bind(&request.title)
            .bind(&request.description)
            .bind(&request.trigger_type)
            .bind(&request.trigger_config)
            .bind(priority)
            .bind(next_trigger_at)
            .bind(related_entity_id)
            .bind(related_fact_id)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to create reminder: {}", e))?;

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(ReminderResponse::from(reminder)),
                    error: None,
                },
            )?)
        }

        // List reminders
        ("GET", "/reminders") => {
            let params = event.query_string_parameters();
            let status = params.first("status");
            let trigger_type = params.first("triggerType");
            let limit: i32 = params
                .first("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(50);
            let offset: i32 = params
                .first("offset")
                .and_then(|o| o.parse().ok())
                .unwrap_or(0);

            let mut query = String::from(
                r#"
                SELECT
                    id, user_id, title, description,
                    trigger_type::text, trigger_config, priority,
                    status::text, next_trigger_at, last_triggered_at,
                    snooze_until, related_entity_id, related_fact_id,
                    created_at, updated_at
                FROM reminders
                WHERE user_id = $1
                "#,
            );

            let mut param_num = 2;

            if status.is_some() {
                query.push_str(&format!(" AND status = ${}::reminder_status", param_num));
                param_num += 1;
            }

            if trigger_type.is_some() {
                query.push_str(&format!(
                    " AND trigger_type = ${}::reminder_trigger_type",
                    param_num
                ));
                param_num += 1;
            }

            query.push_str(&format!(
                " ORDER BY next_trigger_at ASC NULLS LAST LIMIT ${} OFFSET ${}",
                param_num,
                param_num + 1
            ));

            // Build the query with dynamic bindings
            let mut query_builder = sqlx::query_as::<_, ReminderRow>(&query).bind(user_id);

            if let Some(s) = status {
                query_builder = query_builder.bind(s);
            }
            if let Some(t) = trigger_type {
                query_builder = query_builder.bind(t);
            }

            query_builder = query_builder.bind(limit).bind(offset);

            let reminders: Vec<ReminderRow> = query_builder
                .fetch_all(&state.db_pool)
                .await
                .map_err(|e| format!("Failed to fetch reminders: {}", e))?;

            let responses: Vec<ReminderResponse> =
                reminders.into_iter().map(ReminderResponse::from).collect();

            // Get total count
            let total: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM reminders WHERE user_id = $1",
            )
            .bind(user_id)
            .fetch_one(&state.db_pool)
            .await
            .unwrap_or(0);

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "reminders": responses,
                        "total": total,
                        "limit": limit,
                        "offset": offset,
                    })),
                    error: None,
                },
            )?)
        }

        // Get single reminder
        _ if path.starts_with("/reminders/")
            && !path.contains("/snooze")
            && method == "GET" =>
        {
            let reminder_id = path.trim_start_matches("/reminders/");
            let reminder_uuid =
                Uuid::parse_str(reminder_id).map_err(|_| "Invalid reminder ID")?;

            let reminder: Option<ReminderRow> = sqlx::query_as(
                r#"
                SELECT
                    id, user_id, title, description,
                    trigger_type::text, trigger_config, priority,
                    status::text, next_trigger_at, last_triggered_at,
                    snooze_until, related_entity_id, related_fact_id,
                    created_at, updated_at
                FROM reminders
                WHERE id = $1 AND user_id = $2
                "#,
            )
            .bind(reminder_uuid)
            .bind(user_id)
            .fetch_optional(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch reminder: {}", e))?;

            match reminder {
                Some(r) => Ok(json_response(
                    200,
                    &ApiResponse {
                        success: true,
                        data: Some(ReminderResponse::from(r)),
                        error: None,
                    },
                )?),
                None => Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Reminder not found".to_string()),
                    },
                )?),
            }
        }

        // Update reminder
        _ if path.starts_with("/reminders/")
            && !path.contains("/snooze")
            && method == "PUT" =>
        {
            let reminder_id = path.trim_start_matches("/reminders/");
            let reminder_uuid =
                Uuid::parse_str(reminder_id).map_err(|_| "Invalid reminder ID")?;

            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: UpdateReminderRequest =
                serde_json::from_str(body_str).map_err(|e| format!("Invalid request: {}", e))?;

            // Validate status if provided
            if let Some(ref status) = request.status {
                let valid_statuses = ["active", "paused", "cancelled", "completed"];
                if !valid_statuses.contains(&status.as_str()) {
                    return Ok(json_response(
                        400,
                        &ApiResponse::<()> {
                            success: false,
                            data: None,
                            error: Some(format!(
                                "Invalid status. Must be one of: {}",
                                valid_statuses.join(", ")
                            )),
                        },
                    )?);
                }
            }

            // Build dynamic update query
            let mut updates = Vec::new();
            let mut param_num = 3;

            if request.title.is_some() {
                updates.push(format!("title = ${}", param_num));
                param_num += 1;
            }
            if request.description.is_some() {
                updates.push(format!("description = ${}", param_num));
                param_num += 1;
            }
            if request.trigger_config.is_some() {
                updates.push(format!("trigger_config = ${}", param_num));
                param_num += 1;
            }
            if request.priority.is_some() {
                updates.push(format!("priority = ${}", param_num));
                param_num += 1;
            }
            if request.status.is_some() {
                updates.push(format!("status = ${}::reminder_status", param_num));
            }

            if updates.is_empty() {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("No fields to update".to_string()),
                    },
                )?);
            }

            updates.push("updated_at = NOW()".to_string());

            let query = format!(
                r#"
                UPDATE reminders
                SET {}
                WHERE id = $1 AND user_id = $2
                RETURNING
                    id, user_id, title, description,
                    trigger_type::text, trigger_config, priority,
                    status::text, next_trigger_at, last_triggered_at,
                    snooze_until, related_entity_id, related_fact_id,
                    created_at, updated_at
                "#,
                updates.join(", ")
            );

            let mut query_builder = sqlx::query_as::<_, ReminderRow>(&query)
                .bind(reminder_uuid)
                .bind(user_id);

            if let Some(ref title) = request.title {
                query_builder = query_builder.bind(title);
            }
            if let Some(ref description) = request.description {
                query_builder = query_builder.bind(description);
            }
            if let Some(ref trigger_config) = request.trigger_config {
                query_builder = query_builder.bind(trigger_config);
            }
            if let Some(priority) = request.priority {
                query_builder = query_builder.bind(priority);
            }
            if let Some(ref status) = request.status {
                query_builder = query_builder.bind(status);
            }

            let reminder: Option<ReminderRow> = query_builder
                .fetch_optional(&state.db_pool)
                .await
                .map_err(|e| format!("Failed to update reminder: {}", e))?;

            match reminder {
                Some(r) => Ok(json_response(
                    200,
                    &ApiResponse {
                        success: true,
                        data: Some(ReminderResponse::from(r)),
                        error: None,
                    },
                )?),
                None => Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Reminder not found".to_string()),
                    },
                )?),
            }
        }

        // Snooze reminder
        _ if path.ends_with("/snooze") && method == "POST" => {
            let reminder_id = path
                .trim_start_matches("/reminders/")
                .trim_end_matches("/snooze");
            let reminder_uuid =
                Uuid::parse_str(reminder_id).map_err(|_| "Invalid reminder ID")?;

            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: SnoozeReminderRequest =
                serde_json::from_str(body_str).map_err(|e| format!("Invalid request: {}", e))?;

            let snooze_until = DateTime::parse_from_rfc3339(&request.snooze_until)
                .map_err(|_| "Invalid snooze_until datetime")?
                .with_timezone(&Utc);

            let reminder: Option<ReminderRow> = sqlx::query_as(
                r#"
                UPDATE reminders
                SET snooze_until = $3, updated_at = NOW()
                WHERE id = $1 AND user_id = $2
                RETURNING
                    id, user_id, title, description,
                    trigger_type::text, trigger_config, priority,
                    status::text, next_trigger_at, last_triggered_at,
                    snooze_until, related_entity_id, related_fact_id,
                    created_at, updated_at
                "#,
            )
            .bind(reminder_uuid)
            .bind(user_id)
            .bind(snooze_until)
            .fetch_optional(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to snooze reminder: {}", e))?;

            match reminder {
                Some(r) => Ok(json_response(
                    200,
                    &ApiResponse {
                        success: true,
                        data: Some(ReminderResponse::from(r)),
                        error: None,
                    },
                )?),
                None => Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Reminder not found".to_string()),
                    },
                )?),
            }
        }

        // Delete reminder
        _ if path.starts_with("/reminders/") && method == "DELETE" => {
            let reminder_id = path.trim_start_matches("/reminders/");
            let reminder_uuid =
                Uuid::parse_str(reminder_id).map_err(|_| "Invalid reminder ID")?;

            let result = sqlx::query(
                r#"
                UPDATE reminders
                SET status = 'cancelled', updated_at = NOW()
                WHERE id = $1 AND user_id = $2
                "#,
            )
            .bind(reminder_uuid)
            .bind(user_id)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to delete reminder: {}", e))?;

            if result.rows_affected() == 0 {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Reminder not found".to_string()),
                    },
                )?);
            }

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "message": "Reminder cancelled",
                        "reminderId": reminder_id,
                    })),
                    error: None,
                },
            )?)
        }

        _ => Ok(json_response(
            404,
            &ApiResponse::<()> {
                success: false,
                data: None,
                error: Some("Not found".to_string()),
            },
        )?),
    }
}

fn json_response<T: Serialize>(status: u16, body: &T) -> Result<Response<Body>, Error> {
    let json = serde_json::to_string(body)?;
    Ok(Response::builder()
        .status(status)
        .header("Content-Type", "application/json")
        .header("Access-Control-Allow-Origin", "*")
        .body(Body::from(json))?)
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
