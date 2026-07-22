"""Folder index service — scan directory tree, build table/field indexes."""
import json
from pathlib import Path
from app.services.workspace_service import get_workspace_dir, get_script_path

SQL_EXTENSIONS = {".sql"}


# Progress tracking for polling
_INDEX_PROGRESS = {}  # ws_id -> {current, total, phase, errors}

def _set_progress(ws_id: str, current: int, total: int, phase: str):
    _INDEX_PROGRESS[ws_id] = {"current": current, "total": total, "phase": phase, "errors": []}

def get_index_progress(ws_id: str) -> dict:
    return _INDEX_PROGRESS.get(ws_id, {"current": 0, "total": 0, "phase": "idle"})

def scan_folder(ws_id: str) -> dict:
    """Walk workspace scripts/ dir, return hierarchical tree with is_sql flag."""
    ws_dir = get_workspace_dir(ws_id)
    scripts_dir = ws_dir / "scripts"
    if not scripts_dir.exists():
        return {"name": "root", "type": "directory", "children": []}
    
    def _walk(path: Path, rel: str = ""):
        entry = {
            "name": path.name,
            "path": str(path.relative_to(scripts_dir)),
            "type": "directory" if path.is_dir() else "file",
        }
        if path.is_file():
            ext = path.suffix.lower()
            entry["is_sql"] = ext in SQL_EXTENSIONS
        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                children.append(_walk(child))
            entry["children"] = children
        return entry
    
    return _walk(scripts_dir)


def index_scripts(ws_id: str, script_paths: list[str]) -> dict:
    """Analyze selected scripts, build table_index and field_index.
    
    For each script:
      1. Read SQL from workspace/scripts/{path}
      2. Call run_full_analysis()
      3. Extract table/column variables
      4. Build indexes
    
    Returns: {table_index, field_index, script_count, precomputed_count}
    """
    from app.extractor.adapter import run_full_analysis

    table_index = {}   # table_name -> {fields: set, scripts: set}
    field_index = {}   # field_name -> {tables: set, scripts: set}
    script_count = 0
    precomputed = 0
    errors = []
    total = len(script_paths)
    _set_progress(ws_id, 0, total, "analyzing")

    for i, rel_path in enumerate(script_paths):
        sp = get_script_path(ws_id, rel_path)
        if not sp or not sp.exists():
            errors.append({"script": rel_path, "error": "File not found"})
            continue

        try:
            sql_text = sp.read_text(encoding="utf-8", errors="replace")
            result = run_full_analysis(sql_text, rel_path)
            script_count += 1
            _set_progress(ws_id, i + 1, total, "analyzing")

            # Cache analysis result
            cache_dir = get_workspace_dir(ws_id) / "cache"
            import hashlib
            cache_key = hashlib.md5((rel_path + sql_text).encode()).hexdigest()[:12]
            cache_path = cache_dir / f"analysis_{cache_key}.json"
            cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

            # Pre-compute graph
            try:
                from app.services.graph_service import build_graph_data
                graph_data = build_graph_data(result)
                graph_cache_path = cache_dir / f"graph_{cache_key}.json"
                graph_cache_path.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False))
                precomputed += 1
            except Exception:
                pass  # graph pre-computation is optional

            # Build indexes from variables
            variables = result.get("variables", [])
            for v in variables:
                vt = v.get("variable_type", "")
                name = v.get("name", "")

                if vt == "table":
                    table_index.setdefault(name, {"fields": set(), "scripts": set()})
                    table_index[name]["scripts"].add(rel_path)

                elif vt == "column":
                    field_name = name.split(".", 1)[-1] if "." in name else name
                    table_name = name.split(".", 1)[0] if "." in name else ""
                    field_index.setdefault(field_name, {"tables": set(), "scripts": set()})
                    field_index[field_name]["scripts"].add(rel_path)
                    if table_name:
                        field_index[field_name]["tables"].add(table_name)
                        table_index.setdefault(table_name, {"fields": set(), "scripts": set()})
                        table_index[table_name]["fields"].add(field_name)

        except Exception as e:
            errors.append({"script": rel_path, "error": str(e)})
            _set_progress(ws_id, i + 1, total, "analyzing")

    # Convert sets to sorted lists for JSON
    for ti in table_index.values():
        ti["fields"] = sorted(ti["fields"])
        ti["scripts"] = sorted(ti["scripts"])
    for fi in field_index.values():
        fi["tables"] = sorted(fi["tables"])
        fi["scripts"] = sorted(fi["scripts"])

    # Cache indexes
    cache_dir = get_workspace_dir(ws_id) / "cache"
    (cache_dir / "table_index.json").write_text(json.dumps(table_index, indent=2))
    (cache_dir / "field_index.json").write_text(json.dumps(field_index, indent=2))

    # Update workspace meta
    ws_dir = get_workspace_dir(ws_id)
    meta = json.loads((ws_dir / "meta.json").read_text())
    meta["indexed"] = True
    meta["indexed_scripts"] = script_paths
    meta["indexed_at"] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    (ws_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    _set_progress(ws_id, total, total, "done")
    return {
        "table_index": table_index,
        "field_index": field_index,
        "script_count": script_count,
        "precomputed_count": precomputed,
        "errors": errors,
    }


def autocomplete(index: dict, type_: str, query: str) -> list[str]:
    """Return matching names from the index (case-insensitive substring, max 20)."""
    if not query:
        return sorted(index.keys())[:20]
    q = query.lower()
    matches = [k for k in index if q in k.lower()]
    return sorted(matches)[:20]


def tables_for_field(index: dict, field: str) -> list[str]:
    """Return all tables containing the given field."""
    entry = index.get(field, {})
    return entry.get("tables", [])


def fields_for_table(index: dict, table: str) -> list[str]:
    """Return all fields of the given table."""
    entry = index.get(table, {})
    return entry.get("fields", [])


def get_index_status(ws_id: str) -> dict:
    """Return current indexing status."""
    ws_dir = get_workspace_dir(ws_id)
    meta_path = ws_dir / "meta.json"
    if not meta_path.exists():
        return {"indexed": False}
    meta = json.loads(meta_path.read_text())
    return {
        "indexed": meta.get("indexed", False),
        "script_count": len(meta.get("indexed_scripts", [])),
        "indexed_at": meta.get("indexed_at"),
    }
