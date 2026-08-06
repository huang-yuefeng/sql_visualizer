"""Test fixtures for V3 dataflow tests."""
import io
import json
import os
import zipfile
import pytest
from pathlib import Path

TEST_DATA_DIR = Path(__file__).parent


def _make_zip(folder: Path) -> bytes:
    """Create an in-memory zip from a folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(folder.rglob('*')):
            if fpath.is_file():
                arcname = str(fpath.relative_to(folder))
                zf.write(fpath, arcname)
    return buf.getvalue()


@pytest.fixture
def d1_zip():
    """Minimal: 2 scripts + 1 non-SQL."""
    return _make_zip(TEST_DATA_DIR / 'D1_minimal')


@pytest.fixture
def d2_zip():
    """ETL Pipeline: 5 scripts."""
    return _make_zip(TEST_DATA_DIR / 'D2_etl_pipeline')


@pytest.fixture
def d5_zip():
    """Mixed folder: SQL + non-SQL files."""
    return _make_zip(TEST_DATA_DIR / 'D5_mixed')


@pytest.fixture
def d6_zip():
    """Buggy scripts."""
    return _make_zip(TEST_DATA_DIR / 'D6_buggy')


@pytest.fixture
def d7_zip():
    """No SQL files."""
    return _make_zip(TEST_DATA_DIR / 'D7_empty')


@pytest.fixture
def d8_zip():
    """Deep CTE nesting."""
    return _make_zip(TEST_DATA_DIR / 'D8_deep_nesting')


@pytest.fixture
def workspace_client():
    """Create workspace via service layer (fast, no HTTP)."""
    from app.services.workspace_service import (
        create_workspace, get_workspace, delete_workspace,
        get_workspace_dir,
    )

    class Client:
        def create(self, zip_bytes):
            ws_id = create_workspace(zip_bytes)
            return ws_id

        def get(self, ws_id):
            return get_workspace(ws_id)

        def delete(self, ws_id):
            return delete_workspace(ws_id)

        def scan(self, ws_id):
            from app.services.folder_index_service import scan_folder
            return scan_folder(ws_id)

        def index(self, ws_id, scripts=None):
            from app.services.folder_index_service import index_scripts
            if scripts is None:
                tree = self.scan(ws_id)
                scripts = self._collect_sql(tree)
            return index_scripts(ws_id, scripts)

        def autocomplete(self, ws_id, type_, q=""):
            cache_dir = get_workspace_dir(ws_id) / "cache"
            idx_path = cache_dir / f"{type_}_index.json"
            if not idx_path.exists():
                return []
            idx = json.loads(idx_path.read_text())
            from app.services.folder_index_service import autocomplete as ac
            return ac(idx, type_, q)

        def search(self, ws_id, table, field):
            from app.services.dataflow_service import create_search
            import asyncio
            cache_dir = get_workspace_dir(ws_id) / "cache"
            ti = json.loads((cache_dir / "table_index.json").read_text()) if (cache_dir / "table_index.json").exists() else {}
            fi = json.loads((cache_dir / "field_index.json").read_text()) if (cache_dir / "field_index.json").exists() else {}
            return asyncio.run(create_search(ws_id, table, field, ti, fi))

        def _collect_sql(self, tree):
            paths = []
            if tree.get('type') == 'file' and tree.get('is_sql'):
                paths.append(tree['path'])
            for c in tree.get('children', []):
                paths.extend(self._collect_sql(c))
            return paths

    return Client()
