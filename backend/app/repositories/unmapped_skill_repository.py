"""
PHASE B — app/repositories/unmapped_skill_repository.py

New, small collection: `unmapped_skill_suggestions`. Admin-reviewed queue
for skills the LLM found in resume/JD text that aren't in the 50-term
vocabulary yet. Follows the same repository pattern as the existing
repositories in app/repositories/.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

COLLECTION = "unmapped_skill_suggestions"


class UnmappedSkillRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[COLLECTION]

    async def add_many(self, suggestions: list["UnmappedSkillSuggestion"]) -> None:
        if not suggestions:
            return
        docs = [
            {
                "phrase": s.phrase,
                "source_id": s.source_id,
                "source_type": s.source_type,
                "reviewed": False,
                "created_at": datetime.now(timezone.utc),
            }
            for s in suggestions
        ]
        # Cheap de-dupe guard: skip phrases already queued+unreviewed for
        # the same source, so re-parsing the same resume doesn't spam the
        # admin queue.
        for doc in docs:
            existing = await self.collection.find_one(
                {"phrase": doc["phrase"], "source_id": doc["source_id"], "reviewed": False}
            )
            if not existing:
                await self.collection.insert_one(doc)

    async def list_unreviewed(self, limit: int = 100) -> list[dict]:
        cursor = self.collection.find({"reviewed": False}).sort("created_at", -1).limit(limit)
        return [doc async for doc in cursor]

    async def mark_reviewed(self, suggestion_id: str, *, added_to_vocabulary: bool) -> bool:
        result = await self.collection.update_one(
            {"_id": ObjectId(suggestion_id)},
            {"$set": {"reviewed": True, "added_to_vocabulary": added_to_vocabulary}},
        )
        return result.modified_count > 0


# Import at bottom to avoid a circular import at module load time (this
# repository only needs the type for the hint above).
from app.ml.parsing.llm_skill_extractor import UnmappedSkillSuggestion  # noqa: E402