"""Endpoint and service tests for the TPO market analytics API (Phase 3).

The Phase 2 deterministic dataset is seeded into the mock Mongo database and
every aggregate assertion is recomputed independently from the raw generated
postings, so the tests pin the formulas (demand percentages, YoY windows,
trend scores) rather than hardcoded numbers.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime

import pytest

from app.models.user import AdminRegisterRequest
from app.repositories.job_posting_repository import (
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)
from app.services.auth_service import AuthService
from app.services.market_analytics_service import _classify_trend, _growth_pct
from scripts.seed_job_market import MARKET_DATASET_VERSION, build_dataset

FIXED_CREATED_AT = datetime(2026, 11, 15, 9, 0, 0)
MARKET_URL = "/api/v1/analytics/tpo/market"
FILTERS_URL = "/api/v1/analytics/tpo/market/filters"
COMPARISON_URL = "/api/v1/analytics/tpo/market/comparison"
PASSWORD = "StrongPass123"


@pytest.fixture(scope="module")
def dataset():
    return build_dataset(created_at=FIXED_CREATED_AT, verbose=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_login_student(client, email):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Market Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return login.json()["access_token"]


async def _register_login_tpo(client, email):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": PASSWORD, "name": "Market TPO", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return login.json()["access_token"]


async def _register_login_admin(client, email):
    from app.core import database as db_module

    service = AuthService(db_module.mongodb.db)
    await service.register_admin(
        AdminRegisterRequest(email=email, password=PASSWORD, name="Market Admin")
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_market(mock_mongo, dataset):
    """Seed once. mock_mongo is function-scoped, so this can never leak data
    between tests — it only guards tests that call the endpoint several times."""
    if await mock_mongo.job_market_postings.count_documents({}) > 0:
        return
    catalog, postings, _ = dataset
    await MarketSkillCatalogRepository(mock_mongo).create_many(deepcopy(catalog))
    await JobMarketPostingRepository(mock_mongo).create_many(deepcopy(postings))


async def _get_market(client, mock_mongo, dataset, email, **params):
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, email)
    response = await client.get(MARKET_URL, headers=_auth(token), params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


def _skills_of(posting) -> set:
    return set(posting["technical_skills"]) | set(posting["soft_skills"])


def _count_in(postings, name, year, months=None):
    """Distinct postings requiring `name` in `year`, optionally Jan-Oct only."""
    return sum(
        1
        for posting in postings
        if posting["year"] == year
        and name in _skills_of(posting)
        and (months is None or months[0] <= posting["month"] <= months[1])
    )


def _expected_skill_counts(postings) -> Counter:
    counts: Counter = Counter()
    for posting in postings:
        for skill in _skills_of(posting):  # set membership == distinct postings
            counts[skill] += 1
    return counts


def _best_skill(expected_counts: Counter):
    return min(expected_counts.items(), key=lambda item: (-item[1], item[0]))


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_endpoints_require_tpo_role(client, mock_mongo, dataset):
    await _seed_market(mock_mongo, dataset)
    tpo = await _register_login_tpo(client, "mkt.auth.tpo@college.edu")
    student = await _register_login_student(client, "mkt.auth.student@college.edu")
    admin = await _register_login_admin(client, "mkt.auth.admin@college.edu")

    assert (await client.get(MARKET_URL, headers=_auth(tpo))).status_code == 200
    assert (await client.get(MARKET_URL, headers=_auth(student))).status_code == 403
    assert (await client.get(MARKET_URL, headers=_auth(admin))).status_code == 403
    assert (await client.get(MARKET_URL)).status_code == 401

    assert (await client.get(FILTERS_URL, headers=_auth(tpo))).status_code == 200
    assert (await client.get(FILTERS_URL, headers=_auth(student))).status_code == 403
    assert (await client.get(FILTERS_URL, headers=_auth(admin))).status_code == 403
    assert (await client.get(FILTERS_URL)).status_code == 401


# ---------------------------------------------------------------------------
# Response shape, summary and skill analytics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tpo_gets_full_market_analytics_shape(client, mock_mongo, dataset):
    body = await _get_market(client, mock_mongo, dataset, "mkt.shape.tpo@college.edu")

    assert set(body) == {
        "meta",
        "summary",
        "trending_skills",
        "historical_trends",
        "emerging_skills",
        "companies",
        "job_families",
    }
    assert set(body["meta"]) == {
        "source",
        "dataset_version",
        "is_mock_data",
        "comparison_period",
        "is_partial_year",
        "disclaimer",
        "current_period",
        "previous_period",
        "comparison_comparable",
        "filtered_years",
    }
    assert set(body["summary"]) == {
        "total_postings",
        "company_count",
        "distinct_skill_count",
        "most_demanded_skill",
        "yoy_posting_growth_pct",
    }
    assert set(body["trending_skills"][0]) == {
        "name",
        "slug",
        "category",
        "is_technical",
        "posting_count",
        "demand_pct",
        "trend_score",
        "trend",
        "yoy_growth_pct",
        "current_period_count",
        "previous_period_count",
        "yearly_counts",
        "yearly_demand_pct",
    }
    assert set(body["companies"][0]) == {
        "company_name",
        "company_slug",
        "industry",
        "posting_count",
        "posting_share_pct",
        "top_skills",
        "yearly_counts",
    }
    assert set(body["job_families"][0]) == {
        "job_family",
        "posting_count",
        "posting_share_pct",
        "top_skills",
        "yearly_counts",
    }


@pytest.mark.asyncio
async def test_summary_statistics_match_dataset(client, mock_mongo, dataset):
    _, postings, _ = dataset
    body = await _get_market(client, mock_mongo, dataset, "mkt.summary.tpo@college.edu")
    summary = body["summary"]

    expected_counts = _expected_skill_counts(postings)
    best_name, best_count = _best_skill(expected_counts)

    assert summary["total_postings"] == len(postings) == 300
    assert summary["company_count"] == len({p["company_slug"] for p in postings}) == 15
    assert summary["distinct_skill_count"] == len(expected_counts) == 52
    assert summary["most_demanded_skill"]["name"] == best_name
    assert summary["most_demanded_skill"]["posting_count"] == best_count
    assert summary["most_demanded_skill"]["demand_pct"] == round(100 * best_count / 300, 1)

    # Overall growth: Jan-Oct 2026 (all 2026 postings) vs Jan-Oct 2025 only.
    current_total = sum(1 for p in postings if p["year"] == 2026)
    previous_total = sum(1 for p in postings if p["year"] == 2025 and p["month"] <= 10)
    assert summary["yoy_posting_growth_pct"] == round(
        100 * (current_total - previous_total) / previous_total, 1
    )


@pytest.mark.asyncio
async def test_trending_skills_use_distinct_postings_and_shared_denominator(
    client, mock_mongo, dataset
):
    _, postings, _ = dataset
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.demand.tpo@college.edu", limit=20
    )
    expected_counts = _expected_skill_counts(postings)

    assert len(body["trending_skills"]) == 20
    for skill in body["trending_skills"]:
        assert skill["posting_count"] == expected_counts[skill["name"]]
        assert skill["posting_count"] <= 300  # never counted twice per posting
        assert skill["demand_pct"] == round(100 * skill["posting_count"] / 300, 1)


@pytest.mark.asyncio
async def test_sort_options_order_trending_and_demand(client, mock_mongo, dataset):
    _, postings, _ = dataset
    expected_counts = _expected_skill_counts(postings)
    best_name, _ = _best_skill(expected_counts)

    trending_body = await _get_market(
        client, mock_mongo, dataset, "mkt.sort.tpo@college.edu", sort="trending", limit=20
    )
    scores = [skill["trend_score"] for skill in trending_body["trending_skills"]]
    assert scores == sorted(scores, reverse=True)

    demand_body = await _get_market(
        client, mock_mongo, dataset, "mkt.sort2.tpo@college.edu", sort="demand", limit=20
    )
    counts = [skill["posting_count"] for skill in demand_body["trending_skills"]]
    assert counts == sorted(counts, reverse=True)
    assert demand_body["trending_skills"][0]["name"] == best_name


@pytest.mark.asyncio
async def test_limit_bounds(client, mock_mongo, dataset):
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, "mkt.limit.tpo@college.edu")

    default = await client.get(MARKET_URL, headers=_auth(token))
    assert len(default.json()["trending_skills"]) == 10

    capped = await client.get(MARKET_URL, headers=_auth(token), params={"limit": 20})
    assert capped.status_code == 200
    assert len(capped.json()["trending_skills"]) == 20

    assert (await client.get(MARKET_URL, headers=_auth(token), params={"limit": 21})).status_code == 422
    assert (await client.get(MARKET_URL, headers=_auth(token), params={"limit": 0})).status_code == 422


@pytest.mark.asyncio
async def test_yearly_and_historical_aggregation_match_dataset(client, mock_mongo, dataset):
    _, postings, _ = dataset
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.hist.tpo@college.edu", sort="demand", limit=20
    )
    expected_counts = _expected_skill_counts(postings)
    best_name, _ = _best_skill(expected_counts)
    skill = next(s for s in body["trending_skills"] if s["name"] == best_name)

    expected_yearly = Counter(p["year"] for p in postings if best_name in _skills_of(p))
    for year in (2023, 2024, 2025, 2026):
        assert skill["yearly_counts"][str(year)] == expected_yearly.get(year, 0)
        total_in_year = sum(1 for p in postings if p["year"] == year)
        assert skill["yearly_demand_pct"][str(year)] == round(
            100 * expected_yearly.get(year, 0) / total_in_year, 1
        )

    # Historical trends cover every in-scope skill (all 52), not just the top N.
    historical = body["historical_trends"]
    assert len(historical) == len(expected_counts) == 52
    entry = next(h for h in historical if h["slug"] == skill["slug"])
    assert [item["year"] for item in entry["years"]] == [2023, 2024, 2025, 2026]
    assert [item["posting_count"] for item in entry["years"]] == [
        expected_yearly.get(year, 0) for year in (2023, 2024, 2025, 2026)
    ]


@pytest.mark.asyncio
async def test_partial_year_windows_are_used_for_comparisons(client, mock_mongo, dataset):
    _, postings, _ = dataset
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.window.tpo@college.edu", limit=20
    )

    meta = body["meta"]
    assert meta["comparison_period"] == "Jan-Oct"
    assert meta["is_partial_year"] is True
    assert meta["current_period"] == {
        "year": 2026,
        "start_month": 1,
        "end_month": 10,
        "label": "Jan-Oct 2026",
    }
    assert meta["previous_period"]["year"] == 2025
    assert meta["previous_period"]["start_month"] == 1
    assert meta["previous_period"]["end_month"] == 10
    assert meta["comparison_comparable"] is True

    for skill in body["trending_skills"]:
        name = skill["name"]
        expected_current = _count_in(postings, name, 2026, months=(1, 10))
        expected_previous = _count_in(postings, name, 2025, months=(1, 10))
        assert skill["current_period_count"] == expected_current
        assert skill["previous_period_count"] == expected_previous
        if expected_previous:
            assert skill["yoy_growth_pct"] == round(
                100 * (expected_current - expected_previous) / expected_previous, 1
            )
        else:
            assert skill["yoy_growth_pct"] is None

    # Historical growth: Jan-Oct pair for the partial latest year, full years
    # for every earlier pair.
    historical = {entry["slug"]: entry for entry in body["historical_trends"]}
    assert len(historical) == 52
    for entry in body["historical_trends"]:
        name = entry["name"]
        for item in entry["years"]:
            if item["year"] == 2023:
                assert item["yoy_growth_pct"] is None  # 2022 is outside the dataset
                continue
            if item["year"] == 2026:
                current = _count_in(postings, name, 2026, months=(1, 10))
                previous = _count_in(postings, name, 2025, months=(1, 10))
            else:
                current = _count_in(postings, name, item["year"])
                previous = _count_in(postings, name, item["year"] - 1)
            if previous == 0:
                assert item["yoy_growth_pct"] is None
            else:
                assert item["yoy_growth_pct"] == round(
                    100 * (current - previous) / previous, 1
                )

    # The dataset really contains Nov/Dec 2025 postings, so the Jan-Oct window
    # must differ from the full-year count for at least one skill.
    window_differs = [
        name
        for name in _expected_skill_counts(postings)
        if _count_in(postings, name, 2025) != _count_in(postings, name, 2025, months=(1, 10))
    ]
    assert window_differs


# ---------------------------------------------------------------------------
# Company and job-family analytics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_analytics_match_dataset(client, mock_mongo, dataset):
    _, postings, _ = dataset
    body = await _get_market(client, mock_mongo, dataset, "mkt.company.tpo@college.edu")

    slug = postings[0]["company_slug"]
    company_postings = [p for p in postings if p["company_slug"] == slug]
    entry = next(c for c in body["companies"] if c["company_slug"] == slug)

    assert entry["company_name"] == company_postings[0]["company_name"]
    assert entry["industry"] == company_postings[0]["company_industry"]
    assert entry["posting_count"] == len(company_postings)
    assert entry["posting_share_pct"] == round(100 * len(company_postings) / 300, 1)
    assert entry["yearly_counts"] == {
        str(year): sum(1 for p in company_postings if p["year"] == year)
        for year in (2023, 2024, 2025, 2026)
    }

    company_skills: Counter = Counter()
    for posting in company_postings:
        for skill in _skills_of(posting):
            company_skills[skill] += 1
    top_name, top_count = min(company_skills.items(), key=lambda item: (-item[1], item[0]))
    assert entry["top_skills"][0]["name"] == top_name
    assert entry["top_skills"][0]["posting_count"] == top_count
    # Demand percentages inside a company use that company's postings as the
    # denominator, not the global 300.
    assert entry["top_skills"][0]["demand_pct"] == round(
        100 * top_count / len(company_postings), 1
    )
    assert len(entry["top_skills"]) <= 10


@pytest.mark.asyncio
async def test_job_family_analytics_match_dataset(client, mock_mongo, dataset):
    _, postings, _ = dataset
    body = await _get_market(client, mock_mongo, dataset, "mkt.family.tpo@college.edu")

    families = body["job_families"]
    assert sum(f["posting_count"] for f in families) == 300

    family_name = postings[0]["job_family"]
    family_postings = [p for p in postings if p["job_family"] == family_name]
    entry = next(f for f in families if f["job_family"] == family_name)

    assert entry["posting_count"] == len(family_postings)
    assert entry["posting_share_pct"] == round(100 * len(family_postings) / 300, 1)
    assert entry["yearly_counts"] == {
        str(year): sum(1 for p in family_postings if p["year"] == year)
        for year in (2023, 2024, 2025, 2026)
    }

    family_skills: Counter = Counter()
    for posting in family_postings:
        for skill in _skills_of(posting):
            family_skills[skill] += 1
    top_name, top_count = min(family_skills.items(), key=lambda item: (-item[1], item[0]))
    assert entry["top_skills"][0]["name"] == top_name
    assert entry["top_skills"][0]["posting_count"] == top_count
    assert entry["top_skills"][0]["demand_pct"] == round(
        100 * top_count / len(family_postings), 1
    )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_filter_applies_to_every_section(client, mock_mongo, dataset):
    _, postings, _ = dataset
    slug = postings[0]["company_slug"]
    company_postings = [p for p in postings if p["company_slug"] == slug]
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.cfilter.tpo@college.edu", company=slug
    )

    assert body["summary"]["total_postings"] == len(company_postings)
    assert body["summary"]["company_count"] == 1
    assert len(body["companies"]) == 1
    assert body["companies"][0]["company_slug"] == slug
    assert body["companies"][0]["posting_count"] == len(company_postings)

    for skill in body["trending_skills"]:
        assert skill["posting_count"] <= len(company_postings)
        assert skill["demand_pct"] == round(
            100 * skill["posting_count"] / len(company_postings), 1
        )
    for family in body["job_families"]:
        expected = sum(
            1 for p in company_postings if p["job_family"] == family["job_family"]
        )
        assert family["posting_count"] == expected
    assert body["meta"]["filtered_years"] == [2023, 2024, 2025, 2026]


@pytest.mark.asyncio
async def test_job_family_and_location_filters(client, mock_mongo, dataset):
    _, postings, _ = dataset

    family = postings[0]["job_family"]
    family_postings = [p for p in postings if p["job_family"] == family]
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.ffilter.tpo@college.edu", job_family=family
    )
    assert body["summary"]["total_postings"] == len(family_postings)
    assert [f["job_family"] for f in body["job_families"]] == [family]
    assert body["job_families"][0]["posting_count"] == len(family_postings)

    location = postings[0]["location"]
    location_postings = [p for p in postings if p["location"] == location]
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.lfilter.tpo@college.edu", location=location
    )
    assert body["summary"]["total_postings"] == len(location_postings)
    assert body["summary"]["company_count"] == len(
        {p["company_slug"] for p in location_postings}
    )


@pytest.mark.asyncio
async def test_skill_scope_filters(client, mock_mongo, dataset):
    soft = await _get_market(
        client,
        mock_mongo,
        dataset,
        "mkt.soft.tpo@college.edu",
        skill_category="Soft Skill",
    )
    assert soft["summary"]["total_postings"] == 300  # posting denominator unchanged
    assert soft["summary"]["distinct_skill_count"] == 12
    assert all(s["category"] == "Soft Skill" for s in soft["trending_skills"])
    assert all(not s["is_technical"] for s in soft["trending_skills"])

    technical = await _get_market(
        client, mock_mongo, dataset, "mkt.tech.tpo@college.edu", technical_only=True
    )
    assert technical["summary"]["distinct_skill_count"] == 40
    assert all(s["is_technical"] for s in technical["trending_skills"])

    # Combined filters intersect: soft-skill category AND technical-only is empty.
    both = await _get_market(
        client,
        mock_mongo,
        dataset,
        "mkt.both.tpo@college.edu",
        skill_category="Soft Skill",
        technical_only=True,
    )
    assert both["summary"]["total_postings"] == 300
    assert both["summary"]["distinct_skill_count"] == 0
    assert both["summary"]["most_demanded_skill"] is None
    assert both["trending_skills"] == []
    assert both["historical_trends"] == []
    assert both["emerging_skills"] == []


@pytest.mark.asyncio
async def test_year_filters_change_comparability(client, mock_mongo, dataset):
    _, postings, _ = dataset

    # Single year: no previous period in the filtered population.
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.yf1.tpo@college.edu", year_from=2024, year_to=2024
    )
    assert body["summary"]["total_postings"] == 72
    assert body["meta"]["filtered_years"] == [2024]
    assert body["meta"]["comparison_comparable"] is False
    assert body["summary"]["yoy_posting_growth_pct"] is None
    assert all(skill["trend"] is None for skill in body["trending_skills"])

    # Full-year pair (2024 vs 2023).
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.yf2.tpo@college.edu", year_from=2023, year_to=2024
    )
    total_2024 = sum(1 for p in postings if p["year"] == 2024)
    total_2023 = sum(1 for p in postings if p["year"] == 2023)
    assert body["summary"]["total_postings"] == total_2023 + total_2024
    assert body["summary"]["yoy_posting_growth_pct"] == round(
        100 * (total_2024 - total_2023) / total_2023, 1
    )
    assert body["meta"]["comparison_comparable"] is True

    # Partial-year pair (Jan-Oct 2026 vs Jan-Oct 2025).
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.yf3.tpo@college.edu", year_from=2025, year_to=2026
    )
    current_total = sum(1 for p in postings if p["year"] == 2026)
    previous_total = sum(1 for p in postings if p["year"] == 2025 and p["month"] <= 10)
    assert body["summary"]["total_postings"] == sum(
        1 for p in postings if 2025 <= p["year"] <= 2026
    )
    assert body["summary"]["yoy_posting_growth_pct"] == round(
        100 * (current_total - previous_total) / previous_total, 1
    )
    assert body["meta"]["current_period"]["label"] == "Jan-Oct 2026"


@pytest.mark.asyncio
async def test_invalid_query_values_return_http_errors(client, mock_mongo, dataset):
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, "mkt.invalid.tpo@college.edu")

    assert (
        await client.get(MARKET_URL, headers=_auth(token), params={"job_family": "Wizard"})
    ).status_code == 422
    assert (
        await client.get(
            MARKET_URL, headers=_auth(token), params={"skill_category": "Charisma"}
        )
    ).status_code == 422
    assert (
        await client.get(MARKET_URL, headers=_auth(token), params={"sort": "popularity"})
    ).status_code == 422
    assert (
        await client.get(
            MARKET_URL,
            headers=_auth(token),
            params={"company": "definitely-not-a-company"},
        )
    ).status_code == 400
    assert (
        await client.get(MARKET_URL, headers=_auth(token), params={"location": "Atlantis"})
    ).status_code == 400
    assert (
        await client.get(
            MARKET_URL, headers=_auth(token), params={"year_from": 2025, "year_to": 2023}
        )
    ).status_code == 400


# ---------------------------------------------------------------------------
# Empty datasets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_collection_returns_valid_empty_response(client, mock_mongo):
    token = await _register_login_tpo(client, "mkt.empty.tpo@college.edu")
    response = await client.get(MARKET_URL, headers=_auth(token))
    assert response.status_code == 200
    body = response.json()

    assert body["summary"] == {
        "total_postings": 0,
        "company_count": 0,
        "distinct_skill_count": 0,
        "most_demanded_skill": None,
        "yoy_posting_growth_pct": None,
    }
    assert body["trending_skills"] == []
    assert body["historical_trends"] == []
    assert body["emerging_skills"] == []
    assert body["companies"] == []
    assert body["job_families"] == []
    assert body["meta"]["filtered_years"] == []
    assert body["meta"]["current_period"] is None
    assert body["meta"]["previous_period"] is None
    assert body["meta"]["comparison_comparable"] is False
    assert body["meta"]["is_mock_data"] is True

    filters = await client.get(FILTERS_URL, headers=_auth(token))
    assert filters.status_code == 200
    assert filters.json() == {
        "years": [],
        "companies": [],
        "job_families": [],
        "locations": [],
        "skill_categories": [],
    }


@pytest.mark.asyncio
async def test_filter_mismatch_returns_empty_but_valid_response(client, mock_mongo, dataset):
    body = await _get_market(
        client, mock_mongo, dataset, "mkt.mismatch.tpo@college.edu", year_from=2030, year_to=2031
    )
    assert body["summary"]["total_postings"] == 0
    assert body["summary"]["company_count"] == 0
    assert body["trending_skills"] == []
    assert body["meta"]["filtered_years"] == []
    assert body["meta"]["current_period"] is None
    assert body["meta"]["comparison_comparable"] is False


# ---------------------------------------------------------------------------
# Trend helpers (pure functions)
# ---------------------------------------------------------------------------


def test_growth_and_classification_helpers():
    assert _growth_pct(120, 100) == 20.0
    assert _growth_pct(110, 100) == 10.0  # >= +10% -> rising boundary
    assert _growth_pct(90, 100) == -10.0  # <= -10% -> declining boundary
    assert _growth_pct(5, 0) is None  # never divides by zero

    assert _classify_trend(120, 100, True) == "rising"
    assert _classify_trend(110, 100, True) == "rising"
    assert _classify_trend(80, 100, True) == "declining"
    assert _classify_trend(90, 100, True) == "declining"
    assert _classify_trend(105, 100, True) == "stable"
    assert _classify_trend(95, 100, True) == "stable"
    assert _classify_trend(7, 0, True) == "emerging"
    # A filter-excluded previous period must NOT be read as "emerging".
    assert _classify_trend(7, 0, False) is None
    assert _classify_trend(0, 10, False) is None


# ---------------------------------------------------------------------------
# Emerging skills (synthetic mini dataset, full control over the windows)
# ---------------------------------------------------------------------------


def _mini_catalog():
    return [
        {"name": "Python", "slug": "python", "category": "Programming Language", "is_technical": True, "aliases": [], "source": "mock"},
        {"name": "Rust", "slug": "rust", "category": "Programming Language", "is_technical": True, "aliases": [], "source": "mock"},
        {"name": "Legacy System", "slug": "legacy-system", "category": "Backend", "is_technical": True, "aliases": [], "source": "mock"},
        {"name": "Communication", "slug": "communication", "category": "Soft Skill", "is_technical": False, "aliases": [], "source": "mock"},
    ]


def _mini_posting(external_id, company_name, year, month, technical):
    posted_at = datetime(year, month, 15, 9, 0, 0)
    slug = company_name.lower().replace(" ", "-")
    return {
        "external_id": external_id,
        "dataset_version": MARKET_DATASET_VERSION,
        "source": "mock",
        "company_name": company_name,
        "company_slug": slug,
        "company_industry": "Software",
        "company_size": "100-500",
        "company_hq": "Pune",
        "company_website": f"https://{slug}.example",
        "job_title": "Engineer",
        "job_family": "Software Engineering",
        "seniority": "Entry",
        "hiring_type": "Full-time",
        "description": "Fictional demo posting.",
        "jd_text": "Fictional demo JD.",
        "technical_skills": list(technical),
        "soft_skills": ["Communication"],
        "required_skills": list(technical) + ["Communication"],
        "min_experience_years": 0,
        "education_level": "B.Tech",
        "eligible_departments": ["CS"],
        "min_cgpa": 6.0,
        "location": "Pune",
        "work_mode": "Hybrid",
        "salary_band": "6-8 LPA",
        "salary_min_lpa": 6.0,
        "salary_max_lpa": 8.0,
        "posted_at": posted_at,
        "year": year,
        "quarter": (month - 1) // 3 + 1,
        "month": month,
        "is_active": False,
        "created_at": FIXED_CREATED_AT,
    }


async def _seed_mini_dataset(mock_mongo):
    await MarketSkillCatalogRepository(mock_mongo).create_many(deepcopy(_mini_catalog()))
    postings = [
        _mini_posting("mini-1", "Alpha Labs", 2025, 3, ["Python"]),
        _mini_posting("mini-2", "Alpha Labs", 2026, 2, ["Python", "Rust"]),
        _mini_posting("mini-3", "Beta Systems", 2025, 5, ["Legacy System"]),
        _mini_posting("mini-4", "Beta Systems", 2025, 8, ["Legacy System"]),
        _mini_posting("mini-5", "Beta Systems", 2026, 5, ["Legacy System"]),
    ]
    await JobMarketPostingRepository(mock_mongo).create_many(deepcopy(postings))
    return postings


@pytest.mark.asyncio
async def test_emerging_skills_detected_from_window_counts(client, mock_mongo):
    await _seed_mini_dataset(mock_mongo)
    token = await _register_login_tpo(client, "mkt.emerging.tpo@college.edu")
    body = (await client.get(MARKET_URL, headers=_auth(token))).json()

    emerging = body["emerging_skills"]
    # Rust: zero Jan-Oct 2025 postings, one Jan-Oct 2026 posting.
    assert [skill["slug"] for skill in emerging] == ["rust"]
    assert emerging[0]["current_period_count"] == 1
    assert emerging[0]["previous_period_count"] == 0
    assert emerging[0]["current_period_demand_pct"] == 50.0  # 1 of 2 current-window postings
    assert emerging[0]["trend"] == "emerging"

    trends = {skill["slug"]: skill["trend"] for skill in body["trending_skills"]}
    assert trends["rust"] == "emerging"
    assert trends["legacy-system"] == "declining"  # 2 -> 1 within the Jan-Oct windows
    assert trends["python"] == "stable"  # 1 -> 1
    assert body["summary"]["yoy_posting_growth_pct"] == round(100 * (2 - 3) / 3, 1)


@pytest.mark.asyncio
async def test_excluded_previous_period_is_not_emerging(client, mock_mongo):
    await _seed_mini_dataset(mock_mongo)
    token = await _register_login_tpo(client, "mkt.excluded.tpo@college.edu")
    body = (
        await client.get(
            MARKET_URL, headers=_auth(token), params={"year_from": 2026, "year_to": 2026}
        )
    ).json()

    # 2025 was excluded by the year filter, so nothing may be called "emerging".
    assert body["emerging_skills"] == []
    assert body["meta"]["comparison_comparable"] is False
    assert body["meta"]["current_period"]["label"] == "Jan-Oct 2026"
    assert all(skill["trend"] is None for skill in body["trending_skills"])
    assert all(skill["yoy_growth_pct"] is None for skill in body["trending_skills"])
    assert body["summary"]["yoy_posting_growth_pct"] is None
    assert body["summary"]["total_postings"] == 2


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_analytics_ignore_operational_collections(client, mock_mongo, dataset):
    _, postings, _ = dataset
    await _seed_market(mock_mongo, dataset)

    # Operational data exists but must be invisible to the market analytics.
    await mock_mongo.placement_drives.insert_one(
        {"job_title": "Operational Drive", "required_skills": ["Python"]}
    )
    drives_before = await mock_mongo.placement_drives.count_documents({})

    token = await _register_login_tpo(client, "mkt.integrity.tpo@college.edu")
    body = (await client.get(MARKET_URL, headers=_auth(token))).json()

    assert body["summary"]["total_postings"] == 300  # the drive is not counted
    expected_counts = _expected_skill_counts(postings)
    best_name, best_count = _best_skill(expected_counts)
    assert body["summary"]["most_demanded_skill"]["posting_count"] == best_count

    assert await mock_mongo.placement_drives.count_documents({}) == drives_before

    # Mock source / dataset version metadata is preserved in the response.
    assert body["meta"]["source"] == "mock"
    assert body["meta"]["dataset_version"] == MARKET_DATASET_VERSION
    assert body["meta"]["is_mock_data"] is True
    assert "not verified real-world hiring statistics" in body["meta"]["disclaimer"]


# ---------------------------------------------------------------------------
# Filters endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filters_endpoint_derives_options_from_dataset(client, mock_mongo, dataset):
    catalog, postings, _ = dataset
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, "mkt.filters.tpo@college.edu")

    response = await client.get(FILTERS_URL, headers=_auth(token))
    assert response.status_code == 200
    body = response.json()

    assert body["years"] == sorted({p["year"] for p in postings})
    assert body["job_families"] == sorted({p["job_family"] for p in postings})
    assert body["locations"] == sorted({p["location"] for p in postings})
    assert {company["slug"] for company in body["companies"]} == {
        p["company_slug"] for p in postings
    }
    assert {company["name"] for company in body["companies"]} == {
        p["company_name"] for p in postings
    }
    assert body["skill_categories"] == sorted({skill["category"] for skill in catalog})


# ---------------------------------------------------------------------------
# Phase 5 — entity comparison endpoint (companies / job families)
# ---------------------------------------------------------------------------


async def _get_comparison(client, mock_mongo, dataset, email, **params):
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, email)
    response = await client.get(COMPARISON_URL, headers=_auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _company_skill_counters(postings) -> dict[str, Counter]:
    by_company: dict[str, Counter] = defaultdict(Counter)
    for posting in postings:
        for skill in _skills_of(posting):
            by_company[posting["company_slug"]][skill] += 1
    return by_company


def _entity_skill_map(entity) -> dict[str, dict]:
    return {skill["name"]: skill for skill in entity["skills"]}


@pytest.mark.asyncio
async def test_comparison_requires_tpo_role(client, mock_mongo, dataset):
    await _seed_market(mock_mongo, dataset)
    tpo = await _register_login_tpo(client, "mkt.cmp.role.tpo@college.edu")
    student = await _register_login_student(client, "mkt.cmp.role.student@college.edu")
    admin = await _register_login_admin(client, "mkt.cmp.role.admin@college.edu")
    params = {"dimension": "company", "entities": "vertex-robotics"}

    assert (await client.get(COMPARISON_URL, headers=_auth(tpo), params=params)).status_code == 200
    assert (await client.get(COMPARISON_URL, headers=_auth(student), params=params)).status_code == 403
    assert (await client.get(COMPARISON_URL, headers=_auth(admin), params=params)).status_code == 403
    assert (await client.get(COMPARISON_URL, params=params)).status_code == 401


@pytest.mark.asyncio
async def test_company_comparison_returns_full_skills_with_entity_denominator(
    client, mock_mongo, dataset
):
    catalog, postings, _ = dataset
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.shape.tpo@college.edu",
        dimension="company",
        entities=",".join(slug for slug, _ in Counter(p["company_slug"] for p in postings).most_common(3)),
    )

    assert body["dimension"] == "company"
    assert set(body) == {"meta", "dimension", "entities"}
    tech_map = {skill["name"]: skill["is_technical"] for skill in catalog}

    for entity in body["entities"]:
        assert set(entity) == {
            "entity_key",
            "entity_label",
            "industry",
            "posting_count",
            "posting_share_pct",
            "tech_skill_instances",
            "soft_skill_instances",
            "tech_share_pct",
            "soft_share_pct",
            "yearly_counts",
            "skills",
        }
        if entity["skills"]:
            assert set(entity["skills"][0]) == {
                "name",
                "slug",
                "category",
                "is_technical",
                "posting_count",
                "demand_pct",
                "trend_score",
                "trend",
                "yoy_growth_pct",
                "current_period_count",
                "previous_period_count",
                "yearly_counts",
                "yearly_demand_pct",
            }

        slug = entity["entity_key"]
        company_postings = [p for p in postings if p["company_slug"] == slug]
        expected = _company_skill_counters(postings)[slug]

        assert entity["entity_label"] == company_postings[0]["company_name"]
        assert entity["industry"] == company_postings[0]["company_industry"]
        assert entity["posting_count"] == len(company_postings)
        assert entity["posting_share_pct"] == round(100 * len(company_postings) / 300, 1)
        assert entity["yearly_counts"] == {
            str(year): sum(1 for p in company_postings if p["year"] == year)
            for year in (2023, 2024, 2025, 2026)
        }

        got = _entity_skill_map(entity)
        # The FULL skill list, not just a top-10 slice.
        assert set(got) == set(expected)
        for name, count in expected.items():
            assert got[name]["posting_count"] == count
            # Demand percentages use the company's own postings as denominator.
            assert got[name]["demand_pct"] == round(100 * count / len(company_postings), 1)
        counts = [skill["posting_count"] for skill in entity["skills"]]
        assert counts == sorted(counts, reverse=True)

        tech = sum(count for name, count in expected.items() if tech_map[name])
        soft = sum(count for name, count in expected.items() if not tech_map[name])
        assert entity["tech_skill_instances"] == tech
        assert entity["soft_skill_instances"] == soft
        assert entity["tech_share_pct"] == round(100 * tech / (tech + soft), 1)
        assert entity["soft_share_pct"] == round(100 * soft / (tech + soft), 1)


@pytest.mark.asyncio
async def test_company_comparison_shared_and_unique_skills(client, mock_mongo, dataset):
    _, postings, _ = dataset
    selected = [slug for slug, _ in Counter(p["company_slug"] for p in postings).most_common(3)]
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.shared.tpo@college.edu",
        dimension="company",
        entities=",".join(selected),
    )
    entities = {e["entity_key"]: e for e in body["entities"]}
    skill_sets = {
        slug: set(_company_skill_counters(postings)[slug]) for slug in selected
    }

    shared = set.intersection(*(set(skill_sets[slug]) for slug in selected))
    for name in shared:
        for slug in selected:
            assert name in _entity_skill_map(entities[slug])

    counts_by_skill = Counter(
        name for slug in selected for name in skill_sets[slug]
    )
    unique = [name for name, n in counts_by_skill.items() if n == 1]
    for name in unique:
        owners = [slug for slug in selected if name in skill_sets[slug]]
        assert len(owners) == 1
        assert set(_entity_skill_map(entities[owners[0]])) >= {name}
        others = [slug for slug in selected if slug != owners[0]]
        for other in others:
            assert name not in _entity_skill_map(entities[other])

    # Every skill across the three companies appears in exactly the entities
    # that require it — nothing is invented and nothing is dropped.
    union = set(counts_by_skill)
    listed = {name for slug in selected for name in _entity_skill_map(entities[slug])}
    assert listed == union


@pytest.mark.asyncio
async def test_company_comparison_uses_partial_year_windows(client, mock_mongo, dataset):
    _, postings, _ = dataset
    selected = [slug for slug, _ in Counter(p["company_slug"] for p in postings).most_common(2)]
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.window.tpo@college.edu",
        dimension="company",
        entities=",".join(selected),
    )

    for entity in body["entities"]:
        company_postings = [p for p in postings if p["company_slug"] == entity["entity_key"]]
        for skill in entity["skills"]:
            name = skill["name"]
            expected_current = _count_in(company_postings, name, 2026, months=(1, 10))
            expected_previous = _count_in(company_postings, name, 2025, months=(1, 10))
            assert skill["current_period_count"] == expected_current
            assert skill["previous_period_count"] == expected_previous
            if expected_previous == 0:
                assert skill["yoy_growth_pct"] is None
            else:
                assert skill["yoy_growth_pct"] == round(
                    100 * (expected_current - expected_previous) / expected_previous, 1
                )

    # The comparison really exercises the Jan-Oct rule for at least one skill.
    differs = any(
        _count_in([p for p in postings if p["company_slug"] == entity["entity_key"]],
                  skill["name"], 2025)
        != _count_in([p for p in postings if p["company_slug"] == entity["entity_key"]],
                     skill["name"], 2025, months=(1, 10))
        for entity in body["entities"]
        for skill in entity["skills"]
    )
    assert differs


@pytest.mark.asyncio
async def test_comparison_emerging_and_shares_on_mini_dataset(client, mock_mongo):
    await _seed_mini_dataset(mock_mongo)
    token = await _register_login_tpo(client, "mkt.cmp.mini.tpo@college.edu")
    body = (
        await client.get(
            COMPARISON_URL,
            headers=_auth(token),
            params={"dimension": "company", "entities": "alpha-labs,Beta Systems"},
        )
    ).json()

    assert [e["entity_key"] for e in body["entities"]] == ["alpha-labs", "beta-systems"]
    alpha = body["entities"][0]
    beta = body["entities"][1]

    # Alpha: Rust appeared Jan-Oct 2026 but not in the comparable Jan-Oct 2025
    # window, and Alpha DID have postings in that previous window, so the
    # backend may classify it emerging — never a filter artefact.
    alpha_skills = _entity_skill_map(alpha)
    assert alpha_skills["Rust"]["trend"] == "emerging"
    assert alpha_skills["Rust"]["current_period_count"] == 1
    assert alpha_skills["Rust"]["previous_period_count"] == 0
    assert alpha_skills["Python"]["trend"] == "stable"  # 1 -> 1
    assert alpha["tech_skill_instances"] == 3  # Python 2 + Rust 1
    assert alpha["soft_skill_instances"] == 2  # Communication 2
    assert alpha["tech_share_pct"] == 60.0
    assert alpha["soft_share_pct"] == 40.0

    beta_skills = _entity_skill_map(beta)
    assert beta_skills["Legacy System"]["trend"] == "declining"  # 2 -> 1
    assert beta["tech_share_pct"] == 50.0


@pytest.mark.asyncio
async def test_job_family_comparison(client, mock_mongo, dataset):
    _, postings, _ = dataset
    families = sorted({p["job_family"] for p in postings})[:2]
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.family.tpo@college.edu",
        dimension="job_family",
        entities=",".join(families),
    )

    assert body["dimension"] == "job_family"
    assert [e["entity_key"] for e in body["entities"]] == families
    family_counters = defaultdict(Counter)
    for posting in postings:
        for skill in _skills_of(posting):
            family_counters[posting["job_family"]][skill] += 1

    for entity in body["entities"]:
        assert entity["industry"] is None  # families have no industry
        family_postings = [p for p in postings if p["job_family"] == entity["entity_key"]]
        expected = family_counters[entity["entity_key"]]
        assert entity["entity_label"] == entity["entity_key"]
        assert entity["posting_count"] == len(family_postings)
        assert entity["posting_share_pct"] == round(100 * len(family_postings) / 300, 1)
        got = _entity_skill_map(entity)
        assert set(got) == set(expected)
        for name, count in expected.items():
            assert got[name]["posting_count"] == count
            assert got[name]["demand_pct"] == round(100 * count / len(family_postings), 1)


@pytest.mark.asyncio
async def test_comparison_posting_filters_apply(client, mock_mongo, dataset):
    _, postings, _ = dataset
    slug = postings[0]["company_slug"]
    family = postings[0]["job_family"]
    location = postings[0]["location"]

    # When comparing companies, the job-family filter still narrows postings.
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.filter1.tpo@college.edu",
        dimension="company",
        entities=slug,
        job_family=family,
    )
    expected = sum(
        1 for p in postings if p["company_slug"] == slug and p["job_family"] == family
    )
    entity = body["entities"][0]
    assert entity["posting_count"] == expected
    for skill in entity["skills"]:
        company_family_postings = [
            p
            for p in postings
            if p["company_slug"] == slug and p["job_family"] == family
        ]
        count = sum(1 for p in company_family_postings if skill["name"] in _skills_of(p))
        assert skill["posting_count"] == count
        assert skill["demand_pct"] == round(100 * count / expected, 1)

    # When comparing job families, the company filter still narrows postings.
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.filter2.tpo@college.edu",
        dimension="job_family",
        entities=family,
        company=slug,
    )
    entity = body["entities"][0]
    assert entity["posting_count"] == expected

    # Year range filters apply to both dimensions.
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.filter3.tpo@college.edu",
        dimension="company",
        entities=slug,
        year_from=2025,
        location=location,
    )
    entity = body["entities"][0]
    assert entity["yearly_counts"] == {
        str(year): sum(
            1
            for p in postings
            if p["company_slug"] == slug and p["year"] == year and p["location"] == location
        )
        for year in (2025, 2026)
    }


@pytest.mark.asyncio
async def test_comparison_validation_errors(client, mock_mongo, dataset):
    await _seed_market(mock_mongo, dataset)
    token = await _register_login_tpo(client, "mkt.cmp.invalid.tpo@college.edu")
    companies = sorted({p["company_slug"] for p in dataset[1]})
    families = sorted({p["job_family"] for p in dataset[1]})

    async def get(params):
        return await client.get(COMPARISON_URL, headers=_auth(token), params=params)

    assert (await get({"dimension": "company", "entities": "not-a-company"})).status_code == 400
    assert (await get({"dimension": "job_family", "entities": "Wizardry"})).status_code == 400
    assert (await get({"dimension": "company", "entities": ",,,"})).status_code == 400
    # More than 6 distinct entities is rejected.
    assert (
        await get({"dimension": "company", "entities": ",".join(companies[:7])})
    ).status_code == 400
    # Duplicate slugs/names collapse to distinct entities.
    ok = await get(
        {
            "dimension": "job_family",
            "entities": f"{families[0]},{families[0].upper()}",
        }
    )
    assert ok.status_code == 200
    assert len(ok.json()["entities"]) == 1
    # Missing / invalid dimension is a request-validation error.
    assert (await get({"entities": families[0]})).status_code == 422
    assert (
        await get({"dimension": "skill", "entities": families[0]})
    ).status_code == 422
    assert (
        await get({"dimension": "company", "entities": families[0]})
    ).status_code == 400


@pytest.mark.asyncio
async def test_comparison_with_no_matching_postings_is_valid(client, mock_mongo, dataset):
    _, postings, _ = dataset
    slug = postings[0]["company_slug"]
    body = await _get_comparison(
        client,
        mock_mongo,
        dataset,
        "mkt.cmp.empty.tpo@college.edu",
        dimension="company",
        entities=slug,
        year_from=2030,
        year_to=2031,
    )

    entity = body["entities"][0]
    assert entity["entity_key"] == slug
    assert entity["posting_count"] == 0
    assert entity["skills"] == []
    assert entity["yearly_counts"] == {}
    assert body["meta"]["current_period"] is None
    assert body["meta"]["comparison_comparable"] is False
