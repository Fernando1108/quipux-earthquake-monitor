"""Unit tests for GET /health — uses dependency overrides, no DB, no network."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_db
from app.api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _no_mongo():
    """Prevent lifespan from touching MongoDB."""
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        yield


@pytest.fixture
def healthy_db() -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.command = AsyncMock(return_value={"ok": 1})
    return mock_db


# ---------------------------------------------------------------------------
# A. Healthy DB → 200
# ---------------------------------------------------------------------------


def test_health_returns_200_when_db_ok(_no_mongo, healthy_db):
    app.dependency_overrides[get_db] = lambda: healthy_db
    with TestClient(app) as client:
        response = client.get("/health")
    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_health_response_body_when_ok(_no_mongo, healthy_db):
    app.dependency_overrides[get_db] = lambda: healthy_db
    with TestClient(app) as client:
        data = client.get("/health").json()
    app.dependency_overrides.clear()
    assert data == {"status": "ok"}


# ---------------------------------------------------------------------------
# B. Ping failure → 503
# ---------------------------------------------------------------------------


def test_health_returns_503_when_ping_fails(_no_mongo):
    mock_db = AsyncMock()
    mock_db.command = AsyncMock(side_effect=Exception("ping timeout"))
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        response = client.get("/health")
    app.dependency_overrides.clear()
    assert response.status_code == 503


def test_health_response_detail_when_ping_fails(_no_mongo):
    mock_db = AsyncMock()
    mock_db.command = AsyncMock(side_effect=Exception("ping timeout"))
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as client:
        data = client.get("/health").json()
    app.dependency_overrides.clear()
    assert data["detail"] == "Database unavailable"


def test_health_ping_uses_database_command(_no_mongo, healthy_db):
    app.dependency_overrides[get_db] = lambda: healthy_db
    with TestClient(app) as client:
        client.get("/health")
    app.dependency_overrides.clear()
    healthy_db.command.assert_called_once_with("ping")


# ---------------------------------------------------------------------------
# C. Missing registered database → dependency-level 503
# ---------------------------------------------------------------------------


def test_health_returns_503_when_no_database_registered(_no_mongo):
    """RuntimeError from get_database() inside get_db() must resolve to HTTP 503.

    get_db is NOT overridden here; the real get_db runs and converts the
    RuntimeError to HTTPException(503) before health_check() is entered.
    """
    with patch(
        "app.api.dependencies.get_database",
        side_effect=RuntimeError("No active MongoDB connection"),
    ):
        with TestClient(app) as client:
            response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


# ---------------------------------------------------------------------------
# D. CancelledError propagates (not caught by except Exception)
# ---------------------------------------------------------------------------


def test_health_cancelled_error_propagates():
    """CancelledError is BaseException, not Exception; must not be swallowed."""

    async def _inner() -> None:
        mock_db = AsyncMock()
        mock_db.command = AsyncMock(side_effect=asyncio.CancelledError())
        from app.api.routes.health import health_check

        with pytest.raises(asyncio.CancelledError):
            await health_check(database=mock_db)

    asyncio.run(_inner())
