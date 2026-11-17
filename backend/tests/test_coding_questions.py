"""Coding questions with executed test cases.

These tests exercise the real local runner (Python and Node) rather than
mocking it, so they also pin the stdin/stdout contract students and admins
see: the program reads stdin, writes stdout, and trailing whitespace is
ignored when comparing against the expected output.
"""
import pytest

from app.services.code_execution_service import supported_languages

PYTHON_ADD = "a, b = map(int, input().split())\nprint(a + b)\n"
PYTHON_WRONG = "print(0)\n"
PYTHON_HANG = "while True:\n    pass\n"


async def _register_login_admin(client, email="code.admin@college.edu"):
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


async def _register_login_student(client, email="code.student@college.edu"):
    await client.post(
        "/api/v1/auth/register/student",
        json={
            "email": email,
            "password": "StrongPass123",
            "name": "Code Student",
            "department": "CS",
            "batch_year": 2026,
        },
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StrongPass123"})
    return login.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_category(client, admin_token, name="Coding"):
    response = await client.post(
        "/api/v1/questions/categories", headers=_auth(admin_token), json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _coding_payload(
    category_id,
    *,
    language="python",
    test_cases=None,
    starter_code=None,
    text=None,
    difficulty="medium",
):
    return {
        "category_id": category_id,
        "skill_tags": ["Python"],
        "difficulty": difficulty,
        "type": "coding",
        "text": text or "Read two space-separated integers and print their sum.",
        "options": [],
        "language": language,
        "starter_code": starter_code,
        "test_cases": test_cases if test_cases is not None else [],
    }


async def _create_coding_question(client, admin_token, category_id, **kwargs):
    response = await client.post(
        "/api/v1/questions", headers=_auth(admin_token), json=_coding_payload(category_id, **kwargs)
    )
    return response


async def _create_assessment(client, admin_token, category_id, pool_size=1):
    response = await client.post(
        "/api/v1/assessments",
        headers=_auth(admin_token),
        json={
            "title": "Coding Assessment",
            "category_ids": [category_id],
            "question_pool_size": pool_size,
            "time_limit_sec": 600,
            "max_violations": 3,
            "require_fullscreen": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _start(client, student_token, assessment_id):
    response = await client.post(
        f"/api/v1/assessments/{assessment_id}/start",
        headers=_auth(student_token),
        json={"fingerprint_hash": None},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _answer(client, student_token, attempt_id, session_token, question_id, code):
    return await client.post(
        f"/api/v1/assessments/attempts/{attempt_id}/answer",
        headers=_auth(student_token),
        json={
            "session_token": session_token,
            "question_id": question_id,
            "response": code,
            "time_taken_sec": 30.0,
        },
    )


@pytest.mark.asyncio
async def test_coding_question_requires_language_and_at_least_one_test_case(client):
    admin_token = await _register_login_admin(client)
    category_id = await _create_category(client, admin_token)

    missing_language = await client.post(
        "/api/v1/questions",
        headers=_auth(admin_token),
        json={
            "category_id": category_id,
            "difficulty": "easy",
            "type": "coding",
            "text": "Print hello",
            "options": [],
        },
    )
    assert missing_language.status_code == 400
    assert "language" in missing_language.json()["detail"].lower()

    missing_cases = await _create_coding_question(client, admin_token, category_id)
    assert missing_cases.status_code == 400
    assert "test case" in missing_cases.json()["detail"].lower()

    created = await _create_coding_question(
        client,
        admin_token,
        category_id,
        starter_code="a, b = map(int, input().split())\n",
        test_cases=[{"input": "1 2\n", "expected_output": "3", "is_hidden": False}],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["language"] == "python"
    assert body["starter_code"].startswith("a, b")
    assert len(body["test_cases"]) == 1


@pytest.mark.asyncio
async def test_assessment_starts_when_only_easy_coding_question_exists(client):
    """Regression: the engine used to start only at medium and refused to
    start when a category had no medium question (e.g. a single easy coding
    problem). It should fall back to the available difficulty instead."""
    admin_token = await _register_login_admin(client, "code.easy.admin@college.edu")
    category_id = await _create_category(client, admin_token, "EasyOnlyCoding")
    created = await _create_coding_question(
        client,
        admin_token,
        category_id,
        difficulty="easy",
        test_cases=[
            {"name": "sample", "input": "1 2\n", "expected_output": "3", "is_hidden": False}
        ],
    )
    assert created.status_code == 201, created.text
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.easy.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    assert started["next_question"]["type"] == "coding"
    assert started["next_question"]["difficulty"] == "easy"


@pytest.mark.asyncio
async def test_student_view_exposes_only_visible_test_cases(client):
    admin_token = await _register_login_admin(client, "code.view.admin@college.edu")
    category_id = await _create_category(client, admin_token, "ViewCoding")
    question = await _create_coding_question(
        client,
        admin_token,
        category_id,
        test_cases=[
            {"name": "sample", "input": "1 2\n", "expected_output": "3", "is_hidden": False},
            {"name": "hidden", "input": "5 5\n", "expected_output": "10", "is_hidden": True},
        ],
    )
    assert question.status_code == 201, question.text
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.view.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    view = started["next_question"]

    assert view["type"] == "coding"
    assert view["language"] == "python"
    assert "correct_answer" not in view
    assert [case["name"] for case in view["visible_test_cases"]] == ["sample"]
    assert view["visible_test_cases"][0]["expected_output"] == "3"


@pytest.mark.asyncio
async def test_correct_python_solution_passes_all_test_cases(client):
    admin_token = await _register_login_admin(client, "code.pass.admin@college.edu")
    category_id = await _create_category(client, admin_token, "PassCoding")
    await _create_coding_question(
        client,
        admin_token,
        category_id,
        test_cases=[
            {"name": "visible", "input": "1 2\n", "expected_output": "3", "is_hidden": False},
            {"name": "hidden", "input": "40 2\n", "expected_output": "42", "is_hidden": True},
        ],
    )
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.pass.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    result = await _answer(
        client,
        student_token,
        started["attempt_id"],
        started["session_token"],
        started["next_question"]["id"],
        PYTHON_ADD,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_correct"] is True
    assert body["marks_awarded"] == 3
    assert body["code_result"]["all_passed"] is True
    assert body["code_result"]["passed"] == 2
    assert body["attempt_status"] == "submitted"

    # Hidden test-case details must not leak through the results endpoint.
    results = await client.get(
        f"/api/v1/assessments/attempts/{started['attempt_id']}/results", headers=_auth(student_token)
    )
    assert results.status_code == 200, results.text
    answers = results.json()["answers"]
    assert len(answers) == 1
    code_result = answers[0]["code_result"]
    hidden = next(item for item in code_result["results"] if item["is_hidden"])
    assert hidden["input"] is None
    assert hidden["expected_output"] is None
    assert hidden["actual_output"] is None


@pytest.mark.asyncio
async def test_wrong_python_solution_scores_zero(client):
    admin_token = await _register_login_admin(client, "code.wrong.admin@college.edu")
    category_id = await _create_category(client, admin_token, "WrongCoding")
    await _create_coding_question(
        client,
        admin_token,
        category_id,
        test_cases=[{"name": "visible", "input": "1 2\n", "expected_output": "3", "is_hidden": False}],
    )
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.wrong.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    result = await _answer(
        client,
        student_token,
        started["attempt_id"],
        started["session_token"],
        started["next_question"]["id"],
        PYTHON_WRONG,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_correct"] is False
    assert body["marks_awarded"] == 0
    assert body["code_result"]["passed"] == 0
    assert body["code_result"]["results"][0]["status"] == "wrong_answer"


@pytest.mark.asyncio
async def test_run_code_endpoint_only_runs_visible_cases(client):
    admin_token = await _register_login_admin(client, "code.run.admin@college.edu")
    category_id = await _create_category(client, admin_token, "RunCoding")
    await _create_coding_question(
        client,
        admin_token,
        category_id,
        test_cases=[
            {"name": "visible", "input": "1 2\n", "expected_output": "3", "is_hidden": False},
            {"name": "hidden", "input": "9 1\n", "expected_output": "10", "is_hidden": True},
        ],
    )
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.run.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    response = await client.post(
        f"/api/v1/assessments/attempts/{started['attempt_id']}/run-code",
        headers=_auth(student_token),
        json={
            "session_token": started["session_token"],
            "question_id": started["next_question"]["id"],
            "code": PYTHON_ADD,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()["code_result"]
    assert body["total"] == 1
    assert body["passed"] == 1
    assert body["all_passed"] is True
    assert len(body["results"]) == 1


@pytest.mark.asyncio
async def test_timeout_is_reported_and_does_not_hang(client):
    admin_token = await _register_login_admin(client, "code.timeout.admin@college.edu")
    category_id = await _create_category(client, admin_token, "TimeoutCoding")
    await _create_coding_question(
        client,
        admin_token,
        category_id,
        test_cases=[{"name": "visible", "input": "", "expected_output": "done", "is_hidden": False}],
    )
    assessment_id = await _create_assessment(client, admin_token, category_id)

    from app.core.config import get_settings

    settings = get_settings()
    original = settings.CODE_EXECUTION_TIMEOUT_SECONDS
    settings.CODE_EXECUTION_TIMEOUT_SECONDS = 0.5
    try:
        student_token = await _register_login_student(client, "code.timeout.student@college.edu")
        started = await _start(client, student_token, assessment_id)
        result = await _answer(
            client,
            student_token,
            started["attempt_id"],
            started["session_token"],
            started["next_question"]["id"],
            PYTHON_HANG,
        )
    finally:
        settings.CODE_EXECUTION_TIMEOUT_SECONDS = original

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_correct"] is False
    assert body["code_result"]["results"][0]["status"] == "timeout"


@pytest.mark.asyncio
async def test_javascript_coding_question(client):
    if "javascript" not in supported_languages():
        pytest.skip("Node.js is not available on this machine.")

    admin_token = await _register_login_admin(client, "code.js.admin@college.edu")
    category_id = await _create_category(client, admin_token, "JsCoding")
    await _create_coding_question(
        client,
        admin_token,
        category_id,
        language="javascript",
        test_cases=[{"name": "visible", "input": "hello\n", "expected_output": "HELLO", "is_hidden": False}],
    )
    assessment_id = await _create_assessment(client, admin_token, category_id)

    student_token = await _register_login_student(client, "code.js.student@college.edu")
    started = await _start(client, student_token, assessment_id)
    result = await _answer(
        client,
        student_token,
        started["attempt_id"],
        started["session_token"],
        started["next_question"]["id"],
        "const input = require('fs').readFileSync(0, 'utf8').trim();\nconsole.log(input.toUpperCase());\n",
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["is_correct"] is True
    assert body["marks_awarded"] == 3
