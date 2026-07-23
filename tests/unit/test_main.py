"""Unit tests for app/api/main.py — lifespan startup order and cleanup semantics."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lifespan_patches(
    connect_effect=None,
    get_db_effect=None,
    indexes_effect=None,
):
    """Return a tuple of patch context managers for lifespan functions."""
    mock_connect = AsyncMock(side_effect=connect_effect)
    mock_db = MagicMock()
    mock_get_db = MagicMock(
        return_value=mock_db,
        side_effect=get_db_effect,
    )
    mock_indexes = AsyncMock(side_effect=indexes_effect)
    mock_close = MagicMock()
    return (
        patch("app.api.main.connect_to_mongodb", mock_connect),
        patch("app.api.main.get_database", mock_get_db),
        patch("app.api.main.create_indexes", mock_indexes),
        patch("app.api.main.close_mongodb_connection", mock_close),
        mock_connect,
        mock_get_db,
        mock_indexes,
        mock_close,
    )


# ---------------------------------------------------------------------------
# A. Root endpoint
# ---------------------------------------------------------------------------


def test_root_returns_200():
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        with TestClient(app) as client:
            response = client.get("/")
    assert response.status_code == 200


def test_root_response_body():
    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        with TestClient(app) as client:
            data = client.get("/").json()
    assert data == {"message": "Quipux Earthquake Monitor"}


# ---------------------------------------------------------------------------
# B. Startup sequence — exact call order
# ---------------------------------------------------------------------------


def test_lifespan_startup_order():
    """Exact order: connect → get_database → create_indexes → yield → close."""
    call_log: list[str] = []

    async def mock_connect():
        call_log.append("connect")

    mock_db = MagicMock()

    def mock_get_database():
        call_log.append("get_database")
        return mock_db

    async def mock_create_indexes(db):
        call_log.append("create_indexes")

    def mock_close():
        call_log.append("close")

    with (
        patch("app.api.main.connect_to_mongodb", mock_connect),
        patch("app.api.main.get_database", mock_get_database),
        patch("app.api.main.create_indexes", mock_create_indexes),
        patch("app.api.main.close_mongodb_connection", mock_close),
    ):
        with TestClient(app):
            call_log.append("app_running")

    assert call_log == [
        "connect",
        "get_database",
        "create_indexes",
        "app_running",
        "close",
    ]


def test_connect_called_once_on_startup():
    mock_connect = AsyncMock()

    with (
        patch("app.api.main.connect_to_mongodb", mock_connect),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection"),
    ):
        with TestClient(app):
            pass

    mock_connect.assert_called_once()


def test_lifespan_passes_active_database_to_create_indexes():
    mock_db = MagicMock()
    mock_create_indexes = AsyncMock()

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=mock_db),
        patch("app.api.main.create_indexes", mock_create_indexes),
        patch("app.api.main.close_mongodb_connection"),
    ):
        with TestClient(app):
            pass

    mock_create_indexes.assert_called_once_with(mock_db)


# ---------------------------------------------------------------------------
# C. Cleanup semantics — close runs in all outcomes
# ---------------------------------------------------------------------------


def test_close_called_on_normal_shutdown():
    mock_close = MagicMock()

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch("app.api.main.create_indexes", new_callable=AsyncMock),
        patch("app.api.main.close_mongodb_connection", mock_close),
    ):
        with TestClient(app):
            pass

    mock_close.assert_called_once()


def test_close_called_when_connect_fails():
    mock_close = MagicMock()

    with (
        patch(
            "app.api.main.connect_to_mongodb",
            AsyncMock(side_effect=RuntimeError("connect failed")),
        ),
        patch("app.api.main.close_mongodb_connection", mock_close),
    ):
        with pytest.raises(Exception):
            with TestClient(app):
                pass

    mock_close.assert_called_once()


def test_close_called_when_get_database_fails():
    mock_close = MagicMock()

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch(
            "app.api.main.get_database",
            side_effect=RuntimeError("no active connection"),
        ),
        patch("app.api.main.close_mongodb_connection", mock_close),
    ):
        with pytest.raises(Exception):
            with TestClient(app):
                pass

    mock_close.assert_called_once()


def test_close_called_when_create_indexes_fails():
    mock_close = MagicMock()

    with (
        patch("app.api.main.connect_to_mongodb", new_callable=AsyncMock),
        patch("app.api.main.get_database", return_value=MagicMock()),
        patch(
            "app.api.main.create_indexes",
            AsyncMock(side_effect=RuntimeError("index creation failed")),
        ),
        patch("app.api.main.close_mongodb_connection", mock_close),
    ):
        with pytest.raises(Exception):
            with TestClient(app):
                pass

    mock_close.assert_called_once()


def test_startup_exception_propagates():
    with (
        patch(
            "app.api.main.connect_to_mongodb",
            AsyncMock(side_effect=RuntimeError("startup failed")),
        ),
        patch("app.api.main.close_mongodb_connection"),
    ):
        with pytest.raises(RuntimeError, match="startup failed"):
            with TestClient(app):
                pass
