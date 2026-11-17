"""Per-drive analytics detail endpoints (rankings, applicants, participants).

The standalone rankings list was relocated from the TPO analytics response
into per-drive endpoints. These tests pin:

- TPO-only access with drive ownership (other TPOs' drives are invisible).
- Applicants come from the drive's applications (all statuses, real names).
- Test participants come from actual assessment attempts on the drive's
  required assessment — applications and assignments are never treated as
  proof of participation.
- Ranking reuses the existing best-submitted-attempt scoring logic.
- One row per student everywhere; retakes never inflate unique counts.
- Attempts belonging to other drives/assessments never leak in.
"""
from datetime import datetime, timedelta

import pytest
from bson import ObjectId

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
    await service.register_admin(AdminRegisterRequest(email=email, password="StrongPass123", name="Detail Admin"))
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_tpo(client, email):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": "StrongPass123", "name": "Detail TPO", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_student(client, email, name="Detail Student"):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": name,
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
        "company_name": "Detail Corp",
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


async def _build_assessment(client, admin_token, name, pool_size=1):
    category = await client.post("/api/v1/questions/categories", headers=_auth(admin_token), json={"name": name})
    category_id = category.json()["id"]
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
            "type": "drive",
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


async def _start_attempt(client, student_token, assessment_id, application_id):
    start = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json={"fingerprint_hash": None, "application_id": application_id},
    )
    assert start.status_code == 201, start.text
    return start.json()


async def _submit_attempt(client, student_token, assessment_id, application_id, correct=True):
    """Start then answer the single pool question (auto-finalizes)."""
    body = await _start_attempt(client, student_token, assessment_id, application_id)
    response_text = "A" if correct else "B"
    answer = await client.post(
        f"/api/v1/assessments/attempts/{body['attempt_id']}/answer",
        headers=_auth(student_token),
        json={
            "session_token": body["session_token"],
            "question_id": body["next_question"]["id"],
            "response": response_text,
            "time_taken_sec": 12.0,
        },
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["attempt_status"] == "submitted"
    return body["attempt_id"]


# ---------------------------------------------------------------------------
# RBAC and ownership
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_per_drive_endpoints_require_tpo_role(client):
    admin_token = await _register_login_admin(client, "detail.rbacadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.rbactpo@college.edu")
    student_token = await _register_login_student(client, "detail.rbacstudent@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "RBAC Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]
    application_id = await _apply(client, student_token, drive_id)
    await _submit_attempt(client, student_token, assessment_id, application_id)

    paths = [
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking",
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants",
        f"/api/v1/analytics/tpo/drives/{drive_id}/participants",
    ]
    for path in paths:
        assert (await client.get(path)).status_code == 401, path
        assert (await client.get(path, headers=_auth(student_token))).status_code == 403, path
        assert (await client.get(path, headers=_auth(admin_token))).status_code == 403, path
        assert (await client.get(path, headers=_auth(tpo_token))).status_code == 200, path


@pytest.mark.asyncio
async def test_other_tpo_cannot_view_drive_detail(client):
    owner_token = await _register_login_tpo(client, "detail.ownertpo@college.edu")
    other_token = await _register_login_tpo(client, "detail.othertpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth(owner_token), json=_drive_payload())
    drive_id = drive.json()["id"]

    for path in (
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking",
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants",
        f"/api/v1/analytics/tpo/drives/{drive_id}/participants",
    ):
        response = await client.get(path, headers=_auth(other_token))
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_unknown_drive_returns_404(client):
    tpo_token = await _register_login_tpo(client, "detail.unknowntpo@college.edu")
    fake_id = str(ObjectId())
    for path in (
        f"/api/v1/analytics/tpo/drives/{fake_id}/ranking",
        f"/api/v1/analytics/tpo/drives/{fake_id}/applicants",
        f"/api/v1/analytics/tpo/drives/{fake_id}/participants",
    ):
        assert (await client.get(path, headers=_auth(tpo_token))).status_code == 404


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_applicants_include_all_statuses_with_metadata(client):
    tpo_token = await _register_login_tpo(client, "detail.apptpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]

    s1 = await _register_login_student(client, "detail.applied@college.edu", name="Alice Applied")
    s2 = await _register_login_student(client, "detail.shortlisted@college.edu", name="Bob Shortlisted")
    s3 = await _register_login_student(client, "detail.rejected@college.edu", name="Carol Rejected")
    await _apply(client, s1, drive_id)
    app2 = await _apply(client, s2, drive_id)
    app3 = await _apply(client, s3, drive_id)

    shortlisted = await client.patch(
        f"/api/v1/drives/{drive_id}/applications/{app2}",
        headers=_auth(tpo_token),
        json={"status": "shortlisted"},
    )
    assert shortlisted.status_code == 200, shortlisted.text
    rejected = await client.patch(
        f"/api/v1/drives/{drive_id}/applications/{app3}",
        headers=_auth(tpo_token),
        json={"status": "rejected"},
    )
    assert rejected.status_code == 200, rejected.text

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert {e["status"] for e in data["entries"]} == {"applied", "shortlisted", "rejected"}
    assert {e["student_name"] for e in data["entries"]} == {
        "Alice Applied", "Bob Shortlisted", "Carol Rejected",
    }
    assert all(e["department"] == "CS" and e["batch_year"] == 2026 for e in data["entries"])
    assert all(e["applied_at"] for e in data["entries"])


@pytest.mark.asyncio
async def test_applicants_pagination_and_empty_state(client):
    tpo_token = await _register_login_tpo(client, "detail.pagetpo@college.edu")
    empty_drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{empty_drive.json()['id']}/applicants", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["entries"] == []

    drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]
    for i in range(3):
        token = await _register_login_student(client, f"detail.page{i}@college.edu")
        await _apply(client, token, drive_id)

    page1 = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants",
        headers=_auth(tpo_token), params={"page": 1, "limit": 2},
    )
    assert page1.status_code == 200
    assert page1.json()["total"] == 3
    assert len(page1.json()["entries"]) == 2
    page2 = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants",
        headers=_auth(tpo_token), params={"page": 2, "limit": 2},
    )
    assert page2.status_code == 200
    assert len(page2.json()["entries"]) == 1
    # No student appears on both pages.
    ids1 = {e["student_id"] for e in page1.json()["entries"]}
    ids2 = {e["student_id"] for e in page2.json()["entries"]}
    assert ids1 & ids2 == set()


