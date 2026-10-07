from datetime import datetime, timedelta

import pytest

from app.models.drive import VALID_STATUS_TRANSITIONS, ApplicationStatus
from app.models.user import AdminRegisterRequest
from app.services.auth_service import AuthService

FUTURE_DEADLINE = (datetime.utcnow() + timedelta(days=30)).isoformat()
MINIMAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.mark.asyncio
async def test_status_transitions_reject_skipping_shortlisting(client):
    """Pins the status state machine itself.

    An application cannot jump applied -> selected; it must be shortlisted
    first. A test elsewhere once assumed otherwise and failed with a
    misleading assertion rather than the real cause, so the rule is
    asserted directly here.
    """
    tpo_token = await _register_login_tpo(client, "transitions.tpo@college.edu")
    drive = await client.post("/api/v1/drives", headers=_auth_headers(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]

    application_id = await _apply_with_new_student(client, drive_id, "transitions.applicant@college.edu")

    skipped = await client.patch(
        f"/api/v1/drives/{drive_id}/applications/{application_id}",
        headers=_auth_headers(tpo_token),
        json={"status": "selected"},
    )
    assert skipped.status_code == 400
    assert "shortlisted" in skipped.json()["detail"].lower()

    # The declared table must agree with the enforced behaviour.
    assert ApplicationStatus.SELECTED not in VALID_STATUS_TRANSITIONS[ApplicationStatus.APPLIED]
    assert ApplicationStatus.SELECTED in VALID_STATUS_TRANSITIONS[ApplicationStatus.SHORTLISTED]
    # Terminal states have nowhere to go.
    assert VALID_STATUS_TRANSITIONS[ApplicationStatus.SELECTED] == set()
    assert VALID_STATUS_TRANSITIONS[ApplicationStatus.REJECTED] == set()


async def _register_login_student(client, email):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": "Analytics Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_tpo(client, email):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": "StrongPass123", "name": "Analytics TPO", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_admin(client, email):
    from app.core import database as db_module

    service = AuthService(db_module.mongodb.db)
    await service.register_admin(AdminRegisterRequest(email=email, password="StrongPass123", name="Analytics Admin"))
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _drive_payload(**overrides):
    payload = {
        "company_name": "Analytics Corp",
        "job_title": "Software Engineer",
        "description": "Build things",
        "jd_text": "We need a software engineer.",
        "required_skills": ["Python"],
        "eligibility": {},
        "deadline": FUTURE_DEADLINE,
        "selection_process": [],
    }
    payload.update(overrides)
    return payload


async def _apply_with_new_student(client, drive_id: str, email: str) -> str:
    student_token = await _register_login_student(client, email)
    await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    apply_response = await client.post(f"/api/v1/drives/{drive_id}/apply", headers=_auth_headers(student_token))
    return apply_response.json()["id"]


@pytest.mark.asyncio
async def test_tpo_analytics_reflects_own_drives_only(client):
    owner_token = await _register_login_tpo(client, "analytics.owner@college.edu")
    other_token = await _register_login_tpo(client, "analytics.other@college.edu")

    owned_drive = await client.post("/api/v1/drives", headers=_auth_headers(owner_token), json=_drive_payload())
    owned_drive_id = owned_drive.json()["id"]
    await client.post("/api/v1/drives", headers=_auth_headers(other_token), json=_drive_payload())

    application_id = await _apply_with_new_student(client, owned_drive_id, "analytics.applicant1@college.edu")
    await client.patch(
        f"/api/v1/drives/{owned_drive_id}/applications/{application_id}",
        headers=_auth_headers(owner_token),
        json={"status": "shortlisted"},
    )
    await _apply_with_new_student(client, owned_drive_id, "analytics.applicant2@college.edu")

    response = await client.get("/api/v1/analytics/tpo", headers=_auth_headers(owner_token))
    assert response.status_code == 200
    data = response.json()

    assert data["total_drives"] == 1  # only the owner's drive, not the other TPO's
    assert data["total_applications"] == 2
    assert data["breakdown"]["shortlisted"] == 1
    assert data["breakdown"]["applied"] == 1
    assert data["selection_rate_pct"] == 0.0  # none selected yet
    assert len(data["drives"]) == 1
    assert data["drives"][0]["total_applications"] == 2


@pytest.mark.asyncio
async def test_student_and_tpo_cannot_access_admin_analytics(client):
    student_token = await _register_login_student(client, "noanalytics.student@college.edu")
    tpo_token = await _register_login_tpo(client, "noanalytics.tpo@college.edu")

    student_response = await client.get("/api/v1/analytics/admin", headers=_auth_headers(student_token))
    tpo_response = await client.get("/api/v1/analytics/admin", headers=_auth_headers(tpo_token))
    assert student_response.status_code == 403
    assert tpo_response.status_code == 403


@pytest.mark.asyncio
async def test_student_cannot_access_tpo_analytics(client):
    student_token = await _register_login_student(client, "noanalytics2.student@college.edu")
    response = await client.get("/api/v1/analytics/tpo", headers=_auth_headers(student_token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_analytics_counts_placements_and_applications(client):
    admin_token = await _register_login_admin(client, "counts.admin@college.edu")
    tpo_token = await _register_login_tpo(client, "counts.tpo@college.edu")

    drive = await client.post("/api/v1/drives", headers=_auth_headers(tpo_token), json=_drive_payload())
    drive_id = drive.json()["id"]

    application_id = await _apply_with_new_student(client, drive_id, "counts.applicant@college.edu")

    # Walk the legal transition path. VALID_STATUS_TRANSITIONS permits
    # applied -> shortlisted -> selected but NOT applied -> selected, so the
    # original single PATCH was rejected with a 400 that this test never
    # checked — it went on to assert placed_students >= 1 and failed with a
    # misleading "0 >= 1" instead of the real cause. Each step's status is
    # now asserted so a rejected transition fails here, loudly.
    shortlisted = await client.patch(
        f"/api/v1/drives/{drive_id}/applications/{application_id}",
        headers=_auth_headers(tpo_token),
        json={"status": "shortlisted"},
    )
    assert shortlisted.status_code == 200, shortlisted.text

    selected = await client.patch(
        f"/api/v1/drives/{drive_id}/applications/{application_id}",
        headers=_auth_headers(tpo_token),
        json={"status": "selected"},
    )
    assert selected.status_code == 200, selected.text

    response = await client.get("/api/v1/analytics/admin", headers=_auth_headers(admin_token))
    assert response.status_code == 200
    data = response.json()

    assert data["total_drives"] >= 1
    assert data["total_applications"] >= 1
    assert data["placed_students"] >= 1
    assert data["application_breakdown"]["selected"] >= 1
