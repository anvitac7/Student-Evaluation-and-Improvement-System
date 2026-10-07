"""
Student Insights router — the student-facing "where should I focus?"
endpoint, aggregated across every assessment the student has taken.

Kept as its own router (rather than folded into assessments.py) because it
answers a different question from /assessments/attempts/{id}/gap-analysis:
that one is scoped to a single attempt and explains a single score, this one
is scoped to the whole history and drives a revision plan.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.core.limiter import limiter
from app.services.student_insights_service import StudentInsightsService

router = APIRouter(prefix="/insights", tags=["Student Insights"])


class SkillFocusOut(BaseModel):
    skill: str
    mastery_pct: float
    wrong_count: int
    attempts_touched: int
    times_seen: int
    priority_score: float
    severity: str
    trend: str
    last_missed_at: str | None = None


class StudyGuideItemOut(BaseModel):
    question_id: str
    skill: str
    difficulty: str
    question_type: str
    text: str
    your_answer: str | None
    correct_answer: str | None
    missed_count: int


class InsightsOut(BaseModel):
    total_attempts: int
    total_questions_answered: int
    overall_accuracy_pct: float
    average_mastery_pct: float | None
    focus_areas: list[SkillFocusOut]
    strengths: list[SkillFocusOut]
    study_guide: list[StudyGuideItemOut]
    # Null whenever no LLM provider is configured. The endpoint is fully
    # usable without it — frontend shows the deterministic view only.
    narrative: str | None


@router.get("/me", response_model=InsightsOut)
@limiter.limit("20/minute")
async def my_insights(
    request: Request,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = StudentInsightsService(db)
    try:
        result = await service.build(student_user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def to_focus(f):
        return SkillFocusOut(
            skill=f.skill,
            mastery_pct=f.mastery_pct,
            wrong_count=f.wrong_count,
            attempts_touched=f.attempts_touched,
            times_seen=f.times_seen,
            priority_score=f.priority_score,
            severity=f.severity,
            trend=f.trend,
            last_missed_at=f.last_missed_at.isoformat() if f.last_missed_at else None,
        )

    return InsightsOut(
        total_attempts=result.total_attempts,
        total_questions_answered=result.total_questions_answered,
        overall_accuracy_pct=result.overall_accuracy_pct,
        average_mastery_pct=result.average_mastery_pct,
        focus_areas=[to_focus(f) for f in result.focus_areas],
        strengths=[to_focus(s) for s in result.strengths],
        study_guide=[
            StudyGuideItemOut(
                question_id=i.question_id,
                skill=i.skill,
                difficulty=i.difficulty,
                question_type=i.question_type,
                text=i.text,
                your_answer=i.your_answer,
                correct_answer=i.correct_answer,
                missed_count=i.missed_count,
            )
            for i in result.study_guide
        ],
        narrative=result.narrative,
    )