"""Team H12 (v3.3.195) — build_physical_model performance-shape tests.

Measured spec (RFN, in-situ): the build was ~48 ms and pass 3 (dependency
edges) was 85.7% of it. P7 — slotted ``PhysicalEdge`` with a LAZY
``flow_kind``/``reason`` (the single_line payload is derived on FIRST
ACCESS, the anchor line stays eager) — and P1 — a per-var-id memo on
``_var_ref`` (20,674 calls for 1,953 distinct vars) — take ~31% off the
build with a byte-identical model (V6 digest, 10-script corpus).

These tests pin the STRUCTURAL invariants that make that true, so a later
edit cannot silently re-add the eager payload derivation (which is pure
waste: nothing in the pipeline reads ``flow_kind``/``reason`` while
building the model) or break the lazy contract:

* the single_line strategy is NEVER called during the build;
* on first access the payload is EXACTLY the strategy's output over
  ``{"edge_type": self.edge_type, **self.carried}`` — the byte-identity
  proof — and it is computed ONCE per edge (cached);
* ``highlight_line`` stays eager and equals the payload's anchor line;
* ``PhysicalEdge`` is slotted (no per-edge ``__dict__``) and is no longer
  a dataclass;
* the ``_var_ref`` memo is per build — it cannot leak between builds.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import dataclasses

import pytest

from app.extractor.physical_model import PhysicalEdge, build_physical_model
from app.services import highlight_strategies
from app.services.highlight_strategies import STRATEGIES


# ── Fixture helpers (graph-data form: nodes carry label, not name) ──────

def _graph(vars_, edges=None):
    """One graph-data dict in the build_graph_data shape."""
    return {"nodes": vars_, "edges": edges or [], "script_name": "perf.sql"}


def _tbl(var_id, label, line=1, vt="table", context="TOP0"):
    return {"id": var_id, "label": label, "variable_type": vt,
            "source_tables": [], "defined_in": "SELECT",
            "line_start": line, "line_end": line, "context": context,
            "is_output": False}


def _col(var_id, label, table, line=3, vt="column", context="TOP0"):
    return {"id": var_id, "label": label, "variable_type": vt,
            "source_tables": [table], "defined_in": "SELECT",
            "line_start": line, "line_end": line, "context": context,
            "is_output": False}


def _dep(src, tgt, rel, op="", containment=False):
    return {"source_id": src, "target_id": tgt, "relationship": rel,
            "operation": op, "containment": containment}


class _CountingStrategy:
    """Wraps the real single_line strategy and counts every derivation."""

    def __init__(self):
        self.calls = 0
        self.real = STRATEGIES["single_line"]

    def __call__(self, payload):
        self.calls += 1
        return self.real(payload)


@pytest.fixture
def counting_strategy(monkeypatch):
    counter = _CountingStrategy()
    monkeypatch.setitem(highlight_strategies.STRATEGIES, "single_line",
                        counter)
    # the registry contract the lazy property relies on: the strategy is
    # resolved AT ACCESS TIME, so the wrapper above is the one that runs.
    assert highlight_strategies.get_strategy("single_line") is counter
    return counter


# ── P7: the payload is not derived during the build ─────────────────────

def test_build_derives_no_single_line_payload(counting_strategy):
    """Pass 3 must not pay for flow_kind/reason: nothing in the pipeline
    reads them while the model is built."""
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"), _tbl("t2", "t2"),
         _col("c1", "t1.f", "t1"), _col("c2", "t2.g", "t2")],
        [_dep("t1", "t2", "TABLE_FLOW"),
         _dep("c1", "c2", "REF"),
         _dep("c1", "c2", "REF,FILTER"),
         _dep("c2", "t2", "SCHEMA"),
         _dep("c2", "t2", "DML")]))
    # the compound "REF,FILTER" raw type splits per type (Bug 3 mirror)
    assert len(model.edges) == 6
    assert counting_strategy.calls == 0


def test_first_access_derives_once_then_caches(counting_strategy):
    """Lazy, not absent: the first read derives the payload, a second read
    of either attribute reuses it (one computation per edge, ever)."""
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"), _tbl("t2", "t2"),
         _col("c1", "t1.f", "t1"), _col("c2", "t2.g", "t2")],
        [_dep("t1", "t2", "TABLE_FLOW"),
         _dep("c1", "c2", "REF")]))
    edge = model.edges[1]
    assert counting_strategy.calls == 0
    assert edge.flow_kind == "field flow"
    assert counting_strategy.calls == 1
    assert edge.reason                       # same edge, other attribute
    assert edge.flow_kind == "field flow"
    assert counting_strategy.calls == 1      # cached, not recomputed
    assert model.edges[0].flow_kind == "chain"
    assert counting_strategy.calls == 2      # the other edge pays its own


def test_lazy_payload_is_the_strategy_derivation():
    """The byte-identity proof: on first access the attributes are EXACTLY
    the single_line payload over {"edge_type", **carried} — the same dict
    the eager derivation built — and highlight_line (eager) is its anchor."""
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"), _tbl("t2", "t2", line=8, vt="view"),
         _col("c1", "t1.f", "t1", line=3),
         _col("c2", "t2.g", "t2", line=9),
         _col("c3", "t1.h", "t1", line=4, vt="aggregate")],
        [_dep("t1", "t2", "TABLE_FLOW"),
         _dep("t2", "t2", "DML", op="INSERT"),
         _dep("c1", "c2", "REF"),
         _dep("c2", "t2", "SCHEMA"),
         _dep("c1", "c3", "AGGREGATE"),
         _dep("c3", "c2", "FILTER", op="CONDITION")]))
    assert model.edges
    for edge in model.edges:
        payload = STRATEGIES["single_line"](
            {"edge_type": edge.edge_type, **edge.carried})
        assert edge.highlight_line == payload["highlight_line"]
        assert edge.flow_kind == payload["flow_kind"]
        assert edge.reason == payload["reason"]


def test_highlight_line_is_eager(counting_strategy):
    """The anchor stays an eager field — the walker and the lineage read it
    per edge — so it is correct even when the payload is never derived."""
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"), _tbl("t2", "t2", line=8, vt="view"),
         _col("c1", "t1.f", "t1", line=3), _col("c2", "t2.g", "t2", line=9)],
        [_dep("c1", "c2", "REF"), _dep("c2", "t2", "SCHEMA")]))
    derived = {id(e): counting_strategy.real(
        {"edge_type": e.edge_type, **e.carried}) for e in model.edges}
    assert counting_strategy.calls == 0      # the wrapper was never needed
    for edge in model.edges:
        assert edge.highlight_line == derived[id(edge)]["highlight_line"]
    assert counting_strategy.calls == 0


# ── P7: the slotted edge ─────────────────────────────────────────────────

def test_physical_edge_is_slotted_and_not_a_dataclass():
    """One edge per split dependency type (10,800 on RFN): no per-edge
    __dict__, no dataclass machinery. The decorator's __eq__/__repr__ are
    gone with it — measured before the change: no
    dataclasses.asdict/fields/replace/is_dataclass use anywhere, no test
    compares two edges by value, one construction site (_make_edge)."""
    assert not dataclasses.is_dataclass(PhysicalEdge)
    assert not hasattr(PhysicalEdge(  # noqa: SLF001 — constructor contract
        "REF", ("t1", "f"), ("t2", "g"), "a", "b"), "__dict__")
    for slot in ("edge_type", "source", "target", "source_id", "target_id",
                 "source_line", "target_line", "source_label",
                 "target_label", "operation", "containment",
                 "highlight_line", "carried", "_payload"):
        assert slot in PhysicalEdge.__slots__, slot
    edge = PhysicalEdge("REF", ("t1", "f"), ("t2", "g"), "a", "b")
    assert edge.carried == {}                # the dataclass default survives
    with pytest.raises(AttributeError):
        edge.not_a_slot = 1


def test_physical_edge_identity_semantics():
    """Edges are distinct objects that carry their fields read-only-by-
    convention: attribute reads (the only thing the three shape-touching
    suites do) are unchanged."""
    a = PhysicalEdge("REF", ("t1", "f"), ("t2", "g"), "a", "b",
                     source_line=3, target_line=9, operation="READ",
                     containment=True, highlight_line=3,
                     carried={"_op": "READ"})
    assert (a.edge_type, a.source, a.target) == ("REF", ("t1", "f"),
                                                 ("t2", "g"))
    assert (a.source_id, a.target_id) == ("a", "b")
    assert (a.source_line, a.target_line) == (3, 9)
    assert a.operation == "READ" and a.containment is True
    assert a.highlight_line == 3 and a.carried == {"_op": "READ"}


# ── P1: the per-var-id endpoint memo ─────────────────────────────────────

def test_memo_hits_resolve_the_same_ref_as_a_cold_call():
    """A var resolved N times (the dependency graph re-resolves the same
    variable ~10x) yields the SAME endpoint ref on every edge, cold or
    memoized."""
    cols = [_col("c1", "t1.f", "t1", line=3 + i) for i in range(4)]
    consumers = [_col("k%d" % i, "t2.g%d" % i, "t2", line=10 + i)
                 for i in range(4)]
    deps = [_dep("c1", k["id"], "REF") for k in consumers]
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"), _tbl("t2", "t2")] + cols + consumers, deps))
    assert len(model.edges) == 4
    assert {e.source for e in model.edges} == {("t1", "f")}
    assert model.fields[("t1", "f")].uses == [k["id"] for k in consumers]


def test_varref_memo_is_per_build():
    """The memo lives in the build's closure: the same var id resolved by a
    DIFFERENT script must resolve to that script's own entity/owner."""
    script_a = _graph([_tbl("t1", "alpha"), _col("shared", "alpha.f", "alpha")],
                      [_dep("t1", "shared", "SCHEMA")])
    script_b = _graph([_tbl("t2", "beta"), _col("shared", "beta.g", "beta")],
                      [_dep("t2", "shared", "SCHEMA")])
    model_b = build_physical_model(script_b)
    model_a = build_physical_model(script_a)          # after B's memo filled
    assert model_a.edges[0].target == ("alpha", "f")
    assert model_b.edges[0].target == ("beta", "g")
    # and re-building A again is stable (its own memo, same result)
    assert build_physical_model(script_a).edges[0].target == ("alpha", "f")


