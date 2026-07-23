"""Unit tests for ReportingService — all I/O is mocked."""

import asyncio
import inspect
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.earthquake import Earthquake
from app.models.report import Report, TopLocation
from app.repositories.earthquake_repository import EarthquakeRepository
from app.repositories.report_repository import ReportRepository
from app.services import IngestionResult, IngestionService, MetricsService, ReportingService
from app.services.reporting_service import (
    TOP_LOCATIONS_LIMIT,
    ReportingService as ReportingServiceDirect,
    _magnitude_summary,
    _top_locations,
    _utc_now,
    _validated_report_date,
    _validated_utc_now,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UTC = timezone.utc
OFFSET_PLUS_5 = timezone(timedelta(hours=5))

REPORT_DATE = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
PERIOD_START = REPORT_DATE - timedelta(hours=1)
GENERATED_AT = REPORT_DATE + timedelta(seconds=10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


_EQ_COUNTER = 0


def make_earthquake(
    event_id: str | None = None,
    magnitude: float | None = 3.5,
    location: str | None = "California",
    event_time: datetime | None = None,
) -> Earthquake:
    global _EQ_COUNTER
    _EQ_COUNTER += 1
    return Earthquake(
        event_id=event_id or f"us700test{_EQ_COUNTER:04d}",
        magnitude=magnitude,
        location=location,
        latitude=35.0,
        longitude=-120.0,
        depth=10.0,
        event_time=event_time or PERIOD_START + timedelta(minutes=30),
    )


def make_earthquake_repository(earthquakes=None) -> AsyncMock:
    repo = AsyncMock(spec=EarthquakeRepository)
    repo.find_by_time_range = AsyncMock(return_value=earthquakes or [])
    return repo


def make_report_repository() -> AsyncMock:
    repo = AsyncMock(spec=ReportRepository)
    repo.upsert_report = AsyncMock(return_value=None)
    return repo


def make_service(
    earthquakes=None,
    eq_repo=None,
    rep_repo=None,
    now_provider=None,
):
    eq_repo = eq_repo or make_earthquake_repository(earthquakes)
    rep_repo = rep_repo or make_report_repository()
    provider = now_provider or (lambda: GENERATED_AT)
    return ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=provider,
    ), eq_repo, rep_repo


# ---------------------------------------------------------------------------
# A. Public exports and contract
# ---------------------------------------------------------------------------


def test_reporting_service_importable_from_app_services():
    from app.services import ReportingService as RS
    assert RS is not None


def test_package_export_is_same_class_as_direct_import():
    from app.services import ReportingService as RS
    assert RS is ReportingServiceDirect


def test_ingestion_result_remains_exported():
    from app.services import IngestionResult
    assert IngestionResult is not None


def test_ingestion_service_remains_exported():
    from app.services import IngestionService
    assert IngestionService is not None


def test_metrics_service_remains_exported():
    from app.services import MetricsService
    assert MetricsService is not None


def test_all_contains_exactly_four_names():
    import app.services as mod
    assert set(mod.__all__) == {
        "IngestionResult",
        "IngestionService",
        "MetricsService",
        "ReportingService",
    }
    assert len(mod.__all__) == 4


def test_top_locations_limit_equals_3():
    assert TOP_LOCATIONS_LIMIT == 3


def test_generate_hourly_report_annotations():
    hints = get_type_hints(ReportingService.generate_hourly_report)
    assert hints["report_date"] is datetime
    assert hints["return"] is Report


# ---------------------------------------------------------------------------
# B. Constructor
# ---------------------------------------------------------------------------


def test_constructor_preserves_injected_earthquake_repository():
    eq_repo = make_earthquake_repository()
    svc = ReportingService(earthquake_repository=eq_repo, report_repository=make_report_repository())
    assert svc._earthquake_repository is eq_repo


def test_constructor_preserves_injected_report_repository():
    rep_repo = make_report_repository()
    svc = ReportingService(earthquake_repository=make_earthquake_repository(), report_repository=rep_repo)
    assert svc._report_repository is rep_repo


def test_constructor_preserves_injected_now_provider():
    provider = lambda: GENERATED_AT
    svc = ReportingService(earthquake_repository=make_earthquake_repository(), report_repository=make_report_repository(), now_provider=provider)
    assert svc._now_provider is provider


def test_constructor_creates_earthquake_repository_when_missing():
    with patch("app.services.reporting_service.EarthquakeRepository") as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = ReportingService(report_repository=make_report_repository())
        mock_cls.assert_called_once_with()
        assert svc._earthquake_repository is mock_cls.return_value


def test_constructor_creates_report_repository_when_missing():
    with patch("app.services.reporting_service.ReportRepository") as mock_cls:
        mock_cls.return_value = MagicMock()
        svc = ReportingService(earthquake_repository=make_earthquake_repository())
        mock_cls.assert_called_once_with()
        assert svc._report_repository is mock_cls.return_value


def test_constructor_default_clock_is_utc_now():
    svc = ReportingService(
        earthquake_repository=make_earthquake_repository(),
        report_repository=make_report_repository(),
    )
    assert svc._now_provider is _utc_now


def test_constructor_performs_no_repository_reads():
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    ReportingService(earthquake_repository=eq_repo, report_repository=rep_repo)
    eq_repo.find_by_time_range.assert_not_awaited()
    rep_repo.upsert_report.assert_not_awaited()


def test_constructor_performs_no_repository_writes():
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    ReportingService(earthquake_repository=eq_repo, report_repository=rep_repo)
    rep_repo.upsert_report.assert_not_awaited()


# ---------------------------------------------------------------------------
# C. report_date validation
# ---------------------------------------------------------------------------


def test_validated_report_date_rejects_none():
    with pytest.raises(ValueError):
        _validated_report_date(None)


def test_validated_report_date_rejects_string():
    with pytest.raises(ValueError):
        _validated_report_date("2024-06-01T13:00:00Z")


def test_validated_report_date_rejects_integer():
    with pytest.raises(ValueError):
        _validated_report_date(1717250400)


def test_validated_report_date_rejects_float():
    with pytest.raises(ValueError):
        _validated_report_date(1717250400.0)


def test_validated_report_date_rejects_boolean():
    with pytest.raises(ValueError):
        _validated_report_date(True)


def test_validated_report_date_rejects_list():
    with pytest.raises(ValueError):
        _validated_report_date([REPORT_DATE])


def test_validated_report_date_rejects_dict():
    with pytest.raises(ValueError):
        _validated_report_date({"dt": REPORT_DATE})


def test_validated_report_date_rejects_naive():
    with pytest.raises(ValueError):
        _validated_report_date(datetime(2024, 6, 1, 13, 0, 0))


def test_validated_report_date_rejects_non_zero_minute():
    with pytest.raises(ValueError):
        _validated_report_date(datetime(2024, 6, 1, 13, 30, 0, tzinfo=UTC))


def test_validated_report_date_rejects_non_zero_second():
    with pytest.raises(ValueError):
        _validated_report_date(datetime(2024, 6, 1, 13, 0, 1, tzinfo=UTC))


def test_validated_report_date_rejects_non_zero_microsecond():
    with pytest.raises(ValueError):
        _validated_report_date(datetime(2024, 6, 1, 13, 0, 0, 1, tzinfo=UTC))


def test_validated_report_date_rejects_aware_that_misaligns_after_utc_normalization():
    # +05:00 offset, 10:30 local → 05:30 UTC → not aligned
    dt = datetime(2024, 6, 1, 10, 30, 0, tzinfo=OFFSET_PLUS_5)
    with pytest.raises(ValueError):
        _validated_report_date(dt)


def test_validated_report_date_accepts_exact_utc_hour():
    result = _validated_report_date(REPORT_DATE)
    assert result == REPORT_DATE


def test_validated_report_date_accepts_aware_non_utc_representing_exact_utc_hour():
    # 18:00+05:00 → 13:00 UTC = REPORT_DATE
    dt = datetime(2024, 6, 1, 18, 0, 0, tzinfo=OFFSET_PLUS_5)
    result = _validated_report_date(dt)
    assert result == REPORT_DATE
    assert result.tzinfo == UTC


def test_validated_report_date_accepts_historical_exact_hour():
    historical = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = _validated_report_date(historical)
    assert result == historical


def test_validated_report_date_normalizes_to_utc():
    dt = datetime(2024, 6, 1, 18, 0, 0, tzinfo=OFFSET_PLUS_5)
    result = _validated_report_date(dt)
    assert result.tzinfo == UTC
    assert result == REPORT_DATE


# ---------------------------------------------------------------------------
# D. Clock
# ---------------------------------------------------------------------------


def test_utc_now_returns_aware_utc():
    result = _utc_now()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    assert result.utcoffset() is not None


def test_validated_utc_now_calls_provider_exactly_once():
    provider = MagicMock(return_value=GENERATED_AT)
    _validated_utc_now(provider)
    provider.assert_called_once_with()


def test_validated_utc_now_non_datetime_raises():
    with pytest.raises(ValueError):
        _validated_utc_now(lambda: "not-a-datetime")


def test_validated_utc_now_naive_datetime_raises():
    with pytest.raises(ValueError):
        _validated_utc_now(lambda: datetime(2024, 6, 1, 12, 0, 0))


def test_validated_utc_now_aware_non_utc_normalizes_to_utc():
    non_utc = datetime(2024, 6, 1, 18, 0, 10, tzinfo=OFFSET_PLUS_5)  # = GENERATED_AT
    result = _validated_utc_now(lambda: non_utc)
    assert result.tzinfo == UTC
    assert result == GENERATED_AT


def test_validated_utc_now_provider_exception_propagates():
    def bad_provider():
        raise RuntimeError("clock failure")
    with pytest.raises(RuntimeError, match="clock failure"):
        _validated_utc_now(bad_provider)


def test_invalid_clock_prevents_both_repository_calls():
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: "bad",
    )
    with pytest.raises(ValueError):
        run(svc.generate_hourly_report(REPORT_DATE))
    eq_repo.find_by_time_range.assert_not_awaited()
    rep_repo.upsert_report.assert_not_awaited()


