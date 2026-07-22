"""Unit tests for EarthquakeRepository — mocks only, no live MongoDB."""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pymongo
import pymongo.errors
import pytest
from pydantic import ValidationError

from app.repositories import EarthquakeRepository
from app.repositories.earthquake_repository import (
    EarthquakeRepository as EarthquakeRepositoryDirect,
    COLLECTION_NAME,
)
from app.models.earthquake import Earthquake


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def make_earthquake(**overrides) -> Earthquake:
    defaults = {
        "event_id": "us7000test1",
        "magnitude": 3.5,
        "location": "10km N of Testville",
        "latitude": 34.0,
        "longitude": -118.0,
        "depth": 10.0,
        "event_time": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return Earthquake(**defaults)


def make_cursor(documents: list[dict]) -> MagicMock:
    """Cursor with synchronous sort/skip/limit and async to_list."""
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=documents)
    return cursor


def make_collection(
    cursor: MagicMock | None = None,
    insert_raises: Exception | None = None,
    count: int = 0,
) -> MagicMock:
    col = MagicMock()

    if insert_raises is not None:
        col.insert_one = AsyncMock(side_effect=insert_raises)
    else:
        insert_result = MagicMock()
        col.insert_one = AsyncMock(return_value=insert_result)

    col.count_documents = AsyncMock(return_value=count)
    col.find = MagicMock(return_value=cursor if cursor is not None else make_cursor([]))
    return col


def make_database(collection: MagicMock | None = None) -> MagicMock:
    col = collection if collection is not None else make_collection()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    return db


def _sample_doc(**overrides) -> dict:
    doc = {
        "event_id": "us7000test1",
        "magnitude": 3.5,
        "location": "10km N of Testville",
        "latitude": 34.0,
        "longitude": -118.0,
        "depth": 10.0,
        "event_time": datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# 1. Import from app.repositories
# ---------------------------------------------------------------------------

def test_import_from_app_repositories():
    assert EarthquakeRepository is EarthquakeRepositoryDirect


# ---------------------------------------------------------------------------
# 2. Constructor uses an injected database
# ---------------------------------------------------------------------------

def test_constructor_uses_injected_database():
    col = make_collection()
    db = make_database(col)
    repo = EarthquakeRepository(database=db)
    db.__getitem__.assert_called_once_with(COLLECTION_NAME)
    assert repo._collection is col


# ---------------------------------------------------------------------------
# 3. Constructor selects the "earthquakes" collection
# ---------------------------------------------------------------------------

def test_constructor_selects_earthquakes_collection():
    db = make_database()
    EarthquakeRepository(database=db)
    db.__getitem__.assert_called_once_with("earthquakes")


# ---------------------------------------------------------------------------
# 4. Constructor calls get_database() when no database is injected
# ---------------------------------------------------------------------------

def test_constructor_calls_get_database_when_none():
    col = make_collection()
    db = make_database(col)
    with patch("app.repositories.earthquake_repository.get_database", return_value=db) as mock_get:
        EarthquakeRepository()
    mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Constructor does not call get_database() when a database is injected
# ---------------------------------------------------------------------------

def test_constructor_does_not_call_get_database_when_injected():
    db = make_database()
    with patch("app.repositories.earthquake_repository.get_database") as mock_get:
        EarthquakeRepository(database=db)
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Successful insert calls insert_one once
# ---------------------------------------------------------------------------

def test_insert_if_new_calls_insert_one_once():
    col = make_collection()
    db = make_database(col)
    eq = make_earthquake()
    run(EarthquakeRepository(database=db).insert_if_new(eq))
    col.insert_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Successful insert returns True
# ---------------------------------------------------------------------------

def test_insert_if_new_returns_true_on_success():
    col = make_collection()
    db = make_database(col)
    result = run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))
    assert result is True


# ---------------------------------------------------------------------------
# 8. Inserted document contains every Earthquake field
# ---------------------------------------------------------------------------

def test_insert_document_contains_all_earthquake_fields():
    col = make_collection()
    db = make_database(col)
    eq = make_earthquake()
    run(EarthquakeRepository(database=db).insert_if_new(eq))

    inserted_doc = col.insert_one.call_args.args[0]
    for field in ("event_id", "magnitude", "location", "latitude", "longitude", "depth", "event_time"):
        assert field in inserted_doc


# ---------------------------------------------------------------------------
# 9. Inserted document contains an aware UTC ingested_at
# ---------------------------------------------------------------------------

