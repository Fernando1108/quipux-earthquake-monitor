"""Unit tests for app/api/schemas.py — pure unit tests, no DB or HTTP."""

import math
from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from app.api.schemas import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    BaseListQueryParams,
    EarthquakeQueryParams,
    MetricQueryParams,
    ReportQueryParams,
    PaginatedResponse,
    SortOrder,
    build_paginated_response,
)
from app.config.settings import Settings
from app.models.earthquake import Earthquake

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
FIXED_TIME = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
LATER_TIME = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)


def make_earthquake(**overrides) -> Earthquake:
    defaults = dict(
        event_id="us7000test",
        magnitude=3.5,
        location="Test location",
        latitude=35.0,
        longitude=-100.0,
        depth=10.0,
        event_time=FIXED_TIME,
    )
    defaults.update(overrides)
    return Earthquake(**defaults)


# ---------------------------------------------------------------------------
# A. Settings-derived pagination
# ---------------------------------------------------------------------------


def test_default_page_size_matches_settings():
    assert DEFAULT_PAGE_SIZE == Settings().default_page_size


def test_max_page_size_matches_settings():
    assert MAX_PAGE_SIZE == Settings().max_page_size


def test_base_query_default_page_is_1():
    params = BaseListQueryParams()
    assert params.page == 1


def test_base_query_default_page_size_is_settings_value():
    params = BaseListQueryParams()
    assert params.page_size == DEFAULT_PAGE_SIZE


def test_base_query_default_sort_is_desc():
    params = BaseListQueryParams()
    assert params.sort is SortOrder.DESC


# ---------------------------------------------------------------------------
# B. Pagination validation
# ---------------------------------------------------------------------------


def test_positive_page_and_page_size_accepted():
    params = BaseListQueryParams(page=2, page_size=10)
    assert params.page == 2
    assert params.page_size == 10


def test_page_zero_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page=0)


def test_negative_page_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page=-1)


def test_page_size_zero_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page_size=0)


def test_negative_page_size_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page_size=-1)


def test_page_size_above_max_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page_size=MAX_PAGE_SIZE + 1)


def test_string_integer_page_is_parsed():
    params = BaseListQueryParams(page="3")
    assert params.page == 3


def test_string_integer_page_size_is_parsed():
    params = BaseListQueryParams(page_size="5")
    assert params.page_size == 5


def test_bool_page_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page=True)


def test_bool_page_size_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(page_size=False)


def test_extra_query_field_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(unknown_param="value")


# ---------------------------------------------------------------------------
# C. Sort order
# ---------------------------------------------------------------------------


def test_asc_string_becomes_sort_asc():
    params = BaseListQueryParams(sort="asc")
    assert params.sort is SortOrder.ASC


def test_desc_string_becomes_sort_desc():
    params = BaseListQueryParams(sort="desc")
    assert params.sort is SortOrder.DESC


def test_invalid_sort_value_rejected():
    with pytest.raises(ValidationError):
        BaseListQueryParams(sort="ascending")


def test_sort_descending_true_for_desc():
    params = BaseListQueryParams(sort=SortOrder.DESC)
    assert params.sort_descending is True


def test_sort_descending_false_for_asc():
    params = BaseListQueryParams(sort=SortOrder.ASC)
    assert params.sort_descending is False


def test_sort_descending_not_in_model_dump():
    params = BaseListQueryParams()
    dumped = params.model_dump()
    assert "sort_descending" not in dumped


# ---------------------------------------------------------------------------
# D. Datetime validation
# ---------------------------------------------------------------------------


def test_utc_aware_datetime_accepted():
    params = EarthquakeQueryParams(start_time=FIXED_TIME)
    assert params.start_time == FIXED_TIME


def test_offset_aware_datetime_normalized_to_utc():
    offset = timezone(timedelta(hours=5))
    dt = datetime(2024, 6, 1, 17, 0, 0, tzinfo=offset)  # same instant as 12:00 UTC
    params = EarthquakeQueryParams(start_time=dt)
    assert params.start_time == FIXED_TIME
    assert params.start_time.tzinfo == UTC


def test_naive_start_time_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(start_time=datetime(2024, 6, 1, 12, 0, 0))


def test_naive_end_time_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(end_time=datetime(2024, 6, 1, 12, 0, 0))


def test_tzinfo_with_none_utcoffset_rejected():
    import datetime as dt_module

    class NullOffsetTZ(dt_module.tzinfo):
        def utcoffset(self, dt):
            return None
        def tzname(self, dt):
            return "NULL"
        def dst(self, dt):
            return None

    bad_dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=NullOffsetTZ())
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(start_time=bad_dt)


def test_start_before_end_accepted():
    params = EarthquakeQueryParams(start_time=FIXED_TIME, end_time=LATER_TIME)
    assert params.start_time == FIXED_TIME
    assert params.end_time == LATER_TIME


