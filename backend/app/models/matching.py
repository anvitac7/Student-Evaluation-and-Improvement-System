from pydantic import BaseModel


class MatchScoreBreakdown(BaseModel):
    """Core hybrid-score output — field names match the notebook's
    compute_hybrid_scores_batch() dict keys exactly (final_score,
    semantic_score, skills_score, experience_score, matched_skills,
    missing_skills), so anyone comparing this API's output against the
    notebook's own evaluate_resume_pretty() report can do so directly."""

    final_score: float
    semantic_score: float
    skills_score: float
    experience_score: float
    matched_skills: list[str]
    missing_skills: list[str]


class DriveMatchScoreResponse(MatchScoreBreakdown):
    """Phase 7: single resume x single drive."""

    drive_id: str


class RecommendedDriveResponse(MatchScoreBreakdown):
    """Phase 9: one row of the student's ranked drive recommendations."""

    drive_id: str
    job_title: str
    company_name: str
    location: str | None
    package: str | None


class RankedApplicantResponse(MatchScoreBreakdown):
    """Phase 9: one row of a TPO's ranked applicant list for a drive."""

    application_id: str
    student_id: str
    student_name: str
    student_department: str | None = None
    student_cgpa: float | None = None
    resume_id: str
    resume_filename: str | None = None
    status: str = "applied"
    # Eligibility
    eligibility_passed: bool | None = None
    eligibility_reasons: list[str] = []
    # Assessment
    assessment_status: str = "not_required"
    assessment_score_pct: float | None = None
    # Decision
    rejection_reasons: list[str] = []
    rejection_note: str | None = None
    decision_at: str | None = None
    applied_at: str | None = None
