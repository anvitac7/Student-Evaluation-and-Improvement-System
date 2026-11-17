"""
Tests for middleware ordering.

Regression: RequestIdMiddleware was originally registered before
CORSMiddleware. Starlette's add_middleware PREPENDS to the stack, so the
last-registered middleware is outermost — which meant CORSMiddleware sat
outside the request-id layer and every CORS preflight short-circuited
without a correlation id. Preflight failures are precisely the traffic you
most want to trace when a browser reports a CORS error.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.request_context import REQUEST_ID_HEADER
from app.main import app


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_cors_preflight_gets_a_request_id(mock_mongo):
    """An OPTIONS preflight must still be traceable. This is the request that
    was silently untraceable when the ordering was wrong."""
    async with _client() as ac:
        r = await ac.options(
            "/api/v1/insights/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert REQUEST_ID_HEADER in r.headers, "preflight response has no request id"
    assert r.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_cors_preflight_echoes_inbound_request_id(mock_mongo):
    async with _client() as ac:
        r = await ac.options(
            "/api/v1/insights/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                REQUEST_ID_HEADER: "preflight-trace-1",
            },
        )
    assert r.headers[REQUEST_ID_HEADER] == "preflight-trace-1"


@pytest.mark.asyncio
async def test_cors_headers_still_present(mock_mongo):
    """Reordering must not have broken CORS itself."""
    async with _client() as ac:
        r = await ac.options(
            "/api/v1/insights/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-methods"), "CORS headers lost"


@pytest.mark.asyncio
async def test_actual_request_still_works_and_is_correlated(mock_mongo):
    async with _client() as ac:
        r = await ac.get(
            "/api/v1/health",
            headers={"Origin": "http://localhost:3000", REQUEST_ID_HEADER: "real-req"},
        )
    assert r.status_code == 200
    assert r.headers[REQUEST_ID_HEADER] == "real-req"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"