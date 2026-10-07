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
    """Best-effort name guess from the FIRST non-empty line, used only when
    spaCy NER is unavailable.

    Only the first line is considered, deliberately. This used to scan the
    first 10 lines looking for anything name-shaped, which meant a resume
    beginning with contact info would fall through to an arbitrary later line
    and return prose like "Some other content" as the person's name. A name
    belongs at the top of a resume; if the top isn't name-shaped, the honest
    answer is None (the caller leaves the field null), not a confident guess
    at the second line. Returning None is handled gracefully downstream,
    whereas a wrong name propagates into the profile UI and exports.

    Rejects: digits, '@', URLs, >4 words, and a set of document-section
    words ("Resume", "Contact", ...) that are never part of a name.
    """
    blacklist_words = {
        "resume", "curriculum", "vitae", "cv", "page", "profile", "contact",
        "email", "phone", "address", "education", "experience", "skills",
        "projects", "summary", "objective", "about", "portfolio", "github", "linkedin"
    }

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None

    line = lines[0]
    if "@" in line or any(ch.isdigit() for ch in line) or "http" in line.lower() or "www." in line.lower() or ".com" in line.lower():
        return None

    cleaned = re.sub(r"[^A-Za-z\s.\-']", "", line).strip()
    words = cleaned.split()
    if not 1 <= len(words) <= 4:
        return None
    if any(w.lower() in blacklist_words for w in words):
        return None
    return " ".join(words)



def extract_name(text: str) -> str | None:
    head = text[:300]  # a resume's name is always near the very top
    nlp = _get_nlp()
    if nlp:
        doc = nlp(head)
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                return ent.text.strip()

    return _heuristic_name(text)
