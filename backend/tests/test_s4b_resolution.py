"""S4 Phase 2 — S4b index-side AUTO-RESOLUTION + M4-B degraded L1 tests.

The extractor's S4a (auto-attribution landed in parallel) emits per-script
`schema_candidates` (S4a residuals — still-unresolved bare columns in
≥2-table scopes, each carrying its OWN visible_tables), `script_schemas`
(NEW shape {table: {col: evidence_line_int}}; OLD shape {table: [cols]}
still read) and `r6_collision`. S4b (index time, cross-script) must:

- aggregate M_ws = union of all scripts' script_schemas
- re-test each candidate ONLY within its own visible_tables (never a
  workspace-global uniqueness fallback — this REPLACES the old scope-blind
  index S4 loop)
- attribute exactly-one-owner candidates: analysis-cache var + field_index /
  table_index + by_strategy["schema"] + coverage_pct
- never attribute: 0 owners (evidence absent / table not visible), ≥2
  owners (ambiguous), R6 (field == visible table)
- report the schema-EVIDENCE line (new provenance) on owner lines
- expose the `schema_candidates_summary` ({total: post-S4a, unique_owner:
  S4b additions, r6_collision})

M4-B: `_build_l1_graph`'s degraded fallback must be visible — response
`degraded: true` + an L1 diagnostic via `_push`; normal paths `degraded:
false`.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

SAMPLES_DIR = BACKEND_DIR.parent / "samples"

from app.extractor import adapter as adapter_mod
from app.services.folder_index_service import index_scripts, scan_folder
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)

_REAL_RUN = adapter_mod.run_full_analysis


def _make_ws(entries: dict) -> str:
    """Zip-upload fixture pattern (test_orphan_resolution_index.py):
    entries = {script_name: sql}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


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


def _sim(per_script: dict):
    """Inject the NEW dict-of-dicts script_schemas shape (provenance) —
    scenarios the real (old-shape) extractor in the repo can't produce yet.
    per_script: {script_name: {"script_schemas": {table: {col: line}},
                               "candidates": [...], "r6": int,
                               "stats": {extra per-script keys...}}}"""
    def wrapped(sql_text, script_name, ws_id=None):
        result = _REAL_RUN(sql_text, script_name, ws_id=ws_id)
        rs = result.get("resolution_stats")
        rs = dict(rs) if isinstance(rs, dict) else {}
        inj = per_script.get(script_name, {})
        rs["script_schemas"] = inj.get("script_schemas", rs.get("script_schemas", {}))
        rs["schema_candidates"] = inj.get("candidates",
                                          rs.get("schema_candidates", []))
        rs["r6_collision"] = inj.get("r6", rs.get("r6_collision", 0))
        # C4b: arbitrary extra per-script keys (resolved, unresolved_count,
        # coverage_pct) — the index aggregate must ignore them.
        rs.update(inj.get("stats", {}))
        result["resolution_stats"] = rs
        return result
    return wrapped


def _cache_for(ws_id, script_name: str) -> dict | None:
    """Read the analysis cache JSON for a script (matched via script_name)."""
    cache_dir = get_workspace_dir(ws_id) / "cache"
    for cf in sorted(cache_dir.glob("analysis_*.json")):
        data = json.loads(cf.read_text())
        if data.get("script_name") == script_name:
            return data
    return None


# ── TC1: cross-script S4b attribution (DDL evidence in another script) ──

def test_cross_script_ddl_evidence_attributed(monkeypatch):
    """DDL in script1 (CREATE TABLE web_sales (ws_web_page_sk INT)) + bare
    ws_web_page_sk in a 2-table scope in script2 → S4b attributes to
    web_sales: analysis-cache var, field_index/table_index,
    by_strategy["schema"] == 1, coverage reflects it."""
    ws = _make_ws({
        "ddl_tables.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                  "ON web_sales.a = web_page.b;\n"),
    })
    try:
        result, joined = _run_capture(monkeypatch, ws,
                                      ["ddl_tables.sql", "q.sql"])
        stats = result["resolution_stats"]
        assert stats["by_strategy"]["schema"] == 1, stats
        assert stats["unresolved"] == 0, stats
        assert stats["coverage_pct"] == 100.0, stats
        assert result["orphan_field_count"] == 0, result
        assert result["field_index"]["ws_web_page_sk"]["tables"] == ["web_sales"]
        assert ("field: ws_web_page_sk → web_sales (evidence:"
                in joined), joined
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 1, "r6_collision": 0}
        # persisted indexes agree
        fi = json.loads((get_workspace_dir(ws) / "cache"
                         / "field_index.json").read_text())
        ti = json.loads((get_workspace_dir(ws) / "cache"
                         / "table_index.json").read_text())
        assert fi["ws_web_page_sk"]["tables"] == ["web_sales"], fi
        assert "ws_web_page_sk" in ti["web_sales"]["fields"], ti["web_sales"]
        # analysis-cache var updated + resolution_stats consistent
        qcache = _cache_for(ws, "q.sql")
        assert qcache is not None
        var = next(v for v in qcache["variables"]
                   if v.get("variable_type") == "column"
                   and v.get("name") == "ws_web_page_sk")
        assert var["source_tables"] == ["web_sales"], var
        crs = qcache["resolution_stats"]
        assert "ws_web_page_sk" not in crs["unresolved"], crs
        assert crs["resolved_by"]["schema"] >= 1, crs
        assert crs["schema_candidates"] == [], crs
    finally:
        delete_workspace(ws)


