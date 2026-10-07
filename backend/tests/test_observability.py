"""
Tests for request correlation IDs and LLM observability.

These exist because debugging a production-shaped bug (a synchronous LLM call
freezing the event loop) was genuinely painful: interleaved log lines from
concurrent requests could not be attributed to a request, and there was no
signal distinguishing "no LLM configured" from "provider failing" from "cache
stale".
"""
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.request_context import (
    REQUEST_ID_HEADER,
    RequestContextFilter,
    configure_logging,
    get_request_id,
)
from app.main import app
from app.ml.llm.metrics import LLMMetrics, llm_metrics


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# request ids
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_response_carries_a_generated_request_id(mock_mongo):
    async with _client() as ac:
        r = await ac.get("/api/v1/health")
    assert r.status_code == 200
    assert REQUEST_ID_HEADER in r.headers
    assert r.headers[REQUEST_ID_HEADER], "request id must not be empty"


@pytest.mark.asyncio
async def test_inbound_request_id_is_echoed_not_overwritten(mock_mongo):
    """Lets a frontend or proxy stitch one trace across services."""
    async with _client() as ac:
        r = await ac.get("/api/v1/health", headers={REQUEST_ID_HEADER: "upstream-abc123"})
    assert r.headers[REQUEST_ID_HEADER] == "upstream-abc123"


@pytest.mark.asyncio
async def test_access_log_records_real_status_code(mock_mongo, caplog):
    """Regression: the access log once printed "-> ?" for every line because
    raw ASGI never sets scope["status"]. Status must come off the response
    message instead."""
    with caplog.at_level(logging.INFO, logger="app.access"):
        async with _client() as ac:
            await ac.get("/api/v1/health")

    access_lines = [r for r in caplog.records if r.name == "app.access"]
    assert access_lines, "no access log line emitted"
    msg = access_lines[-1].getMessage()
    assert "/api/v1/health" in msg
    assert "-> ?" not in msg, f"status missing from access log: {msg!r}"
    assert "200" in msg


@pytest.mark.asyncio
async def test_access_log_carries_the_request_id(mock_mongo, caplog):
    """Regression: the access log was emitted AFTER the contextvar was reset,
    so every line showed the placeholder "-" and was uncorrelated — which
    defeats the purpose of having request ids at all."""
    with caplog.at_level(logging.INFO, logger="app.access"):
        async with _client() as ac:
            r = await ac.get("/api/v1/health", headers={REQUEST_ID_HEADER: "trace-xyz"})

    access_lines = [rec for rec in caplog.records if rec.name == "app.access"]
    assert access_lines, "no access log line emitted"
    record = access_lines[-1]
    assert getattr(record, "request_id", "-") == "trace-xyz", (
        "access log must be correlated to its request id, not the '-' placeholder"
    )
    assert record.request_id == r.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_two_requests_get_distinct_ids(mock_mongo):
    async with _client() as ac:
        a = await ac.get("/api/v1/health")
        b = await ac.get("/api/v1/health")
    assert a.headers[REQUEST_ID_HEADER] != b.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_inbound_request_id_is_sanitised(mock_mongo):
    """Newlines in an inbound header would otherwise let a caller forge
    extra log lines. The defence is that the value can never span lines —
    the remaining text is inert once embedded in a single log line."""
    hostile = "abc\nINFO fake-log-line-definitely-not-real"
    async with _client() as ac:
        r = await ac.get("/api/v1/health", headers={REQUEST_ID_HEADER: hostile})
    got = r.headers[REQUEST_ID_HEADER]
    assert "\n" not in got and "\r" not in got, "newline would allow log-line forgery"
    assert len(got) <= 64


@pytest.mark.asyncio
async def test_long_inbound_request_id_is_truncated(mock_mongo):
    async with _client() as ac:
        r = await ac.get("/api/v1/health", headers={REQUEST_ID_HEADER: "x" * 500})
    assert len(r.headers[REQUEST_ID_HEADER]) <= 64


def test_request_id_filter_injects_attribute():
    """Every record gets a request_id, including from third-party loggers
    that know nothing about this module. The record is built WITHOUT the
    attribute so the filter is genuinely the thing adding it."""
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    assert not hasattr(rec, "request_id")
    RequestContextFilter().filter(rec)
    assert rec.request_id == get_request_id()


