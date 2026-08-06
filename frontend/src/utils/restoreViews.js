/**
 * R3 — merge the localStorage-saved view entry into the server's view list
 * after a reload (DataFlowApp mount-time restore).
 *
 * The backend now persists every search view (including F1 no_matches
 * results), but the persisted entry omits match_mode/message — those ride
 * only in the localStorage copy. When the server entry exists, overlay the
 * saved metadata onto it so the no-match banner survives a reload; when it
 * does not exist (very old workspaces, or listViews failed), append the
 * saved view wholesale. Server-supplied values win over the saved ones.
 *
 * Pure + unit-testable (no DOM / storage access).
 */
export function mergeRestoredViews(restoredViews, savedView, savedViewId) {
  const base = Array.isArray(restoredViews) ? restoredViews : [];
  const id = savedViewId || (savedView && savedView.view_id);
  if (!savedView || !id) return base;

  const exists = base.some(v => v && v.view_id === id);
  if (!exists) return [...base, savedView];

  return base.map(v =>
    v && v.view_id === id
      ? {
          ...v,
          match_mode: v.match_mode ?? savedView.match_mode ?? null,
          message: v.message ?? savedView.message ?? null,
        }
      : v
  );
}
