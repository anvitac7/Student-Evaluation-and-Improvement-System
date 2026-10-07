import pytest

MINIMAL_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(autouse=True)
def isolate_local_storage(tmp_path, monkeypatch):
    """Redirect local file storage to a pytest tmp_path so tests never
    write into the real project's ./storage directory."""
    from app.services import storage_service

    monkeypatch.setattr(storage_service.settings, "LOCAL_STORAGE_PATH", str(tmp_path))
    yield tmp_path


async def _register_login_student(client, email="resume.student@college.edu"):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": "Resume Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_tpo(client, email="resume.tpo@college.edu"):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": "StrongPass123", "name": "TPO User", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_upload_resume_success(client):
    token = await _register_login_student(client)
    response = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["is_active"] is True
    assert body["file_size_bytes"] == len(MINIMAL_PDF_BYTES)


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf_extension(client):
    token = await _register_login_student(client, email="nonpdf@college.edu")
    response = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.docx", b"not a pdf", "application/octet-stream")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_fake_pdf_content(client):
    token = await _register_login_student(client, email="fakepdf@college.edu")
    response = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", b"this is not really a pdf", "application/pdf")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client, monkeypatch):
    from app.services import resume_service

    monkeypatch.setattr(resume_service, "MAX_RESUME_SIZE_BYTES", 10)  # 10 bytes, easy to exceed
    token = await _register_login_student(client, email="oversize@college.edu")
    response = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_duplicate_upload_rejected(client):
    token = await _register_login_student(client, email="dup.resume@college.edu")
    first = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    second = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_new_version_deactivates_old_one(client):
    token = await _register_login_student(client, email="versions@college.edu")
    await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("v1.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    second = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("v2.pdf", MINIMAL_PDF_BYTES + b"extra", "application/pdf")},
    )
    assert second.status_code == 201
    assert second.json()["version"] == 2

    history = await client.get("/api/v1/resumes/history", headers=_auth_headers(token))
    versions = {item["version"]: item["is_active"] for item in history.json()}
    assert versions[1] is False
    assert versions[2] is True


@pytest.mark.asyncio
async def test_upload_requires_student_role(client):
    token = await _register_login_tpo(client)
    response = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tpo_can_view_but_not_upload_student_resume(client):
    student_token = await _register_login_student(client, email="viewed@college.edu")
    upload = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    resume_id = upload.json()["id"]

    tpo_token = await _register_login_tpo(client, email="viewer.tpo@college.edu")

    # A TPO may only open a resume that is attached to an application in one
    # of THIS TPO's own drives — not any resume in the system. This test used
    # to assert a blanket 200 with no such relationship, and started failing
    # when the access rule was tightened. The endpoint was correct; the test
    # was stale.
    drive = await client.post(
        "/api/v1/drives",
        headers=_auth_headers(tpo_token),
        json={
            "company_name": "ResumeViewer Corp",
            "job_title": "Engineer",
            "description": "Build things",
            "jd_text": "We need an engineer skilled in Python.",
            "required_skills": ["Python"],
            "package": "10 LPA",
            "location": "Remote",
            "eligibility": {},
            "deadline": "2099-01-01T00:00:00Z",
        },
    )
    assert drive.status_code == 201, drive.text
    applied = await client.post(
        f"/api/v1/drives/{drive.json()['id']}/apply", headers=_auth_headers(student_token)
    )
    assert applied.status_code == 201, applied.text

    response = await client.get(f"/api/v1/resumes/{resume_id}", headers=_auth_headers(tpo_token))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_tpo_cannot_view_unrelated_student_resume(client):
    """Companion to the test above: a TPO with no drive/application from this
    student must be refused. Without this, the ownership check could be
    deleted entirely and the suite would still be green."""
    student_token = await _register_login_student(client, email="unrelated@college.edu")
    upload = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    resume_id = upload.json()["id"]

    other_tpo_token = await _register_login_tpo(client, email="stranger.tpo@college.edu")
    response = await client.get(f"/api/v1/resumes/{resume_id}", headers=_auth_headers(other_tpo_token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_student_cannot_view_another_students_resume(client):
    token_a = await _register_login_student(client, email="student.a@college.edu")
    upload = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token_a),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    resume_id = upload.json()["id"]

    token_b = await _register_login_student(client, email="student.b@college.edu")
    response = await client.get(f"/api/v1/resumes/{resume_id}", headers=_auth_headers(token_b))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_download_streams_local_pdf(client):
    token = await _register_login_student(client, email="download@college.edu")
    upload = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    resume_id = upload.json()["id"]

    response = await client.get(f"/api/v1/resumes/{resume_id}/download", headers=_auth_headers(token))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == MINIMAL_PDF_BYTES
