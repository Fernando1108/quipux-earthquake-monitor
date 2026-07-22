"""Unit tests for MetricsService — all I/O is mocked."""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.earthquake import Earthquake
from app.models.metric import MagnitudeDistribution, Metric
from app.services import MetricsService
from app.services.metrics_service import MetricsService as MetricsServiceDirect

# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

UTC = timezone.utc

FIXED_NOW = datetime(2024, 6, 1, 12, 30, 0, tzinfo=UTC)

# event_time sits inside the window 12:00–13:00 UTC
EVENT_TIME = datetime(2024, 6, 1, 12, 15, 0, tzinfo=UTC)
WINDOW_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)

EMPTY_DIST = MagnitudeDistribution(
    under_2=0,
    from_2_to_under_4=0,
    from_4_to_under_5=0,
    from_5_to_under_6=0,
    six_or_more=0,
    unknown=0,
)


def run(coro):
    return asyncio.run(coro)


def make_earthquake(
    magnitude: float | None = 3.5,
    event_time: datetime = EVENT_TIME,
) -> Earthquake:
    return Earthquake(
        event_id="usp000test",
        magnitude=magnitude,
        location="Test location",
        latitude=0.0,
        longitude=0.0,
        depth=10.0,
        event_time=event_time,
    )


def make_metric(
    earthquake_count: int = 0,
    magnitude_count: int = 0,
    magnitude_sum: float = 0.0,
    average_magnitude: float | None = None,
    max_magnitude: float | None = None,
    dist: MagnitudeDistribution | None = None,
) -> Metric:
    return Metric(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        earthquake_count=earthquake_count,
        magnitude_count=magnitude_count,
        magnitude_sum=magnitude_sum,
        average_magnitude=average_magnitude,
        max_magnitude=max_magnitude,
        magnitude_distribution=dist if dist is not None else EMPTY_DIST,
        updated_at=FIXED_NOW,
    )


def make_repo(existing: Metric | None = None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_window_start = AsyncMock(return_value=existing)
    repo.upsert_metric = AsyncMock()
    return repo


def make_service(
    existing: Metric | None = None,
    repo: MagicMock | None = None,
    now: datetime = FIXED_NOW,
) -> tuple[MetricsService, MagicMock]:
    r = repo if repo is not None else make_repo(existing)
    svc = MetricsService(repository=r, now_provider=lambda: now)
    return svc, r


# ---------------------------------------------------------------------------
# 1. Import check
# ---------------------------------------------------------------------------

def test_metrics_service_importable_from_app_services():
    from app.services import MetricsService as MS
    assert MS is MetricsServiceDirect


# ---------------------------------------------------------------------------
# 2-8. Constructor
# ---------------------------------------------------------------------------

def test_constructor_uses_injected_repository():
    repo = make_repo()
    svc = MetricsService(repository=repo, now_provider=lambda: FIXED_NOW)
    assert svc._repository is repo


def test_constructor_creates_metric_repository_when_none():
    with patch(
        "app.services.metrics_service.MetricRepository",
    ) as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        svc = MetricsService(repository=None, now_provider=lambda: FIXED_NOW)
        mock_cls.assert_called_once()
        assert svc._repository is mock_instance


def test_constructor_uses_injected_now_provider():
    sentinel = datetime(2099, 1, 1, 0, 0, 0, tzinfo=UTC)
    calls = []

    def provider():
        calls.append(1)
        return sentinel

    repo = make_repo()
    svc = MetricsService(repository=repo, now_provider=provider)
    repo.get_by_window_start = AsyncMock(return_value=None)
    repo.upsert_metric = AsyncMock()
    run(svc.update_for_earthquake(make_earthquake()))
    assert len(calls) == 1


def test_default_clock_returns_aware_utc_datetime():
    repo = make_repo()
    svc = MetricsService(repository=repo)
    result = svc._now_provider()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.utcoffset() is not None


def test_non_datetime_clock_raises_value_error():
    svc, _ = make_service(now=FIXED_NOW)
    svc._now_provider = lambda: "not-a-datetime"
    with pytest.raises(ValueError):
        run(svc.update_for_earthquake(make_earthquake()))


def test_naive_clock_raises_value_error():
    svc, _ = make_service()
    svc._now_provider = lambda: datetime(2024, 6, 1, 12, 30, 0)
    with pytest.raises(ValueError):
        run(svc.update_for_earthquake(make_earthquake()))


def test_aware_non_utc_clock_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    non_utc_now = datetime(2024, 6, 1, 7, 30, 0, tzinfo=eastern)  # = 12:30 UTC
    svc, repo = make_service(now=non_utc_now)
    run(svc.update_for_earthquake(make_earthquake()))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.updated_at.tzinfo == UTC
    assert saved.updated_at == FIXED_NOW


# ---------------------------------------------------------------------------
# 9-11. Hourly window calculation
# ---------------------------------------------------------------------------

def test_event_time_mapped_to_correct_window_start():
    svc, repo = make_service()
    run(svc.update_for_earthquake(make_earthquake()))
    repo.get_by_window_start.assert_awaited_once_with(WINDOW_START)


def test_window_start_has_zero_minute_second_microsecond():
    svc, repo = make_service()
    run(svc.update_for_earthquake(make_earthquake()))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.window_start.minute == 0
    assert saved.window_start.second == 0
    assert saved.window_start.microsecond == 0


def test_window_end_is_exactly_one_hour_after_start():
    svc, repo = make_service()
    run(svc.update_for_earthquake(make_earthquake()))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.window_end == saved.window_start + timedelta(hours=1)


# ---------------------------------------------------------------------------
# 12-19. Repository interaction and return value
# ---------------------------------------------------------------------------

def test_get_by_window_start_receives_exact_window_start():
    svc, repo = make_service()
    run(svc.update_for_earthquake(make_earthquake()))
    repo.get_by_window_start.assert_awaited_once_with(WINDOW_START)


def test_missing_metric_creates_new_metric():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake()))
    repo.upsert_metric.assert_awaited_once()
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert isinstance(saved, Metric)


