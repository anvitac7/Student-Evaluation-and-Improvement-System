"""
PHASE D — app/routers/jd_explanation.py (CORRECTED)

Fixes from the original draft:
  1. get_current_student -> get_current_user (real dep name).
  2. Calls JDExplanationService.explain(resume_id, drive_id) — the
     service itself now resolves resume/drive/company_name internally
     to match MatchingService's real signature (see FIX_jd_explanation_service.py).
"""
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.core.deps import CurrentUser, require_role
from app.core.database import get_database
from app.services.jd_explanation_service import JDExplanationService

router = APIRouter(prefix="/drives", tags=["jd-explanation"])


class MatchBreakdownOut(BaseModel):
    final_score: float
    semantic_score: float
    skills_score: float
    experience_score: float
    matched_skills: list[str]
    missing_skills: list[str]


class JDExplanationOut(BaseModel):
    breakdown: MatchBreakdownOut
    narrative: str | None


@router.get("/{drive_id}/match-explanation", response_model=JDExplanationOut)
async def get_match_explanation(
    drive_id: str,
    resume_id: str,  # query param — the student's active resume
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    # Ownership check: verify the resume belongs to this student
    from app.repositories.resume_repository import ResumeRepository
    from app.repositories.profile_repositories import StudentRepository

    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    resume = await ResumeRepository(db).get_by_id(resume_id)
    if not resume or resume.student_id != student.id:
        raise HTTPException(status_code=404, detail="Resume not found.")

    service = JDExplanationService(db)
    try:
        result = await service.explain(resume_id=resume_id, drive_id=drive_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    b = result.breakdown
    return JDExplanationOut(
        breakdown=MatchBreakdownOut(
            final_score=round(b["final_score"], 3),
            semantic_score=round(b["semantic_score"], 3),
            skills_score=round(b["skills_score"], 3),
            experience_score=round(b["experience_score"], 3),
            matched_skills=b.get("matched_skills", []),
            missing_skills=b.get("missing_skills", []),
        ),
        narrative=result.narrative,
    )


# ---------------------------------------------------------------------
# Ingestion hook — call this from wherever a drive's JD is created/edited
# (app/services/drive_service.py, on create + update):
#
# from app.ml.rag.knowledge_store import KnowledgeStore
#
# async def on_drive_saved(db, drive_id, jd_text, required_skills):
#     store = KnowledgeStore(db)
#     await store.ingest(
#         text=jd_text, chunk_type="job_description",
#         tags=required_skills, source_id=drive_id,
#     )
# ---------------------------------------------------------------------