# ---------------------------------------------------------------------------
# E. Closed-hour rule
# ---------------------------------------------------------------------------


def test_future_report_date_is_rejected():
    future = GENERATED_AT + timedelta(hours=1)
    # round to hour boundary
    future_hour = future.replace(minute=0, second=0, microsecond=0)
    svc, eq_repo, rep_repo = make_service(now_provider=lambda: GENERATED_AT)
    with pytest.raises(ValueError):
        run(svc.generate_hourly_report(future_hour))


def test_report_date_equal_to_generated_at_is_accepted():
    exact_now = datetime(2024, 6, 1, 14, 0, 0, tzinfo=UTC)
    svc, eq_repo, rep_repo = make_service(now_provider=lambda: exact_now)
    report = run(svc.generate_hourly_report(exact_now))
    assert isinstance(report, Report)


def test_historical_report_date_is_accepted():
    historical = datetime(2020, 1, 1, 6, 0, 0, tzinfo=UTC)
    svc, _, _ = make_service(now_provider=lambda: GENERATED_AT)
    report = run(svc.generate_hourly_report(historical))
    assert isinstance(report, Report)


def test_future_rejection_occurs_before_repository_read():
    future_hour = GENERATED_AT.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    svc, eq_repo, rep_repo = make_service(now_provider=lambda: GENERATED_AT)
    with pytest.raises(ValueError):
        run(svc.generate_hourly_report(future_hour))
    eq_repo.find_by_time_range.assert_not_awaited()


