"""LIVE CHECK (ephemeral) for jaccard_canonical.py -- post-fix match report.

Builds the CURRENT (post-walker-gating-fix) filtered L2 graphs with the
benchmark pipeline (extract_variables_from_sql + build_dependency_graph +
_build_l2_graph("bench", ...)), runs the four spec rules from the module,
and reports which canonical row-entries are matched / UNMATCHED and which
canonical nodes are / are NOT realized. This is the doc-repair backlog --
NOT a baseline-reproduction assertion (the baseline was measured pre-fix).
"""
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend/tests")
sys.path.insert(0, "/app/backend")
from jaccard_canonical import (  # noqa: E402
    CANONICAL_EDGES, CANONICAL_NODES, NORMALIZE_MAP, BASELINE_JACCARD,
)
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402
from app.services.l2_builder import _build_l2_graph  # noqa: E402

SCRIPT = "BDM_ACC_LOAN_INFO_SUP_M.sql"
SQL_PATH = "/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql"
SEED_TABLE = {"bdm": "bdm_acc_loan_info", "sup": "bdm_acc_loan_info_sup"}

sql_text = open(SQL_PATH, encoding="utf-8").read()
result = extract_variables_from_sql(sql_text, SCRIPT)
build_dependency_graph(result, sql_text)


def build(seed):
    l2 = _build_l2_graph("bench", SCRIPT, sql_text, SEED_TABLE[seed], "data_dt")
    g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
    nodes = {n["data"]["id"]: n["data"] for n in g["nodes"]}
    edges = [e["data"] for e in g["edges"]]
    return nodes, edges


def norm(label):
    return NORMALIZE_MAP.get(label, label)


def split_ep(ep):
    label, _, line = ep.rpartition("@")
    return label, (int(line) if line else None)


def endpoint_ok(ep, node_id, nodes, inc):
    c_label, c_line = split_ep(ep)
    if norm(c_label) != norm(nodes[node_id]["label"]):
        return False
    if c_line is None or c_line == 0:
        return True
    return c_line in inc[node_id]


def match_seed(seed):
    nodes, edges = build(seed)
    inc = defaultdict(set)
    for e in edges:
        inc[e["source"]].add(e["highlight_line"])
        inc[e["target"]].add(e["highlight_line"])
    used = set()
    matched = {}

    def candidates(anchor, prefix):
        out = [e for e in edges
               if e["highlight_line"] == anchor and e["edge_type"].startswith(prefix)]
        out.sort(key=lambda e: e["id"])
        return out

    for entry in CANONICAL_EDGES:
        if entry["seed"] != seed:
            continue
        anchor, typ, spec = entry["anchor"], entry["type"], entry["spec"]
        hit = None
        if spec == "anchor_rel":
            for e in candidates(anchor, typ):
                if e["id"] not in used:
                    hit = e
                    break
        elif spec == "anchor_rel_ep":
            for e in candidates(anchor, typ):
                if e["id"] in used:
                    continue
                if (endpoint_ok(entry["src"], e["source"], nodes, inc)
                        and endpoint_ok(entry["dst"], e["target"], nodes, inc)):
                    hit = e
                    break
        elif spec == "two_hop":
            has_alias = any(e["highlight_line"] == anchor
                            and e["edge_type"].startswith("ALIAS") for e in edges)
            for e in candidates(anchor, "TABLE_FLOW"):
                if e["id"] not in used:
                    hit = e
                    break
            if not has_alias:
                hit = None
        elif spec == "ref_alias":
            for e in candidates(anchor, "REF"):
                if e["id"] not in used:
                    hit = e
                    break
        if hit is not None:
            used.add(hit["id"])
            matched[entry["row"]] = hit["id"]
    return nodes, edges, matched


def node_realized(c_label, c_line, nodes, inc):
    for nid, nd in nodes.items():
        if norm(nd["label"]) != norm(c_label):
            continue
        if c_line is None or c_line == 0:
            return True
        if c_line in inc[nid]:
            return True
    return False


def run(seed):
    nodes, edges, matched = match_seed(seed)
    inc = defaultdict(set)
    for e in edges:
        inc[e["source"]].add(e["highlight_line"])
        inc[e["target"]].add(e["highlight_line"])
    rows = [e for e in CANONICAL_EDGES if e["seed"] == seed]
    canon_nodes = CANONICAL_NODES[seed]
    unrealized = [(c["label"], c["line"]) for c in canon_nodes
                  if not node_realized(c["label"], c["line"], nodes, inc)]
    b_hl = sorted({e["anchor"] for e in rows})
    a_hl = sorted({e["highlight_line"] for e in edges if e["highlight_line"] >= 1})
    table = {
        "nodes": (len(nodes), len(canon_nodes),
                  sum(1 for c in canon_nodes
                      if node_realized(c["label"], c["line"], nodes, inc))),
        "edges": (len(edges), len(rows), len(matched)),
        "highlights": (len(a_hl), len(b_hl), len(set(a_hl) & set(b_hl))),
    }
    return table, matched, rows, unrealized


def main():
    print("MODULE WRITTEN -- jaccard_canonical.py (38 CANONICAL_EDGES entries: "
          "24 bdm + 14 sup after the 2026-08-10 DML-routing repair, row-11 "
          "removal and X1-X5 canonization; CANONICAL_NODES 16+9; "
          "NORMALIZE_MAP 13 entries)")
    print("BASELINE_JACCARD (pre-fix date-stamp 2026-08-10):")
    for seed in ("bdm", "sup"):
        print(f"  {seed}: {BASELINE_JACCARD[seed]}")
    for seed in ("bdm", "sup"):
        table, matched, rows, unrealized = run(seed)
        print(f"\n==== LIVE POST-FIX CHECK — seed {seed} ====")
        print(f"{'metric':<11}{'|A|':>6}{'|B|':>6}{'A∩B':>6}{'A∪B':>7}{'Jaccard':>9}")
        for m in ("nodes", "edges", "highlights"):
            a, b, i = table[m]
            print(f"{m:<11}{a:>6}{b:>6}{i:>6}{a+b-i:>7}{i/(a+b-i):>9.4f}")
        rows_seed = [r for r in rows if r["seed"] == seed]
        unmatched = [r for r in rows_seed if r["row"] not in matched]
        print(f"matched rows ({len(matched)}): "
              f"{sorted(matched.keys(), key=str)}")
        print(f"UNMATCHED rows ({len(unmatched)}):")
        for r in unmatched:
            print(f"  row={r['row']} seed={r['seed']} anchor={r['anchor']} "
                  f"rel={r['type']}  src={r['src']} -> dst={r['dst']}")
        if unrealized:
            print(f"canonical nodes NOT realized ({len(unrealized)}):")
            for label, line in unrealized:
                print(f"  label={label} line={line}")
        else:
            print("canonical nodes NOT realized: none -- all realized")


if __name__ == "__main__":
    main()
