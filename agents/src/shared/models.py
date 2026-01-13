"""Pydantic models for Second Brain agents."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FactCreate(BaseModel):
    """Model for creating a new fact."""

    content: str = Field(..., min_length=1, max_length=10000)
    owner_type: str = Field(default="user", pattern="^(user|family)$")
    owner_id: UUID
    about_entity_id: UUID | None = None
    importance: int = Field(default=3, ge=1, le=5)
    visibility_tier: int = Field(default=3, ge=1, le=4)
    valid_from: date | None = None
    valid_to: date | None = None
    source_type: str = Field(default="voice", pattern="^(voice|text|import|calendar)$")
    source_device_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    """Model representing a stored fact."""

    id: UUID
    content: str
    owner_type: str
    owner_id: UUID
    about_entity_id: UUID | None = None
    importance: int
    visibility_tier: int
    valid_from: date | None = None
    valid_to: date | None = None
    recorded_at: datetime
    entity_name: str | None = None


class EntityCreate(BaseModel):
    """Model for creating a new entity."""

    entity_type: str = Field(..., pattern="^(person|organization|place|project|event)$")
    name: str = Field(..., min_length=1, max_length=255)
    owner_type: str = Field(default="user", pattern="^(user|family)$")
    owner_id: UUID
    canonical_name: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Entity(BaseModel):
    """Model representing a stored entity."""

    id: UUID
    entity_type: str
    name: str
    canonical_name: str | None = None
    owner_type: str
    owner_id: UUID
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EntityLocation(BaseModel):
    """Model for entity location data."""

    entity_id: UUID
    label: str
    address_raw: str
    latitude: float
    longitude: float
    geocode_confidence: float = 1.0


class CalendarEvent(BaseModel):
    """Model representing a calendar event."""

    id: UUID
    user_id: UUID
    title: str
    description: str | None = None
    location: str | None = None
    start_time: datetime
    end_time: datetime
    all_day: bool = False
    visibility_tier: int = 3


class SearchResult(BaseModel):
    """Model for search results with similarity score."""

    id: UUID
    content: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)
