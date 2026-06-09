const API_BASE = '/api';

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

export async function getGraph(scriptId) {
  const res = await fetch(`${API_BASE}/scripts/${scriptId}/graph`);
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
