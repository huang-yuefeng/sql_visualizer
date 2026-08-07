"""C-series index-pipeline fixes (Team 2, 2026-08-06) — folder_index_service.

- C-1: `CREATE TABLE … AS SELECT` (CTAS) is a pipeline script, never
  schema DDL — `classify_sql_text` returns "script" before the kind-set
  check (plain CREATE TABLE / CREATE TABLE LIKE keep expression=None →
  schema; VIEW/MATVIEW untouched).
- C-2(a): after the S4b pass, every graph cache in the workspace cache
  dir is deleted (index-time precompute ran pre-S4b; only analysis
  caches carry the S4b mutations) — old AND new GRAPH_CACHE_PREFIX files
  (graph_3_*_*.json shape), never schemas_*/analysis_*/filtered_index.
  GRAPH_CACHE_PREFIX bumped to graph_3_2_17.
- C-3: ambiguous-field revocation mirrors `_apply_s4b_cache_update` into
  the persisted analysis caches (vars cleared, unresolved re-added with
  membership guard, schema counter dropped floor 0, gated on a real
  revocation event — C-4); the cross-run case (field absent from the
  current field_index) iterates every analysis cache with owner=None.
- C-5: post-loop star expansion — unqualified `SELECT * FROM t` /
  `INSERT INTO x SELECT * FROM t` expand each schema-evidence column of
  t into field_index/table_index; no evidence → silent skip (no
  padding); qualified stars (t.*) are the extractor's domain.
- C-13(a): each script is parsed exactly once at index time — scan_folder
  parses and reuses the parse for classification (exported to
  index_scripts, which reuses it for classification AND star detection).
"""

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import sqlglot
from sqlglot import exp

from app.services import cache_keys
from app.services import folder_index_service as fis
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)


