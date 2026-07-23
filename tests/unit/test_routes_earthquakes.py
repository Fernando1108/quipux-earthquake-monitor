"""Unit tests for GET /earthquakes — no DB, no HTTP over the wire."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_earthquake_repository
from app.api.main import app
from app.models.earthquake import Earthquake

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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo() -> AsyncMock:
    mock = AsyncMock()
    mock.list_earthquakes.return_value = ([], 0)
    return mock


@pytest.fixture
def client(mock_repo: AsyncMock):
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_earthquake_repository] = lambda: mock_repo
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Response shape
# ---------------------------------------------------------------------------


def test_list_earthquakes_returns_200(client):
    response = client.get("/earthquakes")
    assert response.status_code == 200


def test_list_earthquakes_response_has_required_fields(client):
    data = client.get("/earthquakes").json()
    assert set(data.keys()) == {"items", "page", "page_size", "total", "total_pages"}


def test_list_earthquakes_empty_items_by_default(client):
    data = client.get("/earthquakes").json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 0


def test_list_earthquakes_serialises_earthquake_items(client, mock_repo):
    eq = make_earthquake()
    mock_repo.list_earthquakes.return_value = ([eq], 1)
    data = client.get("/earthquakes").json()
    assert len(data["items"]) == 1
    assert data["items"][0]["event_id"] == "us7000test"
    assert data["total"] == 1
    assert data["total_pages"] == 1


# ---------------------------------------------------------------------------
# B. Default parameters forwarded to repo
# ---------------------------------------------------------------------------


def test_repo_called_once_per_request(client, mock_repo):
    client.get("/earthquakes")
    mock_repo.list_earthquakes.assert_called_once()


def test_repo_called_with_default_page(client, mock_repo):
    client.get("/earthquakes")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["page"] == 1


def test_repo_called_with_default_page_size(client, mock_repo):
    client.get("/earthquakes")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["page_size"] == 20


def test_repo_called_with_sort_descending_true_by_default(client, mock_repo):
    client.get("/earthquakes")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["sort_descending"] is True


def test_repo_called_with_no_filters_by_default(client, mock_repo):
    client.get("/earthquakes")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["min_magnitude"] is None
    assert kwargs["max_magnitude"] is None
    assert kwargs["start_time"] is None
    assert kwargs["end_time"] is None


# ---------------------------------------------------------------------------
# C. Filter params forwarded to repo
# ---------------------------------------------------------------------------


def test_min_magnitude_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?min_magnitude=2.5")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["min_magnitude"] == pytest.approx(2.5)


def test_max_magnitude_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?max_magnitude=5.0")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["max_magnitude"] == pytest.approx(5.0)


def test_both_magnitudes_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?min_magnitude=1.0&max_magnitude=4.0")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["min_magnitude"] == pytest.approx(1.0)
    assert kwargs["max_magnitude"] == pytest.approx(4.0)


def test_start_time_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?start_time=2024-06-01T12:00:00Z")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["start_time"] == FIXED_TIME


def test_end_time_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?end_time=2024-06-01T13:00:00Z")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["end_time"] == LATER_TIME


# ---------------------------------------------------------------------------
# D. Pagination params
# ---------------------------------------------------------------------------


def test_custom_page_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?page=3")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["page"] == 3


def test_custom_page_size_forwarded_to_repo(client, mock_repo):
    client.get("/earthquakes?page_size=50")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["page_size"] == 50


def test_pagination_reflected_in_response(client, mock_repo):
    mock_repo.list_earthquakes.return_value = ([], 0)
    data = client.get("/earthquakes?page=2&page_size=5").json()
    assert data["page"] == 2
    assert data["page_size"] == 5


# ---------------------------------------------------------------------------
# E. Sort order
# ---------------------------------------------------------------------------


def test_sort_asc_sets_sort_descending_false(client, mock_repo):
    client.get("/earthquakes?sort=asc")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["sort_descending"] is False


def test_sort_desc_sets_sort_descending_true(client, mock_repo):
    client.get("/earthquakes?sort=desc")
    _, kwargs = mock_repo.list_earthquakes.call_args
    assert kwargs["sort_descending"] is True


# ---------------------------------------------------------------------------
# F. Invalid query params → 422
# ---------------------------------------------------------------------------


def test_page_zero_returns_422(client):
    assert client.get("/earthquakes?page=0").status_code == 422


def test_page_size_too_large_returns_422(client):
    assert client.get("/earthquakes?page_size=101").status_code == 422


def test_invalid_sort_value_returns_422(client):
    assert client.get("/earthquakes?sort=ascending").status_code == 422


def test_min_gt_max_magnitude_returns_422(client):
    assert client.get("/earthquakes?min_magnitude=5.0&max_magnitude=2.0").status_code == 422


def test_start_after_end_time_returns_422(client):
    assert (
        client.get(
            "/earthquakes?start_time=2024-06-01T13:00:00Z&end_time=2024-06-01T12:00:00Z"
        ).status_code
        == 422
    )


def test_magnitude_field_rejects_non_numeric_string(client):
    assert client.get("/earthquakes?min_magnitude=abc").status_code == 422


# ---------------------------------------------------------------------------
# G. Repository exception propagates as 500
# ---------------------------------------------------------------------------


def test_repo_exception_returns_500(mock_repo):
    mock_repo.list_earthquakes.side_effect = RuntimeError("DB exploded")
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_earthquake_repository] = lambda: mock_repo
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/earthquakes")
        app.dependency_overrides.clear()
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# H. Datetime string validation (Issue 1 — naive strings reach HTTP layer)
# ---------------------------------------------------------------------------


def test_naive_datetime_string_start_time_returns_422(client):
    """Naive ISO strings must be rejected with 422, not silently accepted."""
    assert client.get("/earthquakes?start_time=2026-07-22T10:00:00").status_code == 422


def test_naive_datetime_string_end_time_returns_422(client):
    assert client.get("/earthquakes?end_time=2026-07-22T10:00:00").status_code == 422


def test_no_repo_call_when_start_time_validation_fails(client, mock_repo):
    client.get("/earthquakes?start_time=2026-07-22T10:00:00")
    mock_repo.list_earthquakes.assert_not_called()


def test_offset_start_time_normalized_to_utc_in_repo_call(client, mock_repo):
    """Offset-aware datetime string must reach the repo normalized to UTC."""
    # "2026-07-22T15:00:00+05:00" → UTC 2026-07-22T10:00:00Z
    client.get(
        "/earthquakes",
        params={"start_time": "2026-07-22T15:00:00+05:00"},
    )
    _, kwargs = mock_repo.list_earthquakes.call_args
    expected_utc = datetime(2026, 7, 22, 10, 0, 0, tzinfo=UTC)
    assert kwargs["start_time"] == expected_utc


# ---------------------------------------------------------------------------
# I. Dependency-level 503 when database not registered
# ---------------------------------------------------------------------------


def test_earthquakes_returns_503_when_database_not_registered():
    """RuntimeError from get_database() in get_db() → HTTP 503 for /earthquakes."""
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
        patch(
            "app.api.dependencies.get_database",
            side_effect=RuntimeError("No active MongoDB connection"),
        ),
    ):
        with TestClient(app) as client:
            response = client.get("/earthquakes")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
