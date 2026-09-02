"""L2 Graph Builder — per-script detail graph construction.

Extracted from dataflow_service.py per ARCHITECTURE_REVIEW S3.
Builds L2 detail view: tables + fields + all 16 edge types for a single script.
"""
import json
import hashlib
import logging
import re
from pathlib import Path

_log = logging.getLogger("sql_visualizer.dataflow")

from app.services.workspace_service import get_workspace_dir
from app.extractor.adapter import run_full_analysis
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.services.graph_service import (
    build_graph_data,
    get_edge_style as _get_edge_style,
    get_category as _get_category,
    EDGE_TYPE_STYLE,
    CATEGORY_MAP,
    MODEL_CACHE_PREFIX,
    load_model_cache,
    write_model_cache,
    graph_with_alias_of,
)
from app.extractor.schema_inference import infer_table_schemas
from app.extractor.physical_model import build_physical_model
from app.extractor.dependency_graph import line_clause_map
from app.extractor.lineage import (filter_by_field_flow, flow_source_id,
                                   flow_targets, classify_flow_roles,
                                   compute_field_flow)
from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.services.highlight_strategies import (
    get_strategy,
    FIELD_LIKE_TYPES,
    _safe_int,
    _flow_kind,
    _anchor_line,
)

# ── L2 helper functions ──────────────────────────────────────────────

def _recompute_line_map(var_likes: list, sql_text: str) -> dict:
    """D1: recompute line_map from cached variable/node dicts.

    Cached line_maps were written before comment-line skipping existed in
    map_variables_to_lines — their table variables point at header comment
    lines. Recompute here so cached workspaces (analysis + graph caches)
    benefit identically to fresh analyses, without a cache-version bump.
    """
    from app.extractor.sql_line_mapper import map_variables_to_lines
    return map_variables_to_lines(var_likes, sql_text)


# ── R43 (2026-08-28, task #384): partition-DDL statement frames ──────
# User ruling: "ALTER TABLE ADD PARTITION statements should not appear in
# the L2 graph — they are folder names, not dataflow." A partition
# ADD/DROP/MSCK statement creates a metadata slot and moves no values, so
# the statement frame the generic statement walk materializes for it (the
# ⟐ output VT, plus the structure edges hung on that VT — the read-side
# occurrence →output TABLE_FLOW and output→occurrence REF pair per ALTER)
# is display noise, never data. Detection is deliberately conservative:
# the statement's own text must open with ALTER TABLE and carry an
# ADD/DROP/MSCK … PARTITION clause. Column DDL (ALTER TABLE … ADD COLUMN),
# CREATE TABLE/CTAS (a real dataflow target) and SET (already no VT) are
# out of scope — no evidence they frame anything but real structure.
_PARTITION_DDL_STMT = re.compile(
    r"\s*ALTER\s+TABLE\b.*?\b(?:ADD|DROP|MSCK)\b\s+"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?PARTITION\b",
    re.IGNORECASE | re.DOTALL)
_TOP_STMT_CTX = re.compile(r"^TOP\d+$")
_DDL_STMT_SCAN_LINES = 200


def _statement_text_from_line(sql_text: str, head_line: int) -> str:
    """R43: the statement text starting at `head_line` (1-based), through
    the first line that closes a statement (contains ';'). The bounded
    scan keeps an unterminated tail from swallowing the rest of the file."""
    lines = sql_text.splitlines()
    if head_line < 1 or head_line > len(lines):
        return ""
    stop = min(head_line - 1 + _DDL_STMT_SCAN_LINES, len(lines))
    out = []
    for i in range(head_line - 1, stop):
        out.append(lines[i])
        if ";" in lines[i]:
            break
    return "\n".join(out)


def _drop_partition_ddl_frames(full_graph: dict, sql_text: str) -> dict:
    """R43 — remove pure-metadata partition-DDL statement frames from the
    L2 display inputs: the statement's ⟐ output VT node plus every edge
    anchored on it. The DML edges that name the ALTERed table belong to
    the WRITE statement's own vars (not to this VT) and are kept — they
    route/dedup exactly as before, so only the VT frames drop.

    Display-layer only, applied AFTER the graph cache load on EVERY build:
    the cache (keyed by extractor version + sql — neither changes) may
    still contain the frames, and this projection removes them
    deterministically on both the cache-hit and fresh-build paths, so no
    cache-format bump is needed and no EXTRACTOR_VERSION change is made.
    Extraction/TOPn statement indexing are untouched (benchmark pins like
    TOP11 stay valid)."""
    dropped = set()
    dropped_ctxs = set()
    for n in full_graph.get("nodes", []):
        nd = n.get("data", n)
        line = _safe_int(nd.get("line_start"))
        if (nd.get("label") == "⟐ output"
                and nd.get("variable_type") == "virtual_table"
                and _TOP_STMT_CTX.match(nd.get("context") or "")
                and line >= 1
                and _PARTITION_DDL_STMT.match(
                    _statement_text_from_line(sql_text, line))):
            dropped.add(nd.get("id"))
            dropped_ctxs.add(nd.get("context"))
    if not dropped:
        return full_graph
    filtered = dict(full_graph)
    filtered["nodes"] = [n for n in full_graph.get("nodes", [])
                         if n.get("data", n).get("id") not in dropped]
    filtered["edges"] = [e for e in full_graph.get("edges", [])
                         if e.get("data", e).get("source") not in dropped
                         and e.get("data", e).get("target") not in dropped]
    # L5: the ALTERed table's own occurrence (a table-like var in the
    # dropped statement's scope) is now isolated — drop it too, so a
    # partition-DDL statement leaves no table node behind (folder names,
    # not dataflow). A table also read/written in ANOTHER statement keeps
    # its own occurrence (different context, still has edges).
    _endpoints = set()
    for e in filtered["edges"]:
        _d = e.get("data", e)
        _endpoints.add(_d.get("source"))
        _endpoints.add(_d.get("target"))
    _TABLE_LIKE = {"table", "view", "merge_target", "function_table"}
    filtered["nodes"] = [
        n for n in filtered["nodes"]
        if not (n.get("data", n).get("variable_type") in _TABLE_LIKE
                and (n.get("data", n).get("context") or "") in dropped_ctxs
                and n.get("data", n).get("id") not in _endpoints)
    ]
    return filtered


# ── L2 phase functions (CW4: split from the _build_l2_graph monolith) ──
# Each phase receives its inputs explicitly and returns its outputs; the
# orchestrator (_build_l2_graph) passes shared state between phases. No
# processing order or edge/node construction semantics changed — the phase
# split is structural only (byte-identical output).

def _load_or_build_graph(ws_id: str, script_name: str, sql_text: str):
    """Phase 1 (CW4): read the graph cache, or run full analysis and write caches.

    Returns (full_graph, table_schemas, physical_model). On a cache hit, table_schemas is
    loaded from the schemas cache (Bug 25); on a build it is inferred.

    J12-10 (stage 2): the physical model (extractor/physical_model.py) is
    built ONCE per build, at build time, from the extraction data the graph
    is derived from — never at render (never-patch rule). On the build path
    the model is built from the analysis result (the alias_of extraction
    truth); on a graph-cache hit it is rebuilt from the analysis cache when
    present and current (same extraction truth), else from the persisted
    alias truth beside the graph cache (FSC-2, v3.3.195) — and only when
    neither survives from the cached graph data (the graph cache does not
    serialize alias_of, so that last resort falls back to the label-keyed
    alias rule). The stage-2 gate pins the decisions byte-identical on the
    analysis and persisted-truth forms; the label-rule fallback is the
    pre-FSC-2 behavior kept for caches written before the artifact existed.
    """
    from app.services.logger import stage_graph

    ws_dir = get_workspace_dir(ws_id)
    cache_dir = ws_dir / "cache"
    # C-3 (review): analysis cache key discriminates the extractor engine —
    # identical to folder_index_service's write-side key (md5 over
    # (EXTRACTOR_VERSION, script_name, sql_text)) or freshly indexed
    # workspaces are never found here. A stale cache written by an older
    # engine can never match this key — exact-key consumers miss and
    # rebuild lazily.
    cache_key = hashlib.md5(
        (EXTRACTOR_VERSION + "|" + script_name + sql_text)
        .encode()).hexdigest()[:12]

    # Try cached graph (v3.2.15 — includes edge filter fix)
    # C3: cache prefix is the shared contract constant (cache_keys.py) — the
    # middle token is the cache CONTRACT version, bump it only on format change.
    graph_cache_path = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
    analysis_cache_path = cache_dir / f"analysis_{cache_key}.json"
    # FSC-2 (v3.3.195): the alias-truth companion of the graph cache —
    # written by every build below, read by every graph-cache hit that
    # cannot rebuild the model from an analysis cache.
    model_cache_path = cache_dir / f"{MODEL_CACHE_PREFIX}_{cache_key}.json"
    full_graph = None
    _table_schemas = None
    if graph_cache_path.exists():
        cached_graph = json.loads(graph_cache_path.read_text())
        # C9 (v3.3.140): graphs below format_version 4 predate the
        # node-carried line_start/line_end the strict table.field walker
        # and its highlights depend on — treat a stale cache as a miss and
        # rebuild (the build path below overwrites the stale cache).
        # Round 12 (2026-08-10): extraction-semantics changes (E3a fix 3 —
        # DML-target attribution) must never serve stale graphs — mirror
        # the analysis-cache extractor_version check (contamination root
        # cause found by Team E2's cold-cache matrix).
        if (cached_graph.get("format_version", 0) >= 4
                and cached_graph.get("extractor_version") == EXTRACTOR_VERSION):
            full_graph = cached_graph
            # D1: cached graphs carry a line_map computed before comment-line
            # skipping existed — recompute from the cached node expressions so
            # stale caches behave like fresh analyses.
            # PERF (v3.3.194): the node dicts carry line_start/line_end
            # (format_version 4) — hand them over so map_variables_to_lines
            # takes its v3.3.140 carried-line short-circuit instead of
            # scanning the whole script per var (the var-carried def lines
            # ARE the extraction truth; the text search stays as the
            # fallback for the nodes that carry no line).
            full_graph["line_map"] = _recompute_line_map(
                [{"id": n["data"].get("id", ""),
                  "sql_expression": n["data"].get("sql_expression", ""),
                  "line_start": n["data"].get("line_start", 0),
                  "line_end": n["data"].get("line_end", 0)}
                 for n in full_graph.get("nodes", [])], sql_text)
            # CW7: normalize edge_type on cache read (cache stores "relationship")
            for _e in full_graph.get("edges", []):
                _ed = _e.get("data", _e)
                _ed.setdefault("edge_type", _ed.get("relationship", "REF"))
            # Item 4: cache format versioning — warn on stale caches
            if full_graph.get("format_version") != 4:
                _log.warning("L2 cache %s has format_version=%r (expected 4) — stale graph cache",
                             graph_cache_path.name, full_graph.get("format_version"))
            stage_graph(len(full_graph.get('nodes',[])), len(full_graph.get('edges',[])), ws_id=ws_id)
            # Bug 25: load cached table_schemas on cache hit
            if schemas_cache_path.exists():
                _table_schemas = json.loads(schemas_cache_path.read_text())
            # J12-10 stage 2: the physical model rides the same build —
            # prefer the analysis cache (alias_of truth) when present and
            # current; next the persisted alias truth beside this very
            # graph cache (FSC-2 — the model it rebuilds is byte-identical
            # to the analysis-cache model); a bare graph-cache hit from a
            # pre-FSC-2 build (snapshot-harness workspaces are never
            # indexed) is the only path left on the label-keyed fallback.
            physical_model = None
            if analysis_cache_path.exists():
                try:
                    cached_analysis = json.loads(analysis_cache_path.read_text())
                except (OSError, ValueError):
                    cached_analysis = None
                if (cached_analysis is not None
                        and cached_analysis.get("extractor_version")
                        == EXTRACTOR_VERSION):
                    physical_model = build_physical_model(
                        cached_analysis, script_name=script_name)
            if physical_model is None:
                alias_of = load_model_cache(
                    model_cache_path, cache_key, EXTRACTOR_VERSION)
                if alias_of:
                    physical_model = build_physical_model(
                        graph_with_alias_of(full_graph, alias_of),
                        script_name=script_name)
            if physical_model is None:
                physical_model = build_physical_model(
                    full_graph, script_name=script_name)
    if full_graph is None:
        # C-2(b): prefer the analysis cache when present — build the graph
        # from the cached analysis dict (same key contract as
        # folder_index_service: md5(EXTRACTOR_VERSION + "|" + script_name
        # + sql_text)[:12]) instead of re-running the full extraction
        # pipeline.
        result = None
        if analysis_cache_path.exists():
            result = json.loads(analysis_cache_path.read_text())
            # C9 (v3.3.140): analysis caches from an older extractor are
            # stale (extraction-semantics changes — phantom subquery dedup,
            # PARTITION vars — must never serve old analysis) — ignore the
            # cache and re-run the full analysis on mismatch.
            if result.get("extractor_version") != EXTRACTOR_VERSION:
                result = None
            else:
                # D1: analysis caches predate comment-line skipping too — the
                # stored line_map is stale; recompute before build_graph_data
                # copies it into the graph.
                result["line_map"] = _recompute_line_map(
                    result.get("variables", []), sql_text)
        if result is None:
            result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        full_graph = build_graph_data(result)
        # Cache for future use
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Item 4: cache format version — bump when graph schema changes
        # C9 (v3.3.140): format_version 4 = node-carried line_start/line_end.
        full_graph["format_version"] = 4
        # Round 12: stamp the extractor version so extraction-semantics
        # changes invalidate graph caches (mirror of the analysis cache).
        full_graph["extractor_version"] = EXTRACTOR_VERSION
        # v3.3.145: A1 records statement-level parse diagnostics on the
        # analysis result — ride them on the graph cache so the fast path
        # (and _build_l2_graph's response) serves the same data. Stale
        # caches predating this default to [] (no reconstruction).
        full_graph["parse_errors"] = result.get("parse_errors", [])
        graph_cache_path.write_text(json.dumps(full_graph, default=str))
        # R18: build table_schemas for lineage seed validation
        _table_schemas = infer_table_schemas(
            result.get("variables", []), result.get("dependencies", []))
        # Bug 25: cache table_schemas alongside graph
        schemas_cache_path.write_text(json.dumps(_table_schemas, default=str))
        # FSC-2 (v3.3.195): persist the alias truth beside the graph cache,
        # from the SAME analysis the graph above was built from — a later
        # graph-cache hit that has lost its analysis cache re-derives the
        # model this build made instead of guessing aliases by label.
        # Written even for an alias-free script: the file's presence is
        # what says "this graph cache carries its truth", and it keeps the
        # old-cache fallback test meaningful (a pre-FSC-2 graph cache has
        # no sibling at all).
        write_model_cache(model_cache_path, cache_key, EXTRACTOR_VERSION,
                          result)
        # J12-10 stage 2: the model is built once, from the analysis the
        # graph was built from (the extraction truth — alias_of rides it).
        physical_model = build_physical_model(result, script_name=script_name)
    return full_graph, _table_schemas, physical_model


def _apply_relevance_filter(full_graph: dict, table: str, field: str,
                            table_schemas: dict | None,
                            relevance_filter: bool = True,
                            physical_model=None,
                            direction="downstream",
                            _flow_memo=None) -> dict:
    """Phase 2 (CW4): apply the strict table.field flow filter, or return the full graph.

    v3.3.140: filter_by_field_flow() (the strict per-instance table.field
    walker in lineage.py) replaces filter_relevant() — the requirement
    changed from table-level flow to exact flow of table.field. Flag
    semantics unchanged: only applied when filtering is requested.

    J12-10 stage 3: the walker consumes the physical model — it is passed
    through to filter_by_field_flow (required when filtering).

    R29 (2026-08-12): direction passes through to filter_by_field_flow —
    "downstream" (default) is byte-identical legacy behavior; "upstream"
    filters to the field's WRITING flow (backward production walk).
    """
    if relevance_filter:
        return filter_by_field_flow(full_graph, table, field,
                                    table_schemas=table_schemas,
                                    physical_model=physical_model,
                                    direction=direction,
                                    _flow_memo=_flow_memo)
    return full_graph


# ── R46a (2026-08-31, FSB hygiene): the searched entity set ──────────
# Mirror of `app/extractor/lineage.py`'s `_ALIAS_SEED_EXPANSION` switch —
# the W1 seed block gates the #399 alias expansion on it, and the display
# gate below re-derives the SAME expansion, so the two switches must move
# together. `tests/test_alias_seed_expansion.py::_set_switch` flips it in
# every module that carries the attribute (lineage AND here) precisely for
# that reason; `_find_feature_module` still resolves to lineage (it is
# probed first), so the sentinel/kill-switch bookkeeping is unchanged.
_ALIAS_SEED_EXPANSION = True


def _searched_entity_keys(physical_model, table: str, field: str) -> set:
    """R46a (2026-08-31, FSB audit — EAST5, 168 pairs): the entity set the
    searched `table.field` actually names — the strict walker's own W1
    seed rule (`target_keys ∪ _tkeys_ci`, widened by the #399 alias seed
    expansion), re-derived here so the DISPLAY's `is_target` stamp answers
    the same question the walker's seed rule answers.

    Why a re-derivation and not an import: the seed set is local to
    `filter_by_field_flow`'s W1 block (lineage.py) and is never exposed;
    the display needs it before classification, and lineage.py is the
    extraction side (the display must not reach into its frame). The three
    clauses below are clause-for-clause the walker's:

      1. every entity NAMED the searched table (exact + case-insensitive
         — CR11), 2. the #399 alias expansion gated field-aware: only when
         NO entity named the searched table HOSTS the searched field do the
         alias's owning entities join (a search that already has its host
         keeps it), 3. one alias name may bind several owning entities in
         one statement — all of them.

    An EMPTY return means the model cannot name a single entity for this
    search (no such table, no alias binding): there is no ownership
    evidence to gate with, so the caller keeps the legacy owner-agnostic
    stamp instead of inventing a restriction the model cannot support.
    """
    if physical_model is None:
        return set()
    tl = (table or "").lower()
    if not tl:
        return set()
    entity_keys = {k for k, t in physical_model.tables.items()
                   if t.name == table or t.name.lower() == tl}
    fk = (field or "").lower()
    hosted = any(tkey in entity_keys and fname.lower() == fk
                 for (tkey, fname) in physical_model.fields)
    if not hosted and _ALIAS_SEED_EXPANSION:
        for _avid, _akey in physical_model.alias_by_var_id.items():
            _ao = physical_model.occurrence(_avid)
            if _ao is not None and ((_ao.get("name") or "").lower() == tl):
                entity_keys.add(_akey)
    return entity_keys


def _compound_entity_key(compound: dict | None, physical_model) -> str | None:
    """R46a: the model entity key a compound node STANDS FOR — an alias
    compound resolves to its canonical entity (the model's alias truth),
    any other table-like compound to its own occurrence's entity."""
    if physical_model is None or not compound:
        return None
    oid = compound.get("original_id")
    if not oid:
        return None
    key = physical_model.alias_by_var_id.get(oid)
    if key is None:
        key = physical_model.entity_of_id.get(oid)
    return key


def _write_target_entity_keys(physical_model, field: str) -> set:
    """R46a ruling amendment (2026-08-31): the entity keys of the DML WRITE
    TARGETS that RECEIVE the searched field's value — the walker's own
    upstream-seed evidence (lineage.py R29 U1: the write targets whose
    statement's write leg carries the searched field), read here from the
    same model fact the walker's `_dml_write_leg` index is built from: a
    non-WRITE_READ DML edge whose SOURCE occurrence's field part is the
    searched field. The write target's compound is where that value lands
    (the R44 family-1 write twin / the P1 MOVE→COPY continuation), so its
    same-name chip keeps the seed claim."""
    _field_key = (field or "").casefold()
    if physical_model is None or not _field_key:
        return set()
    keys = set()
    for e in physical_model.edges:
        if e.edge_type != "DML":
            continue
        if (e.operation or "").upper() == "WRITE_READ":
            continue
        src = physical_model.occurrence(getattr(e, "source_id", ""))
        if src is None:
            continue
        part = ((src.get("name") or "").rsplit(".", 1)[-1].casefold())
        if part != _field_key:
            continue
        target = getattr(e, "target", None)
        if target and target[0]:
            keys.add(target[0])
    return keys


