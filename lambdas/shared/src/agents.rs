//! AgentCore client for invoking Python agents.

use aws_sdk_bedrockagentruntime::Client as BedrockAgentClient;
use serde::{Deserialize, Serialize};

use crate::{Error, Result};

/// Request to the agent system.
#[derive(Debug, Serialize)]
pub struct AgentRequest {
    /// User's message
    pub message: String,
    /// User ID
    pub user_id: String,
    /// Family IDs the user belongs to
    pub family_ids: Vec<String>,
    /// Device ID (optional)
    pub device_id: Option<String>,
    /// Conversation/session ID
    pub conversation_id: Option<String>,
    /// Pre-classified intent (optional)
    pub intent: Option<String>,
    /// Source platform
    pub source: String,
}

/// Response from the agent system.
#[derive(Debug, Deserialize)]
pub struct AgentResponse {
    /// Status of the response
    pub status: String,
    /// Agent's response text
    pub response: String,
    /// User ID (echoed back)
    pub user_id: String,
    /// Conversation ID
    pub conversation_id: Option<String>,
    /// Additional metadata
    pub metadata: Option<AgentMetadata>,
}

/// Metadata about agent execution.
#[derive(Debug, Deserialize)]
pub struct AgentMetadata {
    /// Source platform
    pub source: Option<String>,
    /// Model used
    pub model_id: Option<String>,
    /// Agents that participated
    pub agents_used: Option<Vec<String>>,
    /// Number of handoffs
    pub handoff_count: Option<u32>,
}

/// Client for invoking the agent system.
pub struct AgentClient {
    /// Lambda client for invoking agent Lambda
    lambda_client: aws_sdk_lambda::Client,
    /// Agent Lambda function name/ARN
    agent_function_name: String,
}

impl AgentClient {
    /// Create a new agent client.
    pub fn new(lambda_client: aws_sdk_lambda::Client, agent_function_name: String) -> Self {
        Self {
            lambda_client,
            agent_function_name,
        }
    }

    /// Invoke the agent system.
    pub async fn invoke(&self, request: AgentRequest) -> Result<AgentResponse> {
        let payload = serde_json::to_vec(&request)
            .map_err(|e| Error::Serialization(e))?;

        let response = self
            .lambda_client
            .invoke()
            .function_name(&self.agent_function_name)
            .payload(aws_sdk_lambda::primitives::Blob::new(payload))
            .send()
            .await
            .map_err(|e| Error::Aws(format!("Failed to invoke agent: {}", e)))?;

        let response_payload = response
            .payload()
            .ok_or_else(|| Error::Aws("No response payload from agent".to_string()))?;

        let agent_response: AgentResponse = serde_json::from_slice(response_payload.as_ref())
            .map_err(|e| Error::Aws(format!("Failed to parse agent response: {}", e)))?;

        if agent_response.status == "error" {
            return Err(Error::Internal(agent_response.response));
        }

        Ok(agent_response)
    }

    /// Invoke for a query (convenience method).
    pub async fn query(
        &self,
        message: &str,
        user_id: &str,
        family_ids: Vec<String>,
        conversation_id: Option<String>,
        source: &str,
    ) -> Result<AgentResponse> {
        self.invoke(AgentRequest {
            message: message.to_string(),
            user_id: user_id.to_string(),
            family_ids,
            device_id: None,
            conversation_id,
            intent: Some("query".to_string()),
            source: source.to_string(),
        })
        .await
    }

    /// Invoke for ingestion (convenience method).
    pub async fn ingest(
        &self,
        message: &str,
        user_id: &str,
        family_ids: Vec<String>,
        source: &str,
    ) -> Result<AgentResponse> {
        self.invoke(AgentRequest {
            message: message.to_string(),
            user_id: user_id.to_string(),
            family_ids,
            device_id: None,
            conversation_id: None,
            intent: Some("ingest".to_string()),
            source: source.to_string(),
        })
        .await
    }

    /// Invoke for taxonomy operations (tag suggestions, analysis).
    pub async fn taxonomy(
        &self,
        operation: &str,
        user_id: &str,
        family_ids: Vec<String>,
        context: Option<String>,
    ) -> Result<AgentResponse> {
        let message = match operation {
            "suggest" => format!("Suggest tags for: {}", context.unwrap_or_default()),
            "analyze" => "Analyze my tag taxonomy and suggest improvements".to_string(),
            "batch" => "Find untagged facts and suggest tags for them".to_string(),
            _ => operation.to_string(),
        };

        self.invoke(AgentRequest {
            message,
            user_id: user_id.to_string(),
            family_ids,
            device_id: None,
            conversation_id: None,
            intent: Some("taxonomy".to_string()),
            source: "api".to_string(),
        })
        .await
    }
}
