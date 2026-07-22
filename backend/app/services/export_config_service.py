"""SQL Export Config Service — manage per-workspace export configuration."""
import json
from pathlib import Path
from app.services.workspace_service import get_workspace_dir


DEFAULT_CONFIG = {
    "include_ctes": True,
    "include_temp_tables": True,
    "wrap_transaction": False,
    "add_header": True,
    "context_lines": 3,
    "include_dependencies": True,
    "dialect": "auto",
    "format_output": False,
    "include_comments": True,
    "target_only": False,
}


def get_config_path(ws_id: str) -> Path:
    return get_workspace_dir(ws_id) / "cache" / "export_config.json"


def get_export_config(ws_id: str) -> dict:
    """Return current export config, or default if none uploaded."""
    path = get_config_path(ws_id)
    if path.exists():
        try:
            uploaded = json.loads(path.read_text())
            # Merge with defaults so new keys always have values
            merged = {**DEFAULT_CONFIG, **uploaded}
            return merged
        except (json.JSONDecodeError, TypeError):
            pass
    return dict(DEFAULT_CONFIG)


def save_export_config(ws_id: str, config: dict) -> dict:
    """Save user-uploaded config, merge with defaults. Returns final config."""
    current = {**DEFAULT_CONFIG, **config}
    path = get_config_path(ws_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2))
    return current


def reset_export_config(ws_id: str) -> dict:
    """Delete uploaded config, revert to defaults."""
    path = get_config_path(ws_id)
    if path.exists():
        path.unlink()
    return dict(DEFAULT_CONFIG)


def apply_export_config(sql_text: str, highlights: list,
                        config: dict, script_name: str = "",
                        table: str = "", field: str = "",
                        analysis: dict = None) -> str:
    """Apply export config to SQL text with highlights.

    Returns the final export SQL string based on config settings.
    """
    lines = sql_text.split("\n") if sql_text else []

    if not highlights or not lines:
        return sql_text or ""

    ctx = config.get("context_lines", 3)

    # Compute export line ranges with context
    ranges = []
    for h in highlights:
        start, end = h[0], h[1]
        expanded_start = max(1, start - ctx)
        expanded_end = min(len(lines), end + ctx)
        ranges.append([expanded_start, expanded_end])

    # Merge overlapping ranges
    ranges.sort()
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r[0] <= last[1] + 1:
            merged[-1][1] = max(last[1], r[1])
        else:
            merged.append(r)

    output_parts = []

    # ── Header ──
    if config.get("add_header", True):
        output_parts.append("-- ============================================================")
        output_parts.append(f"-- Exported by SQL Data Flow Debugger v3.1")
        if table and field:
            output_parts.append(f"-- Target: {table}.{field}")
        if script_name:
            output_parts.append(f"-- Source: {script_name}")
        from datetime import datetime, timezone
        output_parts.append(f"-- Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        output_parts.append("-- ============================================================")
        output_parts.append("")

    # ── Transaction wrap ──
    if config.get("wrap_transaction", False):
        output_parts.append("BEGIN;")
        output_parts.append("")

    # ── Extract CTE definitions ──
    if config.get("include_ctes", True) and analysis:
        cte_sql = _extract_cte_definitions(analysis, lines)
        if cte_sql:
            output_parts.append("-- ── CTE Definitions ──")
            output_parts.append(cte_sql)
            output_parts.append("")

    # ── Temp table DDL ──
    if config.get("include_temp_tables", True) and analysis:
        temp_sql = _extract_temp_table_ddl(analysis, lines)
        if temp_sql:
            output_parts.append("-- ── Temp Table DDL ──")
            output_parts.append(temp_sql)
            output_parts.append("")

    # ── Main SQL (highlighted sections) ──
    output_parts.append("-- ── Data Flow SQL ──")
    if config.get("include_comments", True):
        output_parts.append(f"-- Target variable: {table}.{field}" if table and field else "-- Target variable")

    prev_end = 0
    for i, (start, end) in enumerate(merged):
        if start > prev_end + 1 and prev_end > 0:
            output_parts.append(f"-- ... {start - prev_end - 1} lines omitted ...")
        for j in range(start - 1, end):
            if j < len(lines):
                output_parts.append(lines[j])
        prev_end = end

    # ── Transaction close ──
    if config.get("wrap_transaction", False):
        output_parts.append("")
        output_parts.append("COMMIT;")

    return "\n".join(output_parts)


def _extract_cte_definitions(analysis: dict, lines: list) -> str:
    """Extract CTE (WITH ...) definitions from the SQL if present in analysis."""
    variables = analysis.get("variables", [])
    line_map = analysis.get("line_map", {})

    cte_vars = [v for v in variables if v.get("variable_type") == "cte"]
    if not cte_vars:
        return ""

    # Find the WITH clause by looking for the earliest CTE start line
    cte_lines = set()
    for cte in cte_vars:
        vid = cte.get("id", "")
        lr = line_map.get(vid, (0, 0))
        if isinstance(lr, list) and len(lr) >= 2:
            for ln in range(lr[0], lr[1] + 1):
                cte_lines.add(ln)

    if not cte_lines:
        return ""

    min_line = min(cte_lines)
    max_line = max(cte_lines)

    # Walk backward from first CTE line to find WITH
    with_line = min_line
    # Search backward up to 100 lines for WITH keyword
    for i in range(min_line - 1, max(0, min_line - 100), -1):
        if lines[i-1].strip().upper().startswith("WITH"):
            with_line = i
            break
    # Fallback: search entire script from beginning if WITH not found nearby
    if with_line == min_line:
        for i in range(0, min_line):
            if lines[i].strip().upper().startswith("WITH"):
                with_line = i + 1
                break

    result = []
    for i in range(with_line - 1, max_line):
        if i < len(lines):
            result.append(lines[i])
    return "\n".join(result)


def _extract_temp_table_ddl(analysis: dict, lines: list) -> str:
    """Extract CREATE TEMP TABLE / INSERT statements if present."""
    variables = analysis.get("variables", [])
    line_map = analysis.get("line_map", {})

    ddl_lines = set()
    for v in variables:
        if v.get("variable_type") in ("table", "view"):
            defined_in = v.get("defined_in", "")
            if defined_in and "TEMP" in defined_in.upper():
                vid = v.get("id", "")
                lr = line_map.get(vid, (0, 0))
                if isinstance(lr, list) and len(lr) >= 2:
                    for ln in range(lr[0], lr[1] + 1):
                        ddl_lines.add(ln)

    if not ddl_lines:
        return ""

    min_line = min(ddl_lines)
    max_line = max(ddl_lines)
    result = []
    for i in range(min_line - 1, max_line):
        if i < len(lines):
            result.append(lines[i])
    return "\n".join(result)
