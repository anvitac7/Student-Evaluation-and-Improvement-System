"""
PHASE C — app/ml/rag/knowledge_store.py

Small knowledge-chunk store used by BOTH Phase C (gap analysis) and
Phase D (JD explanation) — one store, two kinds of content ingested into
it (`skill` / `syllabus_note` / `question_explanation` for Phase C,
`job_description` / `skill_taxonomy` for Phase D), disambiguated by the
`tags` + `chunk_type` fields, not by separate collections.

Backend: cosine similarity over vectors stored directly in MongoDB
(KNOWLEDGE_STORE_BACKEND=mongodb_cosine). Fine at this project's scale
(hundreds–low thousands of chunks); swap to a real vector DB later by
reimplementing this one class without touching any caller.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError

logger = logging.getLogger(__name__)

COLLECTION = "knowledge_chunks"


@dataclass
class RetrievedChunk:
    text: str
    chunk_type: str
    tags: list[str]
    score: float


class KnowledgeStore:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db[COLLECTION]

    async def ingest(self, *, text: str, chunk_type: str, tags: list[str], source_id: str) -> bool:
        """
        chunk_type: "syllabus_note" | "question_explanation" | "job_description" | "skill_taxonomy"
        tags: skill names this chunk is relevant to (from the same
              CANONICAL_SKILLS vocabulary — keeps retrieval aligned with
              matching/knowledge-tracing skill tags).

        Returns False (never raises) if embedding is unavailable — ingestion
        is a background/admin-triggered step, so degrading to "not ingested
        yet, retry later" is acceptable; it must not crash the admin action
        that triggered it (question creation, JD save, etc.).
        """
        try:
            [vector] = llm_client.embed([text])
        except LLMUnavailableError:
            logger.warning("Embedding unavailable — chunk not ingested (source_id=%s)", source_id)
            return False

        await self.collection.insert_one(
            {
                "text": text,
                "chunk_type": chunk_type,
                "tags": tags,
                "source_id": source_id,
                "vector": vector,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return True

    async def retrieve(self, *, query_skills: list[str], chunk_types: list[str], top_k: int = 5) -> list[RetrievedChunk]:
        """
        Retrieves the most relevant chunks for a set of weak/missing skills,
        restricted to the given chunk_types (e.g. Phase C passes
        ["syllabus_note", "question_explanation"], Phase D passes
        ["job_description", "skill_taxonomy"]).

        Returns [] (never raises) if embeddings are unavailable — callers
        (gap-analysis / JD-explanation services) must treat "no chunks
        retrieved" as "narrate with less grounding" or "skip narrative",
        never as a hard failure.
        """
        if not query_skills:
            return []

        query_text = ", ".join(query_skills)
        try:
            [query_vector] = llm_client.embed([query_text])
        except LLMUnavailableError:
            logger.warning("Embedding unavailable — retrieval skipped for skills=%s", query_skills)
            return []

        # Pre-filter by chunk_type + tag overlap in Mongo (cheap), then
        # rank the (small) remaining set by cosine similarity in Python.
        cursor = self.collection.find(
            {"chunk_type": {"$in": chunk_types}, "tags": {"$in": query_skills}}
        )
        candidates = [doc async for doc in cursor]
        if not candidates:
            return []

        q = np.array(query_vector)
        q_norm = q / (np.linalg.norm(q) + 1e-9)

        scored: list[RetrievedChunk] = []
        for doc in candidates:
            v = np.array(doc["vector"])
            v_norm = v / (np.linalg.norm(v) + 1e-9)
            score = float(np.dot(q_norm, v_norm))
            scored.append(RetrievedChunk(text=doc["text"], chunk_type=doc["chunk_type"], tags=doc["tags"], score=score))

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]