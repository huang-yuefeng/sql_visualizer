"""R46a — target scoping: `is_target` is the SEARCHED table's seed claim.

FSB audit (EAST5_STZFXXB_M, 168 pairs): searching
`bdm_acc_entrusted_payment.data_dt` stamped `is_target` on the `data_dt`
chips of b, c, d and e too (`bdm_acc_loan_info`, `bdm_pub_branch` ×2,
`BDM_ACC_INTERNAL_COUNTERPARTY`) — 54 phantom seed chips across 41 pairs,
i.e. every same-name chip of every table in the joined statement. The flag
is the seed claim for three display consumers — seed-centering, the V2-N1
chip-visibility exemption (`hideEdgelessFieldChips` keeps `is_target`
chips) and the Field Story's seed selection — so foreign chips lit up and
the story could pick a foreign chip.

AD3 ADJUDICATION (2026-08-31), as amended by the coordinator ruling of the
same day: `is_target` = the chip's field-part equals the searched field
AND the chip's parent compound is EITHER an entity of the searched table's
ENTITY SET — the strict walker's own W1 seed rule (`target_keys ∪
_tkeys_ci ∪ _alias_keys`, the #399 alias expansion included) — OR a DML
WRITE-TARGET compound that RECEIVES the searched field's value (the R44
family-1 write twins: "only the field involved in the data flow is shown"
cuts both ways — the write target is the field's own flow continuation).
READ-side same-name chips on OTHER tables' compounds — the FSB phantoms
(b/c/d/e.data_dt, a join partner's partition column) — are ordinary nodes:
their compounds never receive the value, they only compare with it.

WHERE THE RULE LIVES — `l2_builder._scope_target_stamp`, at the display
boundary: `is_target` is load-bearing INSIDE the build, because P2
(`_promote_field_edges`) and P17 (`_simplify_dml_edges`) keep a seed
field's edges at FIELD level and `_attach_flow_payload` walks the closure
from the seed entries. Gating the flag in the seed phase re-routes SERVED
edges (measured on the flagship corpus: the J12-15 per-statement trunk
flagship loses its rrcdm write leg, and J1's LFS129 own-field value copy
goes dark — edge admission is J1's rule and it keeps both). So the seed
sets stay owner-agnostic, the served EDGE sets must be byte-identical
(pinned in TestDisplayOnly below), and only the stamp narrows.

The narrowing only ever REMOVES a stamp. Kept, because the model
attributes each to an admitted compound: the alias-qualified seed copy
(P1 MOVE→COPY — an alias compound resolves to its canonical entity), the
#399 alias-target seed (the expansion widens the entity set) and the R44
family-1 write-side copy (its compound receives the value).
"""

import contextlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "samples" / "sql_sample_v1"

import app.services.l2_builder as LB  # noqa: E402
from app.extractor.adapter import run_full_analysis  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.services.l2_builder import (  # noqa: E402
    _build_l2_graph,
    _scope_target_stamp,
    _searched_entity_keys,
    _write_target_entity_keys,
)
from app.services.workspace_service import (  # noqa: E402
    create_workspace,
    delete_workspace,
)


# ════════════════════════════════════════════════════════════════════════
# fixtures
# ════════════════════════════════════════════════════════════════════════

# Three tables, one shared field name, one joined statement — the EAST5
# shape that produced the finding, reduced to the minimum that still makes
# every same-name chip a real chip of its own table.
JOIN3_SQL = (
    "INSERT OVERWRITE TABLE out_t\n"                                # 1
    "SELECT a.data_dt AS a_dt, b.data_dt AS b_dt, c.data_dt AS c_dt\n"  # 2
    "FROM src_main a\n"                                             # 3
    "LEFT JOIN src_other b\n"                                       # 4
    "  ON b.data_dt = a.data_dt AND b.k = a.k\n"                    # 5
    "LEFT JOIN src_third c\n"                                       # 6
    "  ON c.data_dt = a.data_dt AND c.org_no = a.org_no\n"          # 7
    "WHERE a.data_dt = '$(load_date)';\n"                           # 8
)
JOIN3 = "r46a_join3.sql"

# The write-target copy: the searched field is written into another table,
# which carries its own same-named column (the R44 family-1 twin).
WRITE_SQL = (
    "INSERT OVERWRITE TABLE tgt_t\n"            # 1
    "SELECT a.data_dt, a.k\n"                   # 2
    "FROM src_main a;\n"                        # 3
)
WRITE = "r46a_write.sql"

