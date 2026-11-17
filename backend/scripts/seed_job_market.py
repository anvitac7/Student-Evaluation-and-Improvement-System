"""Seed the deterministic historical job-market demo dataset.

This is the Phase 2 data layer for the Trending Skills & Company Requirements
feature. It creates two separate collections:

    job_market_postings   - historical mock job postings, 2023-2026
    market_skill_catalog  - canonical skill names/categories used by the data

The operational collections (placement_drives, applications, companies,
assessments) are never read, modified or deleted by this script.

The dataset is intentionally fictional. Company names are demo identities,
all websites use reserved ``.example`` domains, and every posting's JD says so.

Usage (from backend/):

    .venv\\Scripts\\python.exe -m scripts.seed_job_market
    .venv\\Scripts\\python.exe -m scripts.seed_job_market --force
    .venv\\Scripts\\python.exe -m scripts.seed_job_market --reset

Default
    Refuse to run if mock market postings already exist.

--force
    Delete existing ``source="mock"`` postings, refresh the mock skill catalog,
    and regenerate the dataset. Non-mock records are never touched.

--reset
    Delete mock postings and mock catalog entries, then recreate both. Catalog
    entries referenced by non-mock postings are preserved.

The 2026 data is deliberately partial: January through October only. Year-over-
year comparisons must use the same Jan-Oct window (see
``MARKET_COMPARISON_PERIOD``).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from pymongo.errors import PyMongoError  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import ensure_market_indexes  # noqa: E402
from app.models.market import (  # noqa: E402
    MARKET_COMPARISON_PERIOD,
    MARKET_DATASET_VERSION,
    MARKET_IS_PARTIAL_YEAR,
    MARKET_LATEST_YEAR,
    HiringType,
    JobFamily,
    SeniorityLevel,
    SkillCategory,
    WorkMode,
)
from app.repositories.job_posting_repository import (  # noqa: E402
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)

RANDOM_SEED = 20261115
EXPECTED_TOTAL_POSTINGS = 300
MOCK_DISCLAIMER = (
    "This is a fictional demo posting generated for the PLACER analytics "
    "dataset; it does not represent verified real-world hiring activity."
)

POSTING_MONTH_WEIGHTS = {
    1: 0.8,
    2: 1.0,
    3: 1.1,
    4: 0.7,
    5: 0.6,
    6: 0.5,
    7: 1.2,
    8: 1.3,
    9: 1.2,
    10: 1.0,
    11: 0.8,
    12: 0.7,
}

# ---------------------------------------------------------------------------
# Centralized configuration tables
# ---------------------------------------------------------------------------

SKILL_CATALOG: list[dict[str, Any]] = [
    # Programming languages
    {"name": "Python", "slug": "python", "category": "Programming Language", "is_technical": True, "aliases": ["python3"]},
    {"name": "Java", "slug": "java", "category": "Programming Language", "is_technical": True, "aliases": []},
    {"name": "JavaScript", "slug": "javascript", "category": "Programming Language", "is_technical": True, "aliases": ["JS"]},
    {"name": "TypeScript", "slug": "typescript", "category": "Programming Language", "is_technical": True, "aliases": ["TS"]},
    {"name": "C++", "slug": "cpp", "category": "Programming Language", "is_technical": True, "aliases": ["cpp"]},
    # Frontend
    {"name": "React.js", "slug": "react-js", "category": "Frontend", "is_technical": True, "aliases": ["React", "ReactJS"]},
    {"name": "Next.js", "slug": "next-js", "category": "Frontend", "is_technical": True, "aliases": ["NextJS"]},
    {"name": "HTML", "slug": "html", "category": "Frontend", "is_technical": True, "aliases": ["HTML5"]},
    {"name": "CSS", "slug": "css", "category": "Frontend", "is_technical": True, "aliases": ["CSS3"]},
    {"name": "jQuery", "slug": "jquery", "category": "Frontend", "is_technical": True, "aliases": []},
    {"name": "AngularJS", "slug": "angularjs", "category": "Frontend", "is_technical": True, "aliases": ["Angular JS"]},
    # Backend
    {"name": "Node.js", "slug": "node-js", "category": "Backend", "is_technical": True, "aliases": ["Node", "NodeJS"]},
    {"name": "FastAPI", "slug": "fastapi", "category": "Backend", "is_technical": True, "aliases": ["Fast API"]},
    {"name": "REST APIs", "slug": "rest-apis", "category": "Backend", "is_technical": True, "aliases": ["REST API", "REST"]},
    {"name": "SOAP", "slug": "soap", "category": "Backend", "is_technical": True, "aliases": ["SOAP APIs"]},
    {"name": "XML", "slug": "xml", "category": "Backend", "is_technical": True, "aliases": ["Extensible Markup Language"]},
    # Databases
    {"name": "SQL", "slug": "sql", "category": "Database", "is_technical": True, "aliases": ["Structured Query Language"]},
    {"name": "MongoDB", "slug": "mongodb", "category": "Database", "is_technical": True, "aliases": ["Mongo"]},
    {"name": "PostgreSQL", "slug": "postgresql", "category": "Database", "is_technical": True, "aliases": ["Postgres"]},
    {"name": "Snowflake", "slug": "snowflake", "category": "Database", "is_technical": True, "aliases": []},
    # Data & ML
    {"name": "Machine Learning", "slug": "machine-learning", "category": "Data & ML", "is_technical": True, "aliases": ["ML"]},
    {"name": "Artificial Intelligence", "slug": "artificial-intelligence", "category": "Data & ML", "is_technical": True, "aliases": ["AI"]},
    {"name": "Generative AI", "slug": "generative-ai", "category": "Data & ML", "is_technical": True, "aliases": ["GenAI", "LLM"]},
    {"name": "NLP", "slug": "nlp", "category": "Data & ML", "is_technical": True, "aliases": ["Natural Language Processing"]},
    {"name": "PyTorch", "slug": "pytorch", "category": "Data & ML", "is_technical": True, "aliases": []},
    {"name": "Pandas", "slug": "pandas", "category": "Data & ML", "is_technical": True, "aliases": []},
    {"name": "Power BI", "slug": "power-bi", "category": "Data & ML", "is_technical": True, "aliases": ["PowerBI"]},
    {"name": "dbt", "slug": "dbt", "category": "Data & ML", "is_technical": True, "aliases": ["Data Build Tool"]},
    {"name": "Excel", "slug": "excel", "category": "Data & ML", "is_technical": True, "aliases": ["Microsoft Excel"]},
    {"name": "Statistics", "slug": "statistics", "category": "Data & ML", "is_technical": True, "aliases": []},
    {"name": "Hadoop", "slug": "hadoop", "category": "Data & ML", "is_technical": True, "aliases": []},
    # Cloud & DevOps
    {"name": "AWS", "slug": "aws", "category": "Cloud & DevOps", "is_technical": True, "aliases": ["Amazon Web Services"]},
    {"name": "Docker", "slug": "docker", "category": "Cloud & DevOps", "is_technical": True, "aliases": []},
    {"name": "Kubernetes", "slug": "kubernetes", "category": "Cloud & DevOps", "is_technical": True, "aliases": ["K8s"]},
    {"name": "Terraform", "slug": "terraform", "category": "Cloud & DevOps", "is_technical": True, "aliases": []},
    {"name": "CI/CD", "slug": "ci-cd", "category": "Cloud & DevOps", "is_technical": True, "aliases": ["CICD", "Continuous Integration"]},
    {"name": "Linux", "slug": "linux", "category": "Cloud & DevOps", "is_technical": True, "aliases": []},
    {"name": "Git", "slug": "git", "category": "Cloud & DevOps", "is_technical": True, "aliases": []},
    # Security and testing
    {"name": "Cybersecurity", "slug": "cybersecurity", "category": "Cybersecurity", "is_technical": True, "aliases": ["Cyber Security", "InfoSec"]},
    {"name": "Manual Testing", "slug": "manual-testing", "category": "Testing", "is_technical": True, "aliases": ["QA Testing"]},
    # Soft skills
    {"name": "Communication", "slug": "communication", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Problem Solving", "slug": "problem-solving", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Teamwork", "slug": "teamwork", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Ownership", "slug": "ownership", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Adaptability", "slug": "adaptability", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Analytical Thinking", "slug": "analytical-thinking", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Stakeholder Management", "slug": "stakeholder-management", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Documentation", "slug": "documentation", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Presentation", "slug": "presentation", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Time Management", "slug": "time-management", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Collaboration", "slug": "collaboration", "category": "Soft Skill", "is_technical": False, "aliases": []},
    {"name": "Attention to Detail", "slug": "attention-to-detail", "category": "Soft Skill", "is_technical": False, "aliases": []},
]

COMPANIES: list[dict[str, Any]] = [
    {
        "name": "Nexora Technologies",
        "slug": "nexora-technologies",
        "industry": "Software Product Development",
        "size": "201-500",
        "hq": "Bengaluru",
        "website": "https://www.nexoratech.example",
        "job_families": ["Software Engineering", "Frontend Engineering", "Backend Engineering"],
        "year_weights": {2023: 1.00, 2024: 1.15, 2025: 1.30, 2026: 1.45},
    },
    {
        "name": "Skyline Analytics",
        "slug": "skyline-analytics",
        "industry": "Data Analytics & Consulting",
        "size": "501-1000",
        "hq": "Hyderabad",
        "website": "https://www.skylineanalytics.example",
        "job_families": ["Data & Analytics", "Business Analysis"],
        "year_weights": {2023: 0.80, 2024: 0.95, 2025: 1.10, 2026: 1.25},
    },
    {
        "name": "QuantumEdge Systems",
        "slug": "quantumedge-systems",
        "industry": "Cybersecurity",
        "size": "51-200",
        "hq": "Pune",
        "website": "https://www.quantumedge.example",
        "job_families": ["Cybersecurity", "Backend Engineering", "Cloud & DevOps"],
        "year_weights": {2023: 0.70, 2024: 0.90, 2025: 1.15, 2026: 1.40},
    },
    {
        "name": "BlueOrbit Solutions",
        "slug": "blueorbit-solutions",
        "industry": "Cloud Infrastructure & DevOps",
        "size": "201-500",
        "hq": "Bengaluru",
        "website": "https://www.blueorbit.example",
        "job_families": ["Cloud & DevOps", "Backend Engineering", "QA & Automation"],
        "year_weights": {2023: 0.75, 2024: 0.95, 2025: 1.20, 2026: 1.40},
    },
    {
        "name": "PixelForge Studios",
        "slug": "pixelforge-studios",
        "industry": "Gaming & Mobile Apps",
        "size": "51-200",
        "hq": "Mumbai",
        "website": "https://www.pixelforge.example",
        "job_families": ["Frontend Engineering", "Software Engineering", "QA & Automation"],
        "year_weights": {2023: 0.80, 2024: 0.90, 2025: 1.00, 2026: 1.10},
    },
    {
        "name": "CloudNest Infrastructure",
        "slug": "cloudnest-infrastructure",
        "industry": "SaaS & Cloud Infrastructure",
        "size": "201-500",
        "hq": "Hyderabad",
        "website": "https://www.cloudnest.example",
        "job_families": ["Backend Engineering", "Cloud & DevOps", "Software Engineering"],
        "year_weights": {2023: 0.90, 2024: 1.05, 2025: 1.25, 2026: 1.45},
    },
    {
        "name": "TerraNova Fintech",
        "slug": "terranova-fintech",
        "industry": "Fintech",
        "size": "501-1000",
        "hq": "Bengaluru",
        "website": "https://www.terranova.example",
        "job_families": ["AI & Machine Learning", "Data & Analytics", "Backend Engineering"],
        "year_weights": {2023: 0.85, 2024: 1.00, 2025: 1.20, 2026: 1.40},
    },
    {
        "name": "Aurora HealthTech",
        "slug": "aurora-healthtech",
        "industry": "Healthcare Technology",
        "size": "201-500",
        "hq": "Chennai",
        "website": "https://www.aurorahealth.example",
        "job_families": ["QA & Automation", "Backend Engineering", "Data & Analytics"],
        "year_weights": {2023: 0.70, 2024: 0.85, 2025: 1.00, 2026: 1.10},
    },
    {
        "name": "GreenLoop Logistics",
        "slug": "greenloop-logistics",
        "industry": "Logistics & Supply Chain",
        "size": "501-1000",
        "hq": "Bengaluru",
        "website": "https://www.greenloop.example",
        "job_families": ["Business Analysis", "Data & Analytics"],
        "year_weights": {2023: 1.20, 2024: 1.00, 2025: 0.75, 2026: 0.50},
    },
    {
        "name": "Vertex Robotics",
        "slug": "vertex-robotics",
        "industry": "Robotics & Automation",
        "size": "201-500",
        "hq": "Hyderabad",
        "website": "https://www.vertexrobotics.example",
        "job_families": ["Embedded & Robotics", "Software Engineering"],
        "year_weights": {2023: 0.60, 2024: 0.80, 2025: 1.00, 2026: 1.20},
    },
    {
        "name": "MediCore Systems",
        "slug": "medicore-systems",
        "industry": "Healthcare Technology",
        "size": "201-500",
        "hq": "Chennai",
        "website": "https://www.medicore.example",
        "job_families": ["Backend Engineering", "Data & Analytics", "QA & Automation"],
        "year_weights": {2023: 0.50, 2024: 0.70, 2025: 0.95, 2026: 1.25},
    },
    {
        "name": "FinSight Labs",
        "slug": "finsight-labs",
        "industry": "Fintech & Analytics",
        "size": "51-200",
        "hq": "Pune",
        "website": "https://www.finsightlabs.example",
        "job_families": ["Data & Analytics", "AI & Machine Learning", "Business Analysis"],
        "year_weights": {2023: 0.40, 2024: 0.65, 2025: 0.95, 2026: 1.30},
    },
    {
        "name": "Orbit Commerce",
        "slug": "orbit-commerce",
        "industry": "E-commerce",
        "size": "501-1000",
        "hq": "Bengaluru",
        "website": "https://www.orbitcommerce.example",
        "job_families": ["Frontend Engineering", "Backend Engineering", "Data & Analytics"],
        "year_weights": {2023: 0.70, 2024: 0.90, 2025: 1.10, 2026: 1.30},
    },
    {
        "name": "Cyan Analytics",
        "slug": "cyan-analytics",
        "industry": "Data Analytics & BI",
        "size": "51-200",
        "hq": "Hyderabad",
        "website": "https://www.cyananalytics.example",
        "job_families": ["Data & Analytics", "Business Analysis", "AI & Machine Learning"],
        "year_weights": {2023: 0.45, 2024: 0.65, 2025: 0.90, 2026: 1.15},
    },
    {
        "name": "Nimbus Cloudworks",
        "slug": "nimbus-cloudworks",
        "industry": "Cloud Services",
        "size": "501-1000",
        "hq": "Pune",
        "website": "https://www.nimbuscloudworks.example",
        "job_families": ["Cloud & DevOps", "Backend Engineering", "Cybersecurity"],
        "year_weights": {2023: 0.60, 2024: 0.80, 2025: 1.05, 2026: 1.30},
    },
]

JOB_FAMILIES: list[str] = [family.value for family in JobFamily]

YEAR_PROFILES: dict[int, dict[str, Any]] = {
    2023: {"postings": 64, "months": list(range(1, 13))},
    2024: {"postings": 72, "months": list(range(1, 13))},
    2025: {"postings": 84, "months": list(range(1, 13))},
    2026: {
        "postings": 80,
        "months": list(range(1, 11)),
        "is_partial_year": True,
        "comparison_period": MARKET_COMPARISON_PERIOD,
    },
}

# Centralized year-wise demand weights. These are demo assumptions, not
# verified industry research. Weights are used only when choosing optional
# skills for a posting; base role skills remain stable.
SKILL_TRENDS: dict[str, dict[int, float]] = {
    "Python": {2023: 0.95, 2024: 1.10, 2025: 1.30, 2026: 1.55},
    "Java": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "JavaScript": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "TypeScript": {2023: 0.40, 2024: 0.80, 2025: 1.50, 2026: 2.20},
    "C++": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "React.js": {2023: 0.60, 2024: 1.20, 2025: 1.80, 2026: 2.50},
    "Next.js": {2023: 0.15, 2024: 0.50, 2025: 1.30, 2026: 2.00},
    "HTML": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "CSS": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "jQuery": {2023: 2.00, 2024: 1.00, 2025: 0.40, 2026: 0.05},
    "AngularJS": {2023: 1.80, 2024: 0.80, 2025: 0.20, 2026: 0.02},
    "Node.js": {2023: 0.70, 2024: 0.90, 2025: 1.10, 2026: 1.40},
    "FastAPI": {2023: 0.10, 2024: 0.40, 2025: 1.20, 2026: 2.00},
    "REST APIs": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "SOAP": {2023: 1.80, 2024: 0.80, 2025: 0.20, 2026: 0.02},
    "XML": {2023: 1.50, 2024: 1.00, 2025: 0.50, 2026: 0.05},
    "SQL": {2023: 1.00, 2024: 1.02, 2025: 1.04, 2026: 1.06},
    "MongoDB": {2023: 0.70, 2024: 0.90, 2025: 1.10, 2026: 1.30},
    "PostgreSQL": {2023: 0.70, 2024: 0.90, 2025: 1.20, 2026: 1.50},
    "Snowflake": {2023: 0.20, 2024: 0.50, 2025: 1.20, 2026: 2.00},
    "Machine Learning": {2023: 0.80, 2024: 1.00, 2025: 1.20, 2026: 1.40},
    "Artificial Intelligence": {2023: 0.60, 2024: 0.80, 2025: 1.20, 2026: 1.70},
    "Generative AI": {2023: 0.02, 2024: 0.10, 2025: 0.80, 2026: 2.20},
    "NLP": {2023: 0.50, 2024: 0.80, 2025: 1.60, 2026: 2.10},
    "PyTorch": {2023: 0.40, 2024: 0.70, 2025: 1.70, 2026: 2.30},
    "Pandas": {2023: 0.70, 2024: 0.90, 2025: 1.30, 2026: 2.10},
    "Power BI": {2023: 0.70, 2024: 0.90, 2025: 1.10, 2026: 1.30},
    "dbt": {2023: 0.05, 2024: 0.30, 2025: 1.00, 2026: 1.80},
    "Excel": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Statistics": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Hadoop": {2023: 1.80, 2024: 0.60, 2025: 0.10, 2026: 0.02},
    "AWS": {2023: 0.80, 2024: 1.00, 2025: 1.40, 2026: 2.00},
    "Docker": {2023: 0.70, 2024: 0.90, 2025: 1.40, 2026: 1.90},
    "Kubernetes": {2023: 0.25, 2024: 0.70, 2025: 1.40, 2026: 2.00},
    "Terraform": {2023: 0.30, 2024: 0.60, 2025: 1.20, 2026: 1.80},
    "CI/CD": {2023: 0.60, 2024: 0.80, 2025: 1.20, 2026: 1.60},
    "Linux": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Git": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Cybersecurity": {2023: 0.80, 2024: 0.90, 2025: 1.10, 2026: 1.30},
    "Manual Testing": {2023: 1.80, 2024: 1.10, 2025: 0.45, 2026: 0.05},
    "Communication": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Problem Solving": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Teamwork": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Ownership": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Adaptability": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Analytical Thinking": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Stakeholder Management": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Documentation": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Presentation": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Time Management": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Collaboration": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
    "Attention to Detail": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
}

SOFT_SKILL_POOL: list[str] = [
    "Communication",
    "Problem Solving",
    "Teamwork",
    "Ownership",
    "Adaptability",
    "Analytical Thinking",
    "Stakeholder Management",
    "Documentation",
    "Presentation",
    "Time Management",
    "Collaboration",
    "Attention to Detail",
]

FAMILY_OPTIONAL_SKILLS: dict[str, list[str]] = {
    "Software Engineering": [
        "TypeScript", "React.js", "Next.js", "Node.js", "FastAPI",
        "Docker", "AWS", "Kubernetes", "MongoDB", "PostgreSQL",
    ],
    "Frontend Engineering": [
        "React.js", "TypeScript", "Next.js", "Node.js", "jQuery",
        "AngularJS", "REST APIs",
    ],
    "Backend Engineering": [
        "FastAPI", "Node.js", "MongoDB", "PostgreSQL", "Docker", "AWS",
        "Kubernetes", "SOAP", "XML", "CI/CD",
    ],
    "Data & Analytics": [
        "Python", "Pandas", "Snowflake", "dbt", "Hadoop", "Machine Learning",
    ],
    "AI & Machine Learning": [
        "PyTorch", "NLP", "Generative AI", "Artificial Intelligence",
        "Snowflake", "AWS", "Docker",
    ],
    "Cloud & DevOps": [
        "Kubernetes", "Terraform", "Python", "Docker", "AWS", "CI/CD", "Linux",
        "MongoDB", "PostgreSQL", "REST APIs",
    ],
    "Cybersecurity": [
        "AWS", "Docker", "REST APIs", "Kubernetes", "Python", "Linux",
    ],
    "QA & Automation": [
        "Manual Testing", "Python", "REST APIs", "Docker", "XML", "CI/CD",
    ],
    "Business Analysis": [
        "Python", "Snowflake", "dbt", "Power BI", "Statistics",
    ],
    "Embedded & Robotics": [
        "Python", "Docker", "REST APIs", "Linux", "Git",
    ],
}

FAMILY_SOFT_SKILLS: dict[str, list[str]] = {
    "Software Engineering": [
        "Communication", "Problem Solving", "Teamwork", "Ownership", "Adaptability",
    ],
    "Frontend Engineering": [
        "Communication", "Teamwork", "Attention to Detail", "Collaboration",
        "Adaptability",
    ],
    "Backend Engineering": [
        "Problem Solving", "Ownership", "Documentation", "Teamwork",
        "Time Management",
    ],
    "Data & Analytics": [
        "Analytical Thinking", "Communication", "Stakeholder Management",
        "Attention to Detail", "Presentation",
    ],
    "AI & Machine Learning": [
        "Problem Solving", "Analytical Thinking", "Communication", "Ownership",
        "Adaptability",
    ],
    "Cloud & DevOps": [
        "Problem Solving", "Ownership", "Documentation", "Collaboration",
        "Time Management",
    ],
    "Cybersecurity": [
        "Analytical Thinking", "Attention to Detail", "Communication",
        "Problem Solving", "Ownership",
    ],
    "QA & Automation": [
        "Attention to Detail", "Communication", "Problem Solving",
        "Documentation", "Time Management",
    ],
    "Business Analysis": [
        "Communication", "Stakeholder Management", "Analytical Thinking",
        "Presentation", "Time Management",
    ],
    "Embedded & Robotics": [
        "Problem Solving", "Attention to Detail", "Teamwork", "Ownership",
        "Documentation",
    ],
}

CS_IT = ["Computer Science", "Information Technology"]
ENG_DEPTS = CS_IT + ["Electronics and Communication", "Electrical Engineering"]
DATA_DEPTS = CS_IT + ["Mathematics and Computing", "Statistics"]
BUSINESS_DEPTS = [
    "Any Engineering",
    "Computer Science",
    "Information Technology",
    "Mathematics and Computing",
]
EMBEDDED_DEPTS = [
    "Electronics and Communication",
    "Electrical Engineering",
    "Computer Science",
    "Mechanical Engineering",
]

ROLE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "Software Engineering": [
        {
            "title": "Software Development Engineer I",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": [
                "Python", "JavaScript", "SQL", "Git", "REST APIs", "Docker",
                "AWS",
            ],
            "description": "Build and ship customer-facing features across web and backend services.",
            "responsibilities": "design REST APIs, build responsive interfaces, write tests, and deploy services with senior engineers",
            "salary_min_lpa": 10.0,
            "salary_max_lpa": 16.0,
            "locations": ["Bengaluru", "Hyderabad", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Associate Software Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["Java", "JavaScript", "SQL", "Git", "REST APIs"],
            "description": "Contribute to feature delivery, debugging and automated testing across a modern web stack.",
            "responsibilities": "implement features, fix production issues, add automated tests, and participate in code reviews",
            "salary_min_lpa": 8.0,
            "salary_max_lpa": 13.0,
            "locations": ["Bengaluru", "Hyderabad", "Chennai"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Full-Stack Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 2.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": [
                "Python", "JavaScript", "React.js", "SQL", "Git", "REST APIs",
                "AWS",
            ],
            "description": "Own end-to-end features spanning React interfaces and Python APIs.",
            "responsibilities": "build React interfaces, extend Python APIs, model data in SQL, and improve reliability",
            "salary_min_lpa": 14.0,
            "salary_max_lpa": 20.0,
            "locations": ["Bengaluru", "Hyderabad"],
            "work_modes": ["Hybrid"],
        },
    ],
    "Frontend Engineering": [
        {
            "title": "Frontend Developer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["JavaScript", "HTML", "CSS", "Git"],
            "description": "Build accessible, responsive interfaces for consumer and enterprise products.",
            "responsibilities": "translate designs into React components, improve accessibility, and optimise page performance",
            "salary_min_lpa": 8.0,
            "salary_max_lpa": 13.0,
            "locations": ["Mumbai", "Bengaluru", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "UI Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["JavaScript", "TypeScript", "HTML", "CSS", "Git"],
            "description": "Own the component library and front-end quality across product surfaces.",
            "responsibilities": "maintain reusable components, review front-end code, and work closely with designers",
            "salary_min_lpa": 11.0,
            "salary_max_lpa": 16.0,
            "locations": ["Bengaluru", "Mumbai"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "Backend Engineering": [
        {
            "title": "Backend Engineer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Python", "SQL", "REST APIs", "Git", "Docker"],
            "description": "Build reliable APIs and data services for high-traffic products.",
            "responsibilities": "design REST APIs, model relational data, write tests, and debug production services",
            "salary_min_lpa": 10.0,
            "salary_max_lpa": 15.0,
            "locations": ["Hyderabad", "Bengaluru", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "API Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": [
                "Python", "SQL", "REST APIs", "Git", "Docker", "AWS",
                "Kubernetes",
            ],
            "description": "Design and operate internal and partner-facing APIs.",
            "responsibilities": "build API contracts, improve observability, and integrate services with queues and databases",
            "salary_min_lpa": 12.0,
            "salary_max_lpa": 18.0,
            "locations": ["Bengaluru", "Hyderabad"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "Data & Analytics": [
        {
            "title": "Data Analyst",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": DATA_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["SQL", "Excel", "Statistics", "Power BI"],
            "description": "Turn transaction and product data into clear business recommendations.",
            "responsibilities": "write SQL queries, build Power BI dashboards, automate reports, and present findings",
            "salary_min_lpa": 7.0,
            "salary_max_lpa": 11.0,
            "locations": ["Hyderabad", "Bengaluru", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Data Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": DATA_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Python", "SQL", "Pandas", "Snowflake", "AWS"],
            "description": "Build reliable data pipelines and analytics-ready datasets.",
            "responsibilities": "ingest source data, model warehouse tables, orchestrate pipelines, and monitor data quality",
            "salary_min_lpa": 10.0,
            "salary_max_lpa": 16.0,
            "locations": ["Hyderabad", "Bengaluru"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "AI & Machine Learning": [
        {
            "title": "Machine Learning Engineer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": DATA_DEPTS,
            "min_cgpa": 7.5,
            "technical_skills": [
                "Python", "Pandas", "Statistics", "Machine Learning", "AWS",
            ],
            "description": "Train, evaluate and deploy machine learning models for production use cases.",
            "responsibilities": "prepare datasets, train models, evaluate performance, and package models for deployment",
            "salary_min_lpa": 12.0,
            "salary_max_lpa": 18.0,
            "locations": ["Bengaluru", "Hyderabad", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Data Scientist",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": DATA_DEPTS,
            "min_cgpa": 7.5,
            "technical_skills": [
                "Python", "Pandas", "Statistics", "Machine Learning", "AWS",
            ],
            "description": "Frame business problems as data science experiments and communicate results.",
            "responsibilities": "explore data, build models, design experiments, and present recommendations to product teams",
            "salary_min_lpa": 14.0,
            "salary_max_lpa": 22.0,
            "locations": ["Bengaluru", "Hyderabad"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "Cloud & DevOps": [
        {
            "title": "DevOps Engineer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Linux", "Docker", "AWS", "Git", "CI/CD", "Kubernetes"],
            "description": "Automate build, deployment and monitoring for cloud-native services.",
            "responsibilities": "maintain CI/CD pipelines, containerise services, monitor production, and improve reliability",
            "salary_min_lpa": 10.0,
            "salary_max_lpa": 16.0,
            "locations": ["Bengaluru", "Pune", "Hyderabad"],
            "work_modes": ["Hybrid", "Remote"],
        },
        {
            "title": "Cloud Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Linux", "AWS", "Docker", "Terraform", "Kubernetes"],
            "description": "Design and operate secure cloud infrastructure for product teams.",
            "responsibilities": "provision cloud resources, write infrastructure as code, and improve cost and security posture",
            "salary_min_lpa": 12.0,
            "salary_max_lpa": 18.0,
            "locations": ["Bengaluru", "Pune"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "Cybersecurity": [
        {
            "title": "Cybersecurity Analyst",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Linux", "Python", "SQL", "Git", "Cybersecurity"],
            "description": "Monitor threats, investigate alerts and improve security operations.",
            "responsibilities": "triage security alerts, analyse logs, document incidents, and support remediation",
            "salary_min_lpa": 8.0,
            "salary_max_lpa": 13.0,
            "locations": ["Pune", "Bengaluru", "Hyderabad"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Security Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 7.5,
            "technical_skills": ["Linux", "Python", "Cybersecurity", "Git", "AWS"],
            "description": "Build secure systems and automate security controls.",
            "responsibilities": "review application security, automate checks, and partner with engineering on remediation",
            "salary_min_lpa": 12.0,
            "salary_max_lpa": 18.0,
            "locations": ["Bengaluru", "Pune"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "QA & Automation": [
        {
            "title": "QA Automation Engineer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["Java", "SQL", "Git", "CI/CD"],
            "description": "Build automated tests that protect product quality and release velocity.",
            "responsibilities": "write automated test suites, maintain CI checks, and report defects with clear reproduction steps",
            "salary_min_lpa": 7.0,
            "salary_max_lpa": 12.0,
            "locations": ["Hyderabad", "Bengaluru", "Chennai"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Test Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": ENG_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["Java", "SQL", "Git", "REST APIs"],
            "description": "Own end-to-end test coverage for web and API products.",
            "responsibilities": "design test plans, validate APIs, automate regression suites, and support release sign-off",
            "salary_min_lpa": 9.0,
            "salary_max_lpa": 14.0,
            "locations": ["Chennai", "Hyderabad"],
            "work_modes": ["Hybrid", "On-site"],
        },
    ],
    "Business Analysis": [
        {
            "title": "Business Analyst",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "Any Bachelor's",
            "eligible_departments": BUSINESS_DEPTS,
            "min_cgpa": 6.5,
            "technical_skills": ["Excel", "SQL", "Power BI", "Statistics"],
            "description": "Analyse operations and product data to support business decisions.",
            "responsibilities": "define KPIs, build reports, analyse trends, and present recommendations to stakeholders",
            "salary_min_lpa": 7.0,
            "salary_max_lpa": 11.0,
            "locations": ["Bengaluru", "Hyderabad", "Pune"],
            "work_modes": ["Hybrid", "On-site"],
        },
        {
            "title": "Product Analyst",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "Any Bachelor's",
            "eligible_departments": BUSINESS_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["Excel", "SQL", "Power BI", "Statistics"],
            "description": "Measure product usage and turn insights into prioritisation decisions.",
            "responsibilities": "build product dashboards, analyse funnels, design experiments, and work with product managers",
            "salary_min_lpa": 10.0,
            "salary_max_lpa": 15.0,
            "locations": ["Bengaluru", "Hyderabad"],
            "work_modes": ["Hybrid", "Remote"],
        },
    ],
    "Embedded & Robotics": [
        {
            "title": "Embedded Software Engineer",
            "seniority": "Entry",
            "hiring_type": "Full-time",
            "min_experience_years": 0.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": EMBEDDED_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["C++", "Linux", "Git"],
            "description": "Develop firmware and control software for connected devices and robots.",
            "responsibilities": "write embedded C++, integrate sensors, debug hardware-software interactions, and test on device",
            "salary_min_lpa": 9.0,
            "salary_max_lpa": 14.0,
            "locations": ["Hyderabad", "Bengaluru", "Pune"],
            "work_modes": ["On-site", "Hybrid"],
        },
        {
            "title": "Firmware Engineer",
            "seniority": "Associate",
            "hiring_type": "Full-time",
            "min_experience_years": 1.0,
            "education_level": "B.E./B.Tech",
            "eligible_departments": EMBEDDED_DEPTS,
            "min_cgpa": 7.0,
            "technical_skills": ["C++", "Linux", "Git", "Python"],
            "description": "Own firmware modules from prototype through production.",
            "responsibilities": "implement device drivers, tune real-time behaviour, and collaborate with hardware engineers",
            "salary_min_lpa": 11.0,
            "salary_max_lpa": 16.0,
            "locations": ["Hyderabad", "Pune"],
            "work_modes": ["On-site", "Hybrid"],
        },
    ],
}


class DatasetValidationError(ValueError):
    """Raised when the generated market dataset fails an invariant."""


def _slugify(value: str) -> str:
    value = value.casefold().replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


_SKILL_LOOKUP: dict[str, str] = {}
for _skill in SKILL_CATALOG:
    _SKILL_LOOKUP[_skill["name"].casefold()] = _skill["name"]
    for _alias in _skill["aliases"]:
        _SKILL_LOOKUP[_alias.casefold()] = _skill["name"]


def normalize_skill(value: str) -> str:
    """Resolve a skill name or alias to its canonical catalog name."""
    key = " ".join(value.split()).casefold()
    try:
        return _SKILL_LOOKUP[key]
    except KeyError as exc:
        raise ValueError(f"Unknown skill: {value!r}") from exc


def normalize_skills(values: list[str]) -> list[str]:
    """Canonicalize and de-duplicate skills while preserving order."""
    normalized: list[str] = []
    for value in values:
        canonical = normalize_skill(value)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _weighted_sample_without_replacement(
    rng: random.Random,
    items: list[str],
    weights: list[float],
    count: int,
) -> list[str]:
    pool = list(items)
    pool_weights = list(weights)
    chosen: list[str] = []
    for _ in range(min(count, len(pool))):
        total = sum(pool_weights)
        if total <= 0:
            break
        marker = rng.uniform(0, total)
        running = 0.0
        selected_index = len(pool) - 1
        for index, weight in enumerate(pool_weights):
            running += weight
            if marker <= running:
                selected_index = index
                break
        chosen.append(pool.pop(selected_index))
        pool_weights.pop(selected_index)
    return chosen


def _posting_datetime(rng: random.Random, year: int) -> datetime:
    months = YEAR_PROFILES[year]["months"]
    month = rng.choices(
        months,
        weights=[POSTING_MONTH_WEIGHTS[month] for month in months],
        k=1,
    )[0]
    day = rng.randint(1, 28)
    hour = rng.randint(9, 18)
    minute = rng.choice([0, 15, 30, 45])
    return datetime(year, month, day, hour, minute)


def _salary_range(template: dict[str, Any], year: int) -> tuple[float, float]:
    # A small year-on-year adjustment keeps historical salary bands realistic.
    factor = 1.0 + 0.035 * (year - 2023)
    salary_min = round(template["salary_min_lpa"] * factor * 2) / 2
    salary_max = round(template["salary_max_lpa"] * factor * 2) / 2
    if salary_max <= salary_min:
        salary_max = salary_min + 1.0
    return salary_min, salary_max


def _family_targets(total_postings: int) -> dict[str, int]:
    """Spread a year's postings evenly across the configured job families."""
    base, remainder = divmod(total_postings, len(JOB_FAMILIES))
    return {
        family: base + (1 if index < remainder else 0)
        for index, family in enumerate(JOB_FAMILIES)
    }


