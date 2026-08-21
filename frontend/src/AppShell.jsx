import React, { useState, useRef, useEffect, useCallback } from 'react';
import App from './App';
import DataFlowApp from './DataFlowApp';
import LoginPage from './components/LoginPage';
import MyWorkspaces from './components/MyWorkspaces';
import NotificationBell from './components/NotificationBell';
import HistoryPanel from './components/HistoryPanel';
import * as api from './api/client';

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-900)', background: 'var(--bg-app)', minHeight: '100vh' }}>
          <h2>Something went wrong</h2>
          <p style={{ color: 'var(--danger)' }}>{this.state.error?.message || 'Unknown error'}</p>
          <button onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}
            style={{ padding: '8px 20px', marginTop: 16, cursor: 'pointer', background: 'var(--success)', border: 'none', borderRadius: 4, color: 'var(--on-success)' }}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// Persist children so React never unmounts them across tab switches (the
// debugger keeps its state when the user glances at SQL Analysis and back).
function PersistentPanel({ show, children }) {
  const [hasMounted, setHasMounted] = useState(show);
  useEffect(() => { if (show) setHasMounted(true); }, [show]);

  if (!hasMounted) return null;

  return (
    <div style={{ display: show ? 'block' : 'none' }}>
      {children}
    </div>
  );
}

/**
 * R31 session-aware shell — the front door before every page.
 *
 * - On mount: GET /api/auth/me. 401 → LoginPage; 200 → the app.
 * - After login the "My workspaces" dashboard is the landing page; opening
 *   a workspace mounts DataFlowApp behind the gate.
 * - Top bar: mode tabs (kept), username chip, notification bell, workspace
 *   History + Close controls, theme toggle, logout.
 * - `?ws={id}` opens a shared workspace link (design §3) once logged in.
 */
export default function AppShell() {
  const [me, setMe] = useState(null);          // null = checking / logged out; {username} = in
  const [checked, setChecked] = useState(false);
  const [mode, setMode] = useState('dataflow');
  // J12-14 (2026-08-11): DEFAULT mode is LIGHT (HSBC official — white
  // surfaces, near-black text, red accents); dark/black mode stays
  // available via the toggle. Stored choice wins; first visit = light.
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');
  const [activeWsId, setActiveWsId] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  // ── Session check (gate) ───────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const m = await api.getMe();
        setMe(m && m.username ? { username: m.username } : null);
      } catch {
        setMe(null);
      }
      setChecked(true);
    })();
  }, []);

  // ── Shared-workspace link `?ws={id}` ───────────────────────────────
  // Any logged-in user who knows the id can open it (design §3 / A-H4).
  // Captured at mount so it is applied the moment login completes.
  useEffect(() => {
    try {
      const ws = new URLSearchParams(window.location.search).get('ws');
      if (ws) setActiveWsId(ws);
    } catch { /* ignore malformed urls */ }
  }, []);

  const handleLogin = useCallback((username) => setMe({ username }), []);

  const handleLogout = useCallback(async () => {
    // DataFlowApp's unmount cleanup flushes the final layout save + ends the
    // visit (closeWorkspace). Order: clear the gate first so the app unmounts.
    setActiveWsId(null);
    try { await api.logout(); } catch { /* session may already be gone */ }
    setMe(null);
  }, []);

  const openWorkspace = useCallback((wsId) => {
    setActiveWsId(wsId);
    setHistoryOpen(false);
  }, []);

  const closeWorkspace = useCallback(() => {
    // DataFlowApp (keyed) unmounts → its cleanup flushes the pending layout
    // save and calls POST /close (final write + visit-end memo, §4 Q4).
    setActiveWsId(null);
  }, []);

  // Upload from the dashboard: create the workspace, then open it (the
  // debugger's open-existing path scans + indexes).
  const handleDashboardUpload = useCallback(async (file) => {
    const result = await api.uploadWorkspace(file);
    openWorkspace(result.workspace_id);
    return result;
  }, [openWorkspace]);

  if (!checked) {
    return (
      <ErrorBoundary>
        <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--bg-app)', color: 'var(--ink-400)', fontSize: 13 }}>
          Loading…
        </div>
      </ErrorBoundary>
    );
  }

  if (!me) {
    return <ErrorBoundary><LoginPage onLogin={handleLogin} /></ErrorBoundary>;
  }

  return (
    <ErrorBoundary>
      {/* ── Top bar: mode tabs (left) + account cluster (right) ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '2px solid var(--border)', background: 'var(--bg-app)',
      }}>
        <div className="mode-tabs" style={{ borderBottom: 'none', flex: 1 }}>
          <button className={mode === 'dataflow' ? 'active' : ''} onClick={() => setMode('dataflow')}>
            Data Flow Debugger
          </button>
          <button className={mode === 'analysis' ? 'active' : ''} onClick={() => setMode('analysis')}>
            SQL Analysis
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, paddingRight: 12 }}>
          {activeWsId && (
            <>
              <button
                onClick={() => setHistoryOpen(true)}
                title="Workspace history (activity log)"
                style={{ background: 'none', border: '1px solid var(--border-strong)', borderRadius: 6,
                  cursor: 'pointer', fontSize: 12, color: 'var(--ink-600)', padding: '4px 10px' }}>
                🕘 History
              </button>
              <button
                onClick={closeWorkspace}
                title="Close workspace (ends this visit)"
                style={{ background: 'none', border: '1px solid var(--border-strong)', borderRadius: 6,
                  cursor: 'pointer', fontSize: 12, color: 'var(--ink-600)', padding: '4px 10px' }}>
                ✕ Close
              </button>
            </>
          )}
          <NotificationBell username={me.username} />
          <span style={{
            fontSize: 12, color: 'var(--ink-600)', border: '1px solid var(--border-strong)',
            borderRadius: 12, padding: '3px 10px', background: 'var(--bg-surface)',
            maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }} title={me.username}>
            👤 {me.username}
          </span>
          <button className="theme-toggle" onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
          <button
            onClick={handleLogout}
            title="Log out (ends this session's visits)"
            style={{ background: 'none', border: '1px solid var(--border-strong)', borderRadius: 6,
              cursor: 'pointer', fontSize: 12, color: 'var(--danger)', padding: '4px 10px' }}>
            Log out
          </button>
        </div>
      </div>

      {/* ── Content behind the gate ── */}
      <PersistentPanel show={mode === 'dataflow'}>
        {activeWsId ? (
          <DataFlowApp
            key={activeWsId}
            openWorkspaceId={activeWsId}
            onCloseWorkspace={closeWorkspace}
          />
        ) : (
          <MyWorkspaces
            open
            onOpen={openWorkspace}
            onUpload={handleDashboardUpload}
          />
        )}
      </PersistentPanel>
      <PersistentPanel show={mode === 'analysis'}>
        <App />
      </PersistentPanel>

      {/* ── Workspace history modal ── */}
      {historyOpen && activeWsId && (
        <HistoryPanel wsId={activeWsId} onClose={() => setHistoryOpen(false)} />
      )}
    </ErrorBoundary>
  );
}
