"""TPO market analytics for the Trending Skills & Company Requirements dashboard.

Reads ONLY the historical job-market dataset collections (``job_market_postings``
+ ``market_skill_catalog``) — never ``placement_drives`` or any other
operational placement collection — so mock market data can never inflate (or
be inflated by) live placement statistics.

The dataset behind this service is mock/demo data (``source="mock"``,
``dataset_version="2026.11"``) whose 2026 slice is deliberately partial
(January-October only, see ``MARKET_COMPARISON_PERIOD``). Every response
carries that metadata plus an explicit mock-data disclaimer so partial-year
numbers are never mistaken for full-year reality.

Trend math (single source of truth for every section of the response):

Demand percentage
    ``demand_pct = (distinct postings requiring the skill / total filtered
    postings) * 100`` — one shared denominator per response. A posting is
    counted at most once per skill: Phase 2 guarantees per-posting skill lists
    are duplicate-free and the aggregator counts list membership once per
    posting.

Year-over-year growth
    ``growth = (current - previous) / previous * 100``, computed between
    COMPARABLE windows. When the latest filtered year is the dataset's partial
    year (2026, January-October), both the current and previous windows are
    January-October — never full-2026 vs full-2025. Any other latest year
    compares full calendar years. ``previous == 0`` yields ``None`` (handled
    by the emerging classification), never a ZeroDivisionError.

Trend score
    Weighted mean of the skill's year-wise DEMAND SHARES (percentages of that
    year's postings, not raw counts)::

        score = sum(w(year) * demand_pct(skill, year))

    with calendar weights 2026: 0.40, 2025: 0.30, 2024: 0.20, 2023: 0.10
    (generalised to ``(0.40, 0.30, 0.20, 0.10)`` by offset from the dataset's
    latest year), normalised over the years present in the filtered
    population. If every present year is older than the 4-year window the
    weights fall back to uniform.

Classification
    previous == 0 and current > 0 -> "emerging"
    growth >= +10%                -> "rising"
    growth <= -10%                -> "declining"
    otherwise                     -> "stable"

    A skill with no comparable previous period (the previous window has no
    postings after filtering, e.g. the range or another filter excluded it)
    gets ``None`` — a skill must never be labelled "emerging" merely because a
    filter excluded the period it used to appear in.

Filter semantics
    ``year_from/year_to/company/job_family/location`` filter the POSTING
    population (the shared demand-percentage denominator). ``skill_category``
    and ``technical_only`` narrow which SKILLS are analysed; they never change
    the posting denominator, and they may be combined (intersection). The
    same filtered population feeds the summary, trending, historical,
    emerging, company and job-family sections.

Comparison endpoint (``dimension`` = company | job_family)
    One method serves company-to-company and job-family-to-job-family
    comparisons. The dimension's own filter is REPLACED by the entity
    selection (comparing companies ignores the single-company filter;
    comparing families ignores the single-family filter); every other
    posting filter (year range, location, and the opposite dimension's
    filter) still applies. Skill-scope filters never apply: comparisons
    always analyse all skill types so the technical/soft split is visible.
    Each entity gets the SAME trend math as the dashboard (window rules,
    classification, trend score) but with the entity's own postings as the
    demand denominator, and entity-level comparability (an entity whose
    previous comparable window has no postings reports ``trend=None``,
    never a fake classification). ``posting_share_pct`` is the entity's
    share of the whole filtered population, not of the selected group.

Performance
    One projected find (aggregate-level fields only — no descriptions or JD
    text) bounded at ``_MAX_POSTINGS`` plus one small catalog read; all
    aggregation is a single in-memory pass over the filtered rows.
"""
import calendar
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.market import (
    MARKET_COMPARISON_PERIOD,
    MARKET_DATASET_VERSION,
    MARKET_IS_PARTIAL_YEAR,
    MARKET_LATEST_YEAR,
    ComparisonEntityAnalytics,
    CompanyFilterOption,
    CompanyMarketAnalytics,
    EmergingSkill,
    HistoricalSkillTrend,
    JobFamilyMarketAnalytics,
    MarketAnalyticsResponse,
    MarketComparisonResponse,
    MarketFiltersResponse,
    MarketMeta,
    MarketPeriodInfo,
    MarketSkillDemand,
    MarketSummary,
    TrendingSkill,
    YearlySkillDemand,
)
from app.repositories.job_posting_repository import (
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)