def test_unresolvable_owner_stays_unparented_through_the_memo():
    """A var with no owner resolves to (None, field) — the memo must not
    turn that into an entity ref, nor leak it onto another var."""
    model = build_physical_model(_graph(
        [_tbl("t1", "t1"),
         _col("orphan", "ghost.f", "ghost"),          # no such entity
         _col("kept", "t1.f", "t1")],
        [_dep("orphan", "kept", "REF"), _dep("kept", "orphan", "REF")]))
    refs = {(e.source, e.target) for e in model.edges}
    assert ((None, "f"), ("t1", "f")) in refs
    assert (("t1", "f"), (None, "f")) in refs
    assert ("ghost", "f") not in {r for pair in refs for r in pair}


def test_scale_build_derives_no_payload(counting_strategy):
    """At scale the build is still payload-free (the measured P7 win is
    exactly this, not a micro-timing claim)."""
    variables = [_tbl("t1", "t1"), _tbl("t2", "t2")]
    variables += [_col("s%d" % i, "t1.f%d" % i, "t1", line=3 + i)
                  for i in range(200)]
    variables += [_col("k%d" % i, "t2.g%d" % i, "t2", line=400 + i)
                  for i in range(200)]
    deps = []
    for i in range(200):                     # 10 consumers per source var
        for j in range(10):
            deps.append(_dep("s%d" % i, "k%d" % ((i + j) % 200), "REF"))
    model = build_physical_model(_graph(variables, deps))
    assert len(model.edges) == 2000
    assert counting_strategy.calls == 0
    assert model.edges[0].flow_kind          # and still answerable
    assert counting_strategy.calls == 1
