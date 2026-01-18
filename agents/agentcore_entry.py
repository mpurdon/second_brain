"""AWS AgentCore Runtime entry point for Second Brain agents.

This module provides the entry point for deploying Second Brain agents
to AWS AgentCore Runtime. It handles request routing and agent orchestration.
"""

import json
import os
from typing import Any

from src.router import create_router_agent
from src.ingestion import create_ingestion_agent
from src.query import create_query_agent
from src.shared.database import reset_knowledge_base, run_async
from src.shared.tools.database import fact_update, fact_delete, fact_search


# Model configuration
DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
)

# Initialize agents (lazy loading)
_router_agent = None
_ingestion_agent = None
_query_agent = None


def get_router_agent():
    """Get or create the Router Agent."""
    global _router_agent
    if _router_agent is None:
        # Use environment model ID instead of hardcoded Haiku
        _router_agent = create_router_agent(model_id=DEFAULT_MODEL_ID, use_haiku=False)
    return _router_agent


def get_ingestion_agent():
    """Get or create the Ingestion Agent."""
    global _ingestion_agent
    if _ingestion_agent is None:
        _ingestion_agent = create_ingestion_agent(model_id=DEFAULT_MODEL_ID)
    return _ingestion_agent


def get_query_agent():
    """Get or create the Query Agent."""
    global _query_agent
    if _query_agent is None:
        _query_agent = create_query_agent(model_id=DEFAULT_MODEL_ID)
    return _query_agent


def handle_request(event: dict[str, Any]) -> dict[str, Any]:
    """Handle an incoming request to the agent system.

    This is the main entry point called by AgentCore Runtime.

    Args:
        event: The incoming event with the following structure:
            {
                "message": str,           # User's message
                "user_id": str,           # User's UUID
                "family_ids": list[str],  # User's family memberships
                "device_id": str,         # Device making the request
                "conversation_id": str,   # Conversation context ID
                "intent": str,            # Pre-classified intent (optional)
                "source": str,            # Source platform (discord, alexa, api)
                "action": str,            # Special action (optional: reset_knowledge)
            }

    Returns:
        Response dictionary with agent output.
    """
    # Handle special actions first
    action = event.get("action")
    if action == "reset_knowledge":
        result = run_async(reset_knowledge_base())
        return result
    elif action == "search_facts":
        # Search for facts - useful for finding facts to edit/delete
        return fact_search(
            user_id=event.get("user_id", ""),
            query_text=event.get("query_text"),
            limit=event.get("limit", 20),
        )
    elif action == "update_fact":
        # Update a fact's content or metadata
        return fact_update(
            fact_id=event.get("fact_id", ""),
            user_id=event.get("user_id", ""),
            content=event.get("content"),
            importance=event.get("importance"),
            visibility_tier=event.get("visibility_tier"),
            valid_from=event.get("valid_from"),
            valid_to=event.get("valid_to"),
        )
    elif action == "delete_fact":
        # Delete a fact
        return fact_delete(
            fact_id=event.get("fact_id", ""),
            user_id=event.get("user_id", ""),
        )

    # Extract request parameters
    message = event.get("message", "")
    user_id = event.get("user_id", "")
    family_ids = event.get("family_ids", [])
    conversation_id = event.get("conversation_id")
    intent = event.get("intent")
    source = event.get("source", "api")

    if not message:
        return {
            "status": "error",
            "message": "No message provided",
        }

    if not user_id:
        return {
            "status": "error",
            "message": "No user_id provided",
        }

    # If intent is pre-classified, route directly
    if intent == "ingest":
        agent = get_ingestion_agent()
        result = agent.process(
            message=message,
            user_id=user_id,
            source_type="voice" if source == "alexa" else "text",
        )
    elif intent == "query":
        agent = get_query_agent()
        result = agent.process(
            query=message,
            user_id=user_id,
            family_ids=family_ids,
        )
    else:
        # Use Router Agent to classify and route
        router = get_router_agent()
        routing_result = router.process(
            message=message,
            user_id=user_id,
            family_ids=family_ids,
        )

        # Parse the routing decision and call appropriate agent
        response_text = routing_result.get("response", "").lower()

        if "ingestion" in response_text or "ingest" in response_text:
            # Route to ingestion agent
            agent = get_ingestion_agent()
            result = agent.process(
                message=message,
                user_id=user_id,
                source_type="text" if source != "alexa" else "voice",
            )
        elif "query" in response_text or "search" in response_text or "find" in response_text:
            # Route to query agent
            agent = get_query_agent()
            result = agent.process(
                query=message,
                user_id=user_id,
                family_ids=family_ids,
            )
        else:
            # Default to query agent for unknown intents
            agent = get_query_agent()
            result = agent.process(
                query=message,
                user_id=user_id,
                family_ids=family_ids,
            )

    return {
        "status": "success",
        "response": result.get("response", ""),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "metadata": {
            "source": source,
            "model_id": DEFAULT_MODEL_ID,
        },
    }


# Lambda handler for direct Lambda invocation (if not using AgentCore)
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda handler function.

    This can be used for direct Lambda invocation outside of AgentCore.
    It detects whether the call is from API Gateway (wraps response)
    or direct Lambda invocation (returns raw response).

    Args:
        event: Lambda event payload.
        context: Lambda context object.

    Returns:
        Response dictionary.
    """
    try:
        # Detect if this is an API Gateway request (has httpMethod or requestContext)
        is_api_gateway = "httpMethod" in event or "requestContext" in event

        # Parse body if this came from API Gateway
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        else:
            body = event

        result = handle_request(body)

        # If called from API Gateway, wrap in API Gateway format
        if is_api_gateway:
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps(result),
            }

        # If called directly (Lambda-to-Lambda), return raw response
        return result

    except Exception as e:
        error_response = {
            "status": "error",
            "response": str(e),
            "user_id": event.get("user_id", ""),
            "conversation_id": event.get("conversation_id"),
            "metadata": {},
        }

        # Check if API Gateway request
        is_api_gateway = "httpMethod" in event or "requestContext" in event
        if is_api_gateway:
            return {
                "statusCode": 500,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": json.dumps(error_response),
            }

        return error_response


# AgentCore Runtime entry point
def agent_handler(event: dict[str, Any]) -> dict[str, Any]:
    """AgentCore Runtime handler.

    This is the entry point used by AgentCore Runtime for managed
    agent deployment.

    Args:
        event: AgentCore event payload.

    Returns:
        Response dictionary.
    """
    return handle_request(event)