logger = logging.getLogger(__name__)

# Bounded in-memory processing: the Phase 1 recommendation for analytics reads.
_MAX_POSTINGS = 5000
_MAX_CATALOG_ENTRIES = 1000
_DEFAULT_SKILL_LIMIT = 10
_TOP_SKILLS_PER_ENTITY = 10  # per company / per job family
_MAX_COMPARISON_ENTITIES = 6  # bounds the comparison response size

# Calendar-year demand-share weights, newest first (see trend score above).
_TREND_WEIGHTS_BY_YEAR_OFFSET = (0.40, 0.30, 0.20, 0.10)

# MARKET_COMPARISON_PERIOD: the partial-year window (January-October).
_PARTIAL_WINDOW = (1, 10)
_FULL_WINDOW = (1, 12)

_DISCLAIMER = (
    "Demo dataset: figures come from the PLACER fictional mock job-market data "
    "and are not verified real-world hiring statistics."
)

# Aggregate-level fields only — job descriptions and JD text are never read.
_POSTING_PROJECTION: dict[str, Any] = {
    "_id": 0,
    "company_name": 1,
    "company_slug": 1,
    "company_industry": 1,
    "job_family": 1,
    "technical_skills": 1,
    "soft_skills": 1,
    "location": 1,
    "source": 1,
    "dataset_version": 1,
    "year": 1,
    "month": 1,
}


class MarketQueryError(ValueError):
    """Invalid market-analytics query values (company/location/year range)."""


@dataclass(frozen=True)
class MarketQuery:
    """Validated-shape query parameters for the market analytics endpoint.

    Enum-style values arrive as plain strings (the router unwraps them) so the
    service layer stays decoupled from request parsing.
    """

    year_from: int | None = None
    year_to: int | None = None
    company: str | None = None
    job_family: str | None = None
    location: str | None = None
    skill_category: str | None = None
    technical_only: bool = False
    sort: str = "trending"
    limit: int = _DEFAULT_SKILL_LIMIT


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a database)
# ---------------------------------------------------------------------------


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole > 0 else 0.0


def _growth_pct(current: int, previous: int) -> float | None:
    """YoY growth between two comparable counts; None when previous is zero."""
    if previous == 0:
        return None
    return round(100.0 * (current - previous) / previous, 1)


def _classify_trend(current: int, previous: int, comparable: bool) -> str | None:
    """Shared trend classification (see module docstring for thresholds)."""
    if not comparable:
        return None
    if previous == 0:
        return "emerging" if current > 0 else None
    growth = 100.0 * (current - previous) / previous
    if growth >= 10.0:
        return "rising"
    if growth <= -10.0:
        return "declining"
    return "stable"


def _slugify(name: str) -> str:
    """Fallback slug for a skill name missing from the catalog."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or "skill"


def _period_info(year: int, window: tuple[int, int]) -> MarketPeriodInfo:
    start, end = window
    label = f"Full year {year}" if end == 12 else f"Jan-{calendar.month_abbr[end]} {year}"
    return MarketPeriodInfo(year=year, start_month=start, end_month=end, label=label)


def _is_partial_latest(latest_year: int) -> bool:
    """True when the latest filtered year is the dataset's partial year."""
    return latest_year == MARKET_LATEST_YEAR and MARKET_IS_PARTIAL_YEAR


def _window_count(full: Counter, jan_oct: Counter, year: int, partial: bool) -> int:
    """A skill's posting count inside a year, restricted to the window."""
    return (jan_oct if partial else full).get(year, 0)


