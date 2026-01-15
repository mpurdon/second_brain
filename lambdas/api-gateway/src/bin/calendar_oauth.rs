//! Google Calendar OAuth Callback Handler
//!
//! Handles the OAuth2 callback from Google Calendar, exchanges authorization
//! codes for tokens, and stores refresh tokens securely.

use lambda_http::{run, service_fn, Body, Error, Request, RequestExt, Response};
use serde::{Deserialize, Serialize};
use shared::ApiResponse;
use std::sync::Arc;
use tracing::{error, info};
use tracing_subscriber::EnvFilter;

/// Google OAuth token response
#[derive(Debug, Deserialize)]
struct GoogleTokenResponse {
    access_token: String,
    refresh_token: Option<String>,
    expires_in: i64,
    token_type: String,
    scope: String,
}

/// Calendar connection stored in database
#[derive(Debug, Serialize)]
struct CalendarConnection {
    user_id: String,
    provider: String,
    connected: bool,
}

/// Application state
struct AppState {
    http_client: reqwest::Client,
    secrets_client: aws_sdk_secretsmanager::Client,
    google_client_id: String,
    google_client_secret: String,
    redirect_uri: String,
}

impl AppState {
    async fn new() -> Result<Self, Error> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let secrets_client = aws_sdk_secretsmanager::Client::new(&config);

        // Get Google OAuth credentials from Secrets Manager
        let secret_arn = std::env::var("GOOGLE_OAUTH_SECRET_ARN")
            .unwrap_or_else(|_| "second-brain/google-oauth".to_string());

        let secret_value = secrets_client
            .get_secret_value()
            .secret_id(&secret_arn)
            .send()
            .await
            .map_err(|e| format!("Failed to get Google OAuth secret: {}", e))?;

        let secret_string = secret_value
            .secret_string()
            .ok_or("Secret string is empty")?;

        let credentials: serde_json::Value = serde_json::from_str(secret_string)
            .map_err(|e| format!("Failed to parse credentials: {}", e))?;

        let client_id = credentials["client_id"]
            .as_str()
            .ok_or("Missing client_id")?
            .to_string();

        let client_secret = credentials["client_secret"]
            .as_str()
            .ok_or("Missing client_secret")?
            .to_string();

        let redirect_uri = std::env::var("OAUTH_REDIRECT_URI")
            .unwrap_or_else(|_| "https://api.example.com/v1/calendar/oauth/callback".to_string());

        Ok(Self {
            http_client: reqwest::Client::new(),
            secrets_client,
            google_client_id: client_id,
            google_client_secret: client_secret,
            redirect_uri,
        })
    }

    /// Exchange authorization code for tokens
    async fn exchange_code(&self, code: &str) -> Result<GoogleTokenResponse, Error> {
        let params = [
            ("code", code),
            ("client_id", &self.google_client_id),
            ("client_secret", &self.google_client_secret),
            ("redirect_uri", &self.redirect_uri),
            ("grant_type", "authorization_code"),
        ];

        let response = self
            .http_client
            .post("https://oauth2.googleapis.com/token")
            .form(&params)
            .send()
            .await
            .map_err(|e| format!("Token exchange request failed: {}", e))?;

        if !response.status().is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(format!("Token exchange failed: {}", error_text).into());
        }

        let token_response: GoogleTokenResponse = response
            .json()
            .await
            .map_err(|e| format!("Failed to parse token response: {}", e))?;

        Ok(token_response)
    }

    /// Store user's calendar tokens in Secrets Manager
    async fn store_user_tokens(
        &self,
        user_id: &str,
        tokens: &GoogleTokenResponse,
    ) -> Result<(), Error> {
        let secret_name = format!("second-brain/calendar/{}", user_id);

        let token_data = serde_json::json!({
            "provider": "google",
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_in": tokens.expires_in,
            "token_type": tokens.token_type,
            "scope": tokens.scope,
            "updated_at": chrono::Utc::now().to_rfc3339(),
        });

        // Try to update existing secret, or create new one
        let result = self
            .secrets_client
            .put_secret_value()
            .secret_id(&secret_name)
            .secret_string(token_data.to_string())
            .send()
            .await;

        match result {
            Ok(_) => {
                info!("Updated calendar tokens for user {}", user_id);
                Ok(())
            }
            Err(e) => {
                // If secret doesn't exist, create it
                if e.to_string().contains("ResourceNotFoundException") {
                    self.secrets_client
                        .create_secret()
                        .name(&secret_name)
                        .secret_string(token_data.to_string())
                        .send()
                        .await
                        .map_err(|e| format!("Failed to create secret: {}", e))?;

                    info!("Created calendar tokens for user {}", user_id);
                    Ok(())
                } else {
                    Err(format!("Failed to store tokens: {}", e).into())
                }
            }
        }
    }
}