# ── TC2: ambiguous (≥2 owners) stays unresolved ─────────────────────────

def test_two_ddl_owners_stays_unresolved():
    """Two scripts' DDL both own `id`; bare `id` in the a⋈b scope → 2
    owners → unresolved, unique_owner not counted, never attributed."""
    ws = _make_ws({
        "ddl_a.sql": "CREATE TABLE a (id INT);\n",
        "ddl_b.sql": "CREATE TABLE b (id INT);\n",
        "q.sql": "SELECT id FROM a JOIN b ON a.x = b.y;\n",
    })
    try:
        result = index_scripts(ws, ["ddl_a.sql", "ddl_b.sql", "q.sql"])
        assert result["field_index"]["id"]["tables"] == [], \
            "ambiguous — must not guess"
        assert "id" in result["orphan_field_samples"], result
        assert result["resolution_stats"]["by_strategy"]["schema"] == 0
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC3: R6 — field == visible table name, never attributed ─────────────

def test_r6_field_equals_visible_table_never_attributed():
    """`call_center` == a visible table name → r6_collision, unresolved —
    even though call_center's own DDL owns Call_Center (case-folded)."""
    ws = _make_ws({
        "ddl.sql": "CREATE TABLE call_center (Call_Center INT);\n",
        "q.sql": "SELECT call_center FROM call_center JOIN x;\n",
    })
    try:
        result = index_scripts(ws, ["ddl.sql", "q.sql"])
        assert result["field_index"]["call_center"]["tables"] == []
        assert "call_center" in result["orphan_field_samples"], result
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 0, "r6_collision": 1}
    finally:
        delete_workspace(ws)


# ── TC4: old scope-blind regression — never attribute to a table the
# ── statement doesn't reference ─────────────────────────────────────────

def test_scope_absent_evidence_never_attributed():
    """Field `id` is known only in table t1 (INSERT target column list),
    but the statement's visible tables are {a, b} — t1 is NOT referenced →
    0 visible owners → stays unresolved. (The old scope-blind S4 loop
    attributed workspace-unique t1.id here — the bug S4b replaces.)"""
    ws = _make_ws({"t.sql":
                   "INSERT INTO t1 (id) SELECT id FROM a JOIN b ON a.x = b.y;\n"})
    try:
        result = index_scripts(ws, ["t.sql"])
        assert result["field_index"]["id"]["tables"] == [], \
            "never attribute to a table the statement doesn't reference"
        assert result["orphan_field_count"] == 1, result
        assert result["resolution_stats"]["by_strategy"]["schema"] == 0
        assert result["schema_candidates_summary"] == {
            "total": 1, "unique_owner": 0, "r6_collision": 0}
    finally:
        delete_workspace(ws)


# ── TC5: report shows the schema-EVIDENCE line (new provenance) ─────────

def test_report_evidence_line_with_provenance(monkeypatch):
    """With the new {table: {col: line}} script_schemas, the owner line
    shows the DDL evidence (ddl.sql L1) plus the bare-use loc (q.sql L1)
    when it differs."""
    ws = _make_ws({
        "ddl.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "q.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    })
    try:
        sim = _sim({
            "ddl.sql": {"script_schemas":
                        {"web_sales": {"ws_web_page_sk": 1}}},
        })
        result, joined = _run_capture(monkeypatch, ws,
                                      ["ddl.sql", "q.sql"], sim)
        assert ("field: ws_web_page_sk → web_sales "
                "(evidence: ddl.sql L1, used: q.sql L1" in joined), joined
        assert result["field_index"]["ws_web_page_sk"]["tables"] == ["web_sales"]
        assert result["schema_candidates_summary"]["unique_owner"] == 1
    finally:
        delete_workspace(ws)


