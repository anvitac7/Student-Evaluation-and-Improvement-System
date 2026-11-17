"""TPO Skill Gap Analysis (Phase 8) tests.

Pinned behaviors:

- TPO-only authorization on all three endpoints (401/403/200).
- Industry demand is recomputed from the seeded Market Insights dataset and
  must match exactly, with the same filter semantics as the market dashboard.
- Assessment evidence comes ONLY from the
  Placement Drive -> required_assessment_id -> submitted attempt chain.
  Practice attempts, standalone (never-linked) assessments and in-progress
  attempts can NEVER contribute — even an in-progress attempt full of
  correct answers must not demonstrate anything.
- Multiple eligible assessments combine (documented rule: all submitted
  attempts combined per graded answer, deduped by attempt id), and retakes
  combine rather than taking the best attempt.
- Self-reported skills (profile + active resume) normalize through the
  market catalog (names + aliases) and are kept strictly separate from
  demonstrated proficiency.
- Gap/priority math is deterministic and matches the documented formulas.
- No operational collection is mutated by the read-only endpoints.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from bson import ObjectId

from app.core import database as db_module
from app.models.user import (
    AdminRegisterRequest,
    StudentRegisterRequest,
    TPORegisterRequest,
)
from app.repositories.job_posting_repository import (
    JobMarketPostingRepository,
    MarketSkillCatalogRepository,
)
from app.services.auth_service import AuthService

PASSWORD = "StrongPass123"
SKILL_GAPS_URL = "/api/v1/analytics/tpo/skill-gaps"
SKILL_GAPS_FILTERS_URL = "/api/v1/analytics/tpo/skill-gaps/filters"
FUTURE_DEADLINE = (datetime.utcnow() + timedelta(days=30)).isoformat()
MINIMAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# Market dataset (small, fully controlled)
# ---------------------------------------------------------------------------

CATALOG = [
    {
        "name": "Python",
        "slug": "python",
        "category": "Programming Language",
        "is_technical": True,
        "aliases": ["py"],
        "source": "mock",
    },
    {
        "name": "React",
        "slug": "react",
        "category": "Frontend",
        "is_technical": True,
        "aliases": ["reactjs"],
        "source": "mock",
    },
    {
        "name": "Communication",
        "slug": "communication",
        "category": "Soft Skill",
        "is_technical": False,
        "aliases": [],
        "source": "mock",
    },
]


def _posting(external_id, year, month, company_name, company_slug, job_family, technical, soft):
    """A market posting passing every JobMarketPostingInDB validator."""
    posted_at = datetime(year, month, 10, 12, 0, 0)
    return {
        "external_id": external_id,
        "dataset_version": "2026.11",
        "source": "mock",
        "company_name": company_name,
        "company_slug": company_slug,
        "company_industry": "Software",
        "company_size": "201-500",
        "company_hq": "Pune",
        "company_website": f"https://{company_slug}.example",
        "job_title": "Engineer",
        "job_family": job_family,
        "seniority": "Entry",
        "hiring_type": "Full-time",
        "description": "Build things.",
        "jd_text": "Required: skills.",
        "technical_skills": technical,
        "soft_skills": soft,
        "required_skills": technical + soft,
        "min_experience_years": 0.0,
        "education_level": "B.Tech",
        "eligible_departments": ["CS"],
        "min_cgpa": 0.0,
        "location": "Pune",
        "work_mode": "Hybrid",
        "salary_band": "5-8 LPA",
        "salary_min_lpa": 5.0,
        "salary_max_lpa": 8.0,
        "posted_at": posted_at,
        "year": year,
        "quarter": (month - 1) // 3 + 1,
        "month": month,
        "is_active": False,
        "created_at": datetime(2026, 11, 15, 9, 0, 0),
    }


POSTINGS = [
    _posting("mock-p1", 2025, 3, "Alpha Labs", "alpha-labs", "Software Engineering", ["Python"], ["Communication"]),
    _posting("mock-p2", 2025, 5, "Beta Systems", "beta-systems", "Frontend Engineering", ["React"], ["Communication"]),
    _posting("mock-p3", 2026, 2, "Alpha Labs", "alpha-labs", "Software Engineering", ["Python", "React"], ["Communication"]),
    _posting("mock-p4", 2026, 6, "Beta Systems", "beta-systems", "Data & Analytics", ["Python"], ["Communication"]),
    _posting("mock-p5", 2026, 8, "Gamma Corp", "gamma-corp", "Software Engineering", ["React"], ["Communication"]),
]


async def _seed_market(mock_mongo):
    if await mock_mongo.market_skill_catalog.count_documents({}) == 0:
        await MarketSkillCatalogRepository(mock_mongo).create_many(deepcopy(CATALOG))
    if await mock_mongo.job_market_postings.count_documents({}) == 0:
        await JobMarketPostingRepository(mock_mongo).create_many(deepcopy(POSTINGS))


# ---------------------------------------------------------------------------
# Operational data builders
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _login(client, email) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _register_direct(email, name, role="student"):
    """Register via the service (no HTTP -> no rate limiter involvement)."""
    service = AuthService(db_module.mongodb.db)
    if role == "student":
        await service.register_student(
            StudentRegisterRequest(
                email=email, password=PASSWORD, name=name, department="CS", batch_year=2026
            )
        )
    elif role == "tpo":
        await service.register_tpo(
            TPORegisterRequest(email=email, password=PASSWORD, name=name, department_scope=[])
        )
    else:
        await service.register_admin(
            AdminRegisterRequest(email=email, password=PASSWORD, name=name)
        )


async def _profile_id(email) -> str:
    """The STUDENT PROFILE id (what attempts/applications key on)."""
    db = db_module.mongodb.db
    user = await db.users.find_one({"email": email})
    student = await db.students.find_one({"user_id": str(user["_id"])})
    return str(student["_id"])


async def _set_profile_skills(profile_id: str, skills: list[str]) -> None:
    await db_module.mongodb.db.students.update_one(
        {"_id": ObjectId(profile_id)}, {"$set": {"skills": skills}}
    )


async def _insert_resume(profile_id: str, skill_set: list[str]) -> None:
    """An ACTIVE resume with an extracted skill_set (self-reported source)."""
    await db_module.mongodb.db.resumes.insert_one(
        {
            "student_id": profile_id,
            "version": 1,
            "original_filename": "resume.pdf",
            "file_url": "mem://resume",
            "file_hash": uuid4().hex,
            "file_size_bytes": 100,
            "parsed": None,
            "resume_text": None,
            "skill_set": skill_set,
            "experience_years": None,
            "resume_embedding": None,
            "uploaded_at": datetime.utcnow(),
            "is_active": True,
        }
    )


async def _create_question(client, admin_token, category_name, skill_tags, count=1):
    category = await client.post(
        "/api/v1/questions/categories",
        headers=_auth(admin_token),
        json={"name": category_name},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    question_ids = []
    for index in range(count):
        response = await client.post(
            "/api/v1/questions",
            headers=_auth(admin_token),
            json={
                "category_id": category_id,
                "skill_tags": skill_tags,
                "difficulty": "medium",
                "type": "mcq",
                "text": f"{category_name} question {index}?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A",
            },
        )
        assert response.status_code == 201, response.text
        question_ids.append(response.json()["id"])
    return category_id, question_ids


async def _create_assessment(client, admin_token, title, category_ids, pool_size, type_):
    response = await client.post(
        "/api/v1/assessments",
        headers=_auth(admin_token),
        json={
            "title": title,
            "category_ids": category_ids,
            "question_pool_size": pool_size,
            "time_limit_sec": 600,
            "max_violations": 3,
            "require_fullscreen": False,
            "type": type_,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_drive(client, tpo_token, title_suffix, assessment_id=None):
    payload = {
        "company_name": "Skill Gap Corp",
        "job_title": f"Backend Engineer {title_suffix}",
        "description": "Build backends",
        "jd_text": "We need a backend engineer.",
        "required_skills": ["Python"],
        "eligibility": {},
        "deadline": FUTURE_DEADLINE,
        "selection_process": [],
    }
    if assessment_id:
        payload["required_assessment_id"] = assessment_id
    response = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _apply(client, student_token, drive_id):
    await client.post(
        "/api/v1/resumes",
        headers=_auth(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    response = await client.post(
        f"/api/v1/drives/{drive_id}/apply", headers=_auth(student_token)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _insert_application(drive_id: str, profile_id: str) -> None:
    await db_module.mongodb.db.applications.insert_one(
        {
            "drive_id": drive_id,
            "student_id": profile_id,
            "resume_id": str(ObjectId()),
            "status": "applied",
            "eligibility_reasons": [],
            "matched_skills": [],
            "missing_skills": [],
            "rejection_reasons": [],
            "assessment_status": "not_required",
            "applied_at": datetime.utcnow(),
        }
    )


def _answer_doc(question_id: str, is_correct: bool) -> dict:
    return {
        "question_id": question_id,
        "response": "A" if is_correct else "B",
        "is_correct": is_correct,
        "marks_awarded": 3 if is_correct else 0,
        "time_taken_sec": 10.0,
        "difficulty_at_time": "medium",
        "question_type": "mcq",
        "code_result": None,
    }


async def _insert_attempt(
    assessment_id: str,
    profile_id: str,
    question_ids: list[str],
    correctness: list[bool],
    status: str = "submitted",
) -> str:
    """Insert an attempt straight into the attempts collection.

    The skill-gap service only reads answers' ``is_correct`` plus the
    questions' ``skill_tags``, so a direct insert exercises exactly the
    evidence rules while keeping each scenario precise.
    """
    doc = {
        "assessment_id": assessment_id,
        "student_id": profile_id,
        "session_token": uuid4().hex,
        "asked_question_ids": question_ids[: len(correctness)],
        "current_question_id": None,
        "current_difficulty": "medium",
        "answers": [
            _answer_doc(question_id, is_correct)
            for question_id, is_correct in zip(question_ids, correctness)
        ],
        "violations": [],
        "status": status,
        "started_at": datetime.utcnow(),
        "submitted_at": datetime.utcnow() if status == "submitted" else None,
    }
    result = await db_module.mongodb.db.assessment_attempts.insert_one(doc)
    return str(result.inserted_id)


async def _run_api_attempt(
    client, student_token, assessment_id, application_id, correctness
) -> str:
    """Real end-to-end attempt through the assessment API."""
    start = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json={"fingerprint_hash": None, "application_id": application_id},
    )
    assert start.status_code == 201, start.text
    body = start.json()
    answered = 0
    while True:
        question = body.get("next_question")
        if question is None:
            break
        response = await client.post(
            f"/api/v1/assessments/attempts/{body['attempt_id']}/answer",
            headers=_auth(student_token),
            json={
                "session_token": body["session_token"],
                "question_id": question["id"],
                "response": "A" if correctness[answered] else "B",
                "time_taken_sec": 10.0,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        answered += 1
        if data["attempt_status"] == "submitted":
            break
        body["next_question"] = data.get("next_question")
    return body["attempt_id"]


async def _get_skill_gaps(client, tpo_token, **params):
    response = await client.get(SKILL_GAPS_URL, headers=_auth(tpo_token), params=params or None)
    assert response.status_code == 200, response.text
    return response.json()


def _skill(response_json, name):
    matches = [entry for entry in response_json["skills"] if entry["name"] == name]
    assert len(matches) == 1, f"expected exactly one {name} row, got {matches}"
    return matches[0]


# ---------------------------------------------------------------------------
# The standard scenario world (10 students, see each test's assertions)
# ---------------------------------------------------------------------------


async def _build_world(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.admin@college.edu", "SG Admin", "admin")
    await _register_direct("sg.tpo@college.edu", "SG TPO", "tpo")
    admin_token = await _login(client, "sg.admin@college.edu")
    tpo_token = await _login(client, "sg.tpo@college.edu")

    core_cat, python_questions = await _create_question(
        client, admin_token, "Python Core", ["Python"], count=3
    )
    quick_cat, single_question = await _create_question(
        client, admin_token, "Python Quick", ["Python"], count=1
    )
    practice_cat, practice_questions = await _create_question(
        client, admin_token, "Practice Python", ["Python"], count=3
    )
    orphan_cat, orphan_questions = await _create_question(
        client, admin_token, "Orphan Python", ["Python"], count=3
    )

    assessment_full = await _create_assessment(
        client, admin_token, "Backend Screen", [core_cat], 3, "drive"
    )
    assessment_single = await _create_assessment(
        client, admin_token, "Quick Screen", [quick_cat], 1, "drive"
    )
    assessment_practice = await _create_assessment(
        client, admin_token, "Practice Rounds", [practice_cat], 3, "practice"
    )
    assessment_orphan = await _create_assessment(
        client, admin_token, "Unlinked Screen", [orphan_cat], 3, "drive"
    )

    drive_full = await _create_drive(client, tpo_token, "One", assessment_full)
    drive_single = await _create_drive(client, tpo_token, "Two", assessment_single)

    student_emails = [
        "sg.alice@college.edu",
        "sg.bob@college.edu",
        "sg.carol@college.edu",
        "sg.dave@college.edu",
        "sg.eve@college.edu",
        "sg.frank@college.edu",
        "sg.jack@college.edu",
        "sg.grace@college.edu",
        "sg.henry@college.edu",
        "sg.iris@college.edu",
    ]
    for email in student_emails:
        await _register_direct(email, email.split("@")[0].replace("sg.", "").title())

    alice_profile = await _profile_id("sg.alice@college.edu")
    bob_profile = await _profile_id("sg.bob@college.edu")
    carol_profile = await _profile_id("sg.carol@college.edu")
    dave_profile = await _profile_id("sg.dave@college.edu")
    eve_profile = await _profile_id("sg.eve@college.edu")
    frank_profile = await _profile_id("sg.frank@college.edu")
    jack_profile = await _profile_id("sg.jack@college.edu")
    grace_profile = await _profile_id("sg.grace@college.edu")
    henry_profile = await _profile_id("sg.henry@college.edu")

    # alice goes through the REAL application + attempt flow end to end.
    alice_token = await _login(client, "sg.alice@college.edu")
    application_id = await _apply(client, alice_token, drive_full)
    await _run_api_attempt(
        client, alice_token, assessment_full, application_id, [True, True, True]
    )

    # everyone else: precise direct inserts
    for profile in (bob_profile, carol_profile, jack_profile, henry_profile):
        await _insert_application(drive_full, profile)
    await _insert_application(drive_single, dave_profile)
    await _insert_attempt(assessment_full, bob_profile, python_questions, [False, False, True])
    await _insert_attempt(assessment_full, carol_profile, python_questions, [True, True, False])
    await _insert_attempt(assessment_single, dave_profile, single_question, [True])
    await _insert_attempt(assessment_full, henry_profile, python_questions, [True, True, True])
    # jack: in-progress with three CORRECT answers — must still be ignored.
    await _insert_attempt(
        assessment_full, jack_profile, python_questions, [True, True, True], status="in_progress"
    )
    # eve: practice attempt (never linked to a drive).
    eve_token = await _login(client, "sg.eve@college.edu")
    await _run_api_attempt(
        client, eve_token, assessment_practice, None, [True, True, True]
    )
    # frank: submitted attempt on a drive-type assessment that NO drive links.
    await _insert_attempt(assessment_orphan, frank_profile, orphan_questions, [True, True, True])

    # self-reported evidence
    await _set_profile_skills(grace_profile, ["py", "ReactJS"])  # both aliases
    await _set_profile_skills(henry_profile, ["Python"])

    return {
        "admin_token": admin_token,
        "tpo_token": tpo_token,
        "assessment_full": assessment_full,
        "python_questions": python_questions,
        "drive_full": drive_full,
        "population": 10,
    }


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_gap_endpoints_require_tpo_role(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.rbac.tpo@college.edu", "RBAC TPO", "tpo")
    await _register_direct("sg.rbac.student@college.edu", "RBAC Student")
    await _register_direct("sg.rbac.admin@college.edu", "RBAC Admin", "admin")
    tpo = await _login(client, "sg.rbac.tpo@college.edu")
    student = await _login(client, "sg.rbac.student@college.edu")
    admin = await _login(client, "sg.rbac.admin@college.edu")

    for url in (SKILL_GAPS_URL, SKILL_GAPS_FILTERS_URL):
        assert (await client.get(url)).status_code == 401, url
        assert (await client.get(url, headers=_auth(student))).status_code == 403, url
        assert (await client.get(url, headers=_auth(admin))).status_code == 403, url
        assert (await client.get(url, headers=_auth(tpo))).status_code == 200, url

    students_url = f"{SKILL_GAPS_URL}/python/students"
    assert (await client.get(students_url)).status_code == 401
    assert (await client.get(students_url, headers=_auth(student))).status_code == 403
    assert (await client.get(students_url, headers=_auth(admin))).status_code == 403
    assert (await client.get(students_url, headers=_auth(tpo))).status_code == 200


@pytest.mark.asyncio
async def test_students_endpoint_unknown_skill_returns_404(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.unknown.tpo@college.edu", "Unknown TPO", "tpo")
    token = await _login(client, "sg.unknown.tpo@college.edu")
    response = await client.get(
        f"{SKILL_GAPS_URL}/no-such-skill/students", headers=_auth(token)
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Industry demand (Market Insights dataset, same filter semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demand_counts_match_market_dataset(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.demand.tpo@college.edu", "Demand TPO", "tpo")
    token = await _login(client, "sg.demand.tpo@college.edu")
    data = await _get_skill_gaps(client, token)

    # Only the demanded skills appear as rows.
    assert {entry["name"] for entry in data["skills"]} == {"Python", "React", "Communication"}
    # total_postings = 5: Python 3/5, React 3/5, Communication 5/5.
    assert _skill(data, "Python")["posting_count"] == 3
    assert _skill(data, "Python")["demand_pct"] == 60.0
    assert _skill(data, "React")["posting_count"] == 3
    assert _skill(data, "React")["demand_pct"] == 60.0
    assert _skill(data, "Communication")["posting_count"] == 5
    assert _skill(data, "Communication")["demand_pct"] == 100.0

    # Demand comes from the market dataset only — mock metadata is preserved.
    assert data["meta"]["market"]["is_mock_data"] is True
    assert data["meta"]["market"]["disclaimer"]
    # Comparable Jan-Oct 2026 vs Jan-Oct 2025 window.
    assert data["meta"]["market"]["comparison_comparable"] is True
    assert data["meta"]["market"]["current_period"]["label"] == "Jan-Oct 2026"

    # Company/family demand comes from the same aggregation pass.
    py = _skill(data, "Python")
    assert py["demanding_company_count"] == 2  # Alpha Labs + Beta Systems
    assert py["demanding_job_family_count"] == 2
    assert py["top_companies"][0]["company_slug"] == "alpha-labs"
    assert py["top_companies"][0]["posting_count"] == 2
    assert py["top_companies"][0]["demand_pct"] == 100.0  # 2 of Alpha's 2 postings


@pytest.mark.asyncio
async def test_company_filter_changes_demand_denominator(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.filter.tpo@college.edu", "Filter TPO", "tpo")
    token = await _login(client, "sg.filter.tpo@college.edu")
    data = await _get_skill_gaps(client, token, company="alpha-labs")

    # Alpha Labs has 2 postings (P1: Python+Communication, P3: Python+React+Communication)
    assert _skill(data, "Python")["posting_count"] == 2
    assert _skill(data, "Python")["demand_pct"] == 100.0
    assert _skill(data, "React")["posting_count"] == 1
    assert _skill(data, "React")["demand_pct"] == 50.0
    assert _skill(data, "Communication")["posting_count"] == 2
    assert _skill(data, "Communication")["demand_pct"] == 100.0


@pytest.mark.asyncio
async def test_invalid_filters_rejected(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.invalid.tpo@college.edu", "Invalid TPO", "tpo")
    token = await _login(client, "sg.invalid.tpo@college.edu")

    unknown = await client.get(
        SKILL_GAPS_URL, headers=_auth(token), params={"company": "no-such-company"}
    )
    assert unknown.status_code == 400

    inverted = await client.get(
        SKILL_GAPS_URL, headers=_auth(token), params={"year_from": 2026, "year_to": 2025}
    )
    assert inverted.status_code == 400


@pytest.mark.asyncio
async def test_filters_endpoint_matches_market_dataset(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.filters.tpo@college.edu", "Filters TPO", "tpo")
    token = await _login(client, "sg.filters.tpo@college.edu")
    response = await client.get(SKILL_GAPS_FILTERS_URL, headers=_auth(token))
    assert response.status_code == 200
    data = response.json()
    assert set(data["years"]) == {2025, 2026}
    assert {c["slug"] for c in data["companies"]} == {
        "alpha-labs", "beta-systems", "gamma-corp",
    }
    assert "Software Engineering" in data["job_families"]
    assert "Pune" in data["locations"]


# ---------------------------------------------------------------------------
# Assessment evidence (drive chain only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drive_assessment_evidence_full_scenario(client, mock_mongo):
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    python = _skill(data, "Python")

    # alice (API flow, 3/3) + henry (3/3) demonstrated; bob 1/3; carol 2/3;
    # dave 1 graded answer (insufficient). eve/practice, frank/orphan and
    # jack/in-progress NEVER contribute.
    assert python["students_demonstrated"] == 2  # alice, henry
    assert python["students_developing"] == 1  # carol
    assert python["students_not_demonstrated"] == 1  # bob
    assert python["students_insufficient_evidence"] == 1  # dave
    assert python["students_reported"] == 2  # grace, henry
    assert python["students_both"] == 1  # henry
    assert python["students_reported_only"] == 1  # grace
    assert python["students_no_evidence"] == 4  # eve, frank, iris, jack
    assert python["students_lacking_demonstrated"] == 8  # 10 - 2
    assert python["demonstrated_pct"] == 20.0
    assert python["gap_pct"] == 80.0

    # Only the drive attempts were used as evidence (5 submitted: alice, bob,
    # carol, dave, henry — NOT eve's practice or frank's orphan attempt).
    assert data["meta"]["submitted_eligible_attempt_count"] == 5
    assert data["meta"]["eligible_assessment_count"] == 2
    assert data["meta"]["eligible_drive_count"] == 2

    # Students endpoint lists the WHOLE population with their evidence
    # classification for the skill (no_evidence students included — they are
    # the training audience); each classification filter narrows it.
    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(world["tpo_token"]), params={"limit": 100})
    assert response.status_code == 200, response.text
    students = {e["student_id"]: e for e in response.json()["entries"]}
    assert response.json()["total"] == 10

    by_name = {e["student_name"]: e for e in response.json()["entries"]}
    alice = by_name["Alice"]
    assert alice["classification"] == "demonstrated"
    assert alice["assessment_classification"] == "demonstrated"
    assert alice["skill_accuracy_pct"] == 100.0
    assert alice["self_reported"] is False
    assert alice["questions_answered"] == 3
    assert len(alice["assessment_evidence"]) == 1
    assert alice["assessment_evidence"][0]["assessment_title"] == "Backend Screen"

    assert by_name["Carol"]["classification"] == "developing"
    assert by_name["Carol"]["skill_accuracy_pct"] == 66.7
    assert by_name["Bob"]["classification"] == "not_demonstrated"
    assert by_name["Bob"]["skill_accuracy_pct"] == 33.3
    assert by_name["Dave"]["classification"] == "insufficient_evidence"
    assert by_name["Dave"]["skill_accuracy_pct"] == 100.0  # shown, but unclassified
    assert by_name["Dave"]["assessment_classification"] == "insufficient_evidence"
    assert by_name["Henry"]["classification"] == "both"
    assert by_name["Grace"]["classification"] == "reported_only"
    assert by_name["Grace"]["self_reported_via"] == ["profile"]
    assert by_name["Eve"]["classification"] == "no_evidence"
    assert by_name["Eve"]["questions_answered"] == 0
    assert by_name["Jack"]["classification"] == "no_evidence"
    assert by_name["Jack"]["questions_answered"] == 0
    assert by_name["Iris"]["classification"] == "no_evidence"

    # Privacy: only analytics fields, never contact data.
    assert "email" not in alice
    assert all("email" not in e for e in response.json()["entries"])


@pytest.mark.asyncio
async def test_practice_attempts_never_contribute(client, mock_mongo):
    """Explicit proof: a practice assessment attempt with a PERFECT score on
    the same skill changes nothing — no possession, no proficiency, no gap."""
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    python = _skill(data, "Python")

    # Eve's 3/3 practice attempt must not appear anywhere:
    assert python["students_demonstrated"] == 2
    assert python["students_developing"] == 1
    assert python["students_not_demonstrated"] == 1
    assert python["students_insufficient_evidence"] == 1
    assert data["meta"]["submitted_eligible_attempt_count"] == 5  # practice attempt excluded

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(world["tpo_token"]), params={"limit": 100})
    by_name = {e["student_name"]: e for e in response.json()["entries"]}
    eve = by_name["Eve"]
    assert eve["classification"] == "no_evidence"
    assert eve["assessment_classification"] is None
    assert eve["questions_answered"] == 0
    assert eve["assessment_evidence"] == []

    # React/Communication rows are unaffected by practice data too.
    assert _skill(data, "React")["students_demonstrated"] == 0


@pytest.mark.asyncio
async def test_standalone_assessments_never_contribute(client, mock_mongo):
    """A drive-type assessment that no drive references is standalone for
    skill-gap purposes — its submitted attempts must be invisible."""
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    python = _skill(data, "Python")

    # Frank's 3/3 orphan attempt changes nothing.
    assert python["students_demonstrated"] == 2
    assert data["meta"]["submitted_eligible_attempt_count"] == 5

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(world["tpo_token"]), params={"limit": 100})
    by_name = {e["student_name"]: e for e in response.json()["entries"]}
    assert by_name["Frank"]["classification"] == "no_evidence"
    assert by_name["Frank"]["questions_answered"] == 0


@pytest.mark.asyncio
async def test_in_progress_attempts_never_demonstrate(client, mock_mongo):
    """Even an in-progress attempt full of CORRECT answers is not evidence —
    only submitted attempts count, per the existing assessment rules."""
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    python = _skill(data, "Python")

    assert python["students_demonstrated"] == 2
    assert python["students_insufficient_evidence"] == 1  # only dave

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(world["tpo_token"]), params={"limit": 100})
    by_name = {e["student_name"]: e for e in response.json()["entries"]}
    jack = by_name["Jack"]
    assert jack["classification"] == "no_evidence"
    assert jack["questions_answered"] == 0
    assert jack["assessment_classification"] is None


@pytest.mark.asyncio
async def test_unmapped_skill_tags_reported_not_dropped(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.unmapped.admin@college.edu", "Unmapped Admin", "admin")
    await _register_direct("sg.unmapped.tpo@college.edu", "Unmapped TPO", "tpo")
    admin_token = await _login(client, "sg.unmapped.admin@college.edu")
    tpo_token = await _login(client, "sg.unmapped.tpo@college.edu")

    weird_category_id, weird_questions = await _create_question(
        client, admin_token, "Weird Tag", ["Quantum Blockchain Bizdev"], count=3
    )
    assessment = await _create_assessment(
        client, admin_token, "Weird Screen", [weird_category_id], 3, "drive"
    )
    drive = await _create_drive(client, tpo_token, "Weird", assessment)
    await _register_direct("sg.unmapped.student@college.edu", "Unmapped Student")
    profile = await _profile_id("sg.unmapped.student@college.edu")
    await _insert_application(drive, profile)
    await _insert_attempt(assessment, profile, weird_questions, [True, True, True])

    data = await _get_skill_gaps(client, tpo_token)
    # The unmapped tag created no fake skill row, but it IS reported.
    assert {e["name"] for e in data["skills"]} == {"Python", "React", "Communication"}
    assert data["meta"]["unmapped_assessment_skill_tags"] == ["Quantum Blockchain Bizdev"]
    # Nothing crashed and the mapped rows still work.
    assert data["summary"]["student_population"] == 1


@pytest.mark.asyncio
async def test_shared_assessment_never_double_counts(client, mock_mongo):
    """Two drives referencing the SAME assessment: one attempt, one application
    set — the attempt's answers count exactly once."""
    await _seed_market(mock_mongo)
    await _register_direct("sg.shared.admin@college.edu", "Shared Admin", "admin")
    await _register_direct("sg.shared.tpo@college.edu", "Shared TPO", "tpo")
    admin_token = await _login(client, "sg.shared.admin@college.edu")
    tpo_token = await _login(client, "sg.shared.tpo@college.edu")

    shared_category, python_questions = await _create_question(
        client, admin_token, "Shared Python", ["Python"], count=3
    )
    assessment = await _create_assessment(
        client, admin_token, "Shared Screen", [shared_category], 3, "drive"
    )
    drive_a = await _create_drive(client, tpo_token, "A", assessment)
    drive_b = await _create_drive(client, tpo_token, "B", assessment)

    await _register_direct("sg.shared.student@college.edu", "Shared Student")
    profile = await _profile_id("sg.shared.student@college.edu")
    await _insert_application(drive_a, profile)
    await _insert_application(drive_b, profile)
    await _insert_attempt(assessment, profile, python_questions, [True, True, True])

    data = await _get_skill_gaps(client, tpo_token)
    python = _skill(data, "Python")
    assert python["students_demonstrated"] == 1
    assert data["meta"]["submitted_eligible_attempt_count"] == 1
    assert data["meta"]["eligible_drive_count"] == 2
    assert data["meta"]["eligible_assessment_count"] == 1

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(tpo_token), params={"limit": 10})
    entry = response.json()["entries"][0]
    assert entry["questions_answered"] == 3  # not 6
    assert entry["correct_answers"] == 3
    assert entry["assessment_evidence"][0]["attempts_used"] == 1


