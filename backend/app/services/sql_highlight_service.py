"""SQL highlight service — line mapping and highlight range computation."""
import hashlib
from app.services.workspace_service import get_workspace_dir


def get_highlight_ranges(ws_id: str, script_name: str,
                         table: str, field: str) -> dict:
    """Return line ranges to highlight for target table.field in a script.

    E4 (item 3): `script_name` is user-controlled and was joined raw into
    the scripts path — `script=..` raised IsADirectoryError (500). Resolve
    through the shared containment resolver; missing / not-a-file keeps the
    existing error shape (the router turns it into a 404 for HTTP callers).
    """
    ws_dir = get_workspace_dir(ws_id)
    scripts_dir = ws_dir / "scripts"
    cache_dir = ws_dir / "cache"

    from app.services.filter_service import resolve_script
    sp = resolve_script(ws_id, script_name)
    if sp is None or not sp.is_file():
        return {"error": f"Script '{script_name}' not found", "highlight_ranges": []}

    sql_text = sp.read_text(encoding="utf-8", errors="replace")
    total_lines = sql_text.count('\n') + 1
    cache_key = hashlib.md5((script_name + sql_text).encode()).hexdigest()[:12]

    # Load analysis to get line_map
    analysis_path = cache_dir / f"analysis_{cache_key}.json"
    if not analysis_path.exists():
        return {
            "script_name": script_name,
            "total_lines": total_lines,
            "highlight_ranges": [],
            "error": "Analysis not cached — index first",
        }

    import json
    analysis = json.loads(analysis_path.read_text())
    line_map = analysis.get("line_map", {})

    # Find variables matching target table.field
    from app.services.dataflow_service import filter_relevant
    from app.services.graph_service import build_graph_data

    graph_data = build_graph_data(analysis)
    filtered = filter_relevant(graph_data, table, field)

    # Get line ranges for highlighted nodes
    ranges = []
    for n in filtered.get("nodes", []):
        nd = n.get("data", n)
        nid = nd.get("id", "")
        if nid in line_map:
            start, end = line_map[nid]
            ranges.append([start, end])

    # Merge overlapping ranges
    if ranges:
        ranges.sort()
        merged = [ranges[0]]
        for r in ranges[1:]:
            last = merged[-1]
            if r[0] <= last[1] + 1:
                merged[-1][1] = max(last[1], r[1])
            else:
                merged.append(r)
        ranges = merged

    return {
        "script_name": script_name,
        "total_lines": total_lines,
        "highlight_ranges": ranges,
        "target_field": f"{table}.{field}",
    }
