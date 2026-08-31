"""TDD specs for #399 alias-aware seed expansion (option b′) — RED until
F-G lands; do not delete; skip via -k 'not alias_seed' in CI if needed.

What the feature is (decision doc /tmp/sim/decisions.md, Decision 1, option
b′): a search whose TABLE part names a SQL ALIAS (`a.data_dt`, `P1.INT_OD_DT`,
`t.acct_no`, `SSALSFP.ALCBP1`, ...) must seed the strict field-flow walker
from the alias's OWNING ENTITY — whatever kind that entity is (physical
table, CTE or derived container) — instead of falling into the empty-seed /
`search_matched: false` / full-graph-fallback dead end. Today the walker's
W1 seed rule matches ENTITIES named the searched table
(`backend/app/extractor/lineage.py`, W1 `target_keys = {k for k, t in
pm.tables.items() if t.name == target_table}` + the CR11 case-insensitive
retry), and an alias is never an entity, so 18 of the 21 S1 not-in-flow
fetches are alias searches that return an empty closure.

SKIPPING MECHANISM (chosen) — a sentinel constant, not a weak probe:

    _ALIAS_SEED_EXPANSION = True      # F-G adds this to app/extractor/lineage.py

F-G adds that module-level constant to `app/extractor/lineage.py` (W1's
home; `app/services/l2_builder.py` is accepted as a fallback location) and
gates the alias-key union on it. This one constant serves three purposes:

  1. skip switch — every gated class here is `skipif`-guarded on it, so the
     suite is GREEN today and flips to real red/green the moment F-G lands
     (it HAS landed: `TestSentinel` pins the sentinel itself, ungated, so
     removing it can never turn this file into a silent skip again);
  2. kill switch — `test_inflow_closures_byte_identical` flips it OFF to
     prove the feature is additive-only for searches that already work
     (so the constant has to BE the gate, not a decorative flag next to an
     unconditional expansion — an ungated expansion makes that test
     vacuous, and the gate test fail);
  3. documentation — the switch names the feature at the exact site that
     implements it.

(`pytest.importorskip` was rejected: it would mask a genuinely broken tree
as a skip, and it cannot be flipped back OFF inside a test. A "feature
present" probe that inspects the W1 source text was rejected as brittle.
`pytest.mark.slow` was rejected for the flagship test: no slow marker is
registered anywhere in this repo — the corpus tests here are gated on the
sample files existing, like test_l2_case_merge.py does.)

HARD CONSTRAINTS PINNED HERE (from the SQL-verified second pass, §3b):

  * expand from `pm.alias_by_var_id` ONLY — never from the label-keyed
    alias map (`physical_model.py` pass 0), which is first-wins per script
    and provably misses the derived-`t` binding in RFN;
  * the expansion target is the alias's OWNING ENTITY whatever its kind —
    not "the physical table" (the rejected option (b): 9/12 S1 targets are
    workspace-ambiguous and 2/12 are CTE-owned);
  * the gate: expand ONLY when no entity is named the searched table (an
    entity named `a` or `t` preempts the expansion);
  * ambiguity ruling: when one alias name binds to several owning entities
    in one statement, seed ALL of them (union closure) — never "pick none
    and keep the full-graph fallback" (`test_ambiguity_semantics_union`).

EVIDENCE BEHIND THE FIXTURES (measured in gps-sql-backend on the working
tree, 2026-08-29): every synthetic fixture here was probed before being
pinned — the alias-search shapes below return `search_matched: false` with
a 0/0 empty closure today and gain a non-empty seed set exactly when
`target_keys |= {alias_by_var_id[vid] for vid, key in pm.alias_by_var_id.items()
if occ(vid).name.casefold() == target.casefold()}` is applied. The flagship
script uses the S1 corpus itself: `a.data_dt` in BDM_ACC_LOAN_INFO_SUP_M.sql
(alias of bdm_evt_loan_trans, occurrence line 55), `a.data_dt` in
EAST5_STZFXXB_M.sql (alias of bdm_acc_entrusted_payment, line 159) and
`SSALSFP.ALCBP1` in BDM_ACC_LOAN_INFO_Digitallending.sql (alias of
ODS_HUB_SSALSFP, lines 63-83) — all three are `search_matched: false` with
an empty closure today and carry the searched field on their owning entity,
so the expansion must turn each of them into a real flow closure.

FINDING WORTH RECORDING (narrowed the spec honestly): a *pure* "alias of a
derived table" case cannot exist in this model. A derived container is
registered under its own alias name (`FROM (SELECT ...) t` → entity
key `("t", "TOP0/subq/t")`, kind "subquery"), so a search for `t.field` is
already served by the entity path — measured on the S1 corpus:
`alias_by_var_id` owners are 104 physical / 23 cte / 0 derived. What CAN be
RED is an alias INSIDE a derived subquery (`FROM (SELECT t.acct_no FROM
src_inner t) q`), and that is what `test_alias_seed_expands_through_derived`
pins, together with a guard that the container-owner search is served from
the per-scope container entity and is NOT rewritten onto a physical table.

Fixture inventory (each is the minimal SQL that reproduces the S1 shape):

  GATE_SQL      an alias `a` AND a real table named `a` (gate preempts)
  PHYS_SQL      alias of a physical table (the plain case)
  NESTED_SQL    alias inside a derived subquery (the RFN derived-`t` shape)
  DERIVED_SQL   a derived CONTAINER is the owning entity (guard, green today)
  CTE_SQL       alias of a CTE (the 2/12 CTE-owned targets)
  AMBIG_SQL     one alias name bound to two owners in one statement (3/12)
  INFLOW_SQL    a physical-table search that already works (additivity)
  S1 corpus     `a.data_dt` / `SSALSFP.ALCBP1` on the real samples
"""

