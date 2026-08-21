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

# R31: login gate. Production enables it (REQUIRE_LOGIN=1 in the run
# command); dev/test default to off so the existing suite keeps running
# unauthenticated. New R31 tests flip it on to exercise the gate.
REQUIRE_LOGIN = os.environ.get("REQUIRE_LOGIN", "false").lower() == "true"

# R31: the admin username for POST /api/admin/users (the only account that
# may create/reset accounts). Provisioned as a normal allowlisted user too.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin@hsbc.com")
