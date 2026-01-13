"""Configuration management for Second Brain agents."""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


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

    # Bedrock
    embedding_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        alias="EMBEDDING_MODEL_ID",
    )
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")

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