@pytest.mark.asyncio
async def test_applicants_search_by_name(client):
    tpo_token = await _register_login_tpo(client, "detail.searchtpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]
    await _register_login_student(client, "detail.zoe@college.edu", name="Zoe Searchable")
    await _register_login_student(client, "detail.yan@college.edu", name="Yan Other")
    await _apply(client, await _login(client, "detail.zoe@college.edu"), drive_id)
    await _apply(client, await _login(client, "detail.yan@college.edu"), drive_id)

    found = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants",
        headers=_auth(tpo_token), params={"search": "zoe"},
    )
    assert found.status_code == 200
    assert found.json()["total"] == 1
    assert found.json()["entries"][0]["student_name"] == "Zoe Searchable"


async def _login(client, email):
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_applicants_never_include_other_drive_students(client):
    tpo_token = await _register_login_tpo(client, "detail.isolationtpo@college.edu")
    drive_a = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload(job_title="Drive A"))
    drive_b = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload(job_title="Drive B"))
    drive_a_id, drive_b_id = drive_a.json()["id"], drive_b.json()["id"]

    token_a = await _register_login_student(client, "detail.onlya@college.edu", name="Only A")
    token_b = await _register_login_student(client, "detail.onlyb@college.edu", name="Only B")
    await _apply(client, token_a, drive_a_id)
    await _apply(client, token_b, drive_b_id)

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_a_id}/applicants", headers=_auth(tpo_token)
    )
    names = {e["student_name"] for e in response.json()["entries"]}
    assert names == {"Only A"}


@pytest.mark.asyncio
async def test_applicants_with_deleted_student_profile_do_not_crash(client):
    from app.core import database as db_module

    tpo_token = await _register_login_tpo(client, "detail.deletedtpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]
    token = await _register_login_student(client, "detail.vanish@college.edu", name="Vanishing Student")
    await _apply(client, token, drive_id)

    before = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants", headers=_auth(tpo_token)
    )
    student_id = before.json()["entries"][0]["student_id"]
    await db_module.mongodb.db.students.delete_one({"_id": ObjectId(student_id)})

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/applicants", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    assert response.json()["entries"][0]["student_name"] == "Unknown student"


