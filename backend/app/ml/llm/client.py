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
    LLM_THINKING_MODE_NARRATIVE / LLM_THINKING_MODE_EXTRACTION
    LLM_REQUEST_TIMEOUT_SECONDS / LLM_MAX_RETRIES
    EMBEDDING_PROVIDER / EMBEDDING_MODEL / EMBEDDING_BASE_URL
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError

from app.core.config import get_settings
from app.ml.llm.exceptions import LLMMalformedResponseError, LLMUnavailableError

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
    """

    # ------------------------------------------------------------------
    # 1. Free-text generation
    # ------------------------------------------------------------------
    def generate_text(self, system_prompt: str, user_prompt: str, *, thinking: bool = True) -> str:
        s = get_settings()
        last_err: Exception | None = None

        for provider in _providers_in_order():
            try:
                return self._call_chat(provider, system_prompt, user_prompt, thinking=thinking, json_mode=False)
            except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as e:
                logger.warning("LLM provider %s failed for generate_text: %s", provider.name, e)
                last_err = e
                continue

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
            for attempt in range(s.LLM_MAX_RETRIES + 1):
                try:
                    raw = self._call_chat(
                        provider, full_system, user_prompt, thinking=False, json_mode=True
                    )
                    return _parse_json_loose(raw)
                except LLMMalformedResponseError as e:
                    logger.warning(
                        "Malformed JSON from %s (attempt %d): %s", provider.name, attempt, e
                    )
                    last_err = e
                    continue
                except (APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as e:
                    logger.warning("LLM provider %s failed for generate_json: %s", provider.name, e)
                    last_err = e
                    break  # don't retry a dead provider, move to fallback

        raise LLMUnavailableError(f"All LLM providers unavailable/malformed for JSON generation: {last_err}")

    # ------------------------------------------------------------------
    # 3. Embeddings — separate small local model, not Qwen/Nemotron
    # ------------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        s = get_settings()
        if not texts:
            return []

        try:
            resp = httpx.post(
                f"{s.EMBEDDING_BASE_URL}/api/embed",
                json={"model": s.EMBEDDING_MODEL, "input": texts},
                timeout=s.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["embeddings"]
        except (httpx.HTTPError, KeyError) as e:
            logger.warning("Embedding provider failed: %s", e)
            raise LLMUnavailableError(f"Embedding model unavailable: {e}")

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _call_chat(
        self, provider: ProviderConfig, system_prompt: str, user_prompt: str, *, thinking: bool, json_mode: bool
    ) -> str:
        client = _client_for(provider)

        extra_body: dict[str, Any] = {}
        # Qwen3's hybrid thinking-mode toggle. Nemotron/other providers
        # silently ignore unknown extra_body fields via OpenAI SDK's
        # passthrough, but we only send it for qwen-flavoured models to be
        # safe and explicit.
        if "qwen" in provider.model.lower():
            extra_body["enable_thinking"] = thinking

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
        return content


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