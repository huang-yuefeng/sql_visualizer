"""L1 Graph Builder — cross-script pipeline graph construction.

Extracted from dataflow_service.py per ARCHITECTURE_REVIEW S3.
Builds L1 pipeline view: scripts + tables + reads_from/writes_to edges.
"""
import json
import uuid
import hashlib
import logging
import traceback
import threading
from collections import OrderedDict

from app.services.workspace_service import get_workspace_dir
from app.extractor.lineage import compute_field_lineage, compute_field_flow, PRODUCTION_EDGES
from app.extractor.physical_model import build_physical_model
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.services.logger import _push

_log = logging.getLogger("sql_visualizer.dataflow")

# ── L1 helper functions ──────────────────────────────────────────────

def _classify_table_node(table_name, all_scripts):
    """Classify a table as source, intermediate, or output based on read/write patterns."""
    readers = set()
    writers = set()
    for s in all_scripts:
        if table_name in s.get("input_tables", []):
            readers.add(s["script_name"])
        if table_name in s.get("output_tables", []):
            writers.add(s["script_name"])
    if readers and not writers:
        return "source_table"
    if writers and not readers:
        return "output_table"
    if writers and readers:
        return "intermediate_table"
    return "source_table"



def detect_role(script_analysis: dict, target_table: str, target_field: str) -> list:
    """Read-only summary: how is (T, f) used in this script?

    Queries the already-extracted variables and dependencies from cached
    analysis data. Uses defined_in, variable_type, is_output, and
    dependency relationship fields. No new SQL parsing.

    Resolves table aliases: if a column is named "sc.customer_id"
    and sc is an alias for stg_customers, it matches target_table="stg_customers".
    """
    # Graph uses nodes (not variables) and edges (not dependencies)
    nodes = script_analysis.get("nodes", [])
    # Also support raw analysis format with "variables" key
    raw_vars = script_analysis.get("variables", [])
    # Unwrap node data: each node is {"data": {...}}
    variables = []
    for n in nodes:
        nd = n.get("data", n)
        variables.append(nd)
    # Merge with raw variables if present
    if raw_vars:
        seen = {v["id"] for v in variables if "id" in v}
        for rv in raw_vars:
            if rv.get("id") not in seen:
                variables.append(rv)

    edges_list = script_analysis.get("edges", [])
    deps_raw = script_analysis.get("dependencies", [])
    # Unwrap edge data
    deps = []
    for e in edges_list:
        ed = e.get("data", e)
        deps.append(ed)
    deps.extend(deps_raw)

    target_full = f"{target_table}.{target_field}"

    var_by_id = {v["id"]: v for v in variables if "id" in v}

    # Build alias map: alias_name -> original_table_name
    alias_map = {}
    for v in variables:
        if v.get("variable_type") == "table":
            vname = v.get("label") or v.get("name", "")
            src_tables = v.get("source_tables", [])
            if src_tables and vname:
                alias_map[vname] = src_tables[0]  # alias -> original

    roles = set()

    for v in variables:
        name = v.get("label") or v.get("name", "")
        vid = v.get("id", "")
        vt = v.get("variable_type", "")

        # Match logic: exact match, alias-resolved match, or bare field match
        matches = False

        # 1. Exact full name match
        if target_full in name:
            matches = True

        # 2. Alias-resolved match: "sc.customer_id" where sc->stg_customers
        if not matches and "." in name:
            prefix, suffix = name.split(".", 1)
            resolved = alias_map.get(prefix, prefix)
            if resolved == target_table and suffix == target_field:
                matches = True

        # 3. Suffix match: "sc.customer_id" field part matches target_field
        if not matches and "." in name:
            suffix = name.rsplit(".", 1)[-1]
            if suffix == target_field:
                matches = True

        # 4. Bare field match (no table prefix at all)
        if not matches and "." not in name:
            if name == target_field:
                matches = True

        # 5. source_columns match
        if not matches:
            src_cols = v.get("source_columns", [])
            for sc in src_cols:
                # B2/CW9: exact field-part semantics — a bare word-boundary
                # regex matched the alias/table part too (target_field="item"
                # vs "item.i_brand"), attributing roles for the wrong field.
                sc_field = sc.rsplit(".", 1)[-1] if "." in sc else sc
                if target_full in sc or sc_field == target_field:
                    matches = True
                    break
                if "." in sc:
                    sp, ss = sc.split(".", 1)
                    if alias_map.get(sp, sp) == target_table and ss == target_field:
                        matches = True
                        break

        if not matches:
            continue

        di = (v.get("defined_in") or "").upper()

        # Column-level: detect role from defined_in context
        if vt == "column":
            if "FROM" in di:
                roles.add("SCHEMA")
            if "JOIN" in di or "ON" in di:
                roles.add("JOIN")
            if "WHERE" in di or "HAVING" in di:
                roles.add("FILTER")
            # GROUP BY modifies AGGREGATE, not a separate edge type
            # ORDER BY modifies WINDOW, not a separate edge type
            if v.get("is_output"):
                roles.add("REF")

        # Computed types: detect role from variable_type
        if vt == "aggregate":
            roles.add("AGGREGATE")
        if vt == "window":
            roles.add("WINDOW")
        if vt == "transform":
            roles.add("TRANSFORM")
        if vt == "case":
            roles.add("COMPUTED")

    # Dependency-level: DML and CORRELATED
    for d in deps:
        rel = d.get("relationship", "")
        tgt_id = d.get("target_id") or d.get("target", "")
        src_id = d.get("source_id") or d.get("source", "")
        tgt = var_by_id.get(tgt_id, {})
        src = var_by_id.get(src_id, {})
        tgt_name = tgt.get("name", "")
        src_name = src.get("name", "")

        def dep_matches(dep_name):
            if not dep_name:
                return False
            if target_full in dep_name:
                return True
            if "." in dep_name:
                p, s = dep_name.split(".", 1)
                if alias_map.get(p, p) == target_table and s == target_field:
                    return True
            if "." not in dep_name and dep_name == target_field:
                return True
            return False

        if rel == "DML" and dep_matches(tgt_name):
            roles.add("DML TARGET")
        if rel == "INDIRECT" and dep_matches(src_name):
            roles.add("CORRELATED")

    return sorted(roles)


