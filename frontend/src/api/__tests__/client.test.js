import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as api from '../client';

/**
 * E-M1 (#276) — shared 401 interceptor.
 *
 * A mid-session expiry surfaces as HTTP 401 on any GATED call. The
 * interceptor must fire the registered handler at most once per 401 batch,
 * and must NOT fire for the login endpoint or the PUBLIC analysis endpoints
 * (/analyze, /scripts, /scripts/{id}/graph) — a 401 there is not a
 * session-expiry signal.
 */
describe('api 401 interceptor (E-M1/#276)', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock;
    api.resetSessionExpired();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function mock401() {
    fetchMock.mockResolvedValue(new Response('', { status: 401 }));
  }

  it('fires the handler once when a gated call returns 401', async () => {
    mock401();
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it('fires only ONCE for a batch of concurrent 401s', async () => {
    mock401();
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await Promise.allSettled([
      api.getMyWorkspaces(),
      api.resumeWorkspace('w1'),
      api.getWorkspaceStatus('w1'),
      api.getWorkspaceActivity('w1'),
    ]);
    expect(cb).toHaveBeenCalledTimes(1);
  });

  it('does NOT fire for a 401 from the public analyze endpoint', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 401 }));
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.analyzeSql('select 1')).rejects.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });

  it('does NOT fire for a 401 from login', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'bad credentials' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      })
    );
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.login('a@hsbc.com', 'x')).rejects.toThrow('bad credentials');
    expect(cb).not.toHaveBeenCalled();
  });

  it('does NOT fire on a non-401 error', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 500 }));
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });

  it('does NOT fire on a 403 (authenticated but forbidden)', async () => {
    // Creator-only checks (#272) return 403 for a non-creator session — the
    // session is still valid, so this must NOT drop the session.
    fetchMock.mockResolvedValue(new Response('', { status: 403 }));
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });

  it('unsubscribe stops the handler from firing', async () => {
    mock401();
    const cb = vi.fn();
    const unsub = api.onSessionExpired(cb);
    unsub();
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });

  it('resetSessionExpired allows a second 401 batch to notify again', async () => {
    mock401();
    const cb = vi.fn();
    api.onSessionExpired(cb);
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).toHaveBeenCalledTimes(1);

    api.resetSessionExpired();
    await expect(api.getMyWorkspaces()).rejects.toThrow();
    expect(cb).toHaveBeenCalledTimes(2);
  });
});