# Alias copy inside the searched table's own entity set: `a` is an alias
# of src_main, so the alias compound belongs to the searched entity.
ALIAS_SQL = (
    "INSERT OVERWRITE TABLE out_t\n"            # 1
    "SELECT a.data_dt, a.k\n"                   # 2
    "FROM src_main a;\n"                        # 3
)
ALIAS = "r46a_alias.sql"


@contextlib.contextmanager
def _ws(sql, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, sql)
    ws_id = create_workspace(buf.getvalue())
    try:
        yield ws_id
    finally:
        delete_workspace(ws_id)


def _build(ws_id, sql, name, table, field, scope=True):
    """The filtered L2 result, with the R46a scoping phase optionally
    disabled (the pre-fix engine) for before/after assertions."""
    if scope:
        return _build_l2_graph(ws_id, name, sql, table, field)
    real = LB._scope_target_stamp
    LB._scope_target_stamp = lambda *a, **k: 0
    try:
        return _build_l2_graph(ws_id, name, sql, table, field)
    finally:
        LB._scope_target_stamp = real


def _graph(res):
    return res.get("graph") if isinstance(res.get("graph"), dict) else res


def _nodes(res):
    return {n["data"]["id"]: n["data"] for n in _graph(res)["nodes"]}


def _edges(res):
    return [e["data"] for e in _graph(res)["edges"]]


def _compounds(res):
    """table_name → compound node for every non-field node."""
    out = {}
    for d in _nodes(res).values():
        if d.get("type") != "field":
            out.setdefault(d.get("table_name"), d)
    return out


def _targets(res):
    """(label, line_start, parent table_name) of every is_target chip."""
    nodes = _nodes(res)
    return sorted((d.get("label"), d.get("line_start"),
                   (nodes.get(d.get("parent")) or {}).get("table_name"))
                  for d in _nodes(res).values()
                  if d.get("is_target") and d.get("type") == "field")


def _model(sql, name):
    return build_physical_model(run_full_analysis(sql, name), script_name=name)


def _assert_targets_admitted(res, table, field, pm):
    """The adjudicated invariant, checked structurally: every is_target
    chip's parent compound is an entity of the searched entity set OR a
    DML write target that receives the field's value."""
    entity_keys = _searched_entity_keys(pm, table, field)
    assert entity_keys, "fixture broken: the model names no entity"
    admitted = entity_keys | _write_target_entity_keys(pm, field)
    compounds = _compounds(res)
    for (label, line, parent_name) in _targets(res):
        compound = compounds.get(parent_name)
        key = None
        if compound is not None and pm is not None:
            oid = compound.get("original_id")
            key = pm.alias_by_var_id.get(oid) or pm.entity_of_id.get(oid)
        if key is not None:
            assert key in admitted, (
                f"is_target chip {label!r}@L{line} sits on {parent_name!r} "
                f"(entity {key!r}), outside the admitted set "
                f"{sorted(str(pm.tables[k].name) for k in admitted)}")
        else:
            assert (parent_name or "").lower() in {
                pm.tables[k].name.lower() for k in admitted}, (
                f"is_target chip {label!r}@L{line} sits on {parent_name!r}, "
                f"outside the admitted set")


def _entity_names(pm, keys):
    return {pm.tables[k].name for k in keys if k in pm.tables}


# ════════════════════════════════════════════════════════════════════════
# 1. the rule — the FSB class
# ════════════════════════════════════════════════════════════════════════

