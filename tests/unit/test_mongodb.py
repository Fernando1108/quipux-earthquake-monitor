"""Unit tests for app.database.mongodb connection lifecycle."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.database.mongodb as mongodb_module
from app.database.mongodb import (
    connect_to_mongodb,
    close_mongodb_connection,
    get_database,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def reset_state() -> None:
    mongodb_module._client = None
    mongodb_module._database = None


@pytest.fixture(autouse=True)
def clean_state():
    reset_state()
    yield
    reset_state()


def make_mock_client(ping_raises: Exception | None = None):
    """Return a mock AsyncIOMotorClient with a controllable ping."""
    mock_db = MagicMock()
    mock_admin = MagicMock()

    if ping_raises is not None:
        mock_admin.command = AsyncMock(side_effect=ping_raises)
    else:
        mock_admin.command = AsyncMock(return_value={"ok": 1})

    mock_client = MagicMock()
    mock_client.admin = mock_admin
    mock_client.__getitem__ = MagicMock(return_value=mock_db)

    return mock_client


# ---------------------------------------------------------------------------
# connect_to_mongodb — success path
# ---------------------------------------------------------------------------

def test_connect_stores_client_and_database():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    assert mongodb_module._client is mock_client
    assert mongodb_module._database is not None


def test_connect_uses_configured_database_name():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client), \
         patch("app.database.mongodb.Settings") as mock_settings_cls:
        mock_settings_cls.return_value.mongo_uri = "mongodb://localhost:27017"
        mock_settings_cls.return_value.mongo_database = "test_db"
        run(connect_to_mongodb())

    mock_client.__getitem__.assert_called_once_with("test_db")


def test_connect_executes_ping():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    mock_client.admin.command.assert_awaited_once_with("ping")


# ---------------------------------------------------------------------------
# connect_to_mongodb — ping failure
# ---------------------------------------------------------------------------

def test_connect_ping_failure_propagates_exception():
    error = ConnectionError("unreachable")
    mock_client = make_mock_client(ping_raises=error)

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        with pytest.raises(ConnectionError, match="unreachable"):
            run(connect_to_mongodb())


def test_connect_ping_failure_closes_client():
    mock_client = make_mock_client(ping_raises=ConnectionError("fail"))

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    mock_client.close.assert_called_once()


def test_connect_ping_failure_clears_state():
    """First-ever connection failure must leave state as None."""
    mock_client = make_mock_client(ping_raises=ConnectionError("fail"))

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    assert mongodb_module._client is None
    assert mongodb_module._database is None


# ---------------------------------------------------------------------------
# connect_to_mongodb — reconnection behaviour
# ---------------------------------------------------------------------------

def test_reconnect_success_closes_prior_client_exactly_once():
    old_client = make_mock_client()
    new_client = make_mock_client()
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())   # first: sets old_client
        run(connect_to_mongodb())   # second: sets new_client, closes old_client

    old_client.close.assert_called_once()


def test_reconnect_success_registers_new_client_and_database():
    old_client = make_mock_client()
    new_client = make_mock_client()
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())
        run(connect_to_mongodb())

    assert mongodb_module._client is new_client
    assert mongodb_module._database is new_client.__getitem__.return_value


def test_reconnect_failure_closes_new_client():
    old_client = make_mock_client()
    new_client = make_mock_client(ping_raises=ConnectionError("new fail"))
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    new_client.close.assert_called_once()


def test_reconnect_failure_preserves_prior_client():
    old_client = make_mock_client()
    new_client = make_mock_client(ping_raises=ConnectionError("new fail"))
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    assert mongodb_module._client is old_client


def test_reconnect_failure_preserves_prior_database():
    old_client = make_mock_client()
    prior_db = old_client.__getitem__.return_value
    new_client = make_mock_client(ping_raises=ConnectionError("new fail"))
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    assert mongodb_module._database is prior_db


def test_reconnect_failure_does_not_close_prior_client():
    old_client = make_mock_client()
    new_client = make_mock_client(ping_raises=ConnectionError("new fail"))
    clients = iter([old_client, new_client])

    with patch("app.database.mongodb.AsyncIOMotorClient", side_effect=clients):
        run(connect_to_mongodb())
        with pytest.raises(ConnectionError):
            run(connect_to_mongodb())

    old_client.close.assert_not_called()


# ---------------------------------------------------------------------------
# get_database
# ---------------------------------------------------------------------------

def test_get_database_returns_database_when_connected():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    db = get_database()
    assert db is mock_client.__getitem__.return_value


def test_get_database_raises_when_not_connected():
    with pytest.raises(RuntimeError, match="No active MongoDB connection"):
        get_database()


# ---------------------------------------------------------------------------
# close_mongodb_connection
# ---------------------------------------------------------------------------

def test_close_calls_client_close():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    close_mongodb_connection()

    mock_client.close.assert_called_once()


def test_close_clears_state():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    close_mongodb_connection()

    assert mongodb_module._client is None
    assert mongodb_module._database is None


def test_close_idempotent_when_not_connected():
    close_mongodb_connection()
    close_mongodb_connection()


def test_close_idempotent_after_close():
    mock_client = make_mock_client()

    with patch("app.database.mongodb.AsyncIOMotorClient", return_value=mock_client):
        run(connect_to_mongodb())

    close_mongodb_connection()
    close_mongodb_connection()

    assert mongodb_module._client is None
