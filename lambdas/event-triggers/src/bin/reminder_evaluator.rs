//! Reminder Evaluator Lambda - Evaluates pending reminders and sends notifications.

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize)]
struct ScheduledEvent {
    #[serde(default)]
    detail_type: String,
}

#[derive(Debug, Serialize)]
struct EvaluatorResponse {
    reminders_evaluated: u32,
    notifications_sent: u32,
}

async fn handler(_event: LambdaEvent<ScheduledEvent>) -> Result<EvaluatorResponse, Error> {
    // TODO: Implement reminder evaluation
    // - Query pending reminders where remind_at <= now
    // - Evaluate trigger conditions
    // - Send notifications via SNS/Discord

    Ok(EvaluatorResponse {
        reminders_evaluated: 0,
        notifications_sent: 0,
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
