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
from typing import Literal

from pydantic import BaseModel

from app.models.market import MarketMeta


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


# ---------------------------------------------------------------------------
# Phase 8 — TPO Skill Gap Analysis
#
# Two independent student-skill evidence sources, never merged:
#
# - Assessment-demonstrated: recomputed per skill from SUBMITTED attempts on
#   placement drives' required assessments only (the
#   Placement Drive -> Required Assessment -> Attempt -> Student chain).
#   Practice attempts can never contribute because only assessments referenced
#   by a drive's ``required_assessment_id`` are ever fetched. The existing
#   ``knowledge_states`` collection is deliberately NOT used as a source —
#   knowledge tracing is updated for practice attempts too, so it would leak
#   practice performance into drive-skill evidence.
# - Self-reported: the student profile's structured ``skills`` list and the
#   ACTIVE resume's extracted ``skill_set``. A self-reported skill is never
#   counted as demonstrated proficiency — the two perspectives are reported
#   side by side (demonstrated gap vs reported gap).
#
# Industry demand comes from the existing Market Insights dataset
# (``job_market_postings`` + ``market_skill_catalog``) with the SAME filter
# semantics and window math as the market dashboard.
# ---------------------------------------------------------------------------

AssessmentEvidenceClass = Literal[
    "demonstrated", "developing", "not_demonstrated", "insufficient_evidence"
]

# The student-facing classification of ONE skill for ONE student: the
# strongest available evidence. ``both`` = self-reported AND assessed with
# enough graded answers to classify (the proficiency level itself is carried
# by ``assessment_classification``/accuracy). A student who reports the skill
# but has too few graded answers is ``reported_only`` — insufficient attempt
# evidence is never promoted to "both".
StudentSkillGapClass = Literal[
    "both",
    "demonstrated",
    "developing",
    "not_demonstrated",
    "reported_only",
    "insufficient_evidence",
    "no_evidence",
]

PriorityClass = Literal["high", "medium", "low"]

SkillGapStudentFilter = Literal[
    "all",
    "both",
    "demonstrated",
    "developing",
    "not_demonstrated",
    "reported_only",
    "insufficient_evidence",
    "no_evidence",
]

SkillGapSort = Literal["priority", "demand", "gap"]


class SkillGapThresholds(BaseModel):
    """The exact constants the skill-gap math used — exposed so the UI can
    explain every classification instead of presenting arbitrary numbers."""

    min_graded_answers: int
    demonstrated_min_pct: float
    developing_min_pct: float
    priority_weights: dict[str, float]
    priority_class_thresholds: dict[str, float]


class StudentEvidenceSource(BaseModel):
    """One eligible drive assessment's contribution to ONE student's evidence
    for ONE skill — the only assessment detail the skill-gap views expose."""

    assessment_title: str
    attempts_used: int
    questions_answered: int
    correct_answers: int


class SkillCompanyDemand(BaseModel):
    """How many of ONE company's (filtered) postings demand the skill."""

    company_slug: str
    company_name: str
    posting_count: int
    demand_pct: float  # share of that company's own postings


class SkillJobFamilyDemand(BaseModel):
    """How many of ONE job family's (filtered) postings demand the skill."""

    job_family: str
    posting_count: int
    demand_pct: float  # share of that family's own postings


class SkillYearDemand(BaseModel):
    """One year of a skill's demand series (calendar-year counts for display;
    growth is always computed between comparable windows, like the market
    dashboard's historical series)."""

    year: int
    posting_count: int
    demand_pct: float
    yoy_growth_pct: float | None = None


