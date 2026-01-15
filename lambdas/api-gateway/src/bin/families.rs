//! Family Management Lambda - Handles family CRUD operations.
//!
//! Endpoints:
//! - POST /v1/families - Create a new family
//! - GET /v1/families - List user's families
//! - GET /v1/families/{id} - Get family details
//! - POST /v1/families/{id}/members - Invite member
//! - DELETE /v1/families/{id}/members/{user_id} - Remove member

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Create family request
#[derive(Debug, Deserialize)]
struct CreateFamilyRequest {
    name: String,
    description: Option<String>,
}

/// Invite member request
#[derive(Debug, Deserialize)]
struct InviteMemberRequest {
    email: String,
    role: Option<String>, // "admin" or "member"
}

/// Family response
#[derive(Debug, Serialize)]
struct FamilyResponse {
    id: String,
    name: String,
    description: Option<String>,
    created_by: String,
    created_at: String,
    member_count: i64,
}

/// Family member response
#[derive(Debug, Serialize)]
struct FamilyMemberResponse {
    user_id: String,
    email: String,
    display_name: Option<String>,
    role: String,
    joined_at: String,
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

        // Get database credentials
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

/// Extract user_id from Cognito claims in request context
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
    let path = event.uri().path();
    let method = event.method().as_str();

