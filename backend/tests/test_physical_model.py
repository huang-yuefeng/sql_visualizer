"""J12-10 stage 1 — Physical Model Layer unit tests.

The physical model (app/extractor/physical_model.py) is the
extraction-time structured info the display's compound graph
approximates: one PhysicalTable per physical name, roles accumulated
from per-occurrence variable types, alias views resolved to their
canonical entity, every original var id preserved as an occurrence id
(nothing lost), and one typed PhysicalEdge per raw dependency (all 16
edge types, compound raw types split).

These unit tests pin the entity contract with synthetic graph-data
inputs (the build_graph_data form) plus one real-extractor test of the
ExtractionResult dataclass form.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.extractor.physical_model import (
    EDGE_TYPES,
    PhysicalModel,
    build_physical_model,
)
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph


# ── Fixture helpers (graph-data form: nodes carry label, not name) ──────

def _graph(vars_, edges=None):
    """One graph-data dict in the build_graph_data shape."""
    return {"nodes": vars_, "edges": edges or [], "script_name": "unit.sql"}


def _tbl(var_id, label, line=1, source_tables=None, vt="table",
         context="TOP0", alias_of=None):
    node = {
        "id": var_id, "label": label, "variable_type": vt,
        "source_tables": list(source_tables or []),
        "defined_in": "SELECT", "line_start": line, "line_end": line,
        "context": context, "is_output": False,
    }
    if alias_of is not None:
        node["alias_of"] = alias_of
    return node


def _col(var_id, label, table, line=3, vt="column", context="TOP0",
         defined_in="SELECT"):
    return {
        "id": var_id, "label": label, "variable_type": vt,
        "source_tables": [table],
        "defined_in": defined_in, "line_start": line, "line_end": line,
        "context": context, "is_output": False,
    }


def _dep(src, tgt, rel, op="", containment=False):
    return {"source_id": src, "target_id": tgt, "relationship": rel,
            "operation": op, "containment": containment}


# ── Entities: one per physical name ─────────────────────────────────────

def test_one_entity_per_physical_name():
    """Same-name table occurrences in different contexts merge into ONE
    physical table (per-statement instances are not separate entities)."""
    model = build_physical_model(_graph([
        _tbl("t1a", "t1", line=1, context="TOP0"),
        _tbl("t1b", "t1", line=9, context="TOP1"),
        _col("c1", "t1.f", "t1", line=2, context="TOP0"),
        _col("c2", "t1.f", "t1", line=10, context="TOP1"),
    ]))
    assert list(model.tables) == ["t1"]
    tbl = model.tables["t1"]
    assert tbl.name == "t1" and tbl.kind == "physical"
    assert tbl.occurrence_ids == ["t1a", "t1b"]
    # both field occurrences merge into the one physical field
    assert list(tbl.fields) == ["f"]
    assert tbl.fields["f"].occurrence_ids == ["c1", "c2"]


def test_qualified_name_is_distinct_key():
    """The qualified name stays its own key when the SQL qualifies it."""
    model = build_physical_model(_graph([
        _tbl("u1", "t1", line=1),
        _tbl("q1", "db.t1", line=5),
    ]))
    assert set(model.tables) == {"t1", "db.t1"}
    assert model.tables["db.t1"].name == "db.t1"


def test_roles_accumulate_read_and_merge_target():
    """Per-occurrence one-of typing accumulates into a per-table SET —
    one table can be read AND merge_target in the same script."""
    model = build_physical_model(_graph([
        _tbl("r1", "gps_accounts", line=2),                       # read
        _tbl("m1", "gps_accounts", line=40, vt="merge_target"),   # merge
    ]))
    assert model.tables["gps_accounts"].roles == {"read", "merge_target"}


def test_view_occurrence_also_reads():
    model = build_physical_model(_graph([
        _tbl("v1", "v_src", line=3, vt="view"),
    ]))
    assert model.tables["v_src"].roles == {"read"}


# ── Alias views ─────────────────────────────────────────────────────────

def test_alias_of_resolves_to_canonical_entity():
    """I4: alias_of carries the exact source var id — the alias resolves
    to the canonical entity and is recorded as an alias view."""
    model = build_physical_model(_graph([
        _tbl("real1", "bdm_acc_loan_info", line=1),
        _tbl("a1", "p1", line=29, alias_of="real1"),
    ]))
    tbl = model.tables["bdm_acc_loan_info"]
    assert model.entity_of_id["a1"] == "bdm_acc_loan_info"
    assert model.alias_by_var_id["a1"] == "bdm_acc_loan_info"
    assert model.resolve_alias("a1") == "bdm_acc_loan_info"
    views = tbl.alias_views
    assert len(views) == 1
    assert views[0]["label"] == "p1"
    assert views[0]["display_label"] == "p1@29"
    assert views[0]["canonical_key"] == "bdm_acc_loan_info"
    # the alias occurrence's id survives on the canonical table
    assert "a1" in tbl.occurrence_ids


def test_alias_of_chain_resolves():
    """alias → alias → canonical chains resolve through the visited-set
    guarded recursion."""
    model = build_physical_model(_graph([
        _tbl("real1", "real", line=1),
        _tbl("b1", "b", line=5, alias_of="real1"),
        _tbl("a1", "a", line=9, alias_of="b1"),
    ]))
    assert model.entity_of_id["a1"] == "real"
    assert model.resolve_alias("a1") == "real"
    assert [v["label"] for v in model.tables["real"].alias_views] == ["b", "a"]


def test_label_keyed_alias_rule_graph_form():
    """Graph-data form (no alias_of): table-like vars with exactly one
    source_table resolve via the label-keyed first-writer-wins rule."""
    model = build_physical_model(_graph([
        _tbl("real1", "real", line=1, source_tables=["real"]),
        _tbl("t1", "t1", line=5, source_tables=["real"]),
    ]))
    assert model.entity_of_id["t1"] == "real"
    assert "t1" in model.tables["real"].alias_views[0]["var_id"]


def test_derived_subquery_alias_stays_own_entity():
    """The flagship regression: derived-table aliases (p2@40 style —
    subquery vt, NO alias_of) are their own (name, context) entities;
    the label-keyed alias rule never fires on subquery/virtual/union
    vars (it would misfire and merge them into a same-named keeper)."""
    model = build_physical_model(_graph([
        _tbl("sup1", "bdm_acc_loan_info_sup", line=199),
        _tbl("p2a", "p2", line=40, vt="subquery", context="CTE{a}/subq1",
             source_tables=["p2"]),
        _tbl("p2b", "p2", line=199, vt="subquery", context="TOP0",
             source_tables=[]),
        _col("f1", "p2.poctcd", "p2", line=41, vt="cte_column",
             context="CTE{a}/subq1"),
    ]))
    assert model.entity_of_id["p2a"] == ("p2", "CTE{a}/subq1")
    assert model.entity_of_id["p2b"] == ("p2", "TOP0")
    # p2@199's subquery fields stay with the subquery entity, NOT the keeper
    assert "poctcd" not in model.tables["bdm_acc_loan_info_sup"].fields
    subq = model.tables[("p2", "CTE{a}/subq1")]
    assert "poctcd" in subq.fields
    # the sup keeper is not an alias of anything and keeps no p2 fields
    assert "p2" not in model.tables["bdm_acc_loan_info_sup"].alias_views


# ── Fields ──────────────────────────────────────────────────────────────

def test_field_value_sources_and_uses():
    """PhysicalField.value_sources = feeding var ids (raw dep sources);
    .uses = consuming var ids (raw dep targets)."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "t1.b", "t1", line=3),
    ], [_dep("f1", "f2", "REF", op="COPY")]))
    assert model.fields[("t1", "a")].uses == ["f2"]
    assert model.fields[("t1", "b")].value_sources == ["f1"]


