"""Folder index service — scan directory tree, build table/field indexes."""
import gzip
import hashlib
import json
import os
import threading
from pathlib import Path

import sqlglot
from sqlglot import exp

from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.services.atomic_io import atomic_write_bytes, atomic_write_text
from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.services.workspace_service import (
    get_workspace_dir, get_script_path, read_meta, write_meta_cas,
)
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

# case1 (Fix A): SELECT-output aliases of NON-column expressions (CASE, NVL/
# TO_CHAR/SUBSTR/getdate, literals, aggregates, windows, generic computed
# expressions) are typed non-COLUMN by the extractor's
# _classify_aliased_expression and previously never entered field_index — so
# bank-ETL target columns written `INSERT INTO tgt SELECT <expr> AS col` were
# invisible to autocomplete. These ARE indexable fields when the variable is a
# genuine statement OUTPUT alias: `is_output` True (excludes CTE bodies) and a
# top-level statement context (excludes subquery-interior / JOIN / EXISTS
# scopes — those carry /subq, /exists, :join markers). #308: these are only
# attributed to a DML write target — a bare SELECT's output alias stays
# un-attributed (computed/derived aliases are not searchable).
_OUTPUT_ALIAS_TYPES = frozenset({
    "case", "transform", "literal", "aggregate", "window", "expression",
})


def _is_top_statement_context(context: str) -> bool:
    """True when ``context`` is a top-level statement output scope.

    Top-level statements are scoped ``TOP{n}`` (or ``TOP{n}/union{i}`` for a
    set-op branch of a top-level statement). Subquery-interior scopes always
    append a marker (``/subq…``, ``/exists…``, ``:join…``) and are excluded —
    their output aliases are not workspace-wide fields.
    """
    if not context or not context.startswith("TOP"):
        return False
    if "/subq" in context or "/exists" in context or ":join" in context:
        return False
    return True


def _is_renamed_output(v: dict, field_name: str) -> bool:
    """R46b: True when this output var's NAME RENAMES the value it projects.

    The extractor stamps the projected source text on the var —
    ``b.org_no AS nbjgh`` → ``sql_expression="b.org_no"`` (mirrored in
    ``source_columns``), ``name="nbjgh"``. Only a rename can produce a
    phantom pair: when the projected column's own bare name IS the var's
    name (``SELECT c.c_first_name …``, ``a.TAG_COUNTRY AS TAG_COUNTRY``)
    the name IS the read column's name, so attributing it to the read
    source is the ordinary S1-S3 read-column attribution (true schema
    evidence, e.g. every unaliased projection of a plain SELECT), never a
    phantom.

    No projected text (`sql_expression`/`source_columns` absent — old
    caches) → False, i.e. the historical read-source attribution stands:
    the discriminator must be extraction-time evidence, never a guess.
    """
    expr = str(v.get("sql_expression") or "").strip()
    if not expr:
        cols = [c for c in (v.get("source_columns") or []) if isinstance(c, str)]
        expr = cols[0].strip() if cols else ""
    if not expr:
        return False
    base = expr.split(".")[-1].strip("`\"'[] ").strip()
    return base.casefold() != str(field_name).casefold()


def _is_plain_field_name(field_name: str) -> bool:
    """True when ``field_name`` looks like a real column name.

    Fix A guard: unaliased expression projections auto-name to sanitized SQL
    fragments (``CASE_WHEN_a.fkfs='A'_…``, ``COUNT*``, ``'01'``) — never
    indexable field names. Require an identifier-shaped token (dots allowed
    for qualified aliases).
    """
    if not field_name:
        return False
    return all(ch.isalnum() or ch in "_.$#" for ch in field_name) \
        and (field_name[0].isalpha() or field_name[0] == "_")


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
                          parsed_cache: dict | None = None,
                          tree: dict | None = None) -> list[str]:
    """A1: rel_paths of schema-classified files in the workspace tree.

    Feeds the index-time schema evidence pass (S4b needs DDL evidence even
    when the caller's script list excludes schema files — the auto-select
    path does). C-13(a): `parsed_cache` (when given) receives the per-file
    parse from scan_folder so index_scripts reuses it instead of
    re-parsing every script for its A1 classification. #257: `tree` (when
    given) is a pre-scanned scan_folder result — the router already
    scanned for its script list, so passing the tree here avoids a second
    scan_folder (and its double parse + two-scan TOCTOU) per index request.
    """
    if tree is None:
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
    filtered_index.json are never touched by THIS deletion — the analysis
    caches are the S4b-mutated source of truth and must survive. (P1: the
    filtered scope is dropped separately, at the end of index_scripts — it
    is derived from the PREVIOUS index.) Returns the number of files
    deleted.
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

# ── P1 (v3.3.194): incremental re-index + freshness metadata ────────────
# A creator re-opening an existing workspace re-ran the whole extraction
# pipeline on every POST /index. Measured on the 106-pipeline-script
# tpcds_qualified corpus (dev container, v3.3.193): POST /scan 0.15s,
# POST /index 2.28–2.37s — identical on the 2nd and 3rd open, because
# nothing was reused: the per-script analysis caches (analysis_{key}.json,
# 7.4MB for this corpus) were REWRITTEN every run and never read back.
# Breakdown of the 2.2s index: run_full_analysis 1.50–1.63s (70%),
# S4b cache mutation 0.146s (7%), aggregation + star expansion + artifact
# writes ~0.43s (20%), analysis-cache writes 0.03s (1.4%).
#
# The index therefore persists, per script, the PRISTINE (pre-S4b) analysis
# result it extracted — keyed by the SAME md5(EXTRACTOR_VERSION|rel_path|
# sql_text) the analysis cache uses — plus the C-5 star detection and the
# A1 file class, gzipped (measured 10x: 7.4MB → 0.77MB). A later index
# whose script hashes to the same key REPLAYS that evidence instead of
# re-extracting:
#   * the pristine analysis is re-written to analysis_{key}.json exactly as
#     a fresh run would write it, so S4b starts from the same baseline —
#     the analysis cache is S4b-MUTATED in place, so replaying from a
#     mutated cache would move resolved_by["schema"], find no
#     schema_candidates records to remove and no unattributed var to
#     attribute, and the report would diverge from a full re-index;
#   * the aggregation, S4b (workspace-wide by design — it always re-runs,
#     on cached extracts) and the C-5 star expansion then run unchanged.
# ⇒ the artifacts are byte-identical to a full re-index for unchanged
# inputs (pinned by tests/test_incremental_index.py). Deletions, additions
# and edits all fall out of the same rule: a script absent from the caller's
# list contributes nothing, a new/changed key has no usable evidence and is
# extracted.
# mtimes are recorded ONLY for the advisory freshness hint (Job 2) — never
# for a reuse decision, which is content-md5 based.
EVIDENCE_PREFIX = "ixevidence_"          # + md5 key + ".json.gz"
MANIFEST_NAME = "index_manifest.json"    # per-file identity + freshness
_GZIP_LEVEL = 1                          # measured 10x at 5ms/40 scripts


def _script_cache_key(rel_path: str, sql_text: str) -> str:
    """The analysis-cache key — md5(EXTRACTOR_VERSION|rel_path|sql_text)[0:12].

    Single source for BOTH the analysis cache name and the evidence key, so
    a script's evidence can only ever be replayed onto its own cache.
    """
    return hashlib.md5(
        (EXTRACTOR_VERSION + "|" + rel_path + sql_text).encode()).hexdigest()[:12]


def _sql_md5(sql_text: str) -> str:
    """Content md5 of a script — the reuse/`changed` discriminator."""
    return hashlib.md5(sql_text.encode()).hexdigest()


