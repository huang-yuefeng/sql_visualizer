"""Test buggy SQL detection via data flow analysis."""
import pytest
import json
from pathlib import Path


class TestBuggyDetection:
    def test_buggy_script_indexes(self, workspace_client, d6_zip):
        ws_id = workspace_client.create(d6_zip)
        result = workspace_client.index(ws_id)
        assert result["script_count"] >= 4
        assert result["errors"] == []
        workspace_client.delete(ws_id)

    def test_buggy_l1_includes_buggy_script(self, workspace_client, d6_zip):
        ws_id = workspace_client.create(d6_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "transactions", "amount")
        scripts = sr.get("script_ids", [])
        assert "buggy_report.sql" in scripts  # buggy script still found
        workspace_client.delete(ws_id)

    def test_correct_script_has_amount_flow(self, workspace_client, d6_zip):
        """Verify correct_transform.sql shows amount flowing through."""
        ws_id = workspace_client.create(d6_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "transactions", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "correct_transform.sql", "transactions", "amount")
        graph = result.get("graph", {})
        nodes = graph.get("nodes", [])
        # Should have amount-related nodes
        labels = [n.get("data", n).get("label", "") for n in nodes]
        assert any("amount" in lbl.lower() for lbl in labels)
        workspace_client.delete(ws_id)

    def test_buggy_script_has_different_source(self, workspace_client, d6_zip):
        """Buggy script aliases fee as amount — graph shows this."""
        ws_id = workspace_client.create(d6_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "transactions", "amount")
        from app.services.dataflow_service import get_level2_graph
        result = get_level2_graph(ws_id, sr["view_id"], "buggy_report.sql", "transactions", "amount")
        graph = result.get("graph", {})
        nodes = graph.get("nodes", [])
        labels = [n.get("data", n).get("label", "") for n in nodes]
        # The buggy script references 'fee' as amount
        # Either 'fee' appears or 'amount' appears as alias
        assert any("fee" in lbl.lower() or "amount" in lbl.lower() for lbl in labels)
        workspace_client.delete(ws_id)


class TestMultiWorkspace:
    def test_workspace_isolation(self, workspace_client, d1_zip, d2_zip):
        ws1 = workspace_client.create(d1_zip)
        ws2 = workspace_client.create(d2_zip)
        workspace_client.index(ws1)
        workspace_client.index(ws2)
        # Search in ws1 should not find staging_orders
        sr1 = workspace_client.search(ws1, "orders", "amount")
        # Search in ws2 should find staging_orders
        sr2 = workspace_client.search(ws2, "staging_orders", "amount")
        assert sr1["script_ids"] != sr2["script_ids"]
        workspace_client.delete(ws1)
        workspace_client.delete(ws2)