def test_insert_document_has_utc_ingested_at():
    col = make_collection()
    db = make_database(col)
    run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))

    inserted_doc = col.insert_one.call_args.args[0]
    ingested_at = inserted_doc["ingested_at"]
    assert isinstance(ingested_at, datetime)
    assert ingested_at.tzinfo is not None
    assert ingested_at.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# 10. Insert does not add _id manually
# ---------------------------------------------------------------------------

def test_insert_document_does_not_contain_explicit_id():
    col = make_collection()
    db = make_database(col)
    run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))

    inserted_doc = col.insert_one.call_args.args[0]
    assert "_id" not in inserted_doc


# ---------------------------------------------------------------------------
# 11. Insert does not mutate the Earthquake model
# ---------------------------------------------------------------------------

def test_insert_does_not_mutate_earthquake():
    col = make_collection()
    db = make_database(col)
    eq = make_earthquake()
    original_event_id = eq.event_id
    original_event_time = eq.event_time

    run(EarthquakeRepository(database=db).insert_if_new(eq))

    assert eq.event_id == original_event_id
    assert eq.event_time == original_event_time
    assert not hasattr(eq, "ingested_at")


# ---------------------------------------------------------------------------
# 12. DuplicateKeyError returns False
# ---------------------------------------------------------------------------

def test_insert_if_new_returns_false_on_duplicate():
    col = make_collection(insert_raises=pymongo.errors.DuplicateKeyError("dup"))
    db = make_database(col)
    result = run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))
    assert result is False


# ---------------------------------------------------------------------------
# 13. DuplicateKeyError does not perform a second database operation
# ---------------------------------------------------------------------------

def test_duplicate_key_does_not_trigger_second_operation():
    col = make_collection(insert_raises=pymongo.errors.DuplicateKeyError("dup"))
    db = make_database(col)
    run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))
    col.insert_one.assert_awaited_once()
    col.count_documents.assert_not_awaited()
    col.find.assert_not_called()


# ---------------------------------------------------------------------------
# 14. A non-duplicate PyMongo error propagates
# ---------------------------------------------------------------------------

def test_non_duplicate_pymongo_error_propagates():
    col = make_collection(insert_raises=pymongo.errors.OperationFailure("oops"))
    db = make_database(col)
    with pytest.raises(pymongo.errors.OperationFailure):
        run(EarthquakeRepository(database=db).insert_if_new(make_earthquake()))


# ---------------------------------------------------------------------------
# 15. list_earthquakes without filters uses {}
# ---------------------------------------------------------------------------

def test_list_earthquakes_no_filters_uses_empty_query():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    query_used = col.find.call_args.args[0]
    assert query_used == {}
    count_query = col.count_documents.call_args.args[0]
    assert count_query == {}


# ---------------------------------------------------------------------------
# 16. min_magnitude produces $gte
# ---------------------------------------------------------------------------

def test_list_earthquakes_min_magnitude_produces_gte():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20, min_magnitude=4.0))

    query = col.find.call_args.args[0]
    assert query["magnitude"]["$gte"] == 4.0
    assert "$lte" not in query["magnitude"]


# ---------------------------------------------------------------------------
# 17. max_magnitude produces $lte
# ---------------------------------------------------------------------------

def test_list_earthquakes_max_magnitude_produces_lte():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20, max_magnitude=7.0))

    query = col.find.call_args.args[0]
    assert query["magnitude"]["$lte"] == 7.0
    assert "$gte" not in query["magnitude"]


# ---------------------------------------------------------------------------
# 18. Both magnitude filters share the same field condition
# ---------------------------------------------------------------------------

def test_list_earthquakes_both_magnitude_filters_in_same_condition():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(
        page=1, page_size=20, min_magnitude=3.0, max_magnitude=6.0,
    ))

    query = col.find.call_args.args[0]
    assert "$gte" in query["magnitude"]
    assert "$lte" in query["magnitude"]
    assert query["magnitude"]["$gte"] == 3.0
    assert query["magnitude"]["$lte"] == 6.0


# ---------------------------------------------------------------------------
# 19. start_time produces $gte
# ---------------------------------------------------------------------------

def test_list_earthquakes_start_time_produces_gte():
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20, start_time=t))

    query = col.find.call_args.args[0]
    assert query["event_time"]["$gte"] == t
    assert "$lte" not in query["event_time"]


# ---------------------------------------------------------------------------
# 20. end_time produces $lte
# ---------------------------------------------------------------------------

def test_list_earthquakes_end_time_produces_lte():
    t = datetime(2024, 12, 31, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20, end_time=t))

    query = col.find.call_args.args[0]
    assert query["event_time"]["$lte"] == t
    assert "$gte" not in query["event_time"]


