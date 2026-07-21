"""MongoDB index definitions to optimise query performance on seismic collections."""

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


async def create_indexes(database: AsyncIOMotorDatabase) -> None:
    """Create all application indexes with explicit, stable names.

    Collections touched: earthquakes, metrics, hourly_reports.
    Safe to call on every startup — MongoDB skips existing indexes with matching
    keys and options.
    """
    earthquakes = database["earthquakes"]

    await earthquakes.create_index(
        [("event_id", ASCENDING)],
        unique=True,
        name="earthquakes_event_id_unique",
    )
    await earthquakes.create_index(
        [("event_time", DESCENDING)],
        name="earthquakes_event_time_desc",
    )
    await earthquakes.create_index(
        [("magnitude", ASCENDING), ("event_time", DESCENDING)],
        name="earthquakes_magnitude_asc_event_time_desc",
    )

    metrics = database["metrics"]

    await metrics.create_index(
        [("window_start", ASCENDING)],
        unique=True,
        name="metrics_window_start_unique",
    )

    hourly_reports = database["hourly_reports"]

    await hourly_reports.create_index(
        [("report_date", ASCENDING)],
        unique=True,
        name="hourly_reports_report_date_unique",
    )

    logger.info("MongoDB indexes created successfully.")
