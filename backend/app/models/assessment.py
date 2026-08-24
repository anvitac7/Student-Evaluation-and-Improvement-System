"""
Knowledge Tracing System models.

Scope decisions made explicit here (see PROJECT_PROGRESS.md for the full
reasoning): coding questions are graded by exact-match against an expected
output, not real sandboxed code execution (a real judge needs untrusted-
code sandboxing — a security-sensitive feature deliberately out of scope
for this phase). Descriptive questions are stored but not auto-graded —
they're flagged for manual review. MCQ is the only fully-automatic type.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel, PyObjectId


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


DIFFICULTY_ORDER = [DifficultyLevel.EASY, DifficultyLevel.MEDIUM, DifficultyLevel.HARD]
DIFFICULTY_MARKS = {DifficultyLevel.EASY: 1, DifficultyLevel.MEDIUM: 3, DifficultyLevel.HARD: 5}


class QuestionType(str, Enum):
    MCQ = "mcq"
    CODING = "coding"
    DESCRIPTIVE = "descriptive"


class AttemptStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


# ---------------------------------------------------------------------------
# DB documents
# ---------------------------------------------------------------------------
class QuestionCategoryInDB(MongoBaseModel):
    name: str
    parent_category_id: PyObjectId | None = None


class QuestionInDB(MongoBaseModel):
    category_id: PyObjectId
    skill_tags: list[str] = Field(default_factory=list)
    difficulty: DifficultyLevel
    type: QuestionType
    text: str
    options: list[str] = Field(default_factory=list)  # MCQ only
    correct_answer: str | None = None  # MCQ: option text. Coding: expected output. Descriptive: None (manual grading).
    marks: int
    company_tags: list[str] = Field(default_factory=list)
    created_by: PyObjectId
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AssessmentInDB(MongoBaseModel):
    title: str
    category_ids: list[PyObjectId] = Field(default_factory=list)
    question_pool_size: int = 10
    time_limit_sec: int = 1800
    anti_cheat_config: dict = Field(default_factory=dict)  # populated by Phase 11
    drive_id: PyObjectId | None = None  # links assessment to a specific drive (set by TPO)
    created_by: PyObjectId
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AnsweredQuestion(BaseModel):
    question_id: str
    response: str
    is_correct: bool | None  # None for descriptive (ungraded)
    marks_awarded: int
    time_taken_sec: float | None = None
    difficulty_at_time: DifficultyLevel


class AssessmentAttemptInDB(MongoBaseModel):
    assessment_id: PyObjectId
    student_id: PyObjectId
    session_token: str
    asked_question_ids: list[str] = Field(default_factory=list)
    current_question_id: str | None = None
    current_difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    answers: list[AnsweredQuestion] = Field(default_factory=list)
    violations: list[dict] = Field(default_factory=list)  # populated by Phase 11
    status: AttemptStatus = AttemptStatus.IN_PROGRESS
    started_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: datetime | None = None
    ip_address: str | None = None
    fingerprint_hash: str | None = None  # populated by Phase 11


class KnowledgeStateInDB(MongoBaseModel):
    student_id: PyObjectId
    skill_tag: str
    mastery_pct: float = 0.0
    confidence: float = 0.0
    attempts_count: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    history: list[dict] = Field(default_factory=list)  # [{date, mastery_pct}]


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------
class CategoryCreateRequest(BaseModel):
    name: str
    parent_category_id: str | None = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    parent_category_id: str | None


class QuestionCreateRequest(BaseModel):
    category_id: str
    skill_tags: list[str] = Field(default_factory=list)
    difficulty: DifficultyLevel
    type: QuestionType
    text: str
    options: list[str] = Field(default_factory=list)
    correct_answer: str | None = None
    company_tags: list[str] = Field(default_factory=list)


class QuestionUpdateRequest(BaseModel):
    category_id: str | None = None
    skill_tags: list[str] | None = None
    difficulty: DifficultyLevel | None = None
    type: QuestionType | None = None
    text: str | None = None
    options: list[str] | None = None
    correct_answer: str | None = None
    company_tags: list[str] | None = None


class QuestionAdminResponse(BaseModel):
    """Includes correct_answer — admin/TPO only, never sent to a student mid-assessment."""

    id: str
    category_id: str
    skill_tags: list[str]
    difficulty: DifficultyLevel
    type: QuestionType
    text: str
    options: list[str]
    correct_answer: str | None
    marks: int
    company_tags: list[str]


class QuestionStudentView(BaseModel):
    """What a student sees during an assessment — no correct_answer field, ever."""

    id: str
    difficulty: DifficultyLevel
    type: QuestionType
    text: str
    options: list[str]
    marks: int


class AssessmentCreateRequest(BaseModel):
    title: str
    category_ids: list[str]
    question_pool_size: int = Field(default=10, ge=1, le=100)
    time_limit_sec: int = Field(default=1800, ge=60)
    max_violations: int = Field(default=3, ge=1, le=20)
    require_fullscreen: bool = True


class AssessmentResponse(BaseModel):
    id: str
    title: str
    category_ids: list[str]
    question_pool_size: int
    time_limit_sec: int
    anti_cheat_config: dict


class StartAttemptRequest(BaseModel):
    fingerprint_hash: str | None = None
    application_id: str | None = None  # required when starting a drive-linked assessment


class StartAttemptResponse(BaseModel):
    attempt_id: str
    session_token: str
    time_limit_sec: int
    anti_cheat_config: dict
    next_question: QuestionStudentView | None


class SubmitAnswerRequest(BaseModel):
    session_token: str
    question_id: str
    response: str
    time_taken_sec: float | None = None


class SubmitAnswerResponse(BaseModel):
    is_correct: bool | None
    marks_awarded: int
    next_question: QuestionStudentView | None
    attempt_status: AttemptStatus


class ViolationReportRequest(BaseModel):
    session_token: str
    type: str
    metadata: dict = Field(default_factory=dict)


class ViolationReportResponse(BaseModel):
    violation_count: int
    max_violations: int
    attempt_status: AttemptStatus
    auto_submitted: bool


class AttemptResultResponse(BaseModel):
    attempt_id: str
    status: AttemptStatus
    total_marks: int
    max_possible_marks: int
    questions_answered: int
    started_at: datetime
    submitted_at: datetime | None


class KnowledgeStateResponse(BaseModel):
    skill_tag: str
    mastery_pct: float
    confidence: float
    attempts_count: int