# ---------------------------------------------------------------------------
# 21. Both time filters share the same field condition
# ---------------------------------------------------------------------------

def test_list_earthquakes_both_time_filters_in_same_condition():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 12, 31, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(
        page=1, page_size=20, start_time=t_start, end_time=t_end,
    ))

    query = col.find.call_args.args[0]
    assert query["event_time"]["$gte"] == t_start
    assert query["event_time"]["$lte"] == t_end


# ---------------------------------------------------------------------------
# 22. Combined magnitude and time filters are preserved
# ---------------------------------------------------------------------------

def test_list_earthquakes_combined_filters():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(
        page=1, page_size=20, min_magnitude=5.0, start_time=t_start,
    ))

    query = col.find.call_args.args[0]
    assert "magnitude" in query
    assert "event_time" in query


# ---------------------------------------------------------------------------
# 23. count_documents receives the exact find query
# ---------------------------------------------------------------------------

def test_count_documents_receives_same_query_as_find():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=5)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(
        page=1, page_size=20, min_magnitude=4.0,
    ))

    find_query = col.find.call_args.args[0]
    count_query = col.count_documents.call_args.args[0]
    assert find_query == count_query


# ---------------------------------------------------------------------------
# 24. find uses a projection excluding _id and ingested_at
# ---------------------------------------------------------------------------

def test_list_earthquakes_find_projection_excludes_id_and_ingested_at():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    projection = col.find.call_args.args[1]
    assert projection["_id"] == 0
    assert projection["ingested_at"] == 0


# ---------------------------------------------------------------------------
# 25. Default ordering is event_time DESCENDING
# ---------------------------------------------------------------------------

def test_list_earthquakes_default_sort_is_descending():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    cursor.sort.assert_called_once_with("event_time", pymongo.DESCENDING)


# ---------------------------------------------------------------------------
# 26. Ascending ordering uses event_time ASCENDING
# ---------------------------------------------------------------------------

def test_list_earthquakes_ascending_sort():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(
        page=1, page_size=20, sort_descending=False,
    ))

    cursor.sort.assert_called_once_with("event_time", pymongo.ASCENDING)


# ---------------------------------------------------------------------------
# 27. Correct skip is used for page 1
# ---------------------------------------------------------------------------

def test_list_earthquakes_page1_skip_is_zero():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    cursor.skip.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# 28. Correct skip is used for a later page
# ---------------------------------------------------------------------------

def test_list_earthquakes_later_page_skip():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=100)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=3, page_size=10))

    cursor.skip.assert_called_once_with(20)


# ---------------------------------------------------------------------------
# 29. limit receives page_size
# ---------------------------------------------------------------------------

def test_list_earthquakes_limit_receives_page_size():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=15))

    cursor.limit.assert_called_once_with(15)


# ---------------------------------------------------------------------------
# 30. to_list receives length=page_size
# ---------------------------------------------------------------------------

def test_list_earthquakes_to_list_receives_page_size():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=0)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=25))

    cursor.to_list.assert_awaited_once_with(length=25)


# ---------------------------------------------------------------------------
# 31. Returned documents become Earthquake objects
# ---------------------------------------------------------------------------

def test_list_earthquakes_returns_earthquake_objects():
    doc = _sample_doc()
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    earthquakes, _ = run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    assert len(earthquakes) == 1
    assert isinstance(earthquakes[0], Earthquake)
    assert earthquakes[0].event_id == doc["event_id"]


# ---------------------------------------------------------------------------
# 32. list_earthquakes returns the total count
# ---------------------------------------------------------------------------

def test_list_earthquakes_returns_total_count():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor, count=42)
    db = make_database(col)
    _, total = run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    assert total == 42


# ---------------------------------------------------------------------------
# 33. MongoDB _id and ingested_at do not enter the Earthquake model
# ---------------------------------------------------------------------------