def test_future_rejection_occurs_before_repository_write():
    future_hour = GENERATED_AT.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    svc, eq_repo, rep_repo = make_service(now_provider=lambda: GENERATED_AT)
    with pytest.raises(ValueError):
        run(svc.generate_hourly_report(future_hour))
    rep_repo.upsert_report.assert_not_awaited()


# ---------------------------------------------------------------------------
# F. Time window and earthquake read
# ---------------------------------------------------------------------------


def test_period_end_equals_normalized_report_date():
    svc, eq_repo, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.period_end == REPORT_DATE


def test_period_start_is_one_hour_before_report_date():
    svc, eq_repo, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.period_start == PERIOD_START


def test_find_by_time_range_awaited_exactly_once():
    svc, eq_repo, _ = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    eq_repo.find_by_time_range.assert_awaited_once()


def test_find_by_time_range_receives_period_start_then_period_end():
    svc, eq_repo, _ = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    args = eq_repo.find_by_time_range.call_args[0]
    assert args[0] == PERIOD_START
    assert args[1] == REPORT_DATE


def test_non_utc_report_date_produces_normalized_utc_query_bounds():
    # 18:00+05:00 → 13:00 UTC = REPORT_DATE; period_start = 12:00 UTC
    non_utc = datetime(2024, 6, 1, 18, 0, 0, tzinfo=OFFSET_PLUS_5)
    svc, eq_repo, _ = make_service()
    run(svc.generate_hourly_report(non_utc))
    args = eq_repo.find_by_time_range.call_args[0]
    assert args[0] == PERIOD_START
    assert args[0].tzinfo == UTC
    assert args[1] == REPORT_DATE
    assert args[1].tzinfo == UTC


