import csv
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, get_current_user, require_role
from app.models.drive import (
    ApplicationDetail,
    ApplicationResponse,
    ApplicationStatus,
    ApplicationStatusUpdateRequest,
    BulkApplicationStatusRequest,
    BulkStatusResult,
    CompanySummary,
    DriveCreateRequest,
    DriveDetail,
    DriveSummary,
    DriveUpdateRequest,
    PlacementDriveInDB,
    ScreeningSummary,
)
from app.repositories.application_repository import ApplicationRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.resume_repository import ResumeRepository
from app.services.drive_service import DriveError, DriveService
from app.services.screening_service import ScreeningService

router = APIRouter()


async def _to_summary(drive: PlacementDriveInDB, db: AsyncIOMotorDatabase) -> DriveSummary:
    company = await CompanyRepository(db).get_by_id(drive.company_id)
    company_summary = (
        CompanySummary(
            id=company.id,
            name=company.name,
            description=company.description,
            website=company.website,
            industry=company.industry,
        )
        if company
        else CompanySummary(id=drive.company_id, name="Unknown company")
    )
    return DriveSummary(
        id=drive.id,
        company=company_summary,
        job_title=drive.job_title,
        package=drive.package,
        location=drive.location,
        deadline=drive.deadline,
        status=drive.status,
        required_skills=drive.required_skills,
    )


async def _to_detail(drive: PlacementDriveInDB, db: AsyncIOMotorDatabase) -> DriveDetail:
    summary = await _to_summary(drive, db)
    return DriveDetail(
        **summary.model_dump(),
        description=drive.description,
        jd_text=drive.jd_text,
        eligibility=drive.eligibility,
        selection_process=drive.selection_process,
        experience_required_years=drive.experience_required_years,
        created_at=drive.created_at,
        required_assessment_id=drive.required_assessment_id,
        assessment_min_score_pct=drive.assessment_min_score_pct,
        assessment_deadline=drive.assessment_deadline,
    )


def _to_application_response(application) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id,
        drive_id=application.drive_id,
        student_id=application.student_id,
        resume_id=application.resume_id,
        status=application.status,
        applied_at=application.applied_at,
        eligibility_passed=getattr(application, "eligibility_passed", None),
        eligibility_reasons=getattr(application, "eligibility_reasons", []),
        final_score=getattr(application, "final_score", None),
        semantic_score=getattr(application, "semantic_score", None),
        skills_score=getattr(application, "skills_score", None),
        experience_score=getattr(application, "experience_score", None),
        matched_skills=getattr(application, "matched_skills", []),
        missing_skills=getattr(application, "missing_skills", []),
        assessment_attempt_id=getattr(application, "assessment_attempt_id", None),
        assessment_score_pct=getattr(application, "assessment_score_pct", None),
        assessment_status=getattr(application, "assessment_status", "not_required"),
        rejection_reasons=getattr(application, "rejection_reasons", []),
        rejection_note=getattr(application, "rejection_note", None),
        decision_at=getattr(application, "decision_at", None),
    )


async def _to_application_detail(application, db: AsyncIOMotorDatabase) -> ApplicationDetail:
    base = _to_application_response(application)
    student = await StudentRepository(db).get_by_id(application.student_id)
    resume = await ResumeRepository(db).get_by_id(application.resume_id)
    return ApplicationDetail(
        **base.model_dump(),
        student_name=student.name if student else "Unknown student",
        student_department=student.department if student else None,
        student_cgpa=student.cgpa if student else None,
        resume_filename=resume.original_filename if resume else None,
    )