def test_occurrence_ids_preserved_nothing_lost():
    """Every original var id survives — merged field instances and
    table occurrences alike."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "t1.a", "t1", line=2, context="TOP0"),
        _col("f2", "t1.a", "t1", line=9, context="TOP1"),
    ]))
    fld = model.fields[("t1", "a")]
    assert fld.occurrence_ids == ["f1", "f2"]
    assert fld.line_first == 2 and fld.line_last == 9
    assert fld.display_label == "a"


def test_field_label_rules():
    """Display-label mirrors: columns keep the bare field part (vt-based
    or exactly one dot); computed values truncate at 36 chars."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "x.y.z", "t1", line=3, vt="column"),
        _col("f3", "c.f", "t1", line=4, vt="cte_column"),
        _col("f4", "CONCAT(a.iidcptl, a.iibrabl, a.iidcno)", "t1",
             line=5, vt="expression"),
        _col("f5", "ROUND(SUM(amount) OVER (PARTITION BY acct_no))", "t1",
             line=6, vt="aggregate"),
    ]))
    tbl = model.tables["t1"]
    assert tbl.fields["a"].name == "a"
    assert tbl.fields["z"].name == "z"          # vt column → bare part
    assert tbl.fields["f"].name == "f"          # cte_column → bare part
    # 3-dot expression is computed → truncated 36
    assert "CONCAT" in tbl.fields["CONCAT(a.iidcptl, a.iibrabl, a.iidcn"].name
    assert len(tbl.fields["CONCAT(a.iidcptl, a.iibrabl, a.iidcn"].name) == 36
    trunc = tbl.fields["ROUND(SUM(amount) OVER (PARTITION BY"]
    assert len(trunc.name) == 36


