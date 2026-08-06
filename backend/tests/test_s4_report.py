"""S4 Phase 1 (REPORT ONLY) tests — index-side SELECT-side schema candidates.

The extractor's S4a (Phase 0, report-only) emits per-script
`schema_candidates` / `script_schemas` / `r6_collision` inside
`resolution_stats`; the index side (S4b Phase 1) must:

- aggregate M_ws = union of all scripts' script_schemas
- re-test each post-S4 orphan: owners = visible(field) ∩ M_ws (whole-name,
  case-insensitive = R4; R6 field==table guard) — REPORT ONLY, never
  attribute
- extend the ORPHAN RESOLUTION REPORT (summary line + per-owner lines)
- expose `schema_candidates_summary` on the index response
- stay byte-identical on old caches (keys absent) and never touch
  coverage_pct / the orphan set

Most tests use the REAL extractor output (S4a is landed); the run_full_analysis
wrapper (`_s4c_sim`) is used only where a scenario cannot be produced by the
real extractor: string locs, partial keys, and old-style stripping.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor import adapter as adapter_mod
from app.services.folder_index_service import index_scripts
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)

# The original analysis entrypoint, captured BEFORE any monkeypatch so the
# wrappers below can call through without recursion.
_REAL_RUN = adapter_mod.run_full_analysis


def _make_ws(entries: dict) -> str:
    """Zip-upload fixture pattern (test_orphan_resolution_index.py /
    test_orphan_fields.py): entries = {script_name: sql}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _s4c_sim(per_script: dict):
    """Wrap run_full_analysis, injecting the S4a keys into each script's
    resolution_stats (used for scenarios the real extractor can't produce:
    string locs / custom candidates). per_script:
    {script_name: {"candidates": [...], "script_schemas": {...}, "r6": int}}."""
    def wrapped(sql_text, script_name, ws_id=None):
        result = _REAL_RUN(sql_text, script_name, ws_id=ws_id)
        rs = result.get("resolution_stats")
        rs = dict(rs) if isinstance(rs, dict) else {}
        inj = per_script.get(script_name, {})
        rs["schema_candidates"] = inj.get("candidates", [])
        rs["r6_collision"] = inj.get("r6", 0)
        rs["script_schemas"] = inj.get("script_schemas", {})
        result["resolution_stats"] = rs
        return result

    return wrapped


def _run_capture(monkeypatch, ws_id, scripts, sim=None):
    """Index with a fake _push; return (result, "\n".join(profile msgs))."""
    msgs = []
    monkeypatch.setattr(
        "app.services.folder_index_service._push",
        lambda ws_id, stage, message: msgs.append((stage, message)))
    if sim is not None:
        monkeypatch.setattr(adapter_mod, "run_full_analysis", sim)
    result = index_scripts(ws_id, scripts)
    joined = "\n".join(m for s, m in msgs if s == "profile")
    return result, joined


# ── TC1: cross-script unique owner ──────────────────────────────────────

