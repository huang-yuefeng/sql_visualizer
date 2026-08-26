import { describe, it, expect } from 'vitest';
import { resolveFlowOnly, applyFlowVisibility, fitAllElements } from '../flowVisibility';

// A minimal cytoscape-like instance: nodes()/edges()/elements() return
// arrays whose elements expose id()/data()/show()/hide()/hidden();
// getElementById(id) returns [el] or [] like the real collection API.
function makeFakeCy({ nodes, edges }) {
  const nodeById = new Map();
  const nodeElems = nodes.map(d => {
    const el = {
      _hidden: false,
      id: () => d.id,
      hide() { el._hidden = true; },
      show() { el._hidden = false; },
      hidden() { return el._hidden; },
    };
    nodeById.set(d.id, el);
    return el;
  });
  const edgeElems = edges.map(d => {
    const el = {
      _hidden: false,
      id: () => d.id,
      data: k => d[k],
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
    elements: () => all,
    getElementById,
    destroyed: () => false,
  };
  // fit recorder — fitAllElements asserts that fit runs over the FULL graph
  cy._fitCalls = [];
  cy.fit = (els, pad) => { cy._fitCalls.push(pad); };
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

describe('fitAllElements — E-M8 (#283) fit bounds the FULL graph, then restores flow visibility', () => {
  it('shows every element before fitting and re-hides non-closure nodes after', () => {
    const cy = makeFakeCy(graph);
    // Start with the flow-only filter applied (View 1).
    applyFlowVisibility(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    });
    expect(cy.nodes().find(n => n.id() === 'n3').hidden()).toBe(true);

    fitAllElements(cy, {
      flowOnly: true,
      flowNodeIds: ['n1', 'n2'],
      flowEdgeIds: ['e1'],
    }, 40);

    // fit ran over the FULL graph (fit() is called with the padding).
    expect(cy._fitCalls).toEqual([40]);
    // After the fit, the flow-only visibility is restored — n3 is hidden again.
    expect(cy.nodes().find(n => n.id() === 'n1').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n2').hidden()).toBe(false);
    expect(cy.nodes().find(n => n.id() === 'n3').hidden()).toBe(true);
    expect(cy.nodes().find(n => n.id() === 'n4').hidden()).toBe(true);
  });

  it('uses the default padding when none is passed', () => {
    const cy = makeFakeCy(graph);
    fitAllElements(cy, { flowOnly: false });
    expect(cy._fitCalls).toEqual([50]);
  });

  it('shows everything when no flow filter is active (flowOnly falsy)', () => {
    const cy = makeFakeCy(graph);
    cy.nodes().forEach(n => n.hide());
    fitAllElements(cy, { flowOnly: null });
    expect(cy._fitCalls).toEqual([50]);
    cy.nodes().forEach(n => expect(n.hidden()).toBe(false));
  });

  it('is defensive on a null/destroyed instance', () => {
    expect(() => fitAllElements(null, {}, 40)).not.toThrow();
    expect(() => fitAllElements({ destroyed: () => true }, {}, 40)).not.toThrow();
  });
});
