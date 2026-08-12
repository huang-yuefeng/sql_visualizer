"""Test dataflow search and graph building."""
import asyncio
import io
import zipfile

import pytest


class TestSearch:
    def test_search_finds_scripts(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "staging_orders", "amount")
        assert "view_id" in result
        assert len(result["script_ids"]) > 0
        workspace_client.delete(ws_id)

    def test_l1_graph_has_nodes(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "staging_orders", "amount")
        nodes = result["l1_graph"].get("nodes", [])
        assert len(nodes) > 0
        workspace_client.delete(ws_id)

    def test_l1_graph_node_type(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "staging_orders", "amount")
        nodes = result["l1_graph"].get("nodes", [])
        valid_types = {"script_node", "source_table", "intermediate_table", "output_table", "field", "query_output", "cte_table"}
        found_script = False
        for n in nodes:
            nd = n.get("data", n)
            assert nd.get("type") in valid_types, f"Unexpected type: {nd.get('type')}"
            if nd.get("type") == "script_node":
                found_script = True
        assert found_script, "L1 graph must contain at least one script_node"
        workspace_client.delete(ws_id)

    def test_search_no_match_returns_no_matches(self, workspace_client, d1_zip):
        """BE2: replaces the old fallback behavior. A field that no script
        queries has no data flow — the result is a banner-compatible
        no_matches (match_mode + message + empty L1 graph), NOT a padded
        list of scripts that merely reference the table."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "nonexistent", "nonexistent")
        assert "view_id" in result
        assert result["match_mode"] == "no_matches", result
        assert result["script_ids"] == [], result
        assert result["l1_graph"]["nodes"] == [], result
        assert result["l1_graph"]["edges"] == [], result
        assert "not queried by any script" in result["message"], result
        assert result["match_mode"] != "fallback", result
        workspace_client.delete(ws_id)

    def test_search_absent_field_no_fallback_padding(self, workspace_client, d1_zip):
        """BE2 (user issue): searching an INDEXED table with a field that no
        script queries must NOT pad in all table-referencing scripts. The
        field has no data flow, so the result is no_matches with an empty L1
        — L1 stays simple instead of showing every table's scripts."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "orders", "ghost_field")
        assert result["match_mode"] == "no_matches", result
        assert result["script_ids"] == [], result
        assert result["l1_graph"]["nodes"] == [], result
        assert "orders.ghost_field" in result["message"], result
        workspace_client.delete(ws_id)

    def test_search_field_not_under_table_returns_no_matches(self, workspace_client, d1_zip):
        """BE2: the field exists in the index (referenced under another
        table) but no script references it together with the searched table
        — the table.field pair has no data flow."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "nonexistent_table", "amount")
        assert result["match_mode"] == "no_matches", result
        assert result["script_ids"] == [], result
        assert "nonexistent_table.amount" in result["message"], result
        workspace_client.delete(ws_id)

    def test_search_field_in_one_script_matches_that_script_only(self, workspace_client):
        """BE2: a field queried by exactly one script matches that script
        only — no fallback padding of table-referencing scripts."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("flow_a.sql",
                        "CREATE TABLE t1 (id BIGINT, val DECIMAL(10,2));\n"
                        "INSERT INTO t2 (id, val) SELECT id, val FROM t1;\n")
            zf.writestr("flow_b.sql",
                        "CREATE TABLE t3 (id BIGINT);\n"
                        "INSERT INTO t4 (id) SELECT id FROM t3;\n")
        ws_id = workspace_client.create(buf.getvalue())
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "t1", "val")
        assert result["match_mode"] == "exact", result
        assert result["script_ids"] == ["flow_a.sql"], result
        workspace_client.delete(ws_id)