# ---------------------------------------------------------------------------
# Test participants
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_participants_require_real_attempts(client):
    admin_token = await _register_login_admin(client, "detail.partadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.parttpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Participation Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]

    # Applied but never started: must NOT appear as a participant.
    no_attempt = await _register_login_student(client, "detail.noattempt@college.edu", name="No Attempt")
    await _apply(client, no_attempt, drive_id)

    # Started but not submitted: a real attempt, shown as in_progress, no score.
    in_progress = await _register_login_student(client, "detail.inprogress@college.edu", name="In Progress")
    app_ip = await _apply(client, in_progress, drive_id)
    await _start_attempt(client, in_progress, assessment_id, app_ip)

    # Actually submitted: shown with a score.
    submitted = await _register_login_student(client, "detail.submitted@college.edu", name="Submitted One")
    app_sub = await _apply(client, submitted, drive_id)
    await _submit_attempt(client, submitted, assessment_id, app_sub, correct=True)

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/participants", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # the applied-but-never-started student is absent
    assert data["assessment_id"] == assessment_id
    by_status = {e["student_name"]: e for e in data["entries"]}
    assert "No Attempt" not in by_status
    assert by_status["In Progress"]["attempt_status"] == "in_progress"
    assert by_status["In Progress"]["score_pct"] is None
    assert by_status["In Progress"]["submitted_at"] is None
    assert by_status["Submitted One"]["attempt_status"] == "submitted"
    assert by_status["Submitted One"]["score_pct"] == 100.0
    assert by_status["Submitted One"]["submitted_at"] is not None

    # The ranking only contains the submitted student.
    ranking = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking", headers=_auth(tpo_token)
    )
    assert ranking.status_code == 200
    entries = ranking.json()["entries"]
    assert [e["student_name"] for e in entries] == ["Submitted One"]
    assert entries[0]["rank"] == 1 and entries[0]["score_pct"] == 100.0

    # Main analytics overview counts unique participants.
    overview = await client.get("/api/v1/analytics/tpo", headers=_auth(tpo_token))
    assert overview.status_code == 200
    funnel = next(d for d in overview.json()["drives"] if d["drive_id"] == drive_id)
    assert funnel["participant_count"] == 2
    assert funnel["submitted_participant_count"] == 1
    assert funnel["assessment_title"] == "Participation Assessment"


@pytest.mark.asyncio
async def test_participants_one_row_per_student_despite_retries(client):
    admin_token = await _register_login_admin(client, "detail.retryadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.retrytpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Retry Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]
    student = await _register_login_student(client, "detail.retrying@college.edu", name="Retrying Student")
    application_id = await _apply(client, student, drive_id)

    # First attempt: submitted.
    await _submit_attempt(client, student, assessment_id, application_id, correct=False)
    # Second attempt: started (in progress) after the submission — the
    # application's attempt link now points at the new attempt, but the
    # student must still be ONE participant represented by their best
    # (submitted) attempt.
    await _start_attempt(client, student, assessment_id, application_id)

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/participants", headers=_auth(tpo_token)
    )
    data = response.json()
    assert data["total"] == 1
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["attempt_status"] == "submitted"  # best attempt wins the row
    assert entry["score_pct"] == 0.0

    overview = await client.get("/api/v1/analytics/tpo", headers=_auth(tpo_token))
    funnel = next(d for d in overview.json()["drives"] if d["drive_id"] == drive_id)
    assert funnel["participant_count"] == 1


@pytest.mark.asyncio
async def test_participants_and_ranking_exclude_other_assessments_and_drives(client):
    admin_token = await _register_login_admin(client, "detail.leakadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.leaktpo@college.edu")
    drive_assessment = await _build_assessment(client, admin_token, "Drive Linked Assessment")
    practice_assessment = await _build_assessment(client, admin_token, "Practice Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=drive_assessment),
    )
    drive_id = drive.json()["id"]

    # Practice attempts never count toward the drive.
    practice_student = await _register_login_student(client, "detail.practice@college.edu", name="Practice Taker")
    start = await client.post(
        f"/api/v1/assessments/{practice_assessment}/start",
        headers=_auth(practice_student),
        json={"fingerprint_hash": None},
    )
    assert start.status_code == 201
    await client.post(
        f"/api/v1/assessments/attempts/{start.json()['attempt_id']}/answer",
        headers=_auth(practice_student),
        json={
            "session_token": start.json()["session_token"],
            "question_id": start.json()["next_question"]["id"],
            "response": "A",
            "time_taken_sec": 5.0,
        },
    )

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/participants", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0  # practice attempt must not leak in

    # A student who applied to a different drive and attempted the SAME
    # assessment (shared across drives) must not appear under this drive.
    other_drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(job_title="Shared Assessment Drive", required_assessment_id=drive_assessment),
    )
    other_drive_id = other_drive.json()["id"]
    cross_student = await _register_login_student(client, "detail.cross@college.edu", name="Cross Drive Student")
    cross_app = await _apply(client, cross_student, other_drive_id)
    await _submit_attempt(client, cross_student, drive_assessment, cross_app, correct=True)

    for path in (f"/api/v1/analytics/tpo/drives/{drive_id}/participants",):
        data = (await client.get(path, headers=_auth(tpo_token))).json()
        assert data["total"] == 0, data
    ranking = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking", headers=_auth(tpo_token)
    )
    assert ranking.json()["entries"] == []
    # The other drive sees its own applicant/participant.
    other = await client.get(
        f"/api/v1/analytics/tpo/drives/{other_drive_id}/participants", headers=_auth(tpo_token)
    )
    assert other.json()["total"] == 1
    assert other.json()["entries"][0]["student_name"] == "Cross Drive Student"


