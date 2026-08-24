from bson import ObjectId

from app.models.user import AdminInDB, StudentInDB, TPOInDB
from app.repositories.base import BaseRepository


class StudentRepository(BaseRepository[StudentInDB]):
    collection_name = "students"
    model = StudentInDB

    async def get_by_user_id(self, user_id: str) -> StudentInDB | None:
        target = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        return await self.find_one({"$or": [{"user_id": target}, {"user_id": str(user_id)}]})


class TPORepository(BaseRepository[TPOInDB]):
    collection_name = "tpos"
    model = TPOInDB

    async def get_by_user_id(self, user_id: str) -> TPOInDB | None:
        target = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        return await self.find_one({"$or": [{"user_id": target}, {"user_id": str(user_id)}]})


class AdminRepository(BaseRepository[AdminInDB]):
    collection_name = "admins"
    model = AdminInDB

    async def get_by_user_id(self, user_id: str) -> AdminInDB | None:
        target = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        return await self.find_one({"$or": [{"user_id": target}, {"user_id": str(user_id)}]})