def _make_ws(entries: dict) -> str:
    """Zip-upload fixture pattern (test_s4b_resolution.py): entries =
    {script_name: sql}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _cache_for(ws_id: str, script_name: str):
    """Read the analysis cache JSON for a script (matched via script_name)."""
    cache_dir = get_workspace_dir(ws_id) / "cache"
    for cf in sorted(cache_dir.glob("analysis_*.json")):
        data = json.loads(cf.read_text())
        if data.get("script_name") == script_name:
            return data, cf
    return None, None


def _find_node(tree: dict, name: str):
    if tree.get("name") == name:
        return tree
    for child in tree.get("children", []):
        hit = _find_node(child, name)
        if hit:
            return hit
    return None


# ══════════════════════════════════════════════════════════════════════
# C-1: CTAS → script (classification matrix)
# ══════════════════════════════════════════════════════════════════════

class TestC1CtasClassification:
    @pytest.mark.parametrize("sql", [
        "CREATE TABLE x AS SELECT a FROM t;\n",
        "CREATE TABLE IF NOT EXISTS x AS SELECT a FROM t;\n",
        "CREATE TABLE x AS (SELECT 1) UNION ALL (SELECT 2);\n",
        "INSERT INTO x SELECT a FROM t;\n",
        "SELECT a FROM t;\n",
    ])
    def test_classified_script(self, sql):
        """CTAS (any shape) and data statements → script."""
        assert fis.classify_sql_text(sql) == "script"

    @pytest.mark.parametrize("sql", [
        "CREATE TABLE x (a INT);\n",
        "CREATE TABLE x LIKE y;\n",
        "CREATE TABLE IF NOT EXISTS x (a INT);\n",
        "CREATE TABLE x (a INT);\nCREATE TABLE y (b INT);\n",
        "CREATE VIEW v AS SELECT a FROM t;\n",
        "CREATE MATERIALIZED VIEW v AS SELECT a FROM t;\n",
        "GRANT SELECT ON t TO u;\n",
        "ALTER TABLE t ADD COLUMN c INT;\n",
        "COMMENT ON TABLE t IS 'x';\n",
    ])
    def test_classified_schema(self, sql):
        """Plain CREATE TABLE / LIKE, CREATE VIEW, MATVIEW and DDL-only
        statements → schema (C-1 must not flip these)."""
        assert fis.classify_sql_text(sql) == "schema"

    def test_ctas_mixed_file_is_script(self):
        """A CTAS anywhere in the file makes it a pipeline script."""
        assert fis.classify_sql_text(
            "CREATE TABLE x (a INT);\nCREATE TABLE y AS SELECT a FROM x;\n"
        ) == "script"

    def test_ctas_indexed_as_pipeline_script(self):
        """End-to-end: a CTAS .sql file is indexed as a script — its body
        flows through run_full_analysis (tables/fields indexed, evidence
        preserved), instead of silently vanishing as a "schema" file."""
        ws = _make_ws({"ctas.sql":
                       "CREATE TABLE x AS SELECT a FROM t;\n"})
        try:
            tree = fis.scan_folder(ws)
            assert _find_node(tree, "ctas.sql")["file_class"] == "script"
            result = fis.index_scripts(ws, ["ctas.sql"])
            assert result["script_count"] == 1, result
            assert "t" in result["table_index"], result["table_index"]
            assert result["field_index"]["a"]["tables"] == ["t"], \
                result["field_index"]
            meta = json.loads((get_workspace_dir(ws) / "meta.json").read_text())
            assert meta["indexed_scripts"] == ["ctas.sql"], meta
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# C-2(a): graph-cache invalidation after the S4b pass + prefix bump
# ══════════════════════════════════════════════════════════════════════

class TestC2GraphCacheInvalidation:
    def test_graph_cache_prefix_bumped(self):
        """C-2: GRAPH_CACHE_PREFIX is bumped to graph_3_2_18 (v3.3.140) —
        the bump is the single-constant invalidation; the name/format is
        unchanged."""
        assert cache_keys.GRAPH_CACHE_PREFIX == "graph_3_2_18", \
            cache_keys.GRAPH_CACHE_PREFIX
        assert fis.GRAPH_CACHE_PREFIX == cache_keys.GRAPH_CACHE_PREFIX

    def test_index_deletes_stale_graph_caches_keeps_other_artifacts(self):
        """After the S4b pass, every graph cache — OLD prefix (3_2_16) and
        NEW prefix (3_2_17) — is deleted; schemas_*, analysis_* and
        filtered_index.json survive. Fixture exercises a real S4b
        attribution (schema counter == 1) so the graphs written during
        the per-script loop are genuinely pre-S4b."""
        ws = _make_ws({
            "ddl.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
            "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                      "ON web_sales.a = web_page.b;\n"),
        })
        try:
            cache_dir = get_workspace_dir(ws) / "cache"
            (cache_dir / "graph_3_2_16_deadbeef.json").write_text("{}")
            (cache_dir / "graph_3_2_17_deadbeef.json").write_text("{}")
            (cache_dir / "schemas_deadbeef.json").write_text("{}")
            (cache_dir / "analysis_deadbeef.json").write_text("{}")
            (cache_dir / "filtered_index.json").write_text("{}")
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            assert result["resolution_stats"]["by_strategy"]["schema"] == 1
            assert result["script_count"] == 1, result
            names = {p.name for p in cache_dir.glob("*.json")}
            assert not any(n.startswith("graph_3_") for n in names), \
                "graph caches must be gone after indexing: %s" % sorted(names)
            assert "schemas_deadbeef.json" in names, names
            assert "analysis_deadbeef.json" in names, names
            assert "filtered_index.json" in names, names
        finally:
            delete_workspace(ws)

    def test_no_graph_caches_after_index_even_without_s4b(self):
        """The invalidation is unconditional — a workspace with no S4b
        activity also ends up with zero graph caches (the analysis caches
        — the S4b-mutated source of truth — survive)."""
        ws = _make_ws({"a.sql": "SELECT a FROM t;\n"})
        try:
            result = fis.index_scripts(ws, ["a.sql"])
            # Index no longer precomputes graph caches at all (C-2: any
            # index-time graph would be pre-S4b and stale) — the counter is
            # kept for API-shape stability and is always 0 now.
            assert result["precomputed_count"] == 0, result
            cache_dir = get_workspace_dir(ws) / "cache"
            assert not list(cache_dir.glob("graph_3_*.json")), \
                "no graph cache may survive indexing"
            assert list(cache_dir.glob("analysis_*.json")), \
                "analysis caches must survive"
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# C-3: S4b revocation mirrored into the persisted analysis caches
# ══════════════════════════════════════════════════════════════════════

class TestC3RevocationMirror:
    def test_ambiguous_revoke_clears_cache_attribution(self):
        """a.sql: S1 resolves f → a (cache var f has source_tables=[a]);
        ddl_c owns f; q2 claims f → c in {c, d} → owner conflict →
        AMBIGUOUS: the a.sql analysis-cache var loses its attribution,
        f returns to the cache's unresolved list (membership guard)."""
        ws = _make_ws({
            "a.sql": "SELECT f FROM a;\n",
            "ddl_c.sql": "CREATE TABLE c (f INT);\n",
            "q2.sql": "SELECT f FROM c JOIN d ON c.k = d.k;\n",
        })
        try:
            result = fis.index_scripts(ws, ["a.sql", "ddl_c.sql", "q2.sql"])
            stats = result["resolution_stats"]
            assert stats["ambiguous"] == 1, stats
            assert result["field_index"]["f"]["tables"] == [], \
                result["field_index"]["f"]
            acache, _ = _cache_for(ws, "a.sql")
            assert acache is not None, "a.sql analysis cache must exist"
            fvar = next(v for v in acache["variables"]
                        if v.get("variable_type") == "column"
                        and v.get("name") == "f")
            assert fvar["source_tables"] == [], fvar
            assert "f" in acache["resolution_stats"]["unresolved"], \
                acache["resolution_stats"]
            # the conflicting claim's script was never touched (no-op)
            q2cache, _ = _cache_for(ws, "q2.sql")
            q2var = next(v for v in q2cache["variables"]
                         if v.get("variable_type") == "column"
                         and v.get("name") == "f")
            assert q2var["source_tables"] == [], q2var
        finally:
            delete_workspace(ws)

    def test_ambiguous_after_reindex_revokes_prior_attribution(self):
        """Cross-run persistence: run 1 attributes f → a (q1's extraction
        + ddl_a evidence). Run 2 adds ddl_c + q2 — a plan claiming f → c
        (different owner than the existing index attribution) → ambiguous:
        the field_index entry is cleared AND the prior run's cache
        attribution (q1's var f → a) is revoked and f returns to the
        unresolved pool."""
        ws = _make_ws({
            "ddl_a.sql": "CREATE TABLE a (f INT);\n",
            "q1.sql": "SELECT f FROM a;\n",
        })
        try:
            r1 = fis.index_scripts(ws, ["ddl_a.sql", "q1.sql"])
            assert r1["field_index"]["f"]["tables"] == ["a"], \
                r1["field_index"]["f"]
            ws_dir = get_workspace_dir(ws)
            (ws_dir / "scripts" / "ddl_c.sql").write_text(
                "CREATE TABLE c (f INT);\n")
            (ws_dir / "scripts" / "q2.sql").write_text(
                "SELECT f FROM c JOIN d ON c.k = d.k;\n")
            r2 = fis.index_scripts(ws,
                                   ["ddl_a.sql", "ddl_c.sql",
                                    "q1.sql", "q2.sql"])
            assert r2["resolution_stats"]["ambiguous"] == 1, \
                r2["resolution_stats"]
            assert r2["field_index"]["f"]["tables"] == [], \
                r2["field_index"]["f"]
            q1cache, _ = _cache_for(ws, "q1.sql")
            fvar = next(v for v in q1cache["variables"]
                        if v.get("variable_type") == "column"
                        and v.get("name") == "f")
            assert fvar["source_tables"] == [], fvar
            assert "f" in q1cache["resolution_stats"]["unresolved"]
            q2cache, _ = _cache_for(ws, "q2.sql")
            q2var = next(v for v in q2cache["variables"]
                         if v.get("variable_type") == "column"
                         and v.get("name") == "f")
            assert q2var["source_tables"] == [], q2var
        finally:
            delete_workspace(ws)

    def test_revoke_helper_cross_run_semantics(self):
        """_revoke_s4b_cache_update with owner=None (the cross-run case —
        field absent from the current field_index, prior-run attribution
        only): clears ANY owner's attribution, re-adds the field to
        unresolved, drops resolved_by["schema"] (floor 0) and removes the
        field's schema_candidates records — mirroring the apply."""
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            cache_dir = get_workspace_dir(ws) / "cache"
            cache_path = cache_dir / "analysis_prior.json"
            cache_path.write_text(json.dumps({
                "script_name": "prior.sql",
                "variables": [
                    {"id": "v1", "name": "f", "variable_type": "column",
                     "source_tables": ["a"], "context": "TOP"},
                ],
                "resolution_stats": {
                    "total_columns": 3,
                    "unresolved": ["g"],
                    "resolved_by": {"schema": 1, "plain_alias": 2},
                    "schema_candidates": [
                        {"field": "f", "visible_tables": ["a", "b"], "loc": 1},
                    ],
                },
            }))
            n = fis._revoke_s4b_cache_update(str(cache_path), "f", None)
            assert n == 1, n
            cdata = json.loads(cache_path.read_text())
            assert cdata["variables"][0]["source_tables"] == []
            rs = cdata["resolution_stats"]
            assert "f" in rs["unresolved"], rs
            assert rs["resolved_by"]["schema"] == 0, rs
            assert rs["schema_candidates"] == [], rs
        finally:
            delete_workspace(ws)

    def test_revoke_noop_does_not_touch_counters(self):
        """C-4: a revoke that clears no var (already un-attributed field)
        must not move the persisted counters or rewrite the cache — the
        in-memory n_attributed gate mirrored."""
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            cache_dir = get_workspace_dir(ws) / "cache"
            cache_path = cache_dir / "analysis_prior.json"
            payload = {
                "script_name": "prior.sql",
                "variables": [
                    {"id": "v1", "name": "f", "variable_type": "column",
                     "source_tables": [], "context": "TOP"},
                ],
                "resolution_stats": {
                    "total_columns": 3,
                    "unresolved": ["f"],
                    "resolved_by": {"schema": 0},
                    "schema_candidates": [
                        {"field": "f", "visible_tables": ["a", "b"], "loc": 1},
                    ],
                },
            }
            cache_path.write_text(json.dumps(payload))
            before = cache_path.read_text()
            n = fis._revoke_s4b_cache_update(str(cache_path), "f", "a")
            assert n == 0, n
            assert cache_path.read_text() == before, \
                "no-op revoke must not rewrite the cache"
            cdata = json.loads(before)
            assert cdata["resolution_stats"]["resolved_by"]["schema"] == 0
            assert cdata["resolution_stats"]["unresolved"] == ["f"]
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# C-4: apply-side gate — a context-mismatch no-op never moves counters
# ══════════════════════════════════════════════════════════════════════