    // Extract user_id from auth context
    let user_id = match extract_user_id(&event) {
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

    match (method, path) {
        // Create family
        ("POST", "/v1/families") => {
            let body = event.body();
            let request: CreateFamilyRequest = serde_json::from_slice(body)
                .map_err(|e| format!("Invalid request body: {}", e))?;

            let family_id = Uuid::new_v4();

            // Create family
            sqlx::query(
                r#"
                INSERT INTO families (id, name, description, created_by)
                VALUES ($1, $2, $3, $4)
                "#,
            )
            .bind(family_id)
            .bind(&request.name)
            .bind(&request.description)
            .bind(user_id)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to create family: {}", e))?;

            // Add creator as admin member
            sqlx::query(
                r#"
                INSERT INTO family_members (family_id, user_id, role)
                VALUES ($1, $2, 'admin')
                "#,
            )
            .bind(family_id)
            .bind(user_id)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to add creator as member: {}", e))?;

            info!("Created family {} by user {}", family_id, user_id);

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "family_id": family_id.to_string(),
                        "name": request.name,
                    })),
                    error: None,
                },
            )?)
        }

        // List user's families
        ("GET", "/v1/families") => {
            let families: Vec<FamilyResponse> = sqlx::query_as::<_, (Uuid, String, Option<String>, Uuid, chrono::DateTime<chrono::Utc>, i64)>(
                r#"
                SELECT f.id, f.name, f.description, f.created_by, f.created_at,
                       (SELECT COUNT(*) FROM family_members fm WHERE fm.family_id = f.id) as member_count
                FROM families f
                JOIN family_members fm ON fm.family_id = f.id
                WHERE fm.user_id = $1
                ORDER BY f.name
                "#,
            )
            .bind(user_id)
            .fetch_all(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch families: {}", e))?
            .into_iter()
            .map(|(id, name, description, created_by, created_at, member_count)| FamilyResponse {
                id: id.to_string(),
                name,
                description,
                created_by: created_by.to_string(),
                created_at: created_at.to_rfc3339(),
                member_count,
            })
            .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(families),
                    error: None,
                },
            )?)
        }

        // Get family details or members
        _ if path.starts_with("/v1/families/") => {
            let path_parts: Vec<&str> = path.trim_start_matches("/v1/families/").split('/').collect();

            let family_id = Uuid::parse_str(path_parts[0])
                .map_err(|_| "Invalid family ID")?;

            // Verify user is a member of this family
            let is_member: bool = sqlx::query_scalar(
                "SELECT EXISTS(SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2)"
            )
            .bind(family_id)
            .bind(user_id)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to check membership: {}", e))?;

            if !is_member {
                return Ok(json_response(
                    403,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Not a member of this family".to_string()),
                    },
                )?);
            }

            match (method, path_parts.len()) {
                // GET /v1/families/{id} - Get family details
                ("GET", 1) => {
                    let family: Option<(Uuid, String, Option<String>, Uuid, chrono::DateTime<chrono::Utc>)> =
                        sqlx::query_as(
                            "SELECT id, name, description, created_by, created_at FROM families WHERE id = $1"
                        )
                        .bind(family_id)
                        .fetch_optional(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to fetch family: {}", e))?;

                    match family {
                        Some((id, name, description, created_by, created_at)) => {
                            // Get members
                            let members: Vec<FamilyMemberResponse> = sqlx::query_as::<_, (Uuid, String, Option<String>, String, chrono::DateTime<chrono::Utc>)>(
                                r#"
                                SELECT u.id, u.email, u.display_name, fm.role, fm.joined_at
                                FROM family_members fm
                                JOIN users u ON u.id = fm.user_id
                                WHERE fm.family_id = $1
                                ORDER BY fm.role DESC, fm.joined_at
                                "#,
                            )
                            .bind(family_id)
                            .fetch_all(&state.db_pool)
                            .await
                            .map_err(|e| format!("Failed to fetch members: {}", e))?
                            .into_iter()
                            .map(|(user_id, email, display_name, role, joined_at)| FamilyMemberResponse {
                                user_id: user_id.to_string(),
                                email,
                                display_name,
                                role,
                                joined_at: joined_at.to_rfc3339(),
                            })
                            .collect();

                            Ok(json_response(
                                200,
                                &ApiResponse {
                                    success: true,
                                    data: Some(serde_json::json!({
                                        "id": id.to_string(),
                                        "name": name,
                                        "description": description,
                                        "created_by": created_by.to_string(),
                                        "created_at": created_at.to_rfc3339(),
                                        "members": members,
                                    })),
                                    error: None,
                                },
                            )?)
                        }
                        None => Ok(json_response(
                            404,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Family not found".to_string()),
                            },
                        )?),
                    }
                }

                // POST /v1/families/{id}/members - Invite member
                ("POST", 2) if path_parts[1] == "members" => {
                    // Check if user is admin
                    let is_admin: bool = sqlx::query_scalar(
                        "SELECT EXISTS(SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2 AND role = 'admin')"
                    )
                    .bind(family_id)
                    .bind(user_id)
                    .fetch_one(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to check admin status: {}", e))?;

                    if !is_admin {
                        return Ok(json_response(
                            403,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Only admins can invite members".to_string()),
                            },
                        )?);
                    }

                    let body = event.body();
                    let request: InviteMemberRequest = serde_json::from_slice(body)
                        .map_err(|e| format!("Invalid request body: {}", e))?;

                    // Find user by email
                    let invitee: Option<Uuid> = sqlx::query_scalar(
                        "SELECT id FROM users WHERE email = $1"
                    )
                    .bind(&request.email)
                    .fetch_optional(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to find user: {}", e))?;

                    match invitee {
                        Some(invitee_id) => {
                            // Add member
                            let role = request.role.unwrap_or_else(|| "member".to_string());

                            sqlx::query(
                                r#"
                                INSERT INTO family_members (family_id, user_id, role)
                                VALUES ($1, $2, $3)
                                ON CONFLICT (family_id, user_id) DO NOTHING
                                "#,
                            )
                            .bind(family_id)
                            .bind(invitee_id)
                            .bind(&role)
                            .execute(&state.db_pool)
                            .await
                            .map_err(|e| format!("Failed to add member: {}", e))?;

                            info!("Added user {} to family {} with role {}", invitee_id, family_id, role);

                            Ok(json_response(
                                200,
                                &ApiResponse {
                                    success: true,
                                    data: Some(serde_json::json!({
                                        "message": "Member added successfully",
                                        "user_id": invitee_id.to_string(),
                                        "role": role,
                                    })),
                                    error: None,
                                },
                            )?)
                        }
                        None => Ok(json_response(
                            404,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("User not found with that email".to_string()),
                            },
                        )?),
                    }
                }

                // DELETE /v1/families/{id}/members/{user_id} - Remove member
                ("DELETE", 3) if path_parts[1] == "members" => {
                    let target_user_id = Uuid::parse_str(path_parts[2])
                        .map_err(|_| "Invalid user ID")?;

                    // Check if requester is admin or removing themselves
                    let is_admin: bool = sqlx::query_scalar(
                        "SELECT EXISTS(SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2 AND role = 'admin')"
                    )
                    .bind(family_id)
                    .bind(user_id)
                    .fetch_one(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to check admin status: {}", e))?;

                    if !is_admin && user_id != target_user_id {
                        return Ok(json_response(
                            403,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Only admins can remove other members".to_string()),
                            },
                        )?);
                    }

                    // Remove member
                    let result = sqlx::query(
                        "DELETE FROM family_members WHERE family_id = $1 AND user_id = $2"
                    )
                    .bind(family_id)
                    .bind(target_user_id)
                    .execute(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to remove member: {}", e))?;

                    if result.rows_affected() > 0 {
                        info!("Removed user {} from family {}", target_user_id, family_id);
                        Ok(json_response(
                            200,
                            &ApiResponse {
                                success: true,
                                data: Some(serde_json::json!({
                                    "message": "Member removed successfully"
                                })),
                                error: None,
                            },
                        )?)
                    } else {
                        Ok(json_response(
                            404,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Member not found".to_string()),
                            },
                        )?)
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
