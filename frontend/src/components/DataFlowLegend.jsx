import React from 'react';

const L2_LEGEND = [
  { label: 'Table', color: '#4A90D9', shape: '■' },
  { label: 'View', color: '#5DADE2', shape: '■' },
  { label: 'Column', color: '#A8D4FF', shape: '●' },
  { label: 'CTE', color: '#5CB85C', shape: '▣' },
  { label: 'CTE Col', color: '#8FD98F', shape: '▲' },
  { label: 'Expression', color: '#F0AD4E', shape: '◆' },
  { label: 'Window', color: '#967ADC', shape: '⬢' },
  { label: 'Aggregate', color: '#37BC9B', shape: '▲' },
  { label: 'Transform', color: '#FFCE54', shape: '▰' },
  { label: 'Case', color: '#D770AD', shape: '⬠' },
  { label: 'Merge', color: '#DA4453', shape: '■' },
  { label: 'Subquery', color: '#AC92EC', shape: '◆' },
  { label: 'Virtual', color: '#2ECC71', shape: '▣' },
  { label: 'Literal', color: '#CCCCCC', shape: '●' },
];

const L1_LEGEND = [
  { label: 'Source Table', color: '#4A90D9', shape: '■' },
  { label: 'Intermediate Table', color: '#5a5a7a', shape: '■' },
  { label: 'Output Table', color: '#2ECC71', shape: '■' },
  { label: 'Script', color: '#F39C12', shape: '●' },
  { label: 'Data Flow', color: '#FFD700', shape: '→', desc: 'Script→Script data lineage' },
  { label: 'Table↔Script', color: '#5DADE2', shape: '↔' },
  { label: 'Role Edge', color: '#00FF88', shape: '→' },
];

const EDGE_LEGEND = [
  { label: 'TABLE_FLOW', color: '#2ECC71', shape: '══', desc: 'Table feeds output' },
  { label: 'ALIAS', color: '#1ABC9C', shape: '- -', desc: 'Original → alias' },
  { label: 'REF', color: '#27AE60', shape: '—', desc: 'Column reference' },
  { label: 'AGGREGATE', color: '#8E44AD', shape: '══', desc: 'SUM/COUNT/AVG' },
  { label: 'TRANSFORM', color: '#D35400', shape: '- -', desc: 'COALESCE/CAST' },
  { label: 'WINDOW', color: '#9B59B6', shape: '- ·', desc: 'ROW_NUMBER/RANK' },
  { label: 'COMPUTED', color: '#E67E22', shape: '···', desc: 'CASE WHEN' },
  { label: 'SCHEMA', color: '#3498DB', shape: '···', desc: 'Table→Column' },
  { label: 'INDIRECT', color: '#C0392B', shape: '·-·', desc: 'HAVING→SELECT' },
  { label: 'FILTER', color: '#E74C3C', shape: '—', desc: 'WHERE condition' },
  { label: 'JOIN', color: '#E91E63', shape: '- -', desc: 'JOIN key' },
  { label: 'CORRELATED', color: '#FF5722', shape: '···', desc: 'Correlated subq' },
  { label: 'DML', color: '#2980B9', shape: '═╪', desc: 'INSERT/UPDATE' },
  { label: 'SET_OP', color: '#F1C40F', shape: '-- --', desc: 'UNION/INTERSECT' },
  { label: 'SUBQUERY', color: '#16A085', shape: '···', desc: 'Subquery ref' },
  { label: 'SUBSET', color: '#7F8C8D', shape: '· ·', desc: 'Bridge' },
];

const CATEGORY_LEGEND = [
  { label: 'Copy (REF)', color: '#2ECC71', shape: '══', desc: 'Value flows unchanged' },
  { label: 'Compute (TRAN/COMP)', color: '#F39C12', shape: '- -', desc: 'Transformation/function' },
  { label: 'Aggregate (SUM/RN)', color: '#967ADC', shape: '══', desc: 'SUM/COUNT/ROW_NUMBER' },
  { label: 'Filter (WHERE/JOIN)', color: '#E74C3C', shape: '···', desc: 'Row filtering/conditions' },
  { label: 'Combine (UNION/SQ)', color: '#E67E22', shape: '- -', desc: 'Set operations/subqueries' },
  { label: 'Write (DML)', color: '#3498DB', shape: '══', desc: 'INSERT/UPDATE/DELETE/MERGE' },
  { label: 'Structure (SCHEMA)', color: '#95A5A6', shape: '···', desc: 'Ownership/alias/bridge' },
];

export default function DataFlowLegend({ level }) {
  let items, title;
  if (level === 'L1') {
    items = L1_LEGEND;
  } else if (level === 'L2') {
    items = L2_LEGEND;
  } else if (level === 'categories') {
    items = CATEGORY_LEGEND;
    title = '7 Edge Categories';
  } else {
    items = L2_LEGEND;
  }

  return (
    <div className="dataflow-legend">
      {title && <span className="legend-title">{title}</span>}
      {items.map(item => (
        <span key={item.label} className="legend-item" title={(item.desc || item.label)}>
          <span style={{ color: item.color, fontWeight: 'bold', fontSize: '0.8em' }}>
            {item.shape}
          </span>
          <span>{item.label}</span>
        </span>
      ))}
    </div>
  );
}