/// Generate OAuth authorization URL
fn build_auth_url(state: &AppState, user_id: &str) -> String {
    let scopes = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
    ]
    .join(" ");

    // State parameter includes user_id for callback identification
    let state_param = base64::Engine::encode(
        &base64::engine::general_purpose::URL_SAFE_NO_PAD,
        user_id.as_bytes(),
    );

    format!(
        "https://accounts.google.com/o/oauth2/v2/auth?\
        client_id={}&\
        redirect_uri={}&\
        response_type=code&\
        scope={}&\
        access_type=offline&\
        prompt=consent&\
        state={}",
        urlencoding::encode(&state.google_client_id),
        urlencoding::encode(&state.redirect_uri),
        urlencoding::encode(&scopes),
        state_param
    )
}

async fn handler(state: Arc<AppState>, event: Request) -> Result<Response<Body>, Error> {
    let path = event.uri().path();
    let method = event.method().as_str();

    match (method, path) {
        // Initiate OAuth flow - returns URL to redirect user to
        ("GET", "/v1/calendar/oauth/start") => {
            // Get user_id from query params or auth context
            let params = event.query_string_parameters();
            let user_id = params.first("user_id").unwrap_or("unknown").to_string();

            let auth_url = build_auth_url(&state, &user_id);

            let response = ApiResponse {
                success: true,
                data: Some(serde_json::json!({
                    "auth_url": auth_url,
                    "message": "Redirect user to auth_url to connect Google Calendar"
                })),
                error: None,
            };

            Ok(Response::builder()
                .status(200)
                .header("content-type", "application/json")
                .body(Body::from(serde_json::to_string(&response)?))
                .expect("Failed to build response"))
        }

        // OAuth callback from Google
        ("GET", "/v1/calendar/oauth/callback") => {
            let params = event.query_string_parameters();

            // Check for error from Google
            if let Some(error) = params.first("error") {
                error!("OAuth error from Google: {}", error);
                return Ok(Response::builder()
                    .status(400)
                    .header("content-type", "application/json")
                    .body(Body::from(
                        serde_json::to_string(&ApiResponse::<()> {
                            success: false,
                            data: None,
                            error: Some(format!("OAuth error: {}", error)),
                        })?,
                    ))
                    .expect("Failed to build response"));
            }

            // Get authorization code
            let code = params
                .first("code")
                .ok_or("Missing authorization code")?;

            // Get user_id from state parameter
            let state_param = params.first("state").ok_or("Missing state parameter")?;

            let user_id_bytes = base64::Engine::decode(
                &base64::engine::general_purpose::URL_SAFE_NO_PAD,
                state_param,
            )
            .map_err(|e| format!("Invalid state parameter: {}", e))?;

            let user_id = String::from_utf8(user_id_bytes)
                .map_err(|e| format!("Invalid user_id in state: {}", e))?;

            info!("Processing OAuth callback for user {}", user_id);

            // Exchange code for tokens
            let tokens = state.exchange_code(code).await?;

            // Store tokens
            state.store_user_tokens(&user_id, &tokens).await?;

            // Return success page (or redirect to app)
            let html = r#"
<!DOCTYPE html>
<html>
<head><title>Calendar Connected</title></head>
<body>
    <h1>Google Calendar Connected!</h1>
    <p>Your calendar has been successfully connected to Second Brain.</p>
    <p>You can close this window.</p>
</body>
</html>
"#;

            Ok(Response::builder()
                .status(200)
                .header("content-type", "text/html")
                .body(Body::from(html))
                .expect("Failed to build response"))
        }

        _ => Ok(Response::builder()
            .status(404)
            .body(Body::from("Not found"))
            .expect("Failed to build response")),
    }
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .json()
        .init();

    let state = Arc::new(AppState::new().await?);

    run(service_fn(move |event| {
        let state = Arc::clone(&state);
        async move { handler(state, event).await }
    }))
    .await
}
