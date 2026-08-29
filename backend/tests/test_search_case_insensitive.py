"""F5 (audit #383, R2.10) at the SEARCH layer — backend case-insensitive
name resolution for create_search + the R17 diagnostic.

Precedent: the frontend ruling already declared SQL identifiers
case-insensitive and shipped `resolveNameCi()` (utils/nameFilter.js) — but
that fixed the FRONTEND echo only. The backend still matched index keys
EXACTLY, and index keys carry whatever casing each script wrote, so on the
flagship corpus:

  * `bdm_acc_loan_info.dm_flag2` matched [PL] while
    `bdm_acc_loan_info.DM_FLAG2` matched [DL, RFN, EAST5] — DISJOINT sets
    for one column;
  * natural spellings (`BDM_ACC_LOAN_INFO.lending_ref`, `T.acct_no`,
    `TEMP_ZCHX.zchxbz`, ...) returned no_matches outright.

Fix (folder_index_service.resolve_name_ci / scripts_for_name_ci + the
create_search call site): the matched SCRIPT set is the UNION over every
case-variant key (ISSUE-4 — one index identity), and the canonical
spelling (exact key first, else the ISSUE-4 majority spelling) replaces
the typed one on the view, the response and the L1 build.

Issue-4 precedent tests (extractor side): test_variable_extractor.py
(TestCaseSensitivePhysicalTableIdentity), test_s4b_resolution.py.
"""

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (  # noqa: E402
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import (  # noqa: E402
    _majority_index_spelling,
    autocomplete,
    fields_for_table,
    resolve_name_ci,
    scripts_for_name_ci,
    tables_for_field,
)

# The disjoint-spelling shape: the SAME column written lowercase in one
# script and uppercase in the next, against a table whose name also flips
# case between the scripts. Pre-fix: field_index carries `dm_flag2` [pl]
# and `DM_FLAG2` [dl] (disjoint), table_index carries `bdm_src` [pl] and
# `BDM_SRC` [dl] — every cross-case query was a silent no_matches.
PL_SQL = (
    "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
    "SELECT a.dm_flag2 AS dm_flag2 FROM bdm_src a;\n"
)
DL_SQL = (
    "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
    "SELECT B.DM_FLAG2 AS DM_FLAG2 FROM BDM_SRC B;\n"
)


def _make_ws(entries: dict) -> str:
    """Zip-upload fixture pattern (test_folder_index_cte.py)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _indexed_ws(entries: dict):
    """Create + index a workspace; returns (ws_id, ti, fi). Caller deletes."""
    ws_id = _make_ws(entries)
    from app.services.folder_index_service import index_scripts
    names = list(entries)
    index_scripts(ws_id, names)
    cache_dir = get_workspace_dir(ws_id) / "cache"
    ti = json.loads((cache_dir / "table_index.json").read_text())
    fi = json.loads((cache_dir / "field_index.json").read_text())
    return ws_id, ti, fi


def _search(ws_id, ti, fi, table, field, direction="downstream"):
    from app.services.dataflow_service import create_search
    return asyncio.run(create_search(ws_id, table, field, ti, fi,
                                     direction=direction))


# ════════════════════════════════════════════════════════════════════════
# Unit: the resolver itself (synthetic index — no workspace needed)
# ════════════════════════════════════════════════════════════════════════

class TestResolveNameCi:
    IDX = {
        "DM_FLAG2": {"scripts": ["dl.sql", "rfn.sql", "east5.sql"],
                     "tables": ["bdm_acc_loan_info"]},
        "dm_flag2": {"scripts": ["pl.sql"], "tables": ["bdm_acc_loan_info"]},
    }

    def test_exact_key_wins_and_returns_whole_group(self):
        """A typed string that IS an index key is the canonical spelling —
        but the group is still EVERY case variant (the caller unions)."""
        canon, group = resolve_name_ci(self.IDX, "dm_flag2")
        assert canon == "dm_flag2", (canon, group)
        assert sorted(group) == ["DM_FLAG2", "dm_flag2"], group

    def test_case_insensitive_hit_resolves_to_majority_spelling(self):
        """No exact key → the ISSUE-4 majority spelling (most scripts)."""
        canon, group = resolve_name_ci(self.IDX, "Dm_Flag2")
        assert canon == "DM_FLAG2", canon
        assert sorted(group) == ["DM_FLAG2", "dm_flag2"], group

    def test_majority_rule_lowercase_preferred_on_tie(self):
        """ISSUE-4 tie rule: equal script counts prefer the lowercase
        spelling (mirrors the extractor's `_majority_spelling`)."""
        idx = {
            "Foo": {"scripts": ["a.sql"], "tables": []},
            "foo": {"scripts": ["b.sql"], "tables": []},
        }
        assert _majority_index_spelling(idx, list(idx)) == "foo", idx

    def test_majority_rule_first_seen_on_full_tie(self):
        """Same count AND same case-ness → the index's own key order (the
        first-seen spelling) decides — deterministic, not arbitrary."""
        idx = {
            "ABC": {"scripts": ["a.sql"], "tables": []},
            "ABc": {"scripts": ["b.sql"], "tables": []},
        }
        assert _majority_index_spelling(idx, ["ABC", "ABc"]) == "ABC", idx
        assert _majority_index_spelling(
            {"ABc": idx["ABc"], "ABC": idx["ABC"]},
            ["ABc", "ABC"]) == "ABc"

    def test_no_match_returns_none(self):
        assert resolve_name_ci(self.IDX, "ghost") == (None, [])
        # Case-insensitivity is NOT a fuzzy match: a prefix / one-char-off
        # query is a MISS (that is the autocomplete dropdown's job).
        assert resolve_name_ci(self.IDX, "dm_flag") == (None, [])
        assert resolve_name_ci(self.IDX, "dm_flag3") == (None, [])

    def test_blank_query_resolves_to_nothing(self):
        assert resolve_name_ci(self.IDX, "") == (None, [])
        assert resolve_name_ci(self.IDX, "   ") == (None, [])
        assert resolve_name_ci(self.IDX, None) == (None, [])

    def test_scripts_for_name_ci_unions_case_variants(self):
        """THE fix: both spellings of one column return the SAME script set
        (the union), so the search can never again report disjoint sets."""
        expected = {"dl.sql", "rfn.sql", "east5.sql", "pl.sql"}
        assert scripts_for_name_ci(self.IDX, "dm_flag2") == expected
        assert scripts_for_name_ci(self.IDX, "DM_FLAG2") == expected
        assert scripts_for_name_ci(self.IDX, "Dm_Flag2") == expected
        assert scripts_for_name_ci(self.IDX, "ghost") == set()

    def test_index_entry_helpers_resolve_ci(self):
        """tables_for_field / fields_for_table follow the same resolution."""
        assert tables_for_field(self.IDX, "dm_flag2") == ["bdm_acc_loan_info"]
        assert fields_for_table({"bdm_src": {"fields": ["DM_FLAG2"]}},
                                "BDM_SRC") == ["DM_FLAG2"]
        assert fields_for_table({"bdm_src": {"fields": ["DM_FLAG2"]}},
                                "ghost") == []


class TestAutocompleteAlreadyCaseInsensitive:
    """Requirement guard: autocomplete was ALREADY case-insensitive
    (substring primary + exact/prefix/Levenshtein ranking over folded
    keys) — the search-layer fix must not change that."""

    IDX = {
        "dm_flag2": {"scripts": ["pl.sql"], "tables": []},
        "DM_FLAG2": {"scripts": ["dl.sql"], "tables": []},
        "DM_FLAG2X": {"scripts": ["dl.sql"], "tables": []},
    }

    def test_uppercase_query_surfaces_lowercase_key(self):
        out = autocomplete(self.IDX, "field", "DM_FLAG2")
        # NOTE (pre-existing behavior, unchanged here): the dropdown dedupes
        # case-insensitively, so two spellings of one name collapse to the
        # sorted-first one. The contract under test: a query in ANY casing
        # surfaces the entry.
        assert "dm_flag2" in {s.lower() for s in out}, out

    def test_lowercase_query_surfaces_uppercase_key(self):
        out = autocomplete(self.IDX, "field", "dm_flag2")
        assert "dm_flag2" in {s.lower() for s in out}, out

    def test_single_variant_index_round_trips_any_case(self):
        idx = {"east5_stzfxxb": {"scripts": ["a.sql"], "tables": []}}
        assert autocomplete(idx, "table", "EAST5_STZFXXB") == ["east5_stzfxxb"]


# ════════════════════════════════════════════════════════════════════════
# Search layer: create_search resolves through the same helpers
# ════════════════════════════════════════════════════════════════════════

class TestSearchCaseVariantUnion:
    """(a) Disjoint case-variant keys now union their scripts."""

    def test_disjoint_case_variant_field_keys_union_scripts(self):
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            # Precondition: the index really does carry the disjoint keys.
            assert fi["dm_flag2"]["scripts"] == ["pl.sql"], fi["dm_flag2"]
            assert fi["DM_FLAG2"]["scripts"] == ["dl.sql"], fi["DM_FLAG2"]
            assert ti["bdm_src"]["scripts"] == ["pl.sql"], ti["bdm_src"]
            assert ti["BDM_SRC"]["scripts"] == ["dl.sql"], ti["BDM_SRC"]

            union = ["dl.sql", "pl.sql"]
            for table, field in (("bdm_src", "dm_flag2"),
                                 ("bdm_src", "DM_FLAG2"),
                                 ("BDM_SRC", "dm_flag2"),
                                 ("BDM_SRC", "DM_FLAG2")):
                r = _search(ws_id, ti, fi, table, field)
                assert r["script_ids"] == union, (table, field, r)
                assert r["match_mode"] != "no_matches", (table, field, r)
        finally:
            delete_workspace(ws_id)

    def test_union_is_identical_whatever_casing_arrives(self):
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            results = [_search(ws_id, ti, fi, t, f)["script_ids"]
                       for t, f in (("bdm_src", "dm_flag2"),
                                    ("BDM_SRC", "DM_FLAG2"),
                                    ("Bdm_Src", "Dm_Flag2"))]
            assert results[0] == results[1] == results[2], results
        finally:
            delete_workspace(ws_id)


class TestSearchNaturalSpelling:
    """(b) Natural-spelling searches stop returning no_matches."""

    def test_natural_spellings_match(self):
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            for table, field in (("BDM_SRC", "dm_flag2"),
                                 ("bdm_src", "dm_flag2"),
                                 ("Bdm_Src", "dm_flag2")):
                r = _search(ws_id, ti, fi, table, field)
                assert r["match_mode"] != "no_matches", (table, field, r)
                assert r["script_ids"] == ["dl.sql", "pl.sql"], r
        finally:
            delete_workspace(ws_id)

    def test_natural_spelling_no_matches_message_quotes_resolved_name(self):
        """A genuine miss keeps the honest BE2 banner; the message quotes the
        RESOLVED canonical spelling when one exists, the typed one when it
        does not."""
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            # No case variant of ghost_field exists → typed spelling echoed.
            r = _search(ws_id, ti, fi, "BDM_SRC", "ghost_field")
            assert r["match_mode"] == "no_matches", r
            assert "ghost_field" in r["message"], r
            assert r["script_ids"] == [], r
        finally:
            delete_workspace(ws_id)

    def test_exact_match_single_variant_unchanged(self):
        """(d) Regression: a workspace whose keys are single-variant keeps
        the exact-match behavior — same script set, same echo."""
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL})
        try:
            assert fi["dm_flag2"]["scripts"] == ["pl.sql"], fi
            r = _search(ws_id, ti, fi, "bdm_src", "dm_flag2")
            assert r["match_mode"] != "no_matches", r
            assert r["script_ids"] == ["pl.sql"], r
            assert r["table"] == "bdm_src", r
            assert r["field"] == "dm_flag2", r
        finally:
            delete_workspace(ws_id)