class TestEntitySetRule:
    def test_search_stamps_only_the_searched_tables_chip(self):
        """The FSB repro, reduced: each same-name chip is a seed of ITS OWN
        search and of nobody else's. (The searched table may carry several
        stamped chips — the output alias copy matches the field part too —
        but every one of them sits on ITS OWN compound.)"""
        with _ws(JOIN3_SQL, JOIN3) as ws_id:
            for table in ("src_main", "src_other", "src_third"):
                res = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL, table, "data_dt")
                assert res.get("search_matched") is True, table
                targets = _targets(res)
                assert targets, f"{table}.data_dt lost its seed chip"
                stamped_parents = {parent for (_l, _ln, parent) in targets}
                assert stamped_parents == {table}, (
                    f"search {table}.data_dt stamped foreign chips: {targets}")

    def test_foreign_same_name_chips_stay_served_as_ordinary_nodes(self):
        """Dropping the stamp never drops the chip: the other tables'
        same-name chips stay in the closure as ordinary nodes."""
        with _ws(JOIN3_SQL, JOIN3) as ws_id:
            res = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL,
                                  "src_main", "data_dt")
            nodes = _nodes(res)
            chips_by_parent = {}
            for d in nodes.values():
                if d.get("type") == "field":
                    parent = (nodes.get(d.get("parent")) or {}).get("table_name")
                    chips_by_parent.setdefault(parent, []).append(d)
            for table in ("src_main", "src_other", "src_third"):
                assert chips_by_parent.get(table), f"{table} lost its chips"
            # exactly the searched table's chips claim the seed
            stamped = [d for d in nodes.values()
                       if d.get("is_target") and d.get("type") == "field"]
            assert stamped, "no seed chip at all"
            assert all(
                (nodes.get(d.get("parent")) or {}).get("table_name")
                == "src_main" for d in stamped), stamped

    def test_entity_set_is_the_walkers_seed_rule(self):
        """`_searched_entity_keys` is the walker's W1 set: the entities
        named the searched table (exact + case-insensitive)."""
        with _ws(JOIN3_SQL, JOIN3) as ws_id:  # noqa: F841 — model source
            pm = _model(JOIN3_SQL, JOIN3)
            keys = _searched_entity_keys(pm, "src_main", "data_dt")
            assert keys, "no entity for src_main"
            assert {pm.tables[k].name for k in keys} == {"src_main"}
            # case-insensitive table part (CR11)
            ci = _searched_entity_keys(pm, "SRC_MAIN", "data_dt")
            assert ci == keys
            # an unknown table names no entity — no ownership evidence
            assert _searched_entity_keys(pm, "no_such_table", "data_dt") == set()
            assert _searched_entity_keys(None, "src_main", "data_dt") == set()


# ════════════════════════════════════════════════════════════════════════
# 2. display-only — the served edges are byte-identical
# ════════════════════════════════════════════════════════════════════════

class TestDisplayOnly:
    def test_edge_and_node_sets_are_unchanged_by_the_scoping(self):
        """The scoping narrows the STAMP only. P2/P17/payload read the flag
        before it is narrowed, so the served edges (ids, types, anchors)
        and the node set are byte-identical with and without it."""
        for table, field in (("src_main", "data_dt"),
                             ("src_other", "data_dt"),
                             ("src_third", "data_dt")):
            with _ws(JOIN3_SQL, JOIN3) as ws_id:
                unscoped = _build(ws_id, JOIN3_SQL, JOIN3, table, field,
                              scope=False)
                scoped = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL, table, field)
            assert sorted(e["id"] for e in _edges(scoped)) == \
                   sorted(e["id"] for e in _edges(unscoped)), table
            assert {(e["id"], e["edge_type"], e.get("highlight_line"))
                    for e in _edges(scoped)} == \
                   {(e["id"], e["edge_type"], e.get("highlight_line"))
                    for e in _edges(unscoped)}, table
            assert {n["id"] for n in _nodes(scoped).values()} == \
                   {n["id"] for n in _nodes(unscoped).values()}, table
            # …and the stamp did narrow (the fixture must stay discriminating)
            assert len(_targets(scoped)) < len(_targets(unscoped)), table


# ════════════════════════════════════════════════════════════════════════
# 3. the legitimate multi-chip cases survive
# ════════════════════════════════════════════════════════════════════════

