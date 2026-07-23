"""Unit tests for ReportRepository — all MongoDB calls are mocked."""

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pymongo
import pytest
from pydantic import ValidationError

from app.models.report import Report, TopLocation
from app.repositories import EarthquakeRepository, MetricRepository, ReportRepository
from app.repositories.report_repository import (
    COLLECTION_NAME,
    ReportRepository as ReportRepositoryDirect,
    _doc_to_report,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UTC = timezone.utc
OFFSET_MINUS_5 = timezone(timedelta(hours=-5))

PERIOD_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(hours=1)
REPORT_DATE = PERIOD_END
GENERATED_AT = PERIOD_END + timedelta(seconds=10)

SAMPLE_REPORT = Report(
    report_date=REPORT_DATE,
    period_start=PERIOD_START,
    period_end=PERIOD_END,
    total_events=3,
    events_with_magnitude=2,
    average_magnitude=2.5,
    max_magnitude=4.0,
    top_locations=[
        TopLocation(location="California", count=2),
        TopLocation(location="Nevada", count=1),
    ],
    generated_at=GENERATED_AT,
)

SAMPLE_DOC: dict = {
    "report_date": REPORT_DATE,
    "period_start": PERIOD_START,
    "period_end": PERIOD_END,
    "total_events": 3,
    "events_with_magnitude": 2,
    "average_magnitude": 2.5,
    "max_magnitude": 4.0,
    "top_locations": [
        {"location": "California", "count": 2},
        {"location": "Nevada", "count": 1},
    ],
    "generated_at": GENERATED_AT,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


def make_repo(collection_mock=None):
    """Return (repo, collection_mock) with a fake injected database."""
    db = MagicMock()
    col = collection_mock if collection_mock is not None else MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    repo = ReportRepository(database=db)
    return repo, col


def make_cursor(documents: list[dict]) -> MagicMock:
    """Build a synchronous cursor mock whose to_list() is async."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=documents)
    return cursor


# ---------------------------------------------------------------------------
# A. Public exports
# ---------------------------------------------------------------------------


def test_report_repository_importable_from_app_repositories():
    from app.repositories import ReportRepository as RR
    assert RR is not None


def test_package_export_is_same_class_as_direct_import():
    from app.repositories import ReportRepository as RR
    assert RR is ReportRepositoryDirect


def test_earthquake_repository_remains_importable():
    from app.repositories import EarthquakeRepository as ER
    from app.repositories.earthquake_repository import EarthquakeRepository as ERDirect
    assert ER is ERDirect


def test_metric_repository_remains_importable():
    from app.repositories import MetricRepository as MR
    from app.repositories.metric_repository import MetricRepository as MRDirect
    assert MR is MRDirect


def test_all_contains_exactly_three_names():
    import app.repositories as mod
    assert set(mod.__all__) == {
        "EarthquakeRepository",
        "MetricRepository",
        "ReportRepository",
    }
    assert len(mod.__all__) == 3


# ---------------------------------------------------------------------------
# B. Collection and constructor
# ---------------------------------------------------------------------------


def test_collection_name_equals_hourly_reports():
    assert COLLECTION_NAME == "hourly_reports"


def test_constructor_uses_injected_database():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    repo = ReportRepository(database=db)
    db.__getitem__.assert_called_once_with(COLLECTION_NAME)
    assert repo._collection is col


def test_constructor_selects_collection_name():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    ReportRepository(database=db)
    db.__getitem__.assert_called_with(COLLECTION_NAME)


def test_constructor_selects_hourly_reports_collection():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    ReportRepository(database=db)
    db.__getitem__.assert_called_with("hourly_reports")


def test_constructor_calls_get_database_when_none():
    fake_db = MagicMock()
    fake_db.__getitem__ = MagicMock(return_value=MagicMock())
    with patch(
        "app.repositories.report_repository.get_database",
        return_value=fake_db,
    ) as mock_get_db:
        ReportRepository(database=None)
        mock_get_db.assert_called_once()


def test_constructor_does_not_call_get_database_when_injected():
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock())
    with patch("app.repositories.report_repository.get_database") as mock_get_db:
        ReportRepository(database=db)
        mock_get_db.assert_not_called()


def test_constructor_performs_no_collection_reads_or_writes():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    ReportRepository(database=db)
    col.find.assert_not_called()
    col.find_one.assert_not_called()
    col.replace_one.assert_not_called()
    col.insert_one.assert_not_called()
    col.update_one.assert_not_called()
    col.count_documents.assert_not_called()


# ---------------------------------------------------------------------------
# C. upsert_report
# ---------------------------------------------------------------------------


def test_upsert_report_replace_one_awaited_once():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    col.replace_one.assert_awaited_once()


def test_upsert_report_filter_uses_report_date():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    filter_arg = col.replace_one.call_args[0][0]
    assert filter_arg == {"report_date": REPORT_DATE}


def test_upsert_report_filter_contains_only_report_date():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    filter_arg = col.replace_one.call_args[0][0]
    assert set(filter_arg.keys()) == {"report_date"}


def test_upsert_report_replacement_contains_exactly_nine_fields():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    replacement = col.replace_one.call_args[0][1]
    expected_keys = {
        "report_date",
        "period_start",
        "period_end",
        "total_events",
        "events_with_magnitude",
        "average_magnitude",
        "max_magnitude",
        "top_locations",
        "generated_at",
    }
    assert set(replacement.keys()) == expected_keys


def test_upsert_report_replacement_values_equal_model_dump():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    replacement = col.replace_one.call_args[0][1]
    dumped = SAMPLE_REPORT.model_dump(mode="python")
    for key, value in dumped.items():
        assert key in replacement
        assert replacement[key] == value


def test_upsert_report_nested_top_locations_are_dicts():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    replacement = col.replace_one.call_args[0][1]
    for item in replacement["top_locations"]:
        assert isinstance(item, dict)


def test_upsert_report_nested_dicts_contain_exactly_location_and_count():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    replacement = col.replace_one.call_args[0][1]
    for item in replacement["top_locations"]:
        assert set(item.keys()) == {"location", "count"}


def test_upsert_report_replacement_does_not_contain_id():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    replacement = col.replace_one.call_args[0][1]
    assert "_id" not in replacement


def test_upsert_report_passes_upsert_true():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    kwargs = col.replace_one.call_args[1]
    assert kwargs.get("upsert") is True


def test_upsert_report_does_not_mutate_report_instance():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    original_date = SAMPLE_REPORT.report_date
    original_total = SAMPLE_REPORT.total_events
    run(repo.upsert_report(SAMPLE_REPORT))
    assert SAMPLE_REPORT.report_date == original_date
    assert SAMPLE_REPORT.total_events == original_total


def test_upsert_report_returns_none():
    repo, col = make_repo()
    col.replace_one = AsyncMock(return_value=MagicMock())
    result = run(repo.upsert_report(SAMPLE_REPORT))
    assert result is None


def test_upsert_report_db_error_propagates():
    repo, col = make_repo()
    col.replace_one = AsyncMock(side_effect=Exception("db failure"))
    with pytest.raises(Exception, match="db failure"):
        run(repo.upsert_report(SAMPLE_REPORT))


def test_upsert_report_find_one_not_awaited():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    col.find_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    col.find_one.assert_not_awaited()


def test_upsert_report_insert_one_not_awaited():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    col.insert_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    col.insert_one.assert_not_awaited()


def test_upsert_report_update_one_not_awaited():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    col.update_one = AsyncMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    col.update_one.assert_not_awaited()


def test_upsert_report_no_read_before_replace_one():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    col.find_one = AsyncMock()
    col.find = MagicMock()
    run(repo.upsert_report(SAMPLE_REPORT))
    col.find_one.assert_not_awaited()
    col.find.assert_not_called()


# ---------------------------------------------------------------------------
# D. get_by_report_date
# ---------------------------------------------------------------------------


def test_get_by_report_date_query_uses_exact_report_date():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_report_date(REPORT_DATE))
    query_arg = col.find_one.call_args[0][0]
    assert query_arg == {"report_date": REPORT_DATE}


def test_get_by_report_date_query_contains_only_report_date():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_report_date(REPORT_DATE))
    query_arg = col.find_one.call_args[0][0]
    assert set(query_arg.keys()) == {"report_date"}


def test_get_by_report_date_projection_excludes_id():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_report_date(REPORT_DATE))
    projection_arg = col.find_one.call_args[0][1]
    assert projection_arg == {"_id": 0}


def test_get_by_report_date_find_one_awaited_exactly_once():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_report_date(REPORT_DATE))
    col.find_one.assert_awaited_once()


def test_get_by_report_date_missing_document_returns_none():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    result = run(repo.get_by_report_date(REPORT_DATE))
    assert result is None


def test_get_by_report_date_found_document_returns_report():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=dict(SAMPLE_DOC))
    result = run(repo.get_by_report_date(REPORT_DATE))
    assert isinstance(result, Report)


def test_get_by_report_date_returned_report_has_expected_values():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=dict(SAMPLE_DOC))
    result = run(repo.get_by_report_date(REPORT_DATE))
    assert result.report_date == REPORT_DATE
    assert result.total_events == 3
    assert result.average_magnitude == pytest.approx(2.5)


def test_get_by_report_date_nested_top_locations_become_toplocation():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=dict(SAMPLE_DOC))
    result = run(repo.get_by_report_date(REPORT_DATE))
    for item in result.top_locations:
        assert isinstance(item, TopLocation)


def test_get_by_report_date_does_not_mutate_original_document():
    repo, col = make_repo()
    original = dict(SAMPLE_DOC)
    col.find_one = AsyncMock(return_value=original)
    run(repo.get_by_report_date(REPORT_DATE))
    for key in SAMPLE_DOC:
        assert key in original


def test_get_by_report_date_unexpected_id_safely_removed():
    repo, col = make_repo()
    doc_with_id = dict(SAMPLE_DOC)
    doc_with_id["_id"] = "some-object-id"
    col.find_one = AsyncMock(return_value=doc_with_id)
    result = run(repo.get_by_report_date(REPORT_DATE))
    assert isinstance(result, Report)
    assert not hasattr(result, "_id")


def test_get_by_report_date_invalid_document_raises_validation_error():
    repo, col = make_repo()
    bad_doc = dict(SAMPLE_DOC)
    bad_doc["total_events"] = -1  # violates ge=0 constraint
    col.find_one = AsyncMock(return_value=bad_doc)
    with pytest.raises(ValidationError):
        run(repo.get_by_report_date(REPORT_DATE))


def test_get_by_report_date_find_one_error_propagates():
    repo, col = make_repo()
    col.find_one = AsyncMock(side_effect=Exception("network error"))
    with pytest.raises(Exception, match="network error"):
        run(repo.get_by_report_date(REPORT_DATE))


# ---------------------------------------------------------------------------
# E. Datetime conversion
# ---------------------------------------------------------------------------


def test_doc_to_report_naive_report_date_becomes_utc():
    doc = dict(SAMPLE_DOC)
    doc["report_date"] = REPORT_DATE.replace(tzinfo=None)
    result = _doc_to_report(doc)
    assert result.report_date.tzinfo is not None
    assert result.report_date == REPORT_DATE


def test_doc_to_report_naive_period_start_becomes_utc():
    doc = dict(SAMPLE_DOC)
    doc["period_start"] = PERIOD_START.replace(tzinfo=None)
    result = _doc_to_report(doc)
    assert result.period_start.tzinfo is not None
    assert result.period_start == PERIOD_START


def test_doc_to_report_naive_period_end_becomes_utc():
    doc = dict(SAMPLE_DOC)
    doc["period_end"] = PERIOD_END.replace(tzinfo=None)
    result = _doc_to_report(doc)
    assert result.period_end.tzinfo is not None
    assert result.period_end == PERIOD_END


def test_doc_to_report_naive_generated_at_becomes_utc():
    doc = dict(SAMPLE_DOC)
    doc["generated_at"] = GENERATED_AT.replace(tzinfo=None)
    result = _doc_to_report(doc)
    assert result.generated_at.tzinfo is not None
    assert result.generated_at == GENERATED_AT


def test_doc_to_report_all_four_naive_fields_become_utc():
    doc = dict(SAMPLE_DOC)
    doc["report_date"] = REPORT_DATE.replace(tzinfo=None)
    doc["period_start"] = PERIOD_START.replace(tzinfo=None)
    doc["period_end"] = PERIOD_END.replace(tzinfo=None)
    doc["generated_at"] = GENERATED_AT.replace(tzinfo=None)
    result = _doc_to_report(doc)
    assert result.report_date == REPORT_DATE
    assert result.period_start == PERIOD_START
    assert result.period_end == PERIOD_END
    assert result.generated_at == GENERATED_AT
    for field in (result.report_date, result.period_start, result.period_end, result.generated_at):
        assert field.tzinfo == UTC


def test_doc_to_report_aware_non_utc_report_date_normalizes_to_utc():
    doc = dict(SAMPLE_DOC)
    # 2024-06-01T08:00:00-05:00 == 13:00 UTC == REPORT_DATE
    doc["report_date"] = datetime(2024, 6, 1, 8, 0, 0, tzinfo=OFFSET_MINUS_5)
    result = _doc_to_report(doc)
    assert result.report_date.tzinfo == UTC
    assert result.report_date == REPORT_DATE


def test_doc_to_report_aware_non_utc_period_start_normalizes_to_utc():
    doc = dict(SAMPLE_DOC)
    # 2024-06-01T07:00:00-05:00 == 12:00 UTC == PERIOD_START
    doc["period_start"] = datetime(2024, 6, 1, 7, 0, 0, tzinfo=OFFSET_MINUS_5)
    result = _doc_to_report(doc)
    assert result.period_start.tzinfo == UTC
    assert result.period_start == PERIOD_START


def test_doc_to_report_aware_non_utc_period_end_normalizes_to_utc():
    doc = dict(SAMPLE_DOC)
    # 2024-06-01T08:00:00-05:00 == 13:00 UTC == PERIOD_END
    doc["period_end"] = datetime(2024, 6, 1, 8, 0, 0, tzinfo=OFFSET_MINUS_5)
    result = _doc_to_report(doc)
    assert result.period_end.tzinfo == UTC
    assert result.period_end == PERIOD_END


def test_doc_to_report_aware_non_utc_generated_at_normalizes_to_utc():
    doc = dict(SAMPLE_DOC)
    # 2024-06-01T08:00:10-05:00 == 13:00:10 UTC == GENERATED_AT
    doc["generated_at"] = datetime(2024, 6, 1, 8, 0, 10, tzinfo=OFFSET_MINUS_5)
    result = _doc_to_report(doc)
    assert result.generated_at.tzinfo == UTC
    assert result.generated_at == GENERATED_AT


def test_doc_to_report_mixed_naive_and_aware_handled_correctly():
    doc = dict(SAMPLE_DOC)
    doc["report_date"] = REPORT_DATE.replace(tzinfo=None)  # naive → UTC
    doc["period_start"] = PERIOD_START                     # already UTC
    doc["period_end"] = PERIOD_END                         # already UTC
    doc["generated_at"] = GENERATED_AT.replace(tzinfo=None)  # naive → UTC
    result = _doc_to_report(doc)
    assert result.report_date == REPORT_DATE
    assert result.period_start == PERIOD_START
    assert result.period_end == PERIOD_END
    assert result.generated_at == GENERATED_AT
    for field in (result.report_date, result.period_start, result.period_end, result.generated_at):
        assert field.tzinfo == UTC


def test_doc_to_report_does_not_mutate_original_document():
    original = dict(SAMPLE_DOC)
    original_report_date = original["report_date"]
    _doc_to_report(original)
    assert original["report_date"] is original_report_date
    for key in SAMPLE_DOC:
        assert key in original


def test_doc_to_report_missing_required_datetime_raises_validation_error():
    doc = dict(SAMPLE_DOC)
    del doc["report_date"]
    with pytest.raises(ValidationError):
        _doc_to_report(doc)


def test_doc_to_report_non_datetime_value_raises_validation_error():
    doc = dict(SAMPLE_DOC)
    doc["report_date"] = "not-a-datetime"
    with pytest.raises(ValidationError):
        _doc_to_report(doc)


def test_doc_to_report_extra_unknown_field_raises_validation_error():
    doc = dict(SAMPLE_DOC)
    doc["unknown_field"] = "surprise"
    with pytest.raises(ValidationError):
        _doc_to_report(doc)


# ---------------------------------------------------------------------------
# F. list_reports query
# ---------------------------------------------------------------------------


def test_list_reports_no_filters_uses_empty_query():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {}


def test_list_reports_start_time_creates_gte():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, start_time=PERIOD_START))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {"report_date": {"$gte": PERIOD_START}}


def test_list_reports_end_time_creates_lte():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, end_time=REPORT_DATE))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {"report_date": {"$lte": REPORT_DATE}}


def test_list_reports_both_filters_share_one_report_date_key():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, start_time=PERIOD_START, end_time=REPORT_DATE))
    query_arg = col.find.call_args[0][0]
    assert "report_date" in query_arg
    assert "$gte" in query_arg["report_date"]
    assert "$lte" in query_arg["report_date"]
    assert query_arg["report_date"]["$gte"] == PERIOD_START
    assert query_arg["report_date"]["$lte"] == REPORT_DATE


def test_list_reports_both_filters_preserve_exact_values():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, start_time=PERIOD_START, end_time=REPORT_DATE))
    query_arg = col.find.call_args[0][0]
    assert query_arg["report_date"]["$gte"] is PERIOD_START
    assert query_arg["report_date"]["$lte"] is REPORT_DATE


def test_list_reports_count_documents_receives_same_query_as_find():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, start_time=PERIOD_START))
    find_query = col.find.call_args[0][0]
    count_query = col.count_documents.call_args[0][0]
    assert find_query == count_query


def test_list_reports_find_projection_excludes_id():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10))
    projection_arg = col.find.call_args[0][1]
    assert projection_arg == {"_id": 0}


def test_list_reports_no_filter_on_period_start():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, start_time=PERIOD_START))
    query_arg = col.find.call_args[0][0]
    assert "period_start" not in query_arg


def test_list_reports_no_filter_on_period_end():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10, end_time=REPORT_DATE))
    query_arg = col.find.call_args[0][0]
    assert "period_end" not in query_arg


def test_list_reports_no_filter_on_generated_at():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_reports(page=1, page_size=10))
    query_arg = col.find.call_args[0][0]
    assert "generated_at" not in query_arg


# ---------------------------------------------------------------------------
# G. list_reports sorting and pagination
# ---------------------------------------------------------------------------


def test_list_reports_default_sort_is_report_date_descending():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=1, page_size=10))
    cursor.sort.assert_called_once_with("report_date", pymongo.DESCENDING)


def test_list_reports_sort_ascending():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=1, page_size=10, sort_descending=False))
    cursor.sort.assert_called_once_with("report_date", pymongo.ASCENDING)


def test_list_reports_page_1_skips_zero():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=1, page_size=10))
    cursor.skip.assert_called_once_with(0)


def test_list_reports_later_pages_calculate_skip_correctly():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=3, page_size=10))
    cursor.skip.assert_called_once_with(20)


def test_list_reports_limit_receives_page_size():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=1, page_size=25))
    cursor.limit.assert_called_once_with(25)


def test_list_reports_to_list_receives_length_page_size():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_reports(page=1, page_size=15))
    cursor.to_list.assert_awaited_once_with(length=15)


def test_list_reports_does_not_calculate_total_pages():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=21)
    col.find = MagicMock(return_value=make_cursor([]))
    result = run(repo.list_reports(page=1, page_size=10))
    assert isinstance(result, tuple)
    assert len(result) == 2
    _, total = result
    assert total == 21


# ---------------------------------------------------------------------------
# H. list_reports return values
# ---------------------------------------------------------------------------


def test_list_reports_empty_cursor_returns_empty_list():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    reports, total = run(repo.list_reports(page=1, page_size=10))
    assert reports == []
    assert total == 0


def test_list_reports_documents_become_report_objects():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([dict(SAMPLE_DOC)]))
    reports, _ = run(repo.list_reports(page=1, page_size=10))
    assert len(reports) == 1
    assert isinstance(reports[0], Report)


def test_list_reports_nested_top_locations_become_toplocation():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([dict(SAMPLE_DOC)]))
    reports, _ = run(repo.list_reports(page=1, page_size=10))
    for item in reports[0].top_locations:
        assert isinstance(item, TopLocation)


def test_list_reports_multiple_documents_preserve_cursor_order():
    doc1 = dict(SAMPLE_DOC)  # REPORT_DATE = 13:00
    doc2 = dict(SAMPLE_DOC)
    later_start = PERIOD_START + timedelta(hours=1)
    later_end = later_start + timedelta(hours=1)
    doc2["period_start"] = later_start
    doc2["period_end"] = later_end
    doc2["report_date"] = later_end
    doc2["generated_at"] = later_end + timedelta(seconds=10)
    doc2["top_locations"] = []
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=2)
    col.find = MagicMock(return_value=make_cursor([doc2, doc1]))
    reports, _ = run(repo.list_reports(page=1, page_size=10))
    assert reports[0].report_date == later_end
    assert reports[1].report_date == REPORT_DATE


def test_list_reports_total_count_returned_unchanged():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=42)
    col.find = MagicMock(return_value=make_cursor([]))
    _, total = run(repo.list_reports(page=1, page_size=10))
    assert total == 42


def test_list_reports_naive_datetimes_converted():
    doc = dict(SAMPLE_DOC)
    doc["report_date"] = REPORT_DATE.replace(tzinfo=None)
    doc["period_start"] = PERIOD_START.replace(tzinfo=None)
    doc["period_end"] = PERIOD_END.replace(tzinfo=None)
    doc["generated_at"] = GENERATED_AT.replace(tzinfo=None)
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([doc]))
    reports, _ = run(repo.list_reports(page=1, page_size=10))
    r = reports[0]
    assert r.report_date.tzinfo == UTC
    assert r.period_start.tzinfo == UTC
    assert r.period_end.tzinfo == UTC
    assert r.generated_at.tzinfo == UTC


def test_list_reports_does_not_mutate_mongodb_documents():
    original = dict(SAMPLE_DOC)
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([original]))
    run(repo.list_reports(page=1, page_size=10))
    for key in SAMPLE_DOC:
        assert key in original


def test_list_reports_invalid_document_raises_validation_error():
    bad_doc = dict(SAMPLE_DOC)
    bad_doc["total_events"] = -99
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([bad_doc]))
    with pytest.raises(ValidationError):
        run(repo.list_reports(page=1, page_size=10))


def test_list_reports_count_documents_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(side_effect=Exception("count failed"))
    col.find = MagicMock(return_value=make_cursor([]))
    with pytest.raises(Exception, match="count failed"):
        run(repo.list_reports(page=1, page_size=10))


def test_list_reports_find_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(side_effect=Exception("find failed"))
    with pytest.raises(Exception, match="find failed"):
        run(repo.list_reports(page=1, page_size=10))


def test_list_reports_cursor_sort_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = MagicMock()
    cursor.sort = MagicMock(side_effect=Exception("sort error"))
    col.find = MagicMock(return_value=cursor)
    with pytest.raises(Exception, match="sort error"):
        run(repo.list_reports(page=1, page_size=10))


def test_list_reports_to_list_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    cursor.to_list = AsyncMock(side_effect=Exception("cursor failed"))
    col.find = MagicMock(return_value=cursor)
    with pytest.raises(Exception, match="cursor failed"):
        run(repo.list_reports(page=1, page_size=10))


# ---------------------------------------------------------------------------
# I. Regression
# ---------------------------------------------------------------------------


def test_existing_earthquake_repository_export_matches_direct_import():
    from app.repositories import EarthquakeRepository as ER
    from app.repositories.earthquake_repository import EarthquakeRepository as ERDirect
    assert ER is ERDirect


def test_existing_metric_repository_export_matches_direct_import():
    from app.repositories import MetricRepository as MR
    from app.repositories.metric_repository import MetricRepository as MRDirect
    assert MR is MRDirect


def test_report_and_toplocation_model_behavior_available():
    r = Report(
        report_date=REPORT_DATE,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        total_events=1,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[],
        generated_at=GENERATED_AT,
    )
    assert isinstance(r, Report)


def test_repository_does_not_import_airflow():
    import app.repositories.report_repository as mod
    source = inspect.getsource(mod)
    assert "airflow" not in source.lower()


def test_repository_does_not_create_indexes():
    import app.repositories.report_repository as mod
    source = inspect.getsource(mod)
    assert "create_index" not in source
    assert "ensure_index" not in source


def test_repository_contains_no_aggregation_pipeline():
    import app.repositories.report_repository as mod
    source = inspect.getsource(mod)
    assert "aggregate" not in source


# ---------------------------------------------------------------------------
# J. Signature regression
# ---------------------------------------------------------------------------


def test_list_reports_public_annotations():
    hints = get_type_hints(ReportRepository.list_reports)
    assert hints["page"] is int
    assert hints["page_size"] is int
    assert hints["start_time"] == datetime | None
    assert hints["end_time"] == datetime | None
    assert hints["sort_descending"] is bool
    assert hints["return"] == tuple[list[Report], int]
