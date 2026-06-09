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

# Anthropic API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

# SQL parsing defaults
SQL_DIALECT = "mysql"

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