class TestLegitimateMultiChip:
    def test_write_target_receiving_the_value_keeps_the_seed_claim(self):
        """Ruling amendment: the DML write target that RECEIVES the searched
        field's value is the field's own flow continuation, so its chip
        keeps the seed claim even though its compound is another table."""
        with _ws(WRITE_SQL, WRITE) as ws_id:
            pm = _model(WRITE_SQL, WRITE)
            # fixture precondition: tgt_t really is a write target of the field
            assert _entity_names(pm, _write_target_entity_keys(pm, "data_dt")) \
                == {"tgt_t"}, _write_target_entity_keys(pm, "data_dt")
            res = _build_l2_graph(ws_id, WRITE, WRITE_SQL,
                                  "src_main", "data_dt")
            assert res.get("search_matched") is True
            parents = {parent for (_l, _ln, parent) in _targets(res)}
            assert parents == {"src_main", "tgt_t"}, _targets(res)
            _assert_targets_admitted(res, "src_main", "data_dt", pm)

    def test_write_table_search_stamps_its_own_chip(self):
        with _ws(WRITE_SQL, WRITE) as ws_id:
            res = _build_l2_graph(ws_id, WRITE, WRITE_SQL, "tgt_t", "data_dt")
            assert res.get("search_matched") is True
            assert {parent for (_l, _ln, parent) in _targets(res)} == {"tgt_t"}

    def test_alias_copy_of_the_seed_keeps_its_stamp(self):
        """P1 MOVE→COPY, scoped: the alias compound resolves to its
        canonical entity (the searched table), so its copy stays a seed."""
        with _ws(ALIAS_SQL, ALIAS) as ws_id:
            res = _build_l2_graph(ws_id, ALIAS, ALIAS_SQL,
                                 "src_main", "data_dt")
            assert res.get("search_matched") is True
            targets = _targets(res)
            assert targets, "the alias-qualified seed lost its stamp"
            _assert_targets_admitted(res, "src_main", "data_dt",
                                          _model(ALIAS_SQL, ALIAS))

    def test_alias_target_search_stamps_the_owning_entity(self):
        """#399: a search whose TABLE part is an alias widens the entity set
        to the alias's owning entities — the stamp follows that set."""
        sql = ("WITH cte_src AS (SELECT p.x FROM base_t p)\n"   # 1
               "SELECT a.x, a.y FROM real_t a;\n")              # 2
        name = "r46a_399.sql"
        with _ws(sql, name) as ws_id:
            res = _build_l2_graph(ws_id, name, sql, "a", "x")
            assert res.get("search_matched") is True, res.get("search_matched")
            targets = _targets(res)
            assert targets, "the #399 alias-target seed lost its stamp"
            assert {parent for (_l, _ln, parent) in targets} == {"real_t"}
            pm = _model(sql, name)
            keys = _searched_entity_keys(pm, "a", "x")
            assert {pm.tables[k].name for k in keys} == {"real_t"}, (
                "the #399 expansion vanished from the entity set")


# ════════════════════════════════════════════════════════════════════════
# 4. deliberate non-changes
# ════════════════════════════════════════════════════════════════════════

class TestDeliberateNonChanges:
    def test_field_group_still_measures_graph_distance(self):
        """`field_group` is a distance notion seeded from the owner-agnostic
        match: a foreign same-name chip stays `direct` while losing the
        seed claim (the ruling scopes the CLAIM, not the grouping)."""
        with _ws(JOIN3_SQL, JOIN3) as ws_id:
            res = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL, "src_main", "data_dt")
            nodes = _nodes(res)
            foreign = [d for d in nodes.values()
                       if d.get("type") == "field"
                       and (nodes.get(d.get("parent")) or {}).get("table_name")
                       == "src_other"]
            assert foreign, "the foreign chip vanished"
            assert all(d.get("field_group") == "direct" for d in foreign), (
                [(d["label"], d.get("field_group")) for d in foreign])
            assert not any(d.get("is_target") for d in foreign)

    def test_full_view_and_searchless_builds_are_untouched(self):
        """No searched table ⇒ no entity set ⇒ the scoping is a no-op (the
        #289/#387 fixtures drive the builder with table='')."""
        assert _scope_target_stamp([], {}, "", "", None) == 0
        with _ws(JOIN3_SQL, JOIN3) as ws_id:
            full = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL, "", "",
                                   relevance_filter=False)
            assert full.get("nodes"), "the full view broke"
            assert not [d for d in _nodes(full).values() if d.get("is_target")]

    def test_scope_returns_dropped_count(self):
        """The phase reports how many stamps it dropped (diagnostics only)."""
        with _ws(JOIN3_SQL, JOIN3) as ws_id:
            res = _build_l2_graph(ws_id, JOIN3, JOIN3_SQL, "src_main", "data_dt")
        dropped = _scope_target_stamp(
            [dict(d) for d in _nodes(res).values()
             if d.get("type") == "field"],
            {}, "src_main", "data_dt", None)
        assert dropped == 0   # no model ⇒ no gate ⇒ nothing dropped


# ════════════════════════════════════════════════════════════════════════
# 5. the FSB corpus itself (gated on the sample files existing)
# ════════════════════════════════════════════════════════════════════════

EAST5 = "EAST5_STZFXXB_M.sql"

