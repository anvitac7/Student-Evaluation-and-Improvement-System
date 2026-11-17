"""
Response schemas for Phase 15 analytics.

Deliberately Python-side aggregation (fetch-then-group-in-memory) rather
than MongoDB aggregation pipelines — consistent with this project's
existing "simple first, optimize when there's a real need" approach (see
e.g. knowledge tracing being an EMA rather than real BKT), and it keeps
these endpoints testable against the same mongomock setup every other
test in this suite already uses without worrying about pipeline-operator
support gaps.
"""
from datetime import datetime

from pydantic import BaseModel


class ApplicationStatusBreakdown(BaseModel):
    applied: int
    shortlisted: int
    rejected: int
    selected: int


class DriveAssessmentRankingEntry(BaseModel):
    """One student's standing in a drive assessment ranking.

    Only drive-type assessments (those linked to a drive) are ranked — practice
    assessment attempts are deliberately excluded from these leaderboards.
    """

    rank: int
    student_id: str
    student_name: str
    department: str | None = None
    cgpa: float | None = None
    score_pct: float
    submitted_at: datetime


class DriveAssessmentRanking(BaseModel):
    """Per-drive ranking — served by the drive-scoped ranking endpoint (the
    standalone rankings list was relocated into each drive's breakdown)."""

    drive_id: str
    job_title: str
    company_name: str
    assessment_id: str
    assessment_title: str
    entries: list[DriveAssessmentRankingEntry]


class DriveFunnel(BaseModel):
    drive_id: str
    job_title: str
    company_name: str
    status: str
    total_applications: int
    breakdown: ApplicationStatusBreakdown
    # Assessment linkage + participation (Phase: per-drive rankings). Additive
    # fields — the ranking detail itself moved to the per-drive endpoint.
    required_assessment_id: str | None = None
    assessment_title: str | None = None
    participant_count: int = 0  # unique students who STARTED the drive assessment
    submitted_participant_count: int = 0  # unique students with a SUBMITTED attempt


class TpoAnalyticsResponse(BaseModel):
    total_drives: int
    open_drives: int
    closed_drives: int
    total_applications: int
    breakdown: ApplicationStatusBreakdown
    selection_rate_pct: float  # selected / total_applications, 0 if no applications
    drives: list[DriveFunnel]


class DriveApplicantEntry(BaseModel):
    """One application behind a drive's applicant list.

    Every application status is included — the TPO sees the full funnel, not
    just active candidates. ``student_id`` is the student PROFILE id (the
    applications collection's ``student_id``), not the auth user id.
    """

    application_id: str
    student_id: str
    student_name: str
    department: str | None = None
    batch_year: int | None = None
    status: str
    applied_at: datetime


class DriveApplicantsResponse(BaseModel):
    drive_id: str
    job_title: str
    company_name: str
    total: int
    page: int
    limit: int
    entries: list[DriveApplicantEntry]


class DriveParticipantEntry(BaseModel):
    """One student's participation in a drive's required assessment.

    One row per student (never per attempt): the displayed attempt is the
    student's best SUBMITTED attempt (same selection the ranking uses), or
    their latest in-progress attempt when they have not submitted yet — an
    in-progress attempt is a real attempt (the student actually started),
    while merely being assigned an assessment is not. ``score_pct`` is None
    for an in-progress attempt.
    """

    student_id: str
    student_name: str
    department: str | None = None
    batch_year: int | None = None
    attempt_id: str
    attempt_status: str  # "in_progress" | "submitted"
    score_pct: float | None = None
    started_at: datetime
    submitted_at: datetime | None = None


class DriveParticipantsResponse(BaseModel):
    drive_id: str
    job_title: str
    company_name: str
    assessment_id: str | None = None
    assessment_title: str | None = None
    total: int  # unique participants across all pages
    page: int
    limit: int
    entries: list[DriveParticipantEntry]


class SkillMasteryOverview(BaseModel):
    skill_tag: str
    avg_mastery_pct: float
    student_count: int


class AdminAnalyticsResponse(BaseModel):
    total_students: int
    total_tpos: int
    total_drives: int
    open_drives: int
    closed_drives: int
    total_applications: int
    application_breakdown: ApplicationStatusBreakdown
    placed_students: int  # unique students with at least one "selected" application
    placement_rate_pct: float  # placed_students / total_students, 0 if no students
    total_categories: int
    total_questions: int
    total_assessments: int
    total_attempts: int
    submitted_attempts: int
    average_score_pct: float  # across submitted attempts with nonzero max possible marks
    skill_mastery_overview: list[SkillMasteryOverview]
