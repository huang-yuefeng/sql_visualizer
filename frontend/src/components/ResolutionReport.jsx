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
export default function ResolutionReport({ stats, orphanFieldSamples }) {
  const [expanded, setExpanded] = useState(false);
  const s = summarizeResolutionStats(stats, orphanFieldSamples);
  if (!s) return null;

  const pct = s.coveragePct !== null ? `${s.coveragePct.toFixed(1)}%` : '—';
  const names = s.names && s.names.length > 0 ? s.names : null;

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
          {s.byStrategy && (
            <div className="rr-strategies">
              {STRATEGY_ORDER.map(k => (
                <span key={k} className="rr-strategy">
                  {strategyLabel(k)}: {typeof s.byStrategy[k] === 'number' ? s.byStrategy[k] : '—'}
                </span>
              ))}
            </div>
          )}
          {names ? (
            <div className="rr-unresolved">
              <div className="rr-unresolved-head">
                Unresolved columns ({names.length}){names.length > MAX_NAMES ? ` — showing first ${MAX_NAMES}` : ''}
              </div>
              <div className="rr-unresolved-list">
                {names.slice(0, MAX_NAMES).map(n => (
                  <span key={n} className="rr-unresolved-name">{n}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="rr-clean">No unresolved columns</div>
          )}
        </div>
      )}
    </div>
  );
}
