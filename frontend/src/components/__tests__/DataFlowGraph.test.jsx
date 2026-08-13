import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import DataFlowGraph, {
  computeFlowCone, applyFlowCone, clearFlowCone, isValueFlowEdge,
} from '../DataFlowGraph';
import { decorateLabelWithLine } from '../../utils/labelDecoration';

// The cytoscape instance is canvas-based — not testable in jsdom. The
// hook is the graph lifecycle; capture the options the component hands
// it and drive the callbacks directly.
const { hookMock } = vi.hoisted(() => ({ hookMock: vi.fn() }));

vi.mock('../../hooks/useCytoscapeGraph', () => ({
  default: (...args) => {
    hookMock(...args);
    return { cyRef: { current: null }, fit: vi.fn(), relayout: vi.fn() };
  },
}));

const edgeData = {
  id: 'e1',
  source: 'n1',
  target: 'n2',
  edge_type: 'TABLE_FLOW',
  flow_kind: 'chain',
  highlight_line: 43,
  reason: 'chain — bdm_acc_loan_info.data_dt@L18 → ‖p1@L29 → p1.data_dt@L43‖ → ⟐subq@L0',
  color: '#2ECC71',
};

const graphData = {
  nodes: [{ data: { id: 'n1', label: 'a' } }, { data: { id: 'n2', label: 'b' } }],
  edges: [{ data: edgeData }],
};

function lastHookOptions() {
  return hookMock.mock.calls[hookMock.mock.calls.length - 1][2];
}

