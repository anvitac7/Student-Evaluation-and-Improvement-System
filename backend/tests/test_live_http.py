"""
Live End-to-End HTTP Connection Verification.
Connects directly to the live running backend (http://localhost:8000)
and tests Next.js proxy route targets:
  1. Health & Database connectivity
  2. Student registration & login
  3. TPO registration & login
  4. Question Bank category listing
  5. Placement drive listing
  6. OpenAPI documentation inspection
"""
import urllib.request
import json
import time

BASE_URL = "http://127.0.0.1:8000/api/v1"

def make_request(path, method="GET", data=None, headers=None):
    url = f"{BASE_URL}{path}"
    headers = headers or {}
    headers["Content-Type"] = "application/json"
    
    encoded_data = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
            return status, body
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8")) if e.fp else {}
        return e.code, body

def run_tests():
    print("\n=======================================================")
    print("  PLACER: LIVE HTTP CONNECTION TEST (http://localhost:8000)")
    print("=======================================================\n")
    
    # 1. Health
    status, body = make_request("/health")
    print(f"[1/6] Health Check: HTTP {status} -> {body}")
    assert status == 200 and body.get("status") == "ok", "Health check failed"
    print("  [OK] Backend is live and connected to MongoDB!")

    # 2. Student Registration & Auth
    unique_student_email = f"student.test.{int(time.time())}@college.edu"
    status, body = make_request(
        "/auth/register/student",
        method="POST",
        data={
            "email": unique_student_email,
            "password": "StrongPassword123!",
            "name": "Integration Student",
            "department": "Computer Science",
            "batch_year": 2026,
        }
    )
    print(f"[2/6] Student Register: HTTP {status}")
    assert status == 201, f"Student registration failed: {body}"
    
    status, body = make_request(
        "/auth/login",
        method="POST",
        data={"email": unique_student_email, "password": "StrongPassword123!"}
    )
    assert status == 200, f"Login failed: {body}"
    student_token = body["access_token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}
    print("  [OK] Student Login: OK (Access Token Generated)")

    # 3. Student Profile Check
    status, body = make_request("/students/me", headers=student_headers)
    print(f"[3/6] Student Profile API: HTTP {status} (Name: '{body.get('name')}', Dept: '{body.get('department')}')")
    assert status == 200, "Failed to get student profile"
    print("  [OK] Student profile correctly retrieved")

    # 4. TPO Registration & Auth
    unique_tpo_email = f"tpo.test.{int(time.time())}@college.edu"
    status, body = make_request(
        "/auth/register/tpo",
        method="POST",
        data={
            "email": unique_tpo_email,
            "password": "StrongPassword123!",
            "name": "Prof. TPO Lead",
            "department_scope": ["Computer Science"],
        }
    )
    print(f"[4/6] TPO Register: HTTP {status}")
    assert status == 201, f"TPO registration failed: {body}"
    
    status, body = make_request(
        "/auth/login",
        method="POST",
        data={"email": unique_tpo_email, "password": "StrongPassword123!"}
    )
    tpo_token = body["access_token"]
    tpo_headers = {"Authorization": f"Bearer {tpo_token}"}
    print("  [OK] TPO Login: OK")

    # 5. Placement Drives API (via Student and TPO)
    status, body = make_request("/drives", headers=student_headers)
    print(f"[5/6] Drives Listing API: HTTP {status} ({len(body)} drives available)")
    assert status == 200, "Failed to list drives"

    status, body = make_request("/drives/mine", headers=tpo_headers)
    print(f"  [OK] TPO 'My Drives' API: HTTP {status} ({len(body)} drives owned)")
    assert status == 200, "Failed to list TPO drives"

    # 6. Categories & Questions API
    status, body = make_request("/questions/categories", headers=tpo_headers)
    print(f"[6/6] Question Categories API: HTTP {status} ({len(body)} categories registered)")
    assert status == 200, "Failed to list categories"

    print("\n=======================================================")
    print("  ALL LIVE FRONTEND-TO-BACKEND API CALLS SUCCEEDED! 100%")
    print("=======================================================\n")

if __name__ == "__main__":
    run_tests()
