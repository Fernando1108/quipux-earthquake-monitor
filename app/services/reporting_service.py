"""Service that assembles and stores periodic seismic activity reports."""

import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.models.earthquake import Earthquake
from app.models.report import Report, TopLocation
from app.repositories.earthquake_repository import EarthquakeRepository
from app.repositories.report_repository import ReportRepository

logger = logging.getLogger(__name__)

TOP_LOCATIONS_LIMIT = 3


class ReportingService:
    """Build and persist consolidated reports for exact closed UTC hours."""

    def __init__(
        self,
        earthquake_repository: EarthquakeRepository | None = None,
        report_repository: ReportRepository | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._earthquake_repository = (
            earthquake_repository
            if earthquake_repository is not None
            else EarthquakeRepository()
        )
        self._report_repository = (
            report_repository
            if report_repository is not None
            else ReportRepository()
        )
        self._now_provider = now_provider if now_provider is not None else _utc_now

    async def generate_hourly_report(
        self,
        report_date: datetime,
    ) -> Report:
        """Build and persist one hourly report for the given closed UTC hour.

        report_date identifies the end of the closed hour.
        Raises ValueError when report_date is invalid, non-UTC-aligned, or refers
        to a future hour that has not yet closed.
        All repository and Pydantic errors propagate unchanged.
        """
        normalized_report_date = _validated_report_date(report_date)
        generated_at = _validated_utc_now(self._now_provider)

        if normalized_report_date > generated_at:
            raise ValueError(
                f"report_date {normalized_report_date.isoformat()!r} is in the future; "
                "report_date must identify an already closed UTC hour"
            )

        period_end = normalized_report_date
        period_start = period_end - timedelta(hours=1)

        earthquakes = await self._earthquake_repository.find_by_time_range(
            period_start,
            period_end,
        )

        events_with_magnitude, average_magnitude, max_magnitude = _magnitude_summary(
            earthquakes
        )
        top_locations = _top_locations(earthquakes)

        report = Report(
            report_date=normalized_report_date,
            period_start=period_start,
            period_end=period_end,
            total_events=len(earthquakes),
            events_with_magnitude=events_with_magnitude,
            average_magnitude=average_magnitude,
            max_magnitude=max_magnitude,
            top_locations=top_locations,
            generated_at=generated_at,
        )

        await self._report_repository.upsert_report(report)

        logger.info(
            "Hourly report generated: report_date=%s total_events=%d "
            "events_with_magnitude=%d top_locations=%d",
            report.report_date.isoformat(),
            report.total_events,
            report.events_with_magnitude,
            len(report.top_locations),
        )

        return report


# ---------------------------------------------------------------------------
# Private helpers — no I/O
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


def _validated_utc_now(provider: Callable[[], datetime]) -> datetime:
    """Call provider and return a timezone-aware UTC datetime.

    Raises ValueError for non-datetime or naive output.
    """
    value = provider()
    if not isinstance(value, datetime):
        raise ValueError(
            f"now_provider must return a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_provider must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _validated_report_date(value: object) -> datetime:
    """Validate and normalize report_date to UTC.

    Requires an actual datetime instance that is timezone-aware and aligned
    to the start of an exact UTC hour.
    Raises ValueError for any invalid input.
    """
    if not isinstance(value, datetime):
        raise ValueError(
            f"report_date must be a datetime instance, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "report_date must be timezone-aware"
        )
    normalized = value.astimezone(timezone.utc)
    if normalized.minute != 0 or normalized.second != 0 or normalized.microsecond != 0:
        raise ValueError(
            f"report_date must be aligned to the start of an exact UTC hour "
            f"(minute=0, second=0, microsecond=0), got {normalized.isoformat()!r}"
        )
    return normalized


def _magnitude_summary(
    earthquakes: list[Earthquake],
) -> tuple[int, float | None, float | None]:
    """Return (events_with_magnitude, average_magnitude, max_magnitude).

    Selects magnitudes where earthquake.magnitude is not None.
    Zero magnitude is valid and is included.
    When no known magnitudes exist, returns (0, None, None).
    Does not mutate the earthquake list or objects.
    """
    magnitudes = [eq.magnitude for eq in earthquakes if eq.magnitude is not None]
    if not magnitudes:
        return 0, None, None
    count = len(magnitudes)
    average = sum(magnitudes) / count
    maximum = max(magnitudes)
    return count, average, maximum


def _top_locations(
    earthquakes: list[Earthquake],
    limit: int = TOP_LOCATIONS_LIMIT,
) -> list[TopLocation]:
    """Return the top locations by earthquake count, deterministically ordered.

    Counts exact location strings (case-sensitive) using Counter.
    Sorts by count descending, then location ascending to break ties.
    Returns at most `limit` TopLocation objects.
    Earthquakes with location=None are ignored.
    Does not mutate the earthquake list or objects.
    """
    counts: Counter[str] = Counter(
        eq.location for eq in earthquakes if eq.location is not None
    )
    if not counts:
        return []
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        TopLocation(location=location, count=count)
        for location, count in sorted_items[:limit]
    ]
