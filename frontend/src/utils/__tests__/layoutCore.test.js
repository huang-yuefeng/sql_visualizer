import { describe, it, expect } from 'vitest';
import { tableHeight, nodeSize, stripFieldParents, fieldPositionsForTable, positionTableFields } from '../layoutCore';
import {
  TABLE_HDR_H, TBL_PAD_TOP, FIELD_RENDER_H, FIELD_GAP,
  TBL_PAD_BOT, TABLE_MIN_H, TABLE_DEFAULT_W, SCRIPT_W, SCRIPT_H,
} from '../../config/layout';

describe('tableHeight', () => {
  it('clamps 0 fields to 1 field height (not TABLE_MIN_H)', () => {
    // tableHeight(0) → Math.max(fieldCount,1)=1 → full 1-field height
    const expected1 = TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H + TBL_PAD_BOT;
    expect(tableHeight(0)).toBe(Math.max(TABLE_MIN_H, expected1));
  });
  it('returns correct height for 1 field', () => {
    const expected = TABLE_HDR_H + TBL_PAD_TOP + FIELD_RENDER_H + TBL_PAD_BOT;
    expect(tableHeight(1)).toBe(Math.max(TABLE_MIN_H, expected));
  });
  it('returns correct height for 5 fields', () => {
    const expected = TABLE_HDR_H + TBL_PAD_TOP + 5 * FIELD_RENDER_H + 4 * FIELD_GAP + TBL_PAD_BOT;
    expect(tableHeight(5)).toBe(Math.max(TABLE_MIN_H, expected));
  });
  it('scales up for 20 fields', () => {
    expect(tableHeight(20)).toBeGreaterThan(600);
  });
  it('is monotonic', () => {
    expect(tableHeight(3)).toBeLessThan(tableHeight(5));
  });
  it('handles negative input (clamped to 1)', () => {
    expect(tableHeight(-1)).toBe(tableHeight(1));
  });
});

describe('nodeSize', () => {
  it('returns script size for script_node', () => {
    expect(nodeSize('script_node', 0)).toEqual({ w: SCRIPT_W, h: SCRIPT_H });
  });
  it('returns table size for source_table', () => {
    const sz = nodeSize('source_table', 3);
    expect(sz.w).toBe(TABLE_DEFAULT_W);
    expect(sz.h).toBeGreaterThanOrEqual(TABLE_MIN_H);
  });
  it('returns table size for query_output', () => {
    expect(nodeSize('query_output', 2).w).toBe(TABLE_DEFAULT_W);
  });
  it('returns table size for cte_table', () => {
    expect(nodeSize('cte_table', 1).w).toBe(TABLE_DEFAULT_W);
  });
  it('returns script size for unknown types', () => {
    expect(nodeSize('bogus', 10)).toEqual({ w: SCRIPT_W, h: SCRIPT_H });
  });
});

describe('stripFieldParents', () => {
  it('renames parent -> _tableParent for field nodes', () => {
    const input = [{ data: { id: 'f1', type: 'field', parent: 'tbl_x', label: 'x' } }];
    const out = stripFieldParents(input);
    expect(out[0].data.parent).toBeUndefined();
    expect(out[0].data._tableParent).toBe('tbl_x');
  });
  it('leaves non-field nodes unchanged', () => {
    const input = [{ data: { id: 't1', type: 'source_table', parent: null } }];
    const out = stripFieldParents(input);
    expect(out[0].data.parent).toBeNull();
    expect(out[0].data._tableParent).toBeUndefined();
  });
  it('handles empty array', () => {
    expect(stripFieldParents([])).toEqual([]);
  });
  it('does not mutate original objects', () => {
    const input = [{ data: { id: 'f1', type: 'field', parent: 'tbl_x' } }];
    stripFieldParents(input);
    expect(input[0].data.parent).toBe('tbl_x');
  });
});

// ── E1: shared field positioning (drag-recompute + applyLayout) ──────
describe('fieldPositionsForTable', () => {
  it('computes absolute field positions from table center + frozen offsets', () => {
    const fieldRel = {
      f1: { parentId: 't1', rx: 8, ry: -20 },
      f2: { parentId: 't1', rx: 8, ry: 32 },
      f_other: { parentId: 't2', rx: 8, ry: 0 },
    };
    expect(fieldPositionsForTable({ x: 100, y: 200 }, fieldRel, 't1')).toEqual({
      f1: { x: 108, y: 180 },
      f2: { x: 108, y: 232 },
    });
    // other tables' fields are untouched
    expect(fieldPositionsForTable({ x: 100, y: 200 }, fieldRel, 't1').f_other).toBeUndefined();
  });

  it('returns an empty map when the table has no fields', () => {
    expect(fieldPositionsForTable({ x: 0, y: 0 }, {}, 't1')).toEqual({});
  });

  it('handles a null/undefined fieldRel', () => {
    expect(fieldPositionsForTable({ x: 0, y: 0 }, null, 't1')).toEqual({});
  });
});

// Minimal fake cy: getElementById returns {length, position()} nodes.
function fakeNode(pos) {
  const state = { x: pos?.x ?? 0, y: pos?.y ?? 0 };
  return {
    length: 1,
    position: (p) => (p ? Object.assign(state, p) : { ...state }),
  };
}
function fakeCy(tableId, tablePos, fieldNodes) {
  const nodes = { [tableId]: fakeNode(tablePos), ...fieldNodes };
  return {
    destroyed: () => false,
    getElementById: (id) => nodes[id] || { length: 0 },
  };
}

describe('positionTableFields (drag-recompute helper)', () => {
  it('repositions a table\'s fields at table.position() + frozen offsets', () => {
    const fieldRel = {
      f1: { parentId: 't1', rx: 8, ry: -20 },
      f2: { parentId: 't1', rx: 8, ry: 32 },
    };
    const cy = fakeCy('t1', { x: 100, y: 200 }, { f1: fakeNode(), f2: fakeNode() });
    positionTableFields(cy, 't1', fieldRel);
    expect(cy.getElementById('f1').position()).toEqual({ x: 108, y: 180 });
    expect(cy.getElementById('f2').position()).toEqual({ x: 108, y: 232 });
  });

  it('snaps pre-drifted fields back to the frozen offset (self-healing)', () => {
    // Field drifted to a stale absolute position (e.g. missed drag frame
    // or a directly-dragged field) — recompute must restore the offset.
    const fieldRel = { f1: { parentId: 't1', rx: 8, ry: -20 } };
    const cy = fakeCy('t1', { x: 100, y: 200 }, { f1: fakeNode({ x: 400, y: 500 }) });
    positionTableFields(cy, 't1', fieldRel);
    expect(cy.getElementById('f1').position()).toEqual({ x: 108, y: 180 });
  });

  it('tracks a moved table (the drag case: table 100,100 → 300,250)', () => {
    const fieldRel = { f1: { parentId: 't1', rx: 8, ry: -20 } };
    const cy = fakeCy('t1', { x: 300, y: 250 }, { f1: fakeNode() });
    positionTableFields(cy, 't1', fieldRel);
    expect(cy.getElementById('f1').position()).toEqual({ x: 308, y: 230 });
  });

  it('is a no-op for an unknown table id', () => {
    const cy = fakeCy('t1', { x: 1, y: 1 }, { f1: fakeNode() });
    expect(() => positionTableFields(cy, 'ghost', { f1: { parentId: 'ghost', rx: 8, ry: 0 } })).not.toThrow();
  });
});