@pytest.mark.asyncio
async def test_multiple_drive_assessments_combine_per_student(client, mock_mongo):
    """A student with attempts on two DIFFERENT drive assessments combines the
    evidence (documented rule), and each assessment shows in the breakdown."""
    await _seed_market(mock_mongo)
    await _register_direct("sg.combine.admin@college.edu", "Combine Admin", "admin")
    await _register_direct("sg.combine.tpo@college.edu", "Combine TPO", "tpo")
    admin_token = await _login(client, "sg.combine.admin@college.edu")
    tpo_token = await _login(client, "sg.combine.tpo@college.edu")

    cat_one, q1 = await _create_question(client, admin_token, "Combine One", ["Python"], count=3)
    cat_two, q2 = await _create_question(client, admin_token, "Combine Two", ["Python"], count=3)
    assessment_one = await _create_assessment(
        client, admin_token, "Combine Screen One", [cat_one], 3, "drive"
    )
    assessment_two = await _create_assessment(
        client, admin_token, "Combine Screen Two", [cat_two], 3, "drive"
    )
    drive_one = await _create_drive(client, tpo_token, "C1", assessment_one)
    drive_two = await _create_drive(client, tpo_token, "C2", assessment_two)

    await _register_direct("sg.combine.student@college.edu", "Combine Student")
    profile = await _profile_id("sg.combine.student@college.edu")
    await _insert_application(drive_one, profile)
    await _insert_application(drive_two, profile)
    await _insert_attempt(assessment_one, profile, q1, [True, True, True])
    await _insert_attempt(assessment_two, profile, q2, [True, False, False])

    data = await _get_skill_gaps(client, tpo_token)
    python = _skill(data, "Python")
    # Combined: 4/6 = 66.7% -> developing (NOT the best attempt's 100%).
    assert python["students_demonstrated"] == 0
    assert python["students_developing"] == 1
    assert data["meta"]["submitted_eligible_attempt_count"] == 2

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(tpo_token), params={"limit": 10})
    entry = response.json()["entries"][0]
    assert entry["classification"] == "developing"
    assert entry["skill_accuracy_pct"] == 66.7
    assert entry["questions_answered"] == 6
    assert entry["correct_answers"] == 4
    titles = {e["assessment_title"] for e in entry["assessment_evidence"]}
    assert titles == {"Combine Screen One", "Combine Screen Two"}


