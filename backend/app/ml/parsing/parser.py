"""
Orchestrates the full extraction pipeline: PDF -> text -> sections ->
structured fields. Deliberately never raises for an ordinary readable-but-
messy resume — a parsing hiccup should degrade to empty/null fields, not
block an upload that already succeeded in Phase 5.
"""
import re

from app.ml.parsing.contact_extractor import (
    extract_email,
    extract_github,
    extract_linkedin,
    extract_phone,
    extract_portfolio,
)
from app.ml.parsing.entity_extractor import extract_name
from app.ml.parsing.section_parser import split_into_sections
from app.ml.parsing.skill_normalizer import extract_skills
from app.ml.parsing.text_extraction import extract_text, extract_text_with_metadata
from app.models.resume import ParsedResumeData


def _split_entries(section_text: str) -> list[str]:
    """One entry per non-empty line/bullet within a section."""
    entries = []
    for line in section_text.splitlines():
        stripped = line.strip(" \t-•*").strip()
        if stripped:
            entries.append(stripped)
    return entries


EXPERIENCE_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*years?", re.IGNORECASE)
CGPA_RE = re.compile(r"(?:cgpa|gpa|percentage|aggregate)[\s:]*([0-9]+(?:\.[0-9]+)?)(?:\s*/\s*(?:10|4|100))?", re.IGNORECASE)
BATCH_YEAR_RE = re.compile(r"\b(20[1-3][0-9])\b")

DEPARTMENT_KEYWORDS: dict[str, list[str]] = {
    "Computer Science and Engineering": [
        "computer science", "cse", "computer engineering", "cs & eng", "cs and engineering"
    ],
    "Information Technology": [
        "information technology", "infotech", r"\bit\b"
    ],
    "Electronics and Communication Engineering": [
        "electronics and communication", "electronics & communication", "ece", "e&c"
    ],
    "Electrical Engineering": [
        "electrical engineering", "electrical and electronics", "eee", "ee"
    ],
    "Mechanical Engineering": [
        "mechanical engineering", "mech eng", "mechanical"
    ],
    "Civil Engineering": [
        "civil engineering", "civil"
    ],
    "Chemical Engineering": [
        "chemical engineering", "chemical"
    ],
    "Artificial Intelligence and Data Science": [
        "artificial intelligence", "data science", "ai & ds", "ai and ds", "aiml", "ai/ml"
    ],
    "Biotechnology": [
        "biotechnology", "biotech"
    ],
    "Aerospace Engineering": [
        "aerospace engineering", "aeronautical"
    ],
}


def _extract_department(text: str) -> str | None:
    text_lower = text.lower()
    for canonical_dept, patterns in DEPARTMENT_KEYWORDS.items():
        for pat in patterns:
            if pat.startswith(r"\b") or pat.endswith(r"\b"):
                if re.search(pat, text_lower):
                    return canonical_dept
            elif pat in text_lower:
                return canonical_dept
    return None


def _extract_cgpa(education_text: str, full_text: str) -> float | None:
    target_text = education_text if education_text else full_text
    match = CGPA_RE.search(target_text)
    if match:
        try:
            val = float(match.group(1))
            if 0.0 <= val <= 10.0:
                return val
            if 10.0 < val <= 100.0:
                return round(val / 10.0, 2)
        except ValueError:
            pass
    return None


def _extract_batch_year(education_text: str, full_text: str) -> int | None:
    target_text = education_text if education_text else full_text
    years = [int(y) for y in BATCH_YEAR_RE.findall(target_text)]
    if years:
        # Most recent / expected graduation year
        return max(years)
    return None


def _estimate_experience_years(experience_entries: list[str]) -> float | None:
    combined = " ".join(experience_entries)
    match = EXPERIENCE_YEARS_RE.search(combined)
    return float(match.group(1)) if match else None


def parse_resume(file_bytes: bytes) -> tuple[ParsedResumeData, str, list[str], float | None]:
    """Returns (parsed_data, raw_text, skill_set, experience_years)."""
    text, extraction_meta = extract_text_with_metadata(file_bytes)
    sections = split_into_sections(text)

    skills = extract_skills(text)

    education_entries = _split_entries(sections.get("education", ""))
    experience_entries = _split_entries(sections.get("experience", ""))
    project_entries = _split_entries(sections.get("projects", ""))
    certification_entries = _split_entries(sections.get("certifications", ""))
    achievement_entries = _split_entries(sections.get("achievements", ""))
    language_entries = _split_entries(sections.get("languages", ""))

    education_combined = sections.get("education", "")
    department = _extract_department(text)
    cgpa = _extract_cgpa(education_combined, text)
    batch_year = _extract_batch_year(education_combined, text)

    parsed = ParsedResumeData(
        name=extract_name(text),
        email=extract_email(text),
        phone=extract_phone(text),
        linkedin_url=extract_linkedin(text),
        github_url=extract_github(text),
        portfolio_url=extract_portfolio(text),
        department=department,
        batch_year=batch_year,
        cgpa=cgpa,
        education=[{"raw": e} for e in education_entries],
        experience=[{"raw": e} for e in experience_entries],
        projects=[{"raw": e} for e in project_entries],
        skills=skills,
        certifications=certification_entries,
        achievements=achievement_entries,
        languages=language_entries,
        parsing_metadata=extraction_meta,
    )

    experience_years = _estimate_experience_years(experience_entries)
    return parsed, text, skills, experience_years