import asyncio
import contextlib
import importlib
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "samples" / "sql_sample_v1"

from app.extractor.adapter import run_full_analysis  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.services.dataflow_service import (  # noqa: E402
    create_search,
    get_level2_graph,
)
from app.services.folder_index_service import index_scripts  # noqa: E402
from app.services.l2_builder import _build_l2_graph  # noqa: E402
from app.services.workspace_service import (  # noqa: E402
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)


# ════════════════════════════════════════════════════════════════════════
# The F-G sentinel — skip switch (now) and kill switch (test 7)
# ════════════════════════════════════════════════════════════════════════

def _find_feature_module():
    """The module holding F-G's `_ALIAS_SEED_EXPANSION` switch (None today)."""
    for modname in ("app.extractor.lineage", "app.services.l2_builder"):
        try:
            mod = importlib.import_module(modname)
        except (ImportError, ModuleNotFoundError):  # pragma: no cover
            # R4 M (2026-08-29): only a MISSING module may be tolerated —
            # that is the "feature not landed" state this module skips on.
            # Anything else (SyntaxError, an import-time crash in a real
            # module, ...) is a broken tree and must fail loudly, never
            # masquerade as a skip.
            continue
        if getattr(mod, "_ALIAS_SEED_EXPANSION", False):
            return mod
    return None


FEATURE_MODULE = _find_feature_module()
_FEATURE_PRESENT = FEATURE_MODULE is not None

# R4 M (2026-08-29): the skip is PER-CLASS, never module-wide. A module-wide
# `pytestmark` would also swallow the sentinel guard below, so deleting the
# sentinel from lineage.py would turn this whole file into a silent skip —
# the one outcome a sentinel cannot be allowed to produce.
_NEEDS_FEATURE = pytest.mark.skipif(
    not _FEATURE_PRESENT,
    reason="#399 option b' not landed: no _ALIAS_SEED_EXPANSION sentinel in "
           "app.extractor.lineage (F-G)")


class TestSentinel:
    """NOT gated on the feature — this is the test that says the gate
    itself still exists."""

    def test_feature_sentinel_is_present(self):
        """The skip above is only honest while the sentinel it keys on is
        real. If `_ALIAS_SEED_EXPANSION` disappears from
        `app/extractor/lineage.py`, every gated class here silently skips
        and the #399 contract loses all its coverage with a GREEN suite —
        this test is the tripwire against exactly that."""
        assert _FEATURE_PRESENT, (
            "sentinel removed — restore lineage.py:_ALIAS_SEED_EXPANSION "
            "or delete this file")
        assert FEATURE_MODULE is not None
        assert getattr(FEATURE_MODULE, "_ALIAS_SEED_EXPANSION") is True