def test_start_equal_end_accepted():
    params = EarthquakeQueryParams(start_time=FIXED_TIME, end_time=FIXED_TIME)
    assert params.start_time == params.end_time


def test_start_after_end_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(start_time=LATER_TIME, end_time=FIXED_TIME)


def test_omitted_time_bounds_accepted():
    params = EarthquakeQueryParams()
    assert params.start_time is None
    assert params.end_time is None


def test_explicit_none_start_time_accepted():
    """Covers the early-return branch when None is passed explicitly."""
    params = EarthquakeQueryParams(start_time=None)
    assert params.start_time is None


def test_non_datetime_start_time_rejected():
    """Covers the branch that passes non-datetime values through to Pydantic."""
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(start_time="not-a-datetime")


# ---------------------------------------------------------------------------
# D2. String-based datetime validation (HTTP query param path)
# ---------------------------------------------------------------------------


def test_utc_string_start_time_accepted():
    params = EarthquakeQueryParams(start_time="2026-07-22T10:00:00Z")
    assert params.start_time == datetime(2026, 7, 22, 10, 0, 0, tzinfo=UTC)


def test_offset_string_start_time_normalized_to_utc():
    params = EarthquakeQueryParams(start_time="2026-07-22T10:00:00-05:00")
    expected = datetime(2026, 7, 22, 15, 0, 0, tzinfo=UTC)
    assert params.start_time == expected
    assert params.start_time.tzinfo == UTC


def test_naive_string_start_time_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(start_time="2026-07-22T10:00:00")


def test_naive_string_end_time_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(end_time="2026-07-22T10:00:00")


def test_range_comparison_occurs_after_normalization():
    # "2026-07-22T15:00:00+05:00" normalises to 10:00Z
    # "2026-07-22T09:00:00Z" is earlier → start > end → rejected
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(
            start_time="2026-07-22T15:00:00+05:00",
            end_time="2026-07-22T09:00:00Z",
        )


def test_aware_offset_strings_accepted_when_start_before_end():
    params = EarthquakeQueryParams(
        start_time="2026-07-22T15:00:00+05:00",  # → 10:00 UTC
        end_time="2026-07-22T11:00:00Z",
    )
    assert params.start_time == datetime(2026, 7, 22, 10, 0, 0, tzinfo=UTC)
    assert params.end_time == datetime(2026, 7, 22, 11, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# D3. Repeat key datetime checks for MetricQueryParams
# ---------------------------------------------------------------------------


def test_metric_naive_start_time_rejected():
    with pytest.raises(ValidationError):
        MetricQueryParams(start_time=datetime(2024, 1, 1))


def test_metric_naive_string_start_time_rejected():
    with pytest.raises(ValidationError):
        MetricQueryParams(start_time="2026-07-22T10:00:00")


def test_metric_start_after_end_rejected():
    with pytest.raises(ValidationError):
        MetricQueryParams(start_time=LATER_TIME, end_time=FIXED_TIME)


# ---------------------------------------------------------------------------
# E. Magnitude validation
# ---------------------------------------------------------------------------


def test_omitted_magnitudes_accepted():
    params = EarthquakeQueryParams()
    assert params.min_magnitude is None
    assert params.max_magnitude is None


def test_only_min_magnitude_accepted():
    params = EarthquakeQueryParams(min_magnitude=2.5)
    assert params.min_magnitude == pytest.approx(2.5)
    assert params.max_magnitude is None


def test_only_max_magnitude_accepted():
    params = EarthquakeQueryParams(max_magnitude=5.0)
    assert params.max_magnitude == pytest.approx(5.0)
    assert params.min_magnitude is None


def test_negative_magnitudes_accepted():
    params = EarthquakeQueryParams(min_magnitude=-1.5, max_magnitude=-0.5)
    assert params.min_magnitude == pytest.approx(-1.5)


def test_equal_magnitude_bounds_accepted():
    params = EarthquakeQueryParams(min_magnitude=3.0, max_magnitude=3.0)
    assert params.min_magnitude == pytest.approx(3.0)


def test_min_greater_than_max_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(min_magnitude=5.0, max_magnitude=2.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_magnitude_rejected(value):
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(min_magnitude=value)


def test_bool_magnitude_rejected():
    with pytest.raises(ValidationError):
        EarthquakeQueryParams(min_magnitude=True)


def test_metric_rejects_magnitude_fields():
    with pytest.raises(ValidationError):
        MetricQueryParams(min_magnitude=1.0)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# F. PaginatedResponse
# ---------------------------------------------------------------------------


def test_valid_paginated_response_construction():
    resp = PaginatedResponse[int](
        items=[1, 2, 3],
        page=1,
        page_size=10,
        total=3,
        total_pages=1,
    )
    assert resp.items == [1, 2, 3]
    assert resp.total == 3


def test_generic_paginated_response_accepts_earthquake():
    eq = make_earthquake()
    resp = PaginatedResponse[Earthquake](
        items=[eq],
        page=1,
        page_size=10,
        total=1,
        total_pages=1,
    )
    assert resp.items[0].event_id == eq.event_id


def test_empty_result_uses_total_pages_zero():
    resp = PaginatedResponse[int](
        items=[],
        page=1,
        page_size=10,
        total=0,
        total_pages=0,
    )
    assert resp.total_pages == 0


def test_exact_division_page_count():
    # 20 items / page_size 10 = 2 pages
    resp = PaginatedResponse[int](
        items=[],
        page=3,
        page_size=10,
        total=20,
        total_pages=2,
    )
    assert resp.total_pages == 2


def test_partial_final_page_count():
    # 21 items / page_size 10 = 3 pages
    resp = PaginatedResponse[int](
        items=[],
        page=4,
        page_size=10,
        total=21,
        total_pages=3,
    )
    assert resp.total_pages == 3


def test_page_beyond_total_pages_with_empty_items_valid():
    resp = PaginatedResponse[int](
        items=[],
        page=99,
        page_size=10,
        total=5,
        total_pages=1,
    )
    assert resp.items == []


def test_negative_total_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[], page=1, page_size=10, total=-1, total_pages=0
        )


def test_negative_total_pages_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[], page=1, page_size=10, total=0, total_pages=-1
        )