def _scope_target_stamp(field_nodes: list, table_nodes: dict,
                        table: str, field: str, physical_model) -> int:
    """R46a (2026-08-31, FSB audit — EAST5, 168 pairs): the DISPLAY half of
    the seed rule. AD3 adjudication, as amended by the coordinator ruling
    of the same day (the user's "only the field involved in the data flow
    is shown" cuts both ways): `is_target` = the chip's field-part equals
    the searched field AND the chip's parent compound is EITHER an entity
    of the searched table's entity set (the walker's `target_keys ∪
    _tkeys_ci ∪ _alias_keys` — the #399 alias expansion included) OR a DML
    write-target compound that RECEIVES the searched field's value (the
    R44 family-1 write twins — where the value goes). READ-side same-name
    chips on other tables' compounds — the FSB phantoms (b/c/d/e.data_dt,
    a JOIN partner's partition column) — are ordinary nodes: their
    compounds never receive the field's value, they only compare with it.

    Why here and not in `_compute_target_and_direct_ids`: `is_target` is
    load-bearing INSIDE the build — P2 (`_promote_field_edges`) and P17
    (`_simplify_dml_edges`) keep a seed field's edges at FIELD level and
    the payload phase (`_attach_flow_payload`) walks the closure from the
    seed entries. Measured on the flagship corpus, gating the flag there
    re-routes SERVED edges (the J12-15 per-statement DML trunk flagship
    loses its rrcdm write leg; J1's LFS129 own-field value copy goes
    dark) — an edge-admission change the ruling never asked for (edge
    admission is J1's rule, and it keeps those edges). So the seed sets
    this phase receives stay owner-agnostic, and the stamp is narrowed
    once, after the last edge consumer has read it and before assembly.

    The narrowing only ever REMOVES a stamp (the admitted set is a subset
    of the owner-agnostic match), so no chip gains a claim it did not
    have. Kept: the searched table's own chips, the alias-qualified seed
    copy (P1 MOVE→COPY — the alias compound resolves to its canonical
    entity), the #399 alias-target seed (the expansion widens the entity
    set) and the write-target copy (the R44 family-1 twin — sup@160,
    rrcdm@213 on the flagship). Dropped: the READ-side same-name chip of
    every other table/CTE/⟐-output compound in the statement — which is
    what lit seed-centering, the V2-N1 chip-visibility exemption and the
    Field Story's seed selection on foreign chips.

    Returns the number of stamps dropped (diagnostics only).
    """
    if physical_model is None or not (table or "").strip():
        return 0
    entity_keys = _searched_entity_keys(physical_model, table, field)
    if not entity_keys:
        # The model names no entity for this search: no ownership evidence,
        # so the stamp stays as the extraction-side match produced it.
        return 0
    admitted = entity_keys | _write_target_entity_keys(physical_model, field)
    entity_names = {physical_model.tables[k].name.lower()
                    for k in admitted if k in physical_model.tables}
    compounds = {tn.get("id"): tn for tn in table_nodes.values()}
    dropped = 0
    for fn in field_nodes:
        if not fn.get("is_target"):
            continue
        compound = compounds.get(fn.get("parent"))
        key = _compound_entity_key(compound, physical_model)
        if key is not None:
            if key in admitted:
                continue
        elif (compound or {}).get("table_name", "").lower() in entity_names:
            # No entity key for the keeper occurrence (the model never saw
            # it) — the compound's own name is the only evidence left.
            continue
        fn["is_target"] = False
        dropped += 1
    return dropped


def _field_part_match_ids(nodes: list, field: str,
                          physical_model=None) -> set:
    """The J12-9 owner-agnostic FIELD-PART match (the predicate both the
    seed phase and the #387 retarget gate consume — one definition, never
    two drifting copies).

    J12-10 stage 3: the match resolves against the physical model —
    PhysicalField entities (field lookup) instead of scanning display
    nodes. The set is the model-union of occurrence ids over the fields
    named `field` (owner-agnostic — one exact field-part rule;
    probe-verified byte-identical to the label predicate on the gate
    sample set, 2026-08-11), intersected with the FIELD_LIKE nodes
    present. The J12-9 source_columns predicate is kept via the model's
    occurrence index (same exact suffix rule, no substring — R4), so a
    var whose label differs but whose source column carries the searched
    field part still matches (alias-copy seed semantics).

    Owner-agnostic BY DESIGN: this answers "does this occurrence carry the
    searched field part", never "is it the searched table's" — the entity
    question is `_searched_entity_keys` + `_scope_target_stamp`.
    """
    # F-A follow-up (K4 item 5, 2026-08-28): the search hands the builders
    # the index's CANONICAL spelling, while each script wrote the field in
    # its own casing (`dm_flag2` in one script, `DM_FLAG2` in the next).
    # SQL identifiers are case-insensitive, so the seed predicates compare
    # casefolded — otherwise the case-variant script rendered
    # search_matched:false and lost every is_target chip.
    _field_key = field.casefold()
    # Model-union: every occurrence whose PhysicalField name is `field`
    # (one exact field-part rule — "table.field" labels are dotted
    # labels, field-only AND alias-qualified labels like `p1.data_dt`
    # still match a search for `bdm_acc_loan_info.data_dt` — the
    # alias-copy seed depends on it; narrowing to name == target_full
    # would regress the Jaccard gate).
    union = set()
    if physical_model is not None:
        for (_tkey, fname), fld in physical_model.fields.items():
            if fname.casefold() == _field_key:
                union.update(fld.occurrence_ids)
    matched = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("variable_type", "") not in FIELD_LIKE_TYPES:
            continue
        nid = nd.get("id")
        # J12-9 label predicate kept ALONGSIDE the model union (the union
        # only adds occurrences whose model field name is `field` — for
        # column-family vars that IS the label field part, so the union is
        # purely additive: display-truncated computed labels (label[:36])
        # whose truncated name is the searched field). Removing the label
        # predicate would regress dotted-suffix searches ("b.ihgmab)" as a
        # suffix of a dotted computed label) and the model=None fallback.
        label = nd.get("label", "")
        if nid in union or label.rsplit(".", 1)[-1].casefold() == _field_key:
            matched.add(nid)
            continue
        # J12-9 source_columns path (kept — a var whose label differs but
        # whose source column carries the searched field part still
        # matches). Read from the occurrence index (the model houses the
        # per-var data; node-carried source_columns as fallback).
        if physical_model is not None:
            o = physical_model.occurrence(nid)
            sc = (o or {}).get("source_columns") or []
        else:
            sc = nd.get("source_columns", [])
        for sc_name in sc:
            if sc_name.rsplit(".", 1)[-1].casefold() == _field_key:
                matched.add(nid)
                break
    return matched


def _compute_target_and_direct_ids(nodes: list, edges: list,
                                   table: str, field: str,
                                   physical_model=None) -> tuple:
    """Phase 3a (CW4): identify target node ids and compute the upstream/
    downstream BFS sets used for direct/indirect field classification.

    J12-10 stage 3: the seed search resolves against the physical model —
    PhysicalField entities (field lookup) instead of scanning display
    nodes. The target set is the model-union of occurrence ids over the
    fields named `field` (one exact field-part rule — the J12-9
    semantics; probe-verified byte-identical to the label predicate on
    the gate sample set, 2026-08-11), intersected with the FIELD_LIKE
    nodes present. The J12-9 source_columns predicate is kept via the
    model's occurrence index (same exact suffix rule, no substring —
    R4), so a var whose label differs but whose source column carries
    the searched field part still matches (alias-copy seed semantics).

    R46a (2026-08-31, FSB audit — EAST5, 168 pairs): this phase stays the
    OWNER-AGNOSTIC field-part match on purpose, because `is_target` is
    load-bearing far beyond the stamp: P2 (`_promote_field_edges`) and P17
    (`_simplify_dml_edges`) keep a seed field's edges at FIELD level, and
    the payload phase (`_attach_flow_payload`) walks the closure from the
    seed entries — all three read the flag. Gating HERE would re-route
    served edges (measured: the J12-15 per-statement trunk flagship and
    J1's LFS129 own-field value copy both go dark). The ruling scopes the
    SEED CLAIM, not the edge admission, so the entity-set gate is applied
    once, at the display boundary, by `_scope_target_stamp` — after every
    edge consumer has read the flag and before assembly. The direct/
    indirect BFS keeps the owner-agnostic seeds for the same reason:
    `field_group` is a graph-DISTANCE notion, not a seed claim.

    Returns (target_node_ids, direct_ids).
    """
    # Identify target node IDs (for is_target and direct/indirect) — the
    # owner-agnostic field-part match (see `_field_part_match_ids`).
    target_node_ids = _field_part_match_ids(nodes, field, physical_model)

    # Compute upstream/downstream sets for direct/indirect classification
    fwd_adj = {}
    rev_adj = {}
    for e in edges:
        ed = e.get("data", e)
        src, tgt = ed.get("source"), ed.get("target")
        fwd_adj.setdefault(src, []).append(tgt)
        rev_adj.setdefault(tgt, []).append(src)

    # BFS from targets — seeded from the owner-agnostic match (see above).
    direct_ids = set(target_node_ids)
    if target_node_ids:
        # Upstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for src in rev_adj.get(cur, []):
                if src not in direct_ids:
                    direct_ids.add(src)
                    queue.append(src)
        # Downstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for tgt in fwd_adj.get(cur, []):
                if tgt not in direct_ids:
                    direct_ids.add(tgt)
                    queue.append(tgt)
    return target_node_ids, direct_ids


def _classify_compound_nodes(nodes: list, full_graph: dict, script_name: str,
                             target_node_ids: set, direct_ids: set,
                             search_table: str | None = None,
                             physical_model=None) -> tuple:
    """Phase 3b (CW4): build the compound node structure — table parents and
    field children, as a projection of the physical model (J12-10 stage 4).

    The model is the extraction-time truth the display mirrors: the keeper
    selection for physical tables is the model's entity lookup
    (`entity_of_id`) — one PhysicalTable per name by construction, keeper
    = first occurrence, later same-entity occurrences merge (their nids
    record `occ_to_id[nid] = keeper id`). Alias detection is the model's
    alias truth (`alias_by_var_id` — the I4 alias_of extraction fact, with
    the label-keyed rule for table/view/cte only; derived-subquery
    aliases like p2@40 stay their own (name, context) entities); alias
    dedup keys (parent, label, line) and field dedup keys
    (parent, label) keep the display semantics (J12-16: same-named
    field instances from different statements fold into ONE display
    field per physical table) — every nid maps through occ_to_id to
    its compound/field id.

    B3/P1: `search_table` names the searched base table (None for phase
    calls that don't carry a search context). is_target seed fields that
    landed on an alias of that table are re-parented onto the table's own
    compound node when it has no same-named field yet — the seed shows on
    the searched table instead of a random alias instance.

    Returns (table_nodes, field_nodes, alias_map, occ_to_id).
    """
    # ── Build compound node structure ──
    # Group field-level nodes by their parent table/CTE
    table_nodes = {}       # id -> table compound node
    # J12-10 stage 2: the physical model's occurrence index (var id → entity
    # key) IS the keeper identity for physical tables — one PhysicalTable
    # per name by construction, keeper = first occurrence (issue a, R22).
    entity_by_var_id = physical_model.entity_of_id
    keeper_by_entity = {}  # model entity key -> keeper compound node
    # C3: (parent_table_id, label, line_start) -> keeper alias compound
    # node — alias identity is (label, line): a different code line = a
    # DIFFERENT alias node; the same (label, line) = the same node.
    alias_nodes_by_key = {}
    fields_by_key = {}     # (parent_id, field label) -> keeper field node (issue a)
    field_nodes = []       # field children
    seen_ids = set()
    # Issue a: original nid -> final compound/field id (the display's
    # id_map replacement — every nid seen during classification maps to
    # the node it became; merged-away nids map to their keeper).
    occ_to_id = {}

    # ── #288 (T1): physical-table merge keys are case-FOLDED ──
    # A physical table referenced with different cases (east5_stzfxxb vs
    # EAST5_STZFXXB) is ONE table → one keeper compound. Only the
    # "physical" entity kind folds; aliases, CTEs, subqueries and ⟐-output
    # VTs keep their case-sensitive (name, context) identities (a case-twin
    # alias A / a is still a DIFFERENT alias node).
    _physical_names_lower = None

    def _is_physical_ekey(ekey):
        """True when the entity key names a physical table (the string-key
        form for table/view/merge_target entities, or the defensive
        (name, 'physical') tuple fallback)."""
        if isinstance(ekey, str):
            tbl = (physical_model.tables.get(ekey)
                   if physical_model is not None else None)
            return tbl is not None and tbl.kind == "physical"
        return (isinstance(ekey, tuple) and len(ekey) == 2
                and ekey[1] == "physical")

    def _fold_physical(ekey):
        """The case-folded merge/lookup key for physical entities; other
        entity kinds pass through unchanged."""
        if not _is_physical_ekey(ekey):
            return ekey
        if isinstance(ekey, str):
            return ekey.lower()
        return (ekey[0].lower(), ekey[1])

    def _physical_names_lower_set():
        """Lowercased names of every physical table in the model — the
        case-insensitive parent-matching gate (never folds aliases)."""
        nonlocal _physical_names_lower
        if _physical_names_lower is None:
            names = set()
            if physical_model is not None:
                for tbl in physical_model.tables.values():
                    if tbl.kind == "physical":
                        names.add(tbl.name.lower())
            _physical_names_lower = names
        return _physical_names_lower

    # ── #289 (T2): INSERT write columns land on the write target ──
    # A column that is a SCHEMA member of a statement's own ⟐ output VT (a
    # SELECT projection) belongs to that statement's DML write target — not
    # to the read-side table/alias it was extracted from (the extractor
    # attributes a projection to the table it reads, so write columns
    # sourced to a read alias — or a phantom alias — rendered off-target).
    # Each statement's output VT is identified exactly like
    # _simplify_dml_edges (entity key ('⟐ <name>', TOP{numeric})); the
    # SCHEMA members × the statement's DML target → write_field_target[
    # projection var id] = write target var id. Statement-local: every
    # statement's own output VT + target pair, never cross-statement.
    write_field_target = {}
    if physical_model is not None:
        _stmt_targets = {}
        _stmt_members = []
        for fe in full_graph.get("edges", []):
            fed = fe.get("data", fe)
            rel = (fed.get("edge_type", "") or fed.get("relationship", "")).upper()
            src = fed.get("source", "")
            _ek = entity_by_var_id.get(src)
            _ctx = _ek[1] if (isinstance(_ek, tuple) and len(_ek) == 2
                              and isinstance(_ek[1], str)) else ""
            if not (isinstance(_ek, tuple) and len(_ek) == 2
                    and isinstance(_ek[0], str)
                    and _ek[0].startswith("⟐ ")
                    and _ctx.startswith("TOP")
                    and _ctx[3:].isdigit()):
                continue
            tgt = fed.get("target", "")
            if "DML" in rel:
                _stmt_targets[src] = tgt
            elif rel == "SCHEMA":
                _stmt_members.append((src, tgt))
        for _src, _member in _stmt_members:
            _tgt = _stmt_targets.get(_src)
            if _tgt is not None:
                write_field_target[_member] = _tgt

    def _resolve_write_target(wtgt):
        """#289: write target var id → its keeper compound id. Physical
        keys are case-folded; a name-scan fallback covers the keeper when
        it is not yet classified (later in node order)."""
        wkey = entity_by_var_id.get(wtgt)
        if wkey is None:
            return None
        keeper = keeper_by_entity.get(_fold_physical(wkey))
        if keeper is not None:
            return keeper["id"]
        name = (wkey if isinstance(wkey, str)
                else (wkey[0] if isinstance(wkey, tuple) and len(wkey) == 2
                      and isinstance(wkey[0], str) else None))
        if name is None:
            return None
        low = name.lower()
        if low in _physical_names_lower_set():
            for tid, tn in table_nodes.items():
                if tn["type"] == "source_table" and tn["table_name"].lower() == low:
                    return tn["id"]
        return None

    # ── Phase 0: alias parent-resolution map from the model's alias
    # views (alias label → canonical entity name) — the alias/field
    # parent fallback's one-hop resolution; the model's alias_by_var_id
    # is the aliasness truth itself.
    alias_map = {}
    if physical_model is not None:
        for tbl in physical_model.tables.values():
            for av in tbl.alias_views:
                canon = physical_model.tables.get(av["canonical_key"])
                if canon is not None:
                    alias_map[av["label"]] = canon.name

    # ── #386 (2026-08-28, CTE-scope ruling): field-occurrence owner index
    # — var id → the model entity KEY of the field it belongs to. A name
    # match cannot tell a CTE from a same-named PHYSICAL table (the
    # ruling: a CTE's scope ends with its statement, so a LATER
    # statement's bare ref is a physical read, never the CTE); the model
    # keys them as distinct entities, so field ownership is the only
    # disambiguator for the column-parent choice below.
    field_owner_key = {}
    if physical_model is not None:
        for (_tkey, _fname), _fld in physical_model.fields.items():
            for _vid in _fld.occurrence_ids:
                field_owner_key.setdefault(_vid, _tkey)

    # Classify each node
    for n in nodes:
        nd = n.get("data", n)
        nid = nd.get("id", "")
        label = nd.get("label", "")
        vt = nd.get("variable_type", "")
        src_tables = nd.get("source_tables", [])
        defined_in = (nd.get("defined_in") or "").upper()
        is_output_node = nd.get("is_output", False)

        if nid in seen_ids:
            continue
        seen_ids.add(nid)

        # ── Table-like nodes → compound parents ──
        if vt in ("table", "view", "cte", "subquery", "virtual_table",
                   "merge_target", "union_branch", "function_table"):
            # Bug 28: Keep aliases as visible compound nodes
            # Aliases carry fields and show the data flow explicitly:
            #   canonical_table --ALIAS--> alias (with fields) --DML--> target_table
            # J12-10 stage 4: aliasness is the model's alias truth (I4
            # alias_of + the label-keyed rule for table/view/cte only) —
            # derived-subquery aliases (p2@40 style) are their own
            # (name, context) entities, not aliases of another table.
            is_alias = (physical_model is not None
                        and nid in physical_model.alias_by_var_id)
            # Issue a: one physical table must appear as exactly ONE L2
            # table node. The extractor emits one TABLE variable per scope,
            # so the same table read/written by N contexts produced N nodes.
            # Non-alias table/view nodes are keyed by their entity (the
            # physical table name) instead of the context nid — the first
            # occurrence is the keeper, later contexts merge into it (their
            # nids record occ_to_id to the keeper, re-pointing every edge).
            # Aliases/subqueries/CTEs keep per-context semantics (Bug 28
            # visible aliases; distinct subquery scopes).
            # Table-dup audit (2026-08-28): merge_target occurrences join
            # the physical fold — the model already keys a MERGE target by
            # its raw name (kind "physical", roles {merge_target, read}),
            # so a table that is MERGE-INTO'd in one statement and read in
            # another is ONE compound node, not a source_table twin beside
            # an intermediate_table twin (family-6 duplicate).
            if vt in ("table", "view", "function_table",
                      "merge_target") and not is_alias:
                # J12-10 stage 2: the keeper lookup is the physical model's
                # entity key — for a non-alias table/view occurrence the
                # model key IS the raw name (kind "physical"), so this is
                # the old label-keyed merge by construction (one keeper per
                # physical table, first occurrence wins; merged-away nids
                # record occ_to_id). The defensive fallback keeps the
                # label key if the model ever misses an occurrence.
                ekey = entity_by_var_id.get(nid)
                if ekey is None:
                    ekey = (label, "physical")
                # #288: the physical merge key is case-folded — the same
                # physical table referenced in different cases is ONE
                # keeper (aliases/CTEs/subqueries keep their exact keys).
                _ekey_folded = _fold_physical(ekey)
                keeper = keeper_by_entity.get(_ekey_folded)
                if keeper is not None:
                    occ_to_id[nid] = keeper["id"]
                    continue

            tbl_id = f"l2_tbl_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            if is_alias:
                tbl_type = "alias_table"
            elif vt == "cte":
                tbl_type = "cte_table"
            elif is_output_node and vt not in ("table", "view", "function_table"):
                tbl_type = "output_table"
            elif vt in ("table", "view", "function_table",
                        "merge_target") and not is_output_node:
                tbl_type = "source_table"
            else:
                tbl_type = "intermediate_table"

            # B5: the DISPLAY label drops the internal "⟐ " marker (never
            # rendered in the UI), while `table_name` keeps the raw name —
            # field-parent matching and the query-output routing pins rely
            # on the exact "⟐ output" sentinel, so only the label is
            # sanitized.
            # #223 (2026-08-13): a subquery-output VT (`⟐ X`, X ≠ "output")
            # renders as `output(X)` so it reads as "the output of the
            # subquery X" — clearly distinct from the derived-table alias X
            # of the same name (the `⟐ t` vs `t` confusion). Top-level
            # `⟐ output` keeps `output` (never a user alias; redundant).
            if label.startswith("⟐ "):
                _base = label[2:]
                display_label = (_base if _base == "output"
                                 else f"output({_base})")
            else:
                display_label = label

            if is_alias:
                # C3 (v3.3.140): alias node identity is (label, line) — the
                # user directive: a different code line = a DIFFERENT alias
                # node; the same (label, line) = the same node. Alias
                # compound nodes merge/dedup by (physical parent, label,
                # line_start), and the display label carries the line
                # ("p1@29") so duplicate alias instances are distinguishable
                # (review item #4). `table_name` keeps the raw label — all
                # field-parent matching uses table_name, never the display
                # label. Physical-table compound nodes keep the entity-keyed
                # merge (R22: one compound node per physical table);
                # ⟐/CTE/output nodes keep their existing keys.
                alias_line = _safe_int(nd.get("line_start"))
                display_label = f"{display_label}@{alias_line}" if alias_line > 0 else display_label
                # Resolve the alias's canonical parent compound id for the
                # dedup key — the model's alias view names the canonical
                # entity; when the canonical compound is not classified yet
                # the key's parent slot is None (same-line duplicates still
                # merge).
                alias_parent_id = None
                canon_key = None
                if physical_model is not None:
                    canon_key = physical_model.alias_by_var_id.get(nid)
                if canon_key is not None:
                    # #288: the canonical physical key is case-folded too —
                    # an alias whose canonical table was merged under the
                    # first (possibly differently-cased) occurrence still
                    # resolves to the keeper.
                    keeper = keeper_by_entity.get(_fold_physical(canon_key))
                    if keeper is not None:
                        alias_parent_id = keeper["id"]
                    else:
                        canon = physical_model.tables.get(canon_key)
                        canon_name = canon.name if canon is not None else None
                        if canon_name is not None:
                            for tn in table_nodes.values():
                                if tn["table_name"] == canon_name:
                                    alias_parent_id = tn["id"]
                                    break
                            # #288: case-insensitive physical-only fallback
                            if (not alias_parent_id
                                    and canon_name.lower()
                                    in _physical_names_lower_set()):
                                for tn in table_nodes.values():
                                    if (tn["type"] == "source_table"
                                            and tn["table_name"].lower()
                                            == canon_name.lower()):
                                        alias_parent_id = tn["id"]
                                        break
                alias_key = (alias_parent_id, label, alias_line)
                dup_alias = alias_nodes_by_key.get(alias_key)
                if dup_alias is not None:
                    occ_to_id[nid] = dup_alias["id"]
                    continue

            table_nodes[nid] = {
                "id": tbl_id,
                "label": display_label,
                "type": tbl_type,
                "table_name": label,
                "variable_type": vt,
                "original_id": nid,
                # The extraction context rides on the compound node — it is
                # carried extraction-time info (scopes like
                # "CTE{loan_final}/subq1"), surfaced in the L2 response.
                "context": nd.get("context", ""),
            }
            occ_to_id[nid] = tbl_id
            if vt in ("table", "view", "function_table",
                      "merge_target") and not is_alias:
                # #288: store under the folded key so case-variant
                # occurrences merge into this keeper (merge_target keepers
                # register too — the table-dup audit fold above).
                keeper_by_entity[_fold_physical(ekey)] = table_nodes[nid]
            elif is_alias:
                alias_nodes_by_key[alias_key] = table_nodes[nid]
            continue

        # ── Column-like nodes → field children ──
        if vt in ("column", "cte_column") or label.count(".") == 1:
            # Find parent table from source_tables
            # I2 (v3.3.145): the extractor's source_tables are exact per
            # field (set at extraction, incl. the defining alias/derived
            # scope), so attribution is extraction-time only — the same-name
            # first-match is pinned and the B3 scope-context picker plus the
            # label-prefix first-match fallback are gone (dead for
            # attribution). Seed placement is handled by the seed re-parent
            # pass instead.
            parent_table_id = None
            # #289: INSERT SELECT projections land on the write target —
            # but ONLY as a fallback. The physical model is the independent
            # truth: a write column sourced to a real table/CTE/alias (a
            # visible parent in this graph) renders ON that source, exactly
            # as the model attributes it. The write-target routing applies
            # only to projection columns the extractor sourced to a phantom
            # alias (no node at all), which would otherwise be unparented.
            if parent_table_id is None and src_tables and len(src_tables) == 1:
                # Bug 28: Match source table name directly (aliases are now visible nodes)
                # Try exact match first, then try canonical name if this is an alias
                src_name = src_tables[0]
                # #386 (CTE-scope ruling): a CTE's scope ends with its
                # statement. When src_name is a CTE VISIBLE in this
                # column's own statement, the reference folds onto the
                # cte compound (in-scope, unchanged behavior); a LATER
                # statement's bare ref to the same name is a PHYSICAL
                # read and must never land on the cte compound.
                if src_name:
                    _stmt_root = ((nd.get("context") or "")
                                  .split(":join:")[0].split("/")[0])
                    for tn in table_nodes.values():
                        if (tn.get("type") == "cte_table"
                                and (tn.get("table_name") or "").lower()
                                == src_name.lower()
                                and ((tn.get("context") or "")
                                     .split(":join:")[0].split("/")[0])
                                == _stmt_root):
                            parent_table_id = tn["id"]
                            break
                # #386: else prefer the model's OWN entity — the field's
                # occurrence owner disambiguates a same-named CTE and
                # physical table where the table_name first-match below
                # cannot (first-by-creation would land an out-of-scope
                # `FROM tmp_loan` read's columns on the cte_table
                # compound).
                if parent_table_id is None:
                    _mk = field_owner_key.get(nid)
                    if _mk is not None:
                        keeper = keeper_by_entity.get(_fold_physical(_mk))
                        if (keeper is not None
                                and keeper.get("table_name") == src_name):
                            parent_table_id = keeper["id"]
                if parent_table_id is None:
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == src_name or tid == src_tables[0]:
                            parent_table_id = tn["id"]
                            break
                # #288: case-insensitive physical-only fallback (a field of
                # a differently-cased occurrence of the merged physical
                # table still lands on the keeper).
                if (not parent_table_id
                        and src_name.lower() in _physical_names_lower_set()):
                    for tid, tn in table_nodes.items():
                        if (tn["type"] == "source_table"
                                and tn["table_name"].lower() == src_name.lower()):
                            parent_table_id = tn["id"]
                            break
                if not parent_table_id:
                    resolved = alias_map.get(src_tables[0], src_tables[0])
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == resolved:
                            parent_table_id = tn["id"]
                            break
                    # #288: case-insensitive physical-only fallback for the
                    # resolved canonical name.
                    if (not parent_table_id
                            and resolved.lower() in _physical_names_lower_set()):
                        for tid, tn in table_nodes.items():
                            if (tn["type"] == "source_table"
                                    and tn["table_name"].lower()
                                    == resolved.lower()):
                                parent_table_id = tn["id"]
                                break

            # #289 fallback: only when the projection column has NO visible
            # source parent (phantom-sourced) does it land on the write
            # target. Real table/CTE/alias sources keep their model owner.
            if parent_table_id is None:
                wtgt = write_field_target.get(nid)
                if wtgt is not None:
                    parent_table_id = _resolve_write_target(wtgt)

            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            # Show orig type as a hint but use "field" for shape
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            # B4: the field label is undecorated (no " ↻" stamp) — the dedup
            # key below uses this exact label, so same-named computed fields
            # under one parent merge instead of twinning.
            field_node = {
                "id": field_id,
                "label": (label.split(".")[-1] if "." in label else label),
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
                # K4 ruling 1 (2026-08-28, FIX-DEFECT): the chip carries the
                # def line so an L2 node click lights its variable's I1
                # definition line (R37's line semantics, previously honoured
                # for tables/aliases only). line_start ONLY — line_end would
                # re-route pickAutoEdge's priority-1 seed-zone pick
                # (frontend/src/utils/pickAutoEdge.js needs BOTH endpoints).
                # The dedup below keeps the FIRST occurrence's node, so the
                # keeper chip anchors at the first-occurrence line.
                "line_start": _safe_int(nd.get("line_start")),
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
                # Issue a: same (keeper table, field name) → one field node.
                # Contexts merged into a keeper table all re-parent here, so
                # the same physical field from two contexts would otherwise
                # duplicate; later duplicates' edges re-point to the first
                # via occ_to_id.
                # J12-16 (user ruling 2026-08-11): the key is NOT scoped by
                # the statement index — same-named field instances from
                # different statements fold into ONE display field per
                # physical table (the merged field carries every incident
                # line; its keeper is the first occurrence, whose context
                # anchors per-statement trunk decisions in
                # _simplify_dml_edges). The ⟐ output VTs themselves are
                # NEVER merged (R19.6b — they are per-statement entities by
                # construction); J12-15's per-statement DML trunk is
                # independent of this field-level fold.
                dedup_key = (parent_table_id, field_node["label"])
                dup = fields_by_key.get(dedup_key)
                if dup is not None:
                    occ_to_id[nid] = dup["id"]
                    continue
                fields_by_key[dedup_key] = field_node
            occ_to_id[nid] = field_id
            field_nodes.append(field_node)
            continue

        # ── Expression/aggregate/window/computed nodes → field children ──
        if vt in ("expression", "aggregate", "window", "case", "transform", "literal"):
            # Find parent table from source_tables or fallback to any existing table
            parent_table_id = None
            if parent_table_id is None and src_tables:
                for tid, tn in table_nodes.items():
                    if tn["table_name"] in src_tables or tid in src_tables:
                        parent_table_id = tn["id"]
                        break
                # #288: case-insensitive physical-only fallback.
                if not parent_table_id:
                    for src in src_tables:
                        if src.lower() not in _physical_names_lower_set():
                            continue
                        for tid, tn in table_nodes.items():
                            if (tn["type"] == "source_table"
                                    and tn["table_name"].lower() == src.lower()):
                                parent_table_id = tn["id"]
                                break
                        if parent_table_id:
                            break
            # #289 fallback: only when the computed projection has no visible
            # source parent (phantom-sourced) does it land on the write target.
            if parent_table_id is None:
                wtgt = write_field_target.get(nid)
                if wtgt is not None:
                    parent_table_id = _resolve_write_target(wtgt)
            if not parent_table_id and table_nodes:
                # Fallback: attach to first table node
                _log.warning("L2 fallback: %s (%s) has no source table — attached to first table node '%s'",
                             label, vt, list(table_nodes.values())[0]["table_name"])
                parent_table_id = list(table_nodes.values())[0]["id"]

            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            # B4: undecorated computed-field label (the " ↻" twin marker was
            # removed — dedup keys are label-based and must not collide with
            # decoration).
            field_node = {
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label),
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
                # K4 ruling 1: chip def line (see the column branch above).
                "line_start": _safe_int(nd.get("line_start")),
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
                # Issue a: same dedup semantics as the column branch — one
                # computed field per (keeper table, label). J12-16 (user
                # ruling 2026-08-11): the statement index is dropped from
                # the key — same-named computed fields fold into one
                # display field per physical table (per-statement identity
                # is a table-level property; the ⟐ output VTs never merge).
                dedup_key = (parent_table_id, field_node["label"])
                dup = fields_by_key.get(dedup_key)
                if dup is not None:
                    occ_to_id[nid] = dup["id"]
                    continue
                fields_by_key[dedup_key] = field_node
            occ_to_id[nid] = field_id
            field_nodes.append(field_node)
            continue

        # Fallback: attach unknown node as field child to first available table
        if table_nodes:
            _log.warning("L2 fallback: unknown node '%s' (vt=%s) has no parent — attached to first table node '%s'",
                         label, vt if vt else "unknown", list(table_nodes.values())[0]["table_name"])
            parent_table_id = list(table_nodes.values())[0]["id"]
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            occ_to_id[nid] = field_id
            field_nodes.append({
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label) + " ·",
                "type": "field",
                "variable_type": "field",
                "orig_type": (vt if vt else "unknown")[:12],
                "is_target": (nid in target_node_ids),
                "field_group": "indirect",
                "original_id": nid,
                "parent": parent_table_id,
                # K4 ruling 1: chip def line (see the column branch above).
                "line_start": _safe_int(nd.get("line_start")),
            })

    # J12-10 stage 3: the B3/P1 seed-copy proxy (seed_{id}_{keeper[:8]})
    # is GONE — the seed field now lands on the searched table's own
    # compound node directly: the physical model attributes every
    # occurrence to its entity, so the searched table's compound carries
    # the real field instance (nothing to synthesize).

    # ── #387 follow-up (2026-08-28): searched-write-table display
    # projection ──
    # A derived-alias write-projection attributed to a REAL read source
    # keeps that parent (#289's model-following rule: `p1.HTJE AS
    # LOAN_AMT` renders on the read source) — #289's write-target
    # fallback only ever covered phantom-sourced projections. But when
    # the SEARCH targets the WRITE table, the projection's own node
    # (the one carrying its value edges) belongs where the user is
    # looking: on the write target. Scoped to the searched field's own
    # projections (nid ∈ target_node_ids) whose write target resolves to
    # the searched table's compound. Display projection only — the
    # extraction truth (source_tables) is untouched, and when the write
    # table's compound already carries a same-named field (the R44
    # write-side twin) the projection's edges re-point onto THAT node
    # instead of duplicating the chip. (R46a leaves this gate owner-
    # agnostic on purpose: its explicit `is_target = True` lands on a chip
    # whose parent IS the searched table's compound, so the display scoping
    # in `_scope_target_stamp` keeps it.)
    if (search_table and physical_model is not None
            and write_field_target and target_node_ids):
        _sl = search_table.lower()
        _retarget = []          # (field node, keeper compound id)
        for fn in field_nodes:
            nid = fn.get("original_id")
            if nid not in write_field_target or nid not in target_node_ids:
                continue
            keeper = _resolve_write_target(write_field_target[nid])
            keeper_node = next((tn for tn in table_nodes.values()
                                if tn.get("id") == keeper), None)
            if (not keeper_node or fn.get("parent") == keeper):
                continue
            if keeper_node.get("table_name", "").lower() != _sl:
                continue
            _retarget.append((fn, keeper))
        for fn, keeper in _retarget:
            same = next((f for f in field_nodes
                         if f is not fn and f.get("parent") == keeper
                         and f.get("label") == fn.get("label")), None)
            if same is not None:
                # Re-point the projection (and every occurrence that
                # folded into its node) onto the write table's existing
                # same-named field — its value edges render there.
                for k, v in list(occ_to_id.items()):
                    if v == fn["id"]:
                        occ_to_id[k] = same["id"]
                if fields_by_key.get((fn.get("parent"), fn.get("label"))) is fn:
                    del fields_by_key[(fn.get("parent"), fn.get("label"))]
                field_nodes.remove(fn)
            else:
                fn["parent"] = keeper
                fn["is_target"] = True
                fields_by_key[(keeper, fn.get("label"))] = fn

    return table_nodes, field_nodes, alias_map, occ_to_id


