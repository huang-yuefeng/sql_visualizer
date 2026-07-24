import { useState, useEffect, useRef } from 'react';
import { useResizable } from '../utils/useResizable';

const STAGE_COLORS = {
  parse:   { bg: '#95A5A6', fg: '#fff', label: 'parse' },
  extract: { bg: '#3498DB', fg: '#fff', label: 'extract' },
  deps:    { bg: '#8E44AD', fg: '#fff', label: 'deps' },
  graph:   { bg: '#1ABC9C', fg: '#fff', label: 'graph' },
  done:    { bg: '#27AE60', fg: '#fff', label: 'done' },
  profile: { bg: '#1ABC9C', fg: '#fff', label: 'profile' },
  error:   { bg: '#E74C3C', fg: '#fff', label: 'error' },
  info:    { bg: '#7F8C8D', fg: '#fff', label: 'info' },
};

const MAX_LOG_LINES = 500;

const stageBadge = (stage) => {
  const s = STAGE_COLORS[stage] || STAGE_COLORS.info;
  return { backgroundColor: s.bg, color: s.fg, label: s.label };
};

export default function LogPanel({ wsId, visible, onClose }) {
  const [expanded, setExpanded] = useState(false);
  const [logHeight, setLogHeight] = useState(220);
  const logResize = useResizable({
    direction: 'vertical', value: logHeight, defaultValue: 220, min: 44, max: 800, invert: true,
    onResize: (v) => setLogHeight(v),
  });
  const [logs, setLogs] = useState([]);
  const bottomRef = useRef(null);
  const eventSourceRef = useRef(null);

  useEffect(() => {
    if (!wsId) return;

    const base = window.location.origin;
    const url = `${base}/api/workspace/${wsId}/logs`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        setLogs(prev => {
          const next = [...prev, entry];
          return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
        });
      } catch (_) { /* ignore parse errors */ }
    };

    es.onerror = () => {
      // EventSource auto-reconnects; no action needed
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [wsId]);

  // Auto-scroll to bottom when expanded
  useEffect(() => {
    if (expanded && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, expanded]);

  const clear = () => setLogs([]);
  const copy = () => {
    const text = logs.map(l => l.msg).join('\n');
    navigator.clipboard.writeText(text).catch(() => {});
  };

  // Latest message for collapsed bar
  const lastMsg = logs.length > 0 ? logs[logs.length - 1] : null;
  const hasError = logs.some(l => l.stage === 'error');

  return (
    <div className={`log-panel ${expanded ? 'expanded' : ''}`} style={expanded ? { height: logHeight + 'px' } : undefined}>
      {/* Collapsed bar */}
      <div
        className="log-bar"
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: 'pointer' }}
      >
        {lastMsg ? (
          <>
            <span
              className="log-stage-dot"
              style={stageBadge(lastMsg.stage)}
            >
              {stageBadge(lastMsg.stage).label}
            </span>
            <span className="log-last-msg">{lastMsg.msg}</span>
          </>
        ) : (
          <span className="log-last-msg dim">Waiting for pipeline...</span>
        )}
        <span className="log-toggle">{expanded ? '▼' : '▲'}</span>
        {hasError && <span className="log-error-indicator">⚠️</span>}
        {onClose && (
          <button
            className="close-btn"
            onClick={(e) => { e.stopPropagation(); onClose(); }}
            title="Close log panel"
            style={{ marginLeft: 6 }}
          >✕</button>
        )}
      </div>

      {/* Expanded panel */}
      {expanded && (
        <>
        <div className="log-resize-handle" {...logResize.handleProps} title="Drag to resize" />
        <div className="log-list" style={{ height: (logHeight - 40) + 'px' }}>
          {logs.length === 0 && (
            <div className="log-empty">No logs yet</div>
          )}
          {logs.map((entry, i) => (
            <div key={i} className="log-line">
              <span className="log-ts">{entry.ts}</span>
              <span className="log-badge" style={stageBadge(entry.stage)}>
                {stageBadge(entry.stage).label}
              </span>
              <span className="log-msg">{entry.msg}</span>
            </div>
          ))}
          <div ref={bottomRef} />

          {/* Actions */}
          <div className="log-actions">
            <button className="btn btn-outline btn-xs" onClick={clear}>Clear</button>
            <button className="btn btn-outline btn-xs" onClick={copy}>Copy</button>
          </div>
        </div>
        </>
      )}
    </div>
  );
}
