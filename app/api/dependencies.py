"""FastAPI dependency injection definitions for shared resources such as database and settings."""

from typing import Annotated

from fastapi import Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database
from app.repositories.earthquake_repository import EarthquakeRepository
from app.repositories.metric_repository import MetricRepository


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database, or raise HTTP 503 if none is registered."""
    try:
        return get_database()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None


def get_earthquake_repository(
    database: Annotated[
        AsyncIOMotorDatabase,
        Depends(get_db),
    ],
) -> EarthquakeRepository:
    """Return an EarthquakeRepository bound to the active database."""
    return EarthquakeRepository(database=database)


def get_metric_repository(
    database: Annotated[
        AsyncIOMotorDatabase,
        Depends(get_db),
    ],
) -> MetricRepository:
    """Return a MetricRepository bound to the active database."""
    return MetricRepository(database=database)
