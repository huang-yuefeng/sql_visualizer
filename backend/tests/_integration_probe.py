"""Integration probe — full served-L2 dump for the re-pin round (J12-13).

Run: docker exec -w /app/backend gps-sql-backend python3 tests/_integration_probe.py
Fresh ws ids per seed (graph-cache bypass). Dumps every served L2 edge with
its full evidence so the canonical fixture can be re-pinned row by row.
"""
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # /app/backend
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import build_graph_data
from app.services.l2_builder import _build_l2_graph

SQL_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
sql = open("/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql",
           encoding="utf-8").read()

for seed_name, tbl in (("bdm", "bdm_acc_loan_info"), ("sup", "bdm_acc_loan_info_sup")):
    ws = f"int-{seed_name}-{uuid.uuid4().hex[:8]}"
    l2 = _build_l2_graph(ws, SQL_NAME, sql, tbl, "data_dt")
    gn = {n["data"]["id"]: n["data"] for n in l2["nodes"]}
    print(f"\n═══════ L2 [{seed_name}] nodes={len(l2['nodes'])} edges={len(l2['edges'])} ═══════")
    print(f"{'id':<42}{'src':<26}{'dst':<26}{'type':<12}{'hl':>4}  {'kind':<10}{'dml':<6}{'op'}")
    for e in sorted(l2["edges"], key=lambda x: (x["data"].get("highlight_line") or 0,
                                                x["data"]["id"])):
        ed = e["data"]
        s = gn.get(ed["source"], {}).get("label", "?")
        t = gn.get(ed["target"], {}).get("label", "?")
        print(f"{ed['id']:<42}{s:<26}{t:<26}{ed.get('edge_type'):<12}"
              f"{ed.get('highlight_line', 0):>4}  {str(ed.get('flow_kind')):<10}"
              f"{str(ed.get('_dml_origin')):<6}{ed.get('operation')}")
    print(f"\n  L2 nodes:")
    for n in sorted(l2["nodes"], key=lambda x: (x["data"].get("line_start") or 0,
                                                x["data"]["label"])):
        nd = n["data"]
        print(f"    {nd.get('label'):<30} line={nd.get('line_start')} ctx={nd.get('context')} "
              f"type={nd.get('variable_type')}")
