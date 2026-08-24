"""
Curated skill vocabulary + alias table. Deliberately not exhaustive —
extend over time as real resumes surface gaps. Grouped loosely to line up
with the categories the Knowledge Tracing System (Phase 10) will use, so
skill tags stay consistent across the app rather than drifting into two
incompatible vocabularies.
"""
import re

CANONICAL_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C", "C#", "Go", "Rust", "PHP", "R", "Dart",
    "SQL", "MongoDB", "PostgreSQL", "MySQL", "Oracle", "SQLite", "Firebase", "Redis",
    "React", "Next.js", "Node.js", "Express", "Django", "Flask", "FastAPI", "Spring Boot",
    "Angular", "Vue", "HTML", "CSS", "Tailwind CSS", "Bootstrap", "Flutter", "Android",
    "Git", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "NLP", "Computer Vision",
    "Data Structures", "Algorithms", "Operating Systems", "Computer Networks",
    "DBMS", "OOP", "REST API", "GraphQL", "Pandas", "NumPy",
    "Scikit-learn", "CI/CD", "Agile", "Jira", "MATLAB",
]

ALIASES = {
    "js": "JavaScript", "reactjs": "React", "react.js": "React",
    "node": "Node.js", "nodejs": "Node.js", "py": "Python",
    "ts": "TypeScript", "postgres": "PostgreSQL", "k8s": "Kubernetes",
    "ml": "Machine Learning", "dl": "Deep Learning", "oops": "OOP",
    "html5": "HTML", "css3": "CSS", "tailwind": "Tailwind CSS",
    "sklearn": "Scikit-learn", "cv": "Computer Vision",
    "expressjs": "Express", "express.js": "Express",
    "vuejs": "Vue", "vue.js": "Vue", "angularjs": "Angular",
    "dsa": "Data Structures", "algo": "Algorithms", "cn": "Computer Networks",
    "os": "Operating Systems", "spring": "Spring Boot",
}

_CANONICAL_LOOKUP = {s.lower(): s for s in CANONICAL_SKILLS}


def _build_skill_pattern() -> re.Pattern:
    all_terms = set(CANONICAL_SKILLS) | set(ALIASES.keys())
    escaped = sorted((re.escape(t) for t in all_terms), key=len, reverse=True)
    # Word-boundary-ish lookaround rather than \b so "C++" and "C#" (whose
    # trailing characters aren't \w) still match correctly.
    return re.compile(rf"(?<![A-Za-z0-9])({'|'.join(escaped)})(?![A-Za-z0-9])", re.IGNORECASE)


SKILL_PATTERN = _build_skill_pattern()


def normalize_skill(raw: str) -> str:
    lower = raw.lower()
    if lower in ALIASES:
        return ALIASES[lower]
    return _CANONICAL_LOOKUP.get(lower, raw)


def extract_skills(text: str) -> list[str]:
    """
    Scans the ENTIRE resume, not just a "Skills" section — candidates
    often mention tools inside Projects/Experience bullets that never make
    it into a dedicated skills list, and those are just as real.
    """
    matches = SKILL_PATTERN.findall(text)
    normalized = {normalize_skill(m) for m in matches}
    return sorted(normalized)