def test_report_evidence_line_prefers_ddl_named_script(monkeypatch):
    """Deterministic evidence selection: DDL-hint script names
    ("table"/"ddl"/"schema") win over the first alphabetical occurrence."""
    ws = _make_ws({
        "a_dml.sql": "INSERT INTO web_sales (ws_web_page_sk) SELECT x FROM s;\n",
        "z_table_defs.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "q.sql": "SELECT ws_web_page_sk FROM web_sales JOIN web_page;\n",
    })
    try:
        sim = _sim({
            "a_dml.sql": {"script_schemas":
                          {"web_sales": {"ws_web_page_sk": 7}}},
            "z_table_defs.sql": {"script_schemas":
                                 {"web_sales": {"ws_web_page_sk": 1}}},
        })
        _, joined = _run_capture(monkeypatch, ws,
                                 ["a_dml.sql", "z_table_defs.sql", "q.sql"],
                                 sim)
        # "z_table_defs" sorts last but wins (DDL-hint); "a_dml" is not a
        # hint but comes first alphabetically. N2: the line is clipped to
        # the W=80 box — the evidence fragment (script + line) survives.
        assert "z_table_defs.sql L1" in joined, joined
        assert "a_dml.sql L7" not in joined, joined
        for line in joined.split("\n"):
            if " → " in line:  # owner lines only (other Phase-1 lines may
                assert len(line) <= 80, \
                    "owner lines must not overflow the box: %r" % line
    finally:
        delete_workspace(ws)


# ── TC6: M4-B — degraded L1 fallback visible ────────────────────────────

def test_l1_degraded_fallback_visible(monkeypatch):
    """M4-B: _build_l1_graph's catch-all must return `degraded: true` (with
    the script-only fallback nodes) and push an L1 GRAPH DEGRADED diagnostic
    via _push; the normal path returns `degraded: false`."""
    from app.services.l1_builder import _build_l1_graph
    ws = _make_ws({
        "s1.sql": "CREATE TABLE t (f INT);\n",
        "s2.sql": "SELECT f FROM t;\n",
    })
    try:
        # normal path — stable contract: degraded: false
        normal = _build_l1_graph(ws, ["s1.sql", "s2.sql"], "t", "f")
        assert normal.get("degraded") is False, normal
        assert normal.get("nodes"), "normal path must still produce nodes"
        assert normal.get("target") == "t.f", normal

        # degraded path — force a failure inside the try block
        msgs = []
        monkeypatch.setattr(
            "app.services.l1_builder._push",
            lambda ws_id, stage, message: msgs.append((stage, message)))

        def boom(*args, **kwargs):
            raise RuntimeError("simulated L1 failure")

        monkeypatch.setattr(
            "app.services.multi_script_service.analyze_multiple_scripts", boom)
        degraded = _build_l1_graph(ws, ["s1.sql", "s2.sql"], "t", "f")
        assert degraded.get("degraded") is True, degraded
        assert degraded.get("nodes"), \
            "script-only fallback nodes must still be present"
        assert degraded.get("edges") == []
        assert degraded.get("target") == "t.f"
        joined = "\n".join(m for s, m in msgs if s == "profile")
        assert "L1 GRAPH DEGRADED" in joined, joined
        assert "simulated L1 failure" in joined, joined
    finally:
        delete_workspace(ws)


# ── TC7: 1b fixture corpus — sample-level never-guess validation ────────

def _ambiguous_id_zip() -> bytes:
    """Build the 1b fixture zip from samples/ambiguous_id/ (samples
    convention: directory + sibling zip)."""
    d = SAMPLES_DIR / "ambiguous_id"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(d.iterdir()):
            if fpath.is_file():
                zf.write(fpath, fpath.name)
    return buf.getvalue()