# ════════════════════════════════════════════════════════════════════════
# Fixtures + helpers (zip-upload a workspace, drive the service layer —
# the test_k4_rulings_fb1.py / test_l2_case_merge.py pattern)
# ════════════════════════════════════════════════════════════════════════

# An alias `a` AND a real table named `a`, in one script. Line 2 registers
# the PHYSICAL entity `a` (bare reference — the only way a table named `a`
# becomes an entity: an aliased reference registers the alias label as the
# var name). Line 6 uses `a` as an ALIAS of real_t, so an ungated expansion
# would add real_t to the seed set. Searching `a.f` must be answered from
# the entity `a` alone.
GATE_SQL = (
    "INSERT OVERWRITE TABLE out_b\n"   # 1
    "SELECT f FROM a;\n"               # 2  ← physical entity `a`
    "INSERT OVERWRITE TABLE out_c\n"   # 3
    "SELECT p.f FROM real_t p;\n"      # 4  ← real_t's own `f`, alias `p`
    "INSERT OVERWRITE TABLE out_d\n"   # 5
    "SELECT a.f FROM real_t a;\n"      # 6  ← `a` is an ALIAS of real_t
)

# Alias of a PHYSICAL table (the plain S1 shape — `dsf_tm.acct_no`).
PHYS_SQL = (
    "WITH cte_src AS (SELECT p.x FROM base_t p)\n"  # 1
    "SELECT a.x, a.y FROM real_t a;\n"              # 2  ← alias `a` → real_t
)

# Alias INSIDE a derived subquery (the RFN derived-`t` shape the label map
# misses): `t` is bound to src_inner inside the container `q`.
NESTED_SQL = (
    "INSERT OVERWRITE TABLE out_t\n"   # 1
    "SELECT q.acct_no\n"               # 2
    "FROM (SELECT t.acct_no\n"         # 3  ← alias `t` → src_inner
    "     FROM src_inner t) q;\n"      # 4
)

# A derived CONTAINER as the owning entity (`FROM (SELECT ...) t`): the
# container is an entity named by its alias, so this already works today.
# Kept as a guard: the owning entity is a per-scope container, never
# rewritten onto the physical table it reads (the rejected option (b)).
DERIVED_SQL = (
    "INSERT OVERWRITE TABLE out_t\n"   # 1
    "SELECT t.acct_no\n"               # 2  ← served by the container entity
    "FROM (SELECT s.acct_no\n"         # 3
    "     FROM src_inner s) t;\n"      # 4
)

# Alias of a CTE (the 2/12 CTE-owned S1 targets — `P1.INT_OD_DT`): the
# owning entity is the CTE `cte_src`, NOT the physical base_t.
CTE_SQL = (
    "WITH cte_src AS (SELECT p.x, p.y FROM base_t p)\n"  # 1
    "SELECT a.x, a.y FROM cte_src a;\n"                  # 2
)

# ONE alias name bound to TWO owning entities inside ONE statement — the
# RFN `t.acct_no` shape (derived-`t` + `BDM_GDC_LABEL_FIN t`): `t` resolves
# to the CTE `w` on line 4 and to the physical `lbl_fin` on line 5.
AMBIG_SQL = (
    "WITH w AS (SELECT y.acct_no FROM inner_src y)\n"  # 1
    "INSERT OVERWRITE TABLE out_t\n"                   # 2
    "SELECT q.acct_no, k.acct_no\n"                    # 3
    "FROM (SELECT t.acct_no FROM w t) q\n"             # 4  ← `t` → w (CTE)
    "JOIN lbl_fin t ON t.acct_no = q.acct_no;\n"       # 5  ← `t` → lbl_fin
)

# A search that already works (a PHYSICAL table name): the feature must
# leave its closure byte-identical.
INFLOW_SQL = (
    "INSERT OVERWRITE TABLE out_b\n"   # 1
    "SELECT r.f FROM real_t r;\n"      # 2
    "INSERT OVERWRITE TABLE out_c\n"   # 3
    "SELECT p.f FROM real_t p;\n"      # 4
)