def _map_search_target_ids(field_nodes: list, table_nodes: dict,
                           target_node_ids: set, direct_ids: set,
                           id_map: dict) -> tuple:
    """Phase 3c (issue a): resolve search-target/direct ids through id_map.

    _compute_target_and_direct_ids yields ORIGINAL graph nids; after the
    table/field dedup those may belong to merged-away contexts. Mapping
    every id through id_map (the classification's occ_to_id) resolves
    them to the merged keeper (single table node / deduped field node),
    so the highlight never lands on a ghost nid. Field nodes are
    re-marked in place: a target field that arrived via a merged-away
    context still lights up on the keeper.

    R46a: this re-mark is an EDGE-machinery seed (P2/P17/payload read it
    below), so it stays owner-agnostic; the display claim is scoped later
    by `_scope_target_stamp`, which runs after it and after the last edge
    consumer.

    Returns (target_mapped, direct_mapped).
    """
    target_mapped = {id_map.get(i, i) for i in target_node_ids}
    direct_mapped = {id_map.get(i, i) for i in direct_ids}
    for fn in field_nodes:
        if fn["id"] in target_mapped:
            fn["is_target"] = True
        if fn["id"] in direct_mapped:
            fn["field_group"] = "direct"
    return target_mapped, direct_mapped


def _carry_edge_info(src_nd: dict, tgt_nd: dict, raw_edge: dict) -> dict:
    """Extraction-time info carried on every L2 edge (W5/R25).

    The payload phase (highlight_strategies.single_line) derives
    highlight_line/flow_kind/reason from these fields ONLY — never from
    text search at render (never-patch rule). All lines are the raw
    var-carried line_start values: merged compound nodes' line_start would
    collapse per-appearance anchors (p1.data_dt@43 vs. the data_dt keeper
    @160), so the per-edge raw lines ride the edge through the pipeline.
    """
    src_vt = src_nd.get("variable_type", "")
    tgt_vt = tgt_nd.get("variable_type", "")
    src_tables = src_nd.get("source_tables") or []
    tgt_tables = tgt_nd.get("source_tables") or []
    src_label = src_nd.get("label", "")
    tgt_label = tgt_nd.get("label", "")

    def _owner(tables, label):
        return tables[0] if tables else (label.rsplit(".", 1)[0] if "." in label else "")

    def _canon(tables, label):
        return tables[0] if tables else (label.rsplit(".", 1)[0] if "." in label else label)

    return {
        "_src_line": _safe_int(src_nd.get("line_start")),
        "_tgt_line": _safe_int(tgt_nd.get("line_start")),
        "_src_label": src_label,
        "_tgt_label": tgt_label,
        "_src_vt": src_vt,
        "_tgt_vt": tgt_vt,
        "_src_tables": list(src_tables),
        "_tgt_tables": list(tgt_tables),
        "_src_ctx": src_nd.get("context", ""),
        # Field-involvement admission, Class I-4 (2026-09-02, the
        # wrong-scope belongs-to): the TARGET occurrence's own scope, read
        # off the same node dict `_src_ctx` reads. A belongs-to whose source
        # instance sits in another scope is the fold's same-named-instance
        # duplicate, and only the two contexts together can tell that — the
        # target's resolved owner (`_tgt_canon`) is already echoed by every
        # same-named instance.
        "_tgt_ctx": tgt_nd.get("context", ""),
        # Field-involvement admission (2026-08-31): the clause each raw
        # endpoint occurrence was COLLECTED in (the extraction-time
        # `defined_in` stamp) — the write-projection read leg is told from
        # its `SELECT expr` stamp, never re-derived from text.
        "_src_defined_in": src_nd.get("defined_in", "") or "",
        "_tgt_defined_in": tgt_nd.get("defined_in", "") or "",
        "_op": raw_edge.get("operation", ""),
        "_src_field_like": (src_vt in FIELD_LIKE_TYPES
                            or (src_nd.get("defined_in") or "").upper() == "PARTITION"),
        "_src_is_vt": src_vt in ("virtual_table", "subquery", "union_branch"),
        "_tgt_is_vt": tgt_vt in ("virtual_table", "subquery", "union_branch"),
        "_src_owner": _owner(src_tables, src_label),
        "_tgt_canon": _canon(tgt_tables, tgt_label),
    }


def _build_edge_list(edges: list, nodes: list, id_map: dict,
                     sql_text: str) -> tuple:
    """Phase 4 (CW4): build the raw edge list with categories and the
    carried extraction-time info the payload derives from (W5/R25).

    Compound edge types are split per-type (Bug 3); each split edge carries
    the same extraction-time info as its parent raw edge. The old
    sql_range enrichment (find_sql_range) is gone with sql_range_finder —
    the payload phase replaces it with per-edge highlight_line.

    Returns (new_edges, node_labels).
    """
    new_edges = []

    # Raw node lookup: id → data (label/line_start/variable_type/…)
    node_info = {}
    for n in nodes:
        nd = n.get("data", n)
        node_info[nd.get("id", "")] = nd

    for e in edges:
        ed = e.get("data", e)
        src_orig = ed.get("source", "")
        tgt_orig = ed.get("target", "")
        rel = ed.get("relationship", "") or ed.get("edge_type", "")
        edge_type = rel if rel else "REF"

        src_new = id_map.get(src_orig, src_orig)
        tgt_new = id_map.get(tgt_orig, tgt_orig)

        if src_new == tgt_new:
            continue  # skip self-loops from ID mapping

        category = _get_category(edge_type)
        style = _get_edge_style(edge_type)

        carried = _carry_edge_info(node_info.get(src_orig, {}),
                                   node_info.get(tgt_orig, {}), ed)

        # Bug 3 fix: split compound edge types, each keeps its own carried
        # extraction-time info (the payload derives per-type anchors).
        etypes = [t.strip() for t in edge_type.split(",")] if "," in edge_type else [edge_type]
        for et in etypes:
            if len(etypes) > 1:
                et_style = EDGE_TYPE_STYLE.get(et, EDGE_TYPE_STYLE["SUBSET"])
                et_category = CATEGORY_MAP.get(et, "structure")
                color = et_style["color"]
                line_style = et_style["line"]
                width = et_style["width"]
                desc = et_style["desc"]
            else:
                color = style["color"]
                line_style = style["line"]
                width = style["width"]
                desc = style["desc"]
            new_edges.append({
                "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{et}'.encode()).hexdigest()[:12]}",
                "source": src_new,
                "target": tgt_new,
                "edge_type": et,
                "category": et_category if len(etypes) > 1 else category,
                "color": color,
                "label": et,
                "line_style": line_style,
                "width": width,
                "desc": desc,
                **carried,
            })
    return new_edges, {i: nd.get("label", "") for i, nd in node_info.items()}


def _carrier_anchor(e: dict) -> int:
    """RC-B multi-anchor (2026-08-31): the highlight_line this carrier will
    be SERVED with — the payload rule itself
    (`highlight_strategies._flow_kind` + `_anchor_line`, evaluated on the
    carrier's carried extraction-time info), not a reconstruction of it.

    This is the fold's occurrence discriminator. Two carriers of one
    (source, target, edge_type) pair whose served anchor differs are two
    occurrences of the field in the SQL text, not two copies of one edge —
    the model carries both, so the served payload must show both (R44 "cover
    all occurrences"; the string-match layer colors served lines)."""
    try:
        return int(_anchor_line(e, _flow_kind(e)) or 0)
    except Exception:                                   # malformed carrier
        return _safe_int(e.get("_src_line"))