def _extract_table_field_pairs(lineage_set: set, nodes: list,
                               alias_map: dict,
                               valid_table_fields: set | None = None,
                               skip_virtual: bool = False) -> set:
    """Collect (table_name, field_name) pairs from lineage nodes.

    Only nodes whose id is in lineage_set. Table/field taken from
    table_name/field_name, falling back to the label's "table.field"
    suffix split when either is missing. Alias prefixes are resolved
    via alias_map. When valid_table_fields is not None, pairs are
    validated against it (exact match to the current loops' behavior:
    an empty set means no validation). skip_virtual drops pairs whose
    (resolved) table name starts with the virtual-table marker ⟐.
    """
    pairs = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("id") not in lineage_set:
            continue
        tn = nd.get("table_name", "")
        fn = nd.get("field_name", "")
        if not tn or not fn:
            label = nd.get("label", "")
            if "." in label:
                parts = label.rsplit(".", 1)
                tn = tn or parts[0]
                fn = fn or parts[1]
        if not (tn and fn):
            continue
        tn = alias_map.get(tn, tn)
        if valid_table_fields is not None and (tn, fn) not in valid_table_fields:
            continue
        if skip_virtual and tn.startswith("⟐"):
            continue
        pairs.add((tn, fn))
    return pairs


def _push_l1_degraded(ws_id: str, table: str, field: str,
                      script_names: list[str], exc: Exception) -> None:
    """M4-B: emit an L1-degraded diagnostic block via the `_push` "profile"
    channel (same mechanism as the R16/R17 blocks) — the LogPanel shows why
    the script-only fallback was returned instead of a full pipeline graph.
    """
    W = 80
    lines = ["┌─ L1 GRAPH DEGRADED " + "─" * (W - len("┌─ L1 GRAPH DEGRADED ") - 1) + "┐"]
    lines.append(("│ target: %s.%s  scripts: %d" % (table, field, len(script_names)))
                 .ljust(W - 1) + "│")
    lines.append(("│ script-only fallback returned — L1 build failed:"
                  ).ljust(W - 1) + "│")
    msg = ("│ %s" % exc).strip()[:72]
    lines.append(msg.ljust(W - 1) + "│")
    lines.append("└" + "─" * (W - 2) + "┘")
    for line in lines:
        _push(ws_id, "profile", line)


def _build_l1_directional_field_flow(all_scripts: list[dict],
                                     model_by_script: dict,
                                     table: str, field: str,
                                     direction: str) -> dict:
    """R29 (J12-22): L1 = the queried field's directional flow projection.

    Per script, the SAME strict walker as L2 (compute_field_flow — the
    per-instance table.field walker, called with the query direction)
    runs over the per-script physical model (model_by_script, built by
    _build_l1_graph from the analysis cache or the inline pipeline). A
    script participates iff its directional closure is non-empty; a
    table participates iff it carries >= 1 closure field — the owning
    PhysicalTables of the closure's node ids (the model's field
    attribution for field occurrences, the entity index for table-like
    occurrences; the seed's own table joins when seed instances are in
    the closure, which they always are). Only physical tables project
    — CTEs/⟐ containers are intra-script structure (L2's domain).

    Emits script nodes + participating table nodes + reads_from/
    writes_to edges restricted to participating nodes. No field nodes,
    no intra-script structure, no terminal markers (R29 item 8
    supersedes R18.1 — the flow terminates at the last table carrying
    it). When EVERY script's directional flow is empty the graph is
    empty with flow_empty=True — the search endpoint renders the
    "no flow in this direction" state (message, not an error).

    A walker failure on one script skips that script (logged); when
    every script's walk fails (e.g. a systemic walker error) the first
    exception propagates so the caller's M4-B degraded fallback fires —
    a build failure must never masquerade as "no flow".
    """
    def _owning_tables(m, closure: set) -> dict:
        """Physical tables owning >= 1 closure node (name → table)."""
        owner_by_id = {}
        for (tkey, _fname), fld in m.fields.items():
            for vid in fld.occurrence_ids:
                owner_by_id.setdefault(vid, tkey)
        out = {}
        for vid in closure:
            for tkey in (owner_by_id.get(vid), m.entity_of_id.get(vid)):
                if tkey is None:
                    continue
                tbl = m.tables.get(tkey)
                if tbl is None or tbl.kind != "physical":
                    continue
                out.setdefault(tbl.name, tbl)
        return out

    participating = []          # script entries carrying the directional flow
    participating_tables = {}   # table name → PhysicalTable (first seen)
    # CR5: per-name read/write role accumulation across ALL participating
    # scripts (a table read in one script and written in another is an
    # intermediate — the raw IO slots aggregate the same way).
    read_role_tables = set()    # names read in some participating script
    write_role_tables = set()   # names written (DML/merge) in some script
    failures = 0
    first_exc = None

    for s in all_scripts:
        sname = s.get("script_name", "")
        m = model_by_script.get(sname)
        gdata = s.get("graph", {})
        if m is None or not gdata or not gdata.get("nodes"):
            continue
        try:
            closure = compute_field_flow(gdata, table, field,
                                         physical_model=m,
                                         direction=direction)
        except Exception as exc:
            failures += 1
            if first_exc is None:
                first_exc = exc
            _log.error("L1 R29: compute_field_flow failed for %s.%s "
                       "direction=%s in %s: %s",
                       table, field, direction, sname, exc, exc_info=True)
            continue
        if not closure:
            continue  # this script does not carry the directional flow
        participating.append(s)
        for tname, tbl in _owning_tables(m, closure).items():
            participating_tables.setdefault(tname, tbl)
            if "read" in tbl.roles:
                read_role_tables.add(tname)
            if "write" in tbl.roles or "merge_target" in tbl.roles:
                write_role_tables.add(tname)

    if not participating:
        if failures:
            raise first_exc  # systemic walker failure → M4-B degraded fallback
        return {"nodes": [], "edges": [], "target": f"{table}.{field}",
                "script_count": 0, "source_tables": [],
                "intermediate_tables": [], "output_tables": [],
                "flow_empty": True, "degraded": False}

    nodes = []
    edges = []
    seen_node_ids = set()
    seen_edge_ids = set()

    def add_node(nid, label, ntype, **extra):
        if nid in seen_node_ids:
            return
        seen_node_ids.add(nid)
        d = {"id": nid, "label": label, "type": ntype}
        d.update(extra)
        nodes.append({"data": d})

    def add_edge(src, tgt, label, etype, role=None, roles=None):
        eid = f"{src}->{tgt}"
        if eid in seen_edge_ids:
            return
        seen_edge_ids.add(eid)
        d = {"id": eid, "source": src, "target": tgt,
             "label": label, "edge_type": etype}
        if roles:
            d["roles"] = roles
            d["role"] = ", ".join(roles)
        elif role:
            d["roles"] = [role]
            d["role"] = role
        edges.append({"data": d})

    # ── Participating tables — classified by the participating scripts'
    # read/write pattern (the projection's own edges). A table carrying
    # the flow but listed as no script's input/output (name divergence)
    # still projects — its role comes from the model's read/write legs
    # (CR5), never a bare default to source. ──
    inputs_by_script = {}
    outputs_by_script = {}
    all_inputs = set()
    all_outputs = set()
    for s in participating:
        sname = s.get("script_name", "")
        ins = {t for t in s.get("input_tables", [])
               if t in participating_tables}
        outs = {t for t in s.get("output_tables", [])
                if t in participating_tables}
        inputs_by_script[sname] = ins
        outputs_by_script[sname] = outs
        all_inputs |= ins
        all_outputs |= outs

    source_tables = sorted(all_inputs - all_outputs)
    intermediate_tables = sorted(all_inputs & all_outputs)
    output_tables = sorted(all_outputs - all_inputs)
    # Safety net: participating tables with no script IO slot (name
    # divergence) still project — classified from the model's own
    # read/write legs (the same per-script signal the raw IO slots derive
    # from) instead of defaulting to source, so a write-only or
    # intermediate table is never mislabeled as a source.
    for tname in sorted(participating_tables):
        if tname in all_inputs or tname in all_outputs:
            continue
        writes = tname in write_role_tables
        if tname in read_role_tables and writes:
            intermediate_tables.append(tname)
        elif writes:
            output_tables.append(tname)
        else:
            source_tables.append(tname)
    source_tables = sorted(set(source_tables))
    intermediate_tables = sorted(set(intermediate_tables))
    output_tables = sorted(set(output_tables))

    for tname in source_tables:
        add_node(f"tbl_{tname}", tname, "source_table", table_name=tname)
    for tname in intermediate_tables:
        add_node(f"tbl_{tname}", tname, "intermediate_table", table_name=tname)
    for tname in output_tables:
        add_node(f"tbl_{tname}", tname, "output_table", table_name=tname)

    # ── Script nodes + restricted reads_from/writes_to edges ──
    for s in participating:
        sid = s["script_id"]
        sname = s["script_name"]
        roles = detect_role(s.get("graph", {}), table, field)

        add_node(sid, sname, "script_node",
                 script_name=sname,
                 total_variables=s.get("total_variables", 0),
                 input_tables=sorted(inputs_by_script.get(sname, set())),
                 output_tables=sorted(outputs_by_script.get(sname, set())),
                 roles=roles)

        for tname in sorted(inputs_by_script.get(sname, set())):
            add_edge(f"tbl_{tname}", sid, tname, "reads_from",
                     roles=roles if roles else None)
        for tname in sorted(outputs_by_script.get(sname, set())):
            add_edge(sid, f"tbl_{tname}", tname, "writes_to",
                     roles=roles if roles else None)

    return {
        "nodes": nodes,
        "edges": edges,
        "target": f"{table}.{field}",
        "source_tables": source_tables,
        "intermediate_tables": intermediate_tables,
        "output_tables": output_tables,
        "script_count": len(participating),
        "flow_empty": False,
        "degraded": False,
    }


