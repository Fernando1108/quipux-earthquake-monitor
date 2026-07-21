"""Pydantic model representing a seismic event as stored and returned by the API."""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator


class Earthquake(BaseModel):
    """Internal domain model for a seismic event.

    Fields map directly to the data stored in MongoDB and returned by the API.
    No USGS-specific fields are included; mapping from the USGS feed is handled
    separately in the ingestion layer.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    magnitude: float | None = None
    location: str | None = None
    latitude: float
    longitude: float
    depth: float
    event_time: datetime

    @field_validator("event_id", mode="before")
    @classmethod
    def validate_event_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("event_id must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("event_id cannot be empty or whitespace")
        return stripped

    @field_validator("location", mode="before")
    @classmethod
    def validate_location(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("location must be a string or None")
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: float) -> float:
        if not -90 <= value <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: float) -> float:
        if not -180 <= value <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return value

    @field_validator("depth")
    @classmethod
    def validate_depth(cls, value: float) -> float:
        if value < 0:
            raise ValueError("depth must be >= 0")
        return value

    @field_validator("event_time")
    @classmethod
    def validate_and_normalize_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_time must include timezone information")
        return value.astimezone(timezone.utc)
