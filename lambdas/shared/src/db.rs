//! Database connection management.

use sqlx::postgres::{PgPool, PgPoolOptions};
use std::time::Duration;

use crate::{Config, Error, Result};

/// Create a database connection pool.
pub async fn create_pool(config: &Config, password: &str) -> Result<PgPool> {
    let database_url = format!(
        "postgres://{}:{}@{}/{}",
        "sbadmin", // username from secret
        password,
        config.db_host,
        config.db_name
    );

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .acquire_timeout(Duration::from_secs(3))
        .connect(&database_url)
        .await
        .map_err(Error::Database)?;

    Ok(pool)
}
