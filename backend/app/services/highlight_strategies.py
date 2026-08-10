"""Per-edge flow payload derivation (R25 §8.3 / §8.7 / §8.8, W5).

The old response-level `highlights` (field-line lists, computed by
_single_line_ranges/_label_only_ranges over graph nodes) is GONE: every L2
edge carries its own payload — `highlight_line` (exactly one script line
>= 1, per the §8.3 anchor rules), `flow_kind` (§8.7 canonical kind set),
`reason` (`<kind> — <flow string>` with the edge's own segment wrapped in
‖…‖, §8.8.3) — computed at L2 build time from the edge's carried
extraction-time info. Nothing is reconstructed at render (never-patch
rule).

The single strategy is `single_line`: one anchor line per edge. The
registry + get_strategy() keep the strategy contract (unknown names fall
back to single_line); the level2 `highlight_strategy` query param was
removed together with the response-level highlights (R25 item 3) — the
payload is unconditional, and `label_only` is gone (every edge carries a
payload).

Strategy callable contract: `strategy(edge: dict) -> payload` where
`edge` is a FINAL L2 edge carrying the builder-attached extraction-time
fields (`_src_line`/`_tgt_line`/`_src_label`/`_tgt_label`/`_op`/… and
`_path_hops`, the closure-walk hop list ending with the edge's own
segment). Returns {"highlight_line": int, "flow_kind": str, "reason": str}.
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
FLOW_KINDS = ("chain", "field flow", "read", "write", "filter",
              "structure", "bridge")

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
    if et == "INDIRECT":
        return "filter"
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
    src_line = int(e.get("_src_line") or 0)
    tgt_line = int(e.get("_tgt_line") or 0)
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
    return src_line                # rule 1 — field-flow appearance line


def _build_reason(e: dict, kind: str) -> str:
    """§8.8.3 — `<flow kind> — <flow string>`.

    The flow string is the closure walk from the searched seed's field to
    this edge's target, rendered `{label}@L{line}` joined by ` → `, with
    the edge's own segment (‖…‖-wrapped) as the final pair. The builder
    pre-computed `_path_hops` (list of (label, line) ending with the edge's
    own segment); leaf/SCHEMA/SUBSET edges carry just their own segment.
    """
    hops = e.get("_path_hops") or []
    if len(hops) < 2:
        hops = [(e.get("_src_label") or "?", int(e.get("_src_line") or 0)),
                (e.get("_tgt_label") or "?", int(e.get("_tgt_line") or 0))]
    flow = ""
    for i, (label, line) in enumerate(hops):
        seg = f"{label}@L{line}"
        if i == len(hops) - 2:
            flow += f"‖{seg} → "
        elif i == len(hops) - 1:
            flow += f"{seg}‖"
        else:
            flow += seg + " → "
    return f"{kind} — {flow}"


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
