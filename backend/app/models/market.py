"""Models for the historical job-market analytics dataset.

This collection is deliberately separate from ``placement_drives``:

- ``placement_drives`` is operational data: live drives, deadlines,
  applications, eligibility and assessment linkage.
- ``job_market_postings`` is a historical market-intelligence dataset used by
  the Trending Skills & Company Requirements dashboard.

The dataset is mock/demo data. Every document carries ``source="mock"`` and a
``dataset_version`` so future real postings can be added without rewriting the
frontend or silently mixing sources.
"""
from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.base import MongoBaseModel


MARKET_DATASET_VERSION = "2026.11"
MARKET_LATEST_YEAR = 2026
MARKET_COMPARISON_PERIOD = "Jan-Oct"
MARKET_IS_PARTIAL_YEAR = True


class SkillCategory(str, Enum):
    PROGRAMMING_LANGUAGE = "Programming Language"
    FRONTEND = "Frontend"
    BACKEND = "Backend"
    DATABASE = "Database"
    DATA_ML = "Data & ML"
    CLOUD_DEVOPS = "Cloud & DevOps"
    CYBERSECURITY = "Cybersecurity"
    TESTING = "Testing"
    SOFT_SKILL = "Soft Skill"


class JobFamily(str, Enum):
    SOFTWARE_ENGINEERING = "Software Engineering"
    FRONTEND_ENGINEERING = "Frontend Engineering"
    BACKEND_ENGINEERING = "Backend Engineering"
    DATA_ANALYTICS = "Data & Analytics"
    AI_ML = "AI & Machine Learning"
    CLOUD_DEVOPS = "Cloud & DevOps"
    CYBERSECURITY = "Cybersecurity"
    QA_AUTOMATION = "QA & Automation"
    BUSINESS_ANALYSIS = "Business Analysis"
    EMBEDDED_ROBOTICS = "Embedded & Robotics"


class SeniorityLevel(str, Enum):
    ENTRY = "Entry"
    ASSOCIATE = "Associate"
    MID = "Mid"


class HiringType(str, Enum):
    FULL_TIME = "Full-time"
    INTERNSHIP = "Internship"


class WorkMode(str, Enum):
    ON_SITE = "On-site"
    HYBRID = "Hybrid"
    REMOTE = "Remote"


class MarketSkillCatalogInDB(MongoBaseModel):
    """Canonical skill entry used to keep trend counts from fragmenting.

    ``source`` is included even though the Phase 2 spec lists only the core
    fields, so ``--reset`` can delete mock catalog entries without touching
    future real catalog entries.
    """

    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    category: SkillCategory
    is_technical: bool
    aliases: list[str] = Field(default_factory=list)
    source: str = "mock"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("name", "slug")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Skill name and slug must not be blank.")
        return value

    @model_validator(mode="after")
    def _validate_skill(self) -> "MarketSkillCatalogInDB":
        if self.category == SkillCategory.SOFT_SKILL and self.is_technical:
            raise ValueError("Soft skills must set is_technical=False.")
        if self.is_technical and self.category == SkillCategory.SOFT_SKILL:
            raise ValueError("Technical skills cannot use the Soft Skill category.")
        if len(self.aliases) != len({alias.casefold() for alias in self.aliases}):
            raise ValueError("Skill aliases must be unique within a catalog entry.")
        return self


