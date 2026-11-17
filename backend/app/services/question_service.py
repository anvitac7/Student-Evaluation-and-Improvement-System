"""
Admin-facing question bank management.

Import/export is JSON-based (bulk create from a JSON array, and a JSON
dump of matching questions) rather than CSV/Excel. This satisfies the
"import questions / export questions" requirement functionally without
pulling in a spreadsheet-parsing dependency for what's fundamentally a
JSON-shaped resource — CSV/Excel support is a reasonable future addition
if a real workflow need for it shows up.
"""
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.models.assessment import (
    DIFFICULTY_MARKS,
    CategoryCreateRequest,
    CodingLanguage,
    QuestionCategoryInDB,
    QuestionCreateRequest,
    QuestionInDB,
    QuestionType,
    QuestionUpdateRequest,
    TestCase,
)
from app.repositories.question_repository import QuestionCategoryRepository, QuestionRepository


class QuestionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class QuestionService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.categories = QuestionCategoryRepository(db)
        self.questions = QuestionRepository(db)

    async def create_category(self, payload: CategoryCreateRequest) -> QuestionCategoryInDB:
        return await self.categories.create(
            {"name": payload.name, "parent_category_id": payload.parent_category_id}
        )

    @staticmethod
    def _validate_question_payload(
        question_type: QuestionType,
        options: list[str],
        correct_answer: str | None,
        language: CodingLanguage | None = None,
        test_cases: list[TestCase] | None = None,
        starter_code: str | None = None,
    ) -> None:
        if question_type == QuestionType.MCQ:
            if len(options) < 2:
                raise QuestionError("MCQ questions need at least 2 options.")
            if not correct_answer:
                raise QuestionError("MCQ questions require a correct_answer.")
            if correct_answer not in options:
                raise QuestionError("correct_answer must be one of the provided options.")
        elif question_type == QuestionType.CODING:
            if language is None:
                raise QuestionError("Coding questions require a language.")
            cases = test_cases or []
            # Backward compatibility: questions created before test cases
            # existed used correct_answer as a single empty-input expected
            # output. Keep accepting that shape so old data and imports work.
            if not cases and not correct_answer:
                raise QuestionError(
                    "Coding questions need at least one test case "
                    "(input + expected output), or a legacy expected-output answer."
                )
            settings = get_settings()
            if len(cases) > settings.CODE_EXECUTION_MAX_TEST_CASES:
                raise QuestionError(
                    f"A coding question can have at most {settings.CODE_EXECUTION_MAX_TEST_CASES} test cases."
                )
            for index, case in enumerate(cases, start=1):
                if len(case.input.encode("utf-8")) > 10000:
                    raise QuestionError(f"Test case {index} input is too large (limit 10,000 bytes).")
                if len(case.expected_output.encode("utf-8")) > 10000:
                    raise QuestionError(f"Test case {index} expected output is too large (limit 10,000 bytes).")
            if starter_code and len(starter_code.encode("utf-8")) > settings.CODE_EXECUTION_MAX_CODE_BYTES:
                raise QuestionError("Starter code is too large.")

    async def create_question(self, admin_user_id: str, payload: QuestionCreateRequest) -> QuestionInDB:
        category = await self.categories.get_by_id(payload.category_id)
        if not category:
            raise QuestionError("Category not found.", 404)

        is_coding = payload.type == QuestionType.CODING
        self._validate_question_payload(
            payload.type,
            payload.options,
            payload.correct_answer,
            language=payload.language if is_coding else None,
            test_cases=payload.test_cases if is_coding else None,
            starter_code=payload.starter_code if is_coding else None,
        )

        return await self.questions.create(
            {
                "category_id": payload.category_id,
                "skill_tags": payload.skill_tags,
                "difficulty": payload.difficulty.value,
                "type": payload.type.value,
                "text": payload.text,
                "options": payload.options,
                "correct_answer": payload.correct_answer,
                "language": payload.language.value if is_coding and payload.language else None,
                "starter_code": payload.starter_code if is_coding else None,
                "test_cases": (
                    [case.model_dump() for case in payload.test_cases] if is_coding else []
                ),
                "marks": DIFFICULTY_MARKS[payload.difficulty],
                "company_tags": payload.company_tags,
                "created_by": admin_user_id,
                "created_at": datetime.utcnow(),
            }
        )

    async def update_question(self, question_id: str, payload: QuestionUpdateRequest) -> QuestionInDB:
        existing = await self.questions.get_by_id(question_id)
        if not existing:
            raise QuestionError("Question not found.", 404)

        update_data = payload.model_dump(exclude_unset=True)

        new_type = payload.type or existing.type
        new_options = payload.options if payload.options is not None else existing.options
        new_answer = payload.correct_answer if "correct_answer" in update_data else existing.correct_answer
        new_language = payload.language if "language" in update_data else existing.language
        new_test_cases = payload.test_cases if "test_cases" in update_data else existing.test_cases
        new_starter_code = payload.starter_code if "starter_code" in update_data else existing.starter_code

        is_coding = new_type == QuestionType.CODING
        self._validate_question_payload(
            new_type,
            new_options,
            new_answer,
            language=new_language if is_coding else None,
            test_cases=new_test_cases if is_coding else None,
            starter_code=new_starter_code if is_coding else None,
        )

        if "difficulty" in update_data:
            update_data["marks"] = DIFFICULTY_MARKS[payload.difficulty]
            update_data["difficulty"] = payload.difficulty.value
        if "type" in update_data:
            update_data["type"] = payload.type.value
        if "language" in update_data:
            update_data["language"] = payload.language.value if payload.language else None
        if "test_cases" in update_data:
            update_data["test_cases"] = [case.model_dump() for case in (payload.test_cases or [])]

        # Switching away from coding must not leave coding-only fields behind.
        if not is_coding:
            update_data["language"] = None
            update_data["starter_code"] = None
            update_data["test_cases"] = []

        updated = await self.questions.update_by_id(question_id, update_data)
        if not updated:
            raise QuestionError("Question not found.", 404)
        return updated

    async def delete_question(self, question_id: str) -> None:
        deleted = await self.questions.delete_by_id(question_id)
        if not deleted:
            raise QuestionError("Question not found.", 404)

    async def bulk_import(self, admin_user_id: str, questions: list[QuestionCreateRequest]) -> list[QuestionInDB]:
        created = []
        for payload in questions:
            created.append(await self.create_question(admin_user_id, payload))
        return created

    async def export_questions(
        self, category_id: str | None = None, difficulty: str | None = None
    ) -> list[QuestionInDB]:
        return await self.questions.find_by_filters(category_id=category_id, difficulty=difficulty, limit=1000)
