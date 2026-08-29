"""R20: index-time orphan resolution (S4 schema pass) + coverage report.

TC1–TC5 per spec. Fixture pattern from test_orphan_fields.py
(zip upload + index_scripts on the real workspace path).

The extractor emits `resolution_stats` in new analyses; the indexer must
read it DEFENSIVELY (TC5 — old analyses without the key), aggregate it
(TC1/TC4), run the S4b cross-script schema pass (scope-aware — candidates
re-tested only within their own visible tables; TC3 is the never-guess
ambiguity regression — TC1 was the 0-visible-owner case until R44
(2026-08-28) made the INSERT target list authored evidence: the write-side
twin attributes the DML target's columns at extraction time), and push the
ORPHAN RESOLUTION REPORT (TC3) + expose resolution_stats on the response.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import index_scripts

# TC1: bare `id` is not qualified anywhere (S1–S3 cannot attribute it: two
# physical tables in scope). Pre-R44 the only schema evidence for `id`
# lived in t1's INSERT target column list, which read-scope visibility
# excluded → stayed unresolved (the s4 never-guess regression).
# R44 (2026-08-28, user ruling "walker occurrence coverage"): the INSERT
# list `(id)` is authored SQL text = positive evidence, NOT a guess — the
# extractor registers the write-side twin t1.id (attributed to t1,
# extraction-time fact), so the statement DOES reference t1 (its DML
# target) and the index records id → t1. INSERT-target attribution is
# allowed under the occurrence-coverage ruling; never-guess governs
# scope-INFERRED attribution only.
TC1_SQL = (
    "INSERT INTO t1 (id) SELECT id FROM a JOIN b ON a.x = b.y;\n"
)
# TC3/TC5: genuinely ambiguous owners (a AND b both infer id/name) → S3
# (≥2 physical tables in the JOIN scope) and S4 (≥2 schema owners) must
# NOT guess; both fields stay orphans and land in the UNRESOLVED section.
TC3_SQL = (
    "INSERT INTO a (id, name) SELECT p, q FROM src1;\n"
    "INSERT INTO b (id, name) SELECT r, s FROM src2;\n"
    "SELECT id, name FROM a JOIN b ON a.x = b.y;\n"
)
# TC2: qualified-only multi-script workflow (mirrors samples/multi_workflow).
MWF_SCRIPTS = {
    "step1_load_orders.sql": (
        "INSERT INTO stg_orders (order_id, customer_id, amount, order_date, status)\n"
        "SELECT o.order_id, o.customer_id, o.amount, o.order_date, o.status\n"
        "FROM raw_orders o\n"
        "WHERE o.order_date >= '2024-01-01' AND o.status IN ('completed', 'pending');\n"
    ),
    "step2_enrich_customers.sql": (
        "INSERT INTO stg_customers (customer_id, name, segment, region)\n"
        "SELECT c.customer_id, c.full_name, c.segment, c.region\n"
        "FROM crm_customers c\n"
        "WHERE c.is_active = 1 AND c.region IN ('NA', 'EMEA', 'APAC');\n"
    ),
    "step3_join_orders_customers.sql": (
        "INSERT INTO analytics_orders (order_id, customer_name, amount, segment, region, order_date)\n"
        "SELECT so.order_id, sc.name, so.amount, sc.segment, sc.region, so.order_date\n"
        "FROM stg_orders so JOIN stg_customers sc ON so.customer_id = sc.customer_id\n"
        "WHERE so.status = 'completed';\n"
    ),
    "step4_aggregate_daily.sql": (
        "INSERT INTO daily_summary (report_date, region, total_orders, total_amount)\n"
        "SELECT DATE(ao.order_date) AS dt, ao.region, COUNT(*) AS cnt, SUM(ao.amount) AS total\n"
        "FROM analytics_orders ao GROUP BY DATE(ao.order_date), ao.region;\n"
    ),
    "step5_final_report.sql": (
        "SELECT ds.report_date, ds.region, ds.total_orders, ds.total_amount,\n"
        "       ROUND(ds.total_amount / NULLIF(ds.total_orders, 0), 2) AS avg_order_value\n"
        "FROM daily_summary ds\n"
        "WHERE ds.report_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)\n"
        "ORDER BY ds.report_date DESC, ds.total_amount DESC;\n"
    ),
}


def _make_ws(entries: dict, script_name: str = "t.sql") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


@pytest.fixture
def tc1_ws():
    ws_id = _make_ws({"t.sql": TC1_SQL})
    yield ws_id
    delete_workspace(ws_id)


@pytest.fixture
def tc3_ws():
    ws_id = _make_ws({"t.sql": TC3_SQL})
    yield ws_id
    delete_workspace(ws_id)


@pytest.fixture
def mwf_ws():
    ws_id = _make_ws(MWF_SCRIPTS)
    yield ws_id
    delete_workspace(ws_id)


def test_tc1_scope_absent_schema_owner_stays_unresolved(tc1_ws):
    """R44 amendment (2026-08-28, user ruling): the INSERT list `(id)` IS
    authored evidence, so the bare SELECT-side `id` now attributes to the
    DML target t1 via the extraction-time write-side twin t1.id — the
    statement references t1 as its write target, read-scope-only
    visibility no longer applies. The S4b SCHEMA strategy itself stays
    untouched (by_strategy.schema == 0 — the twin is extractor-side, not
    an index-time inference); never-guess still governs scope-INFERRED
    attribution (see TC3's ambiguity case)."""
    result = index_scripts(tc1_ws, ["t.sql"])
    stats = result["resolution_stats"]
    assert stats["by_strategy"]["schema"] == 0, stats
    assert result["orphan_field_count"] == 0, result["orphan_field_samples"]
    assert result["orphan_field_samples"] == [], result["orphan_field_samples"]
    assert result["field_index"]["id"]["tables"] == ["t1"], \
        "R44: the INSERT target list is authored evidence for t1.id"
    # persisted indexes must agree
    fi = json.loads((get_workspace_dir(tc1_ws) / "cache" / "field_index.json").read_text())
    ti = json.loads((get_workspace_dir(tc1_ws) / "cache" / "table_index.json").read_text())
    assert fi["id"]["tables"] == ["t1"], fi["id"]
    assert "id" in ti["t1"]["fields"], ti["t1"]


def test_tc2_qualified_only_workflow_full_coverage(mwf_ws):
    """Qualified-only workspace → unresolved 0, coverage 100%."""
    result = index_scripts(mwf_ws, sorted(MWF_SCRIPTS))
    stats = result["resolution_stats"]
    assert result["orphan_field_count"] == 0, result["orphan_field_samples"]
    assert stats["unresolved"] == 0, stats
    assert stats["coverage_pct"] == 100.0, stats
    # resolved must equal total column vars (all resolved) — holds both with
    # the real extractor stats and with the old-cache fallback (0 == 0)
    assert stats["resolved"] == stats["total_columns"], stats


def test_tc3_report_block_pushed(monkeypatch, tc3_ws):
    """R20 block pushed via _push: header, coverage, UNRESOLVED section."""
    messages = []

    def fake_push(ws_id, stage, message):
        messages.append((stage, message))

    monkeypatch.setattr("app.services.folder_index_service._push", fake_push)
    result = index_scripts(tc3_ws, ["t.sql"])
    joined = "\n".join(m for s, m in messages if s == "profile")
    assert "ORPHAN RESOLUTION REPORT" in joined, joined
    assert "unresolved: 2" in joined, joined
    assert "UNRESOLVED orphans — possible bad cases, check SQL:" in joined, joined
    assert "field: id   script: t.sql" in joined, joined
    assert "L1: INSERT INTO a (id" in joined, \
        "a SQL line mentioning the field must be shown in the UNRESOLVED section"


def test_tc3b_report_block_pushed_when_no_orphans(monkeypatch):
    """0 orphans → block still pushed, with unresolved: 0 and no section.
    (Qualified-only workspace — genuinely 0 orphans, unlike tc1_ws whose
    scope-absent `id` S4b now correctly leaves unresolved.)"""
    ws = _make_ws({"qualified.sql":
                   "SELECT c.customer_id FROM crm_customers c;\n"})
    try:
        messages = []

        def fake_push(ws_id, stage, message):
            messages.append((stage, message))

        monkeypatch.setattr("app.services.folder_index_service._push", fake_push)
        result = index_scripts(ws, ["qualified.sql"])
        assert result["orphan_field_count"] == 0, result
        joined = "\n".join(m for s, m in messages if s == "profile")
        assert "ORPHAN RESOLUTION REPORT" in joined, joined
        assert "unresolved: 0" in joined, joined
        assert "UNRESOLVED orphans" not in joined, joined
    finally:
        delete_workspace(ws)


def test_tc4_response_has_resolution_stats(tc3_ws):
    """Response carries resolution_stats with all R20 keys."""
    result = index_scripts(tc3_ws, ["t.sql"])
    stats = result["resolution_stats"]
    assert set(stats) == {"total_columns", "resolved", "unresolved",
                          "container_resolved", "coverage_pct",
                          "by_strategy", "ambiguous"}, stats
    assert set(stats["by_strategy"]) == {"plain_alias", "expr_alias", "scope",
                                         "schema", "sys", "other"}, stats
    assert stats["unresolved"] == result["orphan_field_count"] == 2, stats
    # by_strategy must be non-negative ints
    assert all(v >= 0 for v in stats["by_strategy"].values()), stats


def test_tc5_old_analysis_without_resolution_stats(monkeypatch, tc3_ws):
    """Missing resolution_stats (old caches) → graceful fallback, no crash."""
    from app.extractor import adapter as adapter_mod
    real = adapter_mod.run_full_analysis

    def stripped(sql_text, script_name, ws_id=None):
        result = real(sql_text, script_name, ws_id=ws_id)
        result.pop("resolution_stats", None)  # old-style analysis
        return result

    monkeypatch.setattr(adapter_mod, "run_full_analysis", stripped)
    result = index_scripts(tc3_ws, ["t.sql"])  # must not raise
    stats = result["resolution_stats"]
    assert stats["total_columns"] == 0, stats          # zeros fallback
    assert stats["coverage_pct"] == 100.0, stats       # "if total else 100"
    assert stats["by_strategy"] == {"plain_alias": 0, "expr_alias": 0, "scope": 0,
                                    "schema": 0, "sys": 0, "other": 0}, stats
    # unresolved still computed from field_index (2 ambiguous orphans)
    assert stats["unresolved"] == 2, stats
    assert result["orphan_field_count"] == 2, result


class TestReviewerFixes:
    """R20 reviewer findings: S5/S6 excluded from index-level unresolved;
    CTE names must not leak into table_index or S4 candidates."""

    def test_s5_sys_table_not_counted_unresolved(self):
        """INFORMATION_SCHEMA columns are marked expected — not orphans."""
        ws = _make_ws({"sys.sql":
                       "SELECT TABLE_NAME, TABLE_SCHEMA FROM INFORMATION_SCHEMA.TABLES;"})
        r = index_scripts(ws, ["sys.sql"])
        assert r["orphan_field_count"] == 0, r
        assert r["resolution_stats"]["unresolved"] == 0, r["resolution_stats"]
        assert r["resolution_stats"]["by_strategy"]["sys"] >= 1

    def test_s6_pseudocolumn_not_counted_unresolved(self):
        """LEVEL is a pseudocolumn — marked expected, not an orphan."""
        ws = _make_ws({"pseudo.sql":
                       "SELECT LEVEL FROM dual CONNECT BY LEVEL <= 10;"})
        r = index_scripts(ws, ["pseudo.sql"])
        assert r["orphan_field_count"] == 0, r
        assert r["resolution_stats"]["unresolved"] == 0, r["resolution_stats"]
        assert r["resolution_stats"]["by_strategy"]["other"] >= 1

    def test_cte_name_not_in_table_index(self):
        """CTE names are script-scoped — must not become workspace tables."""
        ws = _make_ws({"cte.sql":
                       "WITH c AS (SELECT SUM(a) AS s FROM t) SELECT s FROM c;"})
        r = index_scripts(ws, ["cte.sql"])
        ti = json.loads((get_workspace_dir(ws) / "cache" / "table_index.json").read_text())
        assert "c" not in ti, "CTE name leaked into table_index"
        # the CTE-resolved field is not an orphan (extractor resolved it)
        assert r["orphan_field_count"] == 0, r


class TestL3Progress:
    """L3: _INDEX_PROGRESS is lock-guarded; errors accumulate instead of
    being silently reset on the error path."""

    def test_l3_errors_accumulate_in_progress(self):
        """Per-script failures surface in get_index_progress with progress kept."""
        from app.services.folder_index_service import get_index_progress
        ws = _make_ws({"ok.sql": "SELECT 1;\n"})
        try:
            result = index_scripts(ws, ["missing.sql", "ok.sql"])
            assert result["errors"], "missing script must be reported"
            p = get_index_progress(ws)
            assert p["phase"] == "done", p
            assert p["current"] == 2 and p["total"] == 2, p
            errs = p["errors"]
            assert len(errs) == 1, errs
            assert errs[0]["script"] == "missing.sql", errs
            assert errs[0]["error"] == "File not found", errs
        finally:
            delete_workspace(ws)

    def test_l3_new_run_resets_previous_errors(self):
        """A fresh index run starts from zero — previous errors don't leak."""
        from app.services.folder_index_service import get_index_progress
        ws = _make_ws({"ok.sql": "SELECT 1;\n"})
        try:
            index_scripts(ws, ["missing.sql"])
            p1 = get_index_progress(ws)
            assert len(p1["errors"]) == 1, p1
            index_scripts(ws, ["ok.sql"])
            p2 = get_index_progress(ws)
            assert p2["errors"] == [], p2
            assert p2["current"] == 1 and p2["total"] == 1, p2
        finally:
            delete_workspace(ws)

    def test_l3_progress_shape_unchanged(self, tc1_ws):
        """The progress dict keeps its {current,total,phase,errors} shape."""
        from app.services.folder_index_service import get_index_progress
        index_scripts(tc1_ws, ["t.sql"])
        p = get_index_progress(tc1_ws)
        assert set(p) == {"current", "total", "phase", "errors"}, p
        assert p["phase"] == "done"

    def test_l7_progress_errors_are_copied(self):
        """Review L7: get_index_progress returns a snapshot — mutating the
        returned errors list or fields must not corrupt the registry."""
        from app.services.folder_index_service import get_index_progress
        ws = _make_ws({"ok.sql": "SELECT 1;\n"})
        try:
            index_scripts(ws, ["missing.sql"])
            p1 = get_index_progress(ws)
            assert len(p1["errors"]) == 1, p1
            p1["errors"].append({"script": "bogus", "error": "injected"})
            p1["errors"].clear()
            p1["current"] = 999
            p2 = get_index_progress(ws)
            assert len(p2["errors"]) == 1, p2
            assert p2["errors"][0]["script"] == "missing.sql", p2
            assert p2["current"] == 1 and p2["total"] == 1, p2
            assert p2["phase"] == "done", p2
        finally:
            delete_workspace(ws)