# ── In-memory L1 caches (J12-11 #193 + #252) ─────────────────────────────
# T1 (#193): per-ws_id memo of the analysis_cache_map, invalidated by the
# analysis cache-dir file-set/mtime signature — the recorded J12-11 design.
# T2 (#252): memo of the whole _build_l1_graph return value, invalidated by
# the analysis-cache signature PLUS the matched-script file-set signature
# (the builder reads the matched scripts' SQL directly, so an edit without
# a re-index must invalidate — the C-H1 stale-edit class).
# Both are in-memory only (lost on restart — intended, J12-8 purge
# philosophy), signature-invalidated (re-index / re-extraction / S4b
# mutation changes the file-set → miss → rebuild), LRU-bounded (no
# unbounded growth across many workspaces), and byte-identical to the disk
# read path (the memos store the SAME dicts a fresh read would produce).
# No external packages (offline rule).

_ANALYSIS_MAP_LRU_MAX = 12    # T1: most-recent workspaces
_L1_GRAPH_MEMO_MAX = 192      # T2: most-recent (sig, ws, scripts, ...) keys
_analysis_map_lru: "OrderedDict[str, tuple[str, dict]]" = OrderedDict()
_l1_graph_memo: "OrderedDict[tuple, dict]" = OrderedDict()
_memo_lock = threading.Lock()


def _file_set_signature(base_dir, pattern) -> str:
    """Hash of sorted (name, mtime_ns, size) for `base_dir.glob(pattern)`.

    The leading byte records directory presence so an absent dir is
    distinct from a present-but-empty one (a cache dir created later must
    invalidate). mtime_ns + size is the same freshness signal the recorded
    design uses; a changed file-set (re-index, re-extraction, S4b mutation,
    script edit) changes the signature → memo miss.
    """
    h = hashlib.sha256()
    h.update(b"\x01" if base_dir.is_dir() else b"\x00")
    if base_dir.is_dir():
        for p in sorted(base_dir.glob(pattern)):
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(p.name.encode("utf-8", "replace"))
            h.update(b"|")
            h.update(str(st.st_mtime_ns).encode("ascii"))
            h.update(b"|")
            h.update(str(st.st_size).encode("ascii"))
            h.update(b";")
    return h.hexdigest()


def _analysis_signature(ws_id: str) -> str:
    """File-set/mtime signature of the workspace's analysis cache dir."""
    return _file_set_signature(get_workspace_dir(ws_id) / "cache",
                               "analysis_*.json")


def _analysis_cache_empty(ws_id: str) -> bool:
    """True when the workspace's analysis cache dir holds NO analysis_*.json.

    A build on an empty cache runs LIVE extraction (run_full_analysis) for
    every matched script — the result's validity depends on the extraction
    environment, which the file-set signature does NOT capture (M4-B #252
    fix, 2026-08-24). Such a result must never be memoized NOR served from
    the T2 graph memo: a later identical call could hit the memo and mask a
    would-be degraded outcome. `_analysis_signature` alone cannot serve as
    the gate (an empty-set signature is stable but indistinguishable from a
    stale prior empty key), so the wrapper checks emptiness directly.
    """
    cache_dir = get_workspace_dir(ws_id) / "cache"
    if not cache_dir.is_dir():
        return True
    return next(cache_dir.glob("analysis_*.json"), None) is None


