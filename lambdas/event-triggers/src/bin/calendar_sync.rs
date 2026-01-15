//! Calendar Sync Lambda - Syncs external calendars (Google, Outlook).
//!
//! This Lambda runs on a schedule (EventBridge) to sync calendar events
//! from connected external calendars into the Second Brain database.

use chrono::{DateTime, Duration, Utc};
use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use std::sync::Arc;
use tracing::{error, info, warn};
use tracing_subscriber::EnvFilter;
use uuid::Uuid;

/// EventBridge scheduled event
#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    #[serde(default)]
    detail_type: String,
    /// Optional: sync only specific user
    user_id: Option<String>,
}

/// Sync response
#[derive(Debug, Serialize)]
struct SyncResponse {
    users_synced: u32,
    events_updated: u32,
    events_created: u32,
    errors: Vec<String>,
}

/// User calendar connection info
#[derive(Debug)]
struct CalendarConnection {
    user_id: Uuid,
    provider: String,
    secret_name: String,
}

/// Google Calendar tokens from Secrets Manager
#[derive(Debug, Deserialize)]
struct GoogleTokens {
    access_token: String,
    refresh_token: Option<String>,
    expires_in: Option<i64>,
}

/// Google Calendar event from API
#[derive(Debug, Deserialize)]
struct GoogleCalendarEvent {
    id: String,
    summary: Option<String>,
    description: Option<String>,
    location: Option<String>,
    start: GoogleEventTime,
    end: GoogleEventTime,
    attendees: Option<Vec<GoogleAttendee>>,
    #[serde(rename = "recurringEventId")]
    recurring_event_id: Option<String>,
    status: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GoogleEventTime {
    #[serde(rename = "dateTime")]
    date_time: Option<String>,
    date: Option<String>,
    #[serde(rename = "timeZone")]
    time_zone: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GoogleAttendee {
    email: Option<String>,
    #[serde(rename = "displayName")]
    display_name: Option<String>,
    #[serde(rename = "responseStatus")]
    response_status: Option<String>,
    #[serde(rename = "self")]
    is_self: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct GoogleCalendarListResponse {
    items: Option<Vec<GoogleCalendarEvent>>,
    #[serde(rename = "nextPageToken")]
    next_page_token: Option<String>,
}

/// Application state
struct AppState {
    db_pool: PgPool,
    secrets_client: aws_sdk_secretsmanager::Client,
    http_client: reqwest::Client,
    google_client_id: String,
    google_client_secret: String,
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

        // Get Google OAuth credentials
        let google_secret_arn = std::env::var("GOOGLE_OAUTH_SECRET_ARN")
            .unwrap_or_else(|_| "second-brain/google-oauth".to_string());

        let google_secret = secrets_client
            .get_secret_value()
            .secret_id(&google_secret_arn)
            .send()
            .await
            .map_err(|e| format!("Failed to get Google OAuth secret: {}", e))?;

        let google_creds: serde_json::Value =
            serde_json::from_str(google_secret.secret_string().unwrap_or("{}"))?;

        Ok(Self {
            db_pool,
            secrets_client,
            http_client: reqwest::Client::new(),
            google_client_id: google_creds["client_id"]
                .as_str()
                .unwrap_or("")
                .to_string(),
            google_client_secret: google_creds["client_secret"]
                .as_str()
                .unwrap_or("")
                .to_string(),
        })
    }

    /// Get all users with connected calendars
    async fn get_connected_users(&self) -> Result<Vec<CalendarConnection>, Error> {
        // For now, we'll list secrets matching the pattern second-brain/calendar/*
        // In a real implementation, you'd also store connection status in the database

        let mut connections = Vec::new();

        let secrets = self
            .secrets_client
            .list_secrets()
            .filters(
                aws_sdk_secretsmanager::types::Filter::builder()
                    .key(aws_sdk_secretsmanager::types::FilterNameStringType::Name)
                    .values("second-brain/calendar/")
                    .build(),
            )
            .send()
            .await
            .map_err(|e| format!("Failed to list secrets: {}", e))?;

        for secret in secrets.secret_list() {
            if let Some(name) = secret.name() {
                // Extract user_id from secret name: second-brain/calendar/{user_id}
                if let Some(user_id_str) = name.strip_prefix("second-brain/calendar/") {
                    if let Ok(user_id) = Uuid::parse_str(user_id_str) {
                        connections.push(CalendarConnection {
                            user_id,
                            provider: "google".to_string(),
                            secret_name: name.to_string(),
                        });
                    }
                }
            }
        }

        Ok(connections)
    }

    /// Refresh Google access token using refresh token
    async fn refresh_google_token(&self, refresh_token: &str) -> Result<String, Error> {
        let params = [
            ("refresh_token", refresh_token),
            ("client_id", &self.google_client_id),
            ("client_secret", &self.google_client_secret),
            ("grant_type", "refresh_token"),
        ];

        let response = self
            .http_client
            .post("https://oauth2.googleapis.com/token")
            .form(&params)
            .send()
            .await
            .map_err(|e| format!("Token refresh request failed: {}", e))?;

        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(format!("Token refresh failed: {}", error_text).into());
        }

        let token_response: serde_json::Value = response
            .json()
            .await
            .map_err(|e| format!("Failed to parse token response: {}", e))?;

        Ok(token_response["access_token"]
            .as_str()
            .ok_or("Missing access_token in refresh response")?
            .to_string())
    }

    /// Fetch events from Google Calendar API
    async fn fetch_google_events(
        &self,
        access_token: &str,
        time_min: DateTime<Utc>,
        time_max: DateTime<Utc>,
    ) -> Result<Vec<GoogleCalendarEvent>, Error> {
        let mut all_events = Vec::new();
        let mut page_token: Option<String> = None;

        loop {
            let mut url = format!(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events?\
                timeMin={}&timeMax={}&singleEvents=true&orderBy=startTime&maxResults=250",
                urlencoding::encode(&time_min.to_rfc3339()),
                urlencoding::encode(&time_max.to_rfc3339())
            );

            if let Some(token) = &page_token {
                url.push_str(&format!("&pageToken={}", token));
            }

            let response = self
                .http_client
                .get(&url)
                .header("Authorization", format!("Bearer {}", access_token))
                .send()
                .await
                .map_err(|e| format!("Calendar API request failed: {}", e))?;

            if !response.status().is_success() {
                let error_text = response.text().await.unwrap_or_default();
                return Err(format!("Calendar API error: {}", error_text).into());
            }

            let calendar_response: GoogleCalendarListResponse = response
                .json()
                .await
                .map_err(|e| format!("Failed to parse calendar response: {}", e))?;

            if let Some(items) = calendar_response.items {
                all_events.extend(items);
            }

            page_token = calendar_response.next_page_token;
            if page_token.is_none() {
                break;
            }
        }

        Ok(all_events)
    }

    /// Sync events for a single user
    async fn sync_user_events(
        &self,
        connection: &CalendarConnection,
    ) -> Result<(u32, u32), Error> {
        // Get user's tokens from Secrets Manager
        let secret_value = self
            .secrets_client
            .get_secret_value()
            .secret_id(&connection.secret_name)
            .send()
            .await
            .map_err(|e| format!("Failed to get user tokens: {}", e))?;

        let tokens: GoogleTokens =
            serde_json::from_str(secret_value.secret_string().unwrap_or("{}"))?;

        // Refresh access token
        let access_token = if let Some(refresh_token) = &tokens.refresh_token {
            self.refresh_google_token(refresh_token).await?
        } else {
            tokens.access_token
        };

        // Fetch events for next 30 days
        let time_min = Utc::now();
        let time_max = time_min + Duration::days(30);

        let events = self
            .fetch_google_events(&access_token, time_min, time_max)
            .await?;

        let mut created = 0u32;
        let mut updated = 0u32;

        for event in events {
            // Skip cancelled events
            if event.status.as_deref() == Some("cancelled") {
                continue;
            }

            let (start_time, all_day) = parse_event_time(&event.start)?;
            let (end_time, _) = parse_event_time(&event.end)?;

            // Upsert event
            let result = sqlx::query_scalar::<_, bool>(
                r#"
                INSERT INTO calendar_events (
                    user_id, external_id, external_provider,
                    title, description, location,
                    start_time, end_time, all_day,
                    is_recurring, visibility_tier
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (external_id, external_provider, user_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    location = EXCLUDED.location,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    all_day = EXCLUDED.all_day,
                    is_recurring = EXCLUDED.is_recurring,
                    updated_at = NOW()
                RETURNING (xmax = 0)
                "#,
            )
            .bind(connection.user_id)
            .bind(&event.id)
            .bind("google")
            .bind(event.summary.as_deref().unwrap_or("(No title)"))
            .bind(&event.description)
            .bind(&event.location)
            .bind(start_time)
            .bind(end_time)
            .bind(all_day)
            .bind(event.recurring_event_id.is_some())
            .bind(3i16) // Default visibility tier
            .fetch_one(&self.db_pool)
            .await;

            match result {
                Ok(is_insert) => {
                    if is_insert {
                        created += 1;
                    } else {
                        updated += 1;
                    }
                }
                Err(e) => {
                    warn!("Failed to upsert event {}: {}", event.id, e);
                }
            }

            // Sync attendees if present
            if let Some(attendees) = &event.attendees {
                for attendee in attendees {
                    if attendee.is_self.unwrap_or(false) {
                        continue; // Skip self
                    }

                    let _ = sqlx::query(
                        r#"
                        INSERT INTO calendar_event_attendees (
                            event_id, email, display_name, response_status
                        )
                        SELECT ce.id, $2, $3, $4
                        FROM calendar_events ce
                        WHERE ce.external_id = $1 AND ce.user_id = $5
                        ON CONFLICT (event_id, email) DO UPDATE SET
                            display_name = EXCLUDED.display_name,
                            response_status = EXCLUDED.response_status
                        "#,
                    )
                    .bind(&event.id)
                    .bind(&attendee.email)
                    .bind(&attendee.display_name)
                    .bind(&attendee.response_status)
                    .bind(connection.user_id)
                    .execute(&self.db_pool)
                    .await;
                }
            }
        }

        Ok((created, updated))
    }
}

/// Parse Google event time to DateTime<Utc>
fn parse_event_time(time: &GoogleEventTime) -> Result<(DateTime<Utc>, bool), Error> {
    if let Some(date_time) = &time.date_time {
        // Full datetime
        let dt = DateTime::parse_from_rfc3339(date_time)
            .map_err(|e| format!("Invalid datetime: {}", e))?;
        Ok((dt.with_timezone(&Utc), false))
    } else if let Some(date) = &time.date {
        // All-day event (date only)
        let naive = chrono::NaiveDate::parse_from_str(date, "%Y-%m-%d")
            .map_err(|e| format!("Invalid date: {}", e))?;
        let dt = naive.and_hms_opt(0, 0, 0).unwrap();
        Ok((DateTime::from_naive_utc_and_offset(dt, Utc), true))
    } else {
        Err("Event has no start time".into())
    }
}

async fn handler(
    state: Arc<AppState>,
    event: LambdaEvent<ScheduledEvent>,
) -> Result<SyncResponse, Error> {
    info!("Starting calendar sync");

    let mut response = SyncResponse {
        users_synced: 0,
        events_updated: 0,
        events_created: 0,
        errors: Vec::new(),
    };

    // Get users to sync
    let connections = if let Some(user_id) = &event.payload.user_id {
        // Sync specific user
        let user_uuid = Uuid::parse_str(user_id)
            .map_err(|e| format!("Invalid user_id: {}", e))?;
        vec![CalendarConnection {
            user_id: user_uuid,
            provider: "google".to_string(),
            secret_name: format!("second-brain/calendar/{}", user_id),
        }]
    } else {
        // Sync all connected users
        state.get_connected_users().await?
    };

    info!("Found {} users with connected calendars", connections.len());

    for connection in connections {
        match state.sync_user_events(&connection).await {
            Ok((created, updated)) => {
                info!(
                    "Synced user {}: {} created, {} updated",
                    connection.user_id, created, updated
                );
                response.users_synced += 1;
                response.events_created += created;
                response.events_updated += updated;
            }
            Err(e) => {
                error!("Failed to sync user {}: {}", connection.user_id, e);
                response.errors.push(format!(
                    "User {}: {}",
                    connection.user_id, e
                ));
            }
        }
    }

    info!(
        "Calendar sync complete: {} users, {} created, {} updated, {} errors",
        response.users_synced,
        response.events_created,
        response.events_updated,
        response.errors.len()
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

    run(service_fn(move |event| {
        let state = Arc::clone(&state);
        async move { handler(state, event).await }
    }))
    .await
}
