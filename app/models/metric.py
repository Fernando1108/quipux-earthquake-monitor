"""Pydantic model representing computed seismic metrics for a given time window."""

import math
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MagnitudeDistribution(BaseModel):
    """Count of earthquakes in each approved magnitude range for one hourly window.

    All six fields are required and must be non-negative integers.
    """

    model_config = ConfigDict(extra="forbid")

    under_2: int = Field(ge=0, strict=True)
    from_2_to_under_4: int = Field(ge=0, strict=True)
    from_4_to_under_5: int = Field(ge=0, strict=True)
    from_5_to_under_6: int = Field(ge=0, strict=True)
    six_or_more: int = Field(ge=0, strict=True)
    unknown: int = Field(ge=0, strict=True)


class Metric(BaseModel):
    """Aggregated seismic statistics for one exact hourly time window.

    All datetime fields must be timezone-aware and are normalised to UTC.
    Internal consistency between counts, sums, averages, and the magnitude
    distribution is enforced at construction time.
    """

    model_config = ConfigDict(extra="forbid")

    window_start: datetime
    window_end: datetime
    earthquake_count: int = Field(ge=0, strict=True)
    magnitude_count: int = Field(ge=0, strict=True)
    magnitude_sum: float
    average_magnitude: float | None
    max_magnitude: float | None
    magnitude_distribution: MagnitudeDistribution
    updated_at: datetime

    # ------------------------------------------------------------------
    # Datetime normalisation — reject naive, convert aware to UTC
    # ------------------------------------------------------------------

    @field_validator("window_start", "window_end", "updated_at")
    @classmethod
    def require_timezone_and_normalise(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include timezone information")
        return value.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # window_start must be exactly on the hour
    # ------------------------------------------------------------------

    @field_validator("window_start")
    @classmethod
    def window_start_must_be_on_hour(cls, value: datetime) -> datetime:
        if value.minute != 0 or value.second != 0 or value.microsecond != 0:
            raise ValueError(
                "window_start must be aligned to the beginning of an hour "
                "(minute=0, second=0, microsecond=0)"
            )
        return value

    # ------------------------------------------------------------------
    # Cross-field validations
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_consistency(self) -> "Metric":
        self._check_window_end()
        self._check_updated_at()
        self._check_magnitude_count()
        self._check_distribution()
        self._check_magnitude_stats()
        return self

    def _check_window_end(self) -> None:
        expected = self.window_start + timedelta(hours=1)
        if self.window_end != expected:
            raise ValueError(
                f"window_end must be exactly window_start + 1 hour "
                f"(expected {expected!r}, got {self.window_end!r})"
            )

    def _check_updated_at(self) -> None:
        if self.updated_at < self.window_start:
            raise ValueError(
                "updated_at must be greater than or equal to window_start"
            )

    def _check_magnitude_count(self) -> None:
        if self.magnitude_count > self.earthquake_count:
            raise ValueError(
                "magnitude_count must not exceed earthquake_count"
            )

    def _check_distribution(self) -> None:
        d = self.magnitude_distribution
        known_total = (
            d.under_2
            + d.from_2_to_under_4
            + d.from_4_to_under_5
            + d.from_5_to_under_6
            + d.six_or_more
        )
        total = known_total + d.unknown

        if total != self.earthquake_count:
            raise ValueError(
                f"sum of all magnitude_distribution counters ({total}) "
                f"must equal earthquake_count ({self.earthquake_count})"
            )
        if known_total != self.magnitude_count:
            raise ValueError(
                f"sum of known magnitude_distribution counters ({known_total}) "
                f"must equal magnitude_count ({self.magnitude_count})"
            )
        expected_unknown = self.earthquake_count - self.magnitude_count
        if d.unknown != expected_unknown:
            raise ValueError(
                f"magnitude_distribution.unknown ({d.unknown}) must equal "
                f"earthquake_count - magnitude_count ({expected_unknown})"
            )

    def _check_magnitude_stats(self) -> None:
        if self.magnitude_count == 0:
            if self.magnitude_sum != 0:
                raise ValueError(
                    "magnitude_sum must be 0 when magnitude_count is 0"
                )
            if self.average_magnitude is not None:
                raise ValueError(
                    "average_magnitude must be None when magnitude_count is 0"
                )
            if self.max_magnitude is not None:
                raise ValueError(
                    "max_magnitude must be None when magnitude_count is 0"
                )
        else:
            if self.average_magnitude is None:
                raise ValueError(
                    "average_magnitude must not be None when magnitude_count > 0"
                )
            if self.max_magnitude is None:
                raise ValueError(
                    "max_magnitude must not be None when magnitude_count > 0"
                )
            expected_avg = self.magnitude_sum / self.magnitude_count
            if not math.isclose(
                self.average_magnitude, expected_avg, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError(
                    f"average_magnitude ({self.average_magnitude}) must equal "
                    f"magnitude_sum / magnitude_count ({expected_avg})"
                )
            if self.max_magnitude < self.average_magnitude:
                raise ValueError(
                    "max_magnitude must be greater than or equal to average_magnitude"
                )
