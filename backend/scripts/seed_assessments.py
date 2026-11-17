"""Seed 10 assessments: 5 practice and 5 drive-linked.

Practice assessments are created with ``AssessmentRepository`` exactly like
the admin ``POST /assessments`` route does. Drive assessments are created the
same way first, then linked to an existing open drive through
``DriveService.update_drive`` using the owning TPO account — which is what
flips the assessment to ``type="drive"`` and sets ``drive_id``.

The five drive assessments are attached to drives whose required skills match
the seeded question categories:

    Nexora Technologies      SDE I                  -> DSA / Python / JS / OOP / SQL / SE
    CloudNest Infrastructure Backend Engineer       -> Python / SQL / Cloud / OOP / DSA
    Skyline Analytics        Data Analyst            -> SQL / Python / ML / Aptitude
    BlueOrbit Solutions      DevOps Engineer         -> Cloud / OS / Networks / Python / Cyber
    PixelForge Studios       Frontend Developer      -> JS / OOP / DSA / SE

The other five are broad practice assessments covering the rest of the bank.

Usage (from backend/):

    .venv\\Scripts\\python.exe -m scripts.seed_assessments
    .venv\\Scripts\\python.exe -m scripts.seed_assessments --force
    .venv\\Scripts\\python.exe -m scripts.seed_assessments --reset

Without --force the script refuses to append when ``assessments`` already has
documents. --force reuses assessments by title and refreshes drive links.
--reset deletes all assessments and unlinks them from drives first; it refuses
if any assessment attempt exists.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from bson import ObjectId  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.assessment import AssessmentType  # noqa: E402
from app.models.drive import DriveUpdateRequest  # noqa: E402
from app.repositories.assessment_repository import AssessmentRepository  # noqa: E402
from app.services.drive_service import DriveError, DriveService  # noqa: E402

ALL_CATEGORIES = [
    "Data Structures & Algorithms",
    "DBMS & SQL",
    "Operating Systems",
    "Computer Networks",
    "Object-Oriented Programming",
    "Python Programming",
    "JavaScript & Web Development",
    "Aptitude & Logical Reasoning",
    "Machine Learning & AI",
    "Cybersecurity",
    "Cloud & DevOps",
    "Software Engineering",
]

PRACTICE_SPECS = [
    {
        "title": "Full-Stack Placement Readiness - Practice",
        "categories": ALL_CATEGORIES,
        "question_pool_size": 10,
        "time_limit_sec": 1800,
        "max_violations": 3,
        "require_fullscreen": True,
    },
    {
        "title": "Data Structures & Algorithms Sprint - Practice",
        "categories": [
            "Data Structures & Algorithms",
            "Python Programming",
            "Object-Oriented Programming",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1200,
        "max_violations": 3,
        "require_fullscreen": True,
    },
    {
        "title": "SQL & Data Analysis Drill - Practice",
        "categories": [
            "DBMS & SQL",
            "Aptitude & Logical Reasoning",
            "Machine Learning & AI",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1200,
        "max_violations": 3,
        "require_fullscreen": True,
    },
    {
        "title": "Cybersecurity & Networks Drill - Practice",
        "categories": [
            "Cybersecurity",
            "Computer Networks",
            "Operating Systems",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1200,
        "max_violations": 3,
        "require_fullscreen": True,
    },
    {
        "title": "Software Engineering & OOP Drill - Practice",
        "categories": [
            "Software Engineering",
            "Object-Oriented Programming",
            "JavaScript & Web Development",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1200,
        "max_violations": 3,
        "require_fullscreen": True,
    },
]

DRIVE_SPECS = [
    {
        "company": "Nexora Technologies",
        "job_title": "Software Development Engineer I",
        "title": "Nexora Technologies - SDE I Coding Assessment",
        "categories": [
            "Data Structures & Algorithms",
            "Python Programming",
            "JavaScript & Web Development",
            "Object-Oriented Programming",
            "DBMS & SQL",
            "Software Engineering",
        ],
        "question_pool_size": 10,
        "time_limit_sec": 1800,
        "max_violations": 3,
        "require_fullscreen": True,
        "min_score_pct": 60.0,
        "assessment_deadline": datetime(2026, 12, 12, 23, 59, 0),
    },
    {
        "company": "CloudNest Infrastructure",
        "job_title": "Backend Engineer",
        "title": "CloudNest Infrastructure - Backend Engineer Assessment",
        "categories": [
            "Python Programming",
            "DBMS & SQL",
            "Cloud & DevOps",
            "Object-Oriented Programming",
            "Data Structures & Algorithms",
        ],
        "question_pool_size": 10,
        "time_limit_sec": 1800,
        "max_violations": 3,
        "require_fullscreen": True,
        "min_score_pct": 65.0,
        "assessment_deadline": datetime(2026, 12, 16, 23, 59, 0),
    },
    {
        "company": "Skyline Analytics",
        "job_title": "Data Analyst",
        "title": "Skyline Analytics - Data Analyst Assessment",
        "categories": [
            "DBMS & SQL",
            "Python Programming",
            "Machine Learning & AI",
            "Aptitude & Logical Reasoning",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1500,
        "max_violations": 3,
        "require_fullscreen": True,
        "min_score_pct": 60.0,
        "assessment_deadline": datetime(2026, 12, 20, 23, 59, 0),
    },
    {
        "company": "BlueOrbit Solutions",
        "job_title": "DevOps Engineer",
        "title": "BlueOrbit Solutions - DevOps Engineer Assessment",
        "categories": [
            "Cloud & DevOps",
            "Operating Systems",
            "Computer Networks",
            "Python Programming",
            "Cybersecurity",
        ],
        "question_pool_size": 10,
        "time_limit_sec": 1800,
        "max_violations": 3,
        "require_fullscreen": True,
        "min_score_pct": 60.0,
        "assessment_deadline": datetime(2026, 12, 28, 23, 59, 0),
    },
    {
        "company": "PixelForge Studios",
        "job_title": "Frontend Developer",
        "title": "PixelForge Studios - Frontend Developer Assessment",
        "categories": [
            "JavaScript & Web Development",
            "Object-Oriented Programming",
            "Data Structures & Algorithms",
            "Software Engineering",
        ],
        "question_pool_size": 8,
        "time_limit_sec": 1500,
        "max_violations": 3,
        "require_fullscreen": True,
        "min_score_pct": 60.0,
        "assessment_deadline": datetime(2027, 1, 3, 23, 59, 0),
    },
]


async def _resolve_category_ids(db, category_names: list[str]) -> list[str]:
    categories = {doc["name"]: str(doc["_id"]) async for doc in db.question_categories.find({})}
    missing = [name for name in category_names if name not in categories]
    if missing:
        raise SystemExit(
            "Missing question categories: " + ", ".join(missing) + ". "
            "Run scripts.seed_question_bank first."
        )
    return [categories[name] for name in category_names]


async def _ensure_assessment(
    assessments: AssessmentRepository,
    spec: dict,
    category_ids: list[str],
    admin_id: str,
) -> tuple:
    existing = await assessments.find_one({"title": spec["title"]})
    if existing:
        return existing, False

    assessment = await assessments.create(
        {
            "title": spec["title"],
            "category_ids": category_ids,
            "question_pool_size": spec["question_pool_size"],
            "time_limit_sec": spec["time_limit_sec"],
            "anti_cheat_config": {
                "max_violations": spec["max_violations"],
                "require_fullscreen": spec["require_fullscreen"],
            },
            "type": AssessmentType.PRACTICE.value,
            "created_by": admin_id,
        }
    )
    return assessment, True


async def _resolve_drive(db, spec: dict):
    company = await db.companies.find_one({"name": spec["company"]})
    if not company:
        raise SystemExit(f"Company not found: {spec['company']}")
    company_oid = company["_id"]
    drive = await db.placement_drives.find_one(
        {
            "company_id": {"$in": [company_oid, str(company_oid)]},
            "job_title": spec["job_title"],
        }
    )
    if not drive:
        raise SystemExit(
            f"Drive not found: {spec['company']} / {spec['job_title']}. "
            "Run scripts.seed_mock_drives first."
        )
    raw_created_by = drive["created_by"]
    created_by_oid = (
        ObjectId(raw_created_by)
        if isinstance(raw_created_by, str) and ObjectId.is_valid(raw_created_by)
        else raw_created_by
    )
    tpo = await db.tpos.find_one({"_id": created_by_oid})
    if not tpo:
        raise SystemExit(
            f"TPO profile not found for drive {spec['company']} / {spec['job_title']}."
        )
    return drive, str(tpo["user_id"])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed 10 PLACER assessments.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reuse assessments by title and refresh drive links if assessments already exist.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing assessments and unlink them from drives first.",
    )
    args = parser.parse_args()

    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]

    try:
        admin = await db.users.find_one({"email": "admin@placer.edu", "role": "admin"})
        if not admin:
            admin = await db.users.find_one({"role": "admin"})
        if not admin:
            print("No admin user found. Create one first with scripts.create_admin.")
            return
        admin_id = str(admin["_id"])

        assessment_count = await db.assessments.count_documents({})
        attempt_count = await db.assessment_attempts.count_documents({})

        if args.reset:
            if attempt_count:
                print(
                    f"Refusing --reset: {attempt_count} assessment attempt(s) exist. "
                    "Delete attempts first if you really want to replace the assessments."
                )
                return
            unlink_result = await db.placement_drives.update_many(
                {},
                {
                    "$unset": {
                        "required_assessment_id": "",
                        "assessment_min_score_pct": "",
                        "assessment_deadline": "",
                    }
                },
            )
            deleted = await db.assessments.delete_many({})
            print(
                f"Reset assessments: deleted {deleted.deleted_count} assessment(s); "
                f"unlinked {unlink_result.modified_count} drive(s)."
            )
        elif assessment_count and not args.force:
            print(
                f"assessments already has {assessment_count} document(s); refusing to append. "
                "Use --force to reuse/refresh or --reset to replace."
            )
            return

        assessments = AssessmentRepository(db)
        drive_service = DriveService(db)

        created_practice = 0
        reused_practice = 0
        created_drive = 0
        reused_drive = 0
        linked_drives = 0
        failures: list[str] = []

        print("Practice assessments:")
        for spec in PRACTICE_SPECS:
            category_ids = await _resolve_category_ids(db, spec["categories"])
            assessment, created = await _ensure_assessment(
                assessments, spec, category_ids, admin_id
            )
            if assessment.type != AssessmentType.PRACTICE:
                failures.append(
                    f"{spec['title']}: existing assessment has unexpected type "
                    f"{assessment.type.value!r}; expected practice."
                )
                print(f"  FAIL  {spec['title']} (unexpected type)")
                continue
            if created:
                created_practice += 1
                print(f"  CREATE {spec['title']} (id={assessment.id})")
            else:
                reused_practice += 1
                print(f"  REUSE  {spec['title']} (id={assessment.id})")

        print("\nDrive assessments:")
        for spec in DRIVE_SPECS:
            drive, tpo_user_id = await _resolve_drive(db, spec)
            category_ids = await _resolve_category_ids(db, spec["categories"])

            if drive.get("required_assessment_id"):
                current = await assessments.get_by_id(str(drive["required_assessment_id"]))
                if current and current.title == spec["title"]:
                    assessment = current
                    created = False
                else:
                    current_title = current.title if current else "missing assessment"
                    failures.append(
                        f"{spec['company']} / {spec['job_title']}: drive already requires "
                        f"{current_title!r}; refusing to overwrite."
                    )
                    print(
                        f"  SKIP   {spec['company']} / {spec['job_title']} "
                        f"(already requires {current_title!r})"
                    )
                    continue
            else:
                assessment, created = await _ensure_assessment(
                    assessments, spec, category_ids, admin_id
                )

            if assessment.drive_id and assessment.drive_id != str(drive["_id"]):
                failures.append(
                    f"{spec['title']}: assessment is already linked to another drive."
                )
                print(f"  SKIP   {spec['title']} (already linked to another drive)")
                continue

            try:
                await drive_service.update_drive(
                    tpo_user_id,
                    str(drive["_id"]),
                    DriveUpdateRequest(
                        required_assessment_id=assessment.id,
                        assessment_min_score_pct=spec["min_score_pct"],
                        assessment_deadline=spec["assessment_deadline"],
                    ),
                )
            except DriveError as exc:
                failures.append(
                    f"{spec['company']} / {spec['job_title']}: {exc.message}"
                )
                print(f"  FAIL   {spec['company']} / {spec['job_title']}: {exc.message}")
                continue

            linked_drives += 1
            if created:
                created_drive += 1
                print(
                    f"  CREATE {spec['title']} (id={assessment.id}) -> "
                    f"{spec['company']} / {spec['job_title']} "
                    f"(min={spec['min_score_pct']}% deadline={spec['assessment_deadline']:%Y-%m-%d})"
                )
            else:
                reused_drive += 1
                print(
                    f"  REUSE  {spec['title']} (id={assessment.id}) -> "
                    f"{spec['company']} / {spec['job_title']} "
                    f"(min={spec['min_score_pct']}% deadline={spec['assessment_deadline']:%Y-%m-%d})"
                )

        total_assessments = await db.assessments.count_documents({})
        practice_total = await db.assessments.count_documents({"type": "practice"})
        drive_total = await db.assessments.count_documents({"type": "drive"})
        linked_total = await db.placement_drives.count_documents(
            {"required_assessment_id": {"$ne": None}}
        )

        print(
            f"\nDone. practice: created={created_practice}, reused={reused_practice}; "
            f"drive: created={created_drive}, reused={reused_drive}, linked={linked_drives}, "
            f"failed={len(failures)}."
        )
        print(
            f"Collection totals: assessments={total_assessments} "
            f"(practice={practice_total}, drive={drive_total}); "
            f"drives_with_assessment={linked_total}."
        )

        print("\nFinal assessment list:")
        for doc in await db.assessments.find({}).sort("title", 1).to_list(length=None):
            drive_label = ""
            if doc.get("drive_id"):
                raw_drive_id = doc["drive_id"]
                drive_oid = (
                    ObjectId(raw_drive_id)
                    if isinstance(raw_drive_id, str) and ObjectId.is_valid(raw_drive_id)
                    else raw_drive_id
                )
                drive = await db.placement_drives.find_one({"_id": drive_oid})
                company = None
                if drive:
                    raw_company_id = drive.get("company_id")
                    company_oid = (
                        ObjectId(raw_company_id)
                        if isinstance(raw_company_id, str) and ObjectId.is_valid(raw_company_id)
                        else raw_company_id
                    )
                    company = await db.companies.find_one({"_id": company_oid})
                drive_label = (
                    f" -> {company['name']} / {drive['job_title']}" if drive and company else ""
                )
            print(
                f"  {doc['type']:8s} | pool={doc['question_pool_size']:2d} | "
                f"{doc['time_limit_sec'] // 60:2d} min | {doc['title']}{drive_label}"
            )

        if failures:
            print("\nFailures:")
            for failure in failures:
                print(f"  - {failure}")
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
