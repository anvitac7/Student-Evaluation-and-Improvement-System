"""Practice vs. drive assessments.

Pins the behaviour that makes the two assessment types distinct:

- A drive assessment (linked to a drive) requires an application and its
  submitted attempts feed the TPO's drive assessment rankings.
- A practice assessment is never linked to a drive, can be started without an
  application, and is deliberately excluded from drive rankings.
"""
from datetime import datetime, timedelta

import pytest

from app.models.user import AdminRegisterRequest
from app.services.auth_service import AuthService

FUTURE_DEADLINE = (datetime.utcnow() + timedelta(days=30)).isoformat()
MINIMAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# Helpers (mirrors the conventions used by test_analytics/test_assessments)
# ---------------------------------------------------------------------------
async def _register_login_admin(client, email):
    from app.core import database as db_module

    service = AuthService(db_module.mongodb.db)
    await service.register_admin(AdminRegisterRequest(email=email, password="StrongPass123", name="Ranking Admin"))
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_tpo(client, email):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": "StrongPass123", "name": "Ranking TPO", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_student(client, email):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": "Ranking Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _drive_payload(**overrides):
    payload = {
        "company_name": "Ranking Corp",
        "job_title": "Backend Engineer",
        "description": "Build backends",
        "jd_text": "We need a backend engineer.",
        "required_skills": ["Python"],
        "eligibility": {},
        "deadline": FUTURE_DEADLINE,
        "selection_process": [],
    }
    payload.update(overrides)
    return payload


async def _build_assessment(client, admin_token, name, assessment_type="practice", pool_size=1):
    category = await client.post("/api/v1/questions/categories", headers=_auth(admin_token), json={"name": name})
    category_id = category.json()["id"]
    # Start difficulty is always medium, so a single medium question is enough
    # for a one-answer attempt that immediately finalizes.
    await client.post(
        "/api/v1/questions",
        headers=_auth(admin_token),
        json={
            "category_id": category_id,
            "skill_tags": ["Python"],
            "difficulty": "medium",
            "type": "mcq",
            "text": f"{name} question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "A",
        },
    )
    assessment = await client.post(
        "/api/v1/assessments",
        headers=_auth(admin_token),
        json={
            "title": name,
            "category_ids": [category_id],
            "question_pool_size": pool_size,
            "time_limit_sec": 600,
            "max_violations": 3,
            "require_fullscreen": False,
            "type": assessment_type,
        },
    )
    assert assessment.status_code == 201, assessment.text
    return assessment.json()["id"]


async def _apply(client, student_token, drive_id):
    await client.post(
        "/api/v1/resumes",
        headers=_auth(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    response = await client.post(f"/api/v1/drives/{drive_id}/apply", headers=_auth(student_token))
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _complete_attempt(client, student_token, assessment_id, application_id=None):
    start_payload = {"fingerprint_hash": None}
    if application_id:
        start_payload["application_id"] = application_id
    start = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json=start_payload,
    )
    assert start.status_code == 201, start.text
    body = start.json()
    answer = await client.post(
        f"/api/v1/assessments/attempts/{body['attempt_id']}/answer",
        headers=_auth(student_token),
        json={
            "session_token": body["session_token"],
            "question_id": body["next_question"]["id"],
            "response": "A",
            "time_taken_sec": 12.0,
        },
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["attempt_status"] == "submitted"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drive_assessment_requires_an_application(client):
    admin_token = await _register_login_admin(client, "rank.reqadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "rank.reqtpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Drive No App", assessment_type="drive")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    assert drive.status_code == 201, drive.text

    student_token = await _register_login_student(client, "rank.reqstudent@college.edu")
    start = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json={"fingerprint_hash": None},
    )
    # A drive assessment is not takeable without the application that links it
    # to the drive — that linkage is what the attempt is ranked against.
    assert start.status_code == 400
    assert "application" in start.json()["detail"].lower()


@pytest.mark.asyncio
async def test_drive_start_resumes_an_in_progress_attempt(client):
    admin_token = await _register_login_admin(client, "rank.resumeadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "rank.resumetpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Drive Resume", assessment_type="drive")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    assert drive.status_code == 201, drive.text
    drive_id = drive.json()["id"]

    student_token = await _register_login_student(client, "rank.resumestudent@college.edu")
    application_id = await _apply(client, student_token, drive_id)
    payload = {"fingerprint_hash": None, "application_id": application_id}

    first = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json=payload,
    )
    assert first.status_code == 201, first.text

    resumed = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json=payload,
    )
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["attempt_id"] == first.json()["attempt_id"]
    assert resumed.json()["session_token"] == first.json()["session_token"]


@pytest.mark.asyncio
async def test_practice_assessment_starts_without_an_application(client):
    admin_token = await _register_login_admin(client, "rank.pracadmin@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Practice Only", assessment_type="practice")

    student_token = await _register_login_student(client, "rank.pracstudent@college.edu")
    start = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json={"fingerprint_hash": None},
    )
    assert start.status_code == 201, start.text


@pytest.mark.asyncio
async def test_drive_ranking_includes_drive_attempts_and_excludes_practice(client):
    admin_token = await _register_login_admin(client, "rank.admin@college.edu")
    tpo_token = await _register_login_tpo(client, "rank.tpo@college.edu")

    drive_assessment = await _build_assessment(client, admin_token, "Drive Assessment", assessment_type="drive")
    practice_assessment = await _build_assessment(client, admin_token, "Practice Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=drive_assessment, assessment_min_score_pct=70),
    )
    assert drive.status_code == 201, drive.text
    drive_id = drive.json()["id"]

    # Two students apply and complete the drive assessment.
    for email in ("rank.s1@college.edu", "rank.s2@college.edu"):
        student_token = await _register_login_student(client, email)
        application_id = await _apply(client, student_token, drive_id)
        await _complete_attempt(client, student_token, drive_assessment, application_id)

    # A third student takes only the practice assessment — this must never
    # show up in the drive leaderboard.
    practice_student = await _register_login_student(client, "rank.practice@college.edu")
    await _complete_attempt(client, practice_student, practice_assessment)

    analytics = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking", headers=_auth(tpo_token)
    )
    assert analytics.status_code == 200, analytics.text
    data = analytics.json()

    assert data["drive_id"] == drive_id
    assert data["assessment_id"] == drive_assessment
    assert len(data["entries"]) == 2
    assert [e["rank"] for e in data["entries"]] == [1, 2]
    assert all(e["score_pct"] == 100.0 for e in data["entries"])
    # The practice-only student must not be present.
    student_ids = {e["student_id"] for e in data["entries"]}
    assert len(student_ids) == 2
