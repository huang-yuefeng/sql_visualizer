"""Test folder indexing and autocomplete."""
import pytest


class TestFolderIndex:
    def test_index_builds_table_index(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        result = workspace_client.index(ws_id)
        ti = result["table_index"]
        assert "orders" in ti
        assert result["script_count"] >= 2
        workspace_client.delete(ws_id)

    def test_index_builds_field_index(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        result = workspace_client.index(ws_id)
        fi = result["field_index"]
        assert "amount" in fi
        assert "customer_id" in fi
        workspace_client.delete(ws_id)

    def test_autocomplete_table(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "table", "sta")
        assert any("staging" in s.lower() for s in suggestions)
        workspace_client.delete(ws_id)

    def test_autocomplete_field(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "field", "amo")
        assert "amount" in suggestions
        workspace_client.delete(ws_id)

    def test_autocomplete_empty_query(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "table", "")
        assert len(suggestions) > 0
        workspace_client.delete(ws_id)

    def test_index_no_sql(self, workspace_client, d7_zip):
        ws_id = workspace_client.create(d7_zip)
        result = workspace_client.index(ws_id)
        assert result["script_count"] == 0
        workspace_client.delete(ws_id)

    def test_index_deep_nesting(self, workspace_client, d8_zip):
        ws_id = workspace_client.create(d8_zip)
        result = workspace_client.index(ws_id)
        assert result["script_count"] == 1
        workspace_client.delete(ws_id)
