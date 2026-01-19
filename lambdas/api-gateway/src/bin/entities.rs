//! Entity Management Lambda - CRUD operations for entities.
//!
//! Endpoints:
//! - POST /entities - Create entity
//! - GET /entities - Search/list entities
//! - GET /entities/{id} - Get entity details with timeline
//! - PUT /entities/{id} - Update entity
//! - DELETE /entities/{id} - Delete entity
//! - POST /entities/{id}/relationships - Create entity relationship
//! - GET /entities/{id}/relationships - List entity relationships
//! - GET /entities/{id}/facts - Get facts about entity (timeline)

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Entity types
const ENTITY_TYPES: [&str; 7] = [
    "person", "organization", "place", "project", "event", "product", "custom"
];

/// Create entity request
#[derive(Debug, Deserialize)]
struct CreateEntityRequest {
    name: String,
    entity_type: String,
    description: Option<String>,
    aliases: Option<Vec<String>>,
    metadata: Option<serde_json::Value>,
    visibility_tier: Option<i16>,
}

/// Update entity request
#[derive(Debug, Deserialize)]
struct UpdateEntityRequest {
    name: Option<String>,
    description: Option<String>,
    aliases: Option<Vec<String>>,
    metadata: Option<serde_json::Value>,
    visibility_tier: Option<i16>,
}

/// Create entity relationship request
#[derive(Debug, Deserialize)]
struct CreateRelationshipRequest {
    target_entity_id: String,
    relationship_type: String,
    metadata: Option<serde_json::Value>,
}

/// Entity response
#[derive(Debug, Serialize)]
struct EntityResponse {
    id: String,
    entity_type: String,
    name: String,
    description: Option<String>,
    aliases: Vec<String>,
    visibility_tier: i16,
    created_at: String,
    fact_count: i64,
}

/// Entity detail response
#[derive(Debug, Serialize)]
struct EntityDetailResponse {
    id: String,
    entity_type: String,
    name: String,
    description: Option<String>,
    aliases: Vec<String>,
    metadata: serde_json::Value,
    visibility_tier: i16,
    linked_user_id: Option<String>,
    created_at: String,
    updated_at: String,
    attributes: Vec<EntityAttribute>,
    locations: Vec<EntityLocation>,
    relationships: Vec<EntityRelationship>,
}

#[derive(Debug, Serialize)]
struct EntityAttribute {
    name: String,
    value: String,
    valid_from: Option<String>,
    valid_to: Option<String>,
}

#[derive(Debug, Serialize)]
struct EntityLocation {
    label: String,
    address: Option<String>,
    latitude: Option<f64>,
    longitude: Option<f64>,
}

#[derive(Debug, Serialize)]
struct EntityRelationship {
    id: String,
    related_entity_id: String,
    related_entity_name: String,
    related_entity_type: String,
    relationship_type: String,
    direction: String,
}

