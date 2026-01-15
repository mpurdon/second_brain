"""Configuration management for Second Brain agents."""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


# Model IDs for different capability levels
BEDROCK_MODELS = {
    "haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "opus": "anthropic.claude-3-opus-20240229-v1:0",
}

# Approximate costs per 1K tokens (input/output)
MODEL_COSTS = {
    "haiku": {"input": 0.00025, "output": 0.00125},
    "sonnet": {"input": 0.003, "output": 0.015},
    "opus": {"input": 0.015, "output": 0.075},
}


def get_model_for_task(
    task_type: Literal["routing", "query", "ingestion", "briefing", "taxonomy"],
    complexity: Literal["low", "medium", "high"] = "medium",
) -> str:
    """Get the appropriate model for a task based on complexity.

    Cost optimization strategy:
    - Low complexity: Use Haiku (cheapest)
    - Medium complexity: Use Sonnet (balanced)
    - High complexity: Use Sonnet (Opus reserved for special cases)

    Args:
        task_type: Type of task being performed.
        complexity: Estimated complexity level.

    Returns:
        Bedrock model ID.
    """
    # Routing is always simple classification - use Haiku
    if task_type == "routing":
        return BEDROCK_MODELS["haiku"]

    # Low complexity tasks use Haiku
    if complexity == "low":
        return BEDROCK_MODELS["haiku"]

    # Medium and high use Sonnet (good balance of capability and cost)
    return BEDROCK_MODELS["sonnet"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_host: str = Field(default="localhost", alias="DB_HOST")
    database_port: int = Field(default=5432, alias="DB_PORT")
    database_name: str = Field(default="second_brain", alias="DB_NAME")
    database_user: str = Field(default="postgres", alias="DB_USER")
    database_password: str = Field(default="", alias="DB_PASSWORD")

    # AWS
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # Bedrock Models - can be overridden via env vars
    router_model: str = Field(
        default=BEDROCK_MODELS["haiku"],
        alias="ROUTER_MODEL_ID",
    )
    agent_model: str = Field(
        default=BEDROCK_MODELS["sonnet"],
        alias="AGENT_MODEL_ID",
    )
    embedding_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        alias="EMBEDDING_MODEL_ID",
    )
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")

    # Cost optimization
    use_haiku_for_routing: bool = Field(default=True, alias="USE_HAIKU_ROUTING")

    # Location Service
    location_place_index: str = Field(
        default="second-brain-place-index",
        alias="LOCATION_PLACE_INDEX",
    )

    @property
    def database_url(self) -> str:
        """Get the database connection URL."""
        return (
            f"postgresql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
