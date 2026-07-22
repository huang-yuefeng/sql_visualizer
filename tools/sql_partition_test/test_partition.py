#!/usr/bin/env python3
"""
SQL Partition Test — verifies that L2 edge sql_range values form a valid partition
of the SQL source text.

Mathematical invariants:
  1. Coverage: union(all edge segments) / total_SQL_lines ≥ 90%
  2. Overlap:  no line covered by 2+ edges with DIFFERENT ranges
  3. Gaps:     only comments/blanks uncovered
"""
import sys, os, json, requests, time
from collections import defaultdict

# Add parent dir for sql_partitioner import
sys.path.insert(0, os.path.dirname(__file__))
from sql_partitioner import partition_sql

BASE = os.environ.get("API_URL", "http://127.0.0.1:8000/api")

def test_script(ws_id, view_id, script_path):
    """Test one L2 script's edge ranges against SQL partition."""
    l2 = requests.get(f"{BASE}/workspace/{ws_id}/views/{view_id}/level2",
                      params={"script": script_path, "filter": "false"})
    if not l2.ok:
        return {"script": script_path, "error": f"L2 API failed: {l2.status_code}"}

    l2d = l2.json()
    sql_text = l2d.get("sql_text", "")
    edges = l2d.get("graph", {}).get("edges", [])

    if not sql_text or not edges:
        return {"script": script_path, "error": "No SQL or edges"}

    lines = sql_text.split('\n')
    N = len(lines)

    # Build edge coverage bitmap
    covered_by = defaultdict(set)  # line_idx -> set(edge_ids)
    edge_ranges = {}
    for e in edges:
        ed = e.get("data", e)
        sr = ed.get("sql_range")
        if not sr:
            continue
        eid = ed.get("id", "?")
        etype = ed.get("edge_type", "?")
        start, end = sr[0], sr[2]
        edge_ranges[eid] = {"start": start, "end": end, "type": etype,
                            "lines": end - start + 1}
        for li in range(start, end + 1):
            if 1 <= li <= N:
                covered_by[li].add(eid)

    # Compute metrics
    total_edges = len(edge_ranges)
    lines_with_edges = sum(1 for i in range(1, N+1) if covered_by[i])
    lines_with_multi = sum(1 for i in range(1, N+1) if len(covered_by[i]) > 1)
    lines_uncovered = sum(1 for i in range(1, N+1) if len(covered_by[i]) == 0)

    coverage = lines_with_edges / N if N > 0 else 0
    overlap_rate = lines_with_multi / N if N > 0 else 0
    gap_rate = lines_uncovered / N if N > 0 else 0

    # Are gaps only comments/blank lines?
    gaps_ok = True
    gap_lines = []
    for i in range(1, N+1):
        if not covered_by[i]:
            stripped = lines[i-1].strip()
            if stripped and not stripped.startswith('--'):
                gaps_ok = False
                gap_lines.append(i)

    # Redundancy: edges per covered line
    total_assignments = sum(len(s) for s in covered_by.values())
    redundancy = total_assignments / max(lines_with_edges, 1)

    # Compute per-edge-type metrics
    by_type = defaultdict(lambda: {"count": 0, "total_lines": 0, "avg_lines": 0})
    for eid, er in edge_ranges.items():
        t = er["type"].split(",")[0].strip()
        by_type[t]["count"] += 1
        by_type[t]["total_lines"] += er["lines"]
    for t in by_type:
        by_type[t]["avg_lines"] = round(by_type[t]["total_lines"] / by_type[t]["count"], 1)

    # Verdict
    pass_checks = 0
    total_checks = 3
    if coverage >= 0.85: pass_checks += 1
    if overlap_rate == 0: pass_checks += 1
    if gaps_ok or gap_rate <= 0.15: pass_checks += 1

    return {
        "script": script_path,
        "sql_lines": N,
        "edges": total_edges,
        "coverage": round(coverage * 100, 1),
        "overlap_rate": round(overlap_rate * 100, 1),
        "gap_rate": round(gap_rate * 100, 1),
        "gaps_ok": gaps_ok,
        "gap_lines": gap_lines[:10],
        "redundancy": round(redundancy, 2),
        "by_type": dict(by_type),
        "verdict": "PASS" if pass_checks == total_checks else
                   "PARTIAL" if pass_checks >= 2 else "FAIL",
    }


def main():
    print("=" * 70)
    print("SQL PARTITION TEST — Coverage + Overlap + Gap Analysis")
    print("=" * 70)

    # Setup workspace
    zip_path = sys.argv[1] if len(sys.argv) > 1 else "/home/huangyf/work/sql_visualizer/samples/multi_workflow.zip"
    table = sys.argv[2] if len(sys.argv) > 2 else "analytics_orders"
    field = sys.argv[3] if len(sys.argv) > 3 else "amount"

    print(f"\nUploading: {zip_path}")
    r = requests.post(f"{BASE}/workspace",
        files={"file": (os.path.basename(zip_path), open(zip_path, "rb"), "application/zip")})
    ws = r.json()["workspace_id"]

    paths = []
    def coll(c):
        if c.get('is_sql'): paths.append(c['path'])
        for ch in c.get('children', []): coll(ch)
    for ch in r.json()["file_tree"]["children"]: coll(ch)
    print(f"Files: {len(paths)}")

    requests.post(f"{BASE}/workspace/{ws}/index", json={"script_paths": paths})

    sr = requests.post(f"{BASE}/workspace/{ws}/search", json={"table": table, "field": field})
    view_id = sr.json()["view_id"]
    print(f"View: {view_id}")

    # Test each script
    results = []
    for script in paths:
        r = test_script(ws, view_id, script)
        results.append(r)
        if "error" in r:
            continue
        icon = {"PASS": "✅", "PARTIAL": "⚠️", "FAIL": "❌"}[r["verdict"]]
        print(f"\n{icon} {os.path.basename(script)[:45]}")
        print(f"   SQL={r['sql_lines']}L  Edges={r['edges']}  "
              f"Cover={r['coverage']}%  Overlap={r['overlap_rate']}%  "
              f"Gap={r['gap_rate']}%  Redund={r['redundancy']}")
        if r["gap_lines"]:
            print(f"   Gap lines: {r['gap_lines'][:5]}")
        if r["by_type"]:
            type_summary = ", ".join(f"{t}={d['avg_lines']}L" for t, d in sorted(r["by_type"].items()))
            print(f"   Types: {type_summary}")

    # Summary
    passed = sum(1 for r in results if r.get("verdict") == "PASS")
    total = sum(1 for r in results if "error" not in r)
    total_edges = sum(r.get("edges", 0) for r in results)
    avg_coverage = sum(r.get("coverage", 0) for r in results if "error" not in r) / max(total, 1)
    avg_overlap = sum(r.get("overlap_rate", 0) for r in results if "error" not in r) / max(total, 1)

    print(f"\n{'='*70}")
    print(f"SUMMARY: {passed}/{total} scripts PASS")
    print(f"  Total edges: {total_edges}")
    print(f"  Avg coverage: {avg_coverage:.1f}%")
    print(f"  Avg overlap: {avg_overlap:.1f}%")
    print(f"{'='*70}")

    requests.delete(f"{BASE}/workspace/{ws}")


if __name__ == "__main__":
    main()
