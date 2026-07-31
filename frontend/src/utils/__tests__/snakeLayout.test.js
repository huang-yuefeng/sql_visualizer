import { describe, it, expect } from 'vitest';
import { computeSnakePositions } from '../snakeLayout';
import { tableHeight } from '../layoutCore';
import { TABLE_DEFAULT_W } from '../../config/layout';

function mkNode(id, type, label, layer) {
  return {
    id: () => id,
    data: (key) => {
      const m = { type, label, layer };
      return key ? m[key] : m;
    },
  };
}

describe('computeSnakePositions', () => {
  it('returns empty object for empty nodes', () => {
    expect(computeSnakePositions([], {})).toEqual({});
  });

  it('positions a single script node', () => {
    const pos = computeSnakePositions([mkNode('s1', 'script_node', 'step1', 0)], {});
    expect(pos.s1).toBeDefined();
    expect(pos.s1.x).toBeGreaterThan(0);
    expect(pos.s1.y).toBeGreaterThan(0);
  });

  it('positions a single table node', () => {
    const info = { t1: { w: TABLE_DEFAULT_W, h: tableHeight(3) } };
    const pos = computeSnakePositions([mkNode('t1', 'source_table', 'raw_orders', 0)], info);
    expect(pos.t1).toBeDefined();
  });

  it('positions 5 mixed nodes without identical positions', () => {
    const nodes = [
      mkNode('s1', 'script_node', 'step1', 0),
      mkNode('t1', 'source_table', 'raw', 0),
      mkNode('s2', 'script_node', 'step2', 1),
      mkNode('t2', 'intermediate_table', 'stg', 1),
      mkNode('s3', 'script_node', 'step3', 2),
    ];
    const info = { t1: { w: TABLE_DEFAULT_W, h: tableHeight(2) }, t2: { w: TABLE_DEFAULT_W, h: tableHeight(3) } };
    const pos = computeSnakePositions(nodes, info);
    nodes.forEach(n => expect(pos[n.id()]).toBeDefined());
    const seen = new Set();
    for (const [id, p] of Object.entries(pos)) {
      const key = `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  });

  it('wraps at 2 columns: row0 has n0+n1, row1 has n2+n3', () => {
    const nodes = [
      mkNode('n0', 'script_node', 'a', 0), mkNode('n1', 'script_node', 'b', 0),
      mkNode('n2', 'script_node', 'c', 1), mkNode('n3', 'script_node', 'd', 1),
    ];
    const pos = computeSnakePositions(nodes, {});
    expect(pos.n0.y).toBeCloseTo(pos.n1.y, 0);
    expect(pos.n2.y).toBeGreaterThan(pos.n0.y);
    expect(pos.n2.y).toBeCloseTo(pos.n3.y, 0);
  });

  it('snake reverses even rows', () => {
    // row 0 (even): n0@col0, n1@col1 → n0 left, n1 right
    // row 1 (odd):  n2@col0, n3@col1 → reversed: n3 left, n2 right
    const nodes = [
      mkNode('n0', 'script_node', 'a', 0), mkNode('n1', 'script_node', 'b', 0),
      mkNode('n2', 'script_node', 'c', 1), mkNode('n3', 'script_node', 'd', 1),
    ];
    const pos = computeSnakePositions(nodes, {});
    expect(pos.n0.x).toBeLessThan(pos.n1.x);
    expect(pos.n3.x).toBeLessThan(pos.n2.x);
  });

  it('handles 120 nodes without crash', () => {
    const nodes = Array.from({ length: 120 }, (_, i) =>
      mkNode(`n${i}`, 'script_node', `s_${i}`, Math.floor(i / 2)));
    const pos = computeSnakePositions(nodes, {});
    expect(Object.keys(pos).length).toBe(120);
  });

  it('layers rows: 3 nodes wrap to 2 rows (2 cols)', () => {
    // 3 nodes → row 0 has n0,n1, row 1 has n2
    // n0,n1 share a row, n2 is alone below
    const nodes = [
      mkNode('n0', 'script_node', 'a', 0),
      mkNode('n1', 'script_node', 'b', 0),
      mkNode('n2', 'script_node', 'c', 1),
    ];
    const pos = computeSnakePositions(nodes, {});
    expect(pos.n0.y).toBeCloseTo(pos.n1.y, -1);  // same row
    expect(pos.n2.y).toBeGreaterThan(pos.n0.y);   // below
  });
});
