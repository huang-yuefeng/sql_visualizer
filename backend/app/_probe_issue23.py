"""Issue 2/3 probe (Team B) — run: docker exec -w /app/backend gps-sql-backend python3 app/_probe_issue23.py"""
import json
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import build_graph_data
from app.extractor.lineage import compute_field_flow
from app.services.l2_builder import _build_l2_graph

SQL_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
sql = open("/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql", encoding="utf-8").read()
result = run_full_analysis(sql, SQL_NAME)
g = build_graph_data(result)

nodes = {n["data"]["id"]: n["data"] for n in g["nodes"]}
edges = g["edges"]

def lab(nid):
    d = nodes.get(nid)
    if not d:
        return f"?{nid[:12]}"
    return f"{d.get('label')}@{d.get('line_start', 0)}[{d.get('context')}]"

print("=== RAW edges: sup@160 / sup@223 / rrcdm / output VTs ===")
for e in edges:
    ed = e.get("data", e)
    s, t = lab(ed.get("source")), lab(ed.get("target"))
    if any(k in s + t for k in ("sup@160", "sup@223", "rrcdm", "output", "sup[")):
        print(f"  {s:<52} -> {t:<52} {ed.get('relationship'):<12} op={ed.get('operation')}")

print("\n=== bdm seed closure: key membership ===")
for seed_name, tbl, fld in (("bdm", "bdm_acc_loan_info", "data_dt"),
                            ("sup", "bdm_acc_loan_info_sup", "data_dt")):
    closure = compute_field_flow(g, tbl, fld)
    print(f"  [{seed_name}] closure size={len(closure)}")
    # short-name -> (label, line) — L2-agnostic raw-node identity
    probes = {
        "bdm@16": ("bdm_acc_loan_info", 16), "rollover@9": ("rollover_loan_info", 9),
        "loan_final@64": ("loan_final", 64), "output@0": ("⟐ output", 0),
        "sup@160": ("bdm_acc_loan_info_sup", 160), "sup@223": ("bdm_acc_loan_info_sup", 223),
        "data_dt@225": ("data_dt", 225), "rrcdm@211": ("rrcdm_job_log_exec_par", 211),
        "data_dt@202": ("p2.data_dt", 202), "p2@199": ("p2", 199),
        "data_dt@160": ("data_dt", 160), "data_dt@213": ("data_dt", 213),
    }
    for pname, (plabel, pline) in probes.items():
        hits = [nid for nid, d in nodes.items()
                if d.get("label") == plabel
                and str(d.get("line_start")) == str(pline)]
        if not hits:
            print(f"      {pname}: NODE NOT FOUND")
            continue
        for h in hits:
            print(f"      {pname} ctx={nodes[h].get('context')}: INCLOSURE={h in closure}")

for seed_name, tbl in (("bdm", "bdm_acc_loan_info"), ("sup", "bdm_acc_loan_info_sup")):
    print(f"\n=== L2 [{seed_name}] edges with hl in 160/211/223 ===")
    l2 = _build_l2_graph("probe-issue23-" + seed_name, SQL_NAME, sql, tbl, "data_dt")
    gn = {n["data"]["id"]: n["data"] for n in l2["nodes"]}
    for e in l2["edges"]:
        ed = e["data"]
        hl = ed.get("highlight_line")
        if hl not in (160, 211, 223):
            continue
        s, t = gn.get(ed["source"], {}).get("label", "?"), gn.get(ed["target"], {}).get("label", "?")
        print(f"  {ed['id']:<42} {s:<28} -> {t:<28} type={ed.get('edge_type'):<12} "
              f"hl={hl} kind={ed.get('flow_kind'):<8} dml={ed.get('_dml_origin')} op={ed.get('operation')}")
    print(f"  L2 nodes={len(l2['nodes'])} edges={len(l2['edges'])}")