def test_first_event_increments_earthquake_count_to_one():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake()))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.earthquake_count == 1


def test_existing_metric_increments_earthquake_count_by_one():
    existing = make_metric(
        earthquake_count=5,
        magnitude_count=5,
        magnitude_sum=15.0,
        average_magnitude=3.0,
        max_magnitude=4.5,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=5, from_4_to_under_5=0,
            from_5_to_under_6=0, six_or_more=0, unknown=0,
        ),
    )
    svc, repo = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.0)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.earthquake_count == 6


def test_upsert_metric_awaited_exactly_once():
    svc, repo = make_service()
    run(svc.update_for_earthquake(make_earthquake()))
    repo.upsert_metric.assert_awaited_once()


def test_returned_metric_is_same_object_passed_to_upsert():
    svc, repo = make_service()
    result = run(svc.update_for_earthquake(make_earthquake()))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert result is saved


def test_existing_metric_not_mutated():
    existing = make_metric(
        earthquake_count=3,
        magnitude_count=3,
        magnitude_sum=9.0,
        average_magnitude=3.0,
        max_magnitude=4.0,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=3, from_4_to_under_5=0,
            from_5_to_under_6=0, six_or_more=0, unknown=0,
        ),
    )
    original_count = existing.earthquake_count
    svc, _ = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.0)))
    assert existing.earthquake_count == original_count


def test_earthquake_not_mutated():
    eq = make_earthquake(magnitude=3.5)
    original_mag = eq.magnitude
    svc, _ = make_service()
    run(svc.update_for_earthquake(eq))
    assert eq.magnitude == original_mag


# ---------------------------------------------------------------------------
# 20-24. None magnitude behaviour
# ---------------------------------------------------------------------------

def test_none_magnitude_increments_unknown():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.magnitude_distribution.unknown == 1


def test_none_magnitude_does_not_increment_magnitude_count():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.magnitude_count == 0


def test_none_magnitude_does_not_alter_magnitude_sum():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.magnitude_sum == 0.0


def test_none_magnitude_preserves_none_average_and_max_in_unknown_only_window():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.average_magnitude is None
    assert saved.max_magnitude is None


def test_none_magnitude_preserves_existing_known_average_and_max():
    existing = make_metric(
        earthquake_count=2,
        magnitude_count=2,
        magnitude_sum=6.0,
        average_magnitude=3.0,
        max_magnitude=4.0,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=2, from_4_to_under_5=0,
            from_5_to_under_6=0, six_or_more=0, unknown=0,
        ),
    )
    svc, repo = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.average_magnitude == 3.0
    assert saved.max_magnitude == 4.0


# ---------------------------------------------------------------------------
# 25-30. Known magnitude statistics
# ---------------------------------------------------------------------------

def test_known_magnitude_increments_magnitude_count():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.5)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.magnitude_count == 1


def test_known_magnitude_adds_to_magnitude_sum():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.5)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert math.isclose(saved.magnitude_sum, 3.5)


def test_known_magnitude_recalculates_average():
    existing = make_metric(
        earthquake_count=1,
        magnitude_count=1,
        magnitude_sum=3.0,
        average_magnitude=3.0,
        max_magnitude=3.0,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=1, from_4_to_under_5=0,
            from_5_to_under_6=0, six_or_more=0, unknown=0,
        ),
    )
    svc, repo = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=5.0)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert math.isclose(saved.average_magnitude, 4.0)


def test_first_known_magnitude_establishes_max():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=4.7)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.max_magnitude == 4.7


def test_smaller_known_magnitude_preserves_existing_max():
    existing = make_metric(
        earthquake_count=1,
        magnitude_count=1,
        magnitude_sum=5.0,
        average_magnitude=5.0,
        max_magnitude=5.0,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=0, from_4_to_under_5=0,
            from_5_to_under_6=1, six_or_more=0, unknown=0,
        ),
    )
    svc, repo = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.0)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.max_magnitude == 5.0