def _combine_edges(new_edges: list, node_lines: dict | None = None) -> list:
    """Phase 5 (CW4): same (source,target,edge_type) → combine labels.

    The first occurrence keeps its carried extraction-time info (the
    payload anchor is per-edge, derived later from that carried info).

    R45 Fix H (2026-08-28.8): EXCEPT when a carrier IS the keeper chip's
    own occurrence. One display field folds every occurrence of a
    physical field (J12-16 — the key is not statement-scoped), so a
    belongs-to/structure edge arrives once per occurrence: the CTE-body
    birth (`SUBSTR(P1.BRANCH_CODE,-3) AS tag_branch` @721) and the outer
    statement's later read occurrence (`A.tag_branch` inside NVL @1030,
    the family-3 twin) both carry `TEMP_BDM_ACC_LOAN_INFO_02 → tag_branch`.
    First-carrier-wins anchored the folded edge at the LATER occurrence and
    the birth line went dark — the field node keeps its birth `line_start`,
    so the carrier that agrees with it is the honest anchor. Carriers that
    do not name the chip's line keep first-carrier-wins (an occurrence-line
    anchor a canonical pin relies on — SUP_M's GROUP BY SCHEMA@59 — is a
    sibling occurrence, never the chip's line).

    LFS108 residual (2026-08-29): EXCEPT as well when the keeper's
    occurrence line is CLAIMED by a different relationship on the same
    endpoint pair. The lending_ref↓SUP_M NOT-IN filter folds three
    carriers of `lending_ref → ⟐subq (FILTER)` — @41 (the JOIN-key
    occurrence, whose line 41 is `... = p1.lending_ref` inside the ON
    clause) and @48 twice (the `AND p1.lending_ref NOT IN (` occurrence +
    its twin). All three carry identical extraction-time info but
    `_src_line`, so the only available discriminator is the graph itself:
    line 41 already carries the pair's JOIN edge (the join key IS what
    that line is), so the @41 FILTER carrier is that JOIN's line wearing
    the wrong type and the anchor belongs to the occurrence whose line is
    unique to this relationship. Guarded so it cannot drift the pins Fix
    H and the canonical rely on: it fires only when Fix H's own rule did
    not, the keeper's field-side line is shared with a different type on
    the same (source, target), and the candidate's is not — Fix H's
    keeper-line rule wins first (SCHEMA@59 keeps its GROUP-BY anchor).

    RC-B multi-anchor (2026-08-31): the fold key is
    (source, target, edge_type, ANCHOR) with ANCHOR = `_carrier_anchor(e)`
    — the highlight_line the carrier will be served with. The old
    (source, target, edge_type) key kept ONE carrier per pair, so when N
    occurrences of the searched field reach the same target the served
    payload showed ONE anchor line and the other N-1 went dark (the 10-case
    cross-check: SUP_M lending_ref @95/@156/@163/@206 all folded into the
    @201 carrier while the model carried all four JOIN edges). Distinct
    anchors ⇒ distinct served edges, one per line, sorted by line.

    Under that key the three landed guards keep their roles, re-scoped to
    the anchor group they always acted on:
      · Fix H — among the carriers of ONE anchor group, the carrier that
        names the keeper chip's own line represents that line (its latch is
        per group). The chip's own line is also just another group now, so
        the birth anchor Fix H rescued is served AND the later occurrence
        keeps its own edge — the R44 ruling the single-carrier fold could
        not express.
      · AD2-B line-0 guard — `node_lines` values of 0 build no `fix_h`
        entry, so a line-0 chip still never promotes a carrier, and a
        group whose anchor is 0 is still only ever kept by carrier order.
      · LFS108 — generalized from "yield the anchor" to "do not mint an
        anchor": a group whose keeper is field-like AND whose field-side
        line another relationship already claims on the same pair is not
        this relationship's own occurrence, so it is dropped when the same
        pair carries a group whose line IS its own (Fix H's carrier stays
        immune — a chip-line carrier is the chip's own occurrence, never a
        borrowed site). `lending_ref → ⟐subq (FILTER)` keeps exactly one
        served edge, anchored at 48; the JOIN-key line 41 does not gain a
        phantom FILTER edge.

    Output is ordered by (anchor, first-carrier position) — content- and
    input-order derived, never hash order (two determinism leaks fixed
    earlier stay fixed). Every survivor is stamped `_fold_anchor` so the
    Phase 9 dedup (which sees the POST-promotion pair, where sibling field
    chips have already been folded onto their parent table) can tell two
    occurrences of one field apart. The carrier is stripped at assembly."""
    # (source, target, field-side occurrence line) -> {edge types} — the
    # relationship claim each line carries for a folded pair.
    claimed: dict[tuple, set] = {}
    for e in new_edges:
        _ln = _safe_int(e.get("_src_line")) or 0
        if _ln:
            claimed.setdefault((e["source"], e["target"], _ln), set()).add(
                e.get("edge_type"))
    # Fix H decided over the WHOLE carrier set, before the loop — not
    # carriers[1:] (2026-08-29): the earlier loop-side guard only saw the
    # carriers after the first, so a Fix-H carrier sitting in slot 0 (or
    # merely ahead of the chip-line carrier) never won, and the LFS108
    # residual latched `keepers` for the first carrier and locked Fix H
    # out for good. `setdefault` keeps first-in-edge-order — deterministic.
    # RC-B: keyed per anchor group — Fix H picks the representative OF a
    # line, it never erases the other lines any more.
    fix_h: dict[tuple, dict] = {}
    if node_lines is not None:
        for e in new_edges:
            _w = node_lines.get(e["target"])
            if not _w or _safe_int(e.get("_tgt_line")) != _w:
                continue
            fix_h.setdefault(
                (e["source"], e["target"], e["edge_type"], _carrier_anchor(e)),
                e)
    combined_edges = {}
    keepers: dict[tuple, int] = {}
    order: dict[tuple, int] = {}
    for idx, e in enumerate(new_edges):
        key = (e["source"], e["target"], e["edge_type"], _carrier_anchor(e))
        if key not in order:
            order[key] = idx
        if key in combined_edges:
            existing = combined_edges[key]
            # Combine labels
            existing_labels = set(existing.get("label", "").split(", "))
            existing_labels.add(e.get("label", ""))
            existing["label"] = ", ".join(sorted(existing_labels))
            if key in fix_h and key not in keepers:
                keepers[key] = 1                      # latch even when already keeper
                if combined_edges[key] is not fix_h[key]:
                    combined_edges[key] = fix_h[key]
            elif node_lines is not None and key not in keepers:
                want = node_lines.get(e["target"])
                if want and _safe_int(e.get("_tgt_line")) == want != _safe_int(
                        existing.get("_tgt_line")):
                    combined_edges[key] = e
                    keepers[key] = 1
                # LFS108 residual: yield the anchor to the occurrence line
                # this relationship alone owns (see docstring).
                elif (existing.get("_src_field_like")
                      and _is_claimed_together(existing, claimed)
                      and not _is_claimed_together(e, claimed)):
                    combined_edges[key] = e
                    keepers[key] = 1
        else:
            combined_edges[key] = e
    # RC-B / LFS108 generalized: a group whose keeper's field-side line is
    # another relationship's site on the same pair earns no edge of its own
    # when the pair has a group whose line is this relationship's alone.
    if node_lines is not None:
        own_line: dict[tuple, set] = {}
        for key, e in combined_edges.items():
            if not _is_claimed_together(e, claimed):
                own_line.setdefault(key[:3], set()).add(key[3])
        combined_edges = {
            key: e for key, e in combined_edges.items()
            if (key in keepers
                or fix_h.get(key) is e          # Fix H's carrier is immune
                or not e.get("_src_field_like")
                or not _is_claimed_together(e, claimed)
                or not own_line.get(key[:3]))
        }
    # Deterministic emission: by anchor line, ties by first-carrier order.
    ordered = sorted(combined_edges.items(),
                     key=lambda kv: (kv[0][3], order[kv[0]]))
    # RC-B: the raw edge id is (source, target, edge_type)-derived, so the
    # per-occurrence siblings of one pair would collide on the same id —
    # and Cytoscape keys elements by id while the benchmark's used-set
    # consumes ids. The first carrier keeps its id; every sibling is
    # re-derived from the pair + ITS anchor, keeping the DML rewrite
    # suffixes the payload contract keys on (`*_dml_out`, `*_value`).
    seen_base: set = set()
    for key, e in ordered:
        raw, suffix = e["id"], ""
        for mark in ("_dml_out", "_value"):
            if raw.endswith(mark):
                suffix, raw = mark, raw[: -len(mark)]
                break
        if raw in seen_base:
            e["id"] = ("l2e_{}".format(
                hashlib.md5(
                    f"{e['source']}{e['target']}{e['edge_type']}{key[3]}"
                    .encode()).hexdigest()[:12]) + suffix)
        seen_base.add(raw)
        e["_fold_anchor"] = key[3]
    return [e for _key, e in ordered]


def _is_claimed_together(edge: dict, claimed: dict) -> bool:
    """True when `edge`'s field-side occurrence line is shared with a
    DIFFERENT edge type on the same (source, target) pair — that line is
    another relationship's site, not this edge's own occurrence."""
    _ln = _safe_int(edge.get("_src_line")) or 0
    if not _ln:
        return False
    types = claimed.get((edge["source"], edge["target"], _ln))
    if not types:
        return False
    return bool(types - {edge.get("edge_type")})


def _promote_field_edges(new_edges: list, field_nodes: list) -> list:
    """Phase 6 (CW4): promote field-level edges to their parent tables.

    SCHEMA edges (table→field ownership) are KEPT as-is — the user ruling
    (2026-08-10): every L2 edge is a data flow and highlights; the SCHEMA
    edge included ("the scheme edge is also included"). Their source is a
    table node already and their target must stay the field node, so they
    are appended unchanged (no promotion of either endpoint). Each edge
    type keeps its own edge with its own carried extraction-time info (W5).

    P2: edges incident on a search-target seed field stay at field level —
    promoting them hid the seed's own data flow (e.g. its FILTER edges
    vanished into the parent alias table node).
    """
    field_parents = {}
    target_field_ids = set()  # P2: search-target seed fields keep field-level edges
    for fn in field_nodes:
        pid = fn.get("parent")
        if pid:
            field_parents[fn["id"]] = pid
        if fn.get("is_target"):
            target_field_ids.add(fn["id"])

    # V3.3.65: Promote fields→tables, keep edges separate per type.
    # Each edge type gets its own edge with its own carried extraction-time
    # info (the W5 payload derives per-type anchors from it).
    # No compound merging — clicking different edge types shows different SQL.
    promoted = []
    for e in new_edges:
        src = e["source"]
        tgt = e["target"]
        etype = e["edge_type"]

        if etype == "SCHEMA":
            # Ownership is implicit in the compound node structure, but the
            # edge itself stays visible (structure kind, §8.7 rule 6).
            promoted.append(e)
            continue
        if src in field_parents and src not in target_field_ids:
            src = field_parents[src]
        if tgt in field_parents and tgt not in target_field_ids:
            tgt = field_parents[tgt]
        if src == tgt:
            continue

        e["source"] = src
        e["target"] = tgt
        promoted.append(e)

    return promoted


def _survive_join_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict, field_nodes: list,
                        node_labels: dict, sql_text: str,
                        strict: bool = False) -> list:
    """Phase 7 (CW4): Bug 45 (Pattern 2) JOIN edge survival pass.

    filter_relevant() removes JOIN edges because JOIN is conditional (both ends
    need a production path). But JOIN edges are semantically valuable — they show
    table relationships even without value flow. After promotion, re-add JOIN
    edges from the full graph that connect tables in the current L2 graph.

    C6 (v3.3.140): gated — when the strict table.field flow filter is active
    (`strict=True`, the flag comes from _build_l2_graph, which knows whether
    filtering was requested), this is a no-op: the strict closure already
    contains the field-relevant JOIN partners (FILTER/JOIN edges are admitted
    by the walker when a seed zone touches either end), and re-adding JOIN
    edges from the full graph would break the strict field-flow closure. The
    survival heuristic (including its name-first-match fallback) runs only on
    the legacy full-graph path (no filtering requested).
    """
    if strict:
        return new_edges
    # Build node_by_id for JOIN survival pass
    node_by_id = {}
    for tn_id, tn in table_nodes.items():
        node_by_id[tn_id] = tn
    for fn in field_nodes:
        node_by_id[fn["id"]] = fn

    # Bug 45: Build full_node_by_id for fallback resolution when id_map misses
    # (field-level endpoints filtered out). Resolve to parent table via label prefix
    # or source_tables.
    full_node_by_id = {}
    for fn in full_graph.get("nodes", []):
        fnd = fn.get("data", fn)
        full_node_by_id[fnd.get("id", "")] = fnd

    seen_join_keys = set()
    for e in new_edges:
        if e.get("edge_type") == "JOIN":
            seen_join_keys.add((e["source"], e["target"]))
    full_edges = full_graph.get("edges", [])
    for fe in full_edges:
        fed = fe.get("data", fe)
        fetype = fed.get("edge_type", "") or fed.get("relationship", "")
        if fetype != "JOIN":
            continue
        src_orig = fed.get("source", "")
        tgt_orig = fed.get("target", "")
        src_new = id_map.get(src_orig)
        tgt_new = id_map.get(tgt_orig)

        # Bug 45: When field-level endpoint was filtered out, resolve to parent table
        if not src_new and src_orig in full_node_by_id:
            src_node = full_node_by_id[src_orig]
            src_label = src_node.get("label", "")
            src_tables = src_node.get("source_tables", [])
            src_parent = (src_tables[0] if src_tables else
                          src_label.rsplit(".", 1)[0] if "." in src_label else "")
            for tn in table_nodes.values():
                if tn.get("table_name") == src_parent:
                    src_new = tn["id"]
                    break
        if not tgt_new and tgt_orig in full_node_by_id:
            tgt_node = full_node_by_id[tgt_orig]
            tgt_label = tgt_node.get("label", "")
            tgt_tables = tgt_node.get("source_tables", [])
            tgt_parent = (tgt_tables[0] if tgt_tables else
                          tgt_label.rsplit(".", 1)[0] if "." in tgt_label else "")
            for tn in table_nodes.values():
                if tn.get("table_name") == tgt_parent:
                    tgt_new = tn["id"]
                    break

        if not src_new or not tgt_new or src_new == tgt_new:
            continue
        key = (src_new, tgt_new)
        if key in seen_join_keys:
            continue
        seen_join_keys.add(key)
        src_obj = node_by_id.get(src_new, {})
        tgt_obj = node_by_id.get(tgt_new, {})
        if src_obj.get("type") in ("field",) or tgt_obj.get("type") in ("field",):
            continue
        # W5: carry the raw full-graph nodes' extraction-time info so the
        # payload phase anchors this survival edge like any other (raw
        # cache edges carry relationship, not edge_type).
        src_raw = full_node_by_id.get(src_orig, {})
        tgt_raw = full_node_by_id.get(tgt_orig, {})
        new_edges.append({
            "id": f"l2e_join_survive_{src_new}_{tgt_new}",
            "source": src_new,
            "target": tgt_new,
            "edge_type": "JOIN",
            "category": "filter",
            "color": "#E91E63",
            "label": "JOIN",
            "line_style": "dashed",
            "width": 2,
            "desc": "JOIN key (table relationship)",
            **_carry_edge_info(src_raw, tgt_raw, fed),
        })
    return new_edges


def _simplify_dml_edges(new_edges: list, full_graph: dict, id_map: dict,
                        table_nodes: dict, field_nodes: list = None,
                        physical_model=None) -> list:
    """Phase 8 (CW4): DML edges route through the ⟐ output (intermediate_table).

    J12-10 stage 3: returns just new_edges — the dml_pairs output fed the
    retired DML-phantom sync (_sync_alias_and_dml_fields, deleted); the
    write targets now resolve through the physical model's roles.

    J12-15 (stage 4, BUG_ANALYSIS): the trunk is selected PER raw DML
    edge — the owning statement's own ⟐ output VT (each output VT entity
    has exactly one occurrence — the raw edge's source var), resolved via
    the physical model's entity_of_id ('⟐ output', TOPn) per-context
    keys. Edges whose statement's output VT is absent from the graph keep
    the "⟐ output"-preferred global fallback (the first intermediate
    table).
    """
    # P17 (§8.5): search-target seed fields keep field-level edges — the
    # value-edge retention below only fires for them.
    target_field_ids = set()
    for fn in field_nodes or []:
        if fn.get("is_target"):
            target_field_ids.add(fn["id"])
    # ── Simplification 1: DML edges route through ⟐ output (intermediate_table) ──
    # Instead of creating synthetic qo_ nodes, use the existing intermediate_table
    # ("⟐ output") node that already represents the SELECT result set.
    # This eliminates 4 regression-prone patches: qo_ creation, dedup, repointing, self-loop removal.
    #
    # Before: raw_orders ──[DML]──> stg_orders
    # After:  raw_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_orders
    #
    # All intermediate operations (TRANSFORM, AGGREGATE, FILTER, JOIN, etc.) connect to ⟐ output,
    # not directly to the DML target. The output node is the trunk of the data flow.
    # W5: the intermediate MUST be the "⟐ output" node — the first
    # intermediate_table in iteration order can be a subquery VT (⟐ subq1),
    # routing DML targets through the wrong trunk (bogus subq1→target
    # edges). Prefer table_name "⟐ output", fall back to the first
    # intermediate_table for graphs without a query-output node.
    intermediate_id = None
    for tn in table_nodes.values():
        if isinstance(tn, dict) and tn.get("type") != "intermediate_table":
            continue
        if intermediate_id is None:
            intermediate_id = tn.get("id")
        if (tn.get("table_name") or "").startswith("⟐ output"):
            intermediate_id = tn.get("id")
            break

    # ── J12-15: per-statement trunk map ──
    # For every raw DML edge whose source var is a statement's own output
    # VT — the model's entity_of_id key ('⟐ <name>', TOPn), output VTs
    # being (name, context)-keyed virtual entities with exactly one
    # occurrence, the raw edge's source var (J12-17: the name is not
    # always "⟐ output" — a bare/VALUES INSERT (no SELECT body) names
    # its output "⟐ insert"; any "⟐ "-prefixed statement-level VT whose
    # context is exactly TOP{numeric} qualifies — nested ⟐ containers
    # carry "/" or ":" context segments and are never DML sources). The
    # statement's own output-VT compound becomes stmt_trunk[TOPn].
    # Statements without an output VT in the graph fall back to the
    # global intermediate (mission contract: the "⟐ output"-preferred
    # fallback stays for missing statement outputs).
    by_orig = {tn.get("original_id"): tn for tn in table_nodes.values()}
    stmt_trunk = {}
    if physical_model is not None:
        for fe in full_graph.get("edges", []):
            fed = fe.get("data", fe)
            rel = fed.get("edge_type", "") or fed.get("relationship", "")
            if "DML" not in rel.upper():
                continue
            src = fed.get("source", "")
            ekey = physical_model.entity_of_id.get(src)
            _ek_ctx = ekey[1] if (
                isinstance(ekey, tuple) and len(ekey) == 2
                and isinstance(ekey[1], str)) else ""
            if not (isinstance(ekey, tuple) and len(ekey) == 2
                    and isinstance(ekey[0], str)
                    and ekey[0].startswith("⟐ ")
                    and _ek_ctx.startswith("TOP")
                    and _ek_ctx[3:].isdigit()):
                continue
            tn = by_orig.get(src)
            if tn is not None:
                stmt_trunk[_ek_ctx] = tn["id"]
    # ALL ⟐ output compound ids — the per-statement trunk guards (rules
    # 1/2 and pattern 2) must exempt every output compound, not just the
    # global intermediate: the FIXED statement-1 write leg (output@TOP1
    # → target) would otherwise be suppressed as a bypass edge.
    output_ids = {tn["id"] for tn in table_nodes.values()
                  if (tn.get("table_name") or "").startswith("⟐ output")}
    # compound → owning statement: table compounds carry their own
    # extraction context; field compounds' keeper occurrence context
    # (J12-15: the statement of the edge's source var picks its trunk).
    ctx_by_id = {}
    for tn in table_nodes.values():
        ctx_by_id[tn["id"]] = tn.get("context", "")
    for fn in field_nodes or []:
        if physical_model is not None:
            occ = physical_model.occurrence(fn.get("original_id", "")) or {}
            ctx_by_id[fn["id"]] = occ.get("context", "")

    def _stmt_of(e: dict) -> str:
        """The edge's OWN statement — the raw source occurrence's carried
        context (`_src_ctx`; J12-16: a folded field compound collapses
        per-statement identities, so the compound's keeper context is NOT
        the edge's statement); compound-context fallback for synthetic
        edges that carry no `_src_ctx`."""
        return ((e.get("_src_ctx") or ctx_by_id.get(e.get("source", "")) or "")
                .split("/", 1)[0])

    def _trunk_for(e: dict) -> str | None:
        """The ⟐ output compound of the edge's OWNING statement — the
        statement of the edge's source OCCURRENCE (carried _src_ctx —
        the J12-15 per-statement identity, which the J12-16 field fold
        must not collapse), via the per-statement trunk map (J12-15);
        the global fallback when the statement's output VT is missing
        from the graph."""
        return stmt_trunk.get(_stmt_of(e), intermediate_id)

    # J12-18: rerouted edges must carry the trunk's own target label/line.
    # The carried _tgt_label/_tgt_line are stamped ONCE at _carry_edge_info
    # from the RAW DML target (the write table); re-targeting onto the ⟐
    # output VT leaves them stale, so the payload's own segment (built
    # from the carried labels) names the DML table while the drawn edge
    # ends at the output VT. _tgt_output (set in _attach_flow_payload)
    # marks the rerouted case.
    l2id_to_tn = {tn["id"]: tn for tn in table_nodes.values()}

    def _retarget_to_trunk(e: dict, trunk_id: str) -> None:
        """Re-point e onto its statement's ⟐ output trunk and refresh the
        carried target label/line to the trunk's own (J12-18)."""
        e["target"] = trunk_id
        _tn = l2id_to_tn.get(trunk_id)
        if _tn is not None:
            e["_tgt_label"] = _tn.get("table_name") or _tn.get("label", "")
            e["_tgt_line"] = _safe_int(_tn.get("line_start"))

    # Collect DML target tables and DML source→target pairs
    # Bug 46: Populate from full_graph.edges (unfiltered), not new_edges.
    # filter_relevant() removes DML edges whose source columns are not in
    # the lineage set, making dml_targets empty. The redirect pass at line
    # ~635 needs dml_targets to route TABLE_FLOW through the trunk.
    dml_targets = set()
    dml_sources = set()
    # J12-16: dml-sourcedness is per-OCCURRENCE — one folded field
    # compound may be a DML source in statement A and a plain read in
    # statement B (flagship sup data_dt: write column @160 in TOP0,
    # reads @223/225 in TOP1). Rule 2's bypass redirect must key off the
    # edge's OWN statement (pre-merge the per-statement field split
    # provided that granularity; the fold erases it, so the per-statement
    # map restores it). Sources whose occurrence context cannot be
    # resolved land in the None bucket — a defensive superset consulted
    # from any statement (no model → everything lands there, which
    # reproduces the global pre-merge semantics exactly).
    dml_sources_by_stmt = {}
    for fe in full_graph.get("edges", []):
        fed = fe.get("data", fe)
        rel = fed.get("edge_type", "") or fed.get("relationship", "")
        if "DML" not in rel.upper():
            continue
        tgt_new = id_map.get(fed.get("target", ""))
        src_new = id_map.get(fed.get("source", ""))
        if tgt_new:
            dml_targets.add(tgt_new)
        if src_new:
            dml_sources.add(src_new)
            stmt = None
            if physical_model is not None:
                occ = physical_model.occurrence(fed.get("source", "")) or {}
                ctx = occ.get("context") or ""
                stmt = ctx.split("/", 1)[0] if ctx else None
            dml_sources_by_stmt.setdefault(stmt, set()).add(src_new)

    new_dml_edges = []
    for e in new_edges:
        etype = e.get("edge_type", "")
        src = e.get("source", "")
        tgt = e.get("target", "")
        # 1. Suppress TABLE_FLOW bypass edges (replaced by source→⟐→target chain)
        if (src in dml_sources and tgt in dml_targets
            and etype == "TABLE_FLOW"
            and src not in output_ids and tgt not in output_ids):
            continue
        # 2. Redirect non-DML bypass edges to the statement's ⟐ output
        # (TRANSFORM, AGGREGATE, etc.). J12-16: the source must be a DML
        # source of the edge's OWN statement — a folded field that is a
        # DML source in another statement only (the stmt-2 sup data_dt
        # reads) is NOT a bypass (pre-merge, the per-statement field
        # split exempted them; the fold restores the exemption here).
        # J12-16: the retarget runs BEFORE _combine_edges (orchestrator
        # order), so this divergence makes the folded field's per-statement
        # edge instances survive the (source, target, edge_type) combine
        # with DISTINCT targets — and the id must be recomputed from the
        # retargeted endpoints (the raw id would collide with the un-
        # retargeted sibling instance, and the benchmark's per-edge used
        # id set consumes ids on first match).
        if ((src in dml_sources_by_stmt.get(_stmt_of(e), set())
             or src in dml_sources_by_stmt.get(None, set()))
            and tgt in dml_targets
            and "DML" not in etype.upper()
            and etype != "TABLE_FLOW"
            and src not in output_ids and tgt not in output_ids
            and intermediate_id):
            if src == _trunk_for(e):
                # J12-17: the edge already starts at its own statement's
                # trunk — retargeting would fold it into a self-loop
                # (a bare/VALUES INSERT's raw REF READ ⟐insert→target
                # duplicates the routed write leg trunk→target; its flow
                # is already represented). Drop the redundant duplicate.
                continue
            _retarget_to_trunk(e, _trunk_for(e))
            e["id"] = f"l2e_{hashlib.md5(f'{e['source']}{e['target']}{e['edge_type']}'.encode()).hexdigest()[:12]}"
            new_dml_edges.append(e)
            continue
        # 3. Replace DML edges with ⟐ output → target (TABLE_FLOW)
        if "DML" in etype.upper() and intermediate_id:
            output_edge = dict(e)
            output_edge["id"] = f"{e['id']}_dml_out"
            output_edge["source"] = _trunk_for(e)
            output_edge["edge_type"] = "TABLE_FLOW"
            output_edge["label"] = "TABLE_FLOW"
            # W5: the rewrite keeps the raw edge's carried extraction-time
            # info; _dml_origin marks the write kind (§8.7 row 3) and its
            # anchor = the write line (rule 3 — the DML target's line).
            output_edge["_dml_origin"] = True
            new_dml_edges.append(output_edge)
            # W-iteration (P17, §8.5): a search-target seed field's VALUE
            # edge (its DML write of the searched field's value column —
            # '$(load_date)' AS data_dt@213 → rrcdm) keeps its source→⟐
            # half: the value appearance stays traceable (the write-group
            # ruling: write line 211 / value line 213 / read line 223).
            # _value_edge marks it so the write anchor uses the VALUE's
            # own line (the source's), not the write line.
            if src in target_field_ids and src != intermediate_id:
                value_edge = dict(e)
                value_edge["id"] = f"{e['id']}_value"
                _retarget_to_trunk(value_edge, _trunk_for(e))
                value_edge["edge_type"] = "TABLE_FLOW"
                value_edge["label"] = "TABLE_FLOW"
                value_edge["_dml_origin"] = True
                value_edge["_value_edge"] = True
                new_dml_edges.append(value_edge)
        else:
            new_dml_edges.append(e)
    new_edges = new_dml_edges

    # Bug 46 (Pattern 2): Redirect TABLE_FLOW edges that bypass ⟐ output.
    # After DML simplification, any surviving TABLE_FLOW edge into a DML target
    # that doesn't go through the statement's trunk should be redirected.
    #
    # W5: when the bypass source already has a TABLE_FLOW edge into its
    # trunk (its qo/FROM edge), the redirect would collide with it in
    # dedup — and the bypass edge can come FIRST, so its carried info (the
    # m1 source's own line) would corrupt the qo edge's payload (sup seed:
    # the p2→sup m1 redirect would overwrite pair 15's qo carried info,
    # anchoring 199 instead of the output node's creation line). Drop the
    # redundant bypass instead: its flow is already represented by
    # src→trunk + trunk→target.
    if output_ids:
        to_intermediate = {(e["source"], e["target"]) for e in new_edges
                           if e.get("target") in output_ids
                           and e.get("edge_type") == "TABLE_FLOW"}
        kept = []
        for e in new_edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            etype = e.get("edge_type", "")
            if tgt in dml_targets and src not in output_ids and etype == "TABLE_FLOW":
                trunk = _trunk_for(e)
                if (src, trunk) in to_intermediate:
                    continue  # redundant bypass — src already flows via its trunk
                e["source"] = trunk
            kept.append(e)
        new_edges = kept

    return new_edges