def test_paginated_response_page_zero_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[], page=0, page_size=10, total=0, total_pages=0
        )


def test_paginated_response_page_size_zero_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[1], page=1, page_size=0, total=1, total_pages=1
        )


def test_more_items_than_page_size_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[1, 2, 3],
            page=1,
            page_size=2,
            total=3,
            total_pages=2,
        )


def test_more_items_than_total_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[1, 2],
            page=1,
            page_size=10,
            total=1,
            total_pages=1,
        )


def test_inconsistent_total_pages_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[],
            page=1,
            page_size=10,
            total=25,
            total_pages=2,  # should be 3
        )


def test_extra_response_fields_rejected():
    with pytest.raises(ValidationError):
        PaginatedResponse[int](
            items=[],
            page=1,
            page_size=10,
            total=0,
            total_pages=0,
            extra_field="bad",
        )


# ---------------------------------------------------------------------------
# G. Builder
# ---------------------------------------------------------------------------


def test_builder_returns_paginated_response():
    result = build_paginated_response(items=[1, 2], page=1, page_size=10, total=2)
    assert isinstance(result, PaginatedResponse)


def test_builder_preserves_items_and_order():
    items = [3, 1, 2]
    result = build_paginated_response(items=items, page=1, page_size=10, total=3)
    assert result.items == [3, 1, 2]


def test_builder_does_not_mutate_supplied_list():
    items = [1, 2, 3]
    original = items.copy()
    build_paginated_response(items=items, page=1, page_size=10, total=3)
    assert items == original


def test_builder_calculates_zero_pages_for_zero_total():
    result = build_paginated_response(items=[], page=1, page_size=10, total=0)
    assert result.total_pages == 0


def test_builder_exact_division():
    result = build_paginated_response(items=[], page=3, page_size=10, total=20)
    assert result.total_pages == 2


def test_builder_partial_division():
    result = build_paginated_response(items=[], page=1, page_size=10, total=21)
    assert result.total_pages == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0, "page_size": 10, "total": 0},   # invalid page
        {"page": 1, "page_size": 0,  "total": 1},   # page_size=0 must not divide
        {"page": 1, "page_size": -1, "total": 1},   # page_size<0 must not divide
        {"page": 1, "page_size": 10, "total": -1},  # negative total
    ],
)
def test_builder_propagates_validation_error(kwargs):
    with pytest.raises(ValidationError):
        build_paginated_response(items=[], **kwargs)


# ---------------------------------------------------------------------------
# H. ReportQueryParams
# ---------------------------------------------------------------------------


def test_report_query_params_default_construction():
    params = ReportQueryParams()
    assert params.page == 1
    assert params.page_size == DEFAULT_PAGE_SIZE
    assert params.sort is SortOrder.DESC
    assert params.start_time is None
    assert params.end_time is None


def test_report_query_params_inherits_pagination():
    params = ReportQueryParams(page=3, page_size=5)
    assert params.page == 3
    assert params.page_size == 5


def test_report_query_params_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        ReportQueryParams(start_time=datetime(2024, 6, 1, 12, 0, 0))


def test_report_query_params_start_after_end_rejected():
    with pytest.raises(ValidationError):
        ReportQueryParams(start_time=LATER_TIME, end_time=FIXED_TIME)


def test_report_query_params_rejects_min_magnitude():
    with pytest.raises(ValidationError):
        ReportQueryParams(min_magnitude=2.5)  # type: ignore[call-arg]
