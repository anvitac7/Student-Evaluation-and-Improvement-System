"""Live-ish test of the student insights endpoint against a real MongoDB.

Unlike the mongomock-based suite, this runs against the actual dev database
via a real HTTP call, because the aggregation logic depends on ObjectId
round-tripping and cross-collection joins that mongomock papers over.

Run with the backend already listening on :8000.
"""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
STU_EMAIL = "insights.stu@college.edu"
STU_PASS = "Student@12345"
ADMIN_EMAIL = "admin@placer.edu"
ADMIN_PASS = "Admin@12345"


def req(method, path, body=None, token=None, expect=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def login(email, password):
    st, body = req("POST", "/auth/login", {"email": email, "password": password})
    assert st == 200, f"login failed for {email}: {st} {body}"
    return body["access_token"]


def main():
    # --- student + tpo + admin setup (idempotent) ---
    req("POST", "/auth/register/student", {
        "email": STU_EMAIL, "password": STU_PASS, "name": "Insights Stu",
        "department": "Computer Science", "batch_year": 2026,
    })
    req("POST", "/auth/register/tpo", {
        "email": "insights.tpo@college.edu", "password": STU_PASS,
        "name": "Insights TPO", "department_scope": ["Computer Science"],
    })

    stu = login(STU_EMAIL, STU_PASS)
    tpo = login("insights.tpo@college.edu", STU_PASS)
    admin = login(ADMIN_EMAIL, ADMIN_PASS)

    # --- question category is required on every question ---
    st, cat = req("POST", "/questions/categories", {"name": "Insights Test Category"}, token=admin)
    if st == 201:
        cat_id = cat["id"]
    else:
        st2, cats = req("GET", "/questions/categories", token=admin)
        cat_id = cats[0]["id"]

    # --- question bank: 3 skills, deliberately varied difficulty ---
    questions = {}
    # The adaptive engine ALWAYS starts an attempt at medium difficulty
    # (AssessmentService.start_attempt), so the bank must contain at least
    # one medium question or the attempt refuses to start.
    for name, skill, difficulty in [
        ("py-medium", "Python", "medium"),
        ("py-hard", "Python", "hard"),
        ("sql-medium", "SQL", "medium"),
        ("algo-hard", "Algorithms", "hard"),
    ]:
        payload = {
            "category_id": cat_id, "skill_tags": [skill], "difficulty": difficulty,
            "type": "mcq", "text": f"Which statement about {skill} ({name}) is true?",
            "options": ["Correct statement", "Wrong statement A", "Wrong statement B"],
            "correct_answer": "Correct statement", "marks": 5,
        }
        st, body = req("POST", "/questions", payload, token=admin)
        assert st == 201, f"could not create question {name}: {st} {body}"
        questions[name] = body["id"]
    print("questions:", questions)

    # --- assessment over the full pool ---
    st, assessment = req("POST", "/assessments", {
        "title": "Insights Test Assessment",
        "category_ids": [cat_id],
        "question_pool_size": 4,
        "time_limit_sec": 1800,
    }, token=admin)
    assert st == 201, f"assessment create failed: {st} {assessment}"
    aid = assessment["id"]

    # --- take it, answering py-* wrong, sql-* right ---
    st, attempt = req("POST", f"/assessments/{aid}/start", {"fingerprint_hash": "insights-test"}, token=stu)
    assert st == 201, f"start failed: {st} {attempt}"
    att_id, session = attempt["attempt_id"], attempt["session_token"]
    # StartAttemptResponse nests the question rather than flattening
    # current_question_id onto the attempt.
    assert attempt["next_question"], "no first question returned"

    answered = 0
    while answered < 4:
        nq = attempt.get("next_question")
        if not nq:
            break
        qid = nq["id"]
        wrong = qid in (questions["py-medium"], questions["py-hard"], questions["algo-hard"])
        payload = {
            "question_id": qid, "session_token": session,
            "response": "Wrong statement A" if wrong else "Correct statement",
        }
        st, nxt = req("POST", f"/assessments/attempts/{att_id}/answer", payload, token=stu)
        assert st == 200, f"answer failed: {st} {nxt}"
        attempt = nxt
        answered += 1
    print(f"answered {answered} questions, attempt status now in results")

    # --- the endpoint under test ---
    st, insights = req("GET", "/insights/me", token=stu)
    print("\n" + "=" * 70)
    print(f"GET /insights/me -> {st}")
    print("=" * 70)
    print(json.dumps(insights, indent=2)[:3000])

    assert st == 200, "insights endpoint failed"
    assert insights["total_attempts"] >= 1, "should see the submitted attempt"
    assert insights["total_questions_answered"] >= 3, "should count graded answers"
    assert insights["study_guide"], "study guide should list missed questions"
    assert insights["focus_areas"], "Python should appear as a focus area (mastery dragged down)"

    missed_ids = {i["question_id"] for i in insights["study_guide"]}
    assert questions["py-medium"] in missed_ids, "guide must include a missed Python question"
    assert questions["sql-medium"] not in missed_ids, "guide must NOT include a correctly-answered question"

    print("\nPASS: cross-attempt focus areas + study guide working")
    print(f"  focus areas: {[f['skill'] for f in insights['focus_areas']]}")
    print(f"  study guide: {len(insights['study_guide'])} items")
    print(f"  narrative:   {insights['narrative']!r}")


if __name__ == "__main__":
    main()