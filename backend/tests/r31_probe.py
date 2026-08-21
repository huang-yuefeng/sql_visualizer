"""R31 login-gate probe — run ONLY in a subprocess with REQUIRE_LOGIN=true.

The gate reads REQUIRE_LOGIN at module import, so it can never be toggled
in-process once the app is imported by the main suite (which runs with the
gate OFF). This standalone script is invoked by test_r31_gate.py with the
env var set; it asserts the gate contract (A-M7) end-to-end and exits 0/1.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.2, A-M7) +
wiki/R31_IMPLEMENTATION.md (§2.5).
"""

import os
import sys
from pathlib import Path

# REQUIRE_LOGIN MUST be set before any app import.
os.environ["REQUIRE_LOGIN"] = "true"
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402


def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def main():
    client = TestClient(app)

    # health stays public
    r = client.get("/api/health")
    check(r.status_code == 200, f"health should be public, got {r.status_code}")

    # every other /api/* is gated behind a session cookie
    for path in ("/api/workspaces", "/api/auth/me", "/api/workspace"):
        r = client.get(path)
        check(r.status_code == 401, f"{path} should 401 without session, got {r.status_code}")

    # unknown username rejected (A-H2) — no auto-create
    r = client.post("/api/auth/login",
                    json={"username": "ghost@hsbc.com", "password": "secret1"})
    check(r.status_code == 401, "unknown username must be rejected")

    # Bootstrap hole (gate-exempt /api/admin/*): on a fresh deploy NO account
    # exists to log in with, so POST /api/admin/users provisions the FIRST
    # account without a session ("default first provisioned user", R31 impl
    # §2.5). The endpoint only ever targets ADMIN_USERNAME.
    r = client.post("/api/admin/users",
                    json={"username": "admin@hsbc.com", "password": "secret1",
                          "force": True})
    check(r.status_code == 200, f"admin bootstrap: {r.status_code} {r.text[:200]}")

    # login with the bootstrapped account
    r = client.post("/api/auth/login",
                    json={"username": "admin@hsbc.com", "password": "secret1"})
    check(r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}")
    check("session" in client.cookies, "session cookie not set")

    # authenticated requests now pass
    r = client.get("/api/workspaces")
    check(r.status_code == 200, f"/api/workspaces after login: {r.status_code}")
    r = client.get("/api/auth/me")
    check(r.status_code == 200 and r.json()["username"] == "admin@hsbc.com",
          f"/api/auth/me after login: {r.status_code}")

    # cross-origin state-changing request is rejected (same-origin check)
    r = client.post(
        "/api/workspace",
        files={"file": ("x.zip", b"pk", "application/zip")},
        headers={"Origin": "http://evil.example.com"},
    )
    check(r.status_code == 403, f"cross-origin POST should 403, got {r.status_code}")

    # same-origin request passes the gate and reaches the handler (400 for a
    # non-zip proves it was not blocked by the middleware)
    r = client.post(
        "/api/workspace",
        files={"file": ("x.txt", b"not a zip", "text/plain")},
        headers={"Origin": "http://testserver"},
    )
    check(r.status_code == 400, f"same-origin POST should reach handler (400), got {r.status_code}")

    # logout clears the session; a fresh /api/* request 401s again
    r = client.post("/api/auth/logout")
    check(r.status_code == 200, "logout failed")
    r = client.get("/api/workspaces")
    check(r.status_code == 401, "gate should re-apply after logout")

    print("GATE PROBE PASS")


if __name__ == "__main__":
    main()
