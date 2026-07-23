from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.workers.ingestion_worker import IngestionWorker

__all__ = ["IngestionWorker"]


def __getattr__(name: str) -> object:
    if name == "IngestionWorker":
        from app.workers.ingestion_worker import IngestionWorker

        return IngestionWorker

    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