def _script_set_signature(ws_id: str, script_names) -> str:
    """File-set/mtime signature of the matched scripts.

    _build_l1_graph reads the matched scripts' SQL directly (sp.read_text)
    and both the sql-keyed analysis lookup and the fresh-extraction
    fallback depend on that text — so the T2 graph memo must invalidate
    when a matched script changes even WITHOUT a re-index (the C-H1
    stale-edit case).
    """
    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    h = hashlib.sha256()
    h.update(b"\x01" if scripts_dir.is_dir() else b"\x00")
    for name in sorted(script_names):
        p = scripts_dir / name
        try:
            st = p.stat()
            h.update(p.name.encode("utf-8", "replace"))
            h.update(b"|")
            h.update(str(st.st_mtime_ns).encode("ascii"))
            h.update(b"|")
            h.update(str(st.st_size).encode("ascii"))
            h.update(b";")
        except OSError:
            h.update(name.encode("utf-8", "replace"))
            h.update(b"|missing;")
    return h.hexdigest()


def _load_analysis_cache_map(ws_id: str) -> dict:
    """Disk read path for the analysis cache map (extracted verbatim from
    the old inline block — the memo stores exactly what this produces)."""
    cache_dir = get_workspace_dir(ws_id) / "cache"
    analysis_cache_map = {}
    if cache_dir.exists():
        for af_path in sorted(cache_dir.glob("analysis_*.json")):
            try:
                adata = json.loads(af_path.read_text())
                sname = adata.get("script_name", "")
                if sname:
                    analysis_cache_map[sname] = adata
            except Exception as exc:
                _log.warning("L1: failed to read analysis cache %s: %s",
                             af_path.name, exc)
    return analysis_cache_map


def _analysis_cache_map_for(ws_id: str) -> dict:
    """T1 (#193): in-memory per-ws_id memo of the analysis cache map.

    Keyed on ws_id + the analysis cache-dir file-set/mtime signature. When
    the files are stable the memo serves the already-loaded dicts; when the
    file-set changes (re-index, re-extraction, S4b mutation) the signature
    changes and the map is rebuilt. Bounded LRU of most-recent workspaces;
    in-memory only (restart-cleanup automatic — intended)."""
    sig = _analysis_signature(ws_id)
    with _memo_lock:
        entry = _analysis_map_lru.get(ws_id)
        if entry is not None and entry[0] == sig:
            _analysis_map_lru.move_to_end(ws_id)
            return entry[1]
    m = _load_analysis_cache_map(ws_id)
    with _memo_lock:
        _analysis_map_lru[ws_id] = (sig, m)
        _analysis_map_lru.move_to_end(ws_id)
        while len(_analysis_map_lru) > _ANALYSIS_MAP_LRU_MAX:
            _analysis_map_lru.popitem(last=False)
    return m


def _l1_graph_memo_key(ws_id: str, script_names, table: str, field: str,
                       direction: str) -> tuple:
    """T2 memo key: every input that can change _build_l1_graph's output
    (ws_id, script_names, table, field, direction) + the analysis-cache
    file-set signature + the matched-script file-set signature. The build
    is deterministic given these (verified: no in-place mutation of the
    result by callers, no writes that later reads depend on — see the
    wrapper's docstring)."""
    return (_analysis_signature(ws_id),
            _script_set_signature(ws_id, script_names),
            ws_id, tuple(script_names), table, field, direction)


def _l1_graph_memo_get(key):
    with _memo_lock:
        g = _l1_graph_memo.get(key)
        if g is not None:
            _l1_graph_memo.move_to_end(key)
        return g


def _l1_graph_memo_set(key, g):
    with _memo_lock:
        _l1_graph_memo[key] = g
        _l1_graph_memo.move_to_end(key)
        while len(_l1_graph_memo) > _L1_GRAPH_MEMO_MAX:
            _l1_graph_memo.popitem(last=False)


def _l1_graph_copy(g: dict) -> dict:
    """Shallow copy protecting the memo from caller mutation.

    Callers (`_filter_l1_by_lineage`, the level1/search routers) read the
    graph and rebuild new node/edge lists but never mutate node/edge dicts
    in place — a copy of the top-level dict + its list containers keeps the
    memoized dict pristine across hits."""
    out = dict(g)
    for k, v in g.items():
        if isinstance(v, list):
            out[k] = list(v)
    return out


def _build_l1_graph(ws_id: str, script_names: list[str],
                    table: str, field: str,
                    direction: str = "upstream") -> dict:
    """Build Level 1 cross-script directional field-flow graph (R29).

    Cached wrapper (#252): the Final-L1-graph memo. A repeat call with
    identical inputs — same (ws_id, script_names, table, field, direction)
    AND the same analysis-cache + script file-set signatures — is served
    from the in-memory LRU (byte-identical, no re-read); any signature
    change (re-index, re-extraction, S4b mutation, a matched-script edit)
    is a miss → rebuild. The signature is the freshness mechanism;
    restart-cleanup is automatic (in-memory). M4-B degraded results are
    never memoized. Full build semantics on `_build_l1_graph_uncached`.
    """
    if len(script_names) < 1:
        return _build_l1_graph_uncached(ws_id, script_names, table, field,
                                        direction)
    # M4-B (#252 fix, 2026-08-24): never memoize NOR serve when the analysis
    # cache is empty — an empty cache means the build ran LIVE extraction
    # (run_full_analysis) for every matched script, so the result's validity
    # is a function of the extraction environment, which the file-set
    # signature does not capture. Serving such a result from the memo would
    # mask a would-be degraded outcome on a later identical call (the
    # test_l1_degraded_fallback_visible contract). Indexed workspaces
    # (non-empty cache) keep the full T2 memo behavior. Residual edge case:
    # a NON-empty cache where some matched scripts still miss (stale/unindexed)
    # runs live for those scripts and IS memoized — documented approximation.
    if _analysis_cache_empty(ws_id):
        return _build_l1_graph_uncached(ws_id, script_names, table, field,
                                        direction)
    memo_key = _l1_graph_memo_key(ws_id, script_names, table, field, direction)
    hit = _l1_graph_memo_get(memo_key)
    if hit is not None:
        return _l1_graph_copy(hit)
    result = _build_l1_graph_uncached(ws_id, script_names, table, field,
                                      direction)
    if not result.get("degraded"):
        _l1_graph_memo_set(memo_key, result)
    # The miss path stores `result` in the memo, so hand the caller a COPY —
    # returning the shared canonical dict would let caller mutation corrupt
    # the memoized graph (the hit path already returns `_l1_graph_copy`).
    return _l1_graph_copy(result)


