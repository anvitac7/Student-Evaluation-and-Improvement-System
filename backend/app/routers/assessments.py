from fastapi import APIRouter, Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, get_current_user, require_role
from app.models.assessment import (
    DIFFICULTY_MARKS,
    AssessmentCreateRequest,
    AssessmentResponse,
    AttemptResultResponse,
    KnowledgeStateResponse,
    StartAttemptRequest,
    StartAttemptResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    ViolationReportRequest,
    ViolationReportResponse,
)
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.profile_repositories import StudentRepository
from app.services.assessment_service import AssessmentError, AssessmentService, to_student_view
from app.services.knowledge_tracing_service import KnowledgeTracingService

router = APIRouter()


@router.post("", response_model=AssessmentResponse, status_code=201)
async def create_assessment(
    payload: AssessmentCreateRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    anti_cheat_config = {
        "max_violations": payload.max_violations,
        "require_fullscreen": payload.require_fullscreen,
    }
    assessment = await AssessmentRepository(db).create(
        {
            "title": payload.title,
            "category_ids": payload.category_ids,
            "question_pool_size": payload.question_pool_size,
            "time_limit_sec": payload.time_limit_sec,
            "anti_cheat_config": anti_cheat_config,
            "created_by": current_user.id,
        }
    )
    return AssessmentResponse(
        id=assessment.id,
        title=assessment.title,
        category_ids=assessment.category_ids,
        question_pool_size=assessment.question_pool_size,
        time_limit_sec=assessment.time_limit_sec,
        anti_cheat_config=assessment.anti_cheat_config,
    )


@router.get("", response_model=list[AssessmentResponse])
async def list_assessments(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    assessments = await AssessmentRepository(db).find_many({}, limit=200)
    return [
        AssessmentResponse(
            id=a.id,
            title=a.title,
            category_ids=a.category_ids,
            question_pool_size=a.question_pool_size,
            time_limit_sec=a.time_limit_sec,
            anti_cheat_config=a.anti_cheat_config,
        )
        for a in assessments
    ]


@router.get("/knowledge-states/me", response_model=list[KnowledgeStateResponse])
async def my_knowledge_states(
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    student = await StudentRepository(db).get_by_user_id(current_user.id)
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    kts = KnowledgeTracingService(db)
    states = await kts.knowledge_states.get_all_for_student(student.id)
    return [
        KnowledgeStateResponse(
            skill_tag=s.skill_tag,
            mastery_pct=s.mastery_pct,
            confidence=s.confidence,
            attempts_count=s.attempts_count,
        )
        for s in states
    ]


@router.get("/knowledge-states/{student_id}", response_model=list[KnowledgeStateResponse])
async def student_knowledge_states(
    student_id: str,
    current_user: CurrentUser = Depends(require_role("tpo", "admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    if current_user.role == "tpo":
        from app.repositories.application_repository import ApplicationRepository
        from app.repositories.drive_repository import PlacementDriveRepository
        from app.repositories.profile_repositories import TPORepository

        tpo = await TPORepository(db).get_by_user_id(current_user.id)
        if not tpo:
            raise HTTPException(status_code=403, detail="TPO profile not found.")
        # Check if this student has applied to any drive owned by this TPO
        drives = await PlacementDriveRepository(db).find_many({"created_by": tpo.id}, limit=500)
        drive_ids = [d.id for d in drives]
        app_match = await ApplicationRepository(db).find_one({"student_id": student_id, "drive_id": {"$in": drive_ids}})
        if not app_match:
            raise HTTPException(status_code=403, detail="You do not have permission to view this student's knowledge states.")

    kts = KnowledgeTracingService(db)
    states = await kts.knowledge_states.get_all_for_student(student_id)
    return [
        KnowledgeStateResponse(
            skill_tag=s.skill_tag,
            mastery_pct=s.mastery_pct,
            confidence=s.confidence,
            attempts_count=s.attempts_count,
        )
        for s in states
    ]


@router.post("/{assessment_id}/start", response_model=StartAttemptResponse, status_code=201)
async def start_assessment(
    assessment_id: str,
    payload: StartAttemptRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AssessmentService(db)
    client_ip = request.client.host if request.client else None
    try:
        attempt, first_question = await service.start_attempt(
            current_user.id,
            assessment_id,
            fingerprint_hash=payload.fingerprint_hash,
            ip_address=client_ip,
            application_id=payload.application_id,
        )
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    assessment = await service.assessments.get_by_id(assessment_id)
    return StartAttemptResponse(
        attempt_id=attempt.id,
        session_token=attempt.session_token,
        time_limit_sec=assessment.time_limit_sec,
        anti_cheat_config=assessment.anti_cheat_config,
        next_question=to_student_view(first_question) if first_question else None,
    )


@router.post("/attempts/{attempt_id}/answer", response_model=SubmitAnswerResponse)
async def submit_answer(
    attempt_id: str,
    payload: SubmitAnswerRequest,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AssessmentService(db)
    try:
        attempt, next_question, is_correct, marks_awarded = await service.submit_answer(
            current_user.id,
            attempt_id,
            payload.session_token,
            payload.question_id,
            payload.response,
            payload.time_taken_sec,
        )
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return SubmitAnswerResponse(
        is_correct=is_correct,
        marks_awarded=marks_awarded,
        next_question=to_student_view(next_question) if next_question else None,
        attempt_status=attempt.status,
    )


@router.post("/attempts/{attempt_id}/violation", response_model=ViolationReportResponse)
async def report_violation(
    attempt_id: str,
    payload: ViolationReportRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Reports a client-detected anti-cheat event. `type` is a free-form
    string by convention — the frontend (Phase 12) sends values like
    "tab_switch", "fullscreen_exit", "devtools_opened", "idle_timeout",
    "copy_paste_attempt" — the backend doesn't hardcode this list, it just
    counts occurrences and auto-submits once the assessment's configured
    threshold is reached.
    """
    service = AssessmentService(db)
    client_ip = request.client.host if request.client else None
    try:
        attempt, violation_count, max_violations, auto_submitted = await service.report_violation(
            current_user.id,
            attempt_id,
            payload.session_token,
            payload.type,
            payload.metadata,
            ip_address=client_ip,
        )
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return ViolationReportResponse(
        violation_count=violation_count,
        max_violations=max_violations,
        attempt_status=attempt.status,
        auto_submitted=auto_submitted,
    )


@router.get("/attempts/{attempt_id}/results", response_model=AttemptResultResponse)
async def get_attempt_results(
    attempt_id: str,
    current_user: CurrentUser = Depends(require_role("student")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = AssessmentService(db)
    try:
        attempt = await service.get_results(current_user.id, attempt_id)
    except AssessmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    total_marks = sum(a.marks_awarded for a in attempt.answers)
    # Max possible marks reconstructed from each question's difficulty at
    # the time it was asked (marks are fully determined by difficulty in
    # this system — see DIFFICULTY_MARKS) rather than from marks_awarded,
    # which is 0 for wrong answers and so can't represent "possible" marks.
    max_possible_marks = sum(DIFFICULTY_MARKS[a.difficulty_at_time] for a in attempt.answers)

    return AttemptResultResponse(
        attempt_id=attempt.id,
        status=attempt.status,
        total_marks=total_marks,
        max_possible_marks=max_possible_marks,
        questions_answered=len(attempt.answers),
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
    )
