"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

import pytest

# Add backend/ to the import path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DATA_DIR = Path(__file__).resolve().parent / "test_data"
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def read_test_sql(filename: str) -> str:
    """Read a SQL test fixture file."""
    path = TEST_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Test fixture not found: {path}")
    return path.read_text()


def read_sample_sql(filename: str) -> str:
    """Read a SQL sample file from the samples directory."""
    path = SAMPLES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Sample not found: {path}")
    return path.read_text()


@pytest.fixture
def sample_fin_query1() -> str:
    """GPS financial query 1: reconciliation."""
    return read_sample_sql("financial/fin_query1_reconciliation.sql")


@pytest.fixture
def sample_fin_query2() -> str:
    """GPS financial query 2: fee calculation."""
    return read_sample_sql("financial/fin_query2_fee_calculation.sql")


@pytest.fixture
def sample_fin_query3() -> str:
    """GPS financial query 3: account balance."""
    return read_sample_sql("financial/fin_query3_account_balance.sql")


@pytest.fixture
def sample_fin_query4() -> str:
    """GPS financial query 4: merge upsert."""
    return read_sample_sql("financial/fin_query4_merge_upsert.sql")


@pytest.fixture
def sample_fin_query5() -> str:
    """GPS financial query 5: union risk report."""
    return read_sample_sql("financial/fin_query5_union_risk_report.sql")


@pytest.fixture
def sample_tables_financial() -> str:
    """GPS financial DDL."""
    return read_sample_sql("financial/tables_financial.sql")

import io, zipfile
from pathlib import Path

@pytest.fixture
def d2_zip():
    """ETL Pipeline: 5 scripts."""
    d2_dir = Path(__file__).resolve().parent / "test_dataflow" / "D2_etl_pipeline"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(d2_dir.rglob('*')):
            if fpath.is_file():
                arcname = str(fpath.relative_to(d2_dir))
                zf.write(fpath, arcname)
    return buf.getvalue()


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

        def _collect_sql(self, tree):
            paths = []
            if tree.get('type') == 'file' and tree.get('is_sql'):
                paths.append(tree['path'])
            for c in tree.get('children', []):
                paths.extend(self._collect_sql(c))
            return paths

    return Client()
