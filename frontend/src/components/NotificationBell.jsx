import React, { useEffect, useState, useRef, useCallback } from 'react';
import * as api from '../api/client';

/**
 * R31 notification bell — unread badge + inbox dropdown (pull, not push:
 * the user sees notifications on next login/open per design §5.4).
 *
 * - unread badge = count of notifications with read === false
 * - clicking a notification marks it read and shows its body
 * - inbox refreshes on open; the badge refreshes on close + a 30s poll so a
 *   creator alert landed while the user is active still surfaces.
 */
export default function NotificationBell({ username }) {
  const [notifs, setNotifs] = useState([]);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const rootRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const body = await api.getNotifications();
      setNotifs(body.notifications || []);
    } catch { /* non-critical — bell stays empty */ }
  }, []);

  useEffect(() => { if (username) refresh(); }, [username, refresh]);

  // 30s poll while the app is open — creator alerts land without a re-login.
  useEffect(() => {
    const t = setInterval(() => { if (username) refresh(); }, 30000);
    return () => clearInterval(t);
  }, [username, refresh]);

  // Click-outside close
  useEffect(() => {
    if (!open) return;
    const h = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);

  const unread = notifs.filter(n => !n.read).length;

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) { await refresh(); setExpanded(null); }
  };

  const markRead = async (n) => {
    setExpanded(expanded === n.id ? null : n.id);
    if (!n.read) {
      try { await api.markNotificationRead(n.id); } catch { /* non-critical */ }
      setNotifs(prev => prev.map(x => x.id === n.id ? { ...x, read: true } : x));
    }
  };

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button onClick={toggle} title="Notifications"
        style={{
          background: 'none', border: 'none', cursor: 'pointer', fontSize: 18,
          position: 'relative', padding: '4px 6px', lineHeight: 1,
        }}>
        🔔
        {unread > 0 && (
          <span style={{
            position: 'absolute', top: -2, right: -4, background: 'var(--accent)',
            color: 'var(--on-accent)', borderRadius: 10, fontSize: 10,
            padding: '1px 5px', fontWeight: 700, minWidth: 16, textAlign: 'center',
          }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div style={{
          position: 'absolute', right: 0, top: 30, width: 340, maxHeight: 420,
          overflowY: 'auto', background: 'var(--bg-elevated)',
          border: '1px solid var(--border-strong)', borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.12)', zIndex: 1000, padding: 8,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink-900)', padding: '4px 6px 8px' }}>
            Notifications
          </div>
          {notifs.length === 0 && (
            <div style={{ color: 'var(--ink-400)', fontSize: 12, padding: '8px 6px' }}>
              No notifications yet.
            </div>
          )}
          {notifs.map(n => (
            <div key={n.id} style={{
              padding: '7px 8px', borderRadius: 6, marginBottom: 4, cursor: 'pointer',
              background: n.read ? 'transparent' : 'var(--accent-soft)',
              borderLeft: n.read ? '3px solid transparent' : '3px solid var(--accent)',
            }} onClick={() => markRead(n)}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
              }}>
                <span style={{
                  fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5,
                  color: n.kind === 'alert' ? 'var(--warning)' : 'var(--ink-600)',
                }}>
                  {n.kind === 'alert' ? '⚑ alert' : 'memo'}
                </span>
                <span style={{ fontSize: 10, color: 'var(--ink-400)' }}>
                  {n.created_at ? String(n.created_at).slice(0, 16) : ''}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--ink-900)', fontWeight: n.read ? 400 : 600, marginTop: 2 }}>
                {n.title}
              </div>
              {expanded === n.id && n.body && (
                <div style={{
                  fontSize: 11, color: 'var(--ink-600)', marginTop: 4, whiteSpace: 'pre-wrap',
                  borderTop: '1px solid var(--border)', paddingTop: 4,
                }}>
                  {n.body}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
