"""Folder index service — scan directory tree, build table/field indexes."""
import json
import threading
from pathlib import Path

import sqlglot
from sqlglot import exp

from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.services.workspace_service import get_workspace_dir, get_script_path
from app.services.logger import _push
from app.services.filter_service import resolve_script

SQL_EXTENSIONS = {".sql"}
# A1: extensions that are DDL by explicit intent — always classified schema
# (content is not sniffed for these).
SCHEMA_EXTENSIONS = {".ddl", ".schema"}
# A1: CREATE kinds that are schema-only statements (kind string from
# sqlglot exp.Create). CREATE MATERIALIZED VIEW also reports kind="VIEW" —
# it is detected via its MaterializedProperty (see classify_sql_text).
_SCHEMA_CREATE_KINDS = {"TABLE", "VIEW"}


def classify_sql_file(filepath: Path, parsed=None) -> str:
    """Classify a SQL file as "schema" (DDL-only) or "script" (pipeline).

    A1 rules: .ddl / .schema extensions → schema (explicit intent, content
    ignored). .sql → content sniff via sqlglot (MySQL dialect — the same
    dialect the extractor uses): schema iff EVERY top-level statement is
    CREATE TABLE / CREATE VIEW / CREATE MATERIALIZED VIEW / GRANT /
    COMMENT / ALTER TABLE (i.e. no data statements outside view bodies);
    otherwise script. Parse failures and empty files default to script
    (conservative — never guess a file away from the pipeline).

    C-13(a): callers that already hold the sqlglot parse for this file
    (scan_folder — one parse per file, reused) pass it as `parsed` so the
    classifier never re-parses.
    """
    if filepath.suffix.lower() in SCHEMA_EXTENSIONS:
        return "schema"
    try:
        sql_text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "script"  # unreadable file → script (conservative, never guess DDL)
    return classify_sql_text(sql_text, parsed=parsed)


def classify_sql_text(sql_text: str, parsed=None) -> str:
    """A1 content sniff — schema iff every top-level statement is DDL-only.

    C-13(a): `parsed` is the raw `sqlglot.parse(sql_text, read="mysql")`
    result when the caller already holds it (scan_folder / index_scripts —
    one parse per script, reused for classification AND the C-5 star pass);
    `parsed=None` keeps the historical parse-inside behavior for external
    callers. The dialect is ALWAYS mysql here — never reuse a different
    dialect's parse (the extractor's clean_sql parse is hive-first and its
    SET-preamble stripping flips A1 semantics).
    """
    if parsed is None:
        try:
            parsed = sqlglot.parse(sql_text, read="mysql")
        except Exception:
            return "script"  # unparsable → script (conservative)
    stmts = [s for s in parsed if s is not None]
    if not stmts:
        return "script"  # empty / comment-only file → not schema
    for stmt in stmts:
        if isinstance(stmt, exp.Create):
            # C-1: CREATE TABLE … AS SELECT (CTAS) runs data statements —
            # a pipeline script, never schema DDL. sqlglot parses CTAS as
            # kind="TABLE" with expression=Select; plain CREATE TABLE /
            # CREATE TABLE LIKE keep expression=None → still schema;
            # VIEW/MATVIEW (kind="VIEW") untouched by this rule.
            if (stmt.args.get("kind") == "TABLE"
                    and stmt.args.get("expression") is not None):
                return "script"
            if stmt.args.get("kind") not in _SCHEMA_CREATE_KINDS:
                return "script"  # CREATE INDEX / others → not schema
            # CREATE MATERIALIZED VIEW parses as kind="VIEW" with a
            # MaterializedProperty — allowed (it is a DDL-only statement).
            props = stmt.args.get("properties")
            if props and any(isinstance(e, exp.MaterializedProperty)
                             for e in props.expressions):
                continue
        elif isinstance(stmt, (exp.Grant, exp.Comment)):
            continue
        elif isinstance(stmt, exp.Alter) and isinstance(stmt.this, exp.Table):
            continue  # ALTER TABLE only — ALTER DATABASE/etc. → script
        else:
            return "script"  # SELECT/INSERT/UPDATE/DELETE/MERGE/DROP/...
    return "schema"


def _collect_schema_files(ws_id: str,
                          parsed_cache: dict | None = None) -> list[str]:
    """A1: rel_paths of schema-classified files in the workspace tree.

    Feeds the index-time schema evidence pass (S4b needs DDL evidence even
    when the caller's script list excludes schema files — the auto-select
    path does). C-13(a): `parsed_cache` (when given) receives the per-file
    parse from scan_folder so index_scripts reuses it instead of
    re-parsing every script for its A1 classification.
    """
    tree = scan_folder(ws_id, parsed_cache=parsed_cache)
    out = []

    def _walk(node):
        if node.get("type") == "file" and node.get("file_class") == "schema":
            out.append(node["path"])
        for child in node.get("children", []):
            _walk(child)

    _walk(tree)
    return out


