"""Unit tests for GET /metrics — no DB, no HTTP over the wire."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_metric_repository
from app.api.main import app
from app.models.metric import MagnitudeDistribution, Metric

UTC = timezone.utc
WINDOW_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)
LATER_TIME = datetime(2024, 6, 1, 14, 0, 0, tzinfo=UTC)

_EMPTY_DIST = MagnitudeDistribution(
    under_2=0,
    from_2_to_under_4=0,
    from_4_to_under_5=0,
    from_5_to_under_6=0,
    six_or_more=0,
    unknown=0,
)


def make_metric(**overrides) -> Metric:
    defaults = dict(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        earthquake_count=0,
        magnitude_count=0,
        magnitude_sum=0.0,
        average_magnitude=None,
        max_magnitude=None,
        magnitude_distribution=_EMPTY_DIST,
        updated_at=WINDOW_START,
    )
    defaults.update(overrides)
    return Metric(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo() -> AsyncMock:
    mock = AsyncMock()
    mock.list_metrics.return_value = ([], 0)
    return mock


@pytest.fixture
def client(mock_repo: AsyncMock):
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_metric_repository] = lambda: mock_repo
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Response shape
# ---------------------------------------------------------------------------


def test_list_metrics_returns_200(client):
    assert client.get("/metrics").status_code == 200


def test_list_metrics_response_has_required_fields(client):
    data = client.get("/metrics").json()
    assert set(data.keys()) == {"items", "page", "page_size", "total", "total_pages"}


def test_list_metrics_empty_by_default(client):
    data = client.get("/metrics").json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 0


def test_list_metrics_serialises_metric_items(client, mock_repo):
    metric = make_metric()
    mock_repo.list_metrics.return_value = ([metric], 1)
    data = client.get("/metrics").json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["total_pages"] == 1


# ---------------------------------------------------------------------------
# B. Default parameters forwarded to repo
# ---------------------------------------------------------------------------


def test_repo_called_once_per_request(client, mock_repo):
    client.get("/metrics")
    mock_repo.list_metrics.assert_called_once()


def test_repo_called_with_default_page(client, mock_repo):
    client.get("/metrics")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["page"] == 1


def test_repo_called_with_default_page_size(client, mock_repo):
    client.get("/metrics")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["page_size"] == 20


def test_repo_called_with_sort_descending_true_by_default(client, mock_repo):
    client.get("/metrics")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["sort_descending"] is True


def test_repo_called_with_no_time_filters_by_default(client, mock_repo):
    client.get("/metrics")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["start_time"] is None
    assert kwargs["end_time"] is None


# ---------------------------------------------------------------------------
# C. Time filter params forwarded to repo
# ---------------------------------------------------------------------------


def test_start_time_forwarded_to_repo(client, mock_repo):
    client.get("/metrics?start_time=2024-06-01T12:00:00Z")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["start_time"] == WINDOW_START


def test_end_time_forwarded_to_repo(client, mock_repo):
    client.get("/metrics?end_time=2024-06-01T14:00:00Z")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["end_time"] == LATER_TIME


# ---------------------------------------------------------------------------
# D. Pagination params
# ---------------------------------------------------------------------------


def test_custom_page_forwarded_to_repo(client, mock_repo):
    client.get("/metrics?page=2")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["page"] == 2


def test_custom_page_size_forwarded_to_repo(client, mock_repo):
    client.get("/metrics?page_size=10")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["page_size"] == 10


def test_pagination_reflected_in_response(client, mock_repo):
    data = client.get("/metrics?page=2&page_size=5").json()
    assert data["page"] == 2
    assert data["page_size"] == 5


# ---------------------------------------------------------------------------
# E. Sort order
# ---------------------------------------------------------------------------


def test_sort_asc_sets_sort_descending_false(client, mock_repo):
    client.get("/metrics?sort=asc")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["sort_descending"] is False


def test_sort_desc_sets_sort_descending_true(client, mock_repo):
    client.get("/metrics?sort=desc")
    _, kwargs = mock_repo.list_metrics.call_args
    assert kwargs["sort_descending"] is True


# ---------------------------------------------------------------------------
# F. Invalid query params → 422
# ---------------------------------------------------------------------------


def test_page_zero_returns_422(client):
    assert client.get("/metrics?page=0").status_code == 422


def test_page_size_too_large_returns_422(client):
    assert client.get("/metrics?page_size=101").status_code == 422


def test_invalid_sort_value_returns_422(client):
    assert client.get("/metrics?sort=ascending").status_code == 422


def test_start_after_end_time_returns_422(client):
    assert (
        client.get(
            "/metrics?start_time=2024-06-01T13:00:00Z&end_time=2024-06-01T12:00:00Z"
        ).status_code
        == 422
    )


def test_magnitude_field_rejected_by_metrics_endpoint(client):
    assert client.get("/metrics?min_magnitude=2.5").status_code == 422


# ---------------------------------------------------------------------------
# G. Repository exception propagates as 500
# ---------------------------------------------------------------------------


def test_repo_exception_returns_500(mock_repo):
    mock_repo.list_metrics.side_effect = RuntimeError("DB exploded")
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_metric_repository] = lambda: mock_repo
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/metrics")
        app.dependency_overrides.clear()
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# H. Datetime string validation (Issue 1 — naive strings reach HTTP layer)
# ---------------------------------------------------------------------------


def test_naive_datetime_string_start_time_returns_422(client):
    """Naive ISO strings must be rejected with 422, not silently accepted."""
    assert client.get("/metrics?start_time=2026-07-22T10:00:00").status_code == 422


def test_naive_datetime_string_end_time_returns_422(client):
    assert client.get("/metrics?end_time=2026-07-22T10:00:00").status_code == 422


def test_no_repo_call_when_start_time_validation_fails(client, mock_repo):
    client.get("/metrics?start_time=2026-07-22T10:00:00")
    mock_repo.list_metrics.assert_not_called()


def test_offset_start_time_normalized_to_utc_in_repo_call(client, mock_repo):
    """Offset-aware datetime string must reach the repo normalized to UTC."""
    # "2026-07-22T15:00:00+05:00" → UTC 2026-07-22T10:00:00Z
    client.get(
        "/metrics",
        params={"start_time": "2026-07-22T15:00:00+05:00"},
    )
    _, kwargs = mock_repo.list_metrics.call_args
    from datetime import timezone as _tz
    expected_utc = datetime(2026, 7, 22, 10, 0, 0, tzinfo=_tz.utc)
    assert kwargs["start_time"] == expected_utc
