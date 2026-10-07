"""
PHASE A — app/ml/llm/client.py

Single reusable, model-agnostic LLM client. Every other phase (B, C, D)
imports THIS module and never talks to an HTTP endpoint directly.

Design:
  - Nemotron (NVIDIA NIM), Qwen via OpenRouter, and Qwen via local Ollama
    are ALL OpenAI-compatible `/chat/completions` APIs. One thin wrapper
    around the `openai` SDK, pointed at different base_url/api_key/model
    per provider, covers all three — provider is just a config value.
  - Primary provider is tried first; on failure (timeout, connection
    error, malformed JSON after retries) it falls back to the secondary
    provider; if BOTH fail, raises LLMUnavailableError so the caller can
    degrade (regex fallback / no-narrative placeholder / 503), matching
    the existing `MatchingModelsUnavailable` pattern in this codebase.
  - Embeddings are a SEPARATE, smaller local model (nomic-embed-text via
    Ollama) — Qwen/Nemotron are never used for embeddings.

Install:
    pip install openai httpx

Env vars consumed (see config_additions.py):
    LLM_PRIMARY_PROVIDER / LLM_PRIMARY_MODEL / LLM_PRIMARY_BASE_URL / LLM_PRIMARY_API_KEY
    LLM_FALLBACK_PROVIDER / LLM_FALLBACK_MODEL / LLM_FALLBACK_BASE_URL / LLM_FALLBACK_API_KEY
    LLM_USE_LOCAL_OLLAMA / OLLAMA_BASE_URL / OLLAMA_MODEL
    LLM_REQUEST_TIMEOUT_SECONDS / LLM_MAX_RETRIES / LLM_RETRY_BACKOFF_SECONDS
    EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_BASE_URL
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anyio
import time

import httpx
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

from app.core.config import get_settings
from app.ml.llm.exceptions import LLMMalformedResponseError, LLMUnavailableError
from app.ml.llm.metrics import llm_metrics

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    name: str
    model: str
    base_url: str
    api_key: str


def _providers_in_order() -> list[ProviderConfig]:
    s = get_settings()

    if s.LLM_USE_LOCAL_OLLAMA:
        # Dev mode: single local provider, no fallback needed (it's already
        # the cheapest/simplest option).
        return [ProviderConfig("ollama", s.OLLAMA_MODEL, f"{s.OLLAMA_BASE_URL}/v1", "ollama")]

    return [
        ProviderConfig(s.LLM_PRIMARY_PROVIDER, s.LLM_PRIMARY_MODEL, s.LLM_PRIMARY_BASE_URL, s.LLM_PRIMARY_API_KEY),
        ProviderConfig(s.LLM_FALLBACK_PROVIDER, s.LLM_FALLBACK_MODEL, s.LLM_FALLBACK_BASE_URL, s.LLM_FALLBACK_API_KEY),
    ]


def _client_for(p: ProviderConfig) -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=p.base_url, api_key=p.api_key or "not-needed", timeout=s.LLM_REQUEST_TIMEOUT_SECONDS)


class LLMClient:
    """
    Three capabilities exposed to the rest of the app:
      1. generate_text()      — free-text narratives (gap analysis, JD explain)
      2. generate_json()      — structured JSON (skill extraction)
      3. embed()               — vector embeddings (RAG retrieval)

    Each has an `*_async` counterpart. USE THE ASYNC ONES from any `async def`.

    Why: all three are synchronous (the `openai` SDK and `httpx` blocking
    calls), and every caller lives inside an `async def` request handler.
    Calling one directly freezes the entire event loop for the full duration
    of the network round-trip — measured at 35s on a real Gemini call,
    during which a 50ms-interval heartbeat coroutine accumulated ZERO
    ticks. Every other request in the process stalls behind it, and the
    Next.js dev proxy reports the symptom as `[Error: socket hang up]
    { code: 'ECONNRESET' }` rather than anything pointing at the real cause.

    The `*_async` wrappers hand the blocking work to a worker thread via
    `anyio.to_thread.run_sync`, so the loop stays free to serve other
    requests while the LLM thinks. The blocking methods are kept because
    they're still correct from a plain sync context (scripts, tests), but
    nothing in an async path should call them directly.
    """

    # ------------------------------------------------------------------
    # async wrappers — the correct entry point from async code
    # ------------------------------------------------------------------
    async def generate_text_async(
        self, system_prompt: str, user_prompt: str, *, thinking: bool = True
    ) -> str:
        return await anyio.to_thread.run_sync(
            lambda: self.generate_text(system_prompt, user_prompt, thinking=thinking)
        )

    async def generate_json_async(
        self, system_prompt: str, user_prompt: str, *, schema_hint: str
    ) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(
            lambda: self.generate_json(system_prompt, user_prompt, schema_hint=schema_hint)
        )

    async def embed_async(self, texts: list[str]) -> list[list[float]]:
        return await anyio.to_thread.run_sync(lambda: self.embed(texts))

    # ------------------------------------------------------------------
    # 1. Free-text generation
    # ------------------------------------------------------------------
    def generate_text(self, system_prompt: str, user_prompt: str, *, thinking: bool = True) -> str:
        s = get_settings()
        last_err: Exception | None = None

        for provider in _providers_in_order():
            attempts = s.LLM_MAX_RETRIES + 1
            for attempt in range(attempts):
                started = time.perf_counter()
                try:
                    text, usage = self._call_chat(
                        provider, system_prompt, user_prompt, thinking=thinking, json_mode=False
                    )
                except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as e:
                    last_err = e
                    latency_ms = (time.perf_counter() - started) * 1000
                    llm_metrics.record_call(
                        provider.name,
                        latency_ms=latency_ms,
                        failed=True,
                        retries=attempt,
                        error=str(e),
                    )
                    logger.warning(
                        "llm.chat provider=%s model=%s status=fail latency_ms=%.0f attempt=%d/%d error=%s",
                        provider.name, provider.model, latency_ms, attempt + 1, attempts, e,
                    )
                    if self._is_retryable(e) and attempt < attempts - 1:
                        delay = s.LLM_RETRY_BACKOFF_SECONDS * (2**attempt)
                        time.sleep(delay)
                        continue
                    break  # exhausted, or not retryable -> try next provider

                latency_ms = (time.perf_counter() - started) * 1000
                llm_metrics.record_call(
                    provider.name,
                    latency_ms=latency_ms,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    retries=attempt,
                )
                logger.info(
                    "llm.chat provider=%s model=%s status=ok latency_ms=%.0f attempt=%d "
                    "prompt_tokens=%d completion_tokens=%d",
                    provider.name, provider.model, latency_ms, attempt + 1,
                    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                )
                return text

        raise LLMUnavailableError(f"All LLM providers unavailable for text generation: {last_err}")

    # ------------------------------------------------------------------
    # 2. Structured JSON generation
    # ------------------------------------------------------------------
    def generate_json(self, system_prompt: str, user_prompt: str, *, schema_hint: str) -> dict[str, Any]:
        """
        `schema_hint` is a short human-readable description of the expected
        JSON shape, appended to the system prompt. We don't rely on any
        provider-specific "JSON mode" flag (Nemotron/OpenRouter support
        vary) — instead we ask explicitly and parse defensively, retrying
        once on malformed output before giving up on that provider.
        """
        s = get_settings()
        full_system = (
            f"{system_prompt}\n\n"
            f"Respond with ONLY valid JSON matching this shape, no markdown "
            f"fences, no preamble, no commentary:\n{schema_hint}"
        )

        last_err: Exception | None = None
        for provider in _providers_in_order():
            attempts = s.LLM_MAX_RETRIES + 1
            for attempt in range(attempts):
                started = time.perf_counter()
                try:
                    raw, usage = self._call_chat(
                        provider, full_system, user_prompt, thinking=False, json_mode=True
                    )
                    parsed = _parse_json_loose(raw)
                except LLMMalformedResponseError as e:
                    latency_ms = (time.perf_counter() - started) * 1000
                    llm_metrics.record_call(
                        provider.name, latency_ms=latency_ms, failed=True,
                        retries=attempt, error=str(e),
                    )
                    logger.warning(
                        "llm.json provider=%s model=%s status=malformed latency_ms=%.0f "
                        "attempt=%d/%d error=%s",
                        provider.name, provider.model, latency_ms, attempt + 1, attempts, e,
                    )
                    last_err = e
                    continue
                except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as e:
                    last_err = e
                    latency_ms = (time.perf_counter() - started) * 1000
                    llm_metrics.record_call(
                        provider.name, latency_ms=latency_ms, failed=True,
                        retries=attempt, error=str(e),
                    )
                    logger.warning(
                        "llm.chat provider=%s model=%s status=fail latency_ms=%.0f attempt=%d/%d error=%s",
                        provider.name, provider.model, latency_ms, attempt + 1, attempts, e,
                    )
                    if self._is_retryable(e) and attempt < attempts - 1:
                        delay = s.LLM_RETRY_BACKOFF_SECONDS * (2**attempt)
                        time.sleep(delay)
                        continue
                    break  # exhausted, or not retryable -> next provider

                latency_ms = (time.perf_counter() - started) * 1000
                llm_metrics.record_call(
                    provider.name,
                    latency_ms=latency_ms,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    retries=attempt,
                )
                logger.info(
                    "llm.json provider=%s model=%s status=ok latency_ms=%.0f attempt=%d "
                    "prompt_tokens=%d completion_tokens=%d",
                    provider.name, provider.model, latency_ms, attempt + 1,
                    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                )
                return parsed

        raise LLMUnavailableError(f"All LLM providers unavailable/malformed for JSON generation: {last_err}")

    # ------------------------------------------------------------------
    # 3. Embeddings — separate small local model, not Qwen/Nemotron
    # ------------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        if not texts:
            return []

        started = time.perf_counter()
        try:
            if s.EMBEDDING_PROVIDER == "openai":
                vectors = self._embed_openai_compatible(texts)
            else:
                vectors = self._embed_ollama(texts)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            llm_metrics.record_embed(failed=True)
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "llm.embed provider=%s model=%s status=fail latency_ms=%.0f error=%s",
                s.EMBEDDING_PROVIDER, s.EMBEDDING_MODEL, latency_ms, e,
            )
            raise LLMUnavailableError(f"Embedding model unavailable: {e}")

        llm_metrics.record_embed()
        latency_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "llm.embed provider=%s model=%s status=ok latency_ms=%.0f texts=%d dim=%d",
            s.EMBEDDING_PROVIDER, s.EMBEDDING_MODEL, latency_ms,
            len(texts), len(vectors[0]) if vectors else 0,
        )
        return vectors

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        """Ollama's native /api/embed shape — still supported, and still the
        only option that needs no API key and no network."""
        s = get_settings()
        return self._post_with_retry(
            lambda: httpx.post(
                f"{s.EMBEDDING_BASE_URL}/api/embed",
                json={"model": s.EMBEDDING_MODEL, "input": texts},
                timeout=s.LLM_REQUEST_TIMEOUT_SECONDS,
            ),
            provider_name="ollama",
        ).json()["embeddings"]

    def _embed_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        """Any OpenAI-compatible /embeddings endpoint. Gemini's compatibility
        layer uses exactly this shape, so one key covers chat AND embeddings
        and there is no need to install/run Ollama locally."""
        s = get_settings()
        headers = {"Content-Type": "application/json"}
        if s.EMBEDDING_API_KEY:
            headers["Authorization"] = f"Bearer {s.EMBEDDING_API_KEY}"

        resp = self._post_with_retry(
            lambda: httpx.post(
                f"{s.EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
                json={"model": s.EMBEDDING_MODEL, "input": texts},
                headers=headers,
                timeout=s.LLM_REQUEST_TIMEOUT_SECONDS,
            ),
            provider_name="embeddings",
        )
        # OpenAI shape: {"data": [{"embedding": [...]}, ...]}. Ordered by
        # the "index" field rather than trusting response order.
        rows = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
        return [row["embedding"] for row in rows]

    @staticmethod
    def _post_with_retry(post, *, provider_name: str):
        """Shared retry wrapper for the raw-httpx embedding calls, which
        bypass the openai SDK and so bypass its own retry handling."""
        s = get_settings()
        attempts = s.LLM_MAX_RETRIES + 1
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = post()
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError,) as e:
                last_err = e
                if LLMClient._is_retryable(e) and attempt < attempts - 1:
                    delay = s.LLM_RETRY_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "llm.embed.retry provider=%s attempt=%d/%d backoff_s=%.1f error=%s",
                        provider_name, attempt + 1, attempts, delay, e,
                    )
                    time.sleep(delay)
                    continue
                break
        raise last_err  # type: ignore[misc]

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """429/5xx/connection errors are worth another go; 4xx auth/validation
        errors are not, and retrying them just burns quota and time.

        The previous code only retried malformed JSON, so a transient 429 or
        503 (both of which real providers return routinely under load)
        aborted the whole request on the first occurrence.
        """
        if isinstance(exc, (APIConnectionError, APITimeoutError, httpx.HTTPError)):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code == 429 or exc.status_code >= 500
        return False

    def _call_chat(
        self, provider: ProviderConfig, system_prompt: str, user_prompt: str, *, thinking: bool, json_mode: bool
    ) -> tuple[str, dict[str, int]]:
        """Returns (content, usage).

        `usage` is best-effort: the OpenAI-compatible shape puts token counts
        on `response.usage`, but some providers omit it entirely or rename the
        fields, so every access here is defensive and callers must tolerate
        an empty dict. Missing usage is reported as zeros rather than an
        exception — losing a token count is never worth failing a request.
        """
        client = _client_for(provider)

        extra_body: dict[str, Any] = {}
        # Reasoning-mode toggle. Each provider family spells this differently,
        # and sending the wrong key is silently ignored — so we send only the
        # one that matches, rather than assuming a universal flag:
        #   qwen*  -> enable_thinking (OpenRouter/Ollama qwen3)
        #   gemini -> reasoning_effort  (v1beta/openai compatibility layer)
        # Anything else gets nothing, because a wrong key would be ignored
        # anyway and this used to mislead readers into thinking `thinking`
        # did something on every provider.
        model_l = provider.model.lower()
        if "qwen" in model_l:
            extra_body["enable_thinking"] = thinking
        elif "gemini" in model_l:
            extra_body["reasoning_effort"] = "medium" if thinking else "none"

        response = client.chat.completions.create(
            model=provider.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2 if json_mode else 0.6,
            extra_body=extra_body or None,
        )
        content = response.choices[0].message.content or ""
        if json_mode and not content.strip():
            raise LLMMalformedResponseError("Empty response body")

        usage: dict[str, int] = {}
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage = {
                "prompt_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
            }
        return content, usage


def _parse_json_loose(raw: str) -> dict[str, Any]:
    """Strips ```json fences etc. before parsing — models frequently wrap
    JSON in markdown even when told not to."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMMalformedResponseError(f"Could not parse JSON: {e}. Raw: {raw[:200]}")


# Module-level singleton — cheap to construct (no model loading, unlike
# MatchingEngine), so a plain singleton is fine, no lazy-load ceremony needed.
llm_client = LLMClient()