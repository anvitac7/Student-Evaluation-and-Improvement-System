import hashlib
import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.models.resume import ResumeInDB
from app.repositories.profile_repositories import StudentRepository
from app.repositories.resume_repository import ResumeRepository
from app.services.resume_parsing_service import ResumeParsingService
from app.services.storage_service import StorageService

settings = get_settings()

PDF_MAGIC_BYTES = b"%PDF"
MAX_RESUME_SIZE_BYTES = settings.MAX_RESUME_SIZE_MB * 1024 * 1024


class ResumeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ResumeService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.resumes = ResumeRepository(db)
        self.students = StudentRepository(db)
        self.storage = StorageService()

    async def upload_resume(self, student_user_id: str, filename: str, file_bytes: bytes) -> ResumeInDB:
        self._validate_file(filename, file_bytes)

        student = await self.students.get_by_user_id(student_user_id)
        if not student:
            raise ResumeError("Student profile not found.", 404)

        file_hash = hashlib.sha256(file_bytes).hexdigest()

        active = await self.resumes.get_active_for_student(student.id)
        if active and active.file_hash == file_hash:
            raise ResumeError("This is identical to your currently active resume.", 409)

        version = await self.resumes.get_next_version_number(student.id)

        # Storage key is independent of the eventual Mongo _id (which
        # doesn't exist until after insert) — just a unique content key.
        storage_key = str(uuid.uuid4())
        file_url = await self.storage.save_pdf(file_bytes, student.id, storage_key)

        # Deactivate old versions BEFORE inserting the new one, so there's
        # never a window with two active resumes for the same student.
        await self.resumes.deactivate_all_for_student(student.id)

        resume = await self.resumes.create(
            {
                "student_id": student.id,
                "version": version,
                "original_filename": filename,
                "file_url": file_url,
                "file_hash": file_hash,
                "file_size_bytes": len(file_bytes),
                "parsed": None,
                "resume_text": None,
                "skill_set": [],
                "experience_years": None,
                "uploaded_at": datetime.utcnow(),
                "is_active": True,
            }
        )

        await self.students.update_by_id(student.id, {"active_resume_id": resume.id})

        # Parse synchronously — no background task queue in this stack yet
        # (Celery/RQ would be the natural addition if parsing latency ever
        # becomes a problem; regex + a small spaCy model is fast enough not
        # to need one now). A parsing failure never fails the upload itself
        # — parse_and_store() logs and returns False rather than raising.
        parsing_service = ResumeParsingService(self.db)
        parsed_ok = await parsing_service.parse_and_store(resume.id)
        if parsed_ok:
            refreshed = await self.resumes.get_by_id(resume.id)
            if refreshed:
                resume = refreshed

            # Automatically autofill/merge profile fields (name, phone, skills)
            try:
                from app.services.profile_autofill_service import ProfileAutofillService
                from app.services.student_profile_service import StudentProfileService

                autofill_service = ProfileAutofillService(self.db)
                suggestion = await autofill_service.build_suggestion(student_user_id, resume.id)
                # Check if there are non-empty fields to update
                fields_to_update = suggestion.patch.model_dump(exclude_unset=True)
                if any(v is not None and v != [] and v != "" for v in fields_to_update.values()):
                    profile_service = StudentProfileService(self.db)
                    await profile_service.update_profile(student_user_id, suggestion.patch)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Profile auto-population encountered an issue: %s", exc, exc_info=True)

        return resume

    @staticmethod
    def _validate_file(filename: str, file_bytes: bytes) -> None:
        if not filename.lower().endswith(".pdf"):
            raise ResumeError("Only PDF files are accepted.")
        if len(file_bytes) == 0:
            raise ResumeError("The uploaded file is empty.")
        if not file_bytes.startswith(PDF_MAGIC_BYTES):
            raise ResumeError("The uploaded file is not a valid PDF.")
        if len(file_bytes) > MAX_RESUME_SIZE_BYTES:
            raise ResumeError(f"File exceeds the {settings.MAX_RESUME_SIZE_MB}MB size limit.", 413)
