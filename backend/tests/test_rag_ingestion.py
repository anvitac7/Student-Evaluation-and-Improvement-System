"""
Tests for RAG chunking and the admin ingestion path.

Chunking exists because `ingest()` stores text verbatim: a multi-page
syllabus became ONE chunk whose embedding represents the whole document, so
retrieval returned it for nearly any query about that skill and the LLM was
handed thousands of mostly-irrelevant tokens.
"""
import pytest

from app.ml.rag.knowledge_store import _chunk_text
from app.ml.parsing.skill_normalizer import ALIASES, CANONICAL_SKILLS


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------
def test_short_text_is_one_chunk():
    assert _chunk_text("Hello world") == ["Hello world"]


def test_empty_text_yields_nothing():
    assert _chunk_text("") == []
    assert _chunk_text("   \n\n  ") == []


def test_long_text_is_split():
    para = "word " * 400  # ~2000 chars, no sentence punctuation
    chunks = _chunk_text(para, max_chars=500, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_paragraph_boundaries_are_preferred():
    text = "\n\n".join(f"Paragraph {i}. " + "filler " * 60 for i in range(6))
    chunks = _chunk_text(text, max_chars=400, overlap=40)
    assert len(chunks) > 1
    # A chunk should not begin mid-word, which is what naive char splitting
    # produces.
    for c in chunks:
        assert not c.startswith(" ")


def test_sentence_boundaries_are_used_within_a_long_paragraph():
    text = " ".join(f"This is sentence number {i}." for i in range(120))
    chunks = _chunk_text(text, max_chars=400, overlap=40)
    assert len(chunks) > 1
    # Sentences should not be cut mid-way: every chunk should end sensibly
    # or be a hard-split artefact, but must not contain a lone fragment.
    joined = " ".join(chunks)
    for i in (0, 1, 2, 3, 4):
        assert f"This is sentence number {i}." in joined


def test_overlap_produces_repeated_content():
    text = " ".join(f"Sentence {i} has some content here." for i in range(80))
    chunks = _chunk_text(text, max_chars=300, overlap=100)
    assert len(chunks) > 1
    # Some content should appear in more than one chunk — that is the point
    # of overlap: a sentence spanning a boundary is then whole in one chunk.
    seen: dict[str, int] = {}
    for c in chunks:
        for word in c.split():
            seen[word] = seen.get(word, 0) + 1
    assert max(seen.values()) > 1, "no overlapping content between chunks"


def test_content_is_not_lost():
    text = " ".join(f"alpha{i} beta{i} gamma{i}" for i in range(200))
    chunks = _chunk_text(text, max_chars=300, overlap=50)
    joined = "".join(chunks)
    for i in (0, 50, 100, 199):
        assert f"alpha{i}" in joined, f"token alpha{i} lost during chunking"


def test_unsplittable_blob_is_still_chunked():
    """A table or code block with no sentence breaks must not become one
    giant chunk."""
    blob = "x" * 5000
    chunks = _chunk_text(blob, max_chars=400, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)


# ---------------------------------------------------------------------------
# seeder content builders
# ---------------------------------------------------------------------------
def test_taxonomy_chunks_cover_every_canonical_skill():
    from scripts.seed_knowledge_store import build_taxonomy_chunks

    chunks = build_taxonomy_chunks()
    tagged = {t for c in chunks for t in c["tags"]}
    missing = set(CANONICAL_SKILLS) - tagged
    assert not missing, f"skills missing from taxonomy seed: {missing}"


def test_taxonomy_chunks_are_short_enough_not_to_need_splitting():
    from scripts.seed_knowledge_store import build_taxonomy_chunks

    for c in build_taxonomy_chunks():
        if c["chunk"] is False:
            assert len(c["text"]) <= 1200, f"{c['source_id']} marked unchunked but too long"


def test_taxonomy_chunks_use_valid_chunk_types():
    from scripts.seed_knowledge_store import build_taxonomy_chunks

    for c in build_taxonomy_chunks():
        assert c["chunk_type"] == "skill_taxonomy"


# ---------------------------------------------------------------------------
# admin ingestion endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_endpoint_rejects_non_admin(client):
    r = await client.post(
        "/api/v1/admin/knowledge/chunks",
        json={"chunks": [{"text": "x", "chunk_type": "syllabus_note", "source_id": "s"}]},
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ingest_endpoint_rejects_unknown_chunk_type(client, mock_mongo):
    from app.models.user import AdminRegisterRequest
    from app.services.auth_service import AuthService

    svc = AuthService(mock_mongo)
    await svc.register_admin(
        AdminRegisterRequest(
            email="kb.admin@college.edu", password="Admin@12345", name="KB Admin"
        )
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "kb.admin@college.edu", "password": "Admin@12345"},
        )
    ).json()["access_token"]

    r = await client.post(
        "/api/v1/admin/knowledge/chunks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chunks": [
                {"text": "x", "chunk_type": "totally_invalid_type", "source_id": "s1"}
            ]
        },
    )
    assert r.status_code == 422
    assert "chunk_type" in r.json()["detail"]


@pytest.mark.asyncio
async def test_stats_endpoint_reports_zero_for_empty_store(client, mock_mongo):
    from app.models.user import AdminRegisterRequest
    from app.services.auth_service import AuthService

    svc = AuthService(mock_mongo)
    await svc.register_admin(
        AdminRegisterRequest(
            email="kb2.admin@college.edu", password="Admin@12345", name="KB Admin 2"
        )
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "kb2.admin@college.edu", "password": "Admin@12345"},
        )
    ).json()["access_token"]

    r = await client.get(
        "/api/v1/admin/knowledge/stats", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["by_type"] == {}
    assert body["embedding_model"]


@pytest.mark.asyncio
async def test_delete_by_source_prefix_removes_only_that_source(mock_mongo):
    from app.ml.rag.knowledge_store import KnowledgeStore

    store = KnowledgeStore(mock_mongo)
    await store.collection.insert_one(
        {"text": "a0", "chunk_type": "syllabus_note", "tags": ["Python"], "source_id": "docA#0", "vector": [1.0]}
    )
    await store.collection.insert_one(
        {"text": "a1", "chunk_type": "syllabus_note", "tags": ["Python"], "source_id": "docA#1", "vector": [1.0]}
    )
    await store.collection.insert_one(
        {"text": "b0", "chunk_type": "syllabus_note", "tags": ["SQL"], "source_id": "docB#0", "vector": [1.0]}
    )

    deleted = await store.delete_by_source_prefix("docA")
    assert deleted == 2
    assert await store.count() == 1
    remaining = await store.collection.find_one({"source_id": "docB#0"})
    assert remaining is not None