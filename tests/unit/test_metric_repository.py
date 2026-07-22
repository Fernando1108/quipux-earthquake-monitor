"""Unit tests for MetricRepository — all MongoDB calls are mocked."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pymongo
import pytest
from pydantic import ValidationError

from app.models.metric import MagnitudeDistribution, Metric
from app.repositories import EarthquakeRepository, MetricRepository
from app.repositories.metric_repository import COLLECTION_NAME, _doc_to_metric

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc

WINDOW_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)
UPDATED_AT = WINDOW_START

EMPTY_DIST = MagnitudeDistribution(
    under_2=0,
    from_2_to_under_4=0,
    from_4_to_under_5=0,
    from_5_to_under_6=0,
    six_or_more=0,
    unknown=0,
)

SAMPLE_METRIC = Metric(
    window_start=WINDOW_START,
    window_end=WINDOW_END,
    earthquake_count=0,
    magnitude_count=0,
    magnitude_sum=0.0,
    average_magnitude=None,
    max_magnitude=None,
    magnitude_distribution=EMPTY_DIST,
    updated_at=UPDATED_AT,
)

SAMPLE_DOC: dict = {
    "window_start": WINDOW_START,
    "window_end": WINDOW_END,
    "earthquake_count": 0,
    "magnitude_count": 0,
    "magnitude_sum": 0.0,
    "average_magnitude": None,
    "max_magnitude": None,
    "magnitude_distribution": {
        "under_2": 0,
        "from_2_to_under_4": 0,
        "from_4_to_under_5": 0,
        "from_5_to_under_6": 0,
        "six_or_more": 0,
        "unknown": 0,
    },
    "updated_at": UPDATED_AT,
}


def run(coro):
    return asyncio.run(coro)


def make_repo(collection_mock=None):
    """Return (repo, collection_mock) with a fake injected database."""
    db = MagicMock()
    col = collection_mock if collection_mock is not None else MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    repo = MetricRepository(database=db)
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
# 1-2. Import checks
# ---------------------------------------------------------------------------

def test_metric_repository_importable_from_app_repositories():
    from app.repositories import MetricRepository as MR
    from app.repositories.metric_repository import MetricRepository as MRDirect
    assert MR is MRDirect


def test_earthquake_repository_remains_importable():
    from app.repositories import EarthquakeRepository as ER
    from app.repositories.earthquake_repository import EarthquakeRepository as ERDirect
    assert ER is ERDirect


# ---------------------------------------------------------------------------
# 3-6. Constructor
# ---------------------------------------------------------------------------

def test_constructor_uses_injected_database():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    repo = MetricRepository(database=db)
    db.__getitem__.assert_called_once_with(COLLECTION_NAME)
    assert repo._collection is col


def test_constructor_selects_metrics_collection():
    db = MagicMock()
    col = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    MetricRepository(database=db)
    db.__getitem__.assert_called_with("metrics")


def test_constructor_calls_get_database_when_none():
    fake_db = MagicMock()
    fake_db.__getitem__ = MagicMock(return_value=MagicMock())
    with patch(
        "app.repositories.metric_repository.get_database",
        return_value=fake_db,
    ) as mock_get_db:
        MetricRepository(database=None)
        mock_get_db.assert_called_once()


def test_constructor_does_not_call_get_database_when_injected():
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock())
    with patch(
        "app.repositories.metric_repository.get_database",
    ) as mock_get_db:
        MetricRepository(database=db)
        mock_get_db.assert_not_called()


# ---------------------------------------------------------------------------
# 7-15. upsert_metric
# ---------------------------------------------------------------------------

def test_upsert_metric_calls_replace_one_once():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    col.replace_one.assert_awaited_once()


def test_upsert_metric_filter_uses_window_start():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    filter_arg = col.replace_one.call_args[0][0]
    assert filter_arg == {"window_start": WINDOW_START}


def test_upsert_metric_replacement_contains_all_metric_fields():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    replacement = col.replace_one.call_args[0][1]
    dumped = SAMPLE_METRIC.model_dump(mode="python")
    for key, value in dumped.items():
        assert key in replacement
        assert replacement[key] == value


def test_upsert_metric_replacement_does_not_contain_id():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    replacement = col.replace_one.call_args[0][1]
    assert "_id" not in replacement


def test_upsert_metric_passes_upsert_true():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    kwargs = col.replace_one.call_args[1]
    assert kwargs.get("upsert") is True


def test_upsert_metric_does_not_mutate_metric_instance():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    original_count = SAMPLE_METRIC.earthquake_count
    original_start = SAMPLE_METRIC.window_start
    run(repo.upsert_metric(SAMPLE_METRIC))
    assert SAMPLE_METRIC.earthquake_count == original_count
    assert SAMPLE_METRIC.window_start == original_start


def test_upsert_metric_returns_none():
    repo, col = make_repo()
    col.replace_one = AsyncMock(return_value=MagicMock())
    result = run(repo.upsert_metric(SAMPLE_METRIC))
    assert result is None


def test_upsert_metric_propagates_db_error():
    repo, col = make_repo()
    col.replace_one = AsyncMock(side_effect=Exception("db failure"))
    with pytest.raises(Exception, match="db failure"):
        run(repo.upsert_metric(SAMPLE_METRIC))


def test_upsert_metric_no_read_before_replace_one():
    repo, col = make_repo()
    col.replace_one = AsyncMock()
    col.find_one = AsyncMock()
    run(repo.upsert_metric(SAMPLE_METRIC))
    col.find_one.assert_not_awaited()


# ---------------------------------------------------------------------------
# 16-26. get_by_window_start
# ---------------------------------------------------------------------------

def test_get_by_window_start_uses_exact_window_start():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_window_start(WINDOW_START))
    query_arg = col.find_one.call_args[0][0]
    assert query_arg == {"window_start": WINDOW_START}


def test_get_by_window_start_excludes_id():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    run(repo.get_by_window_start(WINDOW_START))
    projection_arg = col.find_one.call_args[0][1]
    assert projection_arg == {"_id": 0}


def test_get_by_window_start_returns_none_when_missing():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=None)
    result = run(repo.get_by_window_start(WINDOW_START))
    assert result is None


def test_get_by_window_start_returns_metric_when_found():
    repo, col = make_repo()
    col.find_one = AsyncMock(return_value=dict(SAMPLE_DOC))
    result = run(repo.get_by_window_start(WINDOW_START))
    assert isinstance(result, Metric)
    assert result.window_start == WINDOW_START


def test_get_by_window_start_does_not_mutate_returned_document():
    repo, col = make_repo()
    original = dict(SAMPLE_DOC)
    col.find_one = AsyncMock(return_value=original)
    run(repo.get_by_window_start(WINDOW_START))
    # original should be unchanged — _id was never in it, but keys still intact
    for key in SAMPLE_DOC:
        assert key in original


def test_get_by_window_start_naive_window_start_becomes_utc():
    repo, col = make_repo()
    doc = dict(SAMPLE_DOC)
    doc["window_start"] = WINDOW_START.replace(tzinfo=None)
    col.find_one = AsyncMock(return_value=doc)
    result = run(repo.get_by_window_start(WINDOW_START))
    assert result.window_start.tzinfo is not None
    assert result.window_start == WINDOW_START


def test_get_by_window_start_naive_window_end_becomes_utc():
    repo, col = make_repo()
    doc = dict(SAMPLE_DOC)
    doc["window_end"] = WINDOW_END.replace(tzinfo=None)
    col.find_one = AsyncMock(return_value=doc)
    result = run(repo.get_by_window_start(WINDOW_START))
    assert result.window_end.tzinfo is not None
    assert result.window_end == WINDOW_END


def test_get_by_window_start_naive_updated_at_becomes_utc():
    repo, col = make_repo()
    doc = dict(SAMPLE_DOC)
    doc["updated_at"] = UPDATED_AT.replace(tzinfo=None)
    col.find_one = AsyncMock(return_value=doc)
    result = run(repo.get_by_window_start(WINDOW_START))
    assert result.updated_at.tzinfo is not None
    assert result.updated_at == UPDATED_AT


def test_get_by_window_start_aware_non_utc_normalises_to_utc():
    repo, col = make_repo()
    eastern = timezone(timedelta(hours=-5))
    doc = dict(SAMPLE_DOC)
    doc["window_start"] = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)  # = 12:00 UTC
    doc["window_end"] = datetime(2024, 6, 1, 8, 0, 0, tzinfo=eastern)    # = 13:00 UTC
    doc["updated_at"] = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)
    col.find_one = AsyncMock(return_value=doc)
    result = run(repo.get_by_window_start(WINDOW_START))
    assert result.window_start.tzinfo == UTC
    assert result.window_start == WINDOW_START


def test_get_by_window_start_invalid_doc_raises_validation_error():
    repo, col = make_repo()
    bad_doc = dict(SAMPLE_DOC)
    bad_doc["earthquake_count"] = -999  # violates ge=0 constraint
    col.find_one = AsyncMock(return_value=bad_doc)
    with pytest.raises(ValidationError):
        run(repo.get_by_window_start(WINDOW_START))


def test_get_by_window_start_find_one_error_propagates():
    repo, col = make_repo()
    col.find_one = AsyncMock(side_effect=Exception("network error"))
    with pytest.raises(Exception, match="network error"):
        run(repo.get_by_window_start(WINDOW_START))


# ---------------------------------------------------------------------------
# 27-43. list_metrics
# ---------------------------------------------------------------------------

def test_list_metrics_no_filters_uses_empty_query():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {}


def test_list_metrics_start_time_creates_gte():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10, start_time=WINDOW_START))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {"window_start": {"$gte": WINDOW_START}}


def test_list_metrics_end_time_creates_lte():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10, end_time=WINDOW_END))
    query_arg = col.find.call_args[0][0]
    assert query_arg == {"window_start": {"$lte": WINDOW_END}}


def test_list_metrics_both_filters_share_one_window_start_key():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10, start_time=WINDOW_START, end_time=WINDOW_END))
    query_arg = col.find.call_args[0][0]
    assert "window_start" in query_arg
    assert "$gte" in query_arg["window_start"]
    assert "$lte" in query_arg["window_start"]
    assert query_arg["window_start"]["$gte"] == WINDOW_START
    assert query_arg["window_start"]["$lte"] == WINDOW_END


def test_list_metrics_count_documents_receives_same_query_as_find():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10, start_time=WINDOW_START))
    find_query = col.find.call_args[0][0]
    count_query = col.count_documents.call_args[0][0]
    assert find_query == count_query


def test_list_metrics_find_excludes_id():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(return_value=make_cursor([]))
    run(repo.list_metrics(page=1, page_size=10))
    projection_arg = col.find.call_args[0][1]
    assert projection_arg == {"_id": 0}


def test_list_metrics_default_sort_is_descending():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=1, page_size=10))
    cursor.sort.assert_called_once_with("window_start", pymongo.DESCENDING)


def test_list_metrics_ascending_sort():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=1, page_size=10, sort_descending=False))
    cursor.sort.assert_called_once_with("window_start", pymongo.ASCENDING)


def test_list_metrics_page_1_skips_zero():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=1, page_size=10))
    cursor.skip.assert_called_once_with(0)


def test_list_metrics_later_pages_calculate_skip_correctly():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=3, page_size=10))
    cursor.skip.assert_called_once_with(20)


def test_list_metrics_limit_receives_page_size():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=1, page_size=25))
    cursor.limit.assert_called_once_with(25)


def test_list_metrics_to_list_receives_length_page_size():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    col.find = MagicMock(return_value=cursor)
    run(repo.list_metrics(page=1, page_size=15))
    cursor.to_list.assert_awaited_once_with(length=15)


def test_list_metrics_documents_become_metric_objects():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([dict(SAMPLE_DOC)]))
    metrics, _ = run(repo.list_metrics(page=1, page_size=10))
    assert len(metrics) == 1
    assert isinstance(metrics[0], Metric)


def test_list_metrics_returns_total_count():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=42)
    col.find = MagicMock(return_value=make_cursor([]))
    _, total = run(repo.list_metrics(page=1, page_size=10))
    assert total == 42


def test_list_metrics_does_not_mutate_mongodb_documents():
    repo, col = make_repo()
    original = dict(SAMPLE_DOC)
    col.count_documents = AsyncMock(return_value=1)
    col.find = MagicMock(return_value=make_cursor([original]))
    run(repo.list_metrics(page=1, page_size=10))
    for key in SAMPLE_DOC:
        assert key in original


def test_list_metrics_count_documents_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(side_effect=Exception("count failed"))
    col.find = MagicMock(return_value=make_cursor([]))
    with pytest.raises(Exception, match="count failed"):
        run(repo.list_metrics(page=1, page_size=10))


def test_list_metrics_to_list_error_propagates():
    repo, col = make_repo()
    col.count_documents = AsyncMock(return_value=0)
    cursor = make_cursor([])
    cursor.to_list = AsyncMock(side_effect=Exception("cursor failed"))
    col.find = MagicMock(return_value=cursor)
    with pytest.raises(Exception, match="cursor failed"):
        run(repo.list_metrics(page=1, page_size=10))


# ---------------------------------------------------------------------------
# 44. Existing 218 tests still pass (import smoke test)
# ---------------------------------------------------------------------------

def test_existing_earthquake_repository_still_works():
    """Importing EarthquakeRepository from both paths must succeed."""
    from app.repositories import EarthquakeRepository
    from app.repositories.earthquake_repository import EarthquakeRepository as Direct
    assert EarthquakeRepository is Direct