def _invalidate_graph_caches(cache_dir) -> int:
    """C-2(a): delete every graph cache in the workspace cache dir.

    index_scripts precomputes each graph DURING the per-script loop —
    BEFORE the S4b cross-script attribution/revocation pass mutates the
    analysis caches — so a cached graph can serve pre-attribution data on
    L2 cache hits. Delete BOTH the current GRAPH_CACHE_PREFIX files and
    older-prefix leftovers (the whole `graph_3_*_*.json` shape: any
    graph_3_<ver>_<hash>.json). schemas_*, analysis_* and
    filtered_index.json are never touched — the analysis caches are the
    S4b-mutated source of truth and must survive. Returns the number of
    files deleted.
    """
    n = 0
    for p in cache_dir.glob("graph_3_*.json"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass  # best-effort — a leftover stale graph rebuilds on demand
    return n


# ── C-5 helpers: unqualified-star detection + expansion (post-loop pass) ──

def _iter_select_nodes(statements):
    """Yield every exp.Select in a parse result — top-level statements and
    nested selects (subqueries, CTE bodies, UNION branches, INSERT …
    SELECT bodies) — the C-5 star-detection walk."""
    stack = list(statements or [])
    while stack:
        node = stack.pop()
        if isinstance(node, exp.Select):
            yield node
        stack.extend(node.iter_expressions())


def _star_from_tables(select) -> list[str]:
    """C-5: the FROM tables of a Select whose projections contain an
    UNQUALIFIED star (`SELECT * …`) — [] otherwise. Qualified stars
    (`t.*`) parse as exp.Column(this=exp.Star) and are the extractor's
    domain (its _expand_star_columns records them — the index pass must
    not double-expand). sqlglot 30.x: the single FROM table lives in
    `from_`; comma tables and JOINs land in the `joins` list. Derived
    tables (Subquery/Select/Union/Lateral/UDTF) yield nothing — they
    carry no schema evidence (m_ws is physical-table evidence only)."""
    projs = select.args.get("expressions") or []
    if not any(isinstance(p, exp.Star) for p in projs):
        return []
    out = []
    _collect_from_tables(select.args.get("from_"), out)
    for _j in select.args.get("joins") or []:
        _collect_from_tables(_j.args.get("this"), out)
    return out


def _collect_from_tables(node, out):
    """Collect exp.Table names from a FROM/JOIN source — never descending
    into derived tables (no schema evidence there)."""
    if node is None:
        return
    if isinstance(node, exp.Table):
        out.append(node.name)
    elif isinstance(node, (exp.Select, exp.Subquery, exp.Union,
                           exp.Lateral, exp.UDTF)):
        return  # derived tables — no schema evidence to expand
    else:
        for _c in node.iter_expressions():
            _collect_from_tables(_c, out)


def _evidence_columns(m_ws: dict, table: str):
    """C-5: schema-evidence column set for `table` — exact key first, then
    the single case-variant fallback (mirrors the S4b `_table_owns`
    rules: distinct case variants must never share an evidence pool).
    None when there is no evidence — the caller skips silently (BE2: no
    padding)."""
    cols = m_ws.get(table)
    if cols is None:
        variants = [c2 for t2, c2 in m_ws.items()
                    if t2.lower() == table.lower() and t2 != table]
        if len(variants) == 1:
            cols = variants[0]
        else:
            return None
    return cols


# Progress tracking for polling
_INDEX_PROGRESS = {}  # ws_id -> {current, total, phase, errors}
# L3: concurrent index runs / pollers must not tear the progress dict.
_INDEX_PROGRESS_LOCK = threading.Lock()

def _set_progress(ws_id: str, current: int, total: int, phase: str, errors=None):
    """Update index progress. `errors=None` preserves already-recorded
    errors (L3 — the error path must not silently reset them)."""
    with _INDEX_PROGRESS_LOCK:
        prev = _INDEX_PROGRESS.get(ws_id)
        if errors is None:
            errors = prev.get("errors", []) if prev else []
        _INDEX_PROGRESS[ws_id] = {"current": current, "total": total,
                                  "phase": phase, "errors": errors}

def get_index_progress(ws_id: str) -> dict:
    """Return a snapshot of the progress dict (callers may not mutate it)."""
    with _INDEX_PROGRESS_LOCK:
        entry = _INDEX_PROGRESS.get(ws_id)
    if entry is None:
        return {"current": 0, "total": 0, "phase": "idle", "errors": []}
    # L7 (review): a shallow dict(entry) shares the nested `errors` list —
    # a caller mutating the returned list would corrupt the registry. Copy.
    return {"current": entry.get("current", 0),
            "total": entry.get("total", 0),
            "phase": entry.get("phase", ""),
            "errors": list(entry.get("errors", []))}

def scan_folder(ws_id: str, parsed_cache: dict | None = None) -> dict:
    """Walk workspace scripts/ dir, return hierarchical tree with is_sql flag.

    A1: every SQL file node (is_sql: .sql/.ddl/.schema) also carries
    `file_class`: "schema" (DDL-only) or "script" (pipeline). Consumers
    must default to "script" for old trees without the key (defensive read).

    C-13(a): each .sql file is parsed exactly ONCE here (the parse is
    passed into classify_sql_text instead of being re-parsed inside) and,
    when `parsed_cache` is given (index_scripts), exported under the
    rel_path so the index loop reuses it for classification and the C-5
    star pass. .ddl/.schema files short-circuit on extension — never
    parsed. Unreadable/unparsable files classify "script" (conservative)
    and export no parse.
    """
    ws_dir = get_workspace_dir(ws_id)
    scripts_dir = ws_dir / "scripts"
    if not scripts_dir.exists():
        return {"name": "root", "type": "directory", "children": []}

    def _walk(path: Path, rel: str = ""):
        entry = {
            "name": path.name,
            "path": str(path.relative_to(scripts_dir)),
            "type": "directory" if path.is_dir() else "file",
        }
        if path.is_file():
            ext = path.suffix.lower()
            entry["is_sql"] = (ext in SQL_EXTENSIONS
                               or ext in SCHEMA_EXTENSIONS)
            if entry["is_sql"]:
                if ext in SCHEMA_EXTENSIONS:
                    # A1: extension is explicit intent — no content sniff.
                    entry["file_class"] = "schema"
                else:
                    parsed = None
                    try:
                        _txt = path.read_text(encoding="utf-8",
                                              errors="replace")
                        parsed = sqlglot.parse(_txt, read="mysql")
                    except Exception:
                        # unreadable/unparsable → script (conservative)
                        entry["file_class"] = "script"
                    else:
                        entry["file_class"] = classify_sql_text(_txt,
                                                                parsed=parsed)
                    if parsed_cache is not None and parsed is not None:
                        parsed_cache[entry["path"]] = parsed
        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                children.append(_walk(child))
            entry["children"] = children
        return entry

    return _walk(scripts_dir)


def index_scripts(ws_id: str, script_paths: list[str]) -> dict:
    """Analyze selected scripts, build table_index and field_index.
    
    For each script:
      1. Read SQL from workspace/scripts/{path}
      2. Call run_full_analysis()
      3. Extract table/column variables
      4. Build indexes
    
    Returns: {table_index, field_index, script_count, precomputed_count,
              resolution_stats} — resolution_stats carries the R20 coverage
              numbers aggregated from per-script extraction + the S4b
              cross-script schema pass (plus `ambiguous` — fields claimed
              by ≥2 DIFFERENT owners across scripts: never attributed,
              revoked from the index, counted and reported).
    """
    from app.extractor.adapter import run_full_analysis

    table_index = {}   # table_name -> {fields: set, scripts: set}
    field_index = {}   # field_name -> {tables: set, scripts: set}
    script_count = 0
    precomputed = 0
    errors = []
    total = len(script_paths)
    # L3: explicit fresh start — clears any errors from a previous run.
    _set_progress(ws_id, 0, total, "analyzing", errors=[])

    # R20 / S4 (Phase 2) accumulation: the extractor's per-script resolution
    # counters + S4b (cross-script schema resolution) inputs, aggregated at
    # index time.
    total_columns = 0     # sum of per-script column-variable counts
    extractor_unresolved = set()  # R20: fields the extractor could not resolve (S1-S3, S5/S6 excluded)
    stats_seen = False    # any script carried resolution_stats (fallback gate)
    by_strategy = {"plain_alias": 0, "expr_alias": 0, "scope": 0,
                   "schema": 0, "sys": 0, "other": 0}
    # S4b (Phase 2 — AUTO-RESOLUTION) accumulation: the workspace schema map
    # M_ws (union of the extractor's per-script script_schemas) plus the
    # per-script schema_candidates records (S4a residuals — still-unresolved
    # bare columns in ≥2-table scopes). S4b re-tests each candidate ONLY
    # against its OWN visible_tables — never workspace-global uniqueness.
    m_ws = {}                    # canonical table -> set(columns)
    schema_candidate_records = []  # (script, {field, visible_tables, loc, ...})
    schema_evidence_by_script = {}  # script -> {table_lower: {col_lower: line_int}}
    r6_collision_total = 0       # summed per-script r6_collision (S4a counter)
    s4c_seen = False             # any script carried the new S4 keys
    cache_by_script = {}         # rel_path -> analysis cache path (S4b updates)
    pipeline_paths = []          # A1: paths processed as pipeline scripts

    # C-13(a): one parse per script — scan_folder parses during the A1
    # discovery pass below and exports the per-file parse here; the loop
    # reuses it for A1 classification and the C-5 star pass (no new parse).
    parsed_cache: dict = {}
    parse_by_script: dict = {}  # rel_path -> sqlglot statements (C-5 pass)

    # ── A1: schema evidence pass (DDL-only files are NOT pipeline scripts) ──
    # DDL files (all statements CREATE TABLE/VIEW/MATERIALIZED VIEW, GRANT,
    # COMMENT, ALTER TABLE) still feed S4b: run them through the analysis
    # pipeline and merge their script_schemas into m_ws + provenance. The
    # discovery below covers the auto-select path (callers may exclude
    # schema files from the script list); explicit schema paths in the
    # caller's list are skipped in the loop and handled here too (same pass,
    # dedup by path). Evidence loss would change S4b resolution, so
    # discovery/analysis failures are surfaced in `errors`, never silent.
    schema_evidence_paths = set()
    try:
        schema_evidence_paths = set(_collect_schema_files(ws_id, parsed_cache))
    except Exception as e:
        errors.append({"script": "(schema discovery)", "error": str(e)})
    for _rel in sorted(schema_evidence_paths):
        _process_schema_evidence(ws_id, _rel, m_ws,
                                 schema_evidence_by_script, errors)

    for i, rel_path in enumerate(script_paths):
        sp = get_script_path(ws_id, rel_path)
        if not sp or not sp.exists():
            errors.append({"script": rel_path, "error": "File not found"})
            # L3: surface the error in progress without resetting it.
            _set_progress(ws_id, i, total, "analyzing", errors=errors)
            continue
        if rel_path in schema_evidence_paths:
            # A1: DDL-only file — already processed by the schema evidence
            # pass above; never a pipeline script (no script_count, no
            # index entries, no caches).
            _set_progress(ws_id, i + 1, total, "analyzing")
            continue

        try:
            sql_text = sp.read_text(encoding="utf-8", errors="replace")
            # C-13(a): reuse the scan_folder parse (one parse per script);
            # fall back to parsing here only when the scan parse is missing
            # (unparsable files export none — classify re-tries and yields
            # the same conservative "script").
            parsed = parsed_cache.get(rel_path)
            if parsed is None:
                try:
                    parsed = sqlglot.parse(sql_text, read="mysql")
                except Exception:
                    parsed = None
            if classify_sql_text(sql_text, parsed=parsed) == "schema":
                # A1: DDL-only content in a .sql file (not in the discovered
                # set, e.g. the tree was stale) → evidence pass, never a
                # pipeline script.
                _process_schema_evidence(ws_id, rel_path, m_ws,
                                         schema_evidence_by_script, errors)
                _set_progress(ws_id, i + 1, total, "analyzing")
                continue
            result = run_full_analysis(sql_text, rel_path, ws_id=ws_id)
            script_count += 1
            pipeline_paths.append(rel_path)
            # C-5: the C-13(a) single parse is reused for star detection —
            # never a new parse. None (unparsable) → script skipped there.
            parse_by_script[rel_path] = parsed
            _set_progress(ws_id, i + 1, total, "analyzing")

            # Cache analysis result
            cache_dir = get_workspace_dir(ws_id) / "cache"
            import hashlib
            cache_key = hashlib.md5((rel_path + sql_text).encode()).hexdigest()[:12]
            cache_path = cache_dir / f"analysis_{cache_key}.json"
            cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            cache_by_script[rel_path] = str(cache_path)  # S4b persists attributions

            # ── R20: aggregate per-script resolution stats ──
            # The extractor emits `resolution_stats` in new analyses; old
            # caches / mid-flight versions may not — read defensively.
            # Reviewer finding (R20): the index-level orphan set must follow
            # the extractor's OWN `unresolved` lists (single source of truth)
            # — they exclude S5/S6-marked and CTE/alias-resolved fields, which
            # the tables==[] test alone cannot distinguish.
            # C4b: the extractor's ADDITIVE per-script keys (`resolved`,
            # `unresolved_count`, `coverage_pct`) are deliberately NOT summed
            # here. The aggregate derives from total_columns + the UNION of
            # per-script `unresolved` LISTS (post-S4b orphans, deduped by
            # name), so aggregate coverage = 1 − unresolved/total_columns —
            # never an average of per-script percentages (double-counting
            # names across scripts would skew both numerator and denominator).
            rs = result.get("resolution_stats")
            stats_seen = isinstance(rs, dict)
            if stats_seen:
                total_columns += rs.get("total_columns", 0) or 0
                rb = rs.get("resolved_by")
                if isinstance(rb, dict):
                    for _k in by_strategy:
                        by_strategy[_k] += rb.get(_k, 0) or 0
                for _f in rs.get("unresolved", []) or []:
                    if isinstance(_f, str):
                        extractor_unresolved.add(_f)

                # ── S4b inputs: SELECT-side schema evidence (Phase 2) ──
                # The extractor (S4a) emits `schema_candidates` (S4a
                # residuals), `script_schemas` and `r6_collision` with new
                # analyses; old caches lack them (or carry the Phase-0
                # list-shaped script_schemas) — read defensively. M_ws (the
                # S4b map) is the union of all scripts' script_schemas. NEW
                # shape: {table: {col: evidence_line_int}} — membership
                # `field in script_schemas[t]` works on dict keys, and the
                # line is the schema-EVIDENCE provenance for the report.
                # OLD shape: {table: [cols]} — same membership, no lines.
                # Shared merge: identical for regular scripts and the A1
                # schema-file evidence pass.
                _merge_script_schemas(result, rel_path, m_ws,
                                      schema_evidence_by_script)
                sc4c = rs.get("schema_candidates")
                if isinstance(sc4c, list):
                    for _c in sc4c:
                        if isinstance(_c, dict):
                            schema_candidate_records.append((rel_path, _c))
                _r6 = rs.get("r6_collision")
                if isinstance(_r6, (int, float)) and not isinstance(_r6, bool):
                    r6_collision_total += int(_r6)
                # N3 (review): the Phase-2 report gate requires ALL THREE S4
                # keys in the same analysis — a partially-upgraded cache
                # (e.g. script_schemas only) must keep the Phase-1 block and
                # a zeroed summary rather than print a misleading zero line.
                s4c_seen = (s4c_seen
                            or ("schema_candidates" in rs
                                and "script_schemas" in rs
                                and "r6_collision" in rs))

            # C-2: index-time GRAPH caches are no longer precomputed here —
            # any graph written before the S4b pass is pre-S4b and stale, so
            # the post-S4b invalidation (_invalidate_graph_caches) would
            # delete it moments later (pure double-analysis per script). L2
            # rebuilds on demand from the post-S4b analysis cache and its
            # miss path writes the graph cache itself. Only the schema
            # precompute survives — L2 cache hits use it without re-analysis.
            try:
                from app.extractor.schema_inference import infer_table_schemas
                schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
                if not schemas_cache_path.exists():
                    schemas_cache_path.write_text(json.dumps(
                        infer_table_schemas(result.get("variables", []),
                                            result.get("dependencies", [])),
                        default=str))
            except Exception:
                pass  # schema pre-computation is optional

            # Build indexes from variables
            variables = result.get("variables", [])
            # Bug 49: map SQL aliases → physical tables ("c" → "crm_customers")
            # so column variables register against the real table, not just the alias
            alias_to_physical = {}
            cte_names = set()  # R20 reviewer fix: CTEs are script-scoped —
            for v in variables:
                if v.get("variable_type") in ("table", "view", "cte") and v.get("source_tables"):
                    alias_to_physical[v.get("name", "")] = v.get("source_tables", [None])[0]
                if v.get("variable_type") == "cte":
                    cte_names.add(v.get("name", ""))
            for v in variables:
                vt = v.get("variable_type", "")
                name = v.get("name", "")

                if vt == "table":
                    table_index.setdefault(name, {"fields": set(), "scripts": set()})
                    table_index[name]["scripts"].add(rel_path)

                elif vt == "column":
                    field_name = name.split(".", 1)[-1] if "." in name else name
                    table_name = name.split(".", 1)[0] if "." in name else ""
                    # R20: unqualified columns resolved by the extractor (S1-S3)
                    # carry source_tables — surface them in the index too.
                    # Skip ⟐-prefixed entries (output containers + S5/S6 markers
                    # are script-scoped) and CTE names (script-scoped; must not
                    # become workspace-wide tables or S4 candidates).
                    if not table_name:
                        for _st in v.get("source_tables", []):
                            if _st and not _st.startswith("⟐") and _st not in cte_names:
                                table_name = _st
                                break
                    field_index.setdefault(field_name, {"tables": set(), "scripts": set()})
                    field_index[field_name]["scripts"].add(rel_path)
                    # Bug 49: also register the physical table (alias → canonical),
                    # so autocomplete surfaces crm_customers.customer_id, not just c.customer_id
                    if table_name:
                        physical = alias_to_physical.get(table_name, table_name)
                        for tname in {table_name, physical}:
                            field_index[field_name]["tables"].add(tname)
                            table_index.setdefault(tname, {"fields": set(), "scripts": set()})
                            table_index[tname]["fields"].add(field_name)

            # Bug 41: Cross-reference DML dependencies so that INSERT column
            # names (e.g., total_amount) are indexed alongside SELECT aliases
            # (e.g., total) for autocomplete. This lets users find fields by
            # either the INSERT column name or the SELECT alias.
            dependencies = result.get("dependencies", [])
            if dependencies:
                var_by_id = {v2.get("id"): v2 for v2 in variables}
                for dep in dependencies:
                    if dep.get("relationship") != "DML":
                        continue
                    src = var_by_id.get(dep.get("source_id"))
                    tgt = var_by_id.get(dep.get("target_id"))
                    if not (src and tgt):
                        continue
                    if src.get("variable_type") != "column" or tgt.get("variable_type") != "column":
                        continue
                    src_name = src.get("name", "")
                    tgt_name = tgt.get("name", "")
                    # Target: "daily_summary.total_amount" -> table=daily_summary, field=total_amount
                    tgt_field = tgt_name.split(".", 1)[-1] if "." in tgt_name else tgt_name
                    tgt_table = tgt_name.split(".", 1)[0] if "." in tgt_name else ""
                    # Source: "total" or "analytics_orders.total" -> field=total
                    src_field = src_name.split(".", 1)[-1] if "." in src_name else src_name
                    if not tgt_table:
                        continue
                    # Map both names to the INSERT target table
                    table_index.setdefault(tgt_table, {"fields": set(), "scripts": set()})
                    table_index[tgt_table]["fields"].add(src_field)
                    table_index[tgt_table]["fields"].add(tgt_field)
                    # Index both names in field_index with target table
                    for fn in (src_field, tgt_field):
                        field_index.setdefault(fn, {"tables": set(), "scripts": set()})
                        field_index[fn]["tables"].add(tgt_table)
                        field_index[fn]["scripts"].add(rel_path)

        except Exception as e:
            errors.append({"script": rel_path, "error": str(e)})
            # L3: keep last progress + the error (was: _set_progress wiped
            # the errors list back to zero on every failure).
            _set_progress(ws_id, i + 1, total, "analyzing", errors=errors)


    # ── S4b: cross-script schema resolution (Phase 2 — AUTO) ──
    # REPLACES the scope-blind index S4 loop (Phase-1 audit PASSED,
    # 2026-08-06). Candidates are the extractor's per-script
    # `schema_candidates` (S4a residuals — still-unresolved bare columns in
    # ≥2-table scopes, each carrying its OWN visible_tables). Each is
    # re-tested against M_ws (union of all scripts' script_schemas) but
    # ONLY within the candidate's own scope: a field known only in table T
    # is never attributed to T in a statement that doesn't reference it
    # (never-guess — no workspace-global uniqueness fallback).
    # Rule per candidate:
    #   1. R6 guard — lower(field) ∈ lower(visible_tables) → never attribute
    #      (S4a already counted it in r6_collision; S4b only refuses).
    #   2. owners = {t ∈ visible_tables : field ∈ M_ws[t]} — whole-name,
    #      case-insensitive equality (R4: "id" never matches "customer_id").
    #   3. len(owners) == 1 → attribute; 0 (evidence absent / table not
    #      visible) or ≥2 (ambiguous) → stays unresolved + reported.
    # M12 (review): rule 3 is additionally gated on OWNER CONFLICTS — a
    # field claimed by ≥2 DIFFERENT owners (two scripts' candidates, or a
    # candidate whose owner differs from an existing S1–S3/S4a index
    # attribution) is AMBIGUOUS: no plan for it is applied (no index
    # attribution, no cache update, no schema counter), stale index
    # attributions are revoked, and the field returns to the unresolved
    # pool — counted in resolution_stats["ambiguous"] and listed in the
    # report instead of silently letting the first claim win. Same-owner
    # re-claims keep the no-op skip (first attribution stands).
    # L2 (review): the owner check matches TABLE names EXACTLY first — a
    # case-insensitive fallback applies only when the visible table has NO
    # exact entry in m_ws (distinct case variants like Orders/orders must
    # never be merged into a shared evidence pool). Field names stay
    # case-insensitive (R4).
    def _table_owns(t, field_lower):
        cols = m_ws.get(t)  # exact key first
        if cols is None:
            variants = [c2 for t2, c2 in m_ws.items()
                        if t2.lower() == t.lower() and t2 != t]
            if len(variants) == 1:
                cols = variants[0]
            else:
                return False  # 0 or ≥2 case variants → no evidence (never guess)
        return field_lower in {c.lower() for c in cols}

    # M12 (review): TWO-PHASE processing — phase A PLANS each candidate
    # (read-only, no index/cache mutation); phase B detects OWNER CONFLICTS;
    # phase C applies only non-conflicted plans. A field claimed by ≥2
    # different owners is ambiguous and never attributed.
    s4b_plans = []  # (field, owner, cand_script, cand_record, visible)
    for _srec, _crec in schema_candidate_records:
        if not isinstance(_crec, dict):
            continue
        _f = _crec.get("field")
        visible = [t for t in (_crec.get("visible_tables") or [])
                   if isinstance(t, str) and t]
        if not isinstance(_f, str) or not _f or not visible:
            continue  # malformed record — never guess on it
        if _f.lower() in {t.lower() for t in visible}:
            continue  # R6 guard — field == visible table: never attribute
        owners = [t for t in visible if _table_owns(t, _f.lower())]
        if len(owners) != 1:
            continue  # 0 owners (evidence absent / not visible) or ≥2 → stay
        owner = owners[0]
        # L1 (review): the owner must ALREADY be a real index table (it is a
        # visible table of the statement, so it should be — unless an
        # alias-resolution failure leaked an alias name here). Never
        # fabricate a table_index entry for an unindexed owner: leave the
        # candidate unresolved (never guess) and let it surface in the report.
        if owner not in table_index:
            continue
        s4b_plans.append((_f, owner, _srec, _crec, visible))

    # Phase B — owner-conflict detection (read-only):
    #   * ≥2 plans for the same field with DIFFERENT owners (two scripts'
    #     candidates) → ambiguous;
    #   * a plan whose owner differs from the field's EXISTING index
    #     attribution (S1–S3/S4a extractor-side) → ambiguous too — the
    #     different-owner claim must not be silently skipped ("first script
    #     wins") and the stale attribution must not keep winning.
    ambiguous_fields = set()
    _claimed_owners = {}
    for _f, _owner, _srec, _crec, _vis in s4b_plans:
        _claimed_owners.setdefault(_f, set()).add(_owner.lower())
    for _f, _owners in _claimed_owners.items():
        if len(_owners) > 1:
            ambiguous_fields.add(_f)
    for _f, _owner, _srec, _crec, _vis in s4b_plans:
        _fdata = field_index.get(_f)
        _existing = ([t for t in _fdata.get("tables")
                      if isinstance(t, str) and t] if _fdata else [])
        if _existing and _owner.lower() not in {t.lower() for t in _existing}:
            ambiguous_fields.add(_f)

    # Phase C — apply. Ambiguous fields are REVOKED first (the existing
    # attribution leaves table_index/field_index and the field returns to
    # the unresolved pool so the report lists it), then only non-conflicted
    # plans attribute.
    # C-3: the revocation is MIRRORED into the persisted analysis caches —
    # l1_builder consumes analysis caches today, so a revoked attribution
    # must not survive there. The current-run attribution is snapshotted
    # BEFORE the in-memory clear (owners + the field's scripts) and the
    # cache-by-script mapping locates the analysis file per script.
    # Cross-run: a field ABSENT from the current field_index (its
    # attribution lives only in prior-run caches) iterates EVERY analysis
    # cache in the workspace dir and revokes any owner.
    for _f in ambiguous_fields:
        _fdata = field_index.get(_f)
        _revoked_scripts = (list(_fdata.get("scripts") or [])
                            if _fdata else [])
        _revoked_owners = (list(_fdata.get("tables") or [])
                           if _fdata else [])
        if _fdata:
            for _t in _revoked_owners:
                _ti = table_index.get(_t)
                if _ti:
                    _ti["fields"].discard(_f)
            _fdata["tables"].clear()
            extractor_unresolved.add(_f)  # back into the unresolved pool → report
        if _revoked_scripts:
            for _rel in _revoked_scripts:
                for _own in (_revoked_owners or [None]):
                    _revoke_s4b_cache_update(cache_by_script.get(_rel),
                                             _f, _own)
        else:
            # Cross-run: not in the current field_index — prior-run cache
            # attribution only. No owner known → revoke any owner.
            for _apath in sorted((get_workspace_dir(ws_id) / "cache")
                                 .glob("analysis_*.json")):
                _revoke_s4b_cache_update(str(_apath), _f, None)

    s4b_resolved = []  # (field, owner, cand_script, cand_record) — S4b additions
    for _f, owner, _srec, _crec, visible in s4b_plans:
        if _f in ambiguous_fields:
            continue  # M12 — different-owner claim: never attribute
        fdata = field_index.get(_f)
        if fdata and fdata.get("tables"):
            continue  # already attributed to the SAME owner — no-op skip
        # Index-level attribution (same mechanics as the old loop, but the
        # candidate's own scope replaces workspace-global uniqueness).
        field_index.setdefault(_f, {"tables": set(), "scripts": set()})
        field_index[_f]["tables"].add(owner)
        table_index[owner]["fields"].add(_f)
        extractor_unresolved.discard(_f)  # out of the per-script unresolved lists
        # Persist into the analysis cache: var attribution + resolution_stats
        # (unresolved drop, schema +1, candidate removal) so cache consumers
        # (L1/L2) see the resolution too.
        # M15 (review): the schema-strategy counter counts only real
        # attribution events — `_apply_s4b_cache_update` returns how many
        # analysis vars it actually modified; a stale/missing cache (0
        # modified) is not an attribution event and must not count.
        if _apply_s4b_cache_update(cache_by_script.get(_srec), _f, owner,
                                   visible, _crec):
            by_strategy["schema"] += 1
        s4b_resolved.append((_f, owner, _srec, _crec))
    s4b_unique_owners = len(s4b_resolved)
    n_ambiguous = len(ambiguous_fields)

    # ── C-2(a): stale graph caches vs the S4b pass ──
    # The index-time graph precompute ran DURING the per-script loop —
    # BEFORE the S4b attribution/revocation above mutated the analysis
    # caches — so every graph cache can serve pre-attribution data on L2
    # cache hits. Delete them all (current prefix + older-prefix
    # leftovers); L2 rebuilds on demand from the S4b-mutated analysis.
    _invalidate_graph_caches(get_workspace_dir(ws_id) / "cache")

    # ── C-5: star expansion (POST-LOOP pass) ──
    # `SELECT * FROM t` / `INSERT INTO x SELECT * FROM t` produce NO
    # field-index entries from the extractor (its _expand_star_columns
    # records only QUALIFIED stars) — such scripts silently vanish from
    # search. Schema evidence (script_schemas → m_ws) accumulates DURING
    # the script loop, so this pass runs AFTER the loop (and after S4b —
    # it must not perturb the review-verified S4b phases) and BEFORE the
    # pair_index construction below: every unqualified star's FROM tables
    # expand into field_index/table_index using their schema-evidence
    # columns. No schema evidence → skip silently (BE2: no padding — a
    # star without visible columns is honest "no data", never a guess).
    # Star DETECTION reuses the C-13(a) single per-script parse — no new
    # parse.
    star_expanded_fields = 0
    _star_seen = set()
    for _rel, _stmts in parse_by_script.items():
        if not _stmts:
            continue  # unparsable script — nothing to detect
        for _sel in _iter_select_nodes(_stmts):
            for _t in _star_from_tables(_sel):
                _cols = _evidence_columns(m_ws, _t)
                if not _cols:
                    continue  # no schema evidence → skip silently
                for _c in _cols:
                    if (_rel, _t, _c) in _star_seen:
                        continue
                    _star_seen.add((_rel, _t, _c))
                    field_index.setdefault(_c,
                                           {"tables": set(), "scripts": set()})
                    field_index[_c]["tables"].add(_t)
                    field_index[_c]["scripts"].add(_rel)
                    table_index.setdefault(_t,
                                           {"fields": set(), "scripts": set()})
                    table_index[_t]["fields"].add(_c)
                    star_expanded_fields += 1

    # P1: Build pair_index[(table,field)] → {scripts} for fast seed-script lookup.
    # Used by Algorithm 2 step 2a to find seed scripts without scanning all data.
    # Built AFTER S4 so schema attributions are included.
    cache_dir = get_workspace_dir(ws_id) / "cache"
    pair_index = {}
    for field_name, fdata in field_index.items():
        for table_name in fdata.get("tables", []):
            key = f"{table_name}.{field_name}"
            pair_index.setdefault(key, set()).update(fdata.get("scripts", []))

    # Cache pair_index
    (cache_dir / "pair_index.json").write_text(json.dumps(
        {k: sorted(v) for k, v in pair_index.items()}, indent=2))

    # Convert sets to sorted lists for JSON
    for ti in table_index.values():
        ti["fields"] = sorted(ti["fields"])
        ti["scripts"] = sorted(ti["scripts"])
    for fi in field_index.values():
        fi["tables"] = sorted(fi["tables"])
        fi["scripts"] = sorted(fi["scripts"])

    # Cache indexes
    cache_dir = get_workspace_dir(ws_id) / "cache"
    (cache_dir / "table_index.json").write_text(json.dumps(table_index, indent=2))
    (cache_dir / "field_index.json").write_text(json.dumps(field_index, indent=2))

    # ── R20: orphan resolution coverage report (supersedes Bug 54) ──
    # Post-S4 orphans = fields with no table attribution. The report is the
    # RESIDUAL layer of the resolution pipeline (S1–S4): only fields the
    # extractor genuinely cannot attribute are listed, with SQL evidence,
    # alongside the coverage numbers (resolved / total column variables).
    # Reviewer fix: the orphan set follows the extractor's own `unresolved`
    # lists (excludes S5/S6-marked and CTE/alias-resolved fields). When the
    # analysis caches lack resolution_stats (old data), fall back to the
    # tables==[] test.
    if stats_seen:
        # Extractor-driven: its `unresolved` already excludes S5/S6-marked,
        # CTE/alias-resolved fields. Post-S4 attribution removes more.
        orphan_fields = {fname: sorted(fdata.get("scripts", []))
                         for fname, fdata in field_index.items()
                         if fname in extractor_unresolved
                         and not fdata.get("tables")}
    else:
        # Old caches without resolution_stats: tables==[] fallback.
        orphan_fields = {fname: sorted(fdata.get("scripts", []))
                         for fname, fdata in field_index.items()
                         if not fdata.get("tables")}
    (cache_dir / "orphan_fields.json").write_text(json.dumps(orphan_fields, indent=2))

    # E1 (reviewer): fields resolved to script-scoped containers (⟐ output,
    # CTE) are counted resolved by the extractor but have NO usable table in
    # the workspace index — and were invisible (not attributed, not reported).
    # Surface them as a distinct bucket so nothing is hidden.
    no_table_fields = {fname for fname, fdata in field_index.items()
                       if not fdata.get("tables")}
    container_resolved = sorted(no_table_fields - set(orphan_fields))

    # ── S4b owner lines for the report: schema-EVIDENCE provenance ──
    # One line per S4b attribution (field → owner). With the new
    # dict-of-dicts script_schemas (audit recommendation 2) the line shows
    # the SCHEMA-EVIDENCE line (the DDL / qualified-ref line that proves the
    # owner), plus the bare-use loc when it differs; without provenance
    # (old-shape caches) the Phase-1 format is kept (candidate script + loc).
    s4b_owner_lines = []  # (field, owner, script, loc_label, visible_txt)
    for _f, owner, _srec, _crec in sorted(s4b_resolved, key=lambda r: r[0]):
        visible_names = [t for t in (_crec.get("visible_tables") or [])
                         if isinstance(t, str) and t]
        vis_txt = (", visible: %s" % ", ".join(visible_names[:6])
                   if visible_names else "")
        ev_script, ev_line = _evidence_loc(owner, _f, schema_evidence_by_script)
        if ev_script is None or ev_line is None:
            # no provenance (old-shape script_schemas) → Phase-1 format:
            # candidate script + loc (string/missing loc → SQL line search).
            loc_label = _loc_label(ws_id, _srec, _f, _crec.get("loc"))
            s4b_owner_lines.append((_f, owner, _srec, loc_label, vis_txt))
            continue
        loc_label = "L%d" % ev_line
        used_label = _loc_label(ws_id, _srec, _f, _crec.get("loc"))
        if used_label and (ev_script != _srec or loc_label != used_label):
            loc_label += ", used: %s %s" % (_srec, used_label)
        s4b_owner_lines.append((_f, owner, ev_script, loc_label, vis_txt))
    s4b_unique_owners = len(s4b_owner_lines)

    # L3: don't shadow `total` (script count) — the "done" progress below
    # must report scripts, not column variables.
    total_cols = total_columns
    unresolved = len(orphan_fields)
    resolved = max(0, total_cols - unresolved)
    coverage_pct = round(resolved / total_cols * 100, 1) if total_cols else 100.0
    resolution_stats = {
        "total_columns": total_cols,
        "resolved": resolved,
        "unresolved": unresolved,
        "container_resolved": len(container_resolved),
        "coverage_pct": coverage_pct,
        "by_strategy": dict(by_strategy),
        # M12: fields claimed by ≥2 DIFFERENT owners (cross-script S4b
        # conflict, or a candidate vs an existing S1–S3/S4a attribution) —
        # never attributed; revoked fields return to the unresolved pool
        # and are listed in the report's UNRESOLVED section.
        "ambiguous": n_ambiguous,
    }
    _push_resolution_report(ws_id, resolution_stats, orphan_fields,
                            container_resolved,
                            s4c_seen=s4c_seen,
                            n_cand=len(schema_candidate_records),
                            n_owner=s4b_unique_owners,
                            r6_total=r6_collision_total,
                            owner_lines=s4b_owner_lines)

    # Update workspace meta
    ws_dir = get_workspace_dir(ws_id)
    meta = json.loads((ws_dir / "meta.json").read_text())
    meta["indexed"] = True
    # A1: only pipeline scripts — schema files are evidence-only, never
    # part of the workspace's script list.
    meta["indexed_scripts"] = pipeline_paths
    meta["indexed_at"] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    (ws_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    _set_progress(ws_id, total, total, "done")
    return {
        "table_index": table_index,
        "field_index": field_index,
        "script_count": script_count,
        "precomputed_count": precomputed,
        # C-5: number of (script, table, column) entries added by the
        # post-loop star expansion (SELECT */INSERT…SELECT * over
        # schema-evidence tables). 0 when no unqualified star has schema
        # evidence — no padding.
        "star_expanded_fields": star_expanded_fields,
        "errors": errors,
        "orphan_field_count": len(orphan_fields),
        "orphan_field_samples": list(sorted(orphan_fields))[:20],
        "resolution_stats": resolution_stats,
        # S4b (Phase 2): SELECT-side candidate summary — N = candidate
        # records remaining after S4a (the S4b input), M = resolved by S4b
        # (unique visible owner found), K = summed per-script r6_collision
        # (S4a counter; S4b only refuses r6 candidates, never recounts).
        # Zeroed on old caches (no new keys) so consumers get a stable shape.
        "schema_candidates_summary": {
            "total": len(schema_candidate_records),
            "unique_owner": s4b_unique_owners,
            "r6_collision": r6_collision_total,
        },
        # A1: schema-evidence report — pure facts from the merged M_ws
        # (present = at least one table has column evidence). No advice.
        "schema_evidence": {
            "present": len(m_ws) > 0,
            "tables": len(m_ws),
            "columns": sum(len(c) for c in m_ws.values()),
        },
    }


def _merge_script_schemas(result: dict, rel_path: str, m_ws: dict,
                          schema_evidence_by_script: dict) -> None:
    """Merge a script's script_schemas into the S4b evidence maps: m_ws
    (canonical table -> set(columns)) + schema_evidence_by_script (script ->
    {table_lower: {col_lower: evidence_line}}) for report provenance.
    Old-shape list-valued schemas are accepted (membership only, no lines).
    Shared by the regular script loop and the A1 schema-file evidence pass —
    identical merge, so DDL evidence is indistinguishable from query-side
    evidence in S4b.
    """
    rs = result.get("resolution_stats")
    ss4c = rs.get("script_schemas") if isinstance(rs, dict) else None
    if not isinstance(ss4c, dict):
        return
    ev_map = {}
    for _t, _cols in ss4c.items():
        if not isinstance(_t, str):
            continue
        if isinstance(_cols, dict):
            # new shape: {col: evidence_line_int}
            m_ws.setdefault(_t, set()).update(
                str(c) for c in _cols if isinstance(c, str))
            ev_rows = {}
            for _c, _ln in _cols.items():
                if (isinstance(_c, str) and isinstance(_ln, (int, float))
                        and not isinstance(_ln, bool)):
                    ev_rows[_c.lower()] = int(_ln)
            if ev_rows:
                ev_map.setdefault(_t.lower(), {}).update(ev_rows)
        elif isinstance(_cols, (list, tuple, set)):
            # old shape: column list, no provenance
            m_ws.setdefault(_t, set()).update(
                c for c in _cols if isinstance(c, str))
    if ev_map:
        schema_evidence_by_script[rel_path] = ev_map


def _process_schema_evidence(ws_id: str, rel_path: str, m_ws: dict,
                             schema_evidence_by_script: dict,
                             errors: list) -> None:
    """A1: schema-file evidence pass — run a DDL-only file through the
    analysis pipeline and merge its script_schemas into the S4b maps.

    Schema files are never pipeline scripts: no script_count, no table/
    field index entries (so no filter-scope or L1/L2 involvement) and no
    analysis/graph caches. Analysis failures are surfaced in `errors` —
    lost DDL evidence silently changes S4b resolution, so it must be
    visible.
    """
    sp = get_script_path(ws_id, rel_path)
    if not sp or not sp.exists():
        return  # stale tree entry — the main loop reports missing files
    from app.extractor.adapter import run_full_analysis
    try:
        sql_text = sp.read_text(encoding="utf-8", errors="replace")
        result = run_full_analysis(sql_text, rel_path, ws_id=ws_id)
    except Exception as e:
        errors.append({"script": rel_path, "error": str(e)})
        return
    _merge_script_schemas(result, rel_path, m_ws, schema_evidence_by_script)


def _resolve_orphan_script(ws_id: str, name: str):
    """Locate a script file by index name (path, basename, ±.sql).

    R5: shared resolver — the filter's SQL-evidence diagnostics use the
    same tolerance (see filter_service.resolve_script).
    """
    return resolve_script(ws_id, name)


def _loc_label(ws_id: str, script: str, field: str, loc) -> str:
    """Evidence loc for an S4b owner line: an int loc renders as L<int>;
    a string loc (or a missing loc) reuses the report's SQL-evidence line
    search — first line of `script` mentioning the field — so the evidence
    stays consistent with the UNRESOLVED section's mechanism.
    """
    if isinstance(loc, int) and not isinstance(loc, bool):
        return "L%d" % loc
    sp = _resolve_orphan_script(ws_id, script)
    if sp:
        try:
            sql_txt = sp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            sql_txt = ""  # unreadable script → no evidence lines (benign)
        needle = field.lower()
        for i, ln in enumerate(sql_txt.split("\n")):
            if needle in ln.lower():
                return "L%d" % (i + 1)
    return str(loc) if loc is not None else ""


def _evidence_loc(owner: str, field: str,
                  schema_evidence_by_script: dict) -> tuple:
    """Schema-EVIDENCE (script, line) for an S4b-resolved (owner, field).

    Scans the per-script script_schemas provenance (the new dict-of-dicts
    shape, {table: {col: evidence_line_int}}): scripts whose name suggests
    DDL ("table" / "ddl" / "schema") come first, then alphabetical order —
    deterministic. Returns (script, line) or (None, None) when no
    provenance exists (old-shape list script_schemas).
    """
    owner_l = owner.lower()
    field_l = field.lower()
    for _s, _ev in sorted(schema_evidence_by_script.items(),
                          key=lambda kv: (0 if any(h in kv[0].lower()
                                                   for h in ("table", "ddl", "schema"))
                                          else 1, kv[0])):
        ln = (_ev.get(owner_l) or {}).get(field_l)
        if ln is not None and not isinstance(ln, bool):
            return _s, int(ln)
    return None, None


def _apply_s4b_cache_update(cache_path, field: str, owner: str,
                            visible: list, crec: dict | None = None) -> int:
    """S4b: persist an index-time attribution into the script's analysis
    cache — var.source_tables, resolution_stats (field dropped from
    `unresolved`, `resolved_by["schema"]` +1, the candidate record removed).
    Best-effort: a stale/missing cache is skipped — the in-memory indexes
    are already updated, and a re-index re-extracts from scratch.

    M13 (review): the var attribution is CONTEXT-SCOPED, mirroring S4a's
    `_finalize_schema_candidates` (`v.context in cand["contexts"]`) — a var
    is updated only when its `context` is one of the candidate record's
    `contexts` (the statement scopes where the bare column was actually
    seen). A same-named var in a DIFFERENT context (where the owner was not
    visible) is never attributed. Records without the `contexts` key
    (older analyses / injected fixtures) keep the legacy any-context
    behavior — never a silent no-op. `visible` still scopes ONLY the
    candidate-record removal (same field + same visible set).

    Returns the number of analysis variables actually attributed — M15:
    the caller counts a schema-strategy attribution event only when ≥1 var
    was modified (a stale cache modifies none).
    """
    if not cache_path:
        return 0
    try:
        cdata = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except Exception:
        return 0  # stale/missing cache — update skipped by design (best-effort)
    if not isinstance(cdata, dict):
        return 0
    changed = False
    # M13: context-scoped var matching (mirrors S4a) — a var is attributed
    # only when its context is one of the candidate's recorded contexts.
    has_contexts = isinstance(crec, dict) and "contexts" in crec
    cand_contexts = [c for c in (crec.get("contexts") or [])
                     if isinstance(c, str)] if has_contexts else []
    n_attributed = 0
    for v in cdata.get("variables", []) or []:
        if (isinstance(v, dict)
                and v.get("variable_type") == "column"
                and v.get("name") == field
                and (not has_contexts or v.get("context") in cand_contexts)
                and not v.get("source_tables")):
            v["source_tables"] = [owner]
            n_attributed += 1
            changed = True
    rs = cdata.get("resolution_stats")
    if isinstance(rs, dict):
        ul = rs.get("unresolved")
        if isinstance(ul, list) and field in ul:
            ul.remove(field)
            rb = rs.setdefault("resolved_by", {})
            rb["schema"] = (rb.get("schema", 0) or 0) + 1
            changed = True
        cands = rs.get("schema_candidates")
        if isinstance(cands, list):
            vis_key = sorted(t.lower() for t in visible)
            rs["schema_candidates"] = [
                c for c in cands
                if not (isinstance(c, dict) and c.get("field") == field
                        and sorted((t.lower() for t in
                                    (c.get("visible_tables") or [])
                                    if isinstance(t, str))) == vis_key)]
    if changed:
        try:
            Path(cache_path).write_text(
                json.dumps(cdata, indent=2, ensure_ascii=False))
        except Exception:
            pass  # cache persistence is best-effort
    return n_attributed  # M15: vars actually modified (0 = no event)


def _revoke_s4b_cache_update(cache_path, field: str,
                             owner: str | None = None) -> int:
    """C-3: undo an attribution in the persisted analysis cache — the
    mirror of `_apply_s4b_cache_update` for AMBIGUOUS fields (M12: never
    attribute; every existing attribution is revoked).

    - column vars named `field` whose source_tables contain `owner` are
      cleared (owner=None → ANY owner — the cross-run case, where the
      field's current-run index entry is empty/absent and only prior-run
      attributions exist);
    - the field returns to `resolution_stats["unresolved"]` (membership
      guard — it may already be unresolved there, or resolved by ANOTHER
      strategy: adding a duplicate would corrupt the counters) and
      `resolved_by["schema"]` drops by 1 (floor 0) — but ONLY when a var
      was actually revoked (C-4: mirror the in-memory gate exactly — a
      no-op revoke must not move the persisted counters, just like the
      apply counts a schema event only when n_attributed > 0);
    - the field's schema_candidates records are removed (unconditional,
      mirroring the apply's candidate-record removal).

    Returns the number of analysis variables actually revoked (0 = no-op,
    nothing written). Best-effort: stale/missing caches are skipped.
    """
    if not cache_path:
        return 0
    try:
        cdata = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except Exception:
        return 0  # stale/missing cache — skipped by design (best-effort)
    if not isinstance(cdata, dict):
        return 0
    n_revoked = 0
    for v in cdata.get("variables", []) or []:
        if not (isinstance(v, dict)
                and v.get("variable_type") == "column"
                and v.get("name") == field):
            continue
        st = v.get("source_tables")
        if not isinstance(st, list) or not st:
            continue
        if (owner is None
                or any(isinstance(t, str) and t.lower() == owner.lower()
                       for t in st)):
            v["source_tables"] = []
            n_revoked += 1
    rs = cdata.get("resolution_stats")
    if isinstance(rs, dict):
        ul = rs.get("unresolved")
        # C-4: the persisted counters move only on a REAL revocation event
        # (a var was actually cleared), mirroring the in-memory gate
        # (`by_strategy["schema"]` counts only n_attributed > 0 events).
        if (n_revoked > 0 and isinstance(ul, list) and field not in ul):
            ul.append(field)
            rb = rs.setdefault("resolved_by", {})
            rb["schema"] = max(0, (rb.get("schema", 0) or 0) - 1)
        cands = rs.get("schema_candidates")
        if isinstance(cands, list):
            rs["schema_candidates"] = [
                c for c in cands
                if not (isinstance(c, dict) and c.get("field") == field)]
    if n_revoked:
        try:
            Path(cache_path).write_text(
                json.dumps(cdata, indent=2, ensure_ascii=False))
        except Exception:
            pass  # cache persistence is best-effort
    return n_revoked  # vars actually revoked (0 = no-op)


def _push_resolution_report(ws_id: str, stats: dict, orphan_fields: dict,
                            container_resolved: list | None = None,
                            *, s4c_seen: bool = False, n_cand: int = 0,
                            n_owner: int = 0, r6_total: int = 0,
                            owner_lines: list | None = None):
    """R20: coverage diagnostic — resolved vs total column variables.

    Supersedes the Bug-54 ORPHAN FIELD REPORT (same SQL-evidence mechanism
    for the residual orphans). Always pushed, even when every column is
    resolved. Shows up to 10 fields (name + first script + up to 3 SQL
    lines from that script mentioning the field, stripped to ~70 chars).
    E1 (reviewer): "resolved to output container" fields (⟐ output / CTE —
    script-scoped, no usable workspace table) are surfaced as a distinct
    bucket so nothing is invisible.

    S4b (Phase 2, AUTO-RESOLUTION): when new analyses carry the S4a keys
    (s4c_seen), a schema-candidates summary line (`schema candidates: N
    (unique visible owner found: M) | r6 collision: K`) plus one owner line
    per S4b attribution follows the strategy lines. M = S4b additions;
    N = candidate records remaining after S4a. Owner lines show the
    schema-EVIDENCE script/line (DDL / qualified ref — dict-of-dicts
    provenance) plus the bare-use loc when it differs; old-shape caches
    without provenance keep the Phase-1 candidate-loc format. Old caches
    without the keys produce a byte-identical block.

    M12 (review): the unresolved line additionally shows `ambiguous: N` —
    fields claimed by ≥2 DIFFERENT owners across scripts (never attributed;
    revoked attributions return to the UNRESOLVED section).
    """
    W = 80
    total = stats.get("total_columns", 0)
    resolved = stats.get("resolved", 0)
    coverage_pct = stats.get("coverage_pct", 0)
    by = stats.get("by_strategy", {})
    names = sorted(orphan_fields)
    n = len(names)
    cont = sorted(container_resolved or [])
    nc = len(cont)
    lines = ["┌─ ORPHAN RESOLUTION REPORT "
             + "─" * max(0, W - len("┌─ ORPHAN RESOLUTION REPORT ") - 1) + "┐"]
    lines.append(("│ column vars: %d | resolved: %d (%g%%) |"
                  % (total, resolved, coverage_pct)).ljust(W - 1) + "│")
    lines.append(("│   unresolved: %d | resolved-to-container (no table): %d"
                  " | ambiguous: %d" % (n, nc, stats.get("ambiguous", 0)))
                 .ljust(W - 1) + "│")
    lines.append(("│   by strategy (attribution events, not unique vars): "
                  "pa=%d ea=%d scope=%d schema=%d"
                  % (by.get("plain_alias", 0), by.get("expr_alias", 0),
                     by.get("scope", 0), by.get("schema", 0))).ljust(W - 1) + "│")
    lines.append(("│   (sys=%d other=%d marked expected)"
                  % (by.get("sys", 0), by.get("other", 0))).ljust(W - 1) + "│")
    if nc:
        lines.append(("│   container-resolved sample: %s"
                      % ", ".join(cont[:5])).ljust(W - 1) + "│")
    if s4c_seen:
        # S4 (Phase 1): SELECT-side schema candidates — REPORT ONLY. Only
        # shown when new analyses carry the keys; old caches keep the
        # pre-Phase-1 block byte-identical. Owner lines are sorted by field
        # name (caller builds them from `sorted(orphan_fields)`).
        lines.append(("│   schema candidates: %d (unique visible owner found:"
                      " %d) | r6 collision: %d" % (n_cand, n_owner, r6_total))
                     .ljust(W - 1) + "│")
        for fname, owner, script, loc_label, vis_txt in (owner_lines or []):
            loc_part = (" %s" % loc_label) if loc_label else ""
            # N2 (review): fname/owner/script are truncated, but a long
            # visible-list suffix (6 tables) still overflows the W=80 box —
            # drop the suffix when the line is tight, and clip the content
            # as the final guarantee. The evidence fragment (script + line)
            # always survives.
            base = ("│   field: %s → %s (evidence: %s%s%s)"
                    % (fname[:18], owner[:18], script[:24],
                       loc_part, vis_txt))
            if len(base) > W - 2 and vis_txt:
                base = ("│   field: %s → %s (evidence: %s%s)"
                        % (fname[:18], owner[:18], script[:24], loc_part))
            lines.append(base[:W - 2].ljust(W - 1) + "│")
    lines.append("│" + "─" * (W - 2) + "│")
    if n:
        lines.append(("│ UNRESOLVED orphans — possible bad cases, check SQL:")
                     .ljust(W - 1) + "│")
        for fname in names[:10]:
            script = (orphan_fields[fname] or [""])[0]
            lines.append(("│ field: %s   script: %s"
                          % (fname[:26], script[:32])).ljust(W - 1) + "│")
            # Line search ONLY for reported fields (keep indexing fast)
            sp = _resolve_orphan_script(ws_id, script)
            if sp:
                try:
                    sql_txt = sp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    sql_txt = ""  # unreadable script → no evidence lines (benign)
                needle = fname.lower()
                hits = [(i + 1, ln) for i, ln in enumerate(sql_txt.split("\n"))
                        if needle in ln.lower()]
                for lineno, ln in hits[:3]:
                    lines.append(("│ %s" % ("   L%d: %s" % (lineno, ln.strip()))[:70])
                                 .ljust(W - 1) + "│")
        if n > 10:
            lines.append(("│ ... %d more" % (n - 10)).ljust(W - 1) + "│")
    lines.append("└" + "─" * (W - 2) + "┘")
    for line in lines:
        _push(ws_id, "profile", line)


def autocomplete(index: dict, type_: str, query: str) -> list[str]:
    """Return matching names from the index (case-insensitive substring, max 20)."""
    if not query:
        return sorted(index.keys())[:20]
    q = query.lower()
    matches = [k for k in index if q in k.lower()]
    return sorted(matches)[:20]


def tables_for_field(index: dict, field: str) -> list[str]:
    """Return all tables containing the given field."""
    entry = index.get(field, {})
    return entry.get("tables", [])


def fields_for_table(index: dict, table: str) -> list[str]:
    """Return all fields of the given table."""
    entry = index.get(table, {})
    return entry.get("fields", [])


def get_index_status(ws_id: str) -> dict:
    """Return current indexing status."""
    ws_dir = get_workspace_dir(ws_id)
    meta_path = ws_dir / "meta.json"
    if not meta_path.exists():
        return {"indexed": False}
    meta = json.loads(meta_path.read_text())
    return {
        "indexed": meta.get("indexed", False),
        "script_count": len(meta.get("indexed_scripts", [])),
        "indexed_at": meta.get("indexed_at"),
    }
