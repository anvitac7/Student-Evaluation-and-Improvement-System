"""
Extracts the candidate's name from the top of the resume.

spaCy's small English model does PERSON-entity recognition reasonably
well for this narrow use case (a name near the very top of a document).
The model is a separate download (`python -m spacy download en_core_web_sm`)
from the `spacy` pip package itself — if it's missing, we fall back to a
simple heuristic rather than crashing, since a resume upload succeeding
should never depend on an NLP model being present.
"""
import logging
import re

logger = logging.getLogger(__name__)

_nlp = None
_load_attempted = False


def _get_nlp():
    global _nlp, _load_attempted
    if _load_attempted:
        return _nlp
    _load_attempted = True
    try:
        import spacy

        _nlp = spacy.load("en_core_web_sm")
    except Exception as exc:  # model not downloaded, or spaCy itself missing
        logger.warning(
            "spaCy model 'en_core_web_sm' unavailable (%s) — falling back to a "
            "heuristic for name extraction. Run: python -m spacy download en_core_web_sm",
            exc,
        )
        _nlp = None
    return _nlp


def _heuristic_name(text: str) -> str | None:
    """Finds the most likely candidate name among the first 10 non-empty lines:
    no digits, no '@', no URLs or symbols, 1-4 words."""
    blacklist_words = {
        "resume", "curriculum", "vitae", "cv", "page", "profile", "contact",
        "email", "phone", "address", "education", "experience", "skills",
        "projects", "summary", "objective", "about", "portfolio", "github", "linkedin"
    }

    lines = [l.strip() for l in text.splitlines() if l.strip()][:10]
    for line in lines:
        if "@" in line or any(ch.isdigit() for ch in line) or "http" in line.lower() or "www." in line.lower() or ".com" in line.lower():
            continue
        cleaned = re.sub(r"[^A-Za-z\s.\-']", "", line).strip()
        words = cleaned.split()
        if 1 <= len(words) <= 4:
            if not any(w.lower() in blacklist_words for w in words):
                # Valid name candidate
                return " ".join(words)
    return None



def extract_name(text: str) -> str | None:
    head = text[:300]  # a resume's name is always near the very top
    nlp = _get_nlp()
    if nlp:
        doc = nlp(head)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                return ent.text.strip()

    return _heuristic_name(text)
