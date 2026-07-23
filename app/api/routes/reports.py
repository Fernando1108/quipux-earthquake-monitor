"""Report retrieval endpoints for periodic seismic summaries."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_report_repository
from app.api.schemas import (
    ReportQueryParams,
    PaginatedResponse,
    build_paginated_response,
)
from app.models.report import Report
from app.repositories.report_repository import ReportRepository

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=PaginatedResponse[Report])
async def list_reports(
    params: Annotated[ReportQueryParams, Query()],
    repo: ReportRepository = Depends(get_report_repository),
) -> PaginatedResponse[Report]:
    """Return a paginated, optionally time-filtered list of hourly seismic reports."""
    reports, total = await repo.list_reports(
        page=params.page,
        page_size=params.page_size,
        start_time=params.start_time,
        end_time=params.end_time,
        sort_descending=params.sort_descending,
    )
    return build_paginated_response(
        items=reports,
        page=params.page,
        page_size=params.page_size,
        total=total,
    )
