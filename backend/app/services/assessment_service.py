"""
Adaptive assessment engine.

Selection strategy: start at Medium difficulty. A correct answer moves the
NEXT question one level harder; a wrong answer moves it one level easier
(clamped at the Easy/Hard ends) — a simple, transparent adaptive strategy
matching the project's stated requirement, rather than a more elaborate
IRT/CAT model that would need calibrated item-difficulty parameters this
system doesn't have yet.

Grading: MCQ is exact-match against `correct_answer`, fully automatic.
Coding is exact-match against an expected-output string — NOT real code
execution (running untrusted student code needs a sandboxed executor,
which is a meaningfully large and security-sensitive feature deliberately
out of scope here; flagged as a known limitation, not silently faked).
Descriptive questions are stored ungraded (`is_correct=None`) for manual
review — there's no reliable free/automatic way to grade free-text answers
without an LLM-grading pipeline, which is its own scope decision to make
deliberately, not bolt on as an afterthought.
"""
import random
import secrets
from datetime import datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.assessment import (
    DIFFICULTY_MARKS,
    DIFFICULTY_ORDER,
    AssessmentAttemptInDB,
    AssessmentInDB,
    AttemptStatus,
    DifficultyLevel,
    QuestionInDB,
    QuestionStudentView,
    QuestionType,
)
from app.models.drive import AssessmentStatus
from app.repositories.activity_log_repository import log_activity
from app.repositories.application_repository import ApplicationRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.profile_repositories import StudentRepository
from app.repositories.question_repository import QuestionRepository
from app.services.knowledge_tracing_service import KnowledgeTracingService


class AssessmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def to_student_view(question: QuestionInDB) -> QuestionStudentView:
    shuffled_options = random.sample(question.options, len(question.options)) if question.options else []
    return QuestionStudentView(
        id=question.id,
        difficulty=question.difficulty,
        type=question.type,
        text=question.text,
        options=shuffled_options,
        marks=question.marks,
    )


def _grade(question: QuestionInDB, response: str) -> bool | None:
    if question.type == QuestionType.MCQ:
        return response.strip() == (question.correct_answer or "").strip()
    if question.type == QuestionType.CODING:
        return response.strip() == (question.correct_answer or "").strip()
    return None  # descriptive — manual review


def _adjust_difficulty(current: DifficultyLevel, was_correct: bool) -> DifficultyLevel:
    idx = DIFFICULTY_ORDER.index(current)
    if was_correct:
        idx = min(idx + 1, len(DIFFICULTY_ORDER) - 1)
    else:
        idx = max(idx - 1, 0)
    return DIFFICULTY_ORDER[idx]


