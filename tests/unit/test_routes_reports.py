"""Unit tests for GET /reports — no DB, no HTTP over the wire."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_report_repository
from app.api.main import app
from app.models.report import Report, TopLocation

UTC = timezone.utc
PERIOD_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(hours=1)
GENERATED_AT = PERIOD_END
LATER_TIME = datetime(2024, 6, 1, 14, 0, 0, tzinfo=UTC)


def make_report(**overrides) -> Report:
    defaults = dict(
        report_date=PERIOD_END,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        generated_at=GENERATED_AT,
        total_events=0,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[],
    )
    defaults.update(overrides)
    return Report(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo() -> AsyncMock:
    mock = AsyncMock()
    mock.list_reports.return_value = ([], 0)
    return mock


@pytest.fixture
def client(mock_repo: AsyncMock):
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_report_repository] = lambda: mock_repo
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# A. Response shape
# ---------------------------------------------------------------------------


def test_list_reports_returns_200(client):
    assert client.get("/reports").status_code == 200


def test_list_reports_response_has_required_fields(client):
    data = client.get("/reports").json()
    assert set(data.keys()) == {"items", "page", "page_size", "total", "total_pages"}


def test_list_reports_empty_result(client):
    data = client.get("/reports").json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 0


def test_list_reports_serialises_report_item(client, mock_repo):
    report = make_report()
    mock_repo.list_reports.return_value = ([report], 1)
    data = client.get("/reports").json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["total_pages"] == 1


def test_list_reports_serialises_top_locations(client, mock_repo):
    loc = TopLocation(location="Lima", count=3)
    report = make_report(
        total_events=3,
        events_with_magnitude=0,
        top_locations=[loc],
    )
    mock_repo.list_reports.return_value = ([report], 1)
    data = client.get("/reports").json()
    assert data["items"][0]["top_locations"] == [{"location": "Lima", "count": 3}]


def test_list_reports_full_serialisation(client, mock_repo):
    report = make_report(
        total_events=5,
        events_with_magnitude=5,
        average_magnitude=3.5,
        max_magnitude=5.0,
        top_locations=[TopLocation(location="Cusco", count=2)],
    )
    mock_repo.list_reports.return_value = ([report], 1)
    data = client.get("/reports").json()
    item = data["items"][0]
    assert item["total_events"] == 5
    assert item["events_with_magnitude"] == 5
    assert item["average_magnitude"] == pytest.approx(3.5)
    assert item["max_magnitude"] == pytest.approx(5.0)
    assert item["top_locations"][0]["location"] == "Cusco"


# ---------------------------------------------------------------------------
# B. Default parameters forwarded to repo
# ---------------------------------------------------------------------------


def test_repo_called_once_per_request(client, mock_repo):
    client.get("/reports")
    mock_repo.list_reports.assert_called_once()


def test_repo_called_with_default_page(client, mock_repo):
    client.get("/reports")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["page"] == 1


def test_repo_called_with_default_page_size(client, mock_repo):
    client.get("/reports")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["page_size"] == 20


def test_repo_called_with_sort_descending_true_by_default(client, mock_repo):
    client.get("/reports")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["sort_descending"] is True


def test_repo_called_with_no_time_filters_by_default(client, mock_repo):
    client.get("/reports")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["start_time"] is None
    assert kwargs["end_time"] is None


# ---------------------------------------------------------------------------
# C. Custom parameters forwarded to repo
# ---------------------------------------------------------------------------


def test_custom_page_forwarded_to_repo(client, mock_repo):
    client.get("/reports?page=3")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["page"] == 3


def test_custom_page_size_forwarded_to_repo(client, mock_repo):
    client.get("/reports?page_size=5")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["page_size"] == 5


def test_sort_asc_sets_sort_descending_false(client, mock_repo):
    client.get("/reports?sort=asc")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["sort_descending"] is False


def test_sort_desc_sets_sort_descending_true(client, mock_repo):
    client.get("/reports?sort=desc")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["sort_descending"] is True


def test_start_time_forwarded_to_repo(client, mock_repo):
    client.get("/reports?start_time=2024-06-01T12:00:00Z")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["start_time"] == PERIOD_START


def test_end_time_forwarded_to_repo(client, mock_repo):
    client.get("/reports?end_time=2024-06-01T14:00:00Z")
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["end_time"] == LATER_TIME


def test_offset_start_time_normalized_to_utc(client, mock_repo):
    client.get(
        "/reports",
        params={"start_time": "2024-06-01T17:00:00+05:00"},
    )
    _, kwargs = mock_repo.list_reports.call_args
    assert kwargs["start_time"] == PERIOD_START


def test_pagination_reflected_in_response(client, mock_repo):
    data = client.get("/reports?page=2&page_size=5").json()
    assert data["page"] == 2
    assert data["page_size"] == 5


# ---------------------------------------------------------------------------
# D. Validation — 422
# ---------------------------------------------------------------------------


def test_page_zero_returns_422(client):
    assert client.get("/reports?page=0").status_code == 422


def test_page_size_too_large_returns_422(client):
    assert client.get("/reports?page_size=101").status_code == 422


def test_invalid_sort_value_returns_422(client):
    assert client.get("/reports?sort=ascending").status_code == 422


def test_start_after_end_time_returns_422(client):
    assert (
        client.get(
            "/reports?start_time=2024-06-01T13:00:00Z&end_time=2024-06-01T12:00:00Z"
        ).status_code
        == 422
    )


def test_naive_datetime_start_time_returns_422(client):
    assert client.get("/reports?start_time=2024-06-01T12:00:00").status_code == 422


def test_naive_datetime_end_time_returns_422(client):
    assert client.get("/reports?end_time=2024-06-01T12:00:00").status_code == 422


def test_min_magnitude_rejected(client):
    assert client.get("/reports?min_magnitude=2.5").status_code == 422


def test_repo_not_called_when_validation_fails(client, mock_repo):
    client.get("/reports?page=0")
    mock_repo.list_reports.assert_not_called()


# ---------------------------------------------------------------------------
# E. Errors
# ---------------------------------------------------------------------------


def test_repo_exception_returns_500(mock_repo):
    mock_repo.list_reports.side_effect = RuntimeError("DB exploded")
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        app.dependency_overrides[get_report_repository] = lambda: mock_repo
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/reports")
        app.dependency_overrides.clear()
    assert response.status_code == 500


def test_database_unavailable_returns_503():
    from app.api.dependencies import get_db
    from fastapi import HTTPException

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        def raise_503():
            raise HTTPException(status_code=503, detail="Database unavailable")

        app.dependency_overrides[get_db] = raise_503
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/reports")
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
