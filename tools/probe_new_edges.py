"""Audit probe — verify the round-1 edge emission claims (throwaway).

Checks: canonical READ pairs present + no cross-scope pairs; 1c-extra2
output-VT edges per-statement; WRITE_READ endpoints + no reversed-time
edges; Phase-7 bridge removed; self-loop; 1c-direct CTE edges.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph

sql_text = Path("/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql").read_text()
res = extract_variables_from_sql(sql_text, "BDM_ACC_LOAN_INFO_SUP_M.sql")
deps = build_dependency_graph(res, sql_text)
by_id = {v.id: v for v in res.variables}
print("deps:", len(deps), "| vars:", len(res.variables))

def fmt(nid):
    v = by_id[nid]
    return f"{v.name}@{v.line_start}"

def ctx(nid):
    return by_id[nid].context or "TOP"

# 1. canonical READ pairs + NO cross-scope
reads = [d for d in deps if d.relationship == "SUBSET" and d.operation == "READ"]
print("\nREAD edges:", len(reads))
for want in [("p1.data_dt@43", "p1@29"), ("p1.data_dt@158", "p1@84")]:
    hit = any(fmt(d.source_id) == want[0] and fmt(d.target_id) == want[1] for d in reads)
    print(f"  canonical {want}: {'OK' if hit else 'MISSING'}")
bad = [d for d in reads if ctx(d.source_id) != ctx(d.target_id)]
print("  cross-scope READ pairs (must be 0):", len(bad))
for d in bad[:3]:
    print("   BAD:", fmt(d.source_id), "->", fmt(d.target_id))

# 2. 1c-extra2 output-VT -> DML target: per-statement VTs?
for d in deps:
    if d.relationship == "TABLE_FLOW" and d.operation in ("INSERT", "MERGE"):
        s = by_id[d.source_id]
        if s.variable_type.value == "virtual_table":
            t = by_id[d.target_id]
            print(f"  1c-extra2: {s.name}@{s.line_start} ctx={ctx(d.source_id)!r} -> {t.name}@{t.line_start} ctx={ctx(d.target_id)!r}")

# 3. WRITE_READ edges
wr = [d for d in deps if d.relationship == "DML" and d.operation == "WRITE_READ"]
print("\nWRITE_READ:", len(wr))
for d in wr:
    print("  ", fmt(d.source_id), f"[stmt {ctx(d.source_id)}]", "->", fmt(d.target_id), f"[stmt {ctx(d.target_id)}]")

# 4. Phase-7 bridge still present?
br = [d for d in deps if d.relationship == "SUBSET" and d.operation == "BRIDGE"
      and fmt(d.source_id) == "rrcdm_job_log_exec_par@211"]
print("Phase-7 bridge rrcdm@211->... (must be 0):", len(br))

# 5. self-loops
sl = [(fmt(d.source_id), d.relationship, d.operation) for d in deps if d.source_id == d.target_id]
print("self-loops:", sl)

# 6. 1c-direct CTE edges
for d in deps:
    if d.relationship == "TABLE_FLOW" and d.operation == "REFERENCE":
        s, t = fmt(d.source_id), fmt(d.target_id)
        if s.startswith(("rollover", "loan_final")) and t.startswith(("loan_final", "bdm_acc_loan_info_sup")):
            print("  1c-direct:", s, "->", t)

# 7. count breakdown: relationship/operation histogram of NEW edges vs old
from collections import Counter
hist = Counter((d.relationship, d.operation) for d in deps)
print("\nhistogram (rel, op) -> count:")
for k in sorted(hist):
    print("  ", k, hist[k])