def _trend_score(skill_yearly: Counter, yearly_totals: Counter, years: list[int]) -> float:
    """Weighted mean of year-wise demand shares (see module docstring)."""
    weights: dict[int, float] = {}
    for year in years:
        offset = MARKET_LATEST_YEAR - year
        weights[year] = (
            _TREND_WEIGHTS_BY_YEAR_OFFSET[offset]
            if 0 <= offset < len(_TREND_WEIGHTS_BY_YEAR_OFFSET)
            else 0.0
        )
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        # Every present year is outside the 4-year weighting window — fall
        # back to equal weighting instead of producing a zero score.
        weights = {year: 1.0 for year in years}
        weight_sum = float(len(years))
    score = 0.0
    for year in years:
        share = _pct(skill_yearly.get(year, 0), yearly_totals.get(year, 0))
        score += (weights[year] / weight_sum) * share
    return round(score, 2)


class _SkillScope:
    """Decides which of a posting's skills fall inside the skill filters."""

    def __init__(self, catalog_by_name: dict[str, Any], query: MarketQuery):
        self._technical_only = query.technical_only
        self._allowed: set[str] | None = None
        if query.skill_category is not None:
            self._allowed = {
                name
                for name, doc in catalog_by_name.items()
                if doc.category.value == query.skill_category
            }

    def select(self, row: dict[str, Any]) -> list[str]:
        technical = row.get("technical_skills") or []
        soft = row.get("soft_skills") or []
        names = technical if self._technical_only else technical + soft
        if self._allowed is not None:
            names = [name for name in names if name in self._allowed]
        return names


def _identity_for(name: str, catalog_by_name: dict[str, Any]) -> tuple[str, str | None, bool]:
    """(slug, category, is_technical) for a skill name.

    Skills missing from the catalog (defensive: cannot happen with the Phase 2
    dataset) get a slugified fallback and are treated as technical.
    """
    doc = catalog_by_name.get(name)
    if doc is not None:
        return doc.slug, doc.category.value, doc.is_technical
    return _slugify(name), None, True


# ---------------------------------------------------------------------------
# In-memory aggregation over the filtered postings (single pass)
# ---------------------------------------------------------------------------


@dataclass
class _Aggregate:
    total_postings: int = 0
    years: list[int] = field(default_factory=list)
    yearly_totals: Counter = field(default_factory=Counter)
    yearly_jan_oct_totals: Counter = field(default_factory=Counter)
    skill_totals: Counter = field(default_factory=Counter)
    skill_yearly: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    skill_yearly_jan_oct: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    companies: dict[str, dict[str, Any]] = field(default_factory=dict)
    families: dict[str, dict[str, Any]] = field(default_factory=dict)
    latest_year: int | None = None
    current_window: tuple[int, int] = _FULL_WINDOW
    current_total: int = 0
    previous_total: int = 0
    comparable: bool = False


def _aggregate_postings(
    rows: list[dict[str, Any]],
    catalog_by_name: dict[str, Any],
    query: MarketQuery,
) -> _Aggregate:
    agg = _Aggregate()
    scope = _SkillScope(catalog_by_name, query)

    for row in rows:
        year = int(row["year"])
        month = int(row["month"])

        agg.yearly_totals[year] += 1
        if month <= 10:
            agg.yearly_jan_oct_totals[year] += 1

        company = agg.companies.setdefault(
            row["company_slug"],
            {
                "name": row["company_name"],
                "industry": row["company_industry"],
                "count": 0,
                "yearly": Counter(),
                "skills": Counter(),
            },
        )
        company["count"] += 1
        company["yearly"][year] += 1

        family = agg.families.setdefault(
            row["job_family"],
            {"count": 0, "yearly": Counter(), "skills": Counter()},
        )
        family["count"] += 1
        family["yearly"][year] += 1

        # A skill is counted once per posting: the per-posting skill lists are
        # duplicate-free by model invariant, so list membership is distinct.
        for name in scope.select(row):
            agg.skill_totals[name] += 1
            agg.skill_yearly[name][year] += 1
            if month <= 10:
                agg.skill_yearly_jan_oct[name][year] += 1
            company["skills"][name] += 1
            family["skills"][name] += 1

    agg.total_postings = len(rows)
    agg.years = sorted(agg.yearly_totals)
    agg.latest_year = agg.years[-1] if agg.years else None

    if agg.latest_year is not None:
        agg.current_window = (
            _PARTIAL_WINDOW if _is_partial_latest(agg.latest_year) else _FULL_WINDOW
        )
        partial = agg.current_window[1] != 12
        agg.current_total = _window_count(
            agg.yearly_totals, agg.yearly_jan_oct_totals, agg.latest_year, partial
        )
        agg.previous_total = _window_count(
            agg.yearly_totals, agg.yearly_jan_oct_totals, agg.latest_year - 1, partial
        )
        # Comparable only when the previous window actually has postings in
        # the filtered population — this is what stops a filter from turning
        # every skill into a fake "emerging" trend.
        agg.comparable = agg.previous_total > 0

    return agg


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------


