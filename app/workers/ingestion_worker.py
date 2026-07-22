"""Periodic worker that executes IngestionService on a fixed interval."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.config.logging import configure_logging
from app.config.settings import Settings
from app.database.indexes import create_indexes
from app.database.mongodb import (
    close_mongodb_connection,
    connect_to_mongodb,
    get_database,
)
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

SleepCallable = Callable[[float], Awaitable[None]]


class IngestionWorker:
    """Run IngestionService.run_once on a fixed interval forever."""

    def __init__(
        self,
        service: IngestionService,
        interval_seconds: int,
        sleep_func: SleepCallable | None = None,
    ) -> None:
        if isinstance(interval_seconds, bool):
            raise ValueError("interval_seconds must be an int, got bool")
        if not isinstance(interval_seconds, int):
            raise ValueError(
                f"interval_seconds must be an int, got {type(interval_seconds).__name__}"
            )
        if interval_seconds <= 0:
            raise ValueError(
                f"interval_seconds must be greater than zero, got {interval_seconds}"
            )
        self._service = service
        self._interval_seconds = interval_seconds
        self._sleep_func: SleepCallable = (
            sleep_func if sleep_func is not None else asyncio.sleep
        )

    async def run_forever(self) -> None:
        """Loop: run one iteration, sleep the configured interval, repeat."""
        logger.info(
            "IngestionWorker starting; interval_seconds=%d.",
            self._interval_seconds,
        )
        while True:
            try:
                await self._service.run_once()
            except Exception:
                logger.exception(
                    "Ingestion iteration failed. Retrying after %d seconds.",
                    self._interval_seconds,
                )
            await self._sleep_func(self._interval_seconds)


async def main() -> None:
    """Configure logging, connect to MongoDB, build the worker, and run forever."""
    configure_logging()
    settings = Settings()
    try:
        await connect_to_mongodb()
        database = get_database()
        await create_indexes(database)
        service = IngestionService()
        worker = IngestionWorker(service, settings.ingestion_interval_seconds)
        await worker.run_forever()
    finally:
        close_mongodb_connection()


if __name__ == "__main__":
    asyncio.run(main())
