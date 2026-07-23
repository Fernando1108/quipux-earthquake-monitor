"""Repository layer for persisting and retrieving seismic reports from MongoDB."""

from datetime import datetime, timezone

import pymongo
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database
from app.models.report import Report

COLLECTION_NAME = "hourly_reports"


class ReportRepository:
    """Read and write hourly seismic reports in MongoDB."""

    def __init__(self, database: AsyncIOMotorDatabase | None = None) -> None:
        db = database if database is not None else get_database()
        self._collection = db[COLLECTION_NAME]

    async def upsert_report(self, report: Report) -> None:
        """Insert or replace a report document keyed on report_date.

        Uses replace_one with upsert=True so that a second call for the same
        hour overwrites the previous document instead of creating a duplicate.
        All database errors propagate unchanged.
        """
        document = report.model_dump(mode="python")
        await self._collection.replace_one(
            {"report_date": report.report_date},
            document,
            upsert=True,
        )

    async def get_by_report_date(
        self,
        report_date: datetime,
    ) -> Report | None:
        """Return the report for the given report_date, or None if absent.

        _id is excluded from the projection.
        Database and Pydantic validation errors propagate unchanged.
        """
        document = await self._collection.find_one(
            {"report_date": report_date},
            {"_id": 0},
        )
        if document is None:
            return None
        return _doc_to_report(document)

    async def list_reports(
        self,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sort_descending: bool = True,
    ) -> tuple[list[Report], int]:
        """Return a paginated page of reports and the total matching count.

        Time filters narrow by report_date; combining them places both operators
        inside a single report_date condition.
        """
        query: dict = {}

        if start_time is not None or end_time is not None:
            time_condition: dict = {}
            if start_time is not None:
                time_condition["$gte"] = start_time
            if end_time is not None:
                time_condition["$lte"] = end_time
            query["report_date"] = time_condition

        projection = {"_id": 0}
        sort_direction = pymongo.DESCENDING if sort_descending else pymongo.ASCENDING

        total_count: int = await self._collection.count_documents(query)

        cursor = (
            self._collection.find(query, projection)
            .sort("report_date", sort_direction)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)

        reports = [_doc_to_report(doc) for doc in documents]
        return reports, total_count


def _doc_to_report(document: dict[str, object]) -> Report:
    """Convert a MongoDB document to a Report domain object.

    Copies the document before modification to avoid mutating MongoDB internals.
    Removes _id defensively. Interprets naive datetime values for report_date,
    period_start, period_end, and generated_at as UTC; normalization of aware
    values is delegated to the Report model.
    """
    doc = dict(document)
    doc.pop("_id", None)

    for field in ("report_date", "period_start", "period_end", "generated_at"):
        value = doc.get(field)
        if isinstance(value, datetime) and value.tzinfo is None:
            doc[field] = value.replace(tzinfo=timezone.utc)

    return Report.model_validate(doc)