class TestC4ApplyGate:
    def test_apply_context_mismatch_noop_does_not_touch_counters(self):
        """C-4 (apply side): an attribution whose var contexts do not
        include the candidate's recorded contexts (M13 — the var was seen
        in a scope where the owner was NOT visible) modifies no var:
        n_attributed == 0. The persisted `unresolved` list and
        `resolved_by["schema"]` must NOT move and the cache must not be
        rewritten — the mirror of the revoke-side `n_revoked > 0` gate."""
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            cache_dir = get_workspace_dir(ws) / "cache"
            cache_path = cache_dir / "analysis_prior.json"
            crec = {"field": "f", "visible_tables": ["a", "b"], "loc": 1,
                    "contexts": ["TOP1"]}
            payload = {
                "script_name": "prior.sql",
                "variables": [
                    {"id": "v1", "name": "f", "variable_type": "column",
                     "source_tables": [], "context": "TOP0"},
                ],
                "resolution_stats": {
                    "total_columns": 3,
                    "unresolved": ["f"],
                    "resolved_by": {"schema": 0, "plain_alias": 2},
                    "schema_candidates": [dict(crec)],
                },
            }
            cache_path.write_text(json.dumps(payload))
            before = cache_path.read_text()
            n = fis._apply_s4b_cache_update(str(cache_path), "f", "a",
                                            ["a", "b"], crec)
            assert n == 0, n
            assert cache_path.read_text() == before, \
                "no-op apply must not rewrite the cache"
            rs = json.loads(before)["resolution_stats"]
            assert "f" in rs["unresolved"], rs
            assert rs["resolved_by"]["schema"] == 0, rs
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# C-5: post-loop star expansion (search visibility for SELECT *)
# ══════════════════════════════════════════════════════════════════════