def _build_l1_graph_uncached(ws_id: str, script_names: list[str],
                             table: str, field: str,
                             direction: str = "upstream") -> dict:
    """Build Level 1 cross-script directional field-flow graph (R29).

    Field queries (field truthy): L1 is the queried field's data flow —
    the SAME strict field-level semantic as L2 — at cross-script scale:
    script nodes + the tables between them that carry the flow, in the
    query direction (upstream = writing flow / downstream = reading
    flow). No field nodes, no intra-script structure (L2 is the
    zoom-in). Per-script participation comes from the strict walker
    (compute_field_flow) run in the query direction over the per-script
    physical model; a table participates iff it carries >= 1 closure
    field. When EVERY script's directional flow is empty the graph is
    empty with flow_empty=True — the search endpoint renders the
    "no flow in this direction" state (message, not an error).

    Table-only searches (field falsy): the full table-level pipeline
    graph — scripts + source/intermediate/output tables +
    reads_from/writes_to edges + model-projected field children —
    unchanged (R29 applies to field queries only).

    Edges: table↔script per formal §5.1: (s,t) ∈ E iff s uses t, with
    role badges for target var.
    """
    if len(script_names) < 1:
        return {"nodes": [], "edges": [], "target": f"{table}.{field}",
                "degraded": False, "flow_empty": True}

    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    script_data = []
    for name in script_names:
        sp = scripts_dir / name
        if sp.exists():
            sql = sp.read_text(encoding="utf-8", errors="replace")
            script_data.append((name, sql))

    try:
        # ── Analysis cache map (shared by Pass A and Pass B) ──
        # Built ONCE from the workspace's analysis_*.json files. Both Pass A
        # (the all_scripts entries) and Pass B (the physical models) resolve
        # per-script analysis through `_lookup_analysis`, so a cache hit
        # serves the SAME analysis dict to both passes — the graph and the
        # model can never diverge (fresh-vs-cached L1 byte-identity).
        cache_dir = scripts_dir.parent / "cache"
        # T1 (#193): the analysis cache map is served from the in-memory
        # per-ws_id memo (file-set/mtime-signature invalidated) instead of a
        # full disk re-scan of every analysis_*.json per call. The memo
        # stores the SAME dicts the disk path would load (json.loads of each
        # file) — byte-identical. Staleness of the memoized entries is still
        # bounded by the use-time `_analysis_current` (version + sql_text)
        # guard in `_lookup_analysis` below.
        analysis_cache_map = _analysis_cache_map_for(ws_id)

        def _analysis_current(adata: dict, sql: str) -> bool:
            """C-H1 (2026-08-19 review): a cache entry is usable only when it
            was produced by the current extractor FOR the current on-disk SQL
            text. The old reader checked extractor_version alone and matched
            by script_name, so an edited-then-reindexed script could be served
            the stale analysis left behind under the OLD key (same version,
            different SQL) — wrong lineage."""
            return (adata.get("extractor_version") == EXTRACTOR_VERSION
                    and adata.get("sql_text") == sql)

        def _lookup_analysis(sname: str, sql: str) -> dict | None:
            """Cache lookup: exact sql-keyed read first, then suffix match
            (workspace-dir-prefixed names). A hit is accepted only when both
            extractor_version AND sql_text match the current script — a stale
            analysis (edited script, old key file still on disk) is rejected
            so L1 never serves lineage for SQL that is no longer there. The
            exact key mirrors folder_index_service's write side and the
            dataflow_service/l2_builder read side."""
            cache_key = hashlib.md5(
                (EXTRACTOR_VERSION + "|" + sname + sql)
                .encode()).hexdigest()[:12]
            exact_path = cache_dir / f"analysis_{cache_key}.json"
            if exact_path.exists():
                try:
                    adata = json.loads(exact_path.read_text())
                except Exception as exc:
                    _log.warning("L1: failed to read analysis cache %s: %s",
                                 exact_path.name, exc)
                    adata = None
                if adata is not None and _analysis_current(adata, sql):
                    return adata
            analysis = analysis_cache_map.get(sname)
            if not analysis:
                for cache_name, cache_data in analysis_cache_map.items():
                    if cache_name.endswith("/" + sname) or cache_name == sname:
                        analysis = cache_data
                        break
            if analysis is not None and _analysis_current(analysis, sql):
                return analysis
            return None

        if len(script_data) < 2:
            # R24: single-script workspace — analyze the one script and feed
            # the SAME all_scripts shape downstream, so L1 gets the full
            # pipeline graph (script node + tables + reads/writes edges +
            # lineage field children), exactly like the multi-script path.
            # The script node must always be present so the user can
            # double-click into L2.
            # C-L1 (2026-08-19 review): the single-script path reuses the
            # SAME cache-aware lookup as the multi-script path — a current
            # cached analysis (exact sql-keyed; extractor_version + sql_text
            # guarded) is served WITHOUT re-extraction; a cache miss falls
            # back to the inline extraction pipeline. Both go through
            # `_build_script_entry` so the entry shape is byte-identical
            # (cache-hit L1 == fresh-extraction L1).
            name, sql = script_data[0]
            from app.extractor.adapter import run_full_analysis
            from app.services.multi_script_service import _build_script_entry
            analysis = _lookup_analysis(name, sql)
            if analysis is None:
                analysis = run_full_analysis(sql, name)
            all_scripts = [_build_script_entry(name, sql, analysis)]
            # J12-10 stage 4: the physical model is built ONCE from the
            # per-script analysis (cache-hit or fresh — the same
            # deterministic dict) and drives L1's tables/fields/aliases —
            # display = pure projection.
            all_scripts[0]["_model"] = build_physical_model(
                analysis, script_name=name)
        else:
            from app.services.multi_script_service import _build_script_entry
            from app.extractor.adapter import run_full_analysis
            # Pass A (>=2 scripts): build the all_scripts entries from the
            # analysis cache when present (version-guarded — mirror of
            # dataflow_service.get_level2_graph), falling back to the full
            # extraction pipeline ONLY on a cache miss. Both paths go
            # through the SAME `_build_script_entry` so the entry shape is
            # byte-identical (cache-hit L1 == fresh-extraction L1).
            all_scripts = []
            for name, sql in script_data:
                # C-H1/C-M1: the version+sql guard lives inside
                # _lookup_analysis — shared by Pass A and Pass B.
                analysis = _lookup_analysis(name, sql)
                if analysis is not None:
                    all_scripts.append(_build_script_entry(name, sql, analysis))
                else:
                    all_scripts.append(_build_script_entry(
                        name, sql, run_full_analysis(sql, name)))

        # ── J12-10 stage 4: per-script physical models ──
        # The physical model IS the extraction-time truth L1 projects from
        # (display = pure projection). Built per script from the analysis
        # cache when available (full extraction truth incl. I4 alias_of),
        # else from the inline extraction pipeline (fresh workspaces — no
        # disk cache yet; the SQL text is right here in script_data, and
        # re-running the same deterministic pipeline gives the identical
        # analysis the cache would have stored). The inline single-script
        # path already attached its model to the script entry.
        # NOTE: the graph-data form of build_physical_model is NOT used —
        # graph edges carry source/target (not source_id/target_id), which
        # the model's Pass 3 cannot read, so graph-backed models lose every
        # edge (fresh-vs-cached L1 divergence). Analysis is the extraction
        # truth; the graph is a display projection.
        # (cache_dir / analysis_cache_map / _lookup_analysis are defined
        # above, shared with Pass A — a cache hit serves the SAME analysis
        # dict to both passes.)

        model_by_script = {}  # script_name → PhysicalModel
        sql_by_name = {n: sql for n, sql in script_data}
        for s in all_scripts:
            sname = s.get("script_name", "")
            model = s.get("_model")
            if model is None:
                # C-M1: Pass B now shares the same version+sql guard as Pass A
                # (it previously accepted any analysis by name alone).
                analysis = _lookup_analysis(sname, sql_by_name.get(sname, ""))
                if analysis is None and sname in sql_by_name:
                    # Fresh workspace (no analysis cache on disk): run the
                    # inline pipeline — the SAME deterministic extraction
                    # the cache would hold, so fresh and cached L1 output
                    # is identical.
                    from app.extractor.adapter import run_full_analysis
                    analysis = run_full_analysis(sql_by_name[sname], sname)
                if analysis is not None:
                    model = build_physical_model(analysis,
                                                 script_name=sname)
            if model is not None:
                model_by_script[sname] = model

        # ── R29 (J12-22): the queried field's DIRECTIONAL flow ──
        # Field queries REPLACE the table-level machinery below entirely:
        # L1 is the queried field's data flow at cross-script scale
        # (scripts + the tables that carry the flow — no field nodes, no
        # intra-script structure, no terminal markers; R29 item 8
        # supersedes R18/R18.1). Table-only searches (field falsy) keep
        # the full table-level behavior (R29 applies to field queries
        # only).
        if field:
            return _build_l1_directional_field_flow(
                all_scripts, model_by_script, table, field, direction)

        nodes = []
        edges = []
        seen_node_ids = set()
        seen_edge_ids = set()

        def add_node(nid, label, ntype, **extra):
            if nid in seen_node_ids:
                return
            seen_node_ids.add(nid)
            d = {"id": nid, "label": label, "type": ntype}
            d.update(extra)
            nodes.append({"data": d})

        def add_edge(src, tgt, label, etype, role=None, roles=None):
            eid = f"{src}->{tgt}"
            if eid in seen_edge_ids:
                # Merge roles if edge already exists
                for e in edges:
                    if e["data"]["id"] == eid:
                        existing = e["data"].get("roles", [])
                        if roles:
                            merged = sorted(set(existing + roles))
                            e["data"]["roles"] = merged
                            e["data"]["role"] = ", ".join(merged)
                        break
                return
            seen_edge_ids.add(eid)
            d = {"id": eid, "source": src, "target": tgt,
                 "label": label, "edge_type": etype}
            if roles:
                d["roles"] = roles
                d["role"] = ", ".join(roles)
            elif role:
                d["roles"] = [role]
                d["role"] = role
            edges.append({"data": d})

        # ── Classify tables (filter out aliases) ──
        # J12-10 stage 4: alias truth comes from the physical model — every
        # alias variable (I4 exact alias_of, or the label-keyed rule for
        # table/view/cte) is recorded as an alias view on its canonical
        # PhysicalTable (PhysicalTable.alias_views). The historical scan
        # over _all_vars ("source_tables[0] != name") also marked every
        # column label (e.g. "so.customer_id") and derived-table name as an
        # alias — harmless junk that never collided with table names, but
        # label reconstruction. The model's alias views are the
        # extraction-time truth (Bug 5 semantics: semantic check only).
        aliases = set()
        for m in model_by_script.values():
            for tbl in m.tables.values():
                for av in tbl.alias_views:
                    aliases.add(av["label"])

        all_inputs = set()
        all_outputs = set()
        for s in all_scripts:
            for t in s.get("input_tables", []):
                if not t.startswith("⟐") and t not in aliases:
                    all_inputs.add(t)
            for t in s.get("output_tables", []):
                if not t.startswith("⟐") and t not in aliases:
                    all_outputs.add(t)

        source_tables = sorted(all_inputs - all_outputs)
        intermediate_tables = sorted(all_inputs & all_outputs)
        output_tables = sorted(all_outputs - all_inputs)

        # ── Add table nodes (skip known SQL aliases: short names) ──
        for tname in source_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            if tname.startswith("⟐"):
                continue  # skip virtual/anonymous tables
            add_node(f"tbl_{tname}", tname, "source_table",
                     table_name=tname)
        for tname in intermediate_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            if tname.startswith("⟐"):
                continue  # skip virtual/anonymous tables
            add_node(f"tbl_{tname}", tname, "intermediate_table",
                     table_name=tname)
        for tname in output_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            # If the "output" is a virtual table from SELECT-only script,
            # still show it but mark as query_output
            ntype = "output_table"
            if tname.startswith("⟐"):
                ntype = "query_output"
            add_node(f"tbl_{tname}", tname, ntype,
                     table_name=tname)

        # ── Add script nodes + edges + role detection ──
        for s in all_scripts:
            sid = s["script_id"]
            sname = s["script_name"]
            inputs = [t for t in s.get("input_tables", []) if not t.startswith("⟐")]
            outputs = [t for t in s.get("output_tables", []) if not t.startswith("⟐")]

            # Detect roles for this script (read-only query over cached analysis)
            graph_data = s.get("graph", {})
            roles = detect_role(graph_data, table, field)

            add_node(sid, sname, "script_node",
                     script_name=sname,
                     total_variables=s.get("total_variables", 0),
                     input_tables=inputs,
                     output_tables=outputs,
                     roles=roles)

            # Directed table↔script edges: table→script (reads) + script→table (writes)
            for tname in inputs:
                tbl_id = f"tbl_{tname}"
                if tbl_id in seen_node_ids:
                    add_edge(tbl_id, sid, tname, "reads_from",
                             roles=roles if roles else None)
            for tname in outputs:
                tbl_id = f"tbl_{tname}"
                if tbl_id in seen_node_ids:
                    add_edge(sid, tbl_id, tname, "writes_to",
                             roles=roles if roles else None)
            
            # If script has inputs but no outputs (SELECT-only query),
            # add a virtual terminal output node so the pipeline is complete
            if inputs and not outputs:
                terminal_name = f"⟐result_{sid[:8]}"
                terminal_id = f"tbl_{terminal_name}"
                add_node(terminal_id, "Query Result", "query_output",
                         table_name=terminal_name)
                add_edge(sid, terminal_id, terminal_name, "writes_to",
                         roles=roles if roles else None)

        # ── V3.2.3: Script-to-script data lineage REMOVED ──
        # Per formal definition §5.1: data flows through variables, not scripts.
        # Edges are table→script (reads) and script→table (writes).
        # Script-to-script connectivity is implicit via shared tables.
        # The table_script edges above already capture this: e.g.
        #   step1 → stg_orders → step3 shows data flow through the variable.


        # ── V3.3: Enrich L1 with compound field children (design §5.1, §4.6) ──
        # J12-10 stage 4: field children are a pure projection of the
        # physical model — one PhysicalField per (table, field), rendered
        # under its owning PhysicalTable (tbl.name, fld.name — no label
        # heuristics). direct/indirect = whether ANY of the field's
        # occurrence var ids is reached by a BFS over the model's edges
        # seeded from every occurrence of any field named `field` — the
        # model's field-identity form of the historical label-suffix seed
        # rule ("name == target_full or name.endswith('.field')"; the
        # visited set is identical — verified on the flagship sample).
        target_full = f"{table}.{field}"
        direct_fields = set()    # (table_name, field_name) on path to target
        indirect_fields = set()  # (table_name, field_name) off-path

        for s in all_scripts:
            m = model_by_script.get(s.get("script_name", ""))
            if m is None:
                continue

            seed_ids = set()
            for fld in m.fields.values():
                if fld.name == field:
                    seed_ids.update(fld.occurrence_ids)

            visited = set(seed_ids)
            if seed_ids:
                # Expand to transitively connected variables via BFS over
                # the model's edges (same endpoints as the dependency
                # graph — the model derives its edges from it, typed once).
                adj = {}
                for e in m.edges:
                    adj.setdefault(e.source_id, set()).add(e.target_id)
                    adj.setdefault(e.target_id, set()).add(e.source_id)
                queue = list(seed_ids)
                while queue:
                    vid = queue.pop(0)
                    for neighbor in adj.get(vid, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

            for tbl in m.tables.values():
                tname = tbl.name
                # Skip ⟐ and empty. Accept any valid table name (even short ones).
                if tname in ("⟐", ""):
                    continue
                for fld in tbl.fields.values():
                    key = (tname, fld.name)
                    if any(occ in visited for occ in fld.occurrence_ids):
                        direct_fields.add(key)
                    else:
                        indirect_fields.add(key)

        # Add field child nodes to table compound nodes
        for (tname, fname) in sorted(direct_fields | indirect_fields):
            tbl_id = f"tbl_{tname}"
            if tbl_id not in seen_node_ids:
                continue
            field_id = f"fld_{tname}_{fname}"
            if field_id in seen_node_ids:
                continue
            seen_node_ids.add(field_id)
            is_direct = (tname, fname) in direct_fields
            is_target = (f"{tname}.{fname}" == target_full)
            field_label = f"★{fname}" if is_target else fname
            field_node = {
                "data": {
                    "id": field_id,
                    "label": field_label,
                    "type": "field",
                    "parent": tbl_id,
                    "field_group": "direct" if is_direct else "indirect",
                    "is_target": is_target,
                    "table_name": tname,
                    "field_name": fname,
                }
            }
            nodes.append(field_node)
        
        # ── Build layer info for pipeline layout ──
        # Longest-path layering (V3.3.10): assign layer = max(predecessor_layers) + 1
        # This produces the correct topological depth for densely-connected graphs.
        # Unlike shortest-path BFS, longest-path ensures nodes appear at their true
        # pipeline depth — all upstream dependencies must be at lower layers.
        #
        # Fixed-point iteration: repeat until no layer changes.
        # Edges go from lower layer → higher layer (forward edges propagate +1).
        # Backward edges (higher→lower, indicating cycles) propagate max+1 to break ties.

        # Build adjacency lists
        adj_forward = {}   # source → [targets]  (forward data flow)
        adj_backward = {}  # target → [sources]  (reverse / backward)
        for e in edges:
            ed = e["data"]
            s = ed["source"]
            t = ed["target"]
            adj_forward.setdefault(s, []).append(t)
            adj_backward.setdefault(t, []).append(s)

        # ── V3.3.15: Simple layer propagation (cap at 10) ──
        # Prevents layer explosion for disconnected components by capping
        # new_layer at MAX_LAYER=10. All nodes stay within visible range.
        MAX_LAYER = 10
        node_layers = {}
        for n in nodes:
            node_layers[n["data"]["id"]] = 0

        # Forward pass: longest-path with cap
        for _ in range(200):
            changed = False
            for n in nodes:
                nid = n["data"]["id"]
                max_pred_layer = -1
                for pred in adj_backward.get(nid, []):
                    if pred in node_layers:
                        max_pred_layer = max(max_pred_layer, node_layers[pred])
                if max_pred_layer >= 0:
                    new_layer = min(max_pred_layer + 1, MAX_LAYER)
                    if node_layers[nid] < new_layer:
                        node_layers[nid] = new_layer
                        changed = True
            if not changed:
                break

        # Reverse pass with cap
        for _ in range(20):
            changed = False
            for nid, lyr in list(node_layers.items()):
                max_neighbor = lyr
                for nb in adj_forward.get(nid, []) + adj_backward.get(nid, []):
                    if nb in node_layers and node_layers[nb] > max_neighbor:
                        max_neighbor = node_layers[nb]
                if max_neighbor > lyr + 1:
                    node_layers[nid] = min(max_neighbor - 1, MAX_LAYER)
                    changed = True
            if not changed:
                break

        # Assign layers to nodes
        for n in nodes:
            nid = n['data']['id']
            n['data']['layer'] = node_layers.get(nid, 0)

        # ── Snake-wrap layout (V3.3.9) ──
        # Interleave tables and scripts by layer — no more separate row groups.
        # Fixes: 2.1 (tables+scripts separated), 2.2 (edges span extreme distances),
        #        2.5 (R→L reversal removed)
        # Always left-to-right; no turn edges.
        
        # Collect top-level nodes (tables + scripts), skip field children
        top_nodes = []
        for n in nodes:
            nd = n["data"]
            t = nd.get("type", "")
            if nd.get("parent") or t == "field":
                continue
            if t.endswith("_table") or t == "script_node" or t == "query_output":
                top_nodes.append(n)
        
        # Sort by layer, then by type (tables before scripts in same layer), then label
        def sort_key(n):
            nd = n["data"]
            t = nd.get("type", "")
            type_priority = 0 if t.endswith("_table") else (1 if t == "script_node" else 2)
            return (nd.get("layer", 999), type_priority, nd.get("label", ""))
        
        top_nodes.sort(key=sort_key)
        
        # Snake-wrap parameters (unified row height for all node types)
        MAX_PER_ROW = 3
        NODE_SPACING = 320
        ROW_HEIGHT = 300
        
        # V3.3.15: Simple layer-based positioning (layers capped at 10).
        # All nodes in same layer share same Y; snake-wrap X within layer.
        for n in top_nodes:
            nd = n["data"]
            layer = nd.get("layer", 0)
            col_in_layer = 0
            for prev in top_nodes:
                if prev is n:
                    break
                if prev["data"].get("layer", 0) == layer:
                    col_in_layer += 1
            
            x = col_in_layer * NODE_SPACING + 100
            y = layer * ROW_HEIGHT + 60
            
            n["data"]["x"] = x
            n["data"]["y"] = y
        
        # Field nodes: positioned relative to parent (offset calculated by frontend)
        for n in nodes:
            nd = n["data"]
            if nd.get("parent"):
                nd["x"] = 0
                nd["y"] = 0

        # ── V3.2.6 field propagation DELETED (J12-10 stage 4) ──
        # The propagation inherited upstream tables' fields into
        # intermediate/output tables with zero fields — display-time proxy
        # synthesis compensating for the L1's column-only scan. The
        # physical model replaces it by construction: every PhysicalField
        # has its owning PhysicalTable (design §1.5 "#8/#9 dissolved"), and
        # DML-target columns are extraction-attributed to the target table
        # (e.g. step4's daily_summary carries cnt/dt/total). Field children
        # are now the model projection above; nothing is copied across
        # tables. (Deleted machinery was deletion-verified by the green L1
        # suite: test_l1_l2_integration.py + tests/test_dataflow/.)

        # ── Pattern 1 fix (Bug 47+39): Single P4-based extraction ──
        # Instead of three independent passes with diverging fallbacks,
        # build all_table_fields once from SCHEMA + DML edges across all
        # scripts, then use it as single source of truth.
        # (PRODUCTION_EDGES imported from app.extractor.lineage at module level)

        # J12-10 stage 4: the P4 table_fields / P5 alias_map
        # reconstructions (_absorb_p4 + the graph-cache scan + the
        # analysis-cache alias fallback) are replaced by the physical
        # models — PhysicalTable.fields are the table_fields truth and
        # PhysicalTable.alias_views are the alias truth (label →
        # canonical table name). One source, no disk-cache passes (C2).
        global_alias_map = {}
        all_table_fields = set()
        for m in model_by_script.values():
            for tbl in m.tables.values():
                for av in tbl.alias_views:
                    canon = m.tables.get(av["canonical_key"])
                    if canon is not None:
                        # dict.update() semantics (last-writer-wins across
                        # scripts) mirror the historical P5 merge.
                        global_alias_map[av["label"]] = canon.name
                for fld in tbl.fields.values():
                    all_table_fields.add((tbl.name, fld.name))

        # Single extraction: run compute_field_lineage per script,
        # intersect reached nodes with all_table_fields
        lineage_field_pairs = set()
        for s in all_scripts:
            gdata = s.get("graph", {})
            if not gdata or not gdata.get("nodes"):
                continue
            try:
                # G2/Bug 37 (pinned): this constrained union — production
                # edges plus SCHEMA — is the shared L1/L2 BFS semantics from
                # the single unified engine (app/extractor/lineage.py,
                # EDGE_SEMANTICS). SCHEMA: reverse (column→table) always
                # follows, forward (table→column) is production-filtered.
                lineage_set = compute_field_lineage(gdata, table, field,
                                                    edge_filter=PRODUCTION_EDGES | {"SCHEMA"})
            except Exception as exc:
                _log.error("compute_field_lineage failed for %s.%s: %s",
                           table, field, exc, exc_info=True)
                continue
            # CW3: shared pair extraction — P1 validation + virtual-table skip
            lineage_field_pairs |= _extract_table_field_pairs(
                lineage_set, gdata.get("nodes", []), global_alias_map,
                valid_table_fields=all_table_fields or None,
                skip_virtual=True)

        # Always include target field
        lineage_field_pairs.add((table, field))

        # Multi-hop expansion (Bug 40) — iterate until stable
        _already_expanded = set()
        round_num = 0
        while round_num < 10:
            round_num += 1
            added = False
            for (tn, fn) in list(lineage_field_pairs):
                if (tn, fn) in _already_expanded:
                    continue
                _already_expanded.add((tn, fn))
                for s in all_scripts:
                    gdata = s.get("graph", {})
                    if not gdata or not gdata.get("nodes"):
                        continue
                    try:
                        lineage_set = compute_field_lineage(gdata, tn, fn,
                                                            edge_filter=PRODUCTION_EDGES | {"SCHEMA"})
                    except Exception as exc:
                        _log.error("compute_field_lineage failed for %s.%s: %s",
                                   tn, fn, exc, exc_info=True)
                        continue
                    # CW3: shared pair extraction — P1 validation, no virtual-table skip
                    for pair in _extract_table_field_pairs(
                            lineage_set, gdata.get("nodes", []),
                            global_alias_map,
                            valid_table_fields=all_table_fields or None):
                        if pair not in lineage_field_pairs:
                            lineage_field_pairs.add(pair)
                            added = True
            if not added:
                break

        return {
            "nodes": nodes,
            "edges": edges,
            "target": f"{table}.{field}",
            "source_tables": source_tables,
            "intermediate_tables": intermediate_tables,
            "output_tables": output_tables,
            "script_count": len(all_scripts),
            "lineage_field_pairs": [list(p) for p in lineage_field_pairs],
            # M4-B: stable frontend contract — `degraded` is always present.
            "degraded": False,
            # R29: the directional marker is always present — table-level
            # graphs are never "flow empty" (the marker only describes the
            # directional field-flow state).
            "flow_empty": False,
        }
    except Exception as exc:
        # M4-B: the degraded fallback must be VISIBLE, not a silent success —
        # flag the response and emit an L1 diagnostic (same `_push` "profile"
        # mechanism as the R16/R17 blocks) so the LogPanel shows the failure
        # while the script-only graph still keeps the UI usable.
        import traceback
        traceback.print_exc()
        nodes = []
        for name in script_names:
            sid = hashlib.md5(name.encode()).hexdigest()[:12]
            nodes.append({"data": {"id": sid, "label": name, "type": "script_node", "script_name": name}})
        try:
            _log.error("L1: degraded fallback for %s.%s (%d scripts): %s",
                       table, field, len(script_names), exc)
            _push_l1_degraded(ws_id, table, field, script_names, exc)
        except Exception:
            pass  # diagnostics must never break the response path
        return {"nodes": nodes, "edges": [], "target": f"{table}.{field}",
                "degraded": True, "flow_empty": False}





