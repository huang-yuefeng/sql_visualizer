import { describe, it, expect } from 'vitest';
import { resolveFlowOnly, applyFlowVisibility, fitVisibleElements } from '../flowVisibility';

// A minimal cytoscape-like instance: nodes()/edges()/elements() return
// arrays whose elements expose id()/data()/show()/hide()/hidden();
// getElementById(id) returns [el] or [] like the real collection API.
function makeFakeCy({ nodes, edges }) {
  const nodeById = new Map();
  const nodeElems = nodes.map(d => {
    const el = {
      _hidden: false,
      id: () => d.id,
      data: k => (k === undefined ? d : d[k]),
      hide() { el._hidden = true; },
      show() { el._hidden = false; },
      hidden() { return el._hidden; },
    };
    nodeById.set(d.id, el);
    return el;
  });
  const edgeElems = edges.map(d => {
    const classes = d.classes || '';
    const el = {
      _hidden: false,
      id: () => d.id,
      data: k => d[k],
      hasClass: c => classes.split(/\s+/).includes(c),
      hide() { el._hidden = true; },
      show() { el._hidden = false; },
      hidden() { return el._hidden; },
    };
    return el;
  });
  const all = [...nodeElems, ...edgeElems];
  all.show = function () { this.forEach(e => e.show()); };
  all.hide = function () { this.forEach(e => e.hide()); };
  // cy.getElementById returns a collection: array-like with .hidden().
  const getElementById = (id) => {
    const el = nodeById.get(id);
    if (!el) return [];
    const col = [el];
    col.hidden = () => el.hidden();
    return col;
  };
  const cy = {
    nodes: () => nodeElems,
    edges: () => edgeElems,
    elements: (sel) => (sel === ':visible'
      ? all.filter(e => !e.hidden())
      : all),
    getElementById,
    destroyed: () => false,
  };
  // fit recorder — fitVisibleElements asserts that fit runs over the VISIBLE closure
  cy._fitCalls = [];
  cy._fitEls = [];
  cy.fit = (els, pad) => { cy._fitCalls.push(pad); cy._fitEls.push(els.map ? els.map(e => e.id()) : els); };
  return cy;
}

const graph = {
  nodes: [{ id: 'n1' }, { id: 'n2' }, { id: 'n3' }, { id: 'n4' }],
  edges: [
    { id: 'e1', source: 'n1', target: 'n2' }, // closure edge
    { id: 'e2', source: 'n2', target: 'n3' }, // non-closure (n3 hidden)
    { id: 'e3', source: 'n3', target: 'n4' }, // both endpoints hidden
  ],
};

describe('resolveFlowOnly — default toggle state from an L2 response', () => {
  it('returns true when the response carries a matched flow closure', () => {
    expect(resolveFlowOnly({ flow_node_ids: ['a', 'b'], flow_edge_ids: ['e'] })).toBe(true);
  });

  it('returns null when flow_node_ids is absent (no seed / not matched / filter off)', () => {
    expect(resolveFlowOnly({ graph: { nodes: [] } })).toBe(null);
    expect(resolveFlowOnly({})).toBe(null);
    expect(resolveFlowOnly(null)).toBe(null);
  });

  it('returns null when the closure is empty', () => {
    expect(resolveFlowOnly({ flow_node_ids: [] })).toBe(null);
    expect(resolveFlowOnly({ flow_node_ids: [], flow_edge_ids: [] })).toBe(null);
  });

  it('returns true when only flow_edge_ids is present (edge-only closure)', () => {
    expect(resolveFlowOnly({ flow_edge_ids: ['e1'] })).toBe(true);
  });
});

