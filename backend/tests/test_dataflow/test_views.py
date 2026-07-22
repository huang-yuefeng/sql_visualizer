"""Test view management."""
import pytest
from app.services.dataflow_service import list_views, delete_view


class TestViews:
    def test_list_views_empty(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        views = list_views(ws_id)
        assert isinstance(views, list)
        workspace_client.delete(ws_id)

    def test_create_and_list_view(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        views = list_views(ws_id)
        assert len(views) >= 1
        workspace_client.delete(ws_id)

    def test_delete_view(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr = workspace_client.search(ws_id, "orders", "amount")
        vid = sr["view_id"]
        ok = delete_view(ws_id, vid)
        assert ok is True
        views = list_views(ws_id)
        assert not any(v["view_id"] == vid for v in views)
        workspace_client.delete(ws_id)

    def test_duplicate_search(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        workspace_client.index(ws_id)
        sr1 = workspace_client.search(ws_id, "orders", "amount")
        sr2 = workspace_client.search(ws_id, "orders", "amount")
        views = list_views(ws_id)
        # Both searches should create views
        assert len(views) >= 2
        workspace_client.delete(ws_id)
