"""F2 (audit #383): CTE attribution in table_index — folder_index_service.

Root cause: the index loop attributed FIELDS to a table entry (Bug 49:
alias → canonical/CTE name) but never the SCRIPT — only vt=="table" /
"merge_target" vars carried scripts. A CTE name that receives fields via
qualified references (``TEMP_RFN.dkjjbm``) therefore had ``scripts=[]``,
and create_search's match (``field_index[f].scripts ∩
table_index[t].scripts``) was always empty — a silent no_matches for
every CTE-qualified search (RFN: TEMP_RFN / TEMP_BDM_ACC_LOAN_INFO_01;
DL: temp_kmbh_gl / temp_kmbh_ie).

Fix invariant: any table_index entry that receives a field from script S
also records S in scripts (column branch, SELECT-output-alias branch,
Bug-41 DML cross-ref branch). The R20 ruling is preserved: a CTE
referenced only UNQUALIFIED still never enters table_index (no fields,
no scripts — nothing to search).
"""

import io
import json
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import index_scripts

# The F2 shape (RFN sample, shrunk): a CTE defined in the script and
# referenced through an alias — the qualified columns attribute fields to
# the CTE name (Bug 49 alias→canonical path), which is exactly the entry
# that used to carry scripts=[].
CTE_QUALIFIED_SQL = (
    "WITH temp_rfn AS (\n"
    "    SELECT t.dkjjbm AS dkjjbm, t.ignda AS ignda\n"
    "    FROM src_t t\n"
    ")\n"
    "INSERT INTO tgt (dkjjbm, ignda)\n"
    "SELECT r.dkjjbm, r.ignda FROM temp_rfn r;\n"
)

# R20 companion shape: the CTE is referenced only UNQUALIFIED — the
# extractor resolves `s` to the CTE, and the cte_names guard keeps the
# name out of the index entirely (test_cte_name_not_in_table_index).
CTE_UNQUALIFIED_SQL = (
    "WITH c AS (SELECT SUM(a) AS s FROM t) SELECT s FROM c;\n"
)


def _make_ws(entries: dict) -> str:
    """Zip-upload fixture pattern (test_s4b_resolution.py)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _index(entries: dict, scripts=None):
    """Create + index a workspace; returns (result, ws_id). Caller deletes."""
    ws_id = _make_ws(entries)
    names = scripts or list(entries)
    return index_scripts(ws_id, names), ws_id


class TestF2CteIndexAttribution:

    def test_cte_name_indexed_with_defining_script(self):
        """A CTE referenced via qualified columns carries its defining
        script in table_index — in-memory AND in the cached JSON the
        search endpoint loads."""
        r, ws_id = _index({"cte.sql": CTE_QUALIFIED_SQL})
        try:
            ti = r["table_index"]
            assert "temp_rfn" in ti, ti.keys()
            assert ti["temp_rfn"]["scripts"] == ["cte.sql"], ti["temp_rfn"]
            assert {"dkjjbm", "ignda"} <= set(ti["temp_rfn"]["fields"])
            # the persisted index (what /search actually reads) agrees
            cached = json.loads(
                (get_workspace_dir(ws_id) / "cache" / "table_index.json")
                .read_text())
            assert cached["temp_rfn"]["scripts"] == ["cte.sql"]
        finally:
            delete_workspace(ws_id)

    def test_cte_field_searchable(self):
        """The create_search match expression is non-empty for a
        CTE-qualified pair — field scripts ∩ CTE scripts finds the script
        (this intersection is exactly what create_search computes)."""
        r, ws_id = _index({"cte.sql": CTE_QUALIFIED_SQL})
        try:
            ti, fi = r["table_index"], r["field_index"]
            field_scripts = set(fi.get("dkjjbm", {}).get("scripts", []))
            table_scripts = set(ti.get("temp_rfn", {}).get("scripts", []))
            assert field_scripts & table_scripts == {"cte.sql"}, \
                (field_scripts, table_scripts)
        finally:
            delete_workspace(ws_id)

    def test_cte_scripts_scoped_to_defining_script(self):
        """The CTE entry carries ONLY the script that defines it — a
        sibling script touching other tables never leaks in."""
        r, ws_id = _index({
            "s1_cte.sql": CTE_QUALIFIED_SQL,
            "s2_other.sql": (
                "INSERT INTO other (x) SELECT b.x FROM src2 b;\n"),
        })
        try:
            ti = r["table_index"]
            assert "temp_rfn" in ti
            assert ti["temp_rfn"]["scripts"] == ["s1_cte.sql"], \
                ti["temp_rfn"]
        finally:
            delete_workspace(ws_id)

    def test_alias_entry_carries_script_too(self):
        """Bug 49 companion: the alias entry that receives the field (r)
        also carries the script — no fields-without-scripts zombies."""
        r, ws_id = _index({"cte.sql": CTE_QUALIFIED_SQL})
        try:
            ti = r["table_index"]
            assert "r" in ti, "alias entry missing — Bug 49 path regressed"
            assert ti["r"]["scripts"] == ["cte.sql"], ti["r"]
        finally:
            delete_workspace(ws_id)

    def test_unqualified_only_cte_stays_out(self):
        """R20 ruling preserved: a CTE referenced only unqualified never
        enters table_index — the fix adds scripts only where fields were
        already attributed."""
        r, ws_id = _index({"cte.sql": CTE_UNQUALIFIED_SQL})
        try:
            ti = r["table_index"]
            assert "c" not in ti, "CTE name leaked into table_index"
        finally:
            delete_workspace(ws_id)

    def test_no_fields_without_scripts_entries(self):
        """The general invariant on a mixed two-script workspace: every
        table_index entry with ≥1 field carries ≥1 script."""
        r, ws_id = _index({
            "s1_cte.sql": CTE_QUALIFIED_SQL,
            "s2_other.sql": (
                "INSERT INTO other (x) SELECT b.x FROM src2 b;\n"),
        })
        try:
            for tname, tdata in r["table_index"].items():
                assert not (tdata["fields"] and not tdata["scripts"]), \
                    "fields-without-scripts entry: %s" % tname
        finally:
            delete_workspace(ws_id)
