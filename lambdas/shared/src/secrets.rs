//! AWS Secrets Manager integration.

use aws_sdk_secretsmanager::Client as SecretsClient;
use serde::Deserialize;
use std::collections::HashMap;
use std::sync::OnceLock;
use tokio::sync::RwLock;

use crate::{Error, Result};

/// Cached secrets with lazy initialization.
static SECRETS_CACHE: OnceLock<RwLock<HashMap<String, String>>> = OnceLock::new();

fn get_cache() -> &'static RwLock<HashMap<String, String>> {
    SECRETS_CACHE.get_or_init(|| RwLock::new(HashMap::new()))
}

/// Database credentials from Secrets Manager.
#[derive(Debug, Deserialize)]
pub struct DatabaseCredentials {
    pub username: String,
    pub password: String,
    pub host: Option<String>,
    pub port: Option<u16>,
    pub dbname: Option<String>,
}

/// Get a secret value from Secrets Manager with caching.
pub async fn get_secret(client: &SecretsClient, secret_arn: &str) -> Result<String> {
    // Check cache first
    {
        let cache = get_cache().read().await;
        if let Some(value) = cache.get(secret_arn) {
            return Ok(value.clone());
        }
    }

    // Fetch from Secrets Manager
    let response = client
        .get_secret_value()
        .secret_id(secret_arn)
        .send()
        .await
        .map_err(|e| Error::Aws(format!("Failed to get secret: {}", e)))?;

    let secret_string = response
        .secret_string()
        .ok_or_else(|| Error::Aws("Secret has no string value".to_string()))?
        .to_string();

    // Cache the result
    {
        let mut cache = get_cache().write().await;
        cache.insert(secret_arn.to_string(), secret_string.clone());
    }

    Ok(secret_string)
}

/// Get database credentials from Secrets Manager.
pub async fn get_database_credentials(
    client: &SecretsClient,
    secret_arn: &str,
) -> Result<DatabaseCredentials> {
    let secret_string = get_secret(client, secret_arn).await?;

    serde_json::from_str(&secret_string)
        .map_err(|e| Error::Aws(format!("Failed to parse database credentials: {}", e)))
}

/// Clear the secrets cache (useful for testing or credential rotation).
pub async fn clear_cache() {
    let mut cache = get_cache().write().await;
    cache.clear();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_credentials() {
        let json = r#"{"username":"admin","password":"secret123","host":"db.example.com","port":5432,"dbname":"mydb"}"#;
        let creds: DatabaseCredentials = serde_json::from_str(json).unwrap();
        assert_eq!(creds.username, "admin");
        assert_eq!(creds.password, "secret123");
        assert_eq!(creds.host, Some("db.example.com".to_string()));
    }
}