def test_cross_script_unique_owner_line(monkeypatch):
    """Bare column in a 2-table scope; the owner's schema evidence lives in
    ANOTHER script (DML target list, design source 2) → the report shows the
    unique visible owner line. Nothing is attributed: the field stays in the
    UNRESOLVED section (REPORT ONLY).

    Note: the evidence script must be evidence-only (DDL/DML list) — a
    qualified ref in the same workspace would already attribute the field
    via S1, taking it out of the orphan set the report covers.
    """
    ws = _make_ws({
        "s1.sql": "INSERT INTO web_sales (ws_web_page_sk) SELECT x FROM src1;\n",
        "s2.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    })
    try:
        result, joined = _run_capture(monkeypatch, ws,
                                      ["s1.sql", "s2.sql"])
        assert ("schema candidates: 1 (unique visible owner found: 1)"
                " | r6 collision: 0") in joined, joined
        assert ("field: ws_web_page_sk → web_sales (evidence: s2.sql L1"
                in joined), joined
        # still an orphan — Phase 1 reports, never attributes
        assert "UNRESOLVED orphans — possible bad cases, check SQL:" in joined
        assert "field: ws_web_page_sk   script: s2.sql" in joined
        fi = json.loads((get_workspace_dir(ws) / "cache"
                         / "field_index.json").read_text())
        assert fi["ws_web_page_sk"]["tables"] == [], \
            "Phase 1 must not attribute (REPORT ONLY)"
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 1, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC2: genuinely ambiguous — no owner line ─────────────────────────────

def test_ambiguous_owners_no_line(monkeypatch):
    """BOTH visible tables' script_schemas own the field (evidence in two
    scripts) → ≥2 owners → no owner line; counted in N, not in M."""
    ws = _make_ws({
        "ddl1.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "ddl2.sql": "CREATE TABLE web_page (ws_web_page_sk INT);\n",
        "s2.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    })
    try:
        result, joined = _run_capture(monkeypatch, ws,
                                      ["ddl1.sql", "ddl2.sql", "s2.sql"])
        assert ("schema candidates: 1 (unique visible owner found: 0)"
                " | r6 collision: 0") in joined, joined
        assert "→ web_sales" not in joined, joined
        assert "→ web_page" not in joined, joined
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC3: R6 collision — never an owner ───────────────────────────────────

def test_r6_collision_never_owner(monkeypatch):
    """Field name == a visible table name → r6 collision: counted in K, NO
    owner line — even though call_center's own schema owns Call_Center
    (case-folded) and the scope-blind S4 would match."""
    ws = _make_ws({
        "ddl.sql": "CREATE TABLE call_center (Call_Center INT);\n",
        "s2.sql": "SELECT call_center FROM call_center JOIN x;\n",
    })
    try:
        result, joined = _run_capture(monkeypatch, ws,
                                      ["ddl.sql", "s2.sql"])
        assert ("schema candidates: 1 (unique visible owner found: 0)"
                " | r6 collision: 1") in joined, joined
        assert "→ call_center" not in joined, joined
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 0, "r6_collision": 1}
    finally:
        delete_workspace(ws)


# ── TC4: old caches (no new keys) → byte-identical report ───────────────

def _strip_s4c_keys(sql_text, script_name, ws_id=None):
    """Old-style analysis: resolution_stats without the S4a keys."""
    result = _REAL_RUN(sql_text, script_name, ws_id=ws_id)
    rs = result.get("resolution_stats")
    if isinstance(rs, dict):
        rs = dict(rs)
        rs.pop("schema_candidates", None)
        rs.pop("r6_collision", None)
        rs.pop("script_schemas", None)
        result["resolution_stats"] = rs
    return result


def test_old_cache_report_unchanged(monkeypatch):
    """Analyses WITHOUT the new S4 keys → the report block is byte-identical
    to the pre-Phase-1 format: every old marker present in its exact format,
    none of the new ones, and two runs produce identical bytes. The response
    summary is zeroed."""
    monkeypatch.setattr(adapter_mod, "run_full_analysis", _strip_s4c_keys)
    ws = _make_ws({
        "t.sql": ("INSERT INTO a (id, name) SELECT p, q FROM src1;\n"
                  "INSERT INTO b (id, name) SELECT r, s FROM src2;\n"
                  "SELECT id, name FROM a JOIN b ON a.x = b.y;\n"),
    })
    try:
        result1, joined1 = _run_capture(monkeypatch, ws, ["t.sql"])
        result2, joined2 = _run_capture(monkeypatch, ws, ["t.sql"])
        assert joined1 == joined2, "report must be deterministic on old caches"
        # exact old format (grep the pre-Phase-1 markers)
        assert "┌─ ORPHAN RESOLUTION REPORT " in joined1
        assert "│ column vars:" in joined1
        assert "│   unresolved:" in joined1
        assert "│   by strategy (attribution events, not unique vars):" in joined1
        assert "│   (sys=" in joined1
        assert "UNRESOLVED orphans — possible bad cases, check SQL:" in joined1
        assert "field: id   script: t.sql" in joined1
        # no new content
        assert "schema candidates:" not in joined1
        assert "r6 collision" not in joined1
        assert "→" not in joined1
        assert result1["schema_candidates_summary"] == {
            "total": 0, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


def test_no_resolution_stats_at_all_still_old_format(monkeypatch):
    """Oldest caches (resolution_stats absent entirely) → same old block
    (tables==[] fallback) and a zeroed summary; no crash."""

    def stripped(sql_text, script_name, ws_id=None):
        result = _REAL_RUN(sql_text, script_name, ws_id=ws_id)
        result.pop("resolution_stats", None)  # old-style analysis
        return result

    monkeypatch.setattr(adapter_mod, "run_full_analysis", stripped)
    ws = _make_ws({"t.sql": "SELECT id, name FROM a JOIN b ON a.x = b.y;\n"})
    try:
        result, joined = _run_capture(monkeypatch, ws, ["t.sql"])
        assert "UNRESOLVED orphans" in joined
        assert "schema candidates:" not in joined
        assert "r6 collision" not in joined
        assert result["schema_candidates_summary"] == {
            "total": 0, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC5: case-insensitive whole-name match (R4) ──────────────────────────

def test_case_insensitive_owner_and_word_boundary(monkeypatch):
    """DDL evidence `Id` resolves bare `id` (whole-name, case-folded); `id`
    never matches a `customer_id` column in the other visible table."""
    ws = _make_ws({
        "t.sql": "CREATE TABLE t (Id INT);\n",
        "u.sql": "CREATE TABLE u (customer_id INT);\n",
        "s2.sql": "SELECT id FROM t JOIN u ON t.k = u.k;\n",
    })
    try:
        result, joined = _run_capture(monkeypatch, ws,
                                      ["t.sql", "u.sql", "s2.sql"])
        assert ("schema candidates: 1 (unique visible owner found: 1)"
                " | r6 collision: 0") in joined, joined
        assert "field: id → t (evidence: s2.sql L1" in joined, joined
        assert "→ u" not in joined, "customer_id must not match id (R4)"
        assert "field: id   script: s2.sql" in joined, \
            "still reported as an orphan (REPORT ONLY)"
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 1, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── Edge: string loc (defined_in) → SQL-evidence line search ─────────────

def test_string_loc_uses_sql_evidence_search(monkeypatch):
    """A string loc (defined_in) falls back to the report's SQL-evidence
    line search — first line of the candidate script mentioning the field."""
    ws = _make_ws({
        "ddl.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "s2.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    })
    try:
        sim = _s4c_sim({
            "ddl.sql": {"script_schemas": {"web_sales": ["ws_web_page_sk"]}},
            "s2.sql": {"candidates": [{"field": "ws_web_page_sk",
                                       "visible_tables": ["web_sales", "web_page"],
                                       "loc": "defined_in"}]},
        })
        _, joined = _run_capture(monkeypatch, ws, ["ddl.sql", "s2.sql"], sim)
        assert ("field: ws_web_page_sk → web_sales (evidence: s2.sql L1"
                in joined), joined
    finally:
        delete_workspace(ws)


# ── Edge: partial new keys (mid-flight extractor) ────────────────────────

def test_script_schemas_only_still_reports_zero_line(monkeypatch):
    """New keys present but no candidate records (e.g. a mid-flight extractor
    emitting script_schemas only) → summary line still shown, zeroed — the
    report gate is key PRESENCE, not values."""

    def partial(sql_text, script_name, ws_id=None):
        result = _REAL_RUN(sql_text, script_name, ws_id=ws_id)
        rs = result.get("resolution_stats")
        if isinstance(rs, dict):
            rs = dict(rs)
            rs.pop("schema_candidates", None)
            rs.pop("r6_collision", None)
            result["resolution_stats"] = rs  # script_schemas kept
        return result

    monkeypatch.setattr(adapter_mod, "run_full_analysis", partial)
    ws = _make_ws({"ddl.sql": "CREATE TABLE t (a INT);\n"})
    try:
        result, joined = _run_capture(monkeypatch, ws, ["ddl.sql"])
        assert ("schema candidates: 0 (unique visible owner found: 0)"
                " | r6 collision: 0") in joined, joined
        assert result["schema_candidates_summary"] == {
            "total": 0, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC6: coverage_pct unchanged — Phase 1 is pure-read ───────────────────

def test_coverage_pct_unchanged_by_phase1(monkeypatch):
    """Phase 1 changes NOTHING in the attribution pipeline — every
    resolution_stats field (incl. coverage_pct) and the orphan set are
    identical whether the indexer sees the S4c keys or not."""
    entries = {
        "ddl.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "s2.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    }
    ws = _make_ws(entries)
    try:
        result_plain, _ = _run_capture(monkeypatch, ws, sorted(entries))
        sim = _s4c_sim({  # re-inject the same keys the real S4a emits
            "ddl.sql": {"script_schemas": {"web_sales": ["ws_web_page_sk"]}},
            "s2.sql": {"candidates": [{"field": "ws_web_page_sk",
                                       "visible_tables": ["web_sales", "web_page"],
                                       "loc": 1}], "r6": 0},
        })
        result_sim, _ = _run_capture(monkeypatch, ws, sorted(entries), sim)
        for k in ("total_columns", "resolved", "unresolved", "coverage_pct"):
            assert result_plain["resolution_stats"][k] == \
                result_sim["resolution_stats"][k], k
        assert (result_plain["resolution_stats"]["by_strategy"]
                == result_sim["resolution_stats"]["by_strategy"])
        assert result_plain["orphan_field_count"] == \
            result_sim["orphan_field_count"] == 1
    finally:
        delete_workspace(ws)
