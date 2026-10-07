"""
Tests for KnowledgeStore's embedding-model safety check.

The failure mode being guarded against is subtle and important: two vectors
from DIFFERENT embedding models can share a dimension, dot-product without
error, and return a cosine score that looks entirely reasonable while
meaning nothing. Nothing downstream would detect it. The store therefore
stamps each chunk with the model that produced it and refuses to compare
across models.

These tests bypass the embedding provider entirely and insert vectors
directly — the point is the comparison logic, not the network call.
"""
import numpy as np
import pytest

from app.ml.rag.knowledge_store import KnowledgeStore


async def _chunk(store, *, vector, model="gemini-embedding-001", tags=("Python",), text="chunk"):
    await store.collection.insert_one(
        {
            "text": text,
            "chunk_type": "syllabus_note",
            "tags": list(tags),
            "source_id": f"src-{text}",
            "vector": list(vector),
            "embed_model": model,
            "embed_dim": len(vector),
        }
    )


@pytest.mark.asyncio
async def test_retrieve_accepts_chunks_from_the_same_model(mock_mongo, monkeypatch):
    from app.core.config import get_settings

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "EMBEDDING_MODEL", "model-a", raising=False)

    store = KnowledgeStore(mock_mongo)
    v = [1.0, 0.0, 0.0]
    await _chunk(store, vector=v, model="model-a", text="same-model")

    # retrieve() calls the embedding provider; stub just that step.
    async def fake_embed(_texts):
        return [v]

    monkeypatch.setattr("app.ml.rag.knowledge_store.llm_client.embed_async", fake_embed)

    hits = await store.retrieve(query_skills=["Python"], chunk_types=["syllabus_note"])
    assert len(hits) == 1
    assert hits[0].text == "same-model"
    assert hits[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_retrieve_skips_chunks_from_a_different_model(mock_mongo, monkeypatch):
    """The dangerous case: same dimension, different model. Must NOT be
    compared, because the resulting score would be meaningless."""
    from app.core.config import get_settings

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "EMBEDDING_MODEL", "model-b", raising=False)

    store = KnowledgeStore(mock_mongo)
    v = [1.0, 0.0, 0.0]
    # Stored under model-a, but we are querying with model-b. Same dim, so
    # without this guard np.dot would happily return a clean 1.0.
    await _chunk(store, vector=v, model="model-a", text="foreign-model")

    async def fake_embed(_texts):
        return [v]

    monkeypatch.setattr("app.ml.rag.knowledge_store.llm_client.embed_async", fake_embed)

    hits = await store.retrieve(query_skills=["Python"], chunk_types=["syllabus_note"])
    assert hits == [], "must refuse to score a chunk embedded by a different model"


@pytest.mark.asyncio
async def test_retrieve_skips_legacy_chunks_with_no_model_stamp(mock_mongo, monkeypatch):
    """Chunks ingested before embed_model existed have no stamp. They are
    treated as foreign rather than trusted."""
    from app.core.config import get_settings

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "EMBEDDING_MODEL", "model-a", raising=False)

    store = KnowledgeStore(mock_mongo)
    await store.collection.insert_one(
        {
            "text": "legacy",
            "chunk_type": "syllabus_note",
            "tags": ["Python"],
            "source_id": "legacy",
            "vector": [1.0, 0.0, 0.0],
        }
    )

    async def fake_embed(_texts):
        return [[1.0, 0.0, 0.0]]

    monkeypatch.setattr("app.ml.rag.knowledge_store.llm_client.embed_async", fake_embed)

    hits = await store.retrieve(query_skills=["Python"], chunk_types=["syllabus_note"])
    assert hits == [], "unverifiable legacy chunk must not be compared"


@pytest.mark.asyncio
async def test_retrieve_skips_dimension_mismatches(mock_mongo, monkeypatch):
    """Same model recorded, but the stored vector's length disagrees with the
    query vector. Guarded separately so a corrupted/partial vector cannot
    reach np.dot and crash retrieval."""
    from app.core.config import get_settings

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "EMBEDDING_MODEL", "model-a", raising=False)

    store = KnowledgeStore(mock_mongo)
    await _chunk(store, vector=[1.0, 0.0, 0.0, 0.0, 0.0], model="model-a", text="wrong-dim")

    async def fake_embed(_texts):
        return [[1.0, 0.0, 0.0]]

    monkeypatch.setattr("app.ml.rag.knowledge_store.llm_client.embed_async", fake_embed)

    hits = await store.retrieve(query_skills=["Python"], chunk_types=["syllabus_note"])
    assert hits == [], "dimension mismatch must be skipped, not crash"


@pytest.mark.asyncio
async def test_retrieve_keeps_good_chunks_and_drops_only_foreign(mock_mongo, monkeypatch):
    """Mixed store: only the compatible chunk survives."""
    from app.core.config import get_settings

    settings_obj = get_settings()
    monkeypatch.setattr(settings_obj, "EMBEDDING_MODEL", "model-a", raising=False)

    store = KnowledgeStore(mock_mongo)
    await _chunk(store, vector=[1.0, 0.0, 0.0], model="model-a", text="keep")
    await _chunk(store, vector=[0.0, 1.0, 0.0], model="model-legacy", text="drop")

    async def fake_embed(_texts):
        return [[1.0, 0.0, 0.0]]

    monkeypatch.setattr("app.ml.rag.knowledge_store.llm_client.embed_async", fake_embed)

    hits = await store.retrieve(query_skills=["Python"], chunk_types=["syllabus_note"])
    assert [h.text for h in hits] == ["keep"]
    # sanity: the cosine of the dropped one would have been 0.0 — a number
    # that looks like a real "no relevance" score rather than a model clash.
    assert float(np.dot([1, 0, 0], [0, 1, 0])) == 0.0