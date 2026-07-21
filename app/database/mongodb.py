"""MongoDB connection lifecycle management using Motor async client."""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config.settings import Settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None


async def connect_to_mongodb() -> None:
    """Open the Motor client, verify connectivity with a ping, and store state.

    On ping failure: closes only the new client; prior connection (if any) is
    preserved intact and the original exception is propagated.
    On ping success: registers the new client/database and closes the prior
    client if one existed.
    """
    global _client, _database

    prior_client = _client
    prior_database = _database

    settings = Settings()
    new_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_uri)

    try:
        await new_client.admin.command("ping")
    except Exception:
        new_client.close()
        _client = prior_client
        _database = prior_database
        raise

    _client = new_client
    _database = new_client[settings.mongo_database]
    logger.info("Connected to MongoDB database '%s'.", settings.mongo_database)

    if prior_client is not None and prior_client is not new_client:
        prior_client.close()


def get_database() -> AsyncIOMotorDatabase:
    """Return the active database instance.

    Raises:
        RuntimeError: if connect_to_mongodb() has not been called yet.
    """
    if _database is None:
        raise RuntimeError(
            "No active MongoDB connection. Call connect_to_mongodb() first."
        )
    return _database


def close_mongodb_connection() -> None:
    """Close the Motor client and reset module state. Safe to call multiple times."""
    global _client, _database

    if _client is not None:
        _client.close()
        logger.info("MongoDB connection closed.")

    _client = None
    _database = None
