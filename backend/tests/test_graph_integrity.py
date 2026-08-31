"""Graph integrity tests — uses the topology checker module.

All topological checks are defined in app/services/topology_checker.py.
This test file runs them against every SQL sample.
"""

import sys
import re
from pathlib import Path
from collections import Counter

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import (
    _OCCURRENCE_PREFIX,
    build_dependency_graph,
)
from app.services.topology_checker import run_all_checks

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _all_sample_files():
    """Yield (filename, sql_text) for all test SQL files."""
    for f in sorted(SAMPLES_DIR.glob("*.sql")):
        if f.name.endswith(".sql"):
            yield f.name, f.read_text()
    fin_dir = SAMPLES_DIR / "financial"
    if fin_dir.exists():
        for f in sorted(fin_dir.glob("fin_query*.sql")):
            yield f"financial/{f.name}", f.read_text()


# R4 M (2026-08-29): an empty corpus must fail at COLLECTION time with the
# reason, not silently pass a zero-parameter test ("0 tests ran" green).
assert any(True for _ in _all_sample_files()), (
    f"sample corpus missing — no *.sql / financial/fin_query*.sql under "
    f"{SAMPLES_DIR}: the topology sweep would pass vacuously")


def _var_dicts(variables):
    """Convert VariableDefinition objects to dicts for the checker."""
    return [
        {
            "id": v.id,
            "name": v.name,
            "variable_type": v.variable_type.value,
            "source_columns": v.source_columns,
            "source_tables": v.source_tables,
            "defined_in": v.defined_in,
            "is_output": v.is_output,
        }
        for v in variables
    ]


def _dep_dicts(deps):
    """Convert VariableDependency objects to dicts for the checker."""
    return [
        {
            "source_id": d.source_id,
            "target_id": d.target_id,
            "relationship": d.relationship,
            "operation": d.operation,
            "sql_context": d.sql_context,
        }
        for d in deps
    ]


def _r44_occurrence_twin_names(vars_dict):
    """Every variable the extractor stamped as an occurrence-side twin.

    The stamp IS the marker `defined_in` carries (`OCCURRENCE` +
    the collected clause, dependency_graph._OCCURRENCE_PREFIX) — the only
    extraction-time statement that a var is an occurrence attribution
    rather than a schema member."""
    return {v["name"] for v in vars_dict
            if (v.get("defined_in") or "").upper().startswith(_OCCURRENCE_PREFIX)}


def _r44_derived_read_twin_names(vars_dict):
    """R44 (2026-08-28, user ruling "walker occurrence coverage") — the
    derived-read twins the extractor registers as occurrence-side fields
    (`_register_flow_occurrence_twins` family 2: the outer read
    `source.account_id` through a single-physical-source derived alias
    materializes the occurrence `gps_transactions.account_id`).

    These are occurrence ATTRIBUTIONS, not schema members — txn.txn_count
    (COUNT born inside the subquery) is not a column OF gps_transactions —
    so the checker's BELONGS_TO premise ("a dotted column is a member of
    its prefix table") does not apply. Their model witness is the REF edge
    from their occurrence origin (the derived-alias read), which the
    checker's accepted set (SCHEMA/SELECT/DML) does not count; the
    physical model keys them under the table entity.

    Signature (TIGHTENED 2026-08-29, R4 M-H): column, non-output,
    **`defined_in` carries the `OCCURRENCE` marker**, name =
    {source_tables[0]}.{col}, source_columns non-empty (the occurrence
    origin — family 3's line twins carry an empty list and are covered by
    Phase 4d-gb's belongs-to edge instead, so they need no waiver). The
    marker requirement is what makes the waiver a *scoped* waiver: the
    previous signature keyed on the name shape alone, which matched 88
    (file, column) members corpus-wide of which only **21** carry the
    marker — 67 ordinary columns sat inside the waiver's blast radius and
    it absorbed 14 live `column_connectivity` findings. Every name this
    predicate returns is asserted to be an occurrence twin; anything else
    must be adjudicated in `_ADJUDICATED_CONNECTIVITY` below, one entry at
    a time.

    Write twins are NOT waived: they are only written, and their write-leg
    witness (Phase 4c OUTPUT SCHEMA) exists — the checker's contract
    'every displayed field has a model edge' holds for them and must keep
    holding."""
    occurrence = _r44_occurrence_twin_names(vars_dict)
    names = set()
    for v in vars_dict:
        if v.get("variable_type") != "column":
            continue
        st = v.get("source_tables") or []
        name = v.get("name") or ""
        if (not v.get("is_output") and v.get("source_columns")
                and name in occurrence
                and st and "." in name
                and name.split(".", 1)[0].lower() == st[0].lower()):
            names.add(name)
    # R4 M-H: the waiver is *stated* as an occurrence-twin waiver, so it
    # can only ever be a subset of the occurrence twins. If this fires, the
    # predicate drifted away from the marker that justifies it.
    assert names <= occurrence, (
        "the R44 twin waiver admitted a variable the extractor never "
        f"stamped as an occurrence twin: {sorted(names - occurrence)}")
    return names


