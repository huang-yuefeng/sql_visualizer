"""R46b (AD3, 2026-08-31): the folder index must never attribute an AS-alias
OUTPUT name to the table the VALUE was read from.

FSB/AD3 audited the index against the S1 corpus and found 7 phantom pairs —
an ``is_output`` variable whose NAME is an ``AS`` alias was indexed under its
``source_tables`` entry (the read source), so search offered

    bdm_acc_entrusted_payment.bz              (a.ccy_code AS bz)
    bdm_acc_entrusted_payment.RESERVED_6      (A.Reserved_Field18 AS RESERVED_6)
    bdm_acc_entrusted_payment.COM_RESERVED_1  (a.charge_department AS COM_RESERVED_1)
    bdm_acc_loan_info.dkje                    (b.loan_amt AS dkje)
    bdm_acc_loan_info.nbjgh                   (b.org_no AS nbjgh)
    bdm_acc_loan_info.xdhth                   (b.contract_no AS xdhth)
    bdm_acc_loan_info.xdjjh                   (b.lending_ref AS xdjjh)

and none of those tables hosts such a column — zero-seed closures for a
search that names the pair, mis-parented chips in L2 (6 of #37's residual
``consumed`` steps ride exactly this wrong attribution).

Rule as implemented (AD3): in the index column-attribution loop, a
top-level statement OUTPUT whose NAME RENAMES the projected value is
attributed to the DML WRITE TARGET only (``dml_target_by_src_id`` — Fix A's
map) and never to the value's read source. That is the SAME convention Fix A
(#308) already applies to non-column expression aliases
(``INSERT INTO tgt SELECT <expr> AS col`` indexes ``col`` under ``tgt``; a
bare SELECT's renamed alias has no write target and stays un-attributed).

The rename guard (``_is_renamed_output``) is what keeps the rule from eating
true evidence: a projection that does NOT rename its value
(``SELECT s.c_first_name``, ``s.tag_country AS tag_country``) has a name that
IS the read column's name — that attribution is the ordinary S1–S3
read-column attribution and is untouched. Renamed projections lose nothing
either: their value column is a SEPARATE non-output var (``a.ccy_code``) and
keeps indexing the read source.

Every fixture here was probed against the working tree before being pinned
(EAST5_STZFXXB_M.sql + synthetic shapes, gps-sql-backend).
"""

import io
import json
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.folder_index_service import (  # noqa: E402
    index_scripts,
)
from app.services.workspace_service import (  # noqa: E402
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)

EAST5 = "EAST5_STZFXXB_M.sql"
EAST5_PATH = BACKEND_DIR.parent / "samples" / "sql_sample_v1" / EAST5
WRITE_TARGET = "east5_stzfxxb"

# The 7 adjudicated pairs: (AS-alias output name, table the value came from).
PHANTOM_PAIRS = [
    ("nbjgh", "bdm_acc_loan_info"),
    ("xdhth", "bdm_acc_loan_info"),
    ("xdjjh", "bdm_acc_loan_info"),
    ("dkje", "bdm_acc_loan_info"),
    ("bz", "bdm_acc_entrusted_payment"),
    ("RESERVED_6", "bdm_acc_entrusted_payment"),
    ("COM_RESERVED_1", "bdm_acc_entrusted_payment"),
]

# (alias, the value's own column, the read source it must stay indexed under)
READ_COLUMNS = [
    ("nbjgh", "org_no", "bdm_acc_loan_info"),
    ("xdhth", "contract_no", "bdm_acc_loan_info"),
    ("xdjjh", "lending_ref", "bdm_acc_loan_info"),
    ("dkje", "loan_amt", "bdm_acc_loan_info"),
    ("bz", "ccy_code", "bdm_acc_entrusted_payment"),
    ("RESERVED_6", "Reserved_Field18", "bdm_acc_entrusted_payment"),
    ("COM_RESERVED_1", "charge_department", "bdm_acc_entrusted_payment"),
]

pytestmark = pytest.mark.skipif(not EAST5_PATH.exists(),
                                reason="sample corpus not present")


