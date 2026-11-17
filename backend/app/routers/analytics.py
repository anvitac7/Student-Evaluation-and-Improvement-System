from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Literal

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.models.analytics import (
    AdminAnalyticsResponse,
    DriveApplicantsResponse,
    DriveAssessmentRanking,
    DriveParticipantsResponse,
    SkillGapAnalysisResponse,
    SkillGapSort,
    SkillGapStudentFilter,
    SkillGapStudentsResponse,
    TpoAnalyticsResponse,
)
from app.models.market import JobFamily, MarketFiltersResponse, SkillCategory
from app.services.analytics_service import AnalyticsError, AnalyticsService
from app.services.market_analytics_service import (
    MarketAnalyticsService,
    MarketQueryError,
)
from app.services.skill_gap_service import SkillGapError, SkillGapService

router = APIRouter()


@router.get("/tpo", response_model=TpoAnalyticsResponse)
async def get_tpo_analytics(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AnalyticsService(db)
    return await service.get_tpo_analytics(current_user.id)


@router.get("/tpo/drives/{drive_id}/ranking", response_model=DriveAssessmentRanking)
async def get_drive_ranking(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Ranking for ONE drive's required assessment — shown inside that
    drive's expanded analytics breakdown (the standalone rankings section
    was relocated here)."""
    service = AnalyticsService(db)
    try:
        return await service.get_drive_ranking(current_user.id, drive_id)
    except AnalyticsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/tpo/drives/{drive_id}/applicants", response_model=DriveApplicantsResponse)
async def get_drive_applicants(
    drive_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Students who applied to ONE drive (all application statuses)."""
    service = AnalyticsService(db)
    try:
        return await service.get_drive_applicants(current_user.id, drive_id, page, limit, search)
    except AnalyticsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/tpo/drives/{drive_id}/participants", response_model=DriveParticipantsResponse)
async def get_drive_participants(
    drive_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Students who actually started ONE drive's required assessment — one
    row per student, never per attempt."""
    service = AnalyticsService(db)
    try:
        return await service.get_drive_participants(current_user.id, drive_id, page, limit, search)
    except AnalyticsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


# ---------------------------------------------------------------------------
# Phase 8 — Skill Gap Analysis (TPO-only)
# ---------------------------------------------------------------------------


@router.get("/tpo/skill-gaps", response_model=SkillGapAnalysisResponse)
async def get_skill_gaps(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    year_from: int | None = Query(default=None, ge=2000, le=2100),
    year_to: int | None = Query(default=None, ge=2000, le=2100),
    company: str | None = Query(default=None, max_length=200),
    job_family: JobFamily | None = Query(default=None),
    location: str | None = Query(default=None, max_length=100),
    skill_category: SkillCategory | None = Query(default=None),
    technical_only: bool = Query(default=False),
    sort: SkillGapSort = Query(default="priority"),
):
    """Skill gap analysis: industry demand (Market Insights dataset, same
    filter semantics as the market dashboard) vs. student evidence
    (assessment-demonstrated + self-reported, kept strictly separate)."""
    service = SkillGapService(db)
    try:
        return await service.get_skill_gaps(
            year_from=year_from,
            year_to=year_to,
            company=company,
            job_family=job_family.value if job_family is not None else None,
            location=location,
            skill_category=skill_category.value if skill_category is not None else None,
            technical_only=technical_only,
            sort=sort,
        )
    except MarketQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tpo/skill-gaps/filters", response_model=MarketFiltersResponse)
async def get_skill_gap_filters(
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Filter options for the skill gap dashboard — the SAME live options the
    Market Insights filters endpoint derives (one dataset, one source)."""
    return await MarketAnalyticsService(db).get_available_filters()


@router.get(
    "/tpo/skill-gaps/{skill_id}/students", response_model=SkillGapStudentsResponse
)
async def get_skill_gap_students(
    skill_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    classification: SkillGapStudentFilter = Query(default="all"),
):
    """Students and their evidence for ONE demanded skill — the whole student
    population with a per-student classification (filterable), covering the
    no-evidence training audience too. Only fields relevant to THIS skill are
    returned; never unrelated assessment data or contact information."""
    service = SkillGapService(db)
    try:
        return await service.get_skill_students(
            skill_id, page, limit, search, classification
        )
    except SkillGapError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except MarketQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AnalyticsService(db)
    return await service.get_admin_analytics()
