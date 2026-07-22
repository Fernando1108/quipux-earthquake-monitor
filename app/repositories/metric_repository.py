"""Repository layer for storing and querying computed metrics in MongoDB."""

from datetime import datetime, timezone

import pymongo
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database
from app.models.metric import Metric

COLLECTION_NAME = "metrics"


class MetricRepository:
    """Read and write aggregated seismic metrics in the MongoDB metrics collection."""

    def __init__(self, database: AsyncIOMotorDatabase | None = None) -> None:
        db = database if database is not None else get_database()
        self._collection = db[COLLECTION_NAME]

    async def upsert_metric(self, metric: Metric) -> None:
        """Insert or replace the metric document keyed on window_start.

        Uses replace_one with upsert=True so that a second call for the same
        window overwrites the previous document instead of creating a duplicate.
        All database errors propagate unchanged.
        """
        document = metric.model_dump(mode="python")
        await self._collection.replace_one(
            {"window_start": metric.window_start},
            document,
            upsert=True,
        )

    async def get_by_window_start(
        self,
        window_start: datetime,
    ) -> Metric | None:
        """Return the metric for the given window_start, or None if absent.

        _id is excluded from the projection.
        Database and Pydantic validation errors propagate unchanged.
        """
        document = await self._collection.find_one(
            {"window_start": window_start},
            {"_id": 0},
        )
        if document is None:
            return None
        return _doc_to_metric(document)

    async def list_metrics(
        self,
        *,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sort_descending: bool = True,
    ) -> tuple[list[Metric], int]:
        """Return a paginated page of metrics and the total matching count.

        Time filters narrow by window_start; combining them places both operators
        inside a single window_start condition.
        """
        query: dict = {}

        if start_time is not None or end_time is not None:
            time_condition: dict = {}
            if start_time is not None:
                time_condition["$gte"] = start_time
            if end_time is not None:
                time_condition["$lte"] = end_time
            query["window_start"] = time_condition

        projection = {"_id": 0}
        sort_direction = pymongo.DESCENDING if sort_descending else pymongo.ASCENDING

        total_count: int = await self._collection.count_documents(query)

        cursor = (
            self._collection.find(query, projection)
            .sort("window_start", sort_direction)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)

        metrics = [_doc_to_metric(doc) for doc in documents]
        return metrics, total_count


def _doc_to_metric(document: dict[str, object]) -> Metric:
    """Convert a MongoDB document to a Metric domain object.

    Copies the document before modification to avoid mutating MongoDB internals.
    Interprets naive datetime values for window_start, window_end, and updated_at
    as UTC; aware values are normalised by the Metric model.
    """
    doc = dict(document)
    doc.pop("_id", None)

    for field in ("window_start", "window_end", "updated_at"):
        value = doc.get(field)
        if isinstance(value, datetime) and value.tzinfo is None:
            doc[field] = value.replace(tzinfo=timezone.utc)

    return Metric.model_validate(doc)