def test_list_earthquakes_strips_id_and_ingested_at():
    doc = _sample_doc()
    doc["_id"] = "some-object-id"
    doc["ingested_at"] = datetime(2024, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    earthquakes, _ = run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    eq = earthquakes[0]
    assert not hasattr(eq, "_id")
    assert not hasattr(eq, "ingested_at")


# ---------------------------------------------------------------------------
# 34. The MongoDB document is not mutated during conversion
# ---------------------------------------------------------------------------

def test_doc_to_earthquake_does_not_mutate_original():
    doc = _sample_doc()
    doc["_id"] = "original-id"
    doc["ingested_at"] = datetime(2024, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
    original_keys = set(doc.keys())

    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    assert set(doc.keys()) == original_keys
    assert doc["_id"] == "original-id"
    assert doc["ingested_at"] is not None


# ---------------------------------------------------------------------------
# 35. A naive MongoDB event_time is interpreted as UTC
# ---------------------------------------------------------------------------

def test_naive_event_time_becomes_utc():
    doc = _sample_doc(event_time=datetime(2024, 6, 1, 12, 0, 0))  # no tzinfo
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    earthquakes, _ = run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    eq = earthquakes[0]
    assert eq.event_time.tzinfo is not None
    assert eq.event_time == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 36. An aware non-UTC event_time is normalized by Earthquake
# ---------------------------------------------------------------------------

def test_aware_non_utc_event_time_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    local_time = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)
    doc = _sample_doc(event_time=local_time)
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    earthquakes, _ = run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))

    eq = earthquakes[0]
    assert eq.event_time == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert eq.event_time.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# 37. An invalid stored document raises Pydantic ValidationError
# ---------------------------------------------------------------------------

def test_invalid_stored_document_raises_validation_error():
    doc = _sample_doc(latitude=999.0)  # out of range
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor, count=1)
    db = make_database(col)
    with pytest.raises(ValidationError):
        run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))


# ---------------------------------------------------------------------------
# 38. find_by_time_range uses $gte for start_time
# ---------------------------------------------------------------------------

def test_find_by_time_range_start_time_gte():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    query = col.find.call_args.args[0]
    assert query["event_time"]["$gte"] == t_start


# ---------------------------------------------------------------------------
# 39. find_by_time_range uses $lt for end_time
# ---------------------------------------------------------------------------

def test_find_by_time_range_end_time_lt():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    query = col.find.call_args.args[0]
    assert query["event_time"]["$lt"] == t_end
    assert "$lte" not in query["event_time"]


# ---------------------------------------------------------------------------
# 40. find_by_time_range excludes _id and ingested_at
# ---------------------------------------------------------------------------

def test_find_by_time_range_projection_excludes_id_and_ingested_at():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    projection = col.find.call_args.args[1]
    assert projection["_id"] == 0
    assert projection["ingested_at"] == 0


# ---------------------------------------------------------------------------
# 41. find_by_time_range sorts event_time ASCENDING
# ---------------------------------------------------------------------------

def test_find_by_time_range_sorts_ascending():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    cursor.sort.assert_called_once_with("event_time", pymongo.ASCENDING)


# ---------------------------------------------------------------------------
# 42. find_by_time_range calls to_list(length=None)
# ---------------------------------------------------------------------------

def test_find_by_time_range_to_list_length_none():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    cursor.to_list.assert_awaited_once_with(length=None)


# ---------------------------------------------------------------------------
# 43. find_by_time_range returns Earthquake objects
# ---------------------------------------------------------------------------

def test_find_by_time_range_returns_earthquake_objects():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    doc = _sample_doc()
    cursor = make_cursor([doc])
    col = make_collection(cursor=cursor)
    db = make_database(col)
    result = run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))

    assert len(result) == 1
    assert isinstance(result[0], Earthquake)
    assert result[0].event_id == doc["event_id"]


# ---------------------------------------------------------------------------
# 44. Query and cursor errors propagate
# ---------------------------------------------------------------------------

def test_count_documents_error_propagates():
    cursor = make_cursor([])
    col = make_collection(cursor=cursor)
    col.count_documents = AsyncMock(side_effect=pymongo.errors.OperationFailure("db error"))
    db = make_database(col)
    with pytest.raises(pymongo.errors.OperationFailure):
        run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))


def test_find_to_list_error_propagates():
    cursor = make_cursor([])
    cursor.to_list = AsyncMock(side_effect=pymongo.errors.OperationFailure("cursor error"))
    col = make_collection(cursor=cursor, count=5)
    db = make_database(col)
    with pytest.raises(pymongo.errors.OperationFailure):
        run(EarthquakeRepository(database=db).list_earthquakes(page=1, page_size=20))


def test_find_by_time_range_to_list_error_propagates():
    t_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_end = datetime(2024, 1, 2, tzinfo=timezone.utc)
    cursor = make_cursor([])
    cursor.to_list = AsyncMock(side_effect=pymongo.errors.OperationFailure("cursor error"))
    col = make_collection(cursor=cursor)
    db = make_database(col)
    with pytest.raises(pymongo.errors.OperationFailure):
        run(EarthquakeRepository(database=db).find_by_time_range(t_start, t_end))
