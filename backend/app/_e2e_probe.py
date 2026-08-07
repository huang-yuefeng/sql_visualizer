"""E2E probe (v3.3.140 strict flow) — run: docker exec -w /app/backend gps-sql-backend python3 app/_e2e_probe.py"""
import sys
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import build_graph_data
from app.extractor.lineage import compute_field_flow, filter_by_field_flow
from app.services.l2_builder import _build_l2_graph, _compute_highlight_ranges

sql_text = open("/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql").read()
script_name = "BDM_ACC_LOAN_INFO_SUP_M.sql"
r = run_full_analysis(sql_text, script_name)
print("vars:", len(r.get("variables", [])), "extractor_version:", r.get("extractor_version"))
g = build_graph_data(r)
print("full graph nodes:", len(g["nodes"]), "edges:", len(g["edges"]), "format_version:", g.get("format_version"))
node_lines = sum(1 for n in g["nodes"] if n.get("data", n).get("line_start", 0) > 0)
print("nodes with line_start>0:", node_lines)
pv = [n for n in g["nodes"] if n.get("data", n).get("defined_in") == "PARTITION"]
print("PARTITION vars:", [(n["data"]["label"], n["data"].get("line_start")) for n in pv])

closure = compute_field_flow(g, "bdm_acc_loan_info", "data_dt")
cn = {n["data"]["id"]: n["data"] for n in g["nodes"] if n["data"]["id"] in closure}
print("closure size:", len(closure))
for nid in sorted(cn, key=lambda i: (cn[i].get("label", ""), cn[i].get("context", ""))):
    d = cn[nid]
    print(f"  {d.get('label',''):<22} {d.get('variable_type',''):<14} ctx={str(d.get('context',''))[:48]:<48} line={d.get('line_start',0)}")

f = filter_by_field_flow(g, "bdm_acc_loan_info", "data_dt")
print("filtered:", len(f["nodes"]), "nodes /", len(f["edges"]), "edges")
l2 = _build_l2_graph("ws-probe", script_name, sql_text, "bdm_acc_loan_info", "data_dt", True)
print("search_matched:", l2.get("search_matched"))
l2n = l2.get("nodes", [])
print("L2 nodes:", len(l2n), "edges:", len(l2.get("edges", [])))
for n in sorted(l2n, key=lambda x: (x.get("data", {}).get("table_name", ""), x.get("data", {}).get("label", ""))):
    d = n.get("data", {})
    fields = [fld.get("data", {}).get("label", "") for fld in d.get("fields", [])]
    print(f"  {d.get('table_name',''):<26} label={d.get('label',''):<18} line={d.get('line_start',0)} fields={sorted(set(fields))}")
hids = {n.get("data", n).get("id", "") for n in f.get("nodes", [])}
hl = _compute_highlight_ranges(g, hids, sql_text)
print("HIGHLIGHTS:", hl)
expected = [[18, 18], [43, 43], [158, 158], [160, 160]]
print("BYTE-EXACT:", hl == expected)
