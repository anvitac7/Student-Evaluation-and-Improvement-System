import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, get_current_user, require_role
from app.models.resume import ResumeDetail, ResumeInDB, ResumeSummary, ResumeUploadResponse
from app.repositories.application_repository import ApplicationRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.resume_repository import ResumeRepository
from app.services.resume_parsing_service import ResumeParsingService
from app.services.resume_service import ResumeError, ResumeService
from app.services.storage_service import StorageService

from pydantic import BaseModel

from app.models.user import StudentProfileUpdateRequest
from app.services.profile_autofill_service import ProfileAutofillService
from app.services.student_profile_service import StudentProfileService

router = APIRouter()


async def _get_resume_with_access_check(
    resume_id: str, current_user: CurrentUser, db: AsyncIOMotorDatabase
) -> ResumeInDB:
    """Resume access control:
    - Student: can only view their own resumes
    - TPO: can only view resumes attached to applications in drives they created
    - Admin: can view any resume (platform admin)
    """
    resume = await ResumeRepository(db).get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found.")

    if current_user.role == "student":
        student = await StudentRepository(db).get_by_user_id(current_user.id)
        if not student or resume.student_id != student.id:
            raise HTTPException(status_code=403, detail="You do not have access to this resume.")
    elif current_user.role == "tpo":
        # TPO can only access resumes that belong to applicants in their
        # own drives — not any arbitrary resume in the system.
        tpo = await TPORepository(db).get_by_user_id(current_user.id)
        if not tpo:
            raise HTTPException(status_code=403, detail="TPO profile not found.")
        # Check: does an application exist that references this resume,
        # in a drive owned by this TPO?
        application = await ApplicationRepository(db).find_one({"resume_id": resume_id})
        if not application:
            raise HTTPException(status_code=403, detail="You do not have access to this resume.")
        drive = await PlacementDriveRepository(db).get_by_id(application.drive_id)
        if not drive or drive.created_by != tpo.id:
            raise HTTPException(status_code=403, detail="You do not have access to this resume.")
    # Admin: unrestricted access (no extra check needed)

    return resume


def _to_summary(resume: ResumeInDB) -> ResumeSummary:
    return ResumeSummary(
        id=resume.id,
        version=resume.version,
        original_filename=resume.original_filename,
        uploaded_at=resume.uploaded_at,
        is_active=resume.is_active,
    )


def _to_detail(resume: ResumeInDB) -> ResumeDetail:
    return ResumeDetail(
        id=resume.id,
        version=resume.version,
        original_filename=resume.original_filename,
        uploaded_at=resume.uploaded_at,
        is_active=resume.is_active,
        parsed=resume.parsed,
        skill_set=resume.skill_set,
        experience_years=resume.experience_years,
    )


@router.post("", response_model=ResumeUploadResponse, status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    file_bytes = await file.read()
    service = ResumeService(db)
    try:
        resume = await service.upload_resume(current_user.id, file.filename or "resume.pdf", file_bytes)
    except ResumeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return ResumeUploadResponse(
        id=resume.id,
        version=resume.version,
        original_filename=resume.original_filename,
        file_size_bytes=resume.file_size_bytes,
        uploaded_at=resume.uploaded_at,
        is_active=resume.is_active,
    )


@router.get("/history", response_model=list[ResumeSummary])
async def resume_history(
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    history = await ResumeRepository(db).get_history_for_student(student.id)
    return [_to_summary(r) for r in history]


@router.get("/{resume_id}", response_model=ResumeDetail)
async def get_resume(
    resume_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    resume = await _get_resume_with_access_check(resume_id, current_user, db)
    return _to_detail(resume)


@router.post("/{resume_id}/reparse", response_model=ResumeDetail)
async def reparse_resume(
    resume_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Manually re-triggers parsing on an already-uploaded resume — useful if
    the first pass failed (e.g. a transient storage read error) or after
    a parsing-logic improvement ships and existing resumes should benefit
    without needing to re-upload. Restricted to the resume's own student;
    a bulk "reparse everything" admin tool is a reasonable future addition
    but isn't needed yet at this scale.
    """
    resume = await _get_resume_with_access_check(resume_id, current_user, db)

    parsing_service = ResumeParsingService(db)
    success = await parsing_service.parse_and_store(resume.id)
    if not success:
        raise HTTPException(status_code=422, detail="Resume could not be parsed. The file may be unreadable.")

    refreshed = await ResumeRepository(db).get_by_id(resume.id)
    return _to_detail(refreshed)


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    resume = await _get_resume_with_access_check(resume_id, current_user, db)
    storage = StorageService()

    if resume.file_url.startswith("local://"):
        try:
            file_bytes = storage.read_local_file(resume.file_url)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Resume file is missing from storage.") from exc
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{resume.original_filename}"'},
        )

    # Cloudinary (or any future absolute-URL backend) — just redirect.
    return RedirectResponse(resume.file_url)


# ---------------------------------------------------------------------------
# PHASE E — Autofill endpoints
#
# Security: require_role("student") + ownership check via _resolve_student_resume.
# Never trust frontend-supplied student_id — derive it from the JWT.
# ---------------------------------------------------------------------------

async def _resolve_student_resume(
    resume_id: str, current_user: CurrentUser, db: AsyncIOMotorDatabase
) -> tuple:
    """Resolve student profile and verify resume ownership from auth token."""
    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    resume = await ResumeRepository(db).get_by_id(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found.")
    if resume.student_id != student.id:
        raise HTTPException(status_code=403, detail="You do not have access to this resume.")
    return student, resume


class AutofillSuggestionOut(BaseModel):
    patch: StudentProfileUpdateRequest
    education: list[dict]
    experience: list[dict]


@router.get("/{resume_id}/autofill-suggestion", response_model=AutofillSuggestionOut)
async def get_autofill_suggestion(
    resume_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    student, resume = await _resolve_student_resume(resume_id, current_user, db)
    service = ProfileAutofillService(db)
    suggestion = await service.build_suggestion(student_id=str(current_user.id), resume_id=resume_id)
    return AutofillSuggestionOut(patch=suggestion.patch, education=suggestion.education, experience=suggestion.experience)


@router.post("/{resume_id}/autofill-apply")
async def apply_autofill(
    resume_id: str,
    confirmed_patch: StudentProfileUpdateRequest,  # student may have edited fields before confirming
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    student, resume = await _resolve_student_resume(resume_id, current_user, db)
    profile_service = StudentProfileService(db)
    updated = await profile_service.update_profile(str(current_user.id), confirmed_patch)
    return updated