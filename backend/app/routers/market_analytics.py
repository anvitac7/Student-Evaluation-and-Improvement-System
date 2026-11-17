"""TPO market-analytics endpoints for the Trending Skills & Company
Requirements dashboard.

Reads the historical job-market dataset only (never ``placement_drives``).
Access is TPO-only via the shared ``require_role`` dependency; the dataset is
global market data, so no TPO-ownership filtering is applied.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.models.market import (
    JobFamily,
    MarketAnalyticsResponse,
    MarketComparisonResponse,
    MarketFiltersResponse,
    SkillCategory,
)
from app.services.market_analytics_service import (
    MarketAnalyticsService,
    MarketQuery,
    MarketQueryError,
)

router = APIRouter()


@router.get("/tpo/market", response_model=MarketAnalyticsResponse)
async def get_market_analytics(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    year_from: int | None = Query(
        default=None, ge=2000, le=2100, description="First posting year to include."
    ),
    year_to: int | None = Query(
        default=None, ge=2000, le=2100, description="Last posting year to include."
    ),
    company: str | None = Query(
        default=None,
        max_length=200,
        description="Company slug (or exact company name) to filter by.",
    ),
    job_family: JobFamily | None = Query(
        default=None, description="Job family to filter by."
    ),
    location: str | None = Query(
        default=None, max_length=100, description="Posting location to filter by."
    ),
    skill_category: SkillCategory | None = Query(
        default=None,
        description="Only analyse skills in this catalog category.",
    ),
    technical_only: bool = Query(
        default=False,
        description="Only analyse technical skills (ignores soft skills).",
    ),
    sort: Literal["trending", "demand"] = Query(
        default="trending",
        description="Order trending skills by weighted trend score or raw demand.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=20,
        description="Maximum number of trending skills returned (hard cap 20).",
    ),
):
    """Aggregated market analytics: summary, trending skills, historical
    trends, emerging skills, company and job-family analytics."""
    service = MarketAnalyticsService(db)
    query = MarketQuery(
        year_from=year_from,
        year_to=year_to,
        company=company,
        job_family=job_family.value if job_family is not None else None,
        location=location,
        skill_category=skill_category.value if skill_category is not None else None,
        technical_only=technical_only,
        sort=sort,
        limit=limit,
    )
    try:
        return await service.get_market_analytics(query)
    except MarketQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tpo/market/filters", response_model=MarketFiltersResponse)
async def get_market_filters(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Available filter options, derived live from the market dataset."""
    return await MarketAnalyticsService(db).get_available_filters()


@router.get("/tpo/market/comparison", response_model=MarketComparisonResponse)
async def get_market_comparison(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    dimension: Literal["company", "job_family"] = Query(
        description="Whether the selected entities are companies or job families."
    ),
    entities: str = Query(
        min_length=1,
        max_length=600,
        description=(
            "Comma-separated entity keys (company slugs or names, or job-family "
            "names). At most 6 distinct entities."
        ),
    ),
    year_from: int | None = Query(
        default=None, ge=2000, le=2100, description="First posting year to include."
    ),
    year_to: int | None = Query(
        default=None, ge=2000, le=2100, description="Last posting year to include."
    ),
    job_family: JobFamily | None = Query(
        default=None,
        description="Posting filter applied when comparing companies (ignored otherwise).",
    ),
    company: str | None = Query(
        default=None,
        max_length=200,
        description="Posting filter applied when comparing job families (ignored otherwise).",
    ),
    location: str | None = Query(
        default=None, max_length=100, description="Posting location to filter by."
    ),
):
    """Compare the full skill requirements of multiple companies or job
    families (same trend math as the dashboard, per-entity denominators)."""
    service = MarketAnalyticsService(db)
    entity_values = [part.strip() for part in entities.split(",") if part.strip()]
    try:
        return await service.get_market_comparison(
            dimension=dimension,
            entity_values=entity_values,
            year_from=year_from,
            year_to=year_to,
            cross_company=company,
            cross_job_family=job_family.value if job_family is not None else None,
            location=location,
        )
    except MarketQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