def _assign_anchor_pairs(
    rng: random.Random,
    year: int,
    targets: dict[str, int],
) -> tuple[list[tuple[dict[str, Any], str]], dict[str, int]]:
    """Give every company one posting without exhausting a family quota.

    A small backtracking assignment is used because the two requirements
    interact: every company must appear in every year, and each year's family
    mix must stay stable enough that skill trends are not swamped by a random
    shift from engineering-heavy to analytics-heavy postings.
    """
    remaining = dict(targets)
    companies = list(COMPANIES)
    rng.shuffle(companies)
    companies.sort(key=lambda company: len(company["job_families"]))
    assignment: list[tuple[dict[str, Any], str]] = []

    def backtrack(index: int) -> bool:
        if index == len(companies):
            return True

        company = companies[index]
        eligible = [
            family
            for family in company["job_families"]
            if remaining[family] > 0
        ]
        rng.shuffle(eligible)
        eligible.sort(key=lambda family: remaining[family], reverse=True)

        for family in eligible:
            remaining[family] -= 1
            assignment.append((company, family))
            if backtrack(index + 1):
                return True
            assignment.pop()
            remaining[family] += 1
        return False

    if not backtrack(0):
        raise DatasetValidationError(
            f"Could not assign one anchor posting per company for {year}."
        )
    return assignment, remaining