class TestSearchCanonicalEcho:
    """(c) Ambiguous case variants resolve DETERMINISTICALLY, and the
    resolved spelling is what the view/response/L1 build carry."""

    def test_exact_typed_key_is_echoed(self):
        """Frontend resolveNameCi ruling: a caller that sent a real index
        key must not be rewritten."""
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            r = _search(ws_id, ti, fi, "BDM_SRC", "DM_FLAG2")
            assert r["table"] == "BDM_SRC", r
            assert r["field"] == "DM_FLAG2", r
        finally:
            delete_workspace(ws_id)

    def test_non_exact_input_resolves_to_majority_spelling(self):
        """No exact key → the ISSUE-4 rule over the group: one script per
        spelling here, so the lowercase tie-break decides. Every input
        casing resolves to the SAME script set (the union) — the echo
        differs only when the input IS a key (exact wins)."""
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            unions = [tuple(_search(ws_id, ti, fi, t, f)["script_ids"])
                      for t, f in (("Bdm_Src", "Dm_Flag2"),
                                   ("BDM_SRC", "DM_FLAG2"),
                                   ("bdm_src", "dm_flag2"))]
            assert unions == [("dl.sql", "pl.sql")] * 3, unions
            # Lowercase-preferred tie-break (ISSUE-4) for the non-exact
            # input, both for the field and for the table the view carries.
            r = _search(ws_id, ti, fi, "Bdm_Src", "Dm_Flag2")
            assert r["field"] == "dm_flag2", r
            assert r["table"] == "bdm_src", r
        finally:
            delete_workspace(ws_id)

    def test_resolution_is_deterministic_across_repeats(self):
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            echoes = {_search(ws_id, ti, fi, "BDM_SRC", "dm_flag2")["field"]
                      for _ in range(3)}
            assert len(echoes) == 1, echoes
        finally:
            delete_workspace(ws_id)

    def test_majority_spelling_wins_when_script_counts_differ(self):
        """Three scripts write the uppercase spelling, one the lowercase →
        the canonical echo is the uppercase majority (the spelling most
        scripts wrote — the L2 per-script seed is case-sensitive, so the
        majority spelling serves the most scripts)."""
        idx = {
            "DM_FLAG2": {"scripts": ["a.sql", "b.sql", "c.sql"], "tables": []},
            "dm_flag2": {"scripts": ["d.sql"], "tables": []},
        }
        assert resolve_name_ci(idx, "Dm_Flag2")[0] == "DM_FLAG2", idx


