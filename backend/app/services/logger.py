"""Structured logger for the SQL analysis pipeline.

Logs to stdout (Docker-compatible) at key stages with balanced detail.
"""
import time
import sys


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


# ── Pipeline stages ────────────────────────────────────────────────────

def pipeline_start(script_name: str, sql_len: int):
    print(f"[{_ts()}] ⏳ PIPELINE START  script={script_name}  sql_bytes={sql_len}",
          file=sys.stderr, flush=True)


def stage_parse(ok: bool, statement_count: int):
    status = "OK" if ok else "FALLBACK"
    print(f"[{_ts()}]   ▶ parse  status={status}  statements={statement_count}",
          file=sys.stderr, flush=True)


def stage_extract(variable_count: int, table_count: int, cte_count: int):
    print(f"[{_ts()}]   ▶ extract  vars={variable_count}  tables={table_count}  ctes={cte_count}",
          file=sys.stderr, flush=True)


def stage_deps(edge_count: int, by_type: dict):
    summary = "  ".join(f"{k}={v}" for k, v in sorted(by_type.items())[:6])
    print(f"[{_ts()}]   ▶ deps  edges={edge_count}  {summary}",
          file=sys.stderr, flush=True)


def stage_graph(nodes: int, edges: int):
    print(f"[{_ts()}]   ▶ graph  nodes={nodes}  edges={edges}",
          file=sys.stderr, flush=True)


def pipeline_done(total_ms: float):
    print(f"[{_ts()}] ✅ PIPELINE DONE  elapsed={total_ms:.0f}ms",
          file=sys.stderr, flush=True)


def api_request(method: str, path: str, status: int, detail: str = ""):
    extra = f"  {detail}" if detail else ""
    print(f"[{_ts()}] 🌐 {method} {path}  → {status}{extra}",
          file=sys.stderr, flush=True)
