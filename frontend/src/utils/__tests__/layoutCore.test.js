import { describe, it, expect } from 'vitest';
import { tableHeight, nodeSize, stripFieldParents } from '../layoutCore';
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
