"""Airflow DAG that schedules the hourly seismic report generation task."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone

from airflow.sdk import DAG, get_current_context, task

from app.config.logging import configure_logging
from app.database.indexes import create_indexes
from app.database.mongodb import (
    close_mongodb_connection,
    connect_to_mongodb,
    get_database,
)
from app.repositories.earthquake_repository import EarthquakeRepository
from app.repositories.report_repository import ReportRepository
from app.services.reporting_service import ReportingService

logger = logging.getLogger(__name__)

DAG_ID = "hourly_report_dag"
TASK_ID = "generate_hourly_report"
SCHEDULE = "0 * * * *"
UTC = timezone.utc


# ---------------------------------------------------------------------------
# Private helpers — no I/O
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


def _to_plain_utc_datetime(value: object, field_name: str) -> datetime:
    """Convert any aware datetime (including Pendulum subclasses) to a plain built-in UTC datetime.

    Airflow provides context values as pendulum.DateTime instances.  Arithmetic
    on those objects (e.g. subtracting timedelta) can silently drop timezone
    information in certain Pendulum versions, causing downstream Pydantic
    validation to reject the result.  This helper strips the subclass and
    returns an exact datetime.datetime so the application domain layer only
    ever receives standard library types.

    Contract:
    - Requires value to be a datetime instance.
    - Rejects naive datetimes.
    - Normalizes the instant to UTC.
    - Returns type(result) is datetime (never a subclass).
    - Preserves year, month, day, hour, minute, second, microsecond, fold.
    - Uses datetime.timezone.utc exclusively.
    """
    if not isinstance(value, datetime):
        raise ValueError(
            f"{field_name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    normalized = value.astimezone(UTC)
    return datetime(
        normalized.year,
        normalized.month,
        normalized.day,
        normalized.hour,
        normalized.minute,
        normalized.second,
        normalized.microsecond,
        tzinfo=UTC,
        fold=getattr(normalized, "fold", 0),
    )


def _resolve_report_date(
    context: Mapping[str, object],
    now_provider: Callable[[], datetime] = _utc_now,
) -> datetime:
    """Resolve report_date from Airflow task context as a plain built-in UTC datetime.

    Resolution order:
    1. data_interval_end — authoritative end of the scheduled hour; must already
       be aligned to an exact UTC hour (not silently repaired).
    2. logical_date — normalized to UTC and floored to the nearest UTC hour.
    3. now_provider() — normalized to UTC and floored to the nearest UTC hour.

    The returned value equals period_end for the report.
    ReportingService computes period_start = report_date - 1h internally.

    All context datetime values are converted through _to_plain_utc_datetime so
    that Airflow-specific subclasses (e.g. pendulum.DateTime) never reach the
    application domain layer.
    """
    data_interval_end = context.get("data_interval_end")
    if data_interval_end is not None:
        plain = _to_plain_utc_datetime(data_interval_end, "data_interval_end")
        if plain.minute != 0 or plain.second != 0 or plain.microsecond != 0:
            raise ValueError(
                f"data_interval_end must be aligned to an exact UTC hour "
                f"(minute=0, second=0, microsecond=0), got {plain.isoformat()!r}"
            )
        return plain

    logical_date = context.get("logical_date")
    if logical_date is not None:
        plain = _to_plain_utc_datetime(logical_date, "logical_date")
        return plain.replace(minute=0, second=0, microsecond=0)

    now = now_provider()
    plain = _to_plain_utc_datetime(now, "now_provider")
    return plain.replace(minute=0, second=0, microsecond=0)


async def _generate_report(report_date: datetime) -> dict[str, object]:
    """Connect to MongoDB, delegate to ReportingService, return JSON-serializable summary.

    Always closes the MongoDB connection in a finally block even when errors occur.
    Never catches repository or service errors — they propagate to the Airflow task.
    """
    configure_logging()
    try:
        await connect_to_mongodb()
        database = get_database()
        await create_indexes(database)
        eq_repo = EarthquakeRepository(database=database)
        rep_repo = ReportRepository(database=database)
        service = ReportingService(
            earthquake_repository=eq_repo,
            report_repository=rep_repo,
        )
        report = await service.generate_hourly_report(report_date)
        return {
            "report_date": report.report_date.isoformat(),
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "total_events": report.total_events,
            "events_with_magnitude": report.events_with_magnitude,
            "average_magnitude": report.average_magnitude,
            "max_magnitude": report.max_magnitude,
            "top_locations": [
                {"location": item.location, "count": item.count}
                for item in report.top_locations
            ],
        }
    finally:
        close_mongodb_connection()


def _execute_hourly_report_task() -> dict[str, object]:
    """Airflow task callable: resolve report_date and run async orchestration.

    Obtains the Airflow task context, resolves the target report hour,
    and drives the async MongoDB + ReportingService pipeline synchronously
    via asyncio.run so Airflow's task runner stays single-threaded.
    """
    context = get_current_context()
    report_date = _resolve_report_date(context)
    logger.info(
        "Generating hourly report for report_date=%s", report_date.isoformat()
    )
    return asyncio.run(_generate_report(report_date))


# ---------------------------------------------------------------------------
# DAG definition — no I/O at parse time
# ---------------------------------------------------------------------------

with DAG(
    dag_id=DAG_ID,
    description="Hourly consolidation of seismic activity into a report document",
    schedule=SCHEDULE,
    start_date=datetime(2024, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    tags=["quipux", "earthquakes", "reporting"],
) as hourly_report_dag:

    @task(task_id=TASK_ID, retries=2, retry_delay=timedelta(minutes=5))
    def _run() -> dict[str, object]:
        return _execute_hourly_report_task()

    _run()