def _dedup_edges(new_edges: list) -> list:
    """Phase 9 (CW4): merge edges with the same (source,target,type).

    The first occurrence keeps its carried extraction-time info (the
    payload anchor is derived from it later).

    RC-B multi-anchor (2026-08-31): a folded edge carries the anchor its
    Phase 5 group was keyed on (`_fold_anchor`) and the dedup key includes
    it. This pass runs AFTER `_promote_field_edges` — sibling field chips
    have already been replaced by their parent table — so the promoted pair
    alone cannot tell two occurrences of ONE field from two different
    fields; without the anchor this pass would re-collapse exactly what the
    multi-anchor fold split apart. The carrier is stripped at assembly."""
    deduped = {}
    for e in new_edges:
        anchor = e.get("_fold_anchor")
        key = ((e.get("source"), e.get("target"), e.get("edge_type"))
               if anchor is None else
               (e.get("source"), e.get("target"), e.get("edge_type"), anchor))
        # Rule 4e (2026-09-02): co-located producers of ONE box stay distinct
        # — the own-segment source field (`_src_label`, e.g. BBZ's arm-1
        # `a.charge_department` vs arm-2 `a.TAG_PRIMARY_ACCOUNTABLE_PARTY`
        # at the same box→BBZ pair) is part of the story the user ruled each
        # producer keeps at its own anchor line. Edges without the label
        # dedup exactly as before.
        src_field = e.get("_src_label")
        if src_field:
            key = key + (src_field,)
        if key not in deduped:
            deduped[key] = e
    return list(deduped.values())


def _closure_bfs(start_ids: list, out_adj: dict) -> dict:
    """R20 — the multi-source BFS behind the upstream closure walk.

    Returns the BFS-tree parent map `prev` over EVERY node reachable from
    `start_ids` (directed, FIFO — the discovery order of the former
    per-edge `_bfs`), where `prev[node] = (parent_node, edge_used)` and
    `prev[start] = None`. One run answers the shortest path from the
    closure entries to any node, so the walk is built once per payload
    phase instead of once per edge (PERF v3.3.194)."""
    prev = {sid: None for sid in start_ids}
    queue = list(start_ids)
    seen = set(start_ids)
    qi = 0
    while qi < len(queue):
        node = queue[qi]
        qi += 1
        for oe in out_adj.get(node, []):
            nxt = oe["target"]
            if nxt not in seen:
                seen.add(nxt)
                prev[nxt] = (node, oe)
                queue.append(nxt)
    return prev


def _closure_hops(nid: str, prev_dir: dict, prev_und: dict,
                  junction: tuple) -> list:
    """R20 — the UPSTREAM half of the §8.8.3 flow string, reconstructed
    from `_closure_bfs`' parent maps: the closure walk from the searched
    seed's field (the closure entries) to this edge's SOURCE, rendered as
    {label}@L{line} hops.

    Shortest path over the FINAL L2 edges (directed first, undirected as
    a fallback — the closure walk is connectivity-based); visited sets
    keep the walk acyclic (self-loops can never loop it).

    `junction` is the edge's own carried (source label, source line): the
    walk's final hop IS this edge's source (same node, same carried
    label), so it is deduped away — the caller appends the edge's own
    segment right after. Compared in the RAW carried form (no "?" fill —
    a missing label never matches a filled hop).

    Returns [] when the source is unreachable from the entries in both
    directions, or when it IS a closure entry (no upstream hops — the own
    segment starts the path)."""
    prev = prev_dir if nid in prev_dir else prev_und
    if nid not in prev:
        return []
    path = []
    node = nid
    while prev.get(node) is not None:
        parent, oe = prev[node]
        path.append(oe)
        node = parent
    path.reverse()
    if not path:
        return []
    hops = [(pe.get("_src_label") or "?", _safe_int(pe.get("_src_line")))
            for pe in path]
    hops.append((path[-1].get("_tgt_label") or "?",
                 _safe_int(path[-1].get("_tgt_line"))))
    # Dedup the shared junction hop (the walk's final hop is this edge's
    # source — same node, same carried label).
    if hops and hops[-1] == junction:
        hops = hops[:-1]
    return hops


def _downstream_bfs(start: str, flow_targets: set, adjacency: dict,
                    memo: dict | None = None) -> tuple:
    """The BFS half of `_downstream_walk`: one forward walk to exhaustion
    over the flow adjacency from `start`.

    Returns (reachable, prev) — every reachable flow target (the DML
    write targets in the seed's closure) + the BFS-tree parent map
    (`prev[start] = None`, `prev[node] = (parent, edge_used)`; the visited
    set keeps the walk acyclic, hard rule 5).

    `memo` (per payload phase, never module state): the walk is a pure
    function of (start, flow_targets, adjacency) and every edge whose
    target is `start` needs the SAME walk — one BFS per target node
    instead of one per edge (PERF v3.3.194)."""
    if memo is not None and start in memo:
        return memo[start]
    reachable = {}
    prev = {start: None}
    seen = {start}
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node in flow_targets:
            reachable[node] = True
        for oe in adjacency.get(node, []):
            nxt = oe.get("target")
            if nxt not in seen:
                seen.add(nxt)
                prev[nxt] = (node, oe)
                queue.append(nxt)
    if memo is not None:
        memo[start] = (reachable, prev)
    return reachable, prev


def _downstream_walk(e: dict, flow_targets: set, adjacency: dict,
                     tgt_key_to_target: dict | None = None,
                     write_line_by_target: dict | None = None,
                     _reach_memo: dict | None = None) -> list:
    """R20 — the DOWNSTREAM continuation of the §8.8.3 flow string: the
    FORWARD walk from this edge's final target to a flow target (a DML
    write target in the seed's closure — the target of a `_dml_origin`
    write leg), rendered as {label}@L{line} hops.

    Directed-only (the continuation must be genuine forward flow — never
    the undirected fallback); flow edges only (SCHEMA/SUBSET are exempt
    from the path property, R19.4 — the passed adjacency is pre-filtered
    and this walk itself refuses structure/bridge edges); visited sets
    keep the walk acyclic (hard rule 5). The BFS runs to exhaustion over
    the reachable component and collects EVERY reachable flow target
    (self-contained at build time — hard rule 4), then the continuation
    target is chosen by preference, in order: (1) the edge's own write
    leg — the flow target whose carried (label, line) matches this
    edge's carried target (the value edge `data_dt@L213 → rrcdm@L211`
    continues to rrcdm, never sup); (2) the bracket rule — the flow
    target with the LARGEST write line <= this edge's carried target
    line (the write lines are the statements' start lines, so the rule
    attributes the edge to its own statement's write target: CTE-
    interior edges of the sup statement continue to sup@160, INSERT
    edges to rrcdm@211), with the smallest write line as fallback (the
    first statement's own write is suppressed from the flow targets —
    its edges continue to the next write downstream). Returns [] when
    the edge's target IS a flow target (the own segment already ends the
    path), when no flow target is reachable, or when there are no flow
    targets — the caller falls back to the pre-R20 reason form (never
    crash, never empty).

    `_reach_memo`: the caller's per-phase BFS cache (see
    `_downstream_bfs`) — None (the default) runs the walk standalone."""
    if e.get("edge_type") in ("SCHEMA", "SUBSET") or not flow_targets:
        return []
    start = e.get("target")
    if not start or start in flow_targets:
        return []
    # BFS to exhaustion — every reachable flow target + the tree parent
    # map (the visited set keeps the walk acyclic).
    reachable, prev = _downstream_bfs(start, flow_targets, adjacency,
                                      _reach_memo)
    if not reachable:
        return []
    chosen = None
    # (1) the edge's own write leg — carried (target label, line) match.
    own_key = (e.get("_tgt_label"), _safe_int(e.get("_tgt_line")))
    if tgt_key_to_target and own_key in tgt_key_to_target:
        candidate = tgt_key_to_target[own_key]
        if candidate in reachable:
            chosen = candidate
    # (2) the bracket rule — the flow target whose write line is the
    # largest write line <= the carried target line; none (the carried
    # line precedes every write line — the first statement, whose own
    # write is suppressed) -> the smallest write line.
    if chosen is None:
        wl = write_line_by_target or {}
        mine = _safe_int(e.get("_tgt_line"))
        candidates = [t for t in reachable if wl.get(t) <= mine]
        if candidates:
            chosen = max(candidates, key=lambda t: wl.get(t, 0))
        else:
            chosen = min(reachable, key=lambda t: wl.get(t, 0))
    path = []
    node = chosen
    while prev.get(node) is not None:
        parent, oe = prev[node]
        path.append(oe)
        node = parent
    path.reverse()
    hops = [(pe.get("_src_label") or "?", _safe_int(pe.get("_src_line")))
            for pe in path]
    hops.append((path[-1].get("_tgt_label") or "?",
                 _safe_int(path[-1].get("_tgt_line"))))
    # Dedup the shared junction hop (the walk's first hop is this edge's
    # target — same node, same carried label).
    if hops and hops[0] == (e.get("_tgt_label"), _safe_int(e.get("_tgt_line"))):
        hops = hops[1:]
    return hops


def _next_anchor_after(line: int, anchor_list: list) -> int:
    """The next statement anchor strictly after `line` (0 = none)."""
    for a in anchor_list:
        if a > line:
            return a
    return 0


def _carry_node_lines(table_nodes: dict, physical_model) -> dict:
    """R11-3 — compound table nodes gain line_start/line_end/defined_in
    from their keeper vars. J12-10 stage 4: the per-var facts ride the
    physical model's occurrence index (context/variable_type/line_start/
    line_end/defined_in for every var — the same universe as the
    full-graph node index, in var order — the derived statement anchors
    are byte-identical to the node-index derivation). line_end = the
    next statement's first-token line − 1 (I1 vars are single-line
    [L,L]; the compound's span is the consumption window ref sites are
    scanned in). Returns the derived statement anchors."""
    occurrences = physical_model.occurrences
    anchors: dict = {}
    for occ in occurrences.values():
        ctx = occ.get("context") or ""
        # a write statement's first token is its DML target var's def
        # line (INSERT at L160/L211 in the flagship); for reads, the
        # minimum non-CTE var line approximates it. CTE DEF vars are
        # excluded — their lines sit at the statement head but the
        # compound's consumption window must start at the statement's
        # actual first token.
        if not ctx.startswith("TOP") or occ.get("variable_type") == "cte":
            continue
        line = _safe_int(occ.get("line_start"))
        if line <= 0:
            continue
        stmt = ctx.split("/", 1)[0]
        anchors[stmt] = min(anchors.get(stmt, 10 ** 9), line)
    max_line = max((_safe_int(o.get("line_start"))
                    for o in occurrences.values()), default=0)
    anchor_list = sorted(anchors.values())
    for tn in table_nodes.values():
        occ = occurrences.get(tn.get("original_id", ""))
        if occ is None:
            continue
        ls = _safe_int(occ.get("line_start"))
        tn["line_start"] = ls
        tn["defined_in"] = occ.get("defined_in", "")
        le = _safe_int(occ.get("line_end"))
        if ls > 0 and le <= ls:
            nxt = _next_anchor_after(ls, anchor_list)
            le = (nxt - 1) if nxt else max_line
        tn["line_end"] = max(le, ls)
    return anchors


def _attach_flow_payload(new_edges: list, field_nodes: list,
                         table_nodes: dict | None = None) -> None:
    """W5/R25 + R20 — the per-edge payload phase: every final L2 edge
    carries highlight_line / flow_kind / reason (highlight_strategies.
    single_line), computed from the edge's carried extraction-time info +
    the FULL source→target path: the upstream closure walk from the
    searched seed's field (_closure_hops over `_closure_bfs`' parent
    maps), the edge's own segment, then the downstream continuation to a
    flow target (_downstream_walk). Never reconstructed at render.

    R20 (build-time path, hard rule 4 — self-contained): flow targets are
    the DML write targets in the seed's closure — the targets of the
    `_dml_origin` write legs present in the FINAL edge list (the value
    edges' output-VT targets are not write targets). The downstream walk
    is a directed BFS over the final FLOW edges (SCHEMA/SUBSET excluded
    — R19.4 exemption) from the edge's target to the reachable flow
    targets, chosen by the own-write-leg match or the bracket rule
    (write lines are the statements' start lines — the edge is
    attributed to its own statement's write target); edges without a
    walkable path keep the pre-R20 reason form.

    PERF (v3.3.194): the upstream walk is ONE multi-source BFS from the
    closure entries over the directed edges plus ONE over the undirected
    fallback (`_closure_bfs` — the per-edge parent maps answer every
    edge's shortest path), and the downstream walk reuses one BFS per
    target node (`_downstream_bfs`'s per-phase memo). Both walks are pure
    functions of the final edge list, so the shared runs are
    byte-identical to the former one-BFS-per-edge form.

    Mutates new_edges in place (attaches _path_hops/_own_seg_idx/
    _tgt_output/_src_output, highlight_line, flow_kind, reason; the
    _-prefixed carriers are stripped at assembly).
    """
    if not new_edges:
        return
    strategy = get_strategy("single_line")
    entries = [fn["id"] for fn in field_nodes if fn.get("is_target")]
    adjacency = {}
    reverse = {}
    for e in new_edges:
        adjacency.setdefault(e["source"], []).append(e)
        reverse.setdefault(e["target"], []).append(e)
    # R20: flow targets (DML write targets in the seed's closure) + the
    # synthetic ⟐ output VTs (the write/read legs' junction; the carried
    # _tgt_is_vt reflects the RAW edge, whose target may still be
    # redirected onto the output — the final-endpoint flags fix that).
    flow_targets = {e["target"] for e in new_edges
                    if e.get("_dml_origin") and not e.get("_value_edge")}
    flow_adjacency = {}
    # (carried target label, line) -> flow-target node, from the write
    # legs — lets an edge continue to ITS OWN write leg (the value edge
    # data_dt@L213 → rrcdm@L211 matches the rrcdm write leg, never sup).
    tgt_key_to_target = {}
    # flow-target node -> its write line (the DML statement's start line)
    # — the bracket rule in _downstream_walk attributes an edge to its
    # own statement's write target.
    write_line_by_target = {}
    for e in new_edges:
        if e.get("edge_type") in ("SCHEMA", "SUBSET"):
            continue
        flow_adjacency.setdefault(e["source"], []).append(e)
        if e.get("_dml_origin") and not e.get("_value_edge"):
            tgt_key_to_target[(e.get("_tgt_label"),
                               _safe_int(e.get("_tgt_line")))] = e["target"]
            write_line_by_target[e["target"]] = _safe_int(e.get("_tgt_line"))
    output_ids = set()
    for tn in (table_nodes or {}).values():
        if (tn.get("table_name") or "").startswith("⟐ output"):
            output_ids.add(tn.get("id"))
    # The two upstream walks, built once: directed (the closure walk is
    # connectivity-based, so the undirected fallback — reverse edges
    # traversed as forward ones, in the same adjacency order — is built
    # only when there is something to walk from).
    prev_dir = _closure_bfs(entries, adjacency) if entries else {}
    if entries:
        undirected = {}
        for node, oes in list(adjacency.items()) + list(reverse.items()):
            undirected.setdefault(node, []).extend(oes)
        prev_und = _closure_bfs(entries, undirected)
    else:
        prev_und = {}
    reach_memo = {}
    for e in new_edges:
        e["_tgt_output"] = e.get("target") in output_ids
        e["_src_output"] = e.get("source") in output_ids
        lbl = e.get("_src_label") or "?"
        lnn = _safe_int(e.get("_src_line"))
        # SCHEMA/SUBSET edges (rules 6/7 — structure/bridge display their
        # own endpoints only) carry no upstream walk.
        up = ([] if (e.get("edge_type") in ("SCHEMA", "SUBSET") or not entries)
              else _closure_hops(e["source"], prev_dir, prev_und,
                                 (e.get("_src_label"), lnn)))
        own = [(lbl, lnn),
               (e.get("_tgt_label") or "?", _safe_int(e.get("_tgt_line")))]
        down = _downstream_walk(e, flow_targets, flow_adjacency,
                                tgt_key_to_target=tgt_key_to_target,
                                write_line_by_target=write_line_by_target,
                                _reach_memo=reach_memo)
        e["_path_hops"] = up + own + down
        e["_own_seg_idx"] = len(up)
        payload = strategy(e)
        e["highlight_line"] = payload["highlight_line"]
        e["flow_kind"] = payload["flow_kind"]
        e["reason"] = payload["reason"]


