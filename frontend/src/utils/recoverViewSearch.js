/**
 * Recover the searched table.field for a persisted view (2026-08-27).
 *
 * When an old workspace is reopened, its views.json tree loads with the
 * search inputs EMPTY — the panel state is per-session. Opening an L2 (or
 * L1) from the tree then shows a graph with no visible trace of WHICH
 * table.field it belongs to. The backend persists `table`/`field` on every
 * search-view row (dataflow_service._persist_search_view), so the answer is
 * derivable from the tree itself:
 *
 *   - the view row, when it carries both fields (search views, incl.
 *     no_matches / no_flow rows);
 *   - otherwise its PARENT search row (L2 children persist only their own
 *     {view_id, type:'script', script_name, parent_view_id} — the target
 *     lives on the parent).
 *
 * Pure lookup — no fetches, no state. Returns null when the tree carries no
 * recoverable target (legacy/corrupt rows): the caller then leaves the
 * search panel untouched instead of guessing.
 */
export function recoverViewSearch(views, viewId) {
  if (!Array.isArray(views) || !viewId) return null;
  let entry = views.find(v => v && v.view_id === viewId) || null;
  let parent = null;
  if (!entry) {
    for (const v of views) {
      const child = (v.children || []).find(c => c && c.view_id === viewId);
      if (child) { entry = child; parent = v; break; }
    }
  }
  if (!entry) return null;
  const ok = r => r && typeof r.table === 'string' && r.table !== ''
    && typeof r.field === 'string' && r.field !== '';
  if (ok(entry)) return { table: entry.table, field: entry.field };
  if (ok(parent)) return { table: parent.table, field: parent.field };
  return null;
}
