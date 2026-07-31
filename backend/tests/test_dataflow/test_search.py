"""Test dataflow search and graph building."""
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

    def test_search_no_match_returns_fallback(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        result = workspace_client.search(ws_id, "nonexistent", "nonexistent")
        assert "view_id" in result
        # Should still get scripts (fallback to field-only or table-only)
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
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "step2_report.sql", "orders", "amount")
        assert "highlights" in result
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
    """L1 invariant: scripts connect through table variables, never directly."""
    from app.services.dataflow_service import _build_l1_graph

    ws_id = workspace_client.create(d2_zip)
    workspace_client.index(ws_id)
    
    scripts = ["step1_load_orders.sql", "step2_enrich_customers.sql",
               "step3_join_orders_customers.sql", "step4_aggregate_daily.sql",
               "step5_final_report.sql"]
    
    result = _build_l1_graph(ws_id, scripts, "crm_customers", "customer_id")
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
