//! User Feedback Lambda - Tracks user interactions for learning.
//!
//! Endpoints:
//! - POST /v1/feedback - Record feedback
//! - GET /v1/feedback/stats - Get user's feedback stats
//! - POST /v1/queries/{id}/feedback - Rate a query response

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Record feedback request
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RecordFeedbackRequest {
    feedback_type: String,
    context_type: String,
    context_id: Option<String>,
    action: String,
    rating: Option<i16>,
    metadata: Option<serde_json::Value>,
}

/// Query feedback request (simplified)
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct QueryFeedbackRequest {
    action: String,  // 'thumbs_up' or 'thumbs_down'
    comment: Option<String>,
}

/// Feedback stats response
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct FeedbackStatsResponse {
    total_queries: i32,
    satisfied_queries: i32,
    query_satisfaction_rate: f64,
    total_tag_suggestions: i32,
    accepted_tag_suggestions: i32,
    tag_acceptance_rate: f64,
    total_notifications: i32,
    acted_notifications: i32,
    notification_action_rate: f64,
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

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    let method = event.method().as_str();
    let path = event.uri().path();

    info!("Feedback request: {} {}", method, path);

    // Extract user
    let user_id = match extract_user_id(&event) {
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

    match (method, path) {
        // Record generic feedback
        ("POST", "/v1/feedback") => {
            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: RecordFeedbackRequest = serde_json::from_str(body_str)
                .map_err(|_| "Invalid request body")?;

            // Validate feedback_type
            let valid_types = ["query_satisfaction", "tag_acceptance", "notification_action", "suggestion_action"];
            if !valid_types.contains(&request.feedback_type.as_str()) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Invalid feedback_type".to_string()),
                    },
                )?);
            }

            // Validate action
            let valid_actions = ["accepted", "rejected", "dismissed", "thumbs_up", "thumbs_down", "modified"];
            if !valid_actions.contains(&request.action.as_str()) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Invalid action".to_string()),
                    },
                )?);
            }

            let context_id = request.context_id
                .as_ref()
                .and_then(|id| Uuid::parse_str(id).ok());

            let metadata = request.metadata.unwrap_or(serde_json::json!({}));

            let feedback_id: Uuid = sqlx::query_scalar(
                r#"
                INSERT INTO user_feedback (user_id, feedback_type, context_type, context_id, action, rating, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                "#
            )
            .bind(user_id)
            .bind(&request.feedback_type)
            .bind(&request.context_type)
            .bind(context_id)
            .bind(&request.action)
            .bind(request.rating)
            .bind(&metadata)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to record feedback: {}", e))?;

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "feedbackId": feedback_id.to_string(),
                    })),
                    error: None,
                },
            )?)
        }

        // Get user's feedback stats
        ("GET", "/v1/feedback/stats") => {
            let stats: Option<(i32, i32, f64, i32, i32, f64, i32, i32, f64)> = sqlx::query_as(
                r#"
                SELECT
                    total_queries,
                    satisfied_queries,
                    COALESCE(query_satisfaction_rate, 0)::float8,
                    total_tag_suggestions,
                    accepted_tag_suggestions,
                    COALESCE(tag_acceptance_rate, 0)::float8,
                    total_notifications,
                    acted_notifications,
                    COALESCE(notification_action_rate, 0)::float8
                FROM user_feedback_stats
                WHERE user_id = $1
                "#
            )
            .bind(user_id)
            .fetch_optional(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch stats: {}", e))?;

            let response = if let Some((tq, sq, qsr, tts, ats, tar, tn, an, nar)) = stats {
                FeedbackStatsResponse {
                    total_queries: tq,
                    satisfied_queries: sq,
                    query_satisfaction_rate: qsr,
                    total_tag_suggestions: tts,
                    accepted_tag_suggestions: ats,
                    tag_acceptance_rate: tar,
                    total_notifications: tn,
                    acted_notifications: an,
                    notification_action_rate: nar,
                }
            } else {
                // No stats yet, return zeros
                FeedbackStatsResponse {
                    total_queries: 0,
                    satisfied_queries: 0,
                    query_satisfaction_rate: 0.0,
                    total_tag_suggestions: 0,
                    accepted_tag_suggestions: 0,
                    tag_acceptance_rate: 0.0,
                    total_notifications: 0,
                    acted_notifications: 0,
                    notification_action_rate: 0.0,
                }
            };

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(response),
                    error: None,
                },
            )?)
        }

        // Rate a specific query response
        _ if path.starts_with("/v1/queries/") && path.ends_with("/feedback") => {
            if method != "POST" {
                return Ok(json_response(
                    405,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Method not allowed".to_string()),
                    },
                )?);
            }

            let query_id = path
                .trim_start_matches("/v1/queries/")
                .trim_end_matches("/feedback");

            let query_uuid = Uuid::parse_str(query_id)
                .map_err(|_| "Invalid query ID")?;

            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: QueryFeedbackRequest = serde_json::from_str(body_str)
                .map_err(|_| "Invalid request body")?;

            // Validate action
            if request.action != "thumbs_up" && request.action != "thumbs_down" {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Action must be 'thumbs_up' or 'thumbs_down'".to_string()),
                    },
                )?);
            }

            // Record the feedback
            let mut metadata = serde_json::json!({});
            if let Some(comment) = &request.comment {
                metadata["comment"] = serde_json::Value::String(comment.clone());
            }

            let feedback_id: Uuid = sqlx::query_scalar(
                r#"
                INSERT INTO user_feedback (user_id, feedback_type, context_type, context_id, action, metadata)
                VALUES ($1, 'query_satisfaction', 'query', $2, $3, $4)
                RETURNING id
                "#
            )
            .bind(user_id)
            .bind(query_uuid)
            .bind(&request.action)
            .bind(&metadata)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to record feedback: {}", e))?;

            // Update query session with feedback link
            sqlx::query(
                "UPDATE query_sessions SET feedback_id = $1 WHERE id = $2 AND user_id = $3"
            )
            .bind(feedback_id)
            .bind(query_uuid)
            .bind(user_id)
            .execute(&state.db_pool)
            .await
            .ok(); // Ignore errors (query might not be tracked)

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "feedbackId": feedback_id.to_string(),
                        "queryId": query_id,
                    })),
                    error: None,
                },
            )?)
        }

        // Get recent feedback history
        ("GET", "/v1/feedback/history") => {
            let params = event.query_string_parameters();
            let limit: i32 = params
                .first("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(20);

            let feedback: Vec<(Uuid, String, String, Option<Uuid>, String, Option<i16>, chrono::DateTime<chrono::Utc>)> = sqlx::query_as(
                r#"
                SELECT id, feedback_type, context_type, context_id, action, rating, created_at
                FROM user_feedback
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                "#
            )
            .bind(user_id)
            .bind(limit)
            .fetch_all(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch history: {}", e))?;

            let history: Vec<serde_json::Value> = feedback
                .into_iter()
                .map(|(id, ft, ct, cid, action, rating, created)| {
                    serde_json::json!({
                        "id": id.to_string(),
                        "feedbackType": ft,
                        "contextType": ct,
                        "contextId": cid.map(|u| u.to_string()),
                        "action": action,
                        "rating": rating,
                        "createdAt": created.to_rfc3339(),
                    })
                })
                .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "count": history.len(),
                        "feedback": history,
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
