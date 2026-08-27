import { describe, it, expect } from 'vitest';
import { recoverViewSearch } from '../recoverViewSearch';

// The persisted views.json shape (dataflow_service._persist_search_view):
// search rows carry table/field; L2 children carry only their own identity
// plus parent_view_id — the target lives on the parent row.
const TREE = [
  {
    view_id: 'v1', type: 'search', table: 'east5_stzfxxb', field: 'p_dt',
    children: [
      { view_id: 'c1', type: 'script', script_name: 'EAST5_STZFXXB_M.sql', parent_view_id: 'v1' },
      { view_id: 'c2', type: 'script', script_name: 'x.sql', parent_view_id: 'v1', table: 'T', field: 'F' },
    ],
  },
  { view_id: 'v2', type: 'search', table: '', field: 'f2', children: [] },
  { view_id: 'v3', type: 'search', table: 't3', field: 'f3', children: [] },
];

describe('recoverViewSearch — searched table/field for an opened view', () => {
  it('recovers from the search view itself (L1 tree click)', () => {
    expect(recoverViewSearch(TREE, 'v1')).toEqual({ table: 'east5_stzfxxb', field: 'p_dt' });
    expect(recoverViewSearch(TREE, 'v3')).toEqual({ table: 't3', field: 'f3' });
  });

  it('recovers the L2 via its PARENT search row', () => {
    expect(recoverViewSearch(TREE, 'c1')).toEqual({ table: 'east5_stzfxxb', field: 'p_dt' });
  });

  it('the L2 row itself wins when it unusually carries its own target', () => {
    expect(recoverViewSearch(TREE, 'c2')).toEqual({ table: 'T', field: 'F' });
  });

  it('returns null when nothing recoverable exists', () => {
    expect(recoverViewSearch(TREE, 'v2')).toBeNull();     // empty table on the row
    expect(recoverViewSearch(TREE, 'missing')).toBeNull(); // unknown id
    expect(recoverViewSearch(null, 'v1')).toBeNull();      // malformed tree
    expect(recoverViewSearch([], undefined)).toBeNull();   // missing id
  });
});