#[derive(Debug, Serialize)]
struct FactTimelineEntry {
    id: String,
    content: String,
    importance: i16,
    recorded_at: String,
    valid_from: Option<String>,
    valid_to: Option<String>,
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
                    error: Some("User not registered. Please use the main app to register first.".to_string()),
                },
            )?);
        }
    };

    match (method, path) {
        // Create entity
        ("POST", "/entities") => {
            let request: CreateEntityRequest = match shared::parse_json_body(event.body())? {
                Ok(r) => r,
                Err(response) => return Ok(response),
            };

            // Validate entity type
            if !ENTITY_TYPES.contains(&request.entity_type.as_str()) {
                return Ok(json_response(
                    400,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some(format!(
                            "Invalid entity type. Must be one of: {:?}",
                            ENTITY_TYPES
                        )),
                    },
                )?);
            }

            let entity_id = Uuid::new_v4();
            let visibility = request.visibility_tier.unwrap_or(3);
            let aliases: Vec<String> = request.aliases.unwrap_or_default();
            let metadata = request.metadata.unwrap_or(serde_json::json!({}));

            sqlx::query(
                r#"
                INSERT INTO entities (id, entity_type, name, description, aliases, metadata,
                                      owner_type, owner_id, created_by, visibility_tier)
                VALUES ($1, $2::entity_type, $3, $4, $5, $6, 'user', $7, $7, $8)
                "#,
            )
            .bind(entity_id)
            .bind(&request.entity_type)
            .bind(&request.name)
            .bind(&request.description)
            .bind(&aliases)
            .bind(&metadata)
            .bind(user_id)
            .bind(visibility)
            .execute(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to create entity: {}", e))?;

            info!("Created entity {} ({})", entity_id, request.name);

            Ok(json_response(
                201,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "entity_id": entity_id.to_string(),
                        "name": request.name,
                        "entity_type": request.entity_type,
                    })),
                    error: None,
                },
            )?)
        }

        // Search/list entities
        ("GET", "/entities") => {
            let params = event.query_string_parameters();
            let query = params.first("q");
            let entity_type = params.first("type");
            let limit: i64 = params.first("limit").and_then(|l| l.parse().ok()).unwrap_or(20);

            // Get user's family IDs for permission check
            let family_ids: Vec<Uuid> = sqlx::query_scalar(
                "SELECT family_id FROM family_members WHERE user_id = $1"
            )
            .bind(user_id)
            .fetch_all(&state.db_pool)
            .await
            .unwrap_or_default();

            let entities: Vec<EntityResponse> = if let Some(q) = query {
                // Search with fuzzy matching
                sqlx::query_as::<_, (Uuid, String, String, Option<String>, Vec<String>, i16, chrono::DateTime<chrono::Utc>, i64)>(
                    r#"
                    SELECT e.id, e.entity_type::text, e.name, e.description, e.aliases,
                           e.visibility_tier, e.created_at, COALESCE(COUNT(f.id), 0) as fact_count
                    FROM entities e
                    LEFT JOIN facts f ON f.about_entity_id = e.id
                    WHERE (
                        (e.owner_type = 'user' AND e.owner_id = $1)
                        OR (e.owner_type = 'family' AND e.owner_id = ANY($2))
                    )
                    AND (
                        e.name ILIKE $3
                        OR e.normalized_name ILIKE $3
                        OR $4 = ANY(e.aliases)
                    )
                    GROUP BY e.id
                    ORDER BY e.name
                    LIMIT $5
                    "#,
                )
                .bind(user_id)
                .bind(&family_ids)
                .bind(format!("%{}%", q))
                .bind(q.to_lowercase())
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            } else if let Some(etype) = entity_type {
                // Filter by type
                sqlx::query_as::<_, (Uuid, String, String, Option<String>, Vec<String>, i16, chrono::DateTime<chrono::Utc>, i64)>(
                    r#"
                    SELECT e.id, e.entity_type::text, e.name, e.description, e.aliases,
                           e.visibility_tier, e.created_at, COALESCE(COUNT(f.id), 0) as fact_count
                    FROM entities e
                    LEFT JOIN facts f ON f.about_entity_id = e.id
                    WHERE (
                        (e.owner_type = 'user' AND e.owner_id = $1)
                        OR (e.owner_type = 'family' AND e.owner_id = ANY($2))
                    )
                    AND e.entity_type = $3::entity_type
                    GROUP BY e.id
                    ORDER BY e.name
                    LIMIT $4
                    "#,
                )
                .bind(user_id)
                .bind(&family_ids)
                .bind(etype)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            } else {
                // List all
                sqlx::query_as::<_, (Uuid, String, String, Option<String>, Vec<String>, i16, chrono::DateTime<chrono::Utc>, i64)>(
                    r#"
                    SELECT e.id, e.entity_type::text, e.name, e.description, e.aliases,
                           e.visibility_tier, e.created_at, COALESCE(COUNT(f.id), 0) as fact_count
                    FROM entities e
                    LEFT JOIN facts f ON f.about_entity_id = e.id
                    WHERE (
                        (e.owner_type = 'user' AND e.owner_id = $1)
                        OR (e.owner_type = 'family' AND e.owner_id = ANY($2))
                    )
                    GROUP BY e.id
                    ORDER BY fact_count DESC, e.name
                    LIMIT $3
                    "#,
                )
                .bind(user_id)
                .bind(&family_ids)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            }
            .map_err(|e| format!("Failed to fetch entities: {}", e))?
            .into_iter()
            .map(|(id, entity_type, name, description, aliases, visibility_tier, created_at, fact_count)| {
                EntityResponse {
                    id: id.to_string(),
                    entity_type,
                    name,
                    description,
                    aliases,
                    visibility_tier,
                    created_at: created_at.to_rfc3339(),
                    fact_count,
                }
            })
            .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(entities),
                    error: None,
                },
            )?)
        }

        // Entity-specific routes
        _ if path.starts_with("/entities/") => {
            let path_parts: Vec<&str> = path.trim_start_matches("/entities/").split('/').collect();
            let entity_id = Uuid::parse_str(path_parts[0])
                .map_err(|_| "Invalid entity ID")?;

            // Verify access to entity
            let has_access: bool = sqlx::query_scalar(
                r#"
                SELECT EXISTS(
                    SELECT 1 FROM entities e
                    LEFT JOIN family_members fm ON e.owner_type = 'family' AND e.owner_id = fm.family_id AND fm.user_id = $2
                    WHERE e.id = $1
                    AND (
                        (e.owner_type = 'user' AND e.owner_id = $2)
                        OR (e.owner_type = 'family' AND fm.user_id IS NOT NULL)
                    )
                )
                "#
            )
            .bind(entity_id)
            .bind(user_id)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to verify access: {}", e))?;

            if !has_access {
                return Ok(json_response(
                    404,
                    &ApiResponse::<()> {
                        success: false,
                        data: None,
                        error: Some("Entity not found".to_string()),
                    },
                )?);
            }

            match (method, path_parts.get(1)) {
                // Get entity details
                ("GET", None) => {
                    let entity = sqlx::query_as::<_, (Uuid, String, String, Option<String>, Vec<String>, serde_json::Value, i16, Option<Uuid>, chrono::DateTime<chrono::Utc>, chrono::DateTime<chrono::Utc>)>(
                        r#"
                        SELECT id, entity_type::text, name, description, aliases, metadata,
                               visibility_tier, linked_user_id, created_at, updated_at
                        FROM entities WHERE id = $1
                        "#
                    )
                    .bind(entity_id)
                    .fetch_one(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch entity: {}", e))?;

                    // Get attributes
                    let attributes: Vec<EntityAttribute> = sqlx::query_as::<_, (String, String, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>)>(
                        r#"
                        SELECT attribute_name, attribute_value, valid_from, valid_to
                        FROM entity_attributes
                        WHERE entity_id = $1
                        AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                        ORDER BY attribute_name
                        "#
                    )
                    .bind(entity_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .unwrap_or_default()
                    .into_iter()
                    .map(|(name, value, valid_from, valid_to)| EntityAttribute {
                        name,
                        value,
                        valid_from: valid_from.map(|d| d.to_string()),
                        valid_to: valid_to.map(|d| d.to_string()),
                    })
                    .collect();

                    // Get locations
                    let locations: Vec<EntityLocation> = sqlx::query_as::<_, (String, Option<String>, Option<f64>, Option<f64>)>(
                        r#"
                        SELECT label, address_raw,
                               ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng
                        FROM entity_locations
                        WHERE entity_id = $1
                        AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                        ORDER BY label
                        "#
                    )
                    .bind(entity_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .unwrap_or_default()
                    .into_iter()
                    .map(|(label, address, latitude, longitude)| EntityLocation {
                        label,
                        address,
                        latitude,
                        longitude,
                    })
                    .collect();

                    // Get relationships
                    let relationships: Vec<EntityRelationship> = sqlx::query_as::<_, (Uuid, Uuid, String, String, String, String)>(
                        r#"
                        SELECT er.id,
                               CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END as related_id,
                               e.name, e.entity_type::text, er.relationship_type,
                               CASE WHEN er.source_entity_id = $1 THEN 'outgoing' ELSE 'incoming' END as direction
                        FROM entity_relationships er
                        JOIN entities e ON e.id = CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END
                        WHERE er.source_entity_id = $1 OR er.target_entity_id = $1
                        ORDER BY e.name
                        "#
                    )
                    .bind(entity_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .unwrap_or_default()
                    .into_iter()
                    .map(|(id, related_id, name, entity_type, relationship_type, direction)| EntityRelationship {
                        id: id.to_string(),
                        related_entity_id: related_id.to_string(),
                        related_entity_name: name,
                        related_entity_type: entity_type,
                        relationship_type,
                        direction,
                    })
                    .collect();

                    let response = EntityDetailResponse {
                        id: entity.0.to_string(),
                        entity_type: entity.1,
                        name: entity.2,
                        description: entity.3,
                        aliases: entity.4,
                        metadata: entity.5,
                        visibility_tier: entity.6,
                        linked_user_id: entity.7.map(|u| u.to_string()),
                        created_at: entity.8.to_rfc3339(),
                        updated_at: entity.9.to_rfc3339(),
                        attributes,
                        locations,
                        relationships,
                    };

                    Ok(json_response(200, &ApiResponse {
                        success: true,
                        data: Some(response),
                        error: None,
                    })?)
                }

                // Update entity
                ("PUT", None) => {
                    let request: UpdateEntityRequest = match shared::parse_json_body(event.body())? {
                        Ok(r) => r,
                        Err(response) => return Ok(response),
                    };

                    // Update each field individually for simplicity
                    sqlx::query("UPDATE entities SET updated_at = NOW() WHERE id = $1")
                        .bind(entity_id)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to update entity: {}", e))?;

                    if let Some(name) = &request.name {
                        sqlx::query("UPDATE entities SET name = $2 WHERE id = $1")
                            .bind(entity_id)
                            .bind(name)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(desc) = &request.description {
                        sqlx::query("UPDATE entities SET description = $2 WHERE id = $1")
                            .bind(entity_id)
                            .bind(desc)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(aliases) = &request.aliases {
                        sqlx::query("UPDATE entities SET aliases = $2 WHERE id = $1")
                            .bind(entity_id)
                            .bind(aliases)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(metadata) = &request.metadata {
                        sqlx::query("UPDATE entities SET metadata = $2 WHERE id = $1")
                            .bind(entity_id)
                            .bind(metadata)
                            .execute(&state.db_pool)
                            .await?;
                    }
                    if let Some(visibility) = request.visibility_tier {
                        sqlx::query("UPDATE entities SET visibility_tier = $2 WHERE id = $1")
                            .bind(entity_id)
                            .bind(visibility)
                            .execute(&state.db_pool)
                            .await?;
                    }

                    info!("Updated entity {}", entity_id);

                    Ok(json_response(200, &ApiResponse {
                        success: true,
                        data: Some(serde_json::json!({"message": "Entity updated"})),
                        error: None,
                    })?)
                }

                // Delete entity
                ("DELETE", None) => {
                    sqlx::query("DELETE FROM entities WHERE id = $1")
                        .bind(entity_id)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to delete entity: {}", e))?;

                    info!("Deleted entity {}", entity_id);

                    Ok(json_response(200, &ApiResponse {
                        success: true,
                        data: Some(serde_json::json!({"message": "Entity deleted"})),
                        error: None,
                    })?)
                }

                // Get entity facts (timeline)
                ("GET", Some(&"facts")) => {
                    let params = event.query_string_parameters();
                    let limit: i64 = params.first("limit").and_then(|l| l.parse().ok()).unwrap_or(50);

                    let facts: Vec<FactTimelineEntry> = sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>)>(
                        r#"
                        SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to
                        FROM facts f
                        WHERE f.about_entity_id = $1
                        ORDER BY COALESCE(f.valid_from, f.recorded_at::date) DESC, f.importance DESC
                        LIMIT $2
                        "#
                    )
                    .bind(entity_id)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch facts: {}", e))?
                    .into_iter()
                    .map(|(id, content, importance, recorded_at, valid_from, valid_to)| FactTimelineEntry {
                        id: id.to_string(),
                        content,
                        importance,
                        recorded_at: recorded_at.to_rfc3339(),
                        valid_from: valid_from.map(|d| d.to_string()),
                        valid_to: valid_to.map(|d| d.to_string()),
                    })
                    .collect();

                    Ok(json_response(200, &ApiResponse {
                        success: true,
                        data: Some(serde_json::json!({
                            "entity_id": entity_id.to_string(),
                            "facts": facts,
                            "count": facts.len(),
                        })),
                        error: None,
                    })?)
                }

                // Create entity relationship
                ("POST", Some(&"relationships")) => {
                    let request: CreateRelationshipRequest = match shared::parse_json_body(event.body())? {
                        Ok(r) => r,
                        Err(response) => return Ok(response),
                    };

                    let target_id = Uuid::parse_str(&request.target_entity_id)
                        .map_err(|_| "Invalid target_entity_id")?;

                    let rel_id = Uuid::new_v4();
                    let metadata = request.metadata.unwrap_or(serde_json::json!({}));

                    sqlx::query(
                        r#"
                        INSERT INTO entity_relationships (id, source_entity_id, target_entity_id, relationship_type, metadata, created_by)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        "#
                    )
                    .bind(rel_id)
                    .bind(entity_id)
                    .bind(target_id)
                    .bind(&request.relationship_type)
                    .bind(&metadata)
                    .bind(user_id)
                    .execute(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to create relationship: {}", e))?;

                    info!("Created entity relationship {} -> {}", entity_id, target_id);

                    Ok(json_response(201, &ApiResponse {
                        success: true,
                        data: Some(serde_json::json!({
                            "relationship_id": rel_id.to_string(),
                            "source_entity_id": entity_id.to_string(),
                            "target_entity_id": target_id.to_string(),
                            "relationship_type": request.relationship_type,
                        })),
                        error: None,
                    })?)
                }

                // Get entity relationships
                ("GET", Some(&"relationships")) => {
                    let relationships: Vec<EntityRelationship> = sqlx::query_as::<_, (Uuid, Uuid, String, String, String, String)>(
                        r#"
                        SELECT er.id,
                               CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END as related_id,
                               e.name, e.entity_type::text, er.relationship_type,
                               CASE WHEN er.source_entity_id = $1 THEN 'outgoing' ELSE 'incoming' END as direction
                        FROM entity_relationships er
                        JOIN entities e ON e.id = CASE WHEN er.source_entity_id = $1 THEN er.target_entity_id ELSE er.source_entity_id END
                        WHERE er.source_entity_id = $1 OR er.target_entity_id = $1
                        ORDER BY e.name
                        "#
                    )
                    .bind(entity_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch relationships: {}", e))?
                    .into_iter()
                    .map(|(id, related_id, name, entity_type, relationship_type, direction)| EntityRelationship {
                        id: id.to_string(),
                        related_entity_id: related_id.to_string(),
                        related_entity_name: name,
                        related_entity_type: entity_type,
                        relationship_type,
                        direction,
                    })
                    .collect();

                    Ok(json_response(200, &ApiResponse {
                        success: true,
                        data: Some(relationships),
                        error: None,
                    })?)
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