describe('applyFlowVisibility — View 1 (flow-only) / View 2 (full)', () => {
  it('flow-only: hides non-closure nodes and non-closure edges, shows the closure', () => {
    const cy = makeFakeCy(graph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    });
    const node = id => cy.nodes().find(n => n.id() === id);
    const edge = id => cy.edges().find(e => e.id() === id);

    // closure nodes visible
    expect(node('n1').hidden()).toBe(false);
    expect(node('n2').hidden()).toBe(false);
    // non-closure nodes hidden
    expect(node('n3').hidden()).toBe(true);
    expect(node('n4').hidden()).toBe(true);

    // closure edge visible
    expect(edge('e1').hidden()).toBe(false);
    // non-closure edge hidden even though n2 is visible (e2 touches hidden n3)
    expect(edge('e2').hidden()).toBe(true);
    // edge whose endpoints are both hidden is hidden
    expect(edge('e3').hidden()).toBe(true);
  });

  it('flow-only: hides an edge touching a hidden node even if listed', () => {
    // Defensive: e2 is NOT in flowEdgeIds but suppose it were — a hidden
    // endpoint must still suppress it (edge can never render dangling).
    const cy = makeFakeCy(graph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1', 'e2'], // e2 listed, but its target n3 is hidden
    });
    const edge = id => cy.edges().find(e => e.id() === id);
    expect(edge('e2').hidden()).toBe(true);
  });

  it('flow-only with an edge-only closure derives nodes from the closure edges (H-F1)', () => {
    // flowOnly truthy + empty flowNodeIds + non-empty flowEdgeIds must NOT
    // short-circuit to "show the full graph" — the node set is derived from
    // the closure edges' source/target endpoints.
    const cy = makeFakeCy(graph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: [],
      flowEdgeIds: ['e1'],
    });
    const node = id => cy.nodes().find(n => n.id() === id);
    const edge = id => cy.edges().find(e => e.id() === id);
    // endpoints of the closure edge e1 (n1→n2) are the derived closure
    expect(node('n1').hidden()).toBe(false);
    expect(node('n2').hidden()).toBe(false);
    expect(node('n3').hidden()).toBe(true);
    expect(node('n4').hidden()).toBe(true);
    expect(edge('e1').hidden()).toBe(false);
    expect(edge('e2').hidden()).toBe(true);
    expect(edge('e3').hidden()).toBe(true);
  });

  it('flow-only with edge-only closure derives nodes across multiple closure edges (H-F1)', () => {
    // e1 (n1→n2) + e3 (n3→n4): the derived closure is all four nodes.
    const cy = makeFakeCy(graph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: [],
      flowEdgeIds: ['e1', 'e3'],
    });
    const node = id => cy.nodes().find(n => n.id() === id);
    const edge = id => cy.edges().find(e => e.id() === id);
    expect(node('n1').hidden()).toBe(false);
    expect(node('n2').hidden()).toBe(false);
    expect(node('n3').hidden()).toBe(false);
    expect(node('n4').hidden()).toBe(false);
    expect(edge('e1').hidden()).toBe(false);
    expect(edge('e3').hidden()).toBe(false);
    // e2 (n2→n3) is not in the closure — hidden
    expect(edge('e2').hidden()).toBe(true);
  });

  it('flow-only with flowNodeIds omitted but flowEdgeIds present derives nodes (H-F1)', () => {
    const cy = makeFakeCy(graph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      // flowNodeIds omitted entirely — same edge-only derivation path
      flowEdgeIds: ['e1'],
    });
    expect(cy.nodes().find(n => n.id() === 'n1').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n2').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n3').hidden()).toBe(true);
    expect(cy.nodes().find(n => n.id() === 'n4').hidden()).toBe(true);
  });

  it('full: shows every element when flowOnly is false', () => {
    const cy = makeFakeCy(graph);
    // start hidden, then switch to full
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    });
    applyFlowVisibility(cy, { flowOnly: false, flowNodeIds: ['n1', 'n2'], flowEdgeIds: ['e1'] });
    cy.nodes().forEach(n => expect(n.hidden()).toBe(false));
    cy.edges().forEach(e => expect(e.hidden()).toBe(false));
  });

  it('full: shows everything when flowOnly is null (toggle disabled)', () => {
    const cy = makeFakeCy(graph);
    cy.nodes().forEach(n => n.hide());
    applyFlowVisibility(cy, { flowOnly: null });
    cy.nodes().forEach(n => expect(n.hidden()).toBe(false));
    cy.edges().forEach(e => expect(e.hidden()).toBe(false));
  });

  it('is defensive on a null/destroyed instance', () => {
    expect(() => applyFlowVisibility(null, { flowOnly: true })).not.toThrow();
    expect(() => applyFlowVisibility({ destroyed: () => true }, { flowOnly: true })).not.toThrow();
  });

  it('never calls a layout — only show()/hide() are invoked', () => {
    // A cy without any layout method: calling applyFlowVisibility must not
    // throw and must only mutate visibility.
    const cy = makeFakeCy(graph);
    expect(() => applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    })).not.toThrow();
  });
});