class AssessmentService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.assessments = AssessmentRepository(db)
        self.attempts = AttemptRepository(db)
        self.questions = QuestionRepository(db)
        self.students = StudentRepository(db)
        self.applications = ApplicationRepository(db)
        self.drives = PlacementDriveRepository(db)
        self.kts = KnowledgeTracingService(db)

    async def _resolve_student_id(self, student_user_id: str) -> str:
        student = await self.students.get_by_user_id(student_user_id)
        if not student:
            raise AssessmentError("Student profile not found.", 404)
        return student.id

    async def start_attempt(
        self,
        student_user_id: str,
        assessment_id: str,
        fingerprint_hash: str | None = None,
        ip_address: str | None = None,
        application_id: str | None = None,
    ) -> tuple[AssessmentAttemptInDB, QuestionInDB | None]:
        student_id = await self._resolve_student_id(student_user_id)

        assessment = await self.assessments.get_by_id(assessment_id)
        if not assessment:
            raise AssessmentError("Assessment not found.", 404)

        # If application_id is supplied, validate it belongs to this student and matches drive
        application = None
        if application_id:
            application = await self.applications.get_by_id(application_id)
            if not application or application.student_id != student_id:
                raise AssessmentError("Application not found for this student.", 404)
            drive = await self.drives.get_by_id(application.drive_id)
            if not drive:
                raise AssessmentError("Drive not found.", 404)
            if drive.required_assessment_id and drive.required_assessment_id != assessment.id:
                raise AssessmentError("This assessment does not match the drive requirements.", 400)
            if drive.assessment_deadline and drive.assessment_deadline < datetime.utcnow():
                raise AssessmentError("The assessment deadline for this drive has passed.", 400)

        first_question = await self.questions.get_random_unused(
            category_ids=assessment.category_ids,
            difficulty=DifficultyLevel.MEDIUM.value,
            exclude_ids=[],
        )
        if not first_question:
            raise AssessmentError("No questions available for this assessment yet.", 422)

        attempt = await self.attempts.create(
            {
                "assessment_id": assessment.id,
                "student_id": student_id,
                "session_token": secrets.token_urlsafe(24),
                "asked_question_ids": [first_question.id],
                "current_question_id": first_question.id,
                "current_difficulty": DifficultyLevel.MEDIUM.value,
                "answers": [],
                "violations": [],
                "status": AttemptStatus.IN_PROGRESS.value,
                "started_at": datetime.utcnow(),
                "submitted_at": None,
                "ip_address": ip_address,
                "fingerprint_hash": fingerprint_hash,
            }
        )

        # Link attempt to application if provided
        if application:
            await self.applications.update_by_id(
                application.id,
                {
                    "assessment_attempt_id": attempt.id,
                    "assessment_status": AssessmentStatus.PENDING.value,
                },
            )

        await log_activity(
            self.db,
            student_user_id,
            action="attempt_started",
            entity="assessment_attempt",
            entity_id=attempt.id,
            metadata={"assessment_id": assessment_id, "application_id": application_id},
            ip_address=ip_address,
        )
        return attempt, first_question

    async def _require_in_progress_attempt(
        self, resolved_student_id: str, attempt_id: str, session_token: str
    ) -> tuple[AssessmentAttemptInDB, AssessmentInDB]:
        attempt = await self.attempts.get_by_id(attempt_id)
        if not attempt:
            raise AssessmentError("Attempt not found.", 404)
        if attempt.student_id != resolved_student_id:
            raise AssessmentError("This is not your attempt.", 403)
        if attempt.session_token != session_token:
            raise AssessmentError("Invalid session token for this attempt.", 403)
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise AssessmentError("This attempt has already been submitted.", 400)

        assessment = await self.assessments.get_by_id(attempt.assessment_id)
        if datetime.utcnow() > attempt.started_at + timedelta(seconds=assessment.time_limit_sec):
            await self._finalize_attempt(attempt)
            raise AssessmentError("Time limit exceeded. This attempt has been auto-submitted.", 400)

        return attempt, assessment

    async def _finalize_attempt(self, attempt: AssessmentAttemptInDB) -> AssessmentAttemptInDB:
        """Mark attempt submitted and update any linked application score and status."""
        now = datetime.utcnow()
        updated_attempt = await self.attempts.update_by_id(
            attempt.id,
            {
                "status": AttemptStatus.SUBMITTED.value,
                "submitted_at": now,
                "current_question_id": None,
            },
        )
        if not updated_attempt:
            return attempt

        # Calculate score percentage
        total_marks = sum(a.marks_awarded for a in updated_attempt.answers)
        max_marks = sum(DIFFICULTY_MARKS[a.difficulty_at_time] for a in updated_attempt.answers)
        score_pct = round(100.0 * total_marks / max_marks, 1) if max_marks > 0 else 0.0

        # Check if an application is linked to this attempt
        linked_apps = await self.applications.find_many({"assessment_attempt_id": updated_attempt.id})
        for app in linked_apps:
            drive = await self.drives.get_by_id(app.drive_id)
            pass_status = AssessmentStatus.PASSED.value
            if drive and drive.assessment_min_score_pct is not None:
                if score_pct < drive.assessment_min_score_pct:
                    pass_status = AssessmentStatus.FAILED.value

            await self.applications.update_by_id(
                app.id,
                {
                    "assessment_score_pct": score_pct,
                    "assessment_status": pass_status,
                },
            )

        return updated_attempt

    async def submit_answer(
        self,
        student_user_id: str,
        attempt_id: str,
        session_token: str,
        question_id: str,
        response: str,
        time_taken_sec: float | None,
    ) -> tuple[AssessmentAttemptInDB, QuestionInDB | None, bool | None, int]:
        student_id = await self._resolve_student_id(student_user_id)
        attempt, assessment = await self._require_in_progress_attempt(student_id, attempt_id, session_token)

        if attempt.current_question_id != question_id:
            raise AssessmentError("This is not the current question for this attempt.", 400)

        question = await self.questions.get_by_id(question_id)
        if not question:
            raise AssessmentError("Question not found.", 404)

        is_correct = _grade(question, response)
        marks_awarded = question.marks if is_correct else 0

        if time_taken_sec is not None and time_taken_sec < 3.0:
            await log_activity(
                self.db,
                student_user_id,
                action="fast_answer_detected",
                entity="assessment_attempt",
                entity_id=attempt.id,
                metadata={"question_id": question_id, "time_taken_sec": time_taken_sec},
            )

        if is_correct is not None:
            for skill_tag in question.skill_tags:
                await self.kts.update_mastery(student_id, skill_tag, is_correct, question.difficulty)

        answer_record = {
            "question_id": question_id,
            "response": response,
            "is_correct": is_correct,
            "marks_awarded": marks_awarded,
            "time_taken_sec": time_taken_sec,
            "difficulty_at_time": question.difficulty.value,
        }
        new_answers = [a.model_dump(mode="json") for a in attempt.answers] + [answer_record]

        pool_exhausted = len(new_answers) >= assessment.question_pool_size
        next_question = None
        next_difficulty = attempt.current_difficulty

        if not pool_exhausted:
            next_difficulty = _adjust_difficulty(attempt.current_difficulty, bool(is_correct))
            next_question = await self.questions.get_random_unused(
                category_ids=assessment.category_ids,
                difficulty=next_difficulty.value,
                exclude_ids=attempt.asked_question_ids,
            )
            if not next_question:
                for fallback_difficulty in DIFFICULTY_ORDER:
                    if fallback_difficulty == next_difficulty:
                        continue
                    next_question = await self.questions.get_random_unused(
                        category_ids=assessment.category_ids,
                        difficulty=fallback_difficulty.value,
                        exclude_ids=attempt.asked_question_ids,
                    )
                    if next_question:
                        next_difficulty = fallback_difficulty
                        break

        update_data: dict = {"answers": new_answers}
        if next_question:
            update_data["asked_question_ids"] = attempt.asked_question_ids + [next_question.id]
            update_data["current_question_id"] = next_question.id
            update_data["current_difficulty"] = next_difficulty.value
            updated_attempt = await self.attempts.update_by_id(attempt.id, update_data)
        else:
            # Assessment is finished
            await self.attempts.update_by_id(attempt.id, update_data)
            refreshed = await self.attempts.get_by_id(attempt.id)
            updated_attempt = await self._finalize_attempt(refreshed)

        return updated_attempt, next_question, is_correct, marks_awarded

    async def get_results(self, student_user_id: str, attempt_id: str) -> AssessmentAttemptInDB:
        student_id = await self._resolve_student_id(student_user_id)
        attempt = await self.attempts.get_by_id(attempt_id)
        if not attempt:
            raise AssessmentError("Attempt not found.", 404)
        if attempt.student_id != student_id:
            raise AssessmentError("This is not your attempt.", 403)
        return attempt

    async def report_violation(
        self,
        student_user_id: str,
        attempt_id: str,
        session_token: str,
        violation_type: str,
        metadata: dict,
        ip_address: str | None = None,
    ) -> tuple[AssessmentAttemptInDB, int, int, bool]:
        student_id = await self._resolve_student_id(student_user_id)
        attempt, assessment = await self._require_in_progress_attempt(student_id, attempt_id, session_token)

        violation_record = {
            "type": violation_type,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata,
        }
        new_violations = attempt.violations + [violation_record]

        max_violations = assessment.anti_cheat_config.get("max_violations", 3)
        violation_count = len(new_violations)
        auto_submitted = violation_count >= max_violations

        update_data: dict = {"violations": new_violations}
        if auto_submitted:
            await self.attempts.update_by_id(attempt.id, update_data)
            refreshed = await self.attempts.get_by_id(attempt.id)
            updated_attempt = await self._finalize_attempt(refreshed)
        else:
            updated_attempt = await self.attempts.update_by_id(attempt.id, update_data)

        await log_activity(
            self.db,
            student_user_id,
            action="violation_reported",
            entity="assessment_attempt",
            entity_id=attempt.id,
            metadata={"type": violation_type, "count": violation_count, "auto_submitted": auto_submitted},
            ip_address=ip_address,
        )

        return updated_attempt, violation_count, max_violations, auto_submitted
