"""S4 Phase 2 (AUTO-RESOLUTION) tests — index-side S4b attribution + report.

The extractor's S4a (auto-attribution) emits per-script
`schema_candidates` (S4a residuals — still-unresolved bare columns in
≥2-table scopes, each carrying its OWN visible_tables) / `script_schemas`
(NEW {table: {col: evidence_line}} — OLD list shape handled too) /
`r6_collision` inside `resolution_stats`; the index side (S4b Phase 2)
must:

- aggregate M_ws = union of all scripts' script_schemas
- re-test each candidate ONLY within its own visible_tables: owners =
  visible(field) ∩ M_ws (whole-name, case-insensitive = R4; R6
  field==table guard) — exactly one owner → ATTRIBUTE (analysis-cache var,
  field_index/table_index, by_strategy["schema"], coverage)
- never attribute: 0 owners (evidence absent / table not visible), ≥2
  owners (ambiguous), R6
- extend the ORPHAN RESOLUTION REPORT (summary line + per-owner lines with
  the schema-EVIDENCE line from the new provenance)
- expose `schema_candidates_summary` on the index response
- stay byte-identical on old caches (keys absent)

Most tests use the REAL extractor output; the run_full_analysis wrapper
(`_s4c_sim`) is used only where a scenario cannot be produced by the real
extractor: string locs, partial keys, old-style stripping, and the new
dict-of-dicts provenance shape.
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


# ── TC1: cross-script unique owner (Phase 2: ATTRIBUTED) ────────────────

def test_cross_script_unique_owner_attributed(monkeypatch):
    """Bare column in a 2-table scope; the owner's schema evidence lives in
    ANOTHER script (DML target list, design source 2) → S4b attributes:
    field_index/table_index updated, by_strategy["schema"] +1, the field
    leaves the orphan set, and the report shows the owner line. The
    evidence script must be evidence-only (DDL/DML list) — a qualified ref
    in the same workspace would already attribute via S1.
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
        assert ("field: ws_web_page_sk → web_sales (evidence:"
                in joined), joined
        # Phase 2: the field is resolved — no longer an orphan
        assert "UNRESOLVED orphans — possible bad cases, check SQL:" not in joined
        fi = json.loads((get_workspace_dir(ws) / "cache"
                         / "field_index.json").read_text())
        assert fi["ws_web_page_sk"]["tables"] == ["web_sales"], \
            "S4b must attribute the unique visible owner"
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
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
        assert "field: id → t (evidence:" in joined, joined
        assert "→ u" not in joined, "customer_id must not match id (R4)"
        # Phase 2: attributed to t, so it leaves the UNRESOLVED section
        assert "field: id   script: s2.sql" not in joined, \
            "resolved by S4b — must not stay in the UNRESOLVED section"
        fi = json.loads((get_workspace_dir(ws) / "cache"
                         / "field_index.json").read_text())
        assert fi["id"]["tables"] == ["t"], fi["id"]
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
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

def test_partial_s4_keys_fall_back_to_old_report(monkeypatch):
    """Review N3: the Phase-2 report gate requires ALL THREE S4 keys
    (schema_candidates, script_schemas, r6_collision) in the same analysis.
    A partially-upgraded cache (script_schemas only — mid-flight extractor)
    must keep the byte-identical Phase-1 block instead of printing a
    misleading zeroed 'schema candidates' line; the response summary stays
    zeroed."""

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
    ws = _make_ws({"t.sql":
                   "INSERT INTO a (id, name) SELECT p, q FROM src1;\n"
                   "INSERT INTO b (id, name) SELECT r, s FROM src2;\n"
                   "SELECT id, name FROM a JOIN b ON a.x = b.y;\n"})
    try:
        result, joined = _run_capture(monkeypatch, ws, ["t.sql"])
        assert "schema candidates:" not in joined, joined
        assert "r6 collision" not in joined, joined
        assert "UNRESOLVED orphans" in joined, joined
        assert "field: id   script: t.sql" in joined, joined
        assert result["schema_candidates_summary"] == {
            "total": 0, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


def test_all_three_keys_zeroed_line(monkeypatch):
    """All three S4 keys present (empty values — the S4a extractor's default
    emission on every script) → the Phase-2 line is shown, zeroed."""
    ws = _make_ws({"ddl.sql": "CREATE TABLE t (a INT);\n"})
    try:
        result, joined = _run_capture(monkeypatch, ws, ["ddl.sql"])
        assert ("schema candidates: 0 (unique visible owner found: 0)"
                " | r6 collision: 0") in joined, joined
        assert result["schema_candidates_summary"] == {
            "total": 0, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC6: S4b behavior is key-source-independent (real vs injected) ───────

def test_s4b_result_independent_of_key_source(monkeypatch):
    """S4b resolves the cross-script unique owner identically whether the
    S4a keys come from the real extractor or are injected by the sim — the
    indexer's attribution pipeline is deterministic. Both runs must end at
    the same stats, and the field must be resolved (Phase 2)."""
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
            result_sim["orphan_field_count"] == 0, \
            "S4b resolves the unique visible owner (Phase 2)"
        assert (result_plain["resolution_stats"]["by_strategy"]["schema"] == 1)
    finally:
        delete_workspace(ws)