def _skill_record(
    name: str,
    agg: _Aggregate,
    catalog_by_name: dict[str, Any],
) -> dict[str, Any]:
    slug, category, is_technical = _identity_for(name, catalog_by_name)
    full = agg.skill_yearly[name]
    jan_oct = agg.skill_yearly_jan_oct[name]
    partial = agg.current_window[1] != 12
    current = _window_count(full, jan_oct, agg.latest_year, partial)
    previous = _window_count(full, jan_oct, agg.latest_year - 1, partial)
    return {
        "name": name,
        "slug": slug,
        "category": category,
        "is_technical": is_technical,
        "posting_count": agg.skill_totals[name],
        "demand_pct": _pct(agg.skill_totals[name], agg.total_postings),
        "trend_score": _trend_score(full, agg.yearly_totals, agg.years),
        "trend": _classify_trend(current, previous, agg.comparable),
        "yoy_growth_pct": _growth_pct(current, previous),
        "current_period_count": current,
        "previous_period_count": previous,
        "yearly_counts": {year: full.get(year, 0) for year in agg.years},
        "yearly_demand_pct": {
            year: _pct(full.get(year, 0), agg.yearly_totals.get(year, 0))
            for year in agg.years
        },
        "_full": full,
        "_jan_oct": jan_oct,
    }


def _trending_skill_from_record(record: dict[str, Any]) -> TrendingSkill:
    """Convert an internal ``_skill_record`` dict into the shared model.

    Used by both the dashboard response and the comparison endpoint so the
    trend math is assembled in exactly one place.
    """
    return TrendingSkill(
        name=record["name"],
        slug=record["slug"],
        category=record["category"],
        is_technical=record["is_technical"],
        posting_count=record["posting_count"],
        demand_pct=record["demand_pct"],
        trend_score=record["trend_score"],
        trend=record["trend"],
        yoy_growth_pct=record["yoy_growth_pct"],
        current_period_count=record["current_period_count"],
        previous_period_count=record["previous_period_count"],
        yearly_counts=record["yearly_counts"],
        yearly_demand_pct=record["yearly_demand_pct"],
    )


def _build_meta(
    agg: _Aggregate, source: str, dataset_version: str
) -> MarketMeta:
    """Dataset identity + comparison-window metadata shared by every response."""
    return MarketMeta(
        source=source,
        dataset_version=dataset_version,
        is_mock_data=source == "mock",
        comparison_period=MARKET_COMPARISON_PERIOD,
        is_partial_year=MARKET_IS_PARTIAL_YEAR,
        disclaimer=_DISCLAIMER,
        current_period=(
            _period_info(agg.latest_year, agg.current_window)
            if agg.latest_year is not None
            else None
        ),
        previous_period=(
            _period_info(agg.latest_year - 1, agg.current_window)
            if agg.latest_year is not None
            else None
        ),
        comparison_comparable=agg.comparable,
        filtered_years=agg.years,
    )


def _top_skills(
    skill_counts: Counter,
    denominator: int,
    catalog_by_name: dict[str, Any],
) -> list[MarketSkillDemand]:
    ordered = sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))
    top = []
    for name, count in ordered[:_TOP_SKILLS_PER_ENTITY]:
        slug, category, _ = _identity_for(name, catalog_by_name)
        top.append(
            MarketSkillDemand(
                name=name,
                slug=slug,
                category=category,
                posting_count=count,
                demand_pct=_pct(count, denominator),
            )
        )
    return top