// ── #376: merged views hide field chips no visible edge connects ──
// A line-merged payload promotes every field endpoint to its parent table
// (build_line_merged_edges), so its edge set is entirely table-level while
// the node set is passed through untouched (R32). The searched seed chip is
// therefore in flow_node_ids with ZERO visible edges → floating orphan.
const mergedGraph = {
  nodes: [
    { id: 'T1', label: 'east5', type: 'table' },
    { id: 'A1', label: 'p1@29', type: 'alias' },
    { id: 'T2', label: 'out', type: 'table' },
    // V2-N1: the searched field's own chip — `is_target` is the builder's
    // seed marker (P1 seed copies carry it too) and it must NEVER be pruned,
    // edge-less or not: it is the chip the user searched for and the chip
    // F-B1 made clickable.
    { id: 'F_seed', label: 'p_dt', type: 'field', parent: 'T1', is_target: true },
    // A plain (non-seed) chip in the closure with no visible merged edge —
    // the #376 floating-orphan case that still gets pruned.
    { id: 'F_plain', label: 'amt', type: 'field', parent: 'T1' },
    // Parentless-field case: build_line_merged_edges keeps such an endpoint,
    // so this chip has a real merged edge and must stay visible.
    { id: 'F_kept', type: 'field', parent: null },
    { id: 'T_iso', type: 'table' },          // disconnected TABLE — never hidden
    { id: 'F_iso', type: 'field', parent: 'T_iso' }, // connected only by a SCHEMA line
  ],
  edges: [
    { id: 'e_flow', source: 'T1', target: 'A1' },   // merged closure edge
    { id: 'e_out', source: 'A1', target: 'T2' },    // non-closure in View 1
    { id: 'e_kept', source: 'F_kept', target: 'T1' }, // retained field endpoint
    { id: 'e_schema', source: 'F_iso', target: 'T_iso', classes: 'structure-hidden' },
  ],
};

const findNode = (cy, id) => cy.nodes().find(n => n.id() === id);

describe('mergedView — #376 edgeless field chips hide only in merged modes', () => {
  it('flow-merged: the SEARCHED chip survives the prune while a plain edge-less chip does not (V2-N1)', () => {
    const cy = makeFakeCy(mergedGraph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['T1', 'A1', 'F_seed', 'F_plain', 'F_kept'],
      flowEdgeIds: ['e_flow', 'e_kept'],
      mergedView: true,
    });
    // seed chip: zero visible merged edges, still rendered (V2-N1)
    expect(findNode(cy, 'F_seed').hidden()).toBe(false);
    // non-seed chip without any incident merged edge → hidden (#376)
    expect(findNode(cy, 'F_plain').hidden()).toBe(true);
    // …but with a visible incident merged edge → kept visible
    expect(findNode(cy, 'F_kept').hidden()).toBe(false);
    // tables/aliases always stay, closure or not
    expect(findNode(cy, 'T1').hidden()).toBe(false);
    expect(findNode(cy, 'A1').hidden()).toBe(false);
    expect(findNode(cy, 'T_iso').hidden()).toBe(true); // non-closure still hides
    const findEdge = (c, id) => c.edges().find(e => e.id() === id);
    expect(findEdge(cy, 'e_flow').hidden()).toBe(false);
    expect(findEdge(cy, 'e_schema').hidden()).toBe(true);
  });

  it('every is_target seed chip is exempt — P1 copies land on alias/CTE/target boxes too', () => {
    const cy = makeFakeCy({
      nodes: [
        { id: 'T1', type: 'table' },
        { id: 'A1', type: 'alias' },
        { id: 'S1', type: 'field', parent: 'T1', is_target: true },
        { id: 'S2', type: 'field', parent: 'A1', is_target: true },
        { id: 'P', type: 'field', parent: 'T1' },
      ],
      edges: [{ id: 'e1', source: 'T1', target: 'A1' }],
    });
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['T1', 'A1', 'S1', 'S2', 'P'],
      flowEdgeIds: ['e1'],
      mergedView: true,
    });
    expect(findNode(cy, 'S1').hidden()).toBe(false);
    expect(findNode(cy, 'S2').hidden()).toBe(false);
    expect(findNode(cy, 'P').hidden()).toBe(true);
  });

  it('a non-target flag spelling is NOT exempt (strict `is_target === true`)', () => {
    const cy = makeFakeCy({
      nodes: [
        { id: 'T1', type: 'table' },
        { id: 'Fx', type: 'field', parent: 'T1', is_target: false },
        { id: 'Fy', type: 'field', parent: 'T1', target: true }, // wrong key
      ],
      edges: [],
    });
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['T1', 'Fx', 'Fy'],
      flowEdgeIds: [],
      mergedView: true,
    });
    expect(findNode(cy, 'Fx').hidden()).toBe(true);
    expect(findNode(cy, 'Fy').hidden()).toBe(true);
  });

  it('full-merged: chips whose only edge is structure-hidden are orphans too (seed still shows)', () => {
    const cy = makeFakeCy(mergedGraph);
    applyFlowVisibility(cy, { flowOnly: false, mergedView: true });
    expect(findNode(cy, 'F_iso').hidden()).toBe(true);   // structure-hidden edge ≠ connection
    expect(findNode(cy, 'F_plain').hidden()).toBe(true);
    expect(findNode(cy, 'F_seed').hidden()).toBe(false);  // V2-N1 exemption
    expect(findNode(cy, 'F_kept').hidden()).toBe(false);
    // a disconnected table/alias box is never pruned by the field rule
    expect(findNode(cy, 'T_iso').hidden()).toBe(false);
    cy.edges().forEach(e => expect(e.hidden()).toBe(false));
  });

  it('detailed views never prune: an edgeless chip stays visible in `flow`', () => {
    const cy = makeFakeCy(mergedGraph);
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['T1', 'F_seed'],
      flowEdgeIds: [],
      mergedView: false, // 'flow' / 'full'
    });
    expect(findNode(cy, 'F_seed').hidden()).toBe(false);
    expect(findNode(cy, 'T1').hidden()).toBe(false);
    expect(findNode(cy, 'A1').hidden()).toBe(true);
  });

  it('full detailed (`flowOnly` falsy, no mergedView) shows everything', () => {
    const cy = makeFakeCy(mergedGraph);
    cy.nodes().forEach(n => n.hide());
    applyFlowVisibility(cy, { flowOnly: null });
    cy.nodes().forEach(n => expect(n.hidden()).toBe(false));
  });

  it('fitAllElements forwards mergedView — the restored state re-prunes but keeps the seed', () => {
    const cy = makeFakeCy(mergedGraph);
    fitVisibleElements(cy, {
      flowOnly: true,
      flowNodeIds: ['T1', 'F_seed', 'F_plain'],
      flowEdgeIds: [],
      mergedView: true,
    }, 40);
    expect(cy._fitCalls).toEqual([40]);
    expect(findNode(cy, 'F_seed').hidden()).toBe(false);
    expect(findNode(cy, 'F_plain').hidden()).toBe(true);
  });

  it('is defensive on a null/destroyed instance (merged mode)', () => {
    expect(() => applyFlowVisibility(null, { flowOnly: false, mergedView: true })).not.toThrow();
    expect(() => applyFlowVisibility({ destroyed: () => true }, { mergedView: true }))
      .not.toThrow();
  });
});

