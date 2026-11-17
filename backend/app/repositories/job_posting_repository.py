"""Repositories for the historical job-market dataset."""
from typing import Any

from app.models.market import JobMarketPostingInDB, MarketSkillCatalogInDB
from app.repositories.base import BaseRepository


class JobMarketPostingRepository(BaseRepository[JobMarketPostingInDB]):
    collection_name = "job_market_postings"
    model = JobMarketPostingInDB

    async def create_many(self, documents: list[dict[str, Any]]) -> int:
        """Validate then bulk-insert postings.

        Validation is intentionally done before the insert so a generator bug
        cannot put a malformed document into the analytics collection. The
        original dictionaries are inserted rather than model dumps: the seed
        config already uses JSON/BSON-friendly primitive values, and this
        avoids accidentally persisting enum objects.
        """
        if not documents:
            return 0
        for document in documents:
            self.model.model_validate(document)
        result = await self.collection.insert_many(documents)
        return len(result.inserted_ids)

    async def find_projected(
        self,
        query: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read raw projected documents without Pydantic model validation.

        Used by the market analytics service, which needs aggregate-level
        fields only (never job descriptions or JD text) and should not pay
        full-model validation cost for every posting on every request.
        """
        cursor = self.collection.find(query or {}, projection or {})
        if limit is not None:
            cursor = cursor.limit(limit)
        return [document async for document in cursor]

    async def distinct_values(
        self, field: str, query: dict[str, Any] | None = None
    ) -> list[Any]:
        """Distinct values of a field, optionally scoped by a query."""
        return await self.collection.distinct(field, query or {})


class MarketSkillCatalogRepository(BaseRepository[MarketSkillCatalogInDB]):
    collection_name = "market_skill_catalog"
    model = MarketSkillCatalogInDB

    async def create_many(self, documents: list[dict[str, Any]]) -> int:
        if not documents:
            return 0
        for document in documents:
            self.model.model_validate(document)
        result = await self.collection.insert_many(documents)
        return len(result.inserted_ids)
