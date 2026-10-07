"""
Generic repository base class.

Every collection-specific repository (UserRepository, ResumeRepository, ...)
subclasses this to get consistent CRUD + pagination behavior, keeping raw
Motor/PyMongo calls out of the service layer entirely (Repository Pattern,
per project rule #8).
"""
from typing import Any, Generic, TypeVar

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    collection_name: str
    model: type[ModelT]

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db

    @property
    def collection(self) -> AsyncIOMotorCollection:
        return self._db[self.collection_name]

    async def create(self, data: dict[str, Any]) -> ModelT:
        result = await self.collection.insert_one(data)
        doc = await self.collection.find_one({"_id": result.inserted_id})
        return self.model.model_validate(doc)

    async def get_by_id(self, doc_id: str) -> ModelT | None:
        if not ObjectId.is_valid(doc_id):
            return None
        doc = await self.collection.find_one({"_id": ObjectId(doc_id)})
        return self.model.model_validate(doc) if doc else None

    async def find_one(self, query: dict[str, Any]) -> ModelT | None:
        doc = await self.collection.find_one(query)
        return self.model.model_validate(doc) if doc else None

    async def find_many(
        self,
        query: dict[str, Any] | None = None,
        page: int = 1,
        limit: int | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[ModelT]:
        """Read a slice of a collection.

        `limit=None` (the default) means NO CAP — the caller must decide
        whether an unbounded read is safe.

        This default was previously `limit=20`, which was a silent-data-loss
        footgun: any caller that forgot to pass a limit got exactly 20
        documents with no error and no indication of truncation. Two call
        sites did exactly that, and in both cases the aggregate numbers they
        fed (a student's whole assessment history; the applications linked to
        an attempt) were quietly computed from a partial view. Unbounded is
        the safer default for that failure mode: it is visible in review
        ("this reads everything") rather than invisible at runtime.

        Callers reading user-facing list endpoints should still pass an
        explicit `limit`, and anything unbounded should be scoped by a
        selective query.
        """
        query = query or {}
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.skip((page - 1) * limit).limit(limit)
        return [self.model.model_validate(doc) async for doc in cursor]

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(query or {})

    async def update_by_id(self, doc_id: str, data: dict[str, Any]) -> ModelT | None:
        if not ObjectId.is_valid(doc_id):
            return None
        await self.collection.update_one({"_id": ObjectId(doc_id)}, {"$set": data})
        return await self.get_by_id(doc_id)

    async def delete_by_id(self, doc_id: str) -> bool:
        if not ObjectId.is_valid(doc_id):
            return False
        result = await self.collection.delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count == 1