def test_ambiguous_id_corpus_never_guess():
    """samples/ambiguous_id: customers & orders both own `id`+`name`;
    products owns only `name`; inventory owns neither. Index-level:
    `id` in the 2-owner scope stays unresolved (never-guess invariant),
    `name` with a single visible owner resolves to products, coverage sane."""
    ws = create_workspace(_ambiguous_id_zip())
    try:
        result = index_scripts(ws, ["ddl_tables.sql", "q_ambiguous_id.sql",
                                    "q_single_owner.sql"])
        fi = result["field_index"]
        assert fi["id"]["tables"] == [], \
            "2-owner scope must stay unresolved (never guess)"
        assert fi["name"]["tables"] == ["products"], \
            "single visible owner must resolve"
        assert "id" in result["orphan_field_samples"], \
            "id stays reported as unresolved"
        assert "name" not in result["orphan_field_samples"], \
            "name is resolved — not an orphan"
        summary = result["schema_candidates_summary"]
        assert summary == {"total": 3, "unique_owner": 1, "r6_collision": 0}, \
            summary
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
        cp = result["resolution_stats"]["coverage_pct"]
        assert 0 < cp < 100.0, cp
        # persisted indexes agree
        pfi = json.loads((get_workspace_dir(ws) / "cache"
                          / "field_index.json").read_text())
        assert pfi["id"]["tables"] == []
        assert pfi["name"]["tables"] == ["products"]
        # E2E (review §5): the analysis-cache var was updated by S4b — the
        # real extractor's candidate for `name` now carries source_tables,
        # left the per-script unresolved list, and its candidate record was
        # removed — the full chain, real extractor → index_scripts → S4b.
        qc = _cache_for(ws, "q_single_owner.sql")
        assert qc is not None, "q_single_owner cache must exist"
        var = next(v for v in qc["variables"]
                   if v.get("variable_type") == "column"
                   and v.get("name") == "name")
        assert var["source_tables"] == ["products"], var
        crs = qc["resolution_stats"]
        assert "name" not in crs.get("unresolved", []), crs
        assert crs.get("resolved_by", {}).get("schema", 0) >= 1, crs
        assert crs.get("schema_candidates") == [], crs
    finally:
        delete_workspace(ws)


# ── Review fixes (CODE_REVIEW_2026-08-06) ────────────────────────────────

def test_l1_never_fabricate_unindexed_owner(monkeypatch):
    """Review L1: the unique visible owner must ALREADY be in table_index.
    A candidate whose only owner never appears as a table anywhere (an
    alias-resolution failure leaking an alias name) must stay unresolved —
    S4b must NOT fabricate a table_index entry for it."""
    ws = _make_ws({
        "e.sql": "SELECT 1;\n",
        "q.sql": "SELECT f FROM a JOIN b ON a.x = b.y;\n",
    })
    try:
        sim = _sim({
            "e.sql": {"script_schemas": {"ghost": {"f": 1}}},
            "q.sql": {"candidates": [{"field": "f",
                                      "visible_tables": ["ghost", "a"],
                                      "loc": 1}]},
        })
        result, _ = _run_capture(monkeypatch, ws, ["e.sql", "q.sql"], sim)
        assert "ghost" not in result["table_index"], \
            "must not fabricate an index entry for an unindexed owner"
        assert result["field_index"]["f"]["tables"] == [], \
            "unindexed owner → never attribute (never guess)"
        assert "f" in result["orphan_field_samples"], \
            "stays reported as unresolved"
        assert result["resolution_stats"]["by_strategy"]["schema"] == 0
        assert result["schema_candidates_summary"]["unique_owner"] == 0
    finally:
        delete_workspace(ws)


def test_l2_case_variant_tables_not_merged():
    """Review L2: distinct case-variant tables (Orders / orders, valid
    coexisting names on Linux MySQL) must NOT be merged by the owner check.
    Both visible, evidence under the EXACT 'Orders' → attributed to Orders,
    not ambiguous; and a scope whose visible table has no exact m_ws entry
    falls back case-insensitively to the single case variant."""
    ws = _make_ws({
        "ddl.sql": "CREATE TABLE Orders (id INT, k INT);\n"
                   "CREATE TABLE orders (name VARCHAR(10), k INT);\n",
        "q.sql": "SELECT id FROM Orders JOIN orders ON Orders.k = orders.k;\n",
    })
    try:
        result = index_scripts(ws, ["ddl.sql", "q.sql"])
        assert result["field_index"]["id"]["tables"] == ["Orders"], \
            result["field_index"]["id"]
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
        assert "id" not in result["orphan_field_samples"]
    finally:
        delete_workspace(ws)

    # fallback: the visible table has no exact m_ws entry; the single case
    # variant owns the field → resolves (exact-first, then case fallback).
    # The query must not qualify its own columns — qualified refs would
    # create an exact m_ws key for `orders` and block the fallback.
    ws2 = _make_ws({
        "ddl2.sql": "CREATE TABLE Orders (id INT, k INT);\n",
        "q2.sql": "SELECT id FROM orders, x;\n",
    })
    try:
        result2 = index_scripts(ws2, ["ddl2.sql", "q2.sql"])
        assert result2["field_index"]["id"]["tables"] == ["orders"], \
            result2["field_index"]["id"]
        assert result2["resolution_stats"]["by_strategy"]["schema"] == 1
    finally:
        delete_workspace(ws2)