def test_unparented_fields_recorded_not_fabricated():
    """A column with no resolvable owner is recorded as unparented —
    never guessed onto a table."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "orphan", "", line=2),
    ]))
    assert model.unparented_fields == [("f1", "orphan")]
    assert ("t1", "orphan") not in model.fields


def test_computed_field_falls_back_to_first_entity():
    """L2 mirror: computed vars without a source table attach to the
    first table node (fallback branch)."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "amount * rate", "", line=2, vt="transform"),
    ]))
    assert ("t1", "amount * rate") in model.fields


# ── Keys by container kind ──────────────────────────────────────────────

def test_cte_keyed_by_name_subquery_by_context():
    """CTE entities are keyed by name (one per script); per-scope
    containers (subquery/virtual/union) are keyed by (name, context)."""
    model = build_physical_model(_graph([
        _tbl("c1", "cte_x", line=1, vt="cte", context="TOP0"),
        _tbl("c2", "cte_x", line=20, vt="cte", context="TOP1"),
        _tbl("s1", "s", line=3, vt="subquery", context="TOP0/sub1"),
        _tbl("s2", "s", line=12, vt="subquery", context="TOP0/sub2"),
        _tbl("o1", "⟐ output", line=5, vt="virtual_table", context="TOP0"),
    ]))
    assert [t.kind for t in model.tables.values()].count("cte") == 1
    assert len([k for k in model.tables if k == "cte_x"]) == 1
    assert model.tables[("s", "TOP0/sub1")].kind == "subquery"
    assert model.tables[("s", "TOP0/sub2")].kind == "subquery"
    out = model.tables[("⟐ output", "TOP0")]
    assert out.kind == "virtual"
    assert out.display_label == "output"   # B5: "⟐ " marker stripped


# ── Edge typing ─────────────────────────────────────────────────────────

def test_all_17_edge_types_preserved():
    """One PhysicalEdge per raw dependency, all 17 edge types unchanged."""
    vars_ = [
        _tbl("t1", "t1", line=1),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "t1.b", "t1", line=3),
    ]
    deps = [_dep("f1", "f2", et) for et in sorted(EDGE_TYPES)]
    model = build_physical_model(_graph(vars_, deps))
    assert {e.edge_type for e in model.edges} == set(EDGE_TYPES)
    assert len(model.edges) == 17
    for et in EDGE_TYPES:
        edge = next(e for e in model.edges if e.edge_type == et)
        assert edge.source == ("t1", "a")
        assert edge.target == ("t1", "b")
        assert edge.source_id == "f1" and edge.target_id == "f2"


def test_compound_raw_type_splits_per_type():
    """Bug 3 mirror: compound raw relationships split into separate
    edges before typing — no compound types in the model."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "t1.b", "t1", line=3),
    ], [_dep("f1", "f2", "TABLE_FLOW,REF", op="COPY")]))
    assert sorted(e.edge_type for e in model.edges) == ["REF", "TABLE_FLOW"]
    assert len(model.edges) == 2


def test_edge_endpoints_table_level_allow_none_field():
    """Table-to-table raw edges carry (table_key, None) endpoints."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _tbl("t2", "t2", line=5),
    ], [_dep("t1", "t2", "TABLE_FLOW")]))
    assert model.edges[0].source == ("t1", None)
    assert model.edges[0].target == ("t2", None)


