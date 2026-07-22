"""Repository layer for CRUD operations on the earthquakes MongoDB collection."""

from datetime import datetime, timezone

import pymongo
import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database.mongodb import get_database
from app.models.earthquake import Earthquake

COLLECTION_NAME = "earthquakes"


class EarthquakeRepository:
    """Read and write seismic events in the MongoDB earthquakes collection."""

    def __init__(self, database: AsyncIOMotorDatabase | None = None) -> None:
        db = database if database is not None else get_database()
        self._collection = db[COLLECTION_NAME]

    async def insert_if_new(self, earthquake: Earthquake) -> bool:
        """Insert the earthquake document if event_id has not been seen before.

        Returns True on successful insertion, False on duplicate event_id.
        All other database errors propagate unchanged.
        """
        document = earthquake.model_dump(mode="python")
        document["ingested_at"] = datetime.now(timezone.utc)

        try:
            await self._collection.insert_one(document)
        except pymongo.errors.DuplicateKeyError:
            return False

        return True

    async def list_earthquakes(
        self,
        *,
        page: int,
        page_size: int,
        min_magnitude: float | None = None,
        max_magnitude: float | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        sort_descending: bool = True,
    ) -> tuple[list[Earthquake], int]:
        """Return a paginated page of earthquakes and the total matching count.

        Filters are applied only when provided; combining them narrows the result.
        """
        query: dict = {}

        if min_magnitude is not None or max_magnitude is not None:
            mag_condition: dict = {}
            if min_magnitude is not None:
                mag_condition["$gte"] = min_magnitude
            if max_magnitude is not None:
                mag_condition["$lte"] = max_magnitude
            query["magnitude"] = mag_condition

        if start_time is not None or end_time is not None:
            time_condition: dict = {}
            if start_time is not None:
                time_condition["$gte"] = start_time
            if end_time is not None:
                time_condition["$lte"] = end_time
            query["event_time"] = time_condition

        projection = {"_id": 0, "ingested_at": 0}
        sort_direction = pymongo.DESCENDING if sort_descending else pymongo.ASCENDING

        total_count: int = await self._collection.count_documents(query)

        cursor = (
            self._collection.find(query, projection)
            .sort("event_time", sort_direction)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        documents = await cursor.to_list(length=page_size)

        earthquakes = [_doc_to_earthquake(doc) for doc in documents]
        return earthquakes, total_count

    async def find_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[Earthquake]:
        """Return all earthquakes in the half-open interval [start_time, end_time).

        Results are sorted by event_time ASCENDING.
        """
        query = {
            "event_time": {
                "$gte": start_time,
                "$lt": end_time,
            }
        }
        projection = {"_id": 0, "ingested_at": 0}

        cursor = (
            self._collection.find(query, projection)
            .sort("event_time", pymongo.ASCENDING)
        )
        documents = await cursor.to_list(length=None)

        return [_doc_to_earthquake(doc) for doc in documents]


def _doc_to_earthquake(document: dict) -> Earthquake:
    """Convert a MongoDB document to an Earthquake domain object.

    Copies the document before modification to avoid mutating MongoDB internals.
    Interprets naive event_time as UTC; aware values are normalised by the model.
    """
    doc = dict(document)
    doc.pop("_id", None)
    doc.pop("ingested_at", None)

    event_time = doc.get("event_time")
    if isinstance(event_time, datetime) and event_time.tzinfo is None:
        doc["event_time"] = event_time.replace(tzinfo=timezone.utc)

    return Earthquake.model_validate(doc)