class TestSearchDiagnosticCi:
    """R17 diagnostic: presence + script counts use the same resolution, so
    a case-variant query is never mis-diagnosed as "not in the index"."""

    TI = {"bdm_src": {"scripts": ["pl.sql"], "fields": ["dm_flag2"]},
          "BDM_SRC": {"scripts": ["dl.sql"], "fields": ["DM_FLAG2"]}}
    FI = {"dm_flag2": {"scripts": ["pl.sql"], "tables": ["bdm_src"]},
          "DM_FLAG2": {"scripts": ["dl.sql"], "tables": ["BDM_SRC"]}}

    def _values(self, table, field, ti, fi, result):
        from app.routers.dataflow import _search_diagnostic_values
        return _search_diagnostic_values(
            table, field, ti, fi, result, False, len(ti), len(fi),
            bool(resolve_name_ci(ti, table)[1]),
            bool(resolve_name_ci(fi, field)[1]))

    def test_case_variant_query_is_in_index(self):
        v = self._values("BDM_SRC", "dm_flag2", self.TI, self.FI,
                         {"script_ids": ["dl.sql", "pl.sql"]})
        # (filter_active, scope_tables, scope_fields, table_in_index,
        #  field_in_index, table_scripts, field_scripts, match_scripts, sug)
        assert v[3] is True and v[4] is True, v
        assert v[5] == 2 and v[6] == 2, v
        assert v[8] == "OK", v

    def test_absent_field_still_reports_absent(self):
        v = self._values("BDM_SRC", "ghost_field", self.TI, self.FI,
                         {"script_ids": []})
        assert v[4] is False, v
        assert "no data flow exists" in v[8], v

    def test_base_index_presence_is_case_insensitive(self):
        """BE2: the base-index gate (which distinguishes "no script queries
        it" from "the filter excluded it") folds case too — the endpoint
        computes it with the same resolver, not `table in base_ti`."""
        # A base index keyed `bdm_src` must answer a `BDM_SRC` query.
        base_ti = {"bdm_src": {"scripts": ["pl.sql"], "fields": ["dm_flag2"]}}
        assert bool(resolve_name_ci(base_ti, "BDM_SRC")[1]) is True
        assert bool(resolve_name_ci(base_ti, "other")[1]) is False


class TestSearchEndpointCi:
    """End-to-end through POST /workspace/{id}/search: a natural-spelling
    query runs the full endpoint path (base-index gate + R17 diagnostic +
    create_search) without regressing to no_matches."""

    def test_endpoint_resolves_natural_spelling(self):
        from app.routers.dataflow import search_dataflow
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            r = asyncio.run(search_dataflow(
                ws_id, {"table": "BDM_SRC", "field": "dm_flag2",
                        "direction": "downstream"}))
            assert r["match_mode"] != "no_matches", r
            assert r["script_ids"] == ["dl.sql", "pl.sql"], r
        finally:
            delete_workspace(ws_id)

    def test_endpoint_no_matches_for_genuinely_absent_field(self):
        from app.routers.dataflow import search_dataflow
        ws_id, ti, fi = _indexed_ws({"pl.sql": PL_SQL})
        try:
            r = asyncio.run(search_dataflow(
                ws_id, {"table": "BDM_SRC", "field": "ghost_field",
                        "direction": "downstream"}))
            assert r["match_mode"] == "no_matches", r
            assert r["script_ids"] == [], r
            assert "ghost_field" in r["message"], r
        finally:
            delete_workspace(ws_id)
