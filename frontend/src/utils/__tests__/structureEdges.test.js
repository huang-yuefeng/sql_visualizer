import { describe, it, expect } from 'vitest';
import { isStructureEdge, countStructureEdges } from '../structureEdges';

describe('structureEdges — R19.4/R19.6a SCHEMA detection', () => {
  it('identifies SCHEMA edges by edge_type', () => {
    expect(isStructureEdge({ edge_type: 'SCHEMA' })).toBe(true);
    expect(isStructureEdge({ edge_type: 'REF' })).toBe(false);
    // category "structure" in the payload covers ALIAS/SUBSET/TABLE_FLOW
    // too (backend CATEGORY_MAP) — only the TYPE says SCHEMA, so these
    // must never be treated as structure edges.
    expect(isStructureEdge({ edge_type: 'ALIAS', category: 'structure' })).toBe(false);
    expect(isStructureEdge({ edge_type: 'SUBSET', category: 'structure' })).toBe(false);
    expect(isStructureEdge({ edge_type: 'TABLE_FLOW', category: 'structure' })).toBe(false);
  });

  it('tolerates the legacy relationship key', () => {
    expect(isStructureEdge({ relationship: 'SCHEMA' })).toBe(true);
    expect(isStructureEdge({ relationship: 'REF' })).toBe(false);
  });

  it('is false for missing or malformed data', () => {
    expect(isStructureEdge(null)).toBe(false);
    expect(isStructureEdge(undefined)).toBe(false);
    expect(isStructureEdge({})).toBe(false);
    expect(isStructureEdge('SCHEMA')).toBe(false);
    expect(isStructureEdge(42)).toBe(false);
  });

  it('counts SCHEMA edges in a graph payload', () => {
    const graph = {
      edges: [
        { data: { id: 'a', edge_type: 'TABLE_FLOW' } },
        { data: { id: 'b', edge_type: 'SCHEMA' } },
        { data: { id: 'c', edge_type: 'REF' } },
        { data: { id: 'd', relationship: 'SCHEMA' } },
        { data: { id: 'e', edge_type: 'ALIAS' } },
      ],
    };
    expect(countStructureEdges(graph)).toBe(2);
    expect(countStructureEdges({ edges: [] })).toBe(0);
    expect(countStructureEdges(null)).toBe(0);
    expect(countStructureEdges(undefined)).toBe(0);
    expect(countStructureEdges({})).toBe(0);
    expect(countStructureEdges({ edges: [{ data: null }] })).toBe(0);
  });
});
