"""Pydantic model representing a periodic seismic activity report."""

import math
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TopLocation(BaseModel):
    """Location with earthquake count for a report's top-locations list."""

    model_config = ConfigDict(extra="forbid")

    location: str
    count: int = Field(ge=1, strict=True)

    @field_validator("location", mode="before")
    @classmethod
    def validate_location(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("location must be a non-empty string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("location cannot be empty or whitespace-only")
        return stripped


class Report(BaseModel):
    """Hourly seismic activity report for one exact closed UTC hour.

    All datetime fields must be timezone-aware and are normalised to UTC.
    Internal consistency between the time window, counts, magnitude statistics,
    and top-locations list is enforced at construction time.
    """

    model_config = ConfigDict(extra="forbid")

    report_date: datetime
    period_start: datetime
    period_end: datetime
    total_events: int = Field(ge=0, strict=True)
    events_with_magnitude: int = Field(ge=0, strict=True)
    average_magnitude: float | None
    max_magnitude: float | None
    top_locations: list[TopLocation]
    generated_at: datetime

    # ------------------------------------------------------------------
    # Datetime normalisation — reject naive, convert aware to UTC
    # ------------------------------------------------------------------

    @field_validator("report_date", "period_start", "period_end", "generated_at")
    @classmethod
    def require_timezone_and_normalise(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include timezone information")
        return value.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # period_start must be exactly on the hour (validated after UTC normalisation)
    # ------------------------------------------------------------------

    @field_validator("period_start")
    @classmethod
    def period_start_must_be_on_hour(cls, value: datetime) -> datetime:
        if value.minute != 0 or value.second != 0 or value.microsecond != 0:
            raise ValueError(
                "period_start must be aligned to the beginning of an hour "
                "(minute=0, second=0, microsecond=0)"
            )
        return value

    # ------------------------------------------------------------------
    # Cross-field validations
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_consistency(self) -> "Report":
        self._check_time_window()
        self._check_counts()
        self._check_magnitude_stats()
        self._check_top_locations()
        return self

    def _check_time_window(self) -> None:
        expected_end = self.period_start + timedelta(hours=1)
        if self.period_end != expected_end:
            raise ValueError(
                f"period_end must be exactly period_start + 1 hour "
                f"(expected {expected_end!r}, got {self.period_end!r})"
            )
        if self.report_date != self.period_end:
            raise ValueError(
                f"report_date must equal period_end "
                f"(expected {self.period_end!r}, got {self.report_date!r})"
            )
        if self.generated_at < self.period_end:
            raise ValueError(
                "generated_at must be greater than or equal to period_end"
            )

    def _check_counts(self) -> None:
        if self.events_with_magnitude > self.total_events:
            raise ValueError(
                "events_with_magnitude must not exceed total_events"
            )

    def _check_magnitude_stats(self) -> None:
        if self.events_with_magnitude == 0:
            if self.average_magnitude is not None:
                raise ValueError(
                    "average_magnitude must be None when events_with_magnitude is 0"
                )
            if self.max_magnitude is not None:
                raise ValueError(
                    "max_magnitude must be None when events_with_magnitude is 0"
                )
        else:
            if self.average_magnitude is None:
                raise ValueError(
                    "average_magnitude must not be None when events_with_magnitude > 0"
                )
            if self.max_magnitude is None:
                raise ValueError(
                    "max_magnitude must not be None when events_with_magnitude > 0"
                )
            if not math.isfinite(self.average_magnitude):
                raise ValueError("average_magnitude must be a finite number")
            if not math.isfinite(self.max_magnitude):
                raise ValueError("max_magnitude must be a finite number")
            if self.max_magnitude < self.average_magnitude:
                raise ValueError(
                    "max_magnitude must be greater than or equal to average_magnitude"
                )

    def _check_top_locations(self) -> None:
        locations = [item.location for item in self.top_locations]
        if len(locations) != len(set(locations)):
            raise ValueError(
                "top_locations must not contain duplicate location values"
            )
        total_count = sum(item.count for item in self.top_locations)
        if total_count > self.total_events:
            raise ValueError(
                f"sum of top_locations counts ({total_count}) "
                f"must not exceed total_events ({self.total_events})"
            )
