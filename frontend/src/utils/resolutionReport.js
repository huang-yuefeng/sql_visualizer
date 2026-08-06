/**
 * R20 — Orphan Resolution Report helpers (pure, testable).
 *
 * The backend emits resolution_stats in two shapes:
 *
 * 1. Per-script analysis (extractor, adapter.py / variable_extractor_v2.py):
 *      { total_columns, resolved_by: {plain_alias, expr_alias, scope,
 *        schema, sys, other}, unresolved: ["col_name", ...] }
 *
 * 2. Workspace index (folder_index_service.py):
 *      { total_columns, resolved, unresolved: <count>, container_resolved,
 *        coverage_pct, by_strategy: {plain_alias, expr_alias, scope,
 *        schema, sys, other} }
 *    (the unresolved NAMES ride along as `orphan_field_samples` in the
 *    index response body, not inside resolution_stats)
 *
 * summarizeResolutionStats() flattens either shape into one view-model for
 * the ORPHAN RESOLUTION REPORT block. Returns null when stats are absent
 * (old cached data) so callers can render nothing / "—" gracefully.
 */

export const STRATEGY_ORDER = ['plain_alias', 'expr_alias', 'scope', 'schema', 'sys', 'other'];

export const STRATEGY_LABELS = {
  plain_alias: 'S1 plain alias',
  expr_alias: 'S2 expr alias',
  scope: 'S3 nearest scope',
  schema: 'S4 schema',
  sys: 'S5 system',
  other: 'S6 other',
};

export function strategyLabel(key) {
  return STRATEGY_LABELS[key] || key;
}

export function summarizeResolutionStats(stats, fallbackNames = null) {
  if (!stats || typeof stats !== 'object') return null;

  const total = typeof stats.total_columns === 'number' ? stats.total_columns : null;

  // unresolved: list of names (extractor shape) or a count (index shape)
  const unresolvedArr = Array.isArray(stats.unresolved)
    ? stats.unresolved.filter(n => typeof n === 'string')
    : null;
  const unresolvedCount = unresolvedArr !== null
    ? unresolvedArr.length
    : typeof stats.unresolved === 'number'
      ? stats.unresolved
      : null;

  const byStrategy = stats.resolved_by && typeof stats.resolved_by === 'object'
    ? stats.resolved_by
    : stats.by_strategy && typeof stats.by_strategy === 'object'
      ? stats.by_strategy
      : null;

  // Names: the extractor lists them in `unresolved`; the index shape only
  // carries a count there, so fall back to orphan_field_samples (index
  // response field) when no name list was given.
  let names = unresolvedArr;
  if (names === null && Array.isArray(fallbackNames)) {
    names = fallbackNames.filter(n => typeof n === 'string');
  }

  // Coverage % = 1 - unresolved/total (guard division by zero).
  // Prefer the computed value; fall back to the backend's coverage_pct
  // (index shape) only when we lack the inputs to compute it ourselves.
  // M10: old/mid-flight index caches report total_columns=0 with
  // unresolved>0 while the backend pins coverage_pct=100.0 — never trust
  // that combination (it claims 100% coverage with unresolved columns).
  let coveragePct = null;
  const staleZeroTotal = total === 0 && unresolvedCount !== null && unresolvedCount > 0;
  if (total !== null && total > 0 && unresolvedCount !== null) {
    coveragePct = Math.round((1 - unresolvedCount / total) * 1000) / 10;
  } else if (!staleZeroTotal && typeof stats.coverage_pct === 'number') {
    coveragePct = stats.coverage_pct;
  }

  return { total, unresolvedCount, names, byStrategy, coveragePct };
}