def _line_of(sql, needle):
    """1-based line of the first fixture line containing `needle` — keeps
    the line assertions tied to the SQL text instead of magic numbers."""
    for no, line in enumerate(sql.splitlines(), start=1):
        if needle in line:
            return no
    raise AssertionError(f"{needle!r} not found in fixture")


@contextlib.contextmanager
def _ws(sql, name="alias_seed.sql"):
    """A workspace holding one script, deleted on exit."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, sql)
    ws_id = create_workspace(buf.getvalue())
    try:
        yield ws_id
    finally:
        delete_workspace(ws_id)


def _l2(ws_id, sql, table, field, name="alias_seed.sql"):
    """The filtered L2 result for one table.field search."""
    return _build_l2_graph(ws_id, name, sql, table, field)


def _data(res):
    return [n["data"] for n in res["nodes"]]


def _compounds(res):
    """table_name → L2 compound id for every non-field node."""
    out = {}
    for d in _data(res):
        if d.get("type") != "field":
            out.setdefault(d.get("table_name"), d["id"])
    return out


def _targets(res):
    """(label, line_start, parent compound id) of every is_target chip."""
    return [(d.get("label"), d.get("line_start"), d.get("parent"))
            for d in _data(res) if d.get("is_target")]


def _ids(res):
    return ({n["data"]["id"] for n in res["nodes"]},
            {e["data"]["id"] for e in res["edges"]})


def _model(ws_id, sql, name="alias_seed.sql"):
    """The physical model the L2 builder derives for this script."""
    return build_physical_model(run_full_analysis(sql, name), script_name=name)


def _alias_owners(pm, table):
    """Canonical entity keys of every alias occurrence named `table`
    (exactly the set F-G's expansion unions into target_keys)."""
    tl = table.casefold()
    return {key for vid, key in pm.alias_by_var_id.items()
            if ((pm.occurrence(vid) or {}).get("name") or "").casefold() == tl}


def _field_occurrences(pm, key, field):
    fld = pm.fields.get((key, field))
    return [] if fld is None else list(fld.occurrence_ids)


def _search(ws_id, table, field, name, direction="downstream"):
    """create_search through the folder index (the user-facing entry)."""
    import json
    cache = get_workspace_dir(ws_id) / "cache"
    ti = json.loads((cache / "table_index.json").read_text())
    fi = json.loads((cache / "field_index.json").read_text())
    return asyncio.run(create_search(ws_id, table, field, ti, fi,
                                     direction=direction))


def _set_switch(monkeypatch, value):
    """Flip F-G's `_ALIAS_SEED_EXPANSION` switch in EVERY imported module
    that carries it — the kill switch test 7 uses to prove additivity."""
    for modname in ("app.extractor.lineage", "app.services.l2_builder"):
        mod = sys.modules.get(modname)
        if mod is not None and hasattr(mod, "_ALIAS_SEED_EXPANSION"):
            monkeypatch.setattr(mod, "_ALIAS_SEED_EXPANSION", value)


# ════════════════════════════════════════════════════════════════════════
# 1. the gate
# ════════════════════════════════════════════════════════════════════════

@_NEEDS_FEATURE
class TestGate:
    def test_gate_fires_only_when_no_entity_named_the_search(self):
        """`a` is an alias of real_t on line 6, but a REAL table named `a`
        exists (line 2). The gate preempts: the search is seeded from the
        entity `a` alone — never from the alias's owner.

        Discriminator: real_t's own `f` occurrences (lines 4 and 6, both
        attributed to real_t in the model) must stay OUT of the seed set. An
        implementation that unions the alias keys without the gate puts an
        is_target chip on those lines."""
        with _ws(GATE_SQL) as ws_id:
            pm = _model(ws_id, GATE_SQL)
            # Precondition: the entity named `a` exists and the alias `a`
            # really does bind to real_t (so an ungated expansion WOULD add
            # it) — this is what makes the test discriminating.
            named = [k for k, t in pm.tables.items() if t.name == "a"]
            assert named, f"fixture broken: no entity named 'a': {pm.tables}"
            assert "real_t" in _alias_owners(pm, "a"), \
                f"fixture broken: alias 'a' does not bind to real_t: " \
                f"{pm.alias_by_var_id}"
            real_t_f = _field_occurrences(pm, "real_t", "f")
            assert real_t_f, "fixture broken: real_t hosts no field f"

            res = _l2(ws_id, GATE_SQL, "a", "f")

            # In flow (the entity `a` hosts the searched field) — the gate
            # must not turn a working search into the full-graph fallback.
            assert res.get("search_matched") is True, res.get("search_matched")
            tgts = _targets(res)
            assert tgts, "no is_target chip — the entity-`a` seed was lost"

            bare_line = _line_of(GATE_SQL, "SELECT f FROM a")
            alias_line = _line_of(GATE_SQL, "SELECT a.f FROM real_t a")
            other_alias_line = _line_of(GATE_SQL, "SELECT p.f FROM real_t p")
            assert [ln for (_l, ln, _p) in tgts] == [bare_line] * len(tgts), \
                f"gate leaked: is_target chips off the physical `a` line " \
                f"({bare_line}): {tgts}"
            assert alias_line not in [ln for (_l, ln, _p) in tgts], \
                f"the alias's owner (real_t) was seeded: {tgts}"
            assert other_alias_line not in [ln for (_l, ln, _p) in tgts], \
                f"the alias's owner (real_t) was seeded: {tgts}"
            # The closure serves the searched table's own compound, not the
            # alias's owner.
            assert "real_t" not in _compounds(res), _compounds(res)


# ════════════════════════════════════════════════════════════════════════
# 2-4. the expansion target is the OWNING ENTITY, whatever its kind
# ════════════════════════════════════════════════════════════════════════

@_NEEDS_FEATURE
class TestExpansionTargets:
    def test_alias_seed_expands_to_owning_physical(self):
        """`a.x` with no entity named `a`: the seed must be the field the
        alias's OWNER (real_t) carries — a real closure, not the
        full-graph fallback. RED today (empty closure, search_matched
        false), GREEN once the alias keys join target_keys."""
        with _ws(PHYS_SQL) as ws_id:
            pm = _model(ws_id, PHYS_SQL)
            assert _alias_owners(pm, "a") == {"real_t"}, pm.alias_by_var_id
            assert _field_occurrences(pm, "real_t", "x"), pm.fields
            assert not [k for k, t in pm.tables.items() if t.name == "a"], \
                "fixture broken: an entity named 'a' would preempt the gate"

            res = _l2(ws_id, PHYS_SQL, "a", "x")

            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            assert "real_t" in comps, f"owner compound missing: {comps}"
            tgts = _targets(res)
            assert tgts, "no is_target chip — the alias seed did not attach"
            owner_chip = comps["real_t"]
            assert [t for t in tgts if t[2] == owner_chip], \
                f"no is_target chip on the owning entity: {tgts}"
            assert {ln for (_l, ln, _p) in tgts} == \
                {_line_of(PHYS_SQL, "SELECT a.x")}, \
                f"seeded from a foreign line: {tgts}"

    def test_alias_seed_expands_through_derived(self):
        """Two things at once:

        (a) RED-capable — an alias INSIDE a derived subquery
            (`FROM (SELECT t.acct_no FROM src_inner t) q`): `t` is bound to
            the physical src_inner and no entity is named `t`, so the search
            must seed src_inner (RED today: empty closure).
        (b) GUARD — a derived CONTAINER as the owning entity
            (`FROM (SELECT ...) t`) is already an entity, so that search
            works today and must KEEP working, served from the per-scope
            container and never rewritten onto the physical table it reads
            (option (b)'s "alias → physical" rewrite would do exactly that).
            Measured on the S1 corpus: alias owners are 104 physical / 23
            cte / 0 derived, because a derived container registers under its
            own alias name — that is why this leg is a guard, not a RED."""
        with _ws(NESTED_SQL) as ws_id:
            pm = _model(ws_id, NESTED_SQL)
            assert "src_inner" in _alias_owners(pm, "t"), pm.alias_by_var_id
            assert _field_occurrences(pm, "src_inner", "acct_no"), pm.fields
            assert not [k for k, t in pm.tables.items() if t.name == "t"], \
                "fixture broken: an entity named 't' would preempt the gate"

            res = _l2(ws_id, NESTED_SQL, "t", "acct_no")

            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            assert "src_inner" in comps, \
                f"the alias's owner inside the derived subquery is missing " \
                f"from the closure: {comps}"
            tgts = _targets(res)
            assert tgts, "no is_target chip — the alias seed did not attach"
            assert {ln for (_l, ln, _p) in tgts} == \
                {_line_of(NESTED_SQL, "SELECT t.acct_no")}, \
                f"seeded from a foreign line: {tgts}"

        with _ws(DERIVED_SQL) as ws_id:
            pm = _model(ws_id, DERIVED_SQL)
            container = [k for k, t in pm.tables.items()
                         if t.name == "t" and t.kind != "physical"]
            assert container, f"fixture broken: no derived container: {pm.tables}"

            res = _l2(ws_id, DERIVED_SQL, "t", "acct_no")

            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            assert "t" in comps, f"container compound missing: {comps}"
            tgts = _targets(res)
            assert tgts, "no is_target chip on the container-owned field"
            assert [t for t in tgts if t[2] == comps["t"]], \
                f"the container's own chip was rewritten onto a physical " \
                f"table: {tgts}"

    def test_alias_seed_expands_to_cte_entity(self):
        """`a.x` where `a` is an alias of the CTE cte_src (2 of the 12 S1
        targets are CTE-owned): the owning entity is the CTE — the seed must
        be the CTE's field, and the SEED is the alias/CTE, never the physical
        base_t (an "alias → physical table" implementation would still miss
        this one). RED today.

        G7 RE-SCOPE (2026-08-31, after the RC-C provenance/chain fix): the
        old final assertion was `base_t not in comps`, written when no
        traversal could reach the physical base. `base_t` now LEGITIMATELY
        enters the closure — it is the value's ORIGIN
        (`a.x` ← CTE `cte_src` projection ← `p.x` ← `base_t`), exactly the
        upstream chain the provenance walk exists to surface. So "the base is
        never in the closure" is no longer the contract; what must hold is
        that the base is never the SEED: the chip at the SEARCHED line stays
        on the alias/CTE side — base_t may only carry the copy of the field
        instance that lands on its own upstream read line."""
        with _ws(CTE_SQL) as ws_id:
            pm = _model(ws_id, CTE_SQL)
            assert _alias_owners(pm, "a") == {"cte_src"}, pm.alias_by_var_id
            assert pm.tables[next(iter(_alias_owners(pm, "a")))].kind == "cte"
            assert _field_occurrences(pm, "cte_src", "x"), pm.fields

            res = _l2(ws_id, CTE_SQL, "a", "x")

            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            assert "cte_src" in comps, f"CTE compound missing: {comps}"
            tgts = _targets(res)
            assert tgts, "no is_target chip — the alias seed did not attach"
            assert [t for t in tgts if t[2] == comps["cte_src"]], \
                f"no is_target chip on the CTE entity: {tgts}"
            # G7 RE-SCOPE: the base MAY be in the closure (it is the value's
            # origin), so it is not "base_t not in comps" any more — the
            # contract is that the base is never the SEED. Observable form:
            # the is_target chip at the SEARCHED line (the alias reference
            # line) is parented on the CTE entity only, never on base_t's
            # compound. (base_t's own chip — the same field instance copied
            # onto every node that carries it, P1 MOVE→COPY — sits at the
            # CTE body's upstream read line, which is the origin showing
            # through, not the seed.)
            assert "base_t" in comps, (
                f"the value's origin dropped out of the closure — the "
                f"upstream chain a.x ← cte_src.x ← p.x ← base_t is broken: "
                f"{comps}")
            seed_line = _line_of(CTE_SQL, "SELECT a.x")
            assert {p for (_l, ln, p) in tgts if ln == seed_line} \
                == {comps["cte_src"]}, (
                f"the searched line is seeded from a foreign compound "
                f"(base_t must never be the seed): {tgts}")


# ════════════════════════════════════════════════════════════════════════
# 5-6. ambiguity: seed ALL owning entities (union), never pick none
# ════════════════════════════════════════════════════════════════════════

@_NEEDS_FEATURE
class TestAmbiguity:
    def test_ambiguity_seeds_union_or_keeps_full_graph(self):
        """One alias name, two owning entities, ONE statement (the RFN
        `t.acct_no` shape). RULING (decision doc §3b/§4): seed ALL of them —
        the union closure. The rejected alternative ("pick none and keep the
        full-graph fallback") is what the user sees today: an empty closure,
        `search_matched: false` and a not-in-flow banner over the full
        graph. Pinned: the union closure is served, not the fallback."""
        with _ws(AMBIG_SQL) as ws_id:
            pm = _model(ws_id, AMBIG_SQL)
            owners = _alias_owners(pm, "t")
            assert len(owners) == 2, \
                f"fixture broken: expected 2 owning entities, got {owners}"
            assert not [k for k, t in pm.tables.items() if t.name == "t"], \
                "fixture broken: an entity named 't' would preempt the gate"

            res = _l2(ws_id, AMBIG_SQL, "t", "acct_no")

            # THE ambiguity ruling: a real union closure, never the fallback.
            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            for owner_name in ("w", "lbl_fin"):
                assert owner_name in comps, \
                    f"owning entity {owner_name} dropped from the union " \
                    f"closure: {comps}"
            assert len(_targets(res)) >= 2, \
                f"the union closure lost one owner's seed: {_targets(res)}"

    def test_ambiguity_semantics_union(self):
        """The ruling, stated as a test: `t` in AMBIG_SQL resolves to TWO
        canonical entities through `pm.alias_by_var_id` (per-occurrence
        truth — the label-keyed map cannot express this), BOTH of them carry
        the searched field, and the served closure keeps both. `pick none`
        would return search_matched false with the full graph; `pick one`
        would drop the other owner's compound. Both are rejected."""
        with _ws(AMBIG_SQL) as ws_id:
            pm = _model(ws_id, AMBIG_SQL)

            owners = _alias_owners(pm, "t")
            assert len(owners) == 2, \
                f"fixture broken: expected 2 owners, got {owners}"
            kinds = sorted(pm.tables[k].kind for k in owners)
            assert kinds == ["cte", "physical"], \
                f"fixture drifted: owners are {kinds} (want cte + physical)"
            # Both owners host the searched field — seeding either one alone
            # would be a silent half answer.
            for k in owners:
                assert _field_occurrences(pm, k, "acct_no"), \
                    f"owner {k} ({pm.tables[k].kind}) hosts no acct_no"

            res = _l2(ws_id, AMBIG_SQL, "t", "acct_no")

            assert res.get("search_matched") is True, res.get("search_matched")
            comps = _compounds(res)
            assert {"w", "lbl_fin"} <= set(comps), \
                f"union semantics violated — one owner is missing: {comps}"


# ════════════════════════════════════════════════════════════════════════
# 7. additivity: an in-flow search keeps its closure byte-identical
# ════════════════════════════════════════════════════════════════════════

@_NEEDS_FEATURE
class TestAdditivity:
    def test_inflow_closures_byte_identical(self, monkeypatch):
        """The feature is gated, therefore additive: a PHYSICAL-table search
        (no alias anywhere in the searched name) must produce the same node
        AND edge id set with the expansion switch OFF as with it ON. This is
        the Jaccard-gate / 4-L2-snapshot byte-identity promise, checked at
        the closure level."""
        with _ws(INFLOW_SQL) as ws_id:
            base = _l2(ws_id, INFLOW_SQL, "real_t", "f")
            assert base.get("search_matched") is True, base.get("search_matched")
            base_ids = _ids(base)
            assert base_ids[0] and base_ids[1], \
                "fixture broken: the in-flow closure is empty"

            _set_switch(monkeypatch, False)
            try:
                off = _l2(ws_id, INFLOW_SQL, "real_t", "f")
            finally:
                _set_switch(monkeypatch, True)

            assert _ids(off) == base_ids, (
                "the alias seed expansion changed an in-flow closure: "
                f"nodes {sorted(_ids(off)[0] ^ base_ids[0])}, "
                f"edges {sorted(_ids(off)[1] ^ base_ids[1])}")
            assert off.get("search_matched") is True, off.get("search_matched")


# ════════════════════════════════════════════════════════════════════════
# 8. flagship: the S1 corpus misses become search_matched:true closures
# ════════════════════════════════════════════════════════════════════════

# (script, searched table, searched field, the alias-qualified reference the
# miss line must carry). All three are `search_matched: false` with an empty
# closure today and carry the searched field on the alias's owning entity.
FLAGSHIP = [
    ("BDM_ACC_LOAN_INFO_SUP_M.sql", "a", "data_dt", r"a\s*\.\s*data_dt"),
    ("EAST5_STZFXXB_M.sql", "a", "data_dt", r"a\s*\.\s*data_dt"),
    ("BDM_ACC_LOAN_INFO_Digitallending.sql", "SSALSFP", "ALCBP1",
     r"SSALSFP\s*\.\s*ALCBP1"),
]


@_NEEDS_FEATURE
class TestFlagshipCorpus:
    @pytest.mark.parametrize("script,table,field,pattern", FLAGSHIP)
    def test_alias_target_search_matched(self, script, table, field, pattern):
        """Searching an alias-qualified target on the S1 corpus must yield a
        real flow closure (`search_matched: true`), and the closure must be
        anchored on the alias's OWNING ENTITY: that entity's compound is in
        the served graph and the searched field's own occurrence lines are
        covered by an is_target chip.

        Gated on the sample file existing (the corpus is not shipped with
        the tests). No `slow` marker: none is registered in this repo."""
        path = SAMPLES_DIR / script
        if not path.exists():  # pragma: no cover — corpus layout change
            pytest.skip(f"sample missing: {path}")
        sql = path.read_text()
        assert re.search(pattern, sql, re.IGNORECASE), \
            f"fixture drift: {script} no longer references {table}.{field}"

        # The owning entities the expansion must seed (per-occurrence truth
        # from `alias_by_var_id`), and the lines their field occurrences sit
        # on — the closure has to reach them.
        pm = build_physical_model(run_full_analysis(sql, script),
                                  script_name=script)
        owners = sorted(k for k in _alias_owners(pm, table)
                        if _field_occurrences(pm, k, field))
        assert owners, (
            f"fixture drift: no alias {table!r} occurrence owns the field "
            f"{field!r} in {script}: {pm.alias_by_var_id}")
        owner_lines = set()
        for k in owners:
            fld = pm.fields[(k, field)]
            owner_lines.update(range(fld.line_first, (fld.line_last or
                                                      fld.line_first) + 1))
        owner_names = {pm.tables[k].name for k in owners}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(script, sql)
        ws_id = create_workspace(buf.getvalue())
        try:
            index_scripts(ws_id, [script])
            sr = _search(ws_id, table, field, script)
            assert script in sr["script_ids"], sr
            res = get_level2_graph(ws_id, sr["view_id"], script, table, field)

            # The S1 miss becomes a matched closure — never the full-graph
            # fallback with its not-in-flow banner. R4 L (2026-08-29): the
            # served level2 response writes `search_matched` ONLY as False
            # (absent ⇒ matched), so the old `is not False` could never fail;
            # the honest form asserts the matched default explicitly.
            assert res.get("search_matched", True) is True, (
                f"{script} {table}.{field}: still not in flow "
                f"({res.get('message')})")
            graph = res.get("graph") or {}
            assert graph.get("nodes"), f"{script}: empty served graph"
            served = {n["data"].get("table_name") for n in graph["nodes"]
                      if n["data"].get("type") != "field"}
            assert served & owner_names, (
                f"{script}: none of the owning entities {sorted(owner_names)} "
                f"is in the served closure (got {sorted(served)})")
            chips = [n["data"].get("line_start") for n in graph["nodes"]
                     if n["data"].get("type") == "field"
                     and n["data"].get("is_target")]
            assert chips, f"{script}: no is_target chip on the alias target"
            assert set(chips) & owner_lines, (
                f"{script}: the owning entities' {field} lines "
                f"{sorted(owner_lines)} are not covered by the closure "
                f"(chips at {sorted(set(chips))})")
        finally:
            delete_workspace(ws_id)
