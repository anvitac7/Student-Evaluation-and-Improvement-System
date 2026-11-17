import logging
import re
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.analytics import (
    AdminAnalyticsResponse,
    ApplicationStatusBreakdown,
    DriveApplicantEntry,
    DriveApplicantsResponse,
    DriveAssessmentRanking,
    DriveAssessmentRankingEntry,
    DriveFunnel,
    DriveParticipantEntry,
    DriveParticipantsResponse,
    SkillMasteryOverview,
    TpoAnalyticsResponse,
)
from app.models.assessment import DIFFICULTY_MARKS, AttemptStatus
from app.models.drive import PlacementDriveInDB
from app.repositories.application_repository import ApplicationRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.attempt_repository import AttemptRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.drive_repository import PlacementDriveRepository
from app.repositories.knowledge_state_repository import KnowledgeStateRepository
from app.repositories.profile_repositories import StudentRepository, TPORepository
from app.repositories.question_repository import QuestionCategoryRepository, QuestionRepository

# Generous but finite caps on "fetch everything" queries — this project's
# scale (a college placement cell, not a SaaS product) means these won't
# be hit in practice, but an unbounded find_many() against a collection
# that could theoretically grow unboundedly is still worth capping.
_ANALYTICS_FETCH_LIMIT = 5000

# Hard cap on how many student profiles a name search may match before the
# filter is applied to the applicant/participant query. Far above any real
# cohort; exists so a pathological one-character search can't stream the
# whole students collection into memory.
_SEARCH_STUDENT_CAP = 1000

logger = logging.getLogger(__name__)