class TestLevel2Graph:
    def test_l2_graph_returns_data(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "step2_report.sql", "orders", "amount")
        assert "graph" in result
        assert "nodes" in result["graph"]
        workspace_client.delete(ws_id)

    def test_l2_graph_highlights(self, workspace_client, d1_zip):
        """W5/R25: the response-level `highlights` list is GONE — every L2
        edge carries its own payload (highlight_line / flow_kind / reason),
        and the level2 response adds statement-level parse_errors."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "step2_report.sql", "orders", "amount")
        assert "highlights" not in result, result
        assert isinstance(result.get("parse_errors"), list), result
        for e in result["graph"]["edges"]:
            d = e["data"]
            assert d.get("highlight_line", 0) >= 1, d
            assert d.get("flow_kind"), d
            assert d.get("reason"), d
        workspace_client.delete(ws_id)


class TestRelevanceFilter:
    def test_filter_reduces_nodes(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        from app.services.dataflow_service import filter_relevant
        import json
        from pathlib import Path
        cache_dir = Path("/tmp/workspaces") / ws_id / "cache"
        # Build graph from analysis
        from app.services.graph_service import build_graph_data
        analysis_files = list(cache_dir.glob("analysis_*.json"))
        if not analysis_files:
            pytest.skip("No analysis cache files found")
        analysis_path = analysis_files[0]
        analysis = json.loads(analysis_path.read_text())
        graph_data = build_graph_data(analysis)
        total = len(graph_data.get("nodes", []))
        if total == 0:
            pytest.skip("No nodes in graph — empty analysis")
        filtered = filter_relevant(graph_data, "orders", "amount")
        filtered_count = len(filtered.get("nodes", []))
        assert filtered_count <= total
        workspace_client.delete(ws_id)


def test_l1_no_direct_script_to_script_edges(workspace_client, d2_zip):
    """L1 invariant: scripts connect through table variables, never directly.

    NOTE (R29, 2026-08-12): the seed is `staging_orders.amount` — a real
    d2 table.field with a cross-script flow. The old "crm_customers"/
    "customer_id" seed referenced a table that does not exist in d2: the
    superseded table-level fallback showed the whole pipeline regardless
    of the seed, while the R29 directional projection correctly yields
    the empty no-flow state for it."""
    from app.services.dataflow_service import _build_l1_graph

    ws_id = workspace_client.create(d2_zip)
    workspace_client.index(ws_id)

    scripts = ["step1_load_orders.sql", "step2_enrich_customers.sql",
               "step3_join_orders_customers.sql", "step4_aggregate_daily.sql",
               "step5_final_report.sql"]

    result = _build_l1_graph(ws_id, scripts, "staging_orders", "amount")
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    
    # Build node type lookup
    type_map = {}
    for n in nodes:
        nd = n.get("data", n)
        type_map[nd.get("id", "")] = nd.get("type", "")
    
    # No edge may connect script_node → script_node
    for e in edges:
        ed = e.get("data", e)
        src_t = type_map.get(ed.get("source", ""), "")
        tgt_t = type_map.get(ed.get("target", ""), "")
        assert not (src_t == "script_node" and tgt_t == "script_node"), (
            f"Script→Script edge: {ed.get('source')}→{ed.get('target')}"
        )
    
    assert len(edges) > 0, "Expected non-empty edges"
    workspace_client.delete(ws_id)


class TestL2NotInFlow:
    """BE2 (issue b): L2 for a script that is NOT in the searched field's
    data flow must not show a fake filtered skeleton — the response carries
    search_matched:false + a message and renders the full script graph.

    The `search_matched` flag itself is emitted by _build_l2_graph (BE1's
    contract: False ONLY when filtering was requested and no target/direct
    seed matched). BE1 owns l2_builder.py; these tests simulate the contract
    with a wrapper so the response handling here is verified independently.
    """

    @staticmethod
    def _wrap_search_matched(monkeypatch, dfs):
        """Wrap _build_l2_graph to inject search_matched=False (BE1 contract)
        when the searched field's text is absent from the script."""
        real_build = dfs._build_l2_graph

        def wrapped(ws_id_, script_name, sql_text, table, field,
                    relevance_filter=True, direction="downstream"):
            res = real_build(ws_id_, script_name, sql_text, table, field,
                             relevance_filter, direction)
            if relevance_filter and res.get("error") is None and field not in sql_text:
                res = dict(res)
                res["search_matched"] = False  # simulate BE1's contract
            return res

        monkeypatch.setattr(dfs, "_build_l2_graph", wrapped)

    def test_l2_not_in_flow_search_matched_false_full_graph(self, workspace_client, d1_zip, monkeypatch):
        """L2 with a search view whose field is absent from the script →
        search_matched:false + message + the FULL graph (node count greater
        than the filtered skeleton), not the misleading table-only skeleton."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        import app.services.dataflow_service as dfs
        self._wrap_search_matched(monkeypatch, dfs)

        # "ghost" appears in no script — the script is not in its data flow
        result = dfs.get_level2_graph(ws_id, sr["view_id"], "step2_report.sql",
                                      "orders", "ghost")
        assert result.get("search_matched") is False, result
        assert "ghost" in result.get("message", ""), result
        assert "not in the data flow" in result.get("message", ""), result
        assert "full script graph" in result.get("message", ""), result
        # Full graph — not the skeleton (which is table-only / few nodes)
        assert len(result["graph"]["nodes"]) > 1, result
        assert len(result["graph"]["edges"]) > 0, result
        # Identical to an explicit unfiltered build
        full = dfs.get_level2_graph(ws_id, sr["view_id"], "step2_report.sql",
                                    "orders", "ghost", filter_relevant_nodes=False)
        assert len(result["graph"]["nodes"]) == len(full["graph"]["nodes"]), result
        workspace_client.delete(ws_id)

    def test_l2_natural_not_in_flow_script(self, workspace_client, d2_zip):
        """End-to-end with _build_l2_graph's real search_matched flag (BE1
        contract): a script outside the searched field's directional flow
        carries search_matched:false + message + a usable graph.

        NOTE (R29, 2026-08-12): field queries are now EXACT — the
        directional field-flow search (API team's R29 contract) skips the
        old table-closure expansion, so customers.customer_name matches
        step2_enrich_customers.sql only; step4_aggregate.sql is outside
        the flow and its L2 still renders the full script graph."""
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "customers", "customer_name")
        assert sr["match_mode"] == "exact", sr
        assert sr["script_ids"] == ["step2_enrich_customers.sql"], sr
        from app.services.dataflow_service import get_level2_graph
        # step4_aggregate.sql never references customer_name
        result = get_level2_graph(ws_id, sr["view_id"], "step4_aggregate.sql",
                                  "customers", "customer_name")
        assert result.get("search_matched") is False, result
        assert "customer_name" in result.get("message", ""), result
        assert len(result["graph"]["nodes"]) > 1, result
        workspace_client.delete(ws_id)

    def test_l2_no_search_matched_when_field_present(self, workspace_client, d1_zip):
        """No search_matched field when the script IS in the field's flow
        (frontend treats absence as matched)."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "step2_report.sql",
                                  "orders", "amount")
        assert "search_matched" not in result, result
        assert "message" not in result, result
        workspace_client.delete(ws_id)

    def test_l2_no_search_matched_when_filter_off(self, workspace_client, d1_zip, monkeypatch):
        """No search_matched field when filtering is off, even for a field
        absent from the script."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        import app.services.dataflow_service as dfs
        self._wrap_search_matched(monkeypatch, dfs)
        result = dfs.get_level2_graph(ws_id, sr["view_id"], "step2_report.sql",
                                      "orders", "ghost", filter_relevant_nodes=False)
        assert "search_matched" not in result, result
        workspace_client.delete(ws_id)

    def test_l2_no_search_matched_without_search_target(self, workspace_client, d1_zip, monkeypatch):
        """No search_matched field when the request carries no search target
        (empty table/field) even if the flag is False."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        import app.services.dataflow_service as dfs
        self._wrap_search_matched(monkeypatch, dfs)
        result = dfs.get_level2_graph(ws_id, sr["view_id"], "step2_report.sql",
                                      "", "")
        assert "search_matched" not in result, result
        workspace_client.delete(ws_id)


