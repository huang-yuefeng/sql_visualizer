const API_BASE = '/api';
// Cache busting — read from VERSION or use timestamp
const CACHE_BUST = 'v=' + (document.querySelector('meta[name="version"]')?.content || Date.now());
function bust(url) {
  const sep = url.includes('?') ? '&' : '?';
  return url + sep + CACHE_BUST;
}

// ── E-M1 (#276): shared 401 interceptor ──────────────────────────────
// A mid-session expiry (or a session dropped by the server) surfaces as
// HTTP 401 on any GATED call. AppShell registers ONE handler on mount;
// the interceptor fires it at most once per 401 batch — the session is
// already gone, so a dozen concurrent 401s must not flash a dozen banners
// or re-renders. Login and the PUBLIC analysis endpoints (/analyze,
// /scripts, /scripts/{id}/graph) bypass the interceptor: a 401 there is
// not a session-expiry signal. The handler is expected to drop the session
// (set the shell's me=null) — NOT to redirect-reload the page.
//
// Only 401 fires the handler. The backend distinguishes 401 (unauthenticated
// — the login_gate middleware returns it when the session cookie is missing/
// invalid) from 403 (authenticated-but-forbidden — the creator-only #272
// checks return it when a non-creator mutates a workspace). A 403 means the
// session is still VALID, so it must NOT drop the session; the caller
// surfaces the 403 detail to the user instead.
let sessionExpiredHandler = null;
let sessionExpiredNotified = false;

/** Register the session-expired callback (AppShell mount). Returns an unsubscribe. */
export function onSessionExpired(cb) {
  sessionExpiredHandler = cb;
  sessionExpiredNotified = false;
  return () => { if (sessionExpiredHandler === cb) sessionExpiredHandler = null; };
}

/** Reset the once-per-batch flag after a successful login/re-auth. */
export function resetSessionExpired() {
  sessionExpiredNotified = false;
}

/**
 * fetch wrapper for GATED endpoints — fires the session-expired handler on 401.
 *
 * Deliberately narrow: `=== 401` only. A 403 (authenticated but forbidden —
 * e.g. the creator-only #272 checks, non-creator → 403) is NOT session expiry
 * and must not fire the handler; the caller surfaces that 403 detail directly.
 */
async function gatedFetch(input, init) {
  const res = await fetch(input, init);
  if (res.status === 401 && sessionExpiredHandler && !sessionExpiredNotified) {
    sessionExpiredNotified = true;
    try { sessionExpiredHandler(); } catch { /* handler must never break the call */ }
  }
  return res;
}

// L12: read the error detail from a non-OK response without throwing on
// non-JSON bodies (e.g. proxy 500 HTML) — fall back to the HTTP status.
async function errorDetail(res) {
  try {
    const body = await res.json();
    if (body && typeof body === 'object') {
      if (typeof body.detail === 'string') return body.detail;
      if (typeof body.message === 'string') return body.message;
    }
  } catch { /* non-JSON body */ }
  return `HTTP ${res.status}`;
}


