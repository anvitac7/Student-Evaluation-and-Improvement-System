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
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import get_settings
from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError

logger = logging.getLogger(__name__)

COLLECTION = "knowledge_chunks"

settings = get_settings()


@dataclass
class RetrievedChunk:
    text: str
    chunk_type: str
    tags: list[str]
    score: float


def _chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split `text` into overlapping chunks of at most `max_chars`.

    Prefers paragraph boundaries (blank lines), then sentence boundaries, and
    only hard-splits as a last resort — so chunks stay semantically whole,
    which matters because each one is embedded independently.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []

    def _emit(piece: str) -> None:
        piece = piece.strip()
        if piece:
            chunks.append(piece)

    # Paragraph pass.
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            _emit(current)
        # A single paragraph longer than the budget gets sentence-split.
        if len(para) <= max_chars:
            current = para
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        current = ""
        for sent in sentences:
            cand = f"{current} {sent}".strip() if current else sent
            if len(cand) <= max_chars:
                current = cand
            else:
                _emit(current)
                current = sent
    if current:
        _emit(current)

    # Anything still oversized (no sentence breaks available, e.g. code or a
    # table) gets a hard split with overlap.
    final: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            final.append(chunk[:max_chars])
            chunk = chunk[max_chars - overlap :]
        if chunk.strip():
            final.append(chunk)
    return final or [text]


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
            [vector] = await llm_client.embed_async([text])
        except LLMUnavailableError:
            logger.warning("Embedding unavailable — chunk not ingested (source_id=%s)", source_id)
            return False

        await self.collection.insert_one(
            {
                "text": text,
                "chunk_type": chunk_type,
                "tags": tags,
                "source_id": source_id,
                "chunk_index": 0,
                "vector": vector,
                # Stamped so retrieval can refuse to compare vectors from a
                # different embedding model. Mixing models is the dangerous
                # case: two 768-dim vectors from different models dot-product
                # fine and return a plausible-but-meaningless score, so
                # nothing downstream can tell the difference.
                "embed_model": settings.EMBEDDING_MODEL,
                "embed_dim": len(vector),
                "created_at": datetime.now(timezone.utc),
            }
        )
        return True

    async def ingest_long(
        self,
        *,
        text: str,
        chunk_type: str,
        tags: list[str],
        source_id: str,
        max_chars: int = 1200,
        overlap: int = 150,
    ) -> int:
        """Chunk a long document and ingest each chunk. Returns the count.

        Why this exists: `ingest()` stores a document verbatim, so pasting a
        multi-page syllabus produced ONE chunk whose embedding is a blur of
        the whole thing. Retrieval would return it for almost any query about
        that skill (embedding similarity is dominated by overall topic), and
        the LLM would be handed several thousand tokens of mostly-irrelevant
        text to summarise. Chunking first is what makes retrieval precise.

        Splits on paragraph boundaries where possible, falling back to a hard
        character split for text with no blank lines, so a wall of prose
        still gets chunked rather than becoming one blob. `overlap` repeats
        the tail of the previous chunk so a sentence spanning a boundary is
        still fully present in one of them.
        """
        if not text.strip():
            return 0

        pieces = _chunk_text(text, max_chars=max_chars, overlap=overlap)
        inserted = 0
        for idx, piece in enumerate(pieces):
            ok = await self.ingest(
                text=piece,
                chunk_type=chunk_type,
                tags=tags,
                # Per-chunk source_id keeps chunks independently replaceable.
                source_id=f"{source_id}#{idx}",
            )
            if ok:
                inserted += 1
        logger.info(
            "Ingested %d/%d chunks from %s (%s)", inserted, len(pieces), source_id, chunk_type
        )
        return inserted

    async def delete_by_source_prefix(self, source_id: str) -> int:
        """Remove every chunk belonging to a source document, so a document
        can be re-ingested after an edit without accumulating stale copies."""
        result = await self.collection.delete_many(
            {"source_id": {"$regex": f"^{re.escape(source_id)}(#|$)"}}
        )
        return result.deleted_count

    async def count(self, query: dict | None = None) -> int:
        return await self.collection.count_documents(query or {})

    async def stats(self) -> dict:
        """Counts per chunk_type, for the admin/observability surface."""
        pipeline = [{"$group": {"_id": "$chunk_type", "n": {"$sum": 1}}}]
        rows = await self.collection.aggregate(pipeline).to_list(length=100)
        by_type = {r["_id"]: r["n"] for r in rows}
        return {"total": sum(by_type.values()), "by_type": by_type}

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
            [query_vector] = await llm_client.embed_async([query_text])
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

        # Drop anything embedded by a different model, and say so. Chunks
        # written before the embed_model stamp existed have no stamp at all;
        # those are treated as foreign rather than trusted, because the whole
        # point of this check is to refuse comparisons we cannot verify.
        usable: list[dict] = []
        foreign = 0
        for doc in candidates:
            if doc.get("embed_model") != settings.EMBEDDING_MODEL:
                foreign += 1
                continue
            if len(doc["vector"]) != q.shape[0]:
                foreign += 1
                continue
            usable.append(doc)

        if foreign:
            logger.warning(
                "Skipped %d/%d retrieved chunks: embedded with a model other than %s "
                "(or an unrecorded legacy model). Re-ingest them to use them — "
                "comparing vectors across models yields meaningless scores.",
                foreign, len(candidates), settings.EMBEDDING_MODEL,
            )
        if not usable:
            return []

        scored: list[RetrievedChunk] = []
        for doc in usable:
            v = np.array(doc["vector"])
            v_norm = v / (np.linalg.norm(v) + 1e-9)
            score = float(np.dot(q_norm, v_norm))
            scored.append(RetrievedChunk(text=doc["text"], chunk_type=doc["chunk_type"], tags=doc["tags"], score=score))

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]