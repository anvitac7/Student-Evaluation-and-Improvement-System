from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.models.analytics import (
    AdminAnalyticsResponse,
    DriveApplicantsResponse,
    DriveAssessmentRanking,
    DriveParticipantsResponse,
    TpoAnalyticsResponse,
)
from app.services.analytics_service import AnalyticsError, AnalyticsService

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


@router.get("/admin", response_model=AdminAnalyticsResponse)
async def get_admin_analytics(
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AnalyticsService(db)
    return await service.get_admin_analytics()
