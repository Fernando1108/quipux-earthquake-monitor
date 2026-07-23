"""Metrics endpoints exposing aggregated seismic statistics and indicators."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_metric_repository
from app.api.schemas import (
    MetricQueryParams,
    PaginatedResponse,
    build_paginated_response,
)
from app.models.metric import Metric
from app.repositories.metric_repository import MetricRepository

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=PaginatedResponse[Metric])
async def list_metrics(
    params: Annotated[MetricQueryParams, Query()],
    repo: MetricRepository = Depends(get_metric_repository),
) -> PaginatedResponse[Metric]:
    """Return a paginated, optionally time-filtered list of hourly seismic metrics."""
    metrics, total = await repo.list_metrics(
        page=params.page,
        page_size=params.page_size,
        start_time=params.start_time,
        end_time=params.end_time,
        sort_descending=params.sort_descending,
    )
    return build_paginated_response(
        items=metrics,
        page=params.page,
        page_size=params.page_size,
        total=total,
    )