describe('fitVisibleElements — fit bounds the VISIBLE closure (ruling 2026-09-02, amending E-M8/#283)', () => {
  it('shows every element before fitting and re-hides non-closure nodes after', () => {
    const cy = makeFakeCy(graph);
    // Start with the flow-only filter applied (View 1).
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    });
    expect(cy.nodes().find(n => n.id() === 'n3').hidden()).toBe(true);

    fitVisibleElements(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    }, 40);

    // fit ran over the VISIBLE closure only (ruling 2026-09-02, amending
    // E-M8: the Full view is cut, so hidden elements are unreachable).
    expect(cy._fitCalls).toEqual([40]);
    expect(cy._fitEls[0].sort()).toEqual(['e1', 'n1', 'n2']);
    // After the fit, the flow-only visibility is restored — n3 is hidden again.
    expect(cy.nodes().find(n => n.id() === 'n1').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n2').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n3').hidden()).toBe(true);
    expect(cy.nodes().find(n => n.id() === 'n4').hidden()).toBe(true);
  });

  it('uses the default padding when none is passed', () => {
    const cy = makeFakeCy(graph);
    fitVisibleElements(cy, { flowOnly: false });
    expect(cy._fitCalls).toEqual([50]);
  });

  it('shows everything when no flow filter is active (flowOnly falsy)', () => {
    const cy = makeFakeCy(graph);
    cy.nodes().forEach(n => n.hide());
    fitVisibleElements(cy, { flowOnly: null });
    expect(cy._fitCalls).toEqual([50]);
    cy.nodes().forEach(n => expect(n.hidden()).toBe(false));
  });

  it('is defensive on a null/destroyed instance', () => {
    expect(() => fitVisibleElements(null, {}, 40)).not.toThrow();
    expect(() => fitVisibleElements({ destroyed: () => true }, {}, 40)).not.toThrow();
  });
});