def _build_description(
    company: dict[str, Any],
    template: dict[str, Any],
    job_family: str,
    location: str,
) -> str:
    return (
        f"{company['name']} is hiring a {template['title']} for its "
        f"{job_family} team in {location}. {template['description']}"
    )


def _build_jd_text(
    company: dict[str, Any],
    template: dict[str, Any],
    job_family: str,
    location: str,
    technical_skills: list[str],
    soft_skills: list[str],
) -> str:
    return (
        f"{company['name']} is hiring a {template['title']} for its "
        f"{job_family} team in {location}. You will {template['responsibilities']}. "
        f"The role requires {', '.join(technical_skills)}. Strong "
        f"{', '.join(soft_skills).lower()} skills are important. "
        f"Eligibility: CGPA {template['min_cgpa']:g}+, "
        f"{', '.join(template['eligible_departments'])}; "
        f"{template['education_level']}. {MOCK_DISCLAIMER}"
    )


def build_dataset(
    created_at: datetime | None = None,
    *,
    verbose: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Generate the full deterministic dataset and validate it.

    Returns ``(catalog_documents, posting_documents, validation_report)``.
    The generator is deterministic for a fixed ``created_at``.
    """
    generated_at = created_at or datetime.utcnow()
    rng = random.Random(RANDOM_SEED)

    catalog_documents = [
        {
            **skill,
            "source": "mock",
            "created_at": generated_at,
        }
        for skill in SKILL_CATALOG
    ]

    postings: list[dict[str, Any]] = []

    for year, profile in YEAR_PROFILES.items():
        posting_count = profile["postings"]
        if posting_count < len(COMPANIES):
            raise DatasetValidationError(
                f"{year} needs at least {len(COMPANIES)} postings to cover every company."
            )

        # Keep the family mix stable per year: one anchor posting per company
        # (guaranteeing company coverage), then fill the remaining family
        # quotas with companies weighted by their year-specific hiring profile.
        family_targets = _family_targets(posting_count)
        selected_pairs, remaining_targets = _assign_anchor_pairs(
            rng, year, family_targets
        )

        remaining_slots = posting_count - len(selected_pairs)
        if sum(remaining_targets.values()) != remaining_slots:
            raise DatasetValidationError(
                f"{year}: family quota mismatch after company anchors."
            )

        for job_family, count in remaining_targets.items():
            candidates = [
                company
                for company in COMPANIES
                if job_family in company["job_families"]
            ]
            if not candidates:
                raise DatasetValidationError(
                    f"{year}: no company supports job family {job_family!r}."
                )
            weights = [
                company["year_weights"][year] for company in candidates
            ]
            for _ in range(count):
                company = rng.choices(
                    candidates, weights=weights, k=1
                )[0]
                selected_pairs.append((company, job_family))

        rng.shuffle(selected_pairs)

        for index, (company, job_family) in enumerate(selected_pairs, start=1):
            template = rng.choice(ROLE_TEMPLATES[job_family])

            base_skills = normalize_skills(template["technical_skills"])
            optional_pool = [
                skill
                for skill in FAMILY_OPTIONAL_SKILLS[job_family]
                if skill not in base_skills
            ]
            optional_weights = [
                SKILL_TRENDS[skill][year] for skill in optional_pool
            ]
            # Always include the two strongest year-specific skills for the
            # family, then sample the rest by weight. This makes the historical
            # trend visible instead of leaving it entirely to chance, while
            # still producing varied postings.
            ranked_optional = sorted(
                zip(optional_pool, optional_weights),
                key=lambda item: (-item[1], item[0]),
            )
            featured = [skill for skill, _ in ranked_optional[:3]]
            remaining_pool = [
                skill for skill in optional_pool if skill not in featured
            ]
            remaining_weights = [
                SKILL_TRENDS[skill][year] for skill in remaining_pool
            ]
            optional_count = min(
                rng.randint(2, 4),
                max(3, len(optional_pool) // 2),
                len(optional_pool),
            )
            optional_count = max(optional_count, len(featured))
            optional_skills = featured + _weighted_sample_without_replacement(
                rng,
                remaining_pool,
                remaining_weights,
                optional_count - len(featured),
            )
            technical_skills = normalize_skills(base_skills + optional_skills)

            soft_pool = FAMILY_SOFT_SKILLS[job_family]
            soft_skills = normalize_skills(
                rng.sample(soft_pool, k=rng.randint(2, min(4, len(soft_pool))))
            )
            required_skills = technical_skills + soft_skills

            location = rng.choice(template["locations"])
            work_mode = rng.choice(template["work_modes"])
            posted_at = _posting_datetime(rng, year)
            salary_min, salary_max = _salary_range(template, year)

            postings.append(
                {
                    "external_id": (
                        f"mock-{year}-{company['slug']}-"
                        f"{_slugify(job_family)}-{index:03d}"
                    ),
                    "dataset_version": MARKET_DATASET_VERSION,
                    "source": "mock",
                    "company_name": company["name"],
                    "company_slug": company["slug"],
                    "company_industry": company["industry"],
                    "company_size": company["size"],
                    "company_hq": company["hq"],
                    "company_website": company["website"],
                    "job_title": template["title"],
                    "job_family": job_family,
                    "seniority": template["seniority"],
                    "hiring_type": template["hiring_type"],
                    "description": _build_description(
                        company, template, job_family, location
                    ),
                    "jd_text": _build_jd_text(
                        company,
                        template,
                        job_family,
                        location,
                        technical_skills,
                        soft_skills,
                    ),
                    "technical_skills": technical_skills,
                    "soft_skills": soft_skills,
                    "required_skills": required_skills,
                    "min_experience_years": template["min_experience_years"],
                    "education_level": template["education_level"],
                    "eligible_departments": list(template["eligible_departments"]),
                    "min_cgpa": template["min_cgpa"],
                    "location": location,
                    "work_mode": work_mode,
                    "salary_band": f"₹{salary_min:g}-{salary_max:g} LPA",
                    "salary_min_lpa": salary_min,
                    "salary_max_lpa": salary_max,
                    "posted_at": posted_at,
                    "year": posted_at.year,
                    "quarter": (posted_at.month - 1) // 3 + 1,
                    "month": posted_at.month,
                    "is_active": False,
                    "created_at": generated_at,
                }
            )

    report = validate_dataset(postings, catalog_documents, verbose=verbose)
    return catalog_documents, postings, report


def validate_dataset(
    postings: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """Validate every dataset invariant and return a report.

    Raises ``DatasetValidationError`` with a complete list of failures. The
    validation intentionally runs before any database write so a malformed
    dataset can never reach the analytics collection.
    """
    errors: list[str] = []

    catalog_names = {entry["name"] for entry in catalog}
    technical_catalog = {
        entry["name"] for entry in catalog if entry["is_technical"]
    }
    soft_catalog = {
        entry["name"] for entry in catalog if not entry["is_technical"]
    }

    if len(COMPANIES) != 15:
        errors.append(f"Expected 15 companies, configured {len(COMPANIES)}.")
    if len(JOB_FAMILIES) != 10:
        errors.append(f"Expected 10 job families, configured {len(JOB_FAMILIES)}.")
    if not 35 <= len(technical_catalog) <= 40:
        errors.append(
            f"Expected 35-40 technical skills, configured {len(technical_catalog)}."
        )
    if len(soft_catalog) != 12:
        errors.append(f"Expected 12 soft skills, configured {len(soft_catalog)}.")
    if set(SKILL_TRENDS) != catalog_names:
        missing = sorted(catalog_names - set(SKILL_TRENDS))
        extra = sorted(set(SKILL_TRENDS) - catalog_names)
        if missing:
            errors.append(f"SKILL_TRENDS missing: {', '.join(missing)}")
        if extra:
            errors.append(f"SKILL_TRENDS has unknown skills: {', '.join(extra)}")

    # Catalog integrity
    names: set[str] = set()
    slugs: set[str] = set()
    alias_lookup: dict[str, str] = {}
    for entry in catalog:
        name = entry["name"]
        slug = entry["slug"]
        if name in names:
            errors.append(f"Duplicate catalog skill name: {name}")
        names.add(name)
        if slug in slugs:
            errors.append(f"Duplicate catalog skill slug: {slug}")
        slugs.add(slug)
        if entry.get("source") != "mock":
            errors.append(f"Catalog skill {name} has non-mock source.")
        try:
            category = SkillCategory(entry["category"])
        except ValueError:
            errors.append(f"Catalog skill {name} has invalid category {entry['category']!r}.")
            continue
        if category == SkillCategory.SOFT_SKILL and entry["is_technical"]:
            errors.append(f"Soft skill {name} is marked technical.")
        if entry["is_technical"] and category == SkillCategory.SOFT_SKILL:
            errors.append(f"Technical skill {name} uses the Soft Skill category.")
        for key in [name, *entry.get("aliases", [])]:
            key = key.casefold()
            if key in alias_lookup and alias_lookup[key] != name:
                errors.append(
                    f"Skill alias collision: {key!r} belongs to both "
                    f"{alias_lookup[key]} and {name}."
                )
            alias_lookup[key] = name

    # Config integrity for role templates and family pools
    for family in JOB_FAMILIES:
        if family not in ROLE_TEMPLATES or not ROLE_TEMPLATES[family]:
            errors.append(f"No role templates configured for {family}.")
            continue
        if family not in FAMILY_OPTIONAL_SKILLS:
            errors.append(f"No optional skill pool configured for {family}.")
        if family not in FAMILY_SOFT_SKILLS:
            errors.append(f"No soft skill pool configured for {family}.")
        for template in ROLE_TEMPLATES[family]:
            for skill in template["technical_skills"]:
                if skill not in catalog_names:
                    errors.append(
                        f"{family} / {template['title']} uses unknown skill {skill!r}."
                    )
        for skill in FAMILY_OPTIONAL_SKILLS.get(family, []):
            if skill not in catalog_names:
                errors.append(f"{family} optional pool uses unknown skill {skill!r}.")
        for skill in FAMILY_SOFT_SKILLS.get(family, []):
            if skill not in soft_catalog:
                errors.append(f"{family} soft pool uses unknown skill {skill!r}.")

    for company in COMPANIES:
        if not company["website"].startswith("https://"):
            errors.append(f"{company['name']} website is not HTTPS.")
        if urlparse(company["website"]).hostname is None or not urlparse(
            company["website"]
        ).hostname.endswith(".example"):
            errors.append(f"{company['name']} website does not use .example.")
        if not company["job_families"]:
            errors.append(f"{company['name']} has no job families.")
        for family in company["job_families"]:
            if family not in JOB_FAMILIES:
                errors.append(f"{company['name']} has unknown family {family!r}.")
        if set(company["year_weights"]) != set(YEAR_PROFILES):
            errors.append(f"{company['name']} year weights do not cover every year.")

    expected_by_year = {
        year: profile["postings"] for year, profile in YEAR_PROFILES.items()
    }
    by_year: Counter[int] = Counter()
    companies_by_year: dict[int, set[str]] = defaultdict(set)
    family_years: dict[str, set[int]] = defaultdict(set)
    used_skills: set[str] = set()
    external_ids: set[str] = set()
    valid_seniority = {level.value for level in SeniorityLevel}
    valid_hiring_types = {value.value for value in HiringType}
    valid_work_modes = {mode.value for mode in WorkMode}
    company_by_slug = {company["slug"]: company for company in COMPANIES}

    for posting in postings:
        external_id = posting.get("external_id", "")
        if external_id in external_ids:
            errors.append(f"Duplicate external_id: {external_id}")
        external_ids.add(external_id)
        if not external_id.startswith("mock-"):
            errors.append(f"External ID does not look like mock data: {external_id}")

        if posting.get("source") != "mock":
            errors.append(f"{external_id}: source must be 'mock'.")
        if posting.get("dataset_version") != MARKET_DATASET_VERSION:
            errors.append(f"{external_id}: unexpected dataset_version.")
        if posting.get("is_active"):
            errors.append(f"{external_id}: historical postings must be inactive.")

        company = company_by_slug.get(posting.get("company_slug"))
        if company is None:
            errors.append(f"{external_id}: unknown company_slug.")
        else:
            if posting.get("company_name") != company["name"]:
                errors.append(f"{external_id}: company_name/slug mismatch.")
            if posting.get("job_family") not in company["job_families"]:
                errors.append(f"{external_id}: company does not hire for this family.")

        if posting.get("job_family") not in JOB_FAMILIES:
            errors.append(f"{external_id}: invalid job_family.")
        if posting.get("seniority") not in valid_seniority:
            errors.append(f"{external_id}: invalid seniority.")
        if posting.get("hiring_type") not in valid_hiring_types:
            errors.append(f"{external_id}: invalid hiring_type.")
        if posting.get("work_mode") not in valid_work_modes:
            errors.append(f"{external_id}: invalid work_mode.")

        posted_at = posting.get("posted_at")
        if not isinstance(posted_at, datetime):
            errors.append(f"{external_id}: posted_at is not a datetime.")
            continue
        if posting.get("year") != posted_at.year:
            errors.append(f"{external_id}: year does not match posted_at.")
        if posting.get("month") != posted_at.month:
            errors.append(f"{external_id}: month does not match posted_at.")
        expected_quarter = (posted_at.month - 1) // 3 + 1
        if posting.get("quarter") != expected_quarter:
            errors.append(f"{external_id}: quarter does not match posted_at.")
        if posted_at.year == MARKET_LATEST_YEAR and posted_at > datetime(
            MARKET_LATEST_YEAR, 10, 31, 23, 59, 59
        ):
            errors.append(f"{external_id}: 2026 posting is after 31 October.")
        if posted_at.year not in YEAR_PROFILES:
            errors.append(f"{external_id}: posting year outside configured years.")

        technical_skills = posting.get("technical_skills", [])
        soft_skills = posting.get("soft_skills", [])
        required_skills = posting.get("required_skills", [])
        if len(technical_skills) != len(set(technical_skills)):
            errors.append(f"{external_id}: duplicate technical skill.")
        if len(soft_skills) != len(set(soft_skills)):
            errors.append(f"{external_id}: duplicate soft skill.")
        if set(technical_skills) & set(soft_skills):
            errors.append(f"{external_id}: skill appears in both technical and soft lists.")
        if required_skills != technical_skills + soft_skills:
            errors.append(f"{external_id}: required_skills is not the union in order.")
        if len(required_skills) != len(set(required_skills)):
            errors.append(f"{external_id}: duplicate required skill.")
        for skill in technical_skills:
            if skill not in technical_catalog:
                errors.append(f"{external_id}: unknown technical skill {skill!r}.")
        for skill in soft_skills:
            if skill not in soft_catalog:
                errors.append(f"{external_id}: unknown soft skill {skill!r}.")
        used_skills.update(required_skills)

        if posting.get("salary_min_lpa", 0) > posting.get("salary_max_lpa", 0):
            errors.append(f"{external_id}: salary_min_lpa exceeds salary_max_lpa.")
        if not 0 <= posting.get("min_cgpa", -1) <= 10:
            errors.append(f"{external_id}: min_cgpa outside 0-10.")
        if not posting.get("eligible_departments"):
            errors.append(f"{external_id}: eligible_departments is empty.")
        if not posting.get("description") or not posting.get("jd_text"):
            errors.append(f"{external_id}: description/jd_text is empty.")

        by_year[posted_at.year] += 1
        companies_by_year[posted_at.year].add(posting.get("company_name", ""))
        family_years[posting.get("job_family", "")].add(posted_at.year)

    if len(postings) != EXPECTED_TOTAL_POSTINGS:
        errors.append(
            f"Expected {EXPECTED_TOTAL_POSTINGS} postings, generated {len(postings)}."
        )
    for year, expected_count in expected_by_year.items():
        if by_year[year] != expected_count:
            errors.append(
                f"{year}: expected {expected_count} postings, generated {by_year[year]}."
            )
    if set(by_year) != set(expected_by_year):
        errors.append("Generated years do not match YEAR_PROFILES.")

    for year in YEAR_PROFILES:
        missing_companies = {
            company["name"] for company in COMPANIES
        } - companies_by_year[year]
        if missing_companies:
            errors.append(
                f"{year}: missing postings for {', '.join(sorted(missing_companies))}."
            )

    for family in JOB_FAMILIES:
        years_present = family_years[family]
        if len(years_present) < 2:
            errors.append(
                f"{family}: expected multiple years, found {sorted(years_present)}."
            )

    unused_skills = catalog_names - used_skills
    if unused_skills:
        errors.append(f"Catalog skills never used: {', '.join(sorted(unused_skills))}")

    if errors:
        print("\nDataset validation failed:")
        for error in errors:
            print(f"  [FAIL] {error}")
        raise DatasetValidationError(
            f"Dataset validation failed with {len(errors)} error(s)."
        )

    report = {
        "total_postings": len(postings),
        "by_year": dict(sorted(by_year.items())),
        "companies": len(COMPANIES),
        "job_families": len(JOB_FAMILIES),
        "technical_skills": len(technical_catalog),
        "soft_skills": len(soft_catalog),
        "total_skills": len(catalog_names),
        "comparison_period": MARKET_COMPARISON_PERIOD,
        "is_partial_year": MARKET_IS_PARTIAL_YEAR,
        "latest_year": MARKET_LATEST_YEAR,
    }

    if verbose:
        print("\nDataset validation passed.")
        print(f"  Postings:        {report['total_postings']}")
        print(
            "  By year:         "
            + ", ".join(f"{year}={count}" for year, count in report["by_year"].items())
        )
        print(f"  Companies:       {report['companies']} (all covered every year)")
        print(f"  Job families:    {report['job_families']} (each appears in multiple years)")
        print(
            f"  Skills:          {report['total_skills']} total "
            f"({report['technical_skills']} technical, {report['soft_skills']} soft)"
        )
        print(f"  2026 coverage:   Jan-Oct (partial year)")
        print("  All invariants:  OK")

    return report


async def _protected_catalog_slugs(db) -> set[str]:
    """Skills referenced by non-mock postings; never delete these."""
    protected: set[str] = set()
    cursor = db.job_market_postings.find(
        {"source": {"$ne": "mock"}},
        {"technical_skills": 1, "soft_skills": 1},
    )
    async for posting in cursor:
        protected.update(posting.get("technical_skills", []))
        protected.update(posting.get("soft_skills", []))
    return protected


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the deterministic historical job-market demo dataset."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--force",
        action="store_true",
        help="Delete mock postings, refresh mock catalog entries, and regenerate.",
    )
    group.add_argument(
        "--reset",
        action="store_true",
        help="Delete only mock postings/catalog entries, then regenerate.",
    )
    args = parser.parse_args()

    created_at = datetime.utcnow()
    catalog, postings, report = build_dataset(created_at=created_at)

    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    db = client[settings.MONGODB_DB_NAME]

    try:
        await client.admin.command("ping")
        await ensure_market_indexes(db)

        posting_repo = JobMarketPostingRepository(db)
        catalog_repo = MarketSkillCatalogRepository(db)

        existing_mock = await posting_repo.count({"source": "mock"})
        if existing_mock and not (args.force or args.reset):
            print(
                f"job_market_postings already has {existing_mock} mock document(s); "
                "refusing to add duplicates. Use --force or --reset to regenerate."
            )
            return

        # Refuse a destructive operation if a non-mock record would collide
        # with a generated external_id. This should never happen because the
        # prefix is reserved for mock data, but the check is cheap insurance.
        generated_ids = [posting["external_id"] for posting in postings]
        collisions = await db.job_market_postings.count_documents(
            {"external_id": {"$in": generated_ids}, "source": {"$ne": "mock"}}
        )
        if collisions:
            print(
                f"Refusing to seed: {collisions} non-mock posting(s) already use "
                "generated external IDs."
            )
            return

        protected_slugs = await _protected_catalog_slugs(db) if args.reset else set()

        if args.force or args.reset:
            deleted_postings = await db.job_market_postings.delete_many(
                {"source": "mock"}
            )
            print(f"Deleted {deleted_postings.deleted_count} mock posting(s).")

            if args.reset:
                catalog_query: dict[str, Any] = {"source": "mock"}
                if protected_slugs:
                    catalog_query["name"] = {"$nin": sorted(protected_slugs)}
                deleted_catalog = await db.market_skill_catalog.delete_many(
                    catalog_query
                )
                print(
                    f"Deleted {deleted_catalog.deleted_count} mock catalog "
                    "entry/entries."
                )
                if protected_slugs:
                    print(
                        f"Preserved {len(protected_slugs)} catalog skill(s) "
                        "referenced by non-mock postings."
                    )

        # Upsert catalog entries. Never overwrite a future non-mock catalog
        # row: the dataset is replaceable, but real data must not be modified
        # by a mock seed run.
        skipped_catalog: list[str] = []
        for entry in catalog:
            existing = await db.market_skill_catalog.find_one(
                {"slug": entry["slug"]}, {"source": 1}
            )
            if existing is not None and existing.get("source") != "mock":
                skipped_catalog.append(entry["slug"])
                continue
            await db.market_skill_catalog.update_one(
                {"slug": entry["slug"], "source": "mock"},
                {"$set": entry},
                upsert=True,
            )
        print(f"Catalog ready: {len(catalog) - len(skipped_catalog)} skill(s).")
        if skipped_catalog:
            print(
                f"Preserved {len(skipped_catalog)} non-mock catalog "
                f"entry/entries: {', '.join(sorted(skipped_catalog))}"
            )

        inserted = await posting_repo.create_many(postings)
        print(f"Inserted {inserted} job market posting(s).")

        print("\nSeeded dataset summary:")
        print(f"  Dataset version: {MARKET_DATASET_VERSION}")
        print(f"  Comparison:      {report['comparison_period']} (2026 partial year)")
        for year, count in report["by_year"].items():
            print(f"  {year}: {count} postings")
        print(f"  Companies:       {report['companies']}")
        print(f"  Job families:    {report['job_families']}")
        print(
            f"  Skills:          {report['total_skills']} "
            f"({report['technical_skills']} technical, {report['soft_skills']} soft)"
        )

        total_mock = await posting_repo.count({"source": "mock"})
        total_non_mock = await posting_repo.count({"source": {"$ne": "mock"}})
        print(
            f"\nCollection totals: job_market_postings mock={total_mock}, "
            f"non_mock={total_non_mock}; "
            f"market_skill_catalog={await catalog_repo.count()}."
        )
        print("Operational placement collections were not modified.")
    except PyMongoError as exc:
        print(f"MongoDB operation failed: {exc}")
        print(
            "The generator and validation completed, but live seeding did not. "
            "Start MongoDB and re-run this script."
        )
        raise SystemExit(1) from exc
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
