//! Calendar Sync Lambda - Syncs external calendars (Google, Outlook).

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    #[serde(default)]
    detail_type: String,
}

#[derive(Debug, Serialize)]
struct SyncResponse {
    users_synced: u32,
    events_updated: u32,
    events_created: u32,
}

async fn handler(_event: LambdaEvent<ScheduledEvent>) -> Result<SyncResponse, Error> {
    // TODO: Implement calendar sync
    // - Query users with connected calendars
    // - Fetch events from Google Calendar API
    // - Upsert events to calendar_events table
    // - Link attendees to entities

    Ok(SyncResponse {
        users_synced: 0,
        events_updated: 0,
        events_created: 0,
    })
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    run(service_fn(handler)).await
}