# ── Field-involvement admission (USER RULING, 2026-08-31) ───────────────
# "only edges where the searched field is involved in the data flow are
#  shown."
#
# The served closure's NODE set is the walker's (`compute_field_flow`) and
# stays untouched — so occurrence coverage never regresses (R44). This
# phase admits/serves EDGES, and it never adds one. Two admission classes,
# both on extraction-time facts already carried per edge:
#
#   Class 1 — JOIN OWN-SITE. A JOIN carrier is served only when its anchor
#     line IS a JOIN-ON line. A collapsed carrier's `defined_in` names the
#     GROUP's clause while the line it carries was handed out in stream
#     order (R45 Fix B / F-E1), so a projection/read line can inherit the
#     group's join-key edge: the ledgered PROJECTION-TWIN-INHERITS-JOIN
#     class (SUP_M lending_ref JOIN carriers anchored at the L82 CASE read
#     and the L163 write projection; the LFS123 doctrine — "a carrier whose
#     line is not the relationship's own site does not earn the anchor").
#     The clause of the line comes from `line_clause_map` — the extractor's
#     own `_line_clauses` machinery, never a text re-derivation here.
#
#   Class 2 — SIBLING-FIELD VALUE LEGS. A value leg of a NON-searched field
#     is that sibling's own flow, not the searched field's: its DML write
#     value leg, its ⟐output-frame membership, its write-projection read
#     leg, and the chain leg into the output frame that its write drives.
#     The searched field's own everything, the belongs-to/structural facts
#     of a sibling chip, and the whole table/VT-level skeleton (CTE/FROM
#     chain legs, write legs — carriers that are not field occurrences)
#     stay, per the accepted FSB/G9 classes.
#
# Mini display-layer version of AD3's value-cone gate (v3.3.195 does the
# full walker version): contained, build-time, no reconstruction — the
# per-edge field identity is read from the carried raw endpoints, the
# carried `defined_in` stamps and the carried `_path_hops` walk.

# The edge types whose leg can BE a value carrier. The row-selection and
# combine families (FILTER/INDIRECT/CORRELATED/DML/SET_OP/SUBQUERY) and the
# identity/bridge family are scope/structure facts, never value legs.
_VALUE_CARRIER_TYPES = frozenset({
    "TABLE_FLOW", "REF", "COMPUTED", "TRANSFORM", "AGGREGATE", "WINDOW",
})

# Class I-4's own switch (2026-09-02), in the `_VALUE_CONE_GATE` shape: the
# switch IS the rule, so the before/after pins flip it and the "before" side is
# the real previous engine.
#
# ON drops a belongs-to whose source instance sits outside the target
# occurrence's own scope whenever some other source of the SAME occurrence
# sits in it (`p1.charge_department@44` — scoped to
# `CTE{rollover_loan_info}/subq1/subq` — claimed by p1@29, p1@84 AND p1@198).
#
# OFF (shipped default) keeps the pre-I-4 closure byte-exactly, because the
# canonical ground truth REQUIRES the multi-instance renderings this rule
# drops: jaccard_canonical G8 ("one belongs-to per in-scope p1 alias
# instance", rows LFS130/LFS141/LFS142 for `lending_ref`@41/@163 and the
# LFS126 pairing) and the `bdm` SUP_M rows S3 (`p1@84 -> p1.data_dt@43`) and
# MA1 (`p1@29 -> data_dt@158`) are the same wrong-scope shape this rule
# refuses. Turning it ON costs exactly two benchmark cases
# (lending_ref↓SUP_M edges recall 0.9032, bdm↓SUP_M 0.9310; precision stays
# 1.0000) until those rows are re-derived — a jaccard_canonical.py edit this
# team does not own. The audit's I-4 class and the canonical's G8 ruling
# cannot both hold; the user rules on the ground truth.
_OWN_SCOPE_BELONGS_TO = False