def test_no_paginated_list_method_called():
    svc, eq_repo, _ = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    assert not hasattr(eq_repo, "list_earthquakes") or not eq_repo.list_earthquakes.called


def test_report_repository_not_read_before_generation():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    assert not hasattr(rep_repo, "get_by_report_date") or \
        not rep_repo.get_by_report_date.called
    assert not hasattr(rep_repo, "list_reports") or \
        not rep_repo.list_reports.called


# ---------------------------------------------------------------------------
# G. Empty hour
# ---------------------------------------------------------------------------


def test_empty_hour_total_events_is_zero():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.total_events == 0


def test_empty_hour_events_with_magnitude_is_zero():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.events_with_magnitude == 0


def test_empty_hour_average_magnitude_is_none():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.average_magnitude is None


def test_empty_hour_max_magnitude_is_none():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.max_magnitude is None


def test_empty_hour_top_locations_is_empty():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.top_locations == []


def test_empty_hour_report_is_persisted():
    svc, _, rep_repo = make_service(earthquakes=[])
    run(svc.generate_hourly_report(REPORT_DATE))
    rep_repo.upsert_report.assert_awaited_once()


def test_empty_hour_report_is_returned():
    svc, _, _ = make_service(earthquakes=[])
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert isinstance(report, Report)
    assert report.total_events == 0


# ---------------------------------------------------------------------------
# H. Magnitude statistics
# ---------------------------------------------------------------------------


def test_magnitude_summary_one_known():
    eqs = [make_earthquake(magnitude=3.0)]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 1
    assert avg == pytest.approx(3.0)
    assert maximum == pytest.approx(3.0)


def test_magnitude_summary_multiple_known():
    eqs = [make_earthquake(magnitude=2.0), make_earthquake(magnitude=4.0)]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 2
    assert avg == pytest.approx(3.0)
    assert maximum == pytest.approx(4.0)


def test_magnitude_summary_mixed_known_and_none():
    eqs = [
        make_earthquake(magnitude=2.0),
        make_earthquake(magnitude=None),
        make_earthquake(magnitude=4.0),
    ]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 2
    assert avg == pytest.approx(3.0)
    assert maximum == pytest.approx(4.0)


def test_magnitude_summary_all_none():
    eqs = [make_earthquake(magnitude=None), make_earthquake(magnitude=None)]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 0
    assert avg is None
    assert maximum is None


def test_magnitude_summary_zero_magnitude_included():
    eqs = [make_earthquake(magnitude=0.0)]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 1
    assert avg == pytest.approx(0.0)
    assert maximum == pytest.approx(0.0)


def test_magnitude_summary_negative_magnitude_included():
    eqs = [make_earthquake(magnitude=-1.5), make_earthquake(magnitude=0.5)]
    count, avg, maximum = _magnitude_summary(eqs)
    assert count == 2
    assert avg == pytest.approx(-0.5)
    assert maximum == pytest.approx(0.5)