@pytest.mark.asyncio
async def test_retakes_combine_instead_of_best_attempt(client, mock_mongo):
    """Retake aggregation rule: ALL submitted attempts combine. A perfect
    first attempt followed by a failed retake is 3/6 = 50% (developing), NOT
    the best attempt's 100% (that rule belongs to the per-drive ranking)."""
    await _seed_market(mock_mongo)
    await _register_direct("sg.retake.admin@college.edu", "Retake Admin", "admin")
    await _register_direct("sg.retake.tpo@college.edu", "Retake TPO", "tpo")
    admin_token = await _login(client, "sg.retake.admin@college.edu")
    tpo_token = await _login(client, "sg.retake.tpo@college.edu")

    retake_category, python_questions = await _create_question(
        client, admin_token, "Retake Python", ["Python"], count=3
    )
    assessment = await _create_assessment(
        client, admin_token, "Retake Screen", [retake_category], 3, "drive"
    )
    drive = await _create_drive(client, tpo_token, "R", assessment)
    await _register_direct("sg.retake.student@college.edu", "Retake Student")
    profile = await _profile_id("sg.retake.student@college.edu")
    await _insert_application(drive, profile)
    await _insert_attempt(assessment, profile, python_questions, [True, True, True])
    await _insert_attempt(assessment, profile, python_questions, [False, False, False])

    data = await _get_skill_gaps(client, tpo_token)
    python = _skill(data, "Python")
    assert python["students_demonstrated"] == 0
    assert python["students_developing"] == 1
    assert data["meta"]["submitted_eligible_attempt_count"] == 2

    url = f"{SKILL_GAPS_URL}/python/students"
    response = await client.get(url, headers=_auth(tpo_token), params={"limit": 10})
    entry = response.json()["entries"][0]
    assert entry["classification"] == "developing"
    assert entry["skill_accuracy_pct"] == 50.0
    evidence = entry["assessment_evidence"][0]
    assert evidence["attempts_used"] == 2
    assert evidence["questions_answered"] == 6
    assert evidence["correct_answers"] == 3


