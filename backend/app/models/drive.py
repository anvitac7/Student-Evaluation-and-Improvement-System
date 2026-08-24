from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel, PyObjectId


class DriveStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class ApplicationStatus(str, Enum):
    APPLIED = "applied"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    SELECTED = "selected"


class AssessmentStatus(str, Enum):
    """Assessment requirement status on an application."""
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class RejectionReason(str, Enum):
    LOW_MATCH_SCORE = "low_match_score"
    SKILL_GAP = "skill_gap"
    LOW_ASSESSMENT_SCORE = "low_assessment_score"
    ASSESSMENT_NOT_ATTEMPTED = "assessment_not_attempted"
    ELIGIBILITY = "eligibility"
    EXPERIENCE_GAP = "experience_gap"
    OTHER = "other"


# Valid status transitions — terminal states cannot change.
VALID_STATUS_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: {ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED},
    ApplicationStatus.SHORTLISTED: {ApplicationStatus.SELECTED, ApplicationStatus.REJECTED},
    ApplicationStatus.SELECTED: set(),    # terminal
    ApplicationStatus.REJECTED: set(),    # terminal
}


class EligibilityCriteria(BaseModel):
    min_cgpa: float | None = None
    departments: list[str] = Field(default_factory=list)  # empty = open to all departments
    batch_years: list[int] = Field(default_factory=list)  # empty = open to all batch years


# ---------------------------------------------------------------------------
# DB documents
# ---------------------------------------------------------------------------
class CompanyInDB(MongoBaseModel):
    name: str
    description: str | None = None
    website: str | None = None
    industry: str | None = None


class PlacementDriveInDB(MongoBaseModel):
    company_id: PyObjectId
    job_title: str
    description: str
    jd_text: str
    jd_embedding: list[float] | None = None  # populated by Phase 9 (semantic matching)
    required_skills: list[str] = Field(default_factory=list)
    experience_required_years: float = 0.0  # Phase 9: needed for the hybrid formula's experience_score term
    package: str | None = None
    location: str | None = None
    eligibility: EligibilityCriteria = Field(default_factory=EligibilityCriteria)
    deadline: datetime
    selection_process: list[str] = Field(default_factory=list)
    status: DriveStatus = DriveStatus.OPEN
    created_by: PyObjectId  # TPO document _id (not the User _id)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Assessment linkage — TPO attaches an existing (admin-created) assessment
    required_assessment_id: PyObjectId | None = None
    assessment_min_score_pct: float | None = None  # e.g. 70.0 means 70%
    assessment_deadline: datetime | None = None


class ApplicationInDB(MongoBaseModel):
    drive_id: PyObjectId
    student_id: PyObjectId
    resume_id: PyObjectId
    status: ApplicationStatus = ApplicationStatus.APPLIED
    # Eligibility
    eligibility_passed: bool | None = None
    eligibility_reasons: list[str] = Field(default_factory=list)
    # Matching — persisted after screening so scores are historical
    final_score: float | None = None  # populated by Phase 9
    semantic_score: float | None = None
    skills_score: float | None = None
    experience_score: float | None = None
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    # Assessment
    assessment_attempt_id: PyObjectId | None = None
    assessment_score_pct: float | None = None
    assessment_status: AssessmentStatus = AssessmentStatus.NOT_REQUIRED
    # Decision
    rejection_reasons: list[str] = Field(default_factory=list)  # RejectionReason values
    rejection_note: str | None = None
    decision_at: datetime | None = None
    # Metadata
    evaluation_version: str | None = None  # tracks model/formula version
    applied_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------
class DriveCreateRequest(BaseModel):
    company_name: str
    company_description: str | None = None
    company_website: str | None = None
    company_industry: str | None = None
    job_title: str
    description: str
    jd_text: str
    required_skills: list[str] = Field(default_factory=list)
    experience_required_years: float = Field(default=0.0, ge=0)
    package: str | None = None
    location: str | None = None
    eligibility: EligibilityCriteria = Field(default_factory=EligibilityCriteria)
    deadline: datetime
    selection_process: list[str] = Field(default_factory=list)
    # Assessment linkage
    required_assessment_id: str | None = None
    assessment_min_score_pct: float | None = Field(default=None, ge=0, le=100)
    assessment_deadline: datetime | None = None


class DriveUpdateRequest(BaseModel):
    job_title: str | None = None
    description: str | None = None
    jd_text: str | None = None
    required_skills: list[str] | None = None
    experience_required_years: float | None = Field(default=None, ge=0)
    package: str | None = None
    location: str | None = None
    eligibility: EligibilityCriteria | None = None
    deadline: datetime | None = None
    selection_process: list[str] | None = None
    status: DriveStatus | None = None
    # Assessment linkage
    required_assessment_id: str | None = None
    assessment_min_score_pct: float | None = Field(default=None, ge=0, le=100)
    assessment_deadline: datetime | None = None


class ApplicationStatusUpdateRequest(BaseModel):
    status: ApplicationStatus
    rejection_reasons: list[str] = Field(default_factory=list)  # RejectionReason values
    rejection_note: str | None = Field(default=None, max_length=1000)


class BulkApplicationStatusRequest(BaseModel):
    application_ids: list[str] = Field(min_length=1)
    status: ApplicationStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    rejection_note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------
class CompanySummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    website: str | None = None
    industry: str | None = None


class DriveSummary(BaseModel):
    id: str
    company: CompanySummary
    job_title: str
    package: str | None
    location: str | None
    deadline: datetime
    status: DriveStatus
    required_skills: list[str]


class DriveDetail(DriveSummary):
    description: str
    jd_text: str
    eligibility: EligibilityCriteria
    selection_process: list[str]
    experience_required_years: float
    created_at: datetime
    # Assessment config
    required_assessment_id: str | None = None
    assessment_min_score_pct: float | None = None
    assessment_deadline: datetime | None = None


class ApplicationResponse(BaseModel):
    id: str
    drive_id: str
    student_id: str
    resume_id: str
    status: ApplicationStatus
    applied_at: datetime
    # Eligibility
    eligibility_passed: bool | None = None
    eligibility_reasons: list[str] = Field(default_factory=list)
    # Matching
    final_score: float | None = None
    semantic_score: float | None = None
    skills_score: float | None = None
    experience_score: float | None = None
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    # Assessment
    assessment_attempt_id: str | None = None
    assessment_score_pct: float | None = None
    assessment_status: str = "not_required"
    # Decision
    rejection_reasons: list[str] = Field(default_factory=list)
    rejection_note: str | None = None
    decision_at: datetime | None = None


class ApplicationDetail(ApplicationResponse):
    """Enriched view for TPOs reviewing applicants — adds just enough
    student/resume context to make a shortlist/reject decision without a
    second round-trip per applicant."""

    student_name: str
    student_department: str | None
    student_cgpa: float | None
    resume_filename: str | None


class BulkStatusResult(BaseModel):
    updated_count: int
    failed_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ScreeningSummary(BaseModel):
    total_applications: int
    eligible: int
    ineligible: int
    assessment_pending: int
    assessment_passed: int
    assessment_failed: int
    assessment_expired: int
    assessment_not_required: int
    shortlisted: int
    rejected: int
    selected: int
    recommended_shortlist: int
