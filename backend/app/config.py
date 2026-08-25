"""Application configuration."""

import os
from pathlib import Path

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
SAMPLES_DIR = ROOT_DIR / "samples"
CACHE_DIR = BACKEND_DIR / "analysis_cache"

# Ensure cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# SQL parsing defaults
SQL_DIALECT = "mysql"

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

# R31: login gate. FAILS CLOSED — default ON (M-Po3, 2026-08-25): a deploy
# that forgets the flag now runs LOCKED instead of silently collapsing the
# multi-user model to one anonymous "dev-user". Dev/test must pass
# REQUIRE_LOGIN=false explicitly (backend/tests/conftest.py sets it before
# any app import, so the unauthenticated suite keeps running). The R31 gate
# tests flip it on (test_r31_gate.py subprocess) to exercise the gate.
REQUIRE_LOGIN = os.environ.get("REQUIRE_LOGIN", "true").lower() == "true"

# R31 (#269): config-provisioned users — the ONLY account-provisioning path.
# Every deploy force-syncs each account's password to this allowlist at
# startup (main.py lifespan), so accounts always match config. Default = the
# production admin account (admin@hsbc.com / 123456 — keep unchanged). A
# test/deploy container may pin different users via PROVISIONED_USERS_JSON
# (a JSON dict {username: password}).
import json as _json

PROVISIONED_USERS = {"admin@hsbc.com": "123456"}
_env_provisioned = os.environ.get("PROVISIONED_USERS_JSON")
if _env_provisioned:
    try:
        _parsed = _json.loads(_env_provisioned)
        if isinstance(_parsed, dict):
            PROVISIONED_USERS = _parsed
    except Exception:
        pass  # malformed override → keep the default allowlist