# ── A1 (Item 1): DDL-file classification + schema-evidence report ────────

def _tree_node(tree: dict, name: str) -> dict | None:
    """Walk a scan_folder tree to the node whose `name` matches."""
    if tree.get("name") == name:
        return tree
    for child in tree.get("children", []):
        hit = _tree_node(child, name)
        if hit:
            return hit
    return None


def test_a1_ddl_only_sql_is_schema_evidence_not_script(monkeypatch):
    """A1: a DDL-only .sql file is file_class "schema" — never a pipeline
    script (script_count, meta.indexed_scripts, no analysis/graph caches) —
    but its DDL evidence still flows into S4b: the bare column resolves and
    the report names the DDL file as evidence."""
    ws = _make_ws({
        "ddl_only.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                  "ON web_sales.a = web_page.b;\n"),
    })
    try:
        tree = scan_folder(ws)
        assert _tree_node(tree, "ddl_only.sql")["file_class"] == "schema"
        assert _tree_node(tree, "q.sql")["file_class"] == "script"
        result, joined = _run_capture(monkeypatch, ws,
                                      ["ddl_only.sql", "q.sql"])
        assert result["script_count"] == 1, result  # DDL file is not a script
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
        assert result["field_index"]["ws_web_page_sk"]["tables"] == ["web_sales"]
        assert ("field: ws_web_page_sk → web_sales (evidence: ddl_only.sql L1"
                in joined), joined
        meta = json.loads((get_workspace_dir(ws) / "meta.json").read_text())
        assert meta["indexed_scripts"] == ["q.sql"]
        cache_dir = get_workspace_dir(ws) / "cache"
        caches = [p.name for p in cache_dir.glob("analysis_*.json")]
        assert len(caches) == 1, caches  # only q.sql — DDL file gets no cache
        graphs = [p.name for p in cache_dir.glob("graph_*.json")]
        assert len(graphs) == 1, graphs
        ev = result["schema_evidence"]
        assert ev["present"] is True and ev["tables"] >= 1 and ev["columns"] >= 1, ev
    finally:
        delete_workspace(ws)


def test_a1_ddl_only_table_absent_from_index():
    """A1: indexing a schema file alone → script_count 0 and an EMPTY
    table/field index (no filter scope or L1/L2 involvement), while
    schema_evidence still reports the DDL facts."""
    ws = _make_ws({
        "dim.ddl": "CREATE TABLE dim_date (d_date_sk INT, d_date DATE);\n",
    })
    try:
        result = index_scripts(ws, ["dim.ddl"])
        assert result["script_count"] == 0, result
        assert result["table_index"] == {}, result["table_index"]
        assert result["field_index"] == {}, result["field_index"]
        assert result["schema_evidence"] == {
            "present": True, "tables": 1, "columns": 2}, \
            result["schema_evidence"]
    finally:
        delete_workspace(ws)


def test_a1_create_plus_select_is_script():
    """A1: a .sql file mixing DDL and data statements is a pipeline script
    (classify requires EVERY top-level statement to be DDL-only). Its own
    CREATE still emits script_schemas — but through the SCRIPT path, as a
    regular pipeline script (script_count includes it)."""
    ws = _make_ws({
        "mix.sql": "CREATE TABLE t (f INT);\nSELECT f FROM t;\n",
    })
    try:
        assert _tree_node(scan_folder(ws), "mix.sql")["file_class"] == "script"
        result = index_scripts(ws, ["mix.sql"])
        assert result["script_count"] == 1, result
        # the CREATE ran inside the script — evidence merged, no separation
        assert result["schema_evidence"]["present"] is True, \
            result["schema_evidence"]
    finally:
        delete_workspace(ws)


def test_a1_ddl_extension_is_schema_even_with_query_content():
    """A1: the .ddl extension is explicit intent — content is not sniffed."""
    ws = _make_ws({"odd.ddl": "SELECT 1;\n"})
    try:
        node = _tree_node(scan_folder(ws), "odd.ddl")
        assert node["file_class"] == "schema"
        assert node["is_sql"] is True  # still surfaces in the tree
    finally:
        delete_workspace(ws)


