"""
Analysis Service — manages analysis results with file-based caching.
"""

import hashlib
import json
import time
from pathlib import Path

from app.config import CACHE_DIR
from app.extractor.adapter import run_full_analysis


def _script_key(script_name: str, sql_text: str) -> str:
    """Generate a deterministic cache key for a script."""
    content = f"{script_name}:{sql_text}"
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

    # Cache to file
    cache_path = CACHE_DIR / f"{key}.json"
    cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def get_script(script_id: str) -> dict | None:
    """Retrieve a cached analysis result by script ID."""
    cache_path = CACHE_DIR / f"{script_id}.json"
    if not cache_path.exists():
        return None
    return json.loads(cache_path.read_text())


def list_scripts() -> list[dict]:
    """List all cached analysis results."""
    scripts = []
    for path in sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            scripts.append({
                "script_id": data.get("script_id", path.stem),
                "script_name": data.get("script_name", "unknown"),
                "total_variables": data.get("total_variables", 0),
                "total_dependencies": data.get("total_dependencies", 0),
                "analyzed_at": data.get("analyzed_at", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return scripts