def test_magnitude_summary_average_is_exact_not_rounded():
    eqs = [
        make_earthquake(magnitude=1.0),
        make_earthquake(magnitude=2.0),
        make_earthquake(magnitude=3.0),
    ]
    count, avg, _ = _magnitude_summary(eqs)
    assert count == 3
    assert avg == pytest.approx(2.0)


def test_magnitude_summary_maximum_is_correct():
    eqs = [
        make_earthquake(magnitude=1.0),
        make_earthquake(magnitude=5.5),
        make_earthquake(magnitude=3.0),
    ]
    _, _, maximum = _magnitude_summary(eqs)
    assert maximum == pytest.approx(5.5)


def test_magnitude_summary_counts_only_non_none():
    eqs = [
        make_earthquake(magnitude=None),
        make_earthquake(magnitude=3.0),
        make_earthquake(magnitude=None),
    ]
    count, _, _ = _magnitude_summary(eqs)
    assert count == 1


def test_magnitude_summary_order_does_not_alter_result():
    eqs_a = [make_earthquake(magnitude=1.0), make_earthquake(magnitude=3.0)]
    eqs_b = [make_earthquake(magnitude=3.0), make_earthquake(magnitude=1.0)]
    ca, aa, ma = _magnitude_summary(eqs_a)
    cb, ab, mb = _magnitude_summary(eqs_b)
    assert ca == cb
    assert aa == pytest.approx(ab)
    assert ma == pytest.approx(mb)


def test_magnitude_summary_does_not_mutate_earthquakes():
    eq = make_earthquake(magnitude=3.0)
    original_mag = eq.magnitude
    _magnitude_summary([eq])
    assert eq.magnitude == original_mag


def test_non_finite_magnitudes_cause_validation_error_in_service():
    svc, _, rep_repo = make_service(
        earthquakes=[make_earthquake(magnitude=float("nan"))]
    )
    with pytest.raises(Exception):
        run(svc.generate_hourly_report(REPORT_DATE))


def test_upsert_not_called_after_report_validation_failure():
    svc, _, rep_repo = make_service(
        earthquakes=[make_earthquake(magnitude=float("inf"))]
    )
    with pytest.raises(Exception):
        run(svc.generate_hourly_report(REPORT_DATE))
    rep_repo.upsert_report.assert_not_awaited()


# ---------------------------------------------------------------------------
# I. Top locations
# ---------------------------------------------------------------------------


def test_top_locations_no_earthquakes_returns_empty():
    result = _top_locations([])
    assert result == []


def test_top_locations_all_none_location_returns_empty():
    eqs = [make_earthquake(location=None), make_earthquake(location=None)]
    assert _top_locations(eqs) == []


def test_top_locations_one_location_counted():
    eqs = [make_earthquake(location="California")]
    result = _top_locations(eqs)
    assert len(result) == 1
    assert result[0].location == "California"
    assert result[0].count == 1


def test_top_locations_repeated_location_counted():
    eqs = [make_earthquake(location="California"), make_earthquake(location="California")]
    result = _top_locations(eqs)
    assert result[0].count == 2


def test_top_locations_multiple_locations_counted_independently():
    eqs = [
        make_earthquake(location="California"),
        make_earthquake(location="Nevada"),
        make_earthquake(location="California"),
    ]
    result = _top_locations(eqs)
    locs = {r.location: r.count for r in result}
    assert locs["California"] == 2
    assert locs["Nevada"] == 1


def test_top_locations_none_location_ignored():
    eqs = [
        make_earthquake(location="California"),
        make_earthquake(location=None),
    ]
    result = _top_locations(eqs)
    assert all(r.location is not None for r in result)
    assert len(result) == 1


def test_top_locations_max_length_is_3():
    eqs = [make_earthquake(location=f"Loc{i}") for i in range(10)]
    result = _top_locations(eqs)
    assert len(result) <= 3


