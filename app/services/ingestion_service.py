"""Service orchestrating the fetch-transform-store pipeline for USGS earthquake data."""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from app.clients.usgs_client import USGSClient
from app.models.earthquake import Earthquake
from app.repositories.earthquake_repository import EarthquakeRepository
from app.services.metrics_service import MetricsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Summary of one ingestion iteration."""

    fetched: int
    inserted: int
    duplicates: int
    invalid: int


# ---------------------------------------------------------------------------
# Private helpers — no I/O
# ---------------------------------------------------------------------------


def _require_dict(value: object, name: str) -> dict[str, object]:
    """Raise ValueError if value is not a dict."""
    if not isinstance(value, dict):
        raise ValueError(
            f"{name} must be a dict, got {type(value).__name__}"
        )
    return value


def _validate_finite_number(value: object, name: str) -> float:
    """Return value as float; reject bool, non-numeric, NaN, and infinity."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got bool")
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a number, got {type(value).__name__}"
        )
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    return float(value)


def _ms_to_utc(milliseconds: object) -> datetime:
    """Convert Unix epoch milliseconds to a timezone-aware UTC datetime."""
    ms = _validate_finite_number(milliseconds, "time")
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(f"USGS timestamp is invalid: {exc}") from exc


def _feature_to_earthquake(feature: dict[str, object]) -> Earthquake:
    """Transform a raw USGS GeoJSON feature dict into an Earthquake instance.

    Raises ValueError (or Pydantic ValidationError) for any malformed data.
    Does not mutate the feature dict or any nested structure.
    """
    event_id = feature.get("id")

    properties = _require_dict(feature.get("properties"), "properties")
    geometry = _require_dict(feature.get("geometry"), "geometry")

    coords = geometry.get("coordinates")
    if not isinstance(coords, list):
        raise ValueError(
            f"coordinates must be a list, got {type(coords).__name__}"
        )
    if len(coords) < 3:
        raise ValueError(
            f"coordinates must contain at least 3 entries, got {len(coords)}"
        )

    raw_time = properties.get("time")
    if raw_time is None:
        raise ValueError("properties.time is required")
    event_time = _ms_to_utc(raw_time)

    raw_mag = properties.get("mag")
    magnitude: float | None = (
        _validate_finite_number(raw_mag, "mag") if raw_mag is not None else None
    )

    longitude = _validate_finite_number(coords[0], "longitude")
    latitude = _validate_finite_number(coords[1], "latitude")
    depth = _validate_finite_number(coords[2], "depth")

    location = properties.get("place")

    return Earthquake(
        event_id=event_id,
        magnitude=magnitude,
        location=location,
        latitude=latitude,
        longitude=longitude,
        depth=depth,
        event_time=event_time,
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IngestionService:
    """Perform exactly one fetch-transform-store iteration."""

    def __init__(
        self,
        client: USGSClient | None = None,
        earthquake_repository: EarthquakeRepository | None = None,
        metrics_service: MetricsService | None = None,
    ) -> None:
        self._client = client if client is not None else USGSClient()
        self._earthquake_repository = (
            earthquake_repository
            if earthquake_repository is not None
            else EarthquakeRepository()
        )
        self._metrics_service = (
            metrics_service
            if metrics_service is not None
            else MetricsService()
        )

    async def run_once(self) -> IngestionResult:
        """Fetch USGS features, insert new events, and update metrics.

        Returns an IngestionResult summarising the iteration.
        Fetch, repository, and metrics errors propagate to the caller.
        """
        features = await self._client.fetch_features()
        fetched = len(features)
        inserted = 0
        duplicates = 0
        invalid = 0

        for index, feature in enumerate(features):
            try:
                earthquake = _feature_to_earthquake(feature)
            except (ValueError, ValidationError) as exc:
                logger.warning(
                    "Feature at index %d is invalid and will be skipped: %s",
                    index,
                    exc,
                )
                invalid += 1
                continue

            is_new = await self._earthquake_repository.insert_if_new(earthquake)
            if not is_new:
                duplicates += 1
                continue

            await self._metrics_service.update_for_earthquake(earthquake)
            inserted += 1

        logger.info(
            "Ingestion complete: fetched=%d inserted=%d duplicates=%d invalid=%d",
            fetched,
            inserted,
            duplicates,
            invalid,
        )

        return IngestionResult(
            fetched=fetched,
            inserted=inserted,
            duplicates=duplicates,
            invalid=invalid,
        )
