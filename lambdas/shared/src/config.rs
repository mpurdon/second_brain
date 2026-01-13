//! Configuration management for Lambda functions.

use std::env;

/// Application configuration loaded from environment variables.
#[derive(Debug, Clone)]
pub struct Config {
    /// Database host
    pub db_host: String,
    /// Database name
    pub db_name: String,
    /// ARN of the secret containing database credentials
    pub db_secret_arn: String,
    /// AWS region
    pub aws_region: String,
    /// AgentCore endpoint (if applicable)
    pub agentcore_endpoint: Option<String>,
}

impl Config {
    /// Load configuration from environment variables.
    pub fn from_env() -> Result<Self, env::VarError> {
        Ok(Self {
            db_host: env::var("DATABASE_HOST")?,
            db_name: env::var("DATABASE_NAME").unwrap_or_else(|_| "second_brain".to_string()),
            db_secret_arn: env::var("DATABASE_URL_SECRET_ARN")?,
            aws_region: env::var("AWS_REGION").unwrap_or_else(|_| "us-east-1".to_string()),
            agentcore_endpoint: env::var("AGENTCORE_ENDPOINT").ok(),
        })
    }
}