def test_edge_payload_matches_single_line_anchor_rules():
    """highlight_line/flow_kind are the display's own payload by
    construction — DML anchors at the write line (target), SCHEMA at the
    member line (target), chains at the source line."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _tbl("t2", "t2", line=20),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "t2.b", "t2", line=21),
    ], [
        _dep("f1", "f2", "SCHEMA", op="TABLE_COLUMN"),
        _dep("f1", "t2", "DML", op="INSERT"),
        _dep("t1", "t2", "TABLE_FLOW"),
    ]))
    by_type = {e.edge_type: e for e in model.edges}
    assert by_type["SCHEMA"].highlight_line == 21      # member line
    assert by_type["SCHEMA"].flow_kind == "structure"
    assert by_type["DML"].highlight_line == 20         # write line
    assert by_type["DML"].flow_kind == "write"
    assert by_type["TABLE_FLOW"].highlight_line == 1   # chain src line


def test_containment_flag_carried():
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _tbl("o1", "⟐ nested", line=2, vt="virtual_table", context="TOP0"),
    ], [_dep("t1", "o1", "SCHEMA", containment=True)]))
    assert model.edges[0].containment is True


# ── Roles from edges ────────────────────────────────────────────────────

def test_write_cte_fed_partition_roles():
    """write: DML into a non-merge table target; cte_fed: feeding a CTE
    entity; partition: PARTITION-defined field occurrence."""
    model = build_physical_model(_graph([
        _tbl("t1", "t1", line=1),
        _tbl("t2", "t2", line=10),
        _tbl("cte1", "cte_x", line=5, vt="cte"),
        _col("f1", "t1.a", "t1", line=2),
        _col("f2", "t2.b", "t2", line=11, defined_in="PARTITION"),
        _col("f3", "cte_x.c", "cte_x", line=6, vt="cte_column"),
    ], [
        _dep("f1", "t2", "DML", op="INSERT"),
        _dep("t1", "cte1", "TABLE_FLOW"),
    ]))
    assert "write" in model.tables["t2"].roles
    assert "write" not in model.tables["t1"].roles
    assert "cte_fed" in model.tables["t1"].roles
    assert "partition" in model.tables["t2"].roles


def test_merge_target_write_is_not_merged():
    """A MERGE target is merge_target, never 'write' — the write role is
    for DML into plain table/view targets only."""
    model = build_physical_model(_graph([
        _tbl("m1", "tgt", line=10, vt="merge_target"),
        _col("f1", "tgt.b", "tgt", line=11, vt="column"),
    ], [_dep("f1", "m1", "DML", op="MERGE")]))
    assert model.tables["tgt"].roles == {"merge_target"}


# ── Input forms ─────────────────────────────────────────────────────────

def test_extraction_result_dataclass_form():
    """The ExtractionResult dataclass (enum variable_types) works; the
    dependency graph is passed separately (the extraction result itself
    carries variables only)."""
    sql = "SELECT a.col FROM tbl a WHERE a.col > 1;"
    result = extract_variables_from_sql(sql, "tiny.sql")
    deps = build_dependency_graph(result, sql)
    model = build_physical_model(result, dependencies=deps)
    assert isinstance(model, PhysicalModel)
    assert "tbl" in model.tables
    assert model.tables["tbl"].kind == "physical"
    assert model.edges          # dependencies reached the model
    # bare ExtractionResult (no dependency info) → entities only
    bare = build_physical_model(result)
    assert "tbl" in bare.tables
    assert bare.edges == []


def test_analysis_dict_form():
    """The adapter.run_full_analysis dict form ({variables,
    dependencies}) is accepted directly."""
    from app.extractor.adapter import run_full_analysis
    analysis = run_full_analysis("SELECT 1 AS one;", "tiny2.sql")
    model = build_physical_model(analysis)
    assert isinstance(model, PhysicalModel)
    assert model.script_name == "tiny2.sql"


def test_unknown_input_raises_type_error():
    with pytest.raises(TypeError):
        build_physical_model("not an extraction result")