def test_top_locations_more_than_limit_truncated():
    eqs = [
        make_earthquake(location="A"),
        make_earthquake(location="A"),
        make_earthquake(location="B"),
        make_earthquake(location="B"),
        make_earthquake(location="C"),
        make_earthquake(location="D"),
    ]
    result = _top_locations(eqs)
    assert len(result) == 3


def test_top_locations_highest_counts_come_first():
    eqs = [
        make_earthquake(location="Nevada"),
        make_earthquake(location="California"),
        make_earthquake(location="California"),
    ]
    result = _top_locations(eqs)
    assert result[0].location == "California"
    assert result[0].count == 2


def test_top_locations_equal_counts_ordered_alphabetically():
    eqs = [
        make_earthquake(location="Nevada"),
        make_earthquake(location="Alaska"),
        make_earthquake(location="California"),
    ]
    result = _top_locations(eqs)
    # All count=1, sorted alphabetically
    assert result[0].location == "Alaska"
    assert result[1].location == "California"
    assert result[2].location == "Nevada"


def test_top_locations_tie_order_not_dependent_on_input_order():
    eqs_a = [
        make_earthquake(location="Nevada"),
        make_earthquake(location="Alaska"),
    ]
    eqs_b = [
        make_earthquake(location="Alaska"),
        make_earthquake(location="Nevada"),
    ]
    result_a = _top_locations(eqs_a)
    result_b = _top_locations(eqs_b)
    assert [r.location for r in result_a] == [r.location for r in result_b]


def test_top_locations_case_sensitive():
    eqs = [
        make_earthquake(location="California"),
        make_earthquake(location="california"),
    ]
    result = _top_locations(eqs)
    locations = {r.location for r in result}
    assert "California" in locations
    assert "california" in locations


def test_top_locations_preserves_original_case():
    eqs = [make_earthquake(location="NEW MEXICO")]
    result = _top_locations(eqs)
    assert result[0].location == "NEW MEXICO"


def test_top_locations_no_unknown_synthesized():
    eqs = [make_earthquake(location=None)]
    result = _top_locations(eqs)
    assert not any(r.location.lower() == "unknown" for r in result)


def test_top_locations_returns_toplocation_objects():
    eqs = [make_earthquake(location="California")]
    result = _top_locations(eqs)
    for item in result:
        assert isinstance(item, TopLocation)


def test_top_locations_counts_sum_lte_total_events():
    eqs = [
        make_earthquake(location="California"),
        make_earthquake(location=None),
        make_earthquake(location="Nevada"),
    ]
    result = _top_locations(eqs)
    assert sum(r.count for r in result) <= len(eqs)


def test_top_locations_does_not_mutate_earthquakes():
    eqs = [make_earthquake(location="California")]
    original_loc = eqs[0].location
    _top_locations(eqs)
    assert eqs[0].location == original_loc


def test_top_locations_limit_used_in_generation_flow():
    # Use TOP_LOCATIONS_LIMIT+1 distinct locations, all with equal count
    eqs = [make_earthquake(location=f"Loc{i}") for i in range(TOP_LOCATIONS_LIMIT + 1)]
    svc, _, _ = make_service(earthquakes=eqs)
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert len(report.top_locations) <= TOP_LOCATIONS_LIMIT


# ---------------------------------------------------------------------------
# J. Report construction
# ---------------------------------------------------------------------------


def test_report_date_is_normalized_period_end():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.report_date == REPORT_DATE


def test_period_start_is_exactly_one_hour_before():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.period_start == REPORT_DATE - timedelta(hours=1)


def test_generated_at_is_normalized_clock_result():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.generated_at == GENERATED_AT


def test_total_events_equals_len_earthquakes():
    eqs = [make_earthquake() for _ in range(5)]
    svc, _, _ = make_service(earthquakes=eqs)
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert report.total_events == 5


def test_returned_object_is_report():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert isinstance(report, Report)


def test_nested_locations_are_toplocation():
    eqs = [make_earthquake(location="California")]
    svc, _, _ = make_service(earthquakes=eqs)
    report = run(svc.generate_hourly_report(REPORT_DATE))
    for item in report.top_locations:
        assert isinstance(item, TopLocation)


