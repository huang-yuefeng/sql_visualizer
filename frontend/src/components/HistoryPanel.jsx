import React, { useEffect, useState, useCallback } from 'react';
import * as api from '../api/client';

/**
 * R31 workspace history panel — the shared activity log
 * ({username, ip, ts, action, detail} NDJSON → O_APPEND, design §5.4).
 * Readable by any opener; the "who modified this" answer.
 */
export default function HistoryPanel({ wsId, onClose }) {
  const [records, setRecords] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!wsId) return;
    setLoading(true); setError(null);
    try {
      const body = await api.getWorkspaceActivity(wsId);
      setRecords((body.activity || []).slice().reverse()); // newest first
    } catch (e) {
      setError(e.message || 'Failed to load activity');
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  useEffect(() => { load(); }, [load]);

  const ACTION_LABEL = {
    visit_start: 'Visit started',
    visit_end: 'Visit ended',
    search: 'Search',
    l2_opened: 'L2 opened',
    layout_saved: 'Layout saved',
    workspace_created: 'Workspace created',
    'removed-from-own-list': 'Removed from list',
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}
        style={{ width: 680, maxWidth: '94vw', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 16px', borderBottom: '1px solid var(--border)',
        }}>
          <h3 style={{ margin: 0, fontSize: 14, color: 'var(--ink-900)' }}>
            Workspace history — {String(wsId).slice(0, 8)}…
          </h3>
          <button onClick={onClose} title="Close"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: 'var(--ink-600)' }}>
            ✕
          </button>
        </div>

        <div style={{ padding: 12, overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{
              padding: '8px 12px', borderRadius: 6, background: 'var(--danger-soft)',
              color: 'var(--danger)', fontSize: 12, marginBottom: 8,
            }}>
              {error}
            </div>
          )}
          {!error && loading && (
            <div style={{ color: 'var(--ink-400)', fontSize: 12, padding: 8 }}>Loading…</div>
          )}
          {!error && !loading && records.length === 0 && (
            <div style={{ color: 'var(--ink-400)', fontSize: 12, padding: 8 }}>
              No activity recorded yet.
            </div>
          )}
          {records.map((r, i) => (
            <div key={i} style={{
              padding: '7px 8px', borderLeft: '3px solid var(--border-strong)',
              marginBottom: 6, background: 'var(--bg-surface)', borderRadius: 4,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--ink-600)' }}>
                  <b>{r.username || '—'}</b>
                  {' · '}{ACTION_LABEL[r.action] || r.action}
                </span>
                <span style={{ fontSize: 10, color: 'var(--ink-400)', whiteSpace: 'nowrap' }}>
                  {r.ts ? String(r.ts).slice(0, 16) : ''}{r.ip ? ` · ${r.ip}` : ''}
                </span>
              </div>
              {r.detail && (
                <div style={{ fontSize: 11, color: 'var(--ink-600)', marginTop: 2 }}>
                  {r.detail}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
