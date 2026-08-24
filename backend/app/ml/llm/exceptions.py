"""
PHASE A — app/ml/llm/exceptions.py

Same graceful-degradation contract as
app.ml.matching.inference.MatchingModelsUnavailable — callers catch this
and degrade (regex fallback, "narrative unavailable" placeholder, etc.)
instead of the request crashing.
"""


class LLMUnavailableError(Exception):
    """Raised when neither the primary nor fallback LLM provider could be
    reached (timeout, connection error, or both returned malformed output
    after retries). Callers must catch this and degrade gracefully — never
    let it bubble up as a 500."""


class LLMMalformedResponseError(Exception):
    """Raised specifically for the structured-JSON path when the model's
    output can't be parsed as valid JSON matching the expected schema,
    even after LLM_MAX_RETRIES. Distinct from LLMUnavailableError so
    callers can tell 'server unreachable' apart from 'server responded
    with garbage' if they want different handling."""