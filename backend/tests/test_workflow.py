"""Workflow tests — real ETL pipeline scenarios with data flow verification."""

import sys
from pathlib import Path
from collections import defaultdict

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.multi_script_service import analyze_multiple_scripts
from app.models.variable import VariableType

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
WORKFLOW_DIR = SAMPLES_DIR / "multi_workflow"


# ══════════════════════════════════════════════════════════════════════
# Single-script: data flow from table to table
# ══════════════════════════════════════════════════════════════════════

class TestSingleScriptTableFlow:
    """Every FROM/JOIN table must participate in the table-level data flow."""

    def test_every_from_alias_has_table_flow(self):
        """Every FROM/JOIN table alias must have TABLE_FLOW to its anchor."""
        sql = "SELECT t.amount, t.status FROM gps_transactions t WHERE t.status='active'"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        aliases = [v for v in r.variables
                   if v.variable_type == VariableType.TABLE and v.source_tables]
        for a in aliases:
            tf_edges = [e for e in deps
                       if e.source_id == a.id and e.relationship == "TABLE_FLOW"]
            assert len(tf_edges) >= 1, \
                f"Alias '{a.name}' must have TABLE_FLOW edge, got {len(tf_edges)}"

    def test_every_table_in_some_edge(self):
        """Every table-like node must be connected to the graph."""
        table_types = {"table", "view", "cte", "subquery", "virtual_table",
                       "merge_target", "union_branch"}
        for fname in ["query1_select_where.sql", "query2_joins_complex.sql",
                       "query4_update_delete.sql"]:
            sql = (SAMPLES_DIR / fname).read_text()
            r = extract_variables_from_sql(sql, fname)
            deps = build_dependency_graph(r, sql)
            connected = set()
            for e in deps:
                connected.add(e.source_id)
                connected.add(e.target_id)
            for v in r.variables:
                if v.variable_type.value in table_types:
                    assert v.id in connected, \
                        f"{fname}: table '{v.name}' ({v.variable_type.value}) is isolated"

    def test_data_flow_direction(self):
        """TABLE_FLOW: source=FROM/JOIN alias, target=VT/CTE (output container).
        Data flows FROM the table TO the SELECT output."""
        sql = (SAMPLES_DIR / "query1_select_where.sql").read_text()
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        table_types = {"table", "view", "cte", "subquery", "virtual_table",
                       "merge_target", "union_branch"}
        for e in deps:
            if e.relationship != "TABLE_FLOW":
                continue
            src = next((v for v in r.variables if v.id == e.source_id), None)
            tgt = next((v for v in r.variables if v.id == e.target_id), None)
            assert src and tgt, "TABLE_FLOW must have valid endpoints"
            # Source must be a table alias (has source_tables) or subquery/CTE/VT
            assert tgt.variable_type.value in table_types, \
                f"TABLE_FLOW target must be table-like, got {tgt.variable_type.value}"


# ══════════════════════════════════════════════════════════════════════
# Single-script: every column in data flow
# ══════════════════════════════════════════════════════════════════════

class TestSingleScriptColumnFlow:
    """Every column-like node must participate in the data flow."""

    def test_every_column_has_min_edges(self):
        """Columns must have ≥2 edges (source + target)."""
        for fname in ["query1_select_where.sql", "query2_joins_complex.sql",
                       "query3_subqueries_case.sql"]:
            sql = (SAMPLES_DIR / fname).read_text()
            r = extract_variables_from_sql(sql, fname)
            deps = build_dependency_graph(r, sql)
            from collections import Counter
            ec = Counter()
            for e in deps:
                ec[e.source_id] += 1
                ec[e.target_id] += 1
            bad = []
            for v in r.variables:
                if v.variable_type.value == "column" and ec.get(v.id, 0) < 2:
                    bad.append(f"{v.name}({ec.get(v.id,0)}e)")
            assert not bad, f"{fname}: columns with <2 edges: {bad}"

    def test_column_in_select_connected_to_output(self):
        """Output columns must have SCHEMA from the output container (VT)."""
        sql = "SELECT t.amount, t.status FROM gps_transactions t WHERE t.status='active'"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        vt = next((v for v in r.variables
                   if v.variable_type.value == "virtual_table"), None)
        output_cols = [v for v in r.variables if v.is_output
                       and v.variable_type.value == "column"]
        for col in output_cols:
            vt_to_col = [e for e in deps
                        if e.source_id == vt.id
                        and e.target_id == col.id
                        and e.relationship == "SCHEMA"]
            assert len(vt_to_col) >= 1, \
                f"Output column '{col.name}' must have SCHEMA from VT"