def _build_response(
    agg: _Aggregate,
    catalog_by_name: dict[str, Any],
    query: MarketQuery,
    source: str,
    dataset_version: str,
) -> MarketAnalyticsResponse:
    years = agg.years
    records = {
        name: _skill_record(name, agg, catalog_by_name) for name in agg.skill_totals
    }

    # --- Trending skills (sorted + limited) -------------------------------
    if query.sort == "demand":
        ordered = sorted(
            records.values(), key=lambda r: (-r["posting_count"], r["name"])
        )
    else:  # "trending" — highest weighted demand-share score first
        ordered = sorted(
            records.values(),
            key=lambda r: (-r["trend_score"], -r["posting_count"], r["name"]),
        )
    trending = [_trending_skill_from_record(r) for r in ordered[: query.limit]]

    # --- Historical trends (every in-scope skill, all filtered years) ------
    historical = []
    for r in sorted(records.values(), key=lambda r: (-r["posting_count"], r["name"])):
        year_items = []
        for year in years:
            # Yearly counts are calendar-year totals for display; growth is
            # always computed between comparable windows (Jan-Oct pair for the
            # dataset's partial latest year, full years otherwise).
            partial = year == MARKET_LATEST_YEAR and MARKET_IS_PARTIAL_YEAR
            current = _window_count(r["_full"], r["_jan_oct"], year, partial)
            previous = _window_count(r["_full"], r["_jan_oct"], year - 1, partial)
            year_items.append(
                YearlySkillDemand(
                    year=year,
                    posting_count=r["yearly_counts"][year],
                    demand_pct=r["yearly_demand_pct"][year],
                    yoy_growth_pct=_growth_pct(current, previous),
                )
            )
        historical.append(
            HistoricalSkillTrend(
                name=r["name"], slug=r["slug"], category=r["category"], years=year_items
            )
        )

    # --- Emerging skills ---------------------------------------------------
    emerging = [
        EmergingSkill(
            name=r["name"],
            slug=r["slug"],
            category=r["category"],
            current_period_count=r["current_period_count"],
            current_period_demand_pct=_pct(
                r["current_period_count"], agg.current_total
            ),
            previous_period_count=r["previous_period_count"],
            trend="emerging",
        )
        for r in sorted(
            records.values(), key=lambda r: (-r["current_period_count"], r["name"])
        )
        if r["trend"] == "emerging"
    ]

    # --- Summary -----------------------------------------------------------
    most_demanded = None
    if records:
        best = min(records.values(), key=lambda r: (-r["posting_count"], r["name"]))
        most_demanded = MarketSkillDemand(
            name=best["name"],
            slug=best["slug"],
            category=best["category"],
            posting_count=best["posting_count"],
            demand_pct=best["demand_pct"],
        )
    summary = MarketSummary(
        total_postings=agg.total_postings,
        company_count=len(agg.companies),
        distinct_skill_count=len(records),
        most_demanded_skill=most_demanded,
        yoy_posting_growth_pct=_growth_pct(agg.current_total, agg.previous_total),
    )

    # --- Company analytics -------------------------------------------------
    company_items = []
    for slug in sorted(agg.companies, key=lambda s: (-agg.companies[s]["count"], s)):
        company = agg.companies[slug]
        company_items.append(
            CompanyMarketAnalytics(
                company_name=company["name"],
                company_slug=slug,
                industry=company["industry"],
                posting_count=company["count"],
                posting_share_pct=_pct(company["count"], agg.total_postings),
                top_skills=_top_skills(
                    company["skills"], company["count"], catalog_by_name
                ),
                yearly_counts={
                    year: company["yearly"].get(year, 0) for year in years
                },
            )
        )

    # --- Job-family analytics ---------------------------------------------
    family_items = []
    for family_name in sorted(agg.families, key=lambda f: (-agg.families[f]["count"], f)):
        family = agg.families[family_name]
        family_items.append(
            JobFamilyMarketAnalytics(
                job_family=family_name,
                posting_count=family["count"],
                posting_share_pct=_pct(family["count"], agg.total_postings),
                top_skills=_top_skills(
                    family["skills"], family["count"], catalog_by_name
                ),
                yearly_counts={year: family["yearly"].get(year, 0) for year in years},
            )
        )

    meta = _build_meta(agg, source, dataset_version)

    return MarketAnalyticsResponse(
        meta=meta,
        summary=summary,
        trending_skills=trending,
        historical_trends=historical,
        emerging_skills=emerging,
        companies=company_items,
        job_families=family_items,
    )


