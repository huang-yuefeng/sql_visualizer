"""Physical model layer (J12-10, stage 1) — extraction-time structured info.

Pipeline: syntax layer (per-occurrence variables + dependency edges) →
PHYSICAL layer (this module) → display layer (L2 compound graph). The
physical model is built at extraction time from the same inputs the L2
builder consumes and is NOT used in any response — stage 1 ships it
alongside the existing pipeline with zero behavior change
(wiki/SOLUTION_DESIGN.md §J12-10, tools/BUG_ANALYSIS_AND_SUGGESTIONS.md
J12-10).

The model is the extraction-time truth the display's compound structure
approximates:

* ONE PhysicalTable per physical table NAME — the qualified name stays
  the key when the SQL qualifies it; unqualified names in one script
  resolve to one key. The display's label-keyed keeper compounds mirror
  this bijectively on kind="physical" (asserted by the equivalence
  test). CTE entities are keyed by name; per-scope containers
  (subquery / virtual / union / ⟐ sentinels) are keyed by (name,
  context) — they are per-scope in the display too.
* Per-occurrence variable types accumulate into per-table role SETS:
  "read" (table/view occurrence), "write" (DML edge into a non-merge
  table target), "merge_target" (MERGE target occurrence), "cte_fed"
  (feeds a CTE entity), "partition" (PARTITION-defined field
  occurrence). One-of typing per occurrence, a set per table — the same
  table can be both read AND merge_target (fin_query4_merge_upsert:
  gps_accounts = {read, merge_target}).
* Alias variables (I4: alias_of carries the exact source var id; the
  label-keyed rule mirrors the L2 fallback for graph-data input) resolve
  to their canonical entity, and the alias views are recorded on the
  entity — nothing is dropped.
* Every original variable id survives as an occurrence id on the
  physical table/field it belongs to — nothing lost (display dedup and
  sync/proxy copies reference these occurrences).
* PhysicalEdges are derived ONCE from the dependency graph, typed with
  the 16 edge types unchanged (compound raw types split per type, Bug 3
  mirror), and carry the extraction-time info the display's highlight
  payload derives from (single_line strategy — the anchor lines match
  by construction).

No patch/reconstruction machinery lives here: everything comes from the
extraction result (never-patch rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.highlight_strategies import FIELD_LIKE_TYPES, get_strategy

# ── Canonical type sets (mirrors of the L2 builder's classification) ──

# l2_builder._classify_compound_nodes: table-like variables become the
# compound parents (alias/subquery/CTE/VT/union/merge-target alike).
TABLE_LIKE_TYPES = frozenset({
    "table", "view", "cte", "subquery", "virtual_table",
    "merge_target", "union_branch",
})

# Computed-value variables use the truncated field label (label[:36]).
COMPUTED_TYPES = frozenset({
    "expression", "aggregate", "window", "case", "transform", "literal",
})

# The 16 edge types (mirror of graph_service.EDGE_TYPE_STYLE).
EDGE_TYPES = frozenset({
    "TABLE_FLOW", "ALIAS", "REF", "AGGREGATE", "TRANSFORM", "WINDOW",
    "COMPUTED", "SCHEMA", "INDIRECT", "FILTER", "JOIN", "CORRELATED",
    "DML", "SET_OP", "SUBQUERY", "SUBSET",
})


# ── Entities ────────────────────────────────────────────────────────────

@dataclass
class PhysicalField:
    """One physical field — key (table_key, name); all occurrence var ids
    that name it accumulate here (per-statement instances merge into the
    one physical field — nothing lost)."""

    name: str                          # display label: the BARE field name
    table_key: str                     # owning PhysicalTable.key
    line_first: int = 0                # first/last occurrence line (var-carried line_start)
    line_last: int = 0
    occurrence_ids: List[str] = dc_field(default_factory=list)
    value_sources: List[str] = dc_field(default_factory=list)  # feeding var ids (raw dep sources)
    uses: List[str] = dc_field(default_factory=list)           # consuming var ids (raw dep targets)

    @property
    def key(self) -> Tuple[str, str]:
        return (self.table_key, self.name)

    @property
    def display_label(self) -> str:
        """Physical field label is the bare field name."""
        return self.name


@dataclass
class PhysicalTable:
    """One physical table (or other table-like container).

    key: the physical name for kind="physical" (the qualified name stays
    the key when the SQL qualifies it; unqualified names in one script
    resolve to one key) and for kind="cte"; (name, context) for the
    per-scope containers (subquery / virtual / union / ⟐ sentinels).

    roles: accumulated from occurrence variable types (read / write /
    merge_target / cte_fed / partition) — one-of typing per occurrence,
    a SET per table.

    alias_views: every alias variable resolving to this table (I4
    alias_of exact source var id, or the label-keyed rule), with the
    alias's own label/line/display label and the canonical key.
    """

    key: str
    name: str                          # raw table name (label)
    kind: str                          # "physical" | "cte" | "virtual" | "subquery" | "union"
    context: str = ""
    roles: Set[str] = dc_field(default_factory=set)
    occurrence_ids: List[str] = dc_field(default_factory=list)
    alias_views: List[Dict[str, Any]] = dc_field(default_factory=list)
    line_first: int = 0
    line_last: int = 0
    fields: Dict[str, PhysicalField] = dc_field(default_factory=dict)

    @property
    def display_label(self) -> str:
        # B5 mirror: the display label drops the internal "⟐ " marker.
        return self.name[2:] if self.name.startswith("⟐ ") else self.name


@dataclass
class PhysicalEdge:
    """One typed data-flow edge between physical fields.

    Endpoints are (table_key, field_name) refs — field may be None for
    table-level raw edges (the endpoints are table-like variables).
    Derived ONCE from the dependency graph; compound raw types are split
    per type (Bug 3 mirror). The carried extraction-time info plus the
    single_line strategy produce the display's anchor line by
    construction (same inputs as l2_builder._attach_flow_payload).
    """

    edge_type: str
    source: Tuple[Optional[str], Optional[str]]   # (table_key, field_name)
    target: Tuple[Optional[str], Optional[str]]
    source_id: str                   # original source var id
    target_id: str                   # original target var id
    source_line: int = 0             # var-carried line_start
    target_line: int = 0
    source_label: str = ""           # raw var label
    target_label: str = ""
    operation: str = ""
    containment: bool = False
    highlight_line: int = 0          # single_line anchor (display mirror)
    flow_kind: str = ""
    reason: str = ""
    carried: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class PhysicalModel:
    """The physical model of one script: entities, fields, edges — plus
    the occurrence index (every original var id — nothing lost)."""

    script_name: str = ""
    tables: Dict[str, PhysicalTable] = dc_field(default_factory=dict)
    fields: Dict[Tuple[str, str], PhysicalField] = dc_field(default_factory=dict)
    edges: List[PhysicalEdge] = dc_field(default_factory=list)
    # parentless field occurrences (var id, field name) — the display
    # shows them without a parent; recorded here, never fabricated.
    unparented_fields: List[Tuple[str, str]] = dc_field(default_factory=list)
    # var id -> table key for every table-like occurrence (incl. aliases)
    entity_of_id: Dict[str, str] = dc_field(default_factory=dict)
    # alias var id -> canonical table key (I4 exact source var id)
    alias_by_var_id: Dict[str, str] = dc_field(default_factory=dict)

    def table(self, key) -> Optional[PhysicalTable]:
        return self.tables.get(key)

    def field(self, key) -> Optional[PhysicalField]:
        return self.fields.get(key)

    def resolve_alias(self, var_id: str) -> Optional[str]:
        """Canonical table key of an alias variable (None when not an
        alias occurrence)."""
        return self.alias_by_var_id.get(var_id)


# ── Input normalization ────────────────────────────────────────────────

_VAR_ATTRS = ("id", "name", "variable_type", "source_columns",
              "source_variables", "source_tables", "alias_of", "defined_in",
              "line_start", "line_end", "context", "is_output")


def _var_to_dict(v: Any) -> Dict[str, Any]:
    if isinstance(v, dict):
        out = dict(v)
    else:
        out = {a: getattr(v, a, None) for a in _VAR_ATTRS}
    if hasattr(out.get("variable_type"), "value"):   # VariableType enum
        out["variable_type"] = out["variable_type"].value
    if not out.get("name") and out.get("label"):     # graph-data form
        out["name"] = out["label"]
    return out


def _dep_to_dict(d: Any) -> Dict[str, Any]:
    if isinstance(d, dict):
        return dict(d)
    return {
        "source_id": d.source_id,
        "target_id": d.target_id,
        "relationship": d.relationship,
        "operation": getattr(d, "operation", ""),
        "containment": bool(getattr(d, "containment", False)),
    }


def _normalize_input(extraction_result,
                     extra_deps: Optional[list] = None
                     ) -> Tuple[List[dict], List[dict], str]:
    """Accept the analysis dict (adapter.run_full_analysis), raw graph
    data (build_graph_data), or the ExtractionResult dataclass — the same
    inputs the L2 builder consumes. The ExtractionResult itself carries
    variables only (the dependency graph is a separate extraction-time
    artifact — pass it via the `dependencies` keyword); edges are empty
    when no dependency info is available."""
    if isinstance(extraction_result, dict):
        if "variables" in extraction_result and "dependencies" in extraction_result:
            return ([_var_to_dict(v) for v in extraction_result["variables"]],
                    [_dep_to_dict(d) for d in extraction_result["dependencies"]],
                    extraction_result.get("script_name", ""))
        if "nodes" in extraction_result and "edges" in extraction_result:
            return ([_var_to_dict(n.get("data", n)) for n in extraction_result["nodes"]],
                    [_dep_to_dict(e.get("data", e)) for e in extraction_result["edges"]],
                    extraction_result.get("script_name", ""))
        raise TypeError(
            "build_physical_model: dict input must be an analysis dict "
            "({'variables', 'dependencies'}) or graph data "
            "({'nodes', 'edges'})")
    if hasattr(extraction_result, "variables"):
        deps = getattr(extraction_result, "dependencies", None)
        if extra_deps is not None:
            deps = extra_deps
        return ([_var_to_dict(v) for v in extraction_result.variables],
                [_dep_to_dict(d) for d in (deps or [])],
                getattr(extraction_result, "script_name", ""))
    raise TypeError(
        f"build_physical_model: unsupported input "
        f"{type(extraction_result).__name__}")


# ── Builder ─────────────────────────────────────────────────────────────

def build_physical_model(extraction_result,
                         script_name: Optional[str] = None,
                         dependencies: Optional[list] = None) -> PhysicalModel:
    """Build the physical model at extraction time from the same inputs
    the L2 builder consumes (analysis dict / graph data / the
    ExtractionResult dataclass + its dependency graph).

    Pure derivation — nothing is written, cached or patched; the model
    IS the extraction-time structured info (never-patch rule).
    """
    vars_, deps, result_name = _normalize_input(extraction_result,
                                                extra_deps=dependencies)
    model = PhysicalModel(script_name=script_name or result_name or "")

    # ── Pass 0: label → canonical-name alias map (L2 mirror) ──
    # l2_builder._classify_compound_nodes rebuilds the alias map from the
    # full graph the same way: table-like vars with exactly one
    # source_table, first-writer-wins per label.
    label_alias_map: Dict[str, str] = {}
    for v in vars_:
        st = v.get("source_tables") or []
        if len(st) == 1 and v.get("variable_type") in TABLE_LIKE_TYPES:
            label_alias_map.setdefault(v.get("name", ""), st[0])

    by_id = {v.get("id"): v for v in vars_ if v.get("id")}

    def _is_alias(v: Dict[str, Any]) -> bool:
        # I4: alias_of is the extraction-time truth (exact source var id).
        # The label-keyed rule is the L2 fallback for graph-data input, but
        # only for table/view/cte vars: subquery/virtual/union vars are
        # derived-table aliases (p2@40 style — no alias_of) or ⟐
        # containers, never aliases of another table (the L2's label-keyed
        # aliasness misfires on them; the model follows the extractor's
        # alias_of truth and keeps them as their own entities).
        if v.get("alias_of"):
            return True
        if v.get("variable_type") not in ("table", "view", "cte"):
            return False
        name = v.get("name", "")
        return name in label_alias_map and label_alias_map[name] != name

    # ── Pass 1: table-like occurrences → entities (aliases resolve) ──
    def _entity_key_of(v: Dict[str, Any]) -> Tuple[Any, str]:
        vt = v.get("variable_type") or ""
        name = v.get("name", "")
        if vt in ("table", "view", "merge_target"):
            return name, "physical"
        if vt == "cte":
            return name, "cte"
        kind = {"virtual_table": "virtual",
                "union_branch": "union"}.get(vt, "subquery")
        return (name, v.get("context") or ""), kind

    def _ensure_table(key, name, kind, context) -> PhysicalTable:
        tbl = model.tables.get(key)
        if tbl is None:
            tbl = PhysicalTable(key=key, name=name, kind=kind,
                                context=context or "")
            model.tables[key] = tbl
        return tbl

    def _add_occurrence(tbl: PhysicalTable, v: Dict[str, Any]) -> None:
        # Per-occurrence one-of typing → per-table role set.
        vt = v.get("variable_type") or ""
        if vt in ("table", "view"):
            tbl.roles.add("read")
        elif vt == "merge_target":
            tbl.roles.add("merge_target")
        vid = v.get("id", "")
        if vid and vid not in tbl.occurrence_ids:
            tbl.occurrence_ids.append(vid)
        line = int(v.get("line_start") or 0)
        if line > 0:
            if not tbl.line_first or line < tbl.line_first:
                tbl.line_first = line
            if line > tbl.line_last:
                tbl.line_last = line

    # 1a: non-alias entities first (aliases resolve onto these)
    alias_vars: List[Dict[str, Any]] = []
    for v in vars_:
        if v.get("variable_type") not in TABLE_LIKE_TYPES:
            continue
        if _is_alias(v):
            alias_vars.append(v)
            continue
        key, kind = _entity_key_of(v)
        tbl = _ensure_table(key, v.get("name", ""), kind,
                            v.get("context") or "")
        _add_occurrence(tbl, v)
        model.entity_of_id[v.get("id", "")] = key

    def _name_to_key(name: str, v: Dict[str, Any]) -> Optional[str]:
        """Entity-name lookup mirroring the L2 parent-resolution
        exact-match loop (context disambiguates same-name per-scope
        containers; first-by-creation is the L2's first-match fallback)."""
        exact = [t for t in model.tables.values() if t.name == name]
        if not exact:
            return None
        if len(exact) == 1:
            return exact[0].key
        ctx = v.get("context") or ""
        for t in exact:
            if t.context == ctx:
                return t.key
        return exact[0].key

    def _resolve_label_chain(label: str, visited: Set[str]) -> Optional[str]:
        """Follow label_alias_map entries to a terminal entity name
        (alias → canonical-name chains; cycles guarded)."""
        seen = set(visited)
        cur = label
        while (cur in label_alias_map and label_alias_map[cur] != cur
               and cur not in seen):
            seen.add(cur)
            cur = label_alias_map[cur]
        return _name_to_key(cur, {})

    def _resolve_alias_key(v: Dict[str, Any],
                           visited: Optional[Set[str]] = None) -> Optional[str]:
        visited = visited or set()
        vid = v.get("id")
        if not vid or vid in visited:
            return None
        visited.add(vid)
        alias_of = v.get("alias_of") or ""
        if alias_of:
            key = model.entity_of_id.get(alias_of)
            if key is not None:
                return key
            src = by_id.get(alias_of)
            if src is not None and src.get("variable_type") in TABLE_LIKE_TYPES:
                key = _resolve_alias_key(src, visited)
                if key is not None:
                    return key
        # label rule (L2 mirror) — graph-data form (no alias_of)
        name = v.get("name", "")
        target = label_alias_map.get(name)
        if target and target != name:
            key = _name_to_key(target, v)
            if key is not None:
                return key
            return _resolve_label_chain(name, visited)
        return None

    # 1b: alias occurrences → canonical entity + alias views
    for v in alias_vars:
        key = _resolve_alias_key(v)
        if key is None:
            # unresolvable alias — its own entity (nothing lost)
            key, kind = _entity_key_of(v)
            tbl = _ensure_table(key, v.get("name", ""), kind,
                                v.get("context") or "")
        else:
            tbl = model.tables[key]
        _add_occurrence(tbl, v)
        vid = v.get("id", "")
        model.entity_of_id[vid] = key
        model.alias_by_var_id[vid] = key
        line = int(v.get("line_start") or 0)
        label = v.get("name", "")
        tbl.alias_views.append({
            "var_id": vid,
            "label": label,
            "line_start": line,
            "display_label": f"{label}@{line}" if line > 0 else label,
            "canonical_key": key,
        })

    # ── Pass 2: field-like occurrences → PhysicalFields ──
    first_key = next(iter(model.tables), None)

    def _field_name(v: Dict[str, Any]) -> str:
        # Display label mirrors (l2_builder._classify_compound_nodes):
        # columns keep the bare field part — the column branch is vt-based
        # OR exactly one dot (multi-dot labels like
        # 'CONCAT(a.iidcptl, a.iibrabl, a.iidcno)' are computed and take
        # the truncated label) — computed values truncate at 36 chars.
        vt = v.get("variable_type") or ""
        label = v.get("name", "")
        if vt in ("column", "cte_column") or label.count(".") == 1:
            return label.rsplit(".", 1)[-1] if "." in label else label
        if vt in COMPUTED_TYPES:
            return label[:36] if len(label) > 36 else label
        return (label[:36] if len(label) > 36 else label) + " ·"

    def _resolve_owner(v: Dict[str, Any]) -> Optional[str]:
        """Owner resolution mirroring the L2 parent resolution: exact
        entity-name match first, then the alias map (I2 columns carry
        canonical names already; derived aliases resolve to themselves)."""
        st = v.get("source_tables") or []
        if not st or not st[0]:
            return None
        src = st[0]
        key = _name_to_key(src, v)
        if key is not None:
            return key
        if src in label_alias_map and label_alias_map[src] != src:
            key = _name_to_key(label_alias_map[src], v)
            if key is not None:
                return key
            return _resolve_label_chain(src, set())
        return None

    def _add_field_occurrence(fld: PhysicalField, v: Dict[str, Any]) -> None:
        vid = v.get("id", "")
        if vid and vid not in fld.occurrence_ids:
            fld.occurrence_ids.append(vid)
        line = int(v.get("line_start") or 0)
        if line > 0:
            if not fld.line_first or line < fld.line_first:
                fld.line_first = line
            if line > fld.line_last:
                fld.line_last = line
        if (v.get("defined_in") or "").upper() == "PARTITION":
            tbl = model.tables.get(fld.table_key)
            if tbl is not None:
                tbl.roles.add("partition")

    for v in vars_:
        if v.get("variable_type") in TABLE_LIKE_TYPES:
            continue
        fname = _field_name(v)
        owner = _resolve_owner(v)
        if owner is None:
            if v.get("variable_type") in COMPUTED_TYPES and first_key is not None:
                # L2 mirror: computed vars without a source table attach
                # to the first table node (fallback branch).
                owner = first_key
            else:
                model.unparented_fields.append((v.get("id", ""), fname))
                continue
        fld = model.fields.get((owner, fname))
        if fld is None:
            fld = PhysicalField(name=fname, table_key=owner)
            model.fields[(owner, fname)] = fld
            tbl = model.tables.get(owner)
            if tbl is not None:
                tbl.fields[fname] = fld
        _add_field_occurrence(fld, v)

    # ── Pass 3: dependency edges → PhysicalEdges (typed, once) ──
    def _var_ref(v: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        vt = v.get("variable_type") or ""
        if vt in TABLE_LIKE_TYPES:
            return model.entity_of_id.get(v.get("id", "")), None
        fname = _field_name(v)
        owner = _resolve_owner(v)
        if owner is None and vt in COMPUTED_TYPES and first_key is not None:
            owner = first_key
        if owner is None:
            return None, fname
        return owner, fname

    def _carried(src_nd: Dict[str, Any], tgt_nd: Dict[str, Any],
                 raw_edge: Dict[str, Any]) -> Dict[str, Any]:
        """Mirror of l2_builder._carry_edge_info — the extraction-time
        info the single_line payload derives from (W5/R25). Identical
        inputs → identical carried info → identical anchor lines."""
        src_vt = src_nd.get("variable_type", "")
        tgt_vt = tgt_nd.get("variable_type", "")
        src_tables = src_nd.get("source_tables") or []
        tgt_tables = tgt_nd.get("source_tables") or []
        src_label = src_nd.get("name", "") or src_nd.get("label", "")
        tgt_label = tgt_nd.get("name", "") or tgt_nd.get("label", "")

        def _owner(tables, label):
            return (tables[0] if tables
                    else (label.rsplit(".", 1)[0] if "." in label else ""))

        def _canon(tables, label):
            return (tables[0] if tables
                    else (label.rsplit(".", 1)[0] if "." in label else label))

        return {
            "_src_line": int(src_nd.get("line_start") or 0),
            "_tgt_line": int(tgt_nd.get("line_start") or 0),
            "_src_label": src_label,
            "_tgt_label": tgt_label,
            "_src_vt": src_vt,
            "_tgt_vt": tgt_vt,
            "_src_tables": list(src_tables),
            "_tgt_tables": list(tgt_tables),
            "_op": raw_edge.get("operation", ""),
            "_src_field_like": (src_vt in FIELD_LIKE_TYPES
                                or (src_nd.get("defined_in") or "").upper()
                                == "PARTITION"),
            "_src_is_vt": src_vt in ("virtual_table", "subquery",
                                     "union_branch"),
            "_tgt_is_vt": tgt_vt in ("virtual_table", "subquery",
                                     "union_branch"),
            "_src_owner": _owner(src_tables, src_label),
            "_tgt_canon": _canon(tgt_tables, tgt_label),
        }

    def _make_edge(et: str, sref, tref, svar, tvar, dep) -> PhysicalEdge:
        carried = _carried(svar, tvar, dep)
        payload = get_strategy("single_line")({"edge_type": et, **carried})
        return PhysicalEdge(
            edge_type=et,
            source=sref,
            target=tref,
            source_id=svar.get("id", ""),
            target_id=tvar.get("id", ""),
            source_line=int(svar.get("line_start") or 0),
            target_line=int(tvar.get("line_start") or 0),
            source_label=svar.get("name", "") or svar.get("label", ""),
            target_label=tvar.get("name", "") or tvar.get("label", ""),
            operation=dep.get("operation", ""),
            containment=bool(dep.get("containment", False)),
            highlight_line=payload["highlight_line"],
            flow_kind=payload["flow_kind"],
            reason=payload["reason"],
            carried=carried,
        )

    for dep in deps:
        svar = by_id.get(dep.get("source_id") or "")
        tvar = by_id.get(dep.get("target_id") or "")
        if svar is None or tvar is None:
            continue
        sref = _var_ref(svar)
        tref = _var_ref(tvar)
        rel = (dep.get("relationship") or dep.get("edge_type") or "REF").strip()
        etypes = ([t.strip() for t in rel.split(",")] if "," in rel else [rel])
        for et in etypes:
            if not et:
                continue
            model.edges.append(_make_edge(et, sref, tref, svar, tvar, dep))
            # edge-derived roles: write (DML into a non-merge table
            # target) and cte_fed (feeds a CTE entity).
            tvt = tvar.get("variable_type") or ""
            if et == "DML" and tvt in ("table", "view"):
                tkey = model.entity_of_id.get(tvar.get("id", ""))
                if tkey is not None and tkey in model.tables:
                    model.tables[tkey].roles.add("write")
            tkey = model.entity_of_id.get(tvar.get("id", ""))
            if tkey is not None and model.tables[tkey].kind == "cte":
                skey = model.entity_of_id.get(svar.get("id", ""))
                if skey is not None and skey in model.tables:
                    model.tables[skey].roles.add("cte_fed")
        # field-level value sources / uses from the raw dependency
        # endpoints: the source field is USED by the target var; the
        # target field is FED by the source var (raw var ids — nothing
        # lost, duplicates guarded per field).
        if sref[1] is not None:
            sfld = model.fields.get(sref)
            if sfld is not None and tvar.get("id", "") not in sfld.uses:
                sfld.uses.append(tvar.get("id", ""))
        if tref[1] is not None:
            tfld = model.fields.get(tref)
            if tfld is not None and svar.get("id", "") not in tfld.value_sources:
                tfld.value_sources.append(svar.get("id", ""))

    return model