# ---------------------------------------------------------------------------
# Self-reported evidence (profile + active resume)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alias_normalization_and_resume_source(client, mock_mongo):
    await _build_world(client, mock_mongo)
    # Extra student whose ACTIVE resume reports React via a raw name.
    await _register_direct("sg.resume.student@college.edu", "Resume Student")
    profile = await _profile_id("sg.resume.student@college.edu")
    await _insert_resume(profile, ["React"])

    tpo_token = await _login(client, "sg.tpo@college.edu")
    data = await _get_skill_gaps(client, tpo_token)

    react = _skill(data, "React")
    assert react["students_reported"] == 2  # grace ("ReactJS" alias) + resume student
    assert react["students_reported_only"] == 2
    assert react["students_demonstrated"] == 0
    assert react["students_both"] == 0

    python = _skill(data, "Python")
    # "py" alias normalized to Python for grace.
    assert python["students_reported"] == 2

    url = f"{SKILL_GAPS_URL}/react/students"
    response = await client.get(url, headers=_auth(tpo_token), params={"limit": 100})
    by_name = {e["student_name"]: e for e in response.json()["entries"]}
    assert by_name["Resume Student"]["self_reported_via"] == ["resume"]
    assert by_name["Grace"]["self_reported_via"] == ["profile"]