@contextmanager
def _indexed(name: str, sql: str):
    """Create + index a one-script workspace; always deletes it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, sql)
    ws_id = create_workspace(buf.getvalue())
    try:
        yield index_scripts(ws_id, [name]), ws_id
    finally:
        delete_workspace(ws_id)


def _tables(result: dict, field: str) -> set:
    return set(result["field_index"].get(field, {}).get("tables", []))


@pytest.fixture(scope="module")
def east5():
    """One EAST5 workspace for the whole class (indexing it is the cost)."""
    with _indexed(EAST5, EAST5_PATH.read_text(encoding="utf-8")) as pair:
        yield pair


class TestEast5PhantomPairs:
    """The 7 AD3 pairs on the production sample that produced them."""

    def test_alias_never_indexed_under_read_source(self, east5):
        """THE rule: the alias name is not a column of the read-source table."""
        result, _ws = east5
        for alias, read_source in PHANTOM_PAIRS:
            assert read_source not in _tables(result, alias), (
                f"{read_source}.{alias} is still a phantom index pair")

    def test_alias_indexed_under_write_target(self, east5):
        """The alias name IS the target column produced by the INSERT..SELECT
        — the write target owns it, exactly as Fix A's expression aliases."""
        result, _ws = east5
        for alias, _read_source in PHANTOM_PAIRS:
            tables = _tables(result, alias)
            assert WRITE_TARGET in tables, (alias, sorted(tables))

    def test_write_target_field_list_carries_the_aliases(self, east5):
        """table_index[write_target] offers the alias names for autocomplete."""
        result, _ws = east5
        fields = set(result["table_index"][WRITE_TARGET]["fields"])
        for alias, _read_source in PHANTOM_PAIRS:
            assert alias in fields, (alias, sorted(fields))

    def test_read_source_value_column_still_indexed(self, east5):
        """No recall is traded away: the projected column keeps its own
        read-source attribution (it is a separate non-output variable)."""
        result, _ws = east5
        for _alias, column, read_source in READ_COLUMNS:
            assert read_source in _tables(result, column), (
                f"{read_source}.{column} lost its read attribution")

    def test_pair_index_holds_no_phantom_pair(self, east5):
        """The persisted pair_index.json (the search's seed lookup) agrees."""
        result, ws_id = east5
        pair_index = json.loads(
            (get_workspace_dir(ws_id) / "cache" / "pair_index.json").read_text())
        for alias, read_source in PHANTOM_PAIRS:
            assert f"{read_source}.{alias}" not in pair_index
            assert f"{WRITE_TARGET}.{alias}" in pair_index
            assert set(pair_index[f"{WRITE_TARGET}.{alias}"]) == \
                set(result["field_index"][alias]["scripts"])


class TestAliasAttributionShapes:
    """The mechanism, isolated on synthetic shapes (one script per workspace,
    so no other script's attribution bleeds into an assertion)."""

    def test_renamed_alias_goes_to_write_target_not_read_source(self):
        sql = ("INSERT INTO tgt_acct (nbjgh, xdhth)\n"
               "SELECT b.org_no AS nbjgh, b.contract_no AS xdhth\n"
               "FROM src_loan b;\n")
        with _indexed("renamed.sql", sql) as (result, _ws):
            assert _tables(result, "nbjgh") == {"tgt_acct"}
            assert _tables(result, "xdhth") == {"tgt_acct"}
            # the value's own columns keep their read attribution
            assert {"b", "src_loan"} <= _tables(result, "org_no")
            assert {"b", "src_loan"} <= _tables(result, "contract_no")
            # the write target offers both, from this script (F2 invariant)
            ti = result["table_index"]["tgt_acct"]
            assert {"nbjgh", "xdhth"} <= set(ti["fields"])
            assert ti["scripts"] == ["renamed.sql"]

    def test_unrenamed_projection_keeps_read_source(self):
        """``SELECT s.col …`` and ``s.col AS col`` are NOT renames — the name
        is the read column's own name (S1-S3 read attribution stands)."""
        sql = ("INSERT INTO tgt_cust\n"
               "SELECT s.c_first_name, s.tag_country AS tag_country\n"
               "FROM src_cust s;\n")
        with _indexed("samename.sql", sql) as (result, _ws):
            assert {"s", "src_cust"} <= _tables(result, "c_first_name")
            assert {"s", "src_cust"} <= _tables(result, "tag_country")
            # (the extra tgt_cust entry is the PRE-EXISTING positional
            # INSERT target-side mapping — Bug 41's domain, untouched here)

    def test_bare_select_renamed_alias_stays_unattributed(self):
        """#308: a bare SELECT's renamed output alias has no write target and
        is never indexed under the table it was read from."""
        sql = "SELECT b.org_no AS nbjgh FROM src_loan b;\n"
        with _indexed("bare.sql", sql) as (result, _ws):
            assert _tables(result, "nbjgh") == set()
            assert result["field_index"]["nbjgh"]["scripts"] == ["bare.sql"]
            # the read column itself is untouched
            assert {"b", "src_loan"} <= _tables(result, "org_no")

    def test_subquery_interior_alias_keeps_read_source(self):
        """Fix A's scope convention: a subquery-interior alias is not a
        workspace-wide output, so it keeps the read-source attribution it
        always had (only top-level statement outputs move)."""
        sql = ("INSERT INTO tgt_sub\n"
               "SELECT d.nbjgh FROM (SELECT b.org_no AS nbjgh FROM src_loan b) d;\n")
        with _indexed("subq.sql", sql) as (result, _ws):
            assert "src_loan" in _tables(result, "nbjgh")

    def test_normal_column_attribution_unchanged(self):
        """Plain qualified/unqualified column reads index exactly as before —
        R46b only moves renamed output aliases."""
        sql = ("INSERT INTO tgt_two\n"
               "SELECT s.acct_no, s.curr_cd FROM src_two s;\n")
        with _indexed("plain.sql", sql) as (result, _ws):
            assert {"s", "src_two"} <= _tables(result, "acct_no")
            assert {"s", "src_two"} <= _tables(result, "curr_cd")
            assert result["table_index"]["src_two"]["scripts"] == ["plain.sql"]
