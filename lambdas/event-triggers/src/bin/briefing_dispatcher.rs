//! Briefing Dispatcher Lambda - Triggers morning briefings based on timezone.

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    // EventBridge scheduled event
    #[serde(default)]
    detail_type: String,
}

#[derive(Debug, Serialize)]
struct DispatcherResponse {
    users_processed: u32,
    briefings_triggered: u32,
}

async fn handler(_event: LambdaEvent<ScheduledEvent>) -> Result<DispatcherResponse, Error> {
    // TODO: Implement briefing dispatch
    // - Query users by timezone where it's their briefing time
    // - Trigger briefing generation for each user
    // - Handle batch processing

    Ok(DispatcherResponse {
        users_processed: 0,
        briefings_triggered: 0,
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