def test_report_is_internally_valid():
    eqs = [make_earthquake(magnitude=3.0, location="California")]
    svc, _, _ = make_service(earthquakes=eqs)
    report = run(svc.generate_hourly_report(REPORT_DATE))
    # If we got here without ValidationError, the report is valid
    assert isinstance(report, Report)


def test_report_model_dump_has_exactly_nine_keys():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    expected = {
        "report_date", "period_start", "period_end", "total_events",
        "events_with_magnitude", "average_magnitude", "max_magnitude",
        "top_locations", "generated_at",
    }
    assert set(report.model_dump().keys()) == expected


def test_service_does_not_call_model_dump():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    received = rep_repo.upsert_report.call_args[0][0]
    assert isinstance(received, Report)


def test_service_does_not_build_persistence_dict():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    received = rep_repo.upsert_report.call_args[0][0]
    assert not isinstance(received, dict)


# ---------------------------------------------------------------------------
# K. Persistence and return value
# ---------------------------------------------------------------------------


def test_upsert_report_awaited_exactly_once():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    rep_repo.upsert_report.assert_awaited_once()


def test_upsert_report_receives_report():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    received = rep_repo.upsert_report.call_args[0][0]
    assert isinstance(received, Report)


def test_returned_object_is_same_instance_passed_to_upsert():
    svc, _, rep_repo = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    passed = rep_repo.upsert_report.call_args[0][0]
    assert report is passed


def test_get_by_report_date_not_called():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    if hasattr(rep_repo, "get_by_report_date"):
        rep_repo.get_by_report_date.assert_not_awaited()


def test_list_reports_not_called():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    if hasattr(rep_repo, "list_reports"):
        rep_repo.list_reports.assert_not_awaited()


def test_repeated_generation_calls_upsert_each_time():
    svc, _, rep_repo = make_service()
    run(svc.generate_hourly_report(REPORT_DATE))
    run(svc.generate_hourly_report(REPORT_DATE))
    assert rep_repo.upsert_report.await_count == 2


def test_service_performs_no_direct_collection_access():
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    run(svc.generate_hourly_report(REPORT_DATE))
    assert not hasattr(svc, "_collection")


# ---------------------------------------------------------------------------
# L. Logging
# ---------------------------------------------------------------------------


def test_exactly_one_info_log_after_success(caplog):
    svc, _, _ = make_service()
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        run(svc.generate_hourly_report(REPORT_DATE))
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1


def test_success_log_contains_report_date(caplog):
    svc, _, _ = make_service()
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        run(svc.generate_hourly_report(REPORT_DATE))
    assert any(REPORT_DATE.isoformat() in r.message for r in caplog.records)


def test_success_log_contains_total_events(caplog):
    eqs = [make_earthquake(), make_earthquake()]
    svc, _, _ = make_service(earthquakes=eqs)
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        run(svc.generate_hourly_report(REPORT_DATE))
    assert any("2" in r.message for r in caplog.records if r.levelname == "INFO")


def test_success_log_contains_events_with_magnitude(caplog):
    eqs = [make_earthquake(magnitude=3.0), make_earthquake(magnitude=None)]
    svc, _, _ = make_service(earthquakes=eqs)
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        run(svc.generate_hourly_report(REPORT_DATE))
    assert any("events_with_magnitude=1" in r.message for r in caplog.records)


def test_success_log_contains_top_locations_count(caplog):
    eqs = [make_earthquake(location="California")]
    svc, _, _ = make_service(earthquakes=eqs)
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        run(svc.generate_hourly_report(REPORT_DATE))
    assert any("top_locations=1" in r.message for r in caplog.records)


def test_no_success_log_when_earthquake_read_fails(caplog):
    eq_repo = make_earthquake_repository()
    eq_repo.find_by_time_range = AsyncMock(side_effect=Exception("read failed"))
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        with pytest.raises(Exception, match="read failed"):
            run(svc.generate_hourly_report(REPORT_DATE))
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 0


