import pytest

from tests.pdf_builder import build_test_pdf

# Minimal valid PDF, same approach test_drives.py uses — keeps these tests
# independent of the resume-parsing stack.
MINIMAL_PDF_BYTES = build_test_pdf(["Test Student", "test@college.edu", "Skills: Python"])


async def _register_login_admin(client, email="kts.admin@college.edu"):
    from app.core import database as db_module
    from app.core.security import hash_password

    await db_module.mongodb.db.users.insert_one(
        {
            "email": email,
            "password_hash": hash_password("StrongPass123"),
            "role": "admin",
            "auth_provider": "local",
            "is_active": True,
        }
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_student(client, email="kts.student@college.edu"):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": "KTS Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


async def _register_login_tpo(client, email="kts.tpo@college.edu"):
    await client.post(
        "/api/v1/auth/register/tpo",
        json={"email": email, "password": "StrongPass123", "name": "KTS TPO", "department_scope": []},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_category(client, admin_token, name="Programming"):
    response = await client.post(
        "/api/v1/questions/categories", headers=_auth_headers(admin_token), json={"name": name}
    )
    return response.json()["id"]


async def _create_question(client, admin_token, category_id, difficulty, correct="A", skill_tags=None):
    payload = {
        "category_id": category_id,
        "skill_tags": skill_tags or ["Python"],
        "difficulty": difficulty,
        "type": "mcq",
        "text": f"A {difficulty} question?",
        "options": ["A", "B", "C", "D"],
        "correct_answer": correct,
    }
    response = await client.post("/api/v1/questions", headers=_auth_headers(admin_token), json=payload)
    return response.json()


async def _start_attempt(client, student_token, assessment_id, fingerprint_hash=None):
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth_headers(student_token),
        json={"fingerprint_hash": fingerprint_hash},
    )
    return response


async def _answer(client, student_token, attempt_id, session_token, question_id, response_text, time_taken_sec=None):
    return await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/answer",
        headers=_auth_headers(student_token),
        json={
            "session_token": session_token,
            "question_id": question_id,
            "response": response_text,
            "time_taken_sec": time_taken_sec,
        },
    )


