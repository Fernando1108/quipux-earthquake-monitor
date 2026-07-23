"""Unit tests for app/api/dependencies.py — no DB or HTTP."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.dependencies import get_db, get_earthquake_repository, get_metric_repository, get_report_repository
from app.api.main import app
from app.repositories.earthquake_repository import EarthquakeRepository
from app.repositories.metric_repository import MetricRepository
from app.repositories.report_repository import ReportRepository


# ---------------------------------------------------------------------------
# A. get_db
# ---------------------------------------------------------------------------


def test_get_db_calls_get_database():
    mock_db = MagicMock()
    with patch("app.api.dependencies.get_database", return_value=mock_db) as mock_fn:
        result = get_db()
    mock_fn.assert_called_once_with()
    assert result is mock_db


def test_get_db_returns_exact_database_object():
    mock_db = MagicMock()
    with patch("app.api.dependencies.get_database", return_value=mock_db):
        result = get_db()
    assert result is mock_db


def test_get_db_runtime_error_raises_http_exception():
    from fastapi import HTTPException

    with patch(
        "app.api.dependencies.get_database",
        side_effect=RuntimeError("No active MongoDB connection"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_db()

    assert exc_info.value.status_code == 503


def test_get_db_runtime_error_detail_is_database_unavailable():
    from fastapi import HTTPException

    with patch(
        "app.api.dependencies.get_database",
        side_effect=RuntimeError("No active MongoDB connection"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_db()

    assert exc_info.value.detail == "Database unavailable"


def test_get_db_runtime_error_has_no_chained_cause():
    from fastapi import HTTPException

    with patch(
        "app.api.dependencies.get_database",
        side_effect=RuntimeError("No active MongoDB connection"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            get_db()

    assert exc_info.value.__cause__ is None


def test_get_db_non_runtime_error_propagates_unchanged():
    class CustomError(Exception):
        pass

    with patch(
        "app.api.dependencies.get_database",
        side_effect=CustomError("unexpected"),
    ):
        with pytest.raises(CustomError):
            get_db()


# ---------------------------------------------------------------------------
# B. get_earthquake_repository
# ---------------------------------------------------------------------------


def test_get_earthquake_repository_returns_earthquake_repository_instance():
    mock_db = MagicMock()
    repo = get_earthquake_repository(database=mock_db)
    assert isinstance(repo, EarthquakeRepository)


def test_get_earthquake_repository_passes_injected_db_to_constructor():
    mock_db = MagicMock()
    repo = get_earthquake_repository(database=mock_db)
    assert repo._collection == mock_db["earthquakes"]


def test_get_earthquake_repository_does_not_call_get_db_internally():
    """Repository dependency must use injected database, not call get_db manually."""
    mock_db = MagicMock()
    with patch("app.api.dependencies.get_database") as mock_fn:
        get_earthquake_repository(database=mock_db)
    mock_fn.assert_not_called()


# ---------------------------------------------------------------------------
# C. get_metric_repository
# ---------------------------------------------------------------------------


def test_get_metric_repository_returns_metric_repository_instance():
    mock_db = MagicMock()
    repo = get_metric_repository(database=mock_db)
    assert isinstance(repo, MetricRepository)


def test_get_metric_repository_passes_injected_db_to_constructor():
    mock_db = MagicMock()
    repo = get_metric_repository(database=mock_db)
    assert repo._collection == mock_db["metrics"]


def test_get_metric_repository_does_not_call_get_db_internally():
    """Repository dependency must use injected database, not call get_db manually."""
    mock_db = MagicMock()
    with patch("app.api.dependencies.get_database") as mock_fn:
        get_metric_repository(database=mock_db)
    mock_fn.assert_not_called()


# ---------------------------------------------------------------------------
# D. FastAPI DI chain: overriding get_db propagates to repositories
# ---------------------------------------------------------------------------


def test_get_db_override_propagates_to_earthquake_repository():
    """Override get_db only; the earthquake route must use the overridden database."""
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.find = MagicMock(return_value=mock_cursor)
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_db] = lambda: mock_db
        with TestClient(app) as client:
            response = client.get("/earthquakes")
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.__getitem__.assert_called_with("earthquakes")


def test_get_db_override_propagates_to_metric_repository():
    """Override get_db only; the metrics route must use the overridden database."""
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.find = MagicMock(return_value=mock_cursor)
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_db] = lambda: mock_db
        with TestClient(app) as client:
            response = client.get("/metrics")
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.__getitem__.assert_called_with("metrics")


# ---------------------------------------------------------------------------
# E. get_report_repository
# ---------------------------------------------------------------------------


def test_get_report_repository_returns_report_repository_instance():
    mock_db = MagicMock()
    repo = get_report_repository(database=mock_db)
    assert isinstance(repo, ReportRepository)


def test_get_report_repository_passes_injected_db_to_constructor():
    mock_db = MagicMock()
    repo = get_report_repository(database=mock_db)
    assert repo._collection == mock_db["hourly_reports"]


def test_get_report_repository_does_not_call_get_db_internally():
    """Repository dependency must use injected database, not call get_db manually."""
    mock_db = MagicMock()
    with patch("app.api.dependencies.get_database") as mock_fn:
        get_report_repository(database=mock_db)
    mock_fn.assert_not_called()


def test_get_db_override_propagates_to_report_repository():
    """Override get_db only; the reports route must use the overridden database."""
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_collection.count_documents = AsyncMock(return_value=0)
    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.find = MagicMock(return_value=mock_cursor)
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_db] = lambda: mock_db
        with TestClient(app) as client:
            response = client.get("/reports")
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_db.__getitem__.assert_called_with("hourly_reports")
