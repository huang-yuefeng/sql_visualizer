import React, { useState } from 'react';
import * as api from '../api/client';

/**
 * R31 login gate — pre-provisioned `*@hsbc.com` local accounts only.
 * No self-registration: an unknown username is rejected by the backend.
 * Password recovery is admin-mediated (A-H1) — this page never offers one.
 */
export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(username.trim(), password);
      onLogin(me.username || username.trim());
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg-app)', padding: 24,
    }}>
      <form onSubmit={submit} style={{
        width: 360, maxWidth: '100%', background: 'var(--bg-elevated)',
        border: '1px solid var(--border-strong)', borderRadius: 10, padding: 32,
        boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
      }}>
        <h1 style={{ margin: '0 0 4px', fontSize: 20, color: 'var(--ink-900)' }}>SQL Data Flow Visualizer</h1>
        <p style={{ margin: '0 0 24px', color: 'var(--ink-600)', fontSize: 13 }}>
          Sign in with your HSBC email account
        </p>
        <label style={{ display: 'block', fontSize: 12, color: 'var(--ink-600)', marginBottom: 4 }}>
          Username
        </label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="you@hsbc.com"
          autoComplete="username"
          required
          style={{
            width: '100%', boxSizing: 'border-box', padding: '10px 12px', marginBottom: 14,
            border: '1px solid var(--border-strong)', borderRadius: 6, fontSize: 14,
            color: 'var(--ink-900)', background: 'var(--bg-app)',
          }}
        />
        <label style={{ display: 'block', fontSize: 12, color: 'var(--ink-600)', marginBottom: 4 }}>
          Password
        </label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          autoComplete="current-password"
          required
          style={{
            width: '100%', boxSizing: 'border-box', padding: '10px 12px', marginBottom: 18,
            border: '1px solid var(--border-strong)', borderRadius: 6, fontSize: 14,
            color: 'var(--ink-900)', background: 'var(--bg-app)',
          }}
        />
        {error && (
          <div style={{
            marginBottom: 14, padding: '8px 12px', borderRadius: 6,
            background: 'var(--danger-soft)', color: 'var(--danger)', fontSize: 13,
          }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          style={{
            width: '100%', padding: '11px 0', border: 'none', borderRadius: 6,
            background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 15,
            fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
          }}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