@router.post("", response_model=DriveDetail, status_code=201)
async def create_drive(
    payload: DriveCreateRequest,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        drive = await service.create_drive(current_user.id, payload)
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return await _to_detail(drive, db)


@router.get("", response_model=list[DriveSummary])
async def list_drives(
    page: int = 1,
    limit: int = 20,
    status_filter: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    query: dict = {}
    if status_filter:
        query["status"] = status_filter
    drives = await PlacementDriveRepository(db).find_many(
        query, page=page, limit=limit, sort=[("created_at", -1)]
    )
    return [await _to_summary(d, db) for d in drives]


@router.get("/applications/me", response_model=list[ApplicationResponse])
async def my_applications(
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    applications = await ApplicationRepository(db).get_for_student(student.id)
    return [_to_application_response(a) for a in applications]


@router.get("/mine", response_model=list[DriveSummary])
async def list_my_drives(
    page: int = 1,
    limit: int = 50,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        drives = await service.get_my_drives(current_user.id, page=page, limit=limit)
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return [await _to_summary(d, db) for d in drives]


@router.get("/{drive_id}", response_model=DriveDetail)
async def get_drive(
    drive_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found.")
    return await _to_detail(drive, db)


@router.put("/{drive_id}", response_model=DriveDetail)
async def update_drive(
    drive_id: str,
    payload: DriveUpdateRequest,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        drive = await service.update_drive(current_user.id, drive_id, payload)
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return await _to_detail(drive, db)


@router.delete("/{drive_id}", status_code=204)
async def delete_drive(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        await service.delete_drive(current_user.id, drive_id)
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{drive_id}/clone", response_model=DriveDetail, status_code=201)
async def clone_drive(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Clones an existing drive as a template for a new drive."""
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive to clone not found.")

    company = await CompanyRepository(db).get_by_id(drive.company_id)
    company_name = company.name if company else "Company"

    payload = DriveCreateRequest(
        company_name=company_name,
        company_description=company.description if company else None,
        company_website=company.website if company else None,
        company_industry=company.industry if company else None,
        job_title=f"{drive.job_title} (Copy)",
        description=drive.description,
        jd_text=drive.jd_text,
        required_skills=drive.required_skills,
        experience_required_years=drive.experience_required_years,
        package=drive.package,
        location=drive.location,
        eligibility=drive.eligibility,
        deadline=datetime.utcnow(),
        selection_process=drive.selection_process,
        required_assessment_id=drive.required_assessment_id,
        assessment_min_score_pct=drive.assessment_min_score_pct,
        assessment_deadline=None,
    )
    service = DriveService(db)
    new_drive = await service.create_drive(current_user.id, payload)
    return await _to_detail(new_drive, db)


@router.post("/{drive_id}/apply", response_model=ApplicationResponse, status_code=201)
async def apply_to_drive(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        application = await service.apply_to_drive(current_user.id, drive_id)
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_application_response(application)


# ---------------------------------------------------------------------------
# Screening & Evaluation Endpoints
# ---------------------------------------------------------------------------

@router.get("/{drive_id}/screening-summary", response_model=ScreeningSummary)
async def get_screening_summary(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = ScreeningService(db)
    try:
        return await service.get_screening_summary(current_user.id, drive_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{drive_id}/screen", response_model=list[ApplicationDetail])
async def trigger_screening(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Triggers deterministic screening across all applications in this drive."""
    service = ScreeningService(db)
    try:
        updated_apps = await service.screen_applications(current_user.id, drive_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [await _to_application_detail(a, db) for a in updated_apps]


@router.get("/{drive_id}/recommended-shortlist", response_model=list[ApplicationDetail])
async def get_recommended_shortlist(
    drive_id: str,
    top_n: int = Query(default=10, ge=1, le=100),
    min_score: float = Query(default=0.60, ge=0.0, le=1.0),
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = ScreeningService(db)
    try:
        candidates = await service.get_recommended_shortlist(current_user.id, drive_id, top_n, min_score)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [await _to_application_detail(a, db) for a in candidates]


# ---------------------------------------------------------------------------
# Applications Management (Filters, Sorting, Bulk Actions, CSV Export)
# ---------------------------------------------------------------------------

@router.get("/{drive_id}/applications", response_model=list[ApplicationDetail])
async def get_drive_applications(
    drive_id: str,
    status: str | None = None,
    assessment_status: str | None = None,
    eligible_only: bool = False,
    sort_by: str = "applied_at",
    sort_order: str = "desc",
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found.")

    tpo = await TPORepository(db).get_by_user_id(current_user.id)
    if not tpo or drive.created_by != tpo.id:
        raise HTTPException(status_code=403, detail="You do not have permission to view these applications.")

    # Reconcile any expired assessments lazily
    await ScreeningService(db).reconcile_expired_assessments(drive)

    query: dict = {"drive_id": drive_id}
    if status:
        query["status"] = status
    if assessment_status:
        query["assessment_status"] = assessment_status
    if eligible_only:
        query["eligibility_passed"] = {"$ne": False}

    sort_direction = -1 if sort_order == "desc" else 1
    sort_fields = [(sort_by, sort_direction)]

    applications = await ApplicationRepository(db).find_many(query, limit=5000, sort=sort_fields)
    return [await _to_application_detail(a, db) for a in applications]


@router.patch("/{drive_id}/applications/bulk-status", response_model=BulkStatusResult)
async def bulk_update_application_status(
    drive_id: str,
    payload: BulkApplicationStatusRequest,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    updated_count = 0
    failed_ids = []
    errors = []

    for app_id in payload.application_ids:
        try:
            await service.update_application_status(
                current_user.id,
                drive_id,
                app_id,
                payload.status.value,
                rejection_reasons=payload.rejection_reasons,
                rejection_note=payload.rejection_note,
            )
            updated_count += 1
        except Exception as exc:
            failed_ids.append(app_id)
            errors.append(f"Application {app_id}: {str(exc)}")

    return BulkStatusResult(
        updated_count=updated_count,
        failed_ids=failed_ids,
        errors=errors,
    )


@router.get("/{drive_id}/applications/export")
async def export_applications_csv(
    drive_id: str,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    drive = await PlacementDriveRepository(db).get_by_id(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found.")

    tpo = await TPORepository(db).get_by_user_id(current_user.id)
    if not tpo or drive.created_by != tpo.id:
        raise HTTPException(status_code=403, detail="You do not have permission for this drive.")

    applications = await ApplicationRepository(db).get_for_drive(drive_id)
    details = [await _to_application_detail(a, db) for a in applications]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Application ID",
        "Student Name",
        "Department",
        "CGPA",
        "Status",
        "Eligible",
        "Final Score",
        "Semantic Score",
        "Skills Score",
        "Experience Score",
        "Assessment Status",
        "Assessment Score %",
        "Rejection Reasons",
        "Rejection Note",
        "Applied At",
    ])

    for d in details:
        writer.writerow([
            d.id,
            d.student_name,
            d.student_department or "",
            d.student_cgpa or "",
            d.status,
            "Yes" if d.eligibility_passed else "No",
            d.final_score if d.final_score is not None else "",
            d.semantic_score if d.semantic_score is not None else "",
            d.skills_score if d.skills_score is not None else "",
            d.experience_score if d.experience_score is not None else "",
            d.assessment_status,
            d.assessment_score_pct if d.assessment_score_pct is not None else "",
            "; ".join(d.rejection_reasons),
            d.rejection_note or "",
            d.applied_at.isoformat() if hasattr(d.applied_at, "isoformat") else str(d.applied_at),
        ])

    csv_data = output.getvalue()
    filename = f"applications_drive_{drive_id[:8]}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/{drive_id}/applications/{application_id}", response_model=ApplicationDetail)
async def update_application_status(
    drive_id: str,
    application_id: str,
    payload: ApplicationStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_role("tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = DriveService(db)
    try:
        application = await service.update_application_status(
            current_user.id,
            drive_id,
            application_id,
            payload.status.value,
            rejection_reasons=payload.rejection_reasons,
            rejection_note=payload.rejection_note,
        )
    except DriveError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return await _to_application_detail(application, db)
