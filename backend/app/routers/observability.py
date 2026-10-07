"""
Developer-facing observability endpoint.

Exposes the in-process LLM metrics from app.ml.llm.metrics. Intended for
local debugging and quick manual checks ("is the LLM actually being called, is
it succeeding, is the cache working?").

Access is restricted to ADMIN. There is deliberately no student/TPO route for
it: the payload reveals provider names, error strings, and usage volumes,
which is operational information rather than anything a student should see.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import CurrentUser, require_role
from app.ml.llm.metrics import llm_metrics

router = APIRouter(prefix="/admin/observability", tags=["Observability"])


class ProviderMetricsOut(BaseModel):
    calls: int
    failures: int
    retries: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    avg_latency_ms: float
    last_error: str | None


class EmbeddingMetricsOut(BaseModel):
    calls: int
    failures: int


class CacheMetricsOut(BaseModel):
    hits: int
    misses: int
    hit_rate_pct: float | None


class ObservabilityOut(BaseModel):
    providers: dict[str, ProviderMetricsOut]
    embeddings: EmbeddingMetricsOut
    narrative_cache: CacheMetricsOut


@router.get("/llm", response_model=ObservabilityOut)
async def llm_observability(
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """LLM usage snapshot for this process. Resets on restart — see the
    metrics module docstring for why that is acceptable here."""
    snap = llm_metrics.snapshot()
    return ObservabilityOut(
        providers={
            name: ProviderMetricsOut(**stats) for name, stats in snap["providers"].items()
        },
        embeddings=EmbeddingMetricsOut(**snap["embeddings"]),
        narrative_cache=CacheMetricsOut(**snap["narrative_cache"]),
    )