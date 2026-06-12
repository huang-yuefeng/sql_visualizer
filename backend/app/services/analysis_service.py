"""
Analysis Service — manages analysis results with file-based caching.

Includes version-based cache invalidation: when the project VERSION changes,
all cached results are automatically invalidated and re-analyzed.
"""

import hashlib
import json
import time
from pathlib import Path

from app.config import CACHE_DIR
from app.extractor.adapter import run_full_analysis


def _current_version() -> str:
    """Read the current project version from the VERSION file."""
    version_path = CACHE_DIR.parent.parent / "VERSION"
    try:
        return version_path.read_text().strip()
    except (FileNotFoundError, OSError):
        return "0.0.0"


def _script_key(script_name: str, sql_text: str) -> str:
    """Generate a deterministic cache key including version.

    When the version changes, old cache keys become invalid automatically.
    """
    content = f"{script_name}:{sql_text}:v{_current_version()}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


def analyze_sql(sql_text: str, script_name: str = "unnamed.sql") -> dict:
    """Analyze SQL text and cache the result.

    Args:
        sql_text: The SQL script content.
        script_name: A label for the script.

    Returns:
        The full analysis result dict.
    """
    key = _script_key(script_name, sql_text)
    result = run_full_analysis(sql_text, script_name)
    result["script_id"] = key
    result["analyzed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["_cache_version"] = _current_version()

    # Cache to file
    cache_path = CACHE_DIR / f"{key}.json"
    cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def get_script(script_id: str) -> dict | None:
    """Retrieve a cached analysis result by script ID.

    Returns None if the cache is missing or from an older version.
    """
    cache_path = CACHE_DIR / f"{script_id}.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    # Version check: if the cached data is from an older version, invalidate it
    cached_version = data.get("_cache_version", "0.0.0")
    if cached_version != _current_version():
        cache_path.unlink(missing_ok=True)
        return None
    return data


def list_scripts() -> list[dict]:
    """List all cached analysis results (current version only)."""
    scripts = []
    current_ver = _current_version()
    for path in sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            # Skip stale caches from older versions
            if data.get("_cache_version", "0.0.0") != current_ver:
                path.unlink(missing_ok=True)
                continue
            scripts.append({
                "script_id": data.get("script_id", path.stem),
                "script_name": data.get("script_name", "unknown"),
                "total_variables": data.get("total_variables", 0),
                "total_dependencies": data.get("total_dependencies", 0),
                "analyzed_at": data.get("analyzed_at", ""),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return scripts
