"""
PHASE B — app/ml/parsing/llm_skill_extractor.py

Fixes the regex gap ("hands-on with React" != "React.js") WITHOUT forking
the skill taxonomy. The LLM only matches against the EXISTING
CANONICAL_SKILLS/ALIASES from skill_normalizer.py — it never invents a
new canonical category. Anything it finds outside the vocabulary goes to
an "unmapped skill suggestions" queue for admin review.

Falls back to the old regex extractor if the LLM is unavailable — same
graceful-degradation principle as MatchingModelsUnavailable.
"""
from __future__ import annotations

import logging

from app.ml.llm.client import llm_client
from app.ml.llm.exceptions import LLMUnavailableError
from app.ml.parsing.skill_normalizer import (
    ALIASES,
    CANONICAL_SKILLS,
    extract_skills as regex_extract_skills,
    normalize_skill,
)

logger = logging.getLogger(__name__)

_SCHEMA_HINT = """{
  "matched_skills": ["<canonical skill name or a known alias, taken from the provided vocabulary>", ...],
  "unmapped_candidates": ["<skill-like phrase found in the text that is genuinely NOT in the vocabulary>", ...]
}"""

_SYSTEM_PROMPT = (
    "You are a precise skill-extraction assistant for a resume/JD parsing "
    "pipeline. You will be given (1) a fixed vocabulary of canonical skills "
    "and their known aliases, and (2) a block of resume or job-description "
    "text. Your job: identify which vocabulary terms (or close natural-"
    "language variants of them, e.g. 'hands-on with React' -> 'React') "
    "genuinely appear in the text, using understanding rather than exact "
    "string matching. Do NOT invent skills outside the given vocabulary — "
    "if the text clearly mentions a real technical skill that is not in the "
    "vocabulary (e.g. 'Terraform', 'Kafka'), put the exact phrase you found "
    "into unmapped_candidates instead of matched_skills. Do not guess or "
    "hallucinate skills that aren't actually present in the text."
)


class UnmappedSkillSuggestion:
    """Plain container — persist these via UnmappedSkillRepository (new,
    small collection: {phrase, source_id, source_type, created_at,
    reviewed: bool}). Kept out of this file to avoid coupling extraction
    logic to a specific DB layer."""

    def __init__(self, phrase: str, source_id: str, source_type: str):
        self.phrase = phrase
        self.source_id = source_id
        self.source_type = source_type  # "resume" | "job_description"


def extract_skills_llm(text: str, *, source_id: str, source_type: str) -> tuple[list[str], list[UnmappedSkillSuggestion]]:
    """
    Returns (canonical_skill_tags, unmapped_suggestions).

    On LLM failure, transparently falls back to the regex extractor and
    returns an empty unmapped list (regex has no concept of "unmapped" —
    it silently can't see anything outside its pattern anyway, which is
    exactly the limitation this phase exists to work around when the LLM
    IS available).
    """
    vocabulary = {"canonical_skills": CANONICAL_SKILLS, "aliases": ALIASES}
    user_prompt = f"Vocabulary:\n{vocabulary}\n\nText to analyze:\n{text}"

    try:
        result = llm_client.generate_json(_SYSTEM_PROMPT, user_prompt, schema_hint=_SCHEMA_HINT)
    except LLMUnavailableError:
        logger.warning("LLM unavailable for skill extraction (source=%s %s) — falling back to regex.", source_type, source_id)
        return regex_extract_skills(text), []

    raw_matched = result.get("matched_skills", [])
    raw_unmapped = result.get("unmapped_candidates", [])

    if not isinstance(raw_matched, list) or not isinstance(raw_unmapped, list):
        logger.warning("Malformed LLM skill-extraction shape (source=%s %s) — falling back to regex.", source_type, source_id)
        return regex_extract_skills(text), []

    # Run every LLM hit through the SAME normalize_skill() the regex path
    # uses, so canonicalization logic never forks into two implementations.
    # Anything the LLM claims is "matched" but doesn't actually resolve to
    # a known canonical term is treated as a safety-net unmapped candidate
    # instead of trusted blindly.
    canonical_lookup = {s.lower() for s in CANONICAL_SKILLS}
    matched: set[str] = set()
    demoted_to_unmapped: list[str] = []

    for item in raw_matched:
        if not isinstance(item, str):
            continue
        normalized = normalize_skill(item)
        if normalized.lower() in canonical_lookup:
            matched.add(normalized)
        else:
            demoted_to_unmapped.append(item)

    unmapped_phrases = [p for p in raw_unmapped if isinstance(p, str)] + demoted_to_unmapped
    unmapped = [
        UnmappedSkillSuggestion(phrase=p, source_id=source_id, source_type=source_type)
        for p in dict.fromkeys(unmapped_phrases)  # dedupe, preserve order
    ]

    return sorted(matched), unmapped