class SkillGapEntry(BaseModel):
    """One demanded skill: industry demand + student evidence + gap result."""

    skill_id: str  # catalog slug (or slugified name when not in the catalog)
    name: str
    category: str | None
    is_technical: bool

    # --- Industry demand (Market Insights dataset, filtered population) ---
    posting_count: int
    demand_pct: float  # share of ALL filtered postings
    demanding_company_count: int
    demanding_job_family_count: int
    yearly_counts: dict[int, int]
    yearly_demand_pct: dict[int, float]
    latest_growth_pct: float | None  # comparable-window growth, None if unavailable
    growth_comparable: bool

    # --- Student evidence (aggregated over the student population) ---
    students_demonstrated: int  # strongly demonstrated (>= demonstrated_min_pct)
    students_developing: int
    students_not_demonstrated: int  # classified, but below developing_min_pct
    students_insufficient_evidence: int  # graded answers < min_graded_answers
    students_reported: int  # self-reported (profile and/or active resume)
    students_reported_only: int  # self-reported, without classified assessment evidence
    students_both: int  # self-reported AND classified assessment evidence
    students_no_evidence: int  # neither reported nor any graded attempt evidence
    students_lacking_demonstrated: int  # population - students_demonstrated

    demonstrated_pct: float  # students_demonstrated / population
    reported_pct: float
    gap_pct: float  # students_lacking_demonstrated / population

    # --- Gap result ---
    priority_score: float
    priority_class: PriorityClass

    # --- Detail views (bounded; everything from the same aggregation pass) ---
    top_companies: list[SkillCompanyDemand]
    top_job_families: list[SkillJobFamilyDemand]
    years: list[SkillYearDemand]


class MostDemandedMissingSkill(BaseModel):
    skill_id: str
    name: str
    posting_count: int
    demand_pct: float


class RisingDemandSkill(BaseModel):
    """A skill whose comparable demand is growing while demonstrated student
    proficiency is low — the demand-growth gap the summary card surfaces."""

    skill_id: str
    name: str
    latest_growth_pct: float
    demand_pct: float
    demonstrated_pct: float


class SkillGapSummary(BaseModel):
    total_skills_analyzed: int
    high_priority_gaps: int
    student_population: int
    # Students with NO strongly-demonstrated skill across the whole analysis.
    students_lacking_demonstrated_skills: int
    students_with_reported_skills: int
    students_with_assessment_evidence: int
    # The most demanded skill zero students have demonstrated (None when every
    # demanded skill has at least one demonstrated student).
    most_demanded_missing_skill: MostDemandedMissingSkill | None = None
    rising_demand_skills: list[RisingDemandSkill] = []


class SkillGapMeta(BaseModel):
    """Dataset identity + evidence-coverage explanation for the response."""

    market: MarketMeta  # same metadata block the market dashboard returns
    thresholds: SkillGapThresholds
    eligible_drive_count: int  # drives whose required assessment contributed
    eligible_assessment_count: int  # distinct required assessments used
    submitted_eligible_attempt_count: int  # submitted attempts actually used
    unmapped_assessment_skill_tags: list[str]  # question tags with no catalog/market mapping
    unmapped_self_reported_skills: list[str]  # reported skills with no mapping
    notes: list[str]


class SkillGapAnalysisResponse(BaseModel):
    meta: SkillGapMeta
    summary: SkillGapSummary
    skills: list[SkillGapEntry]


class SkillGapStudentEntry(BaseModel):
    """One student's relationship to ONE demanded skill.

    Analytics-only projection: name, department, batch year and the evidence
    relevant to THIS skill — never emails, resumes, phone numbers, or
    assessment data unrelated to the selected skill."""

    student_id: str  # student PROFILE id (same id space as applications)
    student_name: str
    department: str | None
    batch_year: int | None
    self_reported: bool
    self_reported_via: list[str]  # "profile" and/or "resume"
    classification: StudentSkillGapClass
    assessment_classification: AssessmentEvidenceClass | None = None
    skill_accuracy_pct: float | None = None  # None when insufficient/no evidence
    questions_answered: int
    correct_answers: int
    assessment_evidence: list[StudentEvidenceSource]


class SkillGapStudentsResponse(BaseModel):
    skill_id: str
    skill_name: str
    classification: SkillGapStudentFilter  # echo of the filter applied
    student_population: int
    total: int  # rows matching the filter+search across all pages
    page: int
    limit: int
    entries: list[SkillGapStudentEntry]
