"""
PHASE C — app/routers/gap_analysis.py (CORRECTED)

Fix from the original draft: this codebase's real dependency is
`get_current_user` (returning a `CurrentUser` dataclass with `.id`,
`.role`, `.email`), not `get_current_student` — that name never existed
in app.core.deps and caused an ImportError.
"""
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.core.deps import CurrentUser, get_current_user, require_role
from app.core.database import get_database
from app.services.gap_analysis_service import GapAnalysisService

router = APIRouter(prefix="/assessments", tags=["gap-analysis"])


class SkillBreakdownOut(BaseModel):
    skill: str
    wrong_count: int
    mastery_pct: float


class GapAnalysisOut(BaseModel):
    breakdown: list[SkillBreakdownOut]
    narrative: str | None  # null if LLM was unavailable — frontend shows breakdown-only view


@router.get("/attempts/{attempt_id}/gap-analysis", response_model=GapAnalysisOut)
async def get_gap_analysis(
    attempt_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = GapAnalysisService(db)
    try:
        result = await service.analyze(student_user_id=current_user.id, attempt_id=attempt_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return GapAnalysisOut(
        breakdown=[
            SkillBreakdownOut(skill=b.skill, wrong_count=b.wrong_count, mastery_pct=round(b.mastery_pct, 1))
            for b in result.breakdown
        ],
        narrative=result.narrative,
    )