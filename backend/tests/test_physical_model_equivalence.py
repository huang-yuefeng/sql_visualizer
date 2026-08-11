"""J12-10 stage 1 — Physical Model ↔ L2 display equivalence (acceptance).

The physical model (extraction-time structured info, UNUSED in any
response) must be equivalent to the display's compound graph — which the
L2 builder derives from the same inputs. The equivalence is asserted on
the flagship sample (BDM_ACC_LOAN_INFO_SUP_M.sql):

* bijection: every L2 source-table keeper compound ↔ exactly one model
  PhysicalTable (kind="physical") with the same table name;
* field sets: model fields(T) == display keeper fields(T) ∪ the fields
  of T's alias compounds pre-sync (Sync 1 mirrors those onto the keeper
  in the served graph — the union IS the served display);
* edges: every final L2 edge (post simplify/dedup/attach-payload) has a
  model PhysicalEdge witness with the same carried extraction-time info
  (→ same highlight_line by construction), the same type, and matching
  endpoints after the label→entity mapping. DML write legs (routed
  through the display's synthetic ⟐ output) match the model's DML edge
  on (carried, highlight_line, target) — the display reroutes the
  source, the model records the true producer;
* nothing lost: every post-sync display field label on the keepers
  exists in the model's field universe (sync proxies and DML phantoms
  are labels of real model fields).

fin_query4_merge_upsert.sql pins the §9 invariants (merge upsert):
gps_accounts is exactly ONE entity that is both read AND merge_target,
its balance field accumulates occurrences from both sides of the merge,
gps_audit_trail receives the write role, and the alias views (a, t)
resolve to their canonical entities.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import app.services.l2_builder as l2
from app.extractor.adapter import run_full_analysis
from app.extractor.physical_model import build_physical_model
from app.services.graph_service import build_graph_data

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"

FLAGSHIP = "BDM_ACC_LOAN_INFO_SUP_M.sql"
FLAGSHIP_PATH = SAMPLES / "sql_sample_v1" / FLAGSHIP
FIN_Q4 = "fin_query4_merge_upsert.sql"
FIN_Q4_PATH = SAMPLES / "financial" / FIN_Q4


# ── The L2 display pipeline (in-memory, the served phases) ──────────────

def display_pipeline(sql_text, script_name):
    """Run the L2 build phases the equivalence compares against, ending
    right after _attach_flow_payload (pre-sync field sets)."""
    analysis = run_full_analysis(sql_text, script_name)
    graph = build_graph_data(analysis)
    # J12-10 stage 2: the served phases consume the physical model — build
    # it from the same analysis (like _load_or_build_graph's build path).
    model = build_physical_model(analysis, script_name)
    nodes, edges = graph["nodes"], graph["edges"]
    target_ids, direct_ids = l2._compute_target_and_direct_ids(
        nodes, edges, "", "", physical_model=model)
    # J12-10 stage 4: the classification returns (table_nodes,
    # field_nodes, alias_map, occ_to_id) — occ_to_id IS the id_map (the
    # old _build_id_map is gone).
    table_nodes, field_nodes, _alias_map, occ_to_id = (
        l2._classify_compound_nodes(nodes, graph, script_name,
                                    target_ids, direct_ids, None, model))
    id_map = occ_to_id
    new_edges, node_labels = l2._build_edge_list(edges, nodes, id_map,
                                                 sql_text)
    new_edges = l2._combine_edges(new_edges)
    new_edges = l2._promote_field_edges(new_edges, field_nodes)
    new_edges = l2._survive_join_edges(new_edges, graph, id_map,
                                       table_nodes, field_nodes,
                                       node_labels, sql_text, strict=False)
    # J12-10 stage 3: _simplify_dml_edges returns only new_edges — the
    # dml_pairs collection it fed (the sync phase) is gone. Stage 4
    # (J12-15): the per-statement trunk selection consumes the model.
    new_edges = l2._simplify_dml_edges(new_edges, graph, id_map,
                                       table_nodes, field_nodes,
                                       physical_model=model)
    new_edges = l2._dedup_edges(new_edges)
    l2._attach_flow_payload(new_edges, field_nodes, table_nodes=table_nodes)
    return (table_nodes, field_nodes, new_edges, graph, nodes)


# ── Display→model endpoint mapping ──────────────────────────────────────

def compound_key(tn, model):
    """Display compound → model table key. Alias compounds resolve via
    the model's own occurrence index (alias_of vars land on their
    canonical entity; derived-subquery aliases like p2@40 are their own
    (name, context) entities); keepers and CTE compounds by name."""
    if tn is None:
        return None
    t = tn.get("type")
    if t == "alias_table":
        return model.entity_of_id.get(tn.get("original_id"))
    if t in ("source_table", "cte_table"):
        return tn.get("table_name")
    return (model.entity_of_id.get(tn.get("original_id"))
            or (tn.get("table_name"), tn.get("context")))


def display_endpoint(nid, by_tid, by_fid, model):
    if nid in by_tid:
        return (compound_key(by_tid[nid], model), None)
    f = by_fid.get(nid)
    if f is not None:
        return (compound_key(by_tid.get(f.get("parent")), model),
                f.get("label"))
    return None


def endpoint_match(a, b):
    if a is None or b is None:
        return False
    if a[0] != b[0]:
        return False
    if a[1] is not None and b[1] is not None and a[1] != b[1]:
        return False
    return True


def carried_tuple(edge):
    return (edge.get("_src_label"), edge.get("_tgt_label"),
            edge.get("_src_line"), edge.get("_tgt_line"),
            edge.get("_op"))


def model_witness(display_edge, model, src_ref, tgt_ref):
    """A model PhysicalEdge matching (carried, highlight_line, type,
    endpoints). DML write legs exempt the source endpoint — the display
    reroutes it through the synthetic ⟐ output (the write leg's carried
    info and target are the raw DML edge's)."""
    etype = ("DML" if display_edge.get("_dml_origin")
             else display_edge.get("edge_type"))
    carried = carried_tuple(display_edge)
    for M in model.edges:
        if M.edge_type != etype or M.highlight_line != display_edge.get(
                "highlight_line"):
            continue
        if carried_tuple(M.carried) != carried:
            continue
        if endpoint_match(tgt_ref, M.target) and (
                display_edge.get("_dml_origin")
                or endpoint_match(src_ref, M.source)):
            return M
    return None


# ── Flagship: entities ↔ keeper compounds ───────────────────────────────

def flagship():
    return (build_physical_model(run_full_analysis(
        FLAGSHIP_PATH.read_text(encoding="utf-8"), "BDM_ACC_LOAN_INFO_SUP_M")),
        display_pipeline(FLAGSHIP_PATH.read_text(encoding="utf-8"),
                         "BDM_ACC_LOAN_INFO_SUP_M"))


def test_physical_tables_biject_with_display_keepers():
    """13 display source-table keepers ↔ 13 model kind="physical"
    entities, one per name, with identical field sets."""
    model, (table_nodes, field_nodes, *_rest) = flagship()
    keepers = {tn["table_name"]: tn for tn in table_nodes.values()
               if tn.get("type") == "source_table"}
    physicals = {t.name: t for t in model.tables.values()
                 if t.kind == "physical"}
    assert set(keepers) == set(physicals) == {
        "bdm_acc_loan_info", "ods_hub_lsacmsp", "bdm_evt_loan_trans",
        "bdm_gdc_label_fin",
        "ods_cdp_gdc_acct_migrate_to_diff_branches", "ods_hub_ssclmtp",
        "ods_hie_ipblmsp", "ods_hie_ipdcmsp", "ods_hie_ippdcpp",
        "ods_hie_ipacmsp", "bdm_acc_loan_info_sup",
        "bdm_sys_acc_loan_info", "rrcdm_job_log_exec_par"}
    assert len(keepers) == 13


def test_keeper_field_sets_equal_model_union():
    """model fields(T) == display keeper fields(T) ∪ fields of T's alias
    compounds pre-sync — the served graph mirrors the alias fields onto
    the keeper (Sync 1), so the union IS the served display."""
    model, (table_nodes, field_nodes, *_rest) = flagship()
    by_tid = {tn["id"]: tn for tn in table_nodes.values()}
    by_fid = {f["id"]: f for f in field_nodes}
    by_tname = {tn["table_name"]: tn for tn in table_nodes.values()}

    for key, tbl in model.tables.items():
        if tbl.kind != "physical":
            continue
        tn = by_tname[tbl.name]
        keeper_fields = {f["label"] for f in field_nodes
                         if f.get("parent") == tn["id"]}
        alias_fields = set()
        for f in field_nodes:
            p = by_tid.get(f.get("parent"))
            if p is None or p.get("type") != "alias_table":
                continue
            if compound_key(p, model) == key:
                alias_fields.add(f["label"])
        assert set(tbl.fields) == keeper_fields | alias_fields, (
            f"{tbl.name}: model {sorted(tbl.fields)} vs display "
            f"{sorted(keeper_fields | alias_fields)}")


def test_no_unparented_fields_on_flagship():
    """Every field occurrence of the flagship lands on a physical
    table — the model never leaves an ownerless field behind."""
    model, _ = flagship()
    assert model.unparented_fields == []


def test_flagship_field_count_sup():
    """Pinned spec fact: bdm_acc_loan_info_sup carries exactly 24
    physical fields (the L2 keeper shows the same 24 pre-sync)."""
    model, (table_nodes, field_nodes, *_rest) = flagship()
    sup = model.tables["bdm_acc_loan_info_sup"]
    keeper = next(tn for tn in table_nodes.values()
                  if tn.get("type") == "source_table"
                  and tn["table_name"] == "bdm_acc_loan_info_sup")
    keeper_fields = {f["label"] for f in field_nodes
                     if f.get("parent") == keeper["id"]}
    assert len(sup.fields) == 24
    assert keeper_fields == set(sup.fields)


# ── Flagship: edges ─────────────────────────────────────────────────────

def test_every_display_edge_has_model_witness():
    """All 470 final L2 edges (10 types present in this sample) are
    covered by model PhysicalEdges: same carried extraction-time info,
    same highlight_line, same type (or the DML rewrite), matching
    endpoints after label→entity mapping."""
    model, (table_nodes, field_nodes, new_edges, *_rest) = flagship()
    by_tid = {tn["id"]: tn for tn in table_nodes.values()}
    by_fid = {f["id"]: f for f in field_nodes}

    assert len(new_edges) == 470
    uncovered = []
    for E in new_edges:
        src_ref = display_endpoint(E["source"], by_tid, by_fid, model)
        tgt_ref = display_endpoint(E["target"], by_tid, by_fid, model)
        if src_ref is None or tgt_ref is None:
            uncovered.append((E.get("edge_type"), E.get("highlight_line"),
                              "no endpoint"))
            continue
        if model_witness(E, model, src_ref, tgt_ref) is None:
            uncovered.append((E.get("edge_type"), E.get("highlight_line"),
                              carried_tuple(E), src_ref, tgt_ref))
    assert uncovered == []


def test_display_edge_types_present_in_sample():
    model, (table_nodes, field_nodes, new_edges, *_rest) = flagship()
    types = {E.get("edge_type") for E in new_edges}
    assert types == {"SCHEMA", "TABLE_FLOW", "JOIN", "REF", "ALIAS",
                     "FILTER", "COMPUTED", "SUBQUERY", "AGGREGATE",
                     "TRANSFORM"}
    # every display type is a model type with witnesses (the other 6
    # types are pinned by the unit suite's synthetic 16-type test)
    assert types <= {e.edge_type for e in model.edges}


# ── Flagship: the display is a pure projection of the model ─────────────

def test_keeper_field_labels_in_model_universe():
    """J12-10 stage 3: the display shows model entities directly — every
    field label shown on a display keeper exists as a physical field name
    somewhere in the model (the sync mirrors that used to copy labels
    onto keepers are deleted; nothing outside the model may render)."""
    model, (table_nodes, field_nodes, *_rest) = flagship()

    universe = {fld.name for fld in model.fields.values()}
    by_tname = {tn["table_name"]: tn for tn in table_nodes.values()}
    for tbl in model.tables.values():
        if tbl.kind != "physical":
            continue
        tn = by_tname[tbl.name]
        labels = {f["label"] for f in field_nodes
                  if f.get("parent") == tn["id"]}
        assert labels <= universe, (
            f"{tbl.name} labels outside the model universe: "
            f"{sorted(labels - universe)}")


def test_no_proxy_nodes_in_display_output():
    """J12-10 stage 3: the seed_/sync_/dml_ synthetic node synthesis is
    deleted — no proxy ids may appear in the display output (the model
    entities replace them)."""
    model, (table_nodes, field_nodes, new_edges, *_rest) = flagship()
    all_ids = [tn["id"] for tn in table_nodes.values()]
    all_ids += [f["id"] for f in field_nodes]
    proxies = [nid for nid in all_ids
               if nid.startswith(("seed_", "sync_", "dml_"))]
    assert proxies == [], f"proxy node ids in display output: {proxies}"
    edge_ids = [e.get("id") for e in new_edges]
    assert not [eid for eid in edge_ids
                if eid and eid.startswith(("seed_", "sync_", "dml_"))]


# ── fin_query4_merge_upsert: §9 merge invariants ────────────────────────

def fin_q4():
    return build_physical_model(run_full_analysis(
        FIN_Q4_PATH.read_text(encoding="utf-8"), "fin_query4_merge_upsert"))


def test_fin_query4_gps_accounts_single_entity():
    """gps_accounts is exactly ONE physical entity (the merge target is
    one table, not one entity per side of the merge)."""
    model = fin_q4()
    accounts = [t for k, t in model.tables.items()
                if k == "gps_accounts"]
    assert len(accounts) == 1
    tbl = accounts[0]
    assert tbl.kind == "physical"
    assert {"read", "merge_target"} <= tbl.roles
    assert len(tbl.occurrence_ids) >= 3   # read side + merge side + alias


def test_fin_query4_balance_accumulates_both_sides():
    """The balance physical field accumulates occurrences from both
    sides of the merge — multiple occurrence ids spanning the read and
    the merge statements."""
    model = fin_q4()
    balance = model.tables["gps_accounts"].fields.get("balance")
    assert balance is not None
    assert len(balance.occurrence_ids) >= 2
    assert balance.line_first < balance.line_last


def test_fin_query4_gps_audit_trail_write_role():
    """The INSERT INTO gps_audit_trail gives it the write role."""
    model = fin_q4()
    assert "write" in model.tables["gps_audit_trail"].roles
    assert "merge_target" not in model.tables["gps_audit_trail"].roles


def test_fin_query4_alias_views_resolve_to_canonicals():
    """The alias views (a → gps_accounts, t → gps_transactions) resolve
    to their canonical entities and are recorded on them."""
    model = fin_q4()
    accounts = model.tables["gps_accounts"]
    transactions = model.tables["gps_transactions"]
    assert any(v["label"] == "a" for v in accounts.alias_views)
    assert any(v["label"] == "t" for v in transactions.alias_views)
    for view in accounts.alias_views + transactions.alias_views:
        assert model.entity_of_id[view["var_id"]] == view["canonical_key"]