class TestC5StarExpansion:
    def test_select_star_expands_visible_columns(self):
        """DDL orders(order_id, amount) + `SELECT * FROM orders` → the
        star's schema-evidence columns land in field_index/table_index and
        a search for orders.order_id finds the script (the pre-C-5 silent
        vanish)."""
        ws = _make_ws({
            "ddl.sql":
                "CREATE TABLE orders (order_id INT, amount DECIMAL(10,2));\n",
            "q.sql": "SELECT * FROM orders;\n",
        })
        try:
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            fi = result["field_index"]
            assert "order_id" in fi, fi.keys()
            assert "orders" in fi["order_id"]["tables"], fi["order_id"]
            assert "q.sql" in fi["order_id"]["scripts"], fi["order_id"]
            assert "orders" in fi["amount"]["tables"], fi["amount"]
            assert "order_id" in result["table_index"]["orders"]["fields"]
            assert result["star_expanded_fields"] == 2, result
            # persisted indexes agree (search consumes the disk index)
            cache_dir = get_workspace_dir(ws) / "cache"
            ti = json.loads((cache_dir / "table_index.json").read_text())
            fi2 = json.loads((cache_dir / "field_index.json").read_text())
            assert fi2["order_id"]["scripts"] == ["q.sql"], fi2["order_id"]
            from app.services.dataflow_service import create_search
            sr = asyncio.run(create_search(ws, "orders", "order_id", ti, fi2))
            assert sr["match_mode"] == "exact", sr
            assert "q.sql" in sr["script_ids"], sr
        finally:
            delete_workspace(ws)

    def test_insert_select_star_expands(self):
        """`INSERT INTO x SELECT * FROM orders` — the mandated second
        shape — expands the same way."""
        ws = _make_ws({
            "ddl.sql":
                "CREATE TABLE orders (order_id INT, amount DECIMAL(10,2));\n",
            "q.sql": ("INSERT INTO daily (order_id, amount) "
                      "SELECT * FROM orders;\n"),
        })
        try:
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            fi = result["field_index"]
            assert "order_id" in fi, fi.keys()
            assert "q.sql" in fi["order_id"]["scripts"], fi["order_id"]
            assert "orders" in fi["amount"]["tables"], fi["amount"]
            assert result["star_expanded_fields"] == 2, result
        finally:
            delete_workspace(ws)

    def test_star_without_schema_evidence_skipped(self):
        """No DDL for t → `SELECT * FROM t` adds nothing (no padding) —
        BE2 intact: the search for t.<any column> stays no_matches."""
        ws = _make_ws({"q.sql": "SELECT * FROM t;\n"})
        try:
            result = fis.index_scripts(ws, ["q.sql"])
            assert result["star_expanded_fields"] == 0, result
            assert result["field_index"] == {}, result["field_index"]
            cache_dir = get_workspace_dir(ws) / "cache"
            ti = json.loads((cache_dir / "table_index.json").read_text())
            fi = json.loads((cache_dir / "field_index.json").read_text())
            from app.services.dataflow_service import create_search
            sr = asyncio.run(create_search(ws, "t", "order_id", ti, fi))
            assert sr["match_mode"] == "no_matches", sr
            assert "not queried by any script" in sr["message"], sr
        finally:
            delete_workspace(ws)

    def test_qualified_star_not_double_expanded(self):
        """`t.*` is the extractor's domain (its _expand_star_columns) —
        the index pass detects only UNQUALIFIED stars and adds nothing."""
        ws = _make_ws({
            "ddl.sql": "CREATE TABLE orders (order_id INT);\n",
            "q.sql": "SELECT orders.* FROM orders;\n",
        })
        try:
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            assert result["star_expanded_fields"] == 0, result
        finally:
            delete_workspace(ws)

    def test_join_and_multi_table_star_expands_all_tables(self):
        """`SELECT * FROM a JOIN b` expands the evidence columns of BOTH
        FROM tables."""
        ws = _make_ws({
            "ddl.sql": ("CREATE TABLE a (id INT, k INT);\n"
                        "CREATE TABLE b (bid INT, k INT);\n"),
            "q.sql": "SELECT * FROM a JOIN b ON a.k = b.k;\n",
        })
        try:
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            fi = result["field_index"]
            assert "a" in fi["id"]["tables"], fi["id"]
            assert "b" in fi["bid"]["tables"], fi["bid"]
            assert result["star_expanded_fields"] == 4, result
        finally:
            delete_workspace(ws)

    def test_star_does_not_resurrect_revoked_field(self):
        """C-5↔C-3: a field S4b revoked as ambiguous (claimed by two
        different owners — a.sql's S1 attribution vs q2's c-owner claim)
        must NOT re-enter field_index via star expansion: q3's
        `SELECT * FROM c` runs AFTER the S4b pass, and the post-loop star
        expansion must skip the revoked field instead of resurrecting it
        into field_index/table_index/pair_index."""
        ws = _make_ws({
            "a.sql": "SELECT f FROM a;\n",
            "ddl_c.sql": "CREATE TABLE c (f INT);\n",
            "q2.sql": "SELECT f FROM c JOIN d ON c.k = d.k;\n",
            "q3.sql": "SELECT * FROM c;\n",
        })
        try:
            result = fis.index_scripts(ws,
                                       ["a.sql", "ddl_c.sql", "q2.sql",
                                        "q3.sql"])
            stats = result["resolution_stats"]
            assert stats["ambiguous"] == 1, stats
            fi = result["field_index"]
            assert fi["f"]["tables"] == [], fi["f"]
            assert "q3.sql" not in fi["f"]["scripts"], fi["f"]
            assert "f" not in result["table_index"].get("c", {}) \
                .get("fields", []), result["table_index"]
            # the star pass still expands NON-revoked evidence columns — k
            # (c's evidence via q2's qualified ref c.k) lands under c with
            # q3.sql attached; only the revoked f is excluded.
            assert "q3.sql" in fi["k"]["scripts"], fi["k"]
            assert result["star_expanded_fields"] == 1, result
            # persisted indexes agree (search consumes the disk index)
            cache_dir = get_workspace_dir(ws) / "cache"
            fi2 = json.loads((cache_dir / "field_index.json").read_text())
            assert fi2["f"]["tables"] == [], fi2["f"]
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# C-13(a): one parse per script at index time
# ══════════════════════════════════════════════════════════════════════