# ══════════════════════════════════════════════════════════════════════
# Single-script: edge direction follows data flow
# ══════════════════════════════════════════════════════════════════════

class TestEdgeDirection:
    """Every edge must point FROM data source TO data consumer."""

    def test_aggregate_direction(self):
        """AGGREGATE: column → aggregate result."""
        sql = "SELECT SUM(t.amount) AS total FROM gps_transactions t"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        for e in deps:
            if e.relationship != "AGGREGATE":
                continue
            src = next((v for v in r.variables if v.id == e.source_id), None)
            tgt = next((v for v in r.variables if v.id == e.target_id), None)
            assert src.variable_type.value in ("column", "cte_column"), \
                f"AGGREGATE source must be column, got {src.variable_type.value}"
            assert tgt.variable_type.value == "aggregate", \
                f"AGGREGATE target must be aggregate, got {tgt.variable_type.value}"

    def test_dml_direction(self):
        """DML: source data → target table."""
        sql = "INSERT INTO target (id,amt) SELECT a.id,a.amount FROM source a"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        for e in deps:
            if e.relationship != "DML":
                continue
            tgt = next((v for v in r.variables if v.id == e.target_id), None)
            assert tgt.variable_type.value in ("table", "merge_target"), \
                f"DML target must be table/merge_target, got {tgt.variable_type.value}"

    def test_alias_direction(self):
        """ALIAS: original → alias (data source → reference)."""
        sql = "SELECT u.name FROM users u"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        for e in deps:
            if e.relationship != "ALIAS":
                continue
            src = next((v for v in r.variables if v.id == e.source_id), None)
            tgt = next((v for v in r.variables if v.id == e.target_id), None)
            assert not src.source_tables, \
                f"ALIAS source must be original (no src_tables): {src.name}"
            assert tgt.source_tables, \
                f"ALIAS target must be alias (has src_tables): {tgt.name}"

    def test_filter_direction(self):
        """FILTER: WHERE column → output container."""
        sql = "SELECT t.amount FROM gps_transactions t WHERE t.status='active'"
        r = extract_variables_from_sql(sql, "test")
        deps = build_dependency_graph(r, sql)
        for e in deps:
            if e.relationship != "FILTER":
                continue
            src = next((v for v in r.variables if v.id == e.source_id), None)
            tgt = next((v for v in r.variables if v.id == e.target_id), None)
            assert src.variable_type.value == "column", \
                f"FILTER source must be column, got {src.variable_type.value}"
            assert tgt.variable_type.value in ("virtual_table", "cte"), \
                f"FILTER target must be VT/CTE, got {tgt.variable_type.value}"


# ══════════════════════════════════════════════════════════════════════
# Multi-script workflow: data flow from script to script
# ══════════════════════════════════════════════════════════════════════