describe('DataFlowGraph — R25/§8.8 edge interactions', () => {
  beforeEach(() => {
    hookMock.mockClear();
    // jsdom has no ResizeObserver; the component uses it for auto-fit
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  it('forwards the full per-edge payload on edge tap (highlight_line/flow_kind/reason)', () => {
    const onEdgeClick = vi.fn();
    render(<DataFlowGraph graphData={graphData} level="L2" onEdgeClick={onEdgeClick} />);
    const options = lastHookOptions();
    options.onEdgeTap({ target: { data: () => edgeData } });
    expect(onEdgeClick).toHaveBeenCalledTimes(1);
    // The per-edge payload is the source of truth — passed through whole.
    expect(onEdgeClick.mock.calls[0][0]).toEqual(edgeData);
    expect(onEdgeClick.mock.calls[0][0].highlight_line).toBe(43);
    expect(onEdgeClick.mock.calls[0][0].flow_kind).toBe('chain');
    expect(onEdgeClick.mock.calls[0][0].reason).toContain('‖');
  });

  it('fires onCanvasTap on background taps (canvas click clears selection)', () => {
    const onCanvasTap = vi.fn();
    render(<DataFlowGraph graphData={graphData} level="L2" onCanvasTap={onCanvasTap} />);
    const options = lastHookOptions();
    options.onBgTap();
    expect(onCanvasTap).toHaveBeenCalledTimes(1);
  });

  it('hover tooltip shows edge type + flow kind + anchor line + reason preview', () => {
    const { container } = render(<DataFlowGraph graphData={graphData} level="L2" />);
    const options = lastHookOptions();
    act(() => {
      options.onEdgeHover({ target: { isEdge: () => true, data: () => edgeData } });
    });
    const tooltip = container.querySelector('.edge-tooltip');
    expect(tooltip).not.toBeNull();
    expect(tooltip.textContent).toContain('TABLE_FLOW');
    expect(tooltip.textContent).toContain('kind: chain');
    expect(tooltip.textContent).toContain('anchor: L43');
    expect(tooltip.textContent).toContain('bdm_acc_loan_info.data_dt@L18');
  });

  it('hovering a non-edge leaves the tooltip empty', () => {
    render(<DataFlowGraph graphData={graphData} level="L2" />);
    const options = lastHookOptions();
    act(() => {
      options.onEdgeHover({ target: { isEdge: () => false, data: () => ({}) } });
    });
    expect(screen.queryByText(/kind:/)).not.toBeInTheDocument();
  });
});

// ── R19.4/R19.6a: SCHEMA structure/containment edges are NOT flow ─────
// Structure edges are ALWAYS hidden (the display toggle was removed as
// seldom-used). The legend note still carries the structure-edge count.
const withSchema = {
  nodes: graphData.nodes,
  edges: [
    ...graphData.edges,
    { data: { id: 's1', source: 'n1', target: 'n2', edge_type: 'SCHEMA' } },
  ],
};

describe('DataFlowGraph — R19.4/R19.6a structure edges (always hidden)', () => {
  it('does not render a Structure toggle for L2 (removed)', () => {
    render(<DataFlowGraph graphData={withSchema} level="L2" />);
    expect(screen.queryByRole('button', { name: /Structure/ })).not.toBeInTheDocument();
  });

  it('does not render a Structure toggle for L1', () => {
    render(<DataFlowGraph graphData={graphData} level="L1" />);
    expect(screen.queryByRole('button', { name: /Structure/ })).not.toBeInTheDocument();
  });

  it('legend note appears when the graph has structure edges (always hidden)', () => {
    render(<DataFlowGraph graphData={withSchema} level="L2" />);
    expect(screen.getByTestId('legend-structure-note')).toBeInTheDocument();
    expect(screen.getByTestId('legend-structure-note').textContent).toContain('(1)');
  });

  it('no legend note when the graph has no structure edges', () => {
    render(<DataFlowGraph graphData={graphData} level="L2" />);
    expect(screen.queryByTestId('legend-structure-note')).not.toBeInTheDocument();
  });
});

// ── R30/#222: click-edge flow cone (L2) ──────────────────────────────
// The traversal is a pure helper on the graph payload — fully testable in
// jsdom. Structure edges (SCHEMA/ALIAS/SUBSET) are never part of the cone;
// ROW_FLOW (17th type, row-level flow) and unknown types are flow-class.
const coneGraph = {
  edges: [
    { data: { id: 'e0', source: 'n0', target: 'n1', edge_type: 'ROW_FLOW' } },
    { data: { id: 'e1', source: 'n1', target: 'n2', edge_type: 'TABLE_FLOW' } },
    { data: { id: 'e2', source: 'n2', target: 'n3', edge_type: 'TABLE_FLOW' } },
    { data: { id: 'e3', source: 'n3', target: 'n4', edge_type: 'TRANSFORM' } },
    { data: { id: 'e4', source: 'n2', target: 'n5', edge_type: 'FILTER' } },
    { data: { id: 's1', source: 'n1', target: 'n2', edge_type: 'SCHEMA' } },
    { data: { id: 'a1', source: 'n1', target: 'n1b', edge_type: 'ALIAS' } },
  ],
};

describe('isValueFlowEdge — structure excluded, ROW_FLOW/unknown included', () => {
  it('excludes the structure edge types (SCHEMA, ALIAS, SUBSET)', () => {
    expect(isValueFlowEdge({ edge_type: 'SCHEMA' })).toBe(false);
    expect(isValueFlowEdge({ edge_type: 'ALIAS' })).toBe(false);
    expect(isValueFlowEdge({ edge_type: 'SUBSET' })).toBe(false);
    expect(isValueFlowEdge({ relationship: 'SCHEMA' })).toBe(false);
  });

  it('treats ROW_FLOW and unknown edge types as flow', () => {
    expect(isValueFlowEdge({ edge_type: 'ROW_FLOW' })).toBe(true);
    expect(isValueFlowEdge({ edge_type: 'TABLE_FLOW' })).toBe(true);
    expect(isValueFlowEdge({ edge_type: 'SOME_FUTURE_TYPE' })).toBe(true);
    expect(isValueFlowEdge({})).toBe(true); // unknown → flow (defensive)
  });

  it('is defensive on non-objects', () => {
    expect(isValueFlowEdge(null)).toBe(false);
    expect(isValueFlowEdge(undefined)).toBe(false);
  });
});

describe('computeFlowCone — R30/#222 BFS traversal', () => {
  it('collects upstream (before) and downstream (after) value-flow edges', () => {
    const cone = computeFlowCone(coneGraph, 'e2'); // n2 → n3
    expect(cone.pivot).toBe('e2');
    // before = flow entering n2: e1 (n1→n2) + e0 (n0→n1, ROW_FLOW).
    // s1/a1 are structure edges — never part of the cone.
    expect(cone.before.sort()).toEqual(['e0', 'e1']);
    // after = flow leaving n3: e3 (n3→n4).
    expect(cone.after).toEqual(['e3']);
  });

  it('never traverses through structure edges', () => {
    // e2's upstream via n1 must stop at value-flow; ALIAS/SCHEMA
    // neighbors are invisible to the traversal.
    const cone = computeFlowCone(coneGraph, 'e2');
    expect(cone.before).not.toContain('a1');
    expect(cone.before).not.toContain('s1');
  });

  it('clicking a structure edge produces an empty cone', () => {
    const cone = computeFlowCone(coneGraph, 's1');
    expect(cone.pivot).toBe('s1');
    expect(cone.before).toEqual([]);
    expect(cone.after).toEqual([]);
  });

  it('missing/unknown edge id produces an empty cone', () => {
    const cone = computeFlowCone(coneGraph, 'nope');
    expect(cone.before).toEqual([]);
    expect(cone.after).toEqual([]);
  });

  it('handles a chain (no branches) end-to-end', () => {
    const chain = {
      edges: [
        { data: { id: 'c1', source: 'a', target: 'b', edge_type: 'REF' } },
        { data: { id: 'c2', source: 'b', target: 'c', edge_type: 'REF' } },
        { data: { id: 'c3', source: 'c', target: 'd', edge_type: 'DML' } },
      ],
    };
    const cone = computeFlowCone(chain, 'c2');
    expect(cone.before).toEqual(['c1']);
    expect(cone.after).toEqual(['c3']);
  });
});

// A minimal cytoscape-like instance: edges() returns an array-like
// collection whose elements expose id()/addClass/removeClass and the
// collection itself exposes removeClass (as cytoscape collections do).
function makeFakeCy(edgeDatas) {
  const elems = edgeDatas.map(d => {
    let cls = '';
    return {
      id: () => d.id,
      addClass(c) {
        const add = c.split(' ');
        cls = [...new Set([...cls.split(' ').filter(Boolean), ...add])].join(' ');
      },
      removeClass(c) {
        const rem = c.split(' ');
        cls = cls.split(' ').filter(k => k && !rem.includes(k)).join(' ');
      },
      getClass: () => cls,
    };
  });
  const col = elems;
  col.removeClass = function (c) { this.forEach(e => e.removeClass(c)); };
  return { edges: () => col, destroyed: () => false };
}

describe('applyFlowCone / clearFlowCone — focus classes on the cy instance', () => {
  it('tags pivot gold, before amber, after cyan, and dims the rest', () => {
    const cy = makeFakeCy(coneGraph.edges.map(e => e.data));
    applyFlowCone(cy, coneGraph, 'e2');
    const byId = {};
    cy.edges().forEach(e => { byId[e.id()] = e; });

    expect(byId.e2.getClass()).toContain('flow-cone-pivot');
    expect(byId.e1.getClass()).toContain('flow-cone-before');
    expect(byId.e0.getClass()).toContain('flow-cone-before');
    expect(byId.e3.getClass()).toContain('flow-cone-after');
    // sibling + structure edges are outside the cone → dimmed
    expect(byId.e4.getClass()).toContain('flow-cone-dimmed');
    expect(byId.s1.getClass()).toContain('flow-cone-dimmed');
    expect(byId.a1.getClass()).toContain('flow-cone-dimmed');
  });

  it('re-clicking replaces the previous focus (classes cleared first)', () => {
    const cy = makeFakeCy(coneGraph.edges.map(e => e.data));
    applyFlowCone(cy, coneGraph, 'e2');
    applyFlowCone(cy, coneGraph, 'e3'); // now e3 is the pivot
    const byId = {};
    cy.edges().forEach(e => { byId[e.id()] = e; });
    expect(byId.e3.getClass()).toContain('flow-cone-pivot');
    expect(byId.e2.getClass()).toContain('flow-cone-before'); // e2 feeds e3
    expect(byId.e1.getClass()).toContain('flow-cone-before');
    expect(byId.e0.getClass()).toContain('flow-cone-before');
  });

  it('clearFlowCone removes every focus class', () => {
    const cy = makeFakeCy(coneGraph.edges.map(e => e.data));
    applyFlowCone(cy, coneGraph, 'e2');
    clearFlowCone(cy);
    cy.edges().forEach(e => {
      expect(e.getClass()).not.toContain('flow-cone');
    });
  });

  it('is defensive on a null/destroyed instance', () => {
    expect(() => applyFlowCone(null, coneGraph, 'e2')).not.toThrow();
    expect(() => clearFlowCone(null)).not.toThrow();
    expect(() => applyFlowCone({ destroyed: () => true }, coneGraph, 'e2')).not.toThrow();
  });
});

// ── R27 label decoration: the new subquery-output display label ─────
// The backend will send virtual-table display labels as `output(X)` (the
// ⟐ marker is gone from the DISPLAY label; the internal table_name keeps
// it). decorateLabelWithLine must render `output(t)@L62` — one append,
// never a double-decorate.
describe('DataFlowGraph — VT output(X) display label decoration', () => {
  it('appends @L{line_start} to the new subquery-output display label', () => {
    expect(decorateLabelWithLine('output(t)', 62)).toBe('output(t)@L62');
  });

  it('never double-appends when the backend already carries a line suffix', () => {
    expect(decorateLabelWithLine('output(t)@L62', 62)).toBe('output(t)@L62');
    expect(decorateLabelWithLine('output(t)@62', 62)).toBe('output(t)@62');
  });

  it('is idempotent across repeats for the new label format', () => {
    const once = decorateLabelWithLine('output(t)', 62);
    expect(decorateLabelWithLine(once, 62)).toBe(once);
  });
});