def test_filter_does_not_clobber_existing_id():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    rec.request_id = "preset"
    RequestContextFilter().filter(rec)
    assert rec.request_id == "preset"


def test_configure_logging_is_idempotent():
    """Calling twice must replace handlers, not stack them — otherwise a
    test fixture plus main() would double every log line."""
    root = logging.getLogger()
    before = len(root.handlers)
    configure_logging()
    configure_logging()
    assert len(root.handlers) == 1, "handlers stacked"
    assert before >= 0


# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------
def test_metrics_counts_calls_and_failures():
    m = LLMMetrics()
    m.record_call("gemini", latency_ms=100, prompt_tokens=10, completion_tokens=5)
    m.record_call("gemini", latency_ms=300, prompt_tokens=20, completion_tokens=7)
    m.record_call("gemini", latency_ms=50, failed=True, error="boom")

    snap = m.snapshot()["providers"]["gemini"]
    assert snap["calls"] == 3
    assert snap["failures"] == 1
    assert snap["prompt_tokens"] == 30
    assert snap["completion_tokens"] == 12
    assert snap["total_tokens"] == 42
    assert snap["last_error"].startswith("boom")


def test_metrics_avg_latency():
    m = LLMMetrics()
    m.record_call("p", latency_ms=100)
    m.record_call("p", latency_ms=300)
    assert m.snapshot()["providers"]["p"]["avg_latency_ms"] == 200.0


def test_metrics_cache_hit_rate():
    m = LLMMetrics()
    for _ in range(3):
        m.record_cache(hit=True)
    m.record_cache(hit=False)
    assert m.snapshot()["narrative_cache"]["hits"] == 3
    assert m.snapshot()["narrative_cache"]["misses"] == 1
    assert m.snapshot()["narrative_cache"]["hit_rate_pct"] == 75.0


def test_metrics_cache_hit_rate_none_when_unused():
    """Must be null, not 0.0 — "never called" and "always missed" are
    different states and a UI should be able to tell them apart."""
    assert LLMMetrics().snapshot()["narrative_cache"]["hit_rate_pct"] is None


def test_metrics_reset():
    m = LLMMetrics()
    m.record_call("p", latency_ms=1)
    m.record_embed()
    m.record_cache(hit=True)
    m.reset()
    snap = m.snapshot()
    assert snap["providers"] == {}
    assert snap["embeddings"]["calls"] == 0
    assert snap["narrative_cache"]["hits"] == 0


def test_metrics_embedding_failures_tracked():
    m = LLMMetrics()
    m.record_embed()
    m.record_embed(failed=True)
    assert m.snapshot()["embeddings"] == {"calls": 2, "failures": 1}


# ---------------------------------------------------------------------------
# observability endpoint
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_observability_requires_auth(client):
    r = await client.get("/api/v1/admin/observability/llm")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_observability_forbidden_for_student(client):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": "obs.student@college.edu",
            "password": "Student@12345",
            "name": "Obs Student",
            "department": "Computer Science",
            "batch_year": 2026,
        },
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "obs.student@college.edu", "password": "Student@12345"},
        )
    ).json()["access_token"]
    r = await client.get(
        "/api/v1/admin/observability/llm", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_observability_returns_snapshot_for_admin(client, mock_mongo):
    from app.models.user import AdminRegisterRequest
    from app.services.auth_service import AuthService

    svc = AuthService(mock_mongo)
    await svc.register_admin(
        AdminRegisterRequest(
            email="obs.admin@college.edu", password="Admin@12345", name="Obs Admin"
        )
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "obs.admin@college.edu", "password": "Admin@12345"},
        )
    ).json()["access_token"]

    llm_metrics.record_call("gemini", latency_ms=42, prompt_tokens=7, completion_tokens=3)
    llm_metrics.record_cache(hit=True)

    r = await client.get(
        "/api/v1/admin/observability/llm", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body and "embeddings" in body and "narrative_cache" in body
    assert body["providers"]["gemini"]["calls"] >= 1
    assert body["narrative_cache"]["hits"] >= 1