def _apply_field_involvement(new_edges: list, field: str,
                             relevance_filter: bool,
                             physical_model=None,
                             sql_text: str = "",
                             table: str = "") -> list:
    """Serve only the closure edges the searched field is involved in.

    No-op when no search filter is active (the full view has no searched
    field to be involved). Pure edge filter over the already-payloaded
    list — order, ids and every carried field are preserved, so the pass
    is deterministic by construction.

    `table` (F1, 2026-09-02) is the searched TABLE: it turns the
    seed-endpoint exemption from a NAME match into an OCCURRENCE identity
    (the searched `table.field`), which is what makes the Class-3
    belongs-to drop reachable for a sibling that shares the searched
    field's name. Empty (the legacy signature) ⇒ no ownership evidence ⇒
    the legacy field-part behaviour stands.

    ── The I-batch (2026-09-02, the 557-pair SUP_M+PL classification sweep)
    ──────────────────────────────────────────────────────────────────────
    Four further illegal classes, all inside this pass's post-processing:

      Class I-1 — the sibling PARTITION write carrier. A routed DML write
        leg is the writing statement's own skeleton, but its carried OWN
        segment is whatever written-column occurrence the raw DML edge was
        minted from — on a PARTITIONed INSERT that is the static partition
        key (`‖data_dt@L19 → bdm_acc_loan_info@L19‖` served under the
        ABROAD_LOAN_PURPOSE search). 7-A rule 2 keeps the leg (the
        statement writes the searched column), so this is a CARRIER
        RE-PICK, never a drop: the segment is re-picked to the box hop the
        leg IS (`‖⟐ output@19 → bdm_acc_loan_info@19‖` — the EAST5 form),
        while the searched column's own leg keeps its own hop. Serve-time
        only: `_src_label`/`_src_line` stay the extraction truth they were,
        the SERVED walk and its reason are what get re-picked (no cache, no
        EXTRACTOR_VERSION move).

      Class I-2 — the join-key co-operand. Searching one operand of a
        `‖`/CONCAT/LPAD key served the OTHER operands' JOIN legs
        (`a.acb` → `‖a.ctcd@L250 → ⟐output@L19‖`). Canonical class X1
        (R46c): the searched field sits on ONE side of the `=`, so an
        operand chip is that operand's own flow — rule 3b, dropped.

      Class I-3 — the sibling AND-leg of the same JOIN (`cb_pointer` →
        `‖p2.rn@L249 → ⟐output@L19‖` on
        `ON a.acnw = p2.arrangement_local_number AND p2.rn = 1`). Rule 4b:
        a sibling leg's line stays dark. Both I-2 and I-3 are the ONE test
        at the Class-1 site: a JOIN leg whose OWN carried segment is a
        FIELD occurrence of another name is that sibling's flow.

      Class I-4 — the wrong-scope belongs-to. Duplicate alias names in one
        script (p1 ×3, p2 ×3) made the fold attribute a chip's belongs-to
        to EVERY same-named instance instead of the occurrence's own scope
        instance (`p1.charge_department@44` — scoped to
        `CTE{rollover_loan_info}/subq1/subq` — was claimed by p1@29, p1@84
        AND p1@198). Rule 5e extended across CTE scopes: when some
        belongs-to source sits in the target occurrence's OWN scope, the
        sources that do not are the fold's duplicates and drop. No
        same-scope source ⇒ no scope evidence ⇒ nothing drops (the
        container shape — a CTE box declaring its own column — has no
        same-scope instance by construction and keeps its edge). SHIPPED
        BEHIND `_OWN_SCOPE_BELONGS_TO` (below, default OFF): the canonical's
        own G8 rows require the multi-instance renderings, so the drop
        waits on that ground truth being re-derived.
    """
    if (not new_edges) or (not relevance_filter) or not (field or "").strip():
        return new_edges
    seed = field.strip().casefold()
    table_key = (table or "").strip().casefold()

    # Raw occurrence index (label, line) → variable_type, for the one test
    # the carried endpoints cannot answer: is this upstream hop a FIELD
    # occurrence (a value carrier) or a table/VT chip (skeleton)? Missing
    # model ⇒ never a carrier ⇒ the edge is admitted, never dropped.
    occ_kind = {}
    if physical_model is not None:
        for _o in physical_model.occurrences.values():
            occ_kind[(_o.get("name") or "", _safe_int(_o.get("line_start")))] = \
                _o.get("variable_type")

    def _part(label):
        return (label or "").rsplit(".", 1)[-1].strip().casefold()

    # ── Own-segment facts, read once from the carried payload ───────────
    # The skeleton fallback used to consult the hop BEFORE the edge's own
    # segment and to declare every edge that does not target the ⟐output
    # frame carrier-less — so a sibling field's value leg (EAST5's
    # `‖a.charge_department@L51 → stzfdxzh@L53‖`) and a foreign statement's
    # whole write/read plumbing (EAST5's `‖⟐ output@L179 →
    # rrcdm_job_log_exec_par@L179‖` job-log trunk) were admitted as
    # "skeleton". The edge's OWN carried segment is the evidence:
    #
    #   `_own_seg_idx` — the index of the segment's own source hop in the
    #     carried walk (`_path_hops[idx]` IS the carried
    #     `(_src_label, _src_line)`); a MISSING index is NO segment
    #     evidence, not hop 0 (hop 0 is a segment of its own);
    #   the segment source's OCCURRENCE KIND — a FIELD occurrence drives a
    #     value leg, a table/CTE/VT chip drives the box skeleton;
    #   the segment target's ⟐output frame and write box, resolved at
    #     STATEMENT level — a frame is the searched field's own when the
    #     statement it belongs to WRITES the searched column, and the
    #     written box is the searched field's own write target; a box leg
    #     into any other frame is another statement's plumbing (§7-A
    #     corollary: the job-log statement writes literals and COUNT(1),
    #     never the searched field). Never line-vs-line: the write leg's
    #     carried target line is the WRITE TARGET'S keeper occurrence
    #     (RFN: 768/1168), and the frames are compound keepers whose line
    #     is one statement's (RFN: 867 vs 1429) — comparing lines compares
    #     different statements by construction.
    #
    # ── THE occurrence identity (F1, 2026-09-02) ────────────────────────
    # ONE definition of "is this chip the SEARCHED field's own?" for every
    # STRUCTURE question this pass asks — today that is Class 3's
    # `_own_belongs_to`, the branch F1 landed it in. The pass's VALUE
    # questions (the seed-endpoint exemption, the 7-A write-leg/frame
    # evidence, the feeder set) are deliberately COLUMN-level, each with its
    # ruling-backed reason at its own site below; they used to sit next to
    # the identity with NOTHING marking the difference, which read as one
    # rule answering two questions. Measured (HEAD vs this tree, hash-seed
    # pinned, 21 acceptance closures): keeping the value sites name-level
    # moves 0 served edges, while identity-narrowing them costs canonical
    # ground-truth rows — DL × lending_ref upstream and the bdm seed on
    # SUP_M (the details are at each site).
    #
    # The identity is the searched `table.field`: the chip's part must be
    # the searched field, and its RESOLVED OWNER must be the searched table
    # (`_tgt_canon` for a belongs-to target — the extractor's own I2
    # source-table resolution). Three provisos, all extraction-time facts:
    #   no owner evidence (no searched table — the legacy unit-test shapes —
    #     or an ownerless chip) ⇒ own: never drop on missing evidence;
    #   a LITERAL chip owns nothing (its `source_tables[0]` is the box the
    #     constant is written into — a write target, never an owner), so it
    #     is never a foreign column of the searched name;
    #   a foreign-owned same-named COLUMN is STILL the searched value
    #     carried through a container (a CTE/VT/derived column) while it is
    #     not a written column of its own — a chip the statement writes
    #     under its own name is a second column of that name, a sibling
    #     (the F1 written-chip proviso).
    written_chips = {e.get("source") for e in new_edges
                     if e.get("_value_edge") and e.get("_tgt_output")}

    def _own_occurrence(part, owner, chip_id, column=True):
        if part != seed:
            return False
        owner = (owner or "").strip().casefold()
        if not table_key or not owner or owner == table_key:
            return True
        if not column:
            # a constant projection carries no column ownership at all: the
            # extractor puts the box the constant is written INTO in its
            # `source_tables`, which is a write target, never an owner — so
            # there is no foreign column here to be a sibling of (7-A rule
            # 1's own case: `'$(load_date)' AS data_dt` writes the searched
            # column as a literal).
            return True
        return chip_id not in written_chips

    # The write projection a statement publishes is read off the carried
    # chips: the value edges' own source chip IS the written value, and the
    # searched column counts as written when that chip is the searched
    # column or a chip the searched value flows into (RFN's L877 projections
    # are `SUBSTRING(A.CUST_NO, …)` expression chips — not seed-labelled,
    # but the closure carries the searched chip's own REFERENCE edges INTO
    # them). The written BOX is the value edge's `_tgt_canon`.
    #
    # This set is deliberately keyed at the COLUMN level (7-A is a ruling
    # about the column being written: "when the SEARCHED field is the column
    # being WRITTEN by a statement, its write edge SHOWS"), never narrowed
    # to the occurrence identity — the write-target evidence feeds the
    # carve-out that keeps the searched column's own write legs served
    # (RFN's @768/@1168 legs into bdm_acc_loan_info), and a name-level
    # column read is what that evidence is.
    seed_value_chips = set()
    for _c in new_edges:
        _hops = _c.get("_path_hops") or []
        _idx = _safe_int(_c.get("_own_seg_idx"))
        if _idx is None or not (0 <= _idx < len(_hops)):
            continue
        if _part(_hops[_idx][0]) != seed:
            continue
        seed_value_chips.add(_part(_c.get("_tgt_label")))

    def _seed_written(e):
        """True when the value edge writes the searched column's own value
        (its written chip is the searched column, or a chip the searched
        value flows into — RFN's `SUBSTRING(A.CUST_NO, …)` expression chips
        are not seed-labelled, but the closure carries the searched chip's
        own REFERENCE edges INTO them). The written BOX is the value edge's
        `_tgt_canon`; the frame it lands on is the ⟐output frame the edge
        targets.

        DELIBERATELY COLUMN-level, exactly as wide as 7-A's own wording —
        "when the SEARCHED field is the column being WRITTEN by a statement,
        its write edge SHOWS" — and this ONE test feeds both 7-A consumers:
        `seed_write_targets` (which boxes the searched column is written
        into) and `own_frame_keys` (which ⟐output frames are the searched
        field's OWN frames, the §7-A statement-level frame test). Narrowing
        it to the occurrence identity `_own_occurrence` was MEASURED and
        REJECTED: the identity calls a foreign-owned same-named chip a
        sibling, which strips the frame status from the write frames the
        canonical ground truth needs — DL × `lending_ref` upstream
        (`acctnbr AS lending_ref`, an ods_ccb_cb_loan_acctloan chip, anchors
        ⟐output@99) and the bdm seed on SUP_M (`data_dt@160`, a
        bdm_acc_loan_info_sup chip, anchors ⟐output@160) both lose canonical
        rows. The RESIDUAL is real and is the FINDING-1 frame-identity
        class: on RFN × `ods_gdc_split_fg_rating_temp.cust_no` the
        column-level rule also admits `A.CUST_NO@1178` — a `bdm_acc_loan_info`
        chip the merge-back statement writes under its own name — so the
        job-log statement's ⟐output@1429 frame counts as own.
        `test_frame_is_own_only_when_a_value_edge_lands_the_searched_column`
        and `test_rfn_write_legs_stay_served_and_job_log_stays_dark` pin the
        two sides of that decision that today's engine owns."""
        _p = _part(e.get("_src_label"))
        return _p == seed or (_p and _p in seed_value_chips)

    seed_write_targets = {(e.get("_tgt_canon") or "").strip().casefold()
                          for e in new_edges
                          if e.get("_value_edge") and _seed_written(e)}
    own_frame_keys = {(e.get("_tgt_label"), _safe_int(e.get("_tgt_line")))
                      for e in new_edges
                      if e.get("_tgt_output") and e.get("_value_edge")
                      and _seed_written(e)}
    # The boxes the searched field's own chip is carried between — the
    # admitted feeder boxes: the box owning each chip the segment touches
    # and the box the other endpoint resolves to, taken over every edge
    # whose own segment touches the searched field. A row source that feeds
    # none of them is another column's feeder (EAST5's `e@152`/`f@155` feed
    # the stzfdx* columns only), and its alias hop and row chain are that
    # column's flow, not the searched field's. A box that PRODUCES the
    # searched field's own value at box level counts too (DL's
    # `ods_ccb_cb_loan_acctloan@426 → LENDING_REF@101` projection): the
    # production leg's source chip is the BOX there, so the own hop's kind
    # is deliberately not consulted.
    feeders = set()
    for _c in new_edges:
        _hops = _c.get("_path_hops") or []
        _idx = _safe_int(_c.get("_own_seg_idx"))
        if _idx is None or not (0 <= _idx < len(_hops)):
            continue
        # The FEEDER set is deliberately NOT occurrence-identity keyed — it
        # stays on the field NAME. It is the set of BOXES the searched
        # field's own value is carried between, and a box that PRODUCES the
        # searched field's own value counts through the chip it produces
        # (EAST5 × charge_department: the partition column's value IS
        # `a.charge_department`, a bdm_acc_entrusted_payment chip, so its
        # box `a@141` stays the admitted feeder; DL's
        # `ods_ccb_cb_loan_acctloan@426 → LENDING_REF@101` likewise) — a
        # question the producing chip's ownership cannot answer. Identity
        # lives in the SEGMENT/FRAME tests, not here.
        if seed not in (_part(_hops[_idx][0]), _part(_c.get("_tgt_label"))):
            continue
        feeders.add((_c.get("_src_owner") or "").strip().casefold())
        feeders.add((_c.get("_tgt_canon") or "").strip().casefold())

    def _own_hop(e):
        """The edge's OWN carried segment source — `_path_hops[_own_seg_idx]`,
        the same (label, line) the edge carries as `(_src_label, _src_line)`.
        None when the walk carries no segment index (no evidence)."""
        hops = e.get("_path_hops") or []
        idx = _safe_int(e.get("_own_seg_idx"))
        if idx is None or not (0 <= idx < len(hops)):
            return None
        return hops[idx]

    def _up_hop(e):
        """The hop the closure walk arrives THROUGH — the last hop before
        the edge's own segment. Class 2's chain-leg test: a box-level row
        source the walk reaches through another field's value is the chain
        leg that sibling's write drives."""
        hops = e.get("_path_hops") or []
        idx = _safe_int(e.get("_own_seg_idx"))
        if idx is None or not (1 <= idx < len(hops)):
            return None
        return hops[idx - 1]

    def _hop_is_field(lbl, lnn):
        """Field vs box chip, keyed on the walker's own occurrence index.
        No index (no physical model) ⇒ None: nothing may drop on an
        unknown kind."""
        kind = occ_kind.get((lbl, _safe_int(lnn)))
        return None if kind is None else kind in FIELD_LIKE_TYPES

    def _box_id_of_owner(owner):
        return (owner or "").strip().casefold()

    def _own_segment_carrier(e):
        """The field occurrence that DRIVES the edge's own carried segment
        — read off the segment itself, never off the hop before it and
        never off the display endpoints. Returns the driving part (the
        seed ⇒ involved, anything else ⇒ that sibling's flow) or None when
        the segment is the searched field's own box skeleton.

        A FIELD-driven segment is the searched field's own flow only when
        its driving occurrence IS the searched field. Otherwise it is a
        sibling's value leg — §7-A corollary: a statement whose written
        columns are other fields' values contributes nothing to the
        searched field — with ONE exception, the routed DML write leg: the
        writing statement's own skeleton, kept when the statement is the
        one whose ⟐output frame carries the searched field's own written
        value (7-A rule 1, EAST5's `PARTITION(p_dt, charge_department)`
        write leg @41 stays under the `BBZ` search), dropped when it is
        another statement's write (`‖⟐ output@L179 →
        rrcdm_job_log_exec_par@L179‖` — the job-log trunk writes literals
        and COUNT(1), never the searched field).

        No occurrence index ⇒ no occurrence-kind evidence ⇒ nothing drops
        here (the documented legacy contract stands).
        """
        if not occ_kind:
            return None
        own = _own_hop(e)
        if own is None:
            return None
        lbl, lnn = own
        field = _hop_is_field(lbl, lnn)
        if field is None:
            # no occurrence entry for the chip: the edge's own
            # extraction-time stamp is the same classification
            field = bool(e.get("_src_field_like"))
        if not field:
            return _box_skeleton_carrier(e)
        part = _part(lbl)
        # The VALUE-flow half of the same-named-chip question stays at the
        # field NAME on purpose: a same-named chip that the statement also
        # writes under its own name is a SIBLING for the STRUCTURE question
        # (Class 3's `_own_belongs_to` drops its belongs-to), but its value
        # still IS the searched field's own value when the searched column
        # is produced from it (EAST5 × charge_department: the partition
        # column's value IS `a.charge_department`, a bdm_acc_entrusted_payment
        # chip — its reads, filters and computes are this seed's provenance,
        # which is what keeps that closure at the audited 32). The identity
        # decides the STRUCTURE question (Class 3, above); the value flow is
        # the walker's own closure, already occurrence-covered (R44).
        if part == seed:
            return part
        if e.get("_dml_origin") and not e.get("_value_edge"):
            _box = (e.get("_tgt_canon") or "").strip().casefold()
            if seed_write_targets and _box not in seed_write_targets:
                return _part(e.get("_tgt_label")) or part
            return None
        return part

    def _box_skeleton_carrier(e):
        """A leg whose own segment's source is a table/CTE/VT chip — the
        box-level skeleton. KEPT (None) only as the searched field's own
        skeleton; otherwise the carrier is the box the leg belongs to, and
        the leg drops:
          a row-source chain is not the searched field's when the closure
            walk reaches it THROUGH another field's value (the Class-2
            chain leg that sibling's write drives — `‖p1@L198 →
            ⟐ output@L160‖` arrives through `p1.reserved_field8@L183`),
          when it feeds an ⟐output frame the searched field's own written
            value never lands on (`‖east5_stzfxxb@L189 → ⟐ output@L179‖`:
            p_dt's own frame is ⟐ output@L41), or
          when its box feeds none of the searched field's own occurrences
            (`‖e@L152 → ⟐ output@L41‖`/`‖f@L155 → …``: e and f feed the
            stzfdx* columns only, `a@141` feeds the BBZ arms)."""
        own = _own_hop(e)
        if own is None:
            return None
        # the routed DML write leg is the writing statement's own skeleton
        # when that statement writes the searched column into the box the
        # leg names (STATEMENT level — never the write target's keeper line)
        if e.get("_dml_origin") and not e.get("_value_edge"):
            _box = (e.get("_tgt_canon") or "").strip().casefold()
            if seed_write_targets and _box not in seed_write_targets:
                return _part(e.get("_tgt_label")) or _part(own[0])
            return None
        # the chain leg another field's write drives (Class 2)
        up = _up_hop(e)
        if up is not None:
            up_field = _hop_is_field(up[0], up[1])
            if up_field and _part(up[0]) != seed:
                return _part(up[0])
        # an ⟐output frame whose statement writes nothing of the searched
        # column (RFN's two bdm_acc_loan_info frames are both own; EAST5's
        # ⟐output@179 job-log frame is not)
        if own_frame_keys and e.get("_tgt_output"):
            if (e.get("_tgt_label"), _safe_int(e.get("_tgt_line"))) not in own_frame_keys:
                return _part(e.get("_tgt_label")) or _part(own[0])
        # the box that feeds none of the searched field's own occurrences
        box = _box_id_of_owner(e.get("_src_owner"))
        if box and feeders and box not in feeders:
            return box
        return None

    def _bridge_box_carrier(e):
        """The identity hop / bridge (ALIAS/SUBSET) — the skeleton of the
        box it NAMES. Kept (None) when that box feeds the searched field's
        own occurrences (`‖bdm_acc_entrusted_payment@L141 → a@L141``: a's
        columns are the BBZ arms), dropped as another column's skeleton
        when it does not (`‖BDM_ACC_INTERNAL_COUNTERPARTY@L152 → e@L152``
        and `‖v_bdm_sys_ftpsje_jydsf@L155 → f@L155`` — those tables feed
        the stzfdx* columns only). No feeder evidence ⇒ nothing drops."""
        if not feeders:
            return None
        box = _box_id_of_owner(e.get("_tgt_canon"))
        if box and box not in feeders:
            return box
        return None

    def _is_write_projection(e):
        """True when the raw SOURCE occurrence is a write projection's
        value (`SELECT expr` — the extraction-time clause stamp), i.e. the
        value the statement writes. A row-selection sibling's read leg
        (`JOIN ON`/`WHERE`/`GROUP BY` …) is structure, not a value leg."""
        return ((e.get("_src_defined_in") or "").strip().upper()
                .startswith("SELECT"))

    # ── F1/F2 facts, read once from the carried payload ─────────────────
    # (`written_chips` is read once ABOVE, beside the occurrence identity
    # that consults it.) The boxes the closure's write legs land on (the DML
    # write targets, carried on the routed ⟐output → target leg — never the
    # value legs, whose target is the ⟐output frame itself):
    write_targets = {(e.get("_tgt_label") or "").rsplit(".", 1)[-1]
                     .strip().casefold()
                     for e in new_edges
                     if e.get("flow_kind") == "write" and not e.get("_value_edge")
                     and e.get("_tgt_label")}
    # F2's guard: does the statement write the searched field's own COLUMN?
    # A write value leg whose source chip stands ON a write target — the
    # searched field is a column of the written box itself (the §7-A "the
    # searched field is the column being written" case: EAST5's
    # `PARTITION(…, charge_department)` @41, SUP_M's `data_dt` @213). When
    # it does, the statement's other columns are siblings and their write
    # legs stay out (the §7-A boundary). A source chip on the READ side
    # (the searched source table) is not that: its value is only on its way
    # out, under whatever output column carries it.
    own_write = any(e.get("_value_edge") and e.get("_tgt_output")
                    and _part(e.get("_src_label")) == seed
                    and (e.get("_src_owner") or "").strip().casefold()
                    in write_targets
                    for e in new_edges)
    # F2: the AS-alias / output-column frames whose value IS the searched
    # field's own. Three extraction-time facts, all carried:
    #   provenance — a value-carrying edge runs FROM the searched field's
    #     own chip INTO the frame (the frame's producing expression reads
    #     the searched field: the `TRANSFORM/COMPUTED field→alias` edge the
    #     closure already serves);
    #   the frame is the WRITE TARGET'S own column (its resolved owner is
    #     the box the statement writes) — so the leg writes that value out,
    #     it does not carry a foreign column's;
    #   the statement does not ALSO write a column of the searched field's
    #     own on the written box (`own_write` False) — when it does, the
    #     frame is one of the statement's OTHER columns and its legs stay
    #     the sibling's flow (the §7-A boundary).
    own_frames = set()
    if not own_write:
        for e in new_edges:
            if (e.get("edge_type") or "") not in _VALUE_CARRIER_TYPES:
                continue
            if _part(e.get("_src_label")) != seed:
                continue
            if table_key:
                owner = (e.get("_src_owner") or "").strip().casefold()
                if owner and owner != table_key:
                    continue
            fcanon = (e.get("_tgt_canon") or "").strip().casefold()
            if not fcanon or fcanon not in write_targets:
                continue
            own_frames.add(e.get("target"))

    def _own_belongs_to(e, tgt_part):
        """Class 3's exemption: is this belongs-to edge the SEARCHED
        FIELD'S OWN? (F1, 2026-09-02 — the seed-endpoint check is an
        OCCURRENCE identity, never a name match.)

        A name match admits the belongs-to of a SIBLING that merely shares
        the searched field's name (EAST5 `charge_department`: the source
        table's own `bdm_acc_entrusted_payment.charge_department` reads,
        one per read line, alongside the searched `east5_stzfxxb.
        charge_department`). The identity the search names is
        `table.field`, so the target occurrence's RESOLVED OWNER —
        `_tgt_canon`, the extractor's own I2 source-table resolution —
        must be the searched table.

        A same-named chip that is NOT owned by the searched table is still
        the searched field's own while it is not a written column of its
        own: it is the searched value carried through a container (a
        CTE/VT/derived column — SUP_M's `rollover_loan_info`/`loan_final`
        lending_ref chips, the canonical's LFS8/9/38/74/104/134/139-142),
        and its belongs-to is the searched field's structural fact (the
        R40.12/R44 Reappears class). A same-named chip the statement ALSO
        writes under its own name IS a second column of that name — a
        sibling — and its belongs-to is the sibling's own fact (the 3a
        ruling). No carried owner (the legacy unit-test shapes) ⇒ the
        legacy field-part behaviour stands: never drop on missing
        extraction-time evidence."""
        # the target-side evidence corrections: `_tgt_canon` falls back to
        # ECHOING the chip's own label when the extractor resolved nothing —
        # an echo is no ownership evidence, never a foreign owner — and a
        # LITERAL chip owns nothing at all (its `source_tables[0]` is the box
        # the constant is written INTO).
        canon = (e.get("_tgt_canon") or "").strip().casefold()
        if canon and canon == tgt_part:
            canon = ""
        return _own_occurrence(tgt_part, canon, e.get("target"),
                               column=e.get("_tgt_vt") != "literal")

    clauses = line_clause_map(sql_text)
    # ── Class I-4 evidence: which belongs-to targets have a source in the
    # target occurrence's OWN scope. Read off the CARRIED contexts (the
    # extraction-time scope of each raw endpoint node) before anything is
    # dropped, so the evidence is the whole closure's and not whatever
    # survived an earlier branch. The group is the TARGET OCCURRENCE — the
    # (label, line) pair the walker's occurrence index is keyed on — never
    # the folded display node: the fold maps several scopes' chips onto one
    # node, and a same-scope instance of ONE of them is no evidence about
    # the others. A target whose every source sits elsewhere carries no
    # scope evidence at all — nothing may drop on it (the container shape:
    # `‖rollover_loan_info@L9 → lending_ref@L13‖` has no same-scope
    # instance, because the CTE box's def site lives in the ENCLOSING scope
    # while its columns live in the CTE's own).
    own_scope_targets = set()
    for _b in new_edges:
        if (_b.get("edge_type") or "") != "SCHEMA":
            continue
        if ((_b.get("_op") or "").upper() == "OUTPUT"):
            continue
        _tctx = (_b.get("_tgt_ctx") or "").strip()
        _sctx = (_b.get("_src_ctx") or "").strip()
        if _tctx and _sctx and _sctx == _tctx:
            own_scope_targets.add(((_b.get("_tgt_label") or "").strip().casefold(),
                                   _safe_int(_b.get("_tgt_line"))))

    kept = []
    for e in new_edges:
        etype = e.get("edge_type") or ""
        # ── Class 1: the JOIN carrier's own site ──
        if etype == "JOIN":
            anchor = _safe_int(e.get("highlight_line")) or 0
            if anchor >= 1 and clauses.get(anchor) != "on":
                continue
            # ── Classes I-2 / I-3 (2026-09-02): the leg's OWN carried
            # segment. An ON line is the relationship's own site, but a leg
            # of that relationship is still not the searched field's flow
            # when its own segment is a FIELD occurrence of another name:
            #   I-2 — the other operand of the searched field's key
            #     (`a.acb` → `‖a.ctcd@L250 → ⟐output@L19‖`; canonical X1,
            #     the searched field sits on ONE side of the `=`), and
            #   I-3 — a sibling AND-leg of the same JOIN (`cb_pointer` →
            #     `‖p2.rn@L249 → …‖` on `… AND p2.rn = 1`; rule 4b, a
            #     sibling leg's line stays dark).
            # A BOX-carried own segment (the row-source skeleton, 6d) and a
            # missing segment (no model / no walk) are NOT evidence — the
            # legacy contract stands, nothing drops on an unknown kind.
            _own = _own_hop(e)
            if _own is not None:
                _fld = _hop_is_field(_own[0], _own[1])
                if _fld is None:
                    _fld = bool(e.get("_src_field_like"))
                if _fld and _part(_own[0]) != seed:
                    continue
            kept.append(e)
            continue
        src_part = _part(e.get("_src_label"))
        tgt_part = _part(e.get("_tgt_label"))
        op = (e.get("_op") or "").upper()
        # ── Class 3: the sibling belongs-to drop, BEFORE the seed-endpoint
        # check. It must run first (F1): the seed-endpoint exemption used
        # to be a NAME match that fired first, so a sibling sharing the
        # searched field's name was admitted as "seed endpoint" and the 3a
        # drop was unreachable for it. The exemption is now the occurrence
        # identity in `_own_belongs_to`.
        if etype == "SCHEMA" and op != "OUTPUT":
            if not _own_belongs_to(e, tgt_part):
                continue
            # ── Class I-4 (2026-09-02): the occurrence's OWN scope instance.
            # Gated on `_OWN_SCOPE_BELONGS_TO` (module level, default OFF —
            # the canonical's G8 rows require these renderings; see there).
            # The fold hands a chip's belongs-to to EVERY same-named
            # instance (`p1.charge_department@44`, scoped to
            # `CTE{rollover_loan_info}/subq1/subq`, was claimed by p1@29,
            # p1@84 AND p1@198); rule 5e across CTE scopes says the
            # belongs-to's source must be the occurrence's own instance.
            # The extraction-time contexts are that test: when some source
            # of the same chip sits in the target occurrence's own scope,
            # a source that does not is a fold duplicate. No same-scope
            # source ⇒ no evidence ⇒ the edge stays.
            _tctx = (e.get("_tgt_ctx") or "").strip()
            _sctx = (e.get("_src_ctx") or "").strip()
            if (_OWN_SCOPE_BELONGS_TO and _tctx and _sctx and _sctx != _tctx
                    and ((e.get("_tgt_label") or "").strip().casefold(),
                         _safe_int(e.get("_tgt_line"))) in own_scope_targets):
                continue
            kept.append(e)
            continue
        # ── Class 2: is the searched field involved? ──
        # The seed chip / a same-name copy. Deliberately the field NAME, not
        # the occurrence identity: this is the VALUE-flow half of the
        # same-named-chip question, and a same-named chip is the searched
        # value's carrier whenever the searched column is produced from it —
        # EAST5 × charge_department (the partition column's value IS
        # `a.charge_department`, a bdm_acc_entrusted_payment chip) and
        # DL × lending_ref upstream (`acctnbr AS lending_ref`, an
        # ods_ccb_cb_loan_acctloan chip) are canonical ground truth rows.
        # Narrowing THIS test to `_own_src`/`_own_target` was measured and
        # rejected: it costs the DL upstream row. The identity answers the
        # STRUCTURE question (Class 3 above); the value flow is the walker's
        # own closure, already occurrence-covered (R44).
        if seed in (src_part, tgt_part):
            kept.append(e)
            continue
        # ── F2: the searched field's own value leg routed through an
        # AS-alias / output-column frame. The frame's ⟐output legs are the
        # WRITE VALUE leg (`_value_edge`) and the frame's membership
        # (SCHEMA `OUTPUT`); when the frame's value is the searched field's
        # own (`own_frames`, above) they ARE the searched field's value
        # chain — cutting them leaves the audited TRANSFORM field→alias …
        # hole … DML shape. A sibling's frame is never in `own_frames`, so
        # its legs keep dropping (reserved_field8's stay dropped).
        if e.get("source") in own_frames or e.get("target") in own_frames:
            kept.append(e)
            continue
        if e.get("_value_edge"):
            carrier = src_part                              # write value leg
        elif etype == "SCHEMA":
            # SCHEMA is structure, with ONE value-leg form: the ⟐output
            # frame's membership of a column. The belongs-to form
            # (`TABLE_COLUMN` — the instance owns the occurrence) USED to
            # stay as "skeleton" (the old rule 3a) — USER RULING
            # 2026-09-01: it does NOT. A sibling's belongs-to edge is not
            # the searched field's flow, and on write-heavy statements it
            # drags every co-written column's chip into the closure as
            # clutter. DROPPED. The sibling chips this leaves floating
            # edge-less are pruned too (`_prune_orphan_sibling_chips`,
            # below) — USER RULING 2026-09-01, confirming the full
            # variant: "If the sibling chips, which is not [the]
            # searched target field, and doesn't have any edge, they are
            # not contributing to the data flow. I think they should be
            # removed." The fact "this column exists on this box"
            # becomes a full-view fact. The searched chip's own
            # belongs-to and the R40.12 Reappears class never reach this
            # branch — the belongs-to form is decided ABOVE (Class 3 +
            # `_own_belongs_to`), never here.
            carrier = tgt_part
        elif etype in ("ALIAS", "SUBSET"):
            carrier = _bridge_box_carrier(e)   # the box it names: skeleton iff a feeder
        elif (etype == "REF" and op == "READ" and _is_write_projection(e)):
            carrier = src_part                              # write value's read leg
        else:
            carrier = _own_segment_carrier(e)   # the edge's OWN carried segment
        # No field carrier ⇒ the table/VT skeleton's own leg (CTE/FROM chain,
        # write leg, belongs-to) — structural, admitted. A carrier that IS
        # the searched field ⇒ involved. Anything else is a sibling's flow.
        if carrier is None or carrier == seed:
            kept.append(e)

    # ── Class I-1: the sibling PARTITION write carrier — a CARRIER RE-PICK.
    # A kept routed write leg names, as its OWN carried segment, the written
    # column occurrence the raw DML edge was minted from. When that
    # occurrence is another column (on PL's PARTITIONed INSERT it is the
    # static partition key `data_dt`@19), the served reason names a sibling
    # column's hop for a leg 7-A keeps BECAUSE the statement writes the
    # searched column. The leg is a box hop — the trunk → write-target hop —
    # so that is what the segment is re-picked to (`‖⟐ output@19 →
    # bdm_acc_loan_info@19‖`, the EAST5 form). The searched column's own
    # write leg keeps its own hop: there the carrier IS truthful.
    #
    # Serve-time only, and only the SERVED walk: `_src_label`/`_src_line`
    # keep the extraction-time facts they carried (which written-column
    # occurrence the DML edge was minted from), the `_path_hops` walk and
    # the reason derived from it are the display projection — so no cache
    # key, no EXTRACTOR_VERSION and no snapshot content set moves. Every
    # edge whose walk renders that segment (the write leg itself, and the
    # value edge whose downstream continuation runs through it) re-renders.
    if kept:
        _seg_renames = []
        for _w in kept:
            if not (_w.get("_dml_origin") and not _w.get("_value_edge")):
                continue
            _own = _own_hop(_w)
            if _own is None or _part(_own[0]) == seed:
                continue
            # already a box-level segment (⟐ output → target): nothing to
            # re-pick; a NON-field segment is the skeleton's own form
            if _hop_is_field(_own[0], _own[1]) is False:
                continue
            # The box hop the leg IS: the walk's own previous hop — the last
            # hop before the segment, which for a routed write leg is the
            # trunk's own (label, line), stamped by J12-18 when the value
            # edge was re-targeted onto it. No walk before the segment
            # (the trunk unreachable from the seed) ⇒ no box evidence ⇒
            # the edge keeps the carrier it had.
            _idx = _safe_int(_w.get("_own_seg_idx"))
            _hops = _w.get("_path_hops") or []
            if not (1 <= _idx < len(_hops)):
                continue
            _lbl, _lnn = _hops[_idx - 1]
            _tlbl = _w.get("_tgt_label")
            _tlnn = _safe_int(_w.get("_tgt_line"))
            if not _lbl or _lnn < 1 or not _tlbl or _tlnn < 1:
                continue
            _seg_renames.append(((_own, (_tlbl, _tlnn)), (_lbl, _lnn)))
        if _seg_renames:
            _strategy = get_strategy("single_line")
            for _e in kept:
                _hops = _e.get("_path_hops") or []
                _new = list(_hops)
                _hit = False
                for _i in range(len(_new) - 1):
                    for (_osrc, _otgt), _nsrc in _seg_renames:
                        if _new[_i] == _osrc and _new[_i + 1] == _otgt:
                            _new[_i] = _nsrc
                            _hit = True
                if not _hit:
                    continue
                _e["_path_hops"] = _new
                _payload = _strategy(_e)
                _e["highlight_line"] = _payload["highlight_line"]
                _e["flow_kind"] = _payload["flow_kind"]
                _e["reason"] = _payload["reason"]
    return kept


def _prune_orphan_sibling_chips(field_nodes: list, kept_edges: list,
                                field: str) -> list:
    """USER RULING 2026-09-01 (confirming the full variant of the rule-3a
    reversal): "If the sibling chips, which is not [the] searched target
    field, and doesn't have any edge, they are not contributing to the
    data flow. I think they should be removed." A field chip is pruned
    when it is NOT the searched field's own (label part != the searched
    field, not the R46a `is_target` stamp) and touches NO kept edge —
    a chip the searched field's own flow still feeds survives (e.g.
    SUP_M's `reserved_field8`, fed by lending_ref's L82 COMPUTED).
    Table/VT compounds are skeleton and never pruned here. Runs after
    the field-involvement edge filter and before roles/assembly, so
    flow_node_ids, the merged view and the Field Story all see the same
    narrowed node set."""
    seed = (field or "").strip().casefold()
    if (not field_nodes) or not seed:
        return field_nodes
    live = set()
    for e in kept_edges:
        live.add(e.get("source"))
        live.add(e.get("target"))
    kept = []
    for fn in field_nodes:
        part = (fn.get("label") or "").rsplit(".", 1)[-1].strip().casefold()
        if part == seed or fn.get("is_target") or fn.get("id") in live:
            kept.append(fn)
    return kept