@pytest.mark.asyncio
async def test_self_reported_never_counts_as_demonstrated(client, mock_mongo):
    await _build_world(client, mock_mongo)
    tpo_token = await _login(client, "sg.tpo@college.edu")
    data = await _get_skill_gaps(client, tpo_token)

    react = _skill(data, "React")
    # Grace reports React; nobody has ever demonstrated it on a drive
    # assessment — the reported skill must NOT become demonstrated.
    assert react["students_reported"] == 1
    assert react["students_demonstrated"] == 0
    assert react["students_both"] == 0
    assert react["students_reported_only"] == 1
    assert react["demonstrated_pct"] == 0.0
    # Her demonstrated gap remains 100% despite the report.
    assert react["gap_pct"] == 100.0
    assert react["students_lacking_demonstrated"] == 10


# ---------------------------------------------------------------------------
# Gap and priority calculations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_priority_math_matches_documented_formula(client, mock_mongo):
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    python = _skill(data, "Python")

    # demand 60%, gap 80%, comparable growth Jan-Oct 2026 (2) vs Jan-Oct 2025 (1) = +100%
    assert python["demand_pct"] == 60.0
    assert python["gap_pct"] == 80.0
    assert python["growth_comparable"] is True
    assert python["latest_growth_pct"] == 100.0
    # 0.5*60 + 0.4*80 + 0.1*((100+100)/2) = 30 + 32 + 10 = 72 -> high
    assert python["priority_score"] == 72.0
    assert python["priority_class"] == "high"

    # Documented weights are exposed for the UI tooltip.
    weights = data["meta"]["thresholds"]["priority_weights"]
    assert weights == {"demand": 0.5, "gap": 0.4, "growth": 0.1}


