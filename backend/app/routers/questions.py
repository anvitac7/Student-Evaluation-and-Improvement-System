from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.models.assessment import (
    CategoryCreateRequest,
    CategoryResponse,
    QuestionAdminResponse,
    QuestionCreateRequest,
    QuestionInDB,
    QuestionUpdateRequest,
)
from app.services.question_service import QuestionError, QuestionService

router = APIRouter()


def _to_admin_response(question: QuestionInDB) -> QuestionAdminResponse:
    return QuestionAdminResponse(
        id=question.id,
        category_id=question.category_id,
        skill_tags=question.skill_tags,
        difficulty=question.difficulty,
        type=question.type,
        text=question.text,
        options=question.options,
        correct_answer=question.correct_answer,
        language=question.language,
        starter_code=question.starter_code,
        test_cases=question.test_cases,
        marks=question.marks,
        company_tags=question.company_tags,
    )


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    payload: CategoryCreateRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    category = await service.create_category(payload)
    return CategoryResponse(id=category.id, name=category.name, parent_category_id=category.parent_category_id)


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    current_user: CurrentUser = Depends(require_role("admin", "tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    from app.repositories.question_repository import QuestionCategoryRepository

    categories = await QuestionCategoryRepository(db).find_many({}, limit=200)
    return [
        CategoryResponse(id=c.id, name=c.name, parent_category_id=c.parent_category_id) for c in categories
    ]


@router.post("", response_model=QuestionAdminResponse, status_code=201)
async def create_question(
    payload: QuestionCreateRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    try:
        question = await service.create_question(current_user.id, payload)
    except QuestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_admin_response(question)


@router.get("", response_model=list[QuestionAdminResponse])
async def list_questions(
    category_id: str | None = None,
    difficulty: str | None = None,
    current_user: CurrentUser = Depends(require_role("admin", "tpo")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    questions = await service.questions.find_by_filters(category_id=category_id, difficulty=difficulty, limit=200)
    return [_to_admin_response(q) for q in questions]


@router.put("/{question_id}", response_model=QuestionAdminResponse)
async def update_question(
    question_id: str,
    payload: QuestionUpdateRequest,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    try:
        question = await service.update_question(question_id, payload)
    except QuestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_admin_response(question)


@router.delete("/{question_id}", status_code=204)
async def delete_question(
    question_id: str,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    try:
        await service.delete_question(question_id)
    except QuestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/import", response_model=list[QuestionAdminResponse], status_code=201)
async def import_questions(
    payload: list[QuestionCreateRequest],
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    try:
        questions = await service.bulk_import(current_user.id, payload)
    except QuestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return [_to_admin_response(q) for q in questions]


@router.get("/export", response_model=list[QuestionAdminResponse])
async def export_questions(
    category_id: str | None = None,
    difficulty: str | None = None,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    service = QuestionService(db)
    questions = await service.export_questions(category_id=category_id, difficulty=difficulty)
    return [_to_admin_response(q) for q in questions]