def test_a1_old_tree_without_file_class_defaults_to_script():
    """A1 defensive read: tree nodes without file_class (pre-A1 data) are
    pipeline scripts, not schema — auto-select keeps them."""
    from app.routers.workspace import _collect_sql_files
    tree = {
        "name": "root", "type": "directory", "children": [
            {"name": "a.sql", "path": "a.sql", "type": "file", "is_sql": True},
            {"name": "b.sql", "path": "b.sql", "type": "file", "is_sql": True,
             "file_class": "schema"},
            {"name": "c.txt", "path": "c.txt", "type": "file", "is_sql": False},
        ],
    }
    assert _collect_sql_files(tree) == ["a.sql"]


def test_a1_no_ddl_workspace_evidence_shape_false():
    """A1 response contract: a workspace without DDL reports
    schema_evidence {present: False, tables: 0, columns: 0}."""
    ws = _make_ws({"a.sql": "SELECT 1;\n"})
    try:
        result = index_scripts(ws, ["a.sql"])
        assert result["schema_evidence"] == {
            "present": False, "tables": 0, "columns": 0}, \
            result["schema_evidence"]
    finally:
        delete_workspace(ws)


def test_a1_auto_select_discovery_keeps_evidence(monkeypatch):
    """A1: when the caller's script list EXCLUDES the DDL file (the
    auto-select path does), the index-time discovery pass still merges its
    evidence — S4b resolution must not depend on caller selection."""
    ws = _make_ws({
        "ddl_only.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
        "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                  "ON web_sales.a = web_page.b;\n"),
    })
    try:
        result, joined = _run_capture(monkeypatch, ws, ["q.sql"])
        assert result["script_count"] == 1, result
        assert result["resolution_stats"]["by_strategy"]["schema"] == 1
        assert result["field_index"]["ws_web_page_sk"]["tables"] == ["web_sales"]
        assert result["schema_evidence"]["present"] is True
        assert "ddl_only.sql L1" in joined, joined
    finally:
        delete_workspace(ws)


# ── C3 (Item 2): shared graph-cache prefix constant ──────────────────────

def test_c3_shared_graph_cache_prefix():
    """C3: every reader/writer of the graph cache uses the SAME constant —
    a format-version bump is a one-line change, and the index-time writer
    (folder_index_service) can never drift from the L2 reader's name."""
    from app.services import cache_keys
    from app.services import dataflow_service as dfs
    from app.services import folder_index_service as fis
    prefix = cache_keys.GRAPH_CACHE_PREFIX
    assert prefix.startswith("graph_"), prefix
    assert fis.GRAPH_CACHE_PREFIX == prefix
    assert dfs.GRAPH_CACHE_PREFIX == prefix


# ── C4b (Item 3): aggregate coverage must NOT sum per-script keys ────────

def test_c4b_aggregate_ignores_per_script_resolution_keys(monkeypatch):
    """C4b: the extractor's additive per-script keys (resolved,
    unresolved_count, coverage_pct) must NOT feed the index aggregate —
    aggregate coverage stays 1 − unresolved/total_columns over the UNION of
    per-script unresolved lists. Injected bogus per-script values
    (resolved=999, coverage_pct=100) must not move it."""
    ws = _make_ws({
        "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                  "ON web_sales.a = web_page.b;\n"),
    })
    try:
        sim = _sim({
            "q.sql": {"stats": {"resolved": 999, "unresolved_count": 0,
                                "coverage_pct": 100.0}},
        })
        result, _ = _run_capture(monkeypatch, ws, ["q.sql"], sim)
        stats = result["resolution_stats"]
        tc = stats["total_columns"]
        assert tc >= 1, stats
        assert stats["unresolved"] == 1, stats  # ws_web_page_sk stays orphaned
        assert stats["resolved"] == tc - 1, stats  # NOT the injected 999
        expected = round((tc - 1) / tc * 100, 1)
        assert stats["coverage_pct"] == expected, stats  # NOT injected 100.0
        # the injected keys live in the per-script cache, untouched
        qc = _cache_for(ws, "q.sql")
        assert qc["resolution_stats"]["coverage_pct"] == 100.0, qc
        assert qc["resolution_stats"]["resolved"] == 999, qc
    finally:
        delete_workspace(ws)
