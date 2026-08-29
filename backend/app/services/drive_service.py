from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.drive import (
    ApplicationInDB,
    ApplicationStatus,
    AssessmentStatus,
    CompanyInDB,
    DriveCreateRequest,
    DriveStatus,
    DriveUpdateRequest,
    PlacementDriveInDB,
    VALID_STATUS_TRANSITIONS,
)
from app.models.user import StudentInDB
from app.repositories.application_repository import ApplicationRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository


class DriveError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DriveService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.companies = CompanyRepository(db)
        self.drives = PlacementDriveRepository(db)
        self.applications = ApplicationRepository(db)
        self.students = StudentRepository(db)
        self.tpos = TPORepository(db)
        self.assessments = AssessmentRepository(db)

    # -----------------------------------------------------------------
    # Drive CRUD
    # -----------------------------------------------------------------
    async def _get_or_create_company(self, payload: DriveCreateRequest) -> CompanyInDB:
        existing = await self.companies.get_by_name(payload.company_name)
        if existing:
            return existing
        return await self.companies.create(
            {
                "name": payload.company_name,
                "description": payload.company_description,
                "website": payload.company_website,
                "industry": payload.company_industry,
            }
        )

    async def create_drive(self, tpo_user_id: str, payload: DriveCreateRequest) -> PlacementDriveInDB:
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        if not tpo:
            raise DriveError("TPO profile not found.", 404)

        # Validate assessment if attached
        req_assessment_id = None
        if payload.required_assessment_id:
            assessment = await self.assessments.get_by_id(payload.required_assessment_id)
            if not assessment:
                raise DriveError("Selected required assessment not found.", 404)
            req_assessment_id = assessment.id

        company = await self._get_or_create_company(payload)

        drive = await self.drives.create(
            {
                "company_id": company.id,
                "job_title": payload.job_title,
                "description": payload.description,
                "jd_text": payload.jd_text,
                "jd_embedding": None,
                "required_skills": payload.required_skills,
                "experience_required_years": payload.experience_required_years,
                "package": payload.package,
                "location": payload.location,
                "eligibility": payload.eligibility.model_dump(),
                "deadline": payload.deadline,
                "selection_process": payload.selection_process,
                "status": DriveStatus.OPEN.value,
                "created_by": tpo.id,
                "created_at": datetime.utcnow(),
                "required_assessment_id": req_assessment_id,
                "assessment_min_score_pct": payload.assessment_min_score_pct,
                "assessment_deadline": payload.assessment_deadline,
            }
        )

        # Link assessment back to drive
        if req_assessment_id:
            await self.assessments.update_by_id(req_assessment_id, {"drive_id": drive.id})

        return drive

    async def _require_owned_drive(self, tpo_user_id: str, drive_id: str) -> PlacementDriveInDB:
        drive = await self.drives.get_by_id(drive_id)
        if not drive:
            raise DriveError("Drive not found.", 404)
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        if not tpo or drive.created_by != tpo.id:
            raise DriveError("You do not have permission to modify this drive.", 403)
        return drive

    async def update_drive(
        self, tpo_user_id: str, drive_id: str, payload: DriveUpdateRequest
    ) -> PlacementDriveInDB:
        drive = await self._require_owned_drive(tpo_user_id, drive_id)

        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "eligibility" in update_data and payload.eligibility:
            update_data["eligibility"] = payload.eligibility.model_dump()
        if "status" in update_data and payload.status:
            update_data["status"] = payload.status.value

        if "required_assessment_id" in update_data:
            if payload.required_assessment_id:
                assessment = await self.assessments.get_by_id(payload.required_assessment_id)
                if not assessment:
                    raise DriveError("Selected required assessment not found.", 404)
                update_data["required_assessment_id"] = assessment.id
                await self.assessments.update_by_id(assessment.id, {"drive_id": drive.id})
            else:
                update_data["required_assessment_id"] = None

        # The cached jd_embedding (Phase 9) is only valid for the exact text
        # it was computed from — if anything that feeds that text changes,
        # invalidate the cache so the next match request recomputes it
        # rather than silently scoring against stale content.
        _TEXT_AFFECTING_FIELDS = {"job_title", "description", "jd_text", "required_skills", "experience_required_years"}
        if _TEXT_AFFECTING_FIELDS & update_data.keys():
            update_data["jd_embedding"] = None

        updated = await self.drives.update_by_id(drive_id, update_data)
        if not updated:
            raise DriveError("Drive not found.", 404)
        return updated

    async def delete_drive(self, tpo_user_id: str, drive_id: str) -> None:
        drive = await self._require_owned_drive(tpo_user_id, drive_id)
        await self.drives.delete_by_id(drive.id)

    async def get_my_drives(self, tpo_user_id: str, page: int = 1, limit: int = 50) -> list[PlacementDriveInDB]:
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        if not tpo:
            raise DriveError("TPO profile not found.", 404)
        return await self.drives.find_many(
            {"created_by": tpo.id}, page=page, limit=limit, sort=[("created_at", -1)]
        )

    # -----------------------------------------------------------------
    # Applications
    # -----------------------------------------------------------------
    @staticmethod
    def _check_eligibility(student: StudentInDB, drive: PlacementDriveInDB) -> tuple[bool, list[str]]:
        reasons = []
        elig = drive.eligibility
        if elig.min_cgpa is not None and (student.cgpa is None or student.cgpa < elig.min_cgpa):
            reasons.append(f"Minimum CGPA required: {elig.min_cgpa} (yours: {student.cgpa or 'N/A'})")
        if elig.departments and student.department not in elig.departments:
            reasons.append(f"Open only to: {', '.join(elig.departments)} (yours: {student.department or 'N/A'})")
        if elig.batch_years and student.batch_year not in elig.batch_years:
            reasons.append(f"Open only to batch years: {', '.join(map(str, elig.batch_years))} (yours: {student.batch_year or 'N/A'})")
        return (len(reasons) == 0, reasons)

    async def apply_to_drive(self, student_user_id: str, drive_id: str) -> ApplicationInDB:
        student = await self.students.get_by_user_id(student_user_id)
        if not student:
            raise DriveError("Student profile not found.", 404)

        drive = await self.drives.get_by_id(drive_id)
        if not drive:
            raise DriveError("Drive not found.", 404)
        if drive.status != DriveStatus.OPEN:
            raise DriveError("This drive is closed.", 400)
        if drive.deadline < datetime.utcnow():
            raise DriveError("The application deadline has passed.", 400)

        if not student.active_resume_id:
            raise DriveError("Upload a resume before applying.", 400)

        is_eligible, reasons = self._check_eligibility(student, drive)
        if not is_eligible:
            raise DriveError("You are not eligible for this drive: " + "; ".join(reasons), 403)

        existing = await self.applications.get_existing(drive.id, student.id)
        if existing:
            raise DriveError("You have already applied to this drive.", 409)

        initial_assessment_status = (
            AssessmentStatus.PENDING.value if drive.required_assessment_id else AssessmentStatus.NOT_REQUIRED.value
        )

        return await self.applications.create(
            {
                "drive_id": drive.id,
                "student_id": student.id,
                "resume_id": student.active_resume_id,
                "status": ApplicationStatus.APPLIED.value,
                "eligibility_passed": True,
                "eligibility_reasons": [],
                "final_score": None,
                "semantic_score": None,
                "skills_score": None,
                "experience_score": None,
                "matched_skills": [],
                "missing_skills": [],
                "assessment_attempt_id": None,
                "assessment_score_pct": None,
                "assessment_status": initial_assessment_status,
                "rejection_reasons": [],
                "rejection_note": None,
                "decision_at": None,
                "evaluation_version": None,
                "applied_at": datetime.utcnow(),
            }
        )

    async def update_application_status(
        self,
        tpo_user_id: str,
        drive_id: str,
        application_id: str,
        new_status: str,
        rejection_reasons: list[str] | None = None,
        rejection_note: str | None = None,
    ) -> ApplicationInDB:
        await self._require_owned_drive(tpo_user_id, drive_id)

        application = await self.applications.get_by_id(application_id)
        if not application or application.drive_id != drive_id:
            raise DriveError("Application not found for this drive.", 404)

        try:
            target_status = ApplicationStatus(new_status)
            current_status = ApplicationStatus(application.status)
        except ValueError:
            raise DriveError(f"Invalid status: {new_status}", 400)

        # Status transition validation
        valid_next = VALID_STATUS_TRANSITIONS.get(current_status, set())
        if target_status != current_status and target_status not in valid_next:
            raise DriveError(
                f"Invalid status transition from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed transitions: {[s.value for s in valid_next]}",
                400,
            )

        update_fields: dict = {
            "status": target_status.value,
            "decision_at": datetime.utcnow(),
        }

        if target_status == ApplicationStatus.REJECTED:
            update_fields["rejection_reasons"] = rejection_reasons or []
            update_fields["rejection_note"] = rejection_note
        elif target_status in (ApplicationStatus.SHORTLISTED, ApplicationStatus.SELECTED):
            update_fields["rejection_reasons"] = []
            update_fields["rejection_note"] = None

        updated = await self.applications.update_by_id(application_id, update_fields)
        if not updated:
            raise DriveError("Application not found for this drive.", 404)
        return updated
