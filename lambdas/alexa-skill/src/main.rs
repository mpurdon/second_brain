//! Alexa Skill Lambda - Handles Alexa voice interactions.

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize)]
struct AlexaRequest {
    request: Value,
    session: Option<Value>,
    context: Option<Value>,
}

#[derive(Debug, Serialize)]
struct AlexaResponse {
    version: String,
    response: AlexaResponseBody,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AlexaResponseBody {
    output_speech: OutputSpeech,
    should_end_session: bool,
}

#[derive(Debug, Serialize)]
struct OutputSpeech {
    #[serde(rename = "type")]
    speech_type: String,
    text: String,
}

async fn handler(_event: LambdaEvent<AlexaRequest>) -> Result<AlexaResponse, Error> {
    // TODO: Implement Alexa skill handling
    // - Parse intent
    // - Handle account linking token
    // - Invoke AgentCore
    // - Format Alexa response

    Ok(AlexaResponse {
        version: "1.0".to_string(),
        response: AlexaResponseBody {
            output_speech: OutputSpeech {
                speech_type: "PlainText".to_string(),
                text: "Second Brain is not yet fully implemented.".to_string(),
            },
            should_end_session: true,
        },
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
