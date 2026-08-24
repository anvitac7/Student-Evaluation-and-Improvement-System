"""
PHASE E — app/services/profile_autofill_service.py

DIAGNOSIS (confirmed by inspection, per the workflow doc's checklist,
item 1): ResumeParsingService.parse_and_store() writes `parsed`,
`resume_text`, `skill_set`, `experience_years` onto the RESUME document
only. Nothing ever pushes that data onto StudentInDB. ParsedResumeData
already stores education/experience as list[dict], not raw text blobs —
so item 2 of the diagnosis (unstructured raw-text blockers) does NOT
apply; the fields are already structured enough to map onto the profile.

FIX: after a resume finishes parsing, build a *suggested* profile patch
and return it for a review-and-confirm step — never silently overwrite
fields the student already filled in, and never silently save without
the student confirming (see router below).
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.resume import ParsedResumeData
from app.models.user import StudentInDB, StudentProfileUpdateRequest
from app.repositories.profile_repositories import StudentRepository
from app.repositories.resume_repository import ResumeRepository


class AutofillSuggestion:
    def __init__(self, patch: StudentProfileUpdateRequest, education: list[dict], experience: list[dict]):
        self.patch = patch
        # Education/experience aren't StudentInDB fields today (no such
        # columns exist on the student profile model) — surfaced
        # separately so the frontend can show them for review even though
        # they don't map onto a profile PATCH call. If/when the product
        # adds structured education/experience to StudentInDB, wire them
        # into `patch` the same way skills/phone are handled below.
        self.education = education
        self.experience = experience


class ProfileAutofillService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.resumes = ResumeRepository(db)
        self.students = StudentRepository(db)

    async def build_suggestion(self, student_id: str, resume_id: str) -> AutofillSuggestion:
        resume = await self.resumes.get_by_id(resume_id)
        if not resume or not resume.parsed:
            raise ValueError("Resume not found or not yet parsed")

        student = await self.students.get_by_user_id(student_id)  # matches existing repo method naming pattern
        parsed: ParsedResumeData = ParsedResumeData(**resume.parsed) if isinstance(resume.parsed, dict) else resume.parsed

        patch_fields: dict = {}

        # Auto-fill / suggest fields if not already populated or if placeholder
        if (not student.name or student.name == "(name not set)") and parsed.name:
            patch_fields["name"] = parsed.name
        if not student.phone and parsed.phone:
            patch_fields["phone"] = parsed.phone
        if not student.department and parsed.department:
            patch_fields["department"] = parsed.department
        if not student.batch_year and parsed.batch_year:
            patch_fields["batch_year"] = parsed.batch_year
        if not student.cgpa and parsed.cgpa:
            patch_fields["cgpa"] = parsed.cgpa
        if not student.linkedin_url and parsed.linkedin_url:
            patch_fields["linkedin_url"] = parsed.linkedin_url
        if not student.github_url and parsed.github_url:
            patch_fields["github_url"] = parsed.github_url
        if not student.portfolio_url and parsed.portfolio_url:
            patch_fields["portfolio_url"] = parsed.portfolio_url

        # Certificates & Achievements merge
        if parsed.certifications:
            existing_certs = set(student.certificates or [])
            new_certs = [c for c in parsed.certifications if c not in existing_certs]
            if new_certs:
                patch_fields["certificates"] = (student.certificates or []) + new_certs

        if parsed.achievements:
            existing_ach = set(student.achievements or [])
            new_ach = [a for a in parsed.achievements if a not in existing_ach]
            if new_ach:
                patch_fields["achievements"] = (student.achievements or []) + new_ach

        # Skills merge case: additively union skills
        if not student.skills and resume.skill_set:
            patch_fields["skills"] = resume.skill_set
        elif resume.skill_set:
            merged = sorted(set(student.skills or []) | set(resume.skill_set))
            if merged != sorted(student.skills or []):
                patch_fields["skills"] = merged

        patch = StudentProfileUpdateRequest(**patch_fields)
        return AutofillSuggestion(patch=patch, education=parsed.education, experience=parsed.experience)