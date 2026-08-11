"""Walkable-set contract invariant (code-review 2026-08-06 item 4 —
RC-1 hardening).

Pins app/extractor/walkable_set.py to the STRICT walker's effective
behavior, so a change on either side fails here instead of drifting:

  1. Synthetic per-type probes: a seed field adjacent to a probe node
     via ONE edge of each of the 16 types admits the probe node iff the
     contract classifies the type FIELD_WALKABLE or CONDITIONAL. The
     canonical probe shape satisfies every CONDITIONAL rule (ALIAS via
     source_tables match, FILTER/JOIN via the seed zone, DML forward,
     TABLE_FLOW via the seed's identity in the chain), so the probe
     measures "walkable at all" vs "never walkable" — the walker's
     elif-chain, measured, not re-read.
  2. lineage.FIELD_LAND == the contract's FIELD_WALKABLE (the literal
     set the walker consumes matches the contract).
  3. Flagship sample: every edge type the dependency builder and the
     display graph emit is contract-known (ALL_EDGE_TYPES), and the
     walker closure runs over it.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor import walkable_set as ws
from app.extractor.adapter import run_full_analysis
from app.extractor.dependency_graph import build_dependency_graph
from app.extractor.lineage import FIELD_LAND, compute_field_flow
from app.extractor.physical_model import build_physical_model
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.services.graph_service import build_graph_data

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"

TARGET_TABLE = "t"
TARGET_FIELD = "f"

ALL16 = [
    "TABLE_FLOW", "ALIAS", "REF", "AGGREGATE", "TRANSFORM", "WINDOW",
    "COMPUTED", "SCHEMA", "INDIRECT", "FILTER", "JOIN", "CORRELATED",
    "DML", "SET_OP", "SUBQUERY", "SUBSET",
]


def _canonical_graph(edge_type):
    """Seed field s of table t, probe column n, one edge s→n of type T.
    See module docstring — admission measures walkable vs never-walked.
    A table entity (t1) is present so the model attaches the field."""
    nodes = [
        {"id": "t1", "label": TARGET_TABLE, "variable_type": "table",
         "table_name": TARGET_TABLE, "context": "TOP0"},
        {"id": "s", "label": TARGET_FIELD, "variable_type": "column",
         "context": "TOP0", "source_tables": [TARGET_TABLE]},
        {"id": "n", "label": "g", "variable_type": "column",
         "context": "TOP0", "source_tables": [TARGET_TABLE]},
    ]
    edges = [{"source": "s", "target": "n", "edge_type": edge_type}]
    return {"nodes": nodes, "edges": edges}


def _admitted(edge_type):
    graph = _canonical_graph(edge_type)
    pm = build_physical_model(graph)
    cl = compute_field_flow(graph, TARGET_TABLE, TARGET_FIELD,
                            physical_model=pm)
    return "n" in cl


def test_contract_partition_and_bridge_palette():
    assert ws.ALL_EDGE_TYPES == frozenset(ALL16)
    assert not (ws.FIELD_WALKABLE & ws.CONDITIONAL)
    assert not (ws.FIELD_WALKABLE & ws.NEVER_WALKED)
    assert not (ws.CONDITIONAL & ws.NEVER_WALKED)
    # Bridge palette: every emitted type is classified by the contract,
    # and only SUBSET (the honest physical-bridge fallback) is never-
    # walked.
    assert ws.BRIDGE_EMIT_TYPES <= ws.ALL_EDGE_TYPES
    assert ws.BRIDGE_EMIT_TYPES & ws.NEVER_WALKED == {"SUBSET"}
    assert ws.BRIDGE_EMIT_TYPES & ws.FIELD_WALKABLE == {"REF"}
    assert (ws.BRIDGE_EMIT_TYPES & ws.CONDITIONAL
            == {"FILTER", "JOIN", "DML", "TABLE_FLOW"})


def test_contract_matches_walker_behavior_per_type():
    for et in ALL16:
        admitted = _admitted(et)
        contract_walkable = (et in ws.FIELD_WALKABLE or et in ws.CONDITIONAL)
        assert admitted == contract_walkable, (
            f"walker {'admits' if admitted else 'rejects'} {et} but the "
            f"contract classifies it "
            f"{'never-walked' if contract_walkable else 'walkable'}")


def test_ref_read_narrows_to_field_holder():
    # REF/READ (field → its owning table) is still FIELD_WALKABLE from
    # the field side — the narrowing never un-walks the type itself.
    graph = _canonical_graph("REF")
    graph["edges"][0]["operation"] = "READ"
    pm = build_physical_model(graph)
    cl = compute_field_flow(graph, TARGET_TABLE, TARGET_FIELD,
                            physical_model=pm)
    assert "n" in cl


def test_field_land_matches_contract():
    # The strict walker's literal set equals the contract's walkable set.
    assert FIELD_LAND == ws.FIELD_WALKABLE


def test_flagship_emits_only_contract_types():
    sql = (SAMPLES / "sql_sample_v1"
           / "BDM_ACC_LOAN_INFO_SUP_M.sql").read_text()
    res = extract_variables_from_sql(sql, "BDM_ACC_LOAN_INFO_SUP_M.sql")
    deps = build_dependency_graph(res, sql)
    rels = {d.relationship for d in deps}
    assert rels <= ws.ALL_EDGE_TYPES, f"unknown edge types: {rels - ws.ALL_EDGE_TYPES}"
    # The flagship exercises every conditional bridge type (the Phase-8
    # palette minus SUBSET, which this script does not need).
    assert {"REF", "FILTER", "JOIN", "DML", "TABLE_FLOW"} <= rels

    analysis = run_full_analysis(sql, "BDM_ACC_LOAN_INFO_SUP_M.sql")
    graph = build_graph_data(analysis)
    gtypes = {e["data"]["relationship"] for e in graph["edges"]}
    assert gtypes <= ws.ALL_EDGE_TYPES, \
        f"unknown display edge types: {gtypes - ws.ALL_EDGE_TYPES}"
    # The walker runs on the flagship over contract-classified edges.
    model = build_physical_model(analysis, "BDM_ACC_LOAN_INFO_SUP_M.sql")
    cl = compute_field_flow(graph, "bdm_acc_loan_info_sup", "data_dt",
                            physical_model=model)
    assert cl, "flagship closure must be non-empty"
    assert cl <= {n["data"]["id"] for n in graph["nodes"]}