# ---------------------------------------------------------------------------
# Ranking rules
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ranking_orders_by_score_and_excludes_in_progress(client):
    admin_token = await _register_login_admin(client, "detail.rankadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.ranktpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Ranking Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]

    low = await _register_login_student(client, "detail.low@college.edu", name="Low Score")
    high = await _register_login_student(client, "detail.high@college.edu", name="High Score")
    started_only = await _register_login_student(client, "detail.started@college.edu", name="Started Only")

    app_low = await _apply(client, low, drive_id)
    app_high = await _apply(client, high, drive_id)
    app_started = await _apply(client, started_only, drive_id)

    await _submit_attempt(client, low, assessment_id, app_low, correct=False)  # 0%
    await _submit_attempt(client, high, assessment_id, app_high, correct=True)  # 100%
    await _start_attempt(client, started_only, assessment_id, app_started)  # in progress

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking", headers=_auth(tpo_token)
    )
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [e["student_name"] for e in entries] == ["High Score", "Low Score"]
    assert [e["score_pct"] for e in entries] == [100.0, 0.0]
    assert [e["rank"] for e in entries] == [1, 2]
    assert "Started Only" not in {e["student_name"] for e in entries}


@pytest.mark.asyncio
async def test_ranking_ties_are_deterministic(client):
    admin_token = await _register_login_admin(client, "detail.tieadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.tietpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Tie Assessment")

    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]

    apps = []
    for i in range(2):
        token = await _register_login_student(client, f"detail.tie{i}@college.edu", name=f"Tie Student {i}")
        apps.append((token, await _apply(client, token, drive_id)))
    for token, application_id in apps:
        await _submit_attempt(client, token, assessment_id, application_id, correct=True)

    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive_id}/ranking", headers=_auth(tpo_token)
    )
    entries = response.json()["entries"]
    assert [e["rank"] for e in entries] == [1, 2]
    assert all(e["score_pct"] == 100.0 for e in entries)
    # Ties break by earlier submission — first submitted ranks first.
    assert entries[0]["submitted_at"] <= entries[1]["submitted_at"]
    assert entries[0]["student_name"] == "Tie Student 0"


@pytest.mark.asyncio
async def test_ranking_without_assessment_returns_404(client):
    tpo_token = await _register_login_tpo(client, "detail.noasstpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())
    response = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive.json()['id']}/ranking", headers=_auth(tpo_token)
    )
    assert response.status_code == 404
    assert "assessment" in response.json()["detail"].lower()

    # Participants for an assessment-less drive are simply empty, not an error.
    participants = await client.get(
        f"/api/v1/analytics/tpo/drives/{drive.json()['id']}/participants", headers=_auth(tpo_token)
    )
    assert participants.status_code == 200
    assert participants.json()["total"] == 0
    assert participants.json()["assessment_id"] is None


@pytest.mark.asyncio
async def test_main_analytics_response_no_longer_has_standalone_rankings(client):
    admin_token = await _register_login_admin(client, "detail.mainadmin@college.edu")
    tpo_token = await _register_login_tpo(client, "detail.maintpo@college.edu")
    assessment_id = await _build_assessment(client, admin_token, "Main Analytics Assessment")
    drive = await client.post(
        "/api/v1/drives",
        headers=_auth(tpo_token),
        json=_drive_payload(required_assessment_id=assessment_id),
    )
    drive_id = drive.json()["id"]

    # A drive without an assessment is also created up front — the overview
    # is a snapshot, so both drives must exist before it is fetched.
    plain = await client.post("/api/v1/drives", headers=_auth(tpo_token), json=_drive_payload())

    overview = await client.get("/api/v1/analytics/tpo", headers=_auth(tpo_token))
    assert overview.status_code == 200
    data = overview.json()
    assert "drive_assessment_rankings" not in data  # relocated to the per-drive endpoint
    funnel = next(d for d in data["drives"] if d["drive_id"] == drive_id)
    assert funnel["required_assessment_id"] == assessment_id
    assert funnel["participant_count"] == 0
    assert funnel["submitted_participant_count"] == 0

    plain_funnel = next(d for d in data["drives"] if d["drive_id"] == plain.json()["id"])
    assert plain_funnel["required_assessment_id"] is None
    assert plain_funnel["assessment_title"] is None
    assert plain_funnel["participant_count"] == 0
