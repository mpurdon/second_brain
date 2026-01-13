//! Shared library for Second Brain Lambda functions.
//!
//! This crate provides common utilities, types, and clients used across all Lambda functions.

pub mod config;
pub mod db;
pub mod error;
pub mod models;

pub use config::Config;
pub use error::{Error, Result};
