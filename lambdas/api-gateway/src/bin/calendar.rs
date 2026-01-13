//! Calendar Lambda - Handles /v1/calendar endpoint.

use lambda_http::{run, service_fn, Body, Error, Request, Response};
use tracing_subscriber::EnvFilter;

async fn handler(_event: Request) -> Result<Response<Body>, Error> {
    // TODO: Implement calendar operations
    let response = Response::builder()
        .status(200)
        .header("content-type", "application/json")
        .body(Body::from(r#"{"message": "Calendar endpoint - not yet implemented"}"#))
        .map_err(Box::new)?;

    Ok(response)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    run(service_fn(handler)).await
}
