//! Geocoder Lambda - Geocodes addresses using AWS Location Service.

use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Deserialize)]
struct GeocodeRequest {
    address: String,
    entity_id: String,
    location_label: String,
}

#[derive(Debug, Serialize)]
struct GeocodeResponse {
    success: bool,
    latitude: Option<f64>,
    longitude: Option<f64>,
    confidence: Option<f64>,
    error: Option<String>,
}

async fn handler(event: LambdaEvent<GeocodeRequest>) -> Result<GeocodeResponse, Error> {
    let _request = event.payload;

    // TODO: Implement geocoding
    // - Call AWS Location Service SearchPlaceIndexForText
    // - Store result in entity_locations table
    // - Return coordinates and confidence

    Ok(GeocodeResponse {
        success: false,
        latitude: None,
        longitude: None,
        confidence: None,
        error: Some("Not yet implemented".to_string()),
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
