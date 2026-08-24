"""
MongoDB connection lifecycle, managed via FastAPI's lifespan events.

We keep a single AsyncIOMotorClient for the process lifetime (Motor pools
connections internally, so this is the correct pattern — do not create a
new client per-request).
"""
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class MongoDB:
    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None


mongodb = MongoDB()


async def connect_to_mongo() -> None:
    logger.info("Connecting to MongoDB at %s", settings.MONGODB_URI.split("@")[-1])
    mongodb.client = AsyncIOMotorClient(settings.MONGODB_URI)
    mongodb.db = mongodb.client[settings.MONGODB_DB_NAME]
    # Fail fast if the connection string / cluster is unreachable.
    await mongodb.client.admin.command("ping")
    logger.info("MongoDB connection established.")


async def close_mongo_connection() -> None:
    if mongodb.client is not None:
        mongodb.client.close()
        logger.info("MongoDB connection closed.")


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency — returns the active database handle."""
    if mongodb.db is None:
        raise RuntimeError("Database not initialized. Was connect_to_mongo() called?")
    return mongodb.db


async def ensure_indexes() -> None:
    """
    Create all required indexes. Idempotent — safe to call on every startup.
    Extended in later phases as new collections are introduced.
    """
    db = get_database()

    await db.users.create_index("email", unique=True)

    await db.refresh_tokens.create_index("token_hash", unique=True)
    await db.refresh_tokens.create_index("expires_at", expireAfterSeconds=0)

    await db.knowledge_states.create_index(
        [("student_id", 1), ("skill_tag", 1)], unique=True
    )

    await db.questions.create_index([("category_id", 1), ("difficulty", 1)])

    await db.notifications.create_index([("user_id", 1), ("read", 1), ("created_at", -1)])

    await db.resumes.create_index([("student_id", 1), ("is_active", 1)])
    await db.resumes.create_index([("student_id", 1), ("version", -1)])

    await db.applications.create_index([("drive_id", 1), ("final_score", -1)])
    await db.applications.create_index([("drive_id", 1), ("student_id", 1)], unique=True)
    await db.applications.create_index("student_id")

    await db.placement_drives.create_index([("status", 1), ("deadline", 1)])
    await db.placement_drives.create_index("created_by")

    await db.companies.create_index("name")

    await db.assessment_attempts.create_index([("student_id", 1), ("started_at", -1)])

    await db.activity_logs.create_index([("user_id", 1), ("timestamp", -1)])
    await db.activity_logs.create_index([("entity", 1), ("entity_id", 1)])

    # Profile-to-user uniqueness — each user can have exactly one profile
    await db.students.create_index("user_id", unique=True)
    await db.tpos.create_index("user_id", unique=True)
    await db.admins.create_index("user_id", unique=True)

    # Assessment-drive linkage (Phase 2 additions)
    await db.assessments.create_index("drive_id", sparse=True)
    await db.assessment_attempts.create_index("assessment_id")
    await db.applications.create_index("assessment_attempt_id", sparse=True)

    logger.info("Indexes ensured.")
