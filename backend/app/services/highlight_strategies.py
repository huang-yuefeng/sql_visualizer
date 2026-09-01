"""Per-edge flow payload derivation (R25 §8.3 / §8.7 / §8.8, W5).

The old response-level `highlights` (field-line lists, computed by
_single_line_ranges/_label_only_ranges over graph nodes) is GONE: every L2
edge carries its own payload — `highlight_line` (exactly one script line
>= 1, per the §8.3 anchor rules), `flow_kind` (§8.7 canonical kind set),
`reason` (`<kind> (<path role>) — <flow string>` with the edge's own
segment wrapped in ‖…‖, §8.8.3 + R20 — the flow string is the complete
source→target path: upstream closure walk from the searched seed's field,
the own segment, then the downstream continuation to a flow target) —
computed at L2 build time from the edge's carried extraction-time info.
Nothing is reconstructed at render (never-patch rule).

The single strategy is `single_line`: one anchor line per edge. The
registry + get_strategy() keep the strategy contract (unknown names fall
back to single_line); the level2 `highlight_strategy` query param was
removed together with the response-level highlights (R25 item 3) — the
payload is unconditional, and `label_only` is gone (every edge carries a
payload).

Strategy callable contract: `strategy(edge: dict) -> payload` where
`edge` is a FINAL L2 edge carrying the builder-attached extraction-time
fields (`_src_line`/`_tgt_line`/`_src_label`/`_tgt_label`/`_op`/… and
`_path_hops`, the FULL source→target hop list — upstream closure walk
from the searched seed's field, the edge's own segment, then the
downstream continuation to a flow target — with `_own_seg_idx` marking
the own segment's first hop; R20). Returns
{"highlight_line": int, "flow_kind": str, "reason": str}.
"""

# ── Field-like var classes ──────────────────────────────────────────────
# The vars whose line_start carries the field's own occurrence line (design
# doc §4 FIELD_LIKE). Members verified against VariableType
# (models/variable.py): the doc's "computed"/"variable" are not enum
# members — the actual computed-value members are "case" and "transform".
FIELD_LIKE_TYPES = frozenset({
    "column", "cte_column", "literal", "aggregate", "expression",
    "window", "case", "transform",
})

# ── The canonical flow-kind set (§8.8.1, ruled 2026-08-10) ──────────────
# ROW_FLOW (2026-08-13, #226): "row flow" — the row-selection bridge the
# user sees in the tooltip/legend/edge reason ("row-level flow").
FLOW_KINDS = ("chain", "field flow", "read", "write", "filter",
              "structure", "bridge", "row flow")

# Synthetic-source VTs (rule 4 — the ⟐ nodes have no script presence of
# their own; their anchor is the VT creation line, carried on _src_line).
_VT_TYPES = frozenset({"virtual_table", "subquery", "union_branch"})


def _flow_kind(e: dict) -> str:
    """§8.7 — kind is assigned per edge (real type + endpoint roles),
    never per type alone: a REF edge pointing back at its owning table is a
    READ (rule 2), the same type flowing forward is a field flow (rule 1)."""
    et = e.get("edge_type", "")
    op = (e.get("_op") or "").upper()
    if et == "DML" or e.get("_dml_origin"):
        # The DML rewrite (output→target) keeps edge_type TABLE_FLOW but
        # carries _dml_origin — the write role must win over the chain role
        # (§8.7 row 3 — rule 3 write anchor).
        return "write"
    if et in ("TABLE_FLOW", "ALIAS"):
        return "chain"
    if et == "SCHEMA":
        return "structure"
    if et == "SUBSET":
        # SUBSET/READ is the pre-promotion state of the read pairs
        # (13/14/19, §8.5) — the read role is decided by the raw operation.
        return "read" if op == "READ" else "bridge"
    if et == "FILTER" and op == "ROW_SELECTION":
        # R46d — a CASE WHEN condition arm's occurrence twin is a
        # ROW-SELECTION, not a value flow: the canonical §8.7
        # row-selection kind (#226's "row flow"), anchored at the
        # occurrence's own line (rule below). FILTER's plain CONDITION
        # operation keeps the field-flow kind it always had.
        return "row flow"
    if et == "INDIRECT":
        return "filter"
    if et == "ROW_FLOW":
        # #226 — the row-selection bridge (nested VT → continuation
        # container): a distinct kind from value flow.
        return "row flow"
    if et == "REF":
        if op == "READ":
            return "read"
        # Owning-table pattern: the REF points back at its owning table
        # (the field is read from the table's own perspective — rule 2).
        src_owner = e.get("_src_owner") or ""
        tgt_canon = e.get("_tgt_canon") or ""
        if src_owner and tgt_canon and tgt_canon == src_owner:
            return "read"
        return "field flow"
    # FILTER/JOIN/AGGREGATE/TRANSFORM/WINDOW/COMPUTED/SET_OP/SUBQUERY
    return "field flow"


