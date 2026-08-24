import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Deliberately permissive — resumes format phone numbers wildly
# inconsistently (spaces, dots, dashes, parens, country codes). This
# catches the common shapes without trying to be a full E.164 validator.
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3,4}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_/]+", re.IGNORECASE)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_/]+", re.IGNORECASE)


def extract_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    match = PHONE_RE.search(text)
    return match.group(0).strip() if match else None


def extract_linkedin(text: str) -> str | None:
    match = LINKEDIN_RE.search(text)
    return match.group(0) if match else None


def extract_github(text: str) -> str | None:
    match = GITHUB_RE.search(text)
    return match.group(0) if match else None


PORTFOLIO_RE = re.compile(
    r"(?:https?://)?(?:www\.)?([a-zA-Z0-9-]+\.(?:github\.io|vercel\.app|netlify\.app|portfolio|me|dev|tech|site|online|info|space|link)|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s,]+)?)(?<!\.)",
    re.IGNORECASE,
)


def extract_portfolio(text: str) -> str | None:
    """Extract personal portfolio website / custom domain URL excluding common services."""
    for match in PORTFOLIO_RE.finditer(text):
        url = match.group(0).strip()
        url_lower = url.lower()
        if any(skip in url_lower for skip in ["linkedin.com", "github.com", "gmail.com", "yahoo.com", "outlook.com", "google.com"]):
            continue
        if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
            url = f"https://{url}"
        return url
    return None