# ---------------------------------------------------------------------------
# Service (Router -> Service -> Repository)
# ---------------------------------------------------------------------------


class MarketAnalyticsService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.postings = JobMarketPostingRepository(db)
        self.catalog = MarketSkillCatalogRepository(db)

    # -- Public API ---------------------------------------------------------

    async def get_available_filters(self) -> MarketFiltersResponse:
        """Filter options derived live from the market dataset.

        Nothing is hardcoded: years, companies, job families, locations and
        skill categories all come from the stored postings/catalog.
        """
        years = sorted(int(year) for year in await self.postings.distinct_values("year"))
        job_families = sorted(
            str(family) for family in await self.postings.distinct_values("job_family")
        )
        locations = sorted(
            str(location) for location in await self.postings.distinct_values("location")
        )

        company_rows = await self.postings.find_projected(
            {}, {"_id": 0, "company_slug": 1, "company_name": 1}, limit=_MAX_POSTINGS
        )
        companies: dict[str, str] = {}
        for row in company_rows:
            companies.setdefault(row["company_slug"], row["company_name"])

        catalog_docs = await self.catalog.find_many(limit=_MAX_CATALOG_ENTRIES)
        categories = sorted({doc.category.value for doc in catalog_docs})

        return MarketFiltersResponse(
            years=years,
            companies=[
                CompanyFilterOption(slug=slug, name=name)
                for slug, name in sorted(companies.items())
            ],
            job_families=job_families,
            locations=locations,
            skill_categories=categories,
        )

    async def get_market_analytics(self, query: MarketQuery) -> MarketAnalyticsResponse:
        self._validate_year_range(query)
        mongo_query = await self._build_mongo_query(query)

        rows = await self.postings.find_projected(
            mongo_query, _POSTING_PROJECTION, limit=_MAX_POSTINGS
        )
        catalog_docs = await self.catalog.find_many(limit=_MAX_CATALOG_ENTRIES)
        catalog_by_name = {doc.name: doc for doc in catalog_docs}

        agg = _aggregate_postings(rows, catalog_by_name, query)

        # Dataset identity comes from the data itself (all Phase 2 documents
        # share source/dataset_version); the constants are only a fallback
        # for an empty dataset so the response contract stays stable.
        source = rows[0]["source"] if rows else "mock"
        dataset_version = (
            rows[0].get("dataset_version", MARKET_DATASET_VERSION)
            if rows
            else MARKET_DATASET_VERSION
        )

        logger.debug(
            "Market analytics: %d posting(s) analysed for filters %s",
            agg.total_postings,
            mongo_query,
        )
        return _build_response(agg, catalog_by_name, query, source, dataset_version)

    async def get_market_comparison(
        self,
        dimension: str,
        entity_values: list[str],
        year_from: int | None,
        year_to: int | None,
        cross_company: str | None,
        cross_job_family: str | None,
        location: str | None,
    ) -> MarketComparisonResponse:
        """Phase 5 entity comparison (companies or job families).

        The dimension's own filter is replaced by the entity selection; the
        other posting filters still apply. See the module docstring for the
        exact semantics.
        """
        self._validate_year_range_values(year_from, year_to)
        if not entity_values:
            raise MarketQueryError("Select at least one entity to compare.")

        mongo_query: dict[str, Any] = {}
        year_filter = self._year_filter(year_from, year_to)
        if year_filter:
            mongo_query["year"] = year_filter
        if location is not None:
            mongo_query["location"] = await self._resolve_location(location)

        if dimension == "company":
            if cross_job_family is not None:
                mongo_query["job_family"] = cross_job_family
            info = await self._company_directory()
            selected = self._select_company_entities(entity_values, info)
        elif dimension == "job_family":
            if cross_company is not None:
                mongo_query["company_slug"] = await self._resolve_company(cross_company)
            known_families = {
                str(family).casefold(): str(family)
                for family in await self.postings.distinct_values("job_family")
            }
            selected = self._select_family_entities(entity_values, known_families)
        else:
            raise MarketQueryError(f"Unknown comparison dimension '{dimension}'.")

        if len(selected) > _MAX_COMPARISON_ENTITIES:
            raise MarketQueryError(
                f"At most {_MAX_COMPARISON_ENTITIES} entities can be compared "
                f"at once (got {len(selected)})."
            )

        rows = await self.postings.find_projected(
            mongo_query, _POSTING_PROJECTION, limit=_MAX_POSTINGS
        )
        catalog_docs = await self.catalog.find_many(limit=_MAX_CATALOG_ENTRIES)
        catalog_by_name = {doc.name: doc for doc in catalog_docs}

        # The unfiltered-by-dimension population anchors the comparison
        # window and the posting-share denominator.
        overall = _aggregate_postings(rows, catalog_by_name, MarketQuery())
        source = rows[0]["source"] if rows else "mock"
        dataset_version = (
            rows[0].get("dataset_version", MARKET_DATASET_VERSION)
            if rows
            else MARKET_DATASET_VERSION
        )
        meta = _build_meta(overall, source, dataset_version)

        entities: list[ComparisonEntityAnalytics] = []
        for key in selected:
            if dimension == "company":
                subset = [row for row in rows if row["company_slug"] == key]
                label = info[key]["name"]
                industry: str | None = info[key]["industry"]
            else:
                subset = [row for row in rows if row["job_family"] == key]
                label = key
                industry = None

            entity_agg = _aggregate_postings(subset, catalog_by_name, MarketQuery())
            # Align the window/comparability with the overall population so a
            # company that stopped posting in 2024 is not silently compared
            # full-year 2024 vs 2023 while the rest of the dashboard compares
            # Jan-Oct windows.
            entity_agg.comparable = False
            if overall.latest_year is not None:
                entity_agg.latest_year = overall.latest_year
                entity_agg.current_window = overall.current_window
                partial = overall.current_window[1] != 12
                entity_agg.current_total = _window_count(
                    entity_agg.yearly_totals,
                    entity_agg.yearly_jan_oct_totals,
                    overall.latest_year,
                    partial,
                )
                entity_agg.previous_total = _window_count(
                    entity_agg.yearly_totals,
                    entity_agg.yearly_jan_oct_totals,
                    overall.latest_year - 1,
                    partial,
                )
                entity_agg.comparable = entity_agg.previous_total > 0

            records = [
                _skill_record(name, entity_agg, catalog_by_name)
                for name in sorted(entity_agg.skill_totals)
            ]
            records.sort(key=lambda r: (-r["posting_count"], r["name"]))
            skills = [_trending_skill_from_record(r) for r in records]
            tech_instances = sum(
                skill.posting_count for skill in skills if skill.is_technical
            )
            soft_instances = sum(
                skill.posting_count for skill in skills if not skill.is_technical
            )
            entity_total = tech_instances + soft_instances
            entities.append(
                ComparisonEntityAnalytics(
                    entity_key=key,
                    entity_label=label,
                    industry=industry,
                    posting_count=entity_agg.total_postings,
                    posting_share_pct=_pct(
                        entity_agg.total_postings, overall.total_postings
                    ),
                    tech_skill_instances=tech_instances,
                    soft_skill_instances=soft_instances,
                    tech_share_pct=_pct(tech_instances, entity_total),
                    soft_share_pct=_pct(soft_instances, entity_total),
                    yearly_counts={
                        year: entity_agg.yearly_totals.get(year, 0)
                        for year in overall.years
                    },
                    skills=skills,
                )
            )

        logger.debug(
            "Market comparison: dimension=%s entities=%s postings=%d",
            dimension,
            selected,
            overall.total_postings,
        )
        return MarketComparisonResponse(
            meta=meta, dimension=dimension, entities=entities
        )

    # -- Comparison resolution helpers --------------------------------------

    async def _company_directory(self) -> dict[str, dict[str, str]]:
        """All known companies: slug -> {name, industry} (unfiltered)."""
        rows = await self.postings.find_projected(
            {},
            {"_id": 0, "company_slug": 1, "company_name": 1, "company_industry": 1},
            limit=_MAX_POSTINGS,
        )
        directory: dict[str, dict[str, str]] = {}
        for row in rows:
            directory.setdefault(
                row["company_slug"],
                {"name": row["company_name"], "industry": row["company_industry"]},
            )
        return directory

    @staticmethod
    def _select_company_entities(
        values: list[str], directory: dict[str, dict[str, str]]
    ) -> list[str]:
        """Resolve company slugs/names to canonical slugs, deduped, in order."""
        by_slug: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for slug, entry in directory.items():
            by_slug.setdefault(slug.casefold(), slug)
            by_name.setdefault(entry["name"].casefold(), slug)

        selected: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.strip().casefold()
            slug = by_slug.get(key) or by_name.get(key)
            if slug is None:
                raise MarketQueryError(
                    f"Unknown company '{value}'. Use a company slug or name "
                    "listed by GET /api/v1/analytics/tpo/market/filters."
                )
            if slug not in seen:
                seen.add(slug)
                selected.append(slug)
        return selected

    @staticmethod
    def _select_family_entities(
        values: list[str], known_families: dict[str, str]
    ) -> list[str]:
        """Resolve job-family names (case-insensitive), deduped, in order."""
        selected: list[str] = []
        seen: set[str] = set()
        for value in values:
            family = known_families.get(value.strip().casefold())
            if family is None:
                raise MarketQueryError(
                    f"Unknown job family '{value}'. Use a job family listed "
                    "by GET /api/v1/analytics/tpo/market/filters."
                )
            if family not in seen:
                seen.add(family)
                selected.append(family)
        return selected

    # -- Validation ---------------------------------------------------------

    @staticmethod
    def _validate_year_range_values(year_from: int | None, year_to: int | None) -> None:
        if (
            year_from is not None
            and year_to is not None
            and year_from > year_to
        ):
            raise MarketQueryError(
                f"year_from ({year_from}) cannot be after year_to ({year_to})."
            )

    @classmethod
    def _validate_year_range(cls, query: MarketQuery) -> None:
        cls._validate_year_range_values(query.year_from, query.year_to)

    @staticmethod
    def _year_filter(year_from: int | None, year_to: int | None) -> dict[str, int]:
        year_filter: dict[str, int] = {}
        if year_from is not None:
            year_filter["$gte"] = year_from
        if year_to is not None:
            year_filter["$lte"] = year_to
        return year_filter

    async def _build_mongo_query(self, query: MarketQuery) -> dict[str, Any]:
        mongo_query: dict[str, Any] = {}
        year_filter = self._year_filter(query.year_from, query.year_to)
        if year_filter:
            mongo_query["year"] = year_filter
        if query.job_family is not None:
            mongo_query["job_family"] = query.job_family
        if query.company is not None:
            mongo_query["company_slug"] = await self._resolve_company(query.company)
        if query.location is not None:
            mongo_query["location"] = await self._resolve_location(query.location)
        return mongo_query

    async def _resolve_company(self, value: str) -> str:
        """Resolve a company slug or name to the canonical company_slug."""
        rows = await self.postings.find_projected(
            {}, {"_id": 0, "company_slug": 1, "company_name": 1}, limit=_MAX_POSTINGS
        )
        by_slug: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for row in rows:
            by_slug.setdefault(row["company_slug"].casefold(), row["company_slug"])
            by_name.setdefault(row["company_name"].casefold(), row["company_slug"])
        key = value.strip().casefold()
        if key in by_slug:
            return by_slug[key]
        if key in by_name:
            return by_name[key]
        raise MarketQueryError(
            f"Unknown company '{value}'. Use a company slug or name listed by "
            "GET /api/v1/analytics/tpo/market/filters."
        )

    async def _resolve_location(self, value: str) -> str:
        known = {
            str(location).casefold(): str(location)
            for location in await self.postings.distinct_values("location")
        }
        key = value.strip().casefold()
        if key in known:
            return known[key]
        raise MarketQueryError(
            f"Unknown location '{value}'. Use a location listed by "
            "GET /api/v1/analytics/tpo/market/filters."
        )
