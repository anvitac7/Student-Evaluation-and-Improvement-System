"""
In-process metrics for LLM usage.

Why this exists: the LLM layer talks to a metered, rate-limited third-party
API, and there was previously no way to see what it was spending or how often
it was succeeding. When narratives came back `null` there was no signal
distinguishing "no API key configured" from "provider is erroring" from
"cache is stale" — you had to read interleaved log lines and guess.

Deliberately dependency-free and in-memory. This is a development
observability aid, not a production metrics backend: it is per-process, so
it resets on restart and does not aggregate across workers. Anything that
needs durability should read the structured `app.llm` log lines instead,
which are emitted per call and carry the request id.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ProviderStats:
    calls: int = 0
    failures: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_latency_ms: float = 0.0
    last_error: str | None = None
    last_called_at: float | None = None

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.calls if self.calls else 0.0

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "retries": self.retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_error": self.last_error,
        }


@dataclass
class LLMMetrics:
    """Thread-safe because the blocking LLM calls run in worker threads."""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    providers: dict[str, ProviderStats] = field(
        default_factory=lambda: defaultdict(ProviderStats), repr=False
    )
    embed_calls: int = 0
    embed_failures: int = 0
    # cache_hits / cache_misses are incremented by callers that cache
    # (currently the student-insights narrative cache).
    cache_hits: int = 0
    cache_misses: int = 0

    def record_call(
        self,
        provider: str,
        *,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        failed: bool = False,
        retries: int = 0,
        error: str | None = None,
    ) -> None:
        with self._lock:
            st = self.providers[provider]
            st.calls += 1
            st.retries += retries
            st.prompt_tokens += prompt_tokens
            st.completion_tokens += completion_tokens
            st.total_latency_ms += latency_ms
            st.last_called_at = time.time()
            if failed:
                st.failures += 1
                st.last_error = error[:300] if error else "unknown"

    def record_embed(self, *, failed: bool = False) -> None:
        with self._lock:
            self.embed_calls += 1
            if failed:
                self.embed_failures += 1

    def record_cache(self, *, hit: bool) -> None:
        with self._lock:
            if hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "providers": {name: st.as_dict() for name, st in self.providers.items()},
                "embeddings": {
                    "calls": self.embed_calls,
                    "failures": self.embed_failures,
                },
                "narrative_cache": {
                    "hits": self.cache_hits,
                    "misses": self.cache_misses,
                    "hit_rate_pct": (
                        round(100 * self.cache_hits / (self.cache_hits + self.cache_misses), 1)
                        if (self.cache_hits + self.cache_misses)
                        else None
                    ),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.providers.clear()
            self.embed_calls = 0
            self.embed_failures = 0
            self.cache_hits = 0
            self.cache_misses = 0


llm_metrics = LLMMetrics()