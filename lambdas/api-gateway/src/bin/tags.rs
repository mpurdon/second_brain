//! Tag Management Lambda - Handles tags and taxonomy operations.
//!
//! Endpoints:
//! - POST /tags - Create a tag
//! - GET /tags - List/search tags
//! - GET /tags/{id} - Get tag details
//! - PUT /tags/{id} - Update tag
//! - DELETE /tags/{id} - Delete tag
//! - POST /facts/{id}/tags - Apply tags to a fact
//! - GET /facts/{id}/tags - Get fact's tags
//! - DELETE /facts/{id}/tags/{tagId} - Remove tag from fact
//! - GET /tags/{id}/facts - Get facts with a specific tag

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Create tag request
#[derive(Debug, Deserialize)]
struct CreateTagRequest {
    name: String,
    path: String,
    parent_path: Option<String>,
    description: Option<String>,
    color: Option<String>,
    icon: Option<String>,
}

/// Update tag request
#[derive(Debug, Deserialize)]
struct UpdateTagRequest {
    name: Option<String>,
    description: Option<String>,
    color: Option<String>,
    icon: Option<String>,
}

/// Apply tags request
#[derive(Debug, Deserialize)]
struct ApplyTagsRequest {
    tag_paths: Vec<String>,
    confidence: Option<f64>,
}

/// Tag response
#[derive(Debug, Serialize)]
struct TagResponse {
    id: String,
    name: String,
    path: String,
    description: Option<String>,
    color: Option<String>,
    icon: Option<String>,
    is_system: bool,
    fact_count: i64,
    children: Vec<TagChildResponse>,
}

#[derive(Debug, Serialize)]
struct TagChildResponse {
    id: String,
    name: String,
    path: String,
}

/// Fact with tags response
#[derive(Debug, Serialize)]
struct FactWithTagsResponse {
    id: String,
    content: String,
    importance: i16,
    recorded_at: String,
    tags: Vec<TagSummary>,
}

#[derive(Debug, Serialize)]
struct TagSummary {
    id: String,
    name: String,
    path: String,
    color: Option<String>,
}

/// Tag statistics response
#[derive(Debug, Serialize)]
struct TagStatsResponse {
    path: String,
    name: String,
    fact_count: i64,
    children: Vec<TagStatsResponse>,
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

    info!("Received request: method={}, path={} (raw: {})", method, path, raw_path);

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

    // Get user's family IDs for permission checks
    let family_ids: Vec<Uuid> = sqlx::query_scalar(
        "SELECT family_id FROM family_members WHERE user_id = $1"
    )
    .bind(user_id)
    .fetch_all(&state.db_pool)
    .await
    .unwrap_or_default();

