"""Service that computes and persists aggregated seismic metrics from stored events."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.models.earthquake import Earthquake
from app.models.metric import MagnitudeDistribution, Metric
from app.repositories.metric_repository import MetricRepository


class MetricsService:
    """Classify earthquake magnitudes and maintain one hourly Metric per window."""

    def __init__(
        self,
        repository: MetricRepository | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository if repository is not None else MetricRepository()
        self._now_provider = now_provider if now_provider is not None else _utc_now

    async def update_for_earthquake(self, earthquake: Earthquake) -> Metric:
        """Increment the hourly metric that covers earthquake.event_time.

        Loads the existing metric (or starts from zero), applies the earthquake,
        persists the result, and returns the saved Metric.
        All repository and Pydantic errors propagate unchanged.
        """
        window_start, window_end = _hourly_window(earthquake.event_time)
        updated_at = _validated_utc_now(self._now_provider)

        existing = await self._repository.get_by_window_start(window_start)

        dist_values, counts = _extract_state(existing)
        dist_values, counts = _apply_earthquake(earthquake, dist_values, counts)

        magnitude_distribution = MagnitudeDistribution(**dist_values)
        metric = Metric(
            window_start=window_start,
            window_end=window_end,
            earthquake_count=counts["earthquake_count"],
            magnitude_count=counts["magnitude_count"],
            magnitude_sum=counts["magnitude_sum"],
            average_magnitude=counts["average_magnitude"],
            max_magnitude=counts["max_magnitude"],
            magnitude_distribution=magnitude_distribution,
            updated_at=updated_at,
        )

        await self._repository.upsert_metric(metric)
        return metric


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


def _hourly_window(event_time: datetime) -> tuple[datetime, datetime]:
    """Return (window_start, window_end) for the hour that contains event_time."""
    utc_time = event_time.astimezone(timezone.utc)
    window_start = utc_time.replace(minute=0, second=0, microsecond=0)
    window_end = window_start + timedelta(hours=1)
    return window_start, window_end


def _extract_state(
    existing: Metric | None,
) -> tuple[dict[str, int], dict[str, object]]:
    """Return (dist_values, counts) from an existing Metric or zeroed defaults."""
    if existing is None:
        dist_values = {
            "under_2": 0,
            "from_2_to_under_4": 0,
            "from_4_to_under_5": 0,
            "from_5_to_under_6": 0,
            "six_or_more": 0,
            "unknown": 0,
        }
        counts: dict[str, object] = {
            "earthquake_count": 0,
            "magnitude_count": 0,
            "magnitude_sum": 0.0,
            "average_magnitude": None,
            "max_magnitude": None,
        }
    else:
        d = existing.magnitude_distribution
        dist_values = {
            "under_2": d.under_2,
            "from_2_to_under_4": d.from_2_to_under_4,
            "from_4_to_under_5": d.from_4_to_under_5,
            "from_5_to_under_6": d.from_5_to_under_6,
            "six_or_more": d.six_or_more,
            "unknown": d.unknown,
        }
        counts = {
            "earthquake_count": existing.earthquake_count,
            "magnitude_count": existing.magnitude_count,
            "magnitude_sum": existing.magnitude_sum,
            "average_magnitude": existing.average_magnitude,
            "max_magnitude": existing.max_magnitude,
        }
    return dist_values, counts


def _classify_magnitude(magnitude: float) -> str:
    """Return the distribution field name for a known magnitude value."""
    if magnitude < 2:
        return "under_2"
    if magnitude < 4:
        return "from_2_to_under_4"
    if magnitude < 5:
        return "from_4_to_under_5"
    if magnitude < 6:
        return "from_5_to_under_6"
    return "six_or_more"


def _apply_earthquake(
    earthquake: Earthquake,
    dist_values: dict[str, int],
    counts: dict[str, object],
) -> tuple[dict[str, int], dict[str, object]]:
    """Return updated (dist_values, counts) after incorporating one earthquake.

    Neither the input dicts nor the Earthquake instance are mutated.
    """
    new_dist = dict(dist_values)
    new_counts = dict(counts)

    new_counts["earthquake_count"] = int(new_counts["earthquake_count"]) + 1

    mag = earthquake.magnitude
    if mag is None:
        new_dist["unknown"] = new_dist["unknown"] + 1
    else:
        bucket = _classify_magnitude(mag)
        new_dist[bucket] = new_dist[bucket] + 1

        new_mag_count = int(new_counts["magnitude_count"]) + 1
        new_mag_sum = float(new_counts["magnitude_sum"]) + mag  # type: ignore[arg-type]
        new_avg = new_mag_sum / new_mag_count

        prev_max = new_counts["max_magnitude"]
        new_max = mag if prev_max is None else max(float(prev_max), mag)

        new_counts["magnitude_count"] = new_mag_count
        new_counts["magnitude_sum"] = new_mag_sum
        new_counts["average_magnitude"] = new_avg
        new_counts["max_magnitude"] = new_max

    return new_dist, new_counts
