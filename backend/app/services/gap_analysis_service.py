"""
PHASE C — app/services/gap_analysis_service.py (CORRECTED)

Fix from the original draft: `attempt.student_id` and knowledge-state
records are keyed by the STUDENT PROFILE id, not the auth user id — same
resolution AssessmentService._resolve_student_id() does. The router
passes the raw user id (from CurrentUser.id), so this service must
resolve it to the profile id itself before querying, exactly like
AssessmentService does.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError
from app.ml.rag.knowledge_store import KnowledgeStore
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.knowledge_state_repository import KnowledgeStateRepository
from app.repositories.profile_repositories import StudentRepository
from app.repositories.question_repository import QuestionRepository

logger = logging.getLogger(__name__)

WEAK_MASTERY_THRESHOLD = 50.0

_SYSTEM_PROMPT = (
    "You are an academic coach explaining a student's test results. You will "
    "be given, per skill: how many questions the student got wrong, their "
    "current mastery percentage (already computed by the grading/knowledge-"
    "tracing system — you must NOT recompute or contradict it), and short "
    "reference material retrieved for the weak skills. Write a short (120-180 "
    "word), specific, encouraging explanation of what likely caused the score "
    "and what to review next. Every claim must be traceable to the given "
    "facts or retrieved material — do not invent facts, do not guess at "
    "content that wasn't provided to you."
)


@dataclass
class SkillBreakdown:
    skill: str
    wrong_count: int
    mastery_pct: float


@dataclass
class GapAnalysisResult:
    breakdown: list[SkillBreakdown]
    narrative: str | None  # None if LLM unavailable — endpoint still returns breakdown


class GapAnalysisService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.attempts = AttemptRepository(db)
        self.knowledge_states = KnowledgeStateRepository(db)
        self.knowledge_store = KnowledgeStore(db)
        self.students = StudentRepository(db)
        self.questions = QuestionRepository(db)

    async def _resolve_student_id(self, student_user_id: str) -> str:
        """Same mapping as AssessmentService._resolve_student_id — the
        PROFILE document's own _id is what's stored as "student_id" on
        attempts/knowledge_states, not the auth user id."""
        student = await self.students.get_by_user_id(student_user_id)
        if not student:
            raise ValueError("Student profile not found for this user")
        return str(student.id)

    async def analyze(self, student_user_id: str, attempt_id: str) -> GapAnalysisResult:
        resolved_student_id = await self._resolve_student_id(student_user_id)

        attempt = await self.attempts.get_by_id(attempt_id)
        if not attempt or str(attempt.student_id) != resolved_student_id:
            raise ValueError("Attempt not found for this student")

        # 1. Wrong questions grouped by skill. AnsweredQuestion only stores
        # question_id + is_correct — it does NOT carry skill_tag directly
        # (that lives on the Question document, as skill_tags: list[str],
        # since one question can map to several skills). is_correct can
        # also be None for ungraded descriptive answers — only explicit
        # `False` counts as "wrong" here, None is skipped.
        wrong_by_skill: dict[str, int] = {}
        for answer in attempt.answers:
            if answer.is_correct is not False:
                continue
            question = await self.questions.get_by_id(answer.question_id)
            if not question:
                continue
            for tag in question.skill_tags:
                wrong_by_skill[tag] = wrong_by_skill.get(tag, 0) + 1

        if not wrong_by_skill:
            return GapAnalysisResult(breakdown=[], narrative="Great work — no weak areas detected on this attempt.")

        # 2. Current mastery per skill — already tracked by knowledge tracing.
        breakdown: list[SkillBreakdown] = []
        for skill, wrong_count in wrong_by_skill.items():
            state = await self.knowledge_states.get_by_student_and_skill(resolved_student_id, skill)
            mastery = state.mastery_pct if state else 50.0
            breakdown.append(SkillBreakdown(skill=skill, wrong_count=wrong_count, mastery_pct=mastery))

        weak_skills = [b.skill for b in breakdown if b.mastery_pct < WEAK_MASTERY_THRESHOLD] or [
            b.skill for b in breakdown
        ]

        # 3. Retrieve grounded reference material for the weak skills.
        chunks = await self.knowledge_store.retrieve(
            query_skills=weak_skills, chunk_types=["syllabus_note", "question_explanation"], top_k=5
        )

        # 4. Narrate — already-computed facts only, never a hard failure.
        facts = {
            "breakdown": [{"skill": b.skill, "wrong_count": b.wrong_count, "mastery_pct": round(b.mastery_pct, 1)} for b in breakdown],
            "retrieved_material": [c.text for c in chunks],
        }

        try:
            narrative = llm_client.generate_text(_SYSTEM_PROMPT, str(facts), thinking=True)
        except LLMUnavailableError:
            logger.warning(
                "LLM unavailable for gap analysis (student=%s attempt=%s) — returning breakdown only.",
                resolved_student_id, attempt_id,
            )
            narrative = None

        return GapAnalysisResult(breakdown=breakdown, narrative=narrative)