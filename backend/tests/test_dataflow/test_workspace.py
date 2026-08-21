"""Test workspace creation, scanning, deletion."""
import pytest


class TestWorkspaceLifecycle:
    def test_create_workspace(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        assert ws_id is not None
        assert len(ws_id) == 32  # R31/A-H4: full UUID4 hex, no client input
        ws = workspace_client.get(ws_id)
        assert ws is not None
        assert ws["workspace_id"] == ws_id
        assert ws["file_count"] > 0
        workspace_client.delete(ws_id)

    def test_create_empty_zip(self, workspace_client, d7_zip):
        ws_id = workspace_client.create(d7_zip)
        ws = workspace_client.get(ws_id)
        assert ws is not None
        workspace_client.delete(ws_id)

    def test_delete_workspace(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        assert workspace_client.delete(ws_id) is True
        assert workspace_client.get(ws_id) is None

    def test_get_nonexistent(self, workspace_client):
        assert workspace_client.get("nonexistent123") is None

    def test_delete_nonexistent(self, workspace_client):
        assert workspace_client.delete("nonexistent123") is False


class TestFolderScan:
    def test_scan_detects_sql(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        tree = workspace_client.scan(ws_id)
        # Find SQL files
        def find_sql(t):
            results = []
            if t.get('type') == 'file' and t.get('is_sql'):
                results.append(t['name'])
            for c in t.get('children', []):
                results.extend(find_sql(c))
            return results
        sql_files = find_sql(tree)
        assert 'step1_load.sql' in sql_files
        assert 'step2_report.sql' in sql_files
        workspace_client.delete(ws_id)

    def test_scan_detects_non_sql(self, workspace_client, d5_zip):
        ws_id = workspace_client.create(d5_zip)
        tree = workspace_client.scan(ws_id)
        def find_non_sql(t):
            results = []
            if t.get('type') == 'file' and not t.get('is_sql'):
                results.append(t['name'])
            for c in t.get('children', []):
                results.extend(find_non_sql(c))
            return results
        non_sql = find_non_sql(tree)
        assert 'config.json' in non_sql or 'README.md' in non_sql or 'notes.txt' in non_sql
        workspace_client.delete(ws_id)

    def test_scan_nested_dirs(self, workspace_client, d5_zip):
        ws_id = workspace_client.create(d5_zip)
        tree = workspace_client.scan(ws_id)
        # Should have subdir with util.sql
        def has_sql_in_subdir(t):
            for c in t.get('children', []):
                if c.get('name') == 'subdir':
                    for sc in c.get('children', []):
                        if sc.get('name') == 'util.sql' and sc.get('is_sql'):
                            return True
            return False
        assert has_sql_in_subdir(tree)
        workspace_client.delete(ws_id)

    def test_no_sql_folder(self, workspace_client, d7_zip):
        ws_id = workspace_client.create(d7_zip)
        tree = workspace_client.scan(ws_id)
        def find_sql(t):
            results = []
            if t.get('type') == 'file' and t.get('is_sql'):
                results.append(t['name'])
            for c in t.get('children', []):
                results.extend(find_sql(c))
            return results
        assert len(find_sql(tree)) == 0
        workspace_client.delete(ws_id)
