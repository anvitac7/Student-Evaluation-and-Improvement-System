"""
Application Screening Service.

Centralized deterministic screening orchestration for placement drives.
Handles:
  1. Eligibility verification (min CGPA, department, batch year).
  2. Assessment reconciliation (checks deadlines, updates expired statuses).
  3. Batch matching & final score calculation using the canonical formula
     (0.40 * semantic + 0.30 * skills + 0.20 * experience + 0.10 * assessment).
  4. Score persistence on Application documents for historical record.
  5. Deterministic shortlist recommendation calculation.
  6. Screening summary statistics for TPO dashboards.
"""
from __future__ import annotations

from datetime import datetime
import logging
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.drive import (
    ApplicationInDB,
    ApplicationStatus,
    AssessmentStatus,
    PlacementDriveInDB,
    ScreeningSummary,
)
from app.repositories.application_repository import ApplicationRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.resume_repository import ResumeRepository
from app.services.matching_service import MatchingService, compute_final_score

logger = logging.getLogger(__name__)


class ScreeningService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.drives = PlacementDriveRepository(db)
        self.applications = ApplicationRepository(db)
        self.students = StudentRepository(db)
        self.resumes = ResumeRepository(db)
        self.companies = CompanyRepository(db)
        self.tpos = TPORepository(db)
        self.matching = MatchingService(db)

    async def _require_tpo_drive(self, tpo_user_id: str, drive_id: str) -> tuple[PlacementDriveInDB, str]:
        drive = await self.drives.get_by_id(drive_id)
        if not drive:
            raise ValueError("Drive not found.")
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        if not tpo or drive.created_by != tpo.id:
            raise PermissionError("You do not have permission for this drive.")
        company = await self.companies.get_by_id(drive.company_id)
        company_name = company.name if company else "the company"
        return drive, company_name

    async def reconcile_expired_assessments(self, drive: PlacementDriveInDB) -> int:
        """If a drive had an assessment deadline that has passed, marks any
        pending assessments as expired."""
        if not drive.assessment_deadline or drive.assessment_deadline > datetime.utcnow():
            return 0

        pending_apps = await self.applications.find_many(
            {"drive_id": drive.id, "assessment_status": AssessmentStatus.PENDING.value},
            limit=5000,
        )
        updated_count = 0
        for app in pending_apps:
            await self.applications.update_by_id(
                app.id,
                {"assessment_status": AssessmentStatus.EXPIRED.value},
            )
            updated_count += 1
        return updated_count

    async def screen_applications(self, tpo_user_id: str, drive_id: str) -> list[ApplicationInDB]:
        """Runs the deterministic evaluation pipeline for all applications in this drive
        and persists scores directly on each Application document."""
        drive, company_name = await self._require_tpo_drive(tpo_user_id, drive_id)
        await self.reconcile_expired_assessments(drive)

        applications = await self.applications.find_many({"drive_id": drive.id}, limit=5000)
        if not applications:
            return []

        # Load resumes
        resume_ids = [app.resume_id for app in applications]
        resumes_map = {}
        for r_id in set(resume_ids):
            r = await self.resumes.get_by_id(r_id)
            if r:
                resumes_map[r.id] = r

        # Evaluate match scores for valid resumes
        valid_resumes = [resumes_map[a.resume_id] for a in applications if a.resume_id in resumes_map]
        match_scores_map = {}
        if valid_resumes:
            try:
                ranked = await self.matching.rank_resumes_for_drive(drive, company_name, valid_resumes)
                for item in ranked:
                    match_scores_map[item["candidate_id"]] = item
            except Exception as exc:
                logger.warning("Matching evaluation failed during screening: %s", exc)

        has_assessment = bool(drive.required_assessment_id)
        updated_apps = []

        for app in applications:
            student = await self.students.get_by_id(app.student_id)
            # 1. Eligibility
            is_eligible = True
            elig_reasons = []
            if student:
                elig = drive.eligibility
                if elig.min_cgpa is not None and (student.cgpa is None or student.cgpa < elig.min_cgpa):
                    is_eligible = False
                    elig_reasons.append(f"Minimum CGPA required: {elig.min_cgpa}")
                if elig.departments and student.department not in elig.departments:
                    is_eligible = False
                    elig_reasons.append(f"Open only to: {', '.join(elig.departments)}")
                if elig.batch_years and student.batch_year not in elig.batch_years:
                    is_eligible = False
                    elig_reasons.append(f"Open only to batch years: {', '.join(map(str, elig.batch_years))}")

            # 2. Match scores
            match_data = match_scores_map.get(app.resume_id, {})
            semantic_score = match_data.get("semantic_score", 0.0)
            skills_score = match_data.get("skills_score", 0.0)
            experience_score = match_data.get("experience_score", 0.0)
            matched_skills = match_data.get("matched_skills", [])
            missing_skills = match_data.get("missing_skills", [])

            # 3. Canonical Final Score
            final_score = compute_final_score(
                semantic=semantic_score,
                skills_score=skills_score,
                experience_score=experience_score,
                assessment_score_pct=app.assessment_score_pct,
                has_assessment=has_assessment,
            )

            update_data = {
                "eligibility_passed": is_eligible,
                "eligibility_reasons": elig_reasons,
                "final_score": round(final_score, 4),
                "semantic_score": round(semantic_score, 4),
                "skills_score": round(skills_score, 4),
                "experience_score": round(experience_score, 4),
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
                "evaluation_version": "v1.0-canonical",
            }
            updated = await self.applications.update_by_id(app.id, update_data)
            if updated:
                updated_apps.append(updated)

        return updated_apps

    async def get_screening_summary(self, tpo_user_id: str, drive_id: str) -> ScreeningSummary:
        drive, _ = await self._require_tpo_drive(tpo_user_id, drive_id)
        await self.reconcile_expired_assessments(drive)

        applications = await self.applications.find_many({"drive_id": drive.id}, limit=5000)

        total = len(applications)
        eligible = sum(1 for a in applications if a.eligibility_passed is not False)
        ineligible = sum(1 for a in applications if a.eligibility_passed is False)

        pending = sum(1 for a in applications if a.assessment_status == AssessmentStatus.PENDING.value)
        passed = sum(1 for a in applications if a.assessment_status == AssessmentStatus.PASSED.value)
        failed = sum(1 for a in applications if a.assessment_status == AssessmentStatus.FAILED.value)
        expired = sum(1 for a in applications if a.assessment_status == AssessmentStatus.EXPIRED.value)
        not_req = sum(1 for a in applications if a.assessment_status == AssessmentStatus.NOT_REQUIRED.value)

        shortlisted = sum(1 for a in applications if a.status == ApplicationStatus.SHORTLISTED.value)
        rejected = sum(1 for a in applications if a.status == ApplicationStatus.REJECTED.value)
        selected = sum(1 for a in applications if a.status == ApplicationStatus.SELECTED.value)

        # Recommended shortlist candidate count: eligible + passed/not_req + final_score >= 0.65
        recommended = sum(
            1
            for a in applications
            if a.eligibility_passed is not False
            and a.assessment_status in (AssessmentStatus.PASSED.value, AssessmentStatus.NOT_REQUIRED.value)
            and (a.final_score or 0) >= 0.65
        )

        return ScreeningSummary(
            total_applications=total,
            eligible=eligible,
            ineligible=ineligible,
            assessment_pending=pending,
            assessment_passed=passed,
            assessment_failed=failed,
            assessment_expired=expired,
            assessment_not_required=not_req,
            shortlisted=shortlisted,
            rejected=rejected,
            selected=selected,
            recommended_shortlist=recommended,
        )

    async def get_recommended_shortlist(
        self, tpo_user_id: str, drive_id: str, top_n: int = 10, min_score: float = 0.60
    ) -> list[ApplicationInDB]:
        """Returns top N candidates who meet all deterministic criteria sorted by final_score descending."""
        drive, _ = await self._require_tpo_drive(tpo_user_id, drive_id)
        applications = await self.applications.find_many({"drive_id": drive.id}, limit=5000)

        candidates = [
            a
            for a in applications
            if a.eligibility_passed is not False
            and a.assessment_status in (AssessmentStatus.PASSED.value, AssessmentStatus.NOT_REQUIRED.value)
            and a.status == ApplicationStatus.APPLIED.value
            and (a.final_score or 0) >= min_score
        ]

        candidates.sort(key=lambda a: (a.final_score or 0.0), reverse=True)
        return candidates[:top_n]
