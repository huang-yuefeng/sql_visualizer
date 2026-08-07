"""Regression tests for the sql_sample_v1 ODPS repro script.

The script `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql` is the
OCR-reconstructed user script (MaxCompute/ODPS dialect) behind three reported
issues:

  a. the same physical table (`bdm_acc_loan_info`) parsed into multiple L2
     nodes (4 contexts),
  b/c. searching `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE` matched this script
     although the field is never queried by it — the script is not part of
     that field's data flow.

These tests pin the stable extractor/index invariants (the L2 dedup and
search-participation regression tests live with the feature teams in
`test_compound_l2.py` / `test_search.py`).
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402

from tests.test_dataflow.conftest import _make_zip  # noqa: E402

CASE_DIR = REPO_ROOT / "samples" / "sql_sample_v1"
SCRIPT_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"

# Ground truth: v3.3.140 extractor (statement-anchored lines, phantom
# dedup — the raw walk no longer re-registers subquery-interior columns
# in outer contexts; v3.3.135 measured 344/1102 with the phantoms).
EXPECTED_MIN_VARS = 253
EXPECTED_MIN_DEPS = 660


@pytest.fixture(scope="module")
def script_path():
    path = CASE_DIR / SCRIPT_NAME
    if not path.exists():
        raise FileNotFoundError(f"Repro script not found: {path}")
    return path


@pytest.fixture(scope="module")
def analysis(script_path):
    sql = script_path.read_text()
    res = extract_variables_from_sql(sql, "BDM_ACC_LOAN_INFO_SUP_M")
    deps = build_dependency_graph(res)
    return res, deps


class TestExtractorInvariants:
    def test_variable_count(self, analysis):
        """253 variables — regression anchor for extractor stability."""
        res, _ = analysis
        assert len(res.variables) >= EXPECTED_MIN_VARS, \
            f"Got {len(res.variables)} vars (expected >= {EXPECTED_MIN_VARS})"

    def test_dependency_count(self, analysis):
        """660 dependencies — regression anchor."""
        _, deps = analysis
        assert len(deps) >= EXPECTED_MIN_DEPS, \
            f"Got {len(deps)} deps (expected >= {EXPECTED_MIN_DEPS})"

    def test_table_context_counts(self, analysis):
        """The multi-context signature behind issue a."""
        res, _ = analysis
        tables = [v for v in res.variables if v.variable_type.name == "TABLE"]
        counts = {t.name: sum(1 for v in tables if v.name == t.name) for t in tables}
        # bdm_acc_loan_info is read in 3 contexts (no-alias CTE FROM, p1 CTE
        # join, subquery p1) — the 4th (the NOT IN subquery's raw-walk
        # re-registration) was a phantom duplicate, removed by the v3.3.140
        # dedup. Must stay >= 3 so the L2 one-node-per-table merge has real
        # data to merge.
        assert counts.get("bdm_acc_loan_info", 0) >= 3, \
            f"Expected >=3 bdm_acc_loan_info contexts, got {counts.get('bdm_acc_loan_info', 0)}"
        # INSERT target exists.
        assert counts.get("bdm_acc_loan_info_sup", 0) >= 1, \
            f"Expected bdm_acc_loan_info_sup (INSERT target), got {counts}"
        # NOT IN dependency table.
        assert counts.get("bdm_evt_loan_trans", 0) >= 1, \
            f"Expected bdm_evt_loan_trans, got {counts}"

    def test_key_fields_present(self, analysis):
        """Real fields of this script (in contrast to ABROAD_LOAD_PURPOSE)."""
        res, _ = analysis
        names = {v.name for v in res.variables}
        for field in ("lending_ref", "loan_maturity_dt", "p1.reserved_field8"):
            assert field in names, f"Expected field {field!r} in extracted vars"

    def test_abroad_load_purpose_absent(self, analysis):
        """Issue b/c anchor: this script never queries ABROAD_LOAD_PURPOSE."""
        res, _ = analysis
        names = {v.name.lower() for v in res.variables}
        assert "abroad_load_purpose" not in names, \
            "Script must not contain ABROAD_LOAD_PURPOSE (it is the not-in-flow case)"


class TestWorkspaceIndex:
    """Workspace-level index invariants (folder scan + index, no HTTP)."""

    @pytest.fixture
    def ws(self, workspace_client):
        ws_id = workspace_client.create(_make_zip(CASE_DIR))
        try:
            workspace_client.scan(ws_id)
            workspace_client.index(ws_id)
            yield ws_id
        finally:
            workspace_client.delete(ws_id)

    def _index_text(self, ws, kind):
        from app.services.workspace_service import get_workspace_dir
        path = get_workspace_dir(ws) / "cache" / f"{kind}_index.json"
        assert path.exists(), f"{kind}_index.json missing for workspace {ws}"
        return path.read_text()

    def test_table_index_contains_script_tables(self, ws):
        text = self._index_text(ws, "table")
        for table in ("bdm_acc_loan_info", "bdm_acc_loan_info_sup",
                      "ods_hub_lsacmsp", "rrcdm_job_log_exec_par"):
            assert table in text, f"table index missing {table!r}"

    def test_field_index_has_real_fields(self, ws):
        text = self._index_text(ws, "field")
        assert "lending_ref" in text, "field index missing lending_ref"

    def test_field_index_lacks_abroad_load_purpose(self, ws):
        """Issue b/c anchor: searching this field must NOT match this script."""
        text = self._index_text(ws, "field")
        assert "ABROAD_LOAD_PURPOSE" not in text, \
            "ABROAD_LOAD_PURPOSE must stay out of the field index for this script"
