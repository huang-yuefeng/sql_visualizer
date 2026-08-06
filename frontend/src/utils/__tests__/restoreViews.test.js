import { describe, it, expect } from 'vitest';
import { mergeRestoredViews } from '../restoreViews';

const serverView = {
  view_id: 'v1',
  type: 'search',
  table: 'orders',
  field: 'amount',
  script_ids: ['a.sql'],
  l1_graph_cache: { nodes: [], edges: [] },
  children: [],
};
const savedView = {
  view_id: 'v1',
  type: 'search',
  table: 'orders',
  field: 'amount',
  match_mode: 'no_matches',
  message: 'no tables in scope',
};

describe('mergeRestoredViews', () => {
  it('M8: overlays saved match_mode/message onto the existing server entry', () => {
    const merged = mergeRestoredViews([serverView], savedView, 'v1');
    expect(merged).toHaveLength(1);
    expect(merged[0].view_id).toBe('v1');
    expect(merged[0].match_mode).toBe('no_matches');
    expect(merged[0].message).toBe('no tables in scope');
    // server fields untouched
    expect(merged[0].script_ids).toEqual(['a.sql']);
    expect(merged[0].l1_graph_cache).toEqual({ nodes: [], edges: [] });
  });

  it('M8: appends the saved view wholesale when the server has not persisted it', () => {
    const merged = mergeRestoredViews([], savedView, 'v1');
    expect(merged).toHaveLength(1);
    expect(merged[0]).toEqual(savedView);
  });

  it('M8: keeps server values when the server entry already carries match_mode', () => {
    const merged = mergeRestoredViews(
      [{ ...serverView, match_mode: 'no_matches', message: 'server message' }],
      { ...savedView, message: 'saved message' },
      'v1'
    );
    expect(merged[0].match_mode).toBe('no_matches');
    expect(merged[0].message).toBe('server message');
  });

  it('M8: does not touch unrelated views', () => {
    const other = { view_id: 'v2', type: 'search', table: 'x', field: 'y' };
    const merged = mergeRestoredViews([other, serverView], savedView, 'v1');
    expect(merged).toHaveLength(2);
    expect(merged[0]).toBe(other);
    expect(merged[1].message).toBe('no tables in scope');
  });

  it('M8: uses savedView.view_id when no explicit id is passed', () => {
    const merged = mergeRestoredViews([serverView], savedView);
    expect(merged[0].match_mode).toBe('no_matches');
  });

  it('M8: handles null/undefined inputs defensively', () => {
    expect(mergeRestoredViews(null, savedView, 'v1')).toEqual([savedView]);
    expect(mergeRestoredViews([serverView], null, 'v1')).toHaveLength(1);
    // no id anywhere → no-op, entries untouched
    const base = [serverView];
    expect(mergeRestoredViews(base, { ...savedView, view_id: undefined })).toHaveLength(1);
    expect(base[0].match_mode).toBeUndefined();
  });
});