# ---------------------------------------------------------------------
# Question bank management
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_admin_can_create_category_and_question(client):
    admin_token = await _register_login_admin(client)
    category_id = await _create_category(client, admin_token)
    question = await _create_question(client, admin_token, category_id, "medium")
    assert question["marks"] == 3
    assert question["difficulty"] == "medium"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_question(client):
    student_token = await _register_login_student(client, "noadmin@college.edu")
    response = await client.post(
        "/api/v1/questions",
        headers=_auth_headers(student_token),
        json={
            "category_id": "000000000000000000000000",
            "difficulty": "easy",
            "type": "mcq",
            "text": "x?",
            "options": ["A", "B"],
            "correct_answer": "A",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mcq_without_correct_answer_in_options_rejected(client):
    admin_token = await _register_login_admin(client, "badmcq.admin@college.edu")
    category_id = await _create_category(client, admin_token, "BadMCQ")
    response = await client.post(
        "/api/v1/questions",
        headers=_auth_headers(admin_token),
        json={
            "category_id": category_id,
            "difficulty": "easy",
            "type": "mcq",
            "text": "x?",
            "options": ["A", "B"],
            "correct_answer": "Z",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_coding_question_requires_correct_answer(client):
    admin_token = await _register_login_admin(client, "coding.admin@college.edu")
    category_id = await _create_category(client, admin_token, "Coding")
    response = await client.post(
        "/api/v1/questions",
        headers=_auth_headers(admin_token),
        json={"category_id": category_id, "difficulty": "easy", "type": "coding", "text": "print hello", "options": []},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bulk_import_and_export(client):
    admin_token = await _register_login_admin(client, "import.admin@college.edu")
    category_id = await _create_category(client, admin_token, "ImportCat")

    payload = [
        {
            "category_id": category_id,
            "difficulty": "easy",
            "type": "mcq",
            "text": f"Q{i}?",
            "options": ["A", "B"],
            "correct_answer": "A",
        }
        for i in range(3)
    ]
    imported = await client.post("/api/v1/questions/import", headers=_auth_headers(admin_token), json=payload)
    assert imported.status_code == 201
    assert len(imported.json()) == 3

    exported = await client.get(
        f"/api/v1/questions/export?category_id={category_id}", headers=_auth_headers(admin_token)
    )
    assert exported.status_code == 200
    assert len(exported.json()) == 3


@pytest.mark.asyncio
async def test_update_and_delete_question(client):
    admin_token = await _register_login_admin(client, "update.admin@college.edu")
    category_id = await _create_category(client, admin_token, "UpdateCat")
    question = await _create_question(client, admin_token, category_id, "easy")

    updated = await client.put(
        f"/api/v1/questions/{question['id']}", headers=_auth_headers(admin_token), json={"difficulty": "hard"}
    )
    assert updated.status_code == 200
    assert updated.json()["marks"] == 5

    deleted = await client.delete(f"/api/v1/questions/{question['id']}", headers=_auth_headers(admin_token))
    assert deleted.status_code == 204


# ---------------------------------------------------------------------
# Adaptive assessment engine
# ---------------------------------------------------------------------
async def _setup_assessment_with_one_question_per_difficulty(
    client, admin_token, category_name="Adaptive", max_violations=3
):
    category_id = await _create_category(client, admin_token, category_name)
    for diff in ("easy", "medium", "hard"):
        await _create_question(client, admin_token, category_id, diff, correct="A", skill_tags=["Python"])

    response = await client.post(
        "/api/v1/assessments",
        headers=_auth_headers(admin_token),
        json={
            "title": "Adaptive Test",
            "category_ids": [category_id],
            "question_pool_size": 3,
            "time_limit_sec": 1800,
            "max_violations": max_violations,
        },
    )
    return response.json()["id"]


@pytest.mark.asyncio
async def test_start_assessment_gives_medium_first(client):
    admin_token = await _register_login_admin(client, "start.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "StartCat")

    student_token = await _register_login_student(client, "starter@college.edu")
    response = await _start_attempt(client, student_token, assessment_id)
    assert response.status_code == 201
    body = response.json()
    assert body["next_question"]["difficulty"] == "medium"
    assert body["anti_cheat_config"]["max_violations"] == 3
    assert "session_token" in body


@pytest.mark.asyncio
async def test_correct_answer_increases_difficulty(client):
    admin_token = await _register_login_admin(client, "correct.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "CorrectCat")

    student_token = await _register_login_student(client, "correctstudent@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    first_question_id = start.json()["next_question"]["id"]

    answer = await _answer(client, student_token, attempt_id, session_token, first_question_id, "A")
    assert answer.status_code == 200
    body = answer.json()
    assert body["is_correct"] is True
    assert body["next_question"]["difficulty"] == "hard"


@pytest.mark.asyncio
async def test_wrong_answer_decreases_difficulty(client):
    admin_token = await _register_login_admin(client, "wrong.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "WrongCat")

    student_token = await _register_login_student(client, "wrongstudent@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    first_question_id = start.json()["next_question"]["id"]

    answer = await _answer(client, student_token, attempt_id, session_token, first_question_id, "B")
    assert answer.status_code == 200
    body = answer.json()
    assert body["is_correct"] is False
    assert body["next_question"]["difficulty"] == "easy"


@pytest.mark.asyncio
async def test_pool_exhaustion_auto_submits(client):
    admin_token = await _register_login_admin(client, "pool.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "PoolCat")

    student_token = await _register_login_student(client, "poolstudent@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    question_id = start.json()["next_question"]["id"]

    answer = None
    for _ in range(3):
        answer = await _answer(client, student_token, attempt_id, session_token, question_id, "A")
        if answer.json()["next_question"] is None:
            break
        question_id = answer.json()["next_question"]["id"]

    assert answer.json()["attempt_status"] == "submitted"

    results = await client.get(
        f"/api/v1/assessments/attempts/{attempt_id}/results", headers=_auth_headers(student_token)
    )
    assert results.status_code == 200
    assert results.json()["status"] == "submitted"
    assert results.json()["questions_answered"] >= 1


@pytest.mark.asyncio
async def test_answering_wrong_question_id_rejected(client):
    admin_token = await _register_login_admin(client, "wrongid.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "WrongIdCat")

    student_token = await _register_login_student(client, "wrongidstudent@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]

    response = await _answer(
        client, student_token, attempt_id, session_token, "000000000000000000000000", "A"
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_student_cannot_access_another_students_attempt(client):
    admin_token = await _register_login_admin(client, "isolation.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "IsolationCat")

    student_a_token = await _register_login_student(client, "isolation.a@college.edu")
    start = await _start_attempt(client, student_a_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    question_id = start.json()["next_question"]["id"]

    student_b_token = await _register_login_student(client, "isolation.b@college.edu")
    response = await _answer(client, student_b_token, attempt_id, session_token, question_id, "A")
    assert response.status_code == 403


# ---------------------------------------------------------------------
# Anti-cheat: session token binding, violations, auto-submit
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrong_session_token_rejected(client):
    admin_token = await _register_login_admin(client, "sessiontoken.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "SessionTokenCat")

    student_token = await _register_login_student(client, "sessiontoken.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    question_id = start.json()["next_question"]["id"]

    response = await _answer(client, student_token, attempt_id, "wrong-session-token", question_id, "A")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_fingerprint_captured_at_start(client):
    admin_token = await _register_login_admin(client, "fingerprint.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "FingerprintCat")

    student_token = await _register_login_student(client, "fingerprint.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id, fingerprint_hash="abc123fingerprint")
    attempt_id = start.json()["attempt_id"]

    from bson import ObjectId

    from app.core import database as db_module

    doc = await db_module.mongodb.db.assessment_attempts.find_one({"_id": ObjectId(attempt_id)})
    assert doc["fingerprint_hash"] == "abc123fingerprint"
    assert doc["ip_address"] is not None


@pytest.mark.asyncio
async def test_violations_below_threshold_do_not_submit(client):
    admin_token = await _register_login_admin(client, "belowthresh.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(
        client, admin_token, "BelowThreshCat", max_violations=3
    )

    student_token = await _register_login_student(client, "belowthresh.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]

    response = await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/violation",
        headers=_auth_headers(student_token),
        json={"session_token": session_token, "type": "tab_switch", "metadata": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["violation_count"] == 1
    assert body["max_violations"] == 3
    assert body["auto_submitted"] is False
    assert body["attempt_status"] == "in_progress"


@pytest.mark.asyncio
async def test_violations_reaching_threshold_auto_submits(client):
    admin_token = await _register_login_admin(client, "threshold.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(
        client, admin_token, "ThresholdCat", max_violations=2
    )

    student_token = await _register_login_student(client, "threshold.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]

    first = await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/violation",
        headers=_auth_headers(student_token),
        json={"session_token": session_token, "type": "tab_switch", "metadata": {}},
    )
    assert first.json()["auto_submitted"] is False

    second = await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/violation",
        headers=_auth_headers(student_token),
        json={"session_token": session_token, "type": "fullscreen_exit", "metadata": {}},
    )
    assert second.json()["auto_submitted"] is True
    assert second.json()["attempt_status"] == "submitted"

    question_id = start.json()["next_question"]["id"]
    late_answer = await _answer(client, student_token, attempt_id, session_token, question_id, "A")
    assert late_answer.status_code == 400


@pytest.mark.asyncio
async def test_violation_report_requires_correct_session_token(client):
    admin_token = await _register_login_admin(client, "violsession.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "ViolSessionCat")

    student_token = await _register_login_student(client, "violsession.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]

    response = await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/violation",
        headers=_auth_headers(student_token),
        json={"session_token": "wrong-token", "type": "tab_switch", "metadata": {}},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mcq_options_are_shuffled_but_still_gradeable(client):
    admin_token = await _register_login_admin(client, "shuffle.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "ShuffleCat")

    student_token = await _register_login_student(client, "shuffle.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    question_id = start.json()["next_question"]["id"]
    options = start.json()["next_question"]["options"]
    assert set(options) == {"A", "B", "C", "D"}

    answer = await _answer(client, student_token, attempt_id, session_token, question_id, "A")
    assert answer.json()["is_correct"] is True


# ---------------------------------------------------------------------
# Knowledge tracing
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_correct_answer_raises_mastery_for_skill(client):
    admin_token = await _register_login_admin(client, "mastery.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "MasteryCat")

    student_token = await _register_login_student(client, "masterystudent@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    question_id = start.json()["next_question"]["id"]

    await _answer(client, student_token, attempt_id, session_token, question_id, "A")

    states = await client.get("/api/v1/assessments/knowledge-states/me", headers=_auth_headers(student_token))
    assert states.status_code == 200
    body = states.json()
    assert len(body) == 1
    assert body[0]["skill_tag"] == "Python"
    assert body[0]["mastery_pct"] > 50.0


@pytest.mark.asyncio
async def test_student_cannot_view_other_students_knowledge_states(client):
    student_token = await _register_login_student(client, "privacy.student@college.edu")
    response = await client.get(
        "/api/v1/assessments/knowledge-states/someoneelseid", headers=_auth_headers(student_token)
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tpo_can_view_student_knowledge_states(client):
    admin_token = await _register_login_admin(client, "tpoview.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "TpoViewCat")

    student_token = await _register_login_student(client, "tpoview.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    attempt_id = start.json()["attempt_id"]
    session_token = start.json()["session_token"]
    question_id = start.json()["next_question"]["id"]
    await _answer(client, student_token, attempt_id, session_token, question_id, "A")

    from app.core import database as db_module

    me = await client.get("/api/v1/auth/me", headers=_auth_headers(student_token))
    student_doc = await db_module.mongodb.db.students.find_one({"user_id": me.json()["id"]})

    tpo_token = await _register_login_tpo(client, "tpoview.tpo@college.edu")

    # A TPO may only see a student's knowledge states once that student has
    # applied to one of THIS TPO's drives. This test used to assert a blanket
    # 200 with no such relationship, which is why it started failing when the
    # endpoint was correctly tightened — the endpoint was right, the test was
    # stale. Establish the relationship the access rule actually requires.
    drive = await client.post(
        "/api/v1/drives",
        headers=_auth_headers(tpo_token),
        json={
            "company_name": "TpoView Corp",
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
    drive_id = drive.json()["id"]

    # Applying requires an active resume.
    upload = await client.post(
        "/api/v1/resumes",
        headers=_auth_headers(student_token),
        files={"file": ("resume.pdf", MINIMAL_PDF_BYTES, "application/pdf")},
    )
    assert upload.status_code == 201, upload.text

    applied = await client.post(
        f"/api/v1/drives/{drive_id}/apply", headers=_auth_headers(student_token)
    )
    assert applied.status_code == 201, applied.text

    response = await client.get(
        f"/api/v1/assessments/knowledge-states/{str(student_doc['_id'])}", headers=_auth_headers(tpo_token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_tpo_cannot_view_unrelated_student_knowledge_states(client):
    """The other half of the contract, and the one worth locking down: a TPO
    must NOT be able to read an arbitrary student's mastery data just because
    they hold a TPO account. Without this, the permission check above would
    pass even if it were simply absent."""
    admin_token = await _register_login_admin(client, "tpoview2.admin@college.edu")
    assessment_id = await _setup_assessment_with_one_question_per_difficulty(client, admin_token, "TpoViewCat2")

    student_token = await _register_login_student(client, "tpoview2.student@college.edu")
    start = await _start_attempt(client, student_token, assessment_id)
    await _answer(
        client,
        student_token,
        start.json()["attempt_id"],
        start.json()["session_token"],
        start.json()["next_question"]["id"],
        "A",
    )

    from app.core import database as db_module

    me = await client.get("/api/v1/auth/me", headers=_auth_headers(student_token))
    student_doc = await db_module.mongodb.db.students.find_one({"user_id": me.json()["id"]})

    # A different TPO, with no drive and no application from this student.
    other_tpo_token = await _register_login_tpo(client, "tpoview2.tpo@college.edu")
    response = await client.get(
        f"/api/v1/assessments/knowledge-states/{str(student_doc['_id'])}",
        headers=_auth_headers(other_tpo_token),
    )
    assert response.status_code == 403