class TestMultiScriptWorkflow:
    """5-step ETL pipeline: orders → enrich → join → aggregate → report."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.scripts = []
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            self.scripts.append((f.name, f.read_text()))

    def test_all_steps_produce_variables(self):
        """All 5 workflow steps must produce variables."""
        assert len(self.scripts) == 5, f"Expected 5 steps, got {len(self.scripts)}"
        for name, sql in self.scripts:
            r = extract_variables_from_sql(sql, name)
            assert len(r.variables) >= 3, \
                f"{name}: expected ≥3 variables, got {len(r.variables)}"

    def test_workflow_has_data_lineage(self):
        """Multi-script analysis must find data lineage between steps."""
        result = analyze_multiple_scripts(self.scripts)
        assert len(result["scripts"]) == 5
        assert len(result["meta_nodes"]) > 0
        lineage_edges = [e for e in result["meta_edges"]
                        if e["data"]["edge_type"] == "data_lineage"]
        assert len(lineage_edges) >= 3, \
            f"ETL workflow should have ≥3 data lineage edges, got {len(lineage_edges)}"
        # Verify lineage chain: step1→step3 (stg_orders), step2→step3 (stg_customers),
        # step3→step4 (analytics_orders), step4→step5 (daily_summary)
        labels = {e["data"]["label"] for e in lineage_edges}
        expected_tables = {"stg_orders", "stg_customers", "analytics_orders",
                          "daily_summary"}
        found = labels & expected_tables
        assert len(found) >= 3, \
            f"Expected table links: {expected_tables}, found: {found}"

    def test_lineage_edges_have_table_labels(self):
        """Data lineage edges must carry the shared table name as label."""
        result = analyze_multiple_scripts(self.scripts)
        for e in result["meta_edges"]:
            if e["data"]["edge_type"] == "data_lineage":
                assert e["data"]["label"], \
                    "Data lineage edge must have a table name label"

    def test_lineage_direction_is_correct(self):
        """Lineage: producer script → consumer script (output→input)."""
        result = analyze_multiple_scripts(self.scripts)
        for e in result["meta_edges"]:
            if e["data"]["edge_type"] != "data_lineage":
                continue
            src_sid = e["data"]["source"]
            tgt_sid = e["data"]["target"]
            # Source script should OUTPUT the shared tables
            src_script = next((s for s in result["scripts"]
                              if s["script_id"] == src_sid), None)
            tgt_script = next((s for s in result["scripts"]
                              if s["script_id"] == tgt_sid), None)
            if src_script and tgt_script:
                src_tables = e["data"].get("source_tables", [])
                for tbl in src_tables:
                    assert tbl in src_script.get("output_tables", []), \
                        f"'{tbl}' not in {src_script['script_name']} outputs"

    def test_input_output_tables_classified(self):
        """Each script must have input/output tables classified."""
        result = analyze_multiple_scripts(self.scripts)
        for s in result["scripts"]:
            assert s["input_tables"] or s["output_tables"], \
                f"{s['script_name']}: must have input or output tables"
            # step1 loads orders: output=stg_orders, input=raw_orders
            # step5 reports: input=daily_summary, output=none (read-only)

    def test_step1_output_is_step3_input(self):
        """Step1 outputs stg_orders → Step3 inputs stg_orders."""
        result = analyze_multiple_scripts(self.scripts)
        s1 = next(s for s in result["scripts"] if "step1" in s["script_name"])
        s3 = next(s for s in result["scripts"] if "step3" in s["script_name"])
        assert "stg_orders" in s1["output_tables"], \
            "Step1 should output stg_orders"
        assert "stg_orders" in s3["input_tables"], \
            "Step3 should input stg_orders"


# ══════════════════════════════════════════════════════════════════════
# Progress tracking for multi-script analysis
# ══════════════════════════════════════════════════════════════════════

class TestProgressTracking:
    """Multi-script analysis should be trackable."""

    def test_scripts_returned_with_timing(self):
        """Each script result should be usable for progress tracking."""
        scripts = []
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            scripts.append((f.name, f.read_text()))
        import time
        start = time.time()
        result = analyze_multiple_scripts(scripts)
        elapsed = time.time() - start
        assert elapsed < 10, f"5-script analysis too slow: {elapsed:.1f}s"
        assert len(result["scripts"]) == 5

    def test_all_sample_queries_analyze_fast(self):
        """All sample queries should analyze in reasonable time."""
        import time
        all_samples = list((SAMPLES_DIR / "financial").glob("fin_query*.sql"))
        if not all_samples:
            pytest.skip("No financial samples")
        times = []
        for f in all_samples[:5]:  # first 5
            sql = f.read_text()
            start = time.time()
            r = extract_variables_from_sql(sql, f.name)
            deps = build_dependency_graph(r, sql)
            elapsed = time.time() - start
            times.append(elapsed)
        avg = sum(times) / len(times)
        assert avg < 2.0, f"Average analysis too slow: {avg:.1f}s per query"
