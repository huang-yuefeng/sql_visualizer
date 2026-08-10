"""Display-strategy module (W5/R25): highlight_strategies registry.

The L2 response-level `highlights` is gone — every L2 edge carries its own
payload (`highlight_line`, `flow_kind`, `reason`), derived at L2 build time
from the edge's carried extraction-time info (`_src_line`/`_tgt_line`/
`_op`/`_dml_origin`/`_path_hops`, …). The registry is the single source of
truth; unknown names fall back to the default 'single_line'. `label_only`
was removed with the response-level highlights (R25 item 3) — it now
resolves to single_line like any unknown name.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.highlight_strategies import (
    STRATEGIES,
    FLOW_KINDS,
    _flow_kind,
    _single_line_payload,
    get_strategy,
)


def _edge(**kw):
    """A minimal final-L2 edge dict carrying the W5 extraction-time info."""
    base = {
        "edge_type": "TABLE_FLOW",
        "_op": "FROM",
        "_src_label": "src",
        "_tgt_label": "tgt",
        "_src_line": 10,
        "_tgt_line": 20,
    }
    base.update(kw)
    return base


def test_get_strategy_default_is_single_line():
    """The default strategy is 'single_line' — the W5 payload derivation."""
    assert get_strategy("single_line") is STRATEGIES["single_line"]
    assert get_strategy("single_line") is _single_line_payload


def test_get_strategy_label_only_falls_back_to_single_line():
    """label_only was removed with the response-level highlights (R25 item
    3) — every L2 edge carries a payload, there is no payload-less mode."""
    assert get_strategy("label_only") is STRATEGIES["single_line"]


def test_get_strategy_unknown_name_falls_back_to_single_line():
    """An unknown strategy name must not crash or change semantics — the
    caller contract is get_strategy(name) -> callable, always."""
    assert get_strategy("no_such_strategy") is STRATEGIES["single_line"]
    assert get_strategy("") is STRATEGIES["single_line"]


def test_flow_kinds_are_the_canonical_7():
    assert FLOW_KINDS == ("chain", "field flow", "read", "write",
                          "filter", "structure", "bridge")


def test_single_line_payload_read_edge_anchors_target_line():
    """SUBSET/READ (the pre-promotion state of the read pairs) is a read —
    rule 2 anchors at the alias-def/FROM line of the alias it reads
    through (the target's line)."""
    e = _edge(edge_type="SUBSET", _op="READ", _src_line=43, _tgt_line=29)
    assert _flow_kind(e) == "read"
    payload = _single_line_payload(e)
    assert payload == {
        "highlight_line": 29,
        "flow_kind": "read",
        "reason": "read — ‖src@L43 → tgt@L29‖",
    }


def test_single_line_payload_chain_edge_anchors_source_line():
    """TABLE_FLOW/ALIAS are chains — rule 5 anchors at the source's def
    line."""
    e = _edge(edge_type="TABLE_FLOW", _src_line=64, _tgt_line=160)
    assert _flow_kind(e) == "chain"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 64
    assert payload["flow_kind"] == "chain"
    assert payload["reason"].startswith("chain — ")


def test_single_line_payload_dml_write_edge_anchors_target_line():
    """A raw DML edge is a write — rule 3 anchors at the write line (the
    DML target's line)."""
    e = _edge(edge_type="DML", _op="WRITE_READ", _src_line=160, _tgt_line=211)
    assert _flow_kind(e) == "write"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 211
    assert payload["flow_kind"] == "write"


def test_single_line_payload_rewritten_dml_edge_stays_write():
    """The DML rewrite (output→target) keeps edge_type TABLE_FLOW but
    carries _dml_origin — the write role must win over the chain role
    (§8.7 row 3), and the anchor stays the write line."""
    e = _edge(edge_type="TABLE_FLOW", _op="WRITE_READ",
              _src_line=0, _tgt_line=211, _dml_origin=True)
    assert _flow_kind(e) == "write"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 211
    assert payload["flow_kind"] == "write"


def test_single_line_payload_bridge_edge_anchors_source_line():
    """SUBSET with op != READ is a bridge — rule 7 anchors at the source's
    def line."""
    e = _edge(edge_type="SUBSET", _op="BRIDGE", _src_line=16, _tgt_line=9)
    assert _flow_kind(e) == "bridge"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 16
    assert payload["flow_kind"] == "bridge"


def test_single_line_payload_structure_edge_anchors_target_line():
    """SCHEMA is structure — rule 6 anchors at the member's appearance
    line."""
    e = _edge(edge_type="SCHEMA", _op="TABLE_COLUMN", _src_line=16,
              _tgt_line=18)
    assert _flow_kind(e) == "structure"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 18
    assert payload["flow_kind"] == "structure"


def test_single_line_payload_filter_indirect_endpoint_decided():
    """INDIRECT (correlated) is a filter — the anchor is endpoint-decided:
    the field-like side's line when the source is a field, else the
    target's line."""
    e = _edge(edge_type="INDIRECT", _op="CONDITION", _src_line=43,
              _tgt_line=29, _src_field_like=True)
    assert _flow_kind(e) == "filter"
    assert _single_line_payload(e)["highlight_line"] == 43
    e2 = _edge(edge_type="INDIRECT", _op="CONDITION", _src_line=43,
               _tgt_line=29, _src_field_like=False)
    assert _single_line_payload(e2)["highlight_line"] == 29


def test_single_line_payload_ref_roles():
    """REF is a read when the raw operation is READ or the target is its
    own owning table (rule 2); otherwise it is a field flow (rule 1)."""
    e = _edge(edge_type="REF", _op="READ", _src_line=9, _tgt_line=29)
    assert _flow_kind(e) == "read"
    assert _single_line_payload(e)["highlight_line"] == 29
    e2 = _edge(edge_type="REF", _op="SELECT", _src_line=9, _tgt_line=29,
               _src_owner="t1", _tgt_canon="t1")
    assert _flow_kind(e2) == "read"
    e3 = _edge(edge_type="REF", _op="SELECT", _src_line=9, _tgt_line=29,
               _src_owner="t1", _tgt_canon="t2")
    assert _flow_kind(e3) == "field flow"
    assert _single_line_payload(e3)["highlight_line"] == 9


def test_single_line_payload_field_flow_anchors_source_appearance():
    """FILTER/JOIN/AGGREGATE/… are field flows — rule 1 anchors at the
    source appearance line."""
    e = _edge(edge_type="JOIN", _op="JOIN_CONDITION", _src_line=202,
              _tgt_line=0)
    assert _flow_kind(e) == "field flow"
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 202
    assert payload["flow_kind"] == "field flow"
    e2 = _edge(edge_type="AGGREGATE", _op="GROUP_BY", _src_line=77,
               _tgt_line=80)
    assert _flow_kind(e2) == "field flow"


def test_single_line_payload_reason_wraps_own_segment():
    """The reason is `<kind> — <flow string>`; without a closure walk the
    flow string is the edge's own segment, ‖…‖-wrapped."""
    e = _edge(edge_type="SUBSET", _op="READ", _src_label="p1.data_dt",
              _tgt_label="p1", _src_line=43, _tgt_line=29)
    payload = _single_line_payload(e)
    assert payload["reason"] == "read — ‖p1.data_dt@L43 → p1@L29‖"


def test_single_line_payload_reason_renders_closure_walk():
    """With _path_hops (the builder's closure walk ending in the edge's own
    segment), the full path renders `{label}@L{line} → …` with the final
    two hops ‖…‖-wrapped."""
    e = _edge(edge_type="TABLE_FLOW", _op="WRITE_READ",
              _path_hops=[("p1.data_dt", 158), ("loan_final", 64),
                          ("⟐ output", 0), ("sup", 160), ("rrcdm", 211)])
    payload = _single_line_payload(e)
    assert payload["reason"] == (
        "chain — p1.data_dt@L158 → loan_final@L64 → ⟐ output@L0 → "
        "‖sup@L160 → rrcdm@L211‖")
    # the wrapped segment is the LAST pair
    assert payload["reason"].count("‖") == 2
    assert payload["reason"].endswith("rrcdm@L211‖")


def test_single_line_payload_reason_single_hop_walk():
    """A one-hop closure walk falls back to the edge's own segment (the
    builder guarantees ≥ the own segment, and the fallback keeps the
    ‖…‖ format)."""
    e = _edge(edge_type="TABLE_FLOW", _path_hops=[("sup", 160), ("rrcdm", 211)])
    assert _single_line_payload(e)["reason"] == (
        "chain — ‖sup@L160 → rrcdm@L211‖")


def test_safe_int_non_numeric_carried_lines():
    """N11: a non-numeric carried line must degrade to 0, never crash the
    payload builder (malformed cache / exotic carrier)."""
    from app.services.highlight_strategies import _safe_int, _anchor_line
    assert _safe_int("abc") == 0
    assert _safe_int(None) == 0
    assert _safe_int("") == 0
    assert _safe_int("12") == 12
    assert _safe_int(7) == 7
    e = _edge(_src_line="abc", _tgt_line=None)
    # rule 1 (field flow) anchors at the source appearance line — degrades
    # to 0, and the payload keeps flowing
    assert _anchor_line(e, "field flow") == 0
    payload = _single_line_payload(e)
    assert payload["highlight_line"] == 0
    assert payload["flow_kind"] == "chain"
