"""Health check endpoint to verify API and database connectivity status."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    database: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> dict:
    """Return {"status": "ok"} when the database is reachable, 503 otherwise."""
    try:
        await database.command("ping")
    except asyncio.CancelledError:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None
    return {"status": "ok"}