def _prune_orphan_boxes(table_nodes: dict, kept_edges: list, field_nodes: list,
                        field: str, table: str) -> dict:
    """The 3a ruling's BOX half (USER RULING, same intent — "siblings that
    are not contributing to the data flow should be removed"): a non-seed
    BOX whose every edge the involvement rule just dropped leaves the
    flow-only view with them, exactly like the edge-less sibling chip
    `_prune_orphan_sibling_chips` removes. EAST5's `rrcdm_job_log_exec_par`
    (the job-log statement writes nothing of the searched field, so its
    trunk and its read-side chain both drop) and SUP_M's `p2@199` were
    served as edge-less boxes.

    KEPT: every box a kept edge still touches; the searched table's own
    keeper (`table`); and the holder of the searched field's surviving
    chips — a box is never pruned out from under a chip that stays."""
    seed = (field or "").strip().casefold()
    table_key = (table or "").strip().casefold()
    if (not table_nodes) or not seed:
        return table_nodes
    live = set()
    for e in kept_edges:
        live.add(e.get("source"))
        live.add(e.get("target"))
    holders = {fn.get("parent") for fn in (field_nodes or [])
               if fn.get("parent")}
    # table_nodes is keyed by the RAW node id while the edges and the
    # field chips' parent name the compound's L2 keeper id — compare BOTH
    # (the same split `_attach_flow_roles` documents).
    kept = {}
    for nid, tn in table_nodes.items():
        l2_id = tn.get("id")
        name = (tn.get("table_name") or tn.get("label") or "").strip().casefold()
        if (nid in live or l2_id in live or l2_id in holders or nid in holders
                or (table_key and name == table_key)):
            kept[nid] = tn
    return kept


def _attach_flow_roles(new_edges: list, table_nodes: dict, id_map: dict,
                       full_graph: dict, table: str, field: str,
                       relevance_filter: bool,
                       physical_model=None,
                       direction="downstream",
                       _flow_memo=None) -> None:
    """Phase 10.5 (CW4, Wave 2): R19.1/R19.2/R19.5 flow roles on table
    nodes — additive node-data fields from extraction-time helpers
    (never at render). Filtered view: exactly one flow source (the
    searched seed's table keeper) + every DML write target in the seed's
    flow closure. Full view (no search): net-flow role per PHYSICAL
    table compound (CTE/derived/VT compounds stay neutral).

    J12-10 stage 3: flow_source_id/flow_targets resolve through the
    physical model (required).

    R29 (2026-08-12): upstream flips the roles — the searched table's
    WRITE instances (its DML write targets in the upstream closure) are
    the flow TARGETS (the writing flow ends at the write); the producing
    tables (the closure's table-like vars that are not the searched
    table's own instances — the identity-gated leg sources and their
    holders) are the flow SOURCES.

    The table_nodes dict is keyed by RAW node id; the compound keepers'
    L2 ids (tn["id"], the l2_tbl_* ids the edges and the response use)
    are the values — look up through them, never the dict keys.
    """
    l2_tn = {tn["id"]: tn for tn in table_nodes.values()}
    if relevance_filter:
        if direction == "upstream":
            closure = compute_field_flow(full_graph, table, field,
                                         physical_model=physical_model,
                                         direction="upstream",
                                         _flow_memo=_flow_memo)
            if closure:
                # Flow targets: the searched table's DML write targets in
                # the upstream closure — mirror of the seed selection
                # (non-WRITE_READ DML edges whose target entity is the
                # searched table).
                up_tgt = set()
                for M in physical_model.edges:
                    if M.edge_type != "DML":
                        continue
                    if (M.operation or "").upper() == "WRITE_READ":
                        continue
                    if M.target_id not in closure:
                        continue
                    tgt_tbl = (physical_model.tables.get(M.target[0])
                               if M.target[0] else None)
                    if tgt_tbl is not None and tgt_tbl.name == table:
                        up_tgt.add(M.target_id)
                for rid in up_tgt:
                    kid = id_map.get(rid)
                    if kid in l2_tn:
                        l2_tn[kid]["flow_target"] = True
                # Flow sources: the producing tables — closure table/view
                # vars that are not the searched table's own instances
                # (write targets are already targets; stray same-table
                # vars are excluded by source_tables[0]/name identity).
                for vid, o in physical_model.occurrences.items():
                    if vid not in closure:
                        continue
                    if o.get("variable_type") not in ("table", "view"):
                        continue
                    st = o.get("source_tables") or []
                    if (st and st[0] == table) or o.get("name") == table:
                        continue
                    kid = id_map.get(vid)
                    if kid in l2_tn:
                        l2_tn[kid]["flow_source"] = True
        else:
            src_raw = flow_source_id(full_graph, table,
                                     physical_model=physical_model)
            src_keeper = id_map.get(src_raw) if src_raw else None
            if src_keeper in l2_tn:
                l2_tn[src_keeper]["flow_source"] = True
            for rid in flow_targets(full_graph, table, field,
                                    physical_model=physical_model,
                                    _flow_memo=_flow_memo):
                kid = id_map.get(rid)
                if kid in l2_tn:
                    l2_tn[kid]["flow_target"] = True
    else:
        # R19.5 full-view roles are per PHYSICAL table compound only —
        # CTE/derived/VT compounds (subq, p1@29, ⟐output …) stay neutral.
        phys = {tn["id"] for tn in l2_tn.values()
                if tn.get("variable_type") == "table"}
        roles = classify_flow_roles(new_edges, phys)
        for nid, role in roles.items():
            if nid in l2_tn:
                l2_tn[nid]["flow_role"] = role


def _assemble_output(table_nodes: dict, field_nodes: list, new_edges: list,
                     nodes: list, sql_text: str, script_name: str,
                     target_full: str) -> dict:
    """Phase 11 (CW4): assemble the output graph.

    J12-10 stage 4: no builder-internal bookkeeping exists anymore
    (merged_original_ids is gone — the merge record rides occ_to_id,
    which never enters the response) — the compound nodes are emitted
    as-is.
    """
    # ── Assemble output (only table+field compound nodes) ──
    all_new_nodes = (
        [{"data": dict(tn)} for tn in table_nodes.values()] +
        [{"data": dict(fn)} for fn in field_nodes]
    )

    # W5: strip the builder-internal carriers (_src_line/_path_hops/_dml_
    # origin/…) — the API edge payload is highlight_line/flow_kind/reason.
    new_edges = [{k: v for k, v in e.items() if not k.startswith("_")}
                 for e in new_edges]

    total_edges = len(new_edges)
    return {
        "nodes": all_new_nodes,
        "edges": [{"data": e} for e in new_edges],
        "script_name": script_name,
        "total_nodes": len(nodes),
        "filtered_nodes": len(all_new_nodes),
        "total_edges": total_edges,
        "target": target_full,
    }


def build_line_merged_edges(edges: list, nodes: list) -> list:
    """ISSUE-6 / R32 — the L2 line-merged pass: one SQL line ≈ one edge.

    Built ON TOP of an already-built L2 closure edge list (the same closure
    that produces flow-only / full). The NODE set is never touched — callers
    pass the node list through unchanged. This pass rewrites EDGES only:

      1. Field→table promotion — every field endpoint is replaced by its
         parent table (never dropped, never kept as a field endpoint).
      2. Same-line same-table-pair merge — edges sharing (sql_line,
         unordered table pair) collapse to ONE edge; direction resolves to
         single arrow (one direction) / double arrow (both directions),
         never two separate edges for opposite directions.
      3. Type removed — the merged edge is an untyped "FLOW" edge (no
         edge-type color).
      4. Self-loop — table→same-table kept ONLY when it is the line's sole
         edge; absorbed into the line's other edge(s) otherwise.
      5. No SQL-line reference — an edge whose highlight_line is < 1 is
         dropped.
      6. Line spanning >2 tables — one edge per (unordered) table pair.

    Returns a list of {"data": {...}} merged-edge dicts (the same container
    shape as _assemble_output's edges). Each merged edge carries: id,
    source, target, edge_type ("FLOW"), category ("flow"), label ("FLOW"),
    highlight_line, and bidirectional (double arrow). Edges are emitted in
    deterministic (line, pair) order; ids are content-derived.

    Note: a field node with NO parent (a pre-existing classifier gap —
    phantom-aliased write columns like `a.CHARGE_DEPARTMENT` whose alias
    has no visible table node) has no table to promote to. Its endpoint is
    retained as the field node id (the field node stays in the untouched
    node set; its edge is never dropped). The parent table for such a field
    is not recoverable from the stripped L2 payload without re-running the
    classifier's write-target attribution, which is outside this pass.
    """
    # field node id → parent table id (promotion map). A node is field-like
    # when classified as a field compound ("type" == "field") and carries a
    # parent table id; table/CTE/alias/output nodes have no parent.
    parent_of = {}
    for n in nodes:
        nd = n.get("data", n)
        pid = nd.get("parent")
        if nd.get("type") == "field" and pid:
            parent_of[nd["id"]] = pid

    # Promote every endpoint and bucket by SQL line (rule 1 + rule 5).
    by_line = {}
    for e in edges:
        ed = e.get("data", e)
        line = _safe_int(ed.get("highlight_line"))
        if line < 1:
            continue  # rule 5 — no SQL-line reference
        src = parent_of.get(ed.get("source"), ed.get("source"))
        tgt = parent_of.get(ed.get("target"), ed.get("target"))
        if not src or not tgt:
            continue  # L-E6 — malformed edge with no endpoint; cannot promote
        by_line.setdefault(line, []).append((src, tgt))

    merged = []
    for line in sorted(by_line):
        members = by_line[line]
        # pair → {"self": bool, "dirs": set of ordered (src, tgt) arrows}.
        pairs = {}
        for src, tgt in members:
            if src == tgt:
                key = (src, src)
                pairs.setdefault(key, {"self": True, "dirs": set()})
                # a self-loop contributes no direction arrow
            else:
                a, b = (src, tgt) if src <= tgt else (tgt, src)
                key = (a, b)
                pairs.setdefault(key, {"self": False, "dirs": set()})
                pairs[key]["dirs"].add((src, tgt))

        non_self = [k for k, rec in pairs.items() if not rec["self"]]

        for (a, b), rec in sorted(pairs.items()):
            if rec["self"]:
                # rule 4 — kept ONLY as the line's sole edge (absorbed into
                # the line's non-self edge(s) when any exist). A line of only
                # self-loops keeps EVERY self-loop: two distinct self-loops
                # (T1→T1 + T2→T2) are each their own table's sole edge and
                # must both survive (L-E5 — the old `len(self_loops) > 1`
                # check dropped them both).
                if non_self:
                    continue
                source = target = a
                bidirectional = False
            else:
                # rule 2/3 — one untyped edge per table pair; direction is
                # double arrow only when both directions are present.
                if (a, b) in rec["dirs"] and (b, a) in rec["dirs"]:
                    source, target, bidirectional = a, b, True
                elif (a, b) in rec["dirs"]:
                    source, target, bidirectional = a, b, False
                else:
                    source, target, bidirectional = b, a, False

            merged.append({
                "data": {
                    "id": "l2m_{}".format(
                        hashlib.md5(f"{line}|{a}|{b}".encode()).hexdigest()[:12]),
                    "source": source,
                    "target": target,
                    "edge_type": "FLOW",
                    "category": "flow",
                    "label": "FLOW",
                    "highlight_line": line,
                    "bidirectional": bidirectional,
                },
            })
    return merged


def _build_l2_graph(ws_id: str, script_name: str, sql_text: str,
                    table: str, field: str,
                    relevance_filter: bool = True,
                    direction="downstream",
                    _shared_load: tuple | None = None,
                    _flow_memo: dict | None = None) -> dict:
    """Build Level 2 per-script graph with compound nodes and edge metadata.

    Returns:
      {
        "nodes": [{"data": {id, label, type, parent?, field_group?, is_target?, ...}}],
        "edges": [{"data": {id, source, target, edge_type, category,
                            highlight_line, flow_kind, reason, ...}}],
        "script_name": str,
        "total_nodes": int,           # nodes before filtering
        "filtered_nodes": int,        # nodes after filtering
        "target": "table.field",
        "search_matched": bool,       # False only when a filter was requested
                                      # and no target/direct seed matched
      }

    Issue a: one physical table → exactly one table node (dedup by table
    label); all contexts' edges re-point to the keeper. Field nodes of
    merged contexts re-parent to the keeper and dedup by (parent, name).

    Node types in L2:
      - source_table, intermediate_table, output_table (compound parents)
      - field (child of table, with parent=data.parent)
      - cte_table (CTE definition, L2 only)
      - expression, aggregate, window, transform, case, literal (existing V2 types)

    Edge metadata per formal definition §10 + R25 (W5):
      - edge_type: formal type (REF, JOIN, FILTER, etc.)
      - category: visual group (copy, filter, aggregate, compute, combine, write, structure)
      - highlight_line: exactly ONE script line per edge (§8.3 anchor rules)
      - flow_kind: the §8.7 canonical kind (chain / field flow / read /
        write / filter / structure / bridge)
      - reason: `<kind> — <flow string>` (§8.8.3, ‖…‖-wrapped current edge)
    The old sql_range/sql_ranges and response-level highlights are gone.
    """
    # CW4: orchestration only — every stage is a named phase function above,
    # with shared state passed explicitly between phases. J12-10 (stage 2):
    # phase 1 also builds the physical model once per build; the
    # node-construction phases consume it (keeper selection + sync inputs).
    if _shared_load is not None:
        # PERF (v3.3.194, fix 1 — load once per request): the caller
        # (dataflow_service.get_level2_graph) already loaded the graph,
        # the schemas and the physical model this request needs; take
        # them instead of re-reading the caches — the request runs this
        # build twice (the flow view and the full view). `_shared_load`
        # is the exact (full_graph, table_schemas, physical_model) triple
        # `_load_or_build_graph` returns, and the caller only hands one
        # over when the loaded graph passed the loader's own
        # cache-acceptance test, so a stale/corrupt cache still goes
        # through the loader's rebuild below.
        full_graph, table_schemas, physical_model = _shared_load
        # CW7: normalize edge_type on cache read (the cache stores
        # "relationship") — mirror of the loader's cache-read path.
        # Idempotent: the second build of the same request is a no-op.
        for _e in full_graph.get("edges", []):
            _ed = _e.get("data", _e)
            _ed.setdefault("edge_type", _ed.get("relationship", "REF"))
    else:
        full_graph, table_schemas, physical_model = _load_or_build_graph(
            ws_id, script_name, sql_text)
    # PERF (v3.3.194, fix 6): one strict-walk cache per build — the filter
    # and the flow-role pass walk the SAME graph for the SAME (table,
    # field, direction), so the second walk is a cache hit. The caller
    # (get_level2_graph) hands its own request-scoped cache in, which
    # also covers its response-level filter.
    if _flow_memo is None:
        _flow_memo = {}
    # R43 (2026-08-28, task #384): pure-metadata partition-DDL statement
    # frames never enter the display — dropped here, BEFORE the flow
    # filter, so full AND flow views are clean. Flow closures are
    # unchanged: no closure edge ever anchored on an ALTER line (INV-1's
    # carve-out was exactly that observation).
    full_graph = _drop_partition_ddl_frames(full_graph, sql_text)
    graph_data = _apply_relevance_filter(full_graph, table, field, table_schemas,
                                         relevance_filter, physical_model,
                                         direction, _flow_memo)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    target_node_ids, direct_ids = _compute_target_and_direct_ids(
        nodes, edges, table, field, physical_model)
    # J12-10 stage 4: the classification returns (table_nodes,
    # field_nodes, alias_map, occ_to_id) — occ_to_id IS the id_map (every
    # nid seen during classification maps to its compound/field id; the
    # old _build_id_map is gone).
    table_nodes, field_nodes, _alias_map, occ_to_id = _classify_compound_nodes(
        nodes, full_graph, script_name, target_node_ids, direct_ids, table,
        physical_model)
    id_map = occ_to_id
    # R11-3: compound nodes gain line_start/line_end/defined_in from their
    # keeper vars (def-site anchors; line_end = next stmt anchor − 1) —
    # the model's occurrence index carries the per-var facts.
    _carry_node_lines(table_nodes, physical_model)
    # Issue a: resolve search-target/direct ids to the merged keepers so
    # highlighting lands on the single table node / deduped field node,
    # never on a merged-away ghost nid.
    target_mapped, direct_mapped = _map_search_target_ids(
        field_nodes, table_nodes, target_node_ids, direct_ids, id_map)

    new_edges, node_labels = _build_edge_list(edges, nodes, id_map, sql_text)
    # R45 Fix H: the keeper chip's own line, for the folded-edge anchor.
    node_lines = {}
    for tn in table_nodes.values():
        node_lines[tn.get("id")] = _safe_int(tn.get("line_start"))
    for fn in field_nodes:
        node_lines[fn.get("id")] = _safe_int(fn.get("line_start"))
    # J12-15 (stage 4): per-statement DML trunk — the write/read legs of
    # every statement route through that statement's own ⟐ output VT.
    # J12-16: the DML simplification MUST run BEFORE _combine_edges — a
    # folded field compound's per-instance edges (identical mapped
    # endpoints, different occurrences: the flagship sup data_dt REF
    # @160/TOP0 vs REF @223/TOP1) diverge ONLY through rule 2's
    # retarget (the TOP0 instance → its statement's ⟐ output; the TOP1
    # instance → its read target); _combine_edges keyed on
    # (source, target, edge_type) would collapse the two instances into
    # one (first-wins, keeping only the TOP0 carried info) before the
    # divergence could happen.
    new_edges = _simplify_dml_edges(new_edges, full_graph, id_map,
                                    table_nodes, field_nodes,
                                    physical_model=physical_model)
    new_edges = _combine_edges(new_edges, node_lines)
    new_edges = _promote_field_edges(new_edges, field_nodes)
    # C6 (v3.3.140): under the strict table.field filter the JOIN survival
    # heuristic is a no-op — the strict closure already carries the
    # field-relevant join partners (see _survive_join_edges docstring).
    new_edges = _survive_join_edges(new_edges, full_graph, id_map, table_nodes,
                                    field_nodes, node_labels, sql_text,
                                    strict=relevance_filter)
    new_edges = _dedup_edges(new_edges)
    # W5/R25: per-edge payload — highlight_line/flow_kind/reason from the
    # carried extraction-time info + the closure walk (never at render).
    _attach_flow_payload(new_edges, field_nodes, table_nodes=table_nodes)

    # Field-involvement admission (USER RULING 2026-08-31): "only edges
    # where the searched field is involved in the data flow are shown."
    # Runs AFTER the payload phase (it reads the carried `_path_hops` walk
    # and the served anchor) and BEFORE the roles/response assembly, so
    # every downstream consumer — flow roles, the response's
    # flow_edge_ids, the Field Story, the string-match coverage baseline —
    # sees the admitted set and nothing else.
    new_edges = _apply_field_involvement(new_edges, field, relevance_filter,
                                         physical_model=physical_model,
                                         sql_text=sql_text, table=table)
    # The 3a ruling's node half (USER RULING 2026-09-01, confirmed):
    # sibling chips whose last edge the filter just dropped leave the
    # view with it. FLOW-ONLY ONLY — the full view has no searched field
    # to be involved, and keeps every chip (the J2-era contract).
    if relevance_filter:
        field_nodes = _prune_orphan_sibling_chips(field_nodes, new_edges,
                                                  field)
        # the 3a ruling's box half: an edge-less non-seed box leaves with
        # its edges (EAST5's rrcdm job-log box, SUP_M's p2@199)
        table_nodes = _prune_orphan_boxes(table_nodes, new_edges, field_nodes,
                                          field, table)

    # R46a (2026-08-31, FSB audit): the seed CLAIM is scoped here — the
    # searched table's entity set plus the write targets receiving the
    # field's value — after every edge consumer has
    # read the flag (P2/P17/payload above) and before assembly, so the
    # served edges are untouched and only the stamp narrows. Runs after
    # `_map_search_target_ids`'s keeper re-mark for the same reason: the
    # re-mark is an edge-machinery seed, this is the display claim.
    _scope_target_stamp(field_nodes, table_nodes, table, field, physical_model)

    # J12-10 stage 3: the Sync 1/2 proxy phase (_sync_alias_and_dml_fields)
    # is DELETED — alias mirrors and DML phantoms are real model entities
    # now (nothing to synthesize).
    _attach_flow_roles(new_edges, table_nodes, id_map, full_graph, table,
                       field, relevance_filter, physical_model, direction,
                       _flow_memo)
    result = _assemble_output(table_nodes, field_nodes, new_edges, nodes, sql_text,
                              script_name, f"{table}.{field}")
    # Issue a: search_matched contract (frontend + BE2). False ONLY when a
    # relevance filter was requested and no target/direct seed matched —
    # the exact "the searched field is not in this script" signal. True
    # when the field matched, or when no filter was requested.
    # R29 (2026-08-12): upstream — matched iff the directional closure is
    # non-empty (when filtering, graph_data's nodes ARE the closure; the
    # downstream target/direct mapping is the READ-side seed match, which
    # has no meaning for a writing-only walk).
    if direction == "upstream":
        result["search_matched"] = (not relevance_filter) or bool(
            graph_data.get("nodes"))
    else:
        result["search_matched"] = (not relevance_filter) or bool(target_mapped or direct_mapped)
    return result