class TestC13SingleParse:
    def test_scan_folder_parses_each_file_once(self, monkeypatch):
        """scan_folder must call sqlglot.parse exactly once per .sql file
        (the parse is reused for classification) — .ddl/.schema extensions
        short-circuit without parsing, non-SQL files never parse."""
        ws = _make_ws({
            "a.sql": "SELECT 1;\n",
            "b.sql": "CREATE TABLE x (c INT);\n",
            "c.ddl": "CREATE TABLE y (d INT);\n",
            "d.txt": "not sql",
        })
        try:
            calls = []
            real_parse = fis.sqlglot.parse

            def counting_parse(*args, **kwargs):
                calls.append(args)
                return real_parse(*args, **kwargs)

            monkeypatch.setattr(fis.sqlglot, "parse", counting_parse)
            tree = fis.scan_folder(ws)
            assert len(calls) == 2, \
                "expected exactly 2 parses (a.sql, b.sql), got %d" % len(calls)
            assert _find_node(tree, "a.sql")["file_class"] == "script"
            assert _find_node(tree, "b.sql")["file_class"] == "schema"
            assert _find_node(tree, "c.ddl")["file_class"] == "schema"
        finally:
            delete_workspace(ws)

    def test_classify_sql_text_reuses_provided_parse(self, monkeypatch):
        """classify_sql_text with `parsed=` performs no parse of its own."""
        parsed = sqlglot.parse("SELECT 1;", read="mysql")
        parsed_ddl = sqlglot.parse("CREATE TABLE x (a INT);", read="mysql")
        calls = []

        def boom(*args, **kwargs):
            calls.append(args)
            raise AssertionError("must not parse when parsed= is given")

        monkeypatch.setattr(fis.sqlglot, "parse", boom)
        assert fis.classify_sql_text("SELECT 1;", parsed=parsed) == "script"
        assert calls == []
        assert fis.classify_sql_text("CREATE TABLE x (a INT);",
                                     parsed=parsed_ddl) == "schema"
        assert calls == []

    def test_classify_sql_file_reuses_provided_parse(self, monkeypatch):
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            sp = get_workspace_dir(ws) / "scripts" / "a.sql"
            parsed = sqlglot.parse("SELECT 1;", read="mysql")
            calls = []

            def boom(*args, **kwargs):
                calls.append(args)
                raise AssertionError("must not parse when parsed= is given")

            monkeypatch.setattr(fis.sqlglot, "parse", boom)
            assert fis.classify_sql_file(sp, parsed=parsed) == "script"
            assert calls == []
        finally:
            delete_workspace(ws)

    def test_index_loop_reuses_scan_parse(self, monkeypatch):
        """Every classify_sql_text call during index_scripts (scan + loop)
        receives the shared per-script parse — never re-parses."""
        ws = _make_ws({
            "ddl.sql": "CREATE TABLE web_sales (ws_web_page_sk INT);\n",
            "q.sql": ("SELECT ws_web_page_sk FROM web_sales JOIN web_page "
                      "ON web_sales.a = web_page.b;\n"),
        })
        try:
            seen = []
            real_classify = fis.classify_sql_text

            def wrap(sql_text, parsed=None):
                seen.append(parsed is not None)
                return real_classify(sql_text, parsed=parsed)

            monkeypatch.setattr(fis, "classify_sql_text", wrap)
            result = fis.index_scripts(ws, ["ddl.sql", "q.sql"])
            assert result["script_count"] == 1, result
            assert seen and all(seen), \
                "every classification must reuse the parsed=%r parse" % seen
        finally:
            delete_workspace(ws)
