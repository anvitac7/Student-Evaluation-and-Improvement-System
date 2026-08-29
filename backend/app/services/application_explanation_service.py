"""
Application-level Explanation Service (Phase 7).

Provides unified explanation of placement application outcomes.
Combines:
  1. Eligibility check outcome.
  2. Matching breakdown (semantic, skills, experience).
  3. Assessment results (status, score vs threshold).
  4. Decision records (status, structured rejection reasons, notes).
  5. RAG-grounded narrative explanation synthesized by LLM.

Grounding Rule: The LLM narrates ONLY already-computed facts and retrieved
materials. It never invents criteria, scores, or decisions.
"""
from __future__ import annotations

import logging
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError
from app.ml.rag.knowledge_store import KnowledgeStore
from app.models.drive import ApplicationInDB, PlacementDriveInDB
from app.repositories.application_repository import ApplicationRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.resume_repository import ResumeRepository

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a compassionate, constructive university placement advisor explaining "
    "an application evaluation outcome to a student. You are given strictly verified "
    "facts: application status, eligibility status, match scores (semantic, skills, experience), "
    "missing skills, assessment performance, and structured decision reasons.\n\n"
    "Rules:\n"
    "1. Explain clearly and encouragingly why the application resulted in this status.\n"
    "2. If rejected or with missing skills/low assessment, provide 2-3 specific, actionable improvement steps.\n"
    "3. NEVER contradict or re-calculate the provided numbers or statuses.\n"
    "4. Ground every single statement in the provided facts only. Do not hallucinate."
)


class ApplicationExplanationResult(BaseModel):
    application_id: str
    status: str
    eligibility_passed: bool | None
    eligibility_reasons: list[str]
    final_score: float | None
    semantic_score: float | None
    skills_score: float | None
    experience_score: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    assessment_status: str
    assessment_score_pct: float | None
    rejection_reasons: list[str]
    rejection_note: str | None
    narrative: str | None


class ApplicationExplanationService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.applications = ApplicationRepository(db)
        self.drives = PlacementDriveRepository(db)
        self.companies = CompanyRepository(db)
        self.students = StudentRepository(db)
        self.tpos = TPORepository(db)
        self.resumes = ResumeRepository(db)
        self.knowledge_store = KnowledgeStore(db)

    async def explain_application(
        self, user_id: str, user_role: str, application_id: str
    ) -> ApplicationExplanationResult:
        app = await self.applications.get_by_id(application_id)
        if not app:
            raise ValueError("Application not found.")

        # Authorization:
        # - Student: must own the application
        # - TPO: must own the drive
        # - Admin: full access
        if user_role == "student":
            student = await self.students.get_by_user_id(user_id)
            if not student or app.student_id != student.id:
                raise PermissionError("You do not have access to this application.")
        elif user_role == "tpo":
            tpo = await self.tpos.get_by_user_id(user_id)
            if not tpo:
                raise PermissionError("TPO profile not found.")
            drive = await self.drives.get_by_id(app.drive_id)
            if not drive or drive.created_by != tpo.id:
                raise PermissionError("You do not have permission for this application.")

        drive = await self.drives.get_by_id(app.drive_id)
        company = await self.companies.get_by_id(drive.company_id) if drive else None
        company_name = company.name if company else "Company"

        # RAG retrieval for missing skills or weak areas
        retrieved_texts = []
        if app.missing_skills:
            chunks = await self.knowledge_store.retrieve(
                query_skills=app.missing_skills,
                chunk_types=["job_description", "skill_taxonomy", "syllabus_note"],
                top_k=4,
            )
            retrieved_texts = [c.text for c in chunks]

        facts = {
            "company": company_name,
            "role": drive.job_title if drive else "Role",
            "application_status": app.status,
            "eligibility_passed": app.eligibility_passed,
            "eligibility_reasons": app.eligibility_reasons,
            "final_score": app.final_score,
            "semantic_score": app.semantic_score,
            "skills_score": app.skills_score,
            "experience_score": app.experience_score,
            "matched_skills": app.matched_skills,
            "missing_skills": app.missing_skills,
            "assessment_status": app.assessment_status,
            "assessment_score_pct": app.assessment_score_pct,
            "rejection_reasons": app.rejection_reasons,
            "rejection_note": app.rejection_note,
            "retrieved_reference_material": retrieved_texts,
        }

        narrative = None
        try:
            narrative = llm_client.generate_text(_SYSTEM_PROMPT, str(facts), thinking=True)
        except LLMUnavailableError:
            logger.warning("LLM unavailable for application explanation (app=%s)", application_id)
        except Exception as exc:
            logger.warning("LLM generation error: %s", exc)

        return ApplicationExplanationResult(
            application_id=app.id,
            status=app.status,
            eligibility_passed=app.eligibility_passed,
            eligibility_reasons=app.eligibility_reasons,
            final_score=app.final_score,
            semantic_score=app.semantic_score,
            skills_score=app.skills_score,
            experience_score=app.experience_score,
            matched_skills=app.matched_skills,
            missing_skills=app.missing_skills,
            assessment_status=app.assessment_status,
            assessment_score_pct=app.assessment_score_pct,
            rejection_reasons=app.rejection_reasons,
            rejection_note=app.rejection_note,
            narrative=narrative,
        )
