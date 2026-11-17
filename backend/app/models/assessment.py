"""
Knowledge Tracing System models.

Grading rules (see PROJECT_PROGRESS.md for the full reasoning):

- MCQ is exact-match against ``correct_answer``.
- Coding questions are executed against one or more stdin/stdout test cases
  by ``code_execution_service``. A question passes only when every test case
  passes. Questions created before test cases existed fall back to a single
  empty-input case compared against ``correct_answer``, preserving the old
  behaviour.
- Descriptive questions are stored but not auto-graded — they're flagged for
  manual review.

The local code runner is a best-effort subprocess executor, NOT a hardened
sandbox — see ``code_execution_service`` for the security caveats.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel, PyObjectId


class AssessmentType(str, Enum):
    PRACTICE = "practice"
    DRIVE = "drive"


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


class CodingLanguage(str, Enum):
    """Languages the local code runner can execute.

    Kept deliberately small: Python and JavaScript are the two runtimes
    guaranteed to be present in this project's environments (the backend
    venv and the Node install used by the frontend). Adding a compiled
    language later is a matter of extending the command registry in
    ``code_execution_service`` — no model changes needed.
    """

    PYTHON = "python"
    JAVASCRIPT = "javascript"


class TestCase(BaseModel):
    """One stdin/stdout test case for a coding question.

    The student's program reads ``input`` from stdin and its stdout is
    compared against ``expected_output`` (line-ending and trailing-whitespace
    normalised). Hidden cases are still run, but their input/expected/actual
    values are never returned to the student — only pass/fail.
    """

    name: str | None = None
    input: str = ""
    expected_output: str
    is_hidden: bool = True


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
    correct_answer: str | None = None  # MCQ: option text. Coding: legacy expected output. Descriptive: None (manual grading).
    # --- Coding-only fields (ignored for other question types) ---
    language: CodingLanguage | None = None
    starter_code: str | None = None  # shown pre-filled in the student editor
    test_cases: list[TestCase] = Field(default_factory=list)
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
    type: AssessmentType = AssessmentType.PRACTICE  # practice or drive assessment
    drive_id: PyObjectId | None = None  # links assessment to a specific drive (set by TPO), required for DRIVE type
    created_by: PyObjectId
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AnsweredQuestion(BaseModel):
    question_id: str
    response: str
    is_correct: bool | None  # None for descriptive (ungraded)
    marks_awarded: int
    time_taken_sec: float | None = None
    difficulty_at_time: DifficultyLevel
    question_type: QuestionType | None = None  # stored for results, old records may omit it
    # Detailed per-test outcome for coding questions (None for other types).
    code_result: dict | None = None


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
    language: CodingLanguage | None = None
    starter_code: str | None = None
    test_cases: list[TestCase] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)


class QuestionUpdateRequest(BaseModel):
    category_id: str | None = None
    skill_tags: list[str] | None = None
    difficulty: DifficultyLevel | None = None
    type: QuestionType | None = None
    text: str | None = None
    options: list[str] | None = None
    correct_answer: str | None = None
    language: CodingLanguage | None = None
    starter_code: str | None = None
    test_cases: list[TestCase] | None = None
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
    language: CodingLanguage | None = None
    starter_code: str | None = None
    test_cases: list[TestCase] = Field(default_factory=list)
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
    # Coding-only. Only non-hidden test cases are exposed as samples.
    language: CodingLanguage | None = None
    starter_code: str | None = None
    visible_test_cases: list[TestCase] = Field(default_factory=list)


class AssessmentCreateRequest(BaseModel):
    title: str
    category_ids: list[str]
    question_pool_size: int = Field(default=10, ge=1, le=100)
    time_limit_sec: int = Field(default=1800, ge=60)
    max_violations: int = Field(default=3, ge=1, le=20)
    require_fullscreen: bool = True
    type: AssessmentType = AssessmentType.PRACTICE


class AssessmentResponse(BaseModel):
    id: str
    title: str
    category_ids: list[str]
    question_pool_size: int
    time_limit_sec: int
    anti_cheat_config: dict
    type: AssessmentType
    drive_id: str | None = None


class CodeTestCaseResult(BaseModel):
    """Outcome of one test case.

    ``input``/``expected_output``/``actual_output`` are only populated for
    non-hidden test cases — hidden cases reveal nothing but pass/fail.
    """

    index: int
    name: str | None = None
    is_hidden: bool = True
    passed: bool
    status: str  # passed | wrong_answer | runtime_error | timeout | output_limit_exceeded | skipped
    input: str | None = None
    expected_output: str | None = None
    actual_output: str | None = None
    stderr: str | None = None
    runtime_ms: float | None = None


class CodeRunSummary(BaseModel):
    passed: int
    total: int
    all_passed: bool
    status: str  # completed | disabled | unsupported_language | error
    results: list[CodeTestCaseResult] = Field(default_factory=list)
    error: str | None = None


class StartAttemptRequest(BaseModel):
    fingerprint_hash: str | None = None
    application_id: str | None = None  # required when starting a drive-linked assessment


class StartAttemptResponse(BaseModel):
    attempt_id: str
    session_token: str
    time_limit_sec: int
    time_remaining_sec: int
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
    code_result: CodeRunSummary | None = None


class FinishAttemptRequest(BaseModel):
    session_token: str


class FinishAttemptResponse(BaseModel):
    attempt_id: str
    status: AttemptStatus
    questions_answered: int
    total_marks: int
    max_possible_marks: int
    submitted_at: datetime | None


class RunCodeRequest(BaseModel):
    session_token: str
    question_id: str
    code: str


class RunCodeResponse(BaseModel):
    code_result: CodeRunSummary


class ViolationReportRequest(BaseModel):
    session_token: str
    type: str
    metadata: dict = Field(default_factory=dict)


class ViolationReportResponse(BaseModel):
    violation_count: int
    max_violations: int
    attempt_status: AttemptStatus
    auto_submitted: bool


class AttemptAnswerDetail(BaseModel):
    question_id: str
    type: QuestionType | None = None
    text: str
    response: str
    is_correct: bool | None
    marks_awarded: int
    max_marks: int
    code_result: CodeRunSummary | None = None


class AttemptResultResponse(BaseModel):
    attempt_id: str
    status: AttemptStatus
    total_marks: int
    max_possible_marks: int
    questions_answered: int
    started_at: datetime
    submitted_at: datetime | None
    answers: list[AttemptAnswerDetail] = Field(default_factory=list)


class KnowledgeStateResponse(BaseModel):
    skill_tag: str
    mastery_pct: float
    confidence: float
    attempts_count: int
