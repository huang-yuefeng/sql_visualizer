const API_BASE = '/api';
// Cache busting — read from VERSION or use timestamp
const CACHE_BUST = 'v=' + (document.querySelector('meta[name="version"]')?.content || Date.now());
function bust(url) {
  const sep = url.includes('?') ? '&' : '?';
  return url + sep + CACHE_BUST;
}


export async function analyzeSql(sqlText, scriptName = 'unnamed.sql') {
  const form = new FormData();
  form.append('sql_text', sqlText);
  form.append('script_name', scriptName);
  const res = await fetch(`${API_BASE}/analyze`, { method: 'POST', body: form });
  if (!res.ok) throw new Error((await res.json()).detail || 'Analysis failed');
  return res.json();
}

export async function listScripts() {
  const res = await fetch(`${API_BASE}/scripts`);
  return res.json();
}

export async function getScript(scriptId) {
  const res = await fetch(`${API_BASE}/scripts/${scriptId}`);
  if (!res.ok) throw new Error('Script not found');
  return res.json();
}

export async function getGraph(scriptId, withSnippets = true) {
  const url = withSnippets ? `${API_BASE}/scripts/${scriptId}/graph?snippets=true` : `${API_BASE}/scripts/${scriptId}/graph`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Graph not found');
  return res.json();
}

export async function getVariables(scriptId, search = '', type = '') {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (type) params.set('type', type);
  const res = await fetch(`${API_BASE}/scripts/${scriptId}/variables?${params}`);
  return res.json();
}

export async function getVariable(scriptId, varId) {
  const res = await fetch(`${API_BASE}/scripts/${scriptId}/variables/${varId}`);
  return res.json();
}

// ── V3 Data Flow Debugger API ───────────────────────────────────────

export async function uploadWorkspace(zipFile) {
  const form = new FormData();
  form.append('file', zipFile);
  const res = await fetch('/api/workspace', { method: 'POST', body: form });
  if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed');
  return res.json();
}

export async function deleteWorkspace(wsId) {
  const res = await fetch(`/api/workspace/${wsId}`, { method: 'DELETE' });
  return res.json();
}

export async function getWorkspaceInfo(wsId) {
  const res = await fetch(`/api/workspace/${wsId}`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Workspace not found');
  return res.json();
}

export async function scanWorkspace(wsId) {
  const res = await fetch(`/api/workspace/${wsId}/scan`, { method: 'POST' });
  return res.json();
}

export async function indexWorkspace(wsId, scripts) {
  const res = await fetch(`/api/workspace/${wsId}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scripts }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Index failed');
  return res.json();
}


export async function getWorkspaceStatus(wsId) {
  const res = await fetch(`/api/workspace/${wsId}/status`);
  return res.json();
}


export async function uploadFilterConfig(wsId, scriptTableFile, tableColFile) {
  const form = new FormData();
  if (scriptTableFile) form.append('script_table', scriptTableFile);
  if (tableColFile) form.append('table_col', tableColFile);
  const res = await fetch(`/api/workspace/${wsId}/filter-config`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Filter config failed');
  return res.json();
}

export async function autocomplete(wsId, type, query) {
  const res = await fetch(`/api/workspace/${wsId}/autocomplete?type=${type}&q=${encodeURIComponent(query)}`);
  return res.json();
}

export async function searchDataFlow(wsId, table, field) {
  const res = await fetch(`/api/workspace/${wsId}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ table, field }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Search failed');
  return res.json();
}

export async function listViews(wsId) {
  const res = await fetch(`/api/workspace/${wsId}/views`);
  return res.json();
}

export async function deleteView(wsId, viewId) {
  const res = await fetch(`/api/workspace/${wsId}/views/${viewId}`, { method: 'DELETE' });
  return res.json();
}

export async function getLevel1Graph(wsId, viewId) {
  const res = await fetch(`/api/workspace/${wsId}/views/${viewId}/level1`);
  return res.json();
}

export async function getLevel2Graph(wsId, viewId, script, filter = true) {
  const params = new URLSearchParams({ script, filter: String(filter) });
  const res = await fetch(bust(`/api/workspace/${wsId}/views/${viewId}/level2?${params}`));
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load graph');
  return res.json();
}

export async function getHighlight(wsId, script, table, field) {
  const res = await fetch(`/api/workspace/${wsId}/scripts/${encodeURIComponent(script)}/highlight?table=${encodeURIComponent(table)}&field=${encodeURIComponent(field)}`);
  return res.json();
}

// ── V3.1 SQL Export Config ─────────────────────────────────────────
export async function getExportConfig(wsId) {
  const res = await fetch(`/api/workspace/${wsId}/export-config`);
  return res.json();
}

export async function saveExportConfig(wsId, config) {
  const res = await fetch(`/api/workspace/${wsId}/export-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Save config failed');
  return res.json();
}

export async function resetExportConfig(wsId) {
  const res = await fetch(`/api/workspace/${wsId}/export-config`, { method: 'DELETE' });
  return res.json();
}

export async function getDefaultExportConfig() {
  const res = await fetch(`/api/workspace/_/export-config/default`);
  return res.json();
}

export async function addViewChild(wsId, parentViewId, childEntry) {
  const res = await fetch(`/api/workspace/${wsId}/views/${parentViewId}/children`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(childEntry),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Add child failed');
  return res.json();
}

export async function deleteViewChild(wsId, parentViewId, childId) {
  const res = await fetch(`/api/workspace/${wsId}/views/${parentViewId}/children/${childId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error((await res.json()).detail || "Delete child failed");
  return res.json();
}

