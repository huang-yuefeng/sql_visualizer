import { describe, it, expect } from 'vitest';
import pickAutoEdge from '../pickAutoEdge';

const edge = (id, extra = {}) => ({
  data: { id, source: 'a', target: 'b', flow_kind: 'chain', highlight_line: 9, ...extra },
});

describe('pickAutoEdge — R11-1 auto-selection on L2 load', () => {
  it('returns null when there is no graph or no edges', () => {
    expect(pickAutoEdge(null)).toBeNull();
    expect(pickAutoEdge({})).toBeNull();
    expect(pickAutoEdge({ graph: { nodes: [], edges: [] } })).toBeNull();
    expect(pickAutoEdge({ graph: { nodes: [{ data: { id: 'n1' } }], edges: [] } })).toBeNull();
  });

  it('prefers an edge whose highlight_line is in the seed zone', () => {
    const result = {
      graph: {
        nodes: [{ data: { id: 't', is_target: true, line_start: 60, line_end: 160 } }],
        edges: [
          edge('e1', { flow_kind: 'copy' }),
          edge('e2', { flow_kind: 'chain', highlight_line: 82 }),
          edge('e3', { flow_kind: 'chain', highlight_line: 9 }),
        ],
      },
    };
    expect(pickAutoEdge(result).id).toBe('e2');
  });

  it('skips the seed zone when the seed node has no line range (older payloads)', () => {
    const result = {
      graph: {
        nodes: [{ data: { id: 't', is_target: true } }],
        edges: [
          edge('e1', { flow_kind: 'copy' }),
          edge('e2', { flow_kind: 'chain', highlight_line: 82 }),
        ],
      },
    };
    // No zone → falls to the first chain edge.
    expect(pickAutoEdge(result).id).toBe('e2');
  });

  it('falls back to the first chain edge when no seed-zone edge exists', () => {
    const result = {
      graph: {
        nodes: [{ data: { id: 't', is_target: true, line_start: 60, line_end: 160 } }],
        edges: [
          edge('e1', { flow_kind: 'copy', highlight_line: 43 }),
          edge('e2', { flow_kind: 'chain', highlight_line: 43 }),
          edge('e3', { flow_kind: 'chain', highlight_line: 7 }),
        ],
      },
    };
    expect(pickAutoEdge(result).id).toBe('e2');
  });

  it('falls back to the first edge when nothing better exists', () => {
    const result = {
      graph: {
        nodes: [],
        edges: [edge('e1', { flow_kind: 'copy' }), edge('e2', { flow_kind: 'copy' })],
      },
    };
    expect(pickAutoEdge(result).id).toBe('e1');
  });

  it('ignores edges without data or id', () => {
    const result = {
      graph: {
        nodes: [],
        edges: [{}, { data: { id: 'e1' } }],
      },
    };
    expect(pickAutoEdge(result).id).toBe('e1');
  });

  // R19.4/R19.6a: SCHEMA structure/containment edges are hidden by
  // default — auto-selection prefers visible (flow) edges so the reason
  // panel never shows a hidden edge's reason.
  it('skips SCHEMA structure edges whenever a flow edge exists', () => {
    const result = {
      graph: {
        nodes: [{ data: { id: 't', is_target: true, line_start: 1, line_end: 100 } }],
        edges: [
          { data: { id: 's1', edge_type: 'SCHEMA', flow_kind: 'structure', highlight_line: 9 } },
          { data: { id: 'f1', edge_type: 'TABLE_FLOW', flow_kind: 'chain', highlight_line: 50 } },
        ],
      },
    };
    // The SCHEMA edge is inside the seed zone too — the visible flow edge wins.
    expect(pickAutoEdge(result).id).toBe('f1');
  });

  it('falls back to a SCHEMA edge when the graph has nothing else', () => {
    const result = {
      graph: {
        nodes: [],
        edges: [{ data: { id: 's1', edge_type: 'SCHEMA', flow_kind: 'structure' } }],
      },
    };
    expect(pickAutoEdge(result).id).toBe('s1');
  });
});
