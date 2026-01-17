//! Location & Geographic Lambda - Handles location and proximity queries.
//!
//! Endpoints:
//! - POST /locations/geocode - Geocode an address
//! - GET /locations/nearby - Find entities near a point
//! - POST /entities/{id}/locations - Add location to entity
//! - GET /entities/{id}/locations - Get entity locations
//! - GET /facts/timeline - Get facts with temporal filtering

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// Geocode request
#[derive(Debug, Deserialize)]
struct GeocodeRequest {
    address: String,
}

/// Store location request
#[derive(Debug, Deserialize)]
struct StoreLocationRequest {
    label: String,
    address: String,
    latitude: Option<f64>,
    longitude: Option<f64>,
    valid_from: Option<String>,
    valid_to: Option<String>,
    visibility_tier: Option<i16>,
}

/// Location response
#[derive(Debug, Serialize)]
struct LocationResponse {
    id: String,
    label: String,
    address: Option<String>,
    latitude: Option<f64>,
    longitude: Option<f64>,
    valid_from: Option<String>,
    valid_to: Option<String>,
}

/// Nearby entity response
#[derive(Debug, Serialize)]
struct NearbyEntityResponse {
    entity_id: String,
    entity_type: String,
    name: String,
    location_label: String,
    address: Option<String>,
    latitude: f64,
    longitude: f64,
    distance_meters: f64,
    distance_display: String,
}

