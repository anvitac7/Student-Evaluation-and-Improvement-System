"""Regression tests for the deterministic job-market demo dataset."""
from copy import deepcopy
from collections import Counter, defaultdict
from datetime import datetime

import pytest
from pydantic import ValidationError

from app.core.database import ensure_market_indexes
from app.models.market import JobMarketPostingInDB, MarketSkillCatalogInDB
from app.repositories.job_posting_repository import (
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)
from scripts.seed_job_market import (
    COMPANIES,
    EXPECTED_TOTAL_POSTINGS,
    JOB_FAMILIES,
    MARKET_COMPARISON_PERIOD,
    MARKET_DATASET_VERSION,
    MARKET_LATEST_YEAR,
    build_dataset,
    normalize_skill,
    validate_dataset,
)

FIXED_CREATED_AT = datetime(2026, 11, 15, 9, 0, 0)


@pytest.fixture(scope="module")
def dataset():
    return build_dataset(created_at=FIXED_CREATED_AT, verbose=False)


def test_year_distribution_and_company_coverage(dataset):
    _, postings, report = dataset

    assert len(postings) == EXPECTED_TOTAL_POSTINGS
    assert Counter(posting["year"] for posting in postings) == {
        2023: 64,
        2024: 72,
        2025: 84,
        2026: 80,
    }

    companies_by_year = defaultdict(set)
    for posting in postings:
        companies_by_year[posting["year"]].add(posting["company_name"])

    assert len(COMPANIES) == 15
    for year in (2023, 2024, 2025, 2026):
        assert companies_by_year[year] == {company["name"] for company in COMPANIES}

    assert report["comparison_period"] == MARKET_COMPARISON_PERIOD
    assert report["is_partial_year"] is True
    assert report["latest_year"] == MARKET_LATEST_YEAR


def test_job_families_span_multiple_years(dataset):
    _, postings, _ = dataset

    family_years = defaultdict(set)
    for posting in postings:
        family_years[posting["job_family"]].add(posting["year"])

    assert set(family_years) == set(JOB_FAMILIES)
    assert all(len(years) >= 2 for years in family_years.values())


def test_required_skills_are_the_union_without_duplicates(dataset):
    _, postings, _ = dataset

    for posting in postings:
        technical = posting["technical_skills"]
        soft = posting["soft_skills"]
        required = posting["required_skills"]

        assert required == technical + soft
        assert len(required) == len(set(required))
        assert not set(technical) & set(soft)


def test_external_ids_are_unique_and_deterministic(dataset):
    catalog_a, postings_a, _ = dataset
    catalog_b, postings_b, _ = build_dataset(
        created_at=FIXED_CREATED_AT, verbose=False
    )

    external_ids = [posting["external_id"] for posting in postings_a]
    assert len(external_ids) == len(set(external_ids))
    assert all(external_id.startswith("mock-") for external_id in external_ids)
    assert [posting["external_id"] for posting in postings_b] == external_ids
    assert postings_a == postings_b
    assert catalog_a == catalog_b


def test_2026_is_partial_year_and_all_mock_domains_are_reserved(dataset):
    _, postings, _ = dataset

    for posting in postings:
        assert posting["source"] == "mock"
        assert posting["dataset_version"] == MARKET_DATASET_VERSION
        assert ".example" in posting["company_website"]

        if posting["year"] == MARKET_LATEST_YEAR:
            assert posting["posted_at"] <= datetime(2026, 10, 31, 23, 59, 59)
            assert posting["month"] <= 10


def test_catalog_counts_and_alias_normalization(dataset):
    catalog, _, _ = dataset

    technical = [skill for skill in catalog if skill["is_technical"]]
    soft = [skill for skill in catalog if not skill["is_technical"]]
    assert len(technical) == 40
    assert len(soft) == 12
    assert len({skill["slug"] for skill in catalog}) == len(catalog)

    assert normalize_skill("React") == "React.js"
    assert normalize_skill("JS") == "JavaScript"
    assert normalize_skill("K8s") == "Kubernetes"
    assert normalize_skill("Postgres") == "PostgreSQL"
    assert normalize_skill("GenAI") == "Generative AI"


def test_validation_rejects_duplicate_skills(dataset):
    _, postings, _ = dataset
    bad = deepcopy(postings[0])
    bad["technical_skills"].append(bad["technical_skills"][0])
    bad["required_skills"] = bad["technical_skills"] + bad["soft_skills"]

    with pytest.raises(ValidationError):
        JobMarketPostingInDB.model_validate(bad)


def test_validation_rejects_non_example_mock_company_website(dataset):
    _, postings, _ = dataset
    bad = deepcopy(postings[0])
    bad["company_website"] = "https://www.nexoratech.com"

    with pytest.raises(ValidationError):
        JobMarketPostingInDB.model_validate(bad)


def test_validate_dataset_rejects_incomplete_year(dataset):
    catalog, postings, _ = dataset
    incomplete = deepcopy(postings)
    incomplete = [posting for posting in incomplete if posting["year"] != 2025][:299]

    with pytest.raises(ValueError):
        validate_dataset(incomplete, catalog, verbose=False)


@pytest.mark.asyncio
async def test_market_repositories_round_trip(mock_mongo, dataset):
    catalog, postings, _ = dataset
    catalog_repo = MarketSkillCatalogRepository(mock_mongo)
    posting_repo = JobMarketPostingRepository(mock_mongo)

    assert await catalog_repo.create_many(deepcopy(catalog)) == len(catalog)
    assert await posting_repo.create_many(deepcopy(postings)) == len(postings)

    assert await catalog_repo.count() == len(catalog)
    assert await catalog_repo.count({"is_technical": True}) == 40
    assert await posting_repo.count({"year": 2026}) == 80

    sample = await posting_repo.find_one(
        {"external_id": postings[0]["external_id"]}
    )
    assert sample is not None
    assert sample.required_skills == sample.technical_skills + sample.soft_skills
    assert sample.dataset_version == MARKET_DATASET_VERSION

    skill = await catalog_repo.find_one({"slug": "python"})
    assert skill is not None
    assert isinstance(skill, MarketSkillCatalogInDB)


@pytest.mark.asyncio
async def test_market_indexes_are_created(mock_mongo):
    await ensure_market_indexes(mock_mongo)

    posting_indexes = await mock_mongo.job_market_postings.index_information()
    catalog_indexes = await mock_mongo.market_skill_catalog.index_information()

    assert "external_id_1" in posting_indexes
    assert posting_indexes["external_id_1"].get("unique") is True
    assert "posted_at_1" in posting_indexes
    assert "year_1" in posting_indexes
    assert "company_slug_1" in posting_indexes
    assert "job_family_1" in posting_indexes
    assert "location_1" in posting_indexes
    assert "required_skills_1" in posting_indexes
    assert "technical_skills_1" in posting_indexes
    assert "soft_skills_1" in posting_indexes
    assert "source_1" in posting_indexes

    assert "slug_1" in catalog_indexes
    assert catalog_indexes["slug_1"].get("unique") is True
    assert "category_1" in catalog_indexes
