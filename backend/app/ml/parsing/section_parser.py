"""
Best-effort resume section splitter. Real resumes use wildly inconsistent
headers ("Work Experience" vs "Employment History" vs "Experience"), so
this matches against a curated list of common variants per canonical
section rather than assuming one fixed vocabulary.
"""
import re

SECTION_HEADERS: dict[str, list[str]] = {
    "education": [
        "education", "academic background", "academics", "qualifications", "academic qualifications",
        "educational qualifications", "education & qualifications", "educational background",
    ],
    "experience": [
        "experience", "work experience", "employment history", "professional experience",
        "work history", "internships", "internship experience", "industrial experience",
        "professional background", "relevant experience",
    ],
    "projects": [
        "projects", "academic projects", "personal projects", "key projects", "notable projects",
        "technical projects", "side projects", "project work",
    ],
    "skills": [
        "skills", "technical skills", "skill set", "core competencies", "skills summary",
        "skills & expertise", "skills & tools", "technologies", "key skills", "proficiencies",
        "technical expertise", "skills & abilities", "tools & technologies",
    ],
    "certifications": [
        "certifications", "certificates", "licenses", "certifications & licenses",
        "courses & certifications", "certifications & courses", "training & certifications",
        "trainings & courses", "certifications and training",
    ],
    "achievements": [
        "achievements", "accomplishments", "awards", "honors", "honors & awards",
        "awards & achievements", "scholastic achievements", "extra-curricular achievements",
        "extracurricular activities", "extracurriculars",
    ],
    "languages": [
        "languages", "language proficiency", "languages known",
    ],
}


def _build_header_pattern() -> re.Pattern:
    all_variants = [v for variants in SECTION_HEADERS.values() for v in variants]
    all_variants.sort(key=len, reverse=True)
    escaped = [re.escape(v) for v in all_variants]
    # Match headers even if preceded/followed by decorative characters like |, -, =, :, #
    return re.compile(rf"^[\s\-_#=*•|~]*({'|'.join(escaped)})[\s\-_#=*•|~:]*$", re.IGNORECASE)



HEADER_PATTERN = _build_header_pattern()


def _canonical_section(header_text: str) -> str | None:
    header_lower = header_text.strip().lower()
    for canonical, variants in SECTION_HEADERS.items():
        if header_lower in variants:
            return canonical
    return None


def split_into_sections(text: str) -> dict[str, str]:
    """
    Scans line by line; a line that exactly matches a known header phrase
    (short, standalone — typical of how resumes actually format section
    headers) starts a new section. Content before the first recognized
    header is not attributed to any section (it's still in the full
    resume_text, just not section-tagged).
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        match = HEADER_PATTERN.match(stripped)
        if match:
            canonical = _canonical_section(match.group(1))
            if canonical:
                current = canonical
                sections.setdefault(current, [])
                continue
        if current:
            sections[current].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}