@pytest.mark.asyncio
async def test_missing_growth_data_reweights_instead_of_zeroing(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.growth.tpo@college.edu", "Growth TPO", "tpo")
    # One student with no evidence at all -> every gap is 100%.
    await _register_direct("sg.growth.student@college.edu", "Growth Student")
    token = await _login(client, "sg.growth.tpo@college.edu")
    data = await _get_skill_gaps(client, token, year_to=2025)

    python = _skill(data, "Python")
    assert python["growth_comparable"] is False
    assert python["latest_growth_pct"] is None
    assert python["demand_pct"] == 50.0  # 1 of 2 (2025) postings
    assert python["gap_pct"] == 100.0  # no students exist
    # (0.5*50 + 0.4*100) / 0.9 = 72.2
    assert python["priority_score"] == 72.2
    assert python["priority_class"] == "high"

    # The year series for the filtered dataset is present, growth None.
    years = {y["year"]: y for y in python["years"]}
    assert years[2025]["posting_count"] == 1
    assert years[2025]["yoy_growth_pct"] is None


@pytest.mark.asyncio
async def test_summary_counts_and_cards(client, mock_mongo):
    world = await _build_world(client, mock_mongo)
    data = await _get_skill_gaps(client, world["tpo_token"])
    summary = data["summary"]

    assert summary["total_skills_analyzed"] == 3
    assert summary["high_priority_gaps"] == 3
    assert summary["student_population"] == 10
    # Only alice + henry demonstrated ANY analyzed skill.
    assert summary["students_lacking_demonstrated_skills"] == 8
    assert summary["students_with_reported_skills"] == 2  # grace, henry
    assert summary["students_with_assessment_evidence"] == 5  # alice, bob, carol, dave, henry

    # Most demanded skill with ZERO demonstrated students: Communication (100%).
    missing = summary["most_demanded_missing_skill"]
    assert missing["name"] == "Communication"
    assert missing["demand_pct"] == 100.0

    # Rising demand: Python +100, React +100, Communication +50 (all comparable).
    rising = [(r["name"], r["latest_growth_pct"]) for r in summary["rising_demand_skills"]]
    assert rising == [("Python", 100.0), ("React", 100.0), ("Communication", 50.0)]


@pytest.mark.asyncio
async def test_students_endpoint_search_pagination_and_filter(client, mock_mongo):
    world = await _build_world(client, mock_mongo)
    tpo_token = world["tpo_token"]
    url = f"{SKILL_GAPS_URL}/python/students"

    # Search by name (case-insensitive substring, like the drive endpoints).
    search = await client.get(
        url, headers=_auth(tpo_token), params={"search": "ali", "limit": 10}
    )
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["entries"][0]["student_name"] == "Alice"

    # Classification filter: only henry is "both".
    both = await client.get(
        url, headers=_auth(tpo_token), params={"classification": "both", "limit": 10}
    )
    assert both.status_code == 200
    assert both.json()["total"] == 1
    assert both.json()["entries"][0]["student_name"] == "Henry"

    # Pagination over the full 10-student population, deterministic order.
    page1 = await client.get(url, headers=_auth(tpo_token), params={"page": 1, "limit": 2})
    page2 = await client.get(url, headers=_auth(tpo_token), params={"page": 2, "limit": 2})
    assert page1.json()["total"] == 10
    assert len(page1.json()["entries"]) == 2
    assert len(page2.json()["entries"]) == 2
    names_p1 = [e["student_name"] for e in page1.json()["entries"]]
    names_p2 = [e["student_name"] for e in page2.json()["entries"]]
    assert names_p1 and names_p2 and set(names_p1).isdisjoint(names_p2)


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_endpoints_never_mutate_operational_data(client, mock_mongo):
    world = await _build_world(client, mock_mongo)
    db = db_module.mongodb.db
    collections = [
        "placement_drives", "applications", "assessment_attempts", "students",
        "questions", "assessments", "resumes", "job_market_postings",
        "market_skill_catalog",
    ]
    before = {name: await db[name].count_documents({}) for name in collections}
    attempt_statuses_before = sorted(
        doc["status"] for doc in await db["assessment_attempts"].find({}).to_list(None)
    )

    await _get_skill_gaps(client, world["tpo_token"])
    await client.get(f"{SKILL_GAPS_URL}/python/students", headers=_auth(world["tpo_token"]))
    await client.get(SKILL_GAPS_FILTERS_URL, headers=_auth(world["tpo_token"]))

    after = {name: await db[name].count_documents({}) for name in collections}
    attempt_statuses_after = sorted(
        doc["status"] for doc in await db["assessment_attempts"].find({}).to_list(None)
    )
    assert before == after
    assert attempt_statuses_before == attempt_statuses_after


@pytest.mark.asyncio
async def test_existing_market_endpoints_still_work_alongside(client, mock_mongo):
    await _seed_market(mock_mongo)
    await _register_direct("sg.alongside.tpo@college.edu", "Alongside TPO", "tpo")
    token = await _login(client, "sg.alongside.tpo@college.edu")

    market = await client.get("/api/v1/analytics/tpo/market", headers=_auth(token))
    assert market.status_code == 200
    assert market.json()["summary"]["total_postings"] == 5

    gaps = await _get_skill_gaps(client, token)
    assert gaps["meta"]["market"]["dataset_version"] == market.json()["meta"]["dataset_version"]