def test_larger_known_magnitude_replaces_existing_max():
    existing = make_metric(
        earthquake_count=1,
        magnitude_count=1,
        magnitude_sum=3.0,
        average_magnitude=3.0,
        max_magnitude=3.0,
        dist=MagnitudeDistribution(
            under_2=0, from_2_to_under_4=1, from_4_to_under_5=0,
            from_5_to_under_6=0, six_or_more=0, unknown=0,
        ),
    )
    svc, repo = make_service(existing=existing)
    run(svc.update_for_earthquake(make_earthquake(magnitude=7.2)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    assert saved.max_magnitude == 7.2


# ---------------------------------------------------------------------------
# 31-41. Magnitude classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("magnitude,expected_field", [
    (-1.0,  "under_2"),
    (0.0,   "under_2"),
    (1.999, "under_2"),
    (2.0,   "from_2_to_under_4"),
    (3.999, "from_2_to_under_4"),
    (4.0,   "from_4_to_under_5"),
    (4.999, "from_4_to_under_5"),
    (5.0,   "from_5_to_under_6"),
    (5.999, "from_5_to_under_6"),
    (6.0,   "six_or_more"),
    (7.5,   "six_or_more"),
])
def test_magnitude_classified_into_correct_bucket(magnitude, expected_field):
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=magnitude)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    dist = saved.magnitude_distribution
    assert getattr(dist, expected_field) == 1


def test_exactly_one_distribution_counter_incremented_per_known_magnitude():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.5)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    d = saved.magnitude_distribution
    total_incremented = (
        d.under_2 + d.from_2_to_under_4 + d.from_4_to_under_5
        + d.from_5_to_under_6 + d.six_or_more + d.unknown
    )
    assert total_incremented == 1


def test_existing_distribution_counters_preserved():
    existing_dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=1, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=1,
    )
    existing = make_metric(
        earthquake_count=4,
        magnitude_count=3,
        magnitude_sum=3.0,
        average_magnitude=1.0,
        max_magnitude=2.0,
        dist=existing_dist,
    )
    svc, repo = make_service(existing=existing)
    # Add a 5.0 → from_5_to_under_6
    run(svc.update_for_earthquake(make_earthquake(magnitude=5.0)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    d = saved.magnitude_distribution
    assert d.under_2 == 2
    assert d.from_2_to_under_4 == 1
    assert d.unknown == 1
    assert d.from_5_to_under_6 == 1


def test_window_with_known_and_unknown_magnitudes_is_valid():
    svc, repo = make_service(existing=None)
    run(svc.update_for_earthquake(make_earthquake(magnitude=3.5)))
    saved_after_first: Metric = repo.upsert_metric.call_args[0][0]
    # Feed the saved metric back as existing to simulate second call
    repo.get_by_window_start = AsyncMock(return_value=saved_after_first)
    run(svc.update_for_earthquake(make_earthquake(magnitude=None)))
    saved: Metric = repo.upsert_metric.call_args[0][0]
    # Metric model validates internally — if this passes, the object is consistent
    assert saved.earthquake_count == 2
    assert saved.magnitude_count == 1
    assert saved.magnitude_distribution.unknown == 1


# ---------------------------------------------------------------------------
# 44-47. Error propagation and guard conditions
# ---------------------------------------------------------------------------

def test_get_by_window_start_errors_propagate():
    repo = make_repo()
    repo.get_by_window_start = AsyncMock(side_effect=Exception("db error"))
    svc = MetricsService(repository=repo, now_provider=lambda: FIXED_NOW)
    with pytest.raises(Exception, match="db error"):
        run(svc.update_for_earthquake(make_earthquake()))


def test_upsert_metric_errors_propagate():
    repo = make_repo()
    repo.upsert_metric = AsyncMock(side_effect=Exception("upsert failed"))
    svc = MetricsService(repository=repo, now_provider=lambda: FIXED_NOW)
    with pytest.raises(Exception, match="upsert failed"):
        run(svc.update_for_earthquake(make_earthquake()))


def test_upsert_not_called_when_get_fails():
    repo = make_repo()
    repo.get_by_window_start = AsyncMock(side_effect=Exception("read error"))
    svc = MetricsService(repository=repo, now_provider=lambda: FIXED_NOW)
    with pytest.raises(Exception):
        run(svc.update_for_earthquake(make_earthquake()))
    repo.upsert_metric.assert_not_awaited()


def test_upsert_not_called_when_clock_validation_fails():
    repo = make_repo()
    svc = MetricsService(repository=repo, now_provider=lambda: "bad")
    with pytest.raises(ValueError):
        run(svc.update_for_earthquake(make_earthquake()))
    repo.upsert_metric.assert_not_awaited()


# ---------------------------------------------------------------------------
# 48. Service does not access repository private attributes
# ---------------------------------------------------------------------------

def test_service_does_not_access_collection_attribute():
    repo = make_repo()
    svc = MetricsService(repository=repo, now_provider=lambda: FIXED_NOW)
    run(svc.update_for_earthquake(make_earthquake()))
    # _collection must never have been accessed on the repo mock
    assert "_collection" not in [c[0] for c in repo.method_calls]
