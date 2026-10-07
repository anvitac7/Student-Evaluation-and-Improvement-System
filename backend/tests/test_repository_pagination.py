"""
Regression tests for silent truncation in BaseRepository.find_many.

The bug: `find_many` defaulted to `limit=20`. Any caller that forgot to
pass a limit got exactly 20 documents — no error, no warning, no indication
that the result was partial. Two call sites did exactly that, and in both
cases the data was being aggregated:

  * AttemptRepository.get_for_student — fed every cross-attempt statistic
    (accuracy, mastery trend, focus areas). A student with >20 attempts had
    their whole history silently truncated to the most recent 20, producing
    confident-looking but wrong numbers.
  * AssessmentService.submit_answer's linked-application lookup — a missed
    row means an application never gets its pass/fail status updated.

These tests assert the *observable* contract rather than the implementation:
a student with 25 submitted attempts must have all 25 counted.
"""
from datetime import datetime

import pytest
from bson import ObjectId

from app.models.assessment import AttemptStatus, DifficultyLevel
from app.repositories.attempt_repository import AttemptRepository

ASSESSMENT_ID = str(ObjectId())


def _attempt_doc(i: int, student_id: str) -> dict:
    return {
        "assessment_id": ASSESSMENT_ID,
        "student_id": student_id,
        "session_token": f"tok-{i}",
        "asked_question_ids": [],
        "answers": [],
        "violations": [],
        "status": AttemptStatus.SUBMITTED.value,
        "started_at": datetime(2026, 1, 1 + (i % 28), 12, 0, 0),
        "submitted_at": datetime(2026, 1, 1 + (i % 28), 12, 30, 0),
    }


@pytest.mark.asyncio
async def test_get_for_student_returns_more_than_twenty_attempts(mock_mongo):
    """The regression itself: 25 attempts must come back as 25, not 20.

    Under the old `limit=20` default this returned exactly 20 with no error.
    """
    repo = AttemptRepository(mock_mongo)
    student_id = str(ObjectId())

    for i in range(25):
        await repo.collection.insert_one(_attempt_doc(i, student_id))

    fetched = await repo.get_for_student(student_id)
    assert len(fetched) == 25, f"history truncated: got {len(fetched)} of 25"


@pytest.mark.asyncio
async def test_count_for_student_detects_truncation(mock_mongo):
    """count_for_student must report the true total so callers can detect
    that get_for_student() returned a capped (incomplete) history."""
    repo = AttemptRepository(mock_mongo)
    student_id = str(ObjectId())

    for i in range(25):
        await repo.collection.insert_one(_attempt_doc(i, student_id))

    assert await repo.count_for_student(student_id) == 25
    assert len(await repo.get_for_student(student_id)) == 25


@pytest.mark.asyncio
async def test_get_for_student_respects_the_safety_cap(mock_mongo):
    """The cap is real: exceeding HISTORY_FETCH_LIMIT truncates rather than
    pulling an unbounded set into memory."""
    repo = AttemptRepository(mock_mongo)
    student_id = str(ObjectId())
    over = repo.HISTORY_FETCH_LIMIT + 5

    for i in range(over):
        await repo.collection.insert_one(_attempt_doc(i, student_id))

    fetched = await repo.get_for_student(student_id)
    assert len(fetched) == repo.HISTORY_FETCH_LIMIT
    # ...and count_for_student makes the truncation detectable.
    assert await repo.count_for_student(student_id) == over


@pytest.mark.asyncio
async def test_get_for_student_returns_newest_first(mock_mongo):
    """Ordering must survive the fix — insights relies on recency for
    last_missed_at, and the trend heuristic reads the history in order."""
    repo = AttemptRepository(mock_mongo)
    student_id = str(ObjectId())

    for day in range(1, 6):
        await repo.collection.insert_one(
            {
                "assessment_id": ASSESSMENT_ID,
                "student_id": student_id,
                "session_token": f"tok-{day}",
                "asked_question_ids": [],
                "answers": [],
                "violations": [],
                "status": AttemptStatus.SUBMITTED.value,
                "started_at": datetime(2026, 3, day, 9, 0, 0),
                "submitted_at": datetime(2026, 3, day, 9, 30, 0),
            }
        )

    fetched = await repo.get_for_student(student_id)
    assert len(fetched) == 5
    starts = [a.started_at for a in fetched]
    assert starts == sorted(starts, reverse=True), "attempts must be newest-first"


@pytest.mark.asyncio
async def test_find_many_without_limit_is_unbounded(mock_mongo):
    """Documented default change: find_many() with no limit returns
    everything, so an accidental omission is visible in review rather than
    silently truncating at runtime."""
    from app.repositories.question_repository import QuestionRepository

    repo = QuestionRepository(mock_mongo)
    for i in range(30):
        await repo.collection.insert_one(
            {
                "category_id": "000000000000000000000001",
                "skill_tags": ["Python"],
                "difficulty": DifficultyLevel.EASY.value,
                "type": "mcq",
                "text": f"Question number {i}?",
                "options": ["A", "B"],
                "correct_answer": "A",
                "marks": 5,
                "created_by": "000000000000000000000002",
            }
        )

    assert len(await repo.find_many({})) == 30
    # An explicit limit still pages normally.
    assert len(await repo.find_many({}, limit=20)) == 20