from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.earthquakes import router as earthquakes_router
from app.api.routes.health import router as health_router
from app.api.routes.metrics import router as metrics_router
from app.config.logging import configure_logging
from app.config.settings import Settings
from app.database.indexes import create_indexes
from app.database.mongodb import (
    close_mongodb_connection,
    connect_to_mongodb,
    get_database,
)

configure_logging()

settings = Settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await connect_to_mongodb()
        database = get_database()
        await create_indexes(database)
        yield
    finally:
        close_mongodb_connection()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health_router)
app.include_router(earthquakes_router)
app.include_router(metrics_router)


@app.get("/")
async def root() -> dict:
    return {"message": "Quipux Earthquake Monitor"}