export async function analyzeSql(sqlText, scriptName = 'unnamed.sql') {
  const form = new FormData();
  form.append('sql_text', sqlText);
  form.append('script_name', scriptName);
  const res = await fetch(`${API_BASE}/analyze`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function listScripts() {
  const res = await fetch(`${API_BASE}/scripts`);
  return res.json();
}

export async function getGraph(scriptId, withSnippets = true) {
  const url = withSnippets ? `${API_BASE}/scripts/${scriptId}/graph?snippets=true` : `${API_BASE}/scripts/${scriptId}/graph`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Graph not found');
  return res.json();
}

// ── V3 Data Flow Debugger API ───────────────────────────────────────

export async function uploadWorkspace(zipFile) {
  const form = new FormData();
  form.append('file', zipFile);
  const res = await gatedFetch('/api/workspace', { method: 'POST', body: form });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// R31/A-M1: remove-from-my-history — role-dependent (creator = physical
// delete, participant = link removal). Renamed from the legacy
// deleteWorkspace (the old DELETE /api/workspace/{id} route is gone).
export async function removeFromMyHistory(wsId) {
  const res = await gatedFetch(`/api/me/workspaces/${wsId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// Alias kept for callers that still use the old name (physical delete for
// the creator, link removal otherwise — same endpoint).
export const deleteWorkspace = removeFromMyHistory;

// ── R31 auth / session ─────────────────────────────────────────────
export async function login(username, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  // A new session is established — a future expiry must notify again.
  resetSessionExpired();
  return res.json();
}

export async function logout() {
  await gatedFetch('/api/auth/logout', { method: 'POST' });
}

export async function getMe() {
  const res = await fetch('/api/auth/me');
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// ── R31 my workspaces ──────────────────────────────────────────────
export async function getMyWorkspaces() {
  const res = await gatedFetch('/api/workspaces');
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function resumeWorkspace(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/resume`);
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function closeWorkspace(wsId) {
  await gatedFetch(`/api/workspace/${wsId}/close`, { method: 'POST' });
}

export async function getWorkspaceActivity(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/activity`);
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function saveLayout(wsId, level, script, nodePositions, stateVersion) {
  const res = await gatedFetch(`/api/workspace/${wsId}/layout`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level, script: script || null, node_positions: nodePositions, state_version: stateVersion }),
  });
  return res; // callers inspect status (200 vs 409-with-fresh-state)
}

export async function indexWorkspace(wsId, scripts) {
  const res = await gatedFetch(`/api/workspace/${wsId}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scripts }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// R31 open-existing: the file tree for a workspace already on disk (the
// create path returns a tree inline; resume re-scans).
export async function scanWorkspace(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/scan`, { method: 'POST' });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// ── G3 (2026-08-29): read-only twins of the creator-only scan/index pair ──
// A participant opening a shared workspace must NOT trigger a scan or an
// index (both rewrite shared workspace state — the #272/#380 creator-only
// rule returns 403 to them). G3 serves the already-built tree/index over GET:
//
//   getWorkspaceTree  — GET /workspace/{id}/tree. Returns NULL on any non-OK
//     (404 endpoint-not-there-yet, 409 the workspace has no tree yet, 403…):
//     the caller decides what a missing tree means for ITS role and falls
//     back, so the client stays silent here.
//   getWorkspaceIndex — GET /workspace/{id}/index. Throws on non-OK with the
//     server's detail — an index that cannot be read is a real failure for a
//     participant (there is no second way to get it) and must surface.
export async function getWorkspaceTree(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/tree`);
  if (!res.ok) return null;
  return res.json();
}

export async function getWorkspaceIndex(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/index`);
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}


export async function getWorkspaceStatus(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/status`);
  return res.json();
}


export async function uploadFilterConfig(wsId, scriptTableFile, tableColFile) {
  const form = new FormData();
  if (scriptTableFile) form.append('script_table', scriptTableFile);
  if (tableColFile) form.append('table_col', tableColFile);
  const res = await gatedFetch(`/api/workspace/${wsId}/filter-config`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// K4 ruling 4 (2026-08-28): one direction, downstream. The router coerces
// every legacy value to downstream at the boundary, so the client default
// matches it — an omitted argument must not re-introduce the upstream
// contract the API no longer honors.
export async function searchDataFlow(wsId, table, field, direction = 'downstream') {
  const res = await gatedFetch(`/api/workspace/${wsId}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ table, field, direction }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function listViews(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/views`);
  return res.json();
}

export async function deleteView(wsId, viewId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/views/${viewId}`, { method: 'DELETE' });
  return res.json();
}

export async function getLevel2Graph(wsId, viewId, script, filter = true, direction = 'upstream') {
  const params = new URLSearchParams({ script, filter: String(filter), direction });
  const res = await gatedFetch(bust(`/api/workspace/${wsId}/views/${viewId}/level2?${params}`));
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// ── V3.1 SQL Export Config ─────────────────────────────────────────
export async function getExportConfig(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/export-config`);
  return res.json();
}

export async function saveExportConfig(wsId, config) {
  const res = await gatedFetch(`/api/workspace/${wsId}/export-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function resetExportConfig(wsId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/export-config`, { method: 'DELETE' });
  return res.json();
}

export async function addViewChild(wsId, parentViewId, childEntry) {
  const res = await gatedFetch(`/api/workspace/${wsId}/views/${parentViewId}/children`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(childEntry),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function deleteViewChild(wsId, parentViewId, childId) {
  const res = await gatedFetch(`/api/workspace/${wsId}/views/${parentViewId}/children/${childId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

