// Export current view as CSV — single or multi script

function escapeCSV(val) {
  if (val == null) return '';
  const s = String(val).replace(/"/g, '""');
  return /[",\n\r]/.test(s) ? `"${s}"` : s;
}

// Build upstream/downstream node lists from edges
function buildFlowInfo(nodeId, edges, nodeMap) {
  const upstream = [], downstream = [];
  for (const e of edges) {
    if (e.data.target === nodeId) {
      const src = nodeMap[e.data.source];
      if (src) upstream.push(`${src.label}(${src.type||src.variable_type||''})`);
    }
    if (e.data.source === nodeId) {
      const tgt = nodeMap[e.data.target];
      if (tgt) downstream.push(`${tgt.label}(${tgt.type||tgt.variable_type||''})`);
    }
  }
  return [upstream.join('; '), downstream.join('; ')];
}

// Export multi-script view
function exportMultiCSV(multiView) {
  const rows = [['script_name','input_tables','output_tables','variables','edges','data_lineage_tables']];
  for (const s of (multiView?.scripts||[])) {
    const lineage = (multiView?.meta_edges||[])
      .filter(e => e.data.edge_type==='data_lineage' && (e.data.source===s.script_id||e.data.target===s.script_id))
      .map(e => e.data.label).join('; ');
    rows.push([
      s.script_name,
      (s.input_tables||[]).join('; '),
      (s.output_tables||[]).join('; '),
      s.total_variables,
      s.total_dependencies,
      lineage,
    ]);
  }
  return rows.map(r => r.map(escapeCSV).join(',')).join('\n');
}

// Export single-script view
function exportSingleCSV(graphData) {
  const nodes = graphData?.nodes||[];
  const edges = graphData?.edges||[];
  const nodeMap = {};
  for (const n of nodes) nodeMap[n.data.id] = n.data;

  const rows = [['variable_name','variable_type','table_name','sql_expression','upstream_nodes','downstream_nodes','is_output','defined_in']];
  for (const n of nodes) {
    const d = n.data;
    const [up, down] = buildFlowInfo(d.id, edges, nodeMap);
    const tblName = d.label?.includes('.') ? d.label.split('.')[0] : (d.source_tables||[])[0] || '';
    rows.push([
      d.label||'',
      d.variable_type||'',
      tblName,
      (d.sql_expression||'').replace(/\n/g,' ').substring(0,200),
      up,
      down,
      d.is_output?'Yes':'No',
      d.defined_in||'',
    ]);
  }
  return rows.map(r => r.map(escapeCSV).join(',')).join('\n');
}

function downloadCSV(content, filename) {
  const blob = new Blob(['﻿'+content], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

export function exportCurrentView({multiView, gd, sel}) {
  if (multiView) {
    const csv = exportMultiCSV(multiView);
    downloadCSV(csv, `multi_scripts_${new Date().toISOString().slice(0,10)}.csv`);
  } else if (sel && gd) {
    const csv = exportSingleCSV(gd);
    downloadCSV(csv, `${sel.script_name||'script'}_${new Date().toISOString().slice(0,10)}.csv`);
  }
}