def test_no_success_log_when_report_validation_fails(caplog):
    svc, _, rep_repo = make_service(
        earthquakes=[make_earthquake(magnitude=float("nan"))]
    )
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        with pytest.raises(Exception):
            run(svc.generate_hourly_report(REPORT_DATE))
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 0


def test_no_success_log_when_upsert_fails(caplog):
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    rep_repo.upsert_report = AsyncMock(side_effect=Exception("write failed"))
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with caplog.at_level(logging.INFO, logger="app.services.reporting_service"):
        with pytest.raises(Exception, match="write failed"):
            run(svc.generate_hourly_report(REPORT_DATE))
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 0


# ---------------------------------------------------------------------------
# M. Error propagation
# ---------------------------------------------------------------------------


def test_find_by_time_range_error_propagates():
    eq_repo = make_earthquake_repository()
    eq_repo.find_by_time_range = AsyncMock(side_effect=RuntimeError("db down"))
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with pytest.raises(RuntimeError, match="db down"):
        run(svc.generate_hourly_report(REPORT_DATE))


def test_upsert_not_called_when_find_fails():
    eq_repo = make_earthquake_repository()
    eq_repo.find_by_time_range = AsyncMock(side_effect=RuntimeError("db down"))
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with pytest.raises(RuntimeError):
        run(svc.generate_hourly_report(REPORT_DATE))
    rep_repo.upsert_report.assert_not_awaited()


def test_upsert_error_propagates():
    eq_repo = make_earthquake_repository()
    rep_repo = make_report_repository()
    rep_repo.upsert_report = AsyncMock(side_effect=RuntimeError("write failed"))
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with pytest.raises(RuntimeError, match="write failed"):
        run(svc.generate_hourly_report(REPORT_DATE))


def test_report_validation_error_propagates():
    from pydantic import ValidationError as PydanticValidationError
    svc, _, rep_repo = make_service(
        earthquakes=[make_earthquake(magnitude=float("nan"))]
    )
    with pytest.raises(Exception):
        run(svc.generate_hourly_report(REPORT_DATE))


def test_clock_validation_error_propagates():
    svc, _, _ = make_service(now_provider=lambda: "not-a-datetime")
    with pytest.raises(ValueError):
        run(svc.generate_hourly_report(REPORT_DATE))


def test_no_exception_silently_converted_to_empty_report():
    eq_repo = make_earthquake_repository()
    eq_repo.find_by_time_range = AsyncMock(side_effect=RuntimeError("fatal"))
    rep_repo = make_report_repository()
    svc = ReportingService(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
        now_provider=lambda: GENERATED_AT,
    )
    with pytest.raises(RuntimeError):
        run(svc.generate_hourly_report(REPORT_DATE))


# ---------------------------------------------------------------------------
# N. Architecture regression
# ---------------------------------------------------------------------------


def test_service_does_not_import_airflow():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "airflow" not in source.lower()


def test_service_does_not_import_fastapi():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "fastapi" not in source.lower()


def test_service_does_not_import_motor():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "motor" not in source.lower()


def test_service_does_not_import_pymongo():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "pymongo" not in source.lower()


def test_service_does_not_import_get_database():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "get_database" not in source


def test_service_does_not_create_indexes():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "create_index" not in source
    assert "ensure_index" not in source


def test_service_does_not_access_collection():
    svc, _, _ = make_service()
    report = run(svc.generate_hourly_report(REPORT_DATE))
    assert not hasattr(svc, "_collection")


def test_service_contains_no_aggregation_pipeline():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "aggregate" not in source


def test_service_does_not_import_private_metrics_helpers():
    import app.services.reporting_service as mod
    source = inspect.getsource(mod)
    assert "_extract_state" not in source
    assert "_apply_earthquake" not in source
    assert "_classify_magnitude" not in source
    assert "_hourly_window" not in source


def test_existing_metrics_service_remains_usable():
    from app.services import MetricsService
    assert MetricsService is not None
    svc = MetricsService.__new__(MetricsService)
    assert isinstance(svc, MetricsService)


def test_existing_ingestion_service_remains_usable():
    from app.services import IngestionService
    assert IngestionService is not None
    assert isinstance(IngestionService, type)
