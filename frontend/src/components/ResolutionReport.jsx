import React, { useState } from 'react';
import { summarizeResolutionStats, STRATEGY_ORDER, strategyLabel } from '../utils/resolutionReport';

const MAX_NAMES = 20;

function coverageColor(pct) {
  if (pct === null) return '#888';
  if (pct >= 90) return '#2ECC71';
  if (pct >= 70) return '#F39C12';
  return '#E74C3C';
}

/**
 * R20 — ORPHAN RESOLUTION REPORT
 * Compact collapsible block: coverage % badge, per-strategy breakdown and
 * the unresolved column names (up to 20). Renders nothing when
 * resolution_stats is absent (old cached data).
 */
export default function ResolutionReport({ stats, orphanFieldSamples, schemaCandidates }) {
  const [expanded, setExpanded] = useState(false);
  const s = summarizeResolutionStats(stats, orphanFieldSamples);
  if (!s) return null;

  const pct = s.coveragePct !== null ? `${s.coveragePct.toFixed(1)}%` : '—';
  const names = s.names && s.names.length > 0 ? s.names : null;
  // M9/L14: branch on the COUNT, not on name-list presence — the index
  // shape omits orphan_field_samples, so names may be absent with
  // unresolvedCount > 0. Header count is the real unresolvedCount; the
  // list display stays capped at MAX_NAMES.
  const unresolvedTotal = s.unresolvedCount !== null ? s.unresolvedCount : (names ? names.length : null);
  const showList = !!names && unresolvedTotal !== null && unresolvedTotal > 0;
  const showDetailsUnavailable = unresolvedTotal !== null && unresolvedTotal > 0 && !names;
  const shownNames = names ? Math.min(names.length, MAX_NAMES) : 0;
  const truncated =
    !!names && (names.length < unresolvedTotal || names.length > MAX_NAMES);

  return (
    <div className="resolution-report">
      <div className="rr-header" onClick={() => setExpanded(e => !e)} title="Orphan resolution coverage (R20)">
        <span className="rr-icon">🧩</span>
        <span className="rr-title">Orphan Resolution</span>
        <span className="rr-coverage" style={{ color: coverageColor(s.coveragePct) }}>{pct}</span>
        <span className="rr-toggle">{expanded ? '▲' : '▼'}</span>
      </div>
      {expanded && (
        <div className="rr-body">
          <div className="rr-line">
            {s.total !== null ? `${s.total} column variables` : '—'} ·{' '}
            {s.unresolvedCount !== null
              ? `${s.unresolvedCount} unresolved${s.total !== null && s.total > 0 ? ` (${pct} coverage)` : ''}`
              : 'coverage —'}
          </div>
          {schemaCandidates && typeof schemaCandidates === 'object' && (
            <div className="rr-line rr-schema-candidates">
              Schema candidates: {schemaCandidates.total ?? '—'} (unique owner: {schemaCandidates.unique_owner ?? '—'}) | r6: {schemaCandidates.r6_collision ?? '—'}
            </div>
          )}
          {s.byStrategy && (
            <div className="rr-strategies">
              {STRATEGY_ORDER.map(k => (
                <span key={k} className="rr-strategy">
                  {strategyLabel(k)}: {typeof s.byStrategy[k] === 'number' ? s.byStrategy[k] : '—'}
                </span>
              ))}
            </div>
          )}
          {showList ? (
            <div className="rr-unresolved">
              <div className="rr-unresolved-head">
                Unresolved columns ({unresolvedTotal})
                {truncated ? ` — showing first ${shownNames}` : ''}
              </div>
              <div className="rr-unresolved-list">
                {names.slice(0, MAX_NAMES).map(n => (
                  <span key={n} className="rr-unresolved-name">{n}</span>
                ))}
              </div>
            </div>
          ) : showDetailsUnavailable ? (
            <div className="rr-unavailable">{unresolvedTotal} unresolved (details unavailable)</div>
          ) : (
            <div className="rr-clean">No unresolved columns</div>
          )}
        </div>
      )}
    </div>
  );
}
