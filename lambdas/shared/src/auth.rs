//! JWT authentication utilities.

use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};

use crate::{Error, Result};

/// JWT claims from Cognito.
#[derive(Debug, Serialize, Deserialize)]
pub struct CognitoClaims {
    /// Subject (user id)
    pub sub: String,
    /// Email
    pub email: Option<String>,
    /// Cognito username
    #[serde(rename = "cognito:username")]
    pub cognito_username: Option<String>,
    /// Token use (access or id)
    pub token_use: String,
    /// Client id
    pub client_id: Option<String>,
    /// Issued at
    pub iat: i64,
    /// Expiration
    pub exp: i64,
    /// Issuer
    pub iss: String,
    /// Custom claims - family IDs
    #[serde(rename = "custom:family_ids", default)]
    pub family_ids: Option<String>,
}

/// Decoded user information from JWT.
#[derive(Debug, Clone)]
pub struct AuthenticatedUser {
    /// User's Cognito subject (UUID)
    pub user_id: String,
    /// User's email
    pub email: Option<String>,
    /// User's family IDs (parsed from custom claim)
    pub family_ids: Vec<String>,
}

impl TryFrom<CognitoClaims> for AuthenticatedUser {
    type Error = Error;

    fn try_from(claims: CognitoClaims) -> Result<Self> {
        let family_ids = claims
            .family_ids
            .map(|ids| ids.split(',').map(|s| s.trim().to_string()).collect())
            .unwrap_or_default();

        Ok(Self {
            user_id: claims.sub,
            email: claims.email.or(claims.cognito_username),
            family_ids,
        })
    }
}

/// Validate a JWT token and extract user information.
///
/// Note: In production, this should validate against Cognito's JWKS endpoint.
/// For now, we assume API Gateway has already validated the token.
pub fn validate_token(token: &str, _issuer: &str) -> Result<AuthenticatedUser> {
    // In production, fetch JWKS from Cognito and validate properly
    // For Lambda behind API Gateway with Cognito authorizer, the token is pre-validated
    // We just decode it to extract claims

    // Skip "Bearer " prefix if present
    let token = token.strip_prefix("Bearer ").unwrap_or(token);

    // Decode without validation (API Gateway already validated)
    let mut validation = Validation::new(Algorithm::RS256);
    validation.insecure_disable_signature_validation();
    validation.validate_exp = false;

    // Use a dummy key since we're not validating signature
    let key = DecodingKey::from_secret(b"dummy");

    let token_data = decode::<CognitoClaims>(token, &key, &validation)
        .map_err(|e| Error::Auth(format!("Failed to decode token: {}", e)))?;

    AuthenticatedUser::try_from(token_data.claims)
}

/// Extract user from API Gateway request context.
///
/// When using Cognito authorizer, user info is in requestContext.authorizer.claims
pub fn extract_user_from_context(
    claims: &serde_json::Value,
) -> Result<AuthenticatedUser> {
    let sub = claims
        .get("sub")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::Auth("Missing sub claim".to_string()))?;

    let email = claims.get("email").and_then(|v| v.as_str()).map(String::from);

    let family_ids = claims
        .get("custom:family_ids")
        .and_then(|v| v.as_str())
        .map(|ids| ids.split(',').map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    Ok(AuthenticatedUser {
        user_id: sub.to_string(),
        email,
        family_ids,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_family_ids() {
        let claims = CognitoClaims {
            sub: "user-123".to_string(),
            email: Some("test@example.com".to_string()),
            cognito_username: None,
            token_use: "access".to_string(),
            client_id: None,
            iat: 0,
            exp: 0,
            iss: "https://cognito-idp.us-east-1.amazonaws.com/pool-id".to_string(),
            family_ids: Some("family-1, family-2".to_string()),
        };

        let user = AuthenticatedUser::try_from(claims).unwrap();
        assert_eq!(user.family_ids, vec!["family-1", "family-2"]);
    }
}
