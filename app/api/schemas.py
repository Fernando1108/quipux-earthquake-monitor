"""Shared Pydantic schemas, query-parameter models, and paginated response type."""

import math
from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.config.settings import Settings

# ---------------------------------------------------------------------------
# Settings-derived pagination constants
# ---------------------------------------------------------------------------

_settings = Settings()

DEFAULT_PAGE_SIZE: int = _settings.default_page_size
MAX_PAGE_SIZE: int = _settings.max_page_size

# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class SortOrder(StrEnum):
    """Public API sort direction values."""

    ASC = "asc"
    DESC = "desc"


# ---------------------------------------------------------------------------
# Common query base model
# ---------------------------------------------------------------------------


class BaseListQueryParams(BaseModel):
    """Shared pagination, time-range, and sort-direction parameters."""

    model_config = ConfigDict(extra="forbid")

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    start_time: datetime | None = None
    end_time: datetime | None = None
    sort: SortOrder = SortOrder.DESC

    @field_validator("page", "page_size", mode="before")
    @classmethod
    def reject_bool(cls, value: object) -> object:
        """Reject Python bool values masquerading as integers."""
        if isinstance(value, bool):
            raise ValueError("must be an integer, not bool")
        return value

    @field_validator("page")
    @classmethod
    def page_must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page must be >= 1")
        return value

    @field_validator("page_size")
    @classmethod
    def page_size_in_range(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page_size must be >= 1")
        if value > MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be <= {MAX_PAGE_SIZE}")
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "datetime must include timezone information"
            )
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def start_before_end(self) -> "BaseListQueryParams":
        """Reject start_time > end_time."""
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError("start_time must not be greater than end_time")
        return self

    @property
    def sort_descending(self) -> bool:
        """Return True when sort order is descending."""
        return self.sort is SortOrder.DESC


# ---------------------------------------------------------------------------
# Earthquake query model
# ---------------------------------------------------------------------------


class EarthquakeQueryParams(BaseListQueryParams):
    """Query parameters for GET /earthquakes."""

    min_magnitude: float | None = None
    max_magnitude: float | None = None

    @field_validator("min_magnitude", "max_magnitude", mode="before")
    @classmethod
    def reject_bool_magnitude(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("magnitude must be a number, not bool")
        return value

    @field_validator("min_magnitude", "max_magnitude", mode="after")
    @classmethod
    def require_finite_magnitude(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("magnitude must be finite")
        return value

    @model_validator(mode="after")
    def min_not_greater_than_max(self) -> "EarthquakeQueryParams":
        if (
            self.min_magnitude is not None
            and self.max_magnitude is not None
            and self.min_magnitude > self.max_magnitude
        ):
            raise ValueError("min_magnitude must not be greater than max_magnitude")
        return self


# ---------------------------------------------------------------------------
# Metric query model
# ---------------------------------------------------------------------------


class MetricQueryParams(BaseListQueryParams):
    """Query parameters for GET /metrics."""


# ---------------------------------------------------------------------------
# Report query model
# ---------------------------------------------------------------------------


class ReportQueryParams(BaseListQueryParams):
    """Query parameters for GET /reports."""


# ---------------------------------------------------------------------------
# Generic paginated response
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response returned by list endpoints."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int

    @field_validator("page")
    @classmethod
    def page_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page must be >= 1")
        return value

    @field_validator("page_size")
    @classmethod
    def page_size_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("page_size must be >= 1")
        return value

    @field_validator("total")
    @classmethod
    def total_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("total must be >= 0")
        return value

    @field_validator("total_pages")
    @classmethod
    def total_pages_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("total_pages must be >= 0")
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> "PaginatedResponse[T]":
        if len(self.items) > self.page_size:
            raise ValueError("items count must not exceed page_size")
        if len(self.items) > self.total:
            raise ValueError("items count must not exceed total")
        expected_pages = (
            0
            if self.total == 0
            else (self.total + self.page_size - 1) // self.page_size
        )
        if self.total_pages != expected_pages:
            raise ValueError(
                f"total_pages must be {expected_pages} "
                f"for total={self.total} and page_size={self.page_size}"
            )
        return self


# ---------------------------------------------------------------------------
# Pagination builder
# ---------------------------------------------------------------------------


def build_paginated_response(
    *,
    items: list[T],
    page: int,
    page_size: int,
    total: int,
) -> "PaginatedResponse[T]":
    """Build a PaginatedResponse without floating-point arithmetic.

    total_pages is 0 when total is 0, otherwise ceiling division via
    integer arithmetic: (total + page_size - 1) // page_size.
    """
    total_pages = 0
    if total > 0 and page_size > 0:
        total_pages = (total + page_size - 1) // page_size
    return PaginatedResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "SortOrder",
    "BaseListQueryParams",
    "EarthquakeQueryParams",
    "MetricQueryParams",
    "ReportQueryParams",
    "PaginatedResponse",
    "build_paginated_response",
]
