"""
Per-request correlation IDs.

Motivation (learned the hard way): with three requests in flight at once —
which is the normal case for any page that fans out to several endpoints —
the interleaved log lines are impossible to attribute. During debugging of
the synchronous-LLM event-loop stall, a 500 in one endpoint produced a
traceback that looked like it belonged to a different request entirely, and
the only way to tell requests apart was to guess from timestamps.

This module provides:

  * `REQUEST_ID_HEADER` — the inbound/outbound header name.
  * `new_request_id()` / `get_request_id()` — the contextvar holding the
    current request's ID.
  * `RequestContextFilter` — a logging filter that injects `request_id` onto
    every LogRecord, so ANY logger in the app (including third-party ones)
    automatically carries it with no per-call-site changes.
  * `RequestIdMiddleware` — reads or mints the ID, binds it for the request,
    echoes it on the response, and logs a one-line access record.

Uses a ContextVar rather than thread-locals because the async LLM calls are
dispatched to worker threads via `anyio.to_thread.run_sync`; contextvars are
copied into the thread context that asyncio/anyio sets up, so a log line
emitted from inside a blocking LLM call still resolves the right request.
Thread-locals would NOT propagate that way.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers

REQUEST_ID_HEADER = "X-Request-ID"

# "-" is the conventional "no request in scope" value (e.g. logs emitted at
# startup/shutdown, or from a background thread with no context copied).
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    return _request_id.get()


class RequestContextFilter(logging.Filter):
    """Attach the current request_id to every log record.

    Applied to the ROOT logger's handlers rather than to individual loggers,
    so uvicorn/slowapi/pymongo/httpx records are covered too, not just this
    app's own `logging.getLogger(__name__)` calls.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()  # type: ignore[attr-defined]
        return True


class RequestIdMiddleware:
    """Bind a request ID for the duration of each request and log an
    access record.

    Implemented as raw ASGI rather than BaseHTTPMiddleware on purpose:
    BaseHTTPMiddleware runs the downstream app in a separate task, which
    makes contextvar propagation to the endpoint unreliable across Starlette
    versions. At the ASGI level the set/reset brackets the endpoint call
    exactly, so every log line — including ones emitted deep inside a
    service — resolves the correct ID.

    An inbound `X-Request-ID` is honoured rather than overwritten, so a
    frontend or upstream proxy can stitch a trace across services. Untrusted
    inbound values are truncated and stripped of newlines to keep log lines
    bounded and prevent log injection.
    """

    def __init__(self, app, max_id_len: int = 64):
        self.app = app
        self.max_id_len = max_id_len

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        inbound = headers.get(REQUEST_ID_HEADER, "")
        request_id = (
            inbound.strip().replace("\n", "").replace("\r", "")[: self.max_id_len]
            if inbound.strip()
            else new_request_id()
        )

        status_holder: dict[str, object] = {"status": None}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Raw ASGI never populates scope["status"], so capture it here
                # for the access log rather than logging "?" for every line.
                status_holder["status"] = message.get("status", "?")
                message.setdefault("headers", [])
                message["headers"].append(
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode())
                )
            await send(message)

        token = _request_id.set(request_id)
        started = time.perf_counter()
        access = logging.getLogger("app.access")
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            access.exception(
                "%s %s -> unhandled exception after %.0fms",
                scope.get("method"),
                scope.get("path"),
                (time.perf_counter() - started) * 1000,
            )
            raise
        finally:
            # Log BEFORE resetting: after reset the contextvar falls back to
            # "-" and every access line would be uncorrelated, which defeats
            # the entire point of the middleware.
            access.info(
                "%s %s -> %s in %.0fms",
                scope.get("method"),
                scope.get("path"),
                status_holder["status"] if status_holder["status"] is not None else "?",
                (time.perf_counter() - started) * 1000,
            )
            _request_id.reset(token)


def configure_logging(level: int = logging.INFO, fmt: str | None = None) -> None:
    """Install the request-id-aware formatter on the root handlers.

    Idempotent: repeated calls replace the handler's formatter rather than
    stacking handlers, so calling this from both main() and a test fixture
    cannot produce duplicate log lines.
    """
    if fmt is None:
        fmt = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; route them through ours so its
    # access log carries a request id too.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True