def _evidence_name(cache_key: str) -> str:
    return f"{EVIDENCE_PREFIX}{cache_key}.json.gz"


def _load_manifest(cache_dir: Path, require_version: bool) -> dict | None:
    """Read cache/index_manifest.json.

    ``require_version=True`` (the reuse path) returns None unless the
    manifest was written by THIS extractor version — an older manifest is
    unusable as evidence even though its keys still match (the key embeds
    the version, so a mismatch is already a miss; this is the belt to that
    braces). ``require_version=False`` (the freshness read) returns whatever
    is on disk so the UI can say "indexed by an older engine".
    """
    try:
        data = json.loads((cache_dir / MANIFEST_NAME).read_text("utf-8"))
    except Exception:
        return None  # absent / corrupt → no evidence, no freshness
    if not isinstance(data, dict) or not isinstance(data.get("scripts"), dict):
        return None
    if require_version and data.get("extractor_version") != EXTRACTOR_VERSION:
        return None
    return data


def _write_json_atomic(path: Path, data: str) -> None:
    """Temp file + os.replace — a reader never sees a torn artifact.

    P1 (item 3-i): EVERY index/cache write goes through this (the shared
    `app.services.atomic_io` helper) — a concurrent reader (participant
    search, GET /index, l2_builder's cache read) previously observed a
    half-written file as a 500 or a silently-empty index.
    """
    atomic_write_text(path, data)


