"""
Admin ingestion endpoints for the RAG knowledge store.

There was previously NO way to put content into `knowledge_chunks`: the
ingest methods existed on KnowledgeStore but nothing reachable from the API
called them, so RAG retrieval always returned nothing and every narrative was
written ungrounded while appearing to work.

All routes are ADMIN-only. Knowledge content is injected straight into LLM
prompts downstream, so an open write path would be a prompt-injection
surface.
"""
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.database import get_database
from app.core.deps import CurrentUser, require_role
from app.ml.rag.knowledge_store import KnowledgeStore

router = APIRouter(prefix="/admin/knowledge", tags=["Knowledge Store"])

VALID_CHUNK_TYPES = {
    "syllabus_note",
    "question_explanation",
    "job_description",
    "skill_taxonomy",
}


class ChunkIn(BaseModel):
    text: str = Field(min_length=1)
    chunk_type: str
    tags: list[str] = Field(default_factory=list)
    source_id: str = Field(min_length=1)
    # When true the document is split into overlapping chunks first; use for
    # anything long. Short notes can be stored verbatim.
    chunk: bool = True


class BulkIn(BaseModel):
    chunks: list[ChunkIn] = Field(min_length=1, max_length=500)


class IngestResult(BaseModel):
    attempted: int
    ingested: int
    failed: int


class StoreStats(BaseModel):
    total: int
    by_type: dict[str, int]
    embedding_model: str


@router.post("/chunks", response_model=IngestResult, status_code=201)
async def ingest_chunks(
    payload: BulkIn,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    store = KnowledgeStore(db)
    ingested = failed = 0

    for item in payload.chunks:
        if item.chunk_type not in VALID_CHUNK_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown chunk_type '{item.chunk_type}'. "
                f"Expected one of {sorted(VALID_CHUNK_TYPES)}.",
            )
        try:
            if item.chunk:
                n = await store.ingest_long(
                    text=item.text,
                    chunk_type=item.chunk_type,
                    tags=item.tags,
                    source_id=item.source_id,
                )
                ingested += 1 if n else 0
                failed += 0 if n else 1
            else:
                ok = await store.ingest(
                    text=item.text,
                    chunk_type=item.chunk_type,
                    tags=item.tags,
                    source_id=item.source_id,
                )
                ingested += 1 if ok else 0
                failed += 0 if ok else 1
        except Exception as exc:  # noqa: BLE001
            # One bad document must not abort the batch.
            failed += 1
            continue

    return IngestResult(attempted=len(payload.chunks), ingested=ingested, failed=failed)


@router.delete("/{source_id}", response_model=IngestResult)
async def delete_source(
    source_id: str,
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """Remove every chunk from one source document, so it can be re-ingested
    after an edit without stale duplicates accumulating."""
    deleted = await KnowledgeStore(db).delete_by_source_prefix(source_id)
    return IngestResult(attempted=deleted, ingested=0, failed=0)


@router.get("/stats", response_model=StoreStats)
async def knowledge_stats(
    current_user: CurrentUser = Depends(require_role("admin")),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    store = KnowledgeStore(db)
    stats = await store.stats()
    return StoreStats(
        total=stats["total"],
        by_type=stats["by_type"],
        embedding_model=get_settings().EMBEDDING_MODEL,
    )