    match (method, path) {
        // Create tag
        ("POST", "/tags") => {
            let body = event.body();
            let request: CreateTagRequest = serde_json::from_slice(body)
                .map_err(|e| format!("Invalid request body: {}", e))?;

            // Validate path format
            if !request.path.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '/') {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Path must contain only lowercase letters, numbers, underscores, and slashes".to_string()),
                    },
                )?);
            }

            // Find parent tag if specified
            let parent_id: Option<Uuid> = if let Some(parent_path) = &request.parent_path {
                sqlx::query_scalar("SELECT id FROM tags WHERE path = $1")
                    .bind(parent_path)
                    .fetch_optional(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to find parent tag: {}", e))?
            } else {
                None
            };

            let tag_id = Uuid::new_v4();

            sqlx::query(
                r#"
                INSERT INTO tags (id, name, path, parent_id, description, color, icon, owner_type, owner_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'user', $8)
                "#
            )
            .bind(tag_id)
            .bind(&request.name)
            .bind(&request.path)
            .bind(parent_id)
            .bind(&request.description)
            .bind(&request.color)
            .bind(&request.icon)
            .bind(user_id)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to create tag: {}", e))?;

            info!("Created tag {} ({})", request.name, request.path);

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "tag_id": tag_id.to_string(),
                        "name": request.name,
                        "path": request.path,
                    })),
                    error: None,
                },
            )?)
        }

        // List/search tags
        ("GET", "/tags") => {
            let params = event.query_string_parameters();
            let query = params.first("q");
            let prefix = params.first("prefix");
            let include_system = params.first("include_system")
                .map(|v| v == "true")
                .unwrap_or(true);
            let limit: i64 = params.first("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(50);

            let tags: Vec<(Uuid, String, String, Option<String>, Option<String>, Option<String>, bool, i64)> =
                if let Some(prefix_path) = prefix {
                    // Autocomplete: search by path prefix
                    sqlx::query_as(
                        r#"
                        SELECT t.id, t.name, t.path, t.description, t.color, t.icon,
                               (t.owner_type IS NULL) as is_system,
                               COALESCE(COUNT(ft.fact_id), 0) as fact_count
                        FROM tags t
                        LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                        WHERE t.path LIKE $1 || '%'
                        AND (
                            t.owner_type IS NULL
                            OR (t.owner_type = 'user' AND t.owner_id = $2)
                            OR (t.owner_type = 'family' AND t.owner_id = ANY($3))
                        )
                        GROUP BY t.id
                        ORDER BY t.path
                        LIMIT $4
                        "#
                    )
                    .bind(prefix_path)
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                } else if let Some(q) = query {
                    // Search by name
                    sqlx::query_as(
                        r#"
                        SELECT t.id, t.name, t.path, t.description, t.color, t.icon,
                               (t.owner_type IS NULL) as is_system,
                               COALESCE(COUNT(ft.fact_id), 0) as fact_count
                        FROM tags t
                        LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                        WHERE t.name ILIKE $1
                        AND (
                            t.owner_type IS NULL
                            OR (t.owner_type = 'user' AND t.owner_id = $2)
                            OR (t.owner_type = 'family' AND t.owner_id = ANY($3))
                        )
                        GROUP BY t.id
                        ORDER BY fact_count DESC, t.name
                        LIMIT $4
                        "#
                    )
                    .bind(format!("%{}%", q))
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                } else {
                    // List all accessible tags
                    let system_filter = if include_system { "1=1" } else { "t.owner_type IS NOT NULL" };
                    sqlx::query_as(
                        &format!(r#"
                        SELECT t.id, t.name, t.path, t.description, t.color, t.icon,
                               (t.owner_type IS NULL) as is_system,
                               COALESCE(COUNT(ft.fact_id), 0) as fact_count
                        FROM tags t
                        LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                        WHERE {}
                        AND (
                            t.owner_type IS NULL
                            OR (t.owner_type = 'user' AND t.owner_id = $1)
                            OR (t.owner_type = 'family' AND t.owner_id = ANY($2))
                        )
                        GROUP BY t.id
                        ORDER BY t.path
                        LIMIT $3
                        "#, system_filter)
                    )
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                }
                .map_err(|e| format!("Failed to fetch tags: {}", e))?;

            let response: Vec<serde_json::Value> = tags.into_iter()
                .map(|(id, name, path, description, color, icon, is_system, fact_count)| {
                    serde_json::json!({
                        "id": id.to_string(),
                        "name": name,
                        "path": path,
                        "description": description,
                        "color": color,
                        "icon": icon,
                        "is_system": is_system,
                        "fact_count": fact_count,
                    })
                })
                .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "count": response.len(),
                        "tags": response,
                    })),
                    error: None,
                },
            )?)
        }

        // Tag statistics (tree view)
        ("GET", "/tags/stats") => {
            let params = event.query_string_parameters();
            let root_path = params.first("root").unwrap_or("");

            let stats: Vec<(String, String, i64)> = sqlx::query_as(
                r#"
                SELECT t.path, t.name, COALESCE(COUNT(ft.fact_id), 0) as fact_count
                FROM tags t
                LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                WHERE t.path LIKE $1 || '%'
                AND (
                    t.owner_type IS NULL
                    OR (t.owner_type = 'user' AND t.owner_id = $2)
                    OR (t.owner_type = 'family' AND t.owner_id = ANY($3))
                )
                GROUP BY t.id
                ORDER BY t.path
                "#
            )
            .bind(root_path)
            .bind(user_id)
            .bind(&family_ids)
            .fetch_all(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to fetch tag stats: {}", e))?;

            let response: Vec<serde_json::Value> = stats.into_iter()
                .map(|(path, name, fact_count)| {
                    serde_json::json!({
                        "path": path,
                        "name": name,
                        "fact_count": fact_count,
                    })
                })
                .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(response),
                    error: None,
                },
            )?)
        }

        // Tag suggestions for a specific fact
        ("POST", "/tags/suggestions") => {
            #[derive(Deserialize)]
            struct SuggestRequest {
                fact_id: Option<String>,
                content: Option<String>,
                entity_type: Option<String>,
            }

            let body = event.body();
            let body_str = std::str::from_utf8(body.as_ref()).unwrap_or("{}");
            let request: SuggestRequest = serde_json::from_str(body_str)
                .map_err(|_| "Invalid request body")?;

            let mut suggestions: Vec<serde_json::Value> = Vec::new();

            // If fact_id provided, get suggestions based on entity and similar facts
            if let Some(fact_id_str) = &request.fact_id {
                let fact_id = Uuid::parse_str(fact_id_str)
                    .map_err(|_| "Invalid fact ID")?;

                // Get fact's entity type for suggestions
                let entity_type: Option<String> = sqlx::query_scalar(
                    r#"
                    SELECT e.entity_type::text
                    FROM facts f
                    JOIN entities e ON e.id = f.about_entity_id
                    WHERE f.id = $1
                    "#
                )
                .bind(fact_id)
                .fetch_optional(&state.db_pool)
                .await
                .map_err(|e| format!("Failed to fetch fact: {}", e))?;

                // Suggest tags commonly used with this entity type
                if let Some(et) = entity_type {
                    let entity_tags: Vec<(String, String, i64)> = sqlx::query_as(
                        r#"
                        SELECT t.path, t.name, COUNT(*) as usage_count
                        FROM tags t
                        JOIN fact_tags ft ON ft.tag_id = t.id
                        JOIN facts f ON f.id = ft.fact_id
                        JOIN entities e ON e.id = f.about_entity_id
                        WHERE e.entity_type::text = $1
                        AND (t.owner_type IS NULL OR t.owner_type = 'user' AND t.owner_id = $2)
                        AND ft.fact_id != $3
                        GROUP BY t.id
                        ORDER BY usage_count DESC
                        LIMIT 5
                        "#
                    )
                    .bind(&et)
                    .bind(user_id)
                    .bind(fact_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch suggestions: {}", e))?;

                    for (path, name, usage) in entity_tags {
                        let confidence = (0.5 + (usage as f64 / 20.0)).min(0.9);
                        suggestions.push(serde_json::json!({
                            "path": path,
                            "name": name,
                            "reason": format!("commonly used with {} entities", et),
                            "confidence": confidence,
                        }));
                    }
                }
            }

            // Suggest based on content keywords if provided
            if let Some(content) = &request.content {
                let keyword_tags: Vec<(String, String)> = sqlx::query_as(
                    r#"
                    SELECT t.path, t.name
                    FROM tags t
                    WHERE (t.owner_type IS NULL OR t.owner_type = 'user' AND t.owner_id = $2)
                    AND ($1 ILIKE '%' || t.name || '%')
                    LIMIT 5
                    "#
                )
                .bind(content)
                .bind(user_id)
                .fetch_all(&state.db_pool)
                .await
                .map_err(|e| format!("Failed to fetch keyword suggestions: {}", e))?;

                for (path, name) in keyword_tags {
                    if !suggestions.iter().any(|s| s["path"] == path) {
                        suggestions.push(serde_json::json!({
                            "path": path,
                            "name": name,
                            "reason": "keyword match in content",
                            "confidence": 0.7,
                        }));
                    }
                }
            }

            // Sort by confidence
            suggestions.sort_by(|a, b| {
                let conf_a = a["confidence"].as_f64().unwrap_or(0.0);
                let conf_b = b["confidence"].as_f64().unwrap_or(0.0);
                conf_b.partial_cmp(&conf_a).unwrap_or(std::cmp::Ordering::Equal)
            });

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "suggestions": suggestions,
                    })),
                    error: None,
                },
            )?)
        }

        // Fact tagging routes
        _ if path.starts_with("/facts/") && path.contains("/tags") => {
            let path_parts: Vec<&str> = path
                .trim_start_matches("/facts/")
                .split('/')
                .collect();

            let fact_id = Uuid::parse_str(path_parts[0])
                .map_err(|_| "Invalid fact ID")?;

            // Verify access to fact
            let has_access: bool = sqlx::query_scalar(
                r#"
                SELECT EXISTS(
                    SELECT 1 FROM facts f
                    WHERE f.id = $1
                    AND (
                        (f.owner_type = 'user' AND f.owner_id = $2)
                        OR (f.owner_type = 'family' AND f.owner_id = ANY($3))
                    )
                )
                "#
            )
            .bind(fact_id)
            .bind(user_id)
            .bind(&family_ids)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to verify access: {}", e))?;

            if !has_access {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Fact not found".to_string()),
                    },
                )?);
            }

            match (method, path_parts.get(1), path_parts.get(2)) {
                // Get fact's tags
                ("GET", Some(&"tags"), None) => {
                    let tags: Vec<TagSummary> = sqlx::query_as::<_, (Uuid, String, String, Option<String>)>(
                        r#"
                        SELECT t.id, t.name, t.path, t.color
                        FROM tags t
                        JOIN fact_tags ft ON ft.tag_id = t.id
                        WHERE ft.fact_id = $1
                        ORDER BY t.path
                        "#
                    )
                    .bind(fact_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch tags: {}", e))?
                    .into_iter()
                    .map(|(id, name, path, color)| TagSummary {
                        id: id.to_string(),
                        name,
                        path,
                        color,
                    })
                    .collect();

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(tags),
                            error: None,
                        },
                    )?)
                }

                // Apply tags to fact
                ("POST", Some(&"tags"), None) => {
                    let body = event.body();
                    let request: ApplyTagsRequest = serde_json::from_slice(body)
                        .map_err(|e| format!("Invalid request body: {}", e))?;

                    let confidence = request.confidence.unwrap_or(1.0);
                    let mut applied = Vec::new();

                    for tag_path in &request.tag_paths {
                        // Find tag by path
                        let tag_id: Option<Uuid> = sqlx::query_scalar(
                            "SELECT id FROM tags WHERE path = $1"
                        )
                        .bind(tag_path)
                        .fetch_optional(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to find tag: {}", e))?;

                        if let Some(tid) = tag_id {
                            sqlx::query(
                                r#"
                                INSERT INTO fact_tags (fact_id, tag_id, confidence, assigned_by)
                                VALUES ($1, $2, $3, 'user')
                                ON CONFLICT (fact_id, tag_id) DO UPDATE SET
                                    confidence = EXCLUDED.confidence
                                "#
                            )
                            .bind(fact_id)
                            .bind(tid)
                            .bind(confidence)
                            .execute(&state.db_pool)
                            .await
                            .map_err(|e| format!("Failed to apply tag: {}", e))?;

                            applied.push(tag_path.clone());
                        }
                    }

                    info!("Applied {} tags to fact {}", applied.len(), fact_id);

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({
                                "fact_id": fact_id.to_string(),
                                "tags_applied": applied,
                            })),
                            error: None,
                        },
                    )?)
                }

                // Remove tag from fact
                ("DELETE", Some(&"tags"), Some(tag_id_str)) => {
                    let tag_id = Uuid::parse_str(tag_id_str)
                        .map_err(|_| "Invalid tag ID")?;

                    sqlx::query("DELETE FROM fact_tags WHERE fact_id = $1 AND tag_id = $2")
                        .bind(fact_id)
                        .bind(tag_id)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to remove tag: {}", e))?;

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({"message": "Tag removed"})),
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

        // Tag-specific routes
        _ if path.starts_with("/tags/") => {
            let path_parts: Vec<&str> = path
                .trim_start_matches("/tags/")
                .split('/')
                .collect();

            // Handle /tags/stats separately (already handled above)
            if path_parts[0] == "stats" {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Not found".to_string()),
                    },
                )?);
            }

            let tag_id = Uuid::parse_str(path_parts[0])
                .map_err(|_| "Invalid tag ID")?;

            match (method, path_parts.get(1)) {
                // Get tag details
                ("GET", None) => {
                    let tag = sqlx::query_as::<_, (Uuid, String, String, Option<String>, Option<String>, Option<String>, bool, i64)>(
                        r#"
                        SELECT t.id, t.name, t.path, t.description, t.color, t.icon,
                               (t.owner_type IS NULL) as is_system,
                               COALESCE(COUNT(ft.fact_id), 0) as fact_count
                        FROM tags t
                        LEFT JOIN fact_tags ft ON ft.tag_id = t.id
                        WHERE t.id = $1
                        GROUP BY t.id
                        "#
                    )
                    .bind(tag_id)
                    .fetch_optional(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch tag: {}", e))?;

                    if let Some((id, name, path, description, color, icon, is_system, fact_count)) = tag {
                        // Get children
                        let children: Vec<TagChildResponse> = sqlx::query_as::<_, (Uuid, String, String)>(
                            "SELECT id, name, path FROM tags WHERE parent_id = $1 ORDER BY name"
                        )
                        .bind(tag_id)
                        .fetch_all(&state.db_pool)
                        .await
                        .unwrap_or_default()
                        .into_iter()
                        .map(|(id, name, path)| TagChildResponse {
                            id: id.to_string(),
                            name,
                            path,
                        })
                        .collect();

                        Ok(json_response(
                            200,
                            &ApiResponse {
                                success: true,
                                data: Some(TagResponse {
                                    id: id.to_string(),
                                    name,
                                    path,
                                    description,
                                    color,
                                    icon,
                                    is_system,
                                    fact_count,
                                    children,
                                }),
                                error: None,
                            },
                        )?)
                    } else {
                        Ok(json_response(
                            404,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Tag not found".to_string()),
                            },
                        )?)
                    }
                }

                // Update tag
                ("PUT", None) => {
                    // Check if it's a system tag
                    let is_system: bool = sqlx::query_scalar(
                        "SELECT owner_type IS NULL FROM tags WHERE id = $1"
                    )
                    .bind(tag_id)
                    .fetch_one(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to check tag: {}", e))?;

                    if is_system {
                        return Ok(json_response(
                            403,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Cannot modify system tags".to_string()),
                            },
                        )?);
                    }

                    let body = event.body();
                    let request: UpdateTagRequest = serde_json::from_slice(body)
                        .map_err(|e| format!("Invalid request body: {}", e))?;

                    if let Some(name) = &request.name {
                        sqlx::query("UPDATE tags SET name = $2 WHERE id = $1")
                            .bind(tag_id)
                            .bind(name)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(desc) = &request.description {
                        sqlx::query("UPDATE tags SET description = $2 WHERE id = $1")
                            .bind(tag_id)
                            .bind(desc)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(color) = &request.color {
                        sqlx::query("UPDATE tags SET color = $2 WHERE id = $1")
                            .bind(tag_id)
                            .bind(color)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(icon) = &request.icon {
                        sqlx::query("UPDATE tags SET icon = $2 WHERE id = $1")
                            .bind(tag_id)
                            .bind(icon)
                            .execute(&state.db_pool)
                            .await?;
                    }

                    info!("Updated tag {}", tag_id);

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({"message": "Tag updated"})),
                            error: None,
                        },
                    )?)
                }

                // Delete tag
                ("DELETE", None) => {
                    // Check if it's a system tag
                    let is_system: bool = sqlx::query_scalar(
                        "SELECT owner_type IS NULL FROM tags WHERE id = $1"
                    )
                    .bind(tag_id)
                    .fetch_one(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to check tag: {}", e))?;

                    if is_system {
                        return Ok(json_response(
                            403,
                            &ApiResponse::<()> {
                                success: false,
                                data: None,
                                error: Some("Cannot delete system tags".to_string()),
                            },
                        )?);
                    }

                    sqlx::query("DELETE FROM tags WHERE id = $1")
                        .bind(tag_id)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to delete tag: {}", e))?;

                    info!("Deleted tag {}", tag_id);

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({"message": "Tag deleted"})),
                            error: None,
                        },
                    )?)
                }

                // Get facts with this tag
                ("GET", Some(&"facts")) => {
                    let params = event.query_string_parameters();
                    let limit: i64 = params.first("limit")
                        .and_then(|l| l.parse().ok())
                        .unwrap_or(50);

                    let facts: Vec<FactWithTagsResponse> = sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>)>(
                        r#"
                        SELECT f.id, f.content, f.importance, f.recorded_at
                        FROM facts f
                        JOIN fact_tags ft ON ft.fact_id = f.id
                        WHERE ft.tag_id = $1
                        AND (
                            (f.owner_type = 'user' AND f.owner_id = $2)
                            OR (f.owner_type = 'family' AND f.owner_id = ANY($3))
                        )
                        ORDER BY f.importance DESC, f.recorded_at DESC
                        LIMIT $4
                        "#
                    )
                    .bind(tag_id)
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch facts: {}", e))?
                    .into_iter()
                    .map(|(id, content, importance, recorded_at)| FactWithTagsResponse {
                        id: id.to_string(),
                        content,
                        importance,
                        recorded_at: recorded_at.to_rfc3339(),
                        tags: vec![], // We already know the tag
                    })
                    .collect();

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(serde_json::json!({
                                "tag_id": tag_id.to_string(),
                                "count": facts.len(),
                                "facts": facts,
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