class AnalyticsError(Exception):
    """Raised by analytics endpoints; carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _empty_breakdown() -> ApplicationStatusBreakdown:
    return ApplicationStatusBreakdown(applied=0, shortlisted=0, rejected=0, selected=0)


def _tally(applications) -> ApplicationStatusBreakdown:
    counts = {"applied": 0, "shortlisted": 0, "rejected": 0, "selected": 0}
    for app in applications:
        status = app.status.value if hasattr(app.status, "value") else app.status
        if status in counts:
            counts[status] += 1
    return ApplicationStatusBreakdown(**counts)


def _attempt_score_pct(attempt) -> float:
    """Score percentage for a submitted attempt, reconstructed from the
    difficulty-at-time marks (see DIFFICULTY_MARKS). Returns 0.0 when the
    attempt answered nothing."""
    total_marks = sum(ans.marks_awarded for ans in attempt.answers)
    max_marks = sum(DIFFICULTY_MARKS[ans.difficulty_at_time] for ans in attempt.answers)
    return round(100.0 * total_marks / max_marks, 1) if max_marks > 0 else 0.0


def _name_search_regex(search: str) -> str:
    """Case-insensitive substring matcher, escaped so a search string can
    never inject regex operators into the query."""
    return re.compile(re.escape(search), re.IGNORECASE)


class AnalyticsService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.drives = PlacementDriveRepository(db)
        self.applications = ApplicationRepository(db)
        self.companies = CompanyRepository(db)
        self.students = StudentRepository(db)
        self.tpos = TPORepository(db)
        self.categories = QuestionCategoryRepository(db)
        self.questions = QuestionRepository(db)
        self.assessments = AssessmentRepository(db)
        self.attempts = AttemptRepository(db)
        self.knowledge_states = KnowledgeStateRepository(db)

    async def get_tpo_analytics(self, tpo_user_id: str) -> TpoAnalyticsResponse:
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        if not tpo:
            drives = []
        else:
            drives = await self.drives.find_many({"created_by": tpo.id}, limit=_ANALYTICS_FETCH_LIMIT)

        # One batched company lookup instead of one per drive. Document ids
        # are ObjectIds in storage; profile references (company_id on the
        # drive) are stored as strings, so only _id queries need conversion.
        company_ids = {str(drive.company_id) for drive in drives}
        companies = await self.companies.find_many(
            {"_id": {"$in": [ObjectId(cid) for cid in company_ids]}}, limit=_ANALYTICS_FETCH_LIMIT
        ) if company_ids else []
        company_names = {company.id: company.name for company in companies}

        drive_funnels: list[DriveFunnel] = []
        overall = _empty_breakdown()
        open_count = 0
        closed_count = 0

        for drive in drives:
            if drive.status == "open":
                open_count += 1
            else:
                closed_count += 1

            applications = await self.applications.find_many({"drive_id": drive.id}, limit=_ANALYTICS_FETCH_LIMIT)
            breakdown = _tally(applications)
            for field in ("applied", "shortlisted", "rejected", "selected"):
                setattr(overall, field, getattr(overall, field) + getattr(breakdown, field))

            company_name = company_names.get(str(drive.company_id), "Unknown company")

            # Participation counts for the drive overview. The attempt pool is
            # the drive's required assessment, scoped to the drive's own
            # applicants — see _drive_attempt_pool for why.
            assessment_title = None
            participant_count = 0
            submitted_count = 0
            if drive.required_assessment_id:
                assessment = await self.assessments.get_by_id(str(drive.required_assessment_id))
                if assessment:
                    assessment_title = assessment.title
                    applicant_ids = {app.student_id for app in applications}
                    attempts = await self.attempts.find_many(
                        {"assessment_id": assessment.id}, limit=_ANALYTICS_FETCH_LIMIT
                    )
                    participants = {
                        attempt.student_id
                        for attempt in attempts
                        if attempt.student_id in applicant_ids
                    }
                    participant_count = len(participants)
                    submitted_count = len({
                        attempt.student_id
                        for attempt in attempts
                        if attempt.student_id in applicant_ids
                        and attempt.status == AttemptStatus.SUBMITTED
                    })

            drive_funnels.append(
                DriveFunnel(
                    drive_id=drive.id,
                    job_title=drive.job_title,
                    company_name=company_name,
                    status=drive.status.value if hasattr(drive.status, "value") else drive.status,
                    total_applications=len(applications),
                    breakdown=breakdown,
                    required_assessment_id=str(drive.required_assessment_id) if drive.required_assessment_id else None,
                    assessment_title=assessment_title,
                    participant_count=participant_count,
                    submitted_participant_count=submitted_count,
                )
            )

        total_applications = overall.applied + overall.shortlisted + overall.rejected + overall.selected
        selection_rate = round(100 * overall.selected / total_applications, 1) if total_applications else 0.0

        return TpoAnalyticsResponse(
            total_drives=len(drives),
            open_drives=open_count,
            closed_drives=closed_count,
            total_applications=total_applications,
            breakdown=overall,
            selection_rate_pct=selection_rate,
            drives=drive_funnels,
        )

    # ------------------------------------------------------------------
    # Per-drive detail (Phase: per-drive rankings & participation).
    #
    # Rankings moved out of the main analytics response into drive-scoped
    # endpoints so each drive's expanded breakdown shows its own ranking,
    # applicants and participants without duplicating data.
    # ------------------------------------------------------------------

    async def _get_owned_drive(self, tpo_user_id: str, drive_id: str) -> PlacementDriveInDB:
        """The drive being inspected must exist AND belong to this TPO —
        same ownership rule as the drive-management endpoints (404 hides
        other TPOs' drives from probing, 403 covers the impossible-id case)."""
        tpo = await self.tpos.get_by_user_id(tpo_user_id)
        drive = await self.drives.get_by_id(drive_id)
        if not drive or not tpo:
            raise AnalyticsError("Drive not found.", 404)
        if drive.created_by != tpo.id:
            raise AnalyticsError("You do not have permission to view this drive's analytics.", 403)
        return drive

    async def _drive_attempt_pool(self, drive: PlacementDriveInDB, applicant_ids: set[str]) -> list:
        """All attempts on the drive's required assessment, restricted to the
        drive's own applicants.

        Restricting to the applicant set is what makes this drive-exact: a
        drive assessment can only be started through an application (see
        assessment_service.start_attempt), so in the normal case — one drive
        per assessment — every attempter is already an applicant and this
        restriction changes nothing. But two drives MAY reference the same
        assessment, and then the assessment_id alone cannot tell which drive
        an attempt belongs to; the applicant set can. Without it, drive A's
        leaderboard would list students who only ever applied to drive B.
        """
        if not drive.required_assessment_id:
            return []
        return await self.attempts.find_many(
            {"assessment_id": str(drive.required_assessment_id), "student_id": {"$in": list(applicant_ids)}},
            limit=_ANALYTICS_FETCH_LIMIT,
        )

    async def get_drive_ranking(self, tpo_user_id: str, drive_id: str) -> DriveAssessmentRanking:
        drive = await self._get_owned_drive(tpo_user_id, drive_id)
        company = await self.companies.get_by_id(str(drive.company_id))
        company_name = company.name if company else "Unknown company"

        assessment = (
            await self.assessments.get_by_id(str(drive.required_assessment_id))
            if drive.required_assessment_id
            else None
        )
        if not assessment:
            raise AnalyticsError("This drive has no required assessment, so there is nothing to rank.", 404)

        applications = await self.applications.find_many({"drive_id": drive.id}, limit=_ANALYTICS_FETCH_LIMIT)
        applicant_ids = {app.student_id for app in applications}
        attempts = await self._drive_attempt_pool(drive, applicant_ids)

        # Best score per student (a student can retake a drive assessment —
        # their best submitted attempt represents them in the ranking).
        # Unranked by design: in-progress attempts have no final score.
        best_by_student: dict[str, tuple[float, object]] = {}
        for attempt in attempts:
            if attempt.status != AttemptStatus.SUBMITTED:
                continue
            score = _attempt_score_pct(attempt)
            existing = best_by_student.get(attempt.student_id)
            if existing is None or score > existing[0]:
                best_by_student[attempt.student_id] = (score, attempt)

        # Same ordering the old standalone ranking used (score descending);
        # ties now break deterministically by earlier submission, then
        # student id, instead of by dict insertion order.
        ordered = sorted(
            best_by_student.items(),
            key=lambda kv: (
                -kv[1][0],
                kv[1][1].submitted_at or kv[1][1].started_at,
                kv[0],
            ),
        )

        student_ids = [student_id for student_id, _ in ordered]
        students = {
            student.id: student
            for student in await self.students.find_many(
                {"_id": {"$in": [ObjectId(sid) for sid in student_ids]}}, limit=_SEARCH_STUDENT_CAP
            )
        }

        entries: list[DriveAssessmentRankingEntry] = []
        for rank, (student_id, (score, attempt)) in enumerate(ordered, start=1):
            student = students.get(student_id)
            entries.append(
                DriveAssessmentRankingEntry(
                    rank=rank,
                    student_id=student_id,
                    student_name=student.name if student else "Unknown student",
                    department=student.department if student else None,
                    cgpa=student.cgpa if student else None,
                    score_pct=score,
                    submitted_at=attempt.submitted_at or attempt.started_at,
                )
            )

        return DriveAssessmentRanking(
            drive_id=drive.id,
            job_title=drive.job_title,
            company_name=company_name,
            assessment_id=assessment.id,
            assessment_title=assessment.title,
            entries=entries,
        )

    async def get_drive_applicants(
        self,
        tpo_user_id: str,
        drive_id: str,
        page: int,
        limit: int,
        search: str | None,
    ) -> DriveApplicantsResponse:
        drive = await self._get_owned_drive(tpo_user_id, drive_id)
        company = await self.companies.get_by_id(str(drive.company_id))
        company_name = company.name if company else "Unknown company"

        query: dict = {"drive_id": drive.id}
        if search:
            # Name search resolves against the students collection first, then
            # narrows the application query — no name-based joins anywhere.
            matching = await self.students.find_many(
                {"name": _name_search_regex(search)}, limit=_SEARCH_STUDENT_CAP
            )
            query["student_id"] = {"$in": [student.id for student in matching]}

        total = await self.applications.count(query)
        applications = await self.applications.find_many(
            query, page=page, limit=limit, sort=[("applied_at", -1)]
        )

        # One batched student lookup for the page (no per-row queries).
        page_student_ids = [app.student_id for app in applications]
        students = {
            student.id: student
            for student in await self.students.find_many(
                {"_id": {"$in": [ObjectId(sid) for sid in page_student_ids]}}, limit=limit
            )
        }

        # Defensive dedupe by student (one application per drive/student is
        # enforced at creation; legacy duplicates must not show twice).
        seen_student_ids: set[str] = set()
        entries: list[DriveApplicantEntry] = []
        for app in applications:
            if app.student_id in seen_student_ids:
                continue
            seen_student_ids.add(app.student_id)
            student = students.get(app.student_id)
            status = app.status.value if hasattr(app.status, "value") else app.status
            entries.append(
                DriveApplicantEntry(
                    application_id=app.id,
                    student_id=app.student_id,
                    student_name=student.name if student else "Unknown student",
                    department=student.department if student else None,
                    batch_year=student.batch_year if student else None,
                    status=status,
                    applied_at=app.applied_at,
                )
            )

        return DriveApplicantsResponse(
            drive_id=drive.id,
            job_title=drive.job_title,
            company_name=company_name,
            total=total,
            page=page,
            limit=limit,
            entries=entries,
        )

    async def get_drive_participants(
        self,
        tpo_user_id: str,
        drive_id: str,
        page: int,
        limit: int,
        search: str | None,
    ) -> DriveParticipantsResponse:
        drive = await self._get_owned_drive(tpo_user_id, drive_id)
        company = await self.companies.get_by_id(str(drive.company_id))
        company_name = company.name if company else "Unknown company"

        assessment = (
            await self.assessments.get_by_id(str(drive.required_assessment_id))
            if drive.required_assessment_id
            else None
        )
        if not assessment:
            return DriveParticipantsResponse(
                drive_id=drive.id,
                job_title=drive.job_title,
                company_name=company_name,
                assessment_id=None,
                assessment_title=None,
                total=0,
                page=page,
                limit=limit,
                entries=[],
            )

        applications = await self.applications.find_many({"drive_id": drive.id}, limit=_ANALYTICS_FETCH_LIMIT)
        applicant_ids = {app.student_id for app in applications}
        attempts = await self._drive_attempt_pool(drive, applicant_ids)

        # One row per student: their best submitted attempt represents them
        # (same selection the ranking uses); a student who started but never
        # submitted is shown with their latest in-progress attempt and no
        # score — an actual attempt, not just an assignment.
        best_by_student: dict[str, tuple[float, object]] = {}
        in_progress_by_student: dict[str, object] = {}
        for attempt in attempts:
            if attempt.status == AttemptStatus.SUBMITTED:
                score = _attempt_score_pct(attempt)
                existing = best_by_student.get(attempt.student_id)
                if existing is None or score > existing[0]:
                    best_by_student[attempt.student_id] = (score, attempt)
            else:
                current = in_progress_by_student.get(attempt.student_id)
                if current is None or (attempt.started_at or "") > (current.started_at or ""):
                    in_progress_by_student[attempt.student_id] = attempt

        participant_ids = set(best_by_student) | set(in_progress_by_student)
        participant_rows: list[tuple[str, object]] = [
            (student_id, best_by_student[student_id][1] if student_id in best_by_student
             else in_progress_by_student[student_id])
            for student_id in participant_ids
        ]

        if search:
            matching = await self.students.find_many(
                {"name": _name_search_regex(search)}, limit=_SEARCH_STUDENT_CAP
            )
            allowed_ids = {student.id for student in matching}
            participant_rows = [row for row in participant_rows if row[0] in allowed_ids]

        # Fetch all names once, then sort + paginate in memory (the pool is
        # deduped per student, so it is bounded by the applicant count).
        pool_student_ids = [student_id for student_id, _ in participant_rows]
        students = {
            student.id: student
            for student in await self.students.find_many(
                {"_id": {"$in": [ObjectId(sid) for sid in pool_student_ids]}}, limit=_SEARCH_STUDENT_CAP
            )
        }

        def _sort_key(row: tuple[str, object]):
            student = students.get(row[0])
            return (student.name if student else "", row[0])

        participant_rows.sort(key=_sort_key)
        total = len(participant_rows)
        start = (page - 1) * limit
        page_rows = participant_rows[start:start + limit]

        entries: list[DriveParticipantEntry] = []
        for student_id, attempt in page_rows:
            student = students.get(student_id)
            submitted = attempt.status == AttemptStatus.SUBMITTED
            entries.append(
                DriveParticipantEntry(
                    student_id=student_id,
                    student_name=student.name if student else "Unknown student",
                    department=student.department if student else None,
                    batch_year=student.batch_year if student else None,
                    attempt_id=attempt.id,
                    attempt_status=attempt.status.value if hasattr(attempt.status, "value") else attempt.status,
                    score_pct=_attempt_score_pct(attempt) if submitted else None,
                    started_at=attempt.started_at,
                    submitted_at=attempt.submitted_at,
                )
            )

        return DriveParticipantsResponse(
            drive_id=drive.id,
            job_title=drive.job_title,
            company_name=company_name,
            assessment_id=assessment.id,
            assessment_title=assessment.title,
            total=total,
            page=page,
            limit=limit,
            entries=entries,
        )

    async def get_admin_analytics(self) -> AdminAnalyticsResponse:
        total_students = await self.students.count({})
        total_tpos = await self.tpos.count({})
        total_drives = await self.drives.count({})
        open_drives = await self.drives.count({"status": "open"})
        closed_drives = total_drives - open_drives

        applications = await self.applications.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        breakdown = _tally(applications)
        # The status breakdown and placed-student set are necessarily computed
        # from the fetched rows, but "total_applications" must be the REAL
        # total. Previously it was len(applications), so past the 5000-row
        # fetch limit the dashboard reported 5000 as the total while
        # total_drives (which used count()) stayed accurate — some totals
        # real, some silently capped, with nothing in the response saying so.
        total_applications = await self.applications.count({})
        placed_student_ids = {a.student_id for a in applications if a.status == "selected"}
        placement_rate = round(100 * len(placed_student_ids) / total_students, 1) if total_students else 0.0

        if total_applications > len(applications):
            logger.warning(
                "Admin analytics: application status breakdown is PARTIAL — "
                "fetched %d of %d (fetch limit %d). Counts shown are lower bounds.",
                len(applications), total_applications, _ANALYTICS_FETCH_LIMIT,
            )

        total_categories = await self.categories.count({})
        total_questions = await self.questions.count({})
        total_assessments = await self.assessments.count({})

        attempts = await self.attempts.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        total_attempts = await self.attempts.count({})
        submitted = [a for a in attempts if a.status == AttemptStatus.SUBMITTED]

        if total_attempts > len(attempts):
            logger.warning(
                "Admin analytics: attempt/average-score figures are PARTIAL — "
                "fetched %d of %d (fetch limit %d).",
                len(attempts), total_attempts, _ANALYTICS_FETCH_LIMIT,
            )

        score_pcts = []
        for attempt in submitted:
            total_marks = sum(ans.marks_awarded for ans in attempt.answers)
            max_marks = sum(DIFFICULTY_MARKS[ans.difficulty_at_time] for ans in attempt.answers)
            if max_marks > 0:
                score_pcts.append(100 * total_marks / max_marks)
        average_score = round(sum(score_pcts) / len(score_pcts), 1) if score_pcts else 0.0

        knowledge_states = await self.knowledge_states.find_many({}, limit=_ANALYTICS_FETCH_LIMIT)
        by_skill: dict[str, list[float]] = {}
        for state in knowledge_states:
            by_skill.setdefault(state.skill_tag, []).append(state.mastery_pct)
        skill_overview = sorted(
            (
                SkillMasteryOverview(
                    skill_tag=tag,
                    avg_mastery_pct=round(sum(values) / len(values), 1),
                    student_count=len(values),
                )
                for tag, values in by_skill.items()
            ),
            key=lambda s: s.avg_mastery_pct,
        )

        return AdminAnalyticsResponse(
            total_students=total_students,
            total_tpos=total_tpos,
            total_drives=total_drives,
            open_drives=open_drives,
            closed_drives=closed_drives,
            total_applications=total_applications,
            application_breakdown=breakdown,
            placed_students=len(placed_student_ids),
            placement_rate_pct=placement_rate,
            total_categories=total_categories,
            total_questions=total_questions,
            total_assessments=total_assessments,
            total_attempts=total_attempts,
            submitted_attempts=len(submitted),
            average_score_pct=average_score,
            skill_mastery_overview=skill_overview,
        )