# ════════════════════════════════════════════════════════════════════════
# Adjudicated column_connectivity residue (R4 M-H, 2026-08-29)
# ════════════════════════════════════════════════════════════════════════
# The pre-tightening signature absorbed 14 live `column_connectivity`
# findings corpus-wide; two of the 14 stay covered by the (now marker-gated)
# occurrence waiver itself — the same column name also has an occurrence
# twin in that file — so the rest were handed back here, every entry
# carrying its own verdict. An entry that fires is an entry whose verdict is
# checked; an entry that no longer fires must be DELETED (asserted below).
#
# H11 (2026-08-31): the 7 DEFECT entries — fin_query4's
# gps_transactions.amount/.fee_amount/.txn_id/.settlement_date (MERGE UPDATE
# SET) and .net_amount/.currency_code (MERGE WHEN), fin_query14's
# gps_transactions.merchant_id (JOIN ON) — are FIXED and retired from this
# list: dependency_graph Phase 4d-gc now gives a physical-owner column of a
# MERGE/JOIN ON clause its belongs-to SCHEMA edge from the owner's table
# entity (mirroring the 4d-gb pattern), admission-gated on the model's own
# schema evidence that the owner really has the field. Exactly those 7 edges
# corpus-wide; pinned by tests/test_merge_connectivity.py.
#
# The 7 remaining entries are FALSE POSITIVE — the check's premise does not
# hold for the var: it is NOT a member of its prefix table (a renamed
# projection, an aggregate born in a derived scope, a bare group key owned
# by a derived container), so the missing belongs-to edge is CORRECT and
# emitting it would fabricate a schema fact. The evidence gate is what keeps
# them out; their connectivity witness is the REF from the reference they
# came from.
_ADJUDICATED_CONNECTIVITY = {
    "financial/fin_query4_merge_upsert.sql": {
        # `ON target.account_id = source.account_id` @25 — `source` is the
        # MERGE USING alias and `account_id` is its RENAMED projection
        # (`t.source_account_id AS account_id` @8): gps_transactions has no
        # account_id column in this script, so the belongs-to premise is
        # false. Witness: REF in from `source.account_id` + the DML legs to
        # both merge-target instances of gps_accounts.
        "gps_transactions.account_id":
            "FALSE POSITIVE — renamed USING projection, not a "
            "gps_transactions column (t.source_account_id AS account_id @8)",
    },
    "financial/fin_query8_multi_party_settlement.sql": {
        # `GROUP BY party_id, party_type` @155 inside CTE party_net_positions
        # — bare keys of the DERIVED container `positions`, whose outputs
        # are renamed settlement_legs columns (`sl.debit_party_id AS
        # party_id`). gps_exchange_rates never provides either field here (it
        # appears only as the scalar rate lookup @142-149), so the owner is
        # the single-visible-table fallback and the belongs-to premise is
        # false: emitting the edge would fabricate a schema fact. Witness:
        # REF in from the bare key + REF out to the CTE.
        "gps_exchange_rates.party_id":
            "FALSE POSITIVE — bare GROUP BY key of the derived `positions` "
            "container (sl.debit_party_id AS party_id); gps_exchange_rates "
            "never provides it in this script, so the owner is a "
            "single-visible-table fallback attribution",
        "gps_exchange_rates.party_type":
            "FALSE POSITIVE — bare GROUP BY key of the derived `positions` "
            "container (sl.debit_party_type AS party_type); same fallback "
            "owner as party_id",
    },
    "financial/fin_query14_recursive_account_hierarchy.sql": {
        # `COALESCE(txn.txn_count, 0) AS node_txn_count` @87-90 — txn is the
        # derived subquery @92-107 and each field is an aggregate BORN there
        # (COUNT(t.txn_id), SUM(...), SUM(CASE ...)). Not columns of
        # gps_transactions — the R44 rationale's own named example.
        "gps_transactions.txn_count":
            "FALSE POSITIVE — aggregate born inside the derived `txn` "
            "subquery (COUNT(t.txn_id) @95), not a gps_transactions column",
        "gps_transactions.total_volume":
            "FALSE POSITIVE — aggregate born inside the derived `txn` "
            "subquery (SUM(t.settlement_amount) @96)",
        "gps_transactions.total_fees":
            "FALSE POSITIVE — aggregate born inside the derived `txn` "
            "subquery (SUM(COALESCE(t.merchant_discount,0)+…) @97-100)",
        "gps_transactions.chargeback_count":
            "FALSE POSITIVE — aggregate born inside the derived `txn` "
            "subquery (SUM(CASE WHEN t.txn_type='CHARGEBACK'…) @101-102)",
    },
}


# The topology checker's issue IDENTITY header: every issue opens with
# `[<variable_type>] <name>: ` and only the prose after that colon varies
# per check. Waiving on the PARSED identity (never on rendered prose)
# keeps the R44 waiver alive across wording changes — review L19.
_ISSUE_HEADER = re.compile(r"^\[(?P<vt>[^\]]+)\] (?P<name>.+?): ")
# isolated_nodes appends the offending edge count ("1e, need ≥2").
_EDGE_COUNT = re.compile(r"^(?P<n>\d+)e\b")