class TestLevel1Endpoint:
    """BE2 (issue b): GET level1 must apply the same R18 lineage filter as
    the search response path, so only flow-relevant scripts/tables survive."""

    def test_level1_lineage_filtered_consistent_with_search(self, workspace_client, d1_zip):
        """The level1 endpoint rebuild mirrors the search-time L1:
        identical node set, and the R29 shape holds — no field nodes, no
        superseded lineage_field_pairs, flow_empty always present."""
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        from app.routers.dataflow import search_dataflow, get_level1
        sr = asyncio.run(search_dataflow(ws_id, {"table": "orders", "field": "amount"}))
        l1 = asyncio.run(get_level1(ws_id, sr["view_id"]))
        assert l1["view_id"] == sr["view_id"], l1
        nodes = l1["l1_graph"]["nodes"]
        assert nodes, l1
        # Same node set as the search response (same builder + same filter)
        search_ids = {n.get("data", n).get("id") for n in sr["l1_graph"]["nodes"]}
        level1_ids = {n.get("data", n).get("id") for n in nodes}
        assert level1_ids == search_ids, (search_ids, level1_ids)
        # R29 shape: no field nodes, no lineage_field_pairs, marker present
        for n in nodes:
            assert n.get("data", n).get("type") != "field", \
                "R29: L1 has no field nodes"
        assert "lineage_field_pairs" not in l1["l1_graph"], \
            "R29 supersedes lineage_field_pairs for field queries"
        assert l1["l1_graph"].get("flow_empty") in (True, False), \
            "the directional marker must always be present"
        workspace_client.delete(ws_id)
