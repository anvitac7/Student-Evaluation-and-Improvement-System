from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.models.matching import DriveMatchScoreResponse, RankedApplicantResponse, RecommendedDriveResponse
from app.repositories.application_repository import ApplicationRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.resume_repository import ResumeRepository
from app.services.matching_service import MatchingService, MatchingUnavailableError

router = APIRouter()


async def _get_company_name(db: AsyncIOMotorDatabase, company_id: str) -> str:
    company = await CompanyRepository(db).get_by_id(company_id)
    return company.name if company else "Unknown company"


async def _get_active_resume_or_404(db: AsyncIOMotorDatabase, current_user: CurrentUser):
    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    if not student.active_resume_id:
        raise HTTPException(status_code=404, detail="Upload a resume before requesting match scores.")
    resume = await ResumeRepository(db).get_by_id(student.active_resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Active resume not found.")
    return resume


# ---------------------------------------------------------------------------
# Phase 7 — single resume x single drive
# ---------------------------------------------------------------------------
@router.get("/drives/{drive_id}/score", response_model=DriveMatchScoreResponse)
async def get_drive_match_score(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found.")

    resume = await _get_active_resume_or_404(db, current_user)
    company_name = await _get_company_name(db, drive.company_id)

    try:
        result = await MatchingService(db).score_resume_against_drive(resume, drive, company_name)
    except MatchingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return DriveMatchScoreResponse(drive_id=drive.id, **result)


# ---------------------------------------------------------------------------
# Phase 9 — ranked recommendations / ranked applicants
# ---------------------------------------------------------------------------
@router.get("/recommended-drives", response_model=list[RecommendedDriveResponse])
async def get_recommended_drives(
    limit: int = 10,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    resume = await _get_active_resume_or_404(db, current_user)

    open_drives = await PlacementDriveRepository(db).find_many(
        {"status": "open", "deadline": {"$gt": datetime.utcnow()}}, limit=200
    )
    if not open_drives:
        return []

    drives_with_companies = [(d, await _get_company_name(db, d.company_id)) for d in open_drives]

    try:
        results = await MatchingService(db).rank_drives_for_resume(resume, drives_with_companies)
    except MatchingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    drives_by_id = {d.id: d for d in open_drives}
    names_by_id = {d.id: name for d, name in drives_with_companies}

    response = []
    for r in results[:limit]:
        drive = drives_by_id[r["candidate_id"]]
        response.append(
            RecommendedDriveResponse(
                drive_id=drive.id,
                job_title=drive.job_title,
                company_name=names_by_id[drive.id],
                location=drive.location,
                package=drive.package,
                final_score=r["final_score"],
                semantic_score=r["semantic_score"],
                skills_score=r["skills_score"],
                experience_score=r["experience_score"],
                matched_skills=r["matched_skills"],
                missing_skills=r["missing_skills"],
            )
        )
    return response


@router.get("/drives/{drive_id}/ranked-applicants", response_model=list[RankedApplicantResponse])
async def get_ranked_applicants(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found.")

    tpo = await TPORepository(db).get_by_user_id(current_user.id)
    if not tpo or drive.created_by != tpo.id:
        raise HTTPException(status_code=403, detail="You do not have permission to view these applicants.")

    applications = await ApplicationRepository(db).get_for_drive(drive_id, limit=200)
    if not applications:
        return []

    # Each application locked in the specific resume version submitted at
    # apply-time — deliberately NOT the student's current active resume,
    # which may have changed since (a reasonable thing for a student to do,
    # but it shouldn't retroactively change what a TPO is evaluating).
    resume_repo = ResumeRepository(db)
    student_repo = StudentRepository(db)
    resumes_by_application_id = {}
    students_by_application_id = {}
    valid_applications = []
    for application in applications:
        resume = await resume_repo.get_by_id(application.resume_id)
        student = await student_repo.get_by_id(application.student_id)
        if not resume or not student:
            continue  # data integrity edge case — skip rather than 500
        resumes_by_application_id[application.id] = resume
        students_by_application_id[application.id] = student
        valid_applications.append(application)

    company_name = await _get_company_name(db, drive.company_id)
    resumes = [resumes_by_application_id[a.id] for a in valid_applications]

    try:
        results = await MatchingService(db).rank_resumes_for_drive(drive, company_name, resumes)
    except MatchingUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    applications_by_resume_id = {resumes_by_application_id[a.id].id: a for a in valid_applications}

    response = []
    for r in results:
        application = applications_by_resume_id[r["candidate_id"]]
        student = students_by_application_id[application.id]
        response.append(
            RankedApplicantResponse(
                application_id=application.id,
                student_id=student.id,
                student_name=student.name,
                student_department=student.department,
                student_cgpa=student.cgpa,
                resume_id=application.resume_id,
                resume_filename=resumes_by_application_id[application.id].original_filename,
                status=application.status,
                eligibility_passed=getattr(application, "eligibility_passed", None),
                eligibility_reasons=getattr(application, "eligibility_reasons", []),
                assessment_status=getattr(application, "assessment_status", "not_required"),
                assessment_score_pct=getattr(application, "assessment_score_pct", None),
                rejection_reasons=getattr(application, "rejection_reasons", []),
                rejection_note=getattr(application, "rejection_note", None),
                decision_at=application.decision_at.isoformat() if getattr(application, "decision_at", None) else None,
                applied_at=application.applied_at.isoformat() if getattr(application, "applied_at", None) else None,
                final_score=r["final_score"],
                semantic_score=r["semantic_score"],
                skills_score=r["skills_score"],
                experience_score=r["experience_score"],
                matched_skills=r["matched_skills"],
                missing_skills=r["missing_skills"],
            )
        )
    return response