/// Timeline fact response
#[derive(Debug, Serialize)]
struct TimelineFactResponse {
    id: String,
    content: String,
    importance: i16,
    recorded_at: String,
    valid_from: Option<String>,
    valid_to: Option<String>,
    entity_name: Option<String>,
    is_current: bool,
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

/// Format distance for display
fn format_distance(meters: f64) -> String {
    if meters < 1000.0 {
        format!("{}m", meters as i32)
    } else {
        let km = meters / 1000.0;
        if km < 10.0 {
            format!("{:.1}km", km)
        } else {
            format!("{}km", km as i32)
        }
    }
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

    // Get user's family IDs for permission checks
    let family_ids: Vec<Uuid> = sqlx::query_scalar(
        "SELECT family_id FROM family_members WHERE user_id = $1"
    )
    .bind(user_id)
    .fetch_all(&state.db_pool)
    .await
    .unwrap_or_default();

    match (method, path) {
        // Nearby search
        ("GET", "/locations/nearby") => {
            let params = event.query_string_parameters();

            let lat: f64 = params.first("lat")
                .and_then(|l| l.parse().ok())
                .ok_or("lat parameter required")?;
            // Support both 'lon' and 'lng' parameter names
            let lon: f64 = params.first("lon")
                .or_else(|| params.first("lng"))
                .and_then(|l| l.parse().ok())
                .ok_or("lon or lng parameter required")?;
            // Support radius in meters or radius_km in kilometers
            let radius: f64 = params.first("radius")
                .and_then(|r| r.parse().ok())
                .or_else(|| params.first("radius_km")
                    .and_then(|r| r.parse::<f64>().ok())
                    .map(|km| km * 1000.0))
                .unwrap_or(1000.0);
            let entity_type = params.first("type");
            let limit: i64 = params.first("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(20);

            let results: Vec<NearbyEntityResponse> = if let Some(etype) = entity_type {
                sqlx::query_as::<_, (Uuid, String, String, String, Option<String>, f64, f64, f64)>(
                    r#"
                    SELECT
                        e.id,
                        e.entity_type::text,
                        e.name,
                        el.label,
                        el.address_raw,
                        ST_Y(el.location::geometry) as lat,
                        ST_X(el.location::geometry) as lon,
                        ST_Distance(
                            el.location,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                        ) as distance_meters
                    FROM entities e
                    JOIN entity_locations el ON el.entity_id = e.id
                    WHERE ST_DWithin(
                        el.location,
                        ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                        $3
                    )
                    AND (el.valid_to IS NULL OR el.valid_to > CURRENT_DATE)
                    AND (
                        (e.owner_type = 'user' AND e.owner_id = $4)
                        OR (e.owner_type = 'family' AND e.owner_id = ANY($5))
                    )
                    AND e.entity_type = $6::entity_type
                    ORDER BY distance_meters ASC
                    LIMIT $7
                    "#
                )
                .bind(lon)
                .bind(lat)
                .bind(radius)
                .bind(user_id)
                .bind(&family_ids)
                .bind(etype)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            } else {
                sqlx::query_as::<_, (Uuid, String, String, String, Option<String>, f64, f64, f64)>(
                    r#"
                    SELECT
                        e.id,
                        e.entity_type::text,
                        e.name,
                        el.label,
                        el.address_raw,
                        ST_Y(el.location::geometry) as lat,
                        ST_X(el.location::geometry) as lon,
                        ST_Distance(
                            el.location,
                            ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                        ) as distance_meters
                    FROM entities e
                    JOIN entity_locations el ON el.entity_id = e.id
                    WHERE ST_DWithin(
                        el.location,
                        ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                        $3
                    )
                    AND (el.valid_to IS NULL OR el.valid_to > CURRENT_DATE)
                    AND (
                        (e.owner_type = 'user' AND e.owner_id = $4)
                        OR (e.owner_type = 'family' AND e.owner_id = ANY($5))
                    )
                    ORDER BY distance_meters ASC
                    LIMIT $6
                    "#
                )
                .bind(lon)
                .bind(lat)
                .bind(radius)
                .bind(user_id)
                .bind(&family_ids)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            }
            .map_err(|e| format!("Failed to search nearby: {}", e))?
            .into_iter()
            .map(|(id, entity_type, name, label, address, latitude, longitude, distance)| {
                NearbyEntityResponse {
                    entity_id: id.to_string(),
                    entity_type,
                    name,
                    location_label: label,
                    address,
                    latitude,
                    longitude,
                    distance_meters: distance,
                    distance_display: format_distance(distance),
                }
            })
            .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "center": {"latitude": lat, "longitude": lon},
                        "radius_meters": radius,
                        "count": results.len(),
                        "results": results,
                    })),
                    error: None,
                },
            )?)
        }

        // Calculate distance between two points
        ("GET", "/locations/distance") => {
            let params = event.query_string_parameters();

            let from_lat: f64 = params.first("from_lat")
                .and_then(|l| l.parse().ok())
                .ok_or("from_lat parameter required")?;
            let from_lon: f64 = params.first("from_lon")
                .and_then(|l| l.parse().ok())
                .ok_or("from_lon parameter required")?;
            let to_lat: f64 = params.first("to_lat")
                .and_then(|l| l.parse().ok())
                .ok_or("to_lat parameter required")?;
            let to_lon: f64 = params.first("to_lon")
                .and_then(|l| l.parse().ok())
                .ok_or("to_lon parameter required")?;

            let distance: f64 = sqlx::query_scalar(
                r#"
                SELECT ST_Distance(
                    ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                    ST_SetSRID(ST_MakePoint($3, $4), 4326)::geography
                )
                "#
            )
            .bind(from_lon)
            .bind(from_lat)
            .bind(to_lon)
            .bind(to_lat)
            .fetch_one(&state.db_pool)
            .await
            .map_err(|e| format!("Failed to calculate distance: {}", e))?;

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "distance_meters": distance,
                        "distance_km": distance / 1000.0,
                        "distance_miles": distance / 1609.34,
                        "display": format_distance(distance),
                    })),
                    error: None,
                },
            )?)
        }

        // Temporal timeline query
        ("GET", "/facts/timeline") => {
            let params = event.query_string_parameters();

            // Parse optional date filters
            let as_of = params.first("as_of"); // Point-in-time query
            let from_date = params.first("from");
            let to_date = params.first("to");
            let entity_id = params.first("entity_id");
            let include_expired = params.first("include_expired")
                .map(|v| v == "true")
                .unwrap_or(false);
            let limit: i64 = params.first("limit")
                .and_then(|l| l.parse().ok())
                .unwrap_or(50);

            let results: Vec<TimelineFactResponse> = if let Some(point_in_time) = as_of {
                // Point-in-time query: what was true on this date?
                let date = chrono::NaiveDate::parse_from_str(point_in_time, "%Y-%m-%d")
                    .map_err(|_| "Invalid as_of date format (use YYYY-MM-DD)")?;

                if let Some(eid) = entity_id {
                    let eid = Uuid::parse_str(eid).map_err(|_| "Invalid entity_id")?;
                    sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>, Option<String>)>(
                        r#"
                        SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to, e.name
                        FROM facts f
                        LEFT JOIN entities e ON e.id = f.about_entity_id
                        WHERE f.about_entity_id = $1
                        AND (f.valid_from IS NULL OR f.valid_from <= $2)
                        AND (f.valid_to IS NULL OR f.valid_to > $2)
                        AND (
                            (f.owner_type = 'user' AND f.owner_id = $3)
                            OR (f.owner_type = 'family' AND f.owner_id = ANY($4))
                        )
                        ORDER BY f.importance DESC, f.recorded_at DESC
                        LIMIT $5
                        "#
                    )
                    .bind(eid)
                    .bind(date)
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                } else {
                    sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>, Option<String>)>(
                        r#"
                        SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to, e.name
                        FROM facts f
                        LEFT JOIN entities e ON e.id = f.about_entity_id
                        WHERE (f.valid_from IS NULL OR f.valid_from <= $1)
                        AND (f.valid_to IS NULL OR f.valid_to > $1)
                        AND (
                            (f.owner_type = 'user' AND f.owner_id = $2)
                            OR (f.owner_type = 'family' AND f.owner_id = ANY($3))
                        )
                        ORDER BY f.importance DESC, f.recorded_at DESC
                        LIMIT $4
                        "#
                    )
                    .bind(date)
                    .bind(user_id)
                    .bind(&family_ids)
                    .bind(limit)
                    .fetch_all(&state.db_pool)
                    .await
                }
            } else if from_date.is_some() || to_date.is_some() {
                // Date range query
                let from = from_date
                    .map(|d| chrono::NaiveDate::parse_from_str(d, "%Y-%m-%d"))
                    .transpose()
                    .map_err(|_| "Invalid from date format")?;
                let to = to_date
                    .map(|d| chrono::NaiveDate::parse_from_str(d, "%Y-%m-%d"))
                    .transpose()
                    .map_err(|_| "Invalid to date format")?;

                sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>, Option<String>)>(
                    r#"
                    SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to, e.name
                    FROM facts f
                    LEFT JOIN entities e ON e.id = f.about_entity_id
                    WHERE (
                        (f.owner_type = 'user' AND f.owner_id = $1)
                        OR (f.owner_type = 'family' AND f.owner_id = ANY($2))
                    )
                    AND ($3::date IS NULL OR f.valid_from >= $3 OR f.recorded_at::date >= $3)
                    AND ($4::date IS NULL OR f.valid_from <= $4 OR f.recorded_at::date <= $4)
                    ORDER BY COALESCE(f.valid_from, f.recorded_at::date) DESC, f.importance DESC
                    LIMIT $5
                    "#
                )
                .bind(user_id)
                .bind(&family_ids)
                .bind(from)
                .bind(to)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            } else {
                // Default: recent facts timeline
                let validity_filter = if include_expired {
                    "1=1"
                } else {
                    "(f.valid_to IS NULL OR f.valid_to > CURRENT_DATE)"
                };

                sqlx::query_as::<_, (Uuid, String, i16, chrono::DateTime<chrono::Utc>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>, Option<String>)>(
                    &format!(r#"
                    SELECT f.id, f.content, f.importance, f.recorded_at, f.valid_from, f.valid_to, e.name
                    FROM facts f
                    LEFT JOIN entities e ON e.id = f.about_entity_id
                    WHERE (
                        (f.owner_type = 'user' AND f.owner_id = $1)
                        OR (f.owner_type = 'family' AND f.owner_id = ANY($2))
                    )
                    AND {}
                    ORDER BY f.recorded_at DESC, f.importance DESC
                    LIMIT $3
                    "#, validity_filter)
                )
                .bind(user_id)
                .bind(&family_ids)
                .bind(limit)
                .fetch_all(&state.db_pool)
                .await
            }
            .map_err(|e| format!("Failed to fetch timeline: {}", e))?
            .into_iter()
            .map(|(id, content, importance, recorded_at, valid_from, valid_to, entity_name)| {
                let today = chrono::Utc::now().date_naive();
                let is_current = valid_to.map(|d| d > today).unwrap_or(true);

                TimelineFactResponse {
                    id: id.to_string(),
                    content,
                    importance,
                    recorded_at: recorded_at.to_rfc3339(),
                    valid_from: valid_from.map(|d| d.to_string()),
                    valid_to: valid_to.map(|d| d.to_string()),
                    entity_name,
                    is_current,
                }
            })
            .collect();

            Ok(json_response(
                200,
                &ApiResponse {
                    success: true,
                    data: Some(serde_json::json!({
                        "count": results.len(),
                        "as_of": as_of,
                        "include_expired": include_expired,
                        "facts": results,
                    })),
                    error: None,
                },
            )?)
        }

        // Entity location routes
        _ if path.starts_with("/entities/") && path.contains("/locations") => {
            let path_parts: Vec<&str> = path
                .trim_start_matches("/entities/")
                .split('/')
                .collect();

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

            match method {
                // Get entity locations
                "GET" => {
                    let locations: Vec<LocationResponse> = sqlx::query_as::<_, (Uuid, String, Option<String>, Option<f64>, Option<f64>, Option<chrono::NaiveDate>, Option<chrono::NaiveDate>)>(
                        r#"
                        SELECT id, label, address_raw,
                               ST_Y(location::geometry), ST_X(location::geometry),
                               valid_from, valid_to
                        FROM entity_locations
                        WHERE entity_id = $1
                        ORDER BY label
                        "#
                    )
                    .bind(entity_id)
                    .fetch_all(&state.db_pool)
                    .await
                    .map_err(|e| format!("Failed to fetch locations: {}", e))?
                    .into_iter()
                    .map(|(id, label, address, lat, lon, valid_from, valid_to)| {
                        LocationResponse {
                            id: id.to_string(),
                            label,
                            address,
                            latitude: lat,
                            longitude: lon,
                            valid_from: valid_from.map(|d| d.to_string()),
                            valid_to: valid_to.map(|d| d.to_string()),
                        }
                    })
                    .collect();

                    Ok(json_response(
                        200,
                        &ApiResponse {
                            success: true,
                            data: Some(locations),
                            error: None,
                        },
                    )?)
                }

                // Add location to entity
                "POST" => {
                    let body = event.body();
                    let request: StoreLocationRequest = serde_json::from_slice(body)
                        .map_err(|e| format!("Invalid request body: {}", e))?;

                    let location_id = Uuid::new_v4();
                    let visibility = request.visibility_tier.unwrap_or(3);

                    let valid_from = request.valid_from
                        .map(|d| chrono::NaiveDate::parse_from_str(&d, "%Y-%m-%d"))
                        .transpose()
                        .map_err(|_| "Invalid valid_from date")?;
                    let valid_to = request.valid_to
                        .map(|d| chrono::NaiveDate::parse_from_str(&d, "%Y-%m-%d"))
                        .transpose()
                        .map_err(|_| "Invalid valid_to date")?;

                    if let (Some(lat), Some(lon)) = (request.latitude, request.longitude) {
                        sqlx::query(
                            r#"
                            INSERT INTO entity_locations (id, entity_id, label, address_raw, location,
                                                         valid_from, valid_to, visibility_tier)
                            VALUES ($1, $2, $3, $4, ST_SetSRID(ST_MakePoint($5, $6), 4326)::geography,
                                    $7, $8, $9)
                            ON CONFLICT (entity_id, label) WHERE valid_to IS NULL DO UPDATE SET
                                address_raw = EXCLUDED.address_raw,
                                location = EXCLUDED.location,
                                valid_from = EXCLUDED.valid_from,
                                valid_to = EXCLUDED.valid_to,
                                updated_at = NOW()
                            "#
                        )
                        .bind(location_id)
                        .bind(entity_id)
                        .bind(&request.label)
                        .bind(&request.address)
                        .bind(lon)
                        .bind(lat)
                        .bind(valid_from)
                        .bind(valid_to)
                        .bind(visibility)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to store location: {}", e))?;

                        info!("Stored location {} for entity {}", request.label, entity_id);

                        Ok(json_response(
                            201,
                            &ApiResponse {
                                success: true,
                                data: Some(serde_json::json!({
                                    "location_id": location_id.to_string(),
                                    "entity_id": entity_id.to_string(),
                                    "label": request.label,
                                    "latitude": lat,
                                    "longitude": lon,
                                })),
                                error: None,
                            },
                        )?)
                    } else {
                        // Store without coordinates (address only)
                        sqlx::query(
                            r#"
                            INSERT INTO entity_locations (id, entity_id, label, address_raw,
                                                         valid_from, valid_to, visibility_tier)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            ON CONFLICT (entity_id, label) WHERE valid_to IS NULL DO UPDATE SET
                                address_raw = EXCLUDED.address_raw,
                                valid_from = EXCLUDED.valid_from,
                                valid_to = EXCLUDED.valid_to,
                                updated_at = NOW()
                            "#
                        )
                        .bind(location_id)
                        .bind(entity_id)
                        .bind(&request.label)
                        .bind(&request.address)
                        .bind(valid_from)
                        .bind(valid_to)
                        .bind(visibility)
                        .execute(&state.db_pool)
                        .await
                        .map_err(|e| format!("Failed to store location: {}", e))?;

                        Ok(json_response(
                            201,
                            &ApiResponse {
                                success: true,
                                data: Some(serde_json::json!({
                                    "location_id": location_id.to_string(),
                                    "entity_id": entity_id.to_string(),
                                    "label": request.label,
                                    "note": "Location stored without coordinates. Use geocoding to add coordinates."
                                })),
                                error: None,
                            },
                        )?)
                    }
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
