"""Earthquake query endpoints: list, filter, and retrieve seismic event records."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_earthquake_repository
from app.api.schemas import (
    EarthquakeQueryParams,
    PaginatedResponse,
    build_paginated_response,
)
from app.models.earthquake import Earthquake
from app.repositories.earthquake_repository import EarthquakeRepository

router = APIRouter(prefix="/earthquakes", tags=["earthquakes"])


@router.get("", response_model=PaginatedResponse[Earthquake])
async def list_earthquakes(
    params: Annotated[EarthquakeQueryParams, Query()],
    repo: EarthquakeRepository = Depends(get_earthquake_repository),
) -> PaginatedResponse[Earthquake]:
    """Return a paginated, optionally filtered list of seismic events."""
    earthquakes, total = await repo.list_earthquakes(
        page=params.page,
        page_size=params.page_size,
        min_magnitude=params.min_magnitude,
        max_magnitude=params.max_magnitude,
        start_time=params.start_time,
        end_time=params.end_time,
        sort_descending=params.sort_descending,
    )
    return build_paginated_response(
        items=earthquakes,
        page=params.page,
        page_size=params.page_size,
        total=total,
    )
