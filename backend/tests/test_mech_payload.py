"""R11-2 / R11-3 / N8 — code-evidence mech payload + DML phantom dedup.

R11-2 (2026-08-10): the Sync-2 DML phantom exists-check dedups by
(target, label) only — the old orig_stmt term let the same (parent,
label) pair exist twice on a DML target (rrcdm_job_log_exec_par's
duplicate data_dt from the '$(load_date)' AS data_dt value line in both
the bdm and sup seeds).

R11-3 (2026-08-10, formal spec): per-edge `mech` payload — the reference
site where the source is consumed inside the dst compound's def range
(clause/ref_line/alias/use_lines/sentence), all extraction-time facts
(I1 def lines, I2 source_tables, defined_in). The invariant test pins
the flagship rollover_loan_info → loan_final chain edge: ref_line==155
(L155 LEFT JOIN), clause=="JOIN", alias=="p6".

N8 (2026-08-10): statement-level parse diagnostics ride run_full_analysis
as `parse_errors` (list of dicts; empty when the script parsed cleanly).
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.l2_builder import _build_l2_graph

SQL_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
SQL_PATH = (Path(__file__).resolve().parent.parent.parent
           / "samples" / "sql_sample_v1" / SQL_NAME)
SEED_TABLE = {"bdm": "bdm_acc_loan_info", "sup": "bdm_acc_loan_info_sup"}
TARGET_FIELD = "data_dt"


def _l2(seed: str):
    """Filtered L2 graph for the flagship script (the served path: the
    strict table.field flow filter, bench ws like the Jaccard harness)."""
    sql = SQL_PATH.read_text(encoding="utf-8")
    result = extract_variables_from_sql(sql, SQL_NAME)
    build_dependency_graph(result, sql)
    return _build_l2_graph("bench", SQL_NAME, sql, SEED_TABLE[seed],
                           TARGET_FIELD)


def _compound_nodes(graph):
    return [n["data"] for n in graph["nodes"]
            if n["data"].get("type") in
            ("source_table", "intermediate_table", "output_table",
             "cte_table")]


class TestR11_2DmlPhantomDedup:
    """One DML target gets ONE field per label — no (parent, label)
    duplicates among the dml_ phantom copies (both seeds)."""

    def test_rrcdm_has_single_data_dt_child(self):
        for seed in SEED_TABLE:
            graph = _l2(seed)
            rrcdm = next(t for t in _compound_nodes(graph)
                         if t["table_name"] == "rrcdm_job_log_exec_par")
            children = [n for n in graph["nodes"]
                        if n["data"].get("parent") == rrcdm["id"]]
            data_dt_children = [n["data"] for n in children
                                if n["data"].get("label") == "data_dt"]
            assert len(data_dt_children) == 1, \
                f"seed {seed}: rrcdm must have ONE data_dt child, " \
                f"got {len(data_dt_children)}: " \
                f"{[c['id'] for c in data_dt_children]}"

    def test_no_duplicate_parent_label_pairs(self):
        """Stronger: no (parent, label) pair repeats among the dml_
        phantom fields in either seed."""
        for seed in SEED_TABLE:
            graph = _l2(seed)
            seen = set()
            for n in graph["nodes"]:
                d = n["data"]
                if not d.get("id", "").startswith("dml_"):
                    continue
                key = (d.get("parent"), d.get("label"))
                assert key not in seen, \
                    f"seed {seed}: duplicate phantom pair {key}"
                seen.add(key)


class TestR11_3MechPayload:
    """The code-evidence mech payload rides the per-edge R25 payload."""

    def test_chain_edge_mech_invariant(self):
        """bdm rollover_loan_info → loan_final chain edge carries
        mech {clause: 'JOIN', ref_line: 155, alias: 'p6'} — the formal
        spec's ground-truth invariant (L155 LEFT JOIN rollover_loan_info
        p6 inside loan_final's def range L64..159)."""
        graph = _l2("bdm")
        chain = [e["data"] for e in graph["edges"]
                 if e["data"].get("edge_type") == "TABLE_FLOW"]
        nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
        rolls = [e for e in chain
                 if nodes.get(e.get("source"), {}).get("table_name")
                 == "rollover_loan_info"
                 and nodes.get(e.get("target"), {}).get("table_name")
                 == "loan_final"]
        assert rolls, "the rollover_loan_info → loan_final chain edge must exist"
        e = rolls[0]
        mech = e.get("mech")
        assert mech is not None, f"chain edge must carry mech, got {e}"
        assert mech["clause"] == "JOIN", mech
        assert mech["ref_line"] == 155, mech
        assert mech["alias"] == "p6", mech
        assert 82 in mech.get("use_lines", []), mech
        assert "LEFT JOIN at L155" in mech["sentence"], mech

    def test_compound_nodes_carry_lines(self):
        """R11-3 NEW DATA (1): compound nodes carry line_start/line_end/
        defined_in — loan_final's span is L64..159 (next stmt anchor 160
        − 1), the sup write is L160..210."""
        graph = _l2("bdm")
        tables = {t["table_name"]: t for t in _compound_nodes(graph)}
        lf = tables["loan_final"]
        assert lf.get("line_start") == 64, lf
        assert lf.get("line_end") == 159, lf
        assert lf.get("defined_in") == "CTE{loan_final}", lf
        sup = tables["bdm_acc_loan_info_sup"]
        assert sup.get("line_start") == 160, sup
        assert sup.get("line_end") == 210, sup
        assert sup.get("defined_in") == "INSERT", sup

    def test_mech_absent_edges_still_carry_r25_payload(self):
        """Every edge keeps the R25 payload (highlight_line/flow_kind/
        reason) whether or not a mech resolves; mech presence is additive."""
        graph = _l2("bdm")
        for e in graph["edges"]:
            d = e["data"]
            assert d.get("highlight_line", 0) >= 1, d
            assert d.get("flow_kind"), d
            assert d.get("reason"), d
            mech = d.get("mech")
            if mech is not None:
                assert mech.get("ref_line", 0) >= 1, mech
                assert mech.get("sentence"), mech


class TestN8ParseErrors:
    """N8: statement-level parse diagnostics ride the analysis result."""

    def test_well_formed_script_empty_parse_errors(self):
        from app.extractor.adapter import run_full_analysis
        result = run_full_analysis("SELECT 1;", "ok.sql")
        assert result["parse_errors"] == [], result["parse_errors"]

    def test_broken_statement_records_parse_error(self):
        from app.extractor.adapter import run_full_analysis
        # ');' leaves a hole in sqlglot's statement list (ErrorLevel.IGNORE)
        # — the extractor records it as a statement-level diagnostic.
        result = run_full_analysis("SELECT 1;\n);\n", "broken.sql")
        assert result["parse_errors"], result["parse_errors"]
        assert all(isinstance(e, dict) and "stmt_idx" in e
                   for e in result["parse_errors"]), result["parse_errors"]