class JobMarketPostingInDB(MongoBaseModel):
    """One historical job posting in the market-intelligence dataset."""

    external_id: str = Field(min_length=1, max_length=200)
    dataset_version: str = MARKET_DATASET_VERSION
    source: str = "mock"

    company_name: str = Field(min_length=1, max_length=200)
    company_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    company_industry: str = Field(min_length=1, max_length=200)
    company_size: str = Field(min_length=1, max_length=100)
    company_hq: str = Field(min_length=1, max_length=100)
    company_website: str = Field(min_length=1, max_length=500)

    job_title: str = Field(min_length=1, max_length=200)
    job_family: JobFamily
    seniority: SeniorityLevel
    hiring_type: HiringType
    description: str = Field(min_length=1)
    jd_text: str = Field(min_length=1)

    technical_skills: list[str] = Field(min_length=1)
    soft_skills: list[str] = Field(min_length=1)
    required_skills: list[str] = Field(min_length=1)

    min_experience_years: float = Field(ge=0, le=50)
    education_level: str = Field(min_length=1, max_length=200)
    eligible_departments: list[str] = Field(min_length=1)
    min_cgpa: float = Field(ge=0, le=10)

    location: str = Field(min_length=1, max_length=100)
    work_mode: WorkMode
    salary_band: str = Field(min_length=1, max_length=100)
    salary_min_lpa: float = Field(ge=0)
    salary_max_lpa: float = Field(ge=0)

    posted_at: datetime
    year: int = Field(ge=2000, le=2100)
    quarter: int = Field(ge=1, le=4)
    month: int = Field(ge=1, le=12)

    is_active: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator(
        "technical_skills",
        "soft_skills",
        "required_skills",
        "eligible_departments",
    )
    @classmethod
    def _strip_list_values(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("Skill and department lists must not contain blank values.")
        return cleaned

    @model_validator(mode="after")
    def _validate_posting(self) -> "JobMarketPostingInDB":
        if len(self.technical_skills) != len(set(self.technical_skills)):
            raise ValueError("technical_skills contains duplicates.")
        if len(self.soft_skills) != len(set(self.soft_skills)):
            raise ValueError("soft_skills contains duplicates.")
        if set(self.technical_skills) & set(self.soft_skills):
            raise ValueError("A skill cannot appear in both technical_skills and soft_skills.")
        if self.required_skills != self.technical_skills + self.soft_skills:
            raise ValueError(
                "required_skills must equal technical_skills followed by soft_skills."
            )
        if len(self.required_skills) != len(set(self.required_skills)):
            raise ValueError("required_skills contains duplicates.")

        if self.year != self.posted_at.year:
            raise ValueError("year must match posted_at.year.")
        if self.month != self.posted_at.month:
            raise ValueError("month must match posted_at.month.")
        expected_quarter = (self.posted_at.month - 1) // 3 + 1
        if self.quarter != expected_quarter:
            raise ValueError("quarter must match posted_at.month.")
        if self.salary_min_lpa > self.salary_max_lpa:
            raise ValueError("salary_min_lpa cannot exceed salary_max_lpa.")

        if self.source == "mock":
            host = urlparse(self.company_website).hostname or ""
            if not host.endswith(".example"):
                raise ValueError("Mock company websites must use a reserved .example domain.")
            if (
                self.posted_at.year == MARKET_LATEST_YEAR
                and self.posted_at > datetime(MARKET_LATEST_YEAR, 10, 31, 23, 59, 59)
            ):
                raise ValueError(
                    f"{MARKET_LATEST_YEAR} mock postings must be dated on or before "
                    "31 October."
                )
        return self


# ---------------------------------------------------------------------------
# Phase 3 — TPO market analytics API response models
#
# These are aggregate-only response contracts for the Trending Skills &
# Company Requirements dashboard. They never expose raw postings or job
# descriptions, and they are stable on purpose: the Phase 4 frontend consumes
# this shape, so a future real-market data source must keep it unchanged.
# ---------------------------------------------------------------------------

TrendClassification = Literal["rising", "declining", "stable", "emerging"]


class MarketPeriodInfo(BaseModel):
    """A comparison window, e.g. January-October 2026."""

    year: int
    start_month: int = Field(ge=1, le=12)
    end_month: int = Field(ge=1, le=12)
    label: str


class MarketMeta(BaseModel):
    """Dataset identity and comparison-window metadata for a market response."""

    source: str
    dataset_version: str
    is_mock_data: bool
    comparison_period: str
    is_partial_year: bool
    disclaimer: str
    current_period: MarketPeriodInfo | None = None
    previous_period: MarketPeriodInfo | None = None
    comparison_comparable: bool
    filtered_years: list[int]


class MarketSkillDemand(BaseModel):
    """Demand for one skill within some posting population."""

    name: str
    slug: str
    category: str | None = None
    posting_count: int = Field(ge=0)
    demand_pct: float = Field(ge=0, le=100)


class MarketSummary(BaseModel):
    total_postings: int = Field(ge=0)
    company_count: int = Field(ge=0)
    distinct_skill_count: int = Field(ge=0)
    most_demanded_skill: MarketSkillDemand | None = None
    yoy_posting_growth_pct: float | None = None


class TrendingSkill(BaseModel):
    name: str
    slug: str
    category: str | None = None
    is_technical: bool
    posting_count: int = Field(ge=0)
    demand_pct: float = Field(ge=0, le=100)
    trend_score: float
    trend: TrendClassification | None = None
    yoy_growth_pct: float | None = None
    current_period_count: int = Field(ge=0)
    previous_period_count: int = Field(ge=0)
    yearly_counts: dict[int, int]
    yearly_demand_pct: dict[int, float]


class YearlySkillDemand(BaseModel):
    """One year of a skill's historical demand series."""

    year: int
    posting_count: int = Field(ge=0)
    demand_pct: float = Field(ge=0, le=100)
    yoy_growth_pct: float | None = None


class HistoricalSkillTrend(BaseModel):
    name: str
    slug: str
    category: str | None = None
    years: list[YearlySkillDemand]


class EmergingSkill(BaseModel):
    name: str
    slug: str
    category: str | None = None
    current_period_count: int = Field(ge=0)
    current_period_demand_pct: float = Field(ge=0, le=100)
    previous_period_count: int = Field(ge=0)
    trend: Literal["emerging"]


class CompanyMarketAnalytics(BaseModel):
    company_name: str
    company_slug: str
    industry: str
    posting_count: int = Field(ge=0)
    posting_share_pct: float = Field(ge=0, le=100)
    top_skills: list[MarketSkillDemand]
    yearly_counts: dict[int, int]


class JobFamilyMarketAnalytics(BaseModel):
    job_family: str
    posting_count: int = Field(ge=0)
    posting_share_pct: float = Field(ge=0, le=100)
    top_skills: list[MarketSkillDemand]
    yearly_counts: dict[int, int]


class CompanyFilterOption(BaseModel):
    slug: str
    name: str


class MarketFiltersResponse(BaseModel):
    """Filter options derived live from the market dataset (never hardcoded)."""

    years: list[int]
    companies: list[CompanyFilterOption]
    job_families: list[str]
    locations: list[str]
    skill_categories: list[str]


class MarketAnalyticsResponse(BaseModel):
    meta: MarketMeta
    summary: MarketSummary
    trending_skills: list[TrendingSkill]
    historical_trends: list[HistoricalSkillTrend]
    emerging_skills: list[EmergingSkill]
    companies: list[CompanyMarketAnalytics]
    job_families: list[JobFamilyMarketAnalytics]


# ---------------------------------------------------------------------------
# Phase 5 — entity (company / job-family) comparison
#
# One aggregate-only endpoint powers both company-to-company and
# job-family-to-job-family comparisons. Unlike the dashboard response above
# (which caps each entity at its top-10 skills), this returns EVERY skill the
# entity requires so shared/unique skills can be identified, plus the
# per-entity trend classification of each skill (same math as TrendingSkill)
# and the technical/soft split of the entity's skill demand.
# ---------------------------------------------------------------------------

ComparisonDimension = Literal["company", "job_family"]


class ComparisonEntityAnalytics(BaseModel):
    """Full skill analytics for ONE entity (a company or a job family)."""

    entity_key: str
    entity_label: str
    industry: str | None = None
    posting_count: int = Field(ge=0)
    posting_share_pct: float = Field(ge=0, le=100)
    # Skill-demand instances: one posting requiring one skill = 1 instance
    # (a posting can contribute to both types). Shares use the instance total.
    tech_skill_instances: int = Field(ge=0)
    soft_skill_instances: int = Field(ge=0)
    tech_share_pct: float = Field(ge=0, le=100)
    soft_share_pct: float = Field(ge=0, le=100)
    yearly_counts: dict[int, int]
    # Every skill the entity requires (posting_count > 0 within the filtered
    # population), sorted by posting_count desc then name. demand_pct uses the
    # ENTITY's own postings as the denominator. Entities with no postings in
    # the filtered population come back empty so the UI can say so explicitly.
    skills: list[TrendingSkill]


class MarketComparisonResponse(BaseModel):
    meta: MarketMeta
    dimension: ComparisonDimension
    entities: list[ComparisonEntityAnalytics]
