from app.models.assessment import AssessmentAttemptInDB
from app.repositories.base import BaseRepository


class AttemptRepository(BaseRepository[AssessmentAttemptInDB]):
    collection_name = "assessment_attempts"
    model = AssessmentAttemptInDB

    # Cap on a student's full attempt history. High enough that no realistic
    # student reaches it, but present so a pathological account can't pull an
    # unbounded set into memory. Callers that aggregate over this should treat
    # hitting the cap as "history is incomplete" and say so rather than
    # silently reporting partial totals.
    HISTORY_FETCH_LIMIT = 500

    async def get_for_student(self, student_id: str) -> list[AssessmentAttemptInDB]:
        """Every attempt for a student, newest first.

        Deliberately NOT paginated. This feeds cross-attempt aggregation
        (knowledge tracing, student insights), where silently dropping older
        attempts would bias the student's accuracy and trend figures with no
        visible symptom.
        """
        return await self.find_many(
            {"student_id": student_id},
            sort=[("started_at", -1)],
            limit=self.HISTORY_FETCH_LIMIT,
        )

    async def count_for_student(self, student_id: str) -> int:
        """Total attempt count, so callers can detect that get_for_student()
        returned a capped (i.e. incomplete) history."""
        return await self.count({"student_id": student_id})