def _safe_int(value, default: int = 0) -> int:
    """N11: carried line fields must never crash the payload builder — a
    non-numeric value (malformed cache, exotic carrier) degrades to the
    default instead of raising."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _anchor_line(e: dict, kind: str) -> int:
    """§8.3 — exactly ONE script line per edge, in rule priority order:
    1 field flow → source appearance line; 2 READ → alias-def/FROM line of
    the alias the read happens through; 3 write → the write line (DML
    target's line); 4 synthetic-source → the VT creation line (carried on
    _src_line; VT-TARGETED edges keep the feeding var's line — no override,
    the source rules already anchor there); 5 chain → source def line;
    6 SCHEMA → the member's appearance line; 7 SUBSET → the source's def
    line. Line < 1 is a defect (line 0 = "no line matched" — the W6 VT
    creation lines and the Defect-5 read land here until their extraction
    fixes; never hardcoded)."""
    src_line = _safe_int(e.get("_src_line"))
    tgt_line = _safe_int(e.get("_tgt_line"))
    if kind == "read":
        return tgt_line            # rule 2 — the alias-def/FROM line
    if kind == "write":
        # rule 3 — the write line (DML target's line); a _value_edge (P17,
        # §8.5 — the searched field's VALUE column feeding the INSERT's
        # result set, e.g. '$(load_date)' AS data_dt@213) anchors at the
        # VALUE's own line, not the write line.
        return src_line if e.get("_value_edge") else tgt_line
    if kind == "structure":
        return tgt_line            # rule 6 — the member's appearance line
    if kind == "bridge":
        return src_line            # rule 7 — the source's def line
    if kind == "chain":
        return src_line            # rule 5 — entry line (source def); rule
                                   # 4 — VT creation line (same carried line)
    if kind == "filter":
        # INDIRECT (correlated) — endpoint-decided: the field's token sits
        # at an endpoint (rule 14 of §8.7).
        return src_line if e.get("_src_field_like") else tgt_line
    if kind == "row flow":
        # #226 — the nested subquery VT's creation line (the subquery
        # that does the row-selection the bridge carries).
        return src_line
    if e.get("edge_type") == "WINDOW" and tgt_line >= 1:
        # #387 (2026-08-28): window-key anchoring — a WINDOW edge's anchor
        # is the window application's OWN line (the OVER clause sits on
        # the window var, the edge's target), not the operand's line. The
        # operand kept the anchor everywhere (RFN L464's X5GMAB SELECT
        # projection anchored the ROW_NUMBER partition-key edge while the
        # OVER line L473 — the line the user reads for the window key —
        # never appeared in a flow-only closure). The operand provenance
        # stays visible in the reason's ‖operand → window‖ segment; a
        # target with no real line (0) keeps the operand line.
        return tgt_line
    return src_line                # rule 1 — field-flow appearance line


def _path_role(e: dict) -> str:
    """R20.2 — the edge's role in the scope of its source→target path.

    Derived from extraction-time info ONLY (the carried fields): the DML
    attribution (`_dml_origin`/`_value_edge`), the raw operation (`_op`),
    the raw endpoint variable types (`_src_vt`/`_tgt_vt`/`_src_is_vt`/
    `_tgt_is_vt`), and the builder-attached final-endpoint flags
    (`_src_output`/`_tgt_output` — the final endpoint is the synthetic
    ⟐ output VT; the carried `_tgt_is_vt` reflects the RAW edge, whose
    target may still be redirected onto the output later). SCHEMA/SUBSET
    are exempt (R19.4 — structure/bridge keep the containment/own-segment
    reason), and roles that would merely repeat the §8.7 kind (plain
    `chain`/`read`) return "" — the reason keeps `<kind> — <flow string>`.
    """
    if e.get("_dml_origin"):
        # The DML rewrite's two halves (§8.5): the value edge carries the
        # searched field's VALUE column into the output; the dml_out edge
        # is the write leg output → DML target.
        return "write value" if e.get("_value_edge") else "write leg"
    et = e.get("edge_type")
    op = (e.get("_op") or "").upper()
    if et == "REF":
        if op == "READ":
            # read into the ⟐ output / a subquery VT vs a plain holder
            # read (whose role is the kind itself — no parenthetical).
            return ("read into output"
                    if (e.get("_tgt_is_vt") or e.get("_tgt_output")) else "")
        return "value copy"
    if et == "DML":
        # defensive — the raw DML edge (no ⟐ output to route through)
        return "write leg"
    if et == "ALIAS":
        return "alias hop"
    if et == "FILTER" and op == "ROW_SELECTION":
        # R46d — the continuation arm's row-selection step.
        return "row selection"
    if et in ("FILTER", "INDIRECT"):
        return "filter step"
    if et == "JOIN":
        return "join step"
    if et == "AGGREGATE":
        return "aggregate step"
    if et == "WINDOW":
        return "window step"
    if et in ("TRANSFORM", "COMPUTED"):
        return "compute step"
    if et in ("SET_OP", "SUBQUERY"):
        return "combine step"
    if et == "ROW_FLOW":
        # #226 — the row-selection bridge (nested VT → continuation
        # container).
        return "row selection"
    if et == "TABLE_FLOW":
        svt = e.get("_src_vt")
        tvt = e.get("_tgt_vt")
        if svt == "cte" or tvt == "cte":
            return "CTE chain"
        if (e.get("_tgt_is_vt") or e.get("_tgt_output")) \
                and not (e.get("_src_is_vt") or e.get("_src_output")):
            return "read into output"
        if e.get("_src_is_vt") or e.get("_src_output"):
            return "VT chain"
        return ""            # plain chain — the kind already says it
    return ""


def _build_reason(e: dict, kind: str) -> str:
    """§8.8.3 + R20 — `<kind> (<path role>) — <flow string>`.

    R20.1: the flow string is the COMPLETE source→target path — the
    upstream closure walk from the searched seed's field, the edge's own
    segment (‖…‖-wrapped), then the downstream continuation to a flow
    target (a DML write target in the seed's closure). The builder
    pre-computed `_path_hops` (list of (label, line)) with `_own_seg_idx`
    marking the own segment's first hop; without `_own_seg_idx` (leaf /
    pre-R20 carriers) the own segment is the final pair — the §8.8.3 form.

    R20.2: the path-scope role (write leg / read into output / alias hop /
    CTE chain …) rides after the kind, derived from the edge's carried
    extraction-time info; SCHEMA/SUBSET and role-less edges keep the
    plain `<kind> — <flow string>` form.
    """
    hops = e.get("_path_hops") or []
    own_idx = e.get("_own_seg_idx")
    if own_idx is None:
        own_idx = len(hops) - 2 if len(hops) >= 2 else 0
    if len(hops) < 2:
        hops = [(e.get("_src_label") or "?", _safe_int(e.get("_src_line"))),
                (e.get("_tgt_label") or "?", _safe_int(e.get("_tgt_line")))]
        own_idx = 0
    # Defensive clamp: the own segment must span two hops (a malformed
    # carrier must never crash the payload builder).
    if own_idx > len(hops) - 2:
        own_idx = max(0, len(hops) - 2)
    segs = [f"{label}@L{line}" for label, line in hops]
    flow = f"‖{segs[own_idx]} → {segs[own_idx + 1]}‖"
    if own_idx > 0:
        flow = " → ".join(segs[:own_idx]) + " → " + flow
    if own_idx + 2 < len(segs):
        flow = flow + " → " + " → ".join(segs[own_idx + 2:])
    head = kind
    role = _path_role(e)
    if role:
        head = f"{kind} ({role})"
    return f"{head} — {flow}"


def _single_line_payload(e: dict) -> dict:
    """single_line: exactly one anchor line per edge + flow kind + reason —
    the W5 payload derivation (source of truth = the edge's carried
    extraction-time info, never reconstructed at render)."""
    kind = _flow_kind(e)
    return {
        "highlight_line": _anchor_line(e, kind),
        "flow_kind": kind,
        "reason": _build_reason(e, kind),
    }


# Registry of display strategies (v3.3.145 → W5). Each callable is
# `(edge: dict) -> {"highlight_line", "flow_kind", "reason"}`.
STRATEGIES = {
    "single_line": _single_line_payload,
}


def get_strategy(name: str):
    """Resolve a display strategy by name; unknown names fall back to the
    default 'single_line' (every L2 edge carries a payload — there is no
    payload-less mode; `label_only` was removed with the response-level
    `highlights`, R25 item 3)."""
    return STRATEGIES.get(name, STRATEGIES["single_line"])
