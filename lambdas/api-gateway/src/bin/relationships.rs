//! Relationship Management Lambda - Handles user relationships and access tiers.
//!
//! Endpoints:
//! - POST /relationships - Create a relationship
//! - GET /relationships - List user's relationships
//! - PUT /relationships/{id} - Update access tier
//! - DELETE /relationships/{id} - Remove relationship

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Relationship types
const RELATIONSHIP_TYPES: [&str; 8] = [
    "spouse", "parent", "child", "sibling", "grandparent", "grandchild", "friend", "other"
];

/// Create relationship request
#[derive(Debug, Deserialize)]
struct CreateRelationshipRequest {
    target_user_id: String,
    relationship_type: String,
    access_tier: Option<i16>, // 1-4, defaults based on type
    bidirectional: Option<bool>,
}

/// Update relationship request
#[derive(Debug, Deserialize)]
struct UpdateRelationshipRequest {
    access_tier: i16,
}

/// Relationship response
#[derive(Debug, Serialize)]
struct RelationshipResponse {
    id: String,
    source_user_id: String,
    target_user_id: String,
    relationship_type: String,
    access_tier: i16,
    created_at: String,
    target_user_name: Option<String>,
    target_user_email: Option<String>,
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

/// Get default access tier based on relationship type
fn default_access_tier(relationship_type: &str) -> i16 {
    match relationship_type {
        "spouse" | "parent" => 1, // Full access
        "child" => 2,              // High access (parent sees child's data)
        "sibling" => 3,            // Medium access
        "grandparent" | "grandchild" => 3, // Medium access
        "friend" => 4,             // Low access
        _ => 4,                    // Default to low
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
        .ok_or("Missing claims in authorizer context")?;

    let sub = claims
        .get("sub")
        .and_then(|v| v.as_str())
        .ok_or("Missing sub claim")?;

    Uuid::parse_str(sub).map_err(|e| format!("Invalid user_id: {}", e).into())
}

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    let raw_path = event.uri().path();
    // Strip /api stage prefix if present (API Gateway REST API includes stage in path)
    let path = raw_path.strip_prefix("/api").unwrap_or(raw_path);
    let method = event.method().as_str();

    let cognito_sub = match extract_user_id(&event) {
        Ok(id) => id,
        Err(e) => {
            return Ok(json_response(
                401,
                &ApiResponse::<()> {
                    success: false,
                    data: None,
                    error: Some(format!("Authentication required: {}", e)),
                },
            )?);
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
            )?);
        }
    };

    match (method, path) {
        // Create relationship
        ("POST", "/relationships") => {
            let body = event.body();
            let request: CreateRelationshipRequest = serde_json::from_slice(body)
                .map_err(|e| format!("Invalid request body: {}", e))?;

            // Validate relationship type
            if !RELATIONSHIP_TYPES.contains(&request.relationship_type.as_str()) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some(format!(
                            "Invalid relationship type. Must be one of: {:?}",
                            RELATIONSHIP_TYPES
                        )),
                    },
                )?);
            }

            let target_user_id = Uuid::parse_str(&request.target_user_id)
                .map_err(|_| "Invalid target_user_id")?;

            // Validate target user exists
            let target_exists: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM users WHERE id = $1)"
            )
            .bind(target_user_id)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to verify target user: {}", e))?;

            if !target_exists {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Target user not found".to_string()),
                    },
                )?);
            }

            // Validate access tier
            let access_tier = request.access_tier
                .unwrap_or_else(|| default_access_tier(&request.relationship_type));

            if !(1..=4).contains(&access_tier) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Access tier must be between 1 and 4".to_string()),
                    },
                )?);
            }

            let relationship_id = Uuid::new_v4();

            // Create relationship
            sqlx::query(
                r#"
                INSERT INTO relationships (id, source_user_id, target_user_id, relationship_type, access_tier)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (source_user_id, target_user_id) DO UPDATE SET
                    relationship_type = EXCLUDED.relationship_type,
                    access_tier = EXCLUDED.access_tier
                "#,
            )
            .bind(relationship_id)
            .bind(user_id)
            .bind(target_user_id)
            .bind(&request.relationship_type)
            .bind(access_tier)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to create relationship: {}", e))?;

            // Create bidirectional relationship if requested
            if request.bidirectional.unwrap_or(false) {
                let reverse_type = get_reverse_relationship_type(&request.relationship_type);
                let reverse_tier = default_access_tier(&reverse_type);

                sqlx::query(
                    r#"
                    INSERT INTO relationships (id, source_user_id, target_user_id, relationship_type, access_tier)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (source_user_id, target_user_id) DO UPDATE SET
                        relationship_type = EXCLUDED.relationship_type,
                        access_tier = EXCLUDED.access_tier
                    "#,
                )
                .bind(Uuid::new_v4())
                .bind(target_user_id)
                .bind(user_id)
                .bind(&reverse_type)
                .bind(reverse_tier)
                .execute(&state.db_pool)
                .await
                .map_err(|e| format!("Failed to create reverse relationship: {}", e))?;
            }

            // Refresh access cache
            refresh_access_cache(&state.db_pool, user_id).await?;
            if request.bidirectional.unwrap_or(false) {
                refresh_access_cache(&state.db_pool, target_user_id).await?;
            }

            info!(
                "Created relationship {} -> {} ({})",
                user_id, target_user_id, request.relationship_type
            );

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "relationship_id": relationship_id.to_string(),
                        "relationship_type": request.relationship_type,
                        "access_tier": access_tier,
                    })),
                    error: None,
                },
            )?)
        }

        // List relationships
        ("GET", "/relationships") => {
            let relationships: Vec<RelationshipResponse> = sqlx::query_as::<_, (Uuid, Uuid, Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<String>, Option<String>)>(
                r#"
                SELECT r.id, r.source_user_id, r.target_user_id, r.relationship_type,
                       r.access_tier, r.created_at, u.display_name, u.email
                FROM relationships r
                JOIN users u ON u.id = r.target_user_id
                WHERE r.source_user_id = $1
                ORDER BY r.access_tier, r.relationship_type
                "#,
            )
            .bind(user_id)
            .fetch_all(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch relationships: {}", e))?
            .into_iter()
            .map(|(id, source_user_id, target_user_id, relationship_type, access_tier, created_at, target_user_name, target_user_email)| {
                RelationshipResponse {
                    id: id.to_string(),
                    source_user_id: source_user_id.to_string(),
                    target_user_id: target_user_id.to_string(),
                    relationship_type,
                    access_tier,
                    created_at: created_at.to_rfc3339(),
                    target_user_name,
                    target_user_email,
                }
            })
            .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(relationships),
                    error: None,
                },
            )?)
        }

        // Update or delete specific relationship
        _ if path.starts_with("/relationships/") => {
            let relationship_id = path
                .trim_start_matches("/relationships/")
                .split('/')
                .next()
                .ok_or("Missing relationship ID")?;

            let relationship_id = Uuid::parse_str(relationship_id)
                .map_err(|_| "Invalid relationship ID")?;

            // Verify ownership
            let owns_relationship: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM relationships WHERE id = $1 AND source_user_id = $2)"
            )
            .bind(relationship_id)
            .bind(user_id)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to verify ownership: {}", e))?;

            if !owns_relationship {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Relationship not found".to_string()),
                    },
                )?);
            }

            match method {
                // Update access tier
                "PUT" => {
                    let body = event.body();
                    let request: UpdateRelationshipRequest = serde_json::from_slice(body)
                        .map_err(|e| format!("Invalid request body: {}", e))?;

                    if !(1..=4).contains(&request.access_tier) {
                        return Ok(json_response(
                            400,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Access tier must be between 1 and 4".to_string()),
                            },
                        )?);
                    }

                    sqlx::query(
                        "UPDATE relationships SET access_tier = $1 WHERE id = $2"
                    )
                    .bind(request.access_tier)
                    .bind(relationship_id)
                    .execute(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to update relationship: {}", e))?;

                    // Refresh access cache
                    refresh_access_cache(&state.db_pool, user_id).await?;

                    info!("Updated relationship {} to tier {}", relationship_id, request.access_tier);

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({
                                "message": "Relationship updated",
                                "access_tier": request.access_tier,
                            })),
                            error: None,
                        },
                    )?)
                }

                // Delete relationship
                "DELETE" => {
                    sqlx::query("DELETE FROM relationships WHERE id = $1")
                        .bind(relationship_id)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to delete relationship: {}", e))?;

                    // Refresh access cache
                    refresh_access_cache(&state.db_pool, user_id).await?;

                    info!("Deleted relationship {}", relationship_id);

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({
                                "message": "Relationship deleted"
                            })),
                            error: None,
                        },
                    )?)
                }

                _ => Ok(json_response(
                    405,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Method not allowed".to_string()),
                    },
                )?),
            }
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

/// Get the reverse relationship type for bidirectional relationships
fn get_reverse_relationship_type(relationship_type: &str) -> String {
    match relationship_type {
        "parent" => "child".to_string(),
        "child" => "parent".to_string(),
        "grandparent" => "grandchild".to_string(),
        "grandchild" => "grandparent".to_string(),
        // Symmetric relationships
        "spouse" | "sibling" | "friend" | "other" => relationship_type.to_string(),
        _ => "other".to_string(),
    }
}

/// Refresh the user_access_cache for a user using the database function
async fn refresh_access_cache(pool: &PgPool, user_id: Uuid) -> Result<(), Error> {
    // Use the database function to properly refresh the cache
    sqlx::query("SELECT refresh_user_access_cache($1)")
        .bind(user_id)
        .execute(pool)
        .await
        .map_err(|e| format!("Failed to refresh access cache: {}", e))?;

    Ok(())
}

fn json_response<T: Serialize>(status: u16, data: &T) -> Result<Response<Body>, Error> {
    Ok(Response::builder()
        .status(status)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_string(data)?))
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