def _persist_evidence(cache_dir: Path, rel_path: str, cache_key: str,
                      sql_md5: str, file_class: str, star_tables: list,
                      result: dict, schemas_json: str | None = None) -> None:
    """Write the pristine pre-S4b analysis + star detection for one script.

    ``result`` is the run_full_analysis return BEFORE any S4b mutation —
    exactly the object index_scripts aggregates and the exact JSON the
    analysis cache receives, so a replay is byte-exact by construction.
    """
    payload = {
        "cache_key": cache_key,
        "rel_path": rel_path,
        "extractor_version": EXTRACTOR_VERSION,
        "sql_md5": sql_md5,
        "file_class": file_class,
        # C-5 detection (per script, order-preserving): the FROM/JOIN tables
        # of every unqualified star. Workspace-wide m_ws can change, so the
        # EXPANSION always re-runs — only the parse walk is cached.
        "star_tables": star_tables,
        "analysis": result,
        # the EXACT schemas_{key}.json text (already default=str-serialized),
        # so a replay restores it byte-identically if it went missing
        "schemas_json": schemas_json,
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        atomic_write_bytes(cache_dir / _evidence_name(cache_key),
                           gzip.compress(raw, _GZIP_LEVEL))
    except OSError:
        pass  # best-effort — a missing evidence file is a cache miss


def _detect_star_tables(parsed) -> list:
    """C-5 star DETECTION for one script — the FROM/JOIN tables of every
    UNQUALIFIED star, in parse-walk order, deduped.

    Purely local to the parse, so the list is replayable: the workspace-wide
    m_ws can change between runs, and the expansion (which consults it) is
    re-run every index — only this parse walk is cached.
    """
    if not parsed:
        return []
    out, seen = [], set()
    for _sel in _iter_select_nodes(parsed):
        for _t in _star_from_tables(_sel):
            if _t not in seen:
                seen.add(_t)
                out.append(_t)
    return out


def _record_manifest(manifest_scripts: dict, rel_path: str, cache_key: str,
                     sql_md5: str, file_class: str, sp: Path) -> None:
    """Record one covered SQL file's identity for cache/index_manifest.json.

    `cache_key`/`sql_md5` are BOTH the reuse decision (index time) and the
    change hint (read time) — content, never mtime. `size`/`mtime_ns` ride
    along as context for debugging only.
    """
    try:
        st = sp.stat()
        size, mtime_ns = st.st_size, st.st_mtime_ns
    except OSError:
        size, mtime_ns = None, None
    manifest_scripts[rel_path] = {
        "cache_key": cache_key,
        "sql_md5": sql_md5,
        "file_class": file_class,
        "size": size,
        "mtime_ns": mtime_ns,
    }


def _load_evidence(cache_dir: Path, cache_key: str) -> dict | None:
    """Load + validate one script's evidence (None = cache miss)."""
    path = cache_dir / _evidence_name(cache_key)
    try:
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except Exception:
        return None  # absent / corrupt / truncated → miss, re-extract
    if not isinstance(payload, dict):
        return None
    if (payload.get("cache_key") != cache_key
            or payload.get("extractor_version") != EXTRACTOR_VERSION
            or not isinstance(payload.get("analysis"), dict)
            or not isinstance(payload["analysis"].get("variables"), list)):
        return None
    return payload


def _restore_analysis_cache(cache_dir: Path, cache_key: str, evidence: dict) -> None:
    """Re-write analysis_{key}.json from evidence — PRISTINE, pre-S4b.

    The analysis cache is the S4b-mutated serving copy (C-3/C-10); a replay
    must reset it to the baseline a fresh extraction would have written, or
    the S4b pass below would apply to an already-mutated file.
    """
    _write_json_atomic(cache_dir / f"analysis_{cache_key}.json",
                       json.dumps(evidence["analysis"], indent=2,
                                  ensure_ascii=False))


def _restore_schemas_cache(cache_dir: Path, cache_key: str,
                           evidence: dict) -> None:
    """Re-create schemas_{key}.json from the evidence when it went missing —
    the exact bytes a full index would have written (the serialized form is
    snapshotted, not recomputed)."""
    if not evidence.get("schemas_json"):
        return  # never inferred (optional precompute) — nothing to restore
    path = cache_dir / f"schemas_{cache_key}.json"
    if path.exists():
        return
    try:
        _write_json_atomic(path, evidence["schemas_json"])
    except Exception:
        pass  # optional precompute — a missing file rebuilds on demand


def _prune_stale_evidence(cache_dir: Path, live_keys: set) -> int:
    """Delete evidence files no current script maps to (deleted scripts,
    superseded content, an older extractor version). Analysis caches are
    NOT touched here — their retention is l1_builder's business."""
    n = 0
    for p in cache_dir.glob(f"{EVIDENCE_PREFIX}*.json.gz"):
        if p.name[len(EVIDENCE_PREFIX):-len(".json.gz")] not in live_keys:
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


def manifest_class_cache(ws_id: str) -> dict:
    """Per-file A1 class records from the last index — for a caller that
    scans BEFORE indexing (POST /index), so scan_folder need not re-parse
    files whose content is unchanged.

    {} when there is no usable manifest (never indexed, or built by another
    extractor version). Values are {"sql_md5", "file_class"} only — mtime is
    never consulted here (content decides, always).
    """
    manifest = _load_manifest(get_workspace_dir(ws_id) / "cache",
                              require_version=True)
    out = {}
    for rel, rec in ((manifest or {}).get("scripts") or {}).items():
        if (isinstance(rec, dict) and isinstance(rel, str)
                and rec.get("file_class") in ("script", "schema")
                and isinstance(rec.get("sql_md5"), str)):
            out[rel] = {"sql_md5": rec["sql_md5"],
                        "file_class": rec["file_class"]}
    return out


def _iter_sql_files(ws_id: str) -> list:
    """Every SQL file in the workspace, as (rel_path, text) — a real os.walk
    over the directory (NEVER the persisted tree: a file added since the last
    index would be invisible to a tree walk), reading each file's content
    because the change signal is the CONTENT hash. Measured 0.002s for the
    108-file tpcds_qualified corpus."""
    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    out = []
    if not scripts_dir.exists():
        return out
    for root, _dirs, files in os.walk(scripts_dir):
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in SQL_EXTENSIONS or p.suffix.lower() \
                    in SCHEMA_EXTENSIONS:
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    txt = ""  # unreadable → hash of nothing (still counted)
                out.append((str(p.relative_to(scripts_dir)), txt))
    return sorted(out)


def index_change_diff(ws_id: str) -> dict | None:
    """Content-hash diff between the last index and the scripts on disk.

    The per-script identity the last index persisted
    (cache/index_manifest.json — md5 of the sql text + the derived
    EXTRACTOR_VERSION cache key) is compared against the CURRENT content of
    every SQL file. This is the same discriminator POST /index uses to decide
    which scripts to re-extract, so a zero diff means an index would replay
    every script from evidence and change nothing.

    P2 contract (catch-up UI): the counts are PIPELINE-scoped, so
    `changed_count` is exactly the number of scripts the incremental will
    re-extract and `total` is exactly the `progress.total` the existing
    /status poller already serves (both count pipeline scripts; DDL evidence
    files are evidence-only and never enter the script list). DDL churn is
    reported separately in `schema_changed_count` and still flips `stale` —
    lost DDL evidence would change S4b resolution. `added_count` covers new
    SQL files of either class: an un-indexed file's class is unknown until
    the scan parses it, so it self-corrects at index time.

    `changed_scripts` is a COUNT, not a list — the alias P2's readCatchUp()
    already reads; keep both spellings in sync if this ever grows a list.

    Returns None before the first index (nothing to diff against). O(files).
    """
    cache_dir = get_workspace_dir(ws_id) / "cache"
    manifest = _load_manifest(cache_dir, require_version=False)
    if manifest is None:
        return None
    recorded = manifest.get("scripts") or {}
    current = {rel: txt for rel, txt in _iter_sql_files(ws_id)}
    version_current = manifest.get("extractor_version") == EXTRACTOR_VERSION
    changed = added = removed = schema_changed = 0
    for rel, rec in recorded.items():
        if not isinstance(rec, dict):
            continue
        is_pipeline = rec.get("file_class") != "schema"
        if rel not in current:
            if is_pipeline:
                removed += 1
            else:
                schema_changed += 1
        elif (not version_current
              or _sql_md5(current[rel]) != rec.get("sql_md5")):
            if is_pipeline:
                changed += 1
            else:
                schema_changed += 1
    for rel in current:
        if rel not in recorded:
            added += 1  # class unknown until indexed — counted as pipeline
    total = sum(1 for rec in recorded.values()
                if isinstance(rec, dict) and rec.get("file_class") != "schema")
    if not version_current:
        # an older engine's index is stale wholesale: every recorded pipeline
        # script must be re-extracted, whatever its content did
        changed = max(changed, total)
        reason = "extractor_version"
    elif changed or added or removed or schema_changed:
        reason = "scripts_changed"
    else:
        reason = None
    return {
        "changed_scripts": changed,          # P2 alias (count, not a list)
        "changed_count": changed,
        "added_count": added,
        "removed_count": removed,
        "schema_changed_count": schema_changed,
        "total": total,
        "indexed_at": manifest.get("indexed_at"),
        "extractor_version": manifest.get("extractor_version"),
        "current_extractor_version": EXTRACTOR_VERSION,
        "stale": bool(changed or added or removed or schema_changed),
        "reason": reason,
    }


# Backwards-compatible alias for the first landing of the hint (Job 2) — the
# signal is now content-based, not the advisory size+mtime guess.
get_index_freshness = index_change_diff


def scan_folder(ws_id: str, parsed_cache: dict | None = None,
                *, class_cache: dict | None = None) -> dict:
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

    P1: `class_cache` (keyword-only) is the per-file identity the last index
    persisted — {rel_path: {"sql_md5", "file_class"}} (see
    `manifest_class_cache`). A .sql file whose CONTENT md5 matches its
    record is classified from that record and NOT parsed: the A1 class is
    content-derived, so an md5 match yields exactly the class a parse would,
    and the tree is byte-identical to a parsing scan. No parse is exported
    for such a file (there is none) — index_scripts replays it from
    evidence. Files with no record, or whose md5 differs, are parsed as
    always, so a fresh/edited/never-indexed workspace behaves exactly as
    before. Without `class_cache` (POST /scan, workspace create, the tests)
    the parse walk is untouched.
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
                    _txt = None
                    try:
                        _txt = path.read_text(encoding="utf-8",
                                              errors="replace")
                    except Exception:
                        # unreadable → script (conservative, no parse)
                        entry["file_class"] = "script"
                    if _txt is not None:
                        _rec = (class_cache or {}).get(entry["path"])
                        # P1: content-md5 match → the recorded A1 class IS the
                        # class this parse would produce; skip the parse.
                        if (_rec is not None
                                and _rec.get("sql_md5") == _sql_md5(_txt)):
                            entry["file_class"] = _rec["file_class"]
                        else:
                            try:
                                parsed = sqlglot.parse(_txt, read="mysql")
                            except Exception:
                                # unparsable → script (conservative)
                                entry["file_class"] = "script"
                            else:
                                entry["file_class"] = classify_sql_text(
                                    _txt, parsed=parsed)
                    if parsed_cache is not None and parsed is not None:
                        parsed_cache[entry["path"]] = parsed
        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                children.append(_walk(child))
            entry["children"] = children
        return entry

    return _walk(scripts_dir)


def index_scripts(ws_id: str, script_paths: list[str],
                  tree: dict | None = None,
                  parsed_cache: dict | None = None,
                  *, incremental: bool = True) -> dict:
    """Analyze selected scripts, build table_index and field_index.

    For each script:
      1. Read SQL from workspace/scripts/{path}
      2. Call run_full_analysis() — or REPLAY the persisted per-script
         evidence when EXTRACTOR_VERSION and the sql text are unchanged
      3. Extract table/column variables
      4. Build indexes

    #257: `tree` / `parsed_cache` are optional — a caller that already
    scanned the workspace (the /index router) threads its scan_folder
    result and its per-file parse cache in, so the schema-evidence
    discovery does not scan_folder a second time (double parse + two-scan
    TOCTOU). Direct callers pass neither and keep the scan-inside default;
    semantics stay faithful to `script_paths` (no merge, no auto-complete).

    #380 (AD2-A): the tree covered (the caller's, or the fallback scan) is
    persisted as cache/file_tree.json and the derived report fields as
    cache/index_report.json — the two artifacts the participant-readable
    GET /workspace/{ws_id}/tree and GET /workspace/{ws_id}/index serve,
    since POST /scan + /index are creator-only.

    P1: `incremental=False` disables evidence REUSE for this call (a full
    extraction of every script) while still persisting evidence — the knob
    the equivalence tests use to prove the two paths agree. Production
    callers keep the default: reuse is keyed on content (see the P1 block
    above), so a changed script is always re-extracted and a fresh workspace
    simply has no evidence to reuse. Artifacts written: table_index.json,
    field_index.json, pair_index.json, orphan_fields.json, index_report.json,
    file_tree.json, index_manifest.json (per-file identity + freshness) and
    ixevidence_{key}.json.gz (per-script pristine analysis).

    Returns: {table_index, field_index, precomputed_count,
              star_expanded_fields, script_count, errors,
              orphan_field_count, orphan_field_samples, resolution_stats,
              schema_candidates_summary, schema_evidence} — the report
              fields are exactly the persisted index_report.json payload;
              resolution_stats carries the R20 coverage numbers aggregated
              from per-script extraction + the S4b cross-script schema pass
              (plus `ambiguous` — fields claimed by ≥2 DIFFERENT owners
              across scripts: never attributed, revoked from the index,
              counted and reported).
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
    # #257: the router may thread its pre-scanned tree AND this cache (it
    # calls scan_folder(ws_id, parsed_cache=...) at the call site),
    # collapsing the two scans into one; direct callers keep the
    # empty-cache default.
    if parsed_cache is None:
        parsed_cache = {}
    # P1: C-5 star detection per pipeline script (insertion order = script
    # order). The extraction path detects from the C-13(a) single parse; the
    # replay path reads the detection the same run persisted.
    star_by_script: dict = {}
    # P1: the per-file identity THIS index covers → cache/index_manifest.json
    manifest_scripts: dict = {}
    n_replayed = 0
    n_extracted = 0
    cache_dir = get_workspace_dir(ws_id) / "cache"
    prev_manifest = _load_manifest(cache_dir, require_version=True) \
        if incremental else None
    prev_scripts = (prev_manifest or {}).get("scripts") or {}

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
    # #380 (AD2-A): resolve the tree THIS index covered up front, so the
    # same object can be persisted as cache/file_tree.json for
    # participant reads. When the caller threaded a tree (#257 router
    # path) it is used as-is; otherwise the fallback scan happens HERE
    # instead of inside _collect_schema_files — same single scan, same
    # parsed_cache exports (C-13(a) one-parse-per-script is unchanged),
    # and the result is no longer discarded. P1: the fallback scan reuses
    # the persisted A1 classes (content-md5 keyed) so an unchanged file is
    # not re-parsed here either.
    covered_tree = tree
    if covered_tree is None:
        try:
            covered_tree = scan_folder(ws_id, parsed_cache=parsed_cache,
                                       class_cache=manifest_class_cache(ws_id)
                                       if incremental else None)
        except Exception as e:
            errors.append({"script": "(schema discovery)", "error": str(e)})
    if covered_tree is not None:
        try:
            schema_evidence_paths = set(_collect_schema_files(
                ws_id, parsed_cache, tree=covered_tree))
        except Exception as e:
            errors.append({"script": "(schema discovery)", "error": str(e)})
    else:
        # scan_folder itself failed — the discovery below cannot run
        # without a tree; surface it rather than silently skipping (a
        # second failing scan inside _collect_schema_files would only
        # duplicate the error entry).
        errors.append({"script": "(schema discovery)",
                       "error": "workspace scan failed — no file tree"})
    for _rel in sorted(schema_evidence_paths):
        _process_schema_evidence(ws_id, _rel, m_ws,
                                 schema_evidence_by_script, errors,
                                 cache_dir=cache_dir,
                                 prev_scripts=prev_scripts,
                                 manifest_scripts=manifest_scripts)

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
            # P1: the script's identity. The key is content-derived, so an
            # unchanged script (same EXTRACTOR_VERSION + same text) hashes to
            # the same key — the ONLY reuse signal. mtime is never consulted.
            cache_key = _script_cache_key(rel_path, sql_text)
            sql_md5 = _sql_md5(sql_text)
            cache_path = cache_dir / f"analysis_{cache_key}.json"

            # ── P1: evidence replay (incremental re-index) ──
            # A previous index recorded this exact content (same key) and its
            # pristine analysis survived intact → replay it instead of
            # re-running the extraction pipeline. The replay is byte-exact:
            # the same pristine `result` enters the same aggregation and the
            # same S4b / star passes below; only the analysis cache is
            # re-written (from pristine — the on-disk copy is the S4b-mutated
            # serving copy of the previous run and must be reset, see
            # `_restore_analysis_cache`).
            _prev = prev_scripts.get(rel_path)
            evidence = (_load_evidence(cache_dir, cache_key)
                        if (incremental and isinstance(_prev, dict)
                            and _prev.get("cache_key") == cache_key) else None)
            if evidence is not None and evidence.get("file_class") == "schema":
                # A1: an explicitly-named DDL-only file whose DDL is
                # unchanged — replay its script_schemas (no analysis cache is
                # written for schema evidence, same as the fresh path).
                _merge_script_schemas(evidence["analysis"], rel_path, m_ws,
                                      schema_evidence_by_script)
                _record_manifest(manifest_scripts, rel_path, cache_key,
                                 sql_md5, "schema", sp)
                _set_progress(ws_id, i + 1, total, "analyzing")
                continue

            if evidence is None:
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
                                             schema_evidence_by_script, errors,
                                             cache_dir=cache_dir,
                                             prev_scripts=prev_scripts,
                                             manifest_scripts=manifest_scripts)
                    _set_progress(ws_id, i + 1, total, "analyzing")
                    continue
                result = run_full_analysis(sql_text, rel_path, ws_id=ws_id)
                n_extracted += 1
                # C-5: the C-13(a) single parse is reused for star detection —
                # never a new parse. None (unparsable) → nothing detected.
                star_tables = _detect_star_tables(parsed)

                # C-3 (review): the analysis cache key discriminates the
                # extractor engine — md5 over (EXTRACTOR_VERSION, rel_path,
                # sql_text). A stale cache written by an older engine can never
                # match this key (the load-time extractor_version stamps in
                # l2_builder/dataflow_service guard SERVING; the discriminator
                # guards the key itself — exact-key consumers miss and rebuild
                # lazily, same philosophy as the J12-8 cache-purge ruling:
                # caches are a rebuild-time optimization). Glob consumers
                # (l1_builder, filter_service) are key-agnostic, so the legacy
                # versionless file for the same script is deleted below —
                # otherwise it would coexist and could serve pre-this-run
                # analysis under a sorted-name pick.
                _legacy_path = cache_dir / ("analysis_"
                                            + hashlib.md5(
                                                (rel_path + sql_text).encode())
                                            .hexdigest()[:12] + ".json")
                if _legacy_path.exists():
                    try:
                        _legacy_path.unlink()  # best-effort — leftover rebuilds on demand
                    except OSError:
                        pass
                _write_json_atomic(cache_path,
                                   json.dumps(result, indent=2,
                                              ensure_ascii=False))

                # C-2: index-time GRAPH caches are no longer precomputed here —
                # any graph written before the S4b pass is pre-S4b and stale, so
                # the post-S4b invalidation (_invalidate_graph_caches) would
                # delete it moments later (pure double-analysis per script). L2
                # rebuilds on demand from the post-S4b analysis cache and its
                # miss path writes the graph cache itself. Only the schema
                # precompute survives — L2 cache hits use it without re-analysis.
                # P1: the serialized form rides the evidence snapshot too, so a
                # replayed script can restore a missing schemas_{key}.json
                # byte-identically (a full index would have recomputed it).
                schemas_json = None
                try:
                    from app.extractor.schema_inference import infer_table_schemas
                    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
                    if not schemas_cache_path.exists():
                        schemas_json = json.dumps(
                            infer_table_schemas(result.get("variables", []),
                                                result.get("dependencies", [])),
                            default=str)
                        _write_json_atomic(schemas_cache_path, schemas_json)
                except Exception:
                    schemas_json = None  # schema pre-computation is optional

                # P1: the pristine pre-S4b copy this script can be replayed
                # from on the next index.
                _persist_evidence(cache_dir, rel_path, cache_key, sql_md5,
                                  "script", star_tables, result,
                                  schemas_json=schemas_json)
                _record_manifest(manifest_scripts, rel_path, cache_key,
                                 sql_md5, "script", sp)
            else:
                n_replayed += 1
                result = evidence["analysis"]
                star_tables = evidence.get("star_tables") or []
                _restore_analysis_cache(cache_dir, cache_key, evidence)
                _restore_schemas_cache(cache_dir, cache_key, evidence)
                _record_manifest(manifest_scripts, rel_path, cache_key,
                                 sql_md5, evidence.get("file_class")
                                 or "script", sp)

            script_count += 1
            pipeline_paths.append(rel_path)
            star_by_script[rel_path] = star_tables
            cache_by_script[rel_path] = str(cache_path)  # S4b persists attributions
            _set_progress(ws_id, i + 1, total, "analyzing")

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
            # X2 (review): ANY script carrying resolution_stats arms the
            # extractor-driven report — this was `stats_seen = isinstance(...)`,
            # so the LAST script's analysis decided the gate for the WHOLE
            # report. A corpus whose final script is an old/shapeless analysis
            # (an evidence snapshot predating resolution_stats, or a legacy
            # cache) silently flipped the report to the tables==[] fallback:
            # every container-resolved field (⟐/CTE) became a phantom orphan,
            # while total_columns stayed a partial sum — coverage_pct wrong in
            # both directions, and order-dependent (the same workspace indexed
            # in a different script order reported differently).
            stats_seen = stats_seen or isinstance(rs, dict)
            # …and the per-script ACCUMULATION still reads only scripts that
            # actually have the key (this script's `rs` may be None while an
            # earlier one armed the gate).
            if isinstance(rs, dict):
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
            # Fix A (case1): map each DML dependency's source var → the target
            # TABLE var's name, so INSERT/UPDATE/MERGE SELECT-output aliases
            # are attributed to the WRITE target (east5_stzfxxb) rather than
            # the source table.
            var_by_id = {v2.get("id"): v2 for v2 in variables}
            dml_target_by_src_id = {}
            for dep in result.get("dependencies", []):
                if dep.get("relationship") != "DML":
                    continue
                sid = dep.get("source_id")
                tgt = var_by_id.get(dep.get("target_id"))
                if sid and tgt and tgt.get("variable_type") in ("table", "merge_target"):
                    dml_target_by_src_id[sid] = tgt.get("name", "")
            for v in variables:
                vt = v.get("variable_type", "")
                name = v.get("name", "")
                context = v.get("context", "")

                if vt in ("table", "merge_target"):
                    # merge_target (MERGE target table) is a physical write
                    # target like `table` — it must get the same script
                    # attribution so the table surfaces in autocomplete.
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
                    #
                    # R46b (AD3, 2026-08-31): a top-level statement OUTPUT whose
                    # NAME renames the value it projects (`b.lending_ref AS
                    # xdjjh`) is the TARGET column produced here, not a column
                    # of the table the value was read from — the alias NAME is
                    # attributed to the DML WRITE TARGET only
                    # (dml_target_by_src_id, Fix A's map), NEVER to the value's
                    # read source. Attributing it to `source_tables` indexed a
                    # column the source table does not own (7 phantom pairs on
                    # the S1 corpus:
                    # bdm_acc_loan_info.{nbjgh,xdhth,xdjjh,dkje} and
                    # bdm_acc_entrusted_payment.{bz,RESERVED_6,COM_RESERVED_1});
                    # search then offered those pairs and the model hosts no
                    # such column there — zero-seed closures / mis-parented
                    # chips (#37). This is the SAME convention the Fix A branch
                    # below (#308) already applies to non-column expression
                    # aliases: write target only, and a bare SELECT's renamed
                    # output alias stays un-attributed (no write target → no
                    # table). Nothing is lost on the read side: a renamed
                    # projection's value column is a SEPARATE non-output var
                    # (`a.ccy_code`), and it keeps indexing ccy_code under the
                    # read source. A projection that does NOT rename its value
                    # (`SELECT c.c_first_name`, `a.TAG_COUNTRY AS TAG_COUNTRY`)
                    # is not a phantom — the name is the read column's own name
                    # and keeps the S1-S3 read attribution
                    # (_is_renamed_output). Subquery-interior / JOIN / EXISTS
                    # scopes are excluded by _is_top_statement_context, exactly
                    # as in Fix A — their aliases are not workspace-wide
                    # fields.
                    if not table_name:
                        if (v.get("is_output") and _is_top_statement_context(context)
                                and _is_renamed_output(v, field_name)):
                            table_name = dml_target_by_src_id.get(v.get("id", ""), "")
                        else:
                            for _st in v.get("source_tables", []):
                                if (_st and not _st.startswith("⟐")
                                        and _st not in cte_names):
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
                            # F2 (audit #383): a table entry that receives a
                            # field from this script must also record the
                            # script — create_search matches scripts via
                            # field_index[f].scripts ∩ table_index[t].scripts,
                            # so a fields-without-scripts entry (CTE names,
                            # aliases, derived containers — none of which get
                            # the vt=="table" attribution above) is a silent
                            # no_matches for every search that names it
                            # (TEMP_RFN.dkjjbm).
                            table_index[tname]["scripts"].add(rel_path)

                elif vt in _OUTPUT_ALIAS_TYPES and v.get("is_output") \
                        and _is_top_statement_context(context):
                    # Fix A (case1): SELECT-output aliases of non-column
                    # expressions are indexable fields — a bank-ETL target
                    # column written `INSERT INTO tgt SELECT <expr> AS col` is
                    # the very field the user searches for. Attributed ONLY to
                    # the DML write target (INSERT / UPDATE / MERGE via
                    # dml_target_by_src_id); a bare SELECT's output alias has
                    # no physical table — computed/derived aliases are not
                    # searchable (#308). Name guard: unaliased expression
                    # projections auto-name to SQL fragments — never indexed.
                    field_name = name.split(".", 1)[-1] if "." in name else name
                    if not _is_plain_field_name(field_name):
                        continue
                    table_name = dml_target_by_src_id.get(v.get("id", ""), "")
                    field_index.setdefault(field_name, {"tables": set(), "scripts": set()})
                    field_index[field_name]["scripts"].add(rel_path)
                    if table_name:
                        physical = alias_to_physical.get(table_name, table_name)
                        for tname in {table_name, physical}:
                            field_index[field_name]["tables"].add(tname)
                            table_index.setdefault(tname, {"fields": set(), "scripts": set()})
                            table_index[tname]["fields"].add(field_name)
                            # F2 (audit #383): same invariant as the column
                            # branch — fields from this script imply the
                            # script in table_index[tname].scripts.
                            table_index[tname]["scripts"].add(rel_path)

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
                    # F2 (audit #383): same invariant — the fields just
                    # attributed to the write target imply this script.
                    table_index[tgt_table]["scripts"].add(rel_path)
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
            # C-3: mirror the current-index branch — the revoked field
            # returns to the unresolved pool (the star-expansion exclusion
            # and the orphan-report unresolved set both read it).
            extractor_unresolved.add(_f)
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
        # F2 (audit #383): S4b is a field-attribution site too — the field
        # attributed here implies the candidate's script on BOTH the field
        # and the owner table (create_search matches field_scripts ∩
        # table_scripts, so a schema-resolved field must carry its defining
        # script like every other attribution site).
        field_index[_f]["scripts"].add(_srec)
        table_index[owner]["fields"].add(_f)
        table_index[owner]["scripts"].add(_srec)
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
    # cache hits. Delete them all (current prefix + older-prefix leftovers);
    # L2 rebuilds on demand from the S4b-mutated analysis.
    # P1 (item 3-i): the deletion itself moved to the END of the index (after
    # the last artifact write) — a graph cache a concurrent L2 build wrote
    # from the PREVIOUS run's analysis caches mid-index must not survive into
    # the new state.

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
    # parse. P1: a replayed script contributes the detection its own
    # extraction persisted (`star_tables` in the evidence) — m_ws is
    # workspace-wide, so the EXPANSION always re-runs against the current
    # evidence pool; only the parse walk is cached.
    # P1 (determinism): `_evidence_columns` returns the m_ws SET, whose
    # iteration order is hash-seed dependent — the field_index/table_index
    # KEY ORDER (and pair_index's, which derives from it) differed between
    # processes for the same input. Iterating the sorted columns makes the
    # artifacts byte-stable (the per-entry lists were already sorted before
    # serialization, so no content changes).
    star_expanded_fields = 0
    _star_seen = set()
    # C-5↔C-3 (review): fields S4b revoked (ambiguous — claimed by ≥2
    # different owners, returned to the unresolved pool) or left unresolved
    # by the extractor must NOT re-enter the index via star evidence. This
    # pass runs AFTER S4b, so a star over the owning table would otherwise
    # resurrect a revoked field into field_index/pair_index.
    _star_excluded = extractor_unresolved | ambiguous_fields
    # C-5 (case-insensitive): the revoked/unresolved sets are recorded in
    # original case while star evidence can arrive in any case — a
    # mixed-case field would otherwise resurrect via star. Lowered set
    # computed once, outside the loop.
    _star_excluded_lower = {x.lower() for x in _star_excluded}
    for _rel, _tables in star_by_script.items():
        for _t in _tables:
            _cols = _evidence_columns(m_ws, _t)
            if not _cols:
                continue  # no schema evidence → skip silently
            for _c in sorted(_cols):
                if _c.lower() in _star_excluded_lower:
                    continue  # revoked/unresolved — never resurrect
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
                # F2 (audit #383): star expansion is a field-attribution
                # site too — the star over _t in this script implies the
                # script on the table entry (fields-without-scripts
                # zombies break the create_search intersection).
                table_index[_t]["scripts"].add(_rel)
                star_expanded_fields += 1

    # P1: Build pair_index[(table,field)] → {scripts} for fast seed-script lookup.
    # Used by Algorithm 2 step 2a to find seed scripts without scanning all data.
    # Built AFTER S4 so schema attributions are included.
    cache_dir = get_workspace_dir(ws_id) / "cache"
    pair_index = {}
    for field_name, fdata in field_index.items():
        # P1 (determinism): `tables` is still a SET here (the sorted-list
        # conversion happens below) — its iteration order is hash-seed
        # dependent, so pair_index.json's KEY order differed between
        # processes for identical input. Sorting changes nothing else (the
        # values are sorted lists already).
        for table_name in sorted(fdata.get("tables", [])):
            key = f"{table_name}.{field_name}"
            pair_index.setdefault(key, set()).update(fdata.get("scripts", []))

    # Cache pair_index
    _write_json_atomic(cache_dir / "pair_index.json", json.dumps(
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
    _write_json_atomic(cache_dir / "table_index.json",
                       json.dumps(table_index, indent=2))
    _write_json_atomic(cache_dir / "field_index.json",
                       json.dumps(field_index, indent=2))

    # #380 (AD2-A, participant reads): persist the tree THIS index covered —
    # the same scan_folder shape the create path returns inline (name/path/
    # type/is_sql + A1 file_class). POST /scan and POST /index are
    # creator-only since #380, and they were the only sources of the tree, so
    # a participant opening a shared workspace had no way to obtain it. This
    # write is the read-only half of the fix: GET /workspace/{ws_id}/tree
    # serves this file to any session. Skipped only when the scan itself
    # failed (already surfaced in `errors`) — no tree, nothing to serve.
    if covered_tree is not None:
        _write_json_atomic(cache_dir / "file_tree.json",
                           json.dumps(covered_tree, indent=2))

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
    _write_json_atomic(cache_dir / "orphan_fields.json",
                       json.dumps(orphan_fields, indent=2))

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

    # ── #380 (AD2-A, participant reads): persist the derived report ──
    # The ORPHAN RESOLUTION REPORT above goes to the live SSE stream only,
    # and these fields exist nowhere on disk (orphan_fields.json carries the
    # orphan set, meta.json the indexed flag) — so a participant reading the
    # caches saw a blank ResolutionReport. One dict, two consumers: the
    # index_scripts return and cache/index_report.json (served by
    # GET /workspace/{ws_id}/index). Same values as the return — never a
    # divergent copy.
    index_report = {
        "script_count": script_count,
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
        "schema_evidence": {
            "present": len(m_ws) > 0,
            "tables": len(m_ws),
            "columns": sum(len(c) for c in m_ws.values()),
        },
    }
    _write_json_atomic(cache_dir / "index_report.json",
                       json.dumps(index_report, indent=2))

    # ── P1 (Job 3): the per-file identity manifest ──
    # Written on EVERY index (full or incremental) so the next open can
    # decide, per script, whether its evidence is reusable, and so
    # GET /workspace/{id}/index and /resume can serve the change hint
    # (P1 Job 2 → superseded by the content-hash diff the same manifest
    # drives). Content hash + cache key are the reuse truth; size/mtime_ns
    # ride along as context only.
    from datetime import datetime, timezone as _tz
    manifest = {
        "indexed_at": datetime.now(_tz.utc).isoformat(),
        "extractor_version": EXTRACTOR_VERSION,
        "index_kind": "incremental" if n_replayed else "full",
        "reused_scripts": n_replayed,
        "extracted_scripts": n_extracted,
        "schema_files": sum(1 for v in manifest_scripts.values()
                            if v.get("file_class") == "schema"),
        "scripts": manifest_scripts,
    }
    _write_json_atomic(cache_dir / MANIFEST_NAME,
                       json.dumps(manifest, indent=2))
    # Evidence for scripts that no longer exist (deleted, or superseded by
    # an edit / an extractor bump) is dead weight — drop it. Analysis caches
    # are intentionally NOT pruned here (their retention is l1_builder's).
    _prune_stale_evidence(cache_dir,
                          {v["cache_key"] for v in manifest_scripts.values()})

    # ── P1 (item 3-ii): the filter scope is derived from the PREVIOUS index ──
    # filtered_index.json is built by filter_service.apply_filter_config from
    # the table/field index at upload time (the CSVs are NOT persisted), and
    # every index consumer PREFERS it over the full index — so after any
    # re-index the search kept running inside the OLD scope: a script added
    # since was invisible, a deleted one still matched. Rebuilding would need
    # the CSVs, which do not exist on disk, so the only honest refresh is to
    # drop the derived scope and say so: the creator re-uploads the CSVs (the
    # workspace's index content changed under them anyway).
    filtered_cleared = False
    _fp = cache_dir / "filtered_index.json"
    if _fp.exists():
        try:
            _fp.unlink()
            filtered_cleared = True
        except OSError:
            pass  # a stale scope survives; surfaced as an error below
    if filtered_cleared:
        _push(ws_id, "profile",
              "│ Filter scope cleared: the index was re-indexed, so the "
              "previous table/field filter no longer matches it — re-upload "
              "the CSVs to re-apply.")

    # ── C-2(a): stale graph caches vs the S4b pass — LAST ──
    # Deleted after every artifact write so a graph cache a concurrent L2
    # build wrote from the PREVIOUS run's analysis caches mid-index cannot
    # survive into the new state (pre-S4b / pre-re-index data on an L2 cache
    # hit).
    _invalidate_graph_caches(cache_dir)

    # Update workspace meta — CAS (P1 item 4): a read-modify-write here used
    # to race a concurrent layout save (which bumps state_version) and drop
    # its bump. Merge OUR keys onto whatever is stored now, and retry on a
    # stale version instead of overwriting it.
    meta = read_meta(ws_id)
    for _attempt in range(5):
        if meta is None:
            break  # no meta.json — nothing to update (create path owns it)
        expected = int(meta.get("state_version", 0))
        meta["indexed"] = True
        # A1: only pipeline scripts — schema files are evidence-only, never
        # part of the workspace's script list.
        meta["indexed_scripts"] = pipeline_paths
        meta["indexed_at"] = manifest["indexed_at"]
        if write_meta_cas(ws_id, meta, expected):
            break
        meta = read_meta(ws_id)  # someone else wrote — merge onto theirs

    _set_progress(ws_id, total, total, "done")
    return {
        "table_index": table_index,
        "field_index": field_index,
        "precomputed_count": precomputed,
        # C-5: number of (script, table, column) entries added by the
        # post-loop star expansion (SELECT */INSERT…SELECT * over
        # schema-evidence tables). 0 when no unqualified star has schema
        # evidence — no padding.
        "star_expanded_fields": star_expanded_fields,
        # P1 (item 3-ii): a filter scope derived from the PREVIOUS index was
        # dropped — the index it filtered no longer describes the workspace.
        "filtered_index_cleared": filtered_cleared,
        # P1: how much of this index was replayed from per-script evidence
        # (0 on a first index / after an extractor bump).
        "reused_scripts": n_replayed,
        "extracted_scripts": n_extracted,
        # #380 (AD2-A): the persisted index_report — identical values, so
        # the HTTP return and cache/index_report.json can never diverge.
        **index_report,
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
                             errors: list, cache_dir: Path | None = None,
                             prev_scripts: dict | None = None,
                             manifest_scripts: dict | None = None) -> None:
    """A1: schema-file evidence pass — run a DDL-only file through the
    analysis pipeline and merge its script_schemas into the S4b maps.

    Schema files are never pipeline scripts: no script_count, no table/
    field index entries (so no filter-scope or L1/L2 involvement) and no
    analysis/graph caches. Analysis failures are surfaced in `errors` —
    lost DDL evidence silently changes S4b resolution, so it must be
    visible.

    P1: when `cache_dir` + `manifest_scripts` are given the DDL analysis is
    persisted as per-script evidence too (DDL is re-analysed on every index
    otherwise — the same cost class as a pipeline script), and an unchanged
    DDL file is replayed from it. No analysis_*.json is written for schema
    evidence, before or after this change.
    """
    sp = get_script_path(ws_id, rel_path)
    if not sp or not sp.exists():
        return  # stale tree entry — the main loop reports missing files
    from app.extractor.adapter import run_full_analysis
    try:
        sql_text = sp.read_text(encoding="utf-8", errors="replace")
        cache_key = _script_cache_key(rel_path, sql_text)
        sql_md5 = _sql_md5(sql_text)
        _prev = (prev_scripts or {}).get(rel_path)
        evidence = (_load_evidence(cache_dir, cache_key)
                    if (cache_dir is not None
                        and manifest_scripts is not None
                        and isinstance(_prev, dict)
                        and _prev.get("cache_key") == cache_key) else None)
        if evidence is not None:
            _merge_script_schemas(evidence["analysis"], rel_path, m_ws,
                                  schema_evidence_by_script)
            _record_manifest(manifest_scripts, rel_path, cache_key, sql_md5,
                             evidence.get("file_class") or "schema", sp)
            return
        result = run_full_analysis(sql_text, rel_path, ws_id=ws_id)
        if cache_dir is not None and manifest_scripts is not None:
            _persist_evidence(cache_dir, rel_path, cache_key, sql_md5,
                              "schema", [], result)
            _record_manifest(manifest_scripts, rel_path, cache_key, sql_md5,
                             "schema", sp)
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

    C-4 (review): the `unresolved` drop + `resolved_by["schema"]` +1 are
    gated on a REAL attribution event (n_attributed > 0) — the mirror of
    the revoke side's `n_revoked > 0` gate. An M13 context-mismatch no-op
    (the var's context is not in the candidate's recorded contexts) must
    never move the persisted counters, exactly like the in-memory caller
    gate (`by_strategy["schema"]` counts only n_attributed > 0 events).

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
        # C-4: the persisted counters move only on a REAL attribution
        # event (n_attributed > 0) — mirror the revoke side's
        # `n_revoked > 0` gate (`:1164`). An M13 context-mismatch no-op
        # (no var matched the candidate's contexts) must not drop the
        # field from unresolved or bump resolved_by["schema"].
        if (n_attributed > 0 and isinstance(ul, list) and field in ul):
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
            # P1 (item 3-i): atomic — a reader (l1_builder glob, L2 cache
            # load) must never see a half-written analysis cache.
            _write_json_atomic(Path(cache_path),
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
            # P1 (item 3-i): atomic — see _apply_s4b_cache_update.
            _write_json_atomic(Path(cache_path),
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


def _levenshtein_le1(a: str, b: str) -> bool:
    """True when the edit distance between ``a`` and ``b`` is <= 1.

    Fast path: lengths must differ by at most 1 (each edit changes length by
    at most 1), then a bounded DP bails as soon as every row cell exceeds 1.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        cur = [j]
        row_min = j
        for i, ca in enumerate(a, 1):
            cost = 0 if ca == cb else 1
            val = min(prev[i] + 1, cur[-1] + 1, prev[i - 1] + cost)
            cur.append(val)
            if val < row_min:
                row_min = val
        if row_min > 1:
            return False
        prev = cur
    return prev[-1] <= 1


def autocomplete(index: dict, type_: str, query: str) -> list[str]:
    """Return matching names from the index (max 20).

    Primary matcher: case-insensitive substring. When that returns <2 results
    (0 hits — likely a typo — or a single mid-substring hit), a typo-tolerant
    fallback is added: Levenshtein-distance-<=1 keys, ranked exact > prefix >
    distance-1 (substring hits ride the top). This makes a query with one
    extra/missing/wrong character (case1: ``EAST5_SSTZFXXB`` typed against the
    real ``east5_stzfxxb``) still surface the intended name.
    """
    if not query:
        return sorted(index.keys())[:20]
    q = query.lower()
    sub = sorted(k for k in index if q in k.lower())
    exact = sorted(k for k in index if k.lower() == q)
    prefix = sorted(k for k in index if k.lower().startswith(q))
    # Only short-circuit on an exact/prefix hit — those are confident matches.
    # A substring-only hit (however many) is NOT a confidence signal, so the
    # Levenshtein-<=1 fallback still runs and a typo'd key (one extra/missing/
    # wrong char) can surface the intended name.
    if exact or prefix:
        ranked: list[str] = []
        seen: set[str] = set()
        for k in sub + exact + prefix:
            kl = k.lower()
            if kl not in seen:
                seen.add(kl)
                ranked.append(k)
        return ranked[:20]
    dist1 = sorted(
        k for k in index
        if k.lower() not in {e.lower() for e in exact}
        and k.lower() not in {p.lower() for p in prefix}
        and _levenshtein_le1(k.lower(), q))
    ranked: list[str] = []
    seen: set[str] = set()
    for k in sub + exact + prefix + dist1:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            ranked.append(k)
    return ranked[:20]


# ── F5 (audit #383, R2.10) at the SEARCH layer ──────────────────────────
# SQL identifiers are case-insensitive, but the index keys carry whatever
# casing each script WROTE (`dm_flag2` in one script, `DM_FLAG2` in the
# next). The frontend already resolves a typed name case-insensitively
# (`resolveNameCi()` in utils/nameFilter.js) — but resolution at the UI is
# only an echo: the backend matched index keys EXACTLY, so two case
# variants of one column resolved to DISJOINT script sets and a
# natural-spelling query missed the index outright. These helpers are the
# backend half of the same ruling, built on ISSUE-4's case-insensitive
# physical-table identity (2026-08-25.1, `_canonicalize_table_names` /
# `_majority_spelling` in the extractor): case variants are ONE identity,
# never competing alternatives.

def _majority_index_spelling(index: dict, keys: list[str]) -> str:
    """Canonical spelling of a case-variant key group — the index-level
    form of the extractor's ISSUE-4 `_majority_spelling` rule (most votes
    first, lowercase preferred on a tie, then first-seen).

    The index has no per-occurrence votes, so the closest available
    frequency signal is used: the number of scripts that recorded the
    spelling (`entry["scripts"]`). Ties fall back exactly like the
    extractor — a lowercase spelling beats a non-lowercase one, then the
    index's own key order (insertion = first-seen during indexing)
    decides. Deterministic for a given index, whatever casing arrives.
    """
    order = {k: i for i, k in enumerate(index.keys())}

    def _rank(k: str):
        n_scripts = len((index.get(k) or {}).get("scripts") or [])
        return (-n_scripts, 0 if k.islower() else 1, order.get(k, len(order)))

    return sorted(keys, key=_rank)[0]


def resolve_name_ci(index: dict, query: str) -> tuple:
    """Resolve a typed table/field name against an index, case-insensitively.

    Returns ``(canonical_key, group_keys)``:

    * ``group_keys`` — EVERY index key equal to ``query`` case-insensitively.
      The caller must UNION the entries' script sets: the variants are one
      index identity (ISSUE-4), so `dm_flag2` and `DM_FLAG2` can never
      resolve to disjoint script sets again.
    * ``canonical_key`` — the single spelling a search echoes and hands to
      the L1/L2 builders. The exact key wins (the frontend `resolveNameCi`
      ruling: a caller that sent a real index key must not be rewritten);
      otherwise the group's ISSUE-4 majority spelling
      (`_majority_index_spelling`) — deterministic when several scripts
      wrote the same identifier in different cases. The frontend's
      autocomplete collation (exact > prefix > Levenshtein,
      `autocomplete()` below — already case-insensitive) is a DROPDOWN
      ranking, deliberately NOT a search-resolution rule: falling back to
      prefix/Levenshtein here would answer a question the user did not
      ask.
    * ``(None, [])`` — nothing matches, case-insensitively included. The
      caller keeps its honest no_matches / "not in the index" behavior.

    An empty/blank query resolves to nothing (a table-only search resolves
    its field as "absent" and the caller gates on that itself).
    """
    if not isinstance(query, str):
        return None, []
    q = query.strip()
    if not q:
        return None, []
    q_lower = q.lower()
    group = [k for k in index if isinstance(k, str) and k.lower() == q_lower]
    if not group:
        return None, []
    if q in index:
        return q, group
    return _majority_index_spelling(index, group), group


def scripts_for_name_ci(index: dict, query: str) -> set:
    """Union of the scripts of EVERY case-insensitive-equal index entry.

    The search-layer script-set lookup: `dm_flag2` and `DM_FLAG2` both
    return the same set, so the same column written in different cases by
    different scripts is one searchable identity (the create_search
    intersection is taken over this union, never over one spelling's
    scripts).
    """
    _canonical, group = resolve_name_ci(index, query)
    out: set = set()
    for k in group:
        entry = index.get(k)
        if isinstance(entry, dict):
            out.update(entry.get("scripts") or [])
    return out


def tables_for_field(index: dict, field: str) -> list[str]:
    """Return all tables containing the given field (case-insensitive).

    NOTE (deliberate asymmetry with `scripts_for_name_ci`): resolution is
    case-insensitive, but the returned set comes from the CANONICAL entry
    only — the case-variant group is NOT unioned. No production caller
    today (test-only); `scripts_for_name_ci` is the search-layer lookup
    and unions the whole group because scripts per spelling genuinely
    differ, while `tables`/`fields` are one canonical identity's payload.
    """
    canonical, _group = resolve_name_ci(index, field)
    if canonical is None:
        return []
    return index.get(canonical, {}).get("tables", [])


def fields_for_table(index: dict, table: str) -> list[str]:
    """Return all fields of the given table (case-insensitive).

    Same deliberate asymmetry as `tables_for_field`: canonical entry only,
    no case-variant union (see the NOTE above).
    """
    canonical, _group = resolve_name_ci(index, table)
    if canonical is None:
        return []
    return index.get(canonical, {}).get("fields", [])


# ── P1 (item: catching-up window) ───────────────────────────────────────
# While an index run is in flight the served index is BY CONSTRUCTION the
# previous one: a search whose script set comes from that index returns a
# FALSE no_matches for content that only exists in the not-yet-indexed
# scripts. The creator's open marks the run (only when it actually fires
# POST /index — a zero-diff open never does), and a search during the window
# gets an explicit, retry-able 409 instead of a lying no_matches.
# A registry, not the progress phase: `done`/`analyzing` is a UI progress
# value that a crashed run would leave non-terminal, which would block
# searches forever; a begin/end pair in a `finally` cannot leak.
_INDEX_RUNS: dict = {}  # ws_id -> in-flight run COUNT
_INDEX_RUNS_LOCK = threading.Lock()


def begin_index_run(ws_id: str) -> None:
    """Mark ONE index run in flight for `ws_id` (searches now 409)."""
    with _INDEX_RUNS_LOCK:
        _INDEX_RUNS[ws_id] = _INDEX_RUNS.get(ws_id, 0) + 1


def end_index_run(ws_id: str) -> None:
    """Clear THIS run's mark — once per `begin_index_run`, from a `finally`."""
    with _INDEX_RUNS_LOCK:
        n = _INDEX_RUNS.get(ws_id, 0) - 1
        if n > 0:
            _INDEX_RUNS[ws_id] = n
        else:
            _INDEX_RUNS.pop(ws_id, None)  # clamped at 0 — never sticky


def is_index_catching_up(ws_id: str) -> bool:
    """True while ANY index run is in flight — the index on disk is the
    PREVIOUS one, so index-derived answers (the search script set) are about
    to change. False for a zero-diff open, which never re-indexes.

    X2 (review): a COUNT, not a set. add/discard cleared the flag on the FIRST
    finisher while a second concurrent run was still mid-flight — the search
    409 gate lifted (and P2's poller handed search back) onto a half-written
    index, the exact false-answer the gate exists to prevent. Two runs for one
    workspace are reachable without any malice: the creator's fast-open
    auto-triggers POST /index on a stale/never-indexed workspace, so two tabs
    of the same creator (or a stale tab alongside a fresh one) both fire."""
    with _INDEX_RUNS_LOCK:
        return _INDEX_RUNS.get(ws_id, 0) > 0


def get_index_status(ws_id: str) -> dict:
    """Return current indexing status.

    P1 (Job 2): `freshness` carries the advisory staleness hint (None before
    the first index — nothing has been recorded to compare against), so an
    open path can decide whether a re-index is worth its cost without a
    second round trip.
    """
    ws_dir = get_workspace_dir(ws_id)
    meta_path = ws_dir / "meta.json"
    if not meta_path.exists():
        return {"indexed": False}
    meta = json.loads(meta_path.read_text())
    return {
        "indexed": meta.get("indexed", False),
        "script_count": len(meta.get("indexed_scripts", [])),
        "indexed_at": meta.get("indexed_at"),
        "freshness": get_index_freshness(ws_id),
    }