def _apply_twin_waiver(issues, waived, require_edge=False):
    """Drop the issues that name a waived R44 read twin.

    Returns (kept, unparsed). `unparsed` holds issues that mention a
    waived twin but do not match _ISSUE_HEADER (or, when require_edge is
    set, whose edge count is not a bare integer) — a checker message
    change must fail LOUDLY here ("update the header parser"), never
    silently disable the waiver.
    require_edge: isolated_nodes waives a read twin only when it still
    carries ≥1 edge — the REF witness from its occurrence origin. A twin
    with 0 edges is a real regression and stays a hard error.
    """
    kept, unparsed = [], []
    for issue in issues:
        m = _ISSUE_HEADER.match(issue)
        if m is None:
            if any(name in issue for name in waived):
                unparsed.append(issue)
            else:
                kept.append(issue)
            continue
        if m.group("name") not in waived:
            kept.append(issue)
            continue
        if require_edge:
            c = _EDGE_COUNT.match(issue[m.end():])
            if c is None:
                unparsed.append(issue)
                continue
            if int(c.group("n")) < 1:
                kept.append(issue)   # 0-edge twin: real regression
                continue
    return kept, unparsed


class TestGraphIntegrity:
    """Run ALL topology checks against every SQL sample."""

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_topology_checks_pass(self, fname, sql):
        """Hard-error topology checks must return zero issues.

        Informational checks (component_link_usage, ambiguous_base_names)
        are warnings, not errors — they don't cause test failure.
        """
        r = extract_variables_from_sql(sql, fname)
        if len(r.variables) == 0:
            # R4 M (2026-08-29): a DDL file contributes no variables, which
            # is a legitimate SKIP — a silent `return` is indistinguishable
            # from a test that never ran.
            pytest.skip("DDL file — no variables to check")
        deps = build_dependency_graph(r, "")
        vars_dict = _var_dicts(r.variables)
        deps_dict = _dep_dicts(deps)

        results = run_all_checks(vars_dict, deps_dict)
        # R44 (2026-08-28): derived-read twins are occurrence attributions
        # (REF-witnessed by their origin read), not schema members —
        # their column_connectivity findings are waived (see
        # _r44_derived_read_twin_names). Write twins stay covered.
        waived = _r44_derived_read_twin_names(vars_dict)
        # R4 M-H (2026-08-29): the adjudicated residue the tightened
        # predicate hands back. Each entry carries its own verdict; a
        # listed entry that no longer fires is a WAIVER THAT LOST ITS
        # DEFECT — the fix landed, so delete the entry (and the defect
        # note with it) instead of letting the list rot.
        info_checks = {"component_link_usage", "ambiguous_base_names", "alias_edges", "tables_view_isolation", "duplicate_nodes", "duplicate_table_names", "node_name_uniqueness"}
        adjudicated = _ADJUDICATED_CONNECTIVITY.get(fname, {})
        if adjudicated:
            firing = set()
            for check, issues in results.items():
                if check in info_checks:
                    continue
                for issue in issues:
                    m = _ISSUE_HEADER.match(issue)
                    if m is not None:
                        firing.add(m.group("name"))
            stale = set(adjudicated) - firing
            assert stale == set(), (
                f"{fname}: adjudicated waiver entries that no longer fire — "
                f"the defect was fixed (or the checker stopped reporting "
                f"it), so DELETE the entries and their defect notes: "
                f"{sorted(stale)}")
        unparsed = []
        if waived or adjudicated:
            # column_connectivity: the twin's witness is the REF from its
            # occurrence origin, which the check's accepted set
            # (SCHEMA/SELECT/DML) does not count.
            # isolated_nodes: that same single-REF witness can sit under
            # the check's "dotted column needs ≥2 edges" bar — same
            # false-positive class, so the same identity is waived there
            # (≥1 edge only; a 0-edge twin stays a hard error). The
            # adjudicated residue is column_connectivity-only by verdict:
            # none of its members is a 0-edge node.
            for check, require_edge in (("column_connectivity", False),
                                        ("isolated_nodes", True)):
                if check not in results:
                    continue
                names = waived | (set(adjudicated)
                                  if check == "column_connectivity" else set())
                if not names:
                    continue
                results[check], bad = _apply_twin_waiver(
                    results[check], names, require_edge=require_edge)
                unparsed += bad
        assert unparsed == [], (
            "topology_checker issue text no longer matches the "
            f"`[<type>] <name>:` header the R44 twin waiver parses "
            f"(update _ISSUE_HEADER, do not re-pin prose): {unparsed}")
        hard_errors = {k: v for k, v in results.items()
                       if v and k not in info_checks}
        assert len(hard_errors) == 0, \
            f"{fname}: {len(hard_errors)} hard errors: " \
            + "; ".join(f"{name}: {issues}" for name, issues in hard_errors.items())