# (searched table, searched field) — every pair of the finding, plus the
# mixed-join fields that share a name across the joined statement.
FSB_PAIRS = [
    ("bdm_acc_entrusted_payment", "data_dt"),
    ("bdm_acc_loan_info", "data_dt"),
    ("bdm_pub_branch", "data_dt"),
    ("BDM_ACC_INTERNAL_COUNTERPARTY", "DATA_DT"),
    ("bdm_acc_entrusted_payment", "lending_ref"),
    ("bdm_acc_loan_info", "lending_ref"),
    ("bdm_acc_loan_info", "org_no"),
    ("bdm_acc_entrusted_payment", "ccy_code"),
    ("bdm_acc_loan_info", "ccy_code"),
]


SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"


@pytest.mark.skipif(not (SAMPLES_DIR / SUP_M).exists(),
                    reason="sample corpus not shipped")
class TestRulingWriteTargets:
    """The coordinator ruling's own case (SUP_M × bdm_acc_loan_info.data_dt):
    the two write targets that RECEIVE the field's value keep the seed
    claim; the READ-side same-name chips of join partners lose theirs."""

    def test_write_target_copies_keep_their_stamp(self):
        sql = (SAMPLES_DIR / SUP_M).read_text(encoding="utf-8")
        with _ws(sql, SUP_M) as ws_id:
            res = _build_l2_graph(ws_id, SUP_M, sql,
                                  "bdm_acc_loan_info", "data_dt")
        targets = _targets(res)
        parents = {p for (_l, _ln, p) in targets}
        assert "bdm_acc_loan_info" in parents, targets
        assert {"bdm_acc_loan_info_sup", "rrcdm_job_log_exec_par"} <= parents, (
            f"the receiving write targets lost the seed claim: {targets}")

    def test_read_side_join_partners_are_ordinary_nodes(self):
        sql = (SAMPLES_DIR / SUP_M).read_text(encoding="utf-8")
        with _ws(sql, SUP_M) as ws_id:
            res = _build_l2_graph(ws_id, SUP_M, sql,
                                  "bdm_acc_loan_info", "data_dt")
        parents = {p for (_l, _ln, p) in _targets(res)}
        # bdm_evt_loan_trans / bdm_gdc_label_fin only COMPARE data_dt in a
        # predicate — their compounds never receive the value.
        leaked = parents & {"bdm_evt_loan_trans", "bdm_gdc_label_fin"}
        assert not leaked, f"read-side join partners still claim the seed: {leaked}"


@pytest.mark.skipif(not (SAMPLES_DIR / EAST5).exists(),
                    reason="sample corpus not shipped")
class TestFSBCorpus:
    @pytest.mark.parametrize("table,field", FSB_PAIRS)
    def test_seed_is_only_the_searched_tables_chip(self, table, field):
        sql = (SAMPLES_DIR / EAST5).read_text(encoding="utf-8")
        with _ws(sql, EAST5) as ws_id:
            res = _build_l2_graph(ws_id, EAST5, sql, table, field)
        assert res.get("search_matched") is True, f"{table}.{field}"
        pm = _model(sql, EAST5)
        admitted = _entity_names(
            pm, _searched_entity_keys(pm, table, field)
            | _write_target_entity_keys(pm, field))
        targets = _targets(res)
        assert targets, f"{table}.{field}: no seed chip"
        foreign = [(l, ln, p) for (l, ln, p) in targets if p not in admitted]
        assert not foreign, (
            f"{table}.{field}: READ-side foreign seed chips {foreign} "
            f"(admitted: {sorted(admitted)})")
        assert table in {p for (_l, _ln, p) in targets}, targets
        _assert_targets_admitted(res, table, field, pm)

    @pytest.mark.parametrize("table,field", FSB_PAIRS)
    def test_scoping_does_not_touch_the_served_edges(self, table, field):
        sql = (SAMPLES_DIR / EAST5).read_text(encoding="utf-8")
        with _ws(sql, EAST5) as ws_id:
            scoped = _build_l2_graph(ws_id, EAST5, sql, table, field)
            unscoped = _build(ws_id, sql, EAST5, table, field,
                              scope=False)
        def _sig(res):
            return sorted((e["id"], e["edge_type"], e.get("highlight_line"))
                          for e in _edges(res))
        assert _sig(scoped) == _sig(unscoped), (
            f"{table}.{field}: the scoping re-routed served edges")
        assert {n["id"] for n in _nodes(scoped).values()} == \
               {n["id"] for n in _nodes(unscoped